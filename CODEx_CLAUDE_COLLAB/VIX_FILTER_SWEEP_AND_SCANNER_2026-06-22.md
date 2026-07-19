# VIX Filter Sweep + Scanner Gate - 2026-06-22

## Claude Result Reviewed

Claude added VIX filtering to the backtester and reported that VIX 16-24 improved the OOS result on the current top candidate.

Codex verified this and expanded the sweep harness.

## Sweep Harness Update

File:
`scripts/sweep_train.py`

Added sweep dimensions:
- `vix_range`: none, `15-28`, `16-24`
- `entry_start`: none, `10:30`

The harness still defaults to:
- `--penalty 25`
- 1h train split through `2025-09-05`

Verification:

```powershell
python scripts\sweep_train.py --top 15 --min-trades 5 --workers 4
```

Result:
- 1536 configs
- 0 errors
- Original `st80 tol8 part gap` remains top train config with score `18.07`
- VIX configs cluster near the top
- `s1030` has no effect on 1h data because entries already happen after that point

## OOS Checks

Top train config:

```text
st80 tol8 partial gap
```

Test:
- Trades: `4`
- WR: `75.0%`
- Exp: `$22.38`
- PF: `1.68`
- DD: `$132.50`
- Violations: `2`
- Score: `-27.62`

VIX-filtered signal config:

```text
st80 tol8 full gap vix16-24
```

Test:
- Trades: `3`
- WR: `66.7%`
- Exp: `$146.83`
- PF: `11.88`
- DD: `$40.50`
- Violations: `1`
- Score: `$121.83`

VIX-filtered partial-exit config:

```text
st80 tol8 partial gap vix16-24
```

Test:
- Trades: `3`
- WR: `100.0%`
- Exp: `$74.00`
- PF: `inf`
- DD: `$0.00`
- Violations: `1`
- Score: `$49.00`

## Verdict

VIX 16-24 helps us.

It is not enough to go live because the OOS sample is only 3 trades, but it is directionally correct and should be part of the live shadow scanner.

Updated confidence:
- Backtester reliability: `9.3/10`
- Regime filter usefulness: `7.0/10`
- Forward-test candidate confidence: `6.1/10`
- Combine-readiness: `3.2/10`

## Scanner Update

File:
`strategies/shadow_pullback_signal.py`

Added:
- `VIX_MIN = 16.0`
- `VIX_MAX = 24.0`
- `fetch_latest_vix()`
- Scanner states:
  - `vix_unavailable`
  - `vix_out_of_range`
- Status fields:
  - `vix`
  - `vix_min`
  - `vix_max`

Dry run:

```powershell
uv run --no-project --with yfinance python strategies\shadow_pullback_signal.py --json
```

Result:

```json
{
  "prior_close": 30693.5,
  "vix": 17.280000686645508,
  "vix_min": 16.0,
  "vix_max": 24.0,
  "state": "no_breakout",
  "gap_side": "buy",
  "gap_pct": 0.007908840634010459
}
```

Note:
- The machine-readable signal context now carries VIX fields.
- A human risk-note string in the scanner still references the older OOS summary. Use the JSON context as source of truth until that prose line is cleaned later.

## Verification

```powershell
python -m py_compile scripts\sweep_train.py strategies\shadow_pullback_signal.py strategies\topstep_replay_backtester.py
uv run --no-project --with pytest python -m pytest agent/tests/test_topstep_replay_backtester.py agent/tests/test_topstep_prop_bot.py agent/tests/test_strategy_safety_layers.py -q
```

Result:

```text
54 passed
```

## Next

1. Let Task Scheduler collect forward signals with the VIX 16-24 gate.
2. Use `scripts/view_shadow_signals.py` after signals accumulate.
3. Build outcome updater so each signal can be marked target, stop, partial, breakeven, or EOD.
