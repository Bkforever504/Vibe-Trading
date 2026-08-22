# Green-Day HTF/LTF Reconstruction Preregistration

Date frozen: 2026-07-25

## Purpose

Determine whether the Flip Bot's profitable SPY cohort came from a repeatable
VWAP/50EMA intraday edge, and whether point-in-time higher-timeframe alignment
improves that edge. Apply the same higher-timeframe labels to the completed
Flip shadow episodes as an independent diagnostic.

This is read-only research. It cannot place orders, alter production settings,
or promote a strategy.

## Evidence Separation

1. Actual Flip trades: include closed SPY trades with 1-5 contracts. The
   69-contract pre-hardening loss is reported separately and excluded from the
   current-strategy cohort.
2. Actual options trades: deduplicate records and use closing-reason outcome
   labels only. Dollar P&L is not inferred when fills are missing.
3. Historical SPY replay: use the local IEX one-minute cache and adjusted daily
   cache. This measures underlying direction only, not option returns.
4. Shadow episodes: use completed schema-v3 current-session lifecycles and
   executable ask-to-bid returns where available. Same-day symbols are also
   clustered to avoid pretending correlated observations are independent.

## Frozen Intraday Signal

The historical replay mirrors the current Flip Bot's 9-point recipe:

- Close above/below session VWAP: 2 points
- Close above/below EMA50: 2 points
- EMA50 slope agrees over five bars: 1 point
- Session is green/red: 1 point
- Price is no more than 1.5% from VWAP: 2 points
- A fresh VWAP/EMA pullback confirmed in the prior eight bars: 1 point

Only a full 9/9 signal qualifies. Information available at or after entry is
never used to form the signal.

Primary checkpoint: 10:30 ET. Diagnostic checkpoints: 11:30 and 12:00 ET.
Entry is the checkpoint bar open after using bars strictly before it.

## Frozen Higher-Timeframe States

- Daily: prior completed close versus SMA20, with SMA20 slope versus five
  sessions earlier.
- Weekly: last completed Friday close versus SMA20, with SMA20 slope versus
  five completed weeks earlier.
- Monthly: last completed month close versus SMA10, with SMA10 slope versus
  three completed months earlier.

Each state is bullish, bearish, mixed, or unavailable. A CALL maps to bullish
and a PUT maps to bearish.

## Fixed Variants

1. `ltf_only`
2. `daily_aligned`
3. `weekly_aligned`
4. `daily_weekly_aligned`
5. `daily_weekly_nonopposed`
6. `all_three_aligned`

No variants may be added after viewing results.

## Outcomes and Costs

- Primary historical outcome: 60-minute directional SPY return.
- Secondary: return through 13:45 ET.
- Diagnostic bracket: conservative 25 bps target/stop; stop wins ties.
- Underlying friction: 2 bps round trip.
- Chronological windows: development 2022-2023, selection 2024, diagnostic
  consumed period 2025+.
- Report count, win rate, expectancy, profit factor, maximum drawdown, and a
  five-session moving-block bootstrap interval when sample size permits.

## Gates

Nothing from this experiment is live-ready. A candidate is only worthy of a
new forward shadow lane when:

- expectancy is positive in all three chronological windows;
- selection and 2025+ each contain at least 30 independent session signals;
- 2025+ profit factor is at least 1.20;
- 2025+ expectancy remains positive after removing the best 1% of outcomes;
- the block-bootstrap lower bound is above zero; and
- shadow evidence agrees after date clustering.

The local data and final period have already been examined by this project.
Any pass is a research nomination, not an out-of-sample claim.
