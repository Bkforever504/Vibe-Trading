# Codex Handoff: State After Claude's 2026-07-24/25 Sessions

From: Claude Code
Date: 2026-07-25
Repo: `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading` (branch main)
Commits this cycle: `b8f8b8c`, `e81cea8`, `a718f96`, `7f8f47d`, `a6f4faf`,
`c843443`, `e6bcac1`, plus the trial-ledger backfill commit that follows this
file.

## What Changed (all paper-only, nothing promoted)

1. **Operational truth** (`b8f8b8c`): disabled producers get a `disabled`
   health class instead of permanent false `stale`; schedule alignment
   tolerates `Running` within a 30-minute grace of last run
   (self-observation race fixed) and flags `task_running_too_long` beyond it.
   Alignment now passes 55/55.
2. **Canonical lifecycle adapter** (`e81cea8`):
   `scripts/lifecycle_normalizer.py` (v1.0.0) with per-family direction/P&L/
   risk semantics, quarantine + `unknown_reasons`, and fail-closed
   `FamilyRuleViolation`. Contamination audit
   (`scripts/lifecycle_contamination_audit.py`) found the headline defect:
   **12 of 13 closed options records have no fill-derived P&L** (legacy
   regex-estimates from closing-reason text).
3. **Free options data probe** (`a718f96`): expired SPY contract 1-minute
   bars and trades are free back to >= 2024-03-15; **no historical NBBO on
   the current plan**. Report:
   `~/.vibe-trading/reports/alpaca-options-history-probe.json`.
4. **Green-day lab audited and hardened** (`7f8f47d`, `a6f4faf`): no
   look-ahead found; material finding = complete-IEX filter skews sample
   toward high-volatility days. Preregistered per-checkpoint replication
   widened the sample; 10:30 rejection hardened; 12:00 daily-aligned earned
   a dev CI [+0.07, +17.78] but weakened in consumed 2025+ (trimmed
   negative). Lab/production indicator parity now tested to 1e-9.
5. **Options fill truth hardened** (`c843443`): three defects fixed with
   tests — positive (debit) `filled_avg_price` can no longer become fake
   credit; cancel-after-partial-fill applies real exposure instead of
   sticking `pending`; leg verification is disclosed
   (`verified|unavailable`). Blocked-vs-taken tracker added
   (`scripts/options_caution_gate_outcomes.py`), review-gated at 30
   independent blocked dates.
6. **Option execution replay** (`e6bcac1`): preregistered replay of the
   frozen 12:00 signals on actual expired contracts. Verdict: **option
   implementation falsified** — daily-aligned mean returns -13.25% (0DTE),
   -6.70% (1DTE), -7.81% (3-7DTE), PF <= 0.59, control also negative. The
   few-bps underlying lead cannot pay ~4.4% relative spread (p75 of our own
   forward NBBO capture) plus commissions. Reusable lab:
   `research/options_replay_lab.py`.
7. **Trial ledger backfilled (P0-C)**: `data/edge_trial_ledger.jsonl` went
   from 1 to 6 immutable trials across 5 edges, all with prereg/artifact
   hashes and honest `final_period_opened: true` flags. Multiple-testing
   report now counts **415 effective attempts** (409 from the attempt
   inventory), Bonferroni alpha 0.00012, Benjamini-Hochberg passes: 0,
   promotion-ready: 0. Readiness "research validity sees only 1 trial" is
   resolved.
8. **Robinhood read-only (P0-D) verified fail-closed**: 26 safety tests pass
   (default-deny unknown tools, redaction, classification);
   `_call_remote`/`_remote_status` return deterministic `not_authorized`
   without a cached OAuth token and refuse tools outside `enabled_tools`.
   **Blocked on Kenny**: OAuth bridge requires an interactive desktop run of
   `vibe-trading connector authorize <robinhood profile>`; agents must not
   perform or script the login. Until then, Robinhood work is limited to the
   already-verified Codex-side MCP reads. Cash account ending 8540 only; no
   options permission there.

## Falsified — Do Not Revive By Retuning

- 12:00 SPY signal as an **options** trade (any tested DTE).
- 10:30 SPY VWAP/EMA checkpoint (all variants, both completeness modes).
- Six commercial-indicator proxy families (12/12 promotion failures).
- Everything on the pre-existing rejected list (ORB families, MES sweeps,
  FVG, VWAP fade, quote imbalance/exhaustion, overnight drift, QQQ TOM...).

## Upgrade Queue For Codex (priority order)

1. **Options lifecycle P&L capture (P2 from the three-bot handoff).** The
   single highest-value gap. Wire closing-order fill snapshots into
   `options-trades.json` (closing_filled_avg_price already canonicalized on
   entry side), so new closed positions carry fill-derived realized P&L.
   Target: next 30 closed positions lifecycle-complete. The 12/13 legacy gap
   cannot be repaired retroactively; mark legacy records excluded.
2. **Wire learning reports to normalized views.** `closed_trade_postmortem`,
   `accelerated_bot_learning_report`, and `self_learning_edge_loop` still
   use local direction/credit logic. Consume
   `scripts/lifecycle_normalizer.py`, exclude quarantined/unknown records
   from challenger support, and recompute support counts. Expect challenger
   counts to drop; that is correct.
3. **Grow forward NBBO capture.** Spread calibration currently rests on 15
   samples (p75 4.44%). Every flip/options lifecycle event should call
   `point_in_time_quotes.capture_lifecycle_sample`; verify all four events
   fire and add SPY 12:00/13:00 scheduled snapshots if sample growth stays
   slow. Better calibration directly improves every future replay.
4. **12:00 underlying-only forward shadow decision.** Present Kenny the
   go/no-go: dev CI positive, 2025+ trimmed negative, options falsified.
   If go: frozen shadow logger, >= 30 independent dates, underlying + NBBO
   capture, registered in the ledger before first signal.
5. **Ledger auto-registration.** New research labs should append their trial
   record via `scripts/edge_trial_ledger.py record` at result-write time so
   the 415-attempt multiplicity count stays honest without manual backfill.
6. **Blocked-vs-taken accumulation.** `options_caution_gate_outcomes.py` is
   manual; decide whether to schedule it weekly (read-only). Gate review at
   30 independent blocked dates.
7. **Robinhood bridge (after Kenny authorizes).** Read-only canaries against
   account ending 8540: account discovery, positions, orders, SPY/XLE/XLK
   quotes, redacted audit log, deterministic expiry failure. No write
   scopes, no order tools, no tokens in tracked files.

## Boundaries (unchanged)

No live trading; no purchases (Databento/OPRA/Topstep/indicators); MES task
stays disabled; champions frozen; consumed periods stay consumed; one active
task per STATUS.md; preserve the dirty worktree; human-only promotion.

## Verification Baseline

Focused suites all green as of this handoff: signal-stack health/alignment
(16), lifecycle normalizer (10), green-day patches (6) + lab (11), fill
truth (7), confidence gate (20), gate outcomes (2), options replay (6),
Robinhood safety (26), probe (4). `execution_gate_audit.py` exit 0.
