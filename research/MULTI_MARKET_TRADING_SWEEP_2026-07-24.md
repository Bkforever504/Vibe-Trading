# Multi-Market Trading Research Sweep - 2026-07-24

## Scope

- Eleven cost-capped X API searches; 83 posts retained.
- Thirty-seven recent Reddit and Hacker News items from the last30days engine.
- Supplemental web research using academic, exchange, regulator, prop-firm,
  and official GitHub sources.
- Topics: SPY and 0DTE options, mechanical options strategies, Topstep and
  futures, MoonDev, ihytage, automated signals, Claude/AI trading,
  open-source trading systems, and quantitative trading.
- Two X requests remain under the local 25-request cap. Auto-recharge was not
  enabled.

All social claims remain context-only. No order path or production strategy was
changed.

## Bottom Line

The sweep did not reveal an easy or auditable daily-income strategy. The public
material is dominated by selected winners, alerts, leverage, course marketing,
and incomplete execution records.

The best new testable idea was volatility targeting on the already passing ETF
momentum family. It reduced recent drawdown materially but did not add stable
alpha across regimes. It is a possible risk overlay, not a replacement strategy
and not approved for the bot.

The best actionable engineering finding is to improve options replay fidelity:
minute NBBO, actual contract selection, liquidity-aware fills, Greeks, and
assignment/expiration handling. Underlying-only 0DTE backtests cannot answer
whether an option trade is profitable.

## Ranked Findings

### 1. Preserve diversified momentum as the lead edge

The frozen 12-month, top-two ETF rotation remains the strongest local candidate.
The social and quant sweep did not produce a stronger independently testable
family.

Volatility targeting is a legitimate risk-control technique, but the local
diagnostic showed a return-versus-drawdown trade rather than new expectancy.
The 8% target-volatility, 60-day estimator produced:

| Period | Baseline return | Overlay return | Baseline DD | Overlay DD | Baseline Sharpe | Overlay Sharpe |
|---|---:|---:|---:|---:|---:|---:|
| Through 2020 | 57.37% | 24.84% | 24.18% | 13.99% | 0.554 | 0.475 |
| 2021-2023 | 48.50% | 17.25% | 22.62% | 7.74% | 0.722 | 0.688 |
| 2024+ | 69.21% | 34.58% | 14.04% | 7.10% | 1.260 | 1.327 |

At doubled costs, the 2024+ overlay retained 33.86%, 1.304 Sharpe, and 7.27%
maximum drawdown. Because all periods are already consumed, this is diagnostic
only.

Research basis:

- [Smoothing volatility targeting](https://arxiv.org/abs/2212.07288)
- Local report: `~/.vibe-trading/reports/momentum-vol-target-lab.json`

Decision: do not alter the frozen momentum tracker. Preserve the overlay as a
future preregistered risk-budget challenger with new forward observations.

### 2. SPY level confluence is coherent but still unproven

Recent X posts repeatedly converged on:

- prior-day high and low;
- premarket high and low;
- opening-range state;
- first touch or breakout-retest;
- one-minute RSI or momentum confirmation;
- fixed bracket risk;
- one trade after a clean rejection or failed retest.

Representative posts:

- [shentrades first-touch checklist](https://x.com/shentrades/status/2080021529136660915)
- [PDL plus ORB failed-retest example](https://x.com/NoRiskNoPremium/status/2080433363132063791)

This is not a new passing edge. The project already replicated the nearest
mechanical families:

- SPY first-touch lab: 0 of 144 development configurations survived.
- MES failed-breakdown lab: 0 of 108 development configurations survived.
- Prior-day first touches were directionally interesting but had only 8, 13,
  and 4 trades across the reported regimes.
- The broader SPY ORB family previously failed holdout testing.

Decision: retain level, first-touch, and retest fields as forward telemetry.
Do not retune on consumed periods and do not add another live gate from these
posts.

### 3. 0DTE is an execution-data problem before it is a signal problem

The strongest independent evidence is cautionary:

- Recent research finds substantial 0DTE risk premia, but transaction costs and
  estimation error can make volatility-arbitrage Sharpe economically
  insignificant: [HKUST summary](https://bmvh162.ust.hk/bizinsight/2026/04/are-0dte-options-mispriced).
- Cboe reports that more than 95% of SPX 0DTE trades use limited-risk structures,
  but also emphasizes extreme near-expiry sensitivity:
  [Cboe 0DTE analysis](https://www.cboe.com/insights/posts/0-dt-es-decoded-positioning-trends-and-market-impact).
- The SEC's 2026 market-structure roundtable highlighted exercise and assignment
  risks near the close:
  [SEC roundtable transcript](https://www.sec.gov/files/transcript-options-roundtable-041626.pdf).

Public percentage gains are not reproducible without:

1. exact OCC contract and timestamp;
2. point-in-time bid, ask, quote age, and size;
3. entry and exit fill rules;
4. Greeks and implied volatility;
5. commissions and spread stress;
6. expiration and assignment handling;
7. all trades, including losses and no-fills.

Decision: do not promote SPY 0DTE calls, puts, credit spreads, or iron condors
from social evidence. The next meaningful options test requires historical
minute NBBO.

### 4. Topstep automation is possible, but profitability is not supplied

Recent posts emphasize leverage across many funded accounts, small daily
targets, and hard lockouts. Those are capital-structure and risk-management
ideas, not proof of signal expectancy.

Current official constraints matter:

- TopstepX API access is separately billed and has no sandbox:
  [TopstepX API Access](https://help.topstep.com/en/articles/11187768-topstepx-api-access).
- Automation must run from the trader's personal device; VPNs, VPSs, remote
  servers, latency exploitation, and certain unfair technology are prohibited:
  [Prohibited Conduct](https://help.topstep.com/en/articles/10296582-prohibited-conduct).
- The best day must remain below 50% of total profits for the applicable
  consistency path:
  [Topstep consistency](https://help.topstep.com/en/articles/8284208-consistency-at-topstep).
- ProjectX API automation is prohibited in a Live Funded Account even though
  other automated strategies may be permitted:
  [Live account parameters](https://help.topstep.com/en/articles/10657969-live-funded-account-parameters).

Decision: keep MES execution disabled. Do not purchase API access until a
one-contract MES strategy passes independent holdout, doubled-cost, Monte Carlo,
and forward-simulation gates.

### 5. MoonDev is an idea source, not evidence

The inspected posts included direct concerns about:

- backtests without full live trades;
- spread, slippage, latency, and news;
- strategies that passed backtest/OOS and then failed for a month;
- prediction-market liquidity and delayed-data traps.

The public code collection is useful for hypothesis discovery:
[TomData/Trading-Algos](https://github.com/TomData/Trading-Algos).

Decision: quarantine every MoonDev strategy as unverified external research.
Translate only complete rules into a preregistered local test. Never copy
claimed returns, API keys, order code, or parameter values directly.

### 6. ihytage is not reproducible

The search resolved `@ihytage` and a paid alerts product, but did not find a
complete rule set, audited trade ledger, or independently verifiable account
history. The recent X sample also contained copy-trading spam and accusations
that screenshots showed paper accounts.

Decision: reject as an edge source. No alert copying and no paid subscription
based on this evidence.

### 7. Claude and AI should audit and orchestrate, not predict freely

Recent AI-bot claims often omit benchmark choice, all losses, execution costs,
and data leakage controls. The reusable pattern is:

- deterministic features and strategy rules;
- point-in-time data;
- adversarial model review;
- immutable experiment registry;
- paper-first execution;
- hard risk controls outside the model;
- no ability for an LLM to modify and deploy its own strategy.

Decision: continue using Codex and Claude as builder/reviewer roles. The
self-learning loop may propose challengers, but cannot mutate production rules
or promote itself.

## Open-Source Shortlist

| Repository | Best use here | Decision |
|---|---|---|
| [goldspanlabs/optopsy](https://github.com/goldspanlabs/optopsy) | Option-chain strategy simulation, commissions, spread/liquidity slippage, early exits, risk metrics | Evaluate in an isolated adapter after historical option data is available |
| [nautechsystems/nautilus_trader](https://github.com/nautechsystems/nautilus_trader) | Deterministic event-driven research/live parity, detailed fill models, futures/options support | Architecture reference; migration is too large for the current edge question |
| [QuantConnect/Lean](https://github.com/QuantConnect/Lean) | Mature multi-asset engine, local research/backtest/live workflow | Benchmark infrastructure, not a source of alpha |
| [polakowo/vectorbt](https://github.com/polakowo/vectorbt) | Fast parameter screening and portfolio experiments | Screening only; require event-driven confirmation |
| [TomData/Trading-Algos](https://github.com/TomData/Trading-Algos) | MoonDev strategy idea archive | Untrusted hypothesis intake only |
| [Byte-Ventures/claude-trader](https://github.com/Byte-Ventures/claude-trader) | Multi-agent review and safety-pattern reference | Do not copy its crypto strategy or performance assumptions |

No third-party repository should be executed before license, dependency,
credential, network, order-routing, and prompt-injection review.

## What Was Rejected

- Astrology or narrative forecasts presented as SPY mechanics.
- Discord and alert-room promotions.
- Profit screenshots without full trade sequences.
- Multi-account leverage presented as strategy expectancy.
- Generic RSI/MACD/EMA indicator stacks without ablation or holdout evidence.
- AI-generated predictions without deterministic risk and execution controls.
- Gamma commentary without timestamped dealer-positioning inputs.
- 95% win-rate premium-selling claims that omit average loss and tail exposure.
- Polymarket profits that depend on latency, thin books, or settlement quirks.

## Next Experiments

1. Acquire or identify a no-surprise-cost source of historical SPY option minute
   NBBO before any further 0DTE strategy claims are tested.
2. Build a read-only option replay adapter around the existing lifecycle schema,
   using Optopsy only if it passes dependency and semantics review.
3. Replay the frozen SPY level candidates on actual option quotes, with calls
   and puts separated and 0DTE compared against 1DTE and 3-7DTE contracts.
4. Keep the 8%/60-day volatility-target overlay as a forward-only risk
   challenger; do not replace the canonical momentum lane.
5. Continue the existing momentum, turn-of-month, PEAD, options, and MES shadow
   logs until their predefined evidence gates are met.
6. Keep Topstep MES and all Alpaca option order paths unchanged until the
   relevant lane reaches the 9/10 promotion threshold.

## Verification

- X intake tests, including non-SPY search isolation: passed.
- Volatility-target no-lookahead and exposure-cap tests: passed.
- Quant lab execution: passed and wrote
  `~/.vibe-trading/reports/momentum-vol-target-lab.json`.
- No live order client was imported or called.
- No scheduled execution task was enabled.
