# Claude Code Handoff: SPY Theta Harvester Hardening

Date: 2026-08-10 Central / 2026-08-11 UTC

## Executive Status

The previous `spy_theta_harvester.py` was not a live paper trader. It generated a midpoint-priced JSON setup from yfinance and the monitor treated that file as an open position. It had no broker fill, no shadow fill, no quote timestamps, no IV-versus-realized-volatility gate, no credit-quality gate, and an unsafe VIX3M fallback that invented contango.

Codex replaced it with a fail-closed executable-quote shadow ledger. There is still no order-submission code. No Alpaca paper or live order was submitted.

The saved `SPY 2026-09-11 733P/728P` setup is invalid and has been labeled `legacy_unconfirmed_invalid`.

## Important Correction To The MES Summary

`MES-PUBLIC-REPLICATION-01` used one-minute OHLCV, not BBO/OFI. It rejected five frozen public-rule translations on 618 sessions. It did not establish that all MES intraday strategies are exhausted, and it did not test the existing BBO/OFI caches. Do not repeat the broader claim.

## Why The Saved Theta Setup Was Rejected

The legacy candidate claimed a $0.35 credit on a $5-wide spread.

- Credit-to-width: `0.35 / 5.00 = 7%`, below the frozen 33% minimum.
- Profit management: $17.50 target gain versus $35 stop loss requires a 66.67% win rate before fees and slippage.
- It was generated outside the market entry window.
- It had no quote timestamps and used midpoint pricing.
- Official PPI is September 10 and CPI is September 11, the spread's expiration date. High-impact event risk is concentrated immediately before and on expiry.

A read-only Alpaca chain probe at 22:49 ET found the actual nearest 16-delta candidate:

- Spread: `SPY260911P00739000 / SPY260911P00734000`
- Delta: `0.1589`
- Short bid/ask: `$3.25 / $3.28`
- Long bid/ask: `$2.68 / $2.77`
- Executable entry credit: `$0.48`
- Midpoint credit: `$0.54`
- Credit-to-width: `9.6%`
- Combined quote width / executable credit: `25%`
- Quote timestamps: approximately 15:59 ET, stale at probe time

This candidate also fails. The probe was read-only and submitted no order.

## New Entry Gates

`strategies/spy_theta_harvester.py` now requires all of the following:

1. Monday 09:40-10:15 ET entry window.
2. Current CBOE VIX/VIX3M data with no fallback; VIX below 20 and contango ratio below 1.02.
3. Alpaca option-chain snapshots with both selected-leg quotes no older than 180 seconds.
4. Nearest available 16-delta put in the frozen 28-45 DTE window and exact $5 wing.
5. Executable credit equal to short bid minus long ask, never midpoint.
6. Credit-to-width at least 33%.
7. Maximum planned spread loss no more than $500.
8. Combined leg quote width no more than 25% of executable credit.
9. Maturity-matched ATM IV, zero-mean EWMA RV, and quote-friction instrumentation.
10. IV/RV ratio at least 1.05 and positive net volatility premium after the spread-friction proxy.
11. Complete official macro-calendar coverage through expiry.
12. No high-impact event on expiry or within the prior two calendar days.
13. No same-day short-premium veto.
14. No already-open schema-v2 shadow position.

Any missing input blocks entry. No fallback can create an eligible setup.

## Shadow State And Monitoring

Confirmed entries are conservative shadow fills only:

- State: `data/theta_harvester_state.json`
- Entry decision: `data/theta_harvester_entry_decision.json`
- Monitor decision: `data/theta_harvester_monitor_decision.json`
- Append-only ledger: `data/theta_harvester_ledger.jsonl`
- Log: `~/.vibe-trading/logs/spy-theta-harvester.log`

The old `data/theta_harvester_setup.json` cannot be loaded as an open position.

Monitor marks use executable close debit:

`short ask - long bid`

The state closes only in shadow accounting when that debit reaches the 50% target or 2x-credit stop. The ledger records open, mark, and close events. No broker route exists.

## Scheduler

Both tasks were re-registered successfully:

- `SPY-Theta-Harvester-Entry`: Monday 8:45 AM CT.
- `SPY-Theta-Harvester-Monitor`: Monday-Friday at 9:00, 10:00, 11:00, 12:00, 1:00, and 2:00 CT.

Both are `Ready`. Entry next run: 2026-08-17 08:45 CT. Monitor next run: 2026-08-11 09:00 CT. Catch-up entry runs outside the ET window fail closed.

## Files Changed

- `strategies/spy_theta_harvester.py`
- `scripts/run_spy_theta_harvester.ps1`
- `scripts/run_spy_theta_harvester_monitor.ps1`
- `scripts/register_spy_theta_harvester_task.ps1`
- `scripts/market_catalyst_calendar.py`
- `scripts/options_vol_premium_report.py`
- `agent/tests/test_spy_theta_harvester.py`
- `agent/tests/test_options_vol_premium_report.py`
- `data/theta_harvester_setup.json`

This worktree contains extensive unrelated user and Claude changes. Do not revert, normalize, or stage them accidentally.

## Verification

Focused theta tests:

```powershell
python -m pytest agent/tests/test_spy_theta_harvester.py -q
```

Result after final script split: `10 passed`.

Theta, vol-premium, and calendar group:

```powershell
python -m pytest agent/tests/test_spy_theta_harvester.py agent/tests/test_options_vol_premium_report.py agent/tests/test_market_catalyst_calendar.py -q
```

Result before the final output-path-only change: `35 passed`.

Full suite:

```powershell
python -m pytest agent/tests -q
```

Result: `4537 passed, 4 skipped, 4 warnings` in 235.93 seconds. The subsequent change only separated entry and monitor decision paths and passed its focused test.

Python and PowerShell syntax checks passed. Manual entry and monitor dry runs outside market hours correctly returned `blocked`/`skipped` and created no state.

## Evidence Interpretation

Variance risk premium is academically documented, but it is compensation for downside variance and macro-event risk. It does not establish that a specific 16-delta SPY credit spread is profitable. Relevant primary sources:

- Federal Reserve variance-risk-premium research: `https://www.federalreserve.gov/pubs/FEDS/2010/201014/`
- Federal Reserve macro-event option-premium research: `https://www.federalreserve.gov/econres/ifdp/the-price-of-macroeconomic-uncertainty-evidence-from-daily-options.htm`
- Cboe PUTVM methodology: `https://cdn.cboe.com/api/global/us_indices/governance/PUTVM_Methodology.pdf`
- BLS CPI schedule: `https://www.bls.gov/schedule/news_release/cpi.htm`
- BLS PPI schedule: `https://www.bls.gov/schedule/news_release/ppi.htm`
- 2026 FOMC calendar: `https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm`

## Claude's Next Actions

1. Review the new executable-price and state-transition code. Do not add an order route.
2. On each scheduled run, inspect `theta_harvester_entry_decision.json`. A blocked result is expected and valid.
3. If a schema-v2 `open_shadow` state is created, verify entry quotes, IV/RV fields, event coverage, and ledger consistency before accepting it as evidence.
4. Do not lower the 33% credit-to-width floor to force activity. If no 16-delta $5 spread qualifies, the frozen strategy has no trade.
5. Accumulate at least 60 resolved shadow outcomes over at least three calendar months before evaluating expectancy.
6. Promotion requires positive expectancy after executable entry/exit pricing and explicit costs, profit factor at least 1.20, acceptable drawdown and loss streaks, and no dependence on the best 1% of outcomes.
7. Keep Flip-bot and theta evidence separate. Do not combine their PnL or sample counts.
8. Do not describe social-media traders as verified without timestamped alerts, exact contracts, executable entry windows, all losses, and independently reconciled statements.

## Safety Boundary

`execution_enabled=false`, `can_submit_orders=false`, and `orders_submitted=0` are present in every decision and state. There is no live or Alpaca-paper order function. Changing `THETA_LIVE_EXECUTION` causes an error; it does not unlock execution.
