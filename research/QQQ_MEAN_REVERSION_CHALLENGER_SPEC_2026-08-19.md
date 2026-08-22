# QQQ Mean-Reversion Challenger Specification

Date frozen: 2026-08-19

## Objective

Test whether a small set of causal, economically motivated changes improves the
QQQ Double 7 and RSI(2) daily mean-reversion baselines after costs and without
opening the existing social-sequence tournament's selection or final holdouts.

This is research and forward-shadow instrumentation only. It cannot submit,
recommend, approve, or promote an order.

## Data boundary

- Instrument: adjusted QQQ daily OHLCV.
- Development data: 2015-01-01 through 2023-01-26.
- Existing sealed selection starts 2023-01-27.
- Existing sealed final starts 2024-10-21.
- Decisions use completed close data. Entries and exits fill at the next open.
- Base round-trip cost: 4 basis points on $10,000 notional.
- Stress round-trip cost: 8 basis points.

The two sealed periods are not read by this experiment.

## Frozen variants

1. `double7_baseline`: close above SMA(200) and at a 7-day closing low; exit
   after a 7-day closing high.
2. `double7_sma200_rising20`: baseline plus SMA(200) higher than 20 sessions ago.
3. `double7_gap_guard_1atr`: skip a next-open entry if its gap is below one
   point-in-time ATR(20) under the signal close.
4. `double7_vol_scaled`: baseline with prior 20-day annualized-volatility
   exposure scaling to a 15% target, clipped to 35%-100%.
5. `double7_exit_sma5`: baseline entry; exit after close exceeds SMA(5).
6. `double7_turn_of_month`: baseline entry only during the last four or first
   three trading sessions of a calendar month.
7. `rsi2_baseline`: close above SMA(200), RSI(2) below 10; exit after RSI(2)
   exceeds 70.
8. `rsi2_sma200_rising20`: RSI2 baseline plus rising SMA(200).
9. `rsi2_gap_guard_1atr`: RSI2 baseline with the same causal next-open gap guard.
10. `rsi2_vol_scaled`: RSI2 baseline with the same volatility scaling.
11. `rsi2_exit_prior_high`: RSI2 entry; exit after close exceeds prior high.
12. `double7_rsi2_hybrid`: require both Double 7 and RSI(2) entry conditions;
    exit after either Double 7 or RSI(2) exit condition.

No combined winner assembled after seeing these results is part of this test.

## Diagnostics

Each trade records net P&L, holding sessions, maximum adverse excursion (MAE),
maximum favorable excursion (MFE), entry gap in ATR units, prior annualized
volatility, SMA(200) slope, drawdown from the 20-day high, weekday, and
turn-of-month status. Exploratory conditional tables may suggest a later
preregistration but cannot promote a rule.

## Gates

A development candidate requires all of the following:

- at least 20 trades in each of three chronological development regimes;
- positive expectancy and profit factor above 1 in every regime;
- positive expectancy at 2x friction;
- positive expectancy after removing the best 1% of trades;
- 95% moving-block-bootstrap lower bound above zero;
- one-sided mean-test p-value below `0.05 / 921`, where 921 includes 909 prior
  effective attempts and these 12 trials.

Even a passing development candidate remains shadow-only. Forward review needs
at least 30 logged trading days and 10 completed signals, then explicit human
approval under the signal-registry policy.

## Research basis

- Stefan Nagel, *Evaporating Liquidity* (2012): reversal returns behave like
  compensation for supplying liquidity and vary with market stress.
- de Groot, Huij, and Zhou, *Another Look at Trading Costs and Short-Term
  Reversal Profits* (2012): liquid instruments and lower turnover matter after
  costs.
- Moreira and Muir, *Volatility-Managed Portfolios* (2017): reducing exposure
  when realized volatility rises can improve risk-adjusted outcomes.
- Milkman Trades' public Double 7 restatement supplied by the user is treated as
  a hypothesis source, not independently audited performance evidence.

