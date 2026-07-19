# Repo Evaluation: Trading Dashboard + AI Stack Candidates

Date: 2026-07-05

Purpose: evaluate six user-provided repositories for Vibe-Trading. The filter is practical: improve the bot, dashboard, scanner intelligence, risk controls, or research intake without weakening the existing read-only / paper-first execution gates.

## Executive Ranking

| Rank | Repo | Verdict | Best Use | Integration Risk |
| --- | --- | --- | --- | --- |
| 1 | `tradingview/lightweight-charts` | Use for dashboard V2 | Interactive equity/P&L/candlestick charts in static dashboard | Low |
| 2 | `ccxt/ccxt` | Use only read-only | Crypto exchange market data, OHLCV, funding/rate context, cross-exchange watchlists | Medium |
| 3 | `agiprolabs/claude-trading-skills` | Already partially harvested; continue selectively | Read-only governance tools: walk-forward, sizing, journal, visualization, slippage | Low/Medium |
| 4 | `leoncuhk/awesome-quant-ai` | Research queue, not code dependency | Ideas/papers for regime, ML validation, Mamba/time-series research | Low |
| 5 | `HKUDS/AI-Trader` | Schema/reference only | Agent signal envelope, quality scoring, challenge scoring, dashboard concepts | Medium/High |
| 6 | `bradautomates/claude-video` | Optional manual intake | Analyze trading videos/screenshares before converting ideas to strategy intake | Medium |

## Current Metadata Snapshot

Pulled from GitHub API on 2026-07-05 local time.

| Repo | Stars | Forks | Open Issues | Last Push | License | Language |
| --- | ---: | ---: | ---: | --- | --- | --- |
| `tradingview/lightweight-charts` | 16,496 | 2,517 | 124 | 2026-07-03 | Apache-2.0 | TypeScript |
| `ccxt/ccxt` | 43,218 | 8,728 | 1,299 | 2026-07-05 | MIT | Python |
| `HKUDS/AI-Trader` | 20,482 | 3,141 | 29 | 2026-06-11 | API returned null; README badge says MIT | Python |
| `agiprolabs/claude-trading-skills` | 159 | 37 | 0 | 2026-06-24 | MIT | Python |
| `leoncuhk/awesome-quant-ai` | 435 | 81 | 12 | 2026-04-29 | Apache-2.0 | Jupyter Notebook |
| `bradautomates/claude-video` | 3,527 | 543 | 29 | 2026-07-01 | MIT | Python |

## 1. TradingView Lightweight Charts

Repo: https://github.com/tradingview/lightweight-charts

Verdict: highest-value dashboard upgrade. Do not use it for trading logic. Use it to make the static dashboard easier to read.

Why it helps:
- Mature, active, Apache-2.0.
- Purpose-built for financial time-series charts.
- Fits the current static HTML dashboard: no server required.
- Best visual upgrade for account equity, Flip Bot P/L, IWM open P/L, signal grades over time, hot ticker scores, and daily scanner health.

Recommended Vibe-Trading integration:
- Phase 2 dashboard:
  - equity curve from `bot-status-snapshot` / portfolio reports
  - Flip Bot cumulative P/L chart with pre-fix marker on 2026-06-24 / post-config start 2026-06-29
  - IWM open/unrealized P/L chart
  - scanner health stacked bars
  - hot ticker score timeline
- Keep charts local/static. Either vendor a pinned production bundle or use a pinned CDN URL only if internet availability is acceptable.

Do not:
- Do not embed TradingView widgets requiring external accounts.
- Do not let chart interactions become execution controls.

Priority: P0/P1 for dashboard V2.

## 2. CCXT

Repo: https://github.com/ccxt/ccxt

Verdict: useful, but only in a read-only crypto context module. It should not touch the equities/options bot execution path.

Why it helps:
- Very mature, MIT, huge exchange coverage.
- Good abstraction for crypto OHLCV, tickers, order books, funding, exchange status.
- Could improve crypto context currently represented by MoonDev/liquidation/prediction-market style scanners.

Recommended Vibe-Trading integration:
- Create a read-only `crypto_market_context` scanner:
  - BTC/ETH/SOL/major alt OHLCV
  - spot/perp basis where supported
  - volume shock
  - exchange outage/status checks
  - crypto risk-on/risk-off context for equity names like COIN, MSTR, HOOD, MARA, RIOT
- Add dashboard section:
  - crypto regime
  - BTC/ETH daily change
  - funding pressure
  - exchange health

Risks:
- CCXT has private trading methods. We must instantiate public clients only and block keys.
- Large dependency footprint.
- 1,299 open issues is normal for broad exchange coverage but means exchange quirks are constant.

Do not:
- Do not add exchange API keys.
- Do not use `create_order`, private endpoints, or trading permissions.
- Do not route Flip/IWM decisions directly from crypto data.

Priority: P2 read-only scanner.

## 3. Agiprolabs Claude Trading Skills

Repo: https://github.com/agiprolabs/claude-trading-skills

Verdict: already useful, but only selective harvesting. Continue the same pattern we used: convert valuable ideas into local read-only tools with tests and registry entries.

Already harvested / assessed:
- `walk-forward-validation`: convert to read-only tool.
- `position-sizing`: converted into local risk/sizing sanity report.
- `trade-journal`: should extend existing postmortem/daily review logs.
- `options-pricing`: study only for now; upstream stub was not enough to trust.
- Avoid blanket import.

Additional candidates worth selective review:
- `trading-visualization`: could inform dashboard V2 layouts.
- `slippage-modeling`: useful for shadow P/L realism.
- `signal-classification`: useful for unified schema and promotion gates.
- `market-microstructure-traditional`: potentially useful for GEX/ORB/EMA context.
- `portfolio-analytics`: could improve risk state dashboard.

Do not:
- Do not import skill outputs as live execution logic.
- Do not duplicate existing logs where we already have closed postmortem and daily outcome review.

Priority: P1/P2, intake one skill at a time.

## 4. Awesome Quant AI

Repo: https://github.com/leoncuhk/awesome-quant-ai

Verdict: research index. Useful for deciding what to study next, not as code.

Why it helps:
- Curated map of AI/ML quant topics.
- Has frontier/emerging topic sections that overlap with Mamba/time-series forecasting, AI agents, deep learning, and validation.
- Apache-2.0 and low operational risk because we are not importing runtime code.

Recommended Vibe-Trading integration:
- Add a research queue item type:
  - `source_repo`
  - `paper_or_topic`
  - `expected_bot_impact`
  - `risk_of_overfit`
  - `required_shadow_evidence`
- Use it to pick one monthly research theme:
  - regime detection
  - sequence models/Mamba
  - graph or cross-asset models
  - meta-labeling
  - robust validation / purged CV

Do not:
- Do not turn papers into trading rules without walk-forward and shadow evidence.
- Do not chase every frontier topic.

Priority: P2 research governance.

## 5. HKUDS AI-Trader

Repo: https://github.com/HKUDS/AI-Trader

Verdict: schema/reference only. We already deep-dived this repo on 2026-06-30. It has useful ideas but should not be installed as a platform replacement.

Useful pieces:
- Standardized signal envelope.
- Agent identity / heartbeat concepts.
- Signal quality scoring.
- Challenge scoring / paper competition ideas.
- Feed/dashboard architecture.

Concerns:
- README markets “100% fully automated” trading, which conflicts with our guarded paper-first stack.
- GitHub API license field returned null even though README badge claims MIT. Treat as reference until top-level license is confirmed.
- It is a platform, not a small tool. Replacing our stack with it would increase risk.

Recommended Vibe-Trading integration:
- Borrow schema ideas:
  - `signal_id`
  - `source_agent`
  - `symbol`
  - `market`
  - `side`
  - `entry_context`
  - `confidence`
  - `outcome`
  - `pnl`
  - `postmortem`
- Use “agent heartbeat” as a dashboard concept:
  - last run
  - last artifact
  - health
  - stale/error
  - next expected run

Do not:
- Do not deploy their backend.
- Do not use their copy-trading APIs.
- Do not weaken execution gates.

Priority: P1 schema-only, no dependency.

## 6. Claude Video

Repo: https://github.com/bradautomates/claude-video

Verdict: useful only for manual research intake from videos. Not part of bot runtime.

Why it helps:
- User frequently brings screenshots/videos/posts about strategies.
- A video-aware intake step could turn “watch this trading clip” into structured strategy notes:
  - claimed setup
  - timeframe
  - indicators
  - risk rule
  - screenshots/levels
  - proposed shadow logger
  - reasons to reject

Concerns:
- Requires `yt-dlp` / `ffmpeg`; Windows setup can be brittle.
- It is an agent skill/plugin, not a trading library.
- It may need external APIs for Whisper fallback.

Recommended Vibe-Trading integration:
- Optional manual workflow only:
  - analyze video
  - produce strategy intake JSON
  - route through `strategy_intake_report`
  - never auto-promote
- If installed, keep it outside scheduled bot jobs.

Do not:
- Do not make it part of the EOD stack.
- Do not use social/video claims as direct trade triggers.

Priority: P3 optional.

## Recommended Build Order

1. Dashboard V2 with Lightweight Charts.
   - Highest daily value.
   - Low trading risk.
   - Directly improves visibility into all bots and scanners.

2. Add a unified signal envelope inspired by AI-Trader.
   - Makes Flip, IWM, shadow loggers, social scanners, and review layers easier to compare.
   - Helps future promotion gates.

3. Add CCXT read-only crypto context scanner.
   - Helps COIN/MSTR/HOOD/crypto-sensitive names.
   - Must be public-data-only.

4. Continue selective `claude-trading-skills` intake.
   - Next best: slippage modeling, signal classification, trading visualization.

5. Use awesome-quant-ai as a monthly research queue.
   - Not a runtime dependency.

6. Consider claude-video only if video strategy intake becomes frequent.
   - Useful for extracting rules from clips, not for bot execution.

## Bottom Line

Best immediate improvement: `tradingview/lightweight-charts` for a better static dashboard.

Best medium-term intelligence improvement: AI-Trader-style unified signal envelope plus continued selective trading-skills intake.

Best cautious expansion: CCXT as a read-only crypto context scanner.

Avoid: platform migration, live execution APIs, or importing broad external repos into the bot runtime.
