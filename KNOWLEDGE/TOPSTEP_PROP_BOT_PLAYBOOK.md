# Topstep Prop Bot Playbook

Last updated: 2026-06-21

This is a separate arena from the Alpaca options bot. The Alpaca bot can keep running and being tracked. The Topstep prop bot is futures-first, paper/shadow-first, and rule-gated before any order can become executable.

## Current Build

Implemented:

- `strategies/topstep_prop_bot.py`
  - Paper-only futures scanner.
  - Reads minute candles from CSV.
  - First strategy: opening-range breakout with VWAP confirmation.
  - Supports MNQ, NQ, MES, and ES contract specs.
  - Sizes contracts from risk budget, point value, stop distance, and max-contract cap.
  - Evaluates the proposed trade through `strategies/prop_rule_gate.py`.

- `examples/mnq_opening_range_sample.csv`
  - Small sample file for end-to-end CLI verification.

- `agent/tests/test_topstep_prop_bot.py`
  - Covers opening-range/VWAP signal behavior.
  - Covers risk-based sizing.
  - Covers prop-gate blocking before paper order readiness.
  - Covers CSV parsing.

## Why This Strategy First

Opening-range + VWAP is not magic. It is the first candidate because it is:

- Easy to define.
- Easy to backtest.
- Easy to explain.
- Native to intraday futures.
- Compatible with strict prop-firm risk controls.
- Less discretionary than broad chart-reading.

The goal is not to prove this is the final edge yet. The goal is to create a clean machine for testing edge.

## Current Confidence Scores

Compliance/rule-gate confidence: 9.5/10

Reason:

- Topstep rule profile is machine-readable.
- Unknown rules block by default.
- Daily loss, trailing drawdown, max contracts, consistency, and remote-server/VPS checks exist.
- Sample Topstep-style MNQ paper signal passes only after the rule gate.

Strategy-profit confidence: 4/10

Reason:

- The strategy is clean and testable, but not yet statistically proven.
- We need 50+ closed paper trades or a realistic replay/backtest before increasing confidence.
- We need fees, slippage, session filters, and no-trade news windows.

## CLI Example

```powershell
python strategies\topstep_prop_bot.py `
  --csv examples\mnq_opening_range_sample.csv `
  --profile rules\prop_firms\topstep_topstepx_api.json `
  --symbol MNQ `
  --range-minutes 3 `
  --min-breakout-points 0.5 `
  --risk 100 `
  --max-contracts 2 `
  --day-pnl -100 `
  --drawdown-remaining 1900
```

Expected status for the sample:

```text
paper_order_ready
```

## Build Roadmap

1. Historical data loader
   - Pull MNQ/MES minute data.
   - Cache locally.
   - Normalize to the same CSV format.

2. Replay backtester
   - One day at a time.
   - Opening-range setup only.
   - Include slippage, commissions, target/stop order simulation, and no-trade windows.

3. Daily scorecard
   - Win rate.
   - Profit factor.
   - Expectancy.
   - Max drawdown.
   - Best-day consistency.
   - Rule violations.

4. Shadow AI layer
   - AI explains/ranks the setup.
   - No order authority.
   - Writes to `shadow-ai-signals.jsonl`.

5. Practice-account workflow
   - After local replay proves positive expectancy.
   - Run in Topstep Practice Account or Trading Combine shadow/semi-auto mode.

## Promotion Rule

Do not move this bot from paper/shadow to funded-account automation until:

- 50+ closed paper/replay trades.
- Profit factor above 1.3 after fees/slippage.
- Positive expectancy.
- Max drawdown stays inside Topstep limits with a 30-50% buffer.
- No prop-rule violations.
- Manual-reset kill switch is active.

