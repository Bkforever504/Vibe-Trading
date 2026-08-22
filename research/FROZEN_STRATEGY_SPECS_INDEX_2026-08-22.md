# Kenny's Five Frozen Strategy Specs — Index

**Purpose:** Phase D calibration (execution reliability 8→9) is blocked pending Kenny's five frozen strategy specifications. This file is the index + scaffolding. Each linked spec file has the same skeleton and needs Kenny's content + approval markers.

**Gate rule (matches Phase A governance):** Each spec activates in the promotion pipeline ONLY when its front matter contains both `Status: frozen` AND `Kenny Approval: approved`.

---

## The Five Strategies (Kenny's own; edit slots below)

| # | Slot name | File | Status | Kenny Approval |
|---|---|---|---|---|
| 1 | Strategy 1 (Kenny to name) | `research/FROZEN_STRATEGY_1_2026-08-22.md` | draft | pending |
| 2 | Strategy 2 | `research/FROZEN_STRATEGY_2_2026-08-22.md` | draft | pending |
| 3 | Strategy 3 | `research/FROZEN_STRATEGY_3_2026-08-22.md` | draft | pending |
| 4 | Strategy 4 | `research/FROZEN_STRATEGY_4_2026-08-22.md` | draft | pending |
| 5 | Strategy 5 | `research/FROZEN_STRATEGY_5_2026-08-22.md` | draft | pending |

---

## Each Spec Must Contain (skeleton)

```markdown
# Frozen Strategy Spec — [Name]

**Status:** draft            ← flip to "frozen" when ready
**Kenny Approval:** pending   ← flip to "approved" when signed off
**Author:** Kenny
**Date:** 2026-08-22
**Spec version:** 1

## 1. Hypothesis (one sentence)
E.g., "MES 09:32 ET open range breakout w/ VIX 15-25 filter has ≥ 55% win rate w/ ≥ 1.5R expectancy over 30d rolling window."

## 2. Instrument + timeframe
- Symbol: MES / SPY / IWM / etc.
- Bar TF: 1m / 5m / 15m / 1h / D
- Session: RTH only? RTH+ETH?

## 3. Entry Rules (deterministic, machine-implementable)
- Trigger candle definition
- Volume/RVOL threshold
- Regime filter (VIX range? HMM state? trend/chop?)
- Time-of-day filter
- Signal confluence required

## 4. Exit Rules
- Stop placement (ATR multiple? structural?)
- T1 target
- T2 target
- Time stop
- Trail rule (if any)

## 5. Position Sizing
- Risk per trade (% of account)
- Max concurrent positions
- Kelly / fixed-fractional / etc.

## 6. Success Gates (promotion criteria)
- Minimum n_trades: ___
- Minimum unique dates: ___
- Wilson lower bound win rate: ___
- Minimum avg R: ___
- Max drawdown tolerance: ___

## 7. Kill Criteria (demotion / halt)
- Consecutive losses: ___
- Rolling 20-trade win rate below: ___
- Underwater curve exceeds: ___

## 8. Data Sources
- OHLCV: Alpaca / Databento / etc.
- Regime: VIX from CBOE / HMM from hmm_regime_scanner.py
- Volume: session RTH vs ETH boundary

## 9. Backtest Requirements Before Frozen
- Historical window covered: ___ years
- Out-of-sample holdout: ___ months
- Slippage assumption: ___ ticks/bps
- Commission model: ___

## 10. Manual-Only Confirmation
This spec runs shadow-only until Phase 3 promotion. execution_enabled=false, can_submit_orders=false.

---
Kenny sign-off:
Status: frozen
Kenny Approval: approved
```

---

## Downstream Wiring (Codex — after Kenny signs at least one spec)

1. `scripts/frozen_strategy_loader.py` — reads all `research/FROZEN_STRATEGY_*.md` files. Only loads specs where both `Status: frozen` AND `Kenny Approval: approved` are set.
2. Each frozen spec auto-populates `research/hypothesis_ledger.jsonl` w/ preregistered entry (Phase A intake path).
3. `scripts/replay_frozen_strategies.py` — runs each frozen spec against historical bars, emits `~/.vibe-trading/reports/frozen-strategy-replay-<name>.json` w/ trade log + gate status.
4. Frontend Detection tab surfaces each frozen strategy w/ live progress toward its own success gates.

**No wiring runs until at least Strategy 1 has both frozen + approved markers.**

---

## Why This Matters (from Aug 20 handoff)

> "Kenny's five frozen strategy specifications and subsequent replay outcomes remain the gating evidence" for making verified edge 10/10.

Phase D calibration cannot begin without these. The research-governance foundation (Phase A) can *catalog* hypotheses but has nothing to *validate* until Kenny writes and freezes the actual bets.

**Next action for Kenny:** open `research/FROZEN_STRATEGY_1_2026-08-22.md`, fill sections 1–10, flip Status + Kenny Approval markers. Repeat for 2–5 as ready. No rush; better one solid spec than five sloppy ones.
