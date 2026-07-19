# Codex Handoff — Breadth Uptrend Scanner + Exposure Coach

Project: `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading`
Date: 2026-06-30

## What Shipped

Built the next two intelligence layers from the tradermonty-style market regime queue:

1. `scripts/market_breadth_uptrend_scanner.py`
   - Read-only market breadth/uptrend scanner.
   - Uses shared `scripts.market_data.fetch_close()` so Alpaca is primary and yfinance remains fallback.
   - Measures:
     - percent above 20/50/200 DMA
     - daily advancer percentage
     - leadership above 50DMA
     - defensive rotation using XLU/XLP/GLD/TLT
   - Writes:
     - `data/market_breadth_uptrend_log.jsonl`
     - `~/.vibe-trading/reports/market-breadth-uptrend.json`
   - Important fix: lookback is 420 calendar days, not 260, because Alpaca returned only 178 trading bars with 260 calendar days and that was insufficient for 200DMA.

2. `scripts/exposure_coach.py`
   - Read-only advisory posture generator.
   - Combines:
     - Market Force Score
     - Market Breadth/Uptrend
     - Distribution Day regime
   - Outputs posture only:
     - `aggressive`
     - `normal`
     - `cautious`
     - `cash_priority`
   - Writes:
     - `data/exposure_coach_log.jsonl`
     - `~/.vibe-trading/reports/exposure-coach.json`
   - Does **not** change bot settings or place orders.

3. Runner scripts:
   - `scripts/run_market_breadth_uptrend_scanner.ps1`
   - `scripts/run_exposure_coach.ps1`

4. Integrated into:
   - `scripts/market_force_score.py`
     - New `breadth_force()`
     - Total force stack is now 7 forces.
   - `scripts/signal_stack_health_report.py`
   - `scripts/signal_stack_leaderboard.py`
   - `scripts/export_daily_bot_activity_csv.py`

5. Tests:
   - `agent/tests/test_market_breadth_uptrend_scanner.py`
   - `agent/tests/test_exposure_coach.py`
   - Updated `agent/tests/test_market_force_score.py`

## Scheduled Tasks

Created/updated:

- `\VibeTrade\MarketBreadthUptrendScanner`
  - Weekdays at 15:31 CT
  - Runs before Distribution Day Scanner and Market Force Score.

- `\VibeTrade\ExposureCoach`
  - Weekdays at 15:45 CT
  - Runs after Market Force Score.

Creation command succeeded and showed:

- `MarketBreadthUptrendScanner` next run: 2026-06-30 15:31 CT
- `ExposureCoach` next run: 2026-06-30 15:45 CT

## Verification

Focused tests:

```powershell
uv run --no-project --with pytest --with pandas --with numpy python -m pytest agent\tests\test_market_breadth_uptrend_scanner.py agent\tests\test_exposure_coach.py agent\tests\test_market_force_score.py agent\tests\test_signal_stack_health_report.py agent\tests\test_signal_stack_leaderboard.py agent\tests\test_export_daily_bot_activity_csv.py -q
```

Result:

```text
23 passed
```

Compile check:

```powershell
uv run --no-project python -m py_compile scripts\market_breadth_uptrend_scanner.py scripts\exposure_coach.py scripts\market_force_score.py scripts\signal_stack_health_report.py scripts\signal_stack_leaderboard.py scripts\export_daily_bot_activity_csv.py
```

Result: passed.

## Live Smoke Results For 2026-06-30

Breadth scanner:

```text
status=uptrend_under_pressure
force=-0.25
above50=55.88
above200=70.59
adv=67.65
leadership=3
defensive=3
source=alpaca
```

Market Force after adding breadth:

```text
classification=mixed
score=0.75
confidence=6.75
coverage=6/7
trend          +2.0
levels_gex      0.0
momentum        missing
volatility      0.0
narrative      +1.0
institutional  -2.0
breadth        -0.25
```

Exposure Coach:

```text
posture=cautious
score=-0.75
risk_mult=0.5
reasons:
- Market Force mixed score=0.75
- breadth uptrend under pressure
- severe distribution pressure
```

This is advisory only. No settings changed. No orders placed.

## Health Report

`scripts/signal_stack_health_report.py` now sees Breadth and Exposure Coach.

Current health summary after manual smoke:

```text
OK=10
STALE=0
MISSING=3
ERROR=0
```

Missing rows are expected before 15:20 CT:

- TTM Squeeze
- WaveTrend
- SMC

Daily CSV export for 2026-06-30:

```text
events=36
CSV: ~/.vibe-trading/reports/daily-bot-activity-2026-06-30.csv
```

## Interpretation

This layer improves daily precision without changing execution:

- Distribution scanner says institutions are selling.
- Breadth says uptrend is under pressure, not broken.
- Market Force now correctly downgrades to mixed.
- Exposure Coach says cautious.

That is the right behavior. The bots should not blindly get more aggressive just because one trade worked or pre-open narrative was bullish.

## Next Claude Tasks

1. Review the posture scoring after 5 trading days.
2. Confirm scheduled tasks run successfully at 15:31 and 15:45 CT.
3. After 30 days, compare Exposure Coach posture vs Flip/IWM daily outcomes:
   - Did `aggressive/normal` days produce better expectancy?
   - Did `cautious/cash_priority` days reduce drawdown?
4. Do not wire this into automatic risk sizing yet.

