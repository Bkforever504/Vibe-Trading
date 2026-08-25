# Databento CME Equity-Index Futures Data Integration

Date: 2026-08-24
Status: implementation guidance; first-party sources only
Scope: Python historical and live ingestion for MNQ, NQ, MES, and ES. This
note does not authorize order submission or redistribution.

## Decision

Use Databento dataset `GLBX.MDP3` for all four CME Globex products. Build two
data planes:

1. Use `ohlcv-1s` or `ohlcv-1m` for time-bar signal features.
2. Use `mbp-1` for contemporaneous best-bid/best-ask evidence for a
   one-contract liquidity-taking model. Use `mbp-10` or a correctly maintained
   `mbo` book when quantity can sweep the top level, and use `mbo` when queue
   position or passive-fill modeling is required.

An OHLCV close, last trade, midpoint, or sampled BBO is a price proxy, not an
executable side-specific quote. Even an observed bid or ask is not proof of a
fill; only the execution venue or broker fill record proves execution.
([schema catalog](https://databento.com/docs/schemas-and-data-formats),
[MBP-1](https://databento.com/docs/schemas-and-data-formats/mbp-1),
[MBO](https://databento.com/docs/schemas-and-data-formats/mbo))

## Dataset and products

| Product | Exchange product | Historical/live dataset | Parent request | Suggested liquid continuous request |
|---|---|---|---|---|
| `MNQ` | Micro E-mini Nasdaq-100 | `GLBX.MDP3` | `MNQ.FUT`, `stype_in="parent"` | `MNQ.v.0`, `stype_in="continuous"` |
| `NQ` | E-mini Nasdaq-100 | `GLBX.MDP3` | `NQ.FUT`, `stype_in="parent"` | `NQ.v.0`, `stype_in="continuous"` |
| `MES` | Micro E-mini S&P 500 | `GLBX.MDP3` | `MES.FUT`, `stype_in="parent"` | `MES.v.0`, `stype_in="continuous"` |
| `ES` | E-mini S&P 500 | `GLBX.MDP3` | `ES.FUT`, `stype_in="parent"` | `ES.v.0`, `stype_in="continuous"` |

`GLBX.MDP3` contains CME, CBOT, NYMEX, and COMEX futures and options. Databento
receives the direct MDP 3.0 feed and derives normalized schemas from CME's
order-level MBOFD feed rather than normalizing CME's incremental MBP feed.
Databento documents futures/options coverage beginning on 2010-06-06, but full
granularity MBOFD begins on 2017-05-21. Legacy data before MDP 3.0 does not
have a true capture timestamp or MBO: `ts_recv` is set equal to `ts_event` and
`F_BAD_TS_RECV` is set; timestamps before 2015-11-20 have only millisecond
resolution. MNQ and MES launched later than the dataset, so product availability
must not be inferred from the dataset start. Actual availability is
schema-, product-, and entitlement-specific and must be read from definitions
and `metadata.get_dataset_range()` at runtime.
([GLBX.MDP3 dataset guide](https://databento.com/docs/knowledge-base/datasets/glbx-mdp3),
[historical metadata](https://databento.com/docs/api-reference-historical/metadata/metadata-get-dataset-range))

Parent symbology selects a product family, not one lead contract; it can include
multiple outrights and futures spreads. Use it for discovery or a deliberate
multi-contract collector. Use a raw contract such as `ESH7` when an immutable,
specific expiry is required. Use a continuous symbol when the intent is a
systematic lead-contract series.

## Symbology and roll rules

Databento accepts four input symbology types (`stype_in`):
`raw_symbol`, `instrument_id`, `parent`, and `continuous`. All datasets support
raw-symbol/instrument-ID conversion; `GLBX.MDP3` also supports parent and
continuous inputs. For time-series and batch requests, the default output
symbology is `instrument_id`. Parent and continuous symbology are input
selectors, not generally valid textual output mappings; resolve/persist the
actual raw symbol and `instrument_id` that carried each record.
([symbology conventions](https://databento.com/docs/standards-and-conventions/symbology),
[`symbology.resolve`](https://databento.com/docs/api-reference-historical/symbology/symbology-resolve))

Continuous futures syntax is `[ROOT].[ROLL_RULE].[RANK]`, where rank is
zero-indexed:

| Rule | Code | Mapping basis |
|---|---|---|
| Calendar | `c` | Nearest expiry, then next expiry by rank |
| Open interest | `n` | Previous day's closing open interest |
| Volume | `v` | Previous day's trading volume |

For these liquid equity-index futures, `.v.0` is a defensible default when the
strategy means "currently most active contract"; `.c.0` is appropriate only
when it literally means nearest expiry. The choice is part of the strategy and
must be frozen before a backtest. Databento's continuous prices are original,
unadjusted exchange prices, so rollover gaps remain. Persist each mapping
interval and never treat a roll jump as a return. A trade that crosses a roll
must either close/reopen under an explicit roll policy or be marked
non-comparable.
([continuous symbology](https://databento.com/docs/standards-and-conventions/symbology#continuous),
[continuous-contract example](https://databento.com/docs/examples/symbology/continuous))

Historical mappings can be obtained free with `Historical.symbology.resolve`;
the response includes date intervals and resolved identifiers, plus `partial`
and `not_found` diagnostics. A request accepts up to 2,000 symbols. Live
mappings arrive as `SymbolMappingMsg` records containing the requested symbol,
raw output symbol, `instrument_id`, and mapping interval. Preserve these
records in the raw stream.
([historical API symbology](https://databento.com/docs/api-reference-historical/symbology/symbology-resolve),
[live symbol mapping example](https://databento.com/docs/examples/symbology/live-symbol-mapping))

Important live constraint: an existing continuous-symbol subscription is not
remapped to a different instrument when the rule's mapping changes. A new
identical subscription may resolve differently. Therefore reconnect or renew
the subscription at the controlled daily/roll boundary and verify the fresh
`SymbolMappingMsg` before accepting records into the promotable lane.
([live symbology](https://databento.com/docs/api-reference-live/basics/schemas-and-conventions))

## Schema and field contract

| Schema | Event space and useful fields | Suitable use | Not sufficient for |
|---|---|---|---|
| `mbo` | Every order event at all levels: `order_id`, `action`, `side`, `price`, `size`, `flags`, `sequence`, timestamps | Queue/order-flow research; passive-limit simulation; reconstructing full depth | Direct use without a stateful book; broker fill proof |
| `mbp-10` | Aggregated top 10 price levels with bid/ask price, size, and count | Multi-level liquidity-taking and depth/impact estimates | Order queue position; guaranteed fills |
| `mbp-1` | Every event changing BBO plus trades; `bid_px_00`, `ask_px_00`, `bid_sz_00`, `ask_sz_00`, `bid_ct_00`, `ask_ct_00` | Small aggressive orders and exact event-space spread evidence | Depth beyond BBO; passive queue; fill proof |
| `tbbo` | Each trade plus the BBO immediately before that trade | Trade-context and aggressor studies | Quote at an arbitrary non-trade signal time |
| `bbo-1s`, `bbo-1m` | Last BBO and last sale in each populated interval | Coarse monitoring and low-volume quote review | Intrasecond quote path or exact signal-time quote |
| `trades` | Every last sale: `price`, `size`, aggressor `side` when available, event/receive timestamps | Time and sales; trade-derived bars | Current bid, ask, spread, or displayed liquidity |
| `ohlcv-1s`, `-1m`, `-1h`, `-1d` | Trade-derived `open`, `high`, `low`, `close`, `volume`; interval start timestamp | Bar signals and research features | Quotes, spread, queue, or executable price |
| `definition` / `statistics` / `status` | Tick size, expiry/reference data; official statistics/open interest; trading state | Validation, contract metadata, roll diagnostics, halt/session controls | Substitute for the quote or trade stream |

The current `GLBX.MDP3` schema list should be discovered with
`metadata.list_schemas()` rather than hard-coded. Databento currently lists
`mbo`, `mbp-1`, `mbp-10`, `tbbo`, `trades`, BBO, OHLCV, `definition`,
`statistics`, and `status` for the dataset.
([schema list and fields](https://databento.com/docs/api-reference-historical/metadata/metadata-list-schemas),
[schema comparison](https://databento.com/docs/schemas-and-data-formats))

### Executable-quality versus proxy

For a one-contract aggressive model at causal decision time `t`:

- buy/cover uses the latest valid `ask_px_00` whose chosen causal timestamp is
  not after `t`;
- sell/short uses the latest valid `bid_px_00` whose chosen causal timestamp is
  not after `t`;
- reject a missing, stale, crossed, nonpositive, non-tick-aligned quote, or a
  quote whose displayed size does not cover the modeled quantity;
- retain spread, quote age, displayed size, mapping, sequence, and source
  record identifiers with the modeled execution;
- label the result `quote_observed_not_fill` and retain commissions and a
  preregistered residual latency/impact penalty.

`mbp-1` is the minimum complete event-space BBO source. Databento itself uses
MBP-1 for instantaneous spread-crossing/slippage examples and states it is
sufficient for minimum-size liquidity-taking under a simplifying zero-latency
assumption. For larger quantity, walk `mbp-10` levels or a reconstructed MBO
book; displayed liquidity can cancel before arrival, so neither guarantees a
fill.
([high-frequency liquidity-taking example](https://databento.com/docs/examples/algo-trading/high-frequency),
[execution slippage example](https://databento.com/docs/examples/algo-trading/execution-slippage/result))

`bbo-1s`/`bbo-1m` is sampled in time space. Its `ts_recv` is the interval end;
last-sale or BBO values may be forward-filled within a printed interval, and no
record prints when neither a trade nor quote update occurs. It is acceptable
only when the evidence policy explicitly permits that sampling granularity.
`tbbo` is sampled in trade space and reports the BBO immediately before each
trade, so it cannot establish the quote at an unrelated signal timestamp.
([BBO schema](https://databento.com/docs/schemas-and-data-formats/bbo),
[TBBO schema](https://databento.com/docs/schemas-and-data-formats/tbbo))

MBO consumers must build state. Historical CME data includes a synthetic book
snapshot at the start of each UTC day, and live MBO can request `snapshot=True`.
For CME, apply an event atomically through the record carrying `F_LAST`; the
book between event fragments may show an apparent quote that has already
traded. A live snapshot is not valid until an `F_LAST` boundary if the last
snapshot record itself lacks that flag.
([CME MBO normalization](https://databento.com/docs/knowledge-base/datasets/glbx-mdp3),
[MBO snapshots](https://databento.com/docs/standards-and-conventions/mbo-snapshot))

Treat `flags` as a bit field, not an equality value. At minimum, quarantine
records marked `F_BAD_TS_RECV` from receive-time latency/causality analysis and
fail the executable-book lane on `F_MAYBE_BAD_BOOK` until state is recovered.
Handle `UNDEF_PRICE`/undefined timestamps explicitly rather than coercing them
to valid numeric observations.
([flags and undefined values](https://databento.com/docs/standards-and-conventions/common-fields-enums-types))

## Timestamp semantics

All DBN timestamps are nanoseconds since the Unix epoch. Keep UTC internally
and use timezone-aware `pandas.Timestamp` or ISO 8601 inputs; a bare date means
midnight UTC, and an integer input means Unix nanoseconds.

| Field | Meaning |
|---|---|
| `ts_event` | Publisher/matching-engine event time; for CME, tag 60 `TransactTime` |
| `ts_in_delta` | Nanoseconds from publisher sending time to `ts_recv`; publisher send time is `ts_recv - ts_in_delta` |
| `ts_recv` | Databento capture-server receive time; hardware timestamped, UTC-synchronized, and monotonic per symbol |
| `ts_out` | Optional live gateway-send time; request with `Live(ts_out=True)` |

Publisher and Databento clocks need not be identical; `ts_in_delta` may be
negative and is clamped to signed 32-bit bounds. Use `ts_event` for exchange
event chronology and `ts_recv` for what the Databento collector could have
observed. For strict causal replay of this integration, make the decision clock
explicit and use `ts_recv <= actionable_at` unless the strategy specification
defines another clock and latency model.
([timestamp conventions](https://databento.com/docs/standards-and-conventions/common-fields-enums-types#timestamps),
[CME timestamps](https://databento.com/docs/knowledge-base/datasets/glbx-mdp3#timestamps))

Every schema has an index timestamp: `ts_recv` when the schema contains it,
otherwise `ts_event`. Historical `get_range` filters on that index timestamp.
The range start is inclusive and end is exclusive. OHLCV `ts_event` marks the
interval start and is based on trade-message `ts_recv`; `ohlcv-1d` uses UTC
dates, not CME session dates, and omits intervals with no trades. Re-aggregate
finer bars when exchange-session daily bars are required.
([historical range API](https://databento.com/docs/api-reference-historical/timeseries/timeseries-get-range),
[OHLCV schema](https://databento.com/docs/schemas-and-data-formats/ohlcv))

## Authentication and secret handling

Install and pin the official Python client (`databento`) and its resolved DBN
dependency. Both `db.Historical()` and `db.Live()` read the
`DATABENTO_API_KEY` environment variable when `key` is omitted; Databento
discourages passing a literal key in production code.
([official Python client](https://github.com/databento/databento-python),
[live client constructor](https://databento.com/docs/api-reference-live/client/live))

Required repository behavior:

- inject `DATABENTO_API_KEY` into the process/service environment;
- never put a key in source, `.env` committed to Git, CLI arguments, task
  manifests, cache metadata, exceptions, screenshots, or logs;
- construct `db.Historical()` / `db.Live()` without a key argument;
- log only a boolean such as `databento_api_key_present`, never key content,
  prefix, suffix, or length;
- isolate the feed adapter from all broker/order clients.

Example (intentionally contains no credential):

```python
import databento as db

historical = db.Historical()
live = db.Live(
    heartbeat_interval_s=30,
    reconnect_policy="reconnect",
    ts_out=True,
)
```

## Entitlements, licensing, and service limits

An API key authenticates an identity; it does not by itself grant live CME
rights. Real-time and intraday data require a qualifying plan and completed
venue licensing classification. Databento distinguishes personal/commercial,
display/non-display, internal/external, and distribution use. Algorithmic
trading and automated order/quote generation are non-display uses. External
sharing or a customer-facing feed/display can be distribution and must not be
assumed permitted. Rights and fees are dataset/use-case specific and must be
confirmed in the Databento Plans and live data portal before starting a live
collector.
([portal licensing guide](https://databento.com/docs/portal/live-data),
[pricing and redistribution FAQ](https://databento.com/pricing))

As of this note, the official portal guide says CME personal use is included
with Standard for up to two devices, while commercial use can require venue
fees/approval. These terms and fees can change; store the entitlement decision
and its effective date, not a copied price, and revalidate before deployment.
Historical access older than the live/intraday licensing window is separately
metered or included by plan, and the user's actual per-schema range is the
authority.

Current documented technical limits:

| Surface | Limit |
|---|---|
| Historical concurrency | 100 connections per IP |
| Historical time-series | 100 requests/second/IP |
| Historical symbology | 100 requests/second/IP |
| Historical metadata | 20 requests/second/IP |
| Batch list | 20 requests/second/IP |
| Batch submit | 20 requests/minute/IP |
| Live connections | Standard: 10 per dataset per team; Plus/Unlimited: 50 |
| Live new connections | At most 5/second from one IP to a gateway |
| Live subscription requests | Above 10/second are delayed, not rejected |

Extra API keys do not increase the per-team live session limit. Reuse one
`GLBX.MDP3` live session for multiple symbols and schemas. Historical monthly
spend limits can block further historical requests; live use is not governed
by that historical usage cap.
([historical limits](https://databento.com/docs/api-reference-historical/basics#rate-limits),
[live limits](https://databento.com/docs/api-reference-live/basics#connection-limits),
[billing limits](https://databento.com/docs/portal/billing))

## Historical discovery, estimation, and retrieval

Run these read-only/estimate calls before any billable download:

```python
import databento as db

client = db.Historical()
dataset = "GLBX.MDP3"

schemas = client.metadata.list_schemas(dataset=dataset)
available = client.metadata.get_dataset_range(dataset=dataset)
units = client.metadata.list_unit_prices(dataset=dataset)

request = dict(
    dataset=dataset,
    symbols=["MNQ.v.0", "NQ.v.0", "MES.v.0", "ES.v.0"],
    stype_in="continuous",
    schema="mbp-1",
    start="2026-08-21T13:30:00Z",
    end="2026-08-21T20:00:00Z",
)
estimate_usd = client.metadata.get_cost(**request)
```

`get_dataset_range()` is entitlement-aware and returns overall plus per-schema
inclusive start/exclusive end. `get_cost()` estimates the exact matching range
or batch request and respects plan discounts. Databento warns that estimates
can over-report ranges not divisible into 10-minute blocks; `definition`
estimates are reliable on 24-hour multiples. Billing is based on actual bytes
sent. Keep exact parameter parity between estimate and download, and enforce
per-request and daily USD caps before calling a time-series or batch method.
([metadata API](https://databento.com/docs/api-reference-historical/metadata),
[`get_cost`](https://databento.com/docs/api-reference-historical/metadata/metadata-get-cost))

For bounded interactive retrieval, `timeseries.get_range()` streams DBN and
returns a `DBNStore`; use a `.dbn.zst` `path` so the original response is
persisted before conversion:

```python
data = client.timeseries.get_range(
    **request,
    path="immutable-cache/request-id.dbn.zst",
)
df = data.to_df()
```

There is no application-level pagination requirement: the HTTP stream carries
the requested range. `limit` caps record count and is not a page cursor. There
is no stated size ceiling, but Databento recommends batch for requests over
5 GB. Split smaller immutable requests if bounded retry or memory behavior is
needed; do not retry a billable request merely because a local conversion
failed. Honor HTTP `429` and `Retry-After`.
([historical basics and size limits](https://databento.com/docs/api-reference-historical/basics),
[`get_range`](https://databento.com/docs/api-reference-historical/timeseries/timeseries-get-range))

For large retrievals, submit a background flat-file job, poll its state, list
files, verify the supplied SHA-256, and download:

```python
job = client.batch.submit_job(
    **request,
    encoding="dbn",
    compression="zstd",
    split_duration="day",
)
job_id = job["id"]

details = client.batch.get_job_details(job_id=job_id)
files = client.batch.list_files(job_id=job_id)
paths = client.batch.download(job_id=job_id, output_dir="immutable-cache")
```

Batch supports duration splitting (`day`, `week`, `month`, `year`, `none`) and
1-10 GB size splitting. `split_symbols` cannot be combined with
`ALL_SYMBOLS` or `limit`; `limit` also cannot be combined with
`split_symbols`. A completed batch can be downloaded repeatedly during its
retention period without issuing another data request. Persist the returned job
metadata, request fingerprint, filenames, sizes, hashes, client versions, and
normalization version, but never the API key.
([batch API](https://databento.com/docs/api-reference-historical/batch),
[programmatic batch example](https://databento.com/docs/examples/basics-historical/programmatic-batch-download))

## Live session, heartbeat, and recovery

Use one long-lived `db.Live` client for `GLBX.MDP3`. A session is bound to one
dataset but supports multiple subscriptions and schemas; there is no
unsubscribe method. Callbacks must be non-blocking so disk/analytics work does
not stall the networking loop.
([`Live.subscribe`](https://databento.com/docs/api-reference-live/client/subscribe),
[`Live.add_callback`](https://databento.com/docs/api-reference-live/client/add-callback))

Recommended lifecycle:

1. Create with `heartbeat_interval_s=30`, `reconnect_policy="reconnect"`, and
   `ts_out=True` when gateway latency diagnostics are useful.
2. Subscribe before start; include explicit symbols/schema/stype. Request
   `snapshot=True` only for MBO.
3. Persist raw DBN, `SymbolMappingMsg`, `SystemMsg`, and `ErrorMsg` records
   before normalized projections.
4. Treat `SLOW_READER_WARNING`, skipped records, replay aged out, an unresolved
   symbol, book clear, or an unhealed reconnect gap as non-promotable.
5. Use `add_reconnect_callback` to record the last received event timestamp and
   the reconnected session start. Backfill/validate every gap before restoring
   eligibility.
6. Renew continuous subscriptions at the controlled roll boundary and verify
   the new mapping.

The gateway sends a heartbeat `SystemMsg` only when no other record was sent
during the interval. The default interval is 30 seconds and the documented
configurable range is 5-1,800 seconds. A connection with no messages for one
heartbeat interval plus 10 seconds can be treated as hung. On a clean TCP
disconnect without an error, wait one second before reconnecting to avoid the
gateway rate limiter. Automatic `reconnect` renews the subscriptions with no
replay start, so it does not itself fill the missed interval; the reconnect
callback's timestamps are a gap marker, not proof of recovery. Recover the gap
with an explicit replay/backfill and deterministic de-duplication (or an MBO
snapshot when rebuilding that state). Do not automatically retry a fatal
`ErrorMsg` with the same parameters; fix authentication, entitlement,
connection-limit, or subscription errors first.
([live system/error handling](https://databento.com/docs/api-reference-live/basics#system-messages),
[live error detection](https://databento.com/docs/api-reference-live/basics#error-detection),
[`add_reconnect_callback`](https://databento.com/docs/api-reference-live/client/add-reconnect-callback),
[official Python reconnect implementation](https://github.com/databento/databento-python/blob/main/databento/live/session.py))

Live intraday replay normally covers retained data within the last 24 hours;
weekends/inactive periods may expose less. CME MBO and `definition` have a
special full-weekly-session replay path because of their statefulness. Replay
filters on `ts_event` except BBO/CBBO, which use `ts_recv`; a `REPLAY_COMPLETED`
system message is emitted per schema. A subscription added after the session
starts is not eligible for replay. Use `start=0` for the full replay window
available to that schema and inspect `REPLAY_DATA_AGED_OUT` rather than assuming
coverage.
([live intraday replay](https://databento.com/docs/api-reference-live/basics#intraday-replay))

Monitor [Databento Status](https://status.databento.com/) and subscribe to its
incident/maintenance updates. Also call
`metadata.get_dataset_condition()` for historical dates being promoted; an
operational status page alone does not prove a requested day's data is complete.

## Integration acceptance contract

The remaining Databento gap is closed only when all of the following hold:

1. The collector uses `GLBX.MDP3` and an allowlist of MNQ/NQ/MES/ES symbols and
   approved schemas.
2. Every record retains dataset, schema, requested continuous/parent/raw
   symbol, resolved raw symbol, `instrument_id`, `publisher_id`, `ts_event`,
   `ts_recv` where present, sequence/flags, and raw-cache provenance.
3. Historical requests prove entitlement range, cost estimate, hard-cap pass,
   exact request fingerprint, immutable DBN persistence, byte count, and
   SHA-256 before normalization.
4. Roll mappings are explicit; no P&L crosses a mapping change accidentally.
5. Signal features use only records causally available by `actionable_at`.
6. Aggressive modeled entries/exits use direction-aware MBP-1 (or deeper-book)
   quotes with freshness, spread, size, tick, halt, and session checks.
7. OHLCV/trades/midpoint/sampled BBO fallback remains explicitly
   `proxy_only=true` and cannot pass an executable-evidence promotion gate.
8. MBO, if selected, is snapshot-initialized and updated only through atomic
   `F_LAST` boundaries.
9. Disconnects, slow-reader/skipped-record warnings, replay gaps, mapping
   ambiguity, or incomplete dataset conditions fail closed until backfilled.
10. Credentials and licensing assertions never appear in the data artifacts;
    only credential presence and entitlement decision metadata are recorded.
11. Feed code has no broker/order dependency and retains
    `execution_enabled=false` / `can_submit_orders=false`.

## Primary-source index

- [Official Python client](https://github.com/databento/databento-python)
- [Historical API](https://databento.com/docs/api-reference-historical)
- [Live API](https://databento.com/docs/api-reference-live)
- [GLBX.MDP3 dataset guide](https://databento.com/docs/knowledge-base/datasets/glbx-mdp3)
- [Schemas and data formats](https://databento.com/docs/schemas-and-data-formats)
- [Symbology](https://databento.com/docs/standards-and-conventions/symbology)
- [Timestamp conventions](https://databento.com/docs/standards-and-conventions/common-fields-enums-types)
- [Portal licensing guide](https://databento.com/docs/portal/live-data)
- [Billing guide](https://databento.com/docs/portal/billing)
- [Databento status page](https://status.databento.com/)
