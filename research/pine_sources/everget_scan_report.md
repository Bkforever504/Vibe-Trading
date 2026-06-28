# Pine Source Scan Report

Root: `research\pine_sources\everget-tradingview-pinescript-indicators`

| Metric | Count |
|---|---:|
| Pine files | 210 |
| Indicators/studies | 210 |
| Strategies | 0 |
| Clean files | 196 |
| Warning files | 14 |
| Critical repaint files | 1 |

## Translation Queue

Clean files below have no current scanner warnings. They are not approved strategies; they are candidates for manual translation and backtesting.

| File | Name | Type | Category | Version | License | Tags |
|---|---|---|---|---:|---|---|
| `bands_and_channels/acceleration_bands.pine` | Acceleration Bands | study | bands_and_channels | 3 | gpl-3.0 | SMA |
| `bands_and_channels/interquartile_range_bands.pine` | Interquartile Range Bands | study | bands_and_channels | 3 | gpl-3.0 | - |
| `bands_and_channels/kirshenbaum_bands.pine` | Kirshenbaum Bands | study | bands_and_channels | 3 | gpl-3.0 | EMA, SMA |
| `bands_and_channels/mean_absolute_deviation_bands.pine` | Mean Absolute Deviation Bands | study | bands_and_channels | 4 | gpl-3.0 | SMA |
| `bands_and_channels/moving_average_channel.pine` | Moving Average Channel | study | bands_and_channels | 4 | gpl-3.0 | SMA |
| `bands_and_channels/stoller_average_range_channels.pine` | Stoller Average Range Channels (STARC) Bands | study | bands_and_channels | 3 | gpl-3.0 | EMA, SMA, ATR |
| `bands_and_channels/vortex_bands.pine` | Vortex Bands | study | bands_and_channels | 4 | gpl-3.0 | - |
| `highlighters/bitmex_withdrawals_cutoff_time.pine` | BitMEX Withdrawals Cutoff Time | study | highlighters | 3 | gpl-3.0 | - |
| `highlighters/leap_years.pine` | Leap Years | study | highlighters | 3 | unknown | - |
| `highlighters/quarters.pine` | Quarters | study | highlighters | 3 | unknown | - |
| `highlighters/range_candles.pine` | Range Candles | study | highlighters | 4 | gpl-3.0 | - |
| `highlighters/weekdays_gaps.pine` | Weekdays Gaps | study | highlighters | 4 | gpl-3.0 | - |
| `movings/adaptive_laguerre_filter.pine` | Adaptive Laguerre Filter | study | movings | 4 | gpl-3.0 | - |
| `movings/adaptive_rsi_moving_average.pine` | Adaptive RSI Moving Average | study | movings | 4 | gpl-3.0 | RSI |
| `movings/ahrens_moving_average.pine` | Ahrens Moving Average | study | movings | 4 | gpl-3.0 | - |
| `movings/alpha_decreasing_exponential_moving_average.pine` | Alpha-Decreasing Exponential Moving Average | study | movings | 4 | gpl-3.0 | EMA |
| `movings/apirine_adaptive_exponential_moving_average.pine` | Adaptive Exponential Moving Average | study | movings | 3 | gpl-3.0 | SMA |
| `movings/apirine_adaptive_moving_average.pine` | Apirine Adaptive Moving Average | study | movings | 4 | gpl-3.0 | EMA |
| `movings/arnaud_legoux_moving_average.pine` | Arnaud Legoux Moving Average | study | movings | 3 | gpl-3.0 | - |
| `movings/bryant_adaptive_moving_average.pine` | Bryant Adaptive Moving Average | study | movings | 3 | gpl-3.0 | - |
| `movings/butterworth_filter.pine` | Butterworth Filter | study | movings | 4 | gpl-3.0 | - |
| `movings/corrected_moving_average.pine` | Corrected Moving Average | study | movings | 4 | gpl-3.0 | SMA |
| `movings/distance_coefficient_filter.pine` | Ehlers Distance Coefficient Filter | study | movings | 3 | gpl-3.0 | - |
| `movings/distance_weighted_moving_average.pine` | Distance Weighted Moving Average | study | movings | 3 | gpl-3.0 | - |
| `movings/double_exponential_moving_average.pine` | Double Exponential Moving Average | study | movings | 3 | gpl-3.0 | EMA |
| `movings/double_weighted_moving_average.pine` | Double Weighted Moving Average | study | movings | 3 | gpl-3.0 | - |
| `movings/ehlers_deviation_scaled_moving_average.pine` | Ehlers Deviation-Scaled Moving Average | study | movings | 3 | gpl-3.0 | - |
| `movings/ehlers_distance_coefficient_filter.pine` | Ehlers Distance Coefficient Filter | study | movings | 3 | gpl-3.0 | - |
| `movings/ehlers_leading_indicator.pine` | Ehlers Leading Indicator | study | movings | 3 | gpl-3.0 | - |
| `movings/ehlers_mesa_adaptive_moving_averages.pine` | Ehlers MESA Adaptive Moving Averages (MAMA & FAMA) | study | movings | 3 | gpl-3.0 | - |
| `movings/ehlers_modified_optimum_elliptic_filter.pine` | Ehlers Modified Optimum Elliptic Filter | study | movings | 3 | gpl-3.0 | - |
| `movings/ehlers_optimum_elliptic_filter.pine` | Ehlers Optimum Elliptic Filter | study | movings | 3 | gpl-3.0 | - |
| `movings/ehlers_super_smoother_filter.pine` | Ehlers Super Smoother Filter | study | movings | 3 | gpl-3.0 | - |
| `movings/elastic_volume_weighted_moving_average.pine` | Elastic Volume Weighted Moving Average | study | movings | 4 | gpl-3.0 | - |
| `movings/exponential_moving_average.pine` | Exponential Moving Average | study | movings | 3 | gpl-3.0 | EMA |
| `movings/farey_sequence_weighted_moving_average.pine` | Farey Sequence Weighted Moving Average | study | movings | 4 | gpl-3.0 | - |
| `movings/fibonacci_weighted_moving_average.pine` | Fibonacci Weighted Moving Average | study | movings | 3 | gpl-3.0 | - |
| `movings/finite_impulse_response_filter.pine` | Finite Impulse Response (FIR) Filter | study | movings | 4 | gpl-3.0 | - |
| `movings/fractal_adaptive_moving_average.pine` | Fractal Adaptive Moving Average | study | movings | 3 | gpl-3.0 | - |
| `movings/gaussian_filter.pine` | Gaussian Filter | study | movings | 4 | gpl-3.0 | - |

## Flagged Files

| File | Critical | Warnings |
|---|---|---|
| `research/chart_type_identifier.pine` | - | legacy_security |
| `statistics/bitcoin_ath_hash_rate_level.pine` | - | legacy_security |
| `statistics/dividends_per_share_dps_yearly.pine` | - | legacy_security |
| `statistics/earnings_per_share_eps_yearly.pine` | - | legacy_security |
| `statistics/kendall_rank_correlation_coefficient.pine` | - | legacy_security |
| `statistics/ticker_performance_by_us_president.pine` | - | pine_v6 |
| `statistics/us_treasury_yields.pine` | lookahead_on | legacy_security |
| `trailing_stops/chandelier_exit.pine` | - | pine_v6 |
| `trailing_stops/halftrend.pine` | - | pine_v6 |
| `trailing_stops/nrtr_nick_rypock_trailing_reverse.pine` | - | pine_v6 |
| `trailing_stops/parabolic_sar.pine` | - | pine_v6 |
| `trailing_stops/supertrend.pine` | - | pine_v6 |
| `volatility/mayer_multiple.pine` | - | legacy_security |
| `volume/volume_accumulation.pine` | - | pine_v6 |
