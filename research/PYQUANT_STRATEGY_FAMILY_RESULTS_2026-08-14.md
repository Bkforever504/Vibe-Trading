# PyQuant Strategy-Family Evaluation - 2026-08-14

## Decision

Do not add another production bot. The repository's existing canonical
12-month, top-two, weekly momentum lane is the strongest tested implementation
of the strategy families in the screenshots. Keep it shadow-only because its
eligible forward sample contains only four resolved rotations and their summed
portfolio return is -0.739 percentage points.

## Evidence Basis

The families are legitimate research topics rather than secret strategies:

- Moskowitz, Ooi, and Pedersen document time-series momentum across futures:
  https://research-api.cbs.dk/ws/portalfiles/portal/58851003/time_series_momentum_lasse_heje.pdf
- Faber tests relative-strength selection in sectors and global asset classes:
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1585517
- Faber's tactical-allocation paper studies trend filters and asset allocation:
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=962461
- Blitz and van Vliet document the low-volatility effect:
  https://www.robeco.com/docm/docu-the-volatility-effect-2007.pdf
- Currency carry is a priced risk strategy with material drawdowns, not a
  price-momentum proxy: https://www.nber.org/papers/w20433.pdf

## Tournament Design

- Adjusted daily ETF closes from 2007 onward.
- Every signal delayed by one trading day.
- Six basis points per traded notional; doubled-cost replay also required.
- Fixed definitions only; no parameter sweep.
- Development through 2021, selection in 2022-2024, final from 2025 onward.
- Gate requires positive selection and final CAGR, higher full-period Sharpe
  than SPY, lower maximum drawdown than SPY, and positive doubled-cost CAGR.

## Results

| Strategy | CAGR | Sharpe | Max DD | 2x-cost CAGR | Selection CAGR | Final CAGR | Gate |
|---|---:|---:|---:|---:|---:|---:|---|
| Existing canonical 12m top-2 weekly | 11.11% | 0.693 | 24.83% | 10.22% | 14.08% | 38.15% | pass |
| Sector momentum 12m top-3 monthly | 10.32% | 0.659 | 37.55% | 9.98% | 15.50% | 21.10% | pass |
| Sector low-vol + positive momentum | 8.93% | 0.675 | 34.69% | 8.63% | 8.66% | 8.79% | pass |
| Asset-class momentum 12m top-3 | 7.57% | 0.624 | 26.33% | 7.36% | 1.29% | 25.62% | fail |
| Asset-class 200d trend | 7.65% | 0.642 | 35.95% | 7.34% | -2.38% | 21.36% | fail |
| SPLV/USMV equal-weight proxy | 11.20% | 0.847 | 34.68% | 11.19% | 3.98% | 9.03% | fail vs same-date SPY |

Same-date SPY for the 2007-starting strategies produced 11.10% CAGR, 0.635
Sharpe, and 55.19% maximum drawdown. The low-volatility ETF proxy starts later;
over its same dates SPY had 15.37% CAGR, 0.939 Sharpe, and 33.72% drawdown.

## Interpretation

The best result is already deployed as a shadow lane. Sector momentum and the
low-volatility overlay are useful challengers, but their drawdowns are larger
and their returns lower than the canonical lane. Backtest superiority is not
permission to trade: four forward outcomes are insufficient, and the current
forward sum is negative. Require at least 30 eligible resolved rotations and a
positive after-cost expectancy before considering any paper-capital promotion.

FX carry was not tested. A valid replication needs point-in-time rate
differentials and executable forward or spot-plus-funding returns. Currency ETF
prices alone would mislabel momentum as carry.

All outputs are research-only. Execution is disabled and no broker interface is
imported.
