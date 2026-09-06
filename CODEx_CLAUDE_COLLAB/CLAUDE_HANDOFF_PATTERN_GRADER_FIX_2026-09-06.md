# CLAUDE HANDOFF — Pattern Grader Scheduled-Task ERROR Fix

**Date:** 2026-09-06
**Author:** Claude (Opus 4.7)
**Executor:** Codex
**Prior:** Health report shows `ERROR=1` attributed to Pattern Grader scheduled-task result; all other stack components OK
**Scope:** Diagnose root cause of Pattern Grader ERROR, apply surgical fix OR quarantine with explicit reason, restore health report to `ERROR=0`.

**Sequence position:** May run in parallel with repo hygiene and pre-existing test failure handoffs. Must complete before Tier 4a starts to preserve clean baseline.

---

## Session Summary

Signal stack health report is `OK=64, STALE=0, MISSING=0, ERROR=1`. Codex identified the sole ERROR as Pattern Grader scheduled-task result. Cause unknown from health report alone. This handoff sequences diagnose → root-cause → fix-or-quarantine to restore ERROR=0 without silencing genuine problems.

---

## Non-Negotiable Invariants

- **No silencing the health report.** Do not add ERROR-to-OK translation, do not filter Pattern Grader out of the check, do not comment out the assertion.
- **No fabricated grade output.** If Pattern Grader cannot produce a valid grade, output must remain `status="error"` or `status="missing"`; never synthesize a placeholder grade.
- **Quarantine over silence.** If the Pattern Grader is broken beyond quick repair, explicit quarantine w/ `status="quarantined", reason=<text>` is acceptable; silent removal is not.
- **Root cause every ERROR class.** RCA in PR body: what triggered ERROR, what fix addresses, what regression test locks in.
- **No modification to bot execution logic.**
- **No modification to Windows Task Scheduler entries** without human approval; if scheduling is the issue, propose the change, don't apply it.

---

## Diagnostic Steps for Codex

### Step 1 — locate Pattern Grader source

```powershell
grep -rn "pattern_grader\|PatternGrader\|pattern.grader" agent/ scripts/ config/ | head -30
```

Identify:
- Entry point (script name)
- Output location (JSON/JSONL/DB)
- Health-report consumer path (which script reads Pattern Grader status)
- Scheduled-task command (Windows Task Scheduler entry name if applicable)

### Step 2 — reproduce ERROR

```powershell
python scripts/signal_stack_health_report.py --no-write --verbose 2>&1 | grep -A5 -i pattern
```

Capture exact error message + component name + last-run timestamp + expected-vs-actual status.

Then invoke Pattern Grader directly:

```powershell
python <pattern_grader_entry_point> --dry-run 2>&1 | tail -80
```

Categorize the failure:
- **A. Never ran** — no output artifact exists; scheduler didn't fire, or fired and crashed before writing.
- **B. Ran but crashed mid-run** — partial artifact w/ error field, or empty artifact w/ non-zero exit.
- **C. Ran but output schema drifted** — artifact exists, health report reads it and rejects due to schema mismatch.
- **D. Ran but stale** — artifact exists, valid, but timestamp older than freshness threshold.
- **E. Dependency missing** — module import error, missing config, missing env var.

### Step 3 — root cause per category

**Category A (never ran):**
```powershell
# Windows Task Scheduler check
schtasks /Query /TN "*Pattern*" /FO LIST /V | more
```
Verify: task exists, is enabled, last-run timestamp, last-run result code.
Root causes: task disabled, task path uses stale python, task ran but Python crashed pre-log.

Fix: propose scheduler change to human; do NOT modify scheduler without approval per invariants.

**Category B (crashed mid-run):**
Read the last run log for the traceback.
```powershell
grep -rn "pattern_grader" ~/.vibe-trading/logs/ agent/logs/ 2>&1 | tail -20
```
Root cause examples: unhandled exception on empty input, division by zero on flat bars, timeout on data fetch, network flake.
Fix: catch specific exception, return `status="error", reason=<exception summary>`; DO NOT catch bare `Exception`.

**Category C (schema drift):**
Diff current output schema vs health-report expectation.
Fix: version the schema; write migrator if fields renamed; health-report reads via versioned schema; existing artifact tagged w/ prior version.

**Category D (stale):**
Root cause: schedule frequency mismatch vs freshness threshold, or task ran but new run has not started.
Fix: align freshness threshold to actual schedule; if schedule needs change, escalate to human.

**Category E (dependency missing):**
Verify imports; verify env vars; verify config files.
Fix: fail-honest at startup w/ explicit `raise RuntimeError("Missing env var: X")` rather than crash mid-run.

### Step 4 — surgical fix

Apply the minimum change that addresses the root cause. No refactor. No "while we're here" cleanup.

**Files likely to modify:**
- `<pattern_grader_entry_point>.py` — exception handling, schema output, or dependency assertion
- `scripts/signal_stack_health_report.py` — ONLY if health report itself misreads valid Pattern Grader output; document why in RCA

**Files likely to create:**
- `agent/tests/test_pattern_grader.py` (if absent) — unit tests covering: valid input → grade, empty input → error status not crash, missing dep → RuntimeError at start not mid-run
- `tests/regression/test_pattern_grader_error_regression.py` — locks in the fix

### Step 5 — quarantine fallback

If root cause is deep and fix would exceed this handoff scope (e.g., Pattern Grader depends on a data source that has been decommissioned), quarantine explicitly:

Add to `config/quarantined_components.json`:
```json
{
  "pattern_grader": {
    "quarantined_at": "2026-09-06T...",
    "reason": "<specific technical reason>",
    "restoration_ticket": "<link or reference to follow-up work>",
    "quarantined_by": "codex"
  }
}
```

`signal_stack_health_report.py` reads this file; quarantined components report `status="quarantined"` and do NOT count toward ERROR bucket. This is deliberately visible in health output; not hidden.

Human approval required to add anything to `quarantined_components.json`.

---

## Execution Sequence for Codex

### Step 0 — capture pre-fix state

```powershell
python scripts/signal_stack_health_report.py --no-write --verbose > data/health_snapshots/pre_fix_<date>.txt
```

### Step 1 — diagnose (Steps 1-3 above)

Write RCA to `data/pattern_grader/rca_<date>.md`. Include:
- Reproduction command output
- Category (A/B/C/D/E)
- Root cause statement
- Proposed fix or quarantine

Human reviews RCA before Codex proceeds. This is a 5-minute review; not blocking parallel work.

### Step 2 — branch and fix

```powershell
git checkout -b infra/pattern-grader-fix
# apply surgical fix per RCA
# add unit tests + regression test
```

### Step 3 — verify

```powershell
python <pattern_grader_entry_point> --dry-run
# → completes without ERROR

python scripts/signal_stack_health_report.py --no-write --verbose
# → ERROR=0 OR Pattern Grader explicitly quarantined and reported as such

python -m pytest agent/tests/test_pattern_grader.py tests/regression/test_pattern_grader_error_regression.py -q
# → all pass

python -m pytest agent/tests/ -q
# → same pass count as pre-fix baseline (or higher w/ new tests); no regressions

python scripts/execution_gate_audit.py --print
# → passed=True issues=0

git diff --check
# → clean
```

### Step 4 — capture post-fix state

```powershell
python scripts/signal_stack_health_report.py --no-write --verbose > data/health_snapshots/post_fix_<date>.txt
diff data/health_snapshots/pre_fix_<date>.txt data/health_snapshots/post_fix_<date>.txt
```

Confirm the diff shows exactly: Pattern Grader ERROR → OK (or → quarantined), everything else unchanged.

### Step 5 — open PR

PR body includes:
- Link to RCA document
- Category (A/B/C/D/E)
- Fix summary
- Pre/post health snapshots
- Verification output

---

## Verification Checklist

```powershell
python <pattern_grader_entry_point> --dry-run
# → exit 0, valid output

python scripts/signal_stack_health_report.py --no-write
# → ERROR=0 OR quarantined_count=1 (visible in output)

python -m pytest agent/tests/test_pattern_grader.py tests/regression/test_pattern_grader_error_regression.py -q
# → all pass

python -m pytest agent/tests/ -q
# → no regressions vs pre-fix baseline

python scripts/execution_gate_audit.py --print
# → passed=True issues=0
```

---

## Success Gate

- Health report shows `ERROR=0` OR Pattern Grader explicitly quarantined with human-approved reason recorded.
- Root cause documented in RCA file, not just "fixed".
- Regression test locks in the fix.
- Zero silencing of the health check.
- No previously-passing test regressed.

---

## Open Positions / Active Risks

- No live positions.
- If Pattern Grader is discovered to feed any promoted signal → fixing it may materially change signal output. STOP, escalate; do not silently alter signal behavior.

---

## Known Caveats / Deferred

- **Windows Task Scheduler modifications** require human approval per invariants; Codex proposes, human applies.
- **If quarantine is the outcome**, human must approve `quarantined_components.json` addition. Follow-up ticket required before quarantine expires.
- **Pattern Grader output consumers** — before fix, run `grep -rn "pattern_grader" agent/ scripts/ config/` to enumerate every consumer; fix must not break any consumer's expected schema.

---

## Handoff Complete

Codex: reproduce → categorize → RCA → fix or quarantine → regression test → PR. Never silence the health report. Never fabricate a grade. Escalate before altering signal behavior.
