# Pine Strategy Sweep Report

Research only. Sweep winners still need red-flag review, paper-forward validation, and execution guard approval.

PBO score: 0.25 (0.00=stable, 1.00=likely overfit)

| Strategy | Symbol | Window | Params | Status | Conf | PF | OOS PF | WF | Sharpe | WR% | Trades | Max DD |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| momentum_rotation | UNIVERSE[10] | 2018-01-01:2024-12-31 | lookback_months=12, top_n=2 | paper_candidate | 9.0 | 1.92 | 1.79 | 0.80 | 0.79 | 64.5% | 76 | 24.3% |
| momentum_rotation | UNIVERSE[10] | 2018-01-01:2024-12-31 | lookback_months=12, top_n=3 | rejected | 7.0 | 1.59 | 1.47 | 0.80 | 0.70 | 56.8% | 118 | 29.2% |
| momentum_rotation | UNIVERSE[10] | 2018-01-01:2024-12-31 | lookback_months=12, top_n=1 | rejected | 6.5 | 5.60 | 2.06 | 0.80 | 0.95 | 63.0% | 27 | 26.0% |
| momentum_rotation | UNIVERSE[10] | 2018-01-01:2024-12-31 | lookback_months=6, top_n=1 | rejected | 6.1 | 1.30 | 1.68 | 0.80 | 0.31 | 46.6% | 58 | 39.4% |
| momentum_rotation | UNIVERSE[10] | 2018-01-01:2024-12-31 | lookback_months=6, top_n=3 | rejected | 6.0 | 1.20 | 1.30 | 0.60 | 0.38 | 58.4% | 166 | 32.0% |
| momentum_rotation | UNIVERSE[10] | 2018-01-01:2024-12-31 | lookback_months=6, top_n=2 | rejected | 5.7 | 1.18 | 1.30 | 0.60 | 0.30 | 56.9% | 116 | 32.7% |
| momentum_rotation | UNIVERSE[10] | 2018-01-01:2024-12-31 | lookback_months=3, top_n=3 | rejected | 5.1 | 1.42 | 0.99 | 0.60 | 0.67 | 58.2% | 189 | 28.6% |
| momentum_rotation | UNIVERSE[10] | 2018-01-01:2024-12-31 | lookback_months=3, top_n=1 | rejected | 5.1 | 1.82 | 0.64 | 0.80 | 0.59 | 53.8% | 80 | 28.8% |
| momentum_rotation | UNIVERSE[10] | 2018-01-01:2024-12-31 | lookback_months=3, top_n=2 | rejected | 4.8 | 1.54 | 0.76 | 0.60 | 0.67 | 59.1% | 137 | 29.2% |
