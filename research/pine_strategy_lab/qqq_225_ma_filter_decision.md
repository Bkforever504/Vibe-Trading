# QQQ 225-Day MA Filter Decision

Date: 2026-06-28
Intake ID: `intake-001`
Source: QuantifiedStrategies swing-trading strategy idea

## Verdict

Rejected for now. Do not build a shadow logger.

## What Was Tested

Codex ported the rule to:

`research/pine_strategy_lab/examples/qqq_225_ma_filter_python.py`

Rule:

- Hold long when daily close is above SMA.
- Exit to cash when daily close is below SMA.

Parameter grid:

- SMA 200
- SMA 225
- SMA 250

Sweep:

```powershell
uv run --no-project --with yfinance --with pandas --with numpy python scripts\strategy_sweep_runner.py --strategy research\pine_strategy_lab\examples\qqq_225_ma_filter_python.py --symbols QQQ,SPY --ranges 2015-01-01:2024-12-31 2018-01-01:2024-12-31 --out research\pine_strategy_lab\qqq_225_ma_filter_sweep_report.md
```

## Result

Report:

`research/pine_strategy_lab/qqq_225_ma_filter_sweep_report.md`

Best row:

- Symbol: SPY
- Window: 2015-2024
- SMA: 200
- Confidence: 6.5
- PF: 3.75
- OOS PF: 9.52
- WF: 0.60
- Trades: 23
- Max DD: 17.7%

Exact intake idea:

- Symbol: QQQ
- Window: 2015-2024
- SMA: 225
- Confidence: 5.0
- PF: 3.50
- OOS PF: 99.00
- WF: 0.60
- Trades: 21
- Max DD: 24.3%

## Rejection Reasons

- PBO score was 0.67, above the 0.60 overfit gate.
- Exact QQQ 225-day version had only 21 trades over 2015-2024, below the 30-trade gate.
- Several rows showed OOS PF 99.00, meaning a no-loss OOS slice rather than robust evidence.
- This is not materially stronger than existing KAMA/momentum trend candidates already shadow logging.

## Next Action

Park. Revisit only if a materially different rule set raises trade count and lowers PBO without suspicious OOS artifacts.
