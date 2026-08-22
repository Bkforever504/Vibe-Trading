# Topstep Prop Bot Playbook

Last updated: 2026-08-09

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

## Current Evidence

Compliance/rule-gate confidence: 9.5/10

Reason:

- Topstep rule profile is machine-readable.
- Unknown rules block by default.
- Daily loss, trailing drawdown, max contracts, consistency, and remote-server/VPS checks exist.
- Sample Topstep-style MNQ paper signal passes only after the rule gate.

Strategy-profit confidence: 2/10

Reason:

- Licensed MES replay now covers 1,148 sessions with chronological development,
  selection, and untouched final partitions.
- The frozen 5-minute gap ORB produced $12 across 22 untouched-final trades,
  profit factor 1.016, and $336 maximum drawdown.
- Doubled execution costs produced -$76 and profit factor 0.906.
- ORB, pullback, VWAP fade, SMC/FVG, momentum, reversal, quote imbalance,
  quote exhaustion, and failed-breakdown families have not passed the locked
  evidence gates.

## Exact Combine Simulation

`strategies/topstep_combine_simulator.py` applies the current 50K rules:

- $3,000 base profit target.
- 50% best-day consistency target, including target expansion.
- $2,000 end-of-day trailing Maximum Loss Limit that locks at starting balance.
- Circular block bootstrap over untouched daily P&L, including no-trade days.
- Base and doubled-cost contract grids from one through ten MES contracts.

Run:

```powershell
.\scripts\run_topstep_combine_simulation.ps1
```

Current 5,000-path result:

- 1 MES: 0% base and stressed pass rate over 252 sessions.
- 2 MES: 0% base and stressed pass rate; stressed MLL failure 1.34%.
- 5 MES: 2.48% stressed pass rate and 54.0% MLL failure rate.
- 10 MES: 17.56% stressed pass rate and 80.94% MLL failure rate.

Decision: `do_not_purchase_combine`. More contracts increase account failure,
not edge. The Practice adapter remains the next venue only after a fresh MES
candidate passes untouched and doubled-cost evidence gates.

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
   - Topstep offers a 150K Practice Account with an active Combine subscription.
   - The ProjectX API has no separate sandbox, but the existing adapter permits
     only an API-returned, explicitly allowlisted PRACTICE account.
   - No Combine, XFA, or LFA order bridge exists or may be enabled from Practice.

## Promotion Rule

Do not move this bot from paper/shadow to funded-account automation until:

- 100+ untouched closed paper/replay trades.
- Profit factor above 1.3 after fees/slippage.
- Positive expectancy.
- Positive expectancy and profit factor above 1.2 at doubled costs.
- Max drawdown stays inside Topstep limits with a 30-50% buffer.
- No prop-rule violations.
- At least 60% simulated Combine pass rate at one or two MES contracts.
- Manual-reset kill switch is active.
