# Claude Handoff — Shared Auto-Execution Guard

Project folder:
`C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading`

Date:
2026-06-27

## User Goal

Kenny wants the bots to execute automatically, but only through hard-coded risk gates. The intent is not "AI can buy anything"; the intent is:

1. Signal engine finds trade.
2. Confidence score passes.
3. Risk engine approves.
4. Execution helper submits.
5. Monitor manages exits.

Live money remains locked until paper results justify it.

## What Codex Implemented

### New shared guard

Added:

`strategies/execution_guard.py`

Primary API:

```python
evaluate_execution(...)
```

Blocks orders when:

- manual reset file exists
- live trading is attempted without explicit live unlock
- confidence is below minimum
- contract count is invalid or above cap
- estimated notional/risk exceeds max notional
- spread is wider than configured limit
- duplicate symbol exposure exists
- daily loss percentage breaches limit, writing the manual-reset block file

Default config:

```python
ExecutionGuardConfig(
    min_confidence=8.5,
    max_daily_loss_pct=0.03,
    max_spread_cents=None,
)
```

### Flip Bot wiring

Updated:

`strategies/flip_bot.py`

`run_entry()` now calls `evaluate_execution()` before `_submit()` or `_submit_spread()`.

New live unlock:

```text
FLIP_LIVE_EXECUTION_ENABLED=true
```

If `ALPACA_PAPER=false` but this is not set, opening orders are blocked with:

```text
live_execution_not_enabled
```

Paper orders are allowed if all gates pass.

### IWM / Options Bot wiring

Updated:

`strategies/iwm_options_bot.py`

New env/config:

```text
OPTIONS_LIVE_EXECUTION_ENABLED=true
MAX_CONTRACTS_PER_ORDER=5
```

`_place_mleg()` now calls `_guard_submission()` before Alpaca submit.

`_place_single_leg()` now also calls `_guard_submission()`, and wheel CSP / covered-call call sites pass `trade_meta` with confidence and risk fields.

This prevents wheel trades from becoming an unguarded back door.

## Current Env State Kenny Asked For

Redacted/non-secret flag check from `agent/.env`:

```text
ALPACA_PAPER=true
FLIP_LIVE_EXECUTION_ENABLED=<unset>
OPTIONS_LIVE_EXECUTION_ENABLED=<unset>
CONFIRM_LIVE_TRADING=<unset>
REQUIRE_MANUAL_APPROVAL=false
MAX_ACCOUNT_RISK_PCT=0.02
MAX_DAILY_LOSS_PCT=0.03
MIN_CANDIDATE_CONFIDENCE=8
```

Interpretation:

- Alpaca paper execution can run automatically.
- Real-money execution is still hard-blocked.
- Do not set `FLIP_LIVE_EXECUTION_ENABLED=true` or `OPTIONS_LIVE_EXECUTION_ENABLED=true` until Kenny explicitly decides to go live after forward validation.

## Tests Added

Added:

- `test_execution_guard.py`
- `test_flip_bot_execution_guard.py`
- `test_iwm_options_execution_guard.py`

Verification command:

```powershell
uv run --no-project --with pytest --with yfinance --with numpy --with pandas --with python-dotenv --with requests --with alpaca-py python -m pytest test_execution_guard.py test_flip_bot_execution_guard.py test_iwm_options_execution_guard.py -q
```

Latest result:

```text
6 passed, 1 warning
```

The warning is from `websockets.legacy` via dependency code, not from this change.

## Important Notes For Claude

1. Do not enable live trading.
2. Keep `ALPACA_PAPER=true` unless Kenny explicitly says otherwise.
3. Do not remove `REQUIRE_MANUAL_APPROVAL=false` for paper; Kenny wants paper auto-execution now.
4. If changing guard behavior, write failing tests first.
5. Current options bot has its own `_candidate_confidence_ok()` threshold of `MIN_CANDIDATE_CONFIDENCE=8`; the new shared guard default is stricter at `8.5`. That means options candidates scoring exactly 8 may pass the local candidate gate but still be blocked at submit. This is intentional for now.
6. The repo has many untracked files from previous sessions. Do not clean, reset, or delete unrelated work.

## Suggested Next Claude Tasks

1. Run a manual paper-only Flip Bot entry check during market hours:

```powershell
python strategies\flip_bot.py --entry
```

Expected:

- fetches live equity
- scans signals
- paper-submits only if guard allows
- logs `EXECUTION BLOCKED` with reason if blocked

2. Add dashboard/report section for execution guard blocks:

- reason
- bot
- symbol
- confidence
- notional/risk
- daily loss pct
- manual reset status

3. Consider changing Flip Bot trend-day confidence threshold from 8 to 8.5+ or normalizing all scores to floats so local signal threshold and execution threshold match.

4. Add a guard check for current open Alpaca positions, not just local state, before duplicate exposure. Local JSON can drift; broker truth should win.

5. Add spread/liquidity fields to Flip Bot setups so `ExecutionGuardConfig(max_spread_cents=...)` can be used there too.

## Safety Bottom Line

The bots are now allowed to execute automatically in Alpaca paper mode only.

Live execution remains blocked unless both conditions are true:

- `ALPACA_PAPER=false`
- the bot-specific live unlock env var is set:
  - `FLIP_LIVE_EXECUTION_ENABLED=true`
  - or `OPTIONS_LIVE_EXECUTION_ENABLED=true`

Do not change those live unlocks without explicit Kenny approval.

