# Preregistration: Per-Checkpoint Completeness Replication (Green-Day HTF/LTF)

Date frozen: 2026-07-25 (before first replication run)
Parent experiment: `research/GREEN_DAY_HTF_LTF_PREREGISTRATION_2026-07-25.md`
Motivation: audit finding F1 — the full-session (09:30-13:44) IEX
completeness filter admits only 467/1,137 sessions and skews the sample
toward high-volatility days (+23% mean range, +51% median volume vs
excluded sessions).

## Frozen Specification

Everything from the parent preregistration is unchanged except session
eligibility:

- A session is eligible for a checkpoint if and only if every 1-minute bar
  from 09:30 ET through checkpoint+59m ET is present. No forward-filling.
- Checkpoints, the 9/9 VWAP/EMA recipe, HTF state definitions, variants,
  entry timing (checkpoint bar open), 60-minute horizon, 25 bps bracket,
  2 bps round-trip cost, and window partitions
  (2022-23 development / 2024 selection / 2025+ consumed diagnostic) are
  all identical and frozen.
- The 13:45 hard-exit metric is reported only for sessions that are also
  complete through 13:44; otherwise it is withheld as null, never imputed.
- No parameter, threshold, moving-average length, or checkpoint may change
  in response to replication output.

## Declared Purpose and Interpretation Rules

1. This is a robustness replication of an already-run experiment on a wider,
   still-honest sample. It cannot promote anything by itself.
2. If the 12:00 daily-aligned lead weakens or reverses on the wider sample,
   that counts as evidence against it; the forward shadow lane decision must
   be revisited before any lane is created.
3. If the lead strengthens, the only permitted action remains the already
   proposed frozen forward shadow lane (minimum 30 resolved independent
   dates). No new variants may be derived from this output.
4. All 2022-2025+ data remains consumed for tuning purposes.

## Multiplicity Accounting

This replication re-examines the same 3 checkpoints x 6 variants x 3 outcome
measures = 54 cells already counted for the parent experiment; it adds one
attempted analysis (completeness mode) to the family's trial count, not 54
new hypotheses.

## Execution

```powershell
uv run --no-project --with pandas --with numpy --with pyarrow `
  python research/green_day_htf_ltf_lab.py --completeness per_checkpoint
```

Output: `data/green_day_htf_ltf_results_per_checkpoint.json`
Promotion authority: human (Kenny) only.
