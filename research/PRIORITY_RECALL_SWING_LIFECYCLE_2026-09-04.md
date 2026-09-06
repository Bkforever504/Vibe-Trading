# Priority Recall and Swing Lifecycle Repair — 2026-09-04

## Incident

The September 3 review exposed three different failure modes that the prior aggregate recall metric collapsed into one misleading green result:

- DELL was discovered premarket with a large move, but it was not a reserved symbol and disappeared once the 160-name intraday evaluation cap filled.
- TSLA was evaluated repeatedly intraday and the EOD continuation study retained it as a high-scoring watch, but no persistent multi-day observation lifecycle made that intelligence continuously visible.
- SPY was evaluated, but its early state flipped direction and later valid positive move windows were not represented in the daily top-mover coverage denominator.

The previous `100%` figure described only recall over the final top-mover list. It did not describe recall over the priority universe and therefore could not support the broader claim implied by the dashboard.

## Invariants

1. Priority focus symbols are a single explicit universe: SPY, QQQ, IWM, AAPL, MSFT, NVDA, AMZN, META, GOOGL, TSLA, and DELL.
2. Every available priority symbol receives an intraday evaluation slot before dynamic discovery fills the remaining capacity.
3. Coverage denominators are named. Top-mover recall and priority-universe recall are separate metrics.
4. A symbol absent from ground truth or source data is a visible coverage debt, never an implicit success.
5. Observation visibility is independent from execution eligibility. A useful shadow observation may be shown while every execution gate remains closed.
6. Swing observations persist across sessions with state age and last-transition evidence.
7. Custom/proprietary formulas are not inferred. Social-media rules remain unvalidated hypotheses until prospective evidence supports them.
8. All new paths are shadow-only: `execution_enabled=false`, `can_submit_orders=false`.
9. The governed spine remains: candidate -> independent evidence cards -> veto/risk gate -> shadow alert -> simulated lifecycle -> reconciled outcome -> rule update.
10. No green operational status is allowed when alert delivery is failed, pending, stale, or malformed.

## Tickets and dependencies

- PRI-01: central priority universe and scanner reservation. Independent.
- RECALL-01: priority denominator and omission/debt reporting. Depends on PRI-01.
- SWING-01: persistent priority swing observation state and transition delivery. Depends on PRI-01 conceptually, but may share only the universe module.
- DASH-01: honest priority recall and swing panels. Depends on RECALL-01 and SWING-01 output contracts.
- OPS-01: final wrapper health mirrors the completed run envelope. Independent.
- VERIFY-01: focused tests, full scoped regression, authority guard, live shadow run, report freshness and delivery reconciliation. Depends on all tickets.

## Release acceptance

- DELL cannot be displaced from evaluation by discovery rank when source data exists.
- TSLA/DELL and all other priority symbols have explicit swing rows or explicit data-debt rows.
- SPY priority coverage is reported even when SPY is absent from the top-mover list.
- Dashboard copy never equates observed, alerted, simulated, executable, or profitable.
- Failed notifications remain pending and retryable, with non-secret error classes.
- Runner order and no-order authority tests remain green.

