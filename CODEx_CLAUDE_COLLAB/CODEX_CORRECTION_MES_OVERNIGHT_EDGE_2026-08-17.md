# Correction: MES Overnight Edge Handoff

The original `CLAUDE_HANDOFF_MES_OVERNIGHT_EDGE_2026-08-17.md` must not be
implemented as written.

## Material defects found

1. The proposed 15:55 ET entry uses the 16:00 MES close and same-day final VIX
   close. Those inputs do not exist at decision time.
2. Topstep forces all positions flat by 15:10 CT and permits new positions at
   17:00 CT. A close-to-next-open hold crosses that boundary and is prohibited.
3. `strategies/mes_overnight_shadow_logger.py` reads a static Databento file
   ending 2026-07-19. Its exit path uses the latest 16:00 close, not the 09:30
   open, so it cannot collect valid forward outcomes.

The legacy logger and its invalid log were deleted after this audit. Do not
restore either path.

## Corrected implementation

- Frozen spec: `research/MES_REOPEN_VIX_FILTER_PREREGISTRATION_2026-08-17.md`
- Reproducible lab: `research/mes_reopen_vix_holdout.py`
- Shadow logger: `strategies/mes_reopen_vix_shadow_logger.py`
- Scheduler tasks:
  - `MESReopenVixShadowEntry`, Monday-Thursday at 17:06 CT
  - `MESReopenVixShadowExit`, Tuesday-Friday at 08:36 CT
- Log: `data/mes_reopen_vix_shadow_log.jsonl`

The corrected causal version retains positive retrospective evidence, but that
transfer was evaluated after the original hypothesis and is not a pristine
holdout. It remains shadow-only until 30 new outcomes and all preregistered
promotion gates pass. Do not restore the old task names or the 15:55 ET entry.

## Bootstrap qualification

- Train 90% CI: $2.09 to $22.91; 95% CI: $0.05 to $24.85.
- Independent test 90% CI: -$2.05 to $26.11; 95% CI: -$5.00 to $29.02.
- Full sample 90% CI: $3.68 to $20.66; 95% CI: $1.80 to $22.38.

Because the independent test lower bounds cross zero, describe the result as
supportive shadow evidence, not a statistically confirmed edge.
