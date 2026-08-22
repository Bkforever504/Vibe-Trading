# GEX Level Reaction Preregistration

## Claim under test

A point-in-time rank-1 absolute GEX/OI proxy level predicts a completed-bar
rejection or accepted break/retest better than ranks 2-5 from the same snapshot.

## Causal rules

- The level snapshot must exist before the first touch.
- Exact 0DTE only; open-interest coverage must be at least 60%.
- Public open interest is a proxy. Dealer inventory and trade direction are not observed.
- A level is not pre-labelled support or resistance. Approach and completed bars determine the event.
- Entry is the next bar open after confirmation. Same-bar stop/target ambiguity resolves stop first.
- Options are not traded. Underlying reactions are measured first; options friction is a separate gate.

## Evidence gate

Review requires at least 30 resolved rank-1 events, 30 ranks-2-to-5 controls,
and 20 independent dates. The report cannot enable execution or change sizing.
