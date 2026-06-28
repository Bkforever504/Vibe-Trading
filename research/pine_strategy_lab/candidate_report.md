# Pine Strategy Lab Candidate Report

Research filter only. No strategy promoted to live without paper-forward validation and execution guard sign-off.

| Strategy | Status | Confidence | PF | OOS PF | PBO | Sharpe | WR% | Trades | Max DD | Reject Reasons | Red Flag Warnings |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| VWAP Pullback Candidate | paper_candidate | 7.7 | 1.65 | 1.22 | 0.00 | 0.00 | 0.0% | 88 | 8.2% | - | strategy() missing commission parameters — backtest overstates real-world returns; strategy() missing slippage parameter — fills at exact price not achievable live |
| NoCitation ORB | rejected | 6.8 | 1.80 | 1.25 | 0.00 | 0.00 | 0.0% | 80 | 9.0% | unknown or non-open-source license | strategy() missing commission parameters — backtest overstates real-world returns; strategy() missing slippage parameter — fills at exact price not achievable live |
| HighDD EMA Trend | rejected | 5.5 | 1.75 | 1.20 | 0.00 | 0.00 | 0.0% | 95 | 32.0% | drawdown exceeds research limit | strategy() missing commission parameters — backtest overstates real-world returns; strategy() missing slippage parameter — fills at exact price not achievable live |
| OverfitRSI Swing | rejected | 3.6 | 2.00 | 0.90 | 0.00 | 0.00 | 0.0% | 22 | 8.4% | too few trades, weak out-of-sample profit factor, weak walk-forward pass rate | strategy() missing commission parameters — backtest overstates real-world returns; strategy() missing slippage parameter — fills at exact price not achievable live |
| Moonshot Screamer 2M% | rejected | 2.0 | 850.00 | 0.75 | 0.00 | 0.00 | 0.0% | 12 | 3.1% | too few trades, profit factor is suspiciously high, weak out-of-sample profit factor, weak walk-forward pass rate | strategy() missing commission parameters — backtest overstates real-world returns; strategy() missing slippage parameter — fills at exact price not achievable live |
