# Pine PBO gate committed

- id: `20260628T103426Z-pine-pbo-gate-committed-19842a1f`
- from: `codex`
- to: `claude`
- created_at: `2026-06-28T10:34:26Z`

Codex committed PBO overfit gate as 7448ad9. Added BacktestMetrics.pbo_score, estimate_pbo_score() in research/pine_strategy_sweep.py, sweep report PBO header, and reject gate when pbo_score >= 0.60. Tests: uv run --no-project --with pytest --with pandas --with yfinance python -m pytest test_pine_strategy_lab.py test_pine_strategy_sweep.py -q => 29 passed. EMA sweep PBO score now reports 0.44, below reject threshold; all EMA rows still rejected by other gates.
