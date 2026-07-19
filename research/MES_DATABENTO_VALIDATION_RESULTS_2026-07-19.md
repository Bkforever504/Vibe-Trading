# MES Databento Validation Results

## Dataset

- Source: Databento `GLBX.MDP3`, continuous `MES.v.0`, `ohlcv-1m`.
- Period: 2022-01-03 through 2026-07-17.
- Cleaned sample: 441,238 RTH bars across 1,150 sessions.
- Contract rollover dates and all non-available Databento condition dates were
  excluded before testing.
- Historical data credit used: estimated $5.87 from the $125 signup credit.

## Method

- 805 development sessions split into three internal regimes.
- 172 later sessions used for candidate selection and doubled-cost stress.
- 173 final sessions remained untouched until selection was complete.
- 4,800 executable configurations tested.
- One MES contract, full stop/target exits, maximum 40-tick stop.
- No configuration was promoted or routed to a broker.

## Selected Candidate

- Signal: 5-minute opening-range breakout.
- Minimum breakout: 1 point.
- Stop: 40 ticks (10 points, $50 before costs).
- Target: 2R.
- Filter: opening-gap directional bias.
- Maximum one trade per day.

| Stage | Trades | P&L | Expectancy | Profit factor | Max drawdown |
|---|---:|---:|---:|---:|---:|
| Development | 45 | $570 | $12.67 | 1.42 | $240 |
| Selection | 11 | $156 | $14.18 | 1.48 | $120 |
| Selection, 2x costs | 11 | $112 | $10.18 | 1.32 | $140 |
| Untouched final test | 22 | $12 | $0.55 | 1.02 | $336 |
| Untouched final test, 2x costs | 22 | -$76 | -$3.45 | 0.91 | $372 |

## Verdict

Rejected for deployment and NinjaTrader simulation promotion.

The final test failed the minimum trade-count, profit-factor, doubled-cost
expectancy, and drawdown gates. The development and selection performance did
not generalize. Tuning against the final period now would contaminate it and is
not permitted.

## Confidence

- Data integrity: 9/10.
- Validation design: 9/10.
- Confidence that this ORB family has a deployable edge as tested: 2/10.
- Confidence that the strategy should remain disabled: 9/10.

## Next Legitimate Step

Keep the MES executor disabled. Use the historical dataset for rolling
walk-forward diagnosis and begin a new forward-simulation ledger for a materially
different, pre-registered hypothesis. The next hypothesis must be selected
without using the final-test results above as parameter targets.
