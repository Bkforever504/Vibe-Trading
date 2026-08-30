# Jeremy Cash “100% Winrate” Auto-Trail Video Audit

Date: 2026-08-26  
Disposition: **Do not buy, copy, or route to live execution. Extract only the exit-management idea for a frozen shadow ablation.**

## Source identity

- Exact video: [I Tried a 100% Winrate Strategy: Here Is What Happened | Jeremy Cash](https://www.youtube.com/watch?v=fBzy4gVWCyA), published by `@jeremycash32`, duration 11:31.
- The description’s bot link resolves to this [TradeSupply product page](https://tradesupply.base44.app/ProductDetail?id=6a7b3b99642fafafc7d56d95). The video is therefore product-linked promotional content, not independent validation.
- Regulatory context: [CFTC on forex bots and unrealistic return claims](https://www.cftc.gov/LearnAndProtect/forexfrauds), [CFTC forex-fraud risk guidance](https://www.cftc.gov/LearnAndProtect/AdvisoriesAndArticles/reduce_risk_of_forex_fraud.htm), and the [SEC/Investor.gov trailing-stop bulletin](https://www.investor.gov/introduction-investing/general-resources/news-alerts/alerts-bulletins/investor-bulletins-15).

## What the video actually demonstrates

This is primarily an **exit-management and trade-copying demonstration**, not a fully specified entry strategy.

1. Around 00:35–03:15, the presenter configures a cash-profit threshold that arms a trailing stop, a cash step for subsequent stop movement, and an initial amount of profit to lock.
2. Around 03:24–04:53, the software manages manual or automated entries and can close a profitable basket at a daily profit target.
3. Around 04:55–06:13, the presenter combines the bot with discretionary gold scalps and says the bot may also place its own entries.
4. Around 05:57–07:14, he adds positions while price is unfavorable and discusses add-on/retest entries.
5. Around 06:09–07:40, he says the bot can attach stops, but that he personally often trades without one because of his directional conviction in gold.
6. Around 07:18–08:17, he recommends disabling per-trade confirmation and attributes the resulting profitable closures to a “100% win rate.”
7. Around 08:25–09:18, he promotes copying demo-account trades into live and family accounts.
8. Around 09:44–11:07, he shows separate base/add-on lot sizes and a daily profit amount that can stop the bot for the day.

The video does **not** provide mechanical entry rules, a frozen sample, closed plus open equity history, maximum drawdown, net expectancy, payoff ratio, slippage, spread, margin usage, risk of ruin, or independently verified results.

## Why the headline is not evidence of an edge

The displayed win rate can be made high by closing small winners while losses remain open and therefore outside the closed-trade denominator. Adding positions to an adverse move further increases the chance of recording many small profitable tickets while concentrating risk in a rare, large basket loss. A high percentage of winning tickets is not sufficient; expectancy depends on both win probability and the sizes of wins and losses:

`expectancy = P(win) × average_win − P(loss) × average_loss − costs`

Trailing stops can reduce giveback after favorable excursion, but they cannot repair a negative-expectancy entry process. Cash-denominated thresholds also do not transfer consistently across symbols, volatility regimes, contract sizes, lot sizes, spreads, or account sizes.

The SEC notes that a stop price is a trigger rather than a guaranteed execution price and that volatile markets may execute materially away from the stop. FINRA likewise warns that trailing-stop behavior and execution depend on market conditions and firm handling: [FINRA order types](https://www.finra.org/investors/investing/investment-products/stocks/order-types).

## Decision for Vibe-Trading

### Keep

- Automated, visible transition from initial risk to a profit-protection state.
- A daily profit lock paired with the daily loss lock that the repo already enforces.
- Exit-policy telemetry: armed threshold, locked profit, trailing step, MFE, MAE, realized capture, giveback, time to arm, and stop slippage.
- One-click manual trade adoption only as read-only/shadow telemetry unless separately authorized and validated.

### Reject

- “100% win rate” as a quality metric or dashboard claim.
- No-stop trading.
- Adding to losing positions or increasing basket exposure to rescue an entry.
- Fixed-dollar trail parameters shared across instruments.
- Disabling confirmations for live orders.
- Demo-to-live or family-account copying.
- Purchasing or installing the linked bot without source review, broker compatibility review, registration/due-diligence checks, and independent evidence.

## What the repo already does better

- `scripts/flip_exit_quality_report.py` measures MFE, MAE, capture efficiency, and giveback.
- `scripts/execution_seasonality_report.py` computes path-based MFE/MAE.
- `scripts/topstepx_trade_reconciliation.py` measures executable-side MFE/MAE, giveback, and failed-after-profit behavior.
- `scripts/update_signal_outcomes.py` already supports partial-at-1R, breakeven, runner, and end-of-day outcomes.
- Equity ORB shadow scanners already model break-even activation using risk units rather than arbitrary dollars.

The useful gap is therefore **not another auto-trading bot**. It is a single reconciled dashboard view and a controlled exit-policy comparison on identical frozen entries.

## Recommended shadow-only upgrade

Create one experiment family using the same entry events for every variant:

1. Existing baseline exit policy.
2. Risk-normalized ratchet: arm after a preregistered MFE in `R`, lock a small positive `R`, and advance only on completed bars.
3. Partial at 1R, stop remainder at breakeven, runner to 2R or time exit.
4. ATR/structure trail, calculated from information available at that timestamp.
5. Time/MFE policy: exit when a setup fails to achieve minimum favorable excursion within its preregistered confirmation window.

Hard constraints for every variant:

- No averaging down and no add-on to an underwater position.
- If pyramiding is ever tested, add only to a winner after aggregate worst-case risk remains within the original budget.
- Broker-side catastrophic stop remains present from entry.
- Include bid/ask, spread, slippage, fees, gap-through behavior, and incomplete-quote states.
- Compare net expectancy, profit factor, maximum drawdown, expected shortfall, capture efficiency, giveback, MAE, and risk of ruin—not win rate alone.
- Treat all variants as one multiple-testing family and give them zero production weight until forward evidence qualifies.

## Dashboard additions worth implementing

- `TRAIL INACTIVE / ARMED / LOCKED / EXITED`
- Trigger price, current distance to trigger, locked `R`, next ratchet level, and invalidation price
- A range-based **ETA estimate** to the trigger, explicitly labeled probabilistic and unavailable when volatility/feed quality is insufficient
- Realized P&L plus unrealized P&L and total economic equity
- Closed-ticket win rate plus economic/basket win rate
- Oldest underwater position, largest open loss, aggregate basket risk, and add-on count
- Daily profit lock and daily loss lock shown together
- `NO ADD TO LOSERS`, `HARD STOP PRESENT`, and quote/fill freshness gates

## Bottom line

The video contributes one useful reminder: automate profit protection so a valid winner does not round-trip unnecessarily. The system already contains most of the underlying telemetry and safer exit primitives. The video does not supply evidence that its entry engine has positive expectancy, and its no-stop, adverse-add, confirmation-off, and copy-to-live practices conflict with this repo’s safety standard.

Recommendation: **do not adopt the bot; preregister and shadow-test the risk-normalized exit variants only.**
