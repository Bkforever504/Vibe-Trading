# MoonDev Social Deep Dive - 2026-06-30

Purpose: evaluate MoonDevOnYT's recent social posts and public repos for ideas that can improve Vibe-Trading without weakening the existing paper-first, guard-first operating model.

## Research Coverage

Sources checked:
- Logged-in Chrome read of Moon Dev X profile and X search results for `from:MoonDevOnYT` with keywords: whale, prediction markets, liquidation, TradingView, pine script, TikTok, social arbitrage.
- Public GitHub API for `moondevonyt` repos.
- Public repo READMEs and selected example scripts.
- Live endpoint sanity checks for Limitless public markets and Hyperliquid public metadata.
- last30days engine attempted with a MoonDev query plan, but X returned HTTP 403 and only low-signal Reddit results came back.

## High-Signal MoonDev Themes

### 1. Prediction market whale and contract indexing

Representative X posts:
- `https://x.com/MoonDevOnYT/status/2071292547134054729` - whale wallet dashboard / prediction markets.
- `https://x.com/MoonDevOnYT/status/2071654936119558256` - indexing thousands of Polymarket contracts into custom databases.
- `https://x.com/MoonDevOnYT/status/2071549249943167486` - prediction market limit bids / lowball stink bids.

Repo evidence:
- `https://github.com/moondevonyt/Limitless-Prediction-Market-Bots`
- The README advertises read-only public scripts for:
  - Limitless whale scanner.
  - Limitless versus Polymarket ETH 15-minute arbitrage scanner.
  - Historical market price fetcher.
- Live check confirmed `https://api.limitless.exchange/markets/active?page=1&limit=5` returns active markets without credentials.

Value to Vibe-Trading:
- High. This aligns with our existing Polymarket wallet tracker and Kalshi/Polymarket copy-trader work.
- Best implementation is not live trading. Best implementation is a read-only "prediction market edge lab" that watches:
  - Whale flow by wallet.
  - Cross-venue YES/NO bid/ask gaps.
  - Market liquidity/spread.
  - Whether whale entries predict later price movement.

Risk:
- Limitless is newer and lower-liquidity than Polymarket. Spreads can make the apparent edge vanish.
- Cross-venue arb needs execution speed, fill probability, and settlement-rule matching. Paper first.

Recommendation:
- Build a read-only Limitless scanner module before any execution.
- Add results into the copy-trader scoring pipeline only after logging 100+ whale events and measuring forward drift.

### 2. TradingView/Pine Script strategy extraction and backtest automation

Representative X post:
- `https://x.com/MoonDevOnYT/status/2071013205590331667` - Pine Script plus Claude Code backtesting workflow.

Value to Vibe-Trading:
- High, and already partially implemented. We have:
  - Pine strategy lab.
  - Red-flag scanner for repaint/lookahead traps.
  - Backtester and sweep reports.
  - TradingView MCP cloned but not activated until TradingView Desktop launches with CDP.

What to add:
- A formal `youtube_strategy_intake.md` template:
  - Source link.
  - Exact entry, stop, exit, sizing, timeframe.
  - Ambiguities.
  - Pine translation status.
  - Python port status.
  - Repaint flags.
  - OOS/WF/PBO status.
- Do not use "dangerous mode" or any permission-bypass framing. Treat public Pine files as license-scoped research only.

Risk:
- MoonDev's performance claims are marketing-style. We should trust our gates, not screenshots.
- Protected TradingView indicators may be readable on-screen, but copying proprietary logic is a legal/ethical risk. Use visible values for validation, not cloning.

Recommendation:
- Keep this as a research accelerator, not an execution source.
- Only promote strategies that pass our existing filters: trade count, OOS PF, WF, PBO, max drawdown, and forward shadow logging.

### 3. Liquidation data and CVD/orderflow

Representative X post:
- `https://x.com/MoonDevOnYT/status/2071375594097660211` - liquidation-data backtest claims.

Repo evidence:
- `https://github.com/moondevonyt/Hyperliquid-Data-Layer-API`
- The repo includes examples for:
  - Liquidations.
  - Multi-exchange liquidations.
  - Whale positions.
  - Orderflow.
  - CVD scanner.
  - BTC near-liquidation monitor.
- Live check confirmed Hyperliquid public `https://api.hyperliquid.xyz/info` returns market metadata.

Value to Vibe-Trading:
- Medium. It is useful for crypto research, but it does not directly improve the current Alpaca SPY/QQQ/IWM options bots.
- It can help if we create a separate crypto research lane or if we want a macro/risk context indicator for crypto-linked sentiment.

Risk:
- MoonDev's data layer requires a MoonDev API key for many high-value endpoints. Treat it as third-party infrastructure, not a core dependency.
- Liquidation strategies are easy to overfit because liquidation clusters are visually compelling after the fact.

Recommendation:
- Do not wire liquidation signals into Alpaca options.
- If pursued, build a read-only Hyperliquid liquidation logger with no execution and evaluate:
  - Liquidation imbalance.
  - CVD divergence.
  - Next 15m/1h return.
  - Slippage assumptions.

### 4. Social arbitrage from TikTok/viral trends

Representative X posts:
- `https://x.com/MoonDevOnYT/status/2071186856184590367` - social arbitrage / viral trend keywords.
- `https://x.com/MoonDevOnYT/status/2070824472374898701` - TikTok farming for trade signals.

Value to Vibe-Trading:
- Medium-low for automated trading, high for watchlist/research.
- The idea is plausible: consumer/product virality can move small caps, retail tickers, prediction markets, and crypto themes.
- It is not suitable for autonomous options entries without strong validation.

What to build if we pursue it:
- A social trend watchlist, not a trading bot:
  - Keyword spike.
  - Entity/ticker mapping confidence.
  - Source diversity score.
  - Float/liquidity screen.
  - Existing news catalyst check.
  - Manual review flag.

Risk:
- Very noisy.
- TikTok and X data access can be brittle or paid.
- Most viral content does not map cleanly to liquid public equities.

Recommendation:
- Add this to research queue only after the existing bot health and forward-test stack is stable.

### 5. Open-source AI agent swarms for trading

Representative X posts:
- `https://x.com/MoonDevOnYT/status/2071737981082255399` - 20+ AI agents for trading.
- `https://x.com/MoonDevOnYT/status/2070567773529374850` - agents writing/backtesting trading code.

Repo evidence:
- `https://github.com/moondevonyt/agent-zero`
- `https://github.com/moondevonyt/eliza`
- `https://github.com/moondevonyt/Harvard-Algorithmic-Trading-with-AI`

Value to Vibe-Trading:
- Low as a framework migration.
- Medium as a research workflow. We already have a better core stack for our needs:
  - Scheduler.
  - Alpaca integration.
  - Guard blocks.
  - Portfolio kill switch.
  - Shadow loggers.
  - Claude/Codex bridge.

Risk:
- Generic agent frameworks tend to increase execution risk if connected to real money.

Recommendation:
- Do not migrate.
- Use the RBI framing from the Harvard repo as a checklist: Research, Backtest, Implement.
- Our existing "paper validation first" principle is the correct version of this.

## Implementation Queue

P0 - No live trading changes from MoonDev posts.
- Keep all MoonDev-derived work read-only or shadow-only until measured.

Done - Add conservative pre-open sentiment logger.
- Implemented `scripts/preopen_sentiment_logger.py`.
- Uses public StockTwits SPY/QQQ streams, not brittle X scraping.
- Logs to `data/preopen_sentiment_log.jsonl`.
- Scheduled as `\VibeTrade\PreOpenSentimentLogger` weekdays at 08:25 CT.
- Mode is `context_only`; `execution_enabled` is false; no broker orders are wired.
- First live read-only scan completed: aggregate bullish, SPY bullish, QQQ bullish.

Done - Add automated social trending-symbol baseline.
- Implemented `scripts/social_trending_symbols_scanner.py`.
- Implemented `scripts/run_social_trending_symbols_scanner.ps1`.
- Implemented `agent/tests/test_social_trending_symbols_scanner.py`.
- Added intraday slot metadata to every report row:
  - `intraday_scan_index`,
  - `intraday_slot_label`,
  - `scheduled_start_ct`,
  - `scheduled_interval_minutes`.
- Uses public StockTwits trending-symbol feed as a stable credential-free baseline.
- Logs to `data/social_trending_symbols_log.jsonl`.
- Writes latest report to `~/.vibe-trading/reports/social-trending-symbols.json`.
- Scheduled as `\VibeTrade\SocialTrendingSymbolsScanner`.
- Runs daily starting 08:20 CT and repeats every 2 hours for 11 hours.
- Mode is `context_only`; `execution_enabled` is false; no broker orders are wired.
- Current scan showed 20 symbols across biotech/healthcare, EV/battery, single-stock, crypto, and crypto-equity-proxy buckets.

Done - Add social trending persistence report.
- Implemented `scripts/social_trending_persistence_report.py`.
- Implemented `scripts/run_social_trending_persistence_report.ps1`.
- Implemented `agent/tests/test_social_trending_persistence_report.py`.
- Scheduled as `\VibeTrade\SocialTrendingPersistenceReport` daily at 19:00 CT.
- Reads `data/social_trending_symbols_log.jsonl`.
- Writes latest report to `~/.vibe-trading/reports/social-trending-persistence.json`.
- Purpose: distinguish one-scan hype from repeated intraday attention by grouping `(date, symbol)` and counting slots.
- Mode is `context_only`; `execution_enabled` is false; no broker orders are wired.
- Verification:
  - Focused tests passed: 6/6.
  - Live scanner and persistence report both ran cleanly.

Done - Harden meme-stock noise handling.
- GME/AMC remain visible but are flagged as baseline meme-stock noise.
- Any noise flag now prevents `watch_context` promotion, including the large/liquid generic fallback.
- This prevents always-trending meme names from skewing persistence analysis beside cleaner narrative tickers like NVDA, LLY, NKE, or COIN.
- Focused social scanner/persistence tests passed: 7/7.

Done - Expand social-arb keyword/instrument map.
- `strategies/social_arbitrage_watchlist.py` default keyword map now covers:
  - broad ETFs: SPY, QQQ, SMH and sector context,
  - AI/semis/software: NVDA, MSFT, AMZN, PLTR, RBLX,
  - consumer/retail: NKE, LULU, COST, WMT, CELH, SWK,
  - GLP-1/healthcare: LLY, NVO,
  - EV/batteries: TSLA, QS, LCID, RIVN,
  - crypto equity proxies: COIN, MSTR, HOOD,
  - high-noise meme/speculation: GME, AMC, IWM proxy.
- The cross-platform layer remains research-only and needs observations from X/Threads/Instagram/TikTok/manual research before it produces ideas.

Done - Add Limitless read-only market scanner.
- Implemented `scripts/limitless_market_scanner.py`.
- Implemented `scripts/run_limitless_market_scanner.ps1`.
- Implemented `agent/tests/test_limitless_market_scanner.py`.
- Logs to `data/limitless_market_scan_log.jsonl`.
- Writes latest report to `~/.vibe-trading/reports/limitless-market-scanner.json`.
- Scheduled as `\VibeTrade\LimitlessMarketScanner` daily at 19:10 CT.
- Captures:
  - active market slug/title.
  - YES/NO bid/ask.
  - spread.
  - volume.
  - `isPolyArbitrage`.
  - top whale trades from `/markets/{slug}/get-feed-events`.
- No orders.
- First live read-only scan completed: 10 markets, 2 poly-arb markets, 3 wide-spread markets, 7 whale events.

P1 - Improve prediction-market copy pipeline.
- Add market-level concentration metrics:
  - number of tracked wallets on same market/side.
  - total notional.
  - avg entry.
  - market price drift after entry.
- Add "lowball bid opportunity" report only when spread/liquidity support it.

P2 - Add YouTube/social strategy intake template.
- New doc under `research/social_strategy_intake/`.
- Purpose: convert YouTube/X strategy claims into structured rules for Pine/Python testing.
- Must include ambiguity flags and repaint/lookahead checks.

P2 - Add Hyperliquid read-only liquidation research lane.
- Only if we deliberately want crypto research.
- Start with public endpoints and official Hyperliquid API where possible.
- Avoid third-party MoonDev API dependency until we prove the signal.

P3 - Social arbitrage watchlist.
- Watch keywords and map to tickers manually or with high-confidence entity extraction.
- No execution.

## Bottom Line

MoonDev's posts are useful as an idea radar, not as proof. The best immediate idea for us is prediction-market indexing and whale/contract tracking because it fits work we already built. The second best is improving the Pine/TradingView intake loop because it accelerates strategy rejection. Liquidation data and social arbitrage are interesting, but they belong in separate read-only research lanes.

Do not chase the advertised returns. Make every MoonDev-derived idea pass the same Vibe-Trading gates:
- read-only first,
- paper/shadow logs,
- OOS/WF/PBO where applicable,
- guard blocks,
- confidence score,
- no live execution until forward evidence earns it.
