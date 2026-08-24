# Databento MES Shadow Scanner: Primary-Source Integration Research

Date: 2026-08-23
Status: implementation guidance; no execution authority
Scope: replace the MES scanners' yfinance proxy with Databento evidence while
preserving the frozen strategy rules and the promotion gates.

## Decision

Use a two-plane Databento adapter:

1. Use `GLBX.MDP3` OHLCV records to calculate the existing time-bar features.
2. Use `GLBX.MDP3` `mbp-1` records to capture the direction-aware bid or ask at
   every actionable entry and exit timestamp.

`mbp-1` is the smallest Databento schema that publishes every top-of-book
update, including `bid_px_00`, `ask_px_00`, their displayed sizes, and the
exchange event/Databento receive timestamps. Full `mbo` is necessary only if
the frozen evidence policy literally requires MBO, or if the research needs
order-level queue position, passive-limit fill simulation, or deeper
market-impact modeling. Databento describes MBP-1 as every event that changes
the best bid and offer, while MBO contains every order event at every level.
([MBP-1 schema](https://databento.com/docs/schemas-and-data-formats/mbp-1),
[MBO schema](https://databento.com/docs/schemas-and-data-formats/mbo))

This distinction requires an explicit governance decision:

- **Keep the current literal blocker:** build and validate a stateful MBO book,
  and do not remove `databento_mbo_and_executable_quotes_required` until it is
  complete.
- **Prefer the minimum sufficient source:** amend and re-hash the frozen specs
  before new evidence collection so `mbp-1` is accepted for one-contract
  aggressive-entry quote evidence. Do not silently reinterpret the existing
  blocker.

Neither source proves an actual fill. It proves the quoted market available at
the observation timestamp. A broker fill is the only actual-fill record.

## Dataset and MES symbology

- Dataset: `GLBX.MDP3`. Databento states that it is the direct CME Globex MDP
  3.0 feed for CME, CBOT, NYMEX, and COMEX futures and options. Its supported
  schemas include MBO, MBP-1, MBP-10, TBBO, trades, BBO, OHLCV, definitions,
  statistics, and status. Historical schema availability can differ, so the
  adapter must query metadata rather than assume a range.
  ([GLBX.MDP3 catalog](https://databento.com/datasets/GLBX.MDP3),
  [dataset guide](https://databento.com/docs/knowledge-base/datasets/glbx-mdp3))
- Symbol: `MES.v.0`, with `stype_in="continuous"`. The notation is
  `[ROOT].[ROLL_RULE].[RANK]`; `v` ranks expirations using the previous day's
  trading volume and rank `0` selects the most active expiration.
- Do not use `MES.FUT` with `stype_in="parent"` for the scanners. Parent
  symbology selects the whole MES product family, which can interleave outright
  contracts and spreads. It is suitable for discovering child instruments, not
  for a single front-contract signal stream.
- Continuous prices are original, unadjusted exchange prices. The mapping can
  change `instrument_id` at a roll. Persist both the continuous request symbol
  and the resolved raw contract/instrument ID, and block or separately label a
  trade whose lifecycle crosses a mapping change.
  ([symbology rules](https://databento.com/docs/standards-and-conventions/symbology),
  [continuous-contract example](https://databento.com/docs/examples/symbology/continuous))

Important live limitation: an existing continuous-symbol subscription is not
remapped when its underlying contract mapping changes. The collector must
capture `SymbolMappingMsg` records and deliberately renew the subscription at
the daily/roll boundary; submitting a new identical subscription can receive a
new mapping.
([Live client symbology](https://databento.com/docs/api-reference-live/client/live-blocking))

## Credential and dependency handling

The official Python client reads `DATABENTO_API_KEY` automatically when
`db.Historical()` or `db.Live()` is constructed without an explicit key. The
official docs discourage passing the key in production code; live
authentication uses challenge-response so the API key is not sent over the
network. The current official Python package requires Python 3.10 or newer.
([historical authentication](https://databento.com/docs/api-reference-historical/basics),
[live authentication](https://databento.com/docs/api-reference-live/client/live-blocking),
[official Python client](https://github.com/databento/databento-python))

Repository requirements:

- Prefer process environment injection into the Windows scheduled service.
  Do not place the key in a command line, log, manifest, test fixture, or
  committed configuration.
- The existing fetchers fall back to parsing `agent/.env`. Retain that only as
  a compatibility path; new shared client code should call `db.Historical()`
  or `db.Live()` after checking that the environment variable is present.
- Log only `api_key_present: true/false`, never a prefix or key length.
- Pin and record the tested `databento` and `databento-dbn` versions. Databento
  currently documents its APIs as major version `0`, where the public API is
  not yet stable.

## Schema selection

| Need | Schema | What it establishes | What it cannot establish |
|---|---|---|---|
| 1s/1m/1h signal features | `ohlcv-1s`, `ohlcv-1m`, `ohlcv-1h` | Trade-derived open, high, low, close, volume | Bid, ask, spread, queue, or a fill |
| Every trade | `trades` | Last-sale price, size, aggressor side when supplied | The complete quote state between trades |
| Entry/exit quote | `mbp-1` | Every BBO-changing event, top sizes/order counts, and trades | Depth beyond BBO or order queue position |
| Lower-volume quote sampling | `bbo-1s` | Last BBO and sale in each populated second | Intrasecond quote changes; the timestamp is the interval end |
| Depth-sensitive market fill | `mbp-10` or reconstructed `mbo` | More book depth for estimating a sweep | Guaranteed execution at displayed prices |
| Passive order/queue research | `mbo` | Adds, cancels, modifies, trades, fills, and order IDs | The user's broker fill without broker data |

Databento classifies OHLCV as L0 aggregates, trades as time-and-sales, MBP-1 as
L1 top of book, MBP-10 as L2, and MBO as L3. OHLCV bars are created from trade
messages; a bar is omitted when no trade occurs in its interval. Therefore an
OHLCV close is never an executable bid or ask.
([schema comparison](https://databento.com/docs/knowledge-base/new-users/market-data-schemas),
[OHLCV schema](https://databento.com/docs/schemas-and-data-formats/ohlcv),
[trades schema](https://databento.com/docs/schemas-and-data-formats/trades))

For the two current one-contract MES shadow strategies, `mbp-1` is the
recommended quote plane. Databento's own examples use MBP-1 to calculate exact
instantaneous spread-crossing cost at backtest execution timestamps and to
analyze market-order slippage.
([pairs-trading cost example](https://databento.com/docs/examples/algo-trading/pairs-trading),
[execution-slippage example](https://databento.com/docs/examples/algo-trading/execution-slippage/result))

If MBO is selected, initialize/recover book state with Databento's synthetic
snapshot and apply records only after each instrument's `F_LAST` event flag.
Databento warns that before `F_LAST` the apparent BBO can be transient or
already traded. Historical CME MBO snapshots are emitted at 00:00 UTC on
weekdays when the request spans that timestamp.
([CME MBO normalization](https://databento.com/docs/knowledge-base/datasets/glbx-mdp3),
[MBO snapshots](https://databento.com/docs/standards-and-conventions/mbo-snapshot))

## Historical request semantics and storage

Use `Historical.timeseries.get_range` with explicit, timezone-aware UTC start
and end timestamps. All Databento ranges are start-inclusive and end-exclusive.
The historical endpoint filters on `ts_recv` when the schema contains it and
otherwise on `ts_event`. An unzoned timestamp is assumed to be UTC.
([historical `get_range`](https://databento.com/docs/api-reference-historical/timeseries/timeseries-get-range),
[date/time conventions](https://databento.com/docs/standards-and-conventions))

Before every request:

1. Call `metadata.get_dataset_range(dataset="GLBX.MDP3")` and inspect the
   per-schema end timestamp under the caller's actual entitlements.
2. Clamp the requested end to the returned exclusive end; never assume the
   just-completed bar is already available.
3. Call `metadata.get_cost` with exactly the same dataset, schema, symbols,
   `stype_in`, start, end, and limit.
4. Refuse the request above a configured per-run and rolling-daily cost cap.
5. Reuse an immutable cache keyed by a canonical request fingerprint.

`get_range` streams the response and returns a `DBNStore` after the download
finishes; it does not require application-level page traversal. Use
`path="...dbn.zst"` so large responses stream to compressed DBN rather than
being retained only in memory. `limit` is a record cap, not pagination. For
large requests Databento recommends batch download (particularly above 5 GB).
`DBNStore.to_df()` maps fixed-point prices, pretty timestamps, and symbols; its
DataFrame index is `ts_recv` where available and otherwise `ts_event`. For
large conversions, `to_df(count=N)` or `to_ndarray(count=N)` yields chunks.
([historical API](https://databento.com/docs/api-reference-historical),
[DBN conversion example](https://databento.com/docs/examples/basics-historical/encodings))

Persist raw DBN before any derived Parquet/JSONL. Each normalized record should
retain at least: dataset, schema, continuous symbol, resolved raw symbol,
`instrument_id`, `publisher_id`, `ts_event`, `ts_recv`, sequence, action,
bid/ask prices and sizes, source cache hash, request fingerprint, and collector
version. Keep timestamps in UTC internally and derive ET/CT session labels with
IANA zones only at the strategy boundary.

## Live versus delayed historical collection

The live API supports real-time subscriptions and intraday replay. Normal
replay is limited to the retained portion of the last 24 hours; GLBX MBO and
definition data have a special full-weekly-session recovery path because they
are stateful. Replay completion, slow-reader warnings, skipped records,
heartbeats, subscription errors, and symbol-resolution errors are explicit
system/error records and must fail the promotion-eligible lane closed.
([live API](https://databento.com/docs/api-reference-live/client/live-blocking),
[`Live.subscribe`](https://databento.com/docs/api-reference-live/client/subscribe))

For timely dashboard signals, run one persistent `GLBX.MDP3` live collector;
do not create a new live connection for each scheduled scanner. A live session
is tied to one dataset, while multiple schema subscriptions can share it. Feed
callbacks must be non-blocking. The collector should write an append-only local
DBN stream/ring buffer, while scheduled scanners read a bounded snapshot.

Live data also requires an eligible plan and the applicable CME licensing
classification. Databento distinguishes display, non-display, personal,
commercial, and distribution use. Confirm the account's entitlement in the
portal before implementation; an API key alone does not establish live CME
permission.
([live-data licensing guide](https://databento.com/docs/portal/live-data),
[current pricing](https://databento.com/pricing))

If the account lacks live entitlement, use delayed historical Databento only
for causal after-the-fact replay. Do not relabel a yfinance-triggered signal as
a Databento live signal merely because Databento later confirms the price.
Instead, replay the complete frozen rule from Databento records available no
later than each historical decision timestamp, then compare it with the
original proxy decision.

## Cost and billing safeguards

Databento states that metadata, symbology, and account calls are free, while
time-series data is billed by the uncompressed DBN bytes delivered. Cost
estimates can overstate requests whose ranges are not discrete multiples of 10
minutes; actual billing follows bytes sent. Duplicate historical streaming
requests are billed again. A batch request is billed once and can be downloaded
again for 30 days without another data charge.
([historical metered pricing](https://databento.com/docs/api-reference-historical),
[`get_billable_size`](https://databento.com/docs/api-reference-historical/metadata/metadata-get-billable-size))

Required guards:

- Estimate-only is the default for historical backfill.
- Download requires an explicit flag plus a hard USD cap.
- Request only candidate/session windows, not `ALL_SYMBOLS` or an unrestricted
  MBO firehose.
- Reuse DBN cache by request fingerprint; never overwrite a nonempty cache.
- Record estimate, actual cache bytes, SHA-256, request parameters, package
  version, and whether the cache was reused. Never record credentials.
- Bound retries. Honor `Retry-After` on HTTP 429 and never issue a new billable
  query merely because normalization failed locally.
- For live service, use an allowlist of `MES.v.0` and the approved schemas and
  alert on unexpected symbols/schema traffic. Subscription/licensing cost is a
  separate account-level gate from historical `get_cost`.

## Executable-quote qualification contract

A shadow entry or exit may become **quote-evidence eligible** only when all of
the following are true:

1. The rule was frozen before the session and the signal was generated from
   data available by `actionable_at`.
2. The record is from `GLBX.MDP3` `mbp-1`, or from a correctly reconstructed
   MBO book if the literal MBO gate is retained.
3. The persisted `SymbolMappingMsg`/historical mapping proves the raw MES
   contract and `instrument_id` used at that time.
4. The selected quote has `ts_recv <= actionable_at`; no later record is used.
5. Quote age is within a separately preregistered maximum. Missing or stale
   quotes fail closed; they are not forward-filled across a book clear, halt,
   session boundary, disconnect, skipped-record warning, or roll.
6. Bid and ask are finite, positive, tick-aligned, and not crossed; displayed
   size on the required side covers the modeled one-contract quantity.
7. Direction-aware prices are used: buy/cover at the ask and sell/short at the
   bid. Midpoint and last trade are diagnostics, not aggressive fill prices.
8. The evidence record says `quote_observed_not_fill`. Commission and any
   preregistered residual slippage remain in net P&L.

For `bbo-1s`, `ts_recv` is the interval-end timestamp and the record can omit
intrasecond changes. It can support coarse shadow review only when the frozen
latency rule allows one-second sampling. Do not select the bar whose interval
ends after `actionable_at`.
([BBO schema](https://databento.com/docs/schemas-and-data-formats/bbo),
[MBP-1/BBO/TBBO comparison](https://databento.com/docs/faqs))

Passing this contract is not sufficient by itself for strategy promotion. It
only removes the market-data/executability blocker; the 100-outcome, 30-date,
per-regime, multiple-testing, expectancy, drawdown, and calibration gates still
apply.

## Repository findings

The repository already contains useful components rather than starting from
zero:

- `scripts/fetch_databento_futures.py` implements cost estimation, immutable
  DBN caching, continuous `MES.v.0` OHLCV, roll detection, and session auditing.
- `scripts/fetch_databento_mbo.py` implements a one-session, credit-capped MBO
  fetch with a manifest and hash.
- `scripts/fetch_databento_bbo.py` and local DBN/Parquet caches provide
  historical one-second MES BBO coverage through prior dates.
- Local MBO caches cover only three discovery sessions; they are not a daily
  forward-evidence service.
- The two v2 scanners still build signals and outcomes from yfinance bars and
  correctly leave `promotion_eligible=false`.

The missing component is a shared forward collector/reader contract that
provides causal Databento bars plus contemporaneous side-specific quotes to
both scanners. A new full-history purchase is not the first implementation
step.

## Recommended implementation order

1. Freeze the evidence-source amendment: literal MBO, or MBP-1 as the minimum
   sufficient executable-quote source. Re-hash affected preregistrations.
2. Add a read-only `databento_mes_feed.py` module with no order imports. It
   owns credential checks, entitlement probes, continuous mapping, timestamp
   normalization, quote validation, and immutable DBN persistence.
3. Add an estimate-only historical adapter first. Replay existing local DBN
   fixtures in tests; no paid request is needed for TDD.
4. Add one persistent live collector only after the entitlement probe passes.
   Subscribe to the smallest approved set: MES OHLCV plus MBP-1 (or MBO).
5. Change scanners through dependency injection: their frozen calculations
   consume normalized bars/quotes, while yfinance remains an explicitly
   non-promotable fallback.
6. Re-resolve each candidate using direction-aware Databento entry and exit
   quotes. Preserve both original proxy and Databento counterfactual records;
   never overwrite history.
7. Set `promotion_eligible=true` only in the resolver after every quote-source,
   causality, freshness, mapping, completeness, and cost-provenance check passes.
8. Surface collector health, source, schema, raw contract, quote age, mapping
   age, replay/live state, delayed entitlement, and failure reason on the
   dashboard. Any ambiguity displays HOLD.

## Acceptance gates

- Fixture tests cover mapping changes, DST, Sunday Globex reopen, start/end
  boundaries, stale/crossed/zero quotes, no quote before action, book clear,
  skipped live records, disconnect recovery, and adverse-first outcomes.
- Historical tests prove no record with `ts_recv > actionable_at` influences a
  decision.
- MBO tests, if applicable, prove snapshots and `F_LAST` are honored.
- Cost tests prove estimate-only default, exact parameter parity between
  estimate and download, hard cap refusal, cache reuse, and no retry purchase.
- Secrets do not appear in process arguments, output, logs, fixtures, diffs, or
  manifests.
- Every emitted field retains `execution_enabled=false` and
  `can_submit_orders=false`; the adapter cannot import an order client.
- Promotion remains HOLD until genuine qualifying evidence satisfies every
  frozen governance gate.

## Primary sources

- [Databento historical API](https://databento.com/docs/api-reference-historical)
- [Databento live API](https://databento.com/docs/api-reference-live/client/live-blocking)
- [Official Databento Python client](https://github.com/databento/databento-python)
- [GLBX.MDP3 data catalog](https://databento.com/datasets/GLBX.MDP3)
- [Databento symbology](https://databento.com/docs/standards-and-conventions/symbology)
- [Databento schema comparison](https://databento.com/docs/knowledge-base/new-users/market-data-schemas)
- [Databento MBP-1](https://databento.com/docs/schemas-and-data-formats/mbp-1)
- [Databento MBO](https://databento.com/docs/schemas-and-data-formats/mbo)
- [Databento BBO](https://databento.com/docs/schemas-and-data-formats/bbo)
- [Databento OHLCV](https://databento.com/docs/schemas-and-data-formats/ohlcv)
- [Databento live licensing](https://databento.com/docs/portal/live-data)
