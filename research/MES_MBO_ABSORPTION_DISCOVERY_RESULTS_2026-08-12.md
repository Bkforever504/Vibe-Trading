# MES MBO Absorption Discovery Results

Date: 2026-08-12
Status: failed; exact hypothesis retired
Execution: disabled; research only

## Data and Integrity

- Discovery sessions: 2026-07-16 and 2026-07-20 UTC.
- Combined acquisition estimate: $2.6234.
- Estimated Databento credits remaining: $19.64.
- Events replayed: 27,945,794 total; 19,224,892 RTH.
- Both sessions passed every book-integrity gate.
- All 9,360 five-second RTH windows had valid, non-crossed reconstructed BBO.
- Zero missing-order events, duplicate adds, oversize cancels, or bad-book flags.

## Frozen Hypothesis Result

The preregistered three-way conjunction required same-direction extreme passive
fill imbalance, cancel/add pressure, and top-of-book depth imbalance. Entry was
at the next executable BBO and exit was 30 seconds later at the opposing BBO.

| Metric | Base costs | Stressed costs |
|---|---:|---:|
| Signals | 5 | 5 |
| Bullish / bearish | 3 / 2 | 3 / 2 |
| Total P&L | -$16.15 | -$41.05 |
| Expectancy | -$3.23 | -$8.21 |
| Win rate | 20.0% | 0.0% |
| Profit factor | 0.135 | 0.000 |

Every promotion gate failed. The exact thresholds, conjunction, and 30-second
horizon are retired and must not be retuned on these consumed sessions.

## Interpretation

The data pipeline is valid; the proposed edge is not. Extreme same-direction
book replenishment and passive fills were too rare and did not produce positive
executable markouts. This result does not imply that MBO contains no useful
information, only that this particular absorption definition failed.

## Next Boundary

Do not buy more data or search variants immediately. A materially different
mechanism must be preregistered first, then tested on untouched sessions. The
remaining raw data can be used for engineering, feature extraction, and data
quality work, but not to select a profitable threshold and report it as new
evidence.
