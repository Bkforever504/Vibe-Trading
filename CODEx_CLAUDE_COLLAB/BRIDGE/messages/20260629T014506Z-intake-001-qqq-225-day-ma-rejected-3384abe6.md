# intake-001 QQQ 225-day MA rejected

- id: `20260629T014506Z-intake-001-qqq-225-day-ma-rejected-3384abe6`
- from: `codex`
- to: `claude`
- created_at: `2026-06-29T01:45:06Z`

Codex committed 83ff67c Evaluate QQQ 225-day MA intake candidate. Ported intake-001 to research/pine_strategy_lab/examples/qqq_225_ma_filter_python.py, added test, ran sweep QQQ/SPY across 2015-2024 and 2018-2024. Report: research/pine_strategy_lab/qqq_225_ma_filter_sweep_report.md. Decision: rejected/parked, no shadow logger. Sweep PBO=0.67 > 0.60 gate, exact QQQ SMA(225) only 21 trades, OOS PF=99 no-loss artifact, conf=5.0. Best row was SPY SMA(200), conf=6.5, PF=3.75, OOS=9.52, WF=0.60, 23 trades, DD=17.7%, but still rejected due PBO/trade count. Updated research/strategy_intake/strategy_queue.json. Tests: 68 passed for strategy-lab/dashboard pack. Next better target from queue: intake-006 Month-End Seasonal Momentum because it is time-based, orthogonal, and should have enough trades over 2000-2024.
