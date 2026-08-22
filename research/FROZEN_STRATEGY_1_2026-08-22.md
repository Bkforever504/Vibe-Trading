# Frozen Strategy Spec — Strategy 1: MES ORB 09:32 ET (VIX-filtered)

**Status:** frozen
**Kenny Approval:** approved
**Approval prompt (Kenny, 2026-08-22):** "do everything, don't worry about the cost. We are here to create the best dashboard, give me the best trades so i can make money"
**Author:** Kenny (drafted by Claude 2026-08-22 from Chuk 2025 SSRN 6355218 + prior session pattern research)
**Date:** 2026-08-22
**Spec version:** 1

> Loader activates this spec because both markers above read `Status: frozen` AND `Kenny Approval: approved`.

---

## 1. Hypothesis

MES 09:32 ET (first 2-minute) opening-range breakout, filtered by VIX ∈ [15, 25] and no macro-event window, has ≥ 60% win rate with ≥ 1.8R expectancy over 30d rolling window.

**Basis:** Chuk 2025 SSRN 6355218 measured SPY 5m ORB at 65.4% win rate w/ 1.8R when filtered (Mon/Wed/Fri + VIX 15-25 + no macro). Adapting to MES: same statistical edge should transfer since ES/MES track SPY tick-for-tick; MES leverage improves R:R math but also spread cost per unit.

## 2. Instrument + Timeframe

- **Symbol:** MES (Micro E-mini S&P 500 futures)
- **Bar TF:** 2m (first bar sets range) → 5m for trigger + exit management
- **Session:** RTH only, 09:30–16:00 ET
- **Contract:** Front month, roll 8 calendar days before expiry

## 3. Entry Rules

- **Opening range:** `[OR_H, OR_L] = [max(H), min(L)]` over 09:30:00–09:31:59 ET (first 2 minutes = one 2m bar OR two 1m bars).
- **Trigger candle:** first completed 5m bar (09:30–09:35, 09:35–09:40, or 09:40–09:45) that closes ≥ 0.10% beyond `OR_H` (long) or `OR_L` (short).
- **Volume gate:** RVOL on trigger bar ≥ 1.5 vs prior 20 bars (last 5 sessions same-timestamp average).
- **Regime filter — VIX:** VIX prior close ∈ [15.0, 25.0]. Rejects both dead-vol (< 15) and stress (> 25).
- **Regime filter — HMM:** `hmm_regime_scanner.py` state must be "trend" (state 0). Reject "chop" (state 1).
- **Time filter — macro event window:** reject if today has CPI, PCE, PPI, NFP, FOMC decision, FOMC minutes, or GDP release in the 09:30–15:30 ET window. Feed: `scripts/market_catalyst_calendar.py`.
- **Day-of-week gate:** Monday, Wednesday, Friday only. Chuk 2025 showed Tue/Thu erode edge ~25%.
- **Session filter:** first trigger of the day only. No re-entry after first stop or first target.

## 4. Exit Rules

- **Stop:** opposite side of the opening range. Long trigger → stop at `OR_L - 1 tick`. Short trigger → stop at `OR_H + 1 tick`.
- **T1 (50% off):** trigger price + 1.0 × `(OR_H - OR_L)` for long; mirror for short. Scale out half.
- **T2 (remaining):** trigger price + 2.0 × `(OR_H - OR_L)`. Full exit.
- **Time stop:** flat by 12:00 ET regardless of P/L. Midday drift kills edge.
- **Trail rule:** after T1 hit, move stop to breakeven + 1 tick. No further trail.
- **Break-even nudge:** if position ≥ 0.5R after 15 min AND not yet at T1, move stop to entry.

## 5. Position Sizing

- **Risk per trade:** 0.75% of account equity (Kenny's max risk profile is 25% per trade; this stays well under).
- **Sizing formula:** `contracts = floor((equity * 0.0075) / (stop_distance_pts * $5))` where $5 = MES tick value × 4 ticks per point.
- **Max concurrent positions:** 1 (session-wide, one setup per day).
- **Sizing method:** fixed-fractional per-trade risk. No Kelly, no martingale.
- **Account minimum:** $2,500. Below that, this strategy is dormant.

## 6. Success Gates (promotion to Phase 3 auto-execute)

- Minimum `n_trades`: 60
- Minimum `unique_dates`: 30
- Wilson lower bound win rate (95% CI): ≥ 0.55
- Minimum avg R: ≥ 1.5
- Max drawdown tolerance: ≤ 8% of account peak
- Brier skill vs 50% coin-flip baseline: > 0.08

## 7. Kill Criteria (auto-halt to shadow)

- 5 consecutive losing trades within 10 sessions.
- Rolling 20-trade win rate falls below 0.40.
- Drawdown from peak exceeds 12% of account.
- VIX regime shift: VIX 20-day realized > 30 (structural stress).

## 8. Data Sources

- **OHLCV MES:** Databento MBO parquet aggregated to 2m/5m via existing `scripts/fetch_databento_mbo.py` loaders.
- **VIX:** CBOE prior close via `agent/api_server.py` VIX endpoint.
- **HMM regime state:** `scripts/hmm_regime_scanner.py` daily output.
- **Macro calendar:** `scripts/market_catalyst_calendar.py` for CPI/PCE/PPI/NFP/FOMC/GDP.
- **Volume boundary:** RTH only. ETH bars excluded from RVOL denominator.

## 9. Backtest Requirements (before promotion)

- Historical window: MES data 2022-01-01 → 2026-08-01 (~4.5 years, includes bull + bear + FOMC hiking).
- Out-of-sample holdout: 2026-05-01 → 2026-08-01 (last 3 months).
- Slippage assumption: 1 tick (0.25 pts, $1.25) on entry + exit.
- Commission model: $0.35 per side per contract (Interactive Brokers rate for MES).
- Statistical test: Wilson lower bound on OOS window ≥ 0.50 to survive promotion.

## 10. Manual-Only Confirmation

`execution_enabled=false`, `can_submit_orders=false` until Phase 3 promotion. Currently:
- Signal fires shadow-log only
- Dashboard shows candidate w/ full grade + entry/stop/target
- Kenny manually enters via broker if he chooses
- Auto-execute requires ≥ 30 shadow days + all §6 gates met + Kenny sign-off on `research/STRATEGY_1_PROMOTION_APPROVAL_YYYY-MM-DD.md`

---

## Loader Integration Notes (for Codex Phase D)

- Register in `research/hypothesis_ledger.jsonl` via Phase A weekly intake (Sunday 09:00 CT).
- Backtest driver: `scripts/replay_frozen_strategies.py --spec STRATEGY_1` — reads this file, applies §3–5 rules to historical bars, emits `~/.vibe-trading/reports/frozen-strategy-replay-strategy_1.json`.
- Dashboard tile: Detection tab → "Frozen Strategies" section → Strategy 1 card w/ progress toward §6 gates.

---

**Kenny sign-off — DONE per chat directive 2026-08-22.**
