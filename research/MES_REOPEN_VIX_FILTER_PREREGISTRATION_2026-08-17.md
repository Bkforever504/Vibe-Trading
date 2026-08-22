# MES Reopen-to-Open VIX Filter Shadow Preregistration

Status: frozen forward-shadow candidate. No order authority.

## Reason for this revision

The earlier close-to-open candidate used the 16:00 ET MES close and same-day
VIX close while proposing a 15:55 ET decision. Those inputs are not known at
15:55, and a position opened near 16:00 cannot be carried across Topstep's
15:10 CT daily flatten. This revision moves entry to the 17:00 CT reopen, after
the inputs are final and inside one Topstep trading session.

## Frozen rule

- Instrument: one MES front-month contract, shadow only.
- Signal time: after 16:05 America/New_York on Monday through Thursday.
- Enter benchmark: first executable price at or after 18:00:05 ET.
- Exit benchmark: first executable price at or after 09:30:00 ET the next day.
- Direction: long.
- Enter only when both are true:
  - same-day VIX official close is less than or equal to 18.0;
  - same-day MES 16:00 close-to-prior-session 16:00 close is at least -1.0%.
- Cost model: one tick of slippage per side plus $0.74 commission per side,
  or $3.98 round trip. Executable BBO checks cross the ask at entry and bid at
  exit before fee.
- Friday and Sunday reopen entries are excluded.

## Evidence available at freeze

The rule transfer was evaluated after the original close-to-open result was
known, so the historical results are corroboration, not a pristine discovery
holdout.

| Split | Trades | Avg net/contract | PF | Sharpe | Max DD | Win rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 2022-2024 | 267 | $12.36 | 1.36 | 1.72 | -$820 | 54.7% |
| 2025-2026-07 | 171 | $12.12 | 1.32 | 1.75 | -$1,305 | 59.1% |

Recent Databento BBO corroboration contained nine qualifying observations:
$96.56 average, 88.9% wins, and -$37.47 max drawdown. Nine observations are
far too few for promotion and are reported only as a data-path check.

Stationary block-bootstrap intervals for mean net P&L (10,000 resamples,
mean block length five) are:

| Window | 90% CI | 95% CI | Bootstrap fraction above $0 |
| --- | ---: | ---: | ---: |
| 2022-2024 | $2.09 to $22.91 | $0.05 to $24.85 | 97.53% |
| 2025-2026-07 | -$2.05 to $26.11 | -$5.00 to $29.02 | 92.13% |
| Full sample | $3.68 to $20.66 | $1.80 to $22.38 | 98.87% |

The independent test interval crosses zero at both confidence levels.
Therefore the correct classification is **supportive shadow evidence**, not a
statistically confirmed executable edge. The bootstrap fraction is a resample
diagnostic, not a Bayesian posterior probability.

## Promotion gates

All gates require at least 30 newly resolved forward shadows:

- median net P&L greater than $6 per contract;
- win rate at least 55%;
- profit factor at least 1.10;
- max drawdown better than -$3,000 per contract;
- positive 90% bootstrap lower confidence bound for mean net P&L;
- no stale or proxy-mismatched observations included in scoring;
- reconciled TopstepX practice credentials and explicit user approval in a
  separate execution-change handoff.

Until every gate passes, `execution_enabled` and `can_submit_orders` remain
false.
