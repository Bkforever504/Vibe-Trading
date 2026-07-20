# Preregistration: Post-Earnings Announcement Drift (Long-Only Proxy)

Date: 2026-07-19
Status: frozen before running any simulation
Owner: Claude (research only, no execution)

## Hypothesis

Stocks with strongly positive earnings reactions continue to drift upward
over the following month (PEAD). Proxy for earnings surprise: the price
reaction itself (no analyst-estimate data available free).

## Data Limits (explicit)

yfinance earnings-date history is shallow (roughly 2-4 years). No 2000-2015
development window is possible without paid data. This is therefore a
lower-confidence screen, not a full validation. Splits are chronological
60/40 on event dates within the available window.

## Frozen Test Specification

- Universe (frozen, 30 liquid megacaps): AAPL MSFT NVDA AMZN GOOGL META
  TSLA AVGO JPM V UNH XOM WMT JNJ PG MA HD COST ORCL BAC KO PEP MRK ADBE
  CRM AMD NFLX DIS CSCO INTC.
- Reaction day: of the announcement date and the following trading day,
  the one with the larger absolute close-to-close return.
- Signal: reaction-day return >= +3%. Long at reaction-day close, hold 20
  trading days, exit at close. Long only. One position per event; overlaps
  allowed (each event evaluated independently on $1,000 notional).
- Costs: 0.02% per side; stress at 2x.

## Splits and Gates

- Development: first 60% of events chronologically. Gate: positive mean
  per-event return after base costs.
- Test: last 40%. Gate: positive mean return, event-level profit factor
  >= 1.10, positive at 2x costs.

## Explicit Limits

- Zero parameters searched beyond the frozen +3%/20-day rule.
- Shallow window means a pass only justifies acquiring deeper earnings
  data or forward paper-tracking - never deployment.
- Fail = rejected under this spec on this window.
