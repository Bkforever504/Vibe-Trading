# Course-Intelligence Intake: Top YouTube Trading Course Material

Date: 2026-07-19
Method: yt-dlp transcript harvest of 8 highest-view course/strategy videos
across 8 families (ICT, SMB-style day trading, VWAP, supply/demand, volume
profile, iron condor, turtle trend following, price action). Transcripts in
`data/course_transcripts/` (local only, not committed). Research only.

## Extracted Mechanical Rules and Status

| # | Source family | Mechanical core | Status vs our testing |
|---|---|---|---|
| 1 | ICT concepts (9-min, 556K views) | Liquidity sweeps, FVGs, order blocks | REJECTED - sweep fade and FVG failed development on MES (`data/mes_smc_results.json`) |
| 2 | SMB-style range breakout (106K) | Opening/range breakout, stop at half-range, measured-move target | REJECTED - ORB family failed final test (4,800-config search) |
| 3 | VWAP band fade (Chris Drysdale) | Fade rejection at VWAP +/-1 sigma band back to VWAP, only on range days (price inside value area); skip first 15 min; skip trend days; 60-min time stop; 2-loss daily halt; news blackout | UNTESTED - top candidate; matches the handoff's suggested "VWAP mean reversion on classified range days" family. Claimed 70-80% hit rate on range days is unverified |
| 4 | Volume profile (715K) | Prior-session POC / value-area high-low as reaction levels | PARTIALLY TESTED - key-level proximity filter exists in backtester; POC specifically untested |
| 5 | Supply/demand zones (3.3M) | Consolidation-before-impulse zones, entry on retest | Mostly discretionary; mechanical core overlaps rejected sweep/retest logic. Low priority |
| 6 | Iron condor course (1.3M) | 16-delta wings, 30-45 DTE, defined risk, close at 50% profit | ALREADY DEPLOYED - exactly the IWM bot's iron condor configuration |
| 7 | Turtle rules (571K) | Donchian 20/55-day breakout, N (ATR-20) volatility position sizing, 2N stop, 10/20-day-low exit, drawdown-scaled account sizing | PARTIALLY RELEVANT - trend following spirit lives in the momentum lane. The transferable, untested pieces are ATR-scaled stops and drawdown-scaled sizing |
| 8 | Price action secrets (2.3M) | Full-body candles as S/R, mean reversion to 50MA, momentum acceleration, Fib pullback depth (weak <= 38.2% retrace = continuation) | Mean reversion ~ frozen RSI2. Fib pullback-depth filter is mechanically definable and untested |

## What the Canon Actually Contains

Across 8 courses and ~10M combined views, every entry concept maps to five
mechanical cores: breakout (rejected), sweep/retest (rejected), band/level
mean reversion (partially tested), imbalance continuation (rejected), and
trend following (deployed as momentum). There is no sixth secret. The
genuinely valuable, repeatedly taught material is risk process, not entries:
volatility-scaled sizing, daily loss halts, time stops, news blackouts.

## Ranked Follow-Ups

1. VWAP band fade with an explicit range-day classifier (preregister before
   testing; MES 1m data supports it; final period caveat applies).
2. Risk overlays portable to existing bots without new edge claims:
   ATR-scaled stops, 60-minute time stop, 2-loss daily halt (Flip bot
   already has related protections; audit for gaps).
3. Prior-session POC as an entry filter variable in future preregistrations.
4. Fib pullback-depth (38.2%) continuation filter - low priority.

## Inoculation Record

Future "this YouTuber says X" ideas should be checked against this table
first. If the mechanical core maps to a rejected family, the answer is
already known. No course tested here published audited results.
