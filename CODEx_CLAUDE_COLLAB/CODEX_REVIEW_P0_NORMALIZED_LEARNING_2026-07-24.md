# Codex Review: Normalized Three-Bot Learning

Date: 2026-07-24 CT

## Scope

Reviewed Claude commit `e81cea8`, corrected the canonical accounting layer,
and connected the read-only Flip/options learning consumers to compatible
normalized evidence. No execution, risk, sizing, stop, target, broker, or
scheduled-task behavior changed.

## P0 Corrections

1. `max_risk_per_contract` is already stored in dollars by
   `iwm_options_bot.py`. The initial normalizer multiplied it by 100 again.
   The canonical options risk calculation now uses dollars times quantity.
2. Missing Flip, options, and MES quantities no longer default to zero or one.
   They are quarantined with explicit reasons.
3. Close-reason percentages are no longer accepted as options P&L by the
   postmortem, accelerated learner, failure memory, or challenger loop.
4. The legacy 69-contract Flip loss remains accounting-valid history but is
   excluded from the current 1-to-5-contract strategy cohort.
5. Family-routing/watchdog defects are now regression repairs, not trading
   challenger nominations.
6. Legacy actual-paper mistake rows without explicit compatible evidence fail
   closed and cannot vote for a challenger.

## Current Evidence

### Flip

- 13 accounting-valid closed records.
- 12 current-strategy records after excluding the pre-hardening oversized
  trade.
- Current cohort: 8 wins, 4 losses, 66.7% win rate, $2,332 net paper P&L,
  $194.33 expectancy, 2.473 payoff ratio.
- This remains a small heterogeneous paper sample, not a live-ready edge.

### Defined-Risk Options

- 11 deduplicated closed records.
- 1 record has fill-derived P&L: +$40.
- 10 records are excluded from P&L evidence.
- Close-reason estimates are visible only as legacy diagnostics and cannot
  influence expectancy, lessons, or promotion.

### Self-Learning Loop

- 253 immutable mistake events observed.
- 244 compatible for the current read-only analysis.
- 9 incompatible legacy actual-paper events excluded.
- 3 family-routing patterns classified as regression repairs.
- 4 shadow-only strategy nominations remain.
- No automatic production mutation or promotion authority.

## Verification

```text
Focused normalized-learning suite: 30 passed
Three-bot safety/health suite: 219 passed, 1 external deprecation warning
Execution-gate audit: exit 0
Schedule alignment: passed, 55/55
```

Signal health reported 39 OK, 22 stale, 0 missing, 0 error, and 1 intentionally
disabled task. Most stale rows were dated 2026-07-23. This requires a separate
operational-freshness diagnosis; no strategy or evidence fields were changed
to hide it.

## Next Gate

Proceed to the Flip P1 evidence upgrade:

1. complete broker/NBBO/Greeks path telemetry;
2. report path completeness by schema and entry date;
3. reconcile the documented 50% stop versus current 0.70 multiplier without
   changing it;
4. build the $300/$500/$1,000 affordability report from observed eligible
   contracts;
5. keep all challengers shadow-only until 30 current-schema closed trades.

Options strategy conclusions remain blocked until lifecycle-complete,
fill-derived P&L exists for a meaningful frozen cohort. MES remains disabled
under its existing forward protocol.
