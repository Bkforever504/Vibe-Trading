# Hurst regime scanner added from Ernie Chan repo review

- id: `20260701T043855Z-hurst-regime-scanner-added-from-ernie-chan-repo--279c4501`
- from: `codex`
- to: `claude`
- created_at: `2026-07-01T04:38:55Z`

Implemented the useful piece from zazhang/ep-chan-book-algo-trading as a clean read-only Hurst regime scanner, not an old dependency install. Files: scripts/hurst_regime_scanner.py, scripts/run_hurst_regime_scanner.ps1, agent/tests/test_hurst_regime_scanner.py. Integrated into market_force_score as non-directional strategy-family context, signal_stack_health_report, market_schedule_alignment, export_daily_bot_activity_csv, and research/signal_registry.json. Scheduled task: \\VibeTrade\\HurstRegimeScanner weekdays 08:38 CT, sequenced after RV/IV 08:37 and before Opening Range 08:40. First 2026-06-30 read: SPY hurst=0.600 momentum family, QQQ=0.538 stand aside, IWM=0.517 stand aside; aggregate avg_hurst=0.552 but 2-of-3 vote says random_walk_zone / stand_aside_or_confirm / score=0.0. This is context-only and not bullish/bearish. Verification: focused tests 41 passed, schedule alignment 42/42 issues=0, signal health OK=26 stale/missing/error=0, execution audit passed issues=0 warnings=1 known read-only portfolio concentration warning, EOD green with 98 events. Constraint: do not use Hurst as an execution gate until 30 trading days / 10 relevant samples and promotion review.
