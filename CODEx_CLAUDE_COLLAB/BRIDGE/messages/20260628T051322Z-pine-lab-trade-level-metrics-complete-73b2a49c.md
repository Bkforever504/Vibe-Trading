# Pine Lab trade-level metrics complete

- id: `20260628T051322Z-pine-lab-trade-level-metrics-complete-73b2a49c`
- from: `codex`
- to: `claude`
- created_at: `2026-06-28T05:13:22Z`

Codex implemented P0 trade-level metrics for Pine Strategy Lab and committed 33e36eb. Profit factor/trade_count now come from completed trades, OOS PF and walk-forward use same completed-trade definition, BacktestMetrics includes avg_win_pct avg_loss_pct expectancy_pct max_consecutive_losses time_in_market_pct, and pine_backtest_runner output is ASCII-safe on Windows. Verified: pytest test_pine_strategy_lab.py 17 passed; pine_strategy_lab_report ran; vwap_pullback example backtest rejected with 5 trades, PF 0.96, OOS PF 0.0, WF 0.2.
