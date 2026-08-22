# Social Media Algorithmic Trading Research - 2026-08-19

## Scope

Direct authenticated browser research covered X, TikTok, Threads, and Instagram. Public-web and Last30Days research covered Reddit. The intake also supports reviewed Bluesky and Truth Social snapshots when a source URL and visible text are supplied.

This work is research intake only. It cannot submit orders, change strategy status, alter sizing, or promote a social claim into execution.

## Access matrix

| Platform | Current access | Scheduled collection |
| --- | --- | --- |
| YouTube | yt-dlp search and transcripts | Yes |
| X | Authenticated browser; dedicated-cookie CLI unavailable | No unattended session reuse |
| TikTok | Authenticated browser | No provider configured |
| Threads | Authenticated browser | No provider configured |
| Reddit | Public web and Last30Days | Yes, subject to provider availability |
| Instagram | Authenticated browser | No provider configured |
| Bluesky | Reviewed snapshot adapter | No provider configured |
| Truth Social | Reviewed snapshot adapter | No provider configured |

## Findings

The X, TikTok, Threads, and Instagram samples were dominated by bot demonstrations, fast-build claims, P&L screenshots, and automation marketing. They rarely supplied all of the information required to reproduce an edge: exact entry, exit, risk, timeframe, transaction costs, losing trades, and out-of-sample validation.

No reviewed X, TikTok, Threads, or Instagram post qualified as a preregistration candidate. This is not a finding that the authors are unprofitable. It means the visible material is insufficient to reproduce and test their claims without filling gaps through hindsight.

Two Reddit discussions produced useful process hypotheses:

- Copying entries without synchronizing exits and fragmented-position state can erase apparent source expectancy.
- Large configuration searches require walk-forward validation, purging, embargo, and selection-bias controls.

These are engineering and research lessons, not promoted strategies.

## Intake policy

A source is a preregistration candidate only when it contains:

1. Exact entry rule.
2. Objective entry condition or trigger, not merely an order-entry instruction.
3. Exact exit rule.
4. Risk or invalidation rule.
5. Timeframe.
6. At least one validation field: friction, losses, backtest, or verification.

Independent verification raises the evidence tier but still does not authorize promotion. Every candidate requires an exact preregistration, cost-aware replay, out-of-sample validation, shadow evidence, and the existing promotion gates.

Profit percentages, dollar amounts, screenshots, followers, likes, and comments are not edge evidence. Marketing claims without reproducible rules are explicitly rejected and retained only as provenance.

## Operational result

The nightly Agent-Reach runner already refreshes the research report. Reviewed browser snapshots now remain available to that report even when unattended X, TikTok, or Threads providers are unavailable. The report remains fail-closed with `execution_enabled: false` and `can_submit_orders: false`.
