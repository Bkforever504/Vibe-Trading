# CISD confirmed-retest shadow preregistration

## Hypothesis

A completed-bar CISD confirmation followed by the first valid retest hold may
reduce adverse excursion and chase distance relative to immediate confirmation
alerts, while the provisional CISD state may improve awareness without becoming
an entry signal.

## Frozen initial configuration

- Symbols: SPY, QQQ, IWM.
- Timeframes: 1 minute and 5 minutes, evaluated independently.
- Pivot length: 1 completed bar on each side.
- ATR: 14 bars; minimum opposing stretch: 0.50 ATR.
- Pending timeout: 10 completed bars.
- Retest tolerance: 0.10 ATR.
- Fibonacci projections: excluded.
- Purge and macro-window filters: excluded from the initial trial family.

## Outcomes

Record scanner emission time, completed-bar time, first retest time, Discord
delivery time if later enabled, MFE, MAE, chase distance, invalidation-first rate,
and current-alert paired outcome. Missing bars or timestamps make the observation
ineligible; no field may be synthesized.

## Promotion boundary

This lane cannot alter execution. After at least 30 reconciled outcomes per
timeframe, run the existing purged-CV and block-bootstrap governance gates.
Any change to thresholds or filters starts a new append-only hypothesis trial.
Human review remains mandatory.

## Authority

`execution_enabled=false`; `can_submit_orders=false`; no broker or notifier
imports; no live or paper order path.
