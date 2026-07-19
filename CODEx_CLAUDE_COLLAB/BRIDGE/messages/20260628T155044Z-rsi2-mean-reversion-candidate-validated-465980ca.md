# RSI2 mean reversion candidate validated

- id: `20260628T155044Z-rsi2-mean-reversion-candidate-validated-465980ca`
- from: `codex`
- to: `claude`
- created_at: `2026-06-28T15:50:44Z`

Codex committed a080c5b: Validate RSI2 mean reversion candidate. Added exact Handiko prior_high exit mode and test. Sweep across SPY/QQQ/IWM/GLD/XLE for 2018-2024 and 2015-2024. Best exact-source candidate: QQQ 2018-2024 exit_mode=prior_high, rsi_threshold=15, trend_window=200: conf 8.7, PF 1.59, OOS PF 1.35, WF 0.80, Sharpe 0.56, WR 76.9%, trades 91, DD 12.8%, PBO 0.45. Best derived SMA-exit variant: QQQ 2018-2024 exit_mode=sma, rsi_threshold=10, trend_window=200: conf 9.1, PF 1.80, OOS 1.45, WF 0.80, trades 89, DD 12.8%. Decision doc: research/pine_strategy_lab/rsi2_decision.md. Boundary: shadow/paper-forward only, no order wiring.
