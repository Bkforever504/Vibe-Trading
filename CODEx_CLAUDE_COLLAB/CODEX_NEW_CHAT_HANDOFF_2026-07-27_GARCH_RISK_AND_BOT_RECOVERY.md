# New Chat Handoff - GARCH Risk Layer + Bot Recovery

Project folder:

`C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading`

Date: 2026-07-27

## Ultimate Goal

Stop the Alpaca bots from bleeding on low-quality trades and build toward a high-confidence, self-improving trading system. The learning loop must not just produce reports; it must actively block, size down, quarantine, or promote behavior based on verified evidence. No live-money expansion until forward evidence earns it.

## Important Reality Check

GARCH does **not** predict trade direction. It forecasts volatility magnitude. We are using it as a risk throttle only:

- calm/normal regimes: allow normal evaluated strategy flow
- elevated volatility: reduce size
- storm regimes: block new options risk

This is a protective layer, not a magic profit engine.

## What Codex Just Finished

### 1. GARCH Volatility Risk Report

Added:

`scripts/garch_volatility_risk.py`

What it does:

- Fetches daily OHLCV for symbols.
- Fits a GARCH(1,1) model using `arch`.
- Computes annualized forecast volatility.
- Classifies volatility regime:
  - `calm` <= 33rd percentile
  - `normal` between 33rd and 67th
  - `storm` >= 67th percentile
- Computes position-size multiplier:
  - `min(target_vol / forecast_vol, max_multiplier)`
  - default `target_vol=15%`
  - default `max_multiplier=1.0`, so it never levers up
  - default `min_multiplier=0.25`
- Writes:
  - `~\.vibe-trading\reports\garch-volatility-risk.json`
  - `data/garch_volatility_risk_log.jsonl`
- Never submits orders.

Runner added:

`scripts/run_garch_volatility_risk.ps1`

Task registration added:

`scripts/register_garch_volatility_risk_task.ps1`

Registered task:

`VibeTradingGarchVolatilityRisk`

Schedule:

- weekdays at 8:35 AM Central
- runs before the options entry window
- read-only report only
- no order endpoints

Runs with:

```powershell
uv run --no-project `
  --with arch `
  --with alpaca-py `
  --with numpy `
  --with pandas `
  --with python-dotenv `
  --with yfinance `
  python scripts\garch_volatility_risk.py --print
```

### 2. Options Bot GARCH Gate

Updated:

`strategies/iwm_options_bot.py`

New env/config:

- `GARCH_RISK_REPORT=~\.vibe-trading\reports\garch-volatility-risk.json`
- `ENABLE_GARCH_RISK_GATE=true`
- `OPTIONS_GARCH_STORM_BLOCK=true`
- `OPTIONS_REQUIRE_GARCH_REPORT=false`
- `OPTIONS_GARCH_MIN_ENTRY_MULTIPLIER=0.50`

New helpers:

- `_garch_symbol_row(symbol)`
- `_garch_entry_adjustment(symbol, qty)`
- `_garch_meta(row, reason)`

Entry behavior:

- Missing report does not crash and does not block by default.
- If `OPTIONS_REQUIRE_GARCH_REPORT=true`, missing/bad report blocks entries.
- `regime=storm` blocks new options entries by default.
- multiplier below `OPTIONS_GARCH_MIN_ENTRY_MULTIPLIER` blocks.
- multiplier between threshold and 1.0 reduces contracts.
- multiplier never increases contracts.
- GARCH context is stored in trade metadata under `garch_volatility_risk`.
- Blocked multi-leg candidates are recorded in options shadow twin as `blocked_garch_volatility_risk`.

Applied to:

- `_place_mleg`
- `_place_single_leg`

### 3. Tests Added

Added:

`agent/tests/test_garch_volatility_risk.py`

Covers:

- sizing caps and never levers up
- invalid forecast returns minimum multiplier
- regime classification
- report summary construction without order side effects

Updated:

`agent/tests/test_iwm_options_confidence_gate.py`

Added GARCH coverage:

- storm report blocks multi-leg entry
- missing report allows by default
- normal report with multiplier reduces quantity
- storm report blocks single-leg entry

## Verification Completed

Compile:

```powershell
python -m py_compile scripts\garch_volatility_risk.py strategies\iwm_options_bot.py
```

Passed.

Focused tests:

```powershell
python -m pytest agent\tests\test_garch_volatility_risk.py agent\tests\test_iwm_options_confidence_gate.py -q
```

Result:

`30 passed, 1 warning`

Broader options safety suite:

```powershell
python -m pytest agent\tests\test_iwm_options_confidence_gate.py agent\tests\test_options_state_integrity.py agent\tests\test_options_position_reconciler.py agent\tests\test_options_lifecycle_pnl.py agent\tests\test_options_shadow_twin.py agent\tests\test_self_learning_edge_loop.py agent\tests\test_execution_gate_audit.py agent\tests\test_garch_volatility_risk.py -q
```

Result:

`80 passed, 1 warning`

Real GARCH report run:

```powershell
uv run --no-project --with arch --with alpaca-py --with numpy --with pandas --with python-dotenv --with yfinance python scripts\garch_volatility_risk.py --symbols SPY,IWM,QQQ --print
```

Output:

```text
GARCH Volatility Risk | read-only
========================================================================
2026-07-27 ok=3 storm=QQQ min_mult=0.659
SPY   status=ok    regime=normal  vol=13.08% mult=1.0
IWM   status=ok    regime=normal  vol=18.59% mult=0.807
QQQ   status=ok    regime=storm   vol=22.76% mult=0.659
No orders placed. GARCH forecasts magnitude, not direction.
```

Interpretation:

- SPY options entries are not reduced by GARCH today.
- IWM entries are allowed but size-throttled.
- QQQ entries are blocked because QQQ is currently classified as storm.

## Critical Context From Earlier In This Thread

The biggest bot issue was not that the learning loop had no signal. It was that the options entry path was still permissive.

Already fixed before this GARCH step:

- `_options_consensus_entry_block_reason(consensus)` added.
- Options bot now blocks when learning/shadow consensus says:
  - `stand_aside`
  - `needs_review`
  - no usable `options_playbook`
  - `decision.bot_assist.options_bot` is false
- Applied to both `_place_mleg` and `_place_single_leg`.

Also fixed:

- stale `quote_mark.netted_legs` no longer blocks normal close attempts when broker positions show all legs are present.
- This addressed the stale IWM exit issue where old netting state prevented closure.

Important current state:

- I did **not** submit broker orders.
- I did **not** run monitor loops that could submit close orders.
- Real GARCH report was generated read-only.

## Current Risk Posture

The bots are now more selective, but not “solved.”

Current stack:

1. Learning/shadow consensus can block options entries.
2. Execution guard still blocks unsafe submissions.
3. GARCH now blocks storm volatility regimes and reduces size.
4. The remaining open question is whether the underlying entry strategies have enough positive expectancy after costs.

## Best Next Actions For New Chat

### P0 - Schedule GARCH Before Options Entry

Done. Scheduled task registered:

`VibeTradingGarchVolatilityRisk`

It runs:

- weekdays at 8:35 AM Central
- next run observed: 2026-07-28 8:35 AM Central

Optional improvement: add an 11:30 AM Central rerun if intraday regime refresh becomes useful.

### P0 - Run Full Readiness Snapshot

Run:

```powershell
python scripts\execution_gate_audit.py
python scripts\options_position_reconciler.py --print
python scripts\shadow_consensus_gate.py --print
python scripts\elite_bot_readiness_scorecard.py --print
python scripts\options_grouped_dashboard.py
```

Goal:

- confirm no entry path bypasses new consensus/GARCH gates
- confirm IWM exit state is still understood
- confirm current active risk

### P1 - Add GARCH To Self-Learning Reports

Update learning/postmortem scripts to include:

- `garch_regime`
- `garch_multiplier`
- `forecast_vol_annualized_pct`
- `vol_percentile_1y`
- `report_generated_at`

Purpose:

Losses should now be grouped by volatility regime so the loop can learn:

- losses in storm regimes
- losses after multiplier was low
- wins/losses when GARCH was normal
- whether storm block would have avoided major drawdowns

### P1 - Adversarial Audit GARCH Itself

Build a small audit for GARCH report:

- does it use future data? It should not.
- is the report stale?
- are symbols missing?
- does a missing report silently allow too much risk?
- does the bot log the GARCH state on every candidate?

### P1 - Connect Pre-Dawn / Overnight Research To Shadow, Not Live

User sent screenshots about:

- futures trade nearly 24h
- 2am-5am ET London/Tokyo overlap liquidity
- overnight vs intraday return streams partially reversing
- month-end / quarter-end / index rebalance flows

Do **not** rush this into live trades. Create a preregistered shadow lab:

Hypotheses to test:

- overnight gap direction vs RTH continuation/reversal
- pre-dawn futures move direction vs 9:30-11:30 SPY/QQQ option edge
- month-end/quarter-end flow days vs normal days
- large overnight gap + GARCH storm = no 0DTE risk

Candidate script name:

`research/overnight_handoff_lab.py`

Candidate output:

`data/overnight_handoff_results.json`

### P2 - Improve Confidence Score

The user wants 9-10/10 confidence, but that cannot be declared from vibes. Use a scorecard:

- verified forward sample >= 30 independent trades
- positive expectancy after 2x costs
- positive after removing top 1% outliers
- no look-ahead
- no final-period retuning
- learning loop actually blocks bad conditions
- broker-realized P&L, not estimated text
- max drawdown acceptable for $1,000 account

Anything below those gates stays shadow/paper.

## Files Changed In This Completion

Expected touched files from this final step:

- `scripts/garch_volatility_risk.py`
- `scripts/run_garch_volatility_risk.ps1`
- `scripts/register_garch_volatility_risk_task.ps1`
- `strategies/iwm_options_bot.py`
- `agent/tests/test_garch_volatility_risk.py`
- `agent/tests/test_iwm_options_confidence_gate.py`
- this handoff file

Note: repo is very dirty from prior Claude/Codex work and generated logs. Do not revert unrelated changes.
