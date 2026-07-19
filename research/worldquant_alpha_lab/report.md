# WorldQuant Alpha Lab Report

Research only. These are cross-sectional factor tests, not bot signals and not execution gates.

| Alpha | Status | Conf | PF | OOS PF | WF | PBO | Sharpe | Trades | Max DD | Description | Reject Reasons |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| alpha_003 | rejected | 5.1 | 1.13 | 4.15 | 0.20 | 0.00 | 0.16 | 15 | 8.3% | Open-price rank vs volume rank divergence | too few trades, weak walk-forward pass rate |
| alpha_004 | rejected | 2.0 | 0.92 | 0.97 | 0.40 | 0.00 | -0.46 | 121 | 41.9% | Low-price time-series rank reversal | drawdown exceeds research limit, weak out-of-sample profit factor, weak walk-forward pass rate |
| alpha_006 | rejected | 1.8 | 0.83 | 0.89 | 0.20 | 0.00 | -1.05 | 741 | 62.6% | Open/volume rolling correlation reversal | drawdown exceeds research limit, weak out-of-sample profit factor, weak walk-forward pass rate |
| alpha_002 | rejected | 1.7 | 0.74 | 0.95 | 0.20 | 0.00 | -1.80 | 864 | 69.0% | Volume acceleration vs intraday return divergence | drawdown exceeds research limit, weak out-of-sample profit factor, weak walk-forward pass rate |
| alpha_012 | rejected | 0.9 | 0.65 | 0.58 | 0.00 | 0.00 | -2.51 | 989 | 85.4% | Volume-change sign times negative price delta | drawdown exceeds research limit, weak out-of-sample profit factor, weak walk-forward pass rate |
