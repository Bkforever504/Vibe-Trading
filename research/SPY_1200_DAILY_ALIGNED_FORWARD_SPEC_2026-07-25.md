# SPY 12:00 Daily-Aligned Forward Shadow Specification

Date frozen: 2026-07-25
Parent trial: `green-day-htf-ltf-2026-07-25`

## Decision

Create a research-only forward lane. This is observation, not promotion.

## Frozen Signal

- Symbol: SPY only.
- Checkpoint: 12:00 ET.
- Intraday rule: the existing production-parity 9/9 VWAP/EMA50 recipe.
- Input bars: every one-minute IEX bar from 09:30 through 11:59 ET must be
  present. No forward-filling or interpolation.
- Higher timeframe gate: prior-completed daily state must align with the
  intraday direction.
- Maximum one signal per independent trading date.
- No historical backfill.

The signal is evaluated from bars strictly before 12:00 ET. The forward entry
reference is the first observed SPY latest trade at the first successful
12:03 or 12:08 ET run. The exit reference is the observed latest trade at the
first successful 13:03 or 13:08 ET run. The second run in each pair is only a
transient-data retry; append-only date and signal deduplication makes it a
no-network no-op after success. Net underlying return deducts the same fixed
2 bps round-trip friction used by the parent experiment.

## Option Telemetry

- Correct directional right: call for bullish, put for bearish.
- Expiration: earliest available from 0 through 2 calendar DTE.
- Delta: absolute delta from 0.35 through 0.65.
- Quote: valid positive bid and ask, spread no greater than 20% of midpoint.
- Selection order: earliest expiry, closest absolute delta to 0.50, closest
  strike to SPY, then narrowest percentage spread.
- Entry valuation: observed ask.
- Exit valuation: observed bid.

Alpaca's current options snapshot feed is
`indicative_modified_not_opra_nbbo`. It is not licensed OPRA NBBO and must
never be labeled NBBO. Missing option telemetry does not erase an otherwise
valid underlying signal.

## Timing And Failure Policy

- Signal run window: 11:58-12:10 ET.
- Outcome run window: 12:58-13:15 ET.
- Runs outside those windows fail closed.
- Missing or incomplete bars: no signal.
- Unavailable daily state: no signal.
- Missing underlying entry price: no signal.
- Missing exit price: no outcome is appended, allowing a retry.
- Missing option exit quote: underlying outcome is retained and option outcome
  remains null.

## Gate

Review after 30 resolved independent dates. No automatic promotion is
permitted. The review must report:

- underlying win rate and net expectancy;
- option ask-to-bid win rate and expectancy where complete;
- option quote coverage and spread distribution;
- expectancy after removing the best 1%;
- five-date moving-block interval;
- performance by direction and VIX/regime context when available; and
- any drift from the frozen signal or timing rules.

Human approval is required for any later paper-order experiment. This lane can
never submit, replace, or cancel orders.
