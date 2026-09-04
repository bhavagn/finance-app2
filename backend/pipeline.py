"""State machine: uploaded → parsing → parsed → reconciled|needs_review → enriched.

Orchestrates ingestion → normalize → parser → reconcile → merchant → categorize → detectors → persist.
Not implemented yet — see finance-app-spec.md §6.
"""
