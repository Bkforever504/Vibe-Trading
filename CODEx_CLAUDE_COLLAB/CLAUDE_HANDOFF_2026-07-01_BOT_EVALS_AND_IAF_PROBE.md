# Claude Handoff — 2026-07-01 Bot Evaluations, Profit Protection, IAF Probe

Project:
`C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading`

User goal:
Keep improving the bots toward high-confidence, risk-controlled profitability. No rushed live-capital escalation. Every new signal stays read-only/shadow until it earns promotion through evidence.

## Executive Summary

Today was operationally good and important.

- Alpaca account snapshot from `bot_status_snapshot`: equity `$89,601.06`, day change `+$210.66`, buying power `$355,584.24`.
- No open Flip Bot trades after monitor/profit-protect.
- No open IWM/options tracked positions after monitor.
- IWM put spread closed correctly at `+55.8% of credit`.
- TSLA put spread closed correctly at `+47.7% of credit` by near-target protection after noon ET.
- Flip Bot SPY call was protected after fading from a best mark of `+52.5%` and closed green at about `+$40`.
- Execution gate audit passed: `issues=0`, only warning is known read-only Alpaca account/position reads in `portfolio_concentration_monitor.py`.
- New Investing Algorithm Framework probe is read-only and matched the existing QQQ/GLD shadow signal.

## Important Code Changes Today

### -1. Challenge simulator + 0DTE shadow symbol extension

Built after Claude stopped for session-cost control.

New/updated files:

- `scripts/challenge_account_simulator.py`
- `scripts/run_challenge_account_simulator.ps1`
- `scripts/flip_shadow_candidates_report.py`
- `strategies/flip_bot.py`
- `agent/tests/test_challenge_account_simulator.py`
- `agent/tests/test_flip_bot_safety.py`
- `scripts/signal_stack_leaderboard.py`
- `scripts/signal_stack_health_report.py`
- `scripts/export_daily_bot_activity_csv.py`
- `agent/tests/test_signal_stack_leaderboard.py`
- `research/signal_registry.json`

Challenge simulator:

- Reads closed Flip Bot trades from `~/.vibe-trading/flip-trades.json`.
- Replays them on a configurable small account.
- Default run: `$1,000` start, `2%` fixed fractional risk per trade.
- Writes:
  - `~/.vibe-trading/reports/challenge-account-simulator.json`
  - `data/challenge_account_simulator_log.jsonl`
- Scheduled task:
  - `\VibeTrade\ChallengeAccountSimulator`
  - daily at `19:55 CT`

Latest simulator result:

```text
Start $1,000.00 -> $1,022.78 (+2.28%)
Trades=5
Win rate=80.0%
Max DD=1.33%
Risk=2.0%
Best: 2026-06-30 SPY +$16.16 simulated
Worst: 2026-06-23 SPY -$13.29 simulated
```

Important interpretation:

- This uses realistic fixed fractional sizing, not the original large-account contract count.
- It is read-only and cannot approve leverage by itself.

Flip Bot 0DTE shadow candidates:

- Added `SHADOW_CANDIDATES = ["QQQ", "NVDA", "TSLA"]`.
- Added `log_shadow_0dte_candidates(account)`.
- Called during `run_entry()` after market-open check.
- Logs QQQ/NVDA/TSLA 0DTE candidate setups to:
  `data/flip_shadow_candidates_log.jsonl`
- Entries include:
  - `execution_mode="shadow_only"`
  - `live_execution_allowed=false`
  - promotion requirement notes
- These candidates do not enter the broker submission path.

Latest shadow candidate report:

```text
Rows: 9
By symbol: QQQ=3, NVDA=3, TSLA=3
By right: PUT=3, CALL=6
```

Read-only report:

- `scripts/flip_shadow_candidates_report.py`
- `~/.vibe-trading/reports/flip-shadow-candidates.json`

Governance:

- Added both components to `research/signal_registry.json`.
- Registered Flip Shadow Candidates against the read-only report script, not `strategies/flip_bot.py`, so audit does not falsely treat the shadow registry item as an execution script.
- Execution audit now reports:

```text
passed=True
signals=56
issues=0
warnings=1
```

Focused verification:

```text
agent/tests/test_challenge_account_simulator.py
agent/tests/test_flip_bot_safety.py
agent/tests/test_signal_stack_leaderboard.py
agent/tests/test_export_daily_bot_activity_csv.py

19 passed
```

### 0. CBOE direct VIX/VIX3M term structure

Files:

- `scripts/market_data.py`
- `strategies/flip_bot.py`
- `strategies/iwm_options_bot.py`
- `agent/tests/test_market_data.py`
- `agent/tests/test_flip_bot_safety.py`
- `test_iwm_options_execution_guard.py`

Changed after Claude's VXV note:

- Added `fetch_vix_term_structure_context()` in `scripts/market_data.py`.
- It fetches CBOE direct CSVs:
  - `VIX_History.csv`
  - `VIX3M_History.csv`
- Returns:
  - `vix`
  - `vix3m`
  - `vix_over_vix3m`
  - `vix3m_over_vix`
  - `regime`
  - `source=cboe_vix_vix3m_history`
- Flip Bot now uses this helper instead of Yahoo `^VIX3M`.
- IWM Options Bot now uses this helper instead of Yahoo `^VXV` / `^VIX3M`.
- Fail-open behavior is preserved if CBOE is unavailable, but the primary source is now direct CBOE instead of Yahoo ticker aliases.

Live fetch verification:

```text
{'source': 'cboe_vix_vix3m_history', 'date': '06/30/2026', 'vix': 16.45, 'vix3m': 19.16, 'vix_over_vix3m': 0.8586, 'vix3m_over_vix': 1.1647, 'regime': 'contango'}
```

Focused tests:

```text
agent/tests/test_market_data.py
agent/tests/test_flip_bot_safety.py
test_iwm_options_execution_guard.py

23 passed
```

### 1. Flip Bot profit protection

File:
`strategies/flip_bot.py`

Added a profit-protect mechanism:

- Arms when an open Flip Bot option reaches `+50%` P&L.
- If it later fades to `+30%` or lower while still positive, it closes.
- Records and persists `best_pnl_pct`.
- Close reason format:
  `PROFIT PROTECT +x% (best +y%)`

Why:
The SPY call hit about `+52.5%`, then faded. Old logic would wait for +75%, -50%, or time exit. The new logic preserves winners that already paid us.

Also fixed a state integrity issue:

- `_load()` no longer silently returns `[]` on JSON parse errors.
- It reads with `utf-8-sig` so a BOM in `~\.vibe-trading\flip-trades.json` does not make the bot forget open trades.
- Parse failures now raise instead of hiding state loss.

Test:
`agent/tests/test_flip_bot_safety.py`

Added/updated:

- `test_flip_bot_monitor_profit_protects_fading_winner`
- Mocked broker-open-symbols in existing spread-entry test to avoid live duplicate-exposure interference.

Verification:

```powershell
uv run --no-project pytest -q agent\tests\test_flip_bot_safety.py
```

Result:
`7 passed`

### 2. Investing Algorithm Framework QQQ/GLD probe

Evaluated repo:
`https://github.com/coding-kitties/investing-algorithm-framework`

Verdict:
Useful as a sandbox/backtesting/reporting pattern, not as a replacement for execution.

New files:

- `scripts/iaf_qqq_gld_probe.py`
- `agent/tests/test_iaf_qqq_gld_probe.py`
- `tools/investing_algorithm_framework_probe/README.md`

Current probe:

- Recomputes QQQ/GLD 40-day rotation.
- Produces framework-style metrics.
- Compares latest result against existing `data/qqq_gld_shadow_log.jsonl`.
- Writes:
  `~\.vibe-trading\reports\iaf-qqq-gld-probe.json`

Latest run:

```text
Mode: sandbox_probe | execution_enabled=False
Latest: 2026-06-30 selected=QQQ action=hold_qqq
Backtest: return=+49.36% DD=15.11% Sharpe=2.02 trades=9
Shadow comparison: match
```

Safety:

- `execution_enabled=false`
- `live_trading_allowed=false`
- no broker order calls
- no scheduler by default
- cannot replace existing guard stack

Verification:

```powershell
uv run --no-project pytest -q agent\tests\test_iaf_qqq_gld_probe.py
uv run --no-project --with alpaca-py --with yfinance --with pandas python scripts\iaf_qqq_gld_probe.py --print
uv run --no-project python scripts\execution_gate_audit.py --print --fail-on-issues
```

Results:

- IAF probe tests: `4 passed`
- Execution audit: `passed=True`, `issues=0`

## Bot Evaluations Today

### Flip Bot

Status:
Improved today. No open trades after profit-protect.

Key trade:

- SPY 0DTE call opened earlier today.
- Best observed P&L approximately `+52.5%`.
- Faded from peak.
- New profit protection closed it green at about `+$40`.

Important log facts:

- Later scans were correctly blocked for `confidence_below_minimum`.
- After 2pm ET cutoff, trend entries correctly skipped.
- Market-closed monitor checks correctly skipped after close.

Current evaluation:

- Operationally better after profit-protect.
- Still not promotion-perfect because historical normalized P&L file contains ugly old Flip Bot values.
- Treat current new logic as a fresh forward-test period starting after this fix.

Watch next:

- Confirm future fading winners close by profit-protect.
- Confirm no silent state loss if JSON has BOM or parse issue.
- Keep score separate pre/post profit-protect patch.

### IWM / Alpaca Options Bot

Status:
Good behavior today. No open option positions after monitor.

Key closes:

- IWM put spread closed at `+55.8% of credit`, profit target hit.
- TSLA put spread closed at `+47.7% of credit`, near-target protection after 12:00 ET.

Logs:

```text
Put Spread [IWM] -> profit target hit: +55.8% of credit
Put Spread [TSLA] -> near-target protection: +47.7% of credit >= 45% after 12:00 ET
No open option positions remain; marked tracked groups closed
```

Current evaluation:

- Spread lifecycle handling worked.
- Profit taking worked.
- Duplicate exposure protection worked.
- Some scans skipped correctly due to below-20SMA or credit/risk below minimum.

Watch next:

- VIX/VXV term ratio had a Yahoo/VXV data failure:
  `$^VXV: possibly delisted; no price data found`
- Bot skipped term filter when VXV failed. This is acceptable fallback but should be watched.
- IVR scanner was unavailable for some symbols and fell back to HV proxy. Not urgent, but keep checking IVR logs.

### Portfolio / Guard Stack

Execution gate audit:

```text
passed=True
registered_signal_count=54
issue_count=0
warning_count=1
```

Only warning:
`scripts/portfolio_concentration_monitor.py` imports/uses Alpaca trading client for read-only account/position reads.

Current evaluation:

- Guard stack is working.
- Blocks are doing their job.
- No accidental execution introduced by new probe.

### Account / Exposure

From latest bot status snapshot:

```text
equity: $89,601.06
day_change: +$210.66
buying_power: $355,584.24
portfolio_concentration risk_level: normal
position_count: 1
gross_pct_equity: 0.781%
status: normal
```

Open trades:

```text
flip open: 0
iwm_options open: 0
```

Note:
Snapshot health was `stale` because many read-only/shadow signals had not refreshed at that timestamp. That is not an execution blocker by itself.

## Shadow / Read-Only System Evaluation

Latest signal stack grades:

- Ops grades: `A=27`, `B=5`
- Evidence grades: `D=6`, `F=26`
- Maturity: most are `log_building`
- Promotion-ready: `0`

Interpretation:

- Operational plumbing is strong.
- Evidence is still young.
- No shadow scanner should become an execution gate yet.

Top evidence/readiness from latest reports:

- Market Force Score: best current evidence score, still context-only.
- Closed Trade Postmortem: useful review layer, still sample-building.
- Rejected Trade Intelligence: useful review layer, still sample-building.
- Needs Review Queue: useful governance layer.
- IWM Options Bot: execution-capable, but still needs normalized forward sample.

Shadow strategies:

- QQQ/GLD Rotation: shadow-only, current IAF probe matched latest shadow signal.
- RSI-2 QQQ: shadow-only, not enough samples.
- KAMA QQQ: shadow-only, not enough samples.
- Williams %R: shadow-only, not enough samples.
- Momentum Rotation: shadow-only, not enough samples.
- TTM/WaveTrend/SMC: shadow-only, very early logs.

## Research / Repo Evaluation Today

### FinceptTerminal

Repo:
`https://github.com/Fincept-Corporation/FinceptTerminal`

Verdict:
Do not integrate or copy.

Reason:
License/commercial-use posture is too restrictive for us. Useful only as reference/idea inspiration.

Ideas worth borrowing conceptually:

- terminal-style dashboard
- workflow automation
- multi-agent research views
- portfolio/risk analytics
- connector catalog

### coding-kitties/investing-algorithm-framework

Repo:
`https://github.com/coding-kitties/investing-algorithm-framework`

Verdict:
Use as sandbox/reporting pattern.

Why:
Apache-2.0 and directly aligned with our need for vectorized backtest -> event validation -> ranked metrics.

Implemented first probe:
QQQ/GLD rotation, read-only, shadow comparison matched.

## Important Commands for Claude

Run focused tests:

```powershell
cd "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
uv run --no-project pytest -q agent\tests\test_flip_bot_safety.py agent\tests\test_iaf_qqq_gld_probe.py
```

Run safety audit:

```powershell
uv run --no-project python scripts\execution_gate_audit.py --print --fail-on-issues
```

Run current bot status:

```powershell
uv run --no-project --with alpaca-py --with python-dotenv python scripts\bot_status_snapshot.py --print
```

Run IAF probe:

```powershell
uv run --no-project --with alpaca-py --with yfinance --with pandas python scripts\iaf_qqq_gld_probe.py --print
```

Inspect today logs:

```powershell
Get-Content C:\Users\kenne\.vibe-trading\logs\flip-bot.log -Tail 160
Get-Content C:\Users\kenne\.vibe-trading\logs\options-bot.log -Tail 160
Get-Content C:\Users\kenne\.vibe-trading\flip-trades.json
Get-Content C:\Users\kenne\.vibe-trading\options-trades.json
```

## Next Best Tasks

P0:

1. Commit/review Codex changes if clean:
   - `strategies/flip_bot.py`
   - `agent/tests/test_flip_bot_safety.py`
   - `scripts/iaf_qqq_gld_probe.py`
   - `agent/tests/test_iaf_qqq_gld_probe.py`
   - `tools/investing_algorithm_framework_probe/README.md`

2. Run bot status after market close and verify no stale/health surprises.

P1:

1. Add a 10-date replay comparison for `iaf_qqq_gld_probe.py`.
   - Requirement: IAF probe must match existing QQQ/GLD shadow logic on at least 10 historical dates before expanding.

2. Add `iaf_qqq_gld_probe.py` to signal registry only as a `sandbox_probe` / `read_only` item if desired.

3. Start post-patch Flip Bot evaluation window.
   - Separate old Flip Bot results from new profit-protected results.
   - Old leaderboard P&L is polluted by prior logic and should not be used alone to judge the new monitor behavior.

P2:

1. Investigate VXV source reliability.
   - Yahoo `^VXV` failed today.
   - Better source may be CBOE/VIX3M history already used elsewhere.

2. Tighten IVR scanner availability so IWM Options Bot uses true IVR more often and HV proxy less often.

## Do Not Do

- Do not wire the IAF probe to execution.
- Do not promote any shadow scanner to a gate yet.
- Do not use Threads/X screenshots as proof.
- Do not loosen risk controls because today was green.
- Do not judge Flip Bot solely by old aggregate leaderboard P&L; mark July 1 profit-protect as a behavior boundary.

## Current Bottom Line

The system behaved better today than before:

- profitable spreads were closed,
- fading Flip Bot winner was protected,
- no open bot trades remain,
- account was green on the day,
- execution audit is clean,
- the new backtest/probe path matched existing QQQ/GLD shadow logic.

The stack is still in evidence-building mode. Best move is to keep collecting forward data and only improve observability/validation until a signal earns promotion.
