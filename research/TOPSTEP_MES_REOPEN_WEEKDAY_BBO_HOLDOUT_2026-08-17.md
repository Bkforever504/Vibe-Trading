# Frozen Executable Holdout: MES Reopen Weekday Candidate

Date: 2026-08-17
Status: frozen before purchasing or inspecting the BBO holdout
Authority: research and forward-shadow selection only

## Origin

The 2024 through 2026-07-17 discovery sample found an overall positive MES
reopen-to-cash-open premium with excessive drawdown. A diagnostic weekday split
selected exit weekdays Monday, Wednesday, and Thursday. A free proxy on later
dates was supportive. This specification tests those later dates with
executable Databento quotes.

## Frozen Data And Rule

- Dataset: Databento `GLBX.MDP3`, schema `bbo-1s`, continuous `MES.v.0`.
- Holdout request: 2026-07-18 through 2026-08-17 15:00 UTC.
- Entry: first valid ask from 6:00:05 PM through 6:00:30 PM ET.
- Exit: first valid bid from 9:30:00 AM through 9:30:10 AM ET on the next
  available cash session.
- Contract integrity: entry and exit raw symbols must match.
- Eligible exit weekdays: Monday, Wednesday, and Thursday only.
- Position: long one MES contract.
- Base P&L: `(exit_bid - entry_ask) * $5 - $1.22`.
- Stress 1: base minus one MES tick per side ($2.50 round trip).
- Stress 2: base minus two MES ticks per side ($5.00 round trip).
- No stop, target, event filter, volatility filter, or parameter fitting.

## Frozen Evidence Gate

The holdout is supportive only when all conditions hold:

1. At least 10 eligible trades.
2. Positive base and Stress 1 expectancy.
3. Base profit factor at least 1.05.
4. Base maximum drawdown no worse than -$500.

A pass creates a **forward-shadow candidate**, not Practice or Combine trading
authority. Practice promotion still requires the repository's prior-date route,
at least 30 resolved outcomes, a positive 90% expectancy lower bound, profit
factor at least 1.20, drawdown no worse than -$500, functioning ProjectX
credentials, and broker reconciliation.
