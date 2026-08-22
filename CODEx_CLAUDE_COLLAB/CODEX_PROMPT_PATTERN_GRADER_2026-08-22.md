# Codex — Fresh Session Prompt: Pattern Grader Phase 1

Copy-paste this entire message into a fresh Codex chat.

---

**Task:** Implement Phase 1 of the Pattern Grader for the Vibe-Trading dashboard. Detect chart patterns + market structure across all instruments and timeframes, grade every detected setup A/B/C/D, and publish grades to the dashboard read-only.

**Repo:** `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading`

**Read first (in order):**
1. `CODEx_CLAUDE_COLLAB/CLAUDE_HANDOFF_PATTERN_GRADER_2026-08-22.md` — full spec, deliverables, rubric, safety non-negotiables.
2. `research/pattern_detection_rules_classical.md` — geometric detection rules for classical / candlestick / volume / session families.
3. `research/pattern_detection_rules_smc_wyckoff.md` — detection rules for SMC/ICT, Wyckoff, order flow, options flow, regime composite.

**Phase 1 deliverables (§12 of handoff, steps 1–13):**

1. `research/pattern_taxonomy.json` — populate w/ top-15 setups from ranking tables in the rule packs.
2. Extend `agent/src/tools/pattern_tool.py` + new `agent/src/tools/market_structure.py` — swing detection (fractal w/ ATR filter), BOS, CHoCH, displacement candle, sweep.
3. `agent/src/tools/pattern_detectors/` — one file per family. Start w/ top-5: `orb.py`, `avwap.py`, `flag.py`, `volume_profile.py`, `inverse_hs.py`.
4. `agent/src/tools/regime_composite.py` — HMM state + Hurst + RV/IV + GEX composite.
5. `agent/src/tools/pattern_grade_scorer.py` — implements §5 rubric (6 weighted components + 4 multiplicative penalties → A/B/C/D grade).
6. `scripts/pattern_grader_scanner.py` — driver: per instrument×TF, run detectors → scorer → append to `data/pattern_grader_log.jsonl`.
7. `scripts/pattern_grader_report.py` — nightly aggregator → `~/.vibe-trading/reports/pattern-grader-grades.json`.
8. Wire dashboard panel — edit `scripts/generate_dashboard.py` REPORTS dict + add `render_pattern_grades_panel` (§7 of handoff).
9. Add shadow-only signal registry entry to `research/signal_registry.json` (§9 — `can_submit_orders: false`).
10. Test suite — 16 files under `agent/tests/test_pattern_*.py` (§10).
11. Run `python scripts/execution_gate_audit.py` — must pass.
12. Register scheduler tasks — `scripts/register_pattern_grader_tasks.ps1`.
13. Run scanner for 1h against live feed; verify dashboard renders panel + grade distribution not degenerate; halt for Kenny review.

**Non-negotiables:**
- No live execution in Phase 1. All new registry entries `can_submit_orders=false, execution_enabled=false`.
- Do NOT edit `agent/strategies/flip_bot.py` or `iwm_options_bot.py`.
- `execution_gate_audit.py` must pass after every registry change.
- All detectors deterministic; add `test_pattern_grader_replay_determinism.py`.
- Data freshness: reject bars with `now - bar_close_ts > 60s` in real-time mode; log freshness_violation.
- Windows scheduler jobs idempotent.
- Order-flow proxies (Phase 1) suffixed `_proxy` in pattern IDs.
- Dashboard must render even if `pattern-grader-grades.json` missing (guard w/ exists check).

**Success criteria (report back with):**
- All 16 test files pass (`pytest agent/tests/test_pattern_*.py -v`).
- `execution_gate_audit.py` passes.
- Dashboard renders `pattern_grades` panel w/ live data after 1h scanner run.
- Shadow log ≥ 20 rows across 3+ instruments and 2+ timeframes.
- Regime composite emits at least one full state transition.
- Grade distribution across 20+ signals is not all one grade (scorer discriminates).

**Cost guardrail:** Halt after step 13. Do NOT auto-initiate Phase 2 or Phase 3. Report progress in one Markdown update in `CODEx_CLAUDE_COLLAB/CODEX_STATUS_PATTERN_GRADER_YYYY-MM-DD.md` w/:
- What was built + files created (path list).
- Test results (pass/fail summary).
- Grade distribution histogram from first scanner run.
- Regime composite state trace excerpt.
- Any blockers or spec ambiguities.

Begin with step 1.
