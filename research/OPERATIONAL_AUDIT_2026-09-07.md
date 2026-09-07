# Operational and overfitting audit — 2026-09-07

Verdict: infrastructure repairs verified; strategy promotion remains NOT READY pending prospective evidence.

## Repair update

- Scheduler probing was changed from serial CIM calls to one bounded Task Scheduler COM session. It now preserves partial evidence instead of discarding the full heartbeat on timeout.
- Scanner cadence uses the NYSE calendar, including holidays and early closes. Calendar failure is explicit `calendar_unavailable`; it can never become a healthy weekday guess.
- BLSH outcomes are built once from market bars and joined many-to-one to scanners, preventing cross-scanner contamination. Horizons use complete exchange sessions and fail honest on missing 15-minute coverage.
- LightGBM uses global calendar-month walk-forward folds and purges labels whose outcome ends at or after the prediction boundary. Historical replay rows are explicitly ineligible as live evidence.
- Session VWAP resets by New York trading date. CLI input failures now return nonzero with a timestamped `unavailable` report.
- Live opportunity candidates freeze `signal_available_at` and deadlines for a completed signal bar; repeated dashboard snapshots can no longer make an old setup look fresh.
- Unit tests no longer depend on workstation GARCH or approval files. Missing approval, future/stale gate evidence, and risk veto behavior remain separately tested.
- The repaired statistical gate stays quarantined. Benchmark-relative net returns, multiple-testing control, point-in-time optionable universes, the full HMM/IVR/breadth feature fabric, and prospective three-month collection are still required before a human-review nomination.

## Observed deployment

- Research checkout HEAD before audit: 12d975b, research/ollama-shadow-critic.
- Scheduler checkout HEAD: da8b612, Desktop/MAILK-Repos/Vibe-Trading. The upgrade branch is not deployed there.
- Scheduler checkout has unrelated user changes in a handoff, flip exit comparison data, and the TradingView submodule. Preserved.
- Dashboard HTML regenerates, but aggregate signal-stack-health.json is dated September 4 and records historical failures. Rendering a dashboard does not establish current service health.
- Latest observed heartbeat report: FAIL / TimeoutExpired, September 7 17:12 UTC.
- Radar wrapper failed three observed September 7 runs at institutional_confluence_shadow.py; operational breaker reported OPEN after the third failure. No breaker reset performed.
- Direct scheduler-style launch reproduced ModuleNotFoundError for scripts.options_nbbo_evidence. Fixed repository import bootstrap in both checkouts; direct CLI regression added.
- Last inspected Discord delivery artifact is September 4, four delivered / zero delivery failures in that artifact. This does not prove today's delivery.
- Live opportunity report says connected_hybrid, but candidate_count is zero and reports blocked data quality. Connection status is not evidence of valid tradable data.
- Portfolio monitor, MicroMomentumPaper and WinnerDnaMatchedReplay had result 1; dashboard server tasks had 3221225786 (interrupted). These results need individual diagnosis.
- No listeners were returned for localhost ports 4200, 8080, 11434 or 8000 during the audit. No operational Prefect or local inference service was established by this check.
- September 7 is the Labor Day equity/options market holiday. Absent fresh RTH bars today is expected, and must not be confused with a connection error. Source: https://www.nyse.com/publicdocs/nyse/ICE_NYSE_2026_Yearly_Trading_Calendar.pdf

## Statistical audit

The prior completion report overstates the BLSH implementation. Findings:

1. LightGBM splits ticker-sorted rows instead of using a global chronological boundary; training labels are not purged at the prediction boundary.
2. Forward joins shift the combined prediction table by ticker, permitting scanner-boundary contamination and treating rows as days.
3. The function named diebold_mariano is an independent-observation normal approximation. It has no overlap/dependence correction.
4. Raw signed returns are labeled excess returns without benchmark and transaction-cost subtraction.
5. Counts do not prove prospective collection, three months of actual sessions, independently resolved samples, or multiple-testing control.
6. ARPS uses fixed arbitrary weights and a trend proxy, not the specified trained weights and HMM/IVR/breadth fabric. VWAP is cumulative across sessions; 5/20/60 windows count rows rather than verified days.
7. Only three simple property tests were implemented, two on copied formulas. They do not establish the requested IWM/flip lifecycle and execution-math coverage.
8. Pandera schemas exist but the requested ten scanner and two strategy input boundaries are not wired. Prefect wrappers exist but deployments, schedules and the 48-hour soak are absent.

Containment applied: public statistical_promotion_gate now unconditionally returns blocked_validation_defects, no winner and no automatic registry change. This is a quarantine, not a claim that overfitting has been fixed. All historical BLSH output requires regeneration after repair; no performance claim is admissible from the current pipeline.

## Verification and next completion criteria

- Direct confluence CLI and regression pass after the import fix.
- Nine focused tests passed (CLI bootstrap, BLSH, contracts).
- Order authority invariant: zero violations in the scheduler checkout.
- Complete service-specific failure diagnosis; reconcile the research and scheduler branches through review while preserving user changes.
- Repair causal labels, calendar horizons, single-market-bar outcome joins, costs, point-in-time universe, and dependent/multiple comparisons before lifting the quarantine.
- Wire real deployment and scanner contracts, then collect the specified forward and operational evidence. No assertion of zero overfitting or improved profitability is currently supported.
