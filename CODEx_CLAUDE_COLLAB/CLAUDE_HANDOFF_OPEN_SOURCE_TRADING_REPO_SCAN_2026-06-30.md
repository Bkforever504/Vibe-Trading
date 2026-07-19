# Claude Handoff - Open-Source Trading Repo Scan

Date: 2026-06-30
Owner: Codex

## User Request

Kenny asked to use `last30days` to scan Reddit and TikTok for trading-related repos/bots that can help us, plus other research methods.

## What Happened

Ran the `last30days` engine against:
- Reddit
- TikTok hashtags
- GitHub
- Hacker News
- web

The skill result was thin:
- Reddit: 2 weak generic trading threads
- TikTok: 0 surfaced videos
- GitHub: unavailable through skill run without token
- web: no native backend key

So Codex supplemented with public GitHub API searches and README inspection.

## Report Written

Main research brief:

`research/trading_automation_repo_scan_2026-06-30.md`

## Key Ranking

Best fits for our stack:

1. PMXT - `https://github.com/pmxt-dev/pmxt`
   - prediction-market "ccxt"
   - best immediate read-only sandbox candidate

2. Polymarket CLOB client - `https://github.com/Polymarket/py-clob-client`
   - use to harden wallet tracker / orderbook scanner endpoint logic

3. OpenBB - `https://github.com/OpenBB-finance/OpenBB`
   - possible macro/fundamental/context data layer for Market Force Score

4. NautilusTrader - `https://github.com/nautechsystems/nautilus_trader`
   - architecture/risk/event model reference only

5. CuteMarkets cutebacktests - `https://github.com/cutemarkets/cutebacktests`
   - options backtest realism reference; may need API key

6. Hummingbot / Freqtrade / Lumibot / Qlib
   - useful as references or isolated sandboxes, not migration targets

## Recommended Next Build Queue

P0:
- Build `scripts/pmxt_market_schema_probe.py`
- read-only, no credentials, no execution
- goal: see whether PMXT normalizes Kalshi/Polymarket/Limitless market schemas better than our current custom scanners

P0:
- Compare our Polymarket wallet tracker against `Polymarket/py-clob-client`
- fix endpoint choices if official client suggests better paths

P1:
- Build `scripts/openbb_context_probe.py`
- test whether OpenBB can add macro/fundamental context to Market Force Score without adding paid data

P1:
- Write `research/prediction_market_strategy_taxonomy.md`
- compare our Kalshi/Polymarket/Limitless stack against PMXT and Prediction Market Toolkits strategy archetypes

## Safety Note

Do not run random TikTok/GitHub "AI trading bot" repos with broker keys.

Reject repos that:
- ask for seed phrases/private keys
- require exchange keys before dry-run
- lack tests/license
- make huge return claims without reproducible data
- contain obfuscated code

Everything should remain read-only/sandboxed until reviewed.
