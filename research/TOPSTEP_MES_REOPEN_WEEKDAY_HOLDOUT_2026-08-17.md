# Frozen Holdout: MES Reopen Weekday Candidate

Date: 2026-08-17
Status: frozen before evaluating dates after 2026-07-17
Authority: diagnostic holdout only; no execution authority

## Candidate From Discovery Sample

The 2024-07-17 through 2026-07-17 executable BBO study found positive reopen
drift overall but excessive one-contract drawdown. Its post-test weekday
diagnostic found positive results for sessions exiting Monday, Wednesday, and
Thursday and negative results for sessions exiting Tuesday and Friday. Because
that selection used the discovery sample, it requires later data.

## Frozen Free-Proxy Holdout

- Untouched dates: after 2026-07-17 through 2026-08-17.
- Instrument: Yahoo Finance `MES=F` five-minute extended-hours bars.
- Entry proxy: first bar close timestamped from 6:00 PM through 6:15 PM ET.
- Exit proxy: next available 9:30 AM ET bar open.
- Eligible exit weekdays: Monday, Wednesday, Thursday only.
- Cost deduction: $1.22 TopstepX MES round-turn fee plus one MES tick per side,
  $6.22 total per trade.
- Position: one MES contract; no stop or target.

The proxy is considered supportive only with at least 10 eligible trades,
positive expectancy, profit factor at least 1.05, and drawdown no worse than
-$500. A pass cannot promote the strategy because Yahoo bars are not executable
BBO prices. The separately priced Databento BBO holdout is required next.
