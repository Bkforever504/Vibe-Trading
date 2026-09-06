# Social Trade Intake Audit — 2026-09-01

## Decision

External trader material is valuable only as a **timestamped, structured claim
ledger** and a source of independently replayable hypotheses. It must not be
treated as a live alpha feed, an A+/B+ score input, or execution authority.

The current collector now rejects a callout unless it has exactly one symbol,
direction, entry zone, stop, target, timeframe, and source publication time.
Eligible rows are deduplicated into `data/social_replay_queue.jsonl` with
`execution_enabled=false`. A future replay may assess the claim only from bars
and NBBO data available after the recorded publication timestamp.

## Implementation audit

Verified locally on 2026-09-01:

- The collector's queue schema and dashboard renderer pass 30 focused tests.
- The current collection yielded 27 sources and **zero** replay-ready callouts.
- X direct capture failed because `twitter-cli` is unavailable; existing X
  entries are reviewed snapshots only. Reddit is also reviewed-snapshot-only;
  neither is a live source in the present deployment.
- YouTube discovery works, but a video or transcript is methodology research,
  not a timely trade-call channel.

This means the dashboard's Social Replay section is an honest empty queue, not
a claim that we are currently monitoring trader alerts live.

## Evidence triage

| Family | Verdict | Why |
|---|---|---|
| Options Cafe 5-minute SPY 0DTE ORB | **P1 independent replay** | Rules, time windows, exits, and a trade count are published. The author also discloses midpoint-like fills, no spread/commissions/slippage, a two-year sample, and parameter searching. Rebuild from point-in-time option bid/ask and reserve a held-out period; do not import the M/W/F filter until it survives holdout. |
| FlashAlpha 10:00 expected-move study | Keep as **context cross-check** | The study states a 193-session sample and data method, but the provider owns the data/API and the analysis is not an executable strategy or independent track record. Use it only to audit the existing expected-move module with separate data. |
| Kane Shieh 3pm gamma-pin butterfly | **Blocked** | The advertised 54–14 / 79.4% record is a vendor self-report; the point-in-time gamma-to-pin formula and an independently auditable alert/fill ledger are absent. It is not reproducible. |
| Vortex ORB asymmetry articles | Exploratory only | The stated 60-session / 20-session samples are too short for regime selection and are not an independent, cost-aware options result. Use the idea as a stratification in the ORB replay, not a signal rule. |
| Other screenshots, chat calls, and P/L cards | Discovery only | They usually lack a complete source timestamp, contemporaneous entry/stop/target, full loss record, and executable fills. |

## Corrected backlog order

1. `spy_5min_0dte_orb_shadow`: preregister a point-in-time replay using the
   published mechanical rules, real bid/ask entry and exit, commissions, a
   conservative same-bar stop/target rule, and an untouched holdout. It remains
   shadow-only.
2. Reuse existing expected-move, catalyst, level-lifecycle, RVOL, and options
   feasibility reports as analysis columns. They are filters to compare, not
   parameters to optimize after looking at results.
3. Assess flow-adjusted GEX only after a source can provide point-in-time
   option-flow classification and a documented calculation method; otherwise
   label it unavailable.
4. Do not implement the proprietary 3pm pin model from a marketing statistic.

The registry now reflects this correction: the proprietary pin entry is
`blocked_source_not_reproducible`, while the explicit 5-minute ORB replay is
P1 research. Neither has order authority.

## Required capability before social callouts can be assessed prospectively

- A policy-compliant X source (official API access or an explicitly configured
  dedicated-account collector) that records post ID and publication time.
- A permitted Reddit ingestion route with an immutable post timestamp.
- Stored original text/transcript and a source URL; screenshots alone do not
  qualify.
- Market-data replay availability from the publication timestamp forward,
  including option NBBO where option performance is claimed.

Without these, the correct dashboard state is `reviewed_snapshots_only`, never
"live alerts." 

## Sources

- [Options Cafe — 0DTE Opening Range Breakout: Rules & Backtest](https://options.cafe/blog/0dte-opening-range-breakout-strategy-spy-backtested-results/)
- [FlashAlpha — 193-session 0DTE expected-move study](https://flashalpha.com/articles/are-0dte-straddles-overpriced-193-spy-sessions-data-study)
- [The TradingPub — Kane Shieh gamma-pin promotion](https://thetradingpub.com/kane-shieh/my-0dte-spy-pin-strategy-using-a-gamma-exposure-algorithm/)
- [Vortex Capital Group — 09:30–09:45 ORB article](https://www.vortexcapitalgroup.com/insights/the-09-30-09-45-auction-opening-range-breaks-that-actually-pay)
