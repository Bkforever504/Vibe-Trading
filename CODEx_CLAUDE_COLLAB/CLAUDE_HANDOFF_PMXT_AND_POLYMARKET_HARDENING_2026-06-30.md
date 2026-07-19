# Claude Handoff - PMXT Probe + Polymarket Tracker Hardening

Date: 2026-06-30
Owner: Codex

## User Request

Kenny trusted Codex's repo-scan judgment and asked to proceed.

Codex built the top recommendation:
- PMXT read-only schema probe
- Polymarket wallet tracker data-source hardening

No execution behavior changed.

## PMXT Probe

Files:
- `tools/pmxt-probe/package.json`
- `tools/pmxt-probe/pmxt_schema_probe.mjs`
- `scripts/pmxt_market_schema_probe.py`
- `scripts/run_pmxt_market_schema_probe.ps1`
- `agent/tests/test_pmxt_market_schema_probe.py`

What it does:
- Isolated Node sandbox under `tools/pmxt-probe`.
- Uses `pmxtjs` to try read-only market fetches from:
  - Polymarket
  - Kalshi
  - Limitless
- Normalizes sample market fields:
  - id/title/ticker/slug/url
  - volume/liquidity
  - bid/ask/yes price
  - end date
  - raw key list
- Writes:
  - `data/pmxt_market_schema_probe_log.jsonl`
  - `~/.vibe-trading/reports/pmxt-market-schema-probe.json`

Integration:
- Added to `scripts/signal_stack_leaderboard.py`
- Added to `scripts/export_daily_bot_activity_csv.py` as `prediction_market_context`

Live smoke result:
- Local PMXT mode:
  - Polymarket timed out
  - Kalshi timed out
  - Limitless wanted `pmxt-core` sidecar / `pmxt-server`
- Hosted public mode with `PMXT_BASE_URL=https://api.pmxt.dev`:
  - all venues returned `Too Many Requests`

Current PMXT verdict:
- Not ready as a free backbone.
- Keep manual/read-only only.
- Do not schedule yet.
- Do not provide PMXT credentials or hosted trading keys.

NPM install note:
- `npm install` inside `tools/pmxt-probe` reported 26 vulnerabilities.
- This is isolated, but it reinforces: do not promote PMXT package into the main stack without more audit.

## Polymarket Wallet Tracker Hardening

Files:
- `strategies/polymarket_wallet_tracker.py`
- `agent/tests/test_polymarket_wallet_tracker.py`

What changed:
- `PolymarketPublicClient` now records `request_log`.
- `_get()` records endpoint status, row_count, and errors.
- New `fetch_wallet_trades_with_diagnostics()`.
- Existing `fetch_wallet_trades()` still returns only rows for backward compatibility.
- `wallet_profile_dict()` now adds:
  - `data_source`
  - `data_quality`
  - `endpoint_attempts`
  - `closed_positions_survivorship_warning`

Data-source priority:
1. `data-api/activity`
   - quality: `primary_all_activity`
2. `clob/trades`
   - quality: `fallback_clob_trades`
3. no rows
   - quality: `no_trade_rows`

Closed positions are still fetched for context, but the report now explicitly flags the survivorship risk when closed positions exist and no activity/CLOB rows exist.

## Verification

Tests:

```powershell
uv run --no-project --with pytest --with requests python -m pytest agent\tests\test_pmxt_market_schema_probe.py agent\tests\test_polymarket_wallet_tracker.py agent\tests\test_signal_stack_leaderboard.py agent\tests\test_export_daily_bot_activity_csv.py -q
```

Result:
- `16 passed`

Compile:

```powershell
uv run --no-project python -m py_compile scripts\pmxt_market_schema_probe.py strategies\polymarket_wallet_tracker.py scripts\signal_stack_leaderboard.py scripts\export_daily_bot_activity_csv.py
```

Result:
- passed

Report refresh:
- Signal leaderboard now shows `PMXT Schema Probe`
- Daily CSV now has `prediction_market_context` rows for PMXT

## Recommended Next Step

Skip deeper PMXT for now unless Kenny wants to test with a PMXT key or local sidecar.

Better next work:
1. Use `Polymarket/py-clob-client` docs/source to compare our CLOB endpoint assumptions.
2. Add wallet-cluster consensus report:
   - same market
   - same side
   - multiple wallets
   - post-entry price drift
3. Keep all copy-trader behavior read-only/paper-only.

## Safety

No orders placed.
No credentials added.
No PMXT hosted trading enabled.
No scheduler task created for PMXT.
