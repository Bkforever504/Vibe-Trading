# Edge Upgrades Handoff — 2026-06-25

## Context

Kenny's goal: make a living from trading bots. Research + implementation session
adding best-in-class edges to all three active bots and the copy trader system.
All code is paper-only. Do NOT enable live trading.

---

## What Claude Implemented This Session (do not redo)

### 1. flip_bot.py — ORB Signal + VIX Confirmation already wired
**File:** `strategies/flip_bot.py`

Added `_orb_signal(sym)` (5-min opening range, 9:30–9:35 ET):
- Returns `direction: "bear" | "bull" | "neutral"` + ORB high/low levels
- `find_0dte()` now triggers on ORB breakout in addition to catalyst/gap:
  - ORB bear break → buy PUT 0DTE
  - ORB bull break → buy CALL 0DTE
  - Monday ORB breaks tagged "MONDAY" (highest historical win rate)
- `find_bear_trend_day()` now logs ORB direction as additional context
- VIX term structure already wired from prior session (backwardation blocks bull entries)

Research basis: Monday 0DTE put win rate 42.19%, ORB confirmed 433% NQ return in 1yr study.

### 2. kalshi_weather_bot.py — GFS Ensemble + Edge Gate
**File:** `C:\Users\kenne\Desktop\MAILK-Repos\Kalshi-Weather-Bot\kalshi_weather_bot.py`

Added:
- `fetch_gfs_ensemble(lat, lon)` — free open-meteo ensemble API, 30 GFS members,
  computes daily max temp per member
  URL: `https://ensemble-api.open-meteo.com/v1/ensemble`
- `ensemble_probability_above(member_maxes, threshold)` — fraction of members ≥ threshold
- `EDGE_THRESHOLD = 0.08` — only trade when |ensemble_prob - market_prob| > 8%
- `log_prediction()` now stores `ensemble_prob` in accuracy_log.jsonl
- Live path: after getting orderbook `best_ask`, computes `market_prob = best_ask / 100`,
  compares to `ensemble_prob`, skips if edge below threshold
- Dry-run logs ensemble probability alongside XGBoost prediction

Research basis: Sharpe 4.9 documented on Kalshi weather markets using ensemble method.
Austin RMSE ~1.8°F (viable), NYC/CHI ~5-6°F (no edge — accuracy log gates go-live).

### 3. copy_trader_watchlist.py — Basket Consensus
**File:** `strategies/copy_trader_watchlist.py`

Added `build_basket_consensus(signals, profiles, min_consensus=0.80, min_traders=3)`:
- Groups signals by (symbol, side) across all `paper_watch`-status traders
- Only signals when ≥80% of active paper_watch traders agree on same market+side
- Returns: consensus_ratio, trader_count, avg_kelly, suggested_notional
- Wired into `build_report()` as `basket_consensus` + `basket_consensus_count`
- MAX_PRICE_DRIFT already at 0.05 (5%), Kelly sizing already implemented

Research basis: 12.7% of Polymarket users are profitable; basket approach filters down
to elite consensus trades, eliminates individual bias.

---

## Verification (run before starting Codex tasks)

```powershell
cd "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
uv run --no-project --with pytest --with yfinance --with requests --with python-dotenv python -m pytest agent/tests/test_flip_bear_trend.py agent/tests/test_trade_history_importer.py agent/tests/test_copy_trader_watchlist.py -v
```
Expected: **28 passed**

---

## P0 Codex Tasks (unchanged from prior handoff — still not done)

### P0-A — IWM options stop at -100% of credit
**File:** `strategies/iwm_options_bot.py`

Find the stop multiplier (likely `2.0` or `3.0`) and change to `1.0`.
Current behavior: IWM group closed at -211% of credit on June 25 (-$114 on $54 credit).
Standard: close when position costs 2x credit received = -100% of credit.

Search: `stop`, `max_loss`, `stop_loss_pct`, `trigger` in iwm_options_bot.py.

### P0-B — Wire bear_trend_spread two-leg execution in run_entry()
**File:** `strategies/flip_bot.py`

`_submit_spread()` and `_close_spread()` are already implemented but `run_entry()` and
`run_monitor()` already handle them (checking `is_spread = bool(setup.get("short_option_symbol"))`).

**Verify this actually works end-to-end:** add `test_flip_bot_spread_entry.py` that mocks
`_post` and confirms a spread setup routes through `_submit_spread()` not `_submit()`.

### P0-C — Polymarket public wallet tracker
**File to create:** `strategies/polymarket_wallet_tracker.py`

Public CLOB endpoints (no auth needed):
```
GET https://data-api.polymarket.com/activity?user=0x...&limit=500
GET https://clob.polymarket.com/trades?maker_address=0x...&limit=500
```

Build:
```python
def fetch_wallet_trades(address: str, limit: int = 500) -> list[dict]:
    """Fetch settled trades for a Polymarket wallet. No auth needed."""

def wallet_to_csv(address: str, out_path: Path) -> Path:
    """Fetch trades and write normalised CSV for trade_history_importer."""
```

Output CSV: `timestamp,market,outcome,shares,price,profit_loss,fee`
(matches Polymarket format in trade_history_importer's `_detect_format`)

---

## P1 Codex Tasks

### P1-A — Kalshi fills fetcher
**File to create:** `strategies/kalshi_history_fetcher.py`

```
GET https://trading-api.kalshi.com/trade-api/v2/portfolio/fills
```
Auth: copy `make_headers()` + `signed_headers()` pattern from kalshi_weather_bot.py.

### P1-B — MNQ scanner per-bar logging
**File:** `strategies/shadow_pullback_signal.py`

Log every bar's score (not just final skip). Add "trend mode" when SPY/IWM bear_trend
score ≥ 8: lower pullback requirement, allow entry on any VWAP touch.

### P1-C — Why-Rejected section in copy trader report
**File:** `strategies/copy_trader_watchlist.py`

Add `rejected_traders` list to `build_report()` output. Each entry: handle, platform,
flags, score, what_would_help. `_rejection_guidance(flags)` maps flag → action string:
- "sample too small" → "Need: 30+ trades minimum, 100+ preferred"
- "choppy pnl curve" → "Need: pnl_smoothness ≥ 0.70 (linear equity growth)"
- "unverified social data" → "Need: exported broker history or verified public wallet"

---

## Safety Rules (non-negotiable)

- PAPER_ONLY: `ALPACA_PAPER=true` must remain set
- No live trading without explicit Kenny approval
- No Polymarket wallet keys or order placement — read-only only
- No raising MAX_RISK_PCT above 0.02 (2%)
- IWM stop must be ≤ -100% of credit received
- RSA private key at `C:\Users\kenne\Desktop\MAILK-Repos\Kalshi-Weather-Bot\kalshi_private.pem` — do not expose in code or logs
- Kalshi live orders require BOTH `--live` flag AND `DRY_RUN=false` in .env
