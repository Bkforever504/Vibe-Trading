# Liquidity Sweep Proxy Protocol

Date: 2026-08-11
Status: implemented as research-only telemetry
Execution authority: none

## Evidence verdict

"Liquidity sweep" is not an exchange-defined event visible in OHLCV bars. The
defensible observable is a failed-breakout proxy: price breaches a level known
before the session, closes back inside, and confirms the reversal within a
fixed number of subsequent bars.

The New York Fed paper *Stop-Loss Orders and Price Cascades in Currency
Markets* supports the narrower mechanism that clustered stop orders can
produce rapid price cascades. It does not establish that SPY prior-day-level
reclaims are profitable or that they reverse rather than continue.

Databento's MBO schema is the correct future evidence source for order-book
claims because it includes adds, cancels, modifies, fills, trades, order IDs,
and event timestamps. One-minute Yahoo OHLCV cannot identify resting stops,
aggressor intent, queue depletion, or cross-venue liquidity.

Recent social research was concentrated in Reddit and repeatedly named the
same candidate features: PDH/PDL and overnight levels, close back inside,
fast confirmation, abnormal volume, opening-session timing, and regime. The
same discussions disagreed over which wicks qualify and supplied no reliable
SPY options results net of costs. Those posts are hypothesis sources, not
promotion evidence.

Primary references:

- New York Fed: https://www.newyorkfed.org/research/staff_reports/sr150.html
- Databento MBO: https://databento.com/docs/schemas-and-data-formats/mbo
- Databento schema hierarchy: https://databento.com/docs/schemas-and-data-formats/whats-a-schema
- Order-book event impact study: https://arxiv.org/abs/0904.0900
- Raw last30days evidence: research/last30days/liquidity-sweep-trading-definitions-validation-and-systematic-implementation-for-spy-spx-es-options-raw-liquidity-sweeps-2026-08-11.md

## Preregistered proxy

Reference levels are computed before the event:

- Prior regular-session high and low: PDH, PDL
- Current premarket high and low from 04:00-09:29 ET: ONH, ONL

An event must occur from 09:35-10:30 ET and satisfy:

1. Price breaches a reference level by 0.03%-0.30%.
2. The same bar closes back inside the level.
3. Volume is at least 1.2 times the median of the prior 20 bars. The event bar
   is excluded from its own baseline.
4. A close in the reversal direction occurs within the next three bars.
5. The event becomes available only at the confirmation-bar timestamp.

Recorded outcomes are direction-adjusted returns at 5, 15, 30, and 60 minutes,
plus 60-minute MFE and MAE. Stable event IDs allow later runs to refresh labels
without duplicating observations.

## Strategy integration

The SPY iron condor and SPY 0DTE PM put-credit spread record the proxy context
with each setup. The field is not a gate. Scanner failure is explicit in the
context but cannot silently pass or block a production decision.

The scanner runs at 08:43 CT for pre-entry context, at 09:35 CT after the full
event window, and at 10:40 CT to refresh 60-minute labels. The strategy entry
paths read the freshness-checked cache and never wait on Yahoo. All triggers are
limited-privilege, network-aware, and governed by the schedule alignment report.

## Promotion standard

The event study requires at least 100 events across at least 60 sessions before
it can start a strategy backtest. That threshold does not permit execution.
Each candidate strategy must then pass a separate purged walk-forward test
using point-in-time option quotes, executable entry and close prices, fees,
parameter stability, regime slices, and a held-out final period.

No win-rate claim from the prior memo is accepted as calibrated evidence. A
credit spread, debit spread, and iron condor have different payoff functions;
the event's underlying-direction hit rate cannot be substituted for option
expectancy.
