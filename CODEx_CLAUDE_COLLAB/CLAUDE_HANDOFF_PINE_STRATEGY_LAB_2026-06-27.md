# Claude Handoff - Pine Strategy Lab

Project:

```text
C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading
```

## Why This Exists

Kenny asked whether we can do the useful part of the MoonDev / TradingView Pine strategy idea:

```text
Find open-source Pine strategies, convert useful logic to Python, backtest quickly, and feed only robust candidates into the bots.
```

Important:

Do **not** chase the tweet's "two million percent return" framing. Treat that as a red flag for overfit, lookahead/repainting, impossible fills, no slippage, no commissions, tiny sample size, or distorted compounding.

The safe implementation is now a research filter:

```text
Pine idea -> honest metrics manifest -> candidate report -> paper-forward queue only
```

## What Codex Built

New files:

```text
research/__init__.py
research/pine_strategy_lab.py
research/pine_strategy_lab/README.md
research/pine_strategy_lab/example_manifest.json
research/pine_strategy_lab/examples/vwap_candidate.pine
research/pine_strategy_lab/candidate_report.md
scripts/pine_strategy_lab_report.py
test_pine_strategy_lab.py
```

Core capabilities:

- Parses Pine metadata:
  - strategy name
  - license
  - source URL
  - indicator tags such as EMA, VWAP, RSI, ORB, ATR, MACD
- Flags open-source eligibility.
- Scores candidate metrics.
- Rejects suspicious/hype backtests.
- Writes a ranked Markdown candidate report.
- CLI runner:

```powershell
uv run --no-project python scripts\pine_strategy_lab_report.py --manifest research\pine_strategy_lab\example_manifest.json --out research\pine_strategy_lab\candidate_report.md
```

Tests:

```powershell
uv run --no-project --with pytest python -m pytest test_pine_strategy_lab.py -q
```

Result:

```text
5 passed
```

## Current Rejection Gates

Rejects candidates when:

- license is unknown or non-open-source
- trade count < 30
- profit factor > 10
- max drawdown > 25%
- out-of-sample profit factor < 1.15
- walk-forward pass rate < 0.60

Status values:

```text
rejected
paper_candidate
```

`paper_candidate` means shadow/paper-forward testing only. It does not mean live trading.

## Current Example Output

Generated report:

```text
research/pine_strategy_lab/candidate_report.md
```

Example candidate:

```text
VWAP Pullback Candidate | paper_candidate | confidence 8.5
```

This is only a fixture proving the pipeline works, not a real strategy endorsement.

## Next Best Tasks

### P0 - Connect To Existing Backtest Infrastructure

Create an adapter that can take a translated Python strategy and run it against existing backtest data:

- SPY / QQQ / IWM for flip bot filters
- NQ/MNQ examples for shadow scanner research
- BTC/ETH later only if we add crypto execution safely

Use realistic assumptions:

- slippage
- commissions
- no same-bar impossible fills
- no lookahead
- out-of-sample split
- walk-forward validation

### P0 - Add Reject-Reason Report For Moonshot Strategies

Create examples that intentionally fail:

- too few trades
- suspicious profit factor
- weak OOS
- high drawdown
- unknown license

Goal: make the report emotionally useful for Kenny. It should kill viral screenshot temptation fast.

### P1 - Pine-To-Python Translation Queue

Do not try to fully auto-convert all Pine yet. Start with a translation queue:

```text
source Pine file
strategy family
manual translation status
target bot
known repaint/lookahead risks
Python module path
```

Potential strategy families:

- VWAP reclaim/fail
- EMA trend day
- ORB breakout and retest
- pullback to 9/20/50 EMA
- RSI mean reversion
- ATR trailing stop

### P1 - Bot Integration Rule

No Pine-derived strategy should enter `flip_bot.py` or `shadow_pullback_signal.py` directly.

Route:

```text
pine_strategy_lab report
-> shadow/paper module
-> 30+ forward-test signals
-> confidence score near 9/10
-> only then execution candidate
```

### P2 - Research Sources

Look for legal/open-source Pine strategy repos and scripts only.

Do not scrape private TradingView code, paid scripts, invite-only scripts, or anything with unclear license.

Suggested search targets:

- GitHub open-source Pine strategies
- TradingView scripts with explicit open-source license
- strategy families that match our existing bot research: VWAP, EMA, ORB, pullbacks, trend days

## Safety Position

Kenny wants profitable bots, but the operating principle still stands:

```text
Do not rush to live capital.
Every strategy needs paper validation, forward-test results, rule compliance, and high confidence before real money.
```

This lab helps us move faster without turning hype into live risk.

## Codex Update - 2026-06-28

P0 trade-level metrics are now implemented in:

```text
research/pine_strategy_lab_backtest.py
research/pine_strategy_lab.py
test_pine_strategy_lab.py
research/pine_strategy_lab/README.md
```

What changed:

- `_equity_curve()` now fills the first position diff, so the first trade is no longer lost to a NaN equity point.
- `_completed_trade_returns()` parses completed trades from the shifted position series.
- Profit factor now uses completed-trade P&L instead of bar-level equity returns.
- OOS profit factor and walk-forward pass/fail now use the same completed-trade P&L definition.
- `BacktestMetrics` now includes:
  - `avg_win_pct`
  - `avg_loss_pct`
  - `expectancy_pct`
  - `max_consecutive_losses`
  - `time_in_market_pct`

Verification:

```powershell
uv run --no-project --with pytest --with pandas --with yfinance python -m pytest test_pine_strategy_lab.py -q
```

Result:

```text
17 passed
```

Remaining Pine Strategy Lab queue:

1. Strategy sweep runner across SPY/QQQ/IWM x date ranges x parameter grids.
2. PyneCore evaluation against one simple Pine strategy before integrating.
3. Add a translation queue CSV/JSON for source Pine -> reviewed Python module -> target bot.
