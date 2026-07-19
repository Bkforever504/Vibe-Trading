# Shadow Scanner Verification - 2026-06-22

## What Claude Built

Claude updated `strategies/shadow_pullback_signal.py` to match the best forward-test candidate:

- `PULLBACK_TOL_TICKS = 8`
- `PULLBACK_STOP_TICKS = 80`
- Opening gap bias enabled
- `fetch_today_1h()` returns `(candles, prior_close)`
- Prior close extracted from the same 5-day yfinance fetch
- Gap-bias states:
  - `gap_bias_no_direction`
  - `gap_bias_blocked_{signal.side}_vs_{gap_side}`

## Codex Fixes

Codex reviewed and adjusted:

- Scanner now uses `datetime.now(ET).date()` instead of local `date.today()`.
- Scanner status now always includes:
  - `prior_close`
  - `gap_side`
  - `gap_pct`
- Signal journal context now includes:
  - `prior_close`
  - `gap_side`
  - `gap_pct`
- Task Scheduler script now schedules for Kenny's Central-time machine:
  - `9:30AM` local Central start
  - repeats hourly for 5 hours
  - corresponds to `10:30-15:30 ET`

## Verification

Tests:

```powershell
uv run --no-project --with pytest python -m pytest agent/tests/test_topstep_replay_backtester.py agent/tests/test_topstep_prop_bot.py agent/tests/test_strategy_safety_layers.py -q
```

Result:

```text
54 passed
```

Python compile:

```powershell
python -m py_compile strategies\shadow_pullback_signal.py scripts\view_shadow_signals.py scripts\sweep_train.py scripts\sweep_5m.py strategies\topstep_replay_backtester.py strategies\topstep_prop_bot.py
```

Result: clean.

PowerShell syntax:

```powershell
[System.Management.Automation.Language.Parser]::ParseFile('scripts\setup_task_scheduler.ps1',[ref]$tokens,[ref]$errors)
```

Result:

```text
PowerShell syntax OK
```

Scanner dry run:

```powershell
uv run --no-project --with yfinance python strategies\shadow_pullback_signal.py --json
```

Result:

```json
{
  "date": "2026-06-22",
  "symbol": "MNQ",
  "bars_fetched": 6,
  "prior_close": 30693.5,
  "signal": null,
  "state": "no_breakout",
  "gap_side": "buy",
  "gap_pct": 0.007908840634010459
}
```

## Activation

Run PowerShell as Administrator:

```powershell
cd C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading
.\scripts\setup_task_scheduler.ps1
```

Test immediately:

```powershell
Start-ScheduledTask -TaskName "VibeTradingShadowScanner"
Get-Content "C:\Users\kenne\.vibe-trading\logs\shadow-scanner.log" -Tail 20
```

View signals:

```powershell
uv run --no-project --with yfinance python scripts\view_shadow_signals.py --strategy first_pullback_1h
```

## Gate

No Topstep spend until:

- 30+ forward signals logged
- Viewer/outcome tracking shows positive expectancy
- Consistency violations remain manageable
