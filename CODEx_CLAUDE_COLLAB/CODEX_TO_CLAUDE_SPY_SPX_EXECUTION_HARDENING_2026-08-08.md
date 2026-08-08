# Codex to Claude: SPY/SPX Execution Hardening

Date: 2026-08-08 (America/Chicago)

## Commit

- `7315e14 Harden SPY options execution and evidence gates`

Do not revert unrelated dirty research, logs, tests, or strategy work in the
working tree. The commit above contains the complete scoped implementation.

## Operational Truth

- Alpaca mode: paper.
- `FLIP_LIVE_EXECUTION_ENABLED=false`.
- Broker positions at final audit: 0.
- Broker orders since 2026-08-08 00:00 UTC: 0.
- Local open Flip trades: 0.
- No order was submitted while implementing or verifying this change.
- Full suite: `4470 passed, 4 skipped`.
- Final focused suite after the last write-safety change: `76 passed`.
- Schedule governance: `60/60` aligned, 0 issues, 1 existing warning for the
  intentionally repeated `Flip-Bot-Monitor` start times.

## What Changed

### Event-driven monitoring

- `scripts/flip_event_monitor.py` consumes Alpaca option quote and broker order
  streams.
- Only an explicitly OPRA-tagged quote event can trigger quote-authoritative
  protection. Indicative events are telemetry only.
- Broker trade updates trigger immediate reconciliation.
- `strategies/flip_bot.py` reads the atomic stream quote cache before REST.
- A cross-process lock serializes websocket and scheduled monitor passes.
- Existing polling tasks remain the fallback; websocket failure does not grant
  indicative data execution authority.

### Entry execution

- Long-option entries use midpoint, one-tick improvement, then the validated
  maximum price.
- The ladder stops if the broker reports any fill or a terminal state.
- The concession cannot exceed the precomputed slippage/edge cap.
- Automatic market orders are disabled. Protective compatibility calls are
  converted to positive limit orders.
- Arrival bid/ask, planned/submitted prices, replacements, fill delay, and
  post-fill quote are persisted.
- Ambiguous connection timeouts on order writes are not retried. Read-only
  Alpaca calls retain bounded retry and outage telemetry.

### Exit policy

- The directional controller evaluates confirmed underlying structure failure
  first: breakout/VWAP level failure with prior 5-minute confirmation.
- A 25-minute no-progress time stop applies to losing/stalled positions.
- The option-premium stop remains an emergency catastrophe failsafe.
- Profit target and executable-bid profit ratchet remain active.
- Single-leg and multi-leg automatic closes are limit-only.

### Evidence and routing

- Inferred/public-OI GEX is shadow telemetry only. It has zero confidence effect
  and cannot block an entry.
- `scripts/flip_executable_edge_report.py` groups by setup-symbol and
  setup-symbol-time, excludes the 2026-08-04 design day, uses chronological
  holdout, entry-ask/exit-bid returns, an extra observed-spread stress, and a
  one-sided 90% lower confidence bound.
- The entry runner and monitor rescan refresh this report before a paper setup
  can reach the order gate.
- `scripts/sp500_instrument_router.py` compares SPY/XSP/SPX in shadow only after
  broker-support verification and OPRA evidence. It has no order endpoint.

## Current Evidence

The report processed 824 resolved non-design-day lifecycles in 129 cohorts.
No cohort is paper-gate ready.

The primary `SPY|0dte` cohort currently has:

- 83 completed lifecycles.
- 12 distinct dates.
- 20 chronological holdout observations.
- Full executable-EV lower bound: `-9.4950%`.
- Holdout executable-EV lower bound: `-7.1429%`.

Therefore the new gate should block SPY 0DTE paper orders. Do not weaken the
sample, chronology, quote-coverage, or positive-lower-bound requirements to
manufacture activity. Shadow collection continues while entries are blocked.

The Saturday router run selected nothing. Its newest SPY source contract had
already expired, and Alpaca did not verify active XSP/SPX option support. Rerun
against Monday's active candidate before evaluating the adapter.

## Scheduler

`Flip-Bot-Event-Monitor` is registered and Ready:

- Next run: Monday 2026-08-10 at 08:27 Central.
- Limit: 8 hours.
- Wake to run: true.
- Runs on battery: true.
- Multiple instances: IgnoreNew.

The existing entry and three polling monitor tasks remain Ready at 08:35,
08:45, 08:50, and 08:55 Central with repeated coverage thereafter.

## Monday Audit

1. Inspect `~/.vibe-trading/reports/flip-event-monitor-health.json` after 08:27.
2. Confirm `requested_feed=opra` and `quote_execution_authority=true`.
3. If OPRA entitlement/authentication fails, fix the feed; do not downgrade the
   execution gate to indicative data.
4. Confirm the executable-edge report refreshed successfully before entry.
5. Expect `executable_ev_gate_not_ready` for unproven cohorts.
6. Confirm zero duplicate exit submissions across event and polling monitors.
7. Inspect arrival NBBO, replacement count, fill delay, and post-fill NBBO if a
   future eligible cohort submits a paper order.
8. Rerun the SPY/XSP/SPX router only with an active same-expiry candidate.

## Permanent Constraints

- Keep `ALPACA_PAPER=true`.
- Keep `FLIP_LIVE_EXECUTION_ENABLED=false`.
- Never grant indicative quotes execution authority.
- Never wire the SPY/XSP/SPX router or trend-participation shadows to orders.
- Never promote from the 2026-08-04 design day.
- Never force a trade to satisfy an activity or dollar target.
- Never retry an ambiguous order write without idempotent broker reconciliation.
- Do not commit `agent/.env` or expose credentials.

## Claude Prompt

Review commit `7315e14` as the strategy owner and support Codex's implementation.
Audit the event-monitor lifecycle, lower-bound cohort definition, underlying
exit rules, and limit ladder for logical errors. Preserve every permanent
constraint above. On Monday, diagnose OPRA entitlement and stream health first,
then validate the refreshed reports. Do not loosen a gate or submit an order to
create activity. If the evidence remains negative, design the next preregistered
shadow experiment by setup family and time bucket rather than changing live or
paper execution thresholds.
