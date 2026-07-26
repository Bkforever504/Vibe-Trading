# Claude Adversarial Review: Alpaca Fill Truth and Indicator Audit

Date: 2026-07-25
Handoff: `CLAUDE_HANDOFF_ALPACA_LOSS_AND_INDICATOR_AUDIT_2026-07-25.md`

## 1-2. Fill-Truth Review (`_apply_entry_fill` / `_refresh_entry_order_fills`)

Confirmed correct in Codex's changes:

- Broker `filled_avg_price` is canonical; live records show the Alpaca MLEG
  credit convention is a negative signed price (IWM -0.40, AAPL -0.86,
  NVDA -0.49), matching the corrected credits.
- Risk adjustment is idempotent: `submitted_max_risk_per_contract` is frozen
  on first application, so partial-fill re-applications cannot compound the
  adjustment.
- Leg-mismatch fills are refused and stay pending.
- Terminal unfilled orders (canceled/expired/rejected/replaced with zero
  fills) transition to `entry_canceled`.
- The multi-warning `stand_aside` gate is entry-only (defaults on,
  `OPTIONS_STRICT_CAUTION_MIN_WARNINGS` floor of 2); exit paths, profit
  closes, and stop handling are untouched, and the live-execution flag still
  defaults off. 20 existing confidence-gate tests plus the options
  integration suites pass.

Defects found and fixed (with tests, `test_options_entry_fill_truth.py`):

- **D1 (sign hole).** `abs(signed_fill)` would silently convert a positive
  (net **debit**) fill into fake credit, corrupting `net_credit` and risk.
  Now refused: positive `filled_avg_price` sets
  `entry_fill_review="non_credit_filled_avg_price"` and the group stays
  pending for manual review.
- **D2 (partial-fill-then-cancel gap).** An order canceled after a partial
  fill reported `status=canceled, filled_qty>0`; the old status gate rejected
  it and the terminal branch required `filled_qty<=0`, so real exposure could
  sit in a `pending` record forever. Fill economics are now applied whenever
  `filled_qty>0`, regardless of terminal status.
- **D3 (silent leg-check bypass).** When the order snapshot has no legs the
  mismatch check cannot run; records now carry
  `entry_fill_leg_verification: verified|unavailable` instead of implying
  verification happened.

No exit, sizing, stop, target, symbol, or endpoint behavior was changed.

## 3-4. Commercial Indicator Proxy Lab

Targeted static review (disclosed depth: sampled the signal/entry engine and
indicator loops, did not re-derive all six families):

- Entries execute at the next 5-minute bar open with a same-day guard;
  breakout/volume references are built from `shift(1)` priors; the
  supertrend recursion uses prior-bar bands; KAMA-style warmup is NaN-ed.
  No look-ahead found in the sampled paths.
- The preregistration is dated before results and the verdict (all 12
  SPY/MES promotion decisions failed) is a rejection, not a fit. Nothing in
  the lab retunes against 2025+.
- I did not fully recompute the six families from raw bars this session;
  the focused lab tests pass. If deeper verification is wanted, the next
  step is an independent re-run comparing the frozen JSON hashes, not new
  variants.

Verdict unchanged: **reject**; do not purchase indicators.

## 5. Blocked-vs-Taken Gate Outcome Logger (new)

`scripts/options_caution_gate_outcomes.py` + tests:

- Cohorts: decisions blocked by `shadow_consensus_multi_warning_stand_aside`
  versus `submitted` entries, from the append-only decisions log.
- Outcome: forward underlying move over 5 trading days from local daily
  caches, resolved only after the horizon completes (point-in-time; no
  hindsight fill-in). Explicit basis:
  `underlying_forward_move_proxy_not_option_pnl`.
- Review gate: `review_eligible` only at >= 30 independent blocked dates.
  The logger is observational and cannot change the gate.
- Manual CLI for now; scheduling is a separate decision.

## 6. Next Options Replay Design (for approval, not built)

- Source: confirmed free Alpaca expired-contract 1-minute bars/trades
  (available back to >= 2024-03-15; no historical NBBO on this plan).
- Contract selection: reproduce each bot's actual selection rule at signal
  time (strike/DTE/delta proxy from underlying and chain snapshot), never
  best-hindsight contracts.
- Fills: trade-price based with conservative spread stress calibrated from
  forward `point_in_time_quotes.py` NBBO capture (entry at ask+stress, exit
  at bid-stress for debit; inverted for credit), plus commissions.
- Compare 0DTE vs 1DTE vs 3-7DTE under identical signals; report
  option-return and underlying-return separately; never present
  underlying-only results as option profitability.
- Preregister before first run; register in the trial ledger with hashes.

## Confidence (evidence-based)

- Fill accounting after D1-D3 fixes: 9/10 (broker-truth canonical, tested).
- stand_aside entry gate: 5/10 pending 30 independent blocked outcomes.
- Commercial indicator alpha: 2/10 (12/12 promotion failures) — reject.
- Overall promotion status: unchanged; nothing here is proof of edge.
