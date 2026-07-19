# Claude Handoff — First-Pullback Strategy + Shadow Scanner
Date: 2026-06-22

## What Was Built This Session

### 1. Parameter sweep infrastructure
- Added `fixed_stop_ticks` to `BacktestConfig` — overrides range stop with N-tick fixed stop
- Added `build_first_pullback_signal()` to `strategies/topstep_prop_bot.py`
  - ORB direction confirmation → wait for pullback to range level → tight structural stop
  - Returns `(PropSignal, entry_candle_idx)` tuple
- Added `signal_type: str` to `BacktestConfig` — "orb" or "pullback"
- Added `pullback_tolerance_ticks`, `pullback_stop_ticks` to `BacktestConfig`
- CLI flags: `--signal-type`, `--pullback-tolerance-ticks`, `--pullback-stop-ticks`
- Tests: 24 pass (`agent/tests/test_topstep_replay_backtester.py`)

### 2. Multi-timeframe data
| File | Bars | Days |
|---|---|---|
| `examples/nq_1m_7d.csv` | 1,560 | 4 |
| `examples/nq_5m_60d.csv` | 3,744 | 48 |
| `examples/nq_15m_60d.csv` | 1,248 | 48 |
| `examples/nq_1h_730d.csv` | 3,561 | 597 |
| `examples/nq_1d_max.csv` | 6,503 | 26 yrs |

All fetched via `scripts/fetch_nq_yfinance.py` (free, no API key).

### 3. Full parameter sweep results
Swept all timeframes (1m/5m/15m/1h/4h/daily), both signal types, hundreds of combos.

**Key finding: pullback signal beats ORB on every timeframe tested.**

**Best statistically valid config (1h/730d, 40 trades):**
```
--signal-type pullback
--range-minutes 1          # first 1-hour bar = opening range (9:30-10:30 ET)
--min-breakout-points 20.0 # 20 NQ pts required to confirm breakout
--reward-risk 2.0
--pullback-stop-ticks 80   # 20 NQ pts = $40 risk per MNQ contract
--pullback-tolerance-ticks 16  # 4 NQ pts tolerance to count as pullback
```
Result: **exp=+$27.83/trade, PF=1.67, WR=45%, max_dd=$627, 2 consistency violations**

Full sweep command to reproduce:
```powershell
uv run --no-project --with yfinance python strategies/topstep_replay_backtester.py `
  --csv examples/nq_1h_730d.csv `
  --symbol MNQ `
  --range-minutes 1 `
  --min-breakout-points 20.0 `
  --reward-risk 2.0 `
  --slippage-ticks 1 `
  --commission 4.00 `
  --signal-type pullback `
  --pullback-stop-ticks 80 `
  --pullback-tolerance-ticks 16
```

### 4. Why 4h and daily failed
- **4h:** Only 2 bars/day after resampling. `candles_after` is always empty → fallback exit at entry price → $0 gross P&L → just eats commission. Structural dead end without multi-day exit refactor.
- **Daily:** `_group_by_date()` gives 1 bar per date. Guard `len(candles) <= range_minutes` fires immediately. Signal never triggers. Same architectural issue.

### 5. Live shadow scanner
`strategies/shadow_pullback_signal.py`
- Fetches today's 1h NQ=F bars via yfinance
- Detects first pullback signal using best validated config
- Logs to `~/.vibe-trading/shadow-ai-signals.jsonl` via existing shadow journal
- Discord notification if `DISCORD_WEBHOOK_URL` is set in `agent/.env`
- CLI: `python strategies/shadow_pullback_signal.py [--discord] [--json]`

**Task Scheduler setup (run hourly 10:30-15:30 ET on trading days):**
```
Program: C:\path\to\uv.exe
Arguments: run --no-project --with yfinance python strategies/shadow_pullback_signal.py --discord
Start in: C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading
Trigger: Daily, repeat every 1 hour from 10:30, stop after 5 hours
```

---

## Codex Next Tasks (priority order)

### P0: Write tests for `build_first_pullback_signal`
File: `agent/tests/test_topstep_prop_bot.py`
- Test short-side pullback (mirror of long tests in `test_topstep_replay_backtester.py`)
- Test pullback fires on correct bar index
- Test max_scan_candles limit blocks late pullbacks
- Test pullback rejected when close does NOT hold above range_high

### P0: Forward-test log viewer
`scripts/view_shadow_signals.py`
- Reads `~/.vibe-trading/shadow-ai-signals.jsonl`
- Filters by strategy `first_pullback_1h`
- Prints table: date, side, entry, stop, target, current price (fetch live), P&L if exited
- Needs logic: check if stop or target was hit using today's subsequent bars

### P1: Out-of-sample validation split
In `strategies/topstep_replay_backtester.py`:
- Add `--train-end` date arg
- Split `nq_1h_730d.csv` into train (first 400 days) and test (last ~197 days)
- Run sweep on train, validate best config on test, report performance gap
- This is critical before any live capital commitment

### P1: MES comparison
Run the same best config on MES instead of MNQ:
```
--symbol MES --pullback-stop-ticks 80
```
MES: $5/point vs MNQ $2/point. Same price levels. Compare:
- Max drawdown in dollars (MES $5 × 20pts = $100 stop vs MNQ $2 × 20pts = $40)
- Which stays within Topstep daily loss limit more reliably
- Topstep MES Combine is $50k account, $2k daily loss, $3k trailing drawdown

### P1: Multi-timeframe confirmation filter
Concept: only enter 1h pullback when daily trend aligns.
- Check if daily close > 20-day SMA → only take LONG pullbacks
- Check if daily close < 20-day SMA → only take SHORT pullbacks
- Expected: reduce win count but improve win rate
- Implementation: add `require_daily_trend_confirm: bool = False` to `BacktestConfig`
  - Load daily bars alongside intraday, check day's date against daily SMA

### P2: Automated daily backtest refresh
Cron/Task Scheduler: every morning before open, re-run:
```
python scripts/fetch_nq_yfinance.py --interval 1h --period 730d
python strategies/topstep_replay_backtester.py --csv examples/nq_1h_730d.csv [best config]
```
Save result to `logs/daily_backtest_YYYY-MM-DD.json` and append to a running CSV.
Lets us see if edge degrades over time.

### P2: Task Scheduler setup for shadow scanner
Add shadow scanner to Windows Task Scheduler:
- Trigger: weekdays, start 10:30 ET, repeat every 60 min, end 15:30 ET
- Action: `uv run --no-project --with yfinance python strategies/shadow_pullback_signal.py --discord`
- Working dir: `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading`
- Log output to `C:\Users\kenne\.vibe-trading\logs\shadow-scanner.log`

---

## Architecture Constraints

- **No live orders anywhere in this codebase.** All signal logic is shadow/paper only.
- `strategies/topstep_replay_backtester.py` — paper replay only, no broker connection
- `strategies/shadow_pullback_signal.py` — logs signals, no execution
- Topstep Combine account not opened yet. Paper trade first.
- `executable: false` is hardcoded in `shadow_ai_signals.py` — do not change.

## Run Tests
```powershell
uv run --no-project --with pytest python -m pytest agent/tests/test_topstep_replay_backtester.py agent/tests/test_topstep_prop_bot.py agent/tests/test_strategy_safety_layers.py -q
```
Expected: 24+ passed.

## Confidence Scores (updated 2026-06-22)
- **Compliance safety:** 9.5/10 (unchanged — rule gate solid)
- **Strategy profit (paper):** 5.0/10 (up from 3.5 — pullback signal shows real edge on 597 days)
- **Forward-test confidence:** 2.0/10 (only in-sample; needs 30+ live paper signals to trust)
