# Scheduled-Macro 30-Minute ORB — Research Note (2026-09-01)

## Verdict

The screenshots describe a coherent **candidate**, not a demonstrated edge: form the
09:30–09:59 ET range, wait for the scheduled 10:00 ET macro release, and trade only
the post-release direction that confirms outside that completed range. It is suitable
for a preregistered shadow study. It must not be treated as a trade instruction or
promoted from a same-day outcome screenshot.

## Was the September 1, 2026 catalyst real?

Yes. Two independent primary publishers scheduled releases at 10:00 ET:

- BLS scheduled the July 2026 JOLTS release for September 1 at 10:00 ET. The
  subsequently published release is stamped “For release 10:00 a.m. (ET) Tuesday,
  September 1, 2026” and reported 7.3 million job openings, 5.1 million hires, and
  5.1 million total separations. [BLS schedule](https://www.bls.gov/schedule/news_release/jolts.htm),
  [BLS July release](https://www.bls.gov/news.release/jolts.htm)
- ISM’s official release schedule states that Manufacturing PMI is released on the
  first business day at 10:00 ET, with September 1 listed for 2026. ISM also stated
  that its August 2026 Manufacturing report would be released at 10:00 ET on that
  date; its September 1 roundup reports the August composite at 54.6. [ISM calendar](https://www.ismworld.org/supply-management-news-and-reports/reports/rob-report-calendar/),
  [ISM release notice](https://www.ismworld.org/supply-management-news-and-reports/reports/ism-pmi-reports/pmi/july/),
  [ISM August roundup](https://www.ismworld.org/supply-management-news-and-reports/news-publications/inside-supply-management-magazine/blog/2026/2026-09/ism-pmi-reports-roundup-august-2026-manufacturing/)

This verifies the *scheduled information event*, not that a particular post’s $SPY/
$SPX entry, exit, or option return was achievable.

## Frozen candidate: `macro_dual_release_30m_orb_v1`

**Universe:** SPY underlying only for the initial test. SPX/SPXW options are a later,
separate executable-quote overlay.

**Eligible session:** an NYSE core session with *both* JOLTS and ISM Manufacturing
officially scheduled for 10:00 ET. Capture the calendar snapshot before the open;
missing or conflicting schedule data means **no candidate**. The first version does
not pool other 10:00 releases.

**Inputs:** SIP-quality or equivalent point-in-time 1-minute SPY OHLCV; official
release timestamps; prior completed sessions for volume baseline. No revised data,
post-close labels, social posts, or hindsight levels may enter the decision.

**Rule:**

1. Freeze `OR_high` and `OR_low` from 09:30:00 through 09:59:59 ET.
2. Do nothing before the release. Form the post-event bar from 10:00:00 through
   10:04:59; act only after it completes at 10:05.
3. Long candidate: that five-minute bar closes above `OR_high` by at least
   `max($0.05, 0.02% of OR_high)`, and its volume is at least 1.20 times the median
   volume of the prior 20 eligible 10:00–10:04 bars. Short is symmetric below
   `OR_low`. If both boundaries are crossed intrabar, require the close rule; do not
   infer order from bar high/low.
4. Enter at the **next** one-minute bar’s open (10:05) in the confirmed direction.
   One candidate maximum per session; no re-entry.
5. Initial stop is the opposite OR boundary. Target is `1.5R`; close any remaining
   position at 11:30 ET. If stop and target occur in one unresolved one-minute bar,
   score the stop first. Log the unfilled/late/missing-data state rather than inventing
   a fill.

The numerical buffer, volume threshold, target and time stop are research
parameters—not claims from the screenshots. Freeze them before collecting forward
outcomes and compare only against preregistered controls (same 30-minute ORB on
non-event sessions, and eligible 10:00 releases with only one source).

## SPY vs. SPX/SPXW mechanics

SPY is an ETF listed on NYSE Arca, while SPX is a cash-settled, European-style index
option product; their prices, liquidity, settlement, and contract multiplier are not
interchangeable. The SPY prospectus says shares trade on NYSE Arca under `SPY` and
may trade at a premium or discount to NAV. [SPY prospectus](https://www.sec.gov/Archives/edgar/data/884394/000119312526023648/d935960d497.htm)
Cboe lists SPX regular trading hours as 09:30–16:15 ET and states that expiring SPXW
options ordinarily cease trading at 16:00 ET. [Cboe SPX specifications](https://www.cboe.com/tradable-products/sp-500/spx-options/spx-specifications/)

Accordingly, any later option study must record the actual contract, expiry, bid,
ask, quote timestamp, spread, and fill rule. An SPY-bar win cannot be converted into
a claimed 0DTE SPX/SPXW percentage return.

## Existing-system comparison and gap

| Existing component | What it does | Why it does not test this candidate |
| --- | --- | --- |
| `research/spy_orb_edge_lab.py` / `scripts/spy_orb_rvol_shadow.py` | Uses a 15-minute SPY ORB with RVOL and underlying OHLCV. | No official-release join; not a 30-minute, post-10:00 design; no executable option quotes. |
| `scripts/equity_orb_scout_v2_shadow.py` | Freezes 09:30–09:44:59 range and vetoes any high-impact macro event in 09:30–15:30. | Its macro policy suppresses, rather than measures, a release-reaction setup. |
| `scripts/market_catalyst_calendar.py` | Hardcoded 2026 veto/context calendar. | On review, its September list begins at Sep. 4 and omits the Sep. 1 JOLTS + ISM releases, so it would not label this real catalyst day. The calendar needs primary-source coverage repair before it can support this study. |

## Promotion requirements

Keep `execution_enabled=false`. Require untouched forward observations, separate
in-sample/out-of-sample dates, cost stress, and executable NBBO option replay before
considering any promotion. Report loss rate, expectancy, confidence intervals,
slippage sensitivity, and the number of eligible dual-release days—not only winners.

