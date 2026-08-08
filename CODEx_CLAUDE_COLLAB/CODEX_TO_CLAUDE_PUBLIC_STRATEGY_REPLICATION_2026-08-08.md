# Codex To Claude: Public SPY/SPX Strategy Replication League

Date: 2026-08-08

Repository: `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading`

Implementation commit: `b6c5797 Add public strategy replication league`

Prior SPY execution hardening commits:

- `7315e14 Harden SPY options execution and evidence gates`
- `979951e Add Claude handoff for SPY execution hardening`

Requested Claude role: independent adversarial reviewer, then next-stage data
adapter builder. Do not redesign production execution or weaken any gate.

## Objective

Use public traders as a hypothesis funnel without treating screenshots,
self-reported PnL, testimonials, or post-entry calls as evidence. Convert a
disclosed strategy into a frozen deterministic rule, preserve every eligible
call in tamper-evident storage, reconstruct entries and exits from point-in-time
OPRA executable quotes, and rank cohorts under a fixed conservative standard.

This implementation does not copy orders and does not claim a profitable edge.

## Current Honest State

- The replication league code is complete and committed.
- No public strategy rule has been registered as real evidence.
- No production replication ledger has been created.
- No public signal has been promoted.
- No reconstructed public-strategy outcome exists.
- Nominee count is therefore zero.
- No orders were submitted.
- Existing broker and portfolio safety controls were not changed.

The empty state is intentional. Templates are not strategies and cannot be
reported as evidence.

## Files Added

### Core pipeline

`scripts/public_strategy_replication.py`

Key surfaces:

- line 144: `verify_ledger` verifies the sequence and SHA-256 chain.
- line 185: `append_events` rejects event-ID collisions and appends only.
- line 256: `normalize_rule` freezes and hashes deterministic rules.
- line 336: `register_rules` rejects mutation of an existing version.
- line 377: `snapshot_verified_signals` accepts only eligible pre-entry calls.
- line 479: `normalize_coverage_manifest` requires complete capture, deletion
  tracking, a bounded poll interval, and an archive hash.
- line 550: `normalize_replay_outcome` validates OPRA timing, quote side,
  liquidity, frozen regime method, and computes PnL independently.
- line 654: `import_replay_outcomes` enforces one outcome per signal.
- line 743: `_cohort_report` applies the frozen nomination gates.
- line 829: `build_report` emits a non-executable league report.

### Preregistration and operator contract

- `research/PUBLIC_STRATEGY_REPLICATION_PREREGISTRATION_2026-08-08.md`
- `research/public_strategy_replication/README.md`
- `research/public_strategy_replication/strategy_rule.template.json`
- `research/public_strategy_replication/coverage_manifest.template.json`
- `research/public_strategy_replication/executable_outcome.template.json`
- `scripts/run_public_strategy_replication_report.ps1`

### Tests

`agent/tests/test_public_strategy_replication.py`

Twelve direct tests cover:

- immutable rule hashes and limit-only entry policy
- frozen-version mutation rejection
- historical ledger edit detection
- pre-entry and replay-eligibility enforcement
- option-underlying normalization
- exclusion of signals predating the frozen rule
- pipeline-computed PnL rather than claimed PnL
- OPRA-only reconstruction
- conflicting second-outcome rejection
- complete source coverage and deletion-tracking requirements
- permanent denial of paper and execution authority, even for a synthetic
  cohort that clears every statistical nomination gate

## Event Model

The independent append-only ledger is:

`data/public_strategy_replication_log.jsonl`

It has four event types:

1. `rule_registered`
2. `signal_snapshot`
3. `source_coverage_manifest`
4. `replay_outcome`

Every event contains:

- stable event ID
- schema version
- ingestion timestamp
- `execution_enabled: false`
- `can_submit_orders: false`
- `promotion_eligible: false`
- sequence number
- previous event hash
- current event hash

Any edit, insertion, removal, reorder, malformed line, or conflicting reuse of
an event ID fails closed before report generation.

## Frozen Rule Contract

Every rule version requires:

- attributed source traders
- SPY, SPX, or XSP scope
- Eastern Time session windows
- structured entry predicates
- OPRA contract-selection policy
- maximum quote age and spread
- limit-only entries and no market fallback
- deterministic stop, target, and time exit
- no-trade conditions
- regime filters and a hashed regime definition
- maximum account risk no greater than 1%

A logic change requires a new version. A registered `rule_id + version` cannot
be overwritten with a different hash.

## Source Signal Treatment

The front end remains `scripts/verified_trader_intake.py`. The replication
snapshot accepts only records that are:

- `event.type == signal`
- not quarantined
- replay eligible
- observed at or after their source timestamp
- attributed to a trader named by the frozen rule
- within the rule's instrument scope

Signals captured before `rule.frozen_at` remain historical diagnostics and do
not enter forward counts. A valid point-in-time market join must occur after
observation and within the frozen maximum quote age.

X posts remain context-only under the existing intake policy. Do not make raw X
posts replay eligible merely to increase sample size.

## Outcome Calculation

An outcome must reference one captured signal and the exact rule hash. It must
use OPRA executable quotes and the frozen regime-definition hash.

For long premium:

- entry executable value must be at or above midpoint
- exit executable value must be at or below midpoint

For short premium, those sides are reversed.

The pipeline computes:

- gross PnL
- round-trip spread friction
- net PnL after fees and additional slippage
- net R using declared capital at risk
- doubled-cost PnL and R

An input field claiming PnL is ignored. A second different outcome for one
signal is rejected. Trading dates are derived from the entry timestamp in
`America/New_York`, not trusted from the input.

## Fixed Nomination Gates

All must pass for `forward_shadow_nominee`:

- 30 or more forward pre-entry signals
- 30 or more reconstructed outcomes
- 20 or more independent dates
- source-manifest coverage at least 95%
- valid point-in-time joins at least 80%
- outcome reconstruction rate at least 80%
- positive one-sided 95% full-sample executable LCB
- final chronological 25% holdout with at least 10 outcomes
- positive holdout executable LCB
- profit factor at least 1.20
- positive doubled-cost expectancy
- positive expectancy after removal of the best 1% and best 5%
- maximum cumulative drawdown no greater than 10R
- two or more positive regimes with at least five outcomes each

Even a nominee emits:

- `paper_gate_ready: false`
- `production_change_allowed: false`

Independent adversarial review and explicit human approval remain mandatory.

## Verification

Final focused command:

```powershell
python -m pytest agent/tests/test_public_strategy_replication.py agent/tests/test_verified_trader_intake.py agent/tests/test_winner_dna_matched_replay.py agent/tests/test_spy_spx_execution_upgrade.py agent/tests/test_point_in_time_quotes.py agent/tests/test_execution_gate_audit.py -q
```

Result: `71 passed`.

Final full command, run after commit `b6c5797`:

```powershell
python -m pytest -q
```

Result: `4483 passed, 4 skipped, 4 warnings in 225.52s`.

The warnings are existing FastAPI/Starlette/websockets deprecations. Ruff and
Black are not installed in the active Python 3.12 environment. `py_compile`,
`git diff --cached --check`, focused tests, and the full suite passed.

## Operator Commands

Use the templates only after replacing every placeholder with independently
captured evidence:

```powershell
python scripts/public_strategy_replication.py register-rules --input <rules.json>

python scripts/public_strategy_replication.py snapshot-signals `
  --verified-journal data/verified_trader_evidence_log.jsonl `
  --rule-id <rule_id> `
  --version <version>

python scripts/public_strategy_replication.py import-coverage --input <manifests.json>
python scripts/public_strategy_replication.py import-outcomes --input <outcomes.json>
python scripts/public_strategy_replication.py verify
python scripts/public_strategy_replication.py report --print
```

Do not register the example template as an actual public strategy.

## Claude P0 Adversarial Review

Attack these assumptions before adding network adapters:

1. Can an operator forge a source coverage manifest without possessing the
   referenced archive?
2. Can captured-record counts diverge from archive contents without detection?
3. Can a deleted or revised losing call disappear from the denominator?
4. Can timestamp normalization, DST, or delayed OPRA packets create look-ahead?
5. Can aggregate multi-leg executable values combine legs from different quote
   moments?
6. Can one source call be attributed to multiple rules after its outcome is
   known?
7. Can a missing or unfilled call avoid the reconstruction-rate penalty?
8. Can capital at risk be understated to inflate R?
9. Can a regime label be misclassified while presenting the correct frozen
   regime hash?
10. Can replacement of the complete local ledger and regenerated hashes evade
    detection because no external head-hash archive exists?

Implement fixes for genuine findings and add regression tests. Do not lower a
threshold to make a cohort pass.

## Next Builds

### P0: Archive-bound source coverage

Add a lawful capture adapter that creates an immutable raw archive and computes
the manifest from archive bytes rather than trusting entered counts or hashes.
Publish each daily ledger head hash to a separately controlled location.

Preferred first source: authenticated TradingView webhooks from a cooperating
trader who explicitly permits research. A user-owned export with complete
timestamps is also acceptable. Do not scrape private groups or bypass access
controls.

### P0: OPRA lifecycle reconstructor

Convert existing Databento/OPRA candidate quote data into the executable
outcome schema. Requirements:

- next quote after observed time, never prior quote
- bounded join age
- correct buy/sell executable side
- synchronized multi-leg snapshots
- fees and additional slippage
- unfilled and stale calls retained in the denominator
- frozen regime classification with point-in-time inputs

### P1: Source revision monitor

Represent edits and deletions explicitly in the archive. The final captured
call before entry must remain reconstructable, and post-outcome edits must not
rewrite the strategy or signal.

### P1: Read-only dashboard

Display cohort blockers, coverage, reconstruction rate, LCBs, drawdown, and
outlier sensitivity. Do not merge this report into any execution input.

### P2: Scheduling

The report runner is committed but deliberately not registered as a scheduled
task because no real replication ledger exists. Register governance only after
a lawful source and OPRA reconstructor are operational, then update schedule
alignment tests.

## Worktree Warning

The repository contains many unrelated modified and untracked generated logs,
research files, tests, and prior handoffs. Commit `b6c5797` contains only the
eight files listed above. Do not reset, clean, stage, or overwrite unrelated
worktree changes.

## Paste-Ready Claude Prompt

```text
Open CODEx_CLAUDE_COLLAB/CODEX_TO_CLAUDE_PUBLIC_STRATEGY_REPLICATION_2026-08-08.md.
Independently audit commit b6c5797 against every P0 attack listed in the handoff.
Fix genuine integrity or evidence-inflation defects and add focused regression
tests. Then build the archive-bound lawful source-coverage adapter and the
read-only OPRA lifecycle reconstructor, using existing verified-trader and
Databento infrastructure where appropriate. Keep all outputs research/forward
shadow only. Do not scrape private sources, bypass access controls, submit an
order, lower any nomination gate, register a template as evidence, or claim
profitability. Preserve all unrelated dirty worktree files. Run focused tests,
the execution-gate audit, and the full suite, then commit only scoped files and
write a return handoff with exact evidence counts and remaining blockers.
```
