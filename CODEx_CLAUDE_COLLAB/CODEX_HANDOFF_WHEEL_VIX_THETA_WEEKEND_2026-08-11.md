# Codex Handoff — Wave 3 Strategies
**Date:** 2026-08-11  
**From:** Claude (strategy build session)  
**To:** Codex (hardening + wiring)

---

## What Was Built This Session

Four new shadow-paper strategies plus portfolio-level theta dashboard. All smoke-tested. No live orders anywhere.

### New Files
| File | Type | Status |
|------|------|--------|
| `strategies/spy_wheel.py` | CSP→Assignment→CC state machine | PASS |
| `strategies/vix_call_hedge.py` | OTM VIX call tail hedge | PASS (blocked: no VIX expiry in 45-60d window today) |
| `scripts/portfolio_theta_dashboard.py` | Aggregate theta vs 0.06-0.10% target | PASS ($67/day over target — wheel just opened) |
| `strategies/spy_weekend_vol.py` | Thursday straddle, Friday sell | PASS (blocked: not Thursday) |

### Runner Scripts (need Task Scheduler registration)
| Script | Task Name | Schedule (CT) |
|--------|-----------|---------------|
| `scripts/run_spy_wheel.ps1` | SPY-Wheel-Check | Mon-Fri 9:45 AM |
| `scripts/run_vix_call_hedge.ps1` | VIX-Call-Hedge-Check | Mon-Fri 10:00 AM |
| `scripts/run_spy_weekend_vol.ps1` | SPY-Weekend-Vol-Entry | Thursday 2:30 PM |
| `scripts/run_portfolio_theta_dashboard.ps1` (create) | Portfolio-Theta-Dashboard | Mon-Fri 9:30 AM |

**Action for Codex:** Run `scripts/register_new_strategies_tasks.ps1` as administrator to wire all four tasks. Also create `scripts/run_portfolio_theta_dashboard.ps1` (same pattern as `run_spy_wheel.ps1` but calls `python scripts\portfolio_theta_dashboard.py`).

---

## Complete Strategy Map (All 7 Active Shadow Strategies)

### 1. Theta Harvester (`strategies/spy_theta_harvester.py`)
- **Edge:** Sell SPY 16-delta put spreads, 45 DTE, IVR > 30, IVP > 50
- **Entry:** Monday 8:45 AM CT (Task: SPY-Theta-Harvester-Entry)
- **Monitor:** Mon-Fri hourly 9-2 PM CT (Task: SPY-Theta-Harvester-Monitor)
- **State:** `data/theta_harvester_state.json`
- **Next trigger:** Monday Aug 17

### 2. 0DTE PM Spread (`strategies/spy_0dte_pm_spread.py`)
- **Edge:** 0DTE SPY put credit spread, 12-2 PM ET, SPY above 20d SMA
- **Entry:** Daily 12:00 PM CT (Task: SPY-0DTE-PM-Spread-Entry)
- **Monitor:** 12:30/1:00/1:30/2:00/2:30 PM CT
- **State:** `data/spy_0dte_pm_state.json`

### 3. Iron Condor (`strategies/spy_iron_condor.py`)
- **Edge:** 16-delta both wings, IVP > 60, 21-30 DTE
- **Entry:** Daily 9:45 AM CT (Task: SPY-Iron-Condor-Entry)
- **Monitor:** Daily 11:00 AM CT
- **State:** `data/spy_iron_condor_state.json`

### 4. FOMC IV Crush (`strategies/spy_fomc_iv_crush.py`)
- **Edge:** Sell put spread 1-5 days before FOMC; IV overprices meeting risk
- **Entry:** Manual run during FOMC window (Sept 11-15, 2026 for Sept 16 meeting)
- **State:** `data/spy_fomc_iv_crush_state.json`

### 5. Earnings IV Capture (`strategies/spy_earnings_iv_capture.py`)
- **Edge:** Buy ATM straddle 7-10 days before earnings, close day before
- **Watchlist:** AAPL, NVDA, TSLA, MSFT, AMZN, GOOGL, META
- **Next scan:** Aug 16 (NVDA Aug 26 earnings enters window)
- **State:** `data/spy_earnings_iv_capture_state.json`
- **Action for Codex:** Add daily cron at 9:00 AM CT Mon-Fri: `python strategies/spy_earnings_iv_capture.py --scan`

### 6. Wheel (`strategies/spy_wheel.py`) — NEW
- **Edge:** CSP → Assignment → CC → repeat; VRP + cost basis reduction
- **Gates:** VIX 13-25, IVR > 20, delta ~0.30, DTE 21-35
- **State machine:** idle → csp_open → assigned → cc_open → idle
- **State:** `data/spy_wheel_state.json`
- **Action for Codex:** Register SPY-Wheel-Check task (see above)

### 7. VIX Call Hedge (`strategies/vix_call_hedge.py`) — NEW
- **Purpose:** Tail protection when running short-premium positions
- **Strike:** VIX × 1.5 (30% OTM), DTE 45-60, roll at 21 DTE
- **Gate:** VIX/VIX3M in contango only (max cost $2.00/contract)
- **State:** `data/vix_call_hedge_state.json`
- **Action for Codex:** Register VIX-Call-Hedge-Check task (see above)

### 8. Weekend Vol (`strategies/spy_weekend_vol.py`) — NEW
- **Edge:** People overpay for weekend SPY protection; buy Thursday, sell Friday
- **Entry:** Thursday ONLY, 2:30 PM CT (matches 14:30 ET window start)
- **Close:** Friday 2:00-3:30 PM ET OR Monday 9:45-10:15 ET
- **State:** `data/spy_weekend_vol_state.json`
- **Action for Codex:** Register SPY-Weekend-Vol-Entry task (see above)

### 9. Portfolio Theta Dashboard (`scripts/portfolio_theta_dashboard.py`) — NEW
- **Purpose:** Aggregate daily theta; target 0.06-0.10% of account/day
- **Output:** `data/portfolio_theta_dashboard.json`
- **Action for Codex:** Register Portfolio-Theta-Dashboard task (see above); create PS1 runner

---

## Key Dates / Calendar

| Date | Event | Action |
|------|-------|--------|
| Aug 16, 2026 | NVDA enters 7-10d earnings window | Run `spy_earnings_iv_capture.py` — should find candidate |
| Aug 17, 2026 | Monday — theta harvester fires | PC must be on at 8:45 AM CT |
| Aug 26, 2026 | NVDA earnings | Earnings IV capture auto-closes day before (Aug 25) |
| Sept 11-15, 2026 | FOMC entry window | Run `spy_fomc_iv_crush.py` any day in this range |
| Sept 16, 2026 | FOMC Decision | FOMC strategy closes at 2:00 PM ET |

---

## Security Invariants (DO NOT CHANGE)

All strategy files have these hardcoded — never remove:
```python
execution_enabled: false
can_submit_orders: false
orders_submitted: 0
```

Live execution only unlocks via `THETA_LIVE_EXECUTION=LIVE_CONFIRMED` env var in theta harvester. All other strategies are shadow-only with no live path at all.

---

## Codex Priority Queue

1. **Register 4 new tasks** — run `scripts/register_new_strategies_tasks.ps1` as admin
2. **Create `scripts/run_portfolio_theta_dashboard.ps1`** runner
3. **Wire earnings scan to scheduler** — daily 9:00 AM CT: `spy_earnings_iv_capture.py --scan`
4. **Add wheel + VIX hedge + weekend vol to evidence journal** in iron condor observation system
5. **Wheel assignment handling** — when `spy_wheel_state.json` shows `phase: csp_open` and it's expiry day, run `python strategies/spy_wheel.py --assign` to advance state machine
6. **VIX hedge roll logic** — when `check` returns `status: roll`, close current and call `vix_call_hedge.py` fresh to open new expiry

---

## State Files Reference

```
data/theta_harvester_state.json
data/spy_0dte_pm_state.json
data/spy_iron_condor_state.json
data/spy_fomc_iv_crush_state.json
data/spy_earnings_iv_capture_state.json
data/spy_wheel_state.json          ← NEW (has csp_open entry from smoke test)
data/vix_call_hedge_state.json     ← NEW
data/spy_weekend_vol_state.json    ← NEW
data/portfolio_theta_dashboard.json ← NEW
```

**Note:** `data/spy_wheel_state.json` has a real shadow entry from the smoke test (SPY 753P Sep-4 exp, credit $4.13). This is valid shadow paper data — leave it.

---

## MES Futures (Archived)

30K+ parameter combinations tested. All failed 3-window stability. Low-VIX 2025-2026 regime killed ORB edge. **Do not pay for TopstepX until VIX > 20 returns consistently.** Hypothesis preregistered: long-only + Tue/Wed + gap filter. Test when forward data available.

---

## Codex Hardening And Honest Evaluation 2026-08-11

The original registration file referenced a missing dashboard runner, used
unnecessary `Highest` privileges, scheduled wheel and weekend-vol one hour late
relative to their Eastern gates, and had no weekend exit monitor.

Completed:

- Created `run_portfolio_theta_dashboard.ps1` and
  `run_spy_weekend_vol_monitor.ps1`.
- Registered five limited tasks. Wheel runs 08:45 CT, VIX hedge 09:00 CT,
  dashboard 09:30 CT, weekend entry Thursday 13:35 CT, and weekend monitors
  Friday 13:05/14:05 CT plus Monday 08:50 CT.
- Schedule governance passes 75/75 with zero issues or warnings.
- Wheel uses executable bid/ask pricing. Profit closes advance state, and
  expiry distinguishes worthless puts, put assignment, covered-call expiry,
  and shares called away.
- Cash-secured puts fail when strike x 100 exceeds `PAPER_ACCOUNT_SIZE`.
  The smoke-test SPY 753P requires $75,300 against the configured $10,000 and
  is preserved for audit but blocked and excluded from portfolio metrics.
- The `$67/day theta` result was not an option Greek or expected profit. It was
  a credit-decay proxy applied to an infeasible position. The dashboard now
  labels the metric diagnostic-only, honors `--account`, and reports $0/day
  with zero active feasible positions.
- VIX hedge uses executable ask/bid pricing, prevents duplicate open state,
  persists roll closure, and caps premium spend by paper-account percentage.
- Weekend-vol entry uses asks and exits use bids. Friday/Monday closes persist
  closed shadow state and executable PnL.
- Wheel, VIX hedge, and weekend-vol decisions feed the append-only observation
  journal. All remain shadow-only with zero order authority.

Economic status:

- Wheel: operational but not capital-compatible for SPY/QQQ at $10,000.
- VIX hedge: risk-control research, not an income strategy; currently blocked.
- Weekend vol: unvalidated research hypothesis, not a documented edge.
- Theta dashboard: diagnostics only, not a profitability forecast.

No orders were submitted. Smoke tests do not prove profitability.

Verification after hardening:

- focused lifecycle, journal, and schedule tests: 26 passed;
- full repository suite: 4,591 passed, 4 skipped;
- Windows schedule governance: 75/75 aligned, zero issues, zero warnings;
- registered tasks: all five `Ready`, all `RunLevel Limited`;
- broker orders submitted: zero.
