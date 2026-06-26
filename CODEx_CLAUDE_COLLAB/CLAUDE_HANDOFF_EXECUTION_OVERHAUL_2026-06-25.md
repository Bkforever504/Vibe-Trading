# Execution Overhaul Handoff — 2026-06-25

## Context

Kenny's goal: make a living from trading bots. Current system has good signal quality
but near-zero execution. June 25 was a perfect example: SPY/QQQ/IWM all scored 9/10
bear trend but the flip bot couldn't trade because account size was hardcoded to $5k
instead of the real $88k paper equity.

Paper account: Alpaca paper, equity ~$88,217.

**Everything stays paper-only unless Kenny explicitly says otherwise.**

---

## What Claude Already Fixed This Session (do not redo)

1. `strategies/flip_bot.py` — `resolve_account_size()` now fetches live Alpaca equity
   instead of defaulting to $200/$5k. Budget is now ~$1,764 (2% of $88k).
2. `strategies/flip_bot.py` — `_bear_put_spread()` + spread fallback in
   `find_bear_trend_day()`. When ATM put exceeds budget, tries 2/3/5/7/10pt wide
   bear put debit spread as fallback vehicle.
3. `strategies/trade_history_importer.py` — imports CSV/JSON trade exports, auto-derives
   all 7 diligence metrics, upserts to copy-trader-profiles.json.

Committed: `25817e8` (importer) + latest commit (flip bot fixes).

---

## Priority Task List for Codex

### P0 — Fix IWM options stop loss (30 min)

**File:** `strategies/iwm_options_bot.py`

**Problem:** The recovered IWM 4-leg group closed today at -211% of original credit
($54 credit → $168 debit = -$114 loss). A stop at -211% is industry-worst.

**Fix:** Enforce a hard stop at -100% of credit received (standard: close when position
costs 2x what you took in). Find the stop logic and change the multiplier.

Search for: `stop`, `max_loss`, `stop_loss_pct`, `trigger` in iwm_options_bot.py.
The current value is likely `2.0` or `3.0` — change to `1.0` (100% of credit = max loss).

Also add: log the credit received at entry time so the stop threshold is visible in logs.

---

### P0 — Wire bear_trend_spread execution in run_entry (1 hour)

**File:** `strategies/flip_bot.py`

**Problem:** `find_bear_trend_day()` now returns `strategy: "bear_trend_spread"` with
`option_symbol` (long leg) and `short_option_symbol` (short leg). But `run_entry()`
only knows how to submit single-leg orders via `_submit()`.

**Fix:** In `run_entry()`, detect `setup["strategy"] == "bear_trend_spread"` and:
1. Submit BUY order for `setup["option_symbol"]` (long put leg)
2. Submit SELL TO OPEN order for `setup["short_option_symbol"]` (short put leg)
3. Log both legs, store both OCC symbols in state for monitoring/closing
4. In `run_monitor()` and `close_all()`, handle two-leg positions — close both legs
   when stop/target hit

Test: add `test_flip_bot_spread_entry.py` covering the two-leg submission path.

---

### P0 — Polymarket public wallet tracker (2 hours)

**File to create:** `strategies/polymarket_wallet_tracker.py`

**Goal:** Fetch real public wallet trade history from Polymarket CLOB API (no auth needed).
Feed into copy_trader_watchlist via trade_history_importer.

**Polymarket CLOB public endpoints (no API key):**
```
GET https://clob.polymarket.com/trades?maker_address=0x...&limit=500
GET https://clob.polymarket.com/activity?user=0x...
GET https://data-api.polymarket.com/activity?user=0x...&limit=500
```

**Build:**
```python
def fetch_wallet_trades(address: str, limit: int = 500) -> list[dict]:
    """Fetch settled trades for a Polymarket wallet. No auth needed."""

def wallet_to_csv(address: str, out_path: Path) -> Path:
    """Fetch trades and write normalised CSV for trade_history_importer."""
```

Output CSV columns: `timestamp,market,outcome,shares,price,profit_loss,fee`
(matches Polymarket format auto-detected by importer).

Then one command imports a real wallet:
```
python strategies/polymarket_wallet_tracker.py --address 0xABC... --handle "whale_abc"
python strategies/trade_history_importer.py --file /tmp/whale_abc.csv --handle "whale_abc" --platform polymarket
```

Repos to study for API details (read source, don't install blindly):
- https://github.com/pselamy/polymarket-insider-tracker
- https://github.com/FuckFiat/polymarket-whale-tracker
- https://github.com/Xyryllium/polymarket-tracker-bot

**Important:** Read-only. No wallet keys. No order placement.

---

### P1 — Kalshi trade history importer adapter (1 hour)

**File to create:** `strategies/kalshi_history_fetcher.py`

Kalshi provides trade history export via API (requires auth with existing API key):
```
GET https://trading-api.kalshi.com/trade-api/v2/portfolio/fills
```
Auth: RSA headers (already implemented in kalshi_weather_bot.py — copy the
`make_headers()` + `signed_headers()` pattern).

**Build:**
```python
def fetch_kalshi_fills(key_id: str, pem_path: str, limit: int = 1000) -> list[dict]:
    """Fetch all settled fills from Kalshi account."""

def fills_to_csv(fills: list[dict], out_path: Path) -> Path:
    """Write CSV in Kalshi format for trade_history_importer."""
```

This lets Kenny track his own Kalshi weather bot accuracy as a scored trader profile,
connecting the two projects.

---

### P1 — MNQ shadow scanner signal quality (1 hour)

**File:** `strategies/shadow_pullback_signal.py`

**Problem:** Scanner ran today, logged "No breakout" all day, zero signals.
On a down day with 9/10 bear signals in SPY/QQQ/IWM, MNQ was also likely trending
down — but the scanner found nothing.

**Investigate:**
1. What are the current entry conditions? Log every bar's score, not just the final skip.
2. Is the pullback tolerance too tight? (st80 tol8 from June 22 sweep — may not work on
   trend-down days where price never pulls back, it just grinds lower)
3. Add a "trend mode" that lowers pullback requirement on confirmed bear days
   (when bear_trend score ≥ 8 on SPY/IWM, allow entries on any VWAP touch).

**Do not change thresholds without logging data first.**

---

### P1 — Why-Rejected report section in copy trader watchlist (30 min)

**File:** `strategies/copy_trader_watchlist.py`

Add to `build_report()`:
```python
"rejected_traders": [
    {
        "handle": t.handle,
        "platform": t.platform,
        "flags": scored.risk_flags,
        "score": scored.confidence,
        "what_would_help": _rejection_guidance(scored.risk_flags),
    }
    for t, scored in zip(profiles, scored_list) if scored.status == "reject"
]
```

`_rejection_guidance(flags)` returns a human-readable string per flag, e.g.:
- "unverified social data" → "Need: exported broker history or verified public wallet"
- "sample too small" → "Need: 30+ trades minimum, 100+ preferred"
- "choppy pnl curve" → "Need: pnl_smoothness ≥ 0.70 (linear equity growth)"

This prevents Kenny from being seduced by viral screenshots.

---

### P2 — Flip bot: execute bear_trend_spread on monitor/close (after P0 spread wiring)

Once P0 spread execution is wired, update `run_monitor()` to:
- Track both legs in state
- Close both legs at stop (-50% of net debit paid) or target (+100% of net debit)
- Log max_loss and max_gain from the strategy dict

---

## Verification Gate

After each P0 task, run:
```powershell
uv run --no-project --with pytest --with yfinance --with requests --with python-dotenv python -m pytest agent/tests/ -q
```

All tests must pass before next task.

---

## Safety Rules (non-negotiable)

- PAPER_ONLY: `ALPACA_PAPER=true` must remain set
- No live trading without explicit Kenny approval
- No Polymarket wallet keys or order placement
- No raising MAX_RISK_PCT above 0.02 (2%)
- IWM stop must be ≤ -100% of credit (never worse)
