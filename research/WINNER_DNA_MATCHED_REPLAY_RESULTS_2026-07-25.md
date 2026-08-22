# Winner-DNA Matched Replay Results

Run date: 2026-07-25

## Answer

We can replicate winning trades, and this lab now does it without hiding the
losing twins.

The current-size Flip bot had eight realized winners. Five were the same
10:30 ET bullish VWAP/EMA pullback archetype and three were the bearish mirror.
Each archetype was matched against every production-parity historical signal
from 2022 onward.

The source has 796 sessions complete enough for the 10:30 test. Only 204
sessions produced the frozen 9/9 signal. The previously reported +0.33 bps is
the combined 2022-2023 development partition (86 signals), not the full-period
result. The combined 2024 result was -0.46 bps, 2025+ was -0.18 bps, and all
204 signals together were effectively flat.

## Actual Twins

| Archetype | Winner seeds | Actual twins | Wins | Losses | Net P&L |
|---|---:|---:|---:|---:|---:|
| Bull 10:30 | 5 | 6 | 5 | 1 | +$935.50 |
| Bear 10:30 | 3 | 4 | 3 | 1 | +$1,602.50 |

The actual sample looks excellent but spans only a handful of dates. One
matching loss exists in each family, so neither rule is synonymous with a win.

## Historical Losing-Twin Replay

Outcome: 60-minute directional SPY underlying return after 2 bps friction.
This is not an option-return simulation.

| Archetype | Matches | Win rate | Expectancy | PF | Trimmed expectancy | 95% block CI |
|---|---:|---:|---:|---:|---:|---:|
| Bull 10:30 | 108 | 55.6% | -2.97 bps | 0.78 | -4.32 bps | -6.89 to +2.02 |
| Bear 10:30 | 96 | 60.4% | +3.33 bps | 1.31 | +1.96 bps | -1.97 to +10.56 |

### Bull Verdict

Rejected. It was negative in development and the consumed 2025+ diagnostic
period. The actual green streak did not generalize.

### Bear Verdict

Research lead only. It was positive in 2022-2023 and 2025+, but failed in 2024
with -4.81 bps expectancy and PF 0.62. Its overall confidence interval crosses
zero. It is not eligible for live or paper-order promotion.

## Options Bot

Only one deduplicated closed options trade currently has compatible
fill-derived P&L and is a winner. Ten closed records remain excluded rather
than treating text-based P&L estimates as truth. The options bot needs at least
five verified winners before a winner archetype can be responsibly inferred.

## Decision

1. Do not restore the bullish 10:30 rule from its green streak.
2. Keep the bearish 10:30 archetype as a frozen research lead.
3. Collect a new forward-only sample with point-in-time option NBBO before
   considering promotion.
4. Run this same winner-versus-losing-twin method whenever a new verified
   winner is recorded.

Source artifact:
`data/winner_dna_matched_replay_results.json`
