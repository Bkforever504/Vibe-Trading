# Social evidence ledger

This ledger converts a social-media setup into an auditable research record. It does not copy a trader, infer a fill, or use a profit screenshot as a strategy result.

Add one JSON object per line to `data/social_evidence_claims.jsonl`. A usable record needs a symbol and a timezone-aware `claimed_entry_at` or `observed_at`. If a screenshot displays only a share/post time, use `observed_at` and set `timestamp_basis` to `share_time_not_entry`.

Required fields:

- `claim_id`: stable unique label
- `symbol`: underlying, such as `SPY`, `TSLA`, or `MU`
- `direction`: `bullish`/`bearish` (or call/put)
- `claimed_entry_at` or `observed_at`: ISO 8601 timestamp with timezone
- `timestamp_basis`: e.g. `explicit_entry_time`, `share_time_not_entry`, or `post_time_not_entry`
- `source` and `evidence_ref`: provenance only; no credentialed scraping is required

Run `python scripts/social_evidence_coverage_audit.py --print`. The report links each claim only to the last radar snapshot available before the timestamp. It reports discovery, selection, evaluation, confirmation, and early heads-up visibility; it never asserts a fill, profit, or validity of the source's performance claim.
