"""Server-side Supabase client, authenticated with the service-role key.

This client bypasses Row-Level Security. It must never be imported into frontend code or exposed to
a browser — every write made through it has to set `user_id` explicitly (see repositories.py).
"""
from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv()


class SupabaseConfigError(RuntimeError):
    """Raised when the backend-only Supabase env vars are missing."""


@lru_cache(maxsize=1)
def get_service_client() -> Client:
    """Return a cached Supabase client authenticated with the service-role key.

    Reads `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` from the environment (via `.env` in dev).
    """
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise SupabaseConfigError(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set (see .env.example)"
        )
    return create_client(url, key)
