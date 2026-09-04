# Finance App — Build Spec (Claude Code handoff)

A personal-finance app that parses Indian bank/credit-card PDF statements and turns them into
clean, reconciled, categorised transactions for financial analysis. Context: India (UPI/NEFT/IMPS,
INR, DPDP Act). This document is the source of truth for building the backend + frontend.

Companion docs (in the Claude project "Financial analysis"):
- `supabase-schema.sql` — full DDL (already applied to Supabase project `finance-app2`)
- `supabase-seed.sql` — taxonomy + merchant dictionary seed (already applied)
- `parser-categoriser-feature-spec.md` — full feature spec

---

## 1. Architecture

Three planes — keep logic OUT of the database:

- **Supabase (data plane):** Auth, Postgres (20 tables + RLS), Storage (raw PDFs). Only data-integrity
  logic lives here (RLS, constraints, fingerprint generated column, signup trigger).
- **Python backend (logic plane) — the brain:** parsing, reconciliation, categorisation, detectors.
  Writes with the **service-role key** (bypasses RLS → must set `user_id` on every row).
- **Frontend (React/Next.js):** Supabase Auth, reads transactions directly from Supabase (RLS-safe),
  uploads PDFs to Storage, calls backend to trigger processing.

Rules have two halves: **rules-as-data** live in Postgres tables; the **rule engine** is Python code.

Recommended stack: Next.js frontend + Python/FastAPI backend + worker, all on ONE platform
(Railway or Render — NOT Vercel for the backend; the parser is heavy) · Supabase for data/auth/storage.
Parsing runs async via a job/worker so a 54-page PDF never blocks a request. See §9 for deployment.

---

## 2. Supabase project

- Project name: `finance-app2` (region ap-northeast-1, Postgres 17)
- Schema + seed + signup trigger + layout_signature columns are ALREADY applied and RLS-clean.
- Get the project URL + keys from the Supabase dashboard; put them in backend `.env`
  (`SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`) and frontend env (`NEXT_PUBLIC_SUPABASE_URL`,
  `NEXT_PUBLIC_SUPABASE_ANON_KEY`). NEVER expose the service-role key client-side.
- Create a **private Storage bucket** for raw PDFs (per-user paths, signed URLs).

---

## 3. Data model (key points — full DDL in supabase-schema.sql)

Two-layer core:
- `transactions` = **immutable parsed layer**. Never edited after insert.
- `transaction_enrichment` = **mutable overlay** (category, merchant, payment_method, flags), linked by
  **`fingerprint`, NOT `transactions.id`** — so re-parsing never orphans a user's categories.

Fingerprint = `md5(account_id | days-since-2000 | signed_amount | bank_ref-or-position)`, a generated
column with `unique(account_id, fingerprint)`. This makes two bugs structurally impossible:
- 5 identical SIPs with different bank refs → 5 fingerprints → all kept.
- Same statement re-uploaded → same fingerprints → deduped.

Other tables: `profiles`, `issuers`, `bank_templates` (parser templates + `layout_signature`, versioned),
`accounts` (`product_name + last4` per user), `statements` (printed totals as reconciliation ground truth
+ `layout_signature` + status), `category_taxonomy` (fixed base, each category → one `bucket`),
`merchants`/`merchant_aliases` (VPA/MCC dictionary), `transaction_splits`, `user_rules` (category + parse
scope), `global_merchant_category` (Phase 2, PII-free), `emi_loans`/`emi_instalments`, `recurring_series`,
`transfers`, `reward_points_ledger`, `audit_log`, `review_queue`.

Buckets: `spend | income | transfer | invest | emi_repayment | adjustment | fee`.
Sign convention: **amount < 0 = money out, > 0 = money in**. Money is `numeric(14,2)` — never float.

---

## 4. Locked design decisions

1. Parser keyed on `(issuer, statement_type)` — NOT per card. ICICI Amazon Pay & MMT share one parser;
   card identity is an `accounts` instance (`product_name + last4`).
2. Immutable parsed + fingerprint-keyed enrichment overlay (re-parse never destroys corrections).
3. **Reconciliation is a tri-state gate** with a ±₹1–2 tolerance band (NOT hard binary):
   `reconciled | reconciled_with_warning | unreconciled`. Only reconciled/-with-warning flow onward.
4. **payment_method is orthogonal to category** (EMI/autopay/POS are methods, not categories).
5. EMI = dual-view: purchase stored as economic spend; instalments tagged `emi_repayment`; linked by
   `loan_number`. Analysis toggles accrual (count purchase) vs cash (count instalments) — never both.
6. Cashback/refunds OFFSET spend (bucket `adjustment`); reward points tracked separately (non-money).
7. Self-learning parser templates: **LLM-inferred, fully automatic**, promoted to deterministic only
   after reconciliation passes (per-user first via `owner_user`, then `verified` global). Gated by recon.
8. Layout-signature drift detection: select template by `(issuer, statement_type, layout_signature)`;
   new signature on known issuer/type → re-learn + version bump.
9. Categorisation cascade: **user explicit rule → user learned memory → issuer hint → global (Phase 2)
   → model/LLM**. User always wins. Retroactive apply on manual change (past + future), undoable via audit_log.
10. Two independent learning loops: parser-template (gated by reconciliation) and categorisation
    (gated by user confirmation + k-anonymity). Keep separate.
11. Security at the DB layer: RLS on every table; service-role server-side only; private PDF storage;
    PII minimisation; LLM boundary (redact + zero-retention terms); DPDP cascade delete; MFA before multi-user.
    NEVER put P2P/person VPAs into global learning.

---

## 5. Real-data learnings (validated on 3 statements — build around these)

- Parsing itself is solved-enough for these banks; **reconciliation is the correctness backbone**;
  **transfer + P2P handling is where the product is won or lost** (₹15.4L "outflow" was really ₹28.7k
  discretionary spend once transfers/investments/CC-bills were separated).
- **Categorisation quality is GATED by parsing/merchant-extraction quality.** A truncated merchant string
  guarantees a wrong category. Fixing multi-line UPI merge DOUBLED correct gold detection (61→123) and
  recovered VPAs on 513/537 UPI rows. Measure parse-completeness separately; never blame the categoriser
  for a parse bug.
- **The VPA is the strongest merchant key** (e.g. `SAFEGOLD@YBL`, `INDMONEY.STOCKS@ICICI`,
  `CORPORATEAUTOPAY.CAMSPAY` = mutual-fund SIP). Build a VPA→merchant dictionary.
- **Transaction-level reconciliation catches sign/parse bugs** (caught "SUB**SCR**IPTION" being flagged
  CR because a naive `'CR' in text` matched letters inside "subscription"; use word-boundary `\bCR\b$`).
- Three reconciliation models seen: savings = per-row running balance; HDFC card = `prev − payments +
  purchases + finance = total` (was off ₹0.38 due to GST billed next cycle → tolerance mandatory);
  ICICI card = `prev + purchases + cash − payments = total` (exact).
- A **normalisation layer is required even for digital PDFs**: ` and C → ₹, strip "DUPLICATE" watermark,
  `(cid:1)` glyphs, doubled header letters (`SSTTAATTEEMMEENNTT`), date formats (`dd/mm/yy`, `June 5, 2026`).
- EMI cross-validation works: loan summary table + per-transaction `NB:06 / NBR:01` markers agree →
  detected one closed loan (6/6, ₹0) and one active (1/6, ₹12,256 left).
- Forex is multi-component: base INR + IGST(18%) + FCY markup, as separate lines to link to the parent.

---

## 6. Python backend module structure

```
backend/
├── api/            # FastAPI routes (thin): upload, rules, review
├── ingestion/      # storage download, unlock, pdf_type detect, file_hash dedup
├── normalize/      # text_clean (currency/watermark/cid/doubled), dates, amounts (signed)
├── parser/         # issuer_detect, coordinate (pdfplumber), multiline (UPI merge),
│                   #   statement_meta, signature (layout fingerprint), llm_fallback,
│                   #   template_learner (LLM-inferred → validate → save), templates/*
├── reconcile/      # row_balance, statement_eq, txn_sum, result (tolerance → tri-state)
├── merchant/       # vpa (parse + rail), resolve (alias→canonical), person_detect
├── categorize/     # engine (cascade), payment_method, issuer_hints, llm_categorizer
├── detectors/      # transfers (cross-account match), emi, recurring, refunds, forex
├── learning/       # memory, retroactive, global_agg (Phase 2)
├── db/             # supabase client (service role), repositories, status transitions
├── models/         # pydantic — the canonical transaction contract
├── pipeline.py     # state machine: uploaded→parsing→parsed→reconciled|needs_review→enriched
├── worker.py       # async job/queue consumer
└── tests/          # golden-file suite (the 3 statements as fixtures)
```

Pipeline: `ingestion → normalize → parser → reconcile → merchant → categorize → detectors → persist`.
Each module independently testable (run reconcile on a parsed fixture without a PDF).

What does NOT go in Python: RLS/constraints/fingerprint (Postgres); most analysis/reporting (SQL views
read by frontend); auth (Supabase); simple UI reads (frontend → Supabase direct). Python owns exactly
one job: **raw PDF → correct, enriched rows.**

---

## 7. Phased plan

- **Phase 1 (one PDF → correct rows):** ingestion, normalize, parser (3 templates: hdfc_savings,
  hdfc_cc, icici_cc), reconcile, merchant, categorize (rule + issuer-hints, no LLM), db, pipeline,
  worker, golden-file tests. Storage bucket + upload flow.
- **Phase 2 (make it smart):** detectors (transfers/EMI/recurring/forex/refunds), learning/memory +
  retroactive, LLM fallback (parse + categorise), template_learner + drift.
- **Phase 3 (scale/community):** global cross-user learning, teach-the-parser UI, analysis/dashboards,
  MFA + full security hardening for multi-user.

---

## 8. First tasks for Claude Code

1. Scaffold the repo (folders above), `pyproject`/`requirements` (fastapi, uvicorn, pdfplumber,
   supabase, pydantic), `.env.example`, `.gitignore`.
2. `models/` — the pydantic canonical transaction (mirrors the `transactions` table).
3. `db/client.py` — Supabase service-role client + repositories with status transitions.
4. Port the validated parser: `parser/templates/hdfc_savings.py` first (coordinate extraction +
   multi-line UPI merge), then `hdfc_cc.py`, `icici_cc.py`.
5. `reconcile/` — implement the three formulas + tolerance tri-state.
6. `tests/` — drop the 3 statements in as golden fixtures; assert reconciliation passes and counts match
   (HDFC savings = 549 txns, balances to closing ₹10,079.19).
7. Wire `pipeline.py` end to end; then the Storage upload + `worker.py`.

Validated reference numbers for tests:
- HDFC savings ••9069: 549 txns, opening ₹59,828.38, closing ₹10,079.19, reconciles exact.
- HDFC Millennia ••9670: total due ₹52,368.80, recon diff ₹0.38 (within tolerance), 2 EMI loans.
- ICICI Amazon Pay ••2004: total due ₹6,663.26, reconciles exact both statement- and txn-level.

---

## 9. Deployment

**Recommendation: single platform for everything — Railway (best DX) or Render.**
This is an authenticated app (no anonymous/SEO traffic), users are mostly in India, and Supabase is
in Asia — so a global edge CDN (Vercel's main advantage) adds little here. Prefer operational simplicity
and co-location over frontend edge polish.

- **Host:** Railway or Render — run three services in one project/region:
  1. **Frontend** — Next.js (Node web service)
  2. **Backend API** — FastAPI (web service)
  3. **Worker** — the parsing/enrichment jobs (background worker; NOT the web process)
- **Region:** Singapore or Tokyo (close to Supabase `finance-app2` in ap-northeast-1). Backend↔DB
  latency matters most because parsing writes many rows; put the backend near the DB.
- **Private networking:** let the frontend call the backend, and the backend reach the DB, over the
  platform's private network where possible; the backend need not be publicly exposed beyond its API.
- **Env-var split (critical):**
  - Backend/worker only: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` (bypasses RLS — server-side ONLY),
    any LLM API keys.
  - Frontend only: `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`.
  - Never put the service-role key or LLM keys in the frontend.
- **Cost:** ~$0 during dev (free tiers sleep — fine for building); ~$5–15/mo once the backend/worker
  are always-on.

**Split alternative (only if later needed):** Vercel (frontend) + Render/Railway (backend + worker) —
adopt only when you add a public marketing site or specifically want Vercel's per-PR preview deploys.
Requires CORS setup between the Vercel frontend origin and the backend API.

**Worker note:** you may start with FastAPI background tasks to move fast, but graduate to a dedicated
worker/queue before real users — a 54-page parse must not share the web process.
