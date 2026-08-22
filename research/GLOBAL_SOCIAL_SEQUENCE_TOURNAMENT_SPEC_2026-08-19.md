# Global Social Sequence Tournament

Date: 2026-08-19  
Status: frozen before simulation  
Authority: research only; no order submission, configuration, or promotion authority

## Purpose

Test public, mechanically translatable trading sequences gathered from YouTube,
X, Reddit, Chinese-language sources, and other public educational pages. A
trader's location or popularity is not evidence. Rules without enough detail to
reproduce are recorded as exclusions instead of being completed by hindsight.

## Intraday Families

The following eight families are evaluated independently on SPY, QQQ, and MES:

1. Completed 15-minute opening-range breakout, retest, and continuation.
2. One-hour confirmation beyond the prior-day high/low, then a 5-minute retest.
3. Prior-day liquidity sweep, market-structure shift, FVG, and FVG-midpoint retest.
4. First prior-day-level touch with RSI extreme and close back inside.
5. Strong gap beyond the prior-day range, opening hold, and first EMA pullback.
6. Prior-day-level break/retest aligned with the 8/21 EMA trend.
7. Efficient opening drive followed by the first VWAP pullback.
8. Multi-indicator extreme followed by a reversal confirmation bar.

Each family is tested with fixed 1R, 1.5R, 2R, and 3R exits. These exit variants
are sensitivity tests, not rules attributed to the source. That produces 96
intraday market-sequence trials.

Common mechanics: completed 5-minute bars, next-bar-open execution, one trade
per session, structural stop, stop-first same-bar resolution, 60-minute maximum
hold, and no entries after 14:30 ET. SPY/QQQ use $10,000 notional with four basis
points baseline round-trip friction and eight basis points stress. MES uses one
contract with $4.98 baseline round-trip friction and $9.96 stress.

## Daily Families

Five daily families are evaluated on SPY and QQQ, for 10 additional trials:

1. Close above the 200-day SMA, otherwise cash.
2. 5-day SMA above 20-day SMA, otherwise cash.
3. Connors/Alvarez Double 7: above SMA200, buy a 7-day closing low, exit a
   7-day closing high.
4. RSI(2) mean reversion above SMA200: enter below 10, exit above 70.
5. Chinese-language multi-moving-average majority translation: enter when at
   least five of six trend votes are positive and exit at two or fewer.

Signals are formed after the close and executed at the next open. Round-trip
friction is four basis points, doubled under stress.

## Governance

The source ledger contains the exact source, translation, ambiguity, and
exclusion status. The prior documented effective attempt count is 803. This
tournament adds 106 trials, raising the effective count to 909 and applying a
one-sided Bonferroni threshold of `0.05 / 909`.

Only the first 70% of each instrument's history is opened. That development
segment is divided into three chronological regimes. The next 15% selection and
last 15% final holdouts remain sealed by this program.

A development survivor requires at least 20 completed trades in every regime,
positive expectancy and profit factor above 1.0 in every regime, positive
doubled-friction aggregate expectancy, and an aggregate one-sided p-value below
the corrected threshold. A survivor remains a shadow hypothesis because these
datasets and concept families have prior research exposure.

