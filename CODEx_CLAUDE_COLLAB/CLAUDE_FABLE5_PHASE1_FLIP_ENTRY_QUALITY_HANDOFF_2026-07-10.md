# Claude Fable 5 - Phase 1 Handoff: Flip Bot Trade Quality (Part 1: Telemetry Foundation)

Date: 2026-07-10
Author: Claude Fable 5
Phase: 1 (Flip Bot Trade Quality) - Part 1 complete (telemetry foundation)
Prior handoffs:
- CLAUDE_FABLE5_HANDOFF_MAJOR_BOT_UPGRADES_2026-07-10.md (master)
- CLAUDE_FABLE5_PHASE0_POSITION_INTEGRITY_HANDOFF_2026-07-10.md (Phase 0, verified on host)

## Why telemetry first

Phase 1 asks for entry-timing audits by minute, VWAP distance, ORB state,
spread/slippage/fill-quality measurement, and per-skip attribution. The
existing trade records could not support ANY of that:

- No entry time (only `entry_date`), no exit time (only `exit_date`).
- Estimate-vs-fill slippage computed at entry then thrown away; when the
  order-detail fetch failed, the estimate silently posed as the fill price.
- `spread_cents` measured at signal time but never persisted to the trade.
- Signal internals (score, VWAP distance, EMA state, ORB) flattened into a
  human-readable catalyst string - unusable for analysis.
- MFE tracked (`best_pnl_pct`) but MAE never recorded.

Auditing 10 closed trades that lack these fields would produce guesses.
Part 1 makes every FUTURE trade fully auditable; Part 2 runs the audits
once records accumulate.

## Findings (ordered by severity)

1. (High) Fill-price provenance was silent: on order-detail fetch failure the
   estimate became `entry_price` with no marker. Targets/stops derive from
   that price, so an unnoticed bad estimate skews the whole exit ladder.
   Now recorded as `entry_quality.fill_price_source` = `broker_fill` |
   `estimate_fallback` (and an empty `filled_avg_price` no longer counts
   as a broker fill).
2. (High) No MAE: loss-tail analysis and stop-placement evaluation (Phase 2)
   were impossible. Now `worst_pnl_pct` tracks alongside `best_pnl_pct`.
3. (Medium) No entry/exit timestamps -> no time-to-peak, hold-duration, or
   entry-minute analysis. Now `entry_at`/`exit_at` (UTC) plus
   `entry_quality.entry_minute_et`.
4. (Medium) flip-trades.json written non-atomically (same failure class that
   corrupted Phase 0's options state). Now uses
   `options_state.atomic_save_json` (lock + temp + fsync + replace).
5. (Low) `_get()` had a mutable default argument (Phase 9 hygiene item).

## Exact Files Changed

1. `strategies/flip_bot.py`
   - `_save` -> atomic, lock-safe via `strategies/options_state.py`.
   - `_get(params: dict = {})` -> `params: dict | None = None`.
   - Bear/bull setups (single-leg and spread) now carry a structured
     `signal_snapshot` {score, close, vwap, ema50, vwap_distance_pct,
     reasons} and `orb_direction` (bear side) in addition to the catalyst
     string. Additive keys only.
   - New pure helpers: `_utc_now_text`, `_entry_quality_snapshot`,
     `_update_pnl_extremes`, `_stamp_exit`.
   - Trade records now include `entry_at` and `entry_quality`
     {entry_minute_et, entry_price_est, filled_price, fill_price_source,
     slippage_per_contract, slippage_pct, spread_cents_at_signal,
     orb_direction, signal_snapshot}.
   - Monitor tracks `worst_pnl_pct` (MAE); both exit paths (monitor +
     close-all) stamp `exit_at` via the shared `_stamp_exit`.
   - NO entry/exit decision logic changed. No thresholds changed. No new
     trade sources. Confidence gates untouched.

2. `agent/tests/test_flip_entry_quality.py` (NEW, 6 tests)
   - Slippage math and signal carry-through; missing-estimate handling;
     MFE/MAE transitions; exit stamping (fields + parseable UTC timestamp +
     P&L); atomic save leaves no temp files; no-mutable-default regression.

## Tests And Commands Run (sandbox; re-verify on host)

```
124 passed: full Phase 0 + master suites + new flip telemetry tests
python -m compileall strategies scripts -> passed
```

Host verification command addition:

```powershell
python -m pytest agent\tests\test_flip_entry_quality.py -q -p no:cacheprovider
```

## Before / After

- Before: a filled trade recorded date-only timing, fill price of unknown
  provenance, no spread, no MAE, prose-only signal context.
- After: every new trade carries a complete, structured entry-quality
  record; exits carry timestamps; drawdown extremes accumulate per cycle.

## Remaining Phase 1 Work (Part 2, evidence-driven)

1. After ~10 new trades with telemetry: entry-timing audit (minute
   distribution vs outcome, VWAP-distance vs MAE, ORB alignment vs win rate).
2. Late/chasing detection: pre-submission check comparing signal age and
   VWAP extension against recorded outcomes - only once data supports a
   threshold (do not invent one).
3. One-primary-reason skip attribution: flip currently logs skips as free
   text; port the options bot's `_decision()` JSONL pattern to flip
   (`flip-decisions.jsonl`) so every skipped setup has a structured primary
   reason. (Bounded, good next task.)
4. Quote-age measurement at entry (needs an Alpaca quote-timestamp fetch in
   `_atm_option`; small change, touches live data path - do deliberately.)
5. ATM vs debit-spread comparison once both structures have samples.

## Carried Items

- Netted-leg quote-based marking for the two IWM condors (Phase 2/5) so
  automated exits resume; manual supervision until then. Expiry 2026-08-07.
- Duplicate recovered-vs-original lifecycles (options P&L double-count
  risk) - reporting phase.

## Safety Confirmation

No live flags, kill-switch, risk caps, thresholds, or gate logic touched.
All changes additive telemetry or durability hardening. New records default
to no order capability anywhere.
