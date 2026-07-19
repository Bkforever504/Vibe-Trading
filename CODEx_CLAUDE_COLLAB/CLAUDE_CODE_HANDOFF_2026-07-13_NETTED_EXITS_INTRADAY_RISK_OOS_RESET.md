# Claude Code Handoff: Netted Exits, Intraday Risk, OOS Promotion, Kill Reset

Date: 2026-07-13 (America/Chicago; runtime artifacts after 00:00 UTC show 2026-07-14)

## Workspace

- Repository: `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading`
- Runtime state/reports: `C:\Users\kenne\.vibe-trading`
- Bot code: `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading\strategies`
- Operational/report scripts: `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading\scripts`
- Tests: `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading\agent\tests`
- This worktree is heavily dirty with prior user/agent work. Preserve all unrelated changes. Do not reset, clean, or broadly reformat.

## User Goal

Complete the highest-priority upgrades from the July 13 evaluation:

1. Restore automated monitoring/exits for option groups with broker-netted overlapping legs.
2. Refresh geopolitical/breaking-news risk intraday before consensus decisions.
3. Prevent unproven shadow logic from causing automated exits.
4. Audit and safely administer the stale July 7 paper portfolio kill switch.
5. Preserve the July 14 CPI stand-aside/confirmation policy.

No order was submitted during this work.

## Completed Changes

### 1. Quote-based group marking and safe MLEG exits

Files:

- `strategies/options_state.py`
- `strategies/iwm_options_bot.py`
- `agent/tests/test_options_state_integrity.py`
- `agent/tests/test_iwm_options_confidence_gate.py`
- `test_iwm_options_execution_guard.py`

`quote_mark()` values every leg from current bid/ask quotes and fails closed if any leg is absent or malformed. It calculates midpoint monitoring value, natural liquidation debit, per-group dollar/PCT P&L, and reversed close sides without relying on broker per-symbol positions.

For a netted group, `iwm_options_bot` now closes the whole spread as one reversed `MLEG` limit order with `position_intent: close` on every leg. It refuses unsafe per-symbol close fallback when a leg is known netted. Risk-reducing close orders may bypass a manual entry halt, while all entries remain guarded. New MLEG entries include `position_intent: open`.

Read-only post-close monitor result:

- Group `1733badd-f177-4b51-92fb-14e759280934`: quote status `ok`, group P&L `+$34`, natural close debit `$0.51`.
- Group `d72ded80-b97f-4fb4-a6a7-d3c0d77ddc51`: quote status `ok`, group P&L `+$47`, natural close debit `$0.47`.
- Both include netted leg `IWM260807P00277000`.
- No target/stop fired after close; no closing order was sent.

Broker/state reconciliation remains intentionally `review_required` because both active groups own P277 on opposite sides. The signed expected book equals the broker book exactly and `unexplained_residual={}`. New entries remain blocked by reconciliation until duplicate active ownership is gone.

Official contract references used:

- https://docs.alpaca.markets/us/v1.4.2/reference/optionlatestquotes
- https://docs.alpaca.markets/us/docs/options-trading-overview

Claude review request: verify the MLEG close payload, net-debit price semantics, all-leg `position_intent`, partial/rejected fill handling, and state transition idempotence. Do not replace grouped closure with per-symbol closes.

### 2. Intraday geopolitical/news-risk refresh

Files:

- `scripts/geopolitical_risk_context.py`
- `scripts/intraday_risk_refresh.py`
- `scripts/run_intraday_risk_refresh.ps1`
- `scripts/register_intraday_risk_refresh_task.ps1`
- `scripts/market_catalyst_calendar.py`
- `scripts/market_schedule_alignment.py`
- `scripts/signal_stack_health_report.py`
- `agent/tests/test_geopolitical_risk_context.py`
- `agent/tests/test_market_catalyst_calendar.py`

The new veto-only classifier reads the latest four hours of Alpaca news and current StockTwits context. Only explicit geopolitical/energy evidence can raise medium/high risk. Missing data cannot approve a trade or loosen a gate.

Refresh dependency order:

1. geopolitical risk
2. market catalyst calendar
3. market force
4. adaptive options playbook
5. shadow consensus
6. daily edge orchestrator

Scheduled task:

- Task: `\VibeTrade\IntradayRiskRefresh`
- Next run verified: `2026-07-14 08:24 CT`
- Daily, every 15 minutes for 7 hours 15 minutes
- Action: `powershell.exe -NoProfile -NonInteractive -File "...\scripts\run_intraday_risk_refresh.ps1"`

Current live read-only classification is `high`, with two explicit Iran/Hormuz strike/capability headlines. The catalyst report therefore permits only `stand_aside` today and emits:

- `dynamic_geopolitical_risk`
- `new_short_premium_blocked`
- `size_down_required`

Claude review request: audit false-positive resistance, source freshness, scheduler XML/repetition settings, and failure propagation. Keep this veto-only; never turn news classification into a directional entry signal.

### 3. Shadow exits require chronological out-of-sample evidence

Files:

- `scripts/flip_shadow_pnl_evaluator.py`
- `scripts/shadow_consensus_gate.py`
- `strategies/shadow_consensus.py`
- `agent/tests/test_flip_shadow_pnl_evaluator.py`
- `agent/tests/test_shadow_consensus_advisor.py`
- `agent/tests/test_shadow_consensus_exit_advice.py`

Per-symbol evaluation now reserves the newest 20% of chronologically sorted completed trades, with at least five holdout samples. Promotion requires:

- at least 10 completed lifecycles
- at least 30 trading days
- positive full-history expectancy
- positive chronological holdout expectancy
- controlled average loss

Consensus emits `shadow_exit_control_eligible` plus holdout sample/expectancy evidence. If an unpromoted signal recommends an exit, `exit_advice()` remains `hold`, sets `review_recommended=true`, and adds `shadow_exit_not_oos_ready`. Only a promoted symbol with positive holdout expectancy can return `review_exit` for the bot's defensive-exit path.

Current runtime: zero symbols are shadow-exit eligible. All nine consensus symbols are stand-aside; zero are approved.

Also repaired report compatibility by emitting both `kill_switch` and `portfolio_kill_switch`, because the consumer reads the latter.

Claude review request: challenge the holdout methodology for leakage, symbol sample independence, regime dependence, and minimum sample sufficiency. Do not grant automated exit authority without positive forward/OOS evidence and human promotion.

### 4. Audited paper kill-switch reset

Files:

- `scripts/review_portfolio_kill_switch.py`
- `agent/tests/test_review_portfolio_kill_switch.py`

The script is read-only by default. Approved reset requires all of these:

- `ALPACA_PAPER=true`
- active kill record exists
- current concentration report
- concentration risk `normal`
- current day loss above the hard-loss boundary
- signed option book has zero unexplained residual
- zero error/missing/stale signal processes
- execution-gate audit passed with zero issues
- CPI stand-aside guard present
- explicit `--approve-reset`, approver, and reason

All nine checks passed. The July 7 kill file was atomically archived, not deleted:

`C:\Users\kenne\.vibe-trading\archive\PORTFOLIO_KILL_SWITCH.reset-20260714T002053Z.json`

Audit report:

`C:\Users\kenne\.vibe-trading\reports\portfolio-kill-switch-review.json`

Post-reset proof:

- Original kill path absent.
- Archive present with original trigger at `2026-07-07T15:05:16Z`, reason `max_daily_loss`, daily P&L `-$960`.
- Current paper equity `$90,096.13`; day change `-$32`; hard threshold `-$750`.
- Concentration `normal`, gross market value `$964` / `1.07%` equity.
- Signal health `45 ok, 0 stale, 0 missing, 0 error`.
- Execution audit `passed=true`, 87 registered signals, zero issues.
- Reconciliation signed book balanced; only known P277 overlap remains.

The reset does not submit orders or loosen entry gates. Current geopolitical and catalyst gates independently keep entries closed.

### 5. CPI policy

The July 14 calendar has CPI at 08:30 ET. Allowed playbooks are only:

- `stand_aside`
- `directional_long_post_confirmation`

`new_short_premium_blocked` and `size_down_required` remain active. The Flip entry schedule is after the release, but the bot must still wait for post-release confirmation. Current high geopolitical risk can independently force full stand-aside.

## Verification

Focused safety suite:

```powershell
python -m pytest agent\tests\test_options_state_integrity.py agent\tests\test_iwm_options_confidence_gate.py agent\tests\test_flip_bot_safety.py agent\tests\test_flip_shadow_pnl_evaluator.py agent\tests\test_shadow_consensus_exit_advice.py agent\tests\test_shadow_consensus_advisor.py agent\tests\test_shadow_consensus_gate.py agent\tests\test_geopolitical_risk_context.py agent\tests\test_market_catalyst_calendar.py agent\tests\test_review_portfolio_kill_switch.py -q
```

Result: `97 passed`.

Root IWM execution-guard regression suite:

```powershell
python -m pytest test_iwm_options_execution_guard.py -q
```

Result: `7 passed`.

Loader isolation check:

```powershell
python -m pytest agent\tests\test_futu_loader.py agent\tests\test_mootdx_loader.py -q
```

Result: `50 passed`.

Full suite:

```powershell
python -m pytest agent\tests -q
```

Result: `3625 passed, 4 skipped, 7 failed`. The seven failures are Futu/Mootdx mock-call assertions that pass 50/50 in isolation, proving full-suite import/module-state contamination rather than a bot behavior failure. This remains a test-isolation cleanup item; do not hide it.

Additional successful checks:

```powershell
python scripts\portfolio_concentration_monitor.py --print
python scripts\options_position_reconciler.py --print
python scripts\execution_gate_audit.py --print --fail-on-issues
python scripts\signal_stack_health_report.py
python scripts\flip_shadow_pnl_evaluator.py --print
python scripts\intraday_risk_refresh.py
python strategies\iwm_options_bot.py --monitor-only
```

## Immediate Next Checks for Claude

1. Read the files above and review only; preserve the dirty worktree and all runtime state.
2. Re-run the 97-test safety command.
3. Run `python strategies\iwm_options_bot.py --monitor-only` during market hours and confirm both four-leg marks are complete and fresh.
4. Inspect a paper-only mocked/rejected/partial MLEG close lifecycle. Do not provoke a real order merely to test.
5. Diagnose the full-suite Futu/Mootdx import-state contamination without changing production loader behavior unless a real defect is proven.
6. Confirm `\VibeTrade\IntradayRiskRefresh` repeats every 15 minutes and that a failing upstream step prevents stale downstream consensus generation.
7. After CPI, verify confirmation criteria explicitly before allowing any directional long. Keep short premium blocked for the high-impact window and keep current geopolitical veto authoritative.

## Non-Negotiable Safety Boundaries

- Paper mode only. Do not enable live trading.
- Do not increase risk, daily-loss limits, contract caps, or position size.
- Do not bypass reconciliation, liquidity, catalyst, execution, or kill-switch guards.
- Do not promote shadow entries or exits from social popularity, screenshots, backtest-only results, or in-sample expectancy.
- Do not close overlapping option legs one symbol at a time.
- Do not reset or clean the dirty worktree.
