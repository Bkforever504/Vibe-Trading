# SPY Mastery Deep Research - 2026-07-16

## Executive conclusion

There is no independently verified social-media leaderboard that identifies a
single "best SPY trader" or a secret indicator. The defensible competitive
edge is a complete stack:

1. Trade SPY only when the intraday regime fits a defined setup.
2. Require price confirmation at objective levels instead of predicting.
3. Select a contract whose delta, spread, and price fit the expected move.
4. Execute with spread-aware limit logic rather than paying any available
   market price.
5. Manage exits using both underlying structure and executable option quotes.
6. Learn separately by setup, regime, contract, time bucket, and execution
   policy so that one strategy's results cannot contaminate another.

The repo already has much of this architecture. The largest missing research
strategy is the published SPY Noise Area intraday momentum model. The largest
live execution weakness is that single-leg Flip entries and exits still use
market orders. Both should be addressed in shadow trials before live behavior
changes.

No study or trader can guarantee daily profits, perfect entries, perfect
exits, or exponential returns. The goal is positive expectancy after spreads,
slippage, rejected fills, and drawdowns.

## Research coverage and limitations

Research included:

- Primary sources from SEC DERA, Cboe, and the Options Industry Council.
- SPY-specific SSRN and academic research.
- Current Reddit discussions and publicly indexed X, YouTube, TikTok,
  Instagram, and Threads results.
- The X accounts and screenshots supplied by the user, including ORB,
  liquidity-sweep, premium-level, and SPY scalp claims.
- The existing repo, research registry, shadow loggers, execution path, and
  learning reports.

Collection limits:

- The `last30days` X collector returned HTTP 403 on this run.
- TikTok blocked direct crawling.
- The dedicated TikTok, Instagram, and Threads collector is not configured.
- YouTube search results were accessible through public indexing, but creator
  claims generally lacked machine-verifiable fills and complete trade logs.

No inaccessible-platform claim is treated as verified evidence. Social posts
are discovery inputs only unless their rule can be specified and tested using
point-in-time market data.

## Evidence hierarchy

### Tier 1: market structure and execution facts

1. **Expected move is a magnitude estimate, not a direction signal.** OIC's
   Rule of 16 uses `spot * IV / sqrt(252)` to estimate one daily standard
   deviation. ATM 0DTE options concentrate gamma and theta, so a correct
   directional idea can still lose if the move arrives too slowly.
   Source: [Options Industry Council](https://www.optionseducation.org/news/may-keytakeaways).

2. **Limit-order behavior is part of the edge.** SEC DERA found frequent and
   significant savings from non-marketable customer limit orders in SPXW 0DTE
   options. The paper also warns that OPRA trade and quote events must be
   correctly sequenced before measuring execution quality.
   Source: [SEC DERA](https://www.sec.gov/about/divisions-offices/division-economic-risk-analysis/staff-papers-analyses/hope-reasonable-price_customer-use-limit-orders-0dte-market).

3. **GEX should not be a directional oracle.** Cboe estimated net 0DTE market
   maker gamma hedging at no more than about 0.2% of SPX daily liquidity in its
   aggregate study. Strike levels may be useful context, but broad dealer-flow
   stories do not deserve hard-veto authority.
   Source: [Cboe](https://www.cboe.com/insights/posts/0-dt-es-decoded-positioning-trends-and-market-impact/).

### Tier 2: transparent research candidates

1. **Noise Area plus VWAP intraday momentum.** Zarattini, Aziz, and Barbon
   calculate time-of-day noise boundaries from the prior 14 trading days,
   adjust for overnight gaps, enter only when price moves outside the band at
   scheduled checkpoints, and use VWAP and the boundary as dynamic exits. The
   paper reports strong long-horizon SPY backtest results after estimated
   costs. It remains a backtest, not an audited options strategy.
   Source: [SSRN 4824172](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4824172).

2. **ORB can have edge, but its payoff is regime- and execution-sensitive.**
   A public 303-trade SPY 0DTE backtest reported a 41.3% win rate, about 2:1
   average payoff, 1.40 profit factor, and 7.6% max drawdown using a 5-minute
   ORB. It is self-reported and does not prove live fills, but it demonstrates
   that win rate alone is not the objective.
   Source: [Reddit full backtest](https://www.reddit.com/r/options/comments/1rkx5vr/0dte_opening_range_breakout_strategy_on_spy_full/).

3. **Regime filtering may improve ORB, but recent estimates are fragile.** A
   2026 simulation of SPY 0DTE debit-spread ORB reported improvement after
   weekday, VIX, and macro-event filters. Its fixed 25% loss / 50% profit
   structure requires a 66.7% break-even win rate, so the claimed filtered
   edge is especially sensitive to slippage and sample selection.
   Source: [SSRN 6355218](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6355218).

### Tier 3: social discovery candidates

Current social discussion repeatedly promotes:

- 5-, 15-, or 30-minute ORB with a completed close and retest.
- Prior-day high/low or weekly-level sweeps followed by a close back inside.
- VWAP reclaim or rejection with volume and market breadth confirmation.
- Trading the morning and avoiding midday chop.
- Taking partial profits while leaving a smaller runner.
- Using premium-by-strike levels and order flow as context.

These are testable setup definitions, not proof. Current Reddit discussion is
also split on an 11:00 ET cutoff: many traders report weaker afternoon results,
while others report their best moves after 11. The bot's own time-bucket data
must decide this question; social consensus cannot.

## Ranked SPY strategy families

### 1. Noise Area momentum plus VWAP

Evidence grade: B for SPY underlying, D for direct 0DTE execution.

Candidate rules:

1. Build minute-specific upper and lower noise boundaries from the prior 14
   completed SPY sessions.
2. Adjust the boundary for overnight gaps exactly as preregistered.
3. Evaluate entries at fixed checkpoints, initially every 30 minutes.
4. Long only when SPY closes above the upper band and VWAP; short only below
   the lower band and VWAP.
5. Use the tighter of VWAP and the relevant band as the structural exit.
6. Compare 0DTE ATM, 0.55-0.70 delta ITM, one-strike OTM, and debit spreads
   using contemporaneous ask-at-entry and bid-at-exit quotes.

Why it matters: this is the strongest SPY-specific research lead that is not
already implemented in the repo.

### 2. Confirmed ORB continuation and retest

Evidence grade: C.

Candidate variants must remain separate:

- 5-minute ORB breakout and retest.
- 15-minute ORB breakout and retest.
- 30-minute continuation after a completed opening candle.
- A-plus alignment when the breakout also clears prior-day high/low.

Required context fields:

- Opening-range width as a fraction of expected move.
- Breakout candle range versus ATR and close-location value.
- Expected move already consumed at entry.
- VWAP side, breadth, realized/implied volatility regime, and macro-event flag.
- Retest age, depth, hold quality, and distance to the next objective level.

Do not combine the variants into one sample. Their timing and false-break
profiles differ.

### 3. Failed breakout and liquidity-sweep reversal

Evidence grade: D until forward-tested.

Candidate rules:

1. Price trades through PDH, PDL, prior-week high/low, or an ORB boundary.
2. The same or next completed bar closes back inside the level.
3. Directional close-location and volume show rejection rather than acceptance.
4. Entry occurs only after confirmation, not on the initial wick.
5. Initial target is VWAP or the next objective level; stop is beyond the
   sweep extreme plus a preregistered volatility buffer.

This is a distinct mean-reversion setup and must not share a learner with ORB
continuation.

### 4. VWAP trend pullback and reclaim

Evidence grade: C as context, D as a standalone option strategy.

VWAP should define acceptance and dynamic risk, not automatically generate a
trade. The higher-quality candidate combines:

- Price on the correct side of VWAP.
- A rising/falling VWAP and aligned 20/50 EMA slope.
- Pullback that holds VWAP or the prior impulse level.
- Breadth and volume that confirm the index move.
- No chase after most of the implied move has already been consumed.

### 5. Defined-risk range or premium-selling structures

Evidence grade: C for strategy class, separate from Flip.

Range-day premium selling, condors, and debit/credit spreads have different
payoffs and tail risks from directional long 0DTE flips. Keep them in the
options-bot learner. Do not pool their results with Flip Bot entries.

## Contract-selection research

The current Flip Bot buys the nearest ATM contract. It already records ATM and
up to two OTM shadow alternatives, but does not compare a delta-targeted ITM
contract.

Preregister a four-lane tournament for each directional setup:

1. Nearest ATM.
2. ITM contract closest to 0.60 absolute delta, acceptable range 0.55-0.70.
3. One strike OTM.
4. Narrow debit spread with the long leg near 0.55-0.65 delta.

Promotion metrics:

- Ask-to-bid executable return, not midpoint return.
- Fill opportunity and time-to-fill at each proposed limit.
- Spread cost as a percentage of premium.
- MFE, MAE, capture efficiency, profit factor, expected shortfall, and
  drawdown.
- Robustness after removing the top 5% of winners.

Far OTM lottery contracts should fail unless forward data proves positive
expectancy after the full spread.

## Exit architecture

There is no knowable "perfect exit." The correct objective is to maximize
expected captured return while bounding tail loss.

The challenger set should compare:

1. Current fixed target, stop, and profit ratchet.
2. Underlying structural stop at ORB/retest/VWAP invalidation plus a
   catastrophic option-premium stop.
3. Partial at a preregistered R multiple, then trail the runner behind the
   latest accepted level or VWAP.
4. Time stop when the underlying has not extended within a fixed number of
   bars.
5. Directional-conflict exit already captured by the shadow evaluator.

Every policy must use the same point-in-time path so comparisons are paired,
not separate anecdotes.

## Execution architecture

This is the most important current engineering gap.

Observed repo behavior:

- Single-leg entries and exits are submitted as market orders in
  `strategies/flip_bot.py`.
- Spread entries are limit orders, but spread exits are market orders.
- The bot checks spread width before entry and records quote age.
- Point-in-time quotes are explicitly labeled
  `indicative_modified_not_opra_nbbo`.

Research upgrade, shadow first:

1. Record the BBO, midpoint, spread, quote age, size, and underlying price when
   an order decision is made.
2. Simulate passive limits at midpoint, one tick through midpoint, and a
   bounded marketable limit.
3. Allow no more than two timed reprices and a strict maximum chase.
4. Cancel an entry if the underlying invalidates before fill.
5. For risk exits, allow immediate marketable-limit behavior; do not wait for
   a passive fill while loss is expanding.
6. Measure fill opportunity conservatively from licensed OPRA/NBBO data before
   changing live order behavior.

Free indicative Alpaca quotes can support telemetry, but they are not enough
to prove NBBO execution quality.

## What the repo already has

| Capability | State |
| --- | --- |
| Live 5-minute ORB retest | Built |
| 15-minute ORB retest | Shadow challenger built |
| Prior-level sweep reversal | Shadow challenger built |
| 30-minute continuation / The Strat | Shadow built |
| Expected-move normalization | Built |
| ORB ATR and dislocation telemetry | Built |
| VWAP / 50 EMA trend setup | Built |
| Prior-day and prior-week levels | Built |
| GEX and premium-level context | Built, advisory only |
| Contract ATM/OTM alternatives | Built, incomplete without ITM delta lane |
| Executable ask-entry / bid-exit shadow scoring | Built |
| MFE, MAE, ratchet, and exit-policy comparison | Built |
| Missed-banger and blocker-drought review | Built |
| Noise Area plus VWAP model | Missing |
| Licensed OPRA/NBBO adapter | Missing |
| Passive-limit execution tournament | Missing |
| Setup-specific SPY mastery scorecard | Incomplete |

## Preregistered build order

### Phase A: evidence-only, no live changes

1. Implement the SPY Noise Area plus VWAP strategy as a pure shadow lifecycle.
2. Add delta-targeted ITM and debit-spread contract challengers.
3. Add a passive-limit fill simulator with conservative no-fill accounting.
4. Create a setup-specific SPY scorecard for ORB 5m, ORB 15m, ORB 30m,
   sweep reversal, VWAP trend, and Noise Area momentum.
5. Record macro-event, time bucket, expected-move, volatility, breadth, and
   trend/range regime on every lifecycle.

### Phase B: evidence threshold

Minimum review threshold per setup:

- 100 completed executable-quote paths.
- At least 20 distinct trading days.
- At least 30 chronological out-of-sample paths.
- Positive full-sample and holdout expectancy after spreads.
- Positive or stable performance after removing the top 5% of winners.
- No single day contributes more than 20% of total profit.
- Human review and approval.

### Phase C: bounded live promotion

Promote only one variable at a time:

- One setup or one contract policy.
- One-contract initial cap.
- Existing kill switch, reconciliation, daily-loss, liquidity, and manual
  reset controls unchanged.
- Automatic rollback to shadow on execution degradation, opportunity drought,
  or holdout expectancy failure.

## Rejected upgrades

- Copying social-media entries or reported win rates.
- Treating screenshots as complete trade evidence.
- A universal 11:00 ET ban before the bot's own time buckets support it.
- GEX, order flow, AI forecasts, or sentiment as independent hard vetoes.
- Averaging down 0DTE losers.
- Far OTM contracts selected because their percentage gains look larger.
- Loosening live safety gates merely to collect data faster.
- Allowing a generated strategy or self-improving loop to self-promote.

## Bottom line

The system is materially closer to a serious SPY research and execution stack
than most retail bots, but it is not yet a mastered or proven money printer.
The next competitive jump is not more veto indicators. It is the combination
of a genuinely new SPY-specific signal candidate, setup-isolated evidence,
better contract selection, and measured limit-order execution.
