# Liquid Market Edge Confidence Review - 2026-07-19

## Decision

No strategy is authorized for live execution. The 9/10 promotion standard remains in force.

The strongest local edge is not SPY day trading. It is the frozen 12-month, top-two, weekly momentum rotation across ten liquid ETFs. Its 2025 through 2026-07-17 extension returned 51.08%, with profit factor 3.456, Sharpe 1.572, 12.20% maximum drawdown, and 23 completed holding periods. Doubling modeled switch cost left 49.01%. This is meaningful underlying evidence, but it is not an option backtest.

## Confidence Scorecard

| Candidate | Confidence | Status | Main reason |
|---|---:|---|---|
| Ten-ETF 12-month momentum, weekly top-two | 7.8/10 | Lead paper candidate | Strong 2025+ extension and independent mechanism; still adjusted ETF data with no venue fills or option replay |
| QQQ RSI2 prior-high exit plus elevated volume | 6.7/10 | Continue daily shadow | Positive post-cutoff sample, but selected from a volume matrix and only 14 forward logger days so far |
| TQQQ first-five-minute direction plus opening RVOL | 5.8/10 | Shadow, short side only | Positive 2024-2025 short-side OOS, but 2020-2021 and 2026 are negative; leverage and regime dependence are material |
| QQQ 15-minute OR retest plus EMA fan and RVOL | 4.8/10 | Shadow only | 2025+ improved, but 2020-2023 development expectancy was negative and the bootstrap interval crosses zero |
| Collateralized index put-write / volatility risk premium | 4.5/10 local | Research queue | Strong external mechanism and transparent Cboe benchmarks, but no local option-chain history or tail-risk replay yet |
| SPY ORB family | 2.0/10 | Reject | Negative holdout expectancy in the exact first-bar and retest replications |

Only a strategy score of at least 9.0/10 can enter a manual promotion review. None qualifies today.

## Local Results

### Frozen momentum extension

- Universe: SPY, QQQ, GLD, XLE, TLT, IWM, XLK, XLV, XLF, XLI.
- Frozen rule: 12-month trailing return, rebalance every five trading days, hold the top two positive assets equally, otherwise cash.
- Original selection window ended 2024-12-31.
- 2025+: +51.08%, PF 3.456, Sharpe 1.572, win rate 69.6%, max drawdown 12.20%, 23 trades.
- 2025: +38.08%, Sharpe 2.258.
- 2026 through July 17: +8.95%, PF 1.516, Sharpe 0.804, max drawdown 12.20%.
- Double modeled cost: +49.01% for the full forward extension.
- Latest model holdings: XLK and IWM.

Report: `~/.vibe-trading/reports/momentum-rotation-forward-extension.json`

### Exact first-five-minute direction replication

The published rule enters at the second five-minute bar open in the direction of the first bar. It is not a later breakout entry. The corrected replay excludes the 16:00 extended-hours bar and uses 09:30 through 15:55 ET.

- SPY RVOL EOD variant: failed, 253 post-publication trades, -0.346R expectancy.
- IWM RVOL EOD variant: flat, 235 trades, +0.012R expectancy.
- QQQ RVOL EOD variant: marginal, 262 trades, +0.125R; bootstrap interval crosses zero.
- TQQQ RVOL EOD variant: 254 trades, +0.556R, +20.706 bps/trade, PF 1.755, double-cost +0.511R.
- TQQQ direction split: long -0.087R, short +1.209R.
- TQQQ yearly expectancy: 2020 -0.850R, 2021 -0.223R, 2022 +0.647R, 2023 +0.026R, 2024 +0.827R, 2025 +0.722R, 2026 -0.112R.

That instability blocks promotion despite the attractive pooled result.

Report: `~/.vibe-trading/reports/liquid-universe-orb-replication.json`

### Opening-range retest replication

Eight fixed variants tested 15- and 30-minute opening ranges, next-bar retest entries, 13/48/200 EMA fan, relative opening volume, prior-day levels, 2R targets, one basis point per side, doubled-cost stress, stop-first intrabar ambiguity, direction splits, and moving-block bootstrap.

The best row was QQQ OR15 + EMA + RVOL:

- Development through 2023: 106 trades, -0.114R expectancy, PF 0.846.
- 2025+: 65 trades, +0.292R, +9.034 bps/trade, PF 1.483.
- Doubled cost: +0.124R, PF 1.176.
- Bootstrap 95% interval: -0.032R to +0.608R.
- 2025: +0.465R expectancy; 2026: +0.015R.

This looks like regime change, not a stable copied edge. It stays shadow-only.

Report: `~/.vibe-trading/reports/liquid-universe-retest-lab.json`

## What Winning Posts Actually Contain

The recurring directional recipe is objective levels plus confirmation: previous-day high/low, premarket or opening range, higher-timeframe bias, a lower-timeframe breakout/retest, volume participation, a defined invalidation, and one or two trades. Those ingredients are hypotheses, not proof.

The audit of [Coach Mak's thread](https://x.com/WealthCoachMak/status/2078611703198359732) found a different business from small-account directional trading: roughly $300,000 to $800,000 of collateral, liquid names, 0.15 to 0.25 delta, and 7 to 42 DTE put selling. The dollar income shown online should therefore be judged against collateral and tail risk. It does not validate weekly call buying.

The inspected [TradingWarz](https://x.com/TradingWarz) and [vision](https://x.com/visionstonks) posts showed selected wins and frameworks, but no complete account-level sequence with losses, slippage, capital, and withdrawals. They can generate testable rules, not confidence.

Recent Reddit research included both selected winners and unusually candid failure evidence, including a trader reporting a full year without a green month. The recent sample reinforces survivorship bias rather than identifying a reproducible call/put system: [failed-trader thread](https://www.reddit.com/r/Daytrading/comments/1uyyk8e/yes_i_admit_it_i_am_a_failed_trader_i_am_tired_of/), [edge-validation discussion](https://www.reddit.com/r/algotrading/comments/1uv285c/swing_traders_how_do_you_find_and_validate_a/), and [assigned short-put example](https://www.reddit.com/r/thetagang/comments/1v0247o/sold_put_on_spacex_spcx_at_150_for_600_prem_got/).

## Mechanisms Worth Keeping

1. **Diversified trend/momentum.** The primary literature documents time-series momentum across 58 liquid equity-index, currency, commodity, and bond futures, with return persistence over 1 to 12 months. This matches the strongest local result better than social-media scalping does: [Moskowitz, Ooi, and Pedersen](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2089463).
2. **Volatility risk premium.** Cboe maintains transparent PutWrite and BuyWrite benchmark methodologies. The edge is compensation for left-tail exposure, not free yield: [Cboe benchmark fact sheet](https://cdn.cboe.com/resources/indices/documents/benchmarks-fact-sheet.pdf), [PUTVM methodology](https://cdn.cboe.com/api/global/us_indices/governance/PUTVM_Methodology.pdf).
3. **QQQ retest timing.** A 2026 descriptive paper found retest timing more informative than large pre-retest excursions, but explicitly made no exploitability claim. Our local test supports caution: [QQQ retest study](https://papers.ssrn.com/sol3/Delivery.cfm/6745958.pdf?abstractid=6745958&mirid=1&type=2).
4. **Post-earnings drift.** The anomaly has a plausible under-reaction mechanism, but option prices often already incorporate the known surprise and trading frictions reduce profitability. It needs event data and historical option quotes before implementation: [PEAD and option traders](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2146181), [earnings announcement risk premia](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4342267).
5. **Directional option demand.** Recent research reports that call and put volume have different information content around earnings and that the relationship changes by regime. Aggregate put/call ratios are therefore too crude: [directional option demand study](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6448100).

## Call and Put Evidence Contract

No underlying backtest may be reported as option P&L. A directional signal must now capture:

- exact OCC contract and call/put direction;
- bid, ask, spread, quote timestamp, and quote age;
- delta, gamma, theta, vega, rho, implied volatility, open interest, and volume when observed;
- underlying price and timestamp;
- signal rule, level, direction, risk reference, and RVOL;
- later monitor and exit snapshots joined by signal ID;
- visible blockers when data is missing or the contract fails liquidity checks.

The new `liquid_options_edge_shadow.py` implements the signal-side contract. It has no order client and cannot submit orders.

## Promotion Gates

All gates are mandatory:

1. At least 30 untouched forward signals and 20 completed option lifecycles.
2. Positive underlying and option expectancy after actual bid/ask marks.
3. Positive lower bound from a dependence-aware bootstrap or a documented reason it is not estimable.
4. Positive results under doubled realistic cost.
5. No single year, direction, or symbol provides more than half of total profit.
6. Maximum drawdown and tail loss fit the account risk budget.
7. Independent data-source replication.
8. No lookahead, survivorship, timestamp, or corporate-action audit finding.
9. Manual promotion review with execution guards still disabled during review.
10. Confidence score at least 9.0/10 after all evidence is recorded.

## Automation

Windows task `\VibeTrade\LiquidOptionsEdgeShadow` is registered with 12 checks from 08:40 through 10:30 America/Chicago. Its first scheduled-path test completed with result code 0 on the closed market. Logs are written to `~/.vibe-trading/logs/liquid-options-edge-shadow.log`.

