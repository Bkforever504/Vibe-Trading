# Market-regime and "fragility" claims: research intake

**Scope.** This note evaluates the regime/fragility claims shown in the September 1 screenshots. It is a research specification for the read-only scanner, not a directional forecast, trading rule, or evidence that a social-media result can be repeated.

## What is supported and measurable

| Screenshot claim | Evidence-supported interpretation | Scanner treatment |
| --- | --- | --- |
| "Correlation structure starts to change" | Correlation and volatility vary through time; higher correlation reduces diversification. Cboe's `COR3M` measures the options-implied, three-month expected average correlation of the top 50 value-weighted S&P 500 constituents. [Cboe methodology](https://cdn.cboe.com/resources/indices/documents/Cboe_USO_ImpliedCorrelation_0421_v2.0.2.pdf) | If licensed/live COR data is available, record level, 20-day z-score, one-day change, and skew/term-structure separately. Do **not** infer direction from any one value. |
| "Price is fragile when diversification shrinks" | Cboe says increasing implied correlation corresponds to lower expected diversification benefit and greater systematic-risk exposure; it is an expectation embedded in options, not proof of an imminent break. [Cboe explanation](https://www.cboe.com/us/indices/implied/) | Context/risk tag only; require a separate, instrument-level setup before a candidate can be shown. |
| "Use correlation velocity" | Rolling realized covariances/correlations can be constructed from high-frequency returns. Academic work supports their measurement and forecasting use, but not a universal threshold. [Andersen et al., NBER WP 8160](https://www.nber.org/papers/w8160) | Measure 5-minute, equal-weight pairwise realized correlation of liquid sector ETFs; compare a short window with a longer baseline, then test it walk-forward. |
| "Correlation spike predicts a crisis" | This is overstated. Unadjusted correlations rise mechanically when volatility rises, which can bias crisis comparisons. [Forbes & Rigobon, NBER WP 7267](https://www.nber.org/papers/w7267) | Standardize returns / control for realized volatility and report both raw and adjusted measures. Never label a correlation spike a crash prediction. |
| "Financial conditions / liquidity warn in advance" | NFCI is a weekly 105-indicator financial-conditions composite; STLFSI4 is a weekly 18-series stress composite. Both are slow state variables, not same-day timing tools. [Chicago Fed NFCI background](https://www.chicagofed.org/research/data/nfci/background) · [St. Louis Fed STLFSI4](https://fred.stlouisfed.org/series/STLFSI4/) | Tag each session with the latest release and change/percentile. Do not use the release as an intraday entry trigger. |
| "Options predict the market's direction" | VIX is an SPX-option-derived estimate of expected near-term volatility, not a directional forecast. [Cboe VIX methodology](https://cdn.cboe.com/api/global/us_indices/governance/VIX_Methodology.pdf) | Record VIX level, change, and available term structure as volatility context only. |

## Unsupported as presented

The graphic's named **0–100 "VRC" score**, component weights (15/25/20/25/15), score bands, and statements that it reliably identifies a market break have no cited methodology, data set, out-of-sample evaluation, or uncertainty estimate. They must be treated as unvalidated hypotheses—not imported as a scanner score.

Likewise, a screenshot showing a profitable AAPL/MU/NQ result is post-hoc evidence of one outcome, not evidence of signal quality. The "move the stop to profit after 30 minutes" rule is a separately testable exit-policy hypothesis; it cannot establish a discovery signal.

## Read-only scanner recommendation

Keep three independently visible components; do not collapse them into a claimed predictive score:

1. **Slow conditions:** latest NFCI/ANFCI and STLFSI4 value, release date, percentile, and freshness.
2. **Options-implied risk:** VIX inputs and, only when a licensed/live source is actually present, Cboe implied-correlation level/change/skew. Missing data must display `unavailable`, never a synthetic substitute.
3. **Same-session market structure:** realized sector-ETF correlation, breadth, cross-sectional dispersion, realized volatility, and—only with quote data—bid/ask spread and quoted-depth deterioration.

For every candidate, display these as provenance-stamped *context* alongside the existing catalyst, relative-volume, key-level, and confirmation evidence. The components can reduce a candidate's confidence or place it in `observe-only`; they must not create an order, size, or directional trade instruction.

## Test plan before any promotion

Pre-register feature definitions and thresholds using one training period, freeze them, then walk forward over later sessions. Evaluate each component and their interactions against the same candidate population using: 30/60-minute underlying return, maximum adverse/favorable excursion, stop-first rate, setup hit rate, and coverage/freshness. Include transaction-cost/slippage assumptions only when evaluating an explicitly defined instrument. Report confidence intervals and the number of observations; retain negative results.

The criterion for keeping a feature is incremental, stable out-of-sample information relative to the existing A+ evidence stack—not whether it explains a memorable historical chart. No primary source located supports a universal regime score or a promise to foresee every break.
