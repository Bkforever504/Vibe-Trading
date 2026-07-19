# Claude Handoff — Guard Improvements

Date: 2026-06-27

## What Was Done

### Task 1 — Guard Block JSONL Log + Dashboard Panel

**execution_guard.py**
- Added `GUARD_BLOCK_LOG_FILE = Path("~/.vibe-trading/guard-blocks.jsonl")`
- Added `_append_block_log(decision)` — appends one JSON line per blocked decision
- Refactored all blocked-return paths inside `evaluate_execution` to use internal `_blocked()` helper that calls `_append_block_log` before returning

**trading_dashboard.py**
- Added `GUARD_BLOCK_LOG_FILE` path constant
- Added `guard_blocks_context(path, limit=20)` — reads last 20 JSONL entries, returns dict
- Added `guard_blocks_panel(context)` — renders HTML table: timestamp, bot, symbol, reason, conf/min, notional, daily loss %, manual reset flag
- Wired panel into `render()` between polymarket panel and account equity section

Log location: `~/.vibe-trading/guard-blocks.jsonl`

### Task 2 — Broker Position Sync (truth over local JSON)

**flip_bot.py**
- Added `_extract_underlying(sym)` — strips digits to get underlying from OCC symbol
- Added `_fetch_broker_open_symbols()` — calls `GET /v2/positions`, extracts underlyings, logs result
- `run_entry()` now calls `_fetch_broker_open_symbols()` once before the candidate loop
- `open_symbols` passed to `evaluate_execution` is now `local_open_symbols | broker_symbols` — broker truth wins over stale local JSON

**iwm_options_bot.py**
- Added `_broker_open_underlying_symbols()` — same pattern using `requests` + env KEY/SECRET
- `_guard_submission()` now calls `_broker_open_underlying_symbols()` and passes result as `open_symbols` to `evaluate_execution`

### Task 3 — Confidence Threshold Normalization

**flip_bot.py**
- `BEAR_TREND_MIN_CONFIDENCE = 8` → `8.5`
- Now matches `ExecutionGuardConfig.min_confidence = 8.5` default
- Setups scoring exactly 8 no longer pass the local gate only to get blocked at the guard

### Task 4 — Spread/Liquidity Fields in Flip Bot

**flip_bot.py**
- Added `_option_bid_ask_spread_cents(occ_symbol)` — fetches Alpaca options snapshot, returns `int((ask - bid) * 100)` or `None`
- `find_0dte`, `find_bear_trend_day` (single-leg), `find_bull_trend_day` all now include `spread_cents` in returned setup dict
- `run_entry()` passes `spread_cents=setup.get("spread_cents")` to `evaluate_execution`
- `ExecutionGuardConfig(max_spread_cents=...)` can now actually gate Flip Bot trades — set it when desired

Note: bear put spread setups (`bear_trend_spread`) do not yet have `spread_cents` — computing net spread bid-ask on two legs is non-trivial, left for next session.

## Test Status

```
6 passed, 1 warning in 3.19s
```

All prior guard tests still green. No regressions.

## Current Env State (unchanged)

```
ALPACA_PAPER=true
FLIP_LIVE_EXECUTION_ENABLED=<unset>
OPTIONS_LIVE_EXECUTION_ENABLED=<unset>
CONFIRM_LIVE_TRADING=<unset>
REQUIRE_MANUAL_APPROVAL=false
```

Live execution remains hard-blocked. Paper auto-execution active.

## Suggested Next Codex Tasks

### P0
1. **IWM stop loss** — enforce -100% of credit max (currently allows -211%)
   - File: `strategies/iwm_options_bot.py`
   - Current `STOP_LOSS_PCT = -1.0` (100%) but not enforced on multi-leg unwind

2. **Bear trend spread execution** — `bear_trend_spread` strategy has no `run_monitor` / `run_entry` dual-leg close logic
   - `run_monitor()` in flip_bot already calls `_close_spread()` for spread trades — verify it works
   - Add `spread_cents` to `bear_trend_spread` setup (requires averaging bid-ask across two legs)

### P1
3. **Polymarket wallet tracker** — fetch public CLOB trades, feed copy_trader_watchlist via importer
4. **Kalshi fills fetcher** — pull own trade history for self-scoring
5. **MNQ scanner diagnostics** — add per-bar logging to explain zero signals on high-confidence bear days
6. **Flip Bot `max_spread_cents` config** — now that `spread_cents` is populated, set a reasonable limit
   - Suggested: `ExecutionGuardConfig(max_spread_cents=50)` rejects options with spread > $0.50

## Safety Bottom Line

Do not set `FLIP_LIVE_EXECUTION_ENABLED=true` or `OPTIONS_LIVE_EXECUTION_ENABLED=true`.  
Live execution stays blocked until Kenny explicitly approves after forward validation.
