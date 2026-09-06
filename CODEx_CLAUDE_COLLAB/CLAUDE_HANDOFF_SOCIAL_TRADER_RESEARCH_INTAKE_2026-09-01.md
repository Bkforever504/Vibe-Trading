# CLAUDE → CODEX HANDOFF: Social Trader Research Intake + Shadow Backlog

**Date:** 2026-09-01
**From:** Claude Code (Opus 4.7)
**To:** Codex (next session)
**Topic:** Finish Codex's social-research collector schema, harvest external trader methodology across 4 edge types, wire 10 new shadow-scanner backlog entries into scanner + dashboard, publish gap-match to feed A+ setup pipeline
**Reference:** `research/social_trader_signal_gap_match_2026-09-01.json`

---

## 1. What Claude shipped this session

### 1.1 Codex's social-research collector — schema tightening completed

Codex had tightened `scripts/agent_reach_trading_research.py` to enforce that a social callout enters the replay queue **only when the source explicitly supplies one symbol, direction, entry zone, stop, target, timeframe, and publication time**. The rule enforcement in `extract_trade_callout()` (line 372–419) was already correct: it computes `required` from all 7 fields and sets `eligible_for_shadow_replay = not missing`.

**What was still missing:** the actual write to a downstream replay queue. `build_report()` was only emitting a list of source_ids under `replay_ready_callouts`; downstream consumers (shadow-replay executor, dashboard) had no structured records to consume.

**What I added:**

| File | Change | Key lines |
|------|--------|-----------|
| `scripts/agent_reach_trading_research.py` | Added `DEFAULT_REPLAY_QUEUE = ROOT / "data" / "social_replay_queue.jsonl"` constant | 27 (const) |
| `scripts/agent_reach_trading_research.py` | New `_append_replay_queue(path, normalized_rows)` function — filters `eligible_for_shadow_replay=True`, writes structured record (source_id + queued_at + source_timestamp + platform + author + url + title + symbol + direction + entry_zone_low + entry_zone_high + stop + targets + timeframe + strategy_tags + evidence_tier + independent_verification + status + execution_enabled=false + can_submit_orders=false + authority). Deduped by (source_id, source_timestamp). | 121–176 |
| `scripts/agent_reach_trading_research.py` | Extended `main()` — new `--replay-queue` CLI arg, calls `_append_replay_queue` after `_append_jsonl`, adds `new_replay_queue_count`, `cumulative_replay_queue_count`, `replay_queue_path` to report | 671–685 |
| `agent/tests/test_agent_reach_trading_research.py` | Added `test_replay_queue_only_accepts_eligible_callouts` — verifies eligible callout appended with all 7 fields, ineligible skipped | 259–297 |
| `agent/tests/test_agent_reach_trading_research.py` | Added `test_replay_queue_is_idempotent` — verifies repeated call adds 0 rows | 300–316 |
| `research/agent_reach_trading_sources.json` | Expanded `youtube_queries` from 4 → 7 and `x_queries` from 3 → 6 to cover 4 edge types: 0DTE, opening range, catalyst (FOMC/CPI), gamma/GEX | full config |

**Test suite:** 15/15 passed (13 existing + 2 new). Run: `python -m pytest agent/tests/test_agent_reach_trading_research.py -q`.

**Live run:** `python scripts/agent_reach_trading_research.py --no-transcripts --print` — pipeline succeeded, 27 sources collected, 3 rejected as marketing, 24 research_lead. Replay queue file created at `data/social_replay_queue.jsonl` (empty because current pre-configured social snapshots are intentional rejection examples).

### 1.2 Multi-source trader research — 4 edge types × external methodology extraction

**Sources used (this session):**
- Agent-Reach CLI (already installed at `~/.agent-reach-venv/` with `agent-reach.exe`, `twitter.exe`, `yt-dlp.exe`) — the collector routes to these directly
- Exa web_search (4 queries covering 0DTE, ORB, GEX, catalyst)
- LunarCrush MCP — **subscription paywalled**; deferred. Add to Codex backlog if a subscription is procured.

**19 concrete external methodologies extracted** to strict JSON schema at `research/social_trader_signal_gap_match_2026-09-01.json`. Each row includes: id, edge_type, source URL, author, verification tier (`verified_live_alert_record`, `backtested_100plus_sessions`, `educational_only`, etc.), rule_summary, target_symbol, timeframe, registry_match, match_status (`already_have | partial | missing`), gap.

**Signal cluster summary:**
- **0DTE (6 signals):** TradeAlgo iron condor, Kane Shieh 3pm GEX-pin butterfly (79.4% WR verified live 54-14), Days to Expiry reversal scalping (3 setups), Brendan Kafka opening-candle direction, Mitchell Herrmann Kalman-momentum autonomous bot, FlashAlpha 0DTE VRP study (193 sessions, 71% band-contain vs 68.3% fair)
- **ORB (7 signals):** Options.cafe 5-min 0DTE ORB (303-trade Massive/Polygon backtest 55.2% return 7.6% MDD), Concretum ORB w/ filters (12.1% CAGR vs 1.0% vanilla), Vortex per-symbol asymmetry (NVDA 72.7% vs SPY 54.5% vs IWM 40% follow-through), Vortex short-side inversion (short 46.7% vs long 30.6% in 2025-26 regime), TradeAlgo 15-min ORB, Ross Cameron 1-min gapper ORB, TradeOlogy retest entry (60%+ WR)
- **Gamma/GEX (4 signals):** FlashAlpha 3-level SPY GEX playbook (call wall, put wall, flip), SpotGamma 5-min routine + 3-setup playbook, GEXBoard 30s live flip refresh, FlashAlpha settled-vs-flow-GEX (use flow-GEX after 11am — walls drift $2-5 by midday)
- **Catalyst (3 signals):** Trader Central FOMC IV crush timing (enter post-2:30pm, not at 2pm), Oyamori catalyst-tier + IVR + expected-move composite, Pure Power Picks 3-phase FOMC framework

### 1.3 Gap-match against `research/signal_registry.json`

**Totals from `research/social_trader_signal_gap_match_2026-09-01.json`:**
- Extracted: 19
- Already have (verify only): 2 — `zero_dte_expected_move_context`, `flip_15m_orb_retest_shadow_challenger`
- Partial (existing scanner covers part of it): 13
- Missing (no equivalent scanner): 4

**10 new `research_backlog` stubs appended** to `research/signal_registry.json` (grew 113 → 123 signals). All have `execution_enabled=false`, `can_submit_orders=false`, `status="research_backlog"`, `script="NOT_YET_IMPLEMENTED"`, and point back to the gap-match report via `provenance`. New IDs:

| Priority | ID | Provenance edge type |
|----------|-----|----------------------|
| **P1** | `spy_0dte_iron_condor_shadow_challenger` | 0DTE (TradeAlgo + Days to Expiry) |
| **P1** | `spy_3pm_gex_pin_butterfly_shadow` | 0DTE gamma (Kane Shieh, verified 79.4% WR) |
| **P1** | `spy_post_catalyst_iv_crush_shadow` | Catalyst (Trader Central + Days to Expiry + Pure Power) |
| **P1** | `spy_gex_flow_adjusted_shadow` | Gamma flow (FlashAlpha, GEXBoard) |
| **P1** | `catalyst_tier_ivr_em_composite_gate_shadow` | Catalyst (Oyamori + Trader Central) |
| **P2** | `spy_5min_0dte_orb_shadow` | ORB (Options.cafe 303-trade backtest) |
| **P2** | `orb_symbol_asymmetry_shadow` | ORB (Vortex Capital per-symbol study) |
| **P2** | `orb_short_regime_flag_shadow` | ORB regime (Vortex 20-day inversion) |
| **P2** | `zero_gamma_flip_crossing_shadow` | Gamma (SpotGamma + FlashAlpha + GEXBoard) |
| **P3** | `premarket_gapper_universe_scanner_shadow` | ORB gapper (Ross Cameron methodology) |

### 1.4 Dashboard wiring

New section **`#social` "Social Replay Queue"** added to `scripts/generate_dashboard.py`:

- New constants `SOCIAL_REPLAY_QUEUE` (repo `data/`) and `SOCIAL_GAP_MATCH_REPORT` (repo `research/`)
- New REPORTS entry `agent_reach_research`
- `load_model()` now loads: `agent_reach_research`, `social_replay_queue` (JSONL rows), `social_gap_match`
- New `render_social_replay_queue()` renderer emits 6 stat cards + channel-status line + platform/classification counts + queue-row table (last 25, newest first) + explicit no-execution-authority disclaimer + link to gap-match report
- Nav link `("#social", "Social Replay")` added between Watchlist and Alpha

Dashboard regenerated cleanly. Verified new `<div id="social" class="section">` at output line 1359, nav link at 374. No render errors. Run: `python scripts/generate_dashboard.py`.

---

## 2. What Codex should do next (in priority order)

### 2.1 Verify the completed collector work

```bash
python -m pytest agent/tests/test_agent_reach_trading_research.py -q
python scripts/agent_reach_trading_research.py --no-transcripts --print | tail -30
python scripts/generate_dashboard.py
```

Expected: 15/15 tests pass, live run appends 0 replay-queue rows (current config has no real callouts), dashboard writes successfully.

### 2.2 Implement the P1 shadow scanners (5 new scripts)

Each `research_backlog` entry in `research/signal_registry.json` includes exact rule_summary and external_baseline_sources. All 5 must land as SHADOW-ONLY (`execution_enabled=false`, `can_submit_orders=false`). Do NOT connect to `strategies/iwm_options_bot.py` or `strategies/flip_bot.py`. Suggested script paths:

| Signal ID | Suggested script | Data dependencies |
|-----------|------------------|-------------------|
| `spy_3pm_gex_pin_butterfly_shadow` | `scripts/spy_3pm_gex_pin_butterfly_shadow.py` | Existing `gex_scanner` output, SPY 0DTE chain, close price |
| `spy_gex_flow_adjusted_shadow` | `scripts/spy_gex_flow_adjusted_shadow.py` | SPY minute quotes with side-classification, options chain snapshot |
| `spy_post_catalyst_iv_crush_shadow` | `scripts/spy_post_catalyst_iv_crush_shadow.py` | Existing `market_catalyst_calendar` output, SPY IV term structure, expected-move |
| `catalyst_tier_ivr_em_composite_gate_shadow` | `scripts/catalyst_tier_ivr_em_composite_gate_shadow.py` | Reuses catalyst calendar + ivr_scanner + zero_dte_expected_move_context |
| `spy_0dte_iron_condor_shadow_challenger` | `scripts/spy_0dte_iron_condor_shadow_challenger.py` | SPY options chain @ 9:35 ET, VIX, delta calculator |

Each script must:
1. Log to `data/{signal_id}_log.jsonl` per session (one row per would-be trade + one row per no-trade with rejection reason).
2. Emit `~/.vibe-trading/reports/{signal_id}.json` for dashboard consumption.
3. Register a scheduled task (Windows Task Scheduler) with health-check wrapper matching the pattern in `scripts/run_intraday_opportunity_radar.ps1` (pre/post row-count assertion, timestamped START/STEP/END/ERROR log lines).
4. NEVER call broker APIs. Compute hypothetical fills against `data/spy_move_ledger.jsonl` for evidence.

### 2.3 Wire scanner outputs into A+ pipeline (do NOT auto-promote)

After 30 shadow sessions accumulate, cross-reference each shadow signal against `spy_move_ledger` and `spy_recall_report`. Signals whose captured moves exceed a random-strike baseline become candidates for the ranking-regret / calibration bucket pipeline (workstream from `CLAUDE_HANDOFF_APLUS_EDGE_UPGRADE_2026-08-30.md`). No signal is promoted to A+ executable without: (a) 30 sessions of shadow evidence, (b) qualified calibration bucket, (c) fresh OPRA contract feasibility, (d) no active regime-abstention flag, (e) dual Codex/Claude review.

### 2.4 Reject list (do NOT do these)

- Do NOT re-enable X intake in any promotion gate — `x_intake_scanner.py` still uses dead Nitter scraping and returns `AuthenticationRequired`. Full rewrite against X API v2 with existing `X_BEARER_TOKEN` (in `agent/.env` line 136) is still open.
- Do NOT connect the LunarCrush MCP without a paid subscription — attempted this session, returned `Error: Subscription required to unlock all social data and MCP tools`.
- Do NOT insert extracted-signal rules as executable code paths — they are external methodology intake, not proven edges.
- Do NOT reduce the strictness of `extract_trade_callout()` required fields. The 7-field lock is deliberate to prevent low-quality intake from polluting the replay queue.

---

## 3. Hard constraints (still in force)

Inherited from `CLAUDE_HANDOFF_APLUS_EDGE_UPGRADE_2026-08-30.md`:

1. `execution_enabled: false` and `can_submit_orders: false` on every new signal.
2. Missing paid feeds show as `unavailable`, never guessed.
3. New code lands shadow-only until calibration buckets fill.
4. No revive of pairwise lead-lag (explicitly killed).
5. Contract feasibility sidecar is a hard prerequisite for A+ executable label.
6. All signal promotions require dual review.

New constraint added this session:

7. **Every external-methodology-derived signal must show its `provenance` field** pointing to `research/social_trader_signal_gap_match_2026-09-01.json` (or a newer gap-match doc). Signals without provenance to a specific source URL + author + verification tier are inadmissible.

---

## 4. End-of-session verification checklist for Codex to re-run

```bash
# 1. Test suite (collector schema + replay queue)
python -m pytest agent/tests/test_agent_reach_trading_research.py -q

# 2. Live collector run (populates replay queue if any eligible callouts)
python scripts/agent_reach_trading_research.py --no-transcripts --print | tail -20

# 3. Signal registry sanity
python -c "import json; r=json.load(open('research/signal_registry.json',encoding='utf-8-sig')); print(f'signals={len(r[\"signals\"])}'); backlog=[s for s in r['signals'] if s.get('status')=='research_backlog']; print(f'research_backlog stubs={len(backlog)}'); [print(f'  {s[\"id\"]} ({s.get(\"priority\",\"?\")})') for s in backlog]"

# 4. Dashboard renders with new #social section
python scripts/generate_dashboard.py
grep -c "Social Replay Queue" ~/.vibe-trading/dashboard.html   # expect >= 1

# 5. Radar coverage (from previous session, still in force)
python scripts/radar_coverage_health.py

# 6. SPY recall report (measurement baseline)
python scripts/spy_recall_report.py  # or existing regenerate script
```

Expected: 15/15 tests pass · report writes without error · signals=123 with 10 research_backlog stubs · dashboard contains "Social Replay Queue" · radar health status=ok · recall report regenerated.

---

## 5. Files changed this session

| File | Type | Change |
|------|------|--------|
| `scripts/agent_reach_trading_research.py` | code | +58 lines: DEFAULT_REPLAY_QUEUE const, `_append_replay_queue()` function, main() CLI/report additions |
| `agent/tests/test_agent_reach_trading_research.py` | code | +56 lines: 2 new tests |
| `research/agent_reach_trading_sources.json` | config | Expanded YT + X queries to cover 4 edge types |
| `research/social_trader_signal_gap_match_2026-09-01.json` | NEW report | 19 extracted signals + 10 backlog entries + summary |
| `research/signal_registry.json` | data | +10 research_backlog stubs (113 → 123 signals) |
| `scripts/generate_dashboard.py` | code | +80 lines: constants, REPORTS entry, load_model 3 new keys, render_social_replay_queue(), nav link, HTML section |
| `CODEx_CLAUDE_COLLAB/CLAUDE_HANDOFF_SOCIAL_TRADER_RESEARCH_INTAKE_2026-09-01.md` | NEW handoff | This document |

No files deleted. No existing signals mutated. No execution paths touched.
