# Claude Handoff - Market Force Score

Project:
`C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading`

## What Codex Built

New read-only aggregator:
- `scripts/market_force_score.py`
- `scripts/run_market_force_score.ps1`
- `agent/tests/test_market_force_score.py`

Purpose:
- Implements the "physics / multiple forces" idea safely.
- Reads existing context/scanner logs.
- Produces one daily force tape:
  - trend force from opening-range breadth
  - level/GEX force
  - momentum force from TTM/WaveTrend/SMC
  - volatility context from VIX/IVR
  - narrative force from pre-open sentiment, social, relative volume
  - risk veto from existing kill/reset files
- No orders. No execution gates.

Outputs:
- `data/market_force_score_log.jsonl`
- `~/.vibe-trading/reports/market-force-score.json`

## Integrations

Updated:
- `scripts/signal_stack_health_report.py`
- `scripts/signal_stack_leaderboard.py`
- `scripts/export_daily_bot_activity_csv.py`

Market Force now appears in:
- signal health report
- signal stack leaderboard
- daily bot activity CSV

Leaderboard polish:
- `signal_stack_leaderboard.py` now uses top-level `confidence` for `provider=market_force_score`, instead of averaging nested force scores.

## Scheduler

Registered:
- `\VibeTrade\MarketForceScore`
- Weekdays at `15:40` local
- Runs after:
  - close-time TTM/WaveTrend/SMC loggers at 15:20
  - signal stack health at 15:35

Task status:
- Ready

## Verification

Tests:
```powershell
uv run --no-project --with pytest python -m pytest agent\tests\test_market_force_score.py agent\tests\test_signal_stack_leaderboard.py agent\tests\test_export_daily_bot_activity_csv.py agent\tests\test_signal_stack_health_report.py -q
```

Result:
- 14 passed

Compile:
```powershell
uv run --no-project python -m py_compile scripts\market_force_score.py scripts\signal_stack_health_report.py scripts\signal_stack_leaderboard.py scripts\export_daily_bot_activity_csv.py
```

Result:
- Passed

Smoke run for 2026-06-30:
```powershell
uv run --no-project python scripts\market_force_score.py --date 2026-06-30 --print
```

Result:
- classification: `bullish_confirmation`
- total_score: `3.0`
- confidence: `7.0`
- coverage: `4/5`

Forces:
- trend: `+2.0`, bullish, from opening-range breadth
- levels/GEX: `0.0`, range damper
- momentum: `0.0`, missing until close-time scanner rows exist
- volatility: `0.0`, IVR accumulating
- narrative: `+1.0`, bullish

Important:
- This is not an execution gate.
- Missing momentum is expected before the 15:20 close-time scanners run.
- Re-run after 15:40 to get the full close-time stack.

## Current Health

Signal stack health after build:
- OK: 6
- stale: 0
- missing: 3
- error: 0

OK:
- GEX
- IVR
- Opening Range
- Relative Volume
- SEC Insider
- Market Force

Missing:
- TTM
- WaveTrend
- SMC

Those should clear after their first 15:20 scheduled run.

## Next Suggested Review

After market close:
1. Let TTM/WaveTrend/SMC run at 15:20.
2. Let Market Force run at 15:40.
3. Check:
   ```powershell
   uv run --no-project python scripts\market_force_score.py --print
   uv run --no-project python scripts\signal_stack_health_report.py
   ```
4. Do not wire Market Force to execution until 30 days / enough outcome rows prove it adds predictive value.

