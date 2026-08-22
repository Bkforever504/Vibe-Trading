# CODEX MASTER HANDOFF — 2026-08-22

**From:** Claude Opus 4.7 (session 2026-08-22)
**To:** Codex (next fresh session)
**Repo:** `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading`
**Branch:** main (7 commits landed this session)

---

## 0. Session Summary — What Kenny Asked, What Landed

**Kenny's ask:** Build a system where the dashboard recognizes the most complex market-structure setups for the best entry and exit trades. Simplest → most complex patterns w/ entry + exit. Perfect timing. Grade every setup.

**What shipped across the day (Claude spec + Codex build):**

1. **Pattern Grader Phase 1** — Full spectrum detection (classical, candlestick, volume, SMC/ICT, Wyckoff, orderflow proxy, options, liquidity, MTF combos). A/B/C/D grade rubric w/ 6 weighted components + 4 multiplicative penalties. Streaming Opportunity Engine w/ CBC strong-flip, PDH/PDL/PWH/PWL, session sweep/reclaim, CISD CE. Manual-only.
2. **CISD detector** — Full ICT sequence (HTF FVG → 3rd-candle range → sweep → IFVG → CISD). Body-close required. RTH-anchored. `unvalidated_pattern_hypothesis` gated by ≥100 outcomes + ≥30 dates + Wilson lower-bound + positive Brier skill.
3. **Phase A — Research governance** — Append-only hypothesis + experiment-family ledgers, frozen-spec validator, weekly candidate intake (Sunday 09:00 CT).
4. **Phase B — Execution reliability** — Idempotent fail-closed order envelope, broker reconciliation daemon, shadow outcome resolver, fill-quality report, cockpit schema v7.
5. **Phase C — Detection scorecard** — Fail-closed placeholder ground-truth loader (activates when Kenny approves spec), precision/recall/coverage-delta per pattern, CISD progress card in DetectionTab, additive schema v9.
6. **Phase G — Safety hardening** — Chaos tests, order-authority invariants, secret-leak pre-commit hook, freshness invariants, 24-hour source quarantine telemetry.

**Verification (Codex last reports):**
- Full agent suite: 5,078+ passing
- Frontend: 216 passing
- Production build: passing
- `execution_gate_audit.py`: 0 issues (9 non-blocking warnings)
- `execution_enabled=false`, `can_submit_orders=false` enforced everywhere
- $0 external cost across all sessions

---

## 1. Git State — Now Committed

**7 commits landed this session (Claude):**

```
2a518f3 feat: pre-commit hooks + governance ledgers + preregistration CI
531d6b0 chore: untrack data ledger JSONLs (now gitignored)
fa6735f docs: Codex handoffs, knowledge docs, session status
34e8977 docs+data: research specs, pattern taxonomy, ground-truth spec
6f5e79e feat: frontend dashboard intel layer + Codex strategy additions
ab39f36 feat: Phases A/B/C/G governance + pattern grader (Codex + Claude session)
37da6da chore: gitignore large data artifacts and pytest scratch dirs
```

**Worktree clean.** Only `tools/tradingview-mcp` submodule pointer + `output/` dir remain untracked (benign).

**Gitignore now excludes:**
- `data/databento/*.{parquet,dbn.zst,jsonl}` (>3GB refetchable)
- `data/*.jsonl` append-only logs
- `data/*.json` snapshots (except `promotion_rules.json` + schemas)
- `data/*.csv`, `.playwright-cli/`, pytest scratch dirs

**Explicitly re-included (governance ledgers):**
- `data/promotion_rules.json`
- `data/experiment_family.{jsonl,schema.json}`
- `data/hypothesis_ledger.{jsonl,schema.json}`

---

## 2. Scheduler State — Monday Ready

**All 18 Vibe tasks in `Ready` state.** Confirmed via `Get-ScheduledTask -TaskName '*Vibe*'`:

| Task | Cadence | Purpose |
|---|---|---|
| VibeTradingShadowScanner | intraday | Pattern grader + CISD detection |
| VibeTradingGradeCalibration | daily | Grade rubric health |
| VibeTradingDetectionScorecard | daily post-close | Precision/recall/coverage-delta |
| VibeTradingMoveGroundTruth | daily post-close | Ground-truth labeling (placeholder until Kenny approves spec) |
| VibeTradingUniverseCoverageDelta | daily | Coverage delta computation |
| VibeTradingShadowOutcomeResolver | 16:30 CT | Fills outcome fields |
| VibeTradingBrokerReconciliation | 5-min RTH | Phase B reconciliation |
| VibeTradingFillQuality | daily | Fill quality report |
| VibeTradingWeeklyCandidateIntake | Sunday 09:00 CT | Phase A intake |
| VibeTradingEdgeForwardTracker | daily | Edge tracker |
| VibeTradingWinnerDnaMatchedReplay | daily | Replay match |
| VibeTradingOptionsShadowTwin | intraday | Options shadow |
| VibeTradingNightlyOptionsNBBOEvidence | nightly | Options evidence |
| VibeTradingGarchVolatilityRisk | daily | Vol risk |
| VibeTradingPortfolio-Monitor | 5-min RTH | Portfolio monitor |
| VibeTradingDashboardServer | continuous | Dashboard server |
| Vibe-Trading-Remote-Dashboard | Running | Live dashboard |
| Vibe-Trading-Remote-Dashboard-Fallback | fallback | Failover |

Only `VibeTradingNinjaTraderMESSim` is Disabled (unrelated legacy).

---

## 3. What Blocks Real Numbers

Two spec files require Kenny sign-off before graders produce real (non-placeholder) output:

### 3.1 Ground-Truth Spec — Detection Scorecard Activation
- **File:** `research/MOVE_GROUND_TRUTH_SPEC_2026-08-20.md`
- **Current status:** `Status: draft`, `Kenny Approval: pending`
- **What it defines:** magnitude thresholds per instrument×TF, direction retention, R-multiple gate, session boundaries, ledger schema, coverage-delta math
- **Kenny action:** review §2 thresholds, flip both markers to `frozen` + `approved`
- **Result:** `scripts/move_universe_ground_truth.py` activates real loader, DetectionTab shows non-zero coverage delta

### 3.2 Five Frozen Strategy Specs — Phase D Calibration Unblock
- **Files:** `research/FROZEN_STRATEGY_{1..5}_2026-08-22.md`
- **Current status:** all `draft`/`pending`
- **What they define:** Kenny's five actual trading hypotheses (instrument, TF, entry, exit, sizing, success gates, kill criteria, data sources, backtest reqs)
- **Kenny action:** fill sections 1–10 in each file, flip markers
- **Result:** `frozen_strategy_loader.py` (Codex to build in Phase D) auto-populates `hypothesis_ledger.jsonl`, replay pipeline runs, Phase D calibration begins

**Neither requires code changes to start.** Kenny writes markdown, loaders wake up on next run.

---

## 4. Next Codex Work — CISD Promotion Tracker

**Spec:** `CODEx_CLAUDE_COLLAB/CODEX_PROMPT_CISD_PROMOTION_TRACKER_2026-08-22.md`

**Full deliverables:**
1. `scripts/pattern_grader_outcome_resolver.py` — fills `outcome_5m/15m/60m/eod` in grader JSONL from forward bars
2. `scripts/cisd_promotion_tracker.py` — aggregates CISD outcomes, computes Wilson lower bound + Brier skill, writes `cisd-promotion-status.json`
3. `frontend/src/components/detection/DetectionTab.tsx` — add CISD Progress card w/ 4 stat pills + validated/unvalidated status pill
4. `scripts/promote_validated_patterns.py` — auto-flips `pattern_taxonomy.json` governance_status once all 4 gates pass
5. `scripts/register_cisd_tracker_tasks.ps1` — 3 scheduler tasks (outcome resolver 16:35, tracker 16:40, promoter 16:45)
6. Tests: 4 files covering resolver, tracker (Wilson + Brier math, gate edge cases), promoter (idempotent + audit ledger), DetectionTab render

**Non-negotiables (Phase A/B/C/G all hold):**
- `execution_enabled=false`, `can_submit_orders=false`
- No bot bodies, no signal registry mods, no credentials, no canonical JSONL mutations
- `execution_gate_audit.py` stays at 0 issues
- Fail-closed on missing data — never fabricate outcomes
- Deterministic replay

**Success criteria:**
- All new tests pass
- Agent suite delta ≤ +10 tests
- Frontend delta ≤ +5 tests
- Prod build green
- `cisd-promotion-status.json` emits (likely n=0 until Monday scanner runs)
- $0 external cost

**Halt after step 6. Report to `CODEX_STATUS_CISD_TRACKER_YYYY-MM-DD.md`.**

---

## 5. Deferred Work (After Kenny Signs)

### 5.1 Phase D — Frozen Strategy Replay + Calibration
After Kenny freezes ≥ 1 strategy spec:
1. `scripts/frozen_strategy_loader.py` — reads `FROZEN_STRATEGY_*.md`, only loads frozen+approved
2. Each frozen spec auto-populates `hypothesis_ledger.jsonl`
3. `scripts/replay_frozen_strategies.py` — runs against historical bars, emits per-strategy replay JSON
4. Frontend Detection tab: per-strategy progress toward success gates
5. Grade calibration: rolling win rate + Brier per pattern × instrument × TF, feeds back into `pattern_taxonomy.json` `base_rate` fields (overrides Bulkowski defaults w/ measured stats)

### 5.2 Phase E — True Order Flow (Tick Data)
Only after Databento or Rithmic feed decision:
1. Ingest tick data
2. Build true stacked-imbalance, absorption, iceberg, sweep detectors (drop `_proxy` suffix)
3. Add footprint chart to dashboard

### 5.3 Phase 3 — A-Grade Auto-Execute
After ≥ 30 shadow days + Kenny sign-off + A-grade realized win rate ≥ 0.65 + avg R ≥ 1.5:
1. `agent/src/policies/pattern_grade_execution_policy.py`
2. Registry entry: `can_submit_orders=true, execution_enabled=false` initially
3. `execution_gate_audit.py` whitelist update
4. Paper account 5-day run
5. Kenny toggles `execution_enabled=true`

---

## 6. Files Written This Session (Claude, 2026-08-22)

**Handoff + spec docs:**
- `CODEx_CLAUDE_COLLAB/CLAUDE_HANDOFF_PATTERN_GRADER_2026-08-22.md`
- `CODEx_CLAUDE_COLLAB/CODEX_PROMPT_PATTERN_GRADER_2026-08-22.md`
- `CODEx_CLAUDE_COLLAB/CODEX_PROMPT_CISD_PROMOTION_TRACKER_2026-08-22.md`
- `CODEx_CLAUDE_COLLAB/CODEX_HANDOFF_MASTER_2026-08-22.md` (this file)

**Research packs:**
- `research/pattern_detection_rules_classical.md`
- `research/pattern_detection_rules_smc_wyckoff.md`
- `research/MOVE_GROUND_TRUTH_SPEC_2026-08-20.md` (draft)
- `research/FROZEN_STRATEGY_SPECS_INDEX_2026-08-22.md`
- `research/FROZEN_STRATEGY_{1..5}_2026-08-22.md` (5 skeletons)

**Infra:**
- `.gitignore` — heavy data + pytest scratch exclusions

**All committed in the 7 commits listed §1.**

---

## 7. Fastest Path from Here (recommended order)

1. **Kenny — 30 min:** review + flip `MOVE_GROUND_TRUTH_SPEC_2026-08-20.md` to `frozen`/`approved`. Adjust §2 thresholds first if numbers feel off.
2. **Kenny — 1–3 hours:** draft `FROZEN_STRATEGY_1_2026-08-22.md` sections 1–10 for his best-conviction strategy. Freeze it.
3. **Codex — parallel:** execute `CODEX_PROMPT_CISD_PROMOTION_TRACKER_2026-08-22.md`. No Kenny input needed. Halt for review.
4. **Monday market open:** scheduler auto-runs scanner + grader + resolver + scorecard. Watch dashboard.
5. **Post-market Monday:** Kenny reviews first live grade distribution + coverage delta. Adjusts ground-truth thresholds if labels too sparse/noisy.
6. **After 5+ trading days of shadow data:** Codex builds Phase D replay pipeline against the frozen strategies.
7. **After 30 trading days:** evaluate promotion gates; Kenny decides A-grade auto-execute go/no-go.

---

## 8. Non-Negotiables — Reprinted for Clarity

These have held through every Phase and MUST continue:

1. **No live execution changes without Kenny approval.** All new registry entries `can_submit_orders=false, execution_enabled=false`.
2. **`execution_gate_audit.py` must pass** after every registry change. If not, revert.
3. **Never edit** `agent/strategies/flip_bot.py` or `iwm_options_bot.py` as part of grader/detection work.
4. **Signal registry schema frozen:** `can_submit_orders`, `execution_enabled`, `can_read_order_history` are immutable safety contracts.
5. **Kill switch dominates.** `data/kill_switch.flag` presence suppresses all A-grade actionable prompts.
6. **Data freshness gate:** real-time bars w/ `now - bar_close_ts > 60s` = reject + log `freshness_violation`.
7. **No new API keys embedded.** All new providers go through `.env.example`.
8. **Windows scheduler jobs idempotent.**
9. **Order-flow proxies suffixed `_proxy` in pattern IDs** until true tick data lands.
10. **Backwards-compat:** dashboard renders even if any new report JSON missing (guard w/ `exists()`).
11. **Fail-closed on missing spec approval:** loaders stay in placeholder mode until `Status: frozen` AND `Kenny Approval: approved`.
12. **Deterministic detectors:** no random state, no wall-clock reads inside detector logic.

---

**END OF MASTER HANDOFF. Codex next action: execute CODEX_PROMPT_CISD_PROMOTION_TRACKER_2026-08-22.md, halt for review.**
