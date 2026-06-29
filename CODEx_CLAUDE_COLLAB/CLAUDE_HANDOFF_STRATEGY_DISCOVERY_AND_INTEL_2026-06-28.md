# Claude Handoff - Strategy Discovery + Prediction Market Intelligence

Date: 2026-06-28
Project: `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading`

## Latest Codex Commit

`0efaa01` - `Add prediction market intelligence watchlists`

## What Codex Just Added

### 1. Polymarket Fed Whale Watch

File:
`strategies/polymarket_fed_whale_watch.py`

Wrapper:
`scripts/polymarket_fed_whale_watch_report.py`

Purpose:
Read-only intelligence layer for Polymarket Fed/rate markets.

What it does:
- Uses public Polymarket Gamma events and data-api trades.
- Scans active Fed/rate event slugs:
  - `how-many-fed-rate-cuts-in-2026`
  - `fed-emergency-rate-cut-before-2027`
  - `what-will-fed-rate-hit-before-2027`
  - legacy meeting slugs like `fed-decision-in-july`
- Filters public trades by whale notional.
- Default whale threshold: `$10,000`.
- Creates `paper_watch` consensus only when:
  - `3+` unique wallets agree
  - same market
  - same outcome
  - same side
  - combined notional >= `$250,000`

Safety:
- No private keys.
- No signatures.
- No orders.
- No copy execution.
- Read-only / paper-watch only.

Live run result:
- Scanned `34` active Fed/rate markets.
- Found `0` whale trades above `$10k`.
- Found `0` consensus signals.
- This is a valid quiet-feed result, not a failure.

Report:
`C:\Users\kenne\.vibe-trading\reports\polymarket-fed-whale-watch.json`

Run:
```powershell
uv run --no-project --with requests python scripts\polymarket_fed_whale_watch_report.py --print
```

### 2. Social Arbitrage Watchlist

File:
`strategies/social_arbitrage_watchlist.py`

Wrapper:
`scripts/social_arbitrage_watchlist_report.py`

Purpose:
Research-only layer for mapping viral social/product trends to public ticker watch ideas.

What it does:
- Reads public/manual observations from:
  `C:\Users\kenne\.vibe-trading\social-arb-observations.json`
- Reads keyword-to-ticker map from:
  `C:\Users\kenne\.vibe-trading\social-arb-keyword-map.json`
- Scores ideas by:
  - engagement
  - growth
  - cross-platform source count
  - keyword/ticker mapping
- Promotes only to `paper_watch`, never execution.

Default keyword map examples:
- `stanley cup` -> `SWK`
- `prime drink` -> `CELH`
- `nvidia ai` -> `NVDA`
- `ozempic` -> `LLY`
- `weight loss drug` -> `LLY`

Safety:
- No scraping private feeds.
- No broker orders.
- No automated execution.
- Requires cross-platform confirmation and price/volume confirmation before any paper trade.

Live run result:
- `0` observations loaded.
- `0` ideas.
- This is expected until observations are added.

Report:
`C:\Users\kenne\.vibe-trading\reports\social-arbitrage-watchlist.json`

Run:
```powershell
uv run --no-project python scripts\social_arbitrage_watchlist_report.py --print
```

### 3. Dashboard Integration

File:
`strategies/trading_dashboard.py`

Dashboard now includes:
- Fed Whale Watch panel
- Social Arbitrage Watchlist panel
- Bot status rows for both

Both show as blocked/read-only:
- Fed Whale Watch: `watch-only`
- Social Arbitrage Watchlist: `research-only`

Regenerated dashboard:
`C:\Users\kenne\.vibe-trading\reports\trading-dashboard.html`

### 4. Tests

Added:
- `agent/tests/test_polymarket_fed_whale_watch.py`
- `agent/tests/test_social_arbitrage_watchlist.py`
- dashboard coverage in `agent/tests/test_trading_dashboard.py`

Verification:
```powershell
uv run --no-project --with pytest --with requests --with python-dotenv python -m pytest agent\tests\test_polymarket_fed_whale_watch.py agent\tests\test_social_arbitrage_watchlist.py agent\tests\test_polymarket_wallet_tracker.py agent\tests\test_copy_trader_watchlist.py agent\tests\test_trading_dashboard.py -q
```

Result:
`38 passed`

## User's New Request

Kenny wants to use the Axel Bitblaze / TradingView MCP style workflow:

> Find clear strategies from YouTube/X/Reddit/TikTok/top traders, convert them into backtestable Pine Script or Python, run the tests fast, reject weak ones, and only promote real survivors.

This should become a structured strategy discovery factory.

## Current Local Capabilities

Already present:
- `tools/tradingview-mcp`
- `scripts/tradingview_validation_report.py`
- Pine Strategy Lab
- Pine source scanner
- Pine red-flag scanner
- Backtest runner
- Sweep runner
- PBO overfit gate
- OOS / walk-forward gates
- Repaint/lookahead warnings
- Shadow loggers for real survivors:
  - Momentum rotation
  - RSI-2 QQQ
  - KAMA QQQ

Important existing conclusion:
- Trustdan strategies are parked.
- Alt10 and Alt45 failed to reproduce on daily yfinance bars.
- Do not keep brute-forcing trustdan unless TradingView-equivalent data is easy to source.

## What Claude Should Do Next

### P0 - Build Strategy Intake Queue

Create a durable JSON/Markdown intake system for social/video strategies.

Suggested files:
- `research/strategy_intake/strategy_queue.json`
- `research/strategy_intake/README.md`
- optional CLI: `scripts/strategy_intake_report.py`

Schema should include:
- `id`
- `source_platform`
- `source_url`
- `trader`
- `strategy_name`
- `market`
- `timeframe`
- `entry_rules`
- `stop_loss_rules`
- `take_profit_rules`
- `exit_rules`
- `position_sizing`
- `session_rules`
- `ambiguities`
- `license_or_permission_notes`
- `pine_status`
- `python_status`
- `backtest_status`
- `decision`
- `rejection_reasons`
- `next_action`

Goal:
Turn viral/social strategies into testable candidates, not bot integrations.

### P1 - Research Top Strategy Sources

Use broad research, including last30days if available, to find strategy sources that are:
- rule-clear
- repeatable
- market/timeframe explicit
- not pure discretion
- not repainting indicator dependent
- not "green P&L screenshot only"

Targets:
- YouTube traders with exact rule explanations
- X traders posting full rules
- Reddit systematic strategy writeups
- GitHub Pine/Python strategy repos
- TradingView public open-source strategies where license allows analysis

Rank by:
1. Rule clarity
2. Reproducibility
3. Market fit for our stack
4. Non-repainting likelihood
5. Ease of Python/Pine translation
6. Potential orthogonality to current candidates

### P1 - Add Strategy Conversion Checklist

Every intake item needs ambiguity flags:
- What exactly triggers entry?
- What counts as setup invalidation?
- Does it use current candle close or intrabar values?
- Does it use higher timeframe data?
- If yes, is it offset by at least one completed bar?
- Stop placement?
- Target placement?
- Gap behavior?
- Session/time filter?
- Commission/slippage assumptions?
- Minimum trade count?

### P1 - Use TradingView MCP Carefully

TradingView MCP can help compile/test Pine and inspect charts, but do not trust green P&L.

Verification standard:
- Compile Pine.
- Visual chart inspection: do entries match the stated rules?
- Test 3-5 tickers and/or regimes.
- Export/record Strategy Tester metrics.
- Run our Python backtest if feasible.
- Reject if:
  - low trades
  - unstable OOS
  - high PBO
  - high drawdown
  - suspicious no-loss OOS
  - repaint/lookahead flags

### P2 - Connect New Ideas to Existing Gates

Any strategy that survives intake should go through:
1. Pine red-flag scanner
2. Python translation if feasible
3. `pine_backtest_runner.py`
4. sweep runner where relevant
5. candidate report
6. shadow logger only if candidate passes

No execution wiring until:
- 30+ forward-test days
- 10+ real entry signals
- confidence near 9/10
- risk guard compatibility

## Codex Assessment

The YouTube/social strategy workflow is useful as a fast rejection engine.
It should not be treated as a shortcut to live capital.

Best framing:
Social media is the idea source.
Pine/TradingView is the visual sanity checker.
Python backtesting is the statistical gate.
Shadow logging is the live evidence gate.
Execution is the last step, not the default step.

## Suggested First Research Targets

Prioritize:
- strategies with exact rules in the video/post
- measured move / trend continuation approaches
- RSI/mean-reversion systems with clear thresholds
- VWAP/EMA pullback systems with exact invalidation
- ORB systems with session/time rules
- FOMC / macro event systems with fixed timing

Avoid or de-prioritize:
- vague ICT/SMC content without objective rules
- screenshot-only "insane PF" posts
- strategies relying on protected indicators without visible rule output
- liquidation/whale claims without reproducible data
- repaint-heavy pivot/HTF scripts without offset

## Reminder

Current best validated candidates remain:
- Momentum rotation top-2 weekly
- RSI-2 QQQ mean reversion
- KAMA QQQ trend

Everything new should compete against those under the same gates.
