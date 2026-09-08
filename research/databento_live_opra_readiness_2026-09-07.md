# Databento live OPRA readiness — 2026-09-07

Scope: current Databento requirements and behaviors that matter for a live US-equity-options alert service. Sources are first-party Databento documentation and announcements checked on 2026-09-07. No account credentials or portal-private values were used.

## Executive conclusion

The practical fix is to treat Databento live OPRA as an explicitly licensed, bounded streaming service—not as an ordinary historical request. Activate `OPRA.PILLAR` live entitlement in the Databento portal, classify the bot's display/non-display and any external-distribution use accurately, and use `tcbbo` for trade-driven alerts unless the strategy genuinely needs every NBBO update. Do not use `start=0` by default. Databento provides live usage visibility, but its hard monthly spending limit does **not** apply to live data, so runtime, scope, and throughput guardrails must live in the application.

## 1. Entitlement and licensing

- An API key alone is insufficient. Databento says real-time access requires a Standard, Plus, or Unlimited plan, followed by activation under **Portal → Plans and live data** and a questionnaire that determines subscriber status and licensing requirements. Databento then activates the entitlement after required agreements/approval. [Portal: plans and live data](https://databento.com/docs/portal#plans-and-live-data)
- The use classification matters. Databento defines algorithmic trading and backend processing as non-display use; external sharing of real-time data is distribution. Personal use is limited to a non-professional individual's own investment decisions, research, or education and cannot be shared or leveraged for profit. [Portal: venue licensing requirements](https://databento.com/docs/portal#venue-licensing-requirements)
- A Discord **signal** derived from OPRA data is not necessarily the same as redistributing raw quotes, but this is a licensing question, not a technical assumption. The questionnaire should describe exactly what leaves the private system (derived alerts versus prices/quotes, recipients, delay, and whether the service is commercial), and Databento should confirm the classification before enabling external recipients.
- Databento announced OPRA Standard at **$199/month** and ended usage-based OPRA live pricing for new access on 2025-06-03; only continuously active legacy licenses could retain the old usage-based option. Historical pay-as-you-go remained available. [Databento OPRA pricing announcement](https://databento.com/blog/introducing-new-opra-pricing-plans)
- Current public materials also expose venue-specific OPRA personal/commercial device, firm, and distribution fees, while the plan page describes Standard as having live data and no license fees for its eligible personal-use tier. Therefore the portal-generated quote after the questionnaire—not a hard-coded public price—is the authoritative total for this bot's actual use. [Databento pricing](https://databento.com/pricing) · [Portal licensing table](https://databento.com/docs/portal#venue-license-fees)

**Readiness gate:** the bot should fail closed with a clear `OPRA live entitlement missing` status when authentication/subscription is rejected; it should not silently fall back to delayed or unrelated data.

## 2. Schema choice for NBBO and trades

| Need | Schema | Operational implication |
|---|---|---|
| Every consolidated NBBO update, plus trades | `cmbp-1` | Correct full-fidelity consolidated top-of-book stream, but extremely high volume. OPRA consolidated BBO records use `publisher_id=30`; trade records carry the execution venue's publisher ID. |
| Every trade with the NBBO immediately before it | `tcbbo` | Best default for trade-driven Discord alerts and trade-at-bid/ask context. OPRA does not provide aggressor side (`side` is `N`), so the preceding NBBO is the useful inference input. |
| Trades only | `trades` | Lowest-complexity tape input when spread/NBBO context is unnecessary. |
| Periodic consolidated quote/last-sale state | `cbbo-1s` or `cbbo-1m` | Lower-rate monitoring; unsuitable when every quote transition or exact trade-time NBBO is required. |

These schema semantics are defined in Databento's [schema guide](https://databento.com/docs/schemas-and-data-formats/whats-a-schema) and [OPRA dataset specification](https://databento.com/docs/knowledge-base/datasets/opra-pillar). Databento's own equity-options example says over 99.9% of OPRA events are CMBP-1 updates and recommends easier schemas such as TCBBO or trades when full quote flow is unnecessary. [Equity-options live example](https://databento.com/docs/examples/options/equity-options-introduction/using-parent-symbology-to-fetch-an-option-chain)

For live OPRA `cmbp-1`, Databento always applies slow-reader behavior `skip`, regardless of the client setting. The gateway can therefore drop stale records to catch the consumer up. The bot must surface `SkippedRecordsAfterSlowReading` as a data-quality incident rather than treating the stream as complete. [OPRA live CMBP-1 behavior](https://databento.com/docs/knowledge-base/datasets/opra-pillar#live-cmbp-1-subscriptions)

**Recommendation:** begin with one `tcbbo` subscription for the small underlying allowlist used by alerts. Add `definition` handling for contract metadata. Use `cmbp-1` only behind an explicit feature flag and a proven throughput test.

## 3. Parent symbology and identifiers

- OPRA supports parent symbology. Use `stype_in="parent"` with symbols such as `AAPL.OPT` to select the active option chain. [Databento symbology](https://databento.com/docs/standards-and-conventions/symbology) · [Parent-chain example](https://databento.com/docs/examples/options/equity-options-introduction/using-parent-symbology-to-fetch-an-option-chain)
- Parent roots are not always the cash-underlying ticker: `SPXW` is a documented example. Corporate-action-adjusted contracts can use suffixes such as `MSFT1`. Raw OCC/OSI symbols are exactly 21 characters, including the six-character space-padded root. Do not synthesize raw symbols with loose string formatting. [OPRA symbology and adjusted contracts](https://databento.com/docs/knowledge-base/datasets/opra-pillar#symbology)
- Resolve and persist canonical raw symbols/definitions rather than carrying `instrument_id` across environments. Databento states that live OPRA instrument-ID mappings are stable only within a week and differ from historical mappings. [OPRA live/historical mapping difference](https://databento.com/docs/knowledge-base/datasets/opra-pillar#differences-between-live-and-historical-data)

**Recommendation:** maintain a strict allowlist of parent roots, consume definition/symbol-mapping records, key durable state by raw symbol plus date, and regard instrument IDs as session/week-local routing values.

## 4. Live start, replay, and recovery

- Omitting `start` subscribes to current/new live messages. Supplying `start` requests inclusive intraday replay and it must be set before the session starts. The normal replay window is at most the last 24 hours and may be shorter on weekends or periods with no publication. `start=0` means all replay currently available—not “start live.” [Live API: intraday replay](https://databento.com/docs/api-reference-live/basics/overview#intraday-replay)
- Replay is filtered on `ts_event` for most schemas, but `cbbo-*`/`bbo-*` use `ts_recv`. Databento emits a per-schema replay-completed `SystemMsg` after catch-up, then the subscription continues in real time. Subscriptions added after session start cannot request replay. [Live API: intraday replay](https://databento.com/docs/api-reference-live/basics/overview#intraday-replay)
- A `Live` client session can be started only once. There is no unsubscribe operation; narrowing or replacing scope requires stopping/terminating and opening a new session. [Live client reference](https://databento.com/docs/api-reference-live/basics/overview#live-subscribe)
- For lossless reconnect recovery, Databento recommends persisting the last timestamp and the count of records seen at that timestamp per schema/instrument, replaying inclusively from the lowest saved timestamp, and de-duplicating the overlap. [Live API: recovering after a disconnection](https://databento.com/docs/api-reference-live/basics/overview#recovering-after-a-disconnection)

**Safe default:** no replay on ordinary startup. Make replay an explicit bounded duration (for example, a few minutes), reject requested starts older than the documented window, track `REPLAY_COMPLETED`, and keep Discord output disabled until replay catch-up completes so old events are not emitted as fresh alerts.

## 5. Usage visibility and budget controls

- The portal's Data Usage page shows recent (last 12 hours) cost, GB, open API keys, and connections; historical views can be filtered by date, dataset, API key, and mode including Live, then broken down by schema. A dedicated API key per bot makes this attribution usable. [Databento data-usage guide](https://databento.com/docs/portal/data-usage)
- `Historical.metadata.get_cost` and `get_billable_size` are preflight tools for historical requests. They are not live-stream caps. [Historical metadata API](https://databento.com/docs/api-reference-historical#metadata-get-cost)
- Databento's portal monthly limit blocks **historical** requests only. Its documentation explicitly says live requests are not subject to that limit and live usage is always Unlimited. [Manage historical monthly limit](https://databento.com/docs/knowledge-base/portal/billing/manage-monthly-limit)
- The documented Python `Live` constructor/subscription controls include reconnect behavior, slow-reader behavior, compression, heartbeat, symbols, schema, and replay start, but no dollar/byte budget parameter. This is an inference from the published API surface: Databento does not document a server-enforced per-client live spending cap. [Python Live API reference](https://databento.com/docs/api-reference-live/basics/overview#live)

Application guardrails should therefore include:

1. Dedicated key and `OPRA.PILLAR` entitlement preflight.
2. Parent/raw-symbol allowlist and a maximum number of roots/contracts.
3. `tcbbo`/`trades` default; `cmbp-1` requires explicit enablement.
4. No implicit `start=0`; maximum replay lookback and replay-alert suppression.
5. Maximum runtime plus record-rate/queue/memory ceilings; call `stop()` or `terminate()` on breach.
6. Heartbeat, reconnect-gap, replay-complete, slow-reader, and skipped-record telemetry routed to operational alerts.
7. Periodic portal review by the dedicated API key because application byte counts are only a local approximation of vendor accounting.

## Minimal acceptance checklist

- [ ] Portal shows active real-time `OPRA.PILLAR` entitlement for the declared use case.
- [ ] Databento has confirmed whether the specific Discord payload/audience is personal/internal use or distribution.
- [ ] A market-hours smoke test receives definition/symbol mappings and `tcbbo` records for one allowlisted parent.
- [ ] Startup without replay produces no stale alerts; bounded replay waits for replay-complete before alerting.
- [ ] Reconnect overlap is de-duplicated and any gap or skipped-record error is visible.
- [ ] The bot has its own API key, runtime/throughput limits, and a documented kill switch.
- [ ] Portal Data Usage is reviewed by key/dataset/mode/schema after the smoke test.

