# SPX Weekly -1 ATR Put Spread Preregistration

Date frozen: 2026-08-14

## Public hypothesis

On the first trading day of each week near 10:00 ET:

1. Calculate the previous completed week's 14-week Wilder ATR.
2. Set the short strike to the previous weekly close minus one ATR, rounded to the nearest 5.
3. Buy the put 50 SPX points below the short strike.
4. Use that week's Friday SPXW PM-settled expiration.
5. Hold to settlement and skip non-positive natural credits.

The external source reports 326-327 weeks from May 2020 through August 2026, a 95.4% win rate, profit factor 2.48 at midpoint fills, and profit factor 2.09 using short bid minus long ask. Those are claims to reproduce, not repository evidence.

## Locked first-stage test

The first stage tests only the physical distribution and settlement payoff. It does not claim to reproduce option profitability.

- Underlying: unadjusted S&P 500 index daily OHLC (`^GSPC`).
- Weekly bars: regular-session daily bars grouped by the Friday ending each calendar week; holiday-shortened weeks remain in their normal Friday bucket.
- ATR: true range followed by Wilder RMA, length 14, seeded with the arithmetic mean of the first 14 true ranges.
- Level: `round_half_up_to_5(previous_week_close - previous_week_ATR14)`.
- Settlement proxy: final index close in the target week.
- Intrinsic spread loss: `min(max(short_strike - settlement, 0), 50)` index points.
- Commission proxy: $2.64 per spread, or 0.0264 index points.
- Displayed-credit scenarios: 2.98, 2.73, and 2.48 points. These are sensitivity checks, not historical fills.

The report must disclose that a close proxy can differ from official SPXW settlement and that constant credits cannot validate profit factor.

## No-tuning rule

The ATR length, multiplier, rounding rule, wing width, holding period, and entry weekday are frozen. No filters are added after seeing results. Regime and subperiod summaries are diagnostics only.

## Required second-stage evidence

No execution or sizing authority is permitted until all items below pass:

- Licensed point-in-time SPXW quotes at 10:00 ET for the exact short and long contracts.
- Official Cboe SPXW settlement values.
- Natural-fill reconstruction (short bid minus long ask), including stale/crossed quote rejection.
- At least 250 historical weeks with a separately reported 2024+ holdout.
- Positive net expectancy and profit factor above 1.25 in the holdout under natural fills.
- Positive expectancy after an additional 0.25-point spread-level stress.
- Bootstrap lower confidence bound above zero or a documented inability to establish it because rare tail losses dominate uncertainty.
- At least 52 forward shadow observations before any live review.

## Risk boundary

One SPX 50-wide spread has structural risk near $5,000. It is unsuitable for a $500-$1,000 account. XSP is one-tenth scale but must be validated independently because its credits and friction are not guaranteed to scale from SPX. This lane remains research-only and contains no order path.

## Promotion status

- `execution_enabled: false`
- `can_submit_orders: false`
- `can_change_gates_or_sizing: false`
- `status: research_candidate_unverified`
