# Preregistration: Pre-FOMC Announcement Drift

Date: 2026-07-19
Status: frozen before running any simulation
Owner: Claude (research only, no execution)

## Hypothesis

Equity returns concentrate in the ~24 hours before scheduled FOMC policy
announcements (Lucca-Moench pre-FOMC drift). Literature documents the
effect strongly pre-2015 and questions it after; this test decides on our
gates.

## Frozen Test Specification

- Instrument: SPY only.
- Event dates: FOMC statement release dates from the vtasca
  fed-statement-scraping dataset (`data/fomc_communications.csv`,
  Type = statement, deduplicated), 2000-present.
- Rule: long from the close 2 trading days before each statement date
  through the close of the statement date. Flat otherwise. No filters,
  zero parameters searched.
- Position: 100% of a $1,000 model account.
- Costs: 0.01% per side; stress at 2x and 3x.
- Data: daily closes, auto-adjusted, yfinance.

## Splits and Sequential Gates (same as turn-of-month)

- Development 2000-2015 in three sub-regimes; gate: positive total return
  after base costs in all three.
- Selection 2016-2020; gate: positive at base and 2x costs, max DD > -25%.
- Final 2021+; gate: positive at base and 2x costs, PF >= 1.05,
  max DD > -25%.

## Explicit Limits

- One instrument, one rule. Fail = rejected, no window tuning.
- A pass permits paper forward-testing only.
