# Volume Indicator Edge Research

Date: 2026-07-19

## Decision

No volume overlay is authorized for execution. The only daily hypothesis worth untouched forward logging is the existing QQQ RSI2 prior-high setup conditioned on elevated or accelerating volume. The only intraday hypothesis worth retaining is SPY 15-minute ORB, 2R, entry by 10:30 ET, with CMF aligned to trade direction. The ORB candidate is too cost-sensitive for promotion.

## Research Scope

- Daily matrix: 12 strategy and symbol pairs, 19 volume configurations each, 228 configurations total.
- Intraday matrix: 2 opening ranges, 3 reward/risk settings, 2 entry cutoffs, and 14 volume filters, 168 configurations total.
- Total tested: 396 configurations.
- Daily indicators: RVOL, volume z-score, VROC, volume oscillator, moving-average volume divergence, OBV, CMF, MFI, VPT, ADL, Force Index, PVI, and NVI.
- Intraday indicators: time-of-day bar RVOL, cumulative RVOL, OBV slope, CMF, MFI, VPT slope, ADL slope, and volume acceleration.
- Validation: chronological holdout, modeled costs, doubled-cost ORB stress, bootstrap mean intervals, and year-by-year stability.

## Findings

### QQQ RSI2 plus volume

The strongest family was QQQ RSI2 mean reversion with the original prior-high exit and an entry-day volume filter.

| Filter | Holdout trades | Holdout win rate | Holdout expectancy | Bootstrap 95% mean interval |
| --- | ---: | ---: | ---: | ---: |
| RVOL >= 1.00 | 27 | 77.8% | 91.9 bps/trade | 32.9 to 156.3 bps |
| RVOL >= 1.25 | 15 | 86.7% | 129.1 bps/trade | 55.2 to 220.4 bps |
| Volume z-score >= 1 | 16 | 87.5% | 135.0 bps/trade | 63.5 to 221.4 bps |
| Volume oscillator > 0 | 24 | 83.3% | 102.0 bps/trade | 43.7 to 166.4 bps |
| MAVD > 0 | 24 | 79.2% | 98.2 bps/trade | 27.6 to 171.2 bps |

Limitations:

- These rows were selected after a 228-configuration sweep, so the bootstrap is post-selection evidence, not an untouched confirmatory test.
- All five variants lost in 2022 and 2023, which indicates regime sensitivity.
- The holdout has only 15 to 27 trades per filter.
- Stock returns were tested, not option fills. Options require historical chain, quote, IV, spread, and assignment data.

Action: log all five flags as telemetry in `scripts/rsi2_shadow_logger.py`; do not change the RSI2 signal until 30 or more new entry episodes resolve.

### SPY ORB plus CMF

Best candidate: 15-minute opening range, 2R target, last entry 10:30 ET, CMF aligned with direction.

- Holdout: 140 trades, 43.6% win rate, 0.0806R expectancy, PF 1.156.
- Bootstrap 95% interval: -0.118R to 0.289R. The interval crosses zero.
- Doubled-cost stress: 0.0039R expectancy and PF 1.007.

Action: keep as research-only. It does not meet a high-confidence or realistic-friction gate.

## Shadow Coverage

`research/shadow_volume_coverage.py` discovered and classified all 15 strategy shadow programs.

- Seven received historical volume matrices: RSI2, Williams %R, KAMA, MFI, TTM Squeeze, WaveTrend, and SPY ORB.
- CZT already uses RVOL, VWAP, and a bar-derived volume-profile proxy. It has 9 forward signals and 6 recorded outcomes, below promotion requirements.
- ICT macro, premarket EMA retest, and 30-minute continuation have replay or outcome scaffolding but insufficient resolved samples for an interaction sweep.
- SMC lacks one fixed executable entry and exit contract.
- Momentum and QQQ/GLD operate on weekly multi-asset horizons; adding a daily volume gate now would be an unregistered strategy change.
- Adaptive options cannot be reconstructed from stock OHLCV.

Machine-readable audit: `~/.vibe-trading/reports/shadow-volume-coverage.json`.

## Evidence Standards

- Relative volume is appropriate for identifying unusually active openings, consistent with the Stocks in Play ORB formulation and QuantConnect reproduction: https://www.quantconnect.com/research/18444/opening-range-breakout-for-stocks-in-play/p1
- Empirical work finds moving averages of volume can contain predictive information, which motivated MAVD and volume oscillator tests: https://www.sciencedirect.com/science/article/pii/S0927538X21000019
- Option volume imbalance has separate predictive literature, but it requires option transaction data and should not be proxied with stock volume: https://arxiv.org/abs/2201.09319
- True volume delta, footprint absorption, and order-book imbalance require trade classification or depth data. OHLCV cannot recover them.

## Next Gates

1. Accumulate 30 or more untouched QQQ RSI2 entry episodes with volume telemetry.
2. Evaluate the five flags as preregistered comparisons without changing the base signal.
3. Require option quote replay before applying the result to the Alpaca options bot.
4. Acquire exchange-grade trades and quotes before testing delta, cumulative delta, footprint, or order-book imbalance.
5. Do not add the SPY CMF filter to execution unless realistic quote replay restores a material edge.
