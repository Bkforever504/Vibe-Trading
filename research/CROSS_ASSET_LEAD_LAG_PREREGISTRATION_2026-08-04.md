# Cross-Asset Lead-Lag Preregistration - 2026-08-04

## Question

Do liquid risk proxies contain a delayed five-minute return signal for MES that
survives executable futures quotes, commissions, doubled costs, and a
chronological holdout?

## Frozen hypotheses

Only these five signed hypotheses are tested:

| Leader | Expected MES relation |
| --- | --- |
| SPY | same direction |
| QQQ | same direction |
| HYG | same direction |
| TLT | opposite direction |
| VIX (`^VIX`) | opposite direction |

No pair, lag, threshold, session, or holding-period search is allowed. Yahoo
Finance five-minute bars are research inputs only and cannot establish
execution quality. MES entry and exit prices come from the licensed Databento
BBO sample.

## Frozen timing and rule

- Aggregate MES BBO to five-minute intervals.
- A leader bar is known only at its interval close.
- Compute its five-minute return and a 20-bar trailing z-score using only bars
  available through that close.
- If `abs(z) >= 1.5`, enter MES at the first BBO in the next interval in the
  preregistered signed direction.
- Exit at the last executable BBO of that next interval.
- Permit at most one position per leader at a time.
- Base cost includes observed BBO and $2.48 round-trip commission.
- Stress adds another $2.48 commission plus one MES tick per side.

## Review

- Sessions are split chronologically: first 70% development, last 30% locked
  holdout.
- Each hypothesis needs at least 60 development trades.
- Development must have positive base and stressed expectancy, stressed profit
  factor at least 1.20, and a positive-mean one-sided p-value below
  `0.05 / 520`.
- Only a development survivor may open its holdout. Holdout requires at least
  25 trades and positive base and stressed expectancy.
- No pooling across failed leaders and no winner-selected composite.

## Authority

Research only. This experiment cannot submit orders, change sizing, alter an
entry gate, or promote a strategy.

