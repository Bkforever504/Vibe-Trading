# Social trade-source intake — 2026-09-01

## Decision

Public posts can help discover *hypotheses* and provide a timestamped claim
ledger. They must not become an execution signal, a setup grade, or evidence
that a method has positive expectancy. A winning screenshot, a deleted post,
or a post written after the fact has no place in performance scoring.

The durable system is therefore **source capture -> structured claim ->
independent replay -> prospective scorecard**, rather than copy trading.

## What qualifies for capture

Capture an item only when all of the following are available in the original
public item:

1. a permanent source URL/ID and platform timestamp;
2. instrument and direction;
3. an exact price trigger or mechanically testable condition;
4. an invalidation/stop; and
5. a target, exit condition, or explicit time stop.

Store the immutable raw text/link, source account, observed-at timestamp,
platform-created timestamp, parser version, and every parsed field. Retain the
source identifier even when parsing fails. A post that says only “long SPY,”
“watch this,” a percentage return, or a P&L result is `context_only`, not a
trade claim.

No source is approved because it has followers, a verification badge, or a
sequence of visible winners. Approval requires a prospective, point-in-time
sample with predeclared fill, spread/slippage, time-stop, and survivorship
rules.

## Candidate public sources and disclosed rule families

| Candidate | What is actually public and reproducible | Evidence quality | Candidate rule family | Current repository coverage | Intake decision |
| --- | --- | --- | --- | --- | --- |
| r/RealDayTrading contributors | A detailed public trade log records a HOOD long at a precise time and price, market and stock conditions, technical stop, confirmation expectation, and time-stop condition. It is a useful example of a structured claim, not independently audited performance. | Medium for a single timestamped methodology example; low for source performance. Authorship and fills cannot be independently verified. | Market-first, stock-second; relative strength/weakness; SPY support/structure; stock VWAP; volume confirmation; technical/time stop. | Equity ORB Scout v2 already has daily-trend, relative-strength-vs-SPY, macro and earnings gates. Existing scanners cover VWAP, opening-range and level context. | Study as a schema/template; do not use posts as alerts or rank inputs. |
| r/RealDayTrading live chat | The archived live discussion contains contemporaneous-looking entry/target/stop statements, but authorship, completeness, edits/deletions, and execution cannot be verified. | Low. It is an example of why a raw transcript is not an edge dataset. | Varies by author; no stable, versioned rule specification. | No gap should be inferred. | Exclude from performance scoring. Manual research only. |
| TraderLion (official creator video) | The publisher describes range-break entry through highs, a higher-low stop, multi-timeframe confluence, volume/tightness, pullbacks, anchored VWAP, and ORB examples. This is methodology education, not a timestamped public alert record. | Medium for disclosed rules; no evidence of live-call performance from the video. | Breakout / pullback / ORB with volume and higher-timeframe context. | Existing `flip_shadow_setup_challengers.py`, Equity ORB Scouts, `shadow_pullback_signal.py`, VWAP guards, and contextual pattern observer overlap substantially. | Use only to form a preregistered challenger test; never copy a claimed win rate. |
| X accounts named in supplied screenshots (for example, @TheStrat, @Team2Trading, @SPYderMomTrades) | The supplied material establishes only that the accounts post trade commentary or results. It does **not** establish a stable public, machine-readable, real-time entry/stop/target history. | Insufficient until a prospective audit finds qualifying original posts. | Possible levels, ORB, price action, or scalping hypotheses, but unknown. | Existing level lifecycle, ORB, macro/catalyst, and contextual observers cover much of the cited vocabulary. | Add only to a watched-source registry; no score, alert, or strategy intake yet. |
| Public YouTube livestream channels | YouTube can provide identified live or completed broadcasts and metadata. A live-chat message can be timestamped while the chat is live, but API access is not a dependable historical transcript channel. | Low-to-medium for a time-stamped live statement; low for complete historical audit unless the creator publishes a durable structured ledger. | Depends on creator; must be separately specified. | No automatic inference. | Watchlist and manual candidate discovery only. |

Sources: [RealDayTrading detailed trade log](https://www.reddit.com/r/RealDayTrading/comments/1d9vfup), [RealDayTrading archived live chat](https://www.reddit.com/r/RealDayTrading/comments/z9h7of), and [TraderLion’s disclosed range-breakout methodology](https://www.youtube.com/watch?v=vrkDJZe9OCc).

## Platform feasibility and constraints

### X

X is the only candidate here for a near-real-time, policy-supported capture
pipeline. Its Search Posts documentation allows `from:`, cashtag, exact phrase,
and exclusion operators; recent search covers only seven days, while full
archive access is paid/Enterprise. The filtered stream is suitable for future
capture but needs an approved developer account, app, and credentials. X
documents connection and rate limits, so the collector must queue, deduplicate
on Post ID, record `created_at`, and tolerate delivery/recovery gaps. Do not
scrape the website or use an unofficial relay.

Sources: [X Search Posts](https://docs.x.com/x-api/posts/search/introduction),
[X Filtered Stream overview](https://docs.x.com/x-api/posts/filtered-stream/introduction),
[X Filtered Stream operators](https://docs.x.com/x-api/posts/filtered-stream/integrate/operators),
and [X API rate limits](https://docs.x.com/x-api/fundamentals/rate-limits).

### Reddit

Do not make Reddit a live-alert dependency. Reddit’s supported API is the only
acceptable collection path, and its Data API Terms restrict retention and
unexpressly permitted/commercial uses. Reddit has also described moving toward
more restricted developer-platform access. A moderator-approved, lawful
research project could contribute retrospective examples, but it should not
drive the dashboard or notifications without explicit permission that covers
this use.

Sources: [Reddit developer guidelines](https://developers.reddit.com/docs/guidelines),
[Reddit API overview](https://developers.reddit.com/docs/capabilities/server/reddit-api),
[Reddit Data API Terms](https://redditinc.com/policies/data-api-terms), and
[Reddit’s developer-platform update](https://www.reddit.com/r/redditdev/comments/1vgbm9c/our_plans_for_the_future_of_reddits_public_data/).

### YouTube

Use the official Data API only to discover channels/videos or identify an
active/upcoming broadcast. `search.list` can filter live, completed, or
upcoming broadcasts, but search results can be delayed and are not a reliable
new-upload feed. Live-chat messages are available while the event is live;
ended or disabled chat can return errors, and public captions are not
universally downloadable through the API. Therefore no implementation should
pretend that every spoken call is capturable or replayable.

Sources: [YouTube search API](https://developers.google.com/youtube/v3/docs/search/list),
[YouTube live-chat API](https://developers.google.com/youtube/v3/live/docs/liveChatMessages),
[live-chat listing constraints](https://developers.google.com/youtube/v3/live/docs/liveChatMessages/list),
and [caption API requirements](https://developers.google.com/youtube/v3/guides/implementation/captions).

## Required claim-ledger contract

```text
source_platform, source_account, source_url, source_post_id,
source_created_at, captured_at, raw_text_hash,
ticker, asset_class, direction,
trigger_kind, trigger_price_or_expression,
invalidation_kind, stop_price_or_expression,
target_kind, target_price_or_expression, time_stop,
method_family, parser_confidence, human_review_status,
market_data_snapshot_id, replay_status, exclusion_reason
```

`parser_confidence` is never a trade-quality score. Any ambiguity in ticker,
direction, trigger, or invalidation fails closed to `human_review_required`.
Screenshots, videos, and chart annotations require a human transcription with
the original URL and capture time; OCR alone is not admissible evidence.

## Prospective validation protocol

1. Keep a small, named list of public accounts and capture prospectively only
   through the relevant official API/authorized method.
2. Before inspecting the forward outcome, normalize every qualifying call into
   the ledger contract and bind it to immutable market bars/quotes available at
   its timestamp.
3. Declare fill model, option contract selection (if applicable), NBBO/spread
   treatment, commissions, latency, stop/target precedence, and maximum hold
   time. Exclude a claim if any of these cannot be reconstructed rather than
   granting it a favorable fill.
4. Compare against an instrument-matched baseline and against the repository’s
   independent A+/B+ decision contract. Keep source claims as `external_context`
   until enough out-of-sample observations exist.
5. Publish losses, misses, deleted/edited posts, non-qualifying posts, and
   latency failures alongside winners. Source promotion needs an auditable
   sample and a pre-set threshold; it is never discretionary.

## Recommended product boundary

The dashboard may eventually show a separate **External Claim Ledger** card:
`captured`, `human_review_required`, `replay_pending`, `replayable`,
`insufficient_fields`, or `excluded`. It must be visually and logically
separate from `A+`/`B+ executable-review eligibility.

An external post can at most name a symbol/level that the independent scanner
then evaluates using current bar completion, catalyst, liquidity, risk, spread,
and strategy-family rules. It must not place an order, change position size,
override a veto, or turn a weak internal setup into GREEN.

## Concrete gaps worth investigating—not implementing yet

1. **Relative-strength measurement and walk-forward test:** the methodology
   example motivates auditing the existing relative-strength feature’s formula,
   point-in-time availability, and out-of-sample behavior—not adding another
   subjective “RS” label.
2. **Equity ORB/pullback challenger:** the repository already has multiple ORB
   implementations. Establish a single preregistered comparison with volume,
   VWAP, higher-timeframe, catalyst, and slippage assumptions before merging or
   ranking variants.
3. **External-call replay harness:** first build this data-quality tool; do not
   ingest social feeds into execution. It can reveal whether purportedly great
   trades were posted early enough and with enough detail to have been
   executable.

The likely permanent fix is not finding a better personality to follow. It is
maintaining a causal, auditable pipeline that tells us whether a source’s calls
were complete, timely, and independently executable before letting any new
rule influence the scanner.
