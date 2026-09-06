# CLAUDE HANDOFF — Pre-Existing Test Failures (11 failures)

**Date:** 2026-09-06
**Author:** Claude (Opus 4.7)
**Executor:** Codex
**Prior:**
- WS-CV + WS-BOOTSTRAP landed clean (5,725 pass / 4 skipped / 11 pre-existing failures unchanged)
- `CLAUDE_HANDOFF_REPO_HYGIENE_2026-09-06.md` and `CLAUDE_HANDOFF_FAMILY_MAPPING_FIX_2026-09-06.md` in queue

**Scope:** Root-cause and fix each of the 11 pre-existing test failures Codex flagged. Surgical, one PR per fix category, no blanket skips.

**Sequence position:** May run in parallel with repo hygiene handoff. Must complete before Tier 4a starts, because Tier 4a landing on a red baseline confuses signal.

---

## Session Summary

Codex reported 11 pre-existing failures spanning three categories:
1. Flip contract-limit test configuration
2. Needs-review fixture date windows
3. Shadow-volume coverage classification

None caused by recent WS-CV / WS-BOOTSTRAP / WS-TRACE / WS-EDGAR work. All pre-date this stack of handoffs. This handoff sequences a diagnose → root-cause → surgical-fix pass with one PR per category to keep diffs reviewable.

---

## Non-Negotiable Invariants

- **No `pytest.mark.skip` or `pytest.mark.xfail`** to make a failing test green. Those are declarations of surrender, not fixes.
- **No assertion loosening** (`assert x > 0` → `assert x >= -1`) without a documented root cause AND a corresponding code fix.
- **No fixture date backfill to "now"** unless the test genuinely intends "recent"; if the test intends specific historical dates, fix the fixture generator, not the assertion.
- **Root-cause every failure.** Write the RCA in the PR body: "expected X because Y; observed Z because W; fix addresses W".
- **One PR per category.** Diffs stay reviewable. No omnibus.
- **No modification to bot execution logic.** These are test-layer fixes. If a test failure reveals a real bot bug, STOP, escalate, do not silently fix bot logic under cover of a test-fix PR.
- **Do not touch WS-CV, WS-BOOTSTRAP, WS-TRACE, WS-EDGAR files** — those PRs must land clean; this handoff is orthogonal.
- **Every fix ships with a regression test** that would fail if the fix regresses. Not the SAME test that was failing — a new test locking in the invariant.

---

## Execution Plan Per Category

### Category 1 — Flip contract-limit test configuration

**Symptom (per Codex):** "Flip contract-limit test configuration" failing.

**Likely root causes to investigate (Codex to verify against source):**
- Test fixture hardcodes a contract-count assumption that no longer matches current config (e.g., config bumped from 4 to 6 contracts, test still asserts 4).
- Config source-of-truth moved (e.g., from `config/flip_bot.yaml` to env var), test reads stale path.
- Test asserts against a computed limit that now depends on a runtime state (drawdown budget, market condition) not present in fixture.

**Diagnostic steps for Codex:**
```powershell
python -m pytest <path/to/failing/flip_contract_limit_test.py> -v --tb=long
grep -rn "contract_limit\|max_contract\|MAX_CONTRACTS" agent/flip_bot.py config/ tests/
git log -p --all -- <config file> | head -200
```

Identify: (a) what value the test asserts, (b) what value the code now produces, (c) which is correct.

**Fix approach:**
- If code value is correct → update fixture to reflect current config; add comment linking to the config source-of-truth.
- If test value is correct → real bot bug. STOP. Escalate. Do NOT fix bot logic in this handoff.
- If both are technically correct but for different regimes → test needs to parameterize the regime; add regime fixture; assert per-regime expected value.

**Files to modify:**
- Failing test file
- Optionally: `tests/fixtures/flip_bot_config.py` if fixture is misaligned

**Files to create:**
- `tests/regression/test_flip_contract_limit_regression.py` — locks in the fix so re-regression is caught

**PR title:** `[TEST-FIX] Flip contract-limit test config aligned with current bot config`

---

### Category 2 — Needs-review fixture date windows

**Symptom (per Codex):** "needs-review fixture date windows" failing.

**Likely root causes:**
- Fixture uses `datetime(2026, 1, 15)` or similar hardcoded date; test window has drifted past it.
- Fixture uses `datetime.now() - timedelta(days=X)` but assertion expects window boundary aligned to a specific date.
- Reconciliation window changed in code (e.g., 30 days → 14 days), fixtures still generate 30 days of data.

**Diagnostic steps for Codex:**
```powershell
python -m pytest <path/to/needs_review_test> -v --tb=long
grep -rn "needs_review\|reconciliation_window\|review_window" agent/ scripts/ tests/
```

Identify whether the test expects a FIXED reference date (e.g., "the day the bot went live") or a RELATIVE window ("last 30 days from now").

**Fix approach:**
- If fixed reference: parameterize via `pytest.fixture` producing dates relative to a `REFERENCE_DATE` constant defined in one place; import everywhere.
- If relative: use `freezegun` or equivalent to freeze `datetime.now()` for the test; assertions become deterministic; no more drift.
- Do NOT patch `datetime` globally; scope the freeze to the test class.

**Files to modify:**
- Failing test file
- `tests/fixtures/date_windows.py` (create if not present) — centralize reference dates

**Files to create:**
- `tests/regression/test_needs_review_date_window_regression.py`

**Dependency:** May need `pip install freezegun` if not already present. Pin version.

**PR title:** `[TEST-FIX] Needs-review fixture dates frozen against REFERENCE_DATE constant`

---

### Category 3 — Shadow-volume coverage classification

**Symptom (per Codex):** "shadow-volume coverage classification" failing.

**Likely root causes:**
- Coverage classifier (buckets like `low_volume`, `median_volume`, `high_volume`) uses thresholds that shifted with new data.
- Threshold was hardcoded and never updated; distribution moved.
- Test asserts a ticker in `high_volume` bucket that now falls in `median` due to real volume change.
- Classifier expects `avg_daily_volume` field renamed or refactored.

**Diagnostic steps for Codex:**
```powershell
python -m pytest <path/to/shadow_volume_test> -v --tb=long
grep -rn "shadow_volume\|volume_bucket\|coverage_class" agent/ scripts/ tests/
```

Identify: (a) is threshold hardcoded, (b) is threshold computed from distribution, (c) has the underlying data source changed schema.

**Fix approach:**
- If threshold hardcoded and distribution drifted: replace w/ percentile-based classifier (`low = below p33`, `median = p33-p66`, `high = above p66`); assertions become distribution-relative.
- If schema changed: fix classifier to read new schema; do NOT paper over w/ `.get(field, default)`.
- If test data itself is stale: regenerate test fixtures from a KNOWN snapshot committed to `tests/fixtures/shadow_volume_snapshot_<date>.json`; assertions use that snapshot; snapshot regen is a manual step w/ human review.

**Files to modify:**
- Failing test file
- `agent/analytics/shadow_volume_classifier.py` (or equivalent) if percentile refactor
- `tests/fixtures/shadow_volume_snapshot_<date>.json` (new snapshot)

**Files to create:**
- `tests/regression/test_shadow_volume_classification_regression.py`

**PR title:** `[TEST-FIX] Shadow-volume classifier uses distribution-relative thresholds`

---

## Files to Create (Cross-Cutting)

- `docs/TEST_FIX_PROCESS.md` — codifies the no-skip rule, RCA-in-PR-body requirement, one-PR-per-category discipline, regression-test requirement.

---

## Execution Sequence for Codex

### Step 0 — precondition

```powershell
python -m pytest agent/tests/ -q 2>&1 | tail -50
# → confirm 11 failures unchanged; capture exact test IDs
```

Persist failing test IDs to `data/testfix/pre_fix_failures_<date>.txt` for later diff.

### Step 1 — categorize failures

Map each of the 11 failing test IDs to one of the 3 categories above. If a failure doesn't fit → NEW category, add to this handoff or spawn a separate one.

Output: `data/testfix/failure_categorization_<date>.md` w/ table of `test_id → category → root_cause_hypothesis`.

### Step 2 — one branch per category

```powershell
git checkout -b testfix/flip-contract-limit
# fix + regression test
# verify: only Flip tests changed status
```

Repeat for `testfix/needs-review-dates` and `testfix/shadow-volume-classifier`.

### Step 3 — verify per branch

```powershell
python -m pytest agent/tests/ -q 2>&1 | tail -50
# → previously-failing tests in this category now pass
# → NO previously-passing test now fails
# → total pass count = 5725 + (fixes in this branch) + new regression tests
```

If any previously-passing test breaks → STOP, revert, investigate.

### Step 4 — audit unchanged surfaces

```powershell
python scripts/execution_gate_audit.py --print
# → passed=True issues=0
python scripts/signal_stack_health_report.py --no-write
# → OK count unchanged
git diff --check
# → clean
grep -rn "pytest.mark.skip\|pytest.mark.xfail" tests/ agent/tests/ | wc -l
# → count did NOT increase vs pre-fix baseline
```

### Step 5 — open PRs

One PR per branch. Body of each PR includes:
- Failing test IDs before fix
- Root cause analysis (why it failed, why it now passes)
- Fix summary
- New regression test ID
- Verification output

### Step 6 — after all merged

```powershell
python -m pytest agent/tests/ -q 2>&1 | tail -50
# → 5725+N pass, 4 skipped, 0 failures
```

---

## Verification Checklist

```powershell
python -m pytest agent/tests/ -q
# → 0 failures

grep -rn "pytest.mark.skip\|pytest.mark.xfail" tests/ agent/tests/
# → count unchanged vs baseline

python scripts/execution_gate_audit.py --print
# → passed=True issues=0

python scripts/signal_stack_health_report.py --no-write
# → OK count unchanged or higher; STALE=0; MISSING=0; ERROR<=1 (Pattern Grader handled in separate handoff)

git status --porcelain=v1
# → empty on each branch
```

---

## Success Gate

- All 11 pre-existing failures resolved via ROOT-CAUSE fix, not skip/xfail.
- 3 new regression tests locked in.
- No previously-passing test regressed.
- No bot execution logic modified.
- Zero increase in skip/xfail counts.
- Each fix ships in isolated PR with RCA in body.

---

## Open Positions / Active Risks

- No live positions.
- If any test failure diagnosis reveals a real bot bug (not test-layer bug) → STOP, escalate to human, do NOT fix bot logic under this handoff.

---

## Known Caveats / Deferred

- **Pattern Grader ERROR=1** handled separately in `CLAUDE_HANDOFF_PATTERN_GRADER_FIX_2026-09-06.md`.
- **`freezegun` dependency** may be needed for Category 2; pin version, add to `requirements.txt` in that PR.
- If Codex's category enumeration reveals more than 3 real categories, add categories to this handoff before proceeding — do not force-fit into three buckets.

---

## Handoff Complete

Codex: diagnose first, root-cause per test, one branch per category, no skip/xfail escape hatches, regression test per fix. If a test failure reveals a real bot bug, stop and escalate.
