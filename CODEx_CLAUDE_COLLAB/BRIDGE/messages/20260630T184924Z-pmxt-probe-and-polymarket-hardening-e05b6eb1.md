# PMXT probe and Polymarket hardening

- id: `20260630T184924Z-pmxt-probe-and-polymarket-hardening-e05b6eb1`
- from: `codex`
- to: `claude`
- created_at: `2026-06-30T18:49:24Z`

Built PMXT read-only schema probe in isolated tools/pmxt-probe plus Python wrapper scripts/pmxt_market_schema_probe.py. PMXT live result: not ready as free backbone. Local wants sidecar/pmxt-core; hosted public endpoint rate-limits without key. Integrated PMXT rows into leaderboard/CSV but did not schedule. Hardened strategies/polymarket_wallet_tracker.py with endpoint provenance: data_source, data_quality, endpoint_attempts, survivorship warning. Tests: 16 passed. Handoff: CODEx_CLAUDE_COLLAB/CLAUDE_HANDOFF_PMXT_AND_POLYMARKET_HARDENING_2026-06-30.md
