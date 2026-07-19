# Claude Code Handoff: Topstep Prop Bot Arena

Date: 2026-06-21
Project folder: `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading`

## Kenny's Goal

Build the best realistic automated trading system for a prop-firm path, preferably Topstep, while leaving the existing Alpaca options bot running separately. The prop bot must be a separate futures-first arena with a very high confidence standard.

Important framing:

- Do not chase hype.
- Do not promise easy money.
- Build a system that can prove or disprove edge.
- AI may analyze/rank/explain, but deterministic rules and risk gates control execution.
- No funded/live automation until confidence is earned with data.

## Current State

Codex implemented the first Topstep prop-bot foundation:

- `strategies/topstep_prop_bot.py`
  - Paper-only futures scanner.
  - Supports `MNQ`, `NQ`, `MES`, `ES`.
  - First strategy: opening-range breakout with VWAP confirmation.
  - Reads minute candles from CSV.
  - Sizes contracts using risk budget, stop distance, point value, and max-contract cap.
  - Evaluates every proposed trade through `strategies/prop_rule_gate.py`.

- `strategies/prop_rule_gate.py`
  - Deterministic prop-firm allow/block gate.
  - Blocks automation-prohibited profiles.
  - Blocks VPS/remote-server violations when local device is required.
  - Blocks missing/unknown required rules when `unknown_rules_block` is true.
  - Blocks daily loss, trailing drawdown, max contracts, and consistency-rule breaches.

- `strategies/risk_kill_switch.py`
  - Manual-reset block file: `~\.vibe-trading\MANUAL_RESET_REQUIRED.json`.
  - If the file exists, order helpers refuse broker submission.

- `strategies/shadow_ai_signals.py`
  - Writes shadow-only AI signal records to `~\.vibe-trading\shadow-ai-signals.jsonl`.
  - Every record has `mode: shadow_only` and `executable: false`.

- `rules/prop_firms/`
  - `topstep_topstepx_api.json`
  - `apex_conservative.json`
  - `tradeify_conservative.json`
  - `README.md`

- `examples/mnq_opening_range_sample.csv`
  - Tiny sample CSV for CLI verification.

- `KNOWLEDGE/TOPSTEP_PROP_BOT_PLAYBOOK.md`
  - Operating playbook and confidence score standard.

- `KNOWLEDGE/PROP_FIRM_AUTOMATION_BLUEPRINT.md`
  - Overall prop automation blueprint.

- `KNOWLEDGE/LAST30DAYS_AI_PROP_TRADING_RESEARCH_2026-06-21.md`
  - Research brief from Reddit/YouTube/X-attempts.

## Verification Already Passed

Run from repo root:

```powershell
uv run --no-project --with pytest python -m pytest agent/tests/test_topstep_prop_bot.py agent/tests/test_strategy_safety_layers.py -q
```

Expected:

```text
11 passed
```

Compile check:

```powershell
python -m py_compile strategies\topstep_prop_bot.py strategies\prop_rule_gate.py strategies\risk_kill_switch.py strategies\shadow_ai_signals.py strategies\iwm_options_bot.py strategies\flip_bot.py strategies\trading_dashboard.py
```

Sample CLI:

```powershell
python strategies\topstep_prop_bot.py `
  --csv examples\mnq_opening_range_sample.csv `
  --profile rules\prop_firms\topstep_topstepx_api.json `
  --symbol MNQ `
  --range-minutes 3 `
  --min-breakout-points 0.5 `
  --risk 100 `
  --max-contracts 2 `
  --day-pnl -100 `
  --drawdown-remaining 1900
```

Expected important output:

```text
status = paper_order_ready
rule_gate.allowed = true
rule_gate.confidence_score = 100
```

## Current Confidence Scores

Compliance/rule-gate confidence: 9.5/10

Reason:

- Rule profiles exist.
- Unknown/unverified rules block by default.
- Topstep-style sample passes only after deterministic gate.
- Apex/Tradeify conservative profiles block automation until verified.

Strategy-profit confidence: 4/10

Reason:

- Opening-range/VWAP strategy is clean and testable.
- No historical replay/backtest yet.
- No 50+ closed paper/replay trades yet.
- No fees/slippage modeling yet.
- No news/session filter yet.

## Claude Code Next Task

Replay backtester is now built. Next task is real historical MNQ/MES minute data ingestion and MES vs MNQ comparison runs.

Read this selection note first:

- `CODEx_CLAUDE_COLLAB/PROP_FIRM_SELECTION_2026-06-21.md`

Decision: Topstep is the first prop-firm target. Do not build Take Profit Trader automation. Keep Tradeify as a secondary research candidate only.

Replay backtester implementation:

1. Module: `strategies/topstep_replay_backtester.py`.
2. Tests: `agent/tests/test_topstep_replay_backtester.py`.
3. Input: CSV minute candles in the same format:
   - `timestamp`
   - `open`
   - `high`
   - `low`
   - `close`
   - `volume`
4. Replays one trading day at a time.
5. Uses `build_opening_range_signal()` from `topstep_prop_bot.py`.
6. Simulates target/stop after entry.
7. Includes configurable:
   - slippage in ticks
   - commission per contract round trip
   - max trades per day
   - no-trade after daily loss limit
8. Outputs:
   - trades list
   - total P&L
   - win rate
   - profit factor
   - expectancy
   - max drawdown
   - rule violations

Codex verification:

```powershell
uv run --no-project --with pytest python -m pytest agent/tests/test_topstep_replay_backtester.py agent/tests/test_topstep_prop_bot.py agent/tests/test_strategy_safety_layers.py -q
```

Expected:

```text
28 passed
```

Important fix applied:

- The sample CLI originally produced a fake large loss when there were no candles after the entry candle.
- Codex added regression coverage and fixed EOD fallback to use the entry candle close/time.

Next requirements:

1. Get real MNQ/MES minute data.
2. Run 30+ trading days through the backtester.
3. Report separately for MES and MNQ.
4. Compare win rate, profit factor, expectancy, max drawdown, and consistency-rule violations.
5. Keep everything paper/replay only. No broker connection.

## Design Rules

- Use deterministic code for trade entry, sizing, and risk.
- AI can explain/rank signals later, not execute.
- Keep modules small and testable.
- Do not modify Alpaca options bot strategy logic unless explicitly requested.
- Do not add live Topstep broker/API execution yet.
- Do not store secrets in the repo.

## Success Standard

The next milestone is not "make money" yet. It is:

- Replay backtester exists.
- Tests pass.
- We can run 30-90 days of MNQ/MES data when available.
- Strategy confidence can move from 4/10 toward 6/10 based on measured expectancy.
