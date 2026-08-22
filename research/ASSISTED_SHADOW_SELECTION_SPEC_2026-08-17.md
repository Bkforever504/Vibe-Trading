# Assisted Shadow Selection Experiment

## Hypothesis

A time-limited human approve/skip decision, made from a frozen setup packet
before the outcome is known, improves fee-adjusted expectancy versus skipped
candidates from the same signal generator.

## Fixed protocol

- One contract or option spread equivalent per candidate.
- Candidate includes symbol, strategy, side, entry, stop, target, point value,
  estimated round-trip cost, observed time, and context.
- Candidate digest is fixed before review.
- Decision window is 90 seconds by default and cannot exceed five minutes.
- Decisions are `approve` or `skip`; changing a decision is prohibited.
- Both cohorts receive the same forward counterfactual resolution method.
- The journal is hash chained and fails closed after modification.
- The experiment cannot submit orders and has no broker execution authority.

## Review gate

Review requires at least 30 resolved approved candidates, 30 resolved skipped
candidates, and 20 distinct session dates. Approved expectancy must be positive,
profit factor must be at least 1.20, its normal-approximation 95% lower confidence
bound must be positive, and approve-minus-skip expectancy must be positive.

Passing the review gate permits human review only. It does not automatically
authorize paper or live execution.
