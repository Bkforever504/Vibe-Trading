# Winner-DNA Matched Replay Preregistration

Date frozen: 2026-07-25

## Question

Do the pre-entry traits shared by the current-size Flip bot's realized winners
identify a repeatable edge when every historical occurrence, including losing
twins, is counted?

## Evidence Policy

- Seed trades must be closed Flip records with canonical direction, realized
  P&L, and 1-5 contracts.
- Outcome, exit reason, MFE, MAE, exit price, and realized P&L may label a seed
  but may never become matching features.
- Legacy catalyst text may recover only the strategy's explicit pre-entry
  VWAP/EMA checks. Missing fields are not guessed.
- Historical twins use the frozen production-parity 9/9 VWAP/EMA signal in
  `research/green_day_htf_ltf_lab.py`.
- The entry checkpoint is the modal winner checkpoint, 10:30 ET. It is frozen
  before the directional replay is examined.
- Every matching historical signal is included. Losing matches cannot be
  removed.

## Frozen Archetypes

1. Bull: CALL, above VWAP, above EMA50, rising EMA50, green session, not
   extended from VWAP, pullback held trend.
2. Bear: PUT, below VWAP, below EMA50, falling EMA50, red session, not extended
   from VWAP, pullback failed near trend.

## Outcome

Underlying directional return from the 10:30 ET entry through 60 minutes,
minus 2 basis points round-trip friction. This is not an option-P&L claim.

## Partitions

- Development: 2022-2023
- Selection: 2024
- Consumed diagnostic: 2025+

The consumed diagnostic period cannot promote a strategy.

## Promotion Gate

An archetype is only a forward-shadow nominee when:

- at least 30 historical matches and 20 independent dates exist;
- development, selection, and diagnostic expectancy are all positive;
- profit factor exceeds 1.10 in every partition;
- overall top-1%-removed expectancy remains positive;
- the overall block-bootstrap 95% interval is above zero; and
- no production behavior is changed automatically.

Failure of one gate means `not_nominated`. A near miss may be recorded as a
`research_lead`, but it remains read-only until a new forward-only sample
passes a separately frozen gate.

## Options Bot

Options winners are reported only when canonical fill-derived P&L exists.
Closing-reason percentage estimates are excluded. If fewer than five eligible
winners exist, no options archetype is inferred.

