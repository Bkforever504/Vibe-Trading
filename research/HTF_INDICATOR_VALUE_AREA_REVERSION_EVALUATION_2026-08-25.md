# HTF Suite and Value-Area Reversion Evaluation

Date: 2026-08-25  
Decision: selectively integrate mechanics as independently implemented, shadow-only context; do not copy indicator code or assign grade weight.

## Primary sources reviewed

- JustExecution, [HTF SUITE repository](https://github.com/JustExecution/HTF_indicator), including its README, Pine source inventory, and GPL-3.0 license declaration.
- LuxAlgo, [Value Area Reversion Signals](https://www.luxalgo.com/library/indicator/value-area-reversion-signals/), the vendor's mechanical description and limitations.

## HTF Suite assessment

The repository describes Pine Script v6 tooling for two higher timeframes, a four-candle fractal sequence, CISD, first-presented FVGs, order-block projections, SMT divergence with a second comparison symbol, session boxes, True Day Open / Previous Day Open, and session time filters.

Most analytical coverage already exists locally: completed-bar multi-timeframe scanning, CISD/FVG detection, liquidity sweeps, PMH/PML/PDH/PDL, session timing, and paired-index SMT. Reimplementing the whole Pine indicator would add duplicate labels rather than independent evidence.

The additive idea retained is multi-peer SMT. The local implementation now evaluates every supplied peer, exposes per-peer results, and reports agreement or conflict. Conflicting peers remain neutral and cannot increase a grade. True Day Open was not added to the equity scanner because an equity feed without a midnight print cannot support that futures/FX-specific label honestly. Current-session and prior-session levels remain explicitly sourced instead.

Licensing: the repository identifies GPL-3.0. No Pine code was copied. The implementation uses independently expressed completed-bar mechanics and preserves local provenance.

Repaint/look-ahead risks: live higher-timeframe candles can change before their close, and multi-timeframe `request.security` logic can leak unfinished values if configured incorrectly. The local scanner continues to use completed bars only; 1-minute data may refine but never originate a setup.

## Value-area reversion assessment

LuxAlgo describes an anchored volume profile that calculates VAH, VAL, and POC, then watches for price to leave value and close back inside. Its stricter confirmation requires re-entry volume to exceed the breakout volume; POC is a possible mean-reversion objective, while the failed-breakout area can define risk.

This is useful as a failure/reclaim context, but the current local feed provides bar OHLCV rather than exchange trade-at-price volume. Therefore the dashboard's VAH/VAL/POC is explicitly a typical-price volume-bin proxy, not a true market profile.

The local addition is deliberately narrow and causal:

- build the reference profile from completed bars excluding the signal bar;
- require the immediately prior completed bar to close outside VAH/VAL;
- require the next completed bar to close back inside value;
- require re-entry volume to exceed breakout volume;
- surface direction, boundary, invalidation observation, and volume comparison;
- assign zero grade weight and no execution authority.

If price re-enters without volume confirmation, the state is `reclaim_unconfirmed_volume`, not a signal. A future version may preregister a wider reclaim window only after local replay shows that it improves out-of-sample precision.

## What was rejected

- No copied proprietary LuxAlgo code; the public page describes behavior but does not establish reusable source licensing.
- No claim that proxy POC/VAH/VAL equals exchange volume-at-price.
- No use of unfinished HTF candles.
- No extra confluence points merely because several indicators restate the same price move.
- No social-media or vendor win-rate claim enters ranking.

## Promotion requirements

Both additions remain descriptive shadow context until they have frozen definitions, executable-quality source data where required, resolved forward outcomes across regimes, multiple-testing control, and calibration evidence. `execution_enabled=false` and `can_submit_orders=false` remain mandatory.
