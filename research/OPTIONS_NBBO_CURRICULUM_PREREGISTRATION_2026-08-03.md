# Options NBBO Curriculum Preregistration

Date frozen: 2026-08-03

## Question

Do the bot's already-formed defined-risk option candidates retain positive
expectancy when every leg enters and exits at the executable side of a
point-in-time consolidated quote, after fees and chronological holdout review?

## Frozen Inputs

- Candidates must contain a decision timestamp, concrete OCC leg symbols,
  side, ratio, strategy, quantity, maximum risk, profit target, and stop policy.
- Eligible strategies are put spreads, call spreads, and iron condors.
- Quote history must identify observation time, source quote time, contract,
  bid, ask, and quote scope.
- Only licensed consolidated NBBO scopes are execution evidence. Alpaca
  indicative or modified quotes remain useful coverage diagnostics but cannot
  pass the review gate.
- Missing contracts, quotes, maximum risk, or policy fields are unavailable;
  they are never imputed from the underlying, midpoint, trades, or option bars.

## Frozen Execution Model

- Contract selection is fixed before replay. The engine does not search future
  chains or choose winners after outcomes are known.
- Entry uses sell legs at bid and buy legs at ask at the first complete,
  synchronized quote snapshot available no later than 60 seconds after the
  decision.
- Exit uses buy-to-close short legs at ask and sell-to-close long legs at bid.
- Source quotes must have been observable by the evaluation timestamp, be no
  more than two seconds old, and have no more than two seconds of inter-leg
  timestamp skew.
- Crossed, zero, or wider-than-25%-of-mid leg markets are rejected.
- Profit and stop thresholds use each candidate's recorded credit policy.
  Otherwise the candidate closes at its frozen evaluation end or 15:45 ET on
  expiry, provided a complete fresh quote exists.
- Base fees are $0.66 per contract, per leg, per side. Double- and triple-fee
  stress tests are reported.

## Frozen Review

- Candidate outcomes are ordered chronologically. The last 20% of candidate
  dates are a locked holdout and are not used in development summaries.
- Development evidence is divided into up to five chronological evaluation
  blocks. No policy is optimized inside those blocks.
- Review requires at least 30 resolved candidates, 80% lifecycle coverage,
  three chronological blocks, 60% profitable blocks, positive base and
  double-fee expectancy, positive top-5%-winner-removed expectancy, and at
  least 10 locked-holdout outcomes with positive base and double-fee
  expectancy.
- Any look-ahead, non-NBBO execution quote, or incomplete contract-selection
  audit fails the gate.

## Authority

This curriculum is read-only and cannot submit orders, alter parameters,
change sizing, or promote a strategy. A pass permits human review only. A
missing-data result is a coverage finding, not evidence for or against edge.

## Post-Result Operational Diagnostic Amendment

Added after the first two licensed OPRA lifecycles were resolved. This does
not alter the frozen strategy review gate and cannot count as preregistered
edge evidence.

- Replay each resolved lifecycle at fixed one-, five-, and legacy
  thirty-minute observation schedules anchored to the governed Central-time
  session.
- Use the same executable-side CBBO, freshness, width, and leg-skew rules.
- Label the output scheduled observation only. A sampled target quote is not a
  broker fill and is not equivalent to a resting limit order.
- Cadence results may change telemetry scheduling. They cannot alter entry
  filters, targets, stops, sizing, promotion status, or execution authority.
