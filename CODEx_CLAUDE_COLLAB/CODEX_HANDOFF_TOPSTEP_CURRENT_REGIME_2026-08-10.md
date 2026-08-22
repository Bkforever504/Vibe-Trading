# Codex Handoff: Topstep Current-Regime Research - 2026-08-10

## Executive State

No strategy was promoted and no order was submitted.

The corrected 2024+ MES ORB/pullback search has completed. It found 58
development survivors but only 33 unique trade paths and zero selection
survivors. A separately preregistered opening-gap failure/fade family also
found zero stability survivors and a 0% simulated Combine pass rate at 1-2
MES. Current decision: do not purchase a Combine for these strategies.

## Final ORB Diagnostic

Artifact: `data/mes_strategy_search_2024plus_rollsafe_unique_diagnostic.json`

- Period: 2024-01-02 to 2026-07-17.
- Split: 448 development / 96 selection / 97 diagnostic final sessions.
- Grid: 16,320 executable-only candidates.
- Development survivors: 58.
- Unique development finalists: 33.
- Duplicate trade paths removed: 25.
- Selection survivors: 0.
- Final period: not evaluated because selection had no survivor.
- Evidence label: consumed-history diagnostic, not independent validation.

Least-negative selection row: pullback, 5-minute range, 1-point breakout,
2R, 80-tick stop, EMA20 filter; 14 trades, -$1.77 base expectancy/PF 0.9708,
-$5.95 doubled-cost expectancy/PF 0.9060.

## Integrity Fixes

`strategies/topstep_prop_bot.py`

- `Candle` now retains optional `instrument_id` provenance from licensed CSVs.

`strategies/topstep_replay_backtester.py`

- Opening-gap direction fails closed when the current contract differs from
  the prior session's contract.

`research/mes_futures_strategy_search.py`

- Strict ISO `start_date` parsing and effective-period metadata.
- Explicit research-only/consumed-history labels.
- Exact development trade-path deduplication before finalist selection.
- Optional deterministic local process parallelism via `--workers`.

## Mean-Reversion Challenger

Files:

- `research/MES_OPENING_GAP_FADE_PREREGISTRATION_2026-08-09.md`
- `research/mes_opening_gap_fade_lab.py`
- `data/mes_opening_gap_fade_results.json`
- `research/MES_OPENING_GAP_FADE_RESULTS_2026-08-09.md`

The 12 frozen variants exclude roll boundaries, enter next-bar after explicit
gap rejection, target the prior close, use stop-first ambiguity, include base,
2x, 3x, delayed-entry, and top-winner-removal stress, and run exact 50K
Combine bootstraps. Zero variants passed. The broadest positive row had only
eight trades; do not expand the grid after seeing it.

## New Information Lane

The one-minute OHLCV strategy inventory is saturated. The next lane records
genuinely new ProjectX data:

- `strategies/topstepx_market_recorder.py`: read-only SignalR recorder for MES
  quotes, aggressor trades, and explicit DOM updates; rotating 50 MB x 3;
  source and local timestamps; no account/order methods.
- `scripts/topstepx_market_recorder.py`: authenticated local runner with exact
  personal-device confirmation and credential/token redaction.
- `research/topstepx_microstructure_features.py`: causal five-second spread,
  signed-volume, mid-response, top-five depth, completeness, and receipt-lag
  features. These are measurements, not signals.
- `research/TOPSTEPX_MICROSTRUCTURE_DATA_PROTOCOL_2026-08-09.md`: collection
  gate and the first three allowed future hypotheses.

TopstepX credentials are not configured. The recorder probe correctly exits
blocked before login/socket activity. `data/topstepx_market_recorder_status.json`
records the fail-closed status. Do not install a scheduler yet.

## Activation Sequence

Only on the user's personal device, after TopstepX API access and a Practice
account exist:

1. Set `TOPSTEPX_USERNAME`, `TOPSTEPX_API_KEY`, and
   `TOPSTEPX_PRACTICE_ACCOUNT_ID` in `agent/.env`.
2. Set `TOPSTEPX_LOCAL_DEVICE=PERSONAL_DEVICE_CONFIRMED`; leave Practice order
   confirmation blank while collecting data.
3. Run `scripts/run_topstepx_practice_probe.ps1`.
4. Run `scripts/run_topstepx_market_recorder.ps1` during RTH.
5. Accumulate at least 20 complete sessions and pass the event-count,
   completeness, latency, reconnect-gap, contract, and event-label gates.
6. Freeze one small absorption/continuation test family before analysis.

Do not set `TOPSTEPX_PRACTICE_EXECUTION=PRACTICE_ONLY_CONFIRMED` until a new
strategy passes forward evidence and exact Combine risk requirements.

## Verification

- Focused Topstep/research suite: 90 passed.
- Recorder/feature follow-up after final security and latency edits: 9 passed.
- Full repository suite on final code: 4,514 passed, 4 skipped, 4 existing
  deprecation warnings in 299.95 seconds.
- `git diff --check`: clean except existing LF-to-CRLF notices.
- Final four-worker 16,320-candidate diagnostic completed with empty stderr.

The repository was already heavily dirty with unrelated generated research,
logs, and user/agent edits. Those were left untouched. This work is uncommitted.

## Safety Invariants

- No funded, Combine, or Practice orders were submitted.
- No live broker credentials were present or used.
- Search, gap-fade, recorder, and feature artifacts have no execution authority.
- Topstep API use remains personal-device only; no VPS/VPN/remote scheduling.
- No contract scaling is allowed to compensate for absent expectancy.

## Paste-Ready Claude Code Directive

Continue from this handoff. Do not rerun or widen the failed ORB and opening-gap
fade grids. Their 2024-2026 history has been consumed and cannot be presented as
independent validation.

Your next objective is to make the TopstepX MES microstructure evidence lane
operational on the user's personal device without enabling order submission.

1. Audit the recorder, runner, feature builder, protocol, and their tests before
   changing code. Preserve all credential redaction and read-only boundaries.
2. Check whether TopstepX API access, a Practice account, and the three required
   environment values now exist. Never print secret values. If any prerequisite
   is absent, report the exact missing variable and stop activation work; continue
   only with offline tests and documentation.
3. When prerequisites exist, run the Practice probe and a short manual recorder
   smoke test. Confirm the active MES contract, quote/trade/DOM subscriptions,
   source and receipt timestamps, reconnect behavior, log rotation, and status
   artifact. Do not install a scheduler until this smoke test is clean.
4. Build a daily data-quality report that enforces every threshold in
   `research/TOPSTEPX_MICROSTRUCTURE_DATA_PROTOCOL_2026-08-09.md`. It must fail
   closed on missing event types, contract ambiguity, timestamp disorder,
   reconnect gaps, incomplete RTH coverage, or excessive latency.
5. Collect at least 20 complete RTH sessions before testing an entry rule. Do not
   substitute synthetic, reconstructed, or one-minute data for missing order-flow
   observations.
6. Before looking at outcomes, preregister exactly one small hypothesis family
   from the three allowed in the protocol. Freeze features, thresholds, costs,
   stop/target mechanics, time windows, exclusion rules, familywise alpha, and
   promotion criteria in a dated Markdown file.
7. Evaluate chronological development, selection, and untouched forward data.
   Require positive expectancy after doubled costs, acceptable drawdown, adequate
   trade count, stability across days/regimes, and exact Topstep rule simulation.
   Report zero survivors plainly if that is the result.
8. Keep `execution_enabled: false` and `can_submit_orders: false`. Do not set
   `TOPSTEPX_PRACTICE_EXECUTION`, buy a Combine, submit an order, optimize toward
   a requested win rate, or increase size to manufacture a dollar target.
9. Run focused tests followed by the full repository suite. Do not modify or
   discard unrelated dirty-worktree changes. Produce a new dated handoff listing
   commands, artifacts, exact results, blockers, and whether any order was sent.

Success for the next session means a reliable, auditable dataset and a frozen
experiment, not a claim of profitability. Strategy promotion remains blocked
until genuinely unseen forward evidence passes the stated gates.
