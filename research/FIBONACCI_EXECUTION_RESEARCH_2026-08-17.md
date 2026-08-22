# Fibonacci Execution Research - 2026-08-17

## Current Research

The `last30days` engine was run for July 18 through August 17, 2026. It
retrieved 42 items, but X and YouTube were unavailable and the returned Reddit
clusters were mostly generic trading discussions rather than Fibonacci
evidence. Those generic posts were not treated as strategy evidence.

Supplemental current practitioner search consistently described Fibonacci as
an area-of-interest tool: identify a completed impulse, wait for structure and
trend confirmation, then either rest a retest limit in the 0.618-0.705 area or
wait for a rejection. These are hypotheses, not verified edge claims.

Primary references remain more restrained:

- [Fidelity](https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/fibonacci-retracement)
  defines retracements from two extreme points and lists 23.6%, 38.2%, 50%,
  and 61.8% as possible support/resistance areas.
- [CME Group](https://www.cmegroup.com/education/courses/technical-analysis/fibonacci-retracements-and-extensions.hideSubnav.educationIframe.html?hideAddThisExt=y&hideFooter=y&hideHeader=y&hideRightRail=y)
  describes the levels as alerts and says Fibonacci should be combined with
  other evidence rather than used in isolation.
- The peer-reviewed three-equity-market study
  [DOI 10.1016/j.eswa.2021.115893](https://doi.org/10.1016/j.eswa.2021.115893)
  rejects Fibonacci zones as a standalone profitable rule.

## Execution Protocol Added

Every flip-bot setup now records a shadow-only execution plan when all of the
following are true:

- the impulse endpoints were confirmed causally by an ATR-ZigZag;
- the impulse is at least 2 ATR;
- price rejected the golden zone on a completed bar;
- EMA20, EMA50, and EMA20 slope align with the impulse;
- reward/risk and target-to-cost proxy clear their fixed floors.

The benchmark rests at the underlying 0.618 reference for one completed bar,
never chases or converts to market, cancels on expiry/invalidation/stale data,
and targets the prior impulse extreme. It cannot submit orders, block a
production entry, or change size. Underlying reference prices are explicitly
not option premium limits.

## Preregistered Tournament

The locked V4 tournament compared:

- exact 0.618 limits with 1-, 3-, and 6-bar TTLs;
- 0.650, 0.705, and 0.786 limits with 3-bar TTLs;
- a non-Fibonacci 0.550 placebo with a 3-bar TTL.

Development was 2020-2023, selection was 2024, and final holdout was 2025
onward. Final data was not used to choose a candidate. QQQ and IWM were the
external checks. Costs were tested at 2 bps round trip and doubled. Same-bar
ambiguity was stop-first.

## Verdict

No variant passed the development and selection gates, so no variant was
selected and the final promotion gate remained locked.

| Variant | SPY development expectancy | SPY 2024 expectancy | SPY final expectancy | Final trades |
|---|---:|---:|---:|---:|
| 0.618 / 1 bar | -0.349R | -0.226R | +0.336R | 24 |
| 0.618 / 3 bars | -0.316R | -0.142R | -0.141R | 53 |
| 0.618 / 6 bars | -0.252R | -0.226R | -0.189R | 73 |
| 0.650 / 3 bars | -0.304R | -0.206R | -0.102R | 52 |
| 0.705 / 3 bars | -0.250R | +0.148R | -0.015R | 46 |
| 0.786 / 3 bars | -0.229R | -0.373R | -0.043R | 36 |
| placebo 0.550 / 3 bars | -0.221R | -0.090R | -0.067R | 54 |

The recent 0.618 one-bar SPY slice had 62.5% winners and 1.689 profit factor,
but only 24 trades. It fell to +0.086R expectancy and 1.143 profit factor at
doubled cost, while QQQ final expectancy was -0.055R. It is a shadow research
candidate, not an execution edge.

The execution lesson is useful even though the ratio failed promotion: short
TTL and no chase avoided the much worse performance created by stale three-
and six-bar orders. The bot should retain that order discipline, but Fibonacci
must remain telemetry until forward evidence changes the result.
