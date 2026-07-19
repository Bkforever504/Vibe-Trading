# Codex Handoff — Edge Build 2026-06-27

**From:** Claude  
**To:** Codex  
**Priority:** Work items in order — P0 first.

---

## What Claude shipped this session (do NOT re-implement)

| Item | Files | Status |
|---|---|---|
| IWM stop loss fix (cost-basis fallback) | `strategies/iwm_options_bot.py:1097-1115` | ✅ done, 3 tests pass |
| Portfolio kill switch | `strategies/portfolio_guard.py` (new) | ✅ done |
| Portfolio monitor script | `strategies/portfolio_monitor.py` (new) | ✅ done |
| Portfolio kill wired into Alpaca guard | `strategies/execution_guard.py` | ✅ done |
| Portfolio kill wired into Kalshi guard | `Kalshi-Weather-Bot/prediction_market_guard.py` | ✅ done |
| VIX/VXV term structure gate in IWM | `strategies/iwm_options_bot.py:332-376` | ✅ done |
| Trade journal fields (VIX, IVR, term ratio) | IC + PS `trade_meta` dicts | ✅ done |

---

## P0 — Bear Trend Spread Close Path Verification

**Context:** `bear_trend_spread` strategy was built for Flip Bot. It places a debit put spread (buy ATM put, sell lower put). The monitor/close logic must route through `_close_spread()` and `_spread_mid()` — not the single-leg close path.

**Task:** End-to-end verification in paper. Do NOT place live orders.

**Files:** `strategies/flip_bot.py`

**Steps:**
1. Find `bear_trend_spread` in the strategy dispatcher in `run_entry()` or equivalent.
2. Confirm that when `strategy == "bear_trend_spread"`, the monitor loop calls `_close_spread(trade)` (not `trade_client.close_position(symbol)`).
3. If it falls through to single-leg close, that means both legs get closed via market orders independently — dangerous, leaves naked leg exposure briefly.
4. Write a test that mocks a `bear_trend_spread` open trade and verifies `_close_spread` is called (not individual position closes).
5. If the routing is broken, fix it to mirror how `_close_spread` works for existing spread strategies.

---

## P1 — Task Scheduler: portfolio_monitor.py (every 15 min)

**Context:** `strategies/portfolio_monitor.py` was just created. It polls Alpaca equity and triggers the portfolio kill switch if daily loss exceeds `PORTFOLIO_MAX_DAILY_LOSS_DOLLARS` (default $50).

**Task:** Create a Windows Task Scheduler task that runs this script every 15 minutes Mon-Fri 9:30-16:15 ET.

**Command pattern** (same as existing bot tasks):
```
Program: C:\Users\kenne\AppData\Local\Programs\Python\Python312\python.exe
Arguments: C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading\strategies\portfolio_monitor.py
Start in: C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading
```

**Schedule:** Every 15 minutes, Mon-Fri, starting 9:30 ET, ending 16:15 ET.

**Env:** Uses the same `agent/.env` file as other bots. Confirm `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`, `PORTFOLIO_MAX_DAILY_LOSS_DOLLARS` are set.

**Test it first:** Run manually from CLI, verify it prints portfolio P&L without error.

---

## P2 — NWS Ensemble Divergence Signal for Kalshi Weather Bot

**Context:** Kalshi weather markets (e.g., `KXHIGHNY-26JUN27-T95`) price a binary outcome. NWS publishes ensemble forecast probabilities from multiple models (GFS, NAM, GEFS). When models disagree heavily, Kalshi prices the consensus but the spread between models represents unpriced uncertainty — that's edge.

**Task:** Add an NWS ensemble spread signal to `kalshi_weather_bot.py`.

**Implementation plan:**

1. **Fetch NWS point forecast** for relevant weather station.  
   Endpoint: `https://api.weather.gov/gridpoints/{office}/{gridX},{gridY}/forecast`  
   No API key required. Returns hourly temperature forecasts with confidence intervals.

2. **Fetch probabilistic forecast (NDFD)**:  
   `https://forecast.weather.gov/MapClick.php?CityName=...&unit=0&lg=en&FcstType=digital`  
   Or use the NWS API hourly endpoint which includes `temperatureUnit` and confidence bands.

3. **Compute model spread**:
   ```python
   def nws_ensemble_spread(lat: float, lon: float) -> dict:
       """Return dict with consensus_high_f, spread_f, confidence."""
       # Call NWS gridpoints API
       # Parse temperature max from periods
       # spread = difference between high and low of probabilistic band
       # confidence = 1.0 - (spread / consensus_high_f)
   ```

4. **Signal gate**: Only enter a Kalshi high-temp market if:
   - NWS consensus within 2°F of market strike
   - Model spread < 5°F (models agree)
   - Kalshi price diverges > 8% from NWS implied probability

5. **Wire into bot**: Call before `evaluate_kalshi_order()`. If spread > 5°F, skip — model uncertainty too high to have edge.

**Files to modify:** `Kalshi-Weather-Bot/kalshi_weather_bot.py`  
**New file:** `Kalshi-Weather-Bot/nws_ensemble.py`

---

## P2 — GEX Pin Level Gate for Flip Bot

**Context:** Gamma exposure (GEX) creates gravitational pull toward high open-interest strikes on 0DTE expiration days. When SPY is between two massive OI strikes, it tends to pin rather than trend — Flip Bot's directional bets (bull_trend, bear_trend) lose edge in pinning regimes.

**Task:** Add daily GEX pin level awareness to Flip Bot's entry filter.

**Data source:** CBOE publishes options open interest free at  
`https://www.cboe.com/delayed_quotes/spy/quote_table`  
Or use the yfinance options chain: `yf.Ticker("SPY").option_chain(expiry)` — returns `calls` and `puts` DataFrames with `openInterest` and `strike`.

**Implementation plan:**

1. **Fetch SPY 0DTE OI** (calls + puts at today's expiry):
   ```python
   def spy_gex_pin_levels(top_n: int = 3) -> list[float]:
       """Return top N strikes by open interest for today's SPY expiry."""
       import yfinance as yf
       from datetime import date
       today_str = date.today().strftime("%Y-%m-%d")
       chain = yf.Ticker("SPY").option_chain(today_str)
       combined = pd.concat([chain.calls, chain.puts])
       top = combined.nlargest(top_n * 2, "openInterest")
       return sorted(top["strike"].unique().tolist())[:top_n]
   ```

2. **Pin zone check**: If SPY spot price is within $1.50 of a top-3 OI strike, flag as "GEX pin zone".

3. **Gate in Flip Bot entry**: If `gex_pin_zone == True`, skip `bull_trend` and `bear_trend`. Still allow `bull_trend_spread` and `bear_trend_spread` (defined risk limits exposure in pinning regimes).

4. **Log pin levels daily**: `log.info(f"GEX pin levels: {pin_levels} | spot={spot:.2f} | pin_zone={pin_zone}")`

**Files to modify:** `strategies/flip_bot.py`  
**New function:** `spy_gex_pin_levels()` at top of file or in a new `strategies/gex.py`

---

## System State After This Session

```
~/.vibe-trading/
  MANUAL_RESET_REQUIRED.json        ← per-bot Alpaca kill (manual delete to reset)
  KALSHI_MANUAL_RESET_REQUIRED.json ← per-bot Kalshi kill (manual delete to reset)
  PORTFOLIO_KILL_SWITCH.json        ← NEW: portfolio-wide kill (all bots stop)
  guard-blocks.jsonl                ← Alpaca blocked orders log
  kalshi-guard-blocks.jsonl         ← Kalshi blocked orders log
  options-trades.json               ← IWM trade state
  logs/
    options-bot.log
```

**Kill switch hierarchy (ordered):**
1. `PORTFOLIO_KILL_SWITCH.json` → ALL bots halt (checked first in both guards)
2. `MANUAL_RESET_REQUIRED.json` → Alpaca bots halt
3. `KALSHI_MANUAL_RESET_REQUIRED.json` → Kalshi bot halts

**Paper trading:** all bots paper only. Live execution hard-blocked unless `OPTIONS_LIVE_EXECUTION_ENABLED=true` + `KALSHI_LIVE_EXECUTION_ENABLED=true` set explicitly.

**Tests passing:**
- `test_iwm_options_execution_guard.py` — 3/3
- `test_prediction_market_guard.py` — 8/8
- `test_bull_trend_spread.py` — 8/8 (prior session)
- `agent/tests/` — existing suite

---

## Key Reminder

Do not enable live execution. Kenny reviews paper results for 30 days before going live.  
The portfolio kill switch fires at -$50/day by default (`PORTFOLIO_MAX_DAILY_LOSS_DOLLARS`).  
Kenny can adjust in `agent/.env`.
