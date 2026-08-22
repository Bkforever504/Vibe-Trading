# Initial Balance / Opening Range Preregistration - 2026-07-25

## Purpose

Independently test the social claims supplied on 2026-07-25 without changing
any live, paper, scheduler, broker, or execution-gate behavior.

## Data

- MES: local Databento one-minute RTH bars, 2022-01-03 through 2026-07-17.
- SPY: local Alpaca IEX one-minute cache, 2022-01-03 through 2026-07-17.
- NQ: local five-minute bars, approximately 60 calendar days. NQ is a
  portability diagnostic only because the sample is too short.

MES is used as the liquid ES/MES price-path proxy. Results are expressed in
R-multiples after instrument-specific costs. SPY tests the underlying only;
no option return is inferred.

## Frozen definitions

- Initial Balance (IB): 09:30 through 10:29:59 America/New_York.
- 15-minute Opening Range (OR): 09:30 through 09:44:59.
- High-first / low-first: timestamp of the final range high versus final range
  low. Ties are unknown and do not generate an extreme-order trade.
- Close location: `(range close - range low) / (range high - range low)`.
- Break by wick: a later bar trades strictly beyond a range boundary.
- Break by close: a later bar closes strictly beyond a range boundary.
- Aggressive close: close location at or below 25% after high-first, or at or
  above 75% after low-first.

## Fixed strategy challengers

Each challenger takes at most one trade per session.

1. `extreme_order_sweep`: high-first shorts toward the range low; low-first
   longs toward the range high.
2. `close_confirmed_sweep`: the same trade only when high-first closes below
   the midpoint or low-first closes above it.
3. `aggressive_close_sweep`: the same trade only with an aggressive close.
4. `close_breakout_1r`: after the first completed bar closes beyond the range,
   enter at the next bar open, stop at the opposite range boundary, target 1R.

Sweep trades enter at the first bar open after the range. Their target is the
opposite boundary and their stop is an equal distance from entry, producing a
fixed 1:1 gross reward/risk test.

## Conservative execution

- If stop and target are both touched in one bar, stop wins.
- MES: one tick slippage per side plus $2.48 round-trip commission, $5/point.
- MNQ diagnostic: one tick slippage per side plus $2.48 round-trip commission,
  $2/point.
- SPY: one basis point per side.
- No target is credited from the range-forming bars.
- No parameter optimization is permitted in this experiment.

## Reporting

Report descriptive frequencies and executable expectancy separately. For each
strategy report trade count, target-hit rate, positive-net-return rate, gross
and net expectancy in R, average costs in R, profit factor, maximum drawdown,
and deterministic five-trade moving-block confidence intervals. Report both
the ordinary 95% interval and a familywise 95% interval adjusted for the eight
fixed strategy/window tests.

Chronological 60% / 20% / 20% segments are reported as development,
selection, and diagnostic-later periods. These periods are not globally
untouched because the underlying datasets were used by earlier research.

## Promotion rule

This experiment cannot promote a strategy. A result may become a forward
shadow candidate only if all three MES segments have:

- at least 30 trades,
- positive expectancy,
- profit factor at least 1.10,
- and the aggregate 95% expectancy interval excludes zero.

NQ and SPY are corroboration only. Any option or funded-futures deployment
requires its own point-in-time forward evidence and execution-specific review.

## Adversarial data-quality amendment

Before accepting the first run, an independent reviewer found that the SPY IEX
cache contains incomplete sessions and start-labeled 16:00 bars. This amendment
changes no signal or strategy parameter:

- exclude the 16:00 start-labeled bar,
- require every accepted one-minute session to contain the complete 09:30
  through 15:59 grid,
- require every accepted five-minute session to contain the complete 09:30
  through 15:55 grid,
- report raw, accepted, and excluded session counts,
- and distinguish target-hit rate from trades that merely finish positive at
  the end-of-day exit.

The same reviewer noted that Edgeful's exact "aggressive selling," bias, and
break measurement definitions are unavailable. Results therefore test the
transparent frozen proxies above and must not be described as an exact
replication or falsification of Edgeful's proprietary percentages.
