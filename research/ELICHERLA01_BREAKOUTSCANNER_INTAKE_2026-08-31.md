# Elicherla01/breakoutscanner intake

**Source reviewed:** `Elicherla01/breakoutscanner` at commit
[`408b827`](https://github.com/Elicherla01/breakoutscanner/tree/408b827a0b343becc0790fd58fb05bd4e2e52667)
(2026-07-12).  This is a source-level review; no live scan or performance test was
run.  The repository contains no test files or backtest module.

## Verdict

**Do not adopt as a trading strategy or directly port it into the U.S. intraday
A+ scanner.**  It is a useful, small **candidate-generation pattern** only:
"new N-bar extreme + relative-volume confirmation + close-location filter."  If
we experiment with it, implement that pattern independently behind the existing
U.S. liquidity, market-regime, event, data-quality, and execution gates; then
evaluate it with point-in-time U.S. data, an explicit entry/stop/exit policy,
and walk-forward results.  Do not reuse its bundled ML score.

## What the repository actually scans

The project is an NSE cash-equity scanner, not a broker-connected trading
system.  Its primary universe is NIFTY 500 symbols from NSE's constituent CSV;
symbols are translated to Yahoo tickers by appending `.NS`.  The UI/CLI can also
choose NIFTY 10, NIFTY 50, or an NSE F&O-equity universe.  If fetching fails it
can fall back to a hard-coded large-cap watchlist. [config.py](https://github.com/Elicherla01/breakoutscanner/blob/408b827a0b343becc0790fd58fb05bd4e2e52667/config.py#L16-L50)
[data_loader.py](https://github.com/Elicherla01/breakoutscanner/blob/408b827a0b343becc0790fd58fb05bd4e2e52667/data_loader.py#L52-L99)

Price data are Yahoo Finance OHLCV: hourly is `interval="1h"`, `period="60d"`;
daily is auto-adjusted and requests roughly 400 calendar days by default.
Weekly and monthly bars are resampled locally from daily data.  Monthly scans
request 1,500 days; the current partial month's volume is extrapolated to a
21-session equivalent. [data_loader.py](https://github.com/Elicherla01/breakoutscanner/blob/408b827a0b343becc0790fd58fb05bd4e2e52667/data_loader.py#L164-L212)
[data_loader.py](https://github.com/Elicherla01/breakoutscanner/blob/408b827a0b343becc0790fd58fb05bd4e2e52667/data_loader.py#L238-L291)

It can scan 1H, 1D, 1W, and 1M.  Defaults are:

| Timeframe | Donchian / volume lookback | Baseline volume multiple | Strong-close threshold | ATR strict multiple |
| --- | ---: | ---: | ---: | ---: |
| 1H | 20 / 20 bars | 1.20x | upper/lower 55% of range | 1.0x |
| 1D | 20 / 20 bars | 1.25x | 60% | 1.2x |
| 1W | 10 / 10 bars | 1.15x | 55% | 1.2x |
| 1M | 6 / 6 bars | 1.10x | 55% | 1.2x |

In strict mode the volume multiple becomes 1.5x across timeframes and true
range must exceed the configured ATR multiple. [config.py](https://github.com/Elicherla01/breakoutscanner/blob/408b827a0b343becc0790fd58fb05bd4e2e52667/config.py#L60-L130)
[breakout.py](https://github.com/Elicherla01/breakoutscanner/blob/408b827a0b343becc0790fd58fb05bd4e2e52667/breakout.py#L104-L166)

## Signal mechanics

For the latest available bar, it calculates resistance as the maximum high and
support as the minimum low of the **preceding** `N` bars (the signal bar is
excluded).  A bullish candidate requires:

```
close > prior N-bar highest high
AND volume >= volume_multiple * mean(volume of preceding volume-lookback bars)
AND (close - low) / (high - low) >= strong_close_pct
AND, strict mode only: true_range > ATR_multiple * SMA(true_range, ATR_period)
```

The bearish mirror is `close < prior N-bar lowest low` and uses
`(high - close) / (high - low)` for strong-close location.  True range includes
gaps (`max(high-low, abs(high-prev_close), abs(low-prev_close))`); ATR is a
simple mean of the last 14 (12 for monthly) true-range observations.  The result
reports breakout percent, relative volume, and ATR metrics, but **does not
calculate a trade entry, order type, stop, target, trailing exit, position size,
or holding period.** [breakout.py](https://github.com/Elicherla01/breakoutscanner/blob/408b827a0b343becc0790fd58fb05bd4e2e52667/breakout.py#L40-L98)
[breakout.py](https://github.com/Elicherla01/breakoutscanner/blob/408b827a0b343becc0790fd58fb05bd4e2e52667/breakout.py#L168-L224)

An optional post-filter limits signals to new 52-week highs for bullish daily,
weekly, or monthly candidates.  Results are sorted by timeframe, direction,
relative volume, then breakout percentage rather than by expected return or
risk-adjusted ranking. [breakout.py](https://github.com/Elicherla01/breakoutscanner/blob/408b827a0b343becc0790fd58fb05bd4e2e52667/breakout.py#L176-L179)
[scanner.py](https://github.com/Elicherla01/breakoutscanner/blob/408b827a0b343becc0790fd58fb05bd4e2e52667/scanner.py#L95-L112)

## Optional ML and confluence paths

Every universe scan tries to load/train a Random Forest confidence model.  Its
training set is historical **daily** breakouts from only a 20-name hard-coded
watchlist, with features RSI, relative volume, EMA20 distance, TR/ATR, and
10-day return.  Its label is whether price reached +3% before -2.5% (or -3%
before +2.5% for shorts) within the next ten bars.  It uses no shown
out-of-sample split, cross-validation, calibration, transaction-cost model, or
walk-forward procedure.  The live prediction also substitutes absolute
close-to-close change for the training-time true range, so the `tr_atr_ratio`
feature differs between training and inference. [ml_engine.py](https://github.com/Elicherla01/breakoutscanner/blob/408b827a0b343becc0790fd58fb05bd4e2e52667/ml_engine.py#L151-L239)
[ml_engine.py](https://github.com/Elicherla01/breakoutscanner/blob/408b827a0b343becc0790fd58fb05bd4e2e52667/ml_engine.py#L285-L362)

`confluence_scanner.py` describes a simultaneous same-direction 1H + 1D + 1W
breakout filter.  However it imports `cpr`, `cpr_scanner`, and
`NARROW_CPR_PCT`, none of which are present in this repository/configuration,
and includes a machine-specific absolute path.  Treat this script's CPR path as
non-runnable in the reviewed commit. [confluence_scanner.py](https://github.com/Elicherla01/breakoutscanner/blob/408b827a0b343becc0790fd58fb05bd4e2e52667/confluence_scanner.py#L14-L28)

## Reproducibility and quality gaps

1. **No evidence harness.** There are no tests, no backtest, no sample expected
   results, and no versioned data snapshot.  The documentation itself says
   hypothetical results do not include brokerage, taxes, slippage, impact, or
   borrow. [DISCLAIMER.md](https://github.com/Elicherla01/breakoutscanner/blob/408b827a0b343becc0790fd58fb05bd4e2e52667/DISCLAIMER.md#L34-L45)

2. **Potential incomplete-bar and stale-data signals.** Detection calls the
   latest returned bar the "latest completed bar," but the loader does not
   verify bar completion or exchange session boundaries.  Hourly cache is
   accepted when up to two calendar days old and daily cache when up to three;
   the purported regular-session volume filter retains every row because it
   filters `volume >= 0`. [breakout.py](https://github.com/Elicherla01/breakoutscanner/blob/408b827a0b343becc0790fd58fb05bd4e2e52667/breakout.py#L108-L109)
   [data_loader.py](https://github.com/Elicherla01/breakoutscanner/blob/408b827a0b343becc0790fd58fb05bd4e2e52667/data_loader.py#L201-L207)
   [data_loader.py](https://github.com/Elicherla01/breakoutscanner/blob/408b827a0b343becc0790fd58fb05bd4e2e52667/data_loader.py#L309-L340)

3. **Yahoo Finance is unsuitable as the sole production intraday feed.** The
   implementation depends on yfinance and broad `except` blocks that quietly
   return empty data; universe fetch also silently falls back to a fixed list.
   This can turn a partial-data failure into an apparently valid but incomplete
   scan. [data_loader.py](https://github.com/Elicherla01/breakoutscanner/blob/408b827a0b343becc0790fd58fb05bd4e2e52667/data_loader.py#L52-L83)
   [data_loader.py](https://github.com/Elicherla01/breakoutscanner/blob/408b827a0b343becc0790fd58fb05bd4e2e52667/data_loader.py#L183-L207)

4. **Configuration/implementation drift.** CLI `--lookback` defaults to 20,
   overriding 1W's configured 10 and 1M's configured 6 whenever it is used;
   its default `--vol-mult` similarly overrides timeframe-specific standard
   multiples with 1.25.  The monthly volume extrapolation is an unvalidated
   assumption. [run_scanner.py](https://github.com/Elicherla01/breakoutscanner/blob/408b827a0b343becc0790fd58fb05bd4e2e52667/run_scanner.py#L33-L50)
   [run_scanner.py](https://github.com/Elicherla01/breakoutscanner/blob/408b827a0b343becc0790fd58fb05bd4e2e52667/run_scanner.py#L74-L109)

5. **Unsafe/opaque ML artifact.** A pickled model is committed under
`data_cache/`; pickle should not be trusted from an unverified source, and the
repository does not provide training data, metrics, feature importances, or a
model-card-style provenance record. [ml_engine.py](https://github.com/Elicherla01/breakoutscanner/blob/408b827a0b343becc0790fd58fb05bd4e2e52667/ml_engine.py#L248-L315)

## Fit versus our U.S. intraday A+ scanner

| Dimension | This repository | U.S. intraday A+ adoption position |
| --- | --- | --- |
| Purpose | Latest-bar discovery/ranking | Candidate discovery only; keep the A+ confirmation and execution gates |
| Market/data | Indian NSE cash stocks, Yahoo 1H/daily | Must use our point-in-time U.S. universe and reliable intraday feed |
| Setup | N-bar Donchian extreme + relative volume + close location | Reasonable hypothesis to test as one feature/setup family |
| Risk/execution | Not specified | Must be explicit: entry timing/order type, stop/invalidation, targets, sizing, costs and liquidity |
| Validation | No tests/backtest/OOS proof | Require unit tests, historical simulation, walk-forward and paper/shadow evidence |
| ML score | Small daily in-sample classifier, feature mismatch | Exclude entirely until rebuilt with audited U.S. training/evaluation data |

## Controlled adoption plan

1. Create a new, isolated U.S. scanner feature that computes prior-bar-excluded
   Donchian level, RVOL, close-location value, and normalized range only on
   completed regular-session bars.
2. Make the universe point-in-time and liquidity-filtered; reject stale/partial
   symbol coverage and log all data failures.
3. Define executable mechanics before evaluating: trigger, entry deadline,
   invalidation/stop, target/exit, maximum simultaneous risk, spread/slippage
   and news/event exclusions.
4. Compare it against the current A+ baseline with date-partitioned,
   walk-forward testing and then shadow trade it.  Promote only if it improves
   net, risk-adjusted performance after costs without weakening guardrails.

