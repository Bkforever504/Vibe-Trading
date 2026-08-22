# Global Social Sequence Tournament Results

Date: 2026-08-19  
Status: completed development-only research  
Trials: 106 new; 909 effective attempts including prior documented research  
Corrected one-sided alpha: 0.0000550055  
Survivors: 0

## Research Coverage

The frozen ledger evaluated mechanically stated ideas from Reddit, YouTube, X
attachments supplied in the research thread, and Chinese-language Bilibili
sources. Web searches for Africa-based personalities were also reviewed. Those
results generally exposed marketing, courses, or wealth claims without a full
entry/stop/exit/timing rule, so no rule was invented or attributed to a region.

The source ledger is
`research/social_strategy_intake/global_social_sequence_sources_2026-08-19.json`.

## Intraday Verdict

Every intraday family's best sufficiently sampled variant was negative after
baseline friction on SPY, QQQ, and MES. Selected best variants:

| Market | Best sampled family | Variant | Trades | Net expectancy | PF |
|---|---|---:|---:|---:|---:|
| SPY | EMA 8/21 prior-level break/retest | 3R | 260 | -$2.68 per $10k trade | 0.66 |
| QQQ | 15-minute OR breakout/retest | 3R | 690 | -$1.15 per $10k trade | 0.93 |
| MES | gap continuation/EMA pullback | 1R | 217 | -$3.10 per contract | 0.81 |

The sweep/MSS/FVG sequence was also negative on all three instruments. MES had
only 26 development occurrences, while SPY and QQQ had 71 and 78. This does not
support promoting the social sequence to either bot.

## Daily Findings

Daily mean-reversion families were stronger but did not clear governance:

| Market | Family | Trades | Net expectancy | PF | p-value | Regime issue |
|---|---|---:|---:|---:|---:|---|
| QQQ | Double 7 | 68 | $71.54 per $10k trade | 1.81 | 0.02345 | first regime has 19 trades |
| QQQ | RSI(2) above SMA200 | 106 | $61.36 | 1.80 | 0.02742 | corrected significance fails |
| SPY | Double 7 | 66 | $57.43 | 2.02 | 0.01503 | middle regime expectancy -$5.68 |
| SPY | RSI(2) above SMA200 | 126 | $46.11 | 1.97 | 0.00463 | middle regime expectancy -$1.21 |

QQQ Double 7 is the cleanest forward-shadow candidate because all three regime
expectancies were positive. It is not a verified edge: its p-value is hundreds
of times above the corrected threshold, it is one trade short of the minimum in
the first regime, and the selection/final holdouts remain sealed.

## Decision

No production or paper-execution rule is promoted. Keep QQQ Double 7 and QQQ
RSI(2) as declared forward-shadow challengers only. The next defensible evidence
is live point-in-time shadow collection, not another exit or threshold search on
the same history.

