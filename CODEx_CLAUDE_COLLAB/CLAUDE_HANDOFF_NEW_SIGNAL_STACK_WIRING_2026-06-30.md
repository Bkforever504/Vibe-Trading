# Claude Handoff - New Signal Stack Wiring

Date: 2026-06-30
Repo: `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading`

## User Request

Kenny handed Codex your queue for the five new signal tools:

- TTM Squeeze shadow logger
- WaveTrend shadow logger
- GEX scanner
- IVR scanner
- SMC shadow logger

## Codex Completed

### P0 - Task Scheduler

Created and verified Ready:

- `\VibeTrade\TTMSqueezeShadowLogger` - weekdays 15:20 local
- `\VibeTrade\WaveTrendShadowLogger` - weekdays 15:20 local
- `\VibeTrade\SMCShadowLogger` - weekdays 15:20 local
- `\VibeTrade\GEXScanner` - weekdays 08:35 local
- `\VibeTrade\IVRScanner` - weekdays 08:35 local

Note: local machine timezone is CT. 08:35 local corresponds to 09:35 ET.

### Runner Fix

The new PS1 runners originally used `uv run` inside the project. That fails because the project dependency graph includes `smartmoneyconcepts`, which pulls `zigzag==0.3.2` with invalid metadata under uv.

Updated new runners to use isolated mode:

- `uv run --no-project --with alpaca-py --with pandas --with numpy ...`
- GEX/IVR use `uv run --no-project --with alpaca-py ...`

This matches the mature existing runner pattern and prevents Task Scheduler startup failure.

### P1 - smartmoneyconcepts

Attempted:

`uv add smartmoneyconcepts`

Result: failed due `zigzag==0.3.2` invalid package metadata:

`project.name must be present and non-empty` and invalid `Cython>=^0.29`.

Decision: do not force broken dependency into main env.

Implemented fallback in `scripts/smc_shadow_logger.py`:

- If `smartmoneyconcepts` imports, use package path.
- If unavailable, compute a simple built-in SMC approximation:
  - basic FVG detection
  - simple bullish/bearish BOS
  - simple recent order-block proxy
  - logs `engine: basic_fallback`

### P2 - TTM Squeeze Context in Flip Bot

Updated `strategies/flip_bot.py`:

- Added `_ttm_squeeze_context(hist)`.
- `find_bull_trend_day()` now computes/logs TTM state after breadth passes.
- Candidate dict gets:
  - `ttm_squeeze`
  - catalyst suffix `TTM=<state>`

Important: this does not block trades yet. It is logging-only for the 30-day review.

### P3 - Alpaca IVR in IWM Bot

Updated `strategies/iwm_options_bot.py`:

- Old `iv_rank()` renamed to `_hv_proxy_iv_rank()`.
- New `iv_rank()` tries `scripts.ivr_scanner.scan_symbol(symbol)` first.
- If Alpaca IVR is available, logs/returns true IVR.
- If IVR is accumulating/unavailable, falls back to HV proxy.

Existing `IV_RANK_MIN` gate remains in force. The journal field `iv_rank_at_entry` now receives Alpaca IVR when available.

### P4 - Tests

Added `agent/tests/test_new_shadow_loggers.py`:

- TTM Squeeze math/signal shape
- WaveTrend math/signal shape
- shadow alerts detect `primary` / `comparison` entry actions
- SMC fallback runs without external package

Also fixed `scripts/shadow_alerts.py` so new logger schema can alert:

- old supported keys: `primary_setup`, `comparison_setup`
- new supported keys: `primary`, `comparison`
- now alerts on `enter_long` and `enter_short`

## Verification

Tasks queried Ready:

- TTM Squeeze: Ready
- WaveTrend: Ready
- SMC: Ready
- GEX: Ready
- IVR: Ready

Tests:

`uv run --no-project --with pytest --with pandas --with numpy --with requests --with python-dotenv --with yfinance --with alpaca-py python -m pytest agent\tests\test_new_shadow_loggers.py test_flip_bot_execution_guard.py test_iwm_options_execution_guard.py -q`

Result: `8 passed`

Compile:

`uv run --no-project --with pandas --with numpy --with requests --with python-dotenv --with yfinance --with alpaca-py python -m py_compile ...`

Result: pass.

## Caveat

`strategies/flip_bot.py` had large pre-existing uncommitted changes from Claude before Codex touched it. Codex did not commit this blended diff. Review before committing.

`uv.lock` is untracked from prior repo state and was not intentionally modified by this task.

