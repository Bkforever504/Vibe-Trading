# Preregistration: IWM Overnight-Session Drift (Small-Cap Focus)

Date: 2026-08-17
Status: frozen before running the promotion-scored simulation
Owner: Claude (research only, no execution)

## Relationship to Prior Tests

The 2026-07-19 unconditional overnight-drift test on SPY/QQQ failed at
the development or selection gates. The 2026-08-17 v2 lab (extended to
1993 and adding diagnostic filters) confirmed SPY continues to fail the
promotion gates in the 2021-2026 final window, but flagged IWM
(Russell 2000 ETF) as a persistent, unconditional outlier:

| Symbol | Final 2021-2026 Sharpe | Total % | DD % |
|--------|------------------------|---------|-------|
| SPY    | 0.347                  | 18.07   | -24.45 |
| QQQ    | 0.454                  | 33.44   | -30.83 |
| MDY    | 0.215                  | 10.57   | -25.31 |
| IWM    | **0.646**              | 54.76   | -22.33 |
| EEM    | -0.269                 | -27.29  | -48.11 |

This is consistent with Bogousslavsky (2021), Berkman et al. (2012),
and Barclay et al. (2008) showing that small-cap indices retain a
larger, more persistent overnight-vs-intraday return decomposition
than large-cap indices, plausibly because retail attention and
overnight ETF creation flows disproportionately absorb small-cap
supply after hours.

This document freezes an IWM-only test with real cost stress and
sequential gates. Because the diagnostic scan already saw the final
window on IWM, this document imposes stricter gates than the SPY
prereg to compensate for peeking.

## Frozen Test Specification

- Instrument: IWM only (daily OHLC, auto-adjusted, yfinance).
- Rule: at each trading day t, buy at the IWM close of t and sell at
  the IWM open of t+1. Flat between t+1 open and t+1 close.
- Position: 100 % of a $1,000 model account.
- Costs: 0.02 % per side (2 bps, IWM 1-cent-typical spread on retail
  routing), stressed at 2x and 3x.
- Executability instrument: M2K (Micro Russell 2000 futures) on Topstep.
  If M2K bar data becomes available in `data/databento/`, an
  executability check identical to the MES check in the v2 lab is
  computed. Until then, MES correlation is used as a proxy under the
  documented caveat that IWM/RUT differs from ES/SPX.

## Splits and Sequential Gates

- Development 2000-05-26 to 2015-12-31 in two sub-regimes
  (2000-2009 and 2010-2015). Gate: positive total return after base
  costs in BOTH sub-regimes AND Sharpe > 0.5 on the combined window.
- Selection 2016-01-01 to 2020-12-31. Gate: positive at base AND at
  2x costs, Sharpe > 0.5, max DD > -25 %.
- Final 2021-01-01 to present. Gate: positive at base AND at 2x costs,
  profit factor >= 1.10, Sharpe > 0.5, max DD > -25 %.

## Explicit Limits

- One instrument, one rule, zero parameters searched.
- Failure at any gate = rejected, no filter overlay applied afterward.
- Because IWM final-window statistics were viewed in the v2 diagnostic
  scan, a pass here is considered CONDITIONAL and requires a
  minimum-90-day forward paper period on M2K before any live-trading
  proposal.
- If passed, register as `iwm_overnight_drift` in
  `research/preregistrations/` and expose an `intake_shadow` scanner
  under `strategies/` that logs prospective entries and exits to a
  new jsonl in `data/`.
