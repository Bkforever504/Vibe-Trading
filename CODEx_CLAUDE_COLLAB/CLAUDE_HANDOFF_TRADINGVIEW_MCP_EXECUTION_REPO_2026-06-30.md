# Claude Handoff - TradingView MCP Execution Repo - 2026-06-30

Project: `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading`

Kenny asked Codex to investigate Tom Dörr's linked repo:

- X post: `https://x.com/tom_doerr/status/2068272167788109839`
- Repo: `https://github.com/jackson-video-resources/claude-tradingview-mcp-trading`

Full report:

- `research/claude_tradingview_mcp_trading_deep_dive_2026-06-30.md`

Local reference clone:

- `research/external_repos/claude-tradingview-mcp-trading`

## Verdict

Do not use this repo for execution.

It is useful as an onboarding/docs reference only.

## Critical Findings

Repo facts:

- Created: 2026-04-07
- Last pushed: 2026-05-15
- Stars: 543
- Forks: 285
- Open issues: 5
- GitHub API license: `null`
- No top-level `LICENSE` observed.
- `npm audit` showed 0 known dependency vulnerabilities.

Architecture:

- One Node bot: `bot.js`.
- Uses Binance public candles in cloud mode.
- Executes via BitGet.
- Default strategy: BTCUSDT 1m VWAP + RSI(3) + EMA(8) scalper.
- Depends on a separate TradingView MCP setup; this repo is not the MCP server.

Critical bug:

- `runSafetyCheck()` can pass bearish/short conditions.
- But execution always calls `placeBitGetOrder(CONFIG.symbol, "buy", tradeSize, price)`.
- CSV logger also always writes side `BUY` for paper/live passing trades.
- So a valid bearish setup can still execute a BUY.

Other disqualifiers:

- `rules.json` exit/stop/take-profit rules are text only; no stop/TP/OCO/bracket order is placed.
- Strategy logic is hardcoded to EMA(8), VWAP, RSI(3), and 1.5% VWAP distance despite README saying rules come from `rules.json`.
- Cloud mode bypasses TradingView and uses Binance data.
- Risk controls are thin: max trade size and max daily trade count only.
- No portfolio kill switch, broker sync, duplicate exposure guard, stale price guard, drawdown halt, manual reset, or exit monitor.

## What Might Help Us

P1 useful idea:

- Add formal YouTube/social strategy intake template:
  - `research/social_strategy_intake/youtube_strategy_intake_template.md`
  - should feed our Pine strategy lab, not execution.
  - must include ambiguity, repaint/lookahead, Python port, OOS/WF/PBO, and forward-test status.

P1 useful idea:

- Add daily bot activity CSV export:
  - `scripts/export_daily_bot_activity_csv.py`
  - one human-readable ledger from guard blocks, trades, shadow signals, social trends, Kalshi/Limitless context.

P2:

- Keep TradingView MCP for compile/chart/tester validation only.
- No order routing from TradingView MCP.

## Instructions

If Kenny asks whether to install or run this:

- Answer no for execution.
- It can remain cloned under `research/external_repos/` as reference.
- Do not wire BitGet or crypto exchange API keys.
- Do not run the one-shot prompt against the Vibe-Trading environment.

Our existing Vibe-Trading stack is materially safer and should remain source of truth for tomorrow.
