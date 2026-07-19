# MES Deep-Data Validation Plan

## Decision

Do not optimize or enable the NinjaTrader MES strategy on the 32 local minute
sessions. The default 40-tick, 2R configuration lost $265 across 17 trades and
the sample is too shallow for walk-forward selection.

## Data Gate

Use Databento `GLBX.MDP3` continuous `MES.v.0` one-minute OHLCV from 2022-01-01
through the current completed session. The importer excludes detected contract
roll dates and emits Eastern-time RTH CSV data. It estimates cost before any
download and refuses a download above its configured cap.

```powershell
uv run --no-project --with databento --with pandas python scripts/fetch_databento_futures.py --products MES
```

Review the estimate. Download only after confirming it is covered by available
credits:

```powershell
uv run --no-project --with databento --with pandas python scripts/fetch_databento_futures.py --products MES --download --max-cost 5
```

## Validation Design

`research/mes_futures_strategy_search.py` now uses three chronological stages:

1. First 70%: parameter search across three internal market regimes.
2. Next 15%: candidate selection, including doubled trading costs.
3. Final 15%: untouched confirmation test. Candidates are not reordered or
   filtered using this period.

Run only executable one-contract candidates with stops capped at 40 ticks:

```powershell
python research/mes_futures_strategy_search.py --csv examples/mes_v0_1m_2022-01-01_2026-07-19_rth.csv --executable-only --max-stop-ticks 40 --out data/mes_databento_validation.json
```

## Promotion Gates

A candidate remains research-only unless all of these hold:

- At least 30 trades in the untouched final test.
- Positive final-test expectancy and profit factor at least 1.20.
- Positive expectancy and profit factor at least 1.10 under doubled costs.
- Maximum historical drawdown no greater than $200 per MES contract.
- Monte Carlo 95th-percentile drawdown no greater than $300 on a $1,000 model
  account.
- At least 30 additional forward-sim trades with no rule or execution failures.

Passing these gates permits NinjaTrader simulation only. It does not permit live
or prop-firm execution. A separate user-approved readiness review is required.

## Confidence

- Engineering and fail-closed controls: 9/10.
- Current strategy profitability evidence: 3/10.
- Confidence target after deep final test plus forward simulation: 8/10.

A 10/10 profitability claim is not statistically supportable for a trading
strategy. The strongest honest target is high confidence in process, risk
limits, and reproducibility while profitability remains probabilistic.
