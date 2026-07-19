# Claude Code Handoff: Flip Paper Challengers + Weather Readiness

**Date:** 2026-07-15 CT  
**Repository:** `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading`

## User Objective

1. Accelerate Flip evidence by allowing selected liquid symbols into controlled Alpaca paper execution.
2. Push the Polymarket weather bot toward a go-live decision within one to two weeks.

## Critical Polymarket Constraint

The official endpoint returned this host as blocked:

```json
{"blocked": true, "country": "US", "region": "TX"}
```

Source: `https://polymarket.com/api/geoblock`

Polymarket's official documentation currently lists the United States as blocked for order placement. Do not bypass, obscure, proxy around, or weaken this check. Real Polymarket order submission from this host is not an allowed near-term target. Continue paper research or adapt the strategy to a legally available venue.

## Flip Changes

Files:

- `strategies\flip_bot.py`
- `scripts\run_flip_bot_entry.ps1`
- `scripts\run_flip_bot_monitor.ps1`
- `agent\tests\test_flip_bot_safety.py`

Controlled paper challenger lane:

- Scheduled scripts set `FLIP_PAPER_CHALLENGER_SYMBOLS=AAPL,NVDA`.
- SPY remains the primary execution symbol.
- AAPL/NVDA challengers are authorized only when `ALPACA_PAPER=true`.
- Challenger orders are capped at one contract.
- Any non-paper process fails closed with `symbol_not_promoted`.
- Stored setup telemetry includes `execution_lane=paper_challenger` and the original requested contract count.
- Existing maximum open positions, daily loss guard, same-day re-entry guard, liquidity checks, execution guard, and consensus safety boundaries remain unchanged.

QQQ was not added to the existing breakout scanner because doing so would silently broaden the strategy universe and setup type without a dedicated test/evidence lane. It remains in accelerated shadow collection.

## Weather Changes

Files:

- `strategies\polymarket_weather_bot.py`
- `scripts\polymarket_weather_live_readiness.py`
- `scripts\run_polymarket_weather_bot.ps1`
- `agent\tests\test_polymarket_weather_bot.py`
- `agent\tests\test_polymarket_weather_live_readiness.py`

Every weather scan now:

- Calls Polymarket's official geoblock endpoint.
- Records checked/blocked/country/region/source in `venue_eligibility`.
- Fails closed when jurisdiction is blocked or eligibility is unavailable.
- Still has no wallet, signer, credentials, allowance, or order-submission methods.
- Runs the new readiness evaluator after the paper scanner and performance report.

Readiness requirements:

- Jurisdiction allowed.
- At least 200 promotion-grade closures.
- At least 30 distinct target dates.
- Positive net P&L.
- Profit factor at least 1.25.
- Maximum drawdown no more than 25% of accumulated risk.
- Latest scan has no errors.
- Order adapter separately reviewed.
- Explicit human enablement remains required even if every check passes.

No evidence threshold, model-agreement threshold, spread threshold, or paper risk limit was loosened.

## Current Weather State

Latest real scan:

- Events discovered: 46
- Markets modeled: 506
- Current qualifying opportunities: 1
- Closed paper positions: 4
- Promotion-grade closures: 2
- Distinct target dates: 1
- Promotion-grade net P&L: `-$3.29`
- Profit factor: `0.0`
- Latest scan errors: 0
- Venue status: blocked, US
- Evidence ready: false
- Go-live eligible: false

The one-to-two-week period can produce useful evidence, but it cannot guarantee readiness and cannot override jurisdiction.

## Runtime Outputs

- `~\.vibe-trading\reports\polymarket-weather-bot.json`
- `~\.vibe-trading\reports\polymarket-weather-performance.json`
- `~\.vibe-trading\reports\polymarket-weather-live-readiness.json`
- `~\.vibe-trading\polymarket-weather-paper-state.json`

Scheduled task `PolymarketWeatherBot` remains healthy and runs every 15 minutes. The verified manual workflow completed successfully in 75.9 seconds.

## Verification

Focused suite:

```text
57 passed
compile clean
PowerShell parse clean
```

Full agent suite:

```text
3823 passed, 4 skipped, 7 failed
```

The seven failures were Futu/Mootdx loader tests caused by full-suite test-order pollution. The two failed files pass in isolation:

```text
50 passed
```

Recheck:

```powershell
python -m pytest agent/tests/test_flip_bot_safety.py agent/tests/test_polymarket_weather_bot.py agent/tests/test_polymarket_weather_performance_report.py agent/tests/test_polymarket_weather_live_readiness.py -q
python -m py_compile strategies/flip_bot.py strategies/polymarket_weather_bot.py scripts/polymarket_weather_performance_report.py scripts/polymarket_weather_live_readiness.py
powershell.exe -NonInteractive -ExecutionPolicy Bypass -File scripts/run_polymarket_weather_bot.ps1
python scripts/polymarket_weather_live_readiness.py --print
```

## Recommended Next Work

1. Collect forward weather closures without loosening promotion criteria.
2. Add event-level calibration/Brier scoring so adjacent temperature buckets are not miscounted as independent evidence.
3. Add settlement-source consistency checks against the exact market resolution station.
4. Evaluate a legally available prediction-market venue adapter while keeping venue-specific execution isolated.
5. Review AAPL/NVDA paper challenger fills, path telemetry, correlation, and slippage after five sessions before expanding the paper lane.

## Hard Stops

- Never bypass geographic restrictions.
- Never enable Polymarket orders from this US host.
- Never treat hundreds of correlated contract buckets as hundreds of independent forecasts.
- Never lower the 10% edge threshold from near-miss results automatically.
- Never promote Flip challengers to real money based only on paper authorization.
