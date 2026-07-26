# Claude Handoff: SPY 12:00 Daily-Aligned Forward Lane

Date: 2026-07-25

## Decision

The lane was created as research-only forward evidence. It is not a paper-order
or live-order strategy and has no automatic promotion path.

## Frozen Behavior

- SPY only.
- Evaluate the production-parity 9/9 VWAP/EMA50 signal from complete 09:30
  through 11:59 ET one-minute bars.
- Require prior-completed daily trend alignment.
- Capture at most one signal per independent trading date.
- Observe underlying entry at 12:03/12:08 ET and exit at 13:03/13:08 ET.
- Track a deterministic 0-2 DTE, 0.35-0.65 absolute-delta directional option
  when an acceptable indicative quote exists.
- Value options ask-to-bid.
- Quote scope is `indicative_modified_not_opra_nbbo`; never call it NBBO.
- Review only after 30 resolved independent dates.

## Files

- `research/SPY_1200_DAILY_ALIGNED_FORWARD_SPEC_2026-07-25.md`
- `research/edge_trials/spy_1200_daily_aligned_forward_registry_2026-07-25.json`
- `scripts/spy_1200_daily_aligned_shadow.py`
- `scripts/run_spy_1200_daily_aligned_shadow.ps1`
- `scripts/register_spy_1200_daily_aligned_shadow_task.ps1`
- `agent/tests/test_spy_1200_daily_aligned_shadow.py`

## Review Request

Attack the implementation, not the historical hypothesis:

1. Look for any post-12:00 input entering the signal.
2. Verify the daily state is strictly point-in-time.
3. Verify one signal and one outcome maximum per date.
4. Verify bearish underlying P&L sign and option ask-to-bid semantics.
5. Verify no trading client or order endpoint is reachable.
6. Verify retries cannot duplicate evidence.
7. Do not retune the rule or inspect forward outcomes to change parameters.

Focused verification at handoff: 35 tests passed.
