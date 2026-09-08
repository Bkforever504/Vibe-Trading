# Primary-source catalyst intake for the shadow scanner

**Date:** 2026-09-08
**Decision:** Build a low-latency, shadow-only nomination lane from SEC EDGAR and issuer-controlled investor-relations/newsroom sources. It may create `CATALYST_WATCH` candidates, but it must not select an option contract, bypass deterministic gates, or submit an order.

## Executive conclusion

The fastest defensible design is a two-stage intake:

1. Poll the SEC's global Latest Filings RSS/Atom surface and issuer-approved RSS/news pages for new identifiers and metadata.
2. Verify the primary document and correlate the event with completed-bar Fast Tape, price, volume, VWAP, spread, liquidity, and no-chase gates before a candidate can advance from `WATCH` to `ARMED` or `CONFIRMED`.

EDGAR's Submissions API is unusually timely: the SEC says it is updated as filings are disseminated, with a **typical processing delay under one second**, although delays can be longer during filing peaks. The associated documents are not equally immediate; the SEC says filings are often available on `sec.gov` **one to three minutes after the EDGAR system timestamp**. Therefore, a newly observed accession can be called a *near-real-time filing nomination*, but not a verified real-time news signal until the relevant document or exhibit has been retrieved and parsed. [SEC EDGAR API update schedule](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) · [SEC Webmaster FAQ](https://www.sec.gov/about/webmaster-frequently-asked-questions)

## Source hierarchy

| Tier | Source | Safe use | Timing label |
|---|---|---|---|
| 1 | SEC Latest Filings RSS/Atom and `data.sec.gov/submissions/CIK##########.json` | Discover accepted/disseminated filings; accession number is the canonical deduplication key | `near_real_time_metadata` only when observed promptly and the SEC timestamp is present |
| 1 | SEC filing index, primary document, and exhibits under `sec.gov/Archives/edgar/data/` | Verify form, items, text, attachments, and filing provenance | `primary_document_verified`; never infer document availability from metadata |
| 1 | Manually approved company IR/newsroom RSS or release page on an issuer-controlled domain | Detect issuer-published releases that may appear before or alongside an 8-K/6-K | `publisher_observed`; do not call real-time without a measured source-specific SLA |
| 2 | X Filtered Stream | Nominate a URL, ticker, or possible event for primary-source verification | `unverified_secondary_nomination`; never sufficient for `ARMED` or `CONFIRMED` |

The SEC explicitly supports RSS for Latest Filings and company/form-filtered searches. Its public Latest Filings page displays the accepted time to the second and describes the list as filings received and processed at the SEC. [SEC RSS guidance](https://www.sec.gov/about/rss-feeds) · [SEC Latest Filings](https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent)

Company IR delivery is not standardized, so it requires a governed registry. For example, NVIDIA's own investor-relations site links separate press-release, event, presentation, and SEC-filing RSS feeds; Qualcomm's IR release list exposes release times, while its stock quote explicitly says that quote data is delayed by 20 minutes. These examples support using publisher releases as catalysts, not using an IR site's embedded quote as market data. [NVIDIA IR RSS](https://investor.nvidia.com/investor-resources/rss/default.aspx) · [Qualcomm Investor Relations](https://investor.qualcomm.com/) · [Qualcomm press releases](https://investor.qualcomm.com/news-events/press-releases/)

## Proposed low-latency flow

```text
SEC Latest RSS/Atom ─┐
                     ├─> normalize + dedupe ─> primary-document verification
Issuer IR/RSS ───────┘                                  │
                                                        v
X nomination ─> primary URL required ─────────────> CATALYST_WATCH
                                                        │
                                               completed 1m tape test
                                                        │
                                              ARMED or INVALIDATED
                                                        │
                                      completed 5m + execution-quality gates
                                                        │
                                         CONFIRMED shadow Discord card
```

### SEC discovery

- Poll one global Latest Filings Atom/RSS query rather than polling every CIK continuously. Filter locally against the scanner's governed `ticker -> CIK` universe.
- Start with high-information forms: `8-K`, `6-K`, `10-Q`, `10-K`, `20-F`, `SC 13D`, `SC 13G`, tender/merger forms, and registration/prospectus forms. Preserve form items and amendment status; do not turn a form type alone into directional sentiment.
- On a new in-universe accession, fetch that issuer's Submissions JSON and then the accession index/document. The Submissions endpoint is unauthenticated and includes at least one year or 1,000 recent filings. [SEC EDGAR API documentation](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
- Use a global token bucket capped below the SEC maximum (recommended internal ceiling: 8 requests/second with burst 8). The SEC's published maximum is 10 requests/second in total, regardless of the number of machines, and it may block excessive clients. [SEC fair-access guidance](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data)
- Every request must carry a declared `User-Agent` identifying the application/operator and a real administrative contact email. The SEC supplies this exact pattern and may manage undeclared automated tools. [SEC fair-access guidance](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data)
- Apply exponential backoff plus jitter to `403`, `429`, and `5xx`; queue verification instead of retry-storming. Missing or delayed documents remain `pending_verification` and cannot advance.
- Do not use the nightly bulk ZIPs or daily indexes as the intraday trigger. The SEC says bulk API archives are rebuilt nightly, and same-day indexes are updated nightly. [SEC EDGAR API documentation](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) · [Accessing EDGAR data](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data)
- Do not use the structured-disclosure RSS feeds as the fast trigger: the SEC says those courtesy feeds update every ten minutes on weekdays from 6 a.m. to 10 p.m. Eastern. They are suitable for reconciliation, not low-latency entries. [SEC structured-disclosure RSS](https://www.sec.gov/data-research/structured-data/structured-disclosure-rss-feeds)

### Issuer IR/newsroom discovery

Maintain a reviewed `issuer_source_registry` with `symbol`, `CIK`, exact host, feed/page URL, source kind, expected timezone, polling floor, parser version, last successful fetch, and reviewer. A feed is Tier 1 only when the issuer's own IR/newsroom page links it or the exact host has been manually approved. Redirects outside the allowlist downgrade the event to `unverified`.

- Prefer issuer-published RSS/Atom over scraping HTML.
- Poll approved feeds conditionally with `ETag`/`If-None-Match`, falling back to `Last-Modified`/`If-Modified-Since`. These are cache validators; `Last-Modified` describes the selected web representation and must **not** be treated as the press-release publication time. [RFC 9110 HTTP Semantics](https://www.rfc-editor.org/info/rfc9110/)
- Set a conservative per-host cadence (for example, 15–30 seconds during the extended market day) unless that publisher explicitly permits faster access. Respect `Retry-After`, source terms, robots policy, and any stated limits.
- Hash normalized content and deduplicate by canonical URL plus publisher ID/GUID. A title change, correction, or repost is a new revision of the same event, not a new trading catalyst.
- Never source market price, volume, spread, or quote freshness from the IR page. Use the governed market-data fabric.

## Timestamp contract

Every event needs distinct timestamps. Combining them would make latency claims and chart alignment misleading.

| Field | Meaning | Rule |
|---|---|---|
| `source_accepted_at` | EDGAR acceptance timestamp | Preserve the raw value and normalize through the explicit SEC-time rule below; null for non-EDGAR events |
| `source_published_at` | Publisher/Atom publication time | Normalize to UTC only if the source supplies an unambiguous offset/timezone; date-only values stay date-only |
| `source_updated_at` | Atom/RSS update time or publisher revision time | Never substitute for original publication time; Atom defines `updated` as the most recent significant modification [RFC 4287](https://www.rfc-editor.org/info/rfc4287/) |
| `http_last_modified_at` | Server's representation-modification time | Transport/cache metadata only, not catalyst time [RFC 9110](https://www.rfc-editor.org/info/rfc9110/) |
| `collector_received_at` | UTC wall-clock time when bytes reached the collector | Required for every fetch/event |
| `collector_monotonic_ns` | Local monotonic observation clock | Use for within-process latency; immune to wall-clock adjustments |
| `document_verified_at` | Time primary content and provenance checks completed | Null until verified |
| `scanner_armed_at`, `scanner_confirmed_at`, `discord_delivered_at` | Downstream lifecycle times | Written by their actual stages; never backfilled by inference |

Persist `timestamp_precision` (`second`, `minute`, `date`, `unknown`) and `clock_status`. Compute source-to-observation latency only when both endpoints are unambiguous and clock health is good. Otherwise report `latency_ms: null` with a reason.

EDGAR's accepted time and filing date are not interchangeable. The SEC describes acceptance as the point at which a submission has passed acceptance review; its operating/dissemination rules also allow many submissions started after 5:30 p.m. Eastern to receive the next business day's filing date and dissemination. [SEC acceptance messages](https://www.sec.gov/submit-filings/filer-support-resources/how-do-i-guides/understand-messages-reported-edgar) · [SEC filing status and hours](https://www.sec.gov/submit-filings/filer-support-resources/how-do-i-guides/determine-status-my-filing)

**SEC timestamp trap:** preserve `acceptanceDateTime_raw`. Matching current SEC outputs show that the Submissions JSON may serialize an acceptance time with a trailing `Z` while the filing page and Latest Filings Atom present the same clock value as Eastern time with an explicit `-04:00` offset. Therefore, do not blindly parse the JSON suffix as UTC; reconcile it against the accession's Atom/index accepted time and flag disagreement. This is an inference from matching official outputs, not a documented schema guarantee. [Example Submissions JSON](https://data.sec.gov/submissions/CIK0001805526.json) · [Matching filing index](https://www.sec.gov/Archives/edgar/data/1805526/000180552626000098/0001805526-26-000098-index.htm) · [Latest Filings Atom](https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&output=atom)

The SEC does not expose a canonical timestamp for the instant a document first becomes publicly retrievable. Record `collector_first_seen_at` yourself and label acceptance-to-observation as an upper-bound operational measure, not exact SEC dissemination latency. [SEC Webmaster FAQ](https://www.sec.gov/about/webmaster-frequently-asked-questions)

## Minimum event record

```json
{
  "event_id": "sha256(source|accession_or_guid|revision)",
  "symbol": "QCOM",
  "cik": "0000804328",
  "source_class": "sec_edgar",
  "source_status": "primary_document_verified",
  "form": "8-K",
  "items": ["1.01", "7.01", "9.01"],
  "accession": "...",
  "canonical_url": "https://www.sec.gov/Archives/...",
  "source_accepted_at": "...",
  "source_published_at": null,
  "collector_received_at": "...",
  "document_verified_at": "...",
  "content_sha256": "...",
  "revision": 1,
  "freshness_status": "fresh",
  "verification_reason": null,
  "execution_enabled": false,
  "can_submit_orders": false
}
```

Raw secrets never belong in event records. Keep only source URLs, hashes, status, response timing, and non-sensitive HTTP diagnostics. Store primary documents by URL/hash only unless retention and licensing rules explicitly permit local storage.

## Lifecycle and gates

1. `OBSERVED`: New accession/GUID/URL received.
2. `PENDING_VERIFICATION`: Metadata is plausible but the document or allowlisted primary page is unavailable.
3. `CATALYST_WATCH`: Primary provenance verified; still not directional and not actionable.
4. `ARMED`: Completed one-minute Fast Tape agrees, price remains inside the governed entry/no-chase envelope, and market data is fresh.
5. `CONFIRMED`: Completed five-minute structure plus spread, liquidity, regime, risk, and delivery-deadline gates pass.
6. `INVALIDATED`: Price, tape, time, correction, provenance, or liquidity invalidates the candidate.
7. `EXPIRED`: The event's action window elapsed without confirmation.

A metadata-only EDGAR event may enter `PENDING_VERIFICATION` but not `ARMED`. A publisher event may enter `CATALYST_WATCH` once its allowlisted page is retrieved and hashed. No source may override a deterministic veto, stale-data gate, or no-chase boundary.

## What may and may not be called real-time

**Defensible wording**

- `SEC near-real-time metadata`: the Submissions API was observed promptly after dissemination, carrying the SEC acceptance timestamp.
- `primary document verified`: the filing/release content was successfully retrieved from the primary source.
- `publisher observed`: the collector detected a change on an approved issuer source; no latency SLA is implied.
- `X near-real-time nomination`: X describes Filtered Stream as near real time and currently reports delivery within seconds, but that describes transport, not factual verification. [X Filtered Stream documentation](https://docs.x.com/x-api/posts/filtered-stream/introduction)

**Prohibited wording**

- Do not call a nightly bulk file, nightly index, ten-minute structured RSS feed, or historical reconciliation `real_time`.
- Do not call an IR HTML polling result real time unless a forward measurement shows the source's publication and observation timestamps with a documented SLA.
- Do not infer a filing's publication time from HTTP `Date` or `Last-Modified`.
- Do not call an X post, screenshot, repost, rumor, or account badge a verified catalyst.
- Do not describe the filing document as available merely because accession metadata exists.

## Safe role for X

X can help discover symbols and URLs earlier than a broad polling pass. Its output must be `nomination_only`:

- retain post ID, author ID, `created_at`, collector time, text hash, and expanded URLs;
- require the claimed fact to resolve to SEC, the issuer's allowlisted IR/newsroom, an exchange/regulator, or another explicitly approved primary authority;
- discard screenshots without a primary URL as evidence; OCR may aid search but cannot verify the claim;
- never derive entry, direction, grade, or urgency from engagement metrics;
- expire an unverified nomination quickly and display `UNVERIFIED — NO TRADE`;
- preserve edits as revisions because X says edited posts receive new IDs with edit history.

X's own documentation calls Filtered Stream near-real-time and documents reconnect behavior, but neither speed nor author identity establishes the truth of a market claim. [X Filtered Stream documentation](https://docs.x.com/x-api/posts/filtered-stream/introduction)

## Operational acceptance gates

Keep this lane shadow-only until all of the following hold prospectively:

- 20 consecutive market sessions with no duplicate Discord delivery from the same accession/GUID/revision.
- At least 95% of in-universe SEC events have all required timestamp and provenance fields, or are explicitly marked incomplete.
- SEC request rate never exceeds the internal 8 requests/second ceiling and all requests use the approved contact-bearing User-Agent.
- Source outage, parse failure, redirect mismatch, clock uncertainty, rate limit, and unavailable document each produce an explicit fail-honest status.
- At least 30 paired catalyst candidates have completed-bar chart outcomes and delivery receipts before any claim of improved timeliness or trade quality.
- Promotion requires human review, purged/out-of-sample evaluation, and an execution-authority audit with zero violations. No automatic threshold optimization or auto-promotion.

## Concrete recommendation for the existing scanner

Replace per-symbol rapid SEC polling with a lightweight global Latest Filings discovery loop plus event-driven per-CIK verification. Retain the existing `sec_catalyst_feed` as a slower reconciliation/health adapter, but rename its event freshness from bare `live` to the measured states above. Add a manually reviewed issuer-source registry for the core universe and make every source expose its own latency, health, and timestamp precision.

This lane should improve awareness of events such as a newly announced partnership without turning every headline into a trade. The primary source establishes that an event occurred; completed market data establishes that the market is actually reacting; the execution-quality gates establish whether an entry remains available. All three are required.
