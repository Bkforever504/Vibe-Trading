# Claude Handoff: Scorecard → 10/10

Date: 2026-08-20 America/Chicago
Owner: Claude (audit + blueprint) → Codex (implementation)
Status: Blueprint frozen. No code written this session.

## 0. TL;DR for Codex

Kenny's current scorecard:

| Axis | Current | Target |
|---|---:|---:|
| Research process | 8 | 10 |
| Safety and abstention | 9 | 10 |
| Market discovery coverage | 7 | 10 |
| Dashboard decision clarity | 7.5 | 10 |
| Execution reliability | 5 | 10 |
| Verified forward edge | 3 | 10 |
| Overall readiness | 6 | 10 |

Order of leverage (biggest lift per unit work): **Verified edge (3→10) →
Execution reliability (5→10) → Discovery coverage (7→10) → Dashboard
clarity (7.5→10) → Research process (8→10) → Safety (9→10)**.

Three named gaps drive most of the deficit:

1. **Daily detection scorecard** - measure discovery/ranking against actual moves
2. **Empirical calibration** - grades → post-cost win probability
3. **Execution proof** - resolve every shadow/paper setup with executable
   quotes, fills, MFE/MAE, counterfactuals

Everything below stays inside the read-only contract:
`execution_enabled=false`, `can_submit_orders=false`, no
`signal_registry.json` edits, no live-bot edits, no
manufactured probabilities.

## 1. Existing infrastructure (do not rebuild)

Grep confirms these modules already exist:

- `scripts/probability_calibration.py` + `agent/tests/test_probability_calibration.py`
- `scripts/opportunity_intelligence_pipeline.py` (baseline in
  `data/opportunity_intelligence_report.json`)
- `scripts/options_shadow_twin.py` +
  `data/options_shadow_twin_log.jsonl`
- `scripts/adaptive_options_shadow_playbook.py`
- `research/options_replay_lab.py`
- `scripts/elite_bot_readiness_scorecard.py`
- `scripts/edge_recovery_report.py`
- `scripts/bottom_reversal_forward_tracker.py`
- `scripts/daily_move_coverage_review.py` (fills
  `data/daily-move-coverage-review.json`)
- `scripts/options_evidence_factory.py`
- `strategies/profitability_control_plane.py`

New work extends these; it does NOT reimplement. Where a module already
computes a statistic, the blueprint below points to the additive gap
only.

## 2. Method reference (canonical, non-negotiable)

Every new statistic must be produced with one of these methods. No
ad-hoc splits. No self-tuned thresholds. No re-optimization on the same
dates.

### 2a. Forward validation

- **Walk-forward with purged embargo** (López de Prado, 2018). Purge = at
  least one bar horizon; embargo = 1% of sample. No `train_test_split` on
  time-series.
- **Combinatorial purged CV** (CPCV) for regime-robust point estimates
  where sample allows.
- **Freeze-then-test discipline**: any change to a candidate spec after
  first look at outcomes invalidates the run. Store a hash of the frozen
  spec alongside the result.

### 2b. Multiple-testing control

- **Deflated Sharpe Ratio** (Bailey & López de Prado 2014) as the primary
  gate.
- **PBO** (Probability of Backtest Overfitting) reported alongside every
  Sharpe. PBO > 0.5 = reject.
- **Bonferroni or Benjamini-Hochberg** correction across the
  experiment-wide family size (# of specs tested to date).
- Family size lives in a single append-only ledger; every promotion
  proposal reads that count.

### 2c. Calibration measurement

- **Brier score** (proper scoring rule) is primary.
- **Reliability diagram** with 10 equal-count bins.
- **Expected Calibration Error (ECE)** and **Maximum Calibration Error
  (MCE)** reported per grade and per regime.
- **Post-hoc mapping** via **isotonic regression** (monotone, no
  parametric assumption) when the raw grade is well-ordered but
  miscalibrated. Platt scaling only if isotonic has < 30 samples per bin
  and mapping is near-monotone-logistic.
- Refit calibration **only on out-of-sample** rolling windows. Never
  refit on evaluation data.

### 2d. Execution proof

- Every candidate resolves through the **executable ask-to-bid ladder**
  the codebase already uses in `research/options_replay_lab.py`. Midpoint
  fills are for diagnostic only, never for edge claims.
- **MFE / MAE** (Max Favorable/Adverse Excursion) captured per
  candidate; used for stop-tuning without curve fit (report distribution,
  do not optimize expectancy).
- **Slippage decomposition**: intent→arrival, arrival→fill,
  fill→realized. Report all three.
- **Counterfactual pairs**: for every accepted candidate, log
  the alternative that would have been chosen under the counterfactual
  rule (cash, next-ranked, skip).

### 2e. Detection scorecard

- Ground truth = the causal executable move universe defined by
  `daily_move_coverage_review.py`.
- Per day: **recall@k**, **precision@k**, **discovery latency**
  (bars from move start to first radar surface), and **ranking miss**
  (was it discovered but ranked below k?).
- Per regime: same, sliced by market classification.
- Confusion partition: correct entry, correct skip, discovery miss,
  ranking miss, late alert, false positive.

### 2f. Uncertainty reporting

- Every headline number is a **95% moving-block bootstrap CI**, block
  length = ceil(sqrt(n)) or 5 bars, whichever larger.
- **Lower confidence bound** is what drives promotion, not the point
  estimate.

## 3. Axis-by-axis blueprint

### 3a. Verified forward edge (3 → 10)

Root cause of the 3: every current lane either failed a gate, has n=0
resolved, or decayed. The system needs a **candidate pipeline** that
generates fresh preregistered hypotheses at a rate faster than they get
rejected.

Deliverable set:

1. **Hypothesis intake ledger** at `data/hypothesis_ledger.jsonl`.
   Append-only. One row per proposed candidate. Fields: `id`,
   `proposed_at`, `spec_hash`, `spec_path` (frozen markdown),
   `family_id`, `origin` (research | social | external), `status`
   (proposed | development | shadow | paper_review | approved |
   rejected), `first_resolved_at`, `last_evaluated_at`, `n_resolved`,
   `dsr`, `pbo`, `expectancy_lb`, `verdict_reason`.
2. **Weekly candidate generation job** at
   `scripts/weekly_candidate_intake.py`. Sources: existing shadow
   ledgers, `research/` markdown drafts, social intake filtered by
   provenance. Job promotes an intake row from `proposed` to
   `development` only when the frozen spec file exists and passes
   schema validation.
3. **Frozen-spec validator** at `scripts/preregistration_validator.py`.
   Rejects any spec without: entry rule, exit rule, universe, timestamp
   basis, execution policy, cost stress, spec hash. This is a linter,
   not a promoter.
4. **Multi-lane replay harness** at `research/multi_lane_replay.py`.
   Runs every `development` candidate through purged walk-forward, CPCV,
   moving-block bootstrap, DSR, PBO. Writes results to
   `data/multi_lane_replay_{yyyymmdd}.json` and updates the intake
   ledger.
5. **Promotion gate** at `scripts/promotion_gate.py`. Reads intake
   ledger + replay results. Emits `data/promotion_decisions.jsonl`
   with `promote` | `hold` | `reject` per candidate. Rules
   (non-negotiable, freeze in JSON `data/promotion_rules.json`):
   - n_resolved >= 30 across >= 20 distinct sessions
   - DSR lower bound > 0 after Bonferroni across current family size
   - PBO < 0.5
   - post-cost expectancy lower CI > 0
   - decay monitor: last 20% of sample same sign as full sample
   - placebo pass on shuffled labels
6. **Family-size ledger** at `data/experiment_family.jsonl`. Every
   frozen spec adds one. The promotion gate reads the count for
   Bonferroni. Never decrement.
7. **Kill-switch on stale promotion**: if a promoted candidate produces
   `hold_cash_collect_counterfactuals` in the control plane for N
   consecutive weeks (N=4 default, in `promotion_rules.json`),
   auto-demote to `paper_review`.

Additional research lanes to preregister (each requires its own frozen
spec before any code):

- Overnight cross-sectional mean reversion on QQQ constituents.
- Event-gap continuation with strict n>=30, 20 dates (already flagged
  in master handoff).
- Opening-range breakout on the liquid universe with a fixed R multiple
  and MAE-based stop budget.
- 0DTE SPY put spread on high-IVR days with dealer-gamma qualifier.
- ETF pair mean reversion (XLE/XLF or QQQ/IWM) with cointegration
  half-life monitoring.

None of these is a claim of edge. Each is a hypothesis that will be
tested honestly and probably rejected. That is the correct throughput
mindset.

### 3b. Execution reliability (5 → 10)

Root cause of the 5: scheduler-success is not fill; freshness gaps
degrade to STAND_ASIDE; no closed feedback loop from fill to
counterfactual.

Deliverable set:

1. **Broker reconciliation daemon** at
   `scripts/broker_reconciliation_daemon.py`. Every 5 minutes during
   market hours: pull Alpaca orders + fills + positions; diff against
   local state; emit `data/reconciliation_events.jsonl`. Alert (via
   the new toast/sonner layer) on any diff.
2. **Idempotent order envelope** at `strategies/order_envelope.py`.
   Wraps every existing bot order call. Requires: client_order_id
   derived from `sha256(strategy_id + symbol + intent_ts + bar_ts)`,
   idempotency check against the reconciliation log, kill-switch
   probe, freshness probe. Refuses submit on any red.
3. **Fill quality report** at `scripts/fill_quality_report.py`. For
   every executed order: intent price, arrival mid, fill price, exit
   fill, MFE, MAE, realized R, slippage decomposition per §2d.
   Writes `data/fill_quality_report.json` daily.
4. **Shadow-to-fill resolver** at `scripts/shadow_outcome_resolver.py`.
   Every candidate in every shadow ledger resolves on close of session
   into a row in `data/shadow_outcomes.jsonl` with fields: `plan_id`,
   `entry_fill_executable`, `exit_fill_executable`, `mfe`, `mae`,
   `outcome_r`, `time_in_trade_minutes`, `counterfactual_next_ranked`,
   `counterfactual_cash`, `resolved_at`.
5. **Freshness-fill contract**: every candidate that reaches the
   dashboard with `evidence_fresh: true` gets an entry mark stamp
   inside the shadow ledger at bar close. If freshness lapses before
   entry mark, the ledger row records `stale_before_entry` and the
   candidate contributes to detection-scorecard "late alert", not
   execution stats.
6. **Deterministic replay tests** at
   `agent/tests/test_replay_deterministic.py`. Given a fixed input
   bundle (bars, quotes, calendar), replaying the same day twice
   produces identical shadow outcomes byte-for-byte.
7. **Failure taxonomy dashboard block** (surfaces the existing
   `data/failure-taxonomy.json`): count per class per week
   (freshness_lapse, broker_reject, guard_block, idempotency_collision,
   auth_failure, quote_gap, code_bug). Extend
   `scripts/live_trading_cockpit.py` to expose in schema v7 as
   `operations.failure_taxonomy_week`.

### 3c. Market discovery coverage (7 → 10)

Root cause of the 7: intraday radar covers the liquid universe but the
detection scorecard (below) shows discovery misses that never make it
into the ledger with an explanation.

Deliverable set:

1. **Move ground-truth builder** at
   `scripts/move_universe_ground_truth.py`. For every session: take
   Alpaca aggregates + Polygon-tier proxy (whatever the codebase has),
   compute the top-N causal executable moves defined by size,
   liquidity, catalyst, and no-halt. Freeze in
   `data/move_ground_truth_{yyyymmdd}.json`. This is the denominator.
2. **Detection scorecard job** at `scripts/detection_scorecard.py`.
   For each ground-truth move: was it in premarket radar? intraday
   radar? which rank? at what latency vs move start? was the setup
   confirmed? was the entry gated? was the exit tracked? Writes
   `data/detection_scorecard_{yyyymmdd}.json` and a rolling 30-day
   `data/detection_scorecard_rolling.json`.
3. **Universe coverage delta report** at
   `scripts/universe_coverage_delta.py`. Diff radar universe vs
   ground-truth universe; flag symbols in the causal-move set that
   were never in the discovery universe. Root-cause into: liquidity
   filter, market-cap filter, price filter, sector filter, data gap.
4. **Missed-move postmortem** feeding
   `data/missed_move_postmortem.jsonl` daily. Per row: reason class,
   fix hypothesis, whether the fix would double-count another
   promotion.
5. **Dashboard exposure**: extend schema v7 with
   `discovery.scorecard_rolling` and a new tab **Detection** in
   `frontend/src/pages/Detection.tsx` rendering recall@k, precision@k,
   latency histogram, per-regime slice, top 10 missed moves this
   week.
6. **Cross-check with existing move coverage**:
   `daily_move_coverage_review.py` already exists; the new detection
   scorecard subsumes and formalizes it. Keep the old report emitting
   through the transition; deprecate after two green weeks.

### 3d. Dashboard decision clarity (7.5 → 10)

Root cause of the 7.5: even with the 10/10 UI blueprint shipped, the
grades themselves are not yet probabilities. Kenny sees B+ = 73.8 but
that is factor agreement, not win rate.

Deliverable set:

1. **Grade-to-probability service** at
   `scripts/grade_probability_service.py`. Loads
   `data/shadow_outcomes.jsonl`, fits isotonic regression per (setup
   family, regime, grade), writes
   `data/grade_probability_calibration.json` with:
   - point estimate per bucket
   - 95% bootstrap CI
   - Brier score, ECE, MCE
   - reliability diagram data
   - sample size and refit timestamp
2. **Calibration guard**: refuses to emit a probability for any bucket
   with n < 30 or ECE > 0.15. Dashboard shows "not calibrated" for
   those.
3. **CommandCard extension**: display `probability` object with
   value + label + sample_size + calibration_status. Payload already
   supports it (`TradingCandidate.probability`); the missing piece is
   the service that fills it truthfully.
4. **Reliability diagram widget** at
   `frontend/src/components/trading/ReliabilityDiagram.tsx`.
   Renders the calibration curve per setup family in the new
   Calibration tab.
5. **New tab `Calibration`** at
   `frontend/src/pages/Calibration.tsx`. Shows per-setup Brier,
   ECE, reliability curve, sample size, last refit date, promotion
   status.
6. **Weekly recalibration job** as a scheduled task
   `VibeTradingGradeCalibration`. Runs Sundays 08:00 CT. Uses only
   shadow outcomes older than 24h to avoid look-ahead.

### 3e. Research process (8 → 10)

Root cause of the 8: the pipeline is strong but ad-hoc lane additions
still happen. The gap is enforcement, not method.

Deliverable set:

1. **Preregistration linter** (same file as §3a.3) blocks any spec
   file missing required fields.
2. **CI check** `.github/workflows/preregistration_check.yml` (or
   equivalent local pre-commit hook) that runs the linter on every
   commit touching `research/*.md` or `data/hypothesis_ledger.jsonl`.
3. **Family-size dashboard tile** in the Retro tab: "This week we
   tested N candidates. Bonferroni denominator is now K. Effective
   alpha is 0.05/K."
4. **Reject-with-reason contract**: every rejection in the intake
   ledger must cite a rule ID from `promotion_rules.json` and a
   result-file path. No free-form rejections.
5. **Provenance chain**: every displayed statistic on the dashboard
   links to (report file + line reference + spec hash). Extend the
   existing source-inspector to show provenance without a click.

### 3f. Safety and abstention (9 → 10)

The 9 is close. What is missing:

1. **Chaos test harness** at
   `agent/tests/test_safety_chaos.py`. Injects malformed report
   files, stale timestamps, missing sources, broker auth failures,
   scheduler misfires, quote gaps, kill-switch signals. Asserts the
   system degrades to STAND_ASIDE or fails closed, never to a
   favorable state.
2. **Order-authority invariant test**: static grep + runtime test
   that no endpoint returns `execution_enabled: true` outside a
   single audited path that does not exist today.
3. **Secret leak test**: pre-commit hook + CI check that no
   `.txt|.env|*token*|*api-key*` value leaks into logs, tests, or
   dashboard payloads.
4. **Freshness invariant test**: every source in `REPORT_FILES`
   produces at least one item in the last 24h during market week; if
   not, the source is quarantined and its consumer degrades.

## 4. Phased implementation for Codex

Sequenced so each phase produces a measurable scorecard bump.

### Phase A - Ledger foundations (unblocks everything)

- `data/hypothesis_ledger.jsonl` schema + append-only writer
- `data/experiment_family.jsonl` schema + counter
- `data/shadow_outcomes.jsonl` schema
- `data/promotion_rules.json` frozen JSON
- `scripts/preregistration_validator.py`
- `scripts/weekly_candidate_intake.py` (scheduled Sundays 09:00 CT)
- Tests: `agent/tests/test_hypothesis_ledger.py`,
  `test_preregistration_validator.py`

### Phase B - Execution proof (5 → 8 on execution)

- `strategies/order_envelope.py`
- `scripts/broker_reconciliation_daemon.py` (scheduled every 5 min
  09:30-16:15 CT)
- `scripts/shadow_outcome_resolver.py` (scheduled 16:30 CT weekdays)
- `scripts/fill_quality_report.py` (scheduled 17:00 CT weekdays)
- `agent/tests/test_order_envelope.py`,
  `test_broker_reconciliation.py`,
  `test_shadow_outcome_resolver.py`,
  `test_fill_quality_report.py`,
  `test_replay_deterministic.py`
- Schema v7: `operations.failure_taxonomy_week`,
  `operations.reconciliation_status`

### Phase C - Detection scorecard (7 → 9 on discovery)

- `scripts/move_universe_ground_truth.py` (scheduled 16:30 CT)
- `scripts/detection_scorecard.py` (scheduled 17:15 CT)
- `scripts/universe_coverage_delta.py` (scheduled 17:20 CT)
- Extend `scripts/live_trading_cockpit.py` with
  `discovery.scorecard_rolling`
- New React page `frontend/src/pages/Detection.tsx`, route `/detection`
- Tests for each new script; frontend test for Detection page

### Phase D - Empirical calibration (7.5 → 9.5 on clarity)

- `scripts/grade_probability_service.py` (scheduled Sundays 08:00 CT)
- Extend cockpit payload to fill
  `TradingCandidate.probability` from the calibration file
- `frontend/src/components/trading/ReliabilityDiagram.tsx`
- New React page `frontend/src/pages/Calibration.tsx`, route
  `/calibration`
- Tests

### Phase E - Multi-lane replay + promotion gate (3 → 7 on edge)

- `research/multi_lane_replay.py`
- `scripts/promotion_gate.py`
- 5 frozen preregistration markdown drafts under
  `research/PREREGISTRATION_*_2026-08-*.md` (one per lane in §3a
  list). Kenny writes the specs; Codex builds the machinery.
- Tests

### Phase F - Research-process enforcement (8 → 10)

- Preregistration linter wired into a pre-commit hook
- Family-size tile on Retro tab
- Provenance chain rendered in source inspector

### Phase G - Safety hardening (9 → 10)

- `agent/tests/test_safety_chaos.py`
- Order-authority invariant test
- Secret-leak pre-commit hook
- Freshness-invariant test

### Phase H - Ship gate

- Full pytest suite green
- Full frontend suite green
- Detection scorecard shows recall@10 >= 0.6 on last 20 sessions (this
  is a MEASUREMENT, not a target; ship regardless, publish the
  actual number)
- At least one lane in intake ledger with n_resolved >= 30
- Reconciliation daemon has run for 5 consecutive market days without
  a diff alert

## 5. Non-negotiables (identical to prior handoffs)

- Trading system state = suspended / shadow-only. NO order buttons.
- `execution_enabled` and `can_submit_orders` remain hardcoded false
  in every new payload block and endpoint.
- Do NOT edit `signal_registry.json` or any live-bot config.
- Do NOT fabricate probability / GEX / catalyst / target when the
  source is missing. Degrade to "unavailable".
- Do NOT retune a rejected spec on the same dates and present as new
  evidence.
- Do NOT skip preregistration on any candidate proposed this cycle.
- Follow master handoff Git rules: no reset/clean/checkout; inspect
  before edit; isolate source/test/doc diffs from generated data on
  every commit.

## 6. Scorecard math (how to measure the bump)

Publish the scorecard as a machine-readable object at
`data/scorecard_state.json`, refreshed nightly. Each axis has an
observable rubric:

| Axis | Metric | Target for 10/10 |
|---|---|---|
| Research process | % of proposed candidates with a valid frozen spec | 100% |
| Safety and abstention | # of chaos-test cases passing | 100% of cases in the suite |
| Discovery coverage | recall@10 rolling 30d, missed-move root-cause coverage | recall@10 >= 0.75, 100% RCA coverage |
| Dashboard clarity | # of displayed grades with calibration_status = calibrated | >= 80% of active setups |
| Execution reliability | # of reconciliation diffs in last 20 sessions, replay determinism | 0 diffs, replay identical |
| Verified forward edge | # of lanes with n>=30, DSR LB>0, PBO<0.5, decay pass | >= 1 (10/10 unlocks at >=3) |
| Overall readiness | weighted avg of the above | 9.5+ |

10/10 on "verified forward edge" is genuinely unlockable only when the
evidence supports it. Kenny must accept that this axis is
outcome-gated: no amount of code makes it 10 without real forward
returns. What the blueprint does is guarantee the infrastructure is
ready to recognize a true edge as fast as one appears.

## 7. Test plan for Codex

Before marking any phase complete:

```powershell
Set-Location C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading
python -m pytest agent\tests -q -k "not slow"

Set-Location frontend
npm run test:run
npm run build
```

Per-phase additions:

- Phase A: intake ledger + preregistration validator tests
- Phase B: reconciliation, envelope, resolver, fill-quality, replay
  determinism
- Phase C: ground truth, detection scorecard, coverage delta, Detection
  page
- Phase D: calibration service, ReliabilityDiagram, Calibration page
- Phase E: multi-lane replay, promotion gate
- Phase F: preregistration linter, pre-commit hook, family tile
- Phase G: chaos, invariant, secret-leak, freshness tests

Manual smoke per phase:

- A: propose a fake spec, watch it flow through intake ledger.
- B: force a reconciliation diff in a scratch env; confirm alert
  fires; confirm no order can be submitted.
- C: check recall@10 on a known day; verify a real missed move
  appears in the postmortem.
- D: refresh calibration; confirm a bucket with n<30 shows "not
  calibrated" instead of a fabricated %.
- E: run replay on QQQ mean reversion; confirm DSR, PBO, and the
  Bonferroni denominator increment.
- F: try to commit a spec missing required fields; confirm hook
  blocks.
- G: run chaos suite; confirm every case degrades to STAND_ASIDE or
  fails closed.

## 8. Cost + time estimate for Codex

- Phase A: low (schema + linter)
- Phase B: medium (reconciliation daemon + envelope + fill quality)
- Phase C: medium (ground truth build is the hardest; needs a
  causal-move definition Kenny signs off on first)
- Phase D: low (calibration is ~200 LOC, the widget is small)
- Phase E: medium (walk-forward + CPCV + DSR + PBO are canned methods
  but must be applied uniformly across 5 lanes)
- Phase F: low
- Phase G: medium (chaos suite is broad but each case is small)

Total: 1-2 weeks of Codex time if shipped serially. Phases A, B, C
parallelize.

## 9. What NOT to touch this cycle

- `strategies/*.py` bot bodies (only the new `order_envelope.py`
  wrapper is additive)
- `signal_registry.json`
- Scheduled task registrations for existing bots (add new tasks; do
  not modify existing)
- Broker credentials, `.env`, `~/.vibe-trading/*.txt` secrets
- Existing shadow ledger files under `data/` (append only; never
  overwrite)

## 10. Handoff to Codex

Read this doc. Read the master handoff (2026-08-20) and the dashboard
10/10 handoff (2026-08-20) first. Start with Phase A. Do not
parallelize until Phase A is green. Report cost per phase per
`CLAUDE.md`. Every promotion decision must cite a rule from
`promotion_rules.json`; every rejection must cite a result-file path.

The bar is the process. If the process is honest, the edge - if it
exists - will surface. If it does not exist, the process will not
manufacture one.

End.
