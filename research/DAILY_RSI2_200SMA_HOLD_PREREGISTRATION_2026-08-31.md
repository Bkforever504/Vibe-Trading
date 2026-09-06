# Daily RSI(2) / 200-SMA hold challenger

This is a source-matched transcription of the supplied daily futures rules, frozen before the first run.

- Instruments: continuous-yahoo `ES=F` and `NQ=F` daily bars, with explicit roll/settlement limitations reported.
- Entry: buy the completed daily close only when RSI(2) is below 10 and that close is above the 200-day simple moving average.
- Exit: sell a completed daily close when RSI(2) exceeds 70, or after ten subsequent sessions, whichever comes first.
- Long only, no stop, one notional unit in the underlying-return research. No futures dollars, leverage, margin, options premiums, fills, or slippage are represented.
- Fixed split: entries through 2024-12-31 are in sample; entries on or after 2025-01-01 are out of sample.
- A positive result can at most justify a new forward-shadow implementation after a point-in-time futures-roll and cost model. It has no ranking or execution effect.
