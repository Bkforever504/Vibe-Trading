# Claude Code Handoff: Kalshi Weather Bot

Date: 2026-07-15 CT

## Objective

Replace the US-geoblocked Polymarket weather execution target with a US-regulated Kalshi weather research lane. Preserve evidence-first promotion and fail-closed execution. Do not route around Polymarket restrictions and do not enable Kalshi orders from this handoff.

## Delivered Baseline

- `strategies/kalshi_weather_bot.py`: autonomous public-data paper scanner for 13 Kalshi daily-high-temperature series.
- `strategies/kalshi_weather_execution.py`: dormant authenticated order adapter. It is not imported or scheduled by the paper bot.
- `scripts/kalshi_weather_performance_report.py`: independent city-day P&L, drawdown, expectancy, profit factor, and Brier skill against the executable market probability.
- `scripts/kalshi_weather_readiness.py`: fail-closed evidence gate.
- `scripts/run_kalshi_weather_bot.ps1`: scanner, performance report, and readiness report runner.
- `scripts/register_kalshi_weather_bot_task.ps1`: 15-minute Windows task registration.
- Current Kalshi fixed-point compatibility was also added to `strategies/kalshi_prediction_bot.py` and `strategies/kalshi_history_fetcher.py`.

## Venue Research Encoded

- Markets resolve from the exact NWS Daily Climate Report station named by Kalshi, not a generic city forecast.
- Authentication uses Kalshi RSA-PSS SHA-256 request signing.
- Current market and orderbook fixed-point fields are used; reciprocal YES/NO asks are derived from the single YES book.
- Bulk orderbooks are preferred to avoid rate-limit bursts; retries are bounded exponential backoff.
- Edge is fee-adjusted using the conservative general taker-fee formula.
- Final outcomes are accepted only from Kalshi's finalized result.

Primary references:

- https://help.kalshi.com/en/articles/13823837-weather-markets
- https://docs.kalshi.com/getting_started/quick_start_authenticated_requests
- https://docs.kalshi.com/getting_started/quick_start_market_data
- https://docs.kalshi.com/getting_started/orderbook_responses
- https://docs.kalshi.com/api-reference/market/get-multiple-market-orderbooks
- https://docs.kalshi.com/api-reference/orders/create-order-v2
- https://docs.kalshi.com/getting_started/rate_limits
- https://kalshi.com/docs/kalshi-fee-schedule.pdf

## Model And Selection Rules

- Coverage: New York, Chicago, Miami, Austin, Boston, Denver, Atlanta, Minneapolis, Phoenix, Dallas, Houston, Seattle, Oklahoma City.
- Forecast ensemble: GFS, ECMWF, and ICON model families through Open-Meteo ensemble data.
- Require all three families and at least 20 total members.
- Require at least 10 percentage points of fee-adjusted edge in every model family.
- Maximum family probability disagreement: 0.20.
- Maximum executable spread: 0.10.
- Minimum time to market close: 2 hours.
- Select one best bucket per independent city-day to avoid treating correlated ladder buckets as independent samples.
- Paper sizing: one contract, maximum $15 aggregate daily paper risk, maximum 20 open positions.

## Live Safety Boundary

`strategies/kalshi_weather_execution.py` is dormant. A submission requires all of the following:

- `KALSHI_ENABLE_LIVE_TRADING=true`
- exact acknowledgement `I_ACKNOWLEDGE_KALSHI_WEATHER_LIVE_RISK`
- readiness report has `go_live_eligible=true`
- valid API key and private-key file
- no manual-reset block file
- one contract only

The scheduled task never imports this adapter. No order was submitted.

Promotion requires at least 200 promotion-grade independent closures across 14 target dates, positive net P&L, profit factor at least 1.25, drawdown on risk at most 25%, model Brier at most 0.20, Brier skill over market at least 0.01, complete series coverage, clean latest scan, and separate authenticated-adapter review. Passing sample count alone is not sufficient.

## Verified Host State

- `\KalshiWeatherBot`: Ready, last result `0`, every 15 minutes.
- `\VibeTrade\PolymarketWeatherBot`: Disabled.
- Latest real scan: 13 series, 26 events, 156 modeled contracts, 11 qualifying buckets, 7 selected independent opportunities, 7 open paper positions, 0 errors, about 7.2 seconds.
- Current evidence: 0 finalized closures; readiness correctly false.
- Focused suite: 29 passed.
- Python compile clean; both PowerShell scripts parse cleanly.
- `execution_enabled=false` and `can_submit_orders=false` in paper/performance/readiness outputs.

## Exact Recheck

```powershell
cd C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading
python -m pytest agent/tests/test_kalshi_weather_execution.py agent/tests/test_kalshi_weather_bot.py agent/tests/test_kalshi_weather_performance_report.py agent/tests/test_kalshi_weather_readiness.py agent/tests/test_kalshi_prediction_bot.py agent/tests/test_kalshi_history_fetcher.py -q
python scripts/kalshi_weather_performance_report.py --print
python scripts/kalshi_weather_readiness.py --print
Get-ScheduledTask -TaskName KalshiWeatherBot,PolymarketWeatherBot -ErrorAction SilentlyContinue | Format-Table TaskPath,TaskName,State
```

## Next Work, In Order

1. Let finalized city-days build a real calibration and P&L sample; inspect results daily for station/source mismatches.
2. Add forecast-vintage telemetry so outcomes can be compared by model run age and lead time without lookahead.
3. Add near-miss tracking for 5-9.9% fee-adjusted edge and compare it with the 10% cohort after enough closures.
4. Evaluate reliability curves by city, lead-time bucket, and model family. Do not remove a family or lower the edge threshold from anecdotes.
5. Independently review authenticated endpoint payloads against the current Kalshi production schema before any pilot.
6. If every readiness condition passes, run a manually supervised one-contract pilot first. Do not connect the paper task directly to submission.

## Stop Conditions

- Do not bypass jurisdiction restrictions.
- Do not infer settlement from forecasts or observed weather; wait for Kalshi finalization.
- Do not count multiple buckets in one city-day as independent evidence.
- Do not lower thresholds, enlarge sizing, or enable authenticated execution without point-in-time evidence and explicit human approval.
- Do not weaken the one-contract pilot cap, manual-reset block, or readiness gate.
