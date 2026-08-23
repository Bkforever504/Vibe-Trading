# Codex — ICT Backtest Engine + Dashboard Scorecard

Copy-paste into fresh Codex chat.

---

**Task:** Build a rigorous ICT backtest engine, run the top-10 prioritized ICT concept backtests against historical MES/ES/SPY/EURUSD data, produce a dashboard scorecard, and update `pattern_taxonomy.json` `governance_status` based on measured evidence.

**Repo:** `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading`

**Context read first (in order):**
1. `research/ICT_MODEL_DEEP_DIVE_2026-08-23.md` — full concept catalog, evidence review, backtest priority ranking (§4), integration plan (§5)
2. `research/pattern_detection_rules_smc_wyckoff.md` — existing SMC/ICT detection rule catalog
3. `CODEx_CLAUDE_COLLAB/CODEX_HANDOFF_MASTER_2026-08-22.md` — non-negotiables, existing infrastructure

**Deliverables:**

### D1. `research/ict_backtest_specs.json`
Machine-readable backtest specifications for all 10 concepts from §4 of the deep-dive. Schema:

```json
{
  "schema_version": 1,
  "specs": [
    {
      "id": "kill_zone_ny_am_directional",
      "concept": "NY AM Kill Zone directional bias",
      "family": "kill_zone",
      "instruments": ["MES", "ES", "NQ", "MNQ"],
      "timeframes": ["5m", "15m"],
      "session_filter": {"window_et": ["09:30", "11:00"]},
      "entry_rule_pseudocode": "TODO",
      "exit_rule_pseudocode": "TODO",
      "stop_placement": "0.5 * ATR14",
      "target_placement": "1.5 * ATR14 T1, 3.0 * ATR14 T2",
      "sample_size_target": 500,
      "benchmarks": ["random_entry_same_window", "buy_hold", "vwap_mean_revert"],
      "falsification_threshold": {"wilson_lb_min": 0.53, "sharpe_min": 0.3, "max_dd_pct": 20},
      "historical_window": {"start": "2022-01-01", "end": "2026-05-01"},
      "oos_holdout": {"start": "2026-05-01", "end": "2026-08-01"},
      "cost_model": {"slippage_ticks": 1, "commission_per_side_usd": 0.35}
    }
    // ... 9 more specs
  ]
}
```

### D2. `scripts/ict_backtest_engine.py`
Parameterized driver. Signature:
```python
def run_backtest(spec_id: str, spec_json_path: Path, bars_source: str) -> dict:
    """Returns backtest report dict; writes ~/.vibe-trading/reports/ict-backtest-<spec_id>.json"""
```
- Reads spec from `ict_backtest_specs.json`
- Loads bars from `bars_source` (alpaca / databento / yfinance)
- Applies entry/stop/target rules per spec
- Splits IS / OOS per spec window
- Computes: n_trades, win_rate, wilson_lower_bound_95, avg_r, sharpe, sortino, max_dd, brier_skill, all 3 benchmarks
- Writes per-spec JSON report
- Deterministic: same spec + bars → identical output

### D3. `scripts/ict_backtest_aggregator.py`
Nightly rollup. Reads all `~/.vibe-trading/reports/ict-backtest-*.json`, emits `~/.vibe-trading/reports/ict-backtest-scorecard.json`:

```json
{
  "schema_version": 1,
  "generated_at": "2026-08-30T04:00:00Z",
  "results": [
    {
      "spec_id": "kill_zone_ny_am_directional",
      "concept": "NY AM Kill Zone directional bias",
      "family": "kill_zone",
      "n_trades": 542,
      "wilson_lb_95": 0.541,
      "avg_r": 1.42,
      "sharpe": 0.68,
      "brier_skill": 0.087,
      "max_dd_pct": 12.4,
      "oos_win_rate": 0.564,
      "verdict": "validated",
      "verdict_reasons": ["wilson_lb passes 0.53 threshold", "sharpe passes 0.3 threshold", "OOS >= 50% of IS performance"],
      "backtest_completed_at": "2026-08-29T22:14:00Z"
    }
    // ... more results
  ],
  "summary": {"total": 10, "validated": 3, "rejected": 5, "insufficient_data": 2}
}
```

### D4. `scripts/promote_ict_concepts.py`
Reads scorecard. For each result:
- `verdict == "validated"` → update `research/pattern_taxonomy.json` entry `governance_status: "validated_pattern"`, populate empirical `base_rate` field w/ OOS win rate
- `verdict == "rejected"` → update `governance_status: "rejected_pattern_hypothesis"`, log reason
- `verdict == "insufficient_data"` → keep as `unvalidated_pattern_hypothesis`
- Append audit row to `data/pattern_promotion_ledger.jsonl`
- Idempotent

### D5. Frontend: `frontend/src/components/detection/ICTScorecardTab.tsx`
New tab in Detection page. Shows:
- Table: one row per backtested concept (concept name, family, instrument, TF, n_trades, Wilson LB, avg R, Sharpe, Brier skill, verdict badge)
- Sort by Wilson LB descending
- Filter by family (dropdown)
- Filter by verdict (validated / rejected / insufficient)
- Drill-in: click row → detail panel w/ full backtest report + IS vs OOS comparison + benchmark table
- API contract in `frontend/src/lib/api.ts` — reads `~/.vibe-trading/reports/ict-backtest-scorecard.json`

### D6. Wire into Detection page
Add tab alongside existing DetectionTab. Update `frontend/src/pages/Detection.tsx`.

### D7. Scheduler
Register `VibeTradingICTBacktestAggregator` — daily 04:00 CT. Runs aggregator + `promote_ict_concepts.py`. Idempotent registration script: `scripts/register_ict_backtest_task.ps1`.

### D8. Tests (all must pass):
- `agent/tests/test_ict_backtest_engine.py` — synthetic bars fixture, verify win rate + Wilson LB + Sharpe calc correct, deterministic replay
- `agent/tests/test_ict_backtest_aggregator.py` — mock per-spec reports, verify rollup + verdict assignment
- `agent/tests/test_promote_ict_concepts.py` — idempotent taxonomy edits, correct audit ledger row
- `frontend/src/components/detection/ICTScorecardTab.test.tsx` — renders w/ mock scorecard data, filter + sort work
- `agent/tests/test_ict_specs_schema.py` — validate `ict_backtest_specs.json` against schema

### D9. Run the 10 backtests
Execute in this priority order (from §4 of deep dive):
1. Kill Zone NY AM directional
2. FVG fill probability within N bars
3. Judas Swing (session open false → reverse)
4. Turtle Soup (2-day breakout failure fade)
5. OB retest edge
6. OTE zone A/B/C comparison (50% vs 62-79% vs 79-88%)
7. PO3 daily model (EURUSD)
8. CISD sequence
9. Silver Bullet direction
10. SMT divergence ES vs NQ

**Data availability check first** — if instrument×TF×window combo has < 80% data coverage, mark spec `insufficient_data` and skip. Log gap for later refetch.

### D10. Status report
Write `CODEx_CLAUDE_COLLAB/CODEX_STATUS_ICT_BACKTEST_YYYY-MM-DD.md`:
- Files created + line counts
- Test delta
- Per-spec results table (n_trades, Wilson LB, verdict)
- Which concepts VALIDATED vs REJECTED vs INSUFFICIENT
- pattern_taxonomy.json changes made
- Any blockers (data gaps, schema issues)
- Recommendations for Phase 2 (add rejected concepts back? refine specs?)

---

## Non-Negotiables (Phase A/B/C/G all hold)

1. `execution_enabled=false`, `can_submit_orders=false` — NO auto-execution wired.
2. `execution_gate_audit.py` stays at 0 issues.
3. No bot bodies edited (flip_bot.py, iwm_options_bot.py untouched).
4. Signal registry contracts frozen — no schema changes to `can_submit_orders`, `execution_enabled`, `can_read_order_history`.
5. Deterministic replay — no random state, no wall-clock reads inside backtest logic.
6. Data freshness gate — reject stale bars.
7. Fail-closed on data source unavailable — mark `insufficient_data`, do NOT fabricate results.
8. All new registry entries `can_submit_orders=false`.
9. Backwards-compat — dashboard renders if `ict-backtest-scorecard.json` missing.
10. Validated concepts contribute to grader confluence stack ONLY — never standalone A-grade trigger.

## Success Criteria

- All 5 tests pass (D8)
- Agent suite delta ≤ +15 tests
- Frontend delta ≤ +5 tests
- Prod build green
- `execution_gate_audit.py`: 0 issues
- At least 8 of 10 backtests complete (2 can be `insufficient_data`)
- ICTScorecardTab renders w/ live data
- pattern_taxonomy.json diff shows appropriate `governance_status` flips
- $0 external cost (uses existing Alpaca IEX + Databento MES parquet)

## Halt Points

- After D2 (engine built + first spec run) — sanity check w/ Kenny that Wilson LB math + benchmark comparison look right BEFORE running remaining 9
- After all 10 backtests — halt for Kenny review BEFORE promotion pipeline flips `governance_status`
- Do NOT auto-promote to `validated_pattern` w/o Kenny sign-off on `research/ICT_BACKTEST_APPROVAL_YYYY-MM-DD.md`

## Estimated Effort

- Engine + aggregator + promoter: 8-12 hours
- Frontend tab: 3-4 hours
- Run 10 backtests: 4-8 hours depending on data load time
- Tests: 4-6 hours
- **Total: 20-30 hours Codex work**

Begin with D1 (spec JSON). Then D2. Report progress every 2-3 deliverables.
