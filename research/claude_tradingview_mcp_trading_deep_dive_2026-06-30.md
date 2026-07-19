# Claude TradingView MCP Trading Repo Deep Dive - 2026-06-30

Repo: `https://github.com/jackson-video-resources/claude-tradingview-mcp-trading`

Purpose: evaluate Tom Dörr's linked repo for whether it can improve Vibe-Trading.

## Sources Checked

- GitHub repo metadata through GitHub API.
- Local clone: `research/external_repos/claude-tradingview-mcp-trading`
- Files inspected:
  - `README.md`
  - `.env.example`
  - `package.json`
  - `bot.js`
  - `rules.json`
  - `prompts/01-extract-strategy.md`
  - `prompts/02-one-shot-trade.md`
  - `docs/setup-windows.md`
  - `docs/exchanges/bitget.md`
- GitHub issues through API.
- `npm audit --json`.

## Repo Facts

- Description: "Connect Claude Code to TradingView and execute trades automatically via BitGet"
- Created: 2026-04-07
- Last pushed: 2026-05-15
- Stars at research time: 543
- Forks at research time: 285
- Open issues: 5
- GitHub API license: `null`
- No top-level `LICENSE` file observed in clone.
- Dependencies:
  - `dotenv`
  - `node-fetch`
- `npm audit` found 0 known vulnerabilities.

## What It Actually Is

This is not primarily a TradingView MCP server. It assumes a TradingView MCP exists from another repo/video.

The actual bot:

- Is a Node.js script in `bot.js`.
- Fetches crypto candle data from Binance public API in cloud mode.
- Calculates EMA(8), VWAP, and RSI(3).
- Evaluates a hardcoded safety check around those indicators.
- Places BitGet market orders if all conditions pass and `PAPER_TRADING=false`.
- Logs decisions to `safety-check-log.json`.
- Logs CSV rows to `trades.csv`.

Default strategy in `rules.json`:

- BTCUSDT
- 1m timeframe
- VWAP + RSI(3) + EMA(8) scalping
- Long when price > VWAP, price > EMA(8), RSI(3) < 30
- Short when price < VWAP, price < EMA(8), RSI(3) > 70
- Exit rules are described textually but not actually enforced by the code.

## Major Problems

### 1. Bearish/short logic can execute as BUY

`bot.js` checks bearish short conditions in `runSafetyCheck`, but the execution path always calls:

```js
placeBitGetOrder(CONFIG.symbol, "buy", tradeSize, price)
```

The CSV logger also writes `side = "BUY"` for all paper/live passing trades.

Impact:

- If bearish conditions pass, the bot still buys.
- This is a critical execution-direction bug.
- Disqualifies the repo as an execution template.

### 2. Stop-loss and take-profit rules are text only

`rules.json` says:

- hard stop 0.3%,
- take profit at VWAP touch or EMA cross,
- exit on RSI cross.

But `bot.js` only places a market entry order. It does not place:

- stop-loss order,
- take-profit order,
- bracket/OCO order,
- exit monitor.

Impact:

- Real risk can exceed the strategy's claimed risk.
- "Safety check" covers entry only, not lifecycle management.

### 3. It does not really parse arbitrary `rules.json`

README says safety checks come directly from `rules.json`, but code is hardcoded to:

- EMA(8),
- VWAP,
- RSI(3),
- 1.5% VWAP distance.

Changing `rules.json` text does not automatically change the actual logic.

Impact:

- The repo overstates strategy flexibility.
- YouTube transcript extraction can produce convincing rules that the bot does not actually execute.

### 4. Cloud mode bypasses TradingView

README says Claude reads TradingView chart context, but `bot.js` cloud mode pulls Binance candles directly.

Impact:

- It is not a reliable "TradingView live chart automation" implementation.
- It is a Binance-data crypto bot with BitGet execution.

### 5. Risk controls are too thin

Present:

- Max trade size.
- Max trades per day.
- Paper/live env flag.
- Decision log.

Missing versus Vibe-Trading:

- Portfolio kill switch.
- Daily realized/unrealized loss gate.
- Broker position sync.
- Duplicate exposure guard.
- Manual reset file.
- Stale price guard.
- Slippage/spread check.
- Signal confidence normalization.
- Multi-leg/spread lifecycle.
- Drawdown halt.
- Exit monitor.
- Discord guard block dashboard.

### 6. License ambiguity

GitHub API returned no license, and no top-level license file was present.

Policy:

- Study only.
- Do not copy code into Vibe-Trading.

## What Is Useful

### 1. Good onboarding pattern

The one-shot prompt and docs are good at walking a user through:

- API key setup,
- paper/live mode,
- cron scheduling,
- TradingView CDP setup,
- trade logging.

Useful concept:

- We could improve our own README/onboarding docs with a clearer "daily operator checklist" and "how to safely enable/disable execution" flow.

### 2. CSV/accounting log idea

The repo logs every decision/trade to CSV for tax/accounting review.

We already have richer JSONL logs, but a daily CSV/export view could help Kenny read results faster.

Useful build:

- `scripts/export_daily_bot_activity_csv.py`
- Pull guard blocks, trades, shadow signals, and context-only scans into one daily CSV.

### 3. YouTube strategy extraction prompt

The extraction prompt is conceptually aligned with our Pine strategy lab intake:

- identify indicators,
- entry rules,
- avoid-trade conditions,
- risk management,
- timeframe,
- ambiguity.

Our version should be stricter:

- require repaint/lookahead check,
- require Python port,
- require OOS/WF/PBO,
- require forward shadow logging.

### 4. TradingView CDP launch docs

Windows setup docs match the general pattern we already use:

- launch TradingView Desktop with `--remote-debugging-port=9222`.
- verify `tv_health_check`.

This reinforces our existing TradingView MCP setup, but does not replace it.

## Verdict

Do not use this repo for live or paper execution.

Reasons:

- Crypto/BitGet oriented, not Alpaca equities/options.
- Critical buy/short direction bug.
- No real exit/stop order handling.
- Hardcoded strategy despite flexible-rule claims.
- Thin guardrails.
- License ambiguity.

The repo is useful only as a product/onboarding reference and as a reminder to strengthen our own strategy-intake process.

## Recommended Build Queue

P0 - No execution changes.

- Do not connect this repo to any account.
- Do not port its BitGet executor.
- Do not run its one-shot prompt against our live environment.

P1 - Add a formal social/video strategy intake template.

- Path: `research/social_strategy_intake/youtube_strategy_intake_template.md`
- Fields:
  - source URL,
  - trader/channel,
  - market/timeframe,
  - indicators,
  - entry/exit/stop rules,
  - avoid-trade rules,
  - ambiguous points,
  - Pine status,
  - Python port status,
  - repaint/lookahead scan,
  - OOS/WF/PBO status,
  - forward-test status.

P1 - Add daily bot activity CSV export.

- Path: `scripts/export_daily_bot_activity_csv.py`
- Purpose: human-readable EOD ledger.
- Pull from:
  - Alpaca trade logs,
  - guard-block JSONL,
  - shadow logger JSONL,
  - social trend logs,
  - Limitless/Kalshi context logs.

P2 - TradingView MCP validation only.

- Keep our existing TradingView MCP for:
  - chart screenshots,
  - strategy tester reads,
  - Pine compile loops,
  - visual validation.
- Do not let TradingView MCP place orders.

## Bottom Line

This is not a better version of our bot. It is a simple crypto bot wrapped in a strong demo/onboarding narrative.

Vibe-Trading is materially safer:

- Alpaca broker sync.
- execution guard.
- portfolio kill switch.
- scheduled shadow stack.
- IVR/GEX/context scanners.
- paper-first rules.
- confidence gates.

Steal the documentation pattern. Do not steal the execution architecture.
