# Existing promoted signal statistical re-evaluation

Generated: 2026-09-07T23:46:47.796772Z

Advisory only. No registry promotion flag or execution setting was changed.

| Signal | Family | n | trials | Sharpe | DSR | PSR | PBO | Status | Reason |
|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| flip_bot | momentum | 14 | 26 | None | None | None | None | needs_review | insufficient_outcomes:14/30 |
| iwm_options_bot | momentum | 1 | 26 | None | None | None | None | needs_review | insufficient_outcomes:1/30 |

## Required human review

- Confirm every family assignment in `config/signal_families.json` and `research/signal_registry.json`.
- Legacy trial counts are lower bounds because unrecorded historical experiments cannot be reconstructed.
- Do not demote or promote from this report automatically.
