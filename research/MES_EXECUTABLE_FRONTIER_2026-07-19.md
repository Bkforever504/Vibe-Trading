# MES Executable Strategy Frontier - 2026-07-19

## Decision

No tested MES intraday configuration satisfies both the requested income target and minimal-drawdown constraint for a $1,000 account. The NinjaTrader Sim101 execution task remains disabled, and the stale 40/80 candidate is blocked in code.

## Corrected Research

- Corrected the pullback replay so every signal uses the same fixed stop and target geometry as the NinjaTrader ATM bracket.
- Ran 6,400 broad configurations on 597 ES hourly trading days, using three development regimes and a locked final 120-day holdout.
- Ran nested executable-only grids with full exits and risk caps of 40 ticks (1,600 rows), 60 ticks (2,400 rows), and 80 ticks (3,200 rows).
- Tested the deep SPY one-minute cache: 447,767 bars from 2022-01-03 through 2026-07-17.
- Re-ran 168 SPY ORB/volume configurations and the ORB sensitivity grid.
- Applied base, doubled, and tripled execution costs plus 20,000-path Monte Carlo resampling.

## MES Results

### 40-tick maximum stop

- Development survivors: 22.
- Locked-holdout robust finalists: 0.
- Verdict: the actual 40/80 ATM candidate has no execution-equivalent evidence and is retired.

### 60-tick maximum stop

- One robust finalist: pullback, 3-point breakout, 16-tick tolerance, daily 20-session trend, 60-tick stop, 2.5R target.
- Full sample: 54 trades, $380.25 total, $7.04 expectancy, 1.27 profit factor, $493.75 maximum drawdown.
- Doubled costs: $2.19 expectancy and 1.078 profit factor.
- Monte Carlo at base costs: 73.79% probability of at least 30% drawdown and 30.11% probability of at least 50% drawdown.
- Verdict: rejected for the $1,000 account.

### 80-tick maximum stop

- Best full-exit finalist: 80-tick stop and 1R target.
- Full sample: 54 trades, $359 total, $6.65 expectancy, 1.256 profit factor, $451.25 maximum drawdown.
- Doubled costs: $0.94 expectancy and 1.034 profit factor.
- Monte Carlo at base costs: 74.93% probability of at least 30% drawdown and 31.09% probability of at least 50% drawdown.
- Verdict: rejected for the $1,000 account.

## SPY Results

- Standard 5-minute ORB remained negative in both training and holdout samples.
- The 15-minute ORB plus opening relative volume produced +0.0594R holdout expectancy, but doubled slippage reduced it to -0.0061R.
- The best CMF-direction overlay produced +0.0806R holdout expectancy, but only +0.0039R at doubled costs; its 95% bootstrap interval crossed zero.
- Verdict: useful shadow research, not evidence for automated options or futures deployment.

## Capital Reality

- A 40-tick MES stop risks about $50 before costs, or over 5% of a $1,000 account.
- A 60-tick stop risks about $75 before costs; an 80-tick stop risks about $100.
- Earning $100 per day from $1,000 requires roughly 10% daily return. The tested strategies averaged about $0 to $3 per market day and cannot support that target without unacceptable leverage.

## Approved Path

- Keep NinjaTrader MES execution disabled until deep one-minute MES/ES data produces a one-contract finalist with positive independent holdout expectancy, doubled-cost profit factor at least 1.15, and Monte Carlo probability of 30% drawdown below 10%.
- Continue the isolated half-deployed ETF momentum paper lane. Its consumed 2025+ result was +21.25% with 6.67% maximum drawdown and +20.56% under doubled costs, but it still requires 26 weekly forward decisions before consideration for live capital.
- Do not convert underlying SPY results into option-profit claims without historical option bid/ask replay.
