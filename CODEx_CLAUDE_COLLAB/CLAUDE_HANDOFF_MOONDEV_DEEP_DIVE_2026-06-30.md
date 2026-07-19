# Claude Handoff - MoonDev Deep Dive - 2026-06-30

Project: `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading`

Codex completed a read-only deep dive on recent MoonDevOnYT social posts and public repos.

Full report:
- `research/moondev_social_deep_dive_2026-06-30.md`

## Sources Checked

X via logged-in Chrome:
- `https://x.com/MoonDevOnYT/status/2071737981082255399` - open-source AI agent swarm framing.
- `https://x.com/MoonDevOnYT/status/2071654936119558256` - indexing Polymarket contracts into custom databases.
- `https://x.com/MoonDevOnYT/status/2071549249943167486` - prediction-market lowball bid / limit-order framing.
- `https://x.com/MoonDevOnYT/status/2071375594097660211` - liquidation-data backtest claims.
- `https://x.com/MoonDevOnYT/status/2071292547134054729` - prediction-market whale wallet dashboard.
- `https://x.com/MoonDevOnYT/status/2071186856184590367` - social arbitrage / viral trend keywords.
- `https://x.com/MoonDevOnYT/status/2071013205590331667` - TradingView/Pine extraction and backtesting.
- `https://x.com/MoonDevOnYT/status/2070824472374898701` - TikTok trend-farming for trade signals.

GitHub:
- `https://github.com/moondevonyt/Limitless-Prediction-Market-Bots`
- `https://github.com/moondevonyt/Hyperliquid-Data-Layer-API`
- `https://github.com/moondevonyt/Harvard-Algorithmic-Trading-with-AI`
- `https://github.com/moondevonyt/Moon-Dev-Code`

Endpoint sanity checks:
- `https://api.limitless.exchange/markets/active?page=1&limit=5` returned active markets without credentials.
- `https://api.hyperliquid.xyz/info` returned public market metadata.

last30days:
- Attempted with a MoonDev query plan.
- X returned HTTP 403 and engine only returned low-signal Reddit content.
- Chrome provided the better X evidence.

## Decision

MoonDev is useful as an idea radar, not as proof. Do not use his performance screenshots as validation.

Best actionable ideas for our stack:
1. Prediction-market indexing and whale/concentration tracking.
2. Pine/TradingView strategy intake and rejection pipeline.
3. Hyperliquid liquidation/CVD research as crypto-only, read-only.
4. Social trend arbitrage as watchlist-only, not execution.

## Recommended Build Queue

P0:
- No live execution changes from MoonDev posts.
- Keep all MoonDev-derived ideas read-only/shadow-only until measured.

Completed by Codex after reading Claude's MoonDev assessment:
- Built `scripts/preopen_sentiment_logger.py`.
- Built `scripts/run_preopen_sentiment_logger.ps1`.
- Built `agent/tests/test_preopen_sentiment_logger.py`.
- Scheduled `\VibeTrade\PreOpenSentimentLogger` weekdays at 08:25 CT.
- Data log: `data/preopen_sentiment_log.jsonl`.
- Source: public StockTwits streams for SPY/QQQ.
- Mode: context only, `execution_enabled=false`, no broker orders wired.
- Verification:
  - `uv run --no-project --with pytest python -m pytest agent\tests\test_preopen_sentiment_logger.py -q` => 4 passed.
  - `uv run --no-project python scripts\preopen_sentiment_logger.py --symbols SPY,QQQ --limit 10 --print` ran cleanly.

Completed by Codex after Kenny asked about the social stock layer:
- Built `scripts/social_trending_symbols_scanner.py`.
- Built `scripts/run_social_trending_symbols_scanner.ps1`.
- Built `agent/tests/test_social_trending_symbols_scanner.py`.
- Added `intraday_scan_index`, `intraday_slot_label`, scheduled start, and interval metadata to each scan row.
- Scheduled `\VibeTrade\SocialTrendingSymbolsScanner`.
- Schedule: daily at 08:20 CT, repeat every 2 hours for 11 hours.
- Data log: `data/social_trending_symbols_log.jsonl`.
- Latest report: `~/.vibe-trading/reports/social-trending-symbols.json`.
- Source: public StockTwits trending symbols.
- Mode: context only, `execution_enabled=false`, no broker orders wired.
- Verification:
  - `uv run --no-project --with pytest python -m pytest agent\tests\test_social_arbitrage_watchlist.py agent\tests\test_social_trending_symbols_scanner.py -q` => 6 passed.
  - Live scan completed cleanly and showed current trending buckets: biotech/healthcare, EV/batteries, single-stock, crypto, crypto-equity-proxy.

Completed by Codex after Claude's persistence note:
- Built `scripts/social_trending_persistence_report.py`.
- Built `scripts/run_social_trending_persistence_report.ps1`.
- Built `agent/tests/test_social_trending_persistence_report.py`.
- Scheduled `\VibeTrade\SocialTrendingPersistenceReport` daily at 19:00 CT.
- Latest report: `~/.vibe-trading/reports/social-trending-persistence.json`.
- Purpose: compare 08:20/10:20/12:20/etc. scans and surface tickers that persisted across multiple intraday slots.
- Mode: context only, `execution_enabled=false`, no broker orders wired.
- Verification:
  - `uv run --no-project --with pytest python -m pytest agent\tests\test_social_trending_symbols_scanner.py agent\tests\test_social_trending_persistence_report.py -q` => 6 passed.
  - Live scanner and persistence report both ran cleanly.

Completed by Codex after Claude's GME/AMC noise warning:
- `scripts/social_trending_symbols_scanner.py` now flags GME/AMC as `meme-stock baseline trend; require independent catalyst before scoring`.
- Any `noise_flags` now block generic `watch_context` promotion, including large/liquid fallback promotion.
- GME/AMC remain visible in reports but stay `context_only` unless a separate catalyst layer validates them.
- Regression test added in `agent/tests/test_social_trending_symbols_scanner.py`.
- Verification: focused social scanner/persistence tests now pass 7/7, and the live scanner still runs cleanly.

Also expanded `strategies/social_arbitrage_watchlist.py` default keyword map to 33 mapped themes/instruments:
- SPY, QQQ, SMH/broad ETF context.
- NVDA, MSFT, AMZN, PLTR, RBLX AI/software.
- NKE, LULU, COST, WMT, CELH, SWK consumer/retail.
- LLY, NVO GLP-1/healthcare.
- TSLA, QS, LCID, RIVN EV/battery.
- COIN, MSTR, HOOD crypto-equity proxies.
- GME, AMC, IWM high-noise/meme/squeeze context.

Important: this is not full X/Threads/Instagram/TikTok automation yet. Those platforms need stable API/cookie/last30days ingestion. Current production-safe split:
- StockTwits trend scanner = automated daily retail ticker baseline.
- Social-arb watchlist = cross-platform observation scorer when X/Threads/Instagram/TikTok/manual observations are available.

Completed by Codex:
- Built `scripts/limitless_market_scanner.py`.
- Built `scripts/run_limitless_market_scanner.ps1`.
- Built `agent/tests/test_limitless_market_scanner.py`.
- Scheduled `\VibeTrade\LimitlessMarketScanner` daily at 19:10 CT.
- Data log: `data/limitless_market_scan_log.jsonl`.
- Latest report: `~/.vibe-trading/reports/limitless-market-scanner.json`.
- Source: public Limitless endpoints. No API keys required.
- Captures:
  - market slug/title,
  - YES/NO bid/ask,
  - spread,
  - volume,
  - `isPolyArbitrage`,
  - recent whale events from `/markets/{slug}/get-feed-events`.
- Verification:
  - `uv run --no-project --with pytest python -m pytest agent\tests\test_limitless_market_scanner.py -q` => 4 passed.
  - Live read-only scan completed cleanly: 10 markets, 2 poly-arb markets, 3 wide-spread markets, 7 whale events.

P1:
- Improve Polymarket/Limitless copy-trading reports:
  - wallet cluster consensus,
  - market-level concentration,
  - price drift after whale entry,
  - liquidity/spread gate,
  - why-rejected reasons.

P2:
- Create `research/social_strategy_intake/youtube_strategy_intake_template.md`.
- This should convert YouTube/X strategy claims into:
  - rules,
  - ambiguous edge cases,
  - Pine translation,
  - Python port,
  - repaint/lookahead scan,
  - OOS/WF/PBO status.

P2:
- Hyperliquid liquidation logger only if Kenny explicitly wants a crypto research lane.
- Prefer official Hyperliquid public endpoints before any MoonDev API dependency.
- No execution.

P3:
- Social arbitrage watchlist:
  - trend keyword spike,
  - ticker/entity mapping confidence,
  - source diversity,
  - liquidity/float screen,
  - manual review flag.

## Risk Notes

- MoonDev repos generally have no clear license metadata in GitHub API for the checked repos. Treat as reference unless license is verified.
- Protected TradingView indicators should not be cloned. Use visible outputs for validation only.
- Liquidation and social-arb claims are highly overfit-prone.
- Existing Vibe-Trading guard stack remains the source of truth.
