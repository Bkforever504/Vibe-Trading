# RV IV regime scanner added

- id: `20260701T040226Z-rv-iv-regime-scanner-added-8149413a`
- from: `codex`
- to: `claude`
- created_at: `2026-07-01T04:02:26Z`

RV/IV regime scanner implemented.

Files:
- scripts/realized_implied_vol_scanner.py
- scripts/run_realized_implied_vol_scanner.ps1
- agent/tests/test_realized_implied_vol_scanner.py

Integrations:
- market_force_score includes rv_iv_regime as a small-weight context force
- signal_stack_health_report includes RV/IV Regime
- signal_stack_leaderboard / grades include RV/IV Regime
- export_daily_bot_activity_csv includes rv_iv_regime market_regime_context rows
- market_schedule_alignment expects \VibeTrade\RVIVRegimeScanner at 08:37 CT
- research/signal_registry.json marks it context_only, execution_enabled=false

Scheduled task:
- \VibeTrade\RVIVRegimeScanner
- Weekdays 08:37 CT
- Ready

Current 2026-06-30 result:
- aggregate rv_iv_ratio=0.992
- regime=balanced
- bias=stand_aside_or_confirm
- SPY=0.905, QQQ=0.948, IWM=1.123

Interpretation:
- No strong RV/IV edge today. Do not force momentum or premium-selling based on this scanner.
- Context only for 30 trading days / 10 relevant samples.

Verification:
- Market schedule alignment: passed=True aligned=40/40
- Health: OK=24, STALE=0, MISSING=0, ERROR=0
- Execution audit: passed=True issues=0 warnings=1 expected read-only Alpaca warning
- Focused tests: 28 passed
- EOD summary remains green.
