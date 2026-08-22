# Green-Day HTF/LTF Reconstruction Results

Run date: 2026-07-25

## Verdict

No tested HTF/LTF confluence is ready for live execution.

The current-cap Flip cohort is genuinely profitable in its tiny observed sample:
12 closed SPY trades, 8 winners, 4 losers, +$2,332 net, 66.7% win rate, and
historical report profit factor 4.95. That result does not generalize to the
historical 10:30 ET replay. The original 9/9 VWAP/EMA setup was:

- mildly positive in 2022-2023;
- negative in 2024; and
- slightly negative in the already-consumed 2025+ period.

Daily and weekly alignment made the 10:30 result worse, not better.

## Actual Trade Reconstruction

### Flip Bot

| Cohort | Trades | Wins | Losses | Net |
|---|---:|---:|---:|---:|
| Current contract cap, 1-5 | 12 | 8 | 4 | +$2,332 |
| Pre-hardening oversized trade | 1 | 0 | 1 | -$11,557.50 |

The eight current-cap wins cluster in:

- June 29-30 CALLs at 10:30 ET;
- July 1 CALL at 10:30 ET;
- July 2 PUTs at 10:30 ET; and
- one July 6 CALL at 10:30 ET.

The same July 6 signal also produced a losing duplicate position. Later July 7,
16, and 17 signals lost. This is evidence of a short green regime, not proof of
a stable strategy.

Weekly alignment selected seven actual trades: five wins and two losses.
Daily alignment selected only one trade, a loss. The July 2 PUT winners were
counter to bullish weekly/monthly states, so a strict HTF veto would have
removed three of the largest observed winners.

Only four actual dates could be reconstructed exactly from the local IEX minute
cache. The cache reproduced the current 9/9 direction on July 6 and July 16,
but older green dates had insufficient point-in-time bars. Catalyst text was
not substituted for missing telemetry.

### Options Bot

After deduplication there are 11 closed records. Eight have resolvable
closing-reason outcomes: four wins and four losses. Most lack fill-derived P&L,
so no dollar expectancy was calculated. The sample is too small and
heterogeneous to infer an HTF edge.

## Historical SPY Replay

Data: 2022-01-03 through 2026-07-17 Alpaca IEX one-minute cache.

Coverage gate: 467 of 1,137 sessions had every minute from 09:30 through 13:44
ET. Missing bars were never filled. Returns below are directional underlying
basis points after 2 bps round-trip friction, not option returns.

### Primary 10:30 ET Setup

| Window | Trades | Expectancy | Win rate | PF |
|---|---:|---:|---:|---:|
| 2022-2023 | 51 | +1.90 bps | 62.8% | 1.14 |
| 2024 | 8 | -5.52 bps | 25.0% | 0.27 |
| 2025+ consumed | 61 | -0.87 bps | 52.5% | 0.93 |

No daily/weekly/monthly alignment variant was positive in all windows.

### Noon Research Lead

The fixed 12:00 ET `daily_aligned` variant was positive on the 60-minute mark
in all windows:

| Window | Trades | Expectancy | PF | 95% block CI |
|---|---:|---:|---:|---:|
| 2022-2023 | 26 | +2.54 bps | 1.24 | -3.83 to +12.88 |
| 2024 | 3 | +10.29 bps | 9.37 | unavailable |
| 2025+ consumed | 26 | +5.64 bps | 1.59 | -11.08 to +17.00 |

It fails promotion:

- only three selection trades;
- both measurable confidence intervals cross zero;
- 2025+ expectancy becomes -1.39 bps after removing the best 1%;
- the fixed 25 bps bracket loses in development and 2025+; and
- holding to 13:45 loses in development.

This can become a new forward-only shadow challenger. It cannot be retuned on
the consumed history.

## Shadow Logger Overlay

The source contained 456 completed lifecycle outcomes. Compatible daily caches
covered 338 `ltf_only` episodes across seven trading days.

| Variant | Episodes | Episode expectancy | Clustered days | Clustered expectancy |
|---|---:|---:|---:|---:|
| LTF only | 338 | -3.26% | 7 | -3.26% |
| Daily aligned | 102 | -3.12% | 7 | -7.15% |
| Weekly aligned | 133 | -3.36% | 7 | -2.81% |
| Daily + weekly aligned | 54 | +0.54% | 6 | +5.10% |
| All three aligned | 48 | -2.07% | 5 | +1.82% |

Daily+weekly alignment is the only positive episode-level variant, but it has
six independent dates, a confidence interval spanning zero, and -1.70%
expectancy after removing the best 1%. It is not promotion evidence.

## Higher-Timeframe Strategy Family

The separate, rerun higher-timeframe rotation lab remains stronger than the
intraday confluences:

| Variant | Dev expectancy | 2023 selection | 2024+ final | Final PF | Final at 3x costs |
|---|---:|---:|---:|---:|---:|
| Weekly trend baseline | +18.5 bps | +67.8 | +39.0 | 1.42 | +19.0 |
| Weekly RVOL + dual trend | +64.2 | +38.4 | +58.9 | 1.67 | +38.9 |
| Monthly trend baseline | +225.1 | +263.3 | +297.7 | 3.51 | +277.7 |
| Monthly RVOL 1.25 | +36.1 | -130.4 | +109.3 | 1.40 | +89.3 |

The monthly price-trend baseline is the best historical lane. Volume does not
improve it. It remains paper-only because the 29-symbol current universe has
survivorship bias and the 2024+ period is already consumed.

This result is directionally consistent with published evidence that
time-series momentum persists over multi-month horizons, while published SPY
intraday momentum research concerns a different first-half-hour-to-last-half-
hour relationship, not this VWAP/EMA setup:

- https://www.aqr.com/Insights/Research/Journal-Article/Time-Series-Momentum
- https://www.aqr.com/Insights/Research/Journal-Article/A-Century-of-Evidence-on-Trend-Following-Investing
- https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2440866

## Confidence Scores

| Item | Confidence |
|---|---:|
| Actual Flip accounting, current-cap cohort | 8.5/10 |
| Stable 10:30 VWAP/EMA edge | 3.0/10 |
| Noon daily-aligned research lead | 4.5/10 |
| Daily+weekly shadow confluence | 3.5/10 |
| Monthly rotation historical edge | 6.5/10 |
| Any lane ready for live promotion | 2.0/10 |

## Decision

1. Do not change the live Flip or options strategies from this result.
2. Add a forward-only noon daily-aligned shadow lane with frozen rules.
3. Keep monthly rotation in paper forward tracking.
4. Repair options fill-derived lifecycle P&L before options learning can grade
   profitability.
5. Obtain fuller historical minute data before re-evaluating intraday edge.
