# Preregistration: Overnight-Session Drift on Broad-Market Equities

Date: 2026-08-17
Status: frozen before running any simulation
Owner: Claude (research only, no execution)

## Relationship to Prior Test

An earlier unconditional overnight-drift test on SPY and QQQ over
2000-2015 (preregistration 2026-07-19) FAILED at the development gate on
SPY and at the selection drawdown gate on QQQ. This document specifies
a DIFFERENT hypothesis: that the effect is real but conditional on
volatility regime and event calendar, and that it extends to the pre-2000
period. Because the counterfactuals below were NOT part of the earlier
protocol, they cannot be "rescued" onto the earlier baseline; they must
stand or fall on this new, longer, gated design.

## Hypothesis

The overnight session (US-cash close to next US-cash open) has captured
the overwhelming majority of the S&P 500's cumulative return since the
early 1990s while the intraday RTH session has contributed near zero on
net (Cliff/Cooper/Gulen 2008, Kelly/Clark 2011, Lou/Polk/Skouras 2019).
The excess overnight return is hypothesized to compensate holders for
overnight-gap risk and to reflect systematic buy pressure from ETF
creation flows and end-of-day rebalancing.

If real and persistent, an "overnight-only" rule that holds SPY from
cash close to next cash open and stays flat intraday should:

1. Produce a positive expectancy per trade net of realistic friction.
2. Deliver a higher Sharpe than a comparable buy-and-hold benchmark
   because it participates only in the return-bearing session while
   avoiding intraday noise.
3. Continue to work post-2020 despite the well-known publication and
   the 0DTE-driven compression of intraday variance.

## Frozen Test Specification

- Primary instrument: SPY (daily open/close, auto-adjusted, yfinance).
- Executability instrument: MES front-month futures (1-minute bars,
  Databento `data/databento/mes_v0_1m_2022-01-01_2026-07-19.dbn.zst`),
  used to confirm the same edge survives on the vehicle the flip-bot
  actually trades on Topstep.
- Rule (baseline v1): at each trading day t, buy at the SPY close of t
  and sell at the SPY open of t+1 (skip weekends and holidays natively).
  Flat between t+1 open and t+1 close.
- Position: 100% of a $1,000 model account.
- Costs: 0.01% per side (2 bps round-trip), stressed at 2x and 3x.
- MES executability adjustment: use the 4:00 pm ET 1-min close as
  entry and the next 9:30 am ET 1-min open as exit, apply 0.25 tick
  bid/ask crossing per side ($1.25 per contract) plus $0.35 commission
  per side. Convert to return-space by dividing MES tick P&L by notional.
- Counterfactual overlays (evaluated once, not tuned):
  - v2: skip trade when VIX close is above 25.
  - v3: skip trade when a scheduled FOMC statement falls on t+1.
  - v4: skip trade when the SPY close of t is more than 2 % below the
    prior close (crash-continuation filter).

## Splits and Sequential Gates

- Development 1993-2010 in three sub-regimes (1993-1999, 2000-2004,
  2005-2010). Gate: positive total return after base costs in all
  three sub-regimes and Sharpe > 0.3 on the combined window.
- Selection 2011-2020. Gate: positive at base and 2x costs, Sharpe
  > 0.3, max intraday-equity DD > -20 %.
- Final 2021-2026. Gate: positive at base and 2x costs, profit
  factor >= 1.05, Sharpe > 0.3, max DD > -20 %.
- Executability confirmation (MES) 2022-2026. Gate: strategy
  expectancy in ticks after applied friction is positive and
  correlation with SPY overnight return series is > 0.9.

## Explicit Limits

- One instrument, one rule per counterfactual. No window tuning.
- Counterfactuals are diagnostic only. Only the baseline v1 is
  evaluated against promotion gates. v2/v3/v4 report deltas.
- Failure at any gate = rejected, no re-fitting.
- A pass permits paper forward-testing on MES via shadow scanner only.
  Live routing requires a separate promotion review with the
  profitability evidence framework.
