# MES Public Strategy Replication Tournament Preregistration

Date frozen: 2026-08-10

Experiment: `MES-PUBLIC-REPLICATION-01`

## Purpose

Translate a small set of public ES/MES trading concepts into deterministic rules and test every translation under the same conservative replay assumptions. This is a consumed-history diagnostic, not proof that a public trader is profitable and not authority to place an order.

## Data

- Source: `examples/mes_v0_1m_2022-01-01_2026-07-19_rth.csv`
- Eligible period: 2024-01-01 through the last available session.
- Bars: one-minute MES RTH bars, 09:30 through at least 15:55 New York time.
- Exclusions: incomplete sessions and sessions containing an intraday contract change.
- Chronology: 2024 discovery diagnostic, 2025 selection gate, 2026 sealed-within-this-experiment holdout.
- Limitation: this dataset and period have been used by other repository experiments. The holdout is structurally separated for this experiment but is not independent confirmation.

## Common Execution Model

- One MES contract and at most one trade per strategy per session.
- Entry is the open of the bar after all signal conditions are observable.
- One-bar-delay stress adds one further bar before entry without changing the observed setup.
- Stops have priority when stop and target are both inside the same one-minute bar.
- Positions flatten at the 15:55 bar open.
- Base friction: one tick of slippage and $1.24 commission per side.
- Stress friction: 2x and 3x the complete base friction.
- Minimum initial risk: four ticks. Maximum initial risk: 60 ticks.
- No pyramiding, averaging down, discretionary overrides, or live order route.

## Frozen Strategies

### 1. `orb_breakout_control`

The first 15 minutes define the opening range. From 09:45 through 10:30, the first close at least one tick outside the range and on the same side of live VWAP is a signal. Enter next-bar open, stop one tick beyond the signal bar's opposite extreme, and target 1.5R.

Public concept reference: [Nexural ES futures strategies](https://www.nexural.io/blog/es-futures-trading-strategies). This is a mechanical translation, not copied proprietary code.

### 2. `ib_failure_to_vwap`

The first hour, 09:30 through 10:29, defines initial balance. From 10:30 through 13:00, a bar must trade at least one tick beyond an initial-balance boundary and close back inside it. A failed high must remain above live VWAP; a failed low must remain below live VWAP. Enter the next-bar open toward VWAP, stop one tick beyond the failure bar, and target signal-time VWAP. Required reward/risk is at least 1.0.

Public concept reference: [Reddit Initial Balance strategy discussion](https://www.reddit.com/r/FuturesTrading/comments/1uto3kr/initial_balance_strategy/), including the described failed-IB move back toward New York VWAP. This translation does not establish the poster's profitability.

### 3. `vwap_reclaim_retest`

From 09:45 through 13:30, five consecutive closes must be on one side of their causal live VWAP values, followed by a close through VWAP. Within the next three bars, price must retest within two ticks of live VWAP and close back on the reclaimed side with a directional candle-body confirmation. Enter next-bar open, stop one tick beyond the retest bar, and target 1.5R.

Public concept references: [Reddit VWAP reclaim discussion](https://www.reddit.com/r/FuturesTrading/comments/1vhffuf/vwap_reclaim_strategy_from_beginners/) and [Bulls on Wall Street VWAP reclaim rules](https://www.bullsonwallstreet.com/post/vwap-reclaim-trading-strategy). This is a frozen synthesis of public descriptions.

### 4. `vwap_band_reentry`

After 10:00 and through 13:30, calculate causal session VWAP and the volume-weighted standard deviation of typical price. A bar must open beyond the 1.5-standard-deviation band and close back inside it while remaining on the entry side of VWAP. Enter next-bar open toward VWAP, stop one tick beyond the reentry bar, and target signal-time VWAP. Required reward/risk is at least 1.0.

Public concept reference: [Reddit VWAP deviation discussion](https://www.reddit.com/r/FuturesTrading/comments/1e9mptg/). The exact 1.5-band interpretation is frozen here before running this tournament.

### 5. `opening_drive_vwap_pullback`

The first 15-minute range must be at least the median first-15-minute range of the prior 20 eligible sessions. Net displacement must be at least 60% of that range, the 09:44 close must finish in the outer 20% of the range, and it must be on the matching side of live VWAP. Through 11:30, take the first pullback within two ticks of live VWAP that closes back on the drive side with directional candle-body confirmation. Enter next-bar open, stop one tick beyond the pullback bar, and target 2R.

Public concept reference: opening-drive and trend-pullback concepts summarized in [Nexural ES futures strategies](https://www.nexural.io/blog/es-futures-trading-strategies). This is a causal research translation, not a claim that those exact thresholds came from the source.

## Frozen Evidence Gates

A strategy is a historical survivor only if all conditions pass:

1. At least 15 trades in 2025 and 8 trades in 2026.
2. Positive 2x-cost expectancy and profit factor at least 1.10 in both 2025 and 2026.
3. Positive 2x-cost expectancy in every represented year from 2024 through 2026.
4. Aggregate 2x-cost expectancy is positive and profit factor is at least 1.15.
5. Aggregate 2x-cost expectancy remains positive with one extra entry bar of delay.
6. Aggregate 2x-cost expectancy remains positive after the best 1% of trades are set to zero.
7. At least two-thirds of represented quarters have positive 2x-cost expectancy.
8. The one-sided 99% circular-block-bootstrap lower bound for mean daily P&L is above zero. The 99% level is the Bonferroni-adjusted 5% family error rate for five strategies.

Topstep Combine bootstrap diagnostics are run only for historical survivors. Passing a historical gate can authorize only a frozen forward-practice lane after independent review; it cannot authorize live trading or a Combine purchase.

## Locked Safety Fields

Every output must include:

- `execution_enabled: false`
- `can_submit_orders: false`
- `orders_submitted: 0`

No post-result parameter changes are allowed under this experiment identifier.
