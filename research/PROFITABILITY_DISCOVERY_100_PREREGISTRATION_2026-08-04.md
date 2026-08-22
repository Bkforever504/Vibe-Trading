# Preregistration: 100-Trial MES Profitability Discovery Tournament

Date: 2026-08-04
Status: frozen before registry generation and simulation
Authority: research only; no order, gate, sizing, or promotion authority

## Purpose

Evaluate 100 explicitly counted strategy trials without selecting a lucky
backtest and calling it profitability. The tournament contains ten causal
families and ten frozen variants per family.

Families: opening-range breakout, opening-range failed break, prior-day-level
breakout, prior-day-level reclaim, VWAP trend pullback, VWAP deviation fade,
opening impulse continuation, opening impulse reversal, compression breakout,
and range-expansion reversal.

## Common Execution Model

- One MES contract and at most one trade per session.
- Corrected Databento one-minute RTH data, causally aggregated to 5m.
- Entry at a completed signal bar close; management begins next bar.
- Entry window 09:45-14:30 ET; flatten by 15:55 ET or after 60 minutes.
- Same-bar stop and target resolves to the stop.
- Commission $1.24/side and one MES tick slippage/side; doubled-cost stress.
- Each family uses five frozen threshold levels. Variants 0-4 use 1.5R;
  variants 5-9 repeat those thresholds with a volume confirmation and 2.0R.
- Stops by threshold level: 4, 6, 8, 10, and 12 MES points.

## Data Governance

- Discovery uses only the first 70% of sessions.
- Discovery is split into three chronological regimes.
- The next 15% selection and last 15% final slices remain unopened.
- Existing documented attempts: 415. These 100 raise the effective denominator
  to at least 515, regardless of failures or duplicate-looking outcomes.

## Discovery Survivor Gate

Every chronological regime must contain at least 20 trades, positive
after-cost expectancy, and PF > 1.0. Aggregate development expectancy must
remain positive at doubled costs. The one-sided mean-return p-value must pass
Bonferroni alpha `0.05 / 515`. Passing only creates a candidate for a separately
authorized selection run; it cannot enable execution.

No variants may be added, removed, or adjusted after viewing results. All 100
results, including failures, must remain in the report.

