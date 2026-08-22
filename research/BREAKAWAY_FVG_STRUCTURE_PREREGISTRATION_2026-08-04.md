# Preregistration: MES Breakaway FVG + Structure Challenger

Date: 2026-08-04
Status: frozen before simulation
Authority: research only; no orders, no gate or sizing authority

## Public Claim Being Tested

The advertised Breakaway Bot describes entries from a fair-value gap after a
structural break, with automatic stop, target, and breakeven management. No
public cost-adjusted ledger or drawdown series was found. This protocol tests a
mechanical proxy for the disclosed logic, not proprietary code.

## Frozen Rule

- Instrument: one MES contract.
- Data: corrected Databento MES one-minute RTH CSV, aggregated causally to 5m.
- Entry window: 09:45 through 11:30 ET.
- Maximum one trade per session; earliest valid setup wins.
- Structure: current 5m close breaks the prior six completed 5m highs/lows.
- Displacement: candle body >= 0.60 of ATR(14), volume >= 1.20x the prior
  20-bar mean, and candle direction agrees with the break.
- FVG: same completed break bar creates a three-candle imbalance of at least
  four MES ticks.
- Entry: first midpoint touch within the next six 5m bars.
- Stop: one tick beyond the lowest/highest price of the structure lookback and
  three-bar FVG formation. Skip if risk is below 8 or above 40 ticks.
- Target: 2.0R.
- Breakeven: armed only after a completed later one-minute bar reaches 1.0R;
  it applies from the next bar. No favorable intrabar ordering assumptions.
- Exit: stop, target, breakeven, or 15:55 ET flatten.
- Same-bar adverse and favorable levels: adverse level wins.
- Costs: $1.24 commission plus one tick slippage per side; doubled-cost stress.

## Sequential Gates

- Development: first 70% of sessions, split into three chronological regimes.
  All regimes require at least 30 trades, positive expectancy, and PF > 1.0.
- Selection: next 15%, opened only if development passes. Requires >= 30
  trades, PF >= 1.20, positive expectancy, and positive doubled-cost expectancy.
- Final: last 15%, opened only if selection passes. Requires >= 30 trades,
  PF >= 1.20, positive doubled-cost expectancy, and max drawdown <= $200.

The historical final slice has been consumed by related MES research. Even a
full pass cannot authorize execution and requires 30 forward shadow outcomes.
No parameter changes or rescue variants are permitted on this dataset.

