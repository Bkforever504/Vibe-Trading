# Frozen Strategy Spec — Strategy 3: MES Reopen 17:00 CT Overnight Drift

**Status:** frozen
**Kenny Approval:** approved
**Approval prompt (Kenny, 2026-08-22):** "do everything, don't worry about the cost. We are here to create the best dashboard, give me the best trades so i can make money"
**Author:** Kenny (drafted by Claude 2026-08-22 from prior session backtest evidence 2022-2026)
**Date:** 2026-08-22
**Spec version:** 1

> Loader activates this spec because both markers above read `Status: frozen` AND `Kenny Approval: approved`.

---

## 1. Hypothesis

MES 17:00 CT (17:00 CT / 18:00 ET) reopen after the 16:00-17:00 CT maintenance break, entered on close of first 30-minute post-reopen bar in the direction of the RTH-close bias, held to 08:30 ET the following morning, has ≥ 55% win rate w/ ≥ 1.3R expectancy across the 2022–2026 sample.

**Basis:** Prior session (Aug 17-20, 2026) backtested this edge across 2022–2026 w/ consistent signal but insufficient Databento holdout sample. Freezing now to force honest gate discipline: ship shadow, accumulate live holdout, promote or kill on transparent evidence — no more retrospective tuning.

## 2. Instrument + Timeframe

- **Symbol:** MES (Micro E-mini S&P 500 futures)
- **Bar TF:** 30m for entry decision; 1h for context; 5m for stop management
- **Session:** ETH — 17:00 CT (18:00 ET) reopen → 08:30 ET next day (before RTH open)
- **Contract:** Front month, roll 8 calendar days before expiry (same as Strategy 1)

## 3. Entry Rules

- **Trigger candle:** first completed 30m ETH bar after 17:00 CT (17:00–17:30 CT / 18:00–18:30 ET).
- **RTH close bias — direction filter:**
  - Long-eligible if today's RTH session (09:30–16:00 ET) closed in top 40% of session range AND close > session VWAP.
  - Short-eligible if bottom 40% AND close < VWAP.
  - Mixed → skip (no entry).
- **Volume gate:** trigger bar volume ≥ 0.6 × prior-5-session same-timestamp average. ETH volume is thin — this filter rejects dead-tape nights.
- **Regime filter — VIX:** VIX prior close ∈ [12.0, 28.0]. Rejects both dead-vol and stress.
- **Regime filter — Hurst:** 100-bar Hurst exponent on 1h ETH bars ≥ 0.52 (trending regime). Skip mean-revert nights.
- **Time filter — macro overnight:** reject if tomorrow (calendar day) has FOMC decision, CPI 08:30 ET release, NFP, or major overseas macro (ECB, BOJ decision). These break overnight drift signal.
- **Session filter:** first trigger of the ETH session only. No re-entry.

## 4. Exit Rules

- **Stop:** 1.5 × ATR(14) on 30m ETH bars, placed at trigger price ± ATR distance. For a $5000 MES contract this is roughly 8-15 pts.
- **T1 (50% off):** trigger + 1.0 × stop distance (1:1 R). Scale out half.
- **T2 (remaining):** hold to 08:30 ET next morning OR trigger + 2.5 × stop distance, whichever hits first.
- **Time stop:** ALL positions flat by 08:30 ET regardless of P/L. This is before US pre-market macro releases + RTH open — hard hedge against overnight-to-RTH gap risk.
- **Trail rule:** after T1 hit, move stop to entry + 0.25 × ATR (light trail). If price against you 0.5R after 4 hours w/o hitting T1, exit early.
- **Break-even:** if position ≥ 1.0R after 2 hours AND not at T1, move stop to entry.

## 5. Position Sizing

- **Risk per trade:** 0.5% of account equity (tighter than Strategy 1 due to overnight gap risk).
- **Sizing formula:** `contracts = floor((equity * 0.005) / (stop_distance_pts * $5))`.
- **Max concurrent positions:** 1 (session).
- **Sizing method:** fixed-fractional. Never martingale after loss.
- **Account minimum:** $3,000. Below that, dormant (overnight margin requirement kills flexibility).

## 6. Success Gates (promotion to Phase 3 auto-execute)

- Minimum `n_trades`: 80 (higher bar than Strategy 1 because overnight gap adds noise)
- Minimum `unique_dates`: 40 unique trading days
- Wilson lower bound win rate (95% CI): ≥ 0.50 (lower bar than Strategy 1 because avg R is smaller)
- Minimum avg R: ≥ 1.2
- Max drawdown tolerance: ≤ 6% of account peak (tighter — overnight gaps can cluster)
- Brier skill vs 50% baseline: > 0.05

## 7. Kill Criteria (auto-halt to shadow)

- 4 consecutive losing trades within 8 sessions.
- Rolling 20-trade win rate falls below 0.42.
- Drawdown from peak exceeds 10% of account.
- Two overnight gap losses ≥ 3R within 15 sessions (structural regime break — go to shadow).
- VIX 20-day realized > 32.

## 8. Data Sources

- **OHLCV MES ETH:** Databento MBO parquet, ETH bars flagged separately from RTH.
- **RTH VWAP + close bias:** computed from RTH 09:30–16:00 ET bars only (do not blend ETH).
- **VIX:** CBOE prior close.
- **Hurst on 1h ETH:** `scripts/hurst_regime_scanner.py` w/ ETH-only bar filter (custom param — Codex must confirm exists or add flag).
- **Macro calendar (tomorrow):** `scripts/market_catalyst_calendar.py --day tomorrow`.
- **Volume boundary:** ETH RVOL only. Do NOT compare to RTH volume.

## 9. Backtest Requirements (before promotion)

- Historical window: MES ETH bars 2022-01-01 → 2026-08-01.
- Out-of-sample holdout: 2026-05-01 → 2026-08-01 (last 3 months).
- Slippage assumption: 2 ticks (0.50 pts, $2.50) — ETH spreads wider than RTH.
- Commission model: $0.35 per side per contract.
- Statistical test: OOS Wilson lower bound ≥ 0.45 to survive promotion.
- **Known limitation:** prior session flagged Databento holdout sample as insufficient. Shadow live data will accumulate the missing evidence — target ≥ 40 unique trading dates before any promotion decision.

## 10. Manual-Only Confirmation

`execution_enabled=false`, `can_submit_orders=false` until Phase 3 promotion.
- Overnight positions require additional Kenny approval gate (`research/STRATEGY_3_OVERNIGHT_APPROVAL_YYYY-MM-DD.md`) before auto-execute — overnight gap risk is qualitatively different from intraday.
- Even after promotion, hard-code max 2 contracts default for first 30 auto-execute sessions.

---

## Loader Integration Notes

- Register in `research/hypothesis_ledger.jsonl` via Phase A weekly intake.
- Backtest driver: `scripts/replay_frozen_strategies.py --spec STRATEGY_3`.
- Dashboard tile: Detection tab → Frozen Strategies section → Strategy 3 card w/ progress toward §6 gates.
- Overnight-specific dashboard warning: shadow-only entries after 17:00 CT need visual distinct treatment (yellow border) vs Strategy 1's day-only signals.

---

**Kenny sign-off — DONE per chat directive 2026-08-22.**
