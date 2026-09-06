# CLAUDE HANDOFF — Family Mapping Fix (Sub-Signal Split + Taxonomy)

**Date:** 2026-09-06
**Author:** Claude (Opus 4.7)
**Executor:** Codex
**Prior:**
- WS-CV + WS-BOOTSTRAP landed shadow-only (needs_review outcome on flip_bot, iwm_options_bot)
- `CLAUDE_HANDOFF_REPO_HYGIENE_2026-09-06.md` MUST land first

**Scope:** Correct the mechanical bot-level family assignment (`flip_bot` → momentum, `iwm_options_bot` → momentum). Split each multi-strategy bot into sub-signals with correct family_key. Migrate trial_ledger, re-run WS-CV re-evaluation, produce a report suitable for human review before Tier 2 unpauses.

**Sequence position:** MUST complete before any Tier 2 workstream (WS-PREFECT, WS-TASTY, WS-GEX, WS-META, WS-QUIVER) starts. Reason: Tier 2 signals gate through WS-CV, and WS-CV validity depends on correct family_key assignments.

---

## Session Summary

Codex's review of WS-CV re-evaluation surfaced a real integrity problem: `iwm_options_bot` was mechanically assigned family_key `momentum` despite being a multi-strategy vol/premium system. `flip_bot` also contains multiple entry strategies. Bot-level family assignment is too coarse; it inflates some family trial counts, under-counts others, and produces a Deflated Sharpe that lies in both directions. This handoff decomposes each bot into logical sub-signals with correct family_key, migrates the trial ledger honestly, and re-runs the statistical gate.

---

## Non-Negotiable Invariants

- Sub-signal split is ADDITIVE. Existing bot-level signal_ids remain in registry for backward-compatibility; new sub-signal ids are added alongside.
- Every sub-signal registration counts as a new hypothesis in `trial_ledger` (honest — this IS a new trial family). Do NOT retroactively reassign historical trial rows to new families.
- Historical outcomes remain attached to the bot-level signal_id. New outcomes flow to sub-signal id starting on split date.
- Sub-signal outcomes accumulate independently; no synthetic backfill from bot-level to sub-signal.
- Statistical gate returns `not_ready` for every new sub-signal until n≥min_outcomes accumulates. This is CORRECT and expected.
- Family taxonomy stored in `config/signal_families.json` with schema version; changes require human review.
- No execution wiring changes; shadow-only.
- No modification to any of the 11 pre-existing test failures.

---

## Family Taxonomy (Codex to review before implementing)

Store in `config/signal_families.json`:

```json
{
  "schema_version": "2",
  "reviewed_by_human": false,
  "reviewed_at": null,
  "families": {
    "momentum": {
      "description": "Trend-following entries (ORB, breakout, MA cross, HMM trend regime)",
      "example_signals": ["orb_long", "vwap_breakout", "ma_cross"]
    },
    "mean_reversion": {
      "description": "Fade entries against extended moves (VWAP fade, RSI2, BB reversion)",
      "example_signals": ["vwap_fade", "rsi2_reversion"]
    },
    "volatility_premium": {
      "description": "Short-vol structures: credit spreads, iron condors, cash-secured puts",
      "example_signals": ["iwm_credit_spread", "iwm_iron_condor"]
    },
    "volatility_expansion": {
      "description": "Long-vol / long-premium: straddles, strangles, directional long calls or puts around expected move breaches",
      "example_signals": ["iwm_directional_long_premium"]
    },
    "catalyst_reactive": {
      "description": "Signals triggered by external events already occurred (EDGAR 8-K, earnings beat, insider Form 4 cluster)",
      "example_signals": ["edgar_8k_watchlist", "edgar_form4_cluster"]
    },
    "catalyst_scheduled": {
      "description": "Signals gating around known future events (FOMC blackout, earnings blackout, ex-div)",
      "example_signals": ["fomc_blackout_pass", "earnings_blackout_pass"]
    },
    "orderflow_microstructure": {
      "description": "Signals derived from bid/ask book, NBBO, OFI/VPIN, dark-pool prints",
      "example_signals": ["nbbo_confluence_veto", "ofi_directional_bias"]
    },
    "positioning_dealer": {
      "description": "Dealer positioning inference: GEX, max pain, 0DTE pin/gamma regime",
      "example_signals": ["dealer_gex_regime", "zero_dte_pin_risk"]
    },
    "alt_data_smart_money": {
      "description": "Non-price alt data implying informed positioning: Congress trades, 13F changes, insider buy clusters",
      "example_signals": ["quiver_congress", "quiver_darkpool_short_vol"]
    },
    "sentiment_retail": {
      "description": "Retail sentiment velocity: WSB, StockTwits, X/Twitter volume-weighted",
      "example_signals": ["quiver_wsb_velocity"]
    },
    "regime_macro": {
      "description": "Cross-asset regime state: HMM regime, PCA breadth, RV/IV, VIX term structure, market force",
      "example_signals": ["hmm_regime_gate", "market_force_score"]
    },
    "nlp_catalyst": {
      "description": "NLP-derived catalyst confidence: FinBERT filing sentiment, earnings transcript scoring",
      "example_signals": ["edgar_sentiment_weighted", "earnings_transcript_sentiment"]
    }
  }
}
```

Human must review this taxonomy before Codex uses it. Family definitions determine whose trial count feeds Deflated Sharpe; miscategorization = same bug as before.

---

## Sub-Signal Split Plan

Codex must inspect each bot's source and identify each distinct entry logic. Recommendation for known bots (Codex to verify against actual code before splitting):

### `flip_bot` → candidate sub-signals

Grep `agent/flip_bot.py` (or equivalent) for entry branches. Each branch = candidate sub-signal.

Likely decomposition (verify against source):
- `flip_momentum_orb` — Opening Range Breakout entries. family=`momentum`.
- `flip_momentum_vwap_breakout` — VWAP break-and-hold. family=`momentum`.
- `flip_mean_reversion_vwap_fade` — VWAP fade at extended distance. family=`mean_reversion`.
- `flip_squeeze_expansion` — TTM squeeze release entries. family=`volatility_expansion`.
- `flip_regime_gated_trend` — trend entries gated on HMM/PCA regime. family=`regime_macro`.

### `iwm_options_bot` → candidate sub-signals

- `iwm_credit_spread_premium` — bull put / bear call credit spread entries. family=`volatility_premium`.
- `iwm_iron_condor_premium` — iron condor entries. family=`volatility_premium`.
- `iwm_directional_long_premium` — directional long option entries (if the bot does this). family=`volatility_expansion`.
- `iwm_delta_hedged_scalp` — if applicable. family=`orderflow_microstructure`.

Codex: if the actual code has fewer or more branches than above, follow the code, not the recommendation. Document decisions in the split report.

---

## Files to Create

- `agent/governance/family_taxonomy.py`
  - Loads `config/signal_families.json`.
  - `def family_of(signal_id) -> str | None` — reads from registry entry.
  - `def validate_family(family_key) -> bool` — asserts key exists in taxonomy.
  - `def taxonomy_version() -> str` — hash of taxonomy file, persisted with every gate decision.
- `scripts/governance/split_bot_into_subsignals.py`
  - Interactive-safe CLI (accepts `--bot`, `--dry-run`):
    - Reads bot source; enumerates entry branches; produces a proposed split plan.
    - Writes `data/governance/proposed_split_<bot>_<date>.md` for human review.
    - With `--apply` flag (after review): registers each sub-signal in `signal_registry.json` with family_key, min_outcomes=30, min_deflated_sharpe=0.0, max_pbo=0.5, min_psr=0.95, requires_human_review=true, promoted=false.
    - With `--apply`: writes one row per new sub-signal to `trial_ledger.jsonl` with `{signal_id, hypothesis_hash=SHA of split_plan_row, timestamp, source="family_mapping_fix_2026-09-06"}`.
- `scripts/governance/emit_subsignal_outcomes.py`
  - Runs alongside existing bot; when bot emits an entry, records outcome against sub-signal_id in addition to bot-level signal_id.
  - Sub-signal outcomes stored in `data/outcomes/subsignal/<signal_id>.jsonl`.
- `scripts/governance/rerun_reevaluation.py`
  - Runs `StatisticalGate.evaluate` over EVERY signal (bot-level + sub-signal).
  - Produces `data/governance/reevaluation_report_<date>_v2.md` showing per-signal DSR/PSR/PBO with correct family trial counts.
- `agent/tests/test_family_taxonomy.py`
- `agent/tests/test_subsignal_split.py`
- `agent/tests/test_subsignal_outcome_emission.py`
- `docs/FAMILY_MAPPING.md`
- `docs/SUBSIGNAL_SPLIT_PROCESS.md`

---

## Files to Modify

- `agent/signal_registry.json` — add sub-signal entries per split; do NOT modify or delete existing bot-level entries.
- `config/signal_families.json` — canonical taxonomy (see above).
- `agent/governance/statistical_gate.py`
  - Every gate decision now includes `family_key` and `taxonomy_version` in persisted `gate_history` row.
  - Trial count sourced via `trial_ledger.count_trials(family_key)` using the NEW taxonomy.
- Each affected bot (`flip_bot`, `iwm_options_bot`, others):
  - Add hook that emits per-entry outcome to sub-signal id (via `emit_subsignal_outcomes.py`).
  - Bot logic UNCHANGED; only observability added.
- `scripts/generate_dashboard.py`
  - Governance panel now shows bot-level signal AND its sub-signals nested underneath.
  - Family filter dropdown.
  - Column: `family_key`, `n_outcomes (sub)`, `DSR (sub)`, `PSR (sub)`, `PBO (sub)`, `status`.

---

## Execution Sequence for Codex

### Step 0 — precondition check

```powershell
git status --porcelain=v1
# → empty (repo hygiene handoff must have landed)
```

If not empty → STOP, return to `CLAUDE_HANDOFF_REPO_HYGIENE_2026-09-06.md`.

### Step 1 — commit taxonomy for human review

```powershell
git checkout -b governance/family-taxonomy-v2
# create config/signal_families.json (schema_version=2, reviewed_by_human=false)
# commit with [GOVERNANCE] prefix
```

Open PR. Human reviews taxonomy. On approval, human sets `reviewed_by_human=true` and `reviewed_at=<timestamp>` and merges.

**Codex must NOT proceed to Step 2 until this PR is merged with human review flag set.**

### Step 2 — split plans (read-only)

For each bot:

```powershell
python scripts/governance/split_bot_into_subsignals.py --bot flip_bot --dry-run
# → data/governance/proposed_split_flip_bot_<date>.md

python scripts/governance/split_bot_into_subsignals.py --bot iwm_options_bot --dry-run
# → data/governance/proposed_split_iwm_options_bot_<date>.md
```

Reports include: enumerated entry branches from source, proposed sub-signal_id, proposed family_key, proposed hypothesis_hash.

Human reviews each split plan. Approval required per bot.

### Step 3 — apply approved splits

Only after human approval per bot:

```powershell
python scripts/governance/split_bot_into_subsignals.py --bot flip_bot --apply
# → registry updated, trial_ledger rows written

python scripts/governance/split_bot_into_subsignals.py --bot iwm_options_bot --apply
# → registry updated, trial_ledger rows written
```

Commit on branch `governance/subsignal-splits-<date>`.

### Step 4 — wire outcome emission

Modify each bot to emit sub-signal outcomes alongside bot-level outcomes. Bot LOGIC unchanged; only observability added. Every existing test must still pass.

### Step 5 — re-run gate over EVERYTHING

```powershell
python scripts/governance/rerun_reevaluation.py
# → data/governance/reevaluation_report_<date>_v2.md
```

Expected output per sub-signal: `status=not_ready, n_outcomes=0, reason="awaiting_first_outcome"`. This is correct.

Bot-level signals may show new DSR values because the trial-count denominator changed after taxonomy correction. Neither promoted nor demoted; every change enters `needs_review` per invariant.

### Step 6 — dashboard update

```powershell
python scripts/generate_dashboard.py
# → governance panel shows nested sub-signals; family filter works
```

### Step 7 — full verification

```powershell
python -m pytest agent/tests/test_family_taxonomy.py agent/tests/test_subsignal_split.py agent/tests/test_subsignal_outcome_emission.py -q
# → all pass

python -m pytest agent/tests/ -q
# → 5725 + new tests pass, 4 skipped, 11 pre-existing failures unchanged

python scripts/signal_stack_health_report.py --no-write
# → OK count unchanged or higher

python scripts/execution_gate_audit.py --print
# → passed=True issues=0

git status --porcelain=v1
# → empty on branch
git diff --check
# → clean
```

### Step 8 — open PR

Single PR per bot split OR one combined PR if scope is manageable. PR description includes:
- Link to split plan reports
- Link to reevaluation_report_v2
- Test counts
- Confirmation that human review flag on taxonomy is `true`
- Statement that all new sub-signals are `not_ready` (expected)

---

## Verification Checklist

```powershell
python -m pytest agent/tests/test_family_taxonomy.py -q
python -m pytest agent/tests/test_subsignal_split.py -q
python -m pytest agent/tests/test_subsignal_outcome_emission.py -q
python -m pytest agent/tests/ -q
python scripts/signal_stack_health_report.py --no-write
python scripts/execution_gate_audit.py --print
python scripts/generate_dashboard.py
```

All must return their success signature per invariants above.

---

## Success Gate

- `config/signal_families.json` has `reviewed_by_human=true`.
- Every bot has an approved split plan on file.
- Every sub-signal registered with correct family_key.
- Trial ledger has one honest new-trial row per sub-signal registration.
- Re-evaluation v2 report exists and shows every sub-signal `not_ready` awaiting outcomes.
- Bot-level signals may show updated DSR; none auto-promoted or auto-demoted.
- All prior tests + new tests pass.
- Dashboard governance panel renders nested view without error.

---

## Open Positions / Active Risks

- No live positions.
- Bot-level signals remain in force under `needs_review` from prior WS-CV run; new sub-signal work is additive and does not remove existing state.
- Tier 2 workstreams (WS-PREFECT, WS-TASTY, WS-GEX, WS-META, WS-QUIVER) remain PAUSED until this handoff lands AND the re-evaluation v2 report is human-reviewed.

---

## Next Session Priority After This Ships

1. Human reviews `reevaluation_report_v2` and decides on any bot-level signal that shifted materially.
2. WS-PREFECT unpauses (Tier 2 #1).
3. Then WS-TASTY, WS-GEX, WS-META, WS-QUIVER in prior handoff order.
4. Tier 4a (WS-TCA, WS-HYPOTHESIS, WS-GREEKS) may start in parallel with Tier 2 if bandwidth allows; they do not depend on family mapping being correct (though they benefit from it).

---

## Known Caveats / Deferred

- **Sub-signal outcome accumulation takes time.** Every new sub-signal starts at n=0. Expect 10-30 trading days before any sub-signal accumulates enough outcomes for the gate to return anything but `not_ready`. This is correct behavior, not a bug.
- **Trial-count backfill limit** (from parent WS-CV handoff): historical trials per family under-counted for periods before trial_ledger existed. Documented in ledger header; do not silently pretend counts are complete.
- **Family key changes are one-way audit trail.** Once a signal is registered with a family_key, changing it later requires a new trial_ledger row (new hypothesis).
- **Bot-level signals stay in registry** for backward-compat. They may eventually be retired after sub-signals mature, but not in this handoff.
- **11 pre-existing test failures** remain untouched; separate ticket.
- **Pattern Grader ERROR** in health report remains untouched; separate ticket.

---

## Handoff Complete

Codex: repo hygiene must land first, then taxonomy PR with human review, then per-bot split plans with human approval per bot, then apply, then re-run, then dashboard, then PR. Sub-signals start at zero outcomes; that is correct. Tier 2 remains paused until re-evaluation v2 is human-reviewed.
