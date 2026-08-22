# TimesFM Intake - 2026-08-14

## Verdict

TimesFM is useful as a read-only, independent forecast and uncertainty benchmark. It is not a
trading edge by itself and must not become an execution vote before point-in-time calibration.

Google Research's TimesFM 2.5 release provides a 200M-parameter pretrained time-series model,
up to 16k context, a 1k forecast horizon, and an optional continuous quantile head. The public
repository is Apache-2.0 licensed and explicitly states that it is not an officially supported
Google product.

## Fit With The Existing Stack

| Component | Primary information | TimesFM role |
| --- | --- | --- |
| Kronos | Financial OHLCV path forecast | Independent model comparison |
| GARCH | Conditional variance | Volatility baseline |
| IV/RV and options surface | Market-implied distribution | Market-price comparison |
| TimesFM | Generic univariate forecast plus quantiles | Shadow uncertainty benchmark |

TimesFM's useful addition is the q10-q90 forecast band. The band can measure model disagreement
and uncertainty without converting forecast magnitude into a fabricated confidence score.

## Implementation Boundary

`scripts/timesfm_market_forecaster.py`:

- loads TimesFM only when `--load-model` is explicitly supplied;
- records the point forecast, q10, q50, q90, and interval width;
- marks direction only when the entire q10-q90 band is above or below spot;
- records point-in-time JSON and JSONL evidence;
- has no broker import, order path, sizing authority, scheduler, or production gate integration.

No TimesFM package or model weights are installed by this change.

## Promotion Standard

Do not wire TimesFM into a trading gate or score until all conditions pass:

1. At least 100 resolved point-in-time forecasts spanning at least 30 trading days.
2. Performance exceeds a last-value forecast on MAE and directional accuracy.
3. Quantiles pass empirical coverage checks and improve pinball loss over a simple rolling
   distribution baseline.
4. Incremental value remains after comparison with Kronos, GARCH, trend, and volatility regime.
5. Results hold in preregistered high-volatility, low-volatility, trend, and range cohorts.
6. Any proposed trading use survives spread, slippage, fees, and no-trade controls out of sample.

Until then, `calibration_status` remains `unvalidated` and all forecasts are shadow-only.

## Official Sources

- https://github.com/google-research/timesfm
- https://arxiv.org/abs/2310.10688
