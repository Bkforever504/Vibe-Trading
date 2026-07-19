---
name: vibe-trading-tests
description: Use when testing this repo, running focused suites, interpreting known full-suite failures, or avoiding uv/numpy AppLocker issues.
---

# Vibe-Trading Tests

## How to Run
```powershell
# Full suite (system Python — required for numpy)
python -m pytest agent/tests/ -q --tb=no

# Focused (faster, preferred for bot work)
python -m pytest agent/tests/test_flip_bot_safety.py -q
python -m pytest agent/tests/test_iwm_options_confidence_gate.py -q
python -m pytest agent/tests/test_options_liquidity_feasibility.py -q
python -m pytest agent/tests/test_generate_dashboard.py -q
```

## NEVER use uv for numpy/pandas tests
Windows Smart App Control (SAC/AppLocker) blocks numpy DLLs from uv's temp cache.
```powershell
# WRONG — SAC blocks numpy DLLs from uv temp cache
uv run --no-project --with numpy python -m pytest ...

# RIGHT — system Python has trusted numpy
python -m pytest agent/tests/ -q
```
System Python path: `C:\Users\kenne\AppData\Local\Programs\Python\Python312`

## Known Pre-Existing Failures (not our bugs)
These 7 tests fail in full-suite runs due to test-order pollution from shared module state. They pass in isolation. Ignore when reporting bot-scope test results:
- `test_futu_loader.py::TestFetch::test_futu_symbol_converted_correctly`
- `test_futu_loader.py::TestFetch::test_raises_on_connection_failure`
- `test_futu_loader.py::TestFetch::test_skips_symbol_on_non_ret_ok`
- `test_futu_loader.py::TestFetch::test_context_always_closed`
- `test_mootdx_loader.py::test_fetch_daily_uses_get_k_data`
- `test_mootdx_loader.py::test_fetch_intraday_uses_bars_and_clips_window`
- `test_mootdx_loader.py::test_fetch_skips_bj_symbols_with_warning`

These are Chinese market loaders unrelated to Vibe-Trading bots.

## Other Fixed Issues
- `test_oauth_token_cache.py` chmod tests: skip on Windows (`@pytest.mark.skipif(sys.platform == "win32", ...)`)
- `test_loader_retry_helpers.py`: must monkeypatch `USERPROFILE` (not just `HOME`) on Windows
- `factors/test_registry.py`: symlinks need junction on Windows (`mklink /J`)

## Target Count (2026-07-06)
~3466 passed, 7 pre-existing failures, 4 skipped. Any new test count below this needs investigation.

## Red Flags
- Using `uv run --with numpy` in any test invocation
- A test that patches live Alpaca trading endpoints
- A test file with no assertions (just calling `build_report()` and ignoring output)
