# Flip Bot Handoff — 2026-08-08

## Status: 3 Bug Fixes Applied, NOT YET COMMITTED

Parse-check passed (`python -m py_compile strategies/flip_bot.py` — exit 0, no errors).

**First action in new session:**
```powershell
cd "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
git add strategies/flip_bot.py scripts/flip_shadow_pnl_evaluator.py scripts/run_flip_bot_entry.ps1 scripts/run_flip_bot_monitor.ps1 strategies/robinhood_mimic.py
git commit -m "Fix 3 critical bugs that blocked Friday Aug 7 trades: spot->price NameError, VIX ratio inverted, ADD/TRIN log spam"
git push
```

---

## Why Bot Didn't Trade Friday Aug 7

Three bugs hit simultaneously. SPY had valid `retest_confirmed_fresh entry_ready=True` signal at 9:45 ET. All three bugs blocked it.

### Bug 1 — FATAL: `name 'spot' is not defined` (PRIMARY CAUSE)
- `_find_0dte_for_symbol` uses `price = _spot(sym)` (NOT a variable named `spot`)
- Max pain block used `spot` → FATAL crash at every entry attempt
- Crashed before any order could be placed
- **Fixed:** changed `spot` → `price` in max pain block (~line 2283)

### Bug 2 — VIX ratio inverted (fired in CALM markets)
- `_fetch_vix_term_structure()` returns `vix3m_over_vix` as `ratio` key
- `ratio > 1.0` in contango (calm) = WRONG — was penalizing CALL confidence in calm conditions
- **Fixed:** use `_vts.get("regime") == "backwardation"` + `vix_over_vix3m` key
- Location: ~line 2293 in `_find_0dte_for_symbol`

### Bug 3 — yfinance $ADD/$TRIN ERROR spam
- Yahoo Finance free API returns 404 for NYSE breadth indicators
- Generated 3 ERROR lines per scan, every 5 minutes
- **Fixed:** suppress yfinance logger to CRITICAL during these calls in `_market_internals_signal()` (~line 1856)

---

## All Changes Made This Session (Committed vs Pending)

### Already Committed (5 commits):
1. `69ae82f` — Tighter ratchet (40%→25% arm, 15%→10% giveback), spread filter (MAX_SPREAD_PCT=0.30), symbols = SPY+QQQ only
2. `b42eb38` — Shadow consensus staleness fix (refresh before entry), NBBO task fix
3. `0876930` — Day-of-week modifier (Mon +0.25, Tue/Thu -0.25) + time-of-day modifier (9:50-10:30 +0.25, after 11:00 -0.25)
4. `8f06660` — GEX 4-profile classification using yfinance Black-Scholes gamma
5. `53ffae0` — FLIP_ACCOUNT_SIZE_OVERRIDE=1000 in both PS1 launcher scripts

### Pending Commit (3 bug fixes in `strategies/flip_bot.py`):
- Bug 1: `spot` → `price` in max pain block
- Bug 2: VIX term structure key + ratio inverted
- Bug 3: yfinance log spam suppression

### Other files modified (include in commit):
- `scripts/flip_shadow_pnl_evaluator.py` — ratchet constants synced (ARM=25, FLOOR=15, GIVEBACK=10)
- `scripts/run_flip_bot_entry.ps1` — SPY+QQQ only, $1k override, shadow_consensus_gate refresh before entry
- `scripts/run_flip_bot_monitor.ps1` — SPY+QQQ only, $1k override
- `strategies/robinhood_mimic.py` — PDT threshold $25k → $2k (SEC/FINRA rule change June 4, 2026)

---

## Current Bot Configuration

| Setting | Value | Why |
|---------|-------|-----|
| FLIP_PAPER_CHALLENGER_SYMBOLS | SPY,QQQ | Only positive-expectancy symbols in shadow data |
| FLIP_ACCOUNT_SIZE_OVERRIDE | 1000 | Simulate real $1k Robinhood account |
| PROFIT_PROTECT_ARM_PCT | 25.0 | Was 40% — most 0DTE peaks below old threshold |
| PROFIT_PROTECT_GIVEBACK_PCT | 10.0 | Was 15% — tighter capture |
| MAX_SPREAD_PCT | 0.30 | Skip if bid-ask spread > 30% of mid |
| ENABLE_SHADOW_CONSENSUS_GATE | true | Blocks entries without historical evidence |
| ALPACA_PAPER | true | Paper trading only |
| FLIP_LIVE_EXECUTION_ENABLED | false | No live orders |

---

## Shadow Performance (as of session start)

| Symbol | Expectancy | Verdict |
|--------|-----------|---------|
| QQQ | +20.79% | Keep |
| SPY | +18.55% | Keep |
| RIVN | Negative | Dropped |
| AAPL | Negative | Dropped |
| NVDA | Negative | Dropped |

Capture efficiency was 24.7% (24.7% of peak gain captured). Target: 50%+ after ratchet fix.

---

## Key Architecture Facts

- **Entry script:** `scripts/run_flip_bot_entry.ps1` — runs shadow_consensus_gate.py THEN flip_bot.py --entry
- **Monitor script:** `scripts/run_flip_bot_monitor.ps1` — runs --monitor, --intraday-entry, --monitor --protect-loop
- **Shadow consensus gate:** reads `~/.vibe-trading/reports/shadow-consensus-gate.json`
- **ORB:** 5-min range 9:30-9:35 ET, retest or momentum required
- **Variable name:** spot price in `_find_0dte_for_symbol` = `price` (from `price = _spot(sym)` ~line 2117) — NOT `spot`
- **VIX keys:** `regime` ("backwardation"/"contango"/"flat"), `vix_over_vix3m` (>1.0 = stress), `vix3m_over_vix` (>1.0 = calm)
- **GEX profiles:** positive_pinned (-0.75), positive_mild (-0.25), negative_amplify (+0.5), negative_partial (+0.25)

---

## Deferred (Do Not Implement Without Explicit Approval)

- Debit spreads (instead of naked long options) — biggest structural improvement, large refactor
- Macro catalyst lane (FOMC/CPI/NFP 15-min post-print momentum)
- X/Twitter API credentials
- Polymarket X integration (PMXT)
- Trend participation shadow → live orders (SECURITY: never wire to live)
- Promoting Aug 4 ATH day result (excluded as design day)

---

## Security Constraints (Permanent)

- Never wire trend participation shadow to live orders
- Never promote based on Aug 4 day (excluded as design day)
- Never loosen short-premium gates because of ATH day
- Never add X API credentials or PMXT without explicit Kenny approval
- Never commit agent/.env

---

## Immediate Next Steps (New Session)

1. **Commit + push the 3 bug fixes** (command at top of this file)
2. **Let bot trade Monday Aug 11** — all infrastructure ready, observe real signals
3. After Monday data collected: evaluate capture efficiency improvement
4. Optional: debit spreads refactor (confirm with Kenny first)
