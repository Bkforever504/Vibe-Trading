# Claude Handoff - Alpaca Market Data Swap

Date: 2026-06-28
Project: `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading`

## What Claude Just Built

Replaced yfinance with Alpaca market data API across all 5 shadow loggers.
yfinance is an unofficial Yahoo scraper — it breaks silently when Yahoo changes
their undocumented API. Alpaca is our actual broker with a real API and SLA.
Keys were already in `agent/.env`.

## Files Changed

### New file

`scripts/market_data.py`

Shared market data fetcher for all operational scripts.

- Primary: Alpaca `StockHistoricalDataClient`, `adjustment="all"` (split + dividend adjusted)
- Fallback: yfinance (if Alpaca keys not configured — for research/backtest scripts that run standalone)
- Keys loaded from `agent/.env` (ALPACA_API_KEY, ALPACA_SECRET_KEY) or environment variables
- `fetch_ohlcv(symbol, lookback_days)` → DataFrame with open/high/low/close/volume
- `fetch_close(symbols, lookback_days)` → DataFrame with one column per symbol (close only)
- `data_source()` → "alpaca" or "yfinance" (useful for logging)

### Modified shadow loggers

Each logger had its inline yfinance `fetch_ohlcv` / `fetch_close` function replaced with
an import from `scripts.market_data`.

| File | Change |
|------|--------|
| `scripts/rsi2_shadow_logger.py` | Removed `fetch_ohlcv`, imports `fetch_ohlcv` from market_data |
| `scripts/kama_shadow_logger.py` | Removed `fetch_ohlcv`, imports `fetch_ohlcv` from market_data |
| `scripts/williams_r_shadow_logger.py` | Removed `fetch_ohlcv`, imports `fetch_ohlcv` from market_data |
| `scripts/qqq_gld_shadow_logger.py` | Replaced `fetch_close` body with thin wrapper calling market_data |
| `scripts/momentum_shadow_logger.py` | Removed `_fetch_close`, imports `fetch_close` from market_data |

### Modified PS1 runners

All 4 runners updated: `--with yfinance` → `--with alpaca-py`

- `scripts/run_rsi2_shadow_logger.ps1`
- `scripts/run_kama_shadow_logger.ps1`
- `scripts/run_williams_r_shadow_logger.ps1`
- `scripts/run_qqq_gld_shadow_logger.ps1`

Note: `momentum_shadow_logger.py` is run via a separate existing task — update that PS1 too if one exists.

## Verification

Alpaca fetch confirmed working:

```
Source: alpaca
Rows: 6
                       open     high     low   close      volume
timestamp
2026-06-24 04:00:00  715.37  719.930  704.45  710.62  52665626.0
2026-06-25 04:00:00  725.90  726.830  705.30  716.38  50327101.0
2026-06-26 04:00:00  707.13  715.555  702.81  706.52  47271660.0
```

Williams %R shadow logger end-to-end via Alpaca: clean run, correct output, logged correctly.

## What Codex Should Do

### P0 — Commit this

```
git add scripts/market_data.py scripts/rsi2_shadow_logger.py scripts/kama_shadow_logger.py \
        scripts/williams_r_shadow_logger.py scripts/qqq_gld_shadow_logger.py \
        scripts/momentum_shadow_logger.py \
        scripts/run_rsi2_shadow_logger.ps1 scripts/run_kama_shadow_logger.ps1 \
        scripts/run_williams_r_shadow_logger.ps1 scripts/run_qqq_gld_shadow_logger.ps1
git commit -m "Swap yfinance for Alpaca market data in all shadow loggers"
```

### P1 — Add tests for market_data.py

Write `agent/tests/test_market_data.py`. Key things to test:

1. `_load_env()` reads ALPACA_API_KEY and ALPACA_SECRET_KEY from agent/.env
2. `data_source()` returns "alpaca" when keys present, "yfinance" when not
3. `fetch_ohlcv()` and `fetch_close()` return DataFrames with correct columns
4. Multi-index handling: when Alpaca returns `(symbol, timestamp)` MultiIndex, it gets
   reduced to single timestamp index
5. Timezone stripping: `tz_localize(None)` applied so index has no tz info
6. Mock the Alpaca client — do not make real API calls in tests

### P2 — Check momentum PS1 runner

Verify `scripts/run_momentum_shadow_logger.ps1` exists. If it does, update
`--with yfinance` → `--with alpaca-py` there too.

### P3 — Add `data_source` to shadow log entries

Each shadow logger logs a JSON entry. Add `"data_source": data_source()` to the
entry dict so we know whether a given log row came from Alpaca or yfinance.
Useful for debugging discrepancies if the source ever switches mid-window.

## Important: Do NOT change research/backtest scripts

The files in `research/pine_strategy_lab/examples/` still use yfinance directly.
That is intentional — backtest scripts are standalone research tools, not operational code.
Only the shadow loggers (operational, scheduled) should use Alpaca.

## Alpaca Timestamp Note

Alpaca daily bars have timestamps like `2026-06-26 04:00:00` (UTC midnight ET).
After `tz_localize(None)` these are timezone-naive. The `_last_date()` helper in each
logger uses `idx.date().isoformat()` which correctly returns `2026-06-26` from this timestamp.
No changes needed to downstream date handling.

## Current Shadow Logger Stack (all Ready)

| Logger | Symbol | Schedule | Data Source After This PR |
|--------|--------|----------|--------------------------|
| RSI-2 | QQQ | Daily 15:20 | Alpaca |
| KAMA | QQQ | Daily 15:20 | Alpaca |
| Williams %R | QQQ + SPY | Daily 15:20 | Alpaca |
| QQQ/GLD Rotation | QQQ + GLD | Mon 8:05 AM | Alpaca |
| Momentum Rotation | 10 assets | Mon (existing) | Alpaca |
