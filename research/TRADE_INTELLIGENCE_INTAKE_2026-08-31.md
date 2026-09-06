# Trade-intelligence intake: August 31

All items below are research/shadow-only. A social post, screenshot, or account return is not evidence of a deployable trading edge.

## 1. Trader Barbie: daily / 4H 50% level

The supplied post adds a materially useful detail to the existing CE hypothesis: use the 50% level of either a daily or 4-hour dealing range as a confluence level; trade continuation only after price breaks and holds it, and consider the reversal only after a sweep back through it (her "failed 2" language). This is not equivalent to the already-tested 3-minute CE recross, so it is registered separately as `daily_4h_50pct_hold_or_failed2`.

Needed before a test: define the causal swing/dealing range, prohibit using a swing only visible after the trade, define a hold (one close, two closes, or retest), and define the failed-2 trigger and risk. Until then it has no ranking or alert effect.

## 2. Normalized performance reporting

The key useful idea in the post attributed to The Milk Man is methodological, not a strategy: judge returns per unit of exposure rather than raw points or raw dollars. Our research uses fixed notional and transaction costs, which already prevents a later high-price regime from automatically looking better merely because the same points are worth more. For every new futures test, report R-multiples / return on risk as well as dollars, include costs, and preserve a date-blocked out-of-sample segment. This is now a review requirement, not a signal feature.

## 3. Flat Moon Society: MNQ ORB

The screenshot claims a NinjaTrader strategy that forms data on 1-minute bars, trades 15-minute breakouts, takes one trade a day, and distinguishes 2020–24 in-sample from 2025+ out-of-sample. That design is testable and the one-trade/day cap is valuable because it limits repeated intraday selection. It is registered as `mnq_orb_15m_breakout_1m_execution`, but remains data-partial until we have continuous MNQ history with roll handling and realistic futures fills. A representative ORB description also treats the first 15 minutes as the range and requires a confirmed breakout rather than a wick; that is a hypothesis to test, not proof of profitability. [ORB strategy overview](https://theorbstrategy.com/blog/orb-strategy-for-nq-and-mnq/)

## 4. GEX levels

GEX is an estimate of the hedging flow dealers may need to transact as an underlying moves; it is not an observable support/resistance guarantee. [SpotGamma's definition](https://spotgamma.com/what-is-gex-gamma-exposure/) makes the dependency clear: a usable test needs timestamped, provenance-checked options-chain inputs, contract open interest, implied volatility, and a documented calculation. Our system already marks GEX as data-blocked; screenshots of attractive levels do not remove that block. No external GEX level is copied into the scanner.

## 5. JJ Simon channel claims

The screenshots show public performance claims and quant-finance-themed videos, but no complete, reproducible entry/exit specification. The transferable principle is process: guard against trying many variants on the same data, reserve truly untouched data, and compare equal-risk outcomes. There is no strategy candidate until a video/source yields precise causal rules.

## Outcome

The Wolves/BBR proxy tournament is complete in `data/wolves_bbr_tournament.json`: every SPY/QQQ 5m/15m lane was negative after baseline costs (profit factors 0.60–0.73). This rejects the tested proxy, not every possible implementation of the author's discretionary method. It has zero promotion authority.
