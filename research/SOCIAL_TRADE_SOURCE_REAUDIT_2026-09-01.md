# Social trade-source re-audit — 2026-09-01

## Decision

The repository has a useful **shadow replay queue**, but it does **not** yet
have a compliant, live social-trader collector. Its current data should be
called methodology discovery plus reviewed snapshots, not trader-alert
coverage. There are **zero** currently queued, independently replayable
external calls.

No external item may alter A+/B+ classification, override a risk veto, generate
a GREEN alert, change size, or submit an order. A post can show an attractive
entry after the fact without supplying a contemporaneous, executable instruction.

## Current implementation: verified status

| Path | What it actually does today | Honest status | Prospective replay call today? |
| --- | --- | --- | --- |
| X | `collect_x()` shells out to an unavailable `twitter` executable and requires browser-cookie environment variables. It does not call X's official API. The latest report records `x: twitter-cli unavailable`. | Unavailable; reviewed snapshots only | No |
| Reddit | There is no Reddit collector in `agent_reach_trading_research.py`; configured rows are manually supplied snapshots. | Reviewed snapshots only | No |
| YouTube | Discovery/transcript code invokes `yt-dlp`, not the official YouTube Data API. It can surface educational videos, but the transcript has no immutable spoken-call timestamp or official delivery guarantee. | Methodology discovery only | No |
| Web | The collector fetches pages through `r.jina.ai`; this is a reader/proxy, not an authoritative event feed, and pages can omit original publication time. | Research only | No |
| Dashboard | It reads `data/social_replay_queue.jsonl`, reports channel status, and labels the section shadow-only. The current report has `replay_ready_callouts: []` and a zero queue count. | Accurately empty | N/A |

The queue writer requires a parsed symbol, direction, entry, stop, target,
timeframe, and source timestamp. But it accepts any nonempty supplied timestamp
string and trusts the configured `access_mode`. A screenshot-derived or manual
value could therefore look replay-ready. Before any live workflow, require an
immutable platform ID, original UTC created-at, raw-content hash, capture time,
and API/authorized-collection provenance. This is a data-integrity gap, not a
trading-signal gap.

## Official collection capability

### X: viable after provisioning, not configured

X recent search supports structured searches for the last seven days, including
`from:` and keyword operators; full archive is pay-per-use or Enterprise. The
filtered stream can deliver matching public posts in near real time, but needs
an approved developer account, project, app, bearer token, and paid access. Its
documented P99 delivery latency is about 6–7 seconds, which is still too slow
to assume an option fill at a poster's displayed level. [X search overview](https://docs.x.com/x-api/posts/search/introduction)
and [filtered-stream documentation](https://docs.x.com/x-api/posts/filtered-stream/introduction)
support these capabilities and constraints.

**Required disposition:** `not_configured_official_api`; do not represent a
cookie-based CLI as direct X coverage. If provisioned, use account/query
allow-lists and retain Post ID, edit history, created-at, raw text, matching
rule, and capture latency. X documents that edits have separate IDs and edit
history, so edits/deletions must be state changes, not overwritten records.

### Reddit: conditional, authorization first

Reddit's supported API can expose posts, comments, IDs, bodies, and creation
times in communities where an app is installed, but current terms require
authorized access and restrict use, storage, and rate limits. It is not a
guaranteed general-public firehose for this project. [Reddit API overview](https://developers.reddit.com/docs/capabilities/server/reddit-api)
and [Data API Terms](https://redditinc.com/policies/data-api-terms) are the
controlling sources.

**Required disposition:** `approval_required_no_collector`. Do not scrape
HTML/JSON endpoints or use Reddit as a live notification dependency. It can
become a retrospective, permissioned research input only after the intended use
and retention are approved.

### YouTube: official discovery is feasible; live calls are not

The official Data API can discover public videos and broadcasts with
`search.list` and publisher metadata. It does not make search a low-latency
event stream, captions have separate authorization/availability constraints,
and live-chat messages are usable only while a chat is available. [YouTube
Search API](https://developers.google.com/youtube/v3/docs/search/list),
[live-chat listing](https://developers.google.com/youtube/v3/live/docs/liveChatMessages/list),
and [caption guidance](https://developers.google.com/youtube/v3/guides/implementation/captions)
support those limits.

**Required disposition:** `official_api_not_configured_methodology_only`. Use
the official API for named-channel methodology discovery after a project/API key
is configured. Never label a transcript or spoken level as a timely alert unless
a separately captured live-chat message contains all complete call fields.

## Concrete source review

These examples are useful for **schema and hypothesis design**, not for proving
an edge or populating today's queue.

| Source family/example | What is reproducible | Why it does not enter the live queue | Research disposition |
| --- | --- | --- | --- |
| r/RealDayTrading raw HOOD log | A historical log states a HOOD long at 22.785, conditional stop (SPY 533 breach / HOOD VWAP close), 22.98 passive target, and M5 confirmation process. | It is retrospective; the Reddit post timestamp is not proof that the levels were publicly captured before the move, and the stop is conditional rather than one executable price. | Manual schema example for market-first + relative-strength + VWAP; no performance inference. [Original log](https://www.reddit.com/r/RealDayTrading/comments/1d9vfup/my_raw_trading_log_how_i_stay_focused_prepared/) |
| r/Daytrading SPY review | A recent review supplies SPY long 769.21, stop 767.07, 1R 771.35, runner 772.50, and higher-timeframe/15-minute H1 volume criteria. | The post follows the outcome; it has no pre-entry public capture, immutable live timestamp, or complete source ledger. | Replay-methodology example only. [Original review](https://www.reddit.com/r/Daytrading/comments/1w0c1x8/spy_day_trade_review_05r_but_the_biggest_win_was/) |
| r/RealDayTrading community method | Public examples discuss market-first, stock-second, relative strength/weakness, SPY levels, VWAP, volume, and completed M5 confirmation. | Different authors vary rules; chats are incomplete/editable and personal P&L cannot verify expectancy. | Audit existing relative-strength, VWAP, level, and completed-bar gates rather than multiply them. |
| X indexed explicit calls | An indexed post can contain entry range, stop, and target. | The reviewed example lacks complete direction/timeframe and the system has no official X collector. | Discovery only until official capture exists. |
| YouTube educators/livestreams | Videos can disclose repeatable rules and date metadata. | Videos are commonly post-event; captions/spoken timestamps do not establish timely, executable levels. | Preregistration/hypothesis source only. |

No reviewed X, Reddit, YouTube, or web item currently has all of: verified
contemporaneous platform timestamp; one underlying/contract; direction; entry
condition/price; invalidation; target/time stop; timeframe; and market-data
snapshot beginning at publication. This audit adds **no callout** to
`social_replay_queue.jsonl`.

## Source families worth tracking (unvalidated)

1. **Pre-committed personal trade logs**: useful only if a tamper-evident
   pre-entry record exposes thesis, stop, time stop, and target.
2. **Named-channel YouTube methodology libraries**: potentially useful for
   challenger specifications, never for copied win rates.
3. **Public X account allow-lists**: the best prospective claim source after
   official API provisioning, but accounts must show enough complete calls,
   losses, and non-trades before their methods receive attention.
4. **Discord, Telegram, and paid rooms**: exclude unless separately authorized
   and the provider supplies durable, permissioned timestamped records.

## Durable closure plan

1. Build the independent 5-minute SPY 0DTE ORB shadow replay separately from
   social intake: point-in-time NBBO, conservative intra-bar sequencing, fees,
   latency, and untouched holdout are mandatory.
2. Create a capture-grade ledger: `platform`, `author`, `post_id`, `url`,
   `created_at_utc`, `captured_at_utc`, `raw_text_hash`, edit/deletion state,
   underlying/contract, direction, entry, stop, target, timeframe, parser
   version, and capture latency. Fail closed on ambiguity.
3. Provision official X before claiming live-source coverage. The dashboard
   should say `not_configured`, not await browser cookies.
4. After 30–50 prospectively captured complete calls with a point-in-time fill
   model, compare them against a baseline and the independent scanner. Include
   losses, edited/deleted posts, and missed fills.
5. Promote only a rule: preregistered definition, cost-aware training period,
   untouched holdout, regime stability, and prospective shadow results are
   required before a feature can face the executable-review gates.

## Final status matrix

| Platform | Official capability in principle | Credentials/authorization present | Current source role | Eligible calls | Alert/execution role |
| --- | --- | --- | --- | ---: | --- |
| X | Yes; paid/API provisioning | No | Snapshots only | 0 | None |
| Reddit | Conditional; authorization/terms | No | Snapshots/research | 0 | None |
| YouTube | Yes; API project/key | No | `yt-dlp` methodology discovery | 0 | None |
| Web articles | N/A; not a social stream | N/A | Rule research | 0 | None |
| Dashboard queue | N/A | N/A | Empty shadow ledger | 0 | None |

The permanent fix is not a larger trader list. It is a capture-to-replay
pipeline that proves a call was timely and executable before its rule can have
any influence on the scanner.
