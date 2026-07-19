# Trading Automation Repo Scan

Date: 2026-06-30
Research path: last30days + public GitHub search + README inspection
Scope: Reddit/TikTok-style trading automation claims, open-source trading bots, scanners, backtesters, prediction-market tools, and frameworks that can improve Vibe-Trading without destabilizing execution.

## Executive Verdict

No recent Reddit/TikTok scan produced a high-confidence "magic bot" worth trusting directly. The last30days engine returned only thin Reddit evidence and no TikTok/GitHub hits without additional provider tokens.

The real value is in mature open-source infrastructure:
- use frameworks as references or sandboxes
- extract read-only scanners and risk patterns
- do not migrate the current Alpaca/Kalshi stack
- do not run unknown repos with broker keys

## What last30days Found

Command focus:
- Reddit
- TikTok hashtags: `tradingbot`, `algotrading`, `aitrading`, `quanttrading`, `tradingautomation`
- GitHub / Hacker News / web where available

Result:
- Reddit: 2 weak threads, not repo-specific
- TikTok: 0 videos surfaced
- GitHub: unavailable through the skill run because no GitHub token was configured
- Web: no native web backend key

Conclusion:
- Social evidence was too thin to act on.
- Use social posts as discovery prompts only, then verify repos directly.

## Highest-Value Repos For Our Stack

### 1. OpenBB

Repo: https://github.com/OpenBB-finance/OpenBB

Why it matters:
- Broad data integration layer.
- Can feed macro, fundamentals, sentiment, and market context into our scanners.
- Has AI/MCP direction, which fits our Codex/Claude workflow.

Use for:
- data adapters
- research dashboards
- adding non-price context to Market Force Score

Do not use for:
- execution
- replacing current bot scheduler/guards

Fit: high
Priority: P1 research/sandbox

### 2. PMXT

Repo: https://github.com/pmxt-dev/pmxt

Why it matters:
- "ccxt for prediction markets."
- Targets Polymarket, Kalshi, Limitless, Opinion, Probable.
- Directly overlaps our Kalshi, Polymarket, and Limitless work.

Use for:
- cross-venue prediction-market scanner reference
- unified market schema ideas
- arbitrage visibility concepts

Do not use for:
- hosted trading or live execution until audited
- replacing our Kalshi/Polymarket clients

Fit: very high
Priority: P0/P1 read-only sandbox

### 3. Polymarket py-clob-client

Repo: https://github.com/Polymarket/py-clob-client

Why it matters:
- Official-ish Polymarket CLOB client.
- Best source for wallet/orderbook/trade endpoint behavior.
- Helps our wallet tracker avoid brittle endpoint guessing.

Use for:
- wallet tracker hardening
- market/orderbook scanner
- copy-trader evidence quality

Do not use for:
- live copy trading

Fit: very high
Priority: P0 for prediction-market tooling

### 4. NautilusTrader

Repo: https://github.com/nautechsystems/nautilus_trader

Why it matters:
- Serious event-driven trading engine.
- Strong research-to-live parity, cache/message-bus architecture, and risk concepts.
- Too heavy to migrate into, but excellent architecture reference.

Use for:
- event model ideas
- portfolio/risk layer design
- deterministic backtest/live parity patterns

Do not use for:
- replacing current Alpaca bot execution
- quick options strategy research

Fit: medium-high
Priority: P2 architecture study

### 5. CuteMarkets cutebacktests

Repo: https://github.com/cutemarkets/cutebacktests

Why it matters:
- Options-specific historical/intraday backtesting runtime.
- Contract reconstruction and quote-aware fills are exactly the hard part of options backtests.

Concern:
- Requires CuteMarkets data/API key for many workflows.

Use for:
- options backtest realism reference
- opening-range options profile ideas
- possible paid-data sandbox later

Do not use for:
- immediate free production pipeline

Fit: high concept, medium immediate utility
Priority: P2

### 6. Hummingbot

Repo: https://github.com/hummingbot/hummingbot

Why it matters:
- Mature bot for market making/arbitrage.
- Good reference for connector design, inventory risk, spread capture, and strategy lifecycle.

Use for:
- architecture ideas for prediction-market market making
- risk/inventory patterns

Do not use for:
- equities/options execution

Fit: medium
Priority: P2 reference only

### 7. Freqtrade

Repo: https://github.com/freqtrade/freqtrade

Why it matters:
- Mature crypto bot with backtesting/hyperopt.
- Useful for parameter optimization discipline.

Use for:
- hyperopt ideas
- strategy evaluation workflow
- reporting patterns

Do not use for:
- Alpaca/options execution
- direct migration

Fit: medium
Priority: P2/P3

### 8. Microsoft Qlib

Repo: https://github.com/microsoft/qlib

Why it matters:
- Mature quant research platform.
- Strong for ML alpha research and dataset/evaluation structure.

Use for:
- longer-term research discipline
- model evaluation ideas

Do not use for:
- short-term 0DTE/options bot decisions

Fit: medium
Priority: P3

### 9. Lumibot

Repo: https://github.com/Lumiwealth/lumibot

Why it matters:
- Alpaca-native Python backtesting/live-style framework.
- Previously identified as useful for equity strategy sandboxing.

Use for:
- QQQ/GLD or momentum rotation sandbox
- comparing our shadow logger signals to framework backtests

Do not use for:
- options spread execution yet

Fit: medium-high
Priority: P2

### 10. Prediction Market Toolkits

Repo: https://github.com/HarrierOnChain/Prediction-Markets-Trading-Bot-Toolkits

Why it matters:
- Multi-venue prediction-market strategy catalog.
- Useful list of strategy archetypes: copy trading, cross-market arbitrage, spread farming, resolution sniper, orderbook imbalance, whale signal.

Concern:
- Big claims, many execution strategies, Rust stack, needs audit before trust.

Use for:
- strategy taxonomy
- safety/risk pattern comparison
- scanner ideas only

Do not use for:
- direct execution

Fit: high idea value, low immediate code value
Priority: P2

## Niche Repos Worth Watching

### Polymarket tracker

Repo: https://github.com/0xsteve-00/polymarket-tracker

Use:
- compare whale tracker features to our wallet tracker
- read-only only

Concern:
- very new, very low stars

### Polymarket arbitrage

Repo: https://github.com/ImMike/polymarket-arbitrage

Use:
- market matching ideas between Polymarket and Kalshi
- bundle arbitrage detection patterns

Concern:
- verify math and endpoint handling before using anything

### TradingView Machine Learning GUI / HyperView

Repo: https://github.com/TreborNamor/TradingView-Machine-Learning-GUI

Use:
- TradingView websocket data/backtest loop ideas
- Pine-to-Python validation workflow

Concern:
- Firefox cookie/session access deserves privacy review before running

## Repos To Avoid Running Directly

Avoid unknown repos that:
- ask for private keys or seed phrases
- require exchange keys before dry-run works
- claim huge returns without reproducible tests
- have no license
- have no tests
- have recently created accounts and copy-pasted README hype
- include obfuscated JS/Python

Prediction-market copy bots and "AI trading bot" clones are especially risky.

## Recommended Build Queue

### P0 - PMXT read-only comparison spike

Build:
- `scripts/pmxt_market_schema_probe.py`

Goal:
- Determine whether PMXT can provide cleaner cross-venue market normalization than our current ad-hoc Kalshi/Polymarket/Limitless scanners.

Constraints:
- no credentials
- no trading
- read-only endpoints only

### P0 - Polymarket CLOB client hardening pass

Build:
- Compare our wallet tracker and market scanner endpoint use against `Polymarket/py-clob-client`.

Goal:
- Stop relying on brittle or survivorship-biased endpoints.

### P1 - OpenBB data adapter experiment

Build:
- `scripts/openbb_context_probe.py`

Goal:
- See whether OpenBB can cheaply add macro/fundamental context to Market Force Score without API sprawl.

### P1 - Prediction-market strategy taxonomy report

Build:
- `research/prediction_market_strategy_taxonomy.md`

Goal:
- Compare our current Kalshi/Polymarket/Limitless tools against the strategy archetypes in PMXT and Prediction Market Toolkits.

### P2 - NautilusTrader architecture notes

Build:
- `research/nautilus_architecture_lessons.md`

Goal:
- Pull only the event/risk/cache patterns useful for our system.

### P2 - Lumibot QQQ/GLD sandbox

Goal:
- Validate whether Lumibot backtest output agrees with our QQQ/GLD shadow logger on historical dates.

## Bottom Line

The best next actionable repo is PMXT, followed by Polymarket's CLOB client and OpenBB.

Do not chase TikTok "AI bot" clones. The edge is not in copying a viral repo. The edge is in building a safer evidence pipeline:

1. discover repo or claim
2. inspect license/tests/security
3. extract only read-only data/scanner ideas
4. backtest or forward-test
5. integrate only after the 30-day/10-signal gate
