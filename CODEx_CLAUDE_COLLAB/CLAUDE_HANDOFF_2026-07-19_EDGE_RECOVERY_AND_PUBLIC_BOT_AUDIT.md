# Claude Code Handoff - Edge Recovery And Public Bot Audit

Repo: `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading`

## Boundary

Independent review only. Do not enable live trading, loosen risk gates, rewrite user changes, or select parameters on the 2025+ holdout.

## New Work To Audit

- `scripts/edge_recovery_report.py`
- `research/public_bot_replication_lab.py`
- `research/shadow_volume_coverage.py`
- `research/PUBLIC_BOT_REPLICATION_2026-07-19.md`
- Reports:
  - `~/.vibe-trading/reports/edge-recovery-report.json`
  - `~/.vibe-trading/reports/public-bot-replication-lab.json`
  - `~/.vibe-trading/reports/volume-candidate-validation.json`
  - `~/.vibe-trading/reports/shadow-volume-coverage.json`

## Current Findings

- Flip post-hardening: 12 trades, +$2,332, 66.7% WR.
- Profit peak: +$2,923; latest four trades: 0 wins, -$591.
- Repeated 9/10 score: one unique prediction, Brier 0.2767, Brier skill -0.245 versus constant base rate.
- Two fully instrumented `stand_aside` trades both lost, combined -$206. Sample is insufficient for blanket authority.
- Public mechanism replay 2025+:
  - frozen dual momentum +45.2%, double cost +43.5%, bootstrap lower 95% +4.9%;
  - QuantConnect EMA 20/60 +17.6%, lower 95% -6.5%;
  - diversified Turtle 55/10 +8.7%, lower 95% -16.7%.
- Five QQQ RSI2 plus volume rows pass a post-selection screen, but zero are high-confidence or promotion-ready.
- SPY ORB plus CMF remains rejected because its holdout interval crosses below zero.

## Your Tasks

1. Audit the one-full-bar execution delay and turnover-cost alignment in `public_bot_replication_lab.py`. Add a failing test for any timing or leakage bug you find.
2. Reproduce the QuantConnect 20/60/0.1% signal independently from the Apache-2.0 source. Report any semantic mismatch; do not silently change parameters.
3. Audit `edge_recovery_report.py` for duplicate trades, confidence provenance, peak-split logic, and counterfactual overclaiming.
4. Choose exactly one QQQ RSI2 volume rule using only pre-2025 evidence or a preregistered simplicity rule. Write the frozen choice and rationale; do not search 2025+ again.
5. Design the forward option-lifecycle join for that one candidate: OCC symbol, bid/ask at decision, quote age, Greeks, exit bid, spread/decay/IV attribution, and no same-day hindsight.
6. Inspect official public bot repositories for risk/testing patterns only. Repo popularity and claimed volume are not P&L evidence.

## Verification

Run:

```powershell
uv run --no-project --with pytest --with pandas --with numpy --with pyarrow --with yfinance pytest -q `
  agent/tests/test_edge_recovery_report.py `
  agent/tests/test_public_bot_replication_lab.py `
  agent/tests/test_shadow_volume_coverage.py `
  agent/tests/test_volume_overlay_lab.py `
  agent/tests/test_spy_orb_volume_lab.py `
  agent/tests/test_liquid_options_edge_shadow.py `
  agent/tests/test_liquid_universe_orb_replication.py `
  agent/tests/test_liquid_universe_retest_lab.py `
  agent/tests/test_momentum_rotation_forward_extension.py
```

Current expected result: 21 passed.

Return a findings-first review with exact file/line references and no live promotion recommendation.
