# Swing Drawdown And Profit Results

Date: 2026-08-13
Mode: research only; no execution authority

## Verdict

No tested policy increased absolute selection-period profit while also reducing
drawdown. The closest Pareto improvement is `breadth_bil_cash`: it materially
improved risk-adjusted return while sacrificing less than one percentage point
of total return over 2023-2025.

| Policy | 2023-2025 total return | Max drawdown | Calmar |
|---|---:|---:|---:|
| Equal-weight baseline | 126.738% | -21.784% | 1.538 |
| Breadth + BIL residual cash | 125.934% | -17.038% | 1.956 |

This is a 21.8% relative reduction in maximum drawdown, a 27.2% improvement in
Calmar, and a 0.804 percentage-point reduction in total return.

Development moved in the same direction: breadth plus BIL returned 532.320%
versus 461.231% for baseline, with drawdown reduced from 33.225% to 25.179%.
The five resolved 2026 periods returned 6.389% for breadth plus BIL versus
72.400% for baseline. The baseline result is highly concentrated in a small
sample and cannot establish a durable advantage.

## Rejected Approaches

- `initial_stop_2_5atr`: 73.382% selection return, -22.378% drawdown.
- `chandelier_3atr`: 72.290% selection return, -19.336% drawdown.
- `asymmetric_profit_lock`: 52.083% selection return, -21.143% drawdown.
- `inverse_volatility`: reduced selection drawdown to 17.132%, but return fell
  to 113.282%.
- `combined_risk_overlay`: reduced selection drawdown to 12.131%, but return
  fell to 44.364%.

The result is consistent: trade-level stops clip the momentum strategy's right
tail, while portfolio exposure controls reduce drawdown more efficiently.

## Integrity Findings

- Incomplete 20-session windows are excluded; the prior partial-window mark
  was removed from all three labs.
- Ordinary costs are 10 bps and stress costs are 30 bps.
- Indicators use completed data and entries use the next session open.
- The universe has survivorship bias and adjusted OHLC is not executable quote
  data.
- Some periods contain only one qualifying symbol, producing 100% single-name
  concentration in equal-weight variants. This blocks deployment.
- No candidate passed every promotion gate. No configuration or broker setting
  was changed, and no order was submitted.

## Operational Decision

Keep `breadth_bil_cash` in research/shadow status. Before any paper promotion,
require a point-in-time constituent universe, a 35% maximum single-name weight,
at least 12 new resolved monthly observations, and positive performance after
30-bps costs without dependence on the best observation.

Artifacts:

- `data/swing_risk_overlay_results.json`
- `data/swing_exit_overlay_results.json`
- `data/swing_cash_sleeve_results.json`
