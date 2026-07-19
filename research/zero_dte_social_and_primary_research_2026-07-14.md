# 0DTE Social and Primary Research - 2026-07-14

## Scope and limitations

Research covered current Reddit discussion, public web indexing of X, YouTube,
TikTok, Instagram, and Threads, plus Cboe/OIC and academic sources. The
`last30days` X collector returned HTTP 403. TikTok blocked public crawling and
the dedicated TikTok/Instagram/Threads collector is not configured. No claim
from those inaccessible platforms is represented as verified evidence.

## High-confidence findings

1. **Normalize every intraday setup by the implied daily move.** OIC's June
   2026 Rule of 16 review defines daily standard deviation as annualized IV
   times spot divided by `sqrt(252)`. This provides a stable denominator for
   comparing ORB width, displacement, and breakout overshoot across volatility
   regimes. Source: [Options Industry Council](https://www.optionseducation.org/news/may-keytakeaways).

2. **Regime selection matters more than another indicator.** Current
   practitioner discussions consistently separate directional momentum days
   from range/premium-selling days. The repo already has VWAP/EMA trend, ORB,
   breadth, VIX term structure, HMM, and RV/IV context. The missing research
   variable was how much of the implied move had already been consumed.

3. **Exit quality is path-dependent.** Recent Reddit traders repeatedly cite
   small repeatable gains, scaling out, hard loss limits, and avoiding late-day
   lottery behavior. These are anecdotes, not proof, but they support the
   system's existing MFE/MAE telemetry and profit ratchet rather than replacing
   it with a new fixed target. Source: [current r/optionstrading discussion](https://www.reddit.com/r/optionstrading/comments/1urelw2/the_best_tips_for_0dte_trading/).

4. **Treat dealer GEX as context, not a causal oracle.** Cboe reports balanced
   customer activity and estimates net 0DTE market-maker gamma hedging at at
   most 0.2% of SPX daily liquidity. Strike-level reactions may still be useful
   shadow features, but broad claims that dealer hedging controls the tape are
   not supported by the exchange's aggregate data. Source: [Cboe 0DTE positioning research](https://www.cboe.com/insights/posts/0-dt-es-decoded-positioning-trends-and-market-impact).

5. **Retail profitability is not established by popularity.** Academic work
   using identified retail-originated S&P 500 option trades reports substantial
   aggregate retail losses despite price improvement. Social win screenshots
   cannot substitute for point-in-time fills, costs, and complete trade paths.
   Source: [Beckmeyer, Branger, and Gayda](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4404704).

## Implemented now

- Added `scripts/zero_dte_expected_move_context.py`.
- Computes `spot * atm_iv / sqrt(252)` from existing ATM IV telemetry.
- Normalizes opening-range width, displacement from ORB midpoint, and breakout
  overshoot by the implied daily move.
- Emits preregistered research bins without changing live behavior.
- Wired the fields into `adaptive_options_shadow_playbook.py` as labels and
  inputs only. They do not select a playbook, alter size, or submit orders.
- Added deterministic tests and a PowerShell runner.

## Forward trials

1. Compare long directional outcomes by expected-move consumed at entry:
   `<0.50`, `0.50-1.00`, and `>1.00`.
2. Compare ORB outcomes by ORB-width fraction: `<0.20`, `0.20-0.45`, `>0.45`.
3. Cross those bins with existing RV/IV and trend/range regimes.
4. Measure expectancy, profit factor, MFE, MAE, capture efficiency, slippage,
   and drawdown. Count failed and unavailable observations.
5. Keep all variants shadow-only until the existing promotion policy is met.

## Rejected as live upgrades

- Unverified influencer win rates or screenshots.
- Naked short 0DTE premium.
- A universal GEX buy/sell signal.
- More indicators without ablation evidence.
- Looser live entry gates to increase sample count.
