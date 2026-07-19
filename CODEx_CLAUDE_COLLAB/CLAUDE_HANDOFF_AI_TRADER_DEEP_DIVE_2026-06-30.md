# Claude Handoff - HKUDS AI-Trader Deep Dive - 2026-06-30

Project: `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading`

Codex researched `HKUDS/AI-Trader` after Kenny asked whether Tom Dörr's X post about an agent-native fully automated AI trading platform can help us.

Full report:
- `research/ai_trader_hkuds_deep_dive_2026-06-30.md`

Local reference clone:
- `research/external_repos/AI-Trader`

## Key Findings

AI-Trader is real and popular:
- Repo: `https://github.com/HKUDS/AI-Trader`
- Created: 2025-10-23
- Last pushed: 2026-06-11
- Around 20k stars and 3.1k forks at research time.
- Python/FastAPI backend, React frontend, skills, OpenAPI specs, signal feed, copy trading, leaderboard/challenge scoring, research exports.

Important license caveat:
- README badge claims MIT.
- GitHub API returned `license: null`.
- Local clone had no top-level `LICENSE`.
- Treat code as reference-only. Do not copy code into Vibe-Trading unless license is clarified.

## Live Endpoint Checks

These public endpoints responded:
- `https://ai4trade.ai/api/signals/feed?limit=5`
  - Returned recent public signals and `total` over 700k.
- `https://ai4trade.ai/api/profit/history?limit=5&days=30&include_history=false&metric=risk`
  - Returned top agents with profit, drawdown, trade count, risk-adjusted score.
- `https://ai4trade.ai/api/market-intel/overview`
- `https://ai4trade.ai/api/market-intel/macro-signals`
- `https://ai4trade.ai/api/market-intel/stocks/NVDA/latest`

Market-intel warning:
- Market-intel was stale in the live check.
- Overview last update around 2026-06-22.
- NVDA latest analysis returned `price_stale: true`.
- Do not use AI-Trader market-intel for execution unless freshness-gated.

## What Helps Vibe-Trading

Best ideas to port conceptually:
1. Standardized signal envelope.
2. Strategy/bot leaderboard.
3. Challenge/paper scoring with max drawdown and risk-adjusted score.
4. Public external-agent signal scanner.
5. Research export schemas and comparison reports.

Best local build queue:

P0:
- No live execution changes.
- Do not auto-copy AI-Trader agents.
- Do not connect AI-Trader to Alpaca.
- Do not publish our live trades externally until Kenny decides privacy/competition concerns.

P1:
- Build `research/signal_registry_schema.md`.
- Define one local schema for all Vibe-Trading signal logs:
  - source,
  - strategy,
  - market,
  - symbol,
  - side,
  - confidence,
  - thesis,
  - entry/exit/stop/target,
  - risk dollars,
  - execution mode,
  - guard status,
  - outcome fields.

P1:
- Build `scripts/signal_stack_leaderboard.py`.
- Read our JSONL logs and compare strategies by:
  - sample count,
  - signal count,
  - realized/hypothetical P&L,
  - win rate,
  - max drawdown,
  - risk-adjusted score,
  - freshness,
  - execution mode.

P2:
- Build `scripts/ai_trader_public_signal_scanner.py`.
- Read-only.
- Pull public `operation` signals and top risk-adjusted agents.
- Normalize to our local signal envelope.
- Track forward price drift with Alpaca/yfinance.
- Never route into execution.

P2:
- Add external-agent rejection rules:
  - copied-from content,
  - low trade count,
  - stale agent activity,
  - crypto microcap,
  - missing stop/target,
  - low liquidity,
  - no forward drift evidence.

P3:
- Optional market-intel scanner only if freshness-gated.
- Lower priority than our StockTwits/social/GEX/IVR/TTM stack.

## What Not To Do

- Do not use AI-Trader copytrade skill with auto-copy.
- Copy mode is documented as 1:1 fully automatic.
- This conflicts with our account-specific risk limits, options spreads, portfolio kill switch, and guard-block system.
- Do not trust their `quality_score` as alpha. `signal_quality.py` mostly scores text quality, specificity, novelty, and evidence keywords.

## Bottom Line

AI-Trader is useful as architecture/research inspiration, not as tomorrow's execution layer. Vibe-Trading's guard stack remains the source of truth. The best immediate upgrade from this research is a unified local signal registry + signal stack leaderboard so we can compare all bots/scanners the way AI-Trader compares agents.
