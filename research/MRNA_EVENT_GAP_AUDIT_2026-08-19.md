# MRNA Event-Gap Audit

Date: 2026-08-19

## Catalyst

Moderna and Merck reported positive Phase 3 melanoma results before the open.
MRNA was already approximately 88% higher by 09:05 ET, so the opportunity was
an event-gap continuation rather than an anticipatable ordinary technical move.

## Routing Failure

- MRNA existed in the 124-symbol deep liquid universe.
- MRNA ranked second in the intraday social discovery report.
- The daily directional screen contained only 25 static symbols and excluded MRNA.
- The daily deep scan intentionally used completed prior-day data and still showed
  $62.96, so it could not represent the live 84.63% opening gap.
- The options ranker later observed a 49.3% ATM spread and correctly considered
  options liquidity non-executable.

## Causal Sequence Replay

Formula: `event_gap_or15_break_vwap_same_slot_volume_v2`

- Opening gap: +84.633%.
- Opening 15-minute range: $114.46 to $128.70.
- Completed breakout entry: 09:45 ET at $129.475.
- VWAP: $120.2173.
- VWAP extension: 7.701% (below the frozen 8% cap).
- Same-time volume: 51.254x the median 09:45 volume from prior sessions.
- Relative strength versus SPY: +11.617%.
- Structural stop: $123.1969.
- 2R target: $142.0312.
- Outcome: target reached at 10:05 ET, +2R before transaction costs.

The candidate used only bars completed through 09:45 ET. Later bars were used
only to resolve the shadow outcome.

## Decision

Status: unvalidated shadow hypothesis.

This one successful event does not establish an edge. The sequence has no broker
imports or order authority. Social data can discover a symbol but cannot create a
trade. Options marks are excluded from evidence until executable bid/ask quotes
and size are available.

Promotion review requires at least 30 resolved event-gap candidates across at
least 20 independent dates, positive post-cost expectancy, profit factor above
1.15, and acceptable tail loss under gap-failure scenarios.
