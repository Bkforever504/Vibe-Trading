# CLAUDE HANDOFF — Repository Hygiene (Clean Commit Boundary)

**Date:** 2026-09-06
**Author:** Claude (Opus 4.7)
**Executor:** Codex
**Prior:** WS-CV + WS-BOOTSTRAP landed shadow-only; PR blocked by 293 dirty/untracked entries in main
**Scope:** Return repository to clean `git status` so gate-critical PRs can merge without sweeping unrelated user changes.

**Sequence position:** MUST complete before `CLAUDE_HANDOFF_FAMILY_MAPPING_FIX_2026-09-06.md`. That handoff produces a re-evaluation report requiring an isolated commit boundary.

---

## Session Summary

Codex flagged 293 dirty/untracked entries blocking a clean PR for WS-CV + WS-BOOTSTRAP work. This handoff sequences a categorize → isolate → commit-or-discard pass that yields a clean `git status` without losing any intentional work-in-flight and without silently deleting user artifacts.

---

## Non-Negotiable Invariants

- No `git add -A`, no `git add .`, no `git checkout .`, no `git clean -fdx`, no `git reset --hard`.
- No branch deletion.
- No force-push to any shared branch.
- Every commit is scoped to one logical workstream; commit messages state the workstream tag.
- Uncertain files → move to `.hold/` (gitignored) for human review, never delete.
- `.pytest_cache`, `__pycache__`, `.venv`, transient `.pytest-*` scratch dirs → confirmed via `.gitignore` addition rather than manual removal from working tree if content is untracked.
- Any file matching secret patterns (`.env*`, `*credentials*`, `*.key`, `*.pem`, `*token*`, discord webhook URLs) → NEVER staged, always moved to `.hold/secrets_review/` for rotation check first.
- If any file cannot be categorized with confidence → leave untouched, list in report, escalate to human review.

---

## Files to Create

- `scripts/hygiene/categorize_working_tree.py`
  - Reads `git status --porcelain=v1` output.
  - Classifies every entry into one of:
    - `pytest_cache` — matches `.pytest_cache/**`, `.pytest-*/`, `**/__pycache__/**`
    - `local_scratch` — matches `~*`, `.hold/**`, `output/**` (unless tracked), `data/scratch/**`
    - `secret_candidate` — matches secret patterns above; ALWAYS reported to `.hold/secrets_review/` never auto-actioned
    - `workstream_ws_cv_bootstrap` — files under `agent/governance/`, `agent/analytics/`, `agent/tests/test_statistical_gate.py`, `agent/tests/test_trial_ledger.py`, `agent/tests/test_outcome_bootstrap.py`, `agent/tests/test_paired_bootstrap.py`, `scripts/statistical_governance_report.py`, `scripts/reevaluation_report_*.md`, `docs/STATISTICAL_PROMOTION_GATE.md`, `docs/BOOTSTRAP_CI.md`, `data/governance/**`, `data/latency_pairs.jsonl`, `config/signal_families.json`
    - `workstream_ws_edgar` — files matching prior EDGAR/NBBO workstream (grep BRIDGE messages for filename hints)
    - `workstream_ws_trace` — files under `agent/observability/`, `docs/END_TO_END_TRACING.md`, `~/.vibe-trading/reports/discord-delivery-backfill.json`
    - `workstream_unknown_but_meaningful` — everything else that is NOT pytest cache / scratch / secret
    - `deletion_candidate_unknown` — genuinely orphaned files with no known owner
  - Writes categorization report to `data/hygiene/categorization_report_<date>.md`
  - Does NOT stage, delete, or move anything. Read-only pass.
- `scripts/hygiene/apply_gitignore_updates.py`
  - Diffs `.gitignore` against known-safe additions:
    ```
    .pytest_cache/
    .pytest-*/
    __pycache__/
    ~*
    .hold/
    data/scratch/
    data/hygiene/
    ```
  - Adds missing patterns; never removes existing entries.
  - Runs `git status` after to confirm files that WERE tracked are still tracked.
- `.hold/` directory with `.gitkeep` and `.hold/README.md` explaining purpose (staging area for uncategorized files; contents ignored by git).
- `docs/HYGIENE_PROCESS.md`
- `agent/tests/test_hygiene_categorizer.py`

---

## Files to Modify

- `.gitignore` — additions only, via `apply_gitignore_updates.py`. No removals.

---

## Execution Sequence for Codex

Run each step; produce output; do not proceed until output reviewed.

### Step 1 — snapshot current state

```powershell
git status --porcelain=v1 > data/hygiene/pre_hygiene_status.txt
git stash list > data/hygiene/pre_hygiene_stash_list.txt
git branch -vv > data/hygiene/pre_hygiene_branch.txt
```

Confirm no active stash contains critical work-in-flight. If stash exists, STOP and report to human.

### Step 2 — categorize read-only

```powershell
python scripts/hygiene/categorize_working_tree.py
# → data/hygiene/categorization_report_<date>.md
```

Report contents:
- Count per category.
- Full path list per category.
- `secret_candidate` list top of report; if any → STOP and escalate.
- `deletion_candidate_unknown` list flagged; NEVER auto-delete.

### Step 3 — extend `.gitignore`

```powershell
python scripts/hygiene/apply_gitignore_updates.py --dry-run
# → prints diff
# review, then:
python scripts/hygiene/apply_gitignore_updates.py
git status --porcelain=v1 | wc -l
# → count should drop significantly
```

Any file that becomes untracked due to `.gitignore` update was already NOT staged and is not lost. Verify no tracked file is now marked ignored (git will refuse — but confirm).

### Step 4 — isolate WS-CV + WS-BOOTSTRAP work

```powershell
git checkout -b hygiene/ws-cv-bootstrap-clean
# stage only files in workstream_ws_cv_bootstrap category from Step 2 report
# Codex: iterate the category list and `git add <exact_path>` each
git status --porcelain=v1
# → only WS-CV/BOOTSTRAP files staged
```

Commit with explicit workstream tag:

```
git commit -m "$(cat <<'EOF'
[WS-CV + WS-BOOTSTRAP] Statistical promotion gate + block-bootstrap CIs

- CPCV + Deflated Sharpe + PSR + PBO via purged-cross-validation + pypbo
- Trial ledger (append-only, idempotent)
- Block bootstrap CIs + paired latency test via arch + tsbootstrap
- Dashboard Governance + Latency Proof panels
- Re-evaluation of existing promoted signals: both flip_bot and iwm_options_bot enter needs_review (fail-closed on n<30)

Family mapping intentionally left in current state; family-mapping-fix handoff will
correct the mechanical assignments before Tier 2 unpauses.

Verification:
- 21 statistical gate tests pass
- 58 affected suite tests pass
- Full repo: 5725 pass, 4 skipped, 11 pre-existing failures unrelated to this work
- order_authority_guard violations=0
- execution_gate_audit: passed=True issues=0
- Health: OK=64, STALE=0, MISSING=0, ERROR=1 (pre-existing Pattern Grader)
EOF
)"
```

### Step 5 — isolate WS-TRACE work (if not already committed)

If WS-TRACE files still show as dirty per Step 2:

```powershell
git checkout -b hygiene/ws-trace-clean main
# stage only workstream_ws_trace files
# commit with [WS-TRACE] prefix
```

### Step 6 — isolate WS-EDGAR / NBBO work

Same pattern with `workstream_ws_edgar` category.

### Step 7 — handle `workstream_unknown_but_meaningful`

For each file in this category, Codex must:
- Run `git log -p -- <path>` in case the file has commit history revealing intent.
- Run `git blame <path>` on nearby files that reference it.
- If still ambiguous → move to `.hold/uncategorized_<date>/` and report to human review.
- NEVER commit unknown files into a workstream PR.

### Step 8 — handle `deletion_candidate_unknown`

- NEVER auto-delete.
- Move to `.hold/deletion_review_<date>/` with a copy of `git status` snapshot for context.
- Report list to human review.
- User decides: keep, move to real location, or delete.

### Step 9 — verify clean state per branch

For each new hygiene branch:

```powershell
git status --porcelain=v1
# → empty
git diff --check
# → clean
python scripts/execution_gate_audit.py --print
# → passed=True issues=0
python -m pytest agent/tests/ -q
# → same pass count as before hygiene work
```

### Step 10 — open PRs

Open one PR per branch:
- `hygiene/ws-cv-bootstrap-clean`
- `hygiene/ws-trace-clean` (if applicable)
- `hygiene/ws-edgar-clean` (if applicable)

Each PR description lists exact file count, verification output, and links to the categorization report.

---

## Verification Checklist

```powershell
python -m pytest agent/tests/test_hygiene_categorizer.py -q
# → all pass

# after all hygiene branches merged (or awaiting review):
git status --porcelain=v1
# → empty (or only .hold/ contents flagged as uncategorized, if any)

git diff --check
# → clean

python scripts/signal_stack_health_report.py --no-write
# → OK count unchanged from pre-hygiene

python scripts/execution_gate_audit.py --print
# → passed=True issues=0

python -m pytest agent/tests/ -q
# → same pass count as pre-hygiene (5725 pass / 4 skipped / 11 pre-existing failures)
```

---

## Success Gate

- `git status --porcelain=v1` returns 0 lines OR only `.hold/` entries (which are gitignored).
- Every WS-CV/BOOTSTRAP file lives in exactly one commit on one branch.
- Zero secret candidates staged or committed.
- Categorization report exists and is human-reviewable.
- Pre-existing 11 test failures unchanged (do not attempt to fix in this handoff).

---

## Open Positions / Active Risks

- No live positions.
- WS-CV re-evaluation report already flags `flip_bot` and `iwm_options_bot` as `needs_review`. Family-mapping-fix handoff supersedes; do not act on current re-evaluation report yet.
- 11 pre-existing test failures unchanged; separate ticket.

---

## Next Session Priority After This Ships

`CLAUDE_HANDOFF_FAMILY_MAPPING_FIX_2026-09-06.md` — sub-signal split + family taxonomy + trial_ledger migration + fresh re-evaluation.

Do NOT unpause WS-PREFECT or start any Tier 2 workstream until family mapping fix lands.

---

## Known Caveats / Deferred

- Any file in `.hold/` remains untouched by git. Human must periodically review and decide fate.
- Pattern Grader ERROR in health report is pre-existing; separate ticket, not fixed here.
- If Codex encounters ambiguity on ANY file's workstream membership, escalate rather than guess.
- Windows AppLocker restrictions on `uv`/`numpy` — respect existing pins; hygiene work does not touch dependency versions.

---

## Handoff Complete

Codex: read-only categorization first, escalate on secrets, isolate by workstream, commit with explicit tags, never `git add -A`. Return clean tree, then proceed to family-mapping-fix handoff.
