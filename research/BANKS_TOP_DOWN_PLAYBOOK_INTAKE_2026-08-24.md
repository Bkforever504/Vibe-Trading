# Banks Top-Down Trading Blueprint — Research Intake

Date reviewed: 2026-08-24
Source: https://drive.google.com/file/d/1hExAtfctbRRswfun4kbvcyFchWtl18iY/view
Artifact reviewed: 11-page PDF, `The BANKS Top-Down Trading Blueprint`, attributed to @RealJGBanks.

## Decision

Useful as a checklist and taxonomy input; not admissible as proof of edge.

The guide's sequence is direction (weekly/daily), structure and location
(daily/1h), closed-candle break/reclaim/loss plus retest, then 5m/15m entry.
That is consistent with the dashboard's existing context-location-confirmation
and multi-timeframe design. Its strongest operational contribution is its
explicit no-trade list: ranging 8/21 averages, no fresh location, weak
momentum, repeated level chop, extended entry, conflicted evidence, and late
entry.

## Evidence limits

- The percentage examples are selected historical social-post outcomes, not a
  reproducible dataset or controlled backtest.
- No complete universe, sampling rule, transaction-cost model, losing-trade
  inventory, or out-of-sample result is supplied.
- The guide itself says results are not guaranteed and the trader retains the
  entry, invalidation, size, and fit decision.

## Integration boundary

- Do not change any frozen MNQ rule or score weight from this guide.
- Route the seven no-trade conditions through normal candidate intake if they
  are tested as blocker challengers.
- Preserve closed-bar timing, exact entry/invalidation/targets, and the rule
  that a late or conflicted setup is a no-trade.
- Any proposed 8/21 EMA filter must be preregistered and compared in shadow;
  it is context, not a stand-alone entry signal.

Execution remains disabled. This intake creates no order authority.
