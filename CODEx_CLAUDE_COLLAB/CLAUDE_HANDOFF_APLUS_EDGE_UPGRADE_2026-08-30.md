# CLAUDE → CODEX HANDOFF: A+ Edge Upgrade (Multi-Part)

**Date:** 2026-08-30
**From:** Claude Code (Opus 4.7)
**To:** Codex (mid-session, already executing this workstream)
**Topic:** Finish the multi-part A+ edge upgrade Codex began in the current session
**Reference research:**
- `research/APLUS_UNEXPLORED_EDGE_GAP_ANALYSIS_2026-08-30.md`
- `research/last30days_aplus_gap_plan.json`

---

## 1. Session summary

Codex began the multi-part A+ edge upgrade in the current session. It mapped existing
interfaces and the dirty worktree, started sub-workstreams `Ranking regret`,
`Contract feasibility`, and `Market context challengers`, and confirmed the core
integration bug: the Spotlight currently emits a "trade alert" for score ≥ 93 grade-A
candidates even when calibrated probability and an exact option contract are
unavailable. Codex decided to permanently split the label into two grades:
- **A+ candidate** — visible on dashboard, based on heuristic score only.
- **A+ executable shadow-ready** — requires qualified calibration bucket, fresh OPRA
  contract evidence, and no active regime-abstention flag.

Missing paid feeds must be shown as `unavailable`, never guessed.

The prior Claude Code session (the one writing this handoff) landed operational and
scheduler hardening to make radar and Pattern Grader coverage measurable and
diagnose-able. Full inventory below.

---

## 2. Files changed in the Claude session that precedes this handoff

| File | Change | Key lines |
|------|--------|-----------|
| `scripts/run_intraday_opportunity_radar.ps1` | Full rewrite. Adds timestamped `START/STEP/END/ERROR` lines; pre/post row-count assertion on `data/intraday_opportunity_radar_log.jsonl`; writes `~/.vibe-trading/health/radar_wrapper.json` with `status ∈ {ok, silent_failure, error}` + `row_delta`. Fail-open preserved: throws only on Python non-zero exit; a zero-row-appended success is logged + health-marked but still exits 0 | entire file |
| `scripts/radar_coverage_health.py` | NEW. Counts today's radar-log rows and writes `~/.vibe-trading/health/radar_coverage.json` with `status ∈ {ok, warn, fail}`. **User-edited after Claude wrote it:** now imports `is_expected_market_session` from `signal_stack_health_report`, requires `EXPECTED_ROWS = 78` and `DEFAULT_MIN_ROWS = 70` (was 20), and swaps weekend-only skip for full market-session awareness | 19–34, 53–68 |

## 3. Task Scheduler changes

| Task | Before | After |
|------|--------|-------|
| `IntradayOpportunityRadar` (root path) | 48 individual `Weekly` triggers 08:35–15:00 CT; Aug 28 wrote only 8 rows and the wrapper had no way to detect it | Single `Weekly Mon–Fri` trigger, `Start=08:30 CT`, `RepEvery=5min`, `RepFor=6h30m` → **78 fires per RTH day** covering 09:30–16:00 ET |
| `PatternGrader-Scanner-Intraday` (path `\VibeTrade\`) | `Start=08:35 CT`, `RepEvery=5min`, `RepFor=6h30m`; and it was NOT missing — the earlier "invisible" claim was a `Get-ScheduledTaskInfo` call missing the `-TaskPath` argument | `Start=08:30 CT` same repetition / duration / DoW to align with radar |
| `RadarCoverageHealth` | did not exist | NEW. Daily 15:15 CT. Runs `radar_coverage_health.py`. Writes `~/.vibe-trading/health/radar_coverage.json` |
| `XIntakeScanner` | one-shot trigger 2026-08-29 08:35, `LastTaskResult = 267011` (never fired again) | `RepEvery=15min`, `RepFor=8h` from 08:35. Task now fires — but scraper backend is dead (see §7) |
| Windows event log `Microsoft-Windows-TaskScheduler/Operational` | Disabled → no forensic history | **Enabled** via elevated `wevtutil sl … /e:true` |

## 4. Data changes

- `data/spy_move_ledger.jsonl` — backfilled 10 sessions. Now contains 6 moves
  spanning 2026-08-19, 2026-08-20, 2026-08-28. Low-volatility late-August period
  is the reason the count is small, not a bug in the ledger.
- `reports/spy_recall_report.json` — regenerated post-backfill; still shows
  0% radar / pattern-grader / x-intake capture, which is the exact
  measurement gap this upgrade is meant to close.

## 5. Verification results (from the Claude session)

- Manual `Start-ScheduledTask IntradayOpportunityRadar`: pre 276 rows → post 277,
  `LastTaskResult = 0`, timestamped wrapper log entries confirmed, health file
  written with `status=ok, row_delta=1`.
- Health-check discrimination validated:
  - `2026-08-28` → `status=fail, row_count=8, min_rows=70`
  - `2026-08-20` → `status=ok, row_count=42` (note: 42 < user-tightened min of 70, so
    with the tightened threshold this legacy day would now also flag `fail`;
    threshold intentionally strict per the user's edit)
- `PatternGrader-Scanner-Intraday`: `Last=08/30 09:55 result=0`, next run 08:30 Mon.
- End-of-session verification checklist steps below **were NOT re-run after these
  scheduler edits** (see §12). Codex must re-run them.

## 6. Open positions / active risks

- **Options positions** — no changes from Claude this session. Codex should read
  `~/.vibe-trading/options-trades.json` and confirm no open pending exits are
  affected before touching Spotlight or grade-labeling code.
- **Grade-label change is user-facing.** Downstream consumers of `grade == "A+"`
  (dashboard, Discord alerts, any live-trading guard) must be audited so the split
  into `a_plus_candidate` and `a_plus_executable` does not silently disable a
  filter that was gating something else.
- **Silent-failure semantics.** The new wrapper still exits 0 on a zero-row
  successful Python run to preserve fail-open behavior. If Codex changes this to
  fail-closed, several downstream cron chains will start propagating errors.

## 7. Known caveats / deferred items

1. **X intake backend is dead, not just mis-scheduled.** The 15-min repetition
   trigger now fires, but `x_intake_scanner.py` uses Nitter-style scraping and every
   handle returns `Couldn't get animation key indices`; every direct search returns
   `AuthenticationRequired`. `X_BEARER_TOKEN` **is present** in `agent/.env`
   (line 136) but not read by the scanner. Two paths: (a) rewrite scanner against
   X API v2 with the existing bearer, honoring per-endpoint rate limits, or
   (b) leave X intake permanently marked `unavailable` in the dashboard until an
   authenticated data path exists. **Do NOT re-enable X in any promotion gate
   until this is resolved.**
2. **Contract feasibility sidecar does not yet exist.** `spy_recall_report.py`
   already reads `data/spy_contract_feasibility.jsonl` if present. It is not
   written today.
3. **`radar_coverage_health.py` threshold is intentionally strict (70/78).** Any
   legacy day with < 70 snapshots will read as `fail`. Do not weaken this without
   an explicit decision.
4. **Operational log is enabled but empty for 2026-08-28.** That day cannot be
   reconstructed from Windows events. Root-cause for the 8/28 gap remains
   inferred, not proven: schedule fired 47 times, wrapper produced no timestamps,
   only 8 log-JSON rows landed.

---

## 8. What Codex must complete (the actual work)

Order is deliberate. Each item must land shadow-only.

### (a) Economic ranking regret + full-universe nDCG scorecard

- New script `scripts/ranking_regret_report.py`.
- Inputs: `data/intraday_opportunity_radar_log.jsonl` (ranked candidates per
  snapshot), `data/spy_move_ledger.jsonl` + any per-symbol move ledger, closed
  post-hoc option-return data (see (b)).
- Outputs: `reports/ranking_regret_report.json` per session with:
  - `ndcg@k` for k ∈ {5, 10, 20} computed against realized R-multiple / option
    return of every symbol in the discovered universe (not only the top-N).
  - `regret_R` — best executable R among all universe symbols minus R of the
    top-ranked symbol at each snapshot; report mean, p50, p90, worst 5.
  - Attribution: `discovery_miss`, `ranking_miss`, `confirmation_miss`,
    `execution_miss` — mutually exclusive buckets so we can see which stage
    leaks.
- Runner + Task Scheduler entry at 15:35 CT (after SpyRecallReport).

### (b) OPRA contract-feasibility sidecar

- New script `scripts/spy_contract_feasibility_sidecar.py`.
- Reuses `scripts/fetch_databento_options_nbbo.py` OPRA CBBO 1s pipeline —
  do **not** duplicate its cost-guard logic; import and call it.
- For each row in `data/spy_move_ledger.jsonl`, join the SPY quote nearest to
  `window_start_et − 1s` and emit one JSONL row per candidate contract with the
  full schema `spy_recall_report.py` already expects:
  `move_id, occ_symbol, side, strike, expiry, quote_ts, quote_age_ms,
  bid, ask, mid, spread_pct, displayed_size_bid, displayed_size_ask,
  greeks_ts, delta, gamma, theta, vega, stressed_round_trip_cost_usd,
  feasible (bool), unfeasible_reason (str|null)`.
- Write to `data/spy_contract_feasibility.jsonl` (append, dedupe by
  `sha1(move_id + occ_symbol + quote_ts)`).
- Runner + Task Scheduler entry at 15:20 CT (after ledger finalizes, before
  ranking-regret report).
- Must NOT fabricate quotes. If Databento call yields no coverage for the window,
  write a row with `feasible=null` and `unfeasible_reason="no_opra_coverage"`.

### (c) Shadow-limit fill tracker

- Extend the sidecar in (b): for every `feasible=true` contract, simulate a shadow
  limit at mid-1c on the entry side; scan the next 5 minutes of CBBO quotes; log
  first fill time or `no_fill`.
- Append to a second sidecar `data/spy_shadow_limit_fills.jsonl`.
- `execution_enabled` must remain `false` in every emitted row.

### (d) Change-point abstention (Adams–MacKay BOCPD)

- New module `scripts/regime_change_point.py`. Implement Bayesian Online
  Change-Point Detection per Adams & MacKay 2007 on SPY 1-min returns + realized
  vol. Emit `run_length_posterior` and `p_change_point`.
- New writer `data/regime_change_point.jsonl` — 1 row per 1-min bar.
- Consumer: `scripts/intraday_opportunity_radar.py` grade assignment. When
  `p_change_point >= 0.25`, temporarily strip the `A+` label; log an
  `abstention` reason on the candidate so the dashboard can display why.
- Threshold is **not** tunable via env var initially — hardcoded so calibration
  history stays comparable. Any change requires a new calibration bucket.

### (e) ES/NQ impulse + breadth-acceleration challenger (SHADOW ONLY)

- New scanner `scripts/breadth_impulse_challenger.py` — 1 fire per 1-min bar via
  new task `BreadthImpulseChallenger` (Weekly Mon–Fri, 5-min repetition, matches
  radar cadence).
- Inputs: ES/NQ 1-min impulse (return z-score over trailing N bars) combined with
  advance/decline acceleration (Δ of breadth 5-min slope, not raw breadth).
- Output: `data/breadth_impulse_shadow_log.jsonl`. Never feeds `A+ executable`.
  Purely evidence.
- **Do NOT resurrect simple pairwise lead-lag.** The five previous
  post-cost-negative hypotheses are logged; joining them again would re-introduce
  known false edges.

### (f) NOII opening-auction imbalance + overnight-inventory lane (SHADOW ONLY)

- New scanner `scripts/noii_opening_auction_lane.py` — one fire at 09:29:45 ET
  and 09:30:15 ET.
- Consumes Nasdaq NOII (paid feed). If NOII feed is not entitled, write
  `feed_status="unavailable"` to `data/noii_opening_auction_log.jsonl` — do not
  fabricate.
- Runner + Task Scheduler entry.

### (g) Dashboard changes

Edit `scripts/generate_dashboard.py`:

1. Split the grade column: render `A+ candidate` (blue chip) and
   `A+ executable shadow-ready` (green chip) side by side. A row can hold both,
   candidate only, or neither.
2. Feed-availability strip at the top: OPRA, X, NOII, Databento — each shows
   `available / unavailable / stale` from `~/.vibe-trading/health/*.json`. When
   `unavailable`, dependent columns render `—` not a guessed value.
3. Two new widgets:
   - **Ranking Regret** — mean regret_R last 5 sessions, p90, worst-miss link
     to the report.
   - **nDCG@10** — trailing 5-session sparkline.
4. Change all copy currently saying "trade alert" / "trade-ready" / "best of the
   day" on an unpromoted candidate to "candidate". Only `A+ executable
   shadow-ready` rows may use "shadow-ready".

### (h) Tests

Add under `agent/tests/`:

1. `test_radar_coverage_health.py` — asserts fail at 8 rows, ok at 78, warn
   during pre-close in-progress, ok for non-market days.
2. `test_ranking_regret_report.py` — synthetic universe with a known winner
   ranked 4th; assert `regret_R > 0` and attribution bucket is
   `ranking_miss`.
3. `test_contract_feasibility_schema.py` — round-trip a synthetic move + fake
   Databento response; assert every required field present and
   `execution_enabled=false`.
4. `test_change_point_abstention.py` — synthetic regime break; assert `A+`
   stripped when `p_change_point >= 0.25`.
5. `test_grade_split.py` — assert `a_plus_candidate` and
   `a_plus_executable` are computed independently and dashboard renders both.
6. `test_generate_dashboard.py` — extend existing test to cover the new
   split, missing-feed indicators, and the two new widgets.

---

## 9. Hard constraints (repeated so they are not lost mid-implementation)

- `execution_enabled=false` in every emitted row from every new writer.
- Fail-open on health signals unless the change explicitly justifies fail-closed.
- **No ranking-threshold changes without a new calibration bucket.** The current
  ranking-qualified bucket count is 0; the tightening of A+ criteria must come
  through the two-label split, not by moving the score threshold.
- **Do NOT revive simple pairwise cross-asset lead-lag.** Five prior hypotheses
  failed after costs.
- MBO/MBP-10 depletion / cancellation / replenishment / microprice may be used
  **only** as confirmation or veto (per Cont, Kukanov, Stoikov). They may not
  drive candidate discovery on their own.
- Any unavailable feed renders as `unavailable`. Never impute, never guess.
- Preserve the wrapper-log timestamped format (`ISO8601 START|STEP|END|ERROR`)
  when adding new pipeline steps to `run_intraday_opportunity_radar.ps1` or
  peer wrappers.

---

## 10. End-of-session verification (Codex must run before declaring done)

```powershell
python scripts/signal_stack_health_report.py --no-write
# → OK=38+ STALE=0 MISSING=0 ERROR=0

python scripts/execution_gate_audit.py --print
# → passed=True issues=0

python -m pytest agent/tests/test_flip_bot_safety.py `
                 agent/tests/test_iwm_options_confidence_gate.py `
                 agent/tests/test_options_liquidity_feasibility.py `
                 agent/tests/test_generate_dashboard.py `
                 agent/tests/test_radar_coverage_health.py `
                 agent/tests/test_ranking_regret_report.py `
                 agent/tests/test_contract_feasibility_schema.py `
                 agent/tests/test_change_point_abstention.py `
                 agent/tests/test_grade_split.py -q
# → all pass, show count

python scripts/radar_coverage_health.py --date <last_market_day>
# → status=ok when data present, status=fail otherwise (with reason)

python scripts/spy_recall_report.py
# → recall report regenerated; contract_feasible field now populated where
#   Databento coverage exists

python scripts/generate_dashboard.py
# → Wrote ~/.vibe-trading/dashboard.html; two grade chips visible; feed strip
#   shows OPRA/X/NOII/Databento status; regret + nDCG widgets render
```

Report back with:
- test count
- health OK count
- gate audit result
- whether OPRA cost-guard triggered
- how many `A+ executable` rows appeared vs `A+ candidate` rows on the most
  recent live session
- list of any `unavailable` feeds and why

---

## 11. Next-session priority action

Start with **(b) OPRA contract-feasibility sidecar** — it is the single most
information-dense change and unblocks the executability half of the two-label
split. Everything else can layer on top of a working sidecar.

## 12. Deferred / not run

- The end-of-session verification checklist in §10 was **not** run by Claude
  after the scheduler edits landed. Codex must run it as part of its own close-
  out to confirm no regression in the flip-bot / IWM options / liquidity / gate
  audit suites.
- Contract feasibility, ranking regret, change-point abstention, breadth
  challenger, NOII lane, dashboard split, and the six new tests are all Codex's
  work — none started by Claude.

---

## 13. Red flags to avoid

- Any handoff back that says "tests pass" without a count → reject.
- Any handoff back that omits open options positions → reject.
- Any change that flips `execution_enabled` to `true` anywhere → reject.
- Any change that adds a live-trading path without the two-label executability
  gate + calibrated bucket + no active abstention → reject.
- Any use of the phrase "trade alert" for a row that is only `A+ candidate` →
  reject.

---

**End of handoff. Codex: resume from your active workstreams.**
