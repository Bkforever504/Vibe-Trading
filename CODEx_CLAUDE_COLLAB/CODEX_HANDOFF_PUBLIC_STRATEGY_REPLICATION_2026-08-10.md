# Claude Code Handoff: Public MES Strategy Replication Tournament

Date: 2026-08-10

Experiment: `MES-PUBLIC-REPLICATION-01`

## Bottom Line

Codex translated five public ES/MES strategy concepts into deterministic, preregistered rules and tested them under one conservative execution model. None survived. Do not deploy, paper-route, tune, or promote any of these five rules under this experiment identifier.

This is a useful negative result: public setup descriptions are not a substitute for executable edge. Four challengers have only a few cents to $0.81 of gross expectancy per MES trade before friction. The best raw result, the ORB control, earns $2.71 gross per trade but cannot cover the frozen $4.98 base round trip.

No orders were submitted. Topstep Combine simulations were correctly skipped because there were zero historical survivors.

## Files Added

- `research/MES_PUBLIC_STRATEGY_REPLICATION_PREREGISTRATION_2026-08-10.md`
- `research/mes_public_strategy_replication_tournament.py`
- `agent/tests/test_mes_public_strategy_replication_tournament.py`
- `data/mes_public_strategy_replication_results.json`
- `research/public_futures_replication_query_plan_2026-08-10.json`
- `research/last30days_raw/public-mes-es-futures-strategies-with-exact-reproducible-rules-raw-public-replication-2026-08-10.md`

This handoff is also new. The worktree contains extensive unrelated user and Claude changes; do not revert or normalize them.

## Frozen Public Translations

1. `orb_breakout_control`: 15-minute range, one-tick close breakout with live-VWAP confirmation, next-bar entry, signal-bar stop, 1.5R target.
2. `ib_failure_to_vwap`: first-hour initial balance, one-tick boundary failure and close back inside, next-bar fade to signal-time VWAP.
3. `vwap_reclaim_retest`: five closes on one side, reclaim, retest within two ticks, directional close, next-bar entry, 1.5R target.
4. `vwap_band_reentry`: open outside causal 1.5-standard-deviation VWAP band and close back inside, next-bar fade to VWAP.
5. `opening_drive_vwap_pullback`: first-15 range at least the prior-20-session median, 60% displacement, outer-20% close, first confirmed VWAP pullback, 2R target.

The preregistration contains exact rules and public-source URLs. These are mechanical translations, not claims that any source trader has verified profitability.

## Data And Execution Controls

- Dataset: `examples/mes_v0_1m_2022-01-01_2026-07-19_rth.csv`
- Evaluated period: 2024-01-02 through 2026-07-17
- Eligible complete, single-contract sessions: 618
- Chronology: 2024 discovery diagnostic, 2025 selection, 2026 holdout within this experiment
- Evidence status: consumed history, not independent confirmation
- One MES, one trade per strategy per session
- Entry only after signal completion, at next-bar open
- Stop wins same-bar stop/target ambiguity
- Flatten at 15:55 ET
- Risk limited to 4-60 ticks
- Base friction: one tick plus $1.24 commission per side, $4.98 round trip
- Stress: 2x and 3x complete friction, one-extra-bar entry delay, best 1% of trades set to zero
- One-sided 99% circular block-bootstrap lower bound due to five-family Bonferroni correction
- Execution locks: `execution_enabled=false`, `can_submit_orders=false`, `orders_submitted=0`

## Exact Results

| Strategy | Trades | Gross expectancy | Base expectancy | 2x expectancy | 2026 2x expectancy | 2026 PF | Gates passed |
|---|---:|---:|---:|---:|---:|---:|---:|
| ORB control | 591 | $2.7147 | -$2.2653 | -$7.2453 | -$1.2050 | 0.9358 | 2/10 |
| VWAP reclaim/retest | 506 | $0.4125 | -$4.5675 | -$9.5475 | -$10.3423 | 0.4500 | 2/10 |
| IB failure to VWAP | 519 | $0.8100 | -$4.1700 | -$9.1500 | -$10.4482 | 0.5054 | 2/10 |
| VWAP band reentry | 617 | $0.2174 | -$4.7626 | -$9.7426 | -$11.2142 | 0.4975 | 2/10 |
| Opening-drive pullback | 96 | -$3.4635 | -$8.4435 | -$13.4235 | -$23.3254 | 0.2339 | 2/10 |

Every candidate passed only the 2025 and 2026 sample-count gates. Every edge, robustness, quarter-stability, and bootstrap gate failed.

Execution-budget diagnostic:

- ORB can tolerate at most $1.3573 per side on average, versus the modeled $2.49.
- IB failure can tolerate $0.4050 per side.
- VWAP reclaim can tolerate $0.2063 per side.
- VWAP-band reentry can tolerate $0.1087 per side.
- Opening-drive pullback has no non-negative execution budget because gross expectancy is negative.

The full record, stage metrics, annual and quarterly results, trade ledger, stress results, and gate booleans are in `data/mes_public_strategy_replication_results.json`.

## Audit Results

Generated-trade invariant audit found:

- no duplicate strategy/day trades
- no entry at or before signal time
- no risk outside 4-60 ticks
- no invalid long or short stop/target geometry
- no execution authority

Focused tests:

```powershell
python -m pytest agent/tests/test_mes_public_strategy_replication_tournament.py -q
```

Result: `6 passed`.

Full suite:

```powershell
python -m pytest agent/tests -q
```

Result: `4527 passed, 4 skipped, 4 warnings` in 229.49 seconds.

Compilation:

```powershell
python -m py_compile research/mes_public_strategy_replication_tournament.py agent/tests/test_mes_public_strategy_replication_tournament.py
```

Result: pass.

Ruff could not be launched through `uv` because the existing dependency graph fails while building `zigzag==0.3.2`: its legacy `Cython>=^0.29` metadata is rejected. This is unrelated to the tournament changes.

## Reproduce

```powershell
python research/mes_public_strategy_replication_tournament.py
```

Expected headline: 618 eligible sessions, zero historical survivors, ORB as the least-bad diagnostic candidate.

## Claude's Next Work

1. Review the new tournament and test files for causal timing and conservative execution. Do not change frozen thresholds under `MES-PUBLIC-REPLICATION-01`.
2. Treat the five results as rejected translations. Do not rescue them by searching adjacent thresholds on the same data.
3. Preregister a separate experiment, suggested ID `MES-MICROSTRUCTURE-FILTERED-ORB-01`, only if the design can be fixed before inspecting outcomes.
4. Use signal-time-only fields from the existing BBO/OFI caches:
   - `data/databento/mes_bbo_valid_1s_2024_2026.parquet`
   - `data/databento/mes_bbo_ofi_30s_2024_2026.parquet`
5. The new experiment's economic target must be explicit: raise holdout gross expectancy above the real round-trip friction with a safety margin, then remain positive at 2x cost. Classification accuracy or win rate alone is not success.
6. Limit the preregistered microstructure overlays to a small family, apply familywise correction, and retain the same next-bar, stop-first, delayed-entry, best-trade-removal, and 2026 holdout controls.
7. If no overlay survives, archive ORB for this data regime and move to a genuinely different information source or horizon. Do not buy a Combine or enable execution.
8. Independent forward practice remains mandatory. Historical results in this repo have been repeatedly consumed and cannot authorize capital.

## Safety Boundary

This handoff does not authorize orders, a Topstep purchase, credentials, scheduler activation, or any change to production execution. Any future survivor still requires independent review, at least 60 resolved frozen forward-practice outcomes over three months, positive 2x-cost forward expectancy, forward profit factor at least 1.20, and explicit human approval.
