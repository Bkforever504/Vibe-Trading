# MES Final-Half-Hour Reversal Confirmation Preregistration

Registered: 2026-07-19, after close-momentum development failed and before
evaluating this reversal on selection or final sessions.

## Discovery Evidence

All eight same-direction close-momentum candidates had negative expectancy in
all three development regimes. No candidate touched selection or final data.
This motivates one fixed opposite-direction confirmation test.

## Frozen Configuration

- Instrument: one MES contract.
- Opening signal: `09:59 close / 09:30 open - 1`.
- Minimum absolute opening return: 0.10%.
- Direction: trade opposite the opening return.
- Entry: 15:30 ET bar open.
- Stop: 40 ticks / 10 points / $50 before costs.
- Exit: stop or 15:59 ET close.
- Standard costs: $4 commission plus two ticks total slippage.
- Doubled costs: $8 commission plus four ticks total slippage.
- No other filters and no parameter grid.

## Sequential Gate

Use only the 15% selection period first. Do not evaluate the final 15% unless
selection has at least 30 trades, positive expectancy, PF >= 1.20, maximum
drawdown <= $200, positive doubled-cost expectancy, and doubled-cost PF >= 1.10.

If selection passes, evaluate the final period once using identical mechanics.
Final confirmation requires the same gates. Passing permits Monte Carlo and
forward simulation only, never live or prop-firm execution.
