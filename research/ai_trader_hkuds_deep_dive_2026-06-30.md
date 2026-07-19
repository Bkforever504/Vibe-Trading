# HKUDS AI-Trader Deep Dive - 2026-06-30

Purpose: evaluate `HKUDS/AI-Trader` for Vibe-Trading. The goal is not to chase "fully automated AI trading" marketing. The goal is to identify architecture, data, schemas, and research patterns that can improve our guarded, paper-first trading stack.

## Sources Checked

- GitHub repo: `https://github.com/HKUDS/AI-Trader`
- Local clone: `research/external_repos/AI-Trader`
- GitHub API metadata for stars, forks, issues, pushed date, license field.
- Repo docs:
  - `README.md`
  - `docs/README_AGENT.md`
  - `docs/README_USER.md`
  - `docs/api/copytrade.yaml`
  - `skills/ai4trade/SKILL.md`
  - `skills/copytrade/SKILL.md`
  - `skills/tradesync/SKILL.md`
  - `skills/market-intel/SKILL.md`
  - `skills/polymarket/SKILL.md`
- Code inspected:
  - `service/server/signal_quality.py`
  - `service/server/challenge_scoring.py`
  - `service/server/routes_trading.py`
  - `service/server/price_fetcher.py`
  - `service/server/market_intel.py`
  - `research/scripts/compute_metrics.py`
  - research schemas for signals, trades, and quality scores.
- Live public endpoint checks:
  - `https://ai4trade.ai/api/signals/feed?limit=5`
  - `https://ai4trade.ai/api/profit/history?limit=5&days=30&include_history=false&metric=risk`
  - `https://ai4trade.ai/api/market-intel/overview`
  - `https://ai4trade.ai/api/market-intel/macro-signals`
  - `https://ai4trade.ai/api/market-intel/stocks/NVDA/latest`

## Repo Facts

- GitHub repo exists and is active/popular:
  - Created: 2025-10-23
  - Last pushed: 2026-06-11
  - Stars at research time: about 20k
  - Forks at research time: about 3.1k
  - Main language: Python
  - Open issues: 26
- README claims MIT via badge, but GitHub API returned `license: null`, and local clone had no top-level `LICENSE` file. Treat code as reference-only until license is clarified.
- This is not a single trading strategy repo. It is a platform:
  - FastAPI backend.
  - React/Vite frontend.
  - Signal feed.
  - Copy trading APIs.
  - Agent registration/heartbeat.
  - Paper trading / challenge scoring.
  - Research export schemas and analysis scripts.

## What Is Actually Useful

### 1. Standardized signal envelope

AI-Trader has a clean signal/trade shape:

- `message_type`: operation, strategy, discussion
- `market`
- `symbol` / `symbols`
- `side`
- `entry_price`
- `exit_price`
- `quantity`
- `pnl`
- `title`
- `content`
- `tags`
- `created_at`
- `executed_at`
- agent identity fields

Vibe-Trading should adopt a local version of this idea for our shadow logs and bot reports. This would let us compare Flip Bot, IWM Bot, RSI-2, KAMA, Williams %R, QQQ/GLD, social trend, Limitless, and Kalshi-style signals with one schema.

Recommended local artifact:

- `research/signal_registry_schema.md`
- Optional later: `scripts/signal_registry_report.py`

### 2. Leaderboard / challenge scoring model

`challenge_scoring.py` replays trades, marks positions, computes equity, max drawdown, return, and risk-adjusted score. It also includes max-position and max-drawdown disqualification logic.

This maps directly to our need for a strategy leaderboard:

- Strategy
- Mode: live, paper, shadow, context-only
- Trade/signal count
- Return or hypothetical return
- Max drawdown
- Risk-adjusted score
- Disqualification/block reasons
- Freshness/status

We already have many JSONL logs. AI-Trader's challenge pattern suggests building one roll-up rather than reading every log manually.

Recommended local artifact:

- `scripts/signal_stack_leaderboard.py`
- Output: `~/.vibe-trading/reports/signal-stack-leaderboard.json`

### 3. Public signal feed as a research dataset

`https://ai4trade.ai/api/signals/feed?limit=5` returned public signals without auth. There were more than 700k signals in the feed response. Current examples included copied crypto trades and strategy posts.

Use case:

- Read-only scanner.
- Track top public AI-Trader agents/signals.
- Measure forward drift of their signals ourselves.
- Never auto-copy.

This can be an additional "external AI sentiment/copy-trade candidate" source beside Polymarket wallets and Kalshi profiles.

Recommended local artifact:

- `scripts/ai_trader_public_signal_scanner.py`
- Context-only.
- Fetch operation signals.
- Normalize to our local signal envelope.
- Log top symbols, side, agent, quality score, duplicate/copy flags.
- Block all copied signals from direct action until the original provider is traced and scored.

### 4. Risk-adjusted leaderboard concept

`/api/profit/history?metric=risk` returned top agents with:

- profit percent,
- trade count,
- max drawdown,
- risk-adjusted score,
- quality score average,
- adoption/collaboration metrics.

Useful idea:

- Do not rank strategies by P&L only.
- Sort by risk-adjusted score and minimum sample size.
- Penalize low trade count and stale activity.

Important caveat:

- Some public top agents had very low trade counts, e.g. 2 or 7 trades. Those are not statistically reliable even if risk-adjusted score looks high.

### 5. Skill-file routing pattern

The agent skills are a decent interface pattern:

- main skill routes to child skills,
- child skills define clear endpoints and constraints,
- market-intel skill explicitly says read-only and context-only.

For us, this reinforces that each bot/tool should have a small "contract" doc:

- what it reads,
- what it writes,
- whether it can execute,
- what gates apply,
- how to verify it.

## What Is Not Useful / Too Risky

### Do not copy trade from AI-Trader

The copytrade skill says copy mode is fully automatic and 1:1. That is incompatible with our account guard rules, options spreads, portfolio kill switch, and daily loss system.

Hard rule:

- Do not enable AI-Trader auto-follow or auto-copy.
- Do not connect external AI agents to Alpaca execution.

### Do not trust AI-Trader quality_score as edge

`signal_quality.py` scores:

- verifiability,
- evidence,
- specificity,
- novelty,
- review.

These are text-quality metrics, not trading edge. A good write-up can still lose money. Use their quality score only as a content filter, not a signal confidence score.

### Do not use market-intel without freshness gates

Live endpoint check showed stale data:

- Market-intel overview last updated around 2026-06-22.
- Macro signals as-of dates around 2026-06-18 to 2026-06-22.
- NVDA latest analysis returned stale price metadata with `price_stale: true`.

Therefore:

- AI-Trader market-intel is not currently acceptable as an execution input.
- If scanned, require `available=true` and freshness within a strict window.

### License risk

README badge says MIT, but repo API reported `license: null` and no top-level `LICENSE` file appeared in the local clone.

Policy:

- Do not copy code into Vibe-Trading.
- Reimplement concepts independently if useful.
- Keep the clone in `research/external_repos/AI-Trader` as reference only.

## Direct Comparison To Vibe-Trading

AI-Trader strengths:

- Agent-native signal API.
- Public signal feed.
- Leaderboard and risk-adjusted display.
- Challenge/paper-trading scoring.
- Research export schemas.
- Copy-trading interface.

AI-Trader weaknesses for our use:

- Copy trading is too blunt.
- Signal quality is mostly heuristic text quality.
- No proof that public agent signals are profitable after slippage.
- Market-intel freshness is questionable.
- No obvious options-spread execution rigor matching our Alpaca/IWM setup.
- License ambiguity.

Vibe-Trading strengths:

- Local guard stack.
- Alpaca paper/live integration.
- Portfolio kill switch.
- Spread-aware options bots.
- Scheduled shadow loggers.
- Daily JSONL evidence.
- Pine strategy lab with OOS/WF/PBO/repaint checks.
- Clear paper-first discipline.

Verdict:

- AI-Trader should not replace Vibe-Trading.
- It can improve our reporting, signal schema, external-signal scanner, and strategy leaderboard.

## Recommended Build Queue

P0 - No live execution changes.

- Do not connect AI-Trader to Alpaca.
- Do not auto-copy agents.
- Do not publish our live trades to AI-Trader until we decide privacy/competitive concerns.

P1 - Build local signal registry schema.

- Create one normalized local schema for all bots/signals.
- Include:
  - source,
  - strategy,
  - market,
  - symbol,
  - side,
  - confidence,
  - thesis,
  - entry/exit/stop/target if any,
  - risk dollars,
  - execution mode,
  - outcome fields,
  - guard block fields.

P1 - Build `signal_stack_leaderboard.py`.

- Read our JSONL logs.
- Compare strategies by:
  - sample count,
  - signal count,
  - realized/hypothetical P&L when available,
  - win rate,
  - max drawdown,
  - risk-adjusted score,
  - freshness,
  - execution mode.

P2 - Build AI-Trader public signal scanner.

- Read-only.
- Pull recent public `operation` signals and top risk-adjusted agents.
- Normalize to local schema.
- Track forward price drift with Alpaca/yfinance only for research.
- Never route into execution.

P2 - Add external-agent rejection rules.

- Reject if:
  - copied-from content,
  - low trade count,
  - stale agent activity,
  - crypto microcap,
  - missing stop/target,
  - low liquidity,
  - no forward drift evidence.

P3 - Optional market-intel scanner.

- Only if freshness-gated.
- Read-only context source.
- Probably lower priority than our StockTwits/social/GEX/IVR/TTM stack.

## Bottom Line

AI-Trader is useful as a mirror: it shows what a full agent-native trading platform looks like. The parts worth adopting are boring but powerful:

- standardized signal envelopes,
- paper/challenge scoring,
- risk-adjusted leaderboards,
- public signal feed scanning,
- research exports.

The parts to avoid are the exciting ones:

- fully automatic copy trading,
- agent autonomy over broker execution,
- trusting text quality scores as alpha,
- stale market-intel without freshness checks.

For tomorrow, the existing Vibe-Trading stack remains the source of truth. AI-Trader is a research/reference lane, not an execution dependency.
