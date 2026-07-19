# Market Force Score built

- id: `20260630T141848Z-market-force-score-built-d801c62c`
- from: `codex`
- to: `claude`
- created_at: `2026-06-30T14:18:48Z`

Codex built scripts/market_force_score.py as the read-only physics/multiple-forces aggregator. It reads ORB breadth, GEX, IVR/VIX context, TTM/WaveTrend/SMC, preopen sentiment, social trending, relative volume, and risk veto files. Outputs data/market_force_score_log.jsonl and ~/.vibe-trading/reports/market-force-score.json. Integrated into signal_stack_health_report.py, signal_stack_leaderboard.py, and export_daily_bot_activity_csv.py. Added scripts/run_market_force_score.ps1 and scheduled \\VibeTrade\\MarketForceScore weekdays 15:40 local. Verification: 14 focused tests passed, py_compile passed. 2026-06-30 smoke: classification=bullish_confirmation score=3.0 confidence=7.0 coverage=4/5; momentum missing until 15:20 close-time scanners run. Full handoff: CODEx_CLAUDE_COLLAB/CLAUDE_HANDOFF_MARKET_FORCE_SCORE_2026-06-30.md
