# Trend Participation Shadow Preregistration - 2026-08-04

## Motivation and boundary

The 2026-08-04 record-risk-on session exposed a playbook coverage gap: the
context stack identified bullish aligned structure and opening-range breakouts,
but the candidate engine only formed short-premium structures. That date is a
consumed design day and cannot count as evidence.

Forward evidence begins 2026-08-05. This lane is shadow-only and cannot submit
orders, alter the short-volatility gate, change sizing, or promote itself.

## Frozen signal

Symbols: SPY, QQQ, and NVDA.

A symbol qualifies only when all are true:

- daily, intraday, and weekly context produces `primary_bias=bullish` with
  `intraday_alignment=aligned`;
- the latest opening-range state is `above_opening_range`;
- market-force classification is `bullish` or `bullish_lean` with no risk veto;
- the catalyst calendar has no high-impact event or active caution window;
- no unresolved shadow position already exists for the symbol.

## Frozen structure

- 7-21 DTE call debit spread;
- long call absolute delta 0.50-0.70;
- short call absolute delta 0.25-0.40 at a higher strike and same expiry;
- each leg relative spread at most 15%;
- executable debit = long ask minus short bid;
- debit must be positive, no more than 55% of width, and no more than $250;
- one contract and at most one new candidate per symbol per session.

## Frozen exits

- profit: capture 50% of maximum possible spread profit;
- stop: lose 50% of entry debit;
- time: close after seven calendar days or at 2 DTE, whichever comes first;
- executable close value = long bid minus short ask;
- fees: $0.66 per contract per leg per side, with doubled-fee reporting.

## Evidence gate

The first 60 resolved candidates are development. The next 30 are locked
chronological holdout. Review requires positive development and holdout
expectancy under doubled fees, development profit factor at least 1.30, no
single winner above 25% of net profit, and explicit human approval.
