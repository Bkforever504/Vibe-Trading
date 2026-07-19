# Claude Fable 5 - Point-In-Time Option Quote Capture (Next Jump, Step 1)

Date: 2026-07-13
Author: Claude Fable 5
Continues: CLAUDE_HANDOFF_2026-07-13_OPTIONS_RESEARCH_VALIDITY_NEXT_JUMP.md
Status: Step 1 of the Next Competitive Jump implemented; Steps 2-5 pending.

## Codex Host Acceptance Addendum

Host verification found and repaired three issues before acceptance:

- Free Alpaca options data is now explicitly requested as `feed=indicative`
  and labeled `indicative_modified_not_opra_nbbo`; the underlying is pinned to
  free `feed=iex`. The data is no longer described as NBBO.
- Lifecycle network capture runs on non-daemon background threads, so option
  and underlying HTTP latency cannot delay entry or exit decisions. JSONL
  appends are process-locked and reject NaN/Infinity.
- A trade ID is allocated before the signal sample and reused in the durable
  trade record. Every spread sample also records `leg_role=long|short`, making
  signal-to-fill-to-monitor-to-exit joins unambiguous.

Additional hardening rejects nonfinite/crossed quotes for derived mid/spread
and persists thrown vendor failures as `provenance.status=unavailable`.

Authenticated read-only host probe on SPY returned HTTP 200 from the
`indicative` feed with quote, Greeks, IV, and volume. Open interest was absent,
so the parser correctly labeled the sample `partial` instead of estimating it.

Final host verification: 200 tests passed, compile clean, execution audit clean.

## What Was Built

### `scripts/point_in_time_quotes.py` (NEW, telemetry-only)

Vendor-neutral point-in-time option capture with provenance:

- Record schema v1: event (signal|fill|monitor|exit), captured_at (UTC ms),
  bot, trade_id, order_id, contract, quote {bid, ask, bid_size, ask_size,
  quote_timestamp, quote_age_seconds, mid, spread_cents}, trade {price,
  size, trade_timestamp, conditions}, greeks {delta, gamma, theta, vega,
  rho}, implied_volatility, open_interest, volume, underlying {symbol,
  price, price_timestamp, source}, provenance {provider, status
  ok|partial|unavailable, missing_fields, endpoint, http_status,
  latency_ms}, context (caller-supplied), flow_classification.
- Default provider: `alpaca_options_snapshot_v1beta1` with the free
  `indicative` feed explicitly pinned (latest quote/trade,
  greeks, IV, OI, daily volume where returned). Underlying price fetched
  separately with its own source timestamp
  (`alpaca_stocks_trades_latest`).
- Honesty guarantees (tested): missing fields are null AND enumerated in
  provenance.missing_fields; a failed fetch is recorded with status
  "unavailable" (visible gap, not a guess); nanosecond timestamps are
  parsed correctly; quote age clamps at zero, never negative.
- `flow_classification` is ALWAYS "unknown"
  (`reason: no_licensed_classified_opra_adapter`) - the hard stop against
  labeling unsigned public volume as smart money is enforced in code, not
  convention. Step 2's licensed adapter replaces `classified_flow()`.
- Store: append-only JSONL at
  `~\.vibe-trading\logs\option-quote-samples.jsonl`, overridable via
  `OPTION_QUOTE_SAMPLES_FILE` (root conftest.py now redirects it under
  pytest alongside FLIP_DECISION_LOG_FILE).
- Alpaca documents the free options feed as indicative: trades may be delayed
  and quotes modified. Records say `indicative_modified_not_opra_nbbo`; they
  must not be described as OPRA NBBO.
- No broker trading endpoints imported or called. Cannot place orders.
- `capture_lifecycle_sample` NEVER raises into a trading path (tested,
  including an unwritable path).

### `strategies/flip_bot.py` wiring (4 sites, all wrapped)

`_capture_point_in_time(event, trade_or_setup, context)` captures every leg
(long + short for spreads):

1. `signal` - immediately before order submission (strategy, confidence,
   entry_price_est, spread at signal).
2. `fill` - after the trade record is saved (filled_price,
   fill_price_source, estimate).
3. `monitor` - each monitor cycle per open trade (mid, pnl_pct).
4. `exit` - after `_stamp_exit` (exit_reason, exit_price, pnl).

Capture runs on non-daemon background threads. Network latency cannot delay
entry or exit decisions, while the process still waits for durable completion
before shutdown. Failures log and continue. No entry/exit/sizing/threshold
logic changed anywhere.

### Tests: `agent/tests/test_point_in_time_quotes.py` (NEW, 10 tests)

Full-payload parse (NBBO, sizes, mid, spread, nanosecond quote age, greeks,
IV, OI, volume, conditions); partial payload -> nulls + enumerated missing;
empty payload -> unavailable; flow always unknown; unknown event rejected;
JSONL schema; failed fetch persisted as unavailable; never-raises;
quote-age edge cases; flip wrapper captures both legs and no-ops without
legs.

## Verification (sandbox; re-run on host)

```
140 passed (flip, options, research-validity, ops suites + new tests)
python -m compileall strategies scripts -> clean
```

Host addition to the recheck block:

```powershell
python -m pytest agent\tests\test_point_in_time_quotes.py -q -p no:cacheprovider
```

Note for host: first live samples will appear in
`~\.vibe-trading\logs\option-quote-samples.jsonl` after the next flip
entry/monitor run. Verify provenance.status distribution early - if Alpaca
omits greeks/OI on some contracts, records will correctly show "partial";
that is data honesty, not a bug.

## Design Decisions

- Monitor-cycle sampling is per leg per 15-minute cycle (~26/leg/day):
  small, and it builds the option lifecycle dataset Step 3 needs, keyed by
  trade_id/order_id/contract from day one.
- The options bot (iwm_options_bot) is NOT yet wired; its quote_mark path
  already snapshots quotes for netted groups. Extending lifecycle capture
  to it is a natural follow-up once flip samples validate the schema.
- Alpaca is research-grade, not OPRA-consolidated NBBO. Records are labeled
  with provider for exactly this reason; when a licensed feed lands, both
  provider streams coexist in the same store and can be compared.

## Steps Remaining From The Master Plan (in order)

2. Licensed/classified OPRA adapter (buyer/seller initiation,
   open/close inference). BLOCKED ON KENNY: vendor + budget decision
   (e.g., Databento OPRA, Polygon options, CBOE DataShop). Interface is
   ready: implement a `fetch_fn` + parser and replace `classified_flow()`;
   missing data must keep failing to "unknown".
3. Option lifecycle dataset completeness report: join
   option-quote-samples.jsonl with flip-trades.json per trade; report path
   completeness (signal->fill->monitor...->exit), stale-quote fraction,
   spread cost at each stage, Greek decay, MFE/MAE alignment.
4. Preregistered hypotheses in the edge trial ledger before any sweep;
   purged walk-forward windows; family-wide trial counting (ledger exists,
   count currently 0 - keep it honest).
5. Ablation-nominated shadow experiments only after 30 schema-v1 closed
   Flip trades, with separate forward replication and Kenny approval.

## Hard Stops (unchanged)

All hard stops from the 2026-07-13 handoff remain in force. This phase
changed no execution symbols, live/paper flags, risk limits, stops,
targets, sizing, reconciliation, kill switches, or broker paths.
