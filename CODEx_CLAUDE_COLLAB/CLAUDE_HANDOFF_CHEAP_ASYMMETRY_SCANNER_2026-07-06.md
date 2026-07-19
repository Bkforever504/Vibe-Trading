# Claude Handoff: Cheap Asymmetry Scanner

Date: 2026-07-06

## Objective

Move the bot stack toward the screenshot goal:

> Small defined option cost, large asymmetric upside, clean profit capture.

Example target profile:

- Cost at open: about $10-$50 per contract
- Close credit: 3x-6x+ possible
- Realized/captured return: ideally 500%+ for true goal matches
- Tight spread
- No chasing after the move is mature
- No execution until repeated shadow evidence exists

## What Codex Implemented

Added a new read-only scanner:

- `scripts/cheap_asymmetry_scanner.py`
- `scripts/run_cheap_asymmetry_scanner.ps1`
- `agent/tests/test_cheap_asymmetry_scanner.py`
- Registry entry in `research/signal_registry.json`

The scanner consumes:

- `~/.vibe-trading/reports/flip-shadow-pnl-evaluator.json`

It writes:

- `~/.vibe-trading/reports/cheap-asymmetry-scanner.json`
- `data/cheap_asymmetry_scan_log.jsonl`

It never calls broker APIs and has:

- `execution_enabled=false`
- `can_submit_orders=false`
- no `/v2/orders`

## Scanner Rules

Current thresholds:

- `MIN_CONTRACT_COST = 10.0`
- `MAX_CONTRACT_COST = 50.0`
- `MIN_RETURN_PCT = 200.0`
- `GOAL_RETURN_PCT = 500.0`
- `MAX_SPREAD_CENTS = 20`

Candidate:

- Cost between $10 and $50
- Best return at least +200%
- Spread no wider than 20 cents

True `goal_match`:

- Cost between $10 and $50
- Best return at least +500%
- Simulated/captured return at least +500%
- Spread no wider than 20 cents

This distinction matters. A contract can be a huge runner but not yet a screenshot-style captured winner.

## July 6 Result

Command:

```powershell
python scripts\cheap_asymmetry_scanner.py --date 2026-07-06 --print
```

Output summary:

```text
Cheap Asymmetry Scanner | read-only
date=2026-07-06 candidates=2 goal_matches=0 rejected=23
AAPL CALL cost=$31.00 best=$198.00 profit=$167.00 ret=538.7%
META CALL cost=$23.00 best=$79.00 profit=$56.00 ret=243.5%
No orders placed. No settings changed.
```

Interpretation:

- We are finding the kind of cheap explosive contracts.
- We did not yet prove the bot can capture the full screenshot-style move.
- Dashboard should show both `best possible` and `simulated captured`, so we do not fool ourselves.

## Verification Already Run

```powershell
python -m pytest agent/tests/test_cheap_asymmetry_scanner.py agent/tests/test_execution_gate_audit.py -q
```

Result:

```text
5 passed
```

```powershell
python scripts\execution_gate_audit.py --print
```

Result:

```text
passed=True signals=74 issues=0 warnings=1
```

The one warning is the known read-only portfolio concentration broker-client warning.

## Claude Code Next Tasks

Please continue from here.

1. Dashboard Integration
   - Add a “Cheap Asymmetry” section to `scripts/generate_dashboard.py`.
   - Show:
     - cost at open
     - best credit
     - best profit
     - best return %
     - simulated/captured return %
     - capture efficiency
     - spread cents
     - labels
     - goal_match count
   - Keep it visually aligned with dashboard standards.
   - Do not add a live server.

2. Scheduler Integration
   - Decide whether to schedule `scripts/run_cheap_asymmetry_scanner.ps1` after `FlipShadowPnLEvaluator`.
   - If scheduling, add a Task Scheduler job under `\VibeTrade\CheapAsymmetryScanner`.
   - Then add it to `scripts/signal_stack_health_report.py`.
   - Do not add it to health until the task exists, or health will false-warn.

3. Promotion Governance
   - Update signal grades / leaderboard only as read-only if there is an established local pattern.
   - Add promotion rules:
     - at least 30 trading days
     - at least 10 completed samples per symbol
     - repeated goal matches or high capture efficiency
     - options liquidity gate passes
     - no overtrading
     - dual Claude/Codex review

4. Bot Strategy Implication
   - Do not wire this directly to Flip Bot entries.
   - The next live/paper step should be evidence review, not execution.
   - The big question is whether cheap runners should influence symbol selection, not whether we should blindly buy cheap contracts.

5. Tests
   - Add dashboard tests for the new section.
   - Run:

```powershell
python -m pytest agent/tests/test_cheap_asymmetry_scanner.py agent/tests/test_generate_dashboard.py agent/tests/test_execution_gate_audit.py -q
python scripts\execution_gate_audit.py --print
python scripts\cheap_asymmetry_scanner.py --date 2026-07-06 --print
python scripts\generate_dashboard.py
```

## Safety Reminder

This is read-only evidence. It helps us move toward the goal:

- cheap controlled-risk plays
- explosive upside
- strong capture
- adaptive selection

But it is not permission to trade cheap lottos.

