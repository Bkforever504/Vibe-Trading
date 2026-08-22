# Claude Code Handoff: TradingView Indicator Recipe Audit

Project:
`C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading`

Ultimate goal:
Build profitable, scalable, risk-controlled Alpaca/options and Topstep systems
without manufacturing confidence from social screenshots, synthetic fills,
parameter sweeps, or consumed data.

## What Codex Completed

Codex researched and backtested:

- New York AM Killzone timing.
- Traditional floor pivots plus prior-day high/low.
- Three-bar Strat-style Failed 2.
- Source-matched single-candle Failed 2 from the current open-source
  TradingView description.
- 15-minute Heikin-Ashi state using real-price fills.
- Session VWAP.
- Point-in-time daily/weekly non-opposition.

Two preregistered experiments, 12 fixed variants, two markets, and 24
market-by-variant promotion decisions were produced. Every promotion decision
failed.

## Results

Three-bar interpretation:

- MES raw: 1,104 trades, -0.1398R expectancy, PF 0.7948.
- SPY raw: 409 trades, -0.2016R expectancy, PF 0.7158.
- MES full recipe: 22 trades, -0.2588R, PF 0.6354.
- SPY full recipe: 12 trades, -0.1917R, PF 0.7069.

Source-matched Failed 2:

- MES all day: 949 trades, -0.3211R, PF 0.5904.
- SPY all day: 306 trades, -0.0746R, PF 0.8865.
- MES full: 178 trades, -0.3184R, PF 0.5932.
- SPY full: 60 trades, -0.3984R, PF 0.5034.

The source-matched SPY all-day rule was gross-positive but negative after
ordinary costs and negative in development and 2025+. It is rejected.

## Important Integrity Details

- Complete RTH sessions only.
- Next-bar entries.
- Same-bar stop/target collision resolves to stop.
- Gap-through-stop entries fail closed.
- Two-sided slippage and commissions.
- HA is state only; no synthetic HA fills.
- Prior-session levels only.
- Point-in-time HTF states.
- Fixed 2022-23 development, 2024 selection, 2025+ consumed diagnostic.
- Double-cost and top-1%-removed checks.
- No broker/scheduler/order imports.
- No production settings changed.

## Files To Review

- `research/INDICATOR_RECIPE_PREREGISTRATION_2026-07-25.md`
- `research/indicator_recipe_lab.py`
- `data/indicator_recipe_results.json`
- `research/FAILED2_SOURCE_MATCHED_PREREGISTRATION_2026-07-25.md`
- `research/failed2_source_matched_lab.py`
- `data/failed2_source_matched_results.json`
- `research/INDICATOR_RECIPE_RESULTS_2026-07-25.md`
- `agent/tests/test_indicator_recipe_lab.py`
- `agent/tests/test_failed2_source_matched_lab.py`

## Claude's Next Task

Perform an adversarial read-only audit. Do not tune parameters or add variants.

Attack:

1. Failed 2 source fidelity.
2. Session boundaries and DST.
3. Pivot and prior-session as-of correctness.
4. HA completion timing and real-price fill separation.
5. VWAP timing.
6. Stop/target path and gap handling.
7. MES cost math and SPY IEX limitations.
8. Duplicate same-day signals and one-trade enforcement.
9. Metric and promotion-gate correctness.
10. Whether any conclusion overstates what the data proves.

Only patch objective defects. If a material defect changes results, rerun both
frozen experiments and document before/after. Do not promote these indicators
or alter live bots.

## Recommended Direction After Audit

Keep Killzone, pivot, HA, VWAP, and Failed 2 as optional context fields in
research logs. Do not add them as Alpaca or Topstep gates. Continue collecting
forward evidence for the already-passing momentum rotation, turn-of-month, and
PEAD lanes. A future intraday challenger must be a materially different,
preregistered family rather than another combination of these losing filters.
