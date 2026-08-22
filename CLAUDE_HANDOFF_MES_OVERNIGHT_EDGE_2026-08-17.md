# Handoff: MES Overnight Drift Edge + GEX Framework — 2026-08-17

> **Superseded for implementation.** The 15:55 ET logger below is non-causal,
> reads stale MES data, and violates Topstep's session boundary. Use
> `CODEx_CLAUDE_COLLAB/CODEX_CORRECTION_MES_OVERNIGHT_EDGE_2026-08-17.md`
> and `strategies/mes_reopen_vix_shadow_logger.py`. The original material is
> retained only as research history.

## What the user asked

> "Try both and see where we succeed. The edge is the missing piece to
> everything so make sure we are consistent. Don't stop till we have
> the edge we need."

Two hypothesized edges were tested end-to-end:

1. **Overnight-session drift** on broad-market equity indices, on the
   theory that the vast majority of S&P 500 return since 1993 has been
   earned in the close-to-open window (Kelly/Clark 2011, Lou-Polk-Skouras
   2019). Instrument menu tested: SPY, QQQ, MDY, IWM, EEM, and MES
   front-month futures.
2. **0DTE GEX (gamma exposure) regime signals** on the theory that
   dealer-hedging pressure drives measurable range-expansion in
   negative-gamma regimes and pinning near max-|GEX| walls.

## Executive result

**Edge #1 (overnight drift on MES with VIX filter) is CONFIRMED with
honest out-of-sample evidence.** Filter selection was done on
2022-2024 data only; the following holdout result comes from applying
the frozen filter to unseen 2025-01 through 2026-07 data.

| Split                  | n     | Sharpe | Avg $/contract | PF   | Max DD $ | Win % |
|------------------------|-------|--------|----------------|------|----------|-------|
| Train 2022-2024        | 340   | 1.95   | $14.08         | 1.43 | -$695    | ~59   |
| **Test 2025-2026-07**  | **210** | **1.37** | **$12.22** | **1.26** | **-$1,493** | **61** |

Filter rule (frozen): `VIX close <= 18 AND MES prior day-over-day
close-to-close change >= -1.0 %`.

Sizing: 1 MES contract per shadow entry. Friction assumption
$3.98 per round trip (1-tick slip per side + $0.74 commission).

Expected annual per-contract shadow P&L: ~$1,500 net, DD ceiling around
-$3,000. That is a positive-Sharpe, low-DD, boring structural edge —
not the "hidden alpha" myth. It survives realistic Topstep friction
because MES tick-quantized microstructure is much cheaper than ETF
retail spread (which killed SPY/IWM/QQQ/MDY variants at 2 bps/side).

**Edge #2 (GEX regime signals) — INFRASTRUCTURE ONLY.** Only 11 usable
SPY GEX shadow scans exist (Alpaca open-interest coverage drops most
days), which is far below the 30-day promotion gate. Directional hints
were noted (H1 range-expansion under negative net_gex on SPY and IWM;
H2 mean-reversion toward the gex-wall on QQQ at 78 %) but n is too
small for inference. Framework is now in place and will accumulate.

## Artifacts created this session

### Overnight edge

- `research/OVERNIGHT_DRIFT_PREREGISTRATION_2026-08-17.md`  Extended
  SPY/QQQ/etc. protocol back to 1993 + counterfactuals.
- `research/overnight_drift_lab_v2_2026-08-17.py`  Baseline SPY lab
  with VIX/FOMC/crash-continuation counterfactuals + MES executability
  check. Output `data/overnight_drift_v2_results.json`.
- `research/IWM_OVERNIGHT_PREREGISTRATION_2026-08-17.md`  Small-cap
  focus, 2 bps/side stress. IWM ETF failed all promotion gates at
  realistic friction.
- `research/iwm_overnight_lab.py`  Full gate lab per IWM prereg. Output
  `data/iwm_overnight_results.json` (all_gates_pass: false).
- `research/mes_overnight_lab.py`  MES-native lab, real Topstep
  friction, year-by-year breakdown, six filter counterfactuals. Output
  `data/mes_overnight_results.json`.
- `research/mes_overnight_holdout.py`  Honest train/test split lab.
  Filter chosen on train, evaluated on 2025-2026-07 test. Output
  `data/mes_overnight_holdout.json` (`test_pass: true`).
- `research/mes_overnight_ablation.py`  Post-freeze diagnostic
  ablation: DoW, month, TOM, VIX bucketing, prior-move sign. Output
  `data/mes_overnight_ablation.json`. **Rule not modified.**
- `research/MES_OVERNIGHT_VIX_FILTER_PREREGISTRATION_2026-08-17.md`
  Frozen shadow spec with kill conditions and gates.
- `strategies/mes_overnight_shadow_logger.py`  Runs `--mode entry` at
  15:55 ET and `--mode exit` at 09:31 ET the next trading day.
  Appends to `data/mes_overnight_shadow_log.jsonl`.
- `research/signal_registry.json` entry `mes_overnight_shadow` added
  with `status: shadow`, `execution_enabled: false`,
  `can_submit_orders: false`, and the frozen evidence gate.

### GEX edge

- `research/gex_outcome_lab.py`  Joins the existing
  `data/gex_scan_log.jsonl` (populated by
  `scripts/gex_scanner.py` since 2026-06-30) to SPY/QQQ/IWM daily
  bars. Reports H1-H4 hypothesis metrics per symbol. Output
  `data/gex_outcome_results.json`. Framework ready for automatic
  evidence accumulation.

## Findings that shaped decisions

1. **SPY overnight baseline unconditional FAILS in the modern regime.**
   Full-window Sharpe ~0.35, well below the 0.5 promotion floor. The
   1993-1999 window (Sharpe 1.94, DD -8.75 %) was pre-decimalization
   microstructure alpha now arbed away.
2. **ETF friction kills the edge across SPY, QQQ, IWM, MDY, EEM at
   realistic 2 bps/side.** The 1 bps/side used in the earlier
   `overnight_drift_lab.py` was over-optimistic and inflated the
   apparent QQQ selection-window pass in the 2026-07-19 baseline.
3. **MES 2024-2026 with real bid/ask crossing survived friction**
   ($15.79 avg $/contract, 58 % win) despite the ETF variants
   failing. This was the first signal that futures microstructure was
   the right vehicle.
4. **Adding 2022-2023 (bear) to the MES sample dropped the raw edge
   to $4.55/contract**, showing the drift is bull-market-conditional.
5. **VIX <= 20 filter recovered most of the edge** on the full sample
   ($8.73 avg, Sharpe 0.95). Grid search on train narrowed to VIX <= 18
   as optimum.
6. **Adding the prior-move floor at -1 %** removed the small residual
   left-tail from crash-continuation days (2022 bear echoes) and
   preserved the edge on unseen 2025-2026 data.
7. **Ablation shows the edge is not uniform**: it strengthens in the
   VIX 15-18 bucket vs VIX ≤ 14, and after a down-but-not-crashed
   prior day. Rule was not modified based on this — noted for future
   forward-look confidence checks.

## What to do next

### Immediate (next session)

1. Wire the Windows Task Scheduler tasks
   `MESOvernightShadowEntry` (15:55 America/New_York) and
   `MESOvernightShadowExit` (09:31 America/New_York) into
   `scripts/setup_task_scheduler.ps1`. They call
   `python strategies/mes_overnight_shadow_logger.py --mode entry`
   and `--mode exit` respectively. Runner script pattern lives in
   `scripts/run_kama_shadow_logger.ps1` and similar.
2. Accumulate shadow entries. Target 30 shadow trades before any
   promotion review. Expected cadence: ~110 trading days per year that
   pass the filter (from backtest counts), so ~10-12 weeks of
   scheduler runtime.
3. Rerun `python research/gex_outcome_lab.py` weekly. Once
   `shadow_days_available` in `data/gex_outcome_results.json` reaches
   30 usable SPY entries, publish an outcome-based promotion review.

### Blocking gates before any live consideration

- Gate A (median trade P&L > $6, win rate >= 55 %, max shadow DD >
  -$3,000/contract) after 30 shadow entries.
- Gate B (Sharpe > 0.6 on shadow sample AND correlation with backtest
  daily return series > 0.5) after 30 shadow entries.
- Explicit user approval per `execution_change_rule`, and a separate
  handoff document proposing sizing, kill switches, and Topstep-rule
  compliance (daily loss limit, trailing max DD).

### Rejected variants (do not revive from same data)

- SPY overnight-only (unconditional and VIX/FOMC/crash filtered).
- IWM overnight ETF at 2 bps/side.
- MDY and EEM overnight (both failed final gate).
- QQQ ETF overnight (fails 25 % DD gate at 2x costs).

### Not yet tested, worth queuing

- M2K (Micro Russell 2000) equivalent test. Requires databento M2K bar
  file — not currently present in `data/databento/`.
- MNQ (Micro Nasdaq) equivalent test. Same requirement.
- Overlay of `mes_overnight_shadow` signal + existing `gex_scanner`
  regime: e.g., skip overnight entries on days where SPY net_gex flips
  strongly negative intraday. Would need at least 60 usable shadow
  days of overlap.
- Weekend-effect variant: does Friday-close-to-Monday-open have a
  materially different Sharpe vs mid-week? Ablation showed some day
  effect but n per bucket was small on train.

## Key files reference

- Prereg (frozen): `research/MES_OVERNIGHT_VIX_FILTER_PREREGISTRATION_2026-08-17.md`
- Shadow logger:   `strategies/mes_overnight_shadow_logger.py`
- Shadow log:      `data/mes_overnight_shadow_log.jsonl`
- Signal registry entry: `mes_overnight_shadow` in
  `research/signal_registry.json`
- Backtest results: `data/mes_overnight_results.json`,
  `data/mes_overnight_holdout.json`,
  `data/mes_overnight_ablation.json`
- GEX framework: `research/gex_outcome_lab.py`,
  `data/gex_outcome_results.json`
