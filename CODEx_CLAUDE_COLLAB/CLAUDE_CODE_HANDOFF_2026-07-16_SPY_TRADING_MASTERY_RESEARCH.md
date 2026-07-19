# Claude Code Handoff: SPY Trading Mastery Research

Date: 2026-07-16 CT
Author: Claude Code
Repo: C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading

## User Intent

Kenny asked for extensive multi-source research on mastering SPY trading — all strategies,
best traders, backtested data, social media, and internet. This handoff captures all findings
for Codex to implement as bot logic, shadow strategies, or paper trading lanes.

---

## What SPY Is (For Bot Context)

- Most liquid instrument on earth. $30B+ daily options volume.
- ~45% of all S&P 500 options volume is now 0DTE.
- Options expire: Mon / Wed / Fri (0DTE available every MWF). Weekly every Friday. Monthly 3rd Friday.
- Market makers continuously gamma-hedge, creating mechanical price movements around key strikes.
- SPY (American-style) vs SPX (European-style, cash-settled). For small accounts: SPY.

---

## STRATEGY A — 0DTE Opening Range Breakout (ORB)

Source: options.cafe backtested results (303 trades, ~2 years, $25K account)

### Performance

| Metric | Value |
|---|---|
| Win rate | 41.3% (125 wins / 303 trades) |
| Payoff ratio | 1.99x (avg win $417.66 / avg loss $209.82) |
| Profit factor | 1.40 |
| Total return | +59.4% ($25K → $39.9K) |
| Max drawdown | 7.6% ($2,611) |
| Avg hold time | 92 minutes |

### Exact Entry Rules

1. Opening range = first 5 minutes only (9:30–9:35 AM ET). Record high and low.
2. First breakout above range high = buy ATM call.
   First breakout below range low = buy ATM put.
   ATM = strike price closest to current SPY price.
3. One trade per day maximum.
4. Trade days: Monday / Wednesday / Friday ONLY. Tuesday and Thursday excluded — underperform.
5. Average breakout occurs 7.4 minutes after open.

### Exact Exit Rules

1. Profit target: option doubles (+100% of entry price).
2. Stop loss: option falls -50% of entry price.
3. Time stop: exit at 3:30 PM ET if neither hit. Only 3% of trades ever reached this stop.

### Position Sizing

- Flat $500 position size per trade = 2% of $25K account.
- Number of contracts varies by option premium.

### Trade Outcome Breakdown

- 120 trades hit profit target → +$51,599
- 174 trades hit stop loss → -$37,184
- 9 trades hit time stop → +$446
- Net: +$14,861 on $25K base

### Bot Implementation Notes

- Setup builder: record 9:30–9:35 high/low on SPY 1-min chart.
- At first candle close above high: submit ATM call market/limit order.
- At first candle close below low: submit ATM put market/limit order.
- Auto-exit at +100% or -50% of fill price.
- Hard time-stop scheduler: exit any open 0DTE position at 3:30 PM ET.
- MWF-only gate at the scheduler level.

---

## STRATEGY B — SPY Put Credit Spread (Theta Income)

Source: options.cafe backtested results (156 trades, 2022–2026)

### Performance

| Year | Win Rate | Net P&L |
|---|---|---|
| 2022 | 100% | $370 (2 trades — 50-day filter kept sidelined most of year) |
| 2023 | 96% | $5,439 (49 trades) |
| 2024 | 92% | $4,299 (36 trades) |
| 2025 | 93% | $3,259 → 42.33% annual return |
| 2026 YTD | 79% | $1,858 (14 trades) |
| **Total** | **91%+** | **$15,226** |

### Exact Entry Rules

1. DTE: Enter 30–45 DTE. Optimal for theta decay acceleration.
2. Delta: Short strike at 0.15–0.20 delta (~5–8% OTM). ~80–85% probability of expiring worthless.
3. Spread width: $5-wide only. Long put $5 below short put.
4. Market condition filter: SPY must be above 50-day MA. Pause in bear markets / when below.
5. Position sizing: 1–2% account risk per trade. $500 buying power per $5-wide spread.

### Strike Example (SPY at $580)

- Sell $540 put (collect $2.50)
- Buy $535 put (pay $1.80)
- Net credit: $0.70 per share ($70 per contract)
- Maximum loss: $4.30 per share ($430 per contract)

### Exact Exit Rules

1. Close winning positions at 50% of maximum credit collected. Do not hold for last $0.10.
2. Evaluate closing or rolling when loss reaches 2x credit received.
3. NEVER hold into final 5 days before expiration (gamma risk explodes). Always close before expiration week.

### Critical Warning

91% win rate sounds invincible. One full-spread loss wipes 6–8 winners.
On a $10K account: realistic monthly income $100–$300 ($1,200–$3,600/year).
SPY drops 5%+ within 30 days only ~11% of the time — statistical basis for why this works.

---

## STRATEGY C — VWAP Pullback Scalp

Best window: 10:00 AM – 2:00 PM ET.

### Entry Rules

Uptrend: SPY pulls back to VWAP → forms reversal candle + volume spike → long calls.
Downtrend: SPY rallies to VWAP → rejection → long puts.

### Exit Rules

- Stop: $0.12–$0.18 SPY below/above VWAP.
- Target: $0.25–$0.45 SPY move toward recent swing high/low.

### Why It Works

VWAP is the institutional execution benchmark. Pullbacks to VWAP = fast money
exhaustion + institutional absorption. One of the highest-probability intraday setups.

---

## STRATEGY D — Weekly Credit Spreads (Short-Term Income)

Consensus pick across multiple sources as "best lifestyle-compatible SPY strategy":

- Sell bull put spreads or bear call spreads 7–14 DTE.
- 15–20 delta short strike → ~80%+ win rate.
- Take profit at 50% max profit.
- Max loss at 2x credit received.
- Realistic income on $25K: $1,200–$3,600/year.

Lower-reward but lower-stress version of Strategy B.

---

## MARKET STRUCTURE: CLASSIFY THE DAY BEFORE ANY TRADE

Misclassifying trend vs range day is the #1 retail loss cause on SPY.

### Trend Day Signals (Check Pre-Open + First 30 Min)

- Overnight futures gap > 0.5% in either direction.
- Major macro catalyst scheduled: CPI, FOMC, NFP, earnings season peak.
- NYSE TICK stays persistently above +400 (bull) or below -400 (bear). Spikes to ±800+.
- Price does NOT return to VWAP after first hour.
- First 15-min candle is large, directional, closes near its extreme.
- ADX > 25 on 5-min chart.

### Range Day Signals

- No significant overnight catalyst.
- Price oscillates around VWAP throughout session.
- NYSE TICK stays between -400 and +400.
- Opening range is narrow (< 0.3% SPY).
- ADX < 20.

### Strategy Matrix

| Day Type | Use | Avoid |
|---|---|---|
| Trend day | Buy breakouts, add on pullbacks | Fading moves, mean reversion |
| Range day | Fade extremes, sell at VWAP | Breakout entries |

Using trend-day entries on a range day (and vice versa) produces most losses.

---

## TECHNICAL INDICATORS FOR SPY BOT

| Indicator | Timeframe | Purpose |
|---|---|---|
| VWAP | Intraday (reset daily) | Dynamic S/R, institutional benchmark |
| 9 EMA | 5-min, 15-min | Short-term trend |
| 21 EMA | 5-min, 15-min | Medium-term trend direction |
| 50-day MA | Daily | Credit spread strategy filter (above = trade) |
| 200-day MA | Daily | Long-term trend gate |
| NYSE TICK | 1-min | Market-wide sentiment, trend confirmation |
| RSI (14) | 15-min, daily | Overbought/oversold |
| ADX | 5-min | Trend strength gate (>25 trending, <20 ranging) |
| Volume | 5-min | Breakout validation (above avg = valid) |

### ORB + VWAP Combo Filter (Required for Quality ORB Setups)

All four conditions required for a long ORB trade:
1. Candle closes above the 5-min opening range high.
2. Price is above VWAP with VWAP sloping upward.
3. 21 EMA sloping up on 5-min.
4. Above-average volume on the breakout candle.

If price is below a falling VWAP and breaks out long — skip. Counter-flow.

---

## 0DTE GREEKS: WHAT DIFFERENTIATES PROFESSIONAL EXECUTION

0DTE gamma is 3–10x higher than weekly options. Delta changes violently with every $1 SPY move.
A 30-delta call at 10 AM can be 80-delta by 2 PM after a $3 SPY move.

### Theta Decay Curve on 0DTE

- Decay is slow until ~noon ET.
- Accelerates after 2:00 PM ET.
- Near-vertical after 3:30 PM ET.

### Implication for Buyers (ORB Strategy)

Enter before 11:00 AM — time premium still provides buffer on moves.
Entering at 2:00 PM as buyer means theta actively decays premium even on a flat SPY.

### Implication for Sellers

0DTE naked credit selling = catastrophic gamma risk on any large move.
Retail cannot hedge at the speed required (millisecond execution by market makers).
Minimum: defined-risk spreads. Do not sell naked 0DTE on SPY.

---

## TIME-OF-DAY EDGE MAP

| Window | Characteristic | Best Setup |
|---|---|---|
| 9:30–9:35 AM | ORB formation | Observe only — do not trade yet |
| 9:35–10:00 AM | Highest volatility, widest spreads | ORB breakout if A-quality |
| 10:00–11:30 AM | Institutional order flow, trend confirmation | Trend continuation, VWAP plays |
| 11:30 AM–2:00 PM | Lunch chop, low volume | Avoid or reduce size significantly |
| 2:00–3:30 PM | Afternoon trend resumes | Continuation trades, credit spread entries |
| 3:30–4:00 PM | Theta collapse, EOD hedging | Time-stop exits only, no new entries |

---

## TOP TRADERS TO FOLLOW AND STUDY

| Trader | Platform | Focus | Key Insight |
|---|---|---|---|
| Adam Mancini | X `@AdamManciniNYC`, Substack | ES/SPX levels, Failed Breakdown | Most respected pure S&P level trader. Publishes daily levels on X for free. Primary setup: Failed Breakdown — price breaks below support, reverses back above, enter long. Level-to-level scaling. |
| Ripster47 | X | SPY/TSLA technicals | Raw daily trade breakdowns. Technical analysis junkie. |
| Peter Brandt | X `@PeterLBrandt` | Classical chart patterns | 40+ years. Transparent P&L. Master of classical patterns on SPY/SPX. |
| Mark Minervini | X, books | SEPA strategy | US Investing Champion. Specific Entry Point Analysis. Momentum with defined risk. |
| Ross Cameron | YouTube (Warrior Trading) | Momentum day trading | $583 → $10M+. Best source for trade psychology and execution discipline. |
| Rayner Teo | YouTube (18M subs) | TA education | Clearest structured technical analysis teaching. |

### Adam Mancini Method (Public Portions)

- Identifies key S/R levels on ES/SPX daily + weekly charts each morning.
- Primary setup: **Failed Breakdown** — price breaks below a support level, reverses back above it, triggering a long. The failed break traps shorts who entered below support, forcing them to cover and accelerating the move.
- Scales in and out of positions as price moves between defined levels.
- Explains every trade decision in real-time on X.
- Full methodology (15-point framework) is paid Substack. Free X posts give levels daily.
- His ES levels translate directly to SPY (divide ES by ~10 approximately, but use SPY chart).

---

## WHAT DOES NOT WORK (SAVE MONTHS OF LOSSES)

- YOLO single-leg 0DTE calls/puts without a defined system = lottery, not trading.
- Buying options after 3:00 PM hoping for a gap = buying pure theta decay.
- Ignoring the 50-day MA filter for credit spreads = 2022 bear market destroyed unprepared accounts.
- Fading trend days = market can trend further than rational expectation.
- Over-trading 11:30 AM–2:00 PM lunch chop = low volume, no edge, bleeds commissions.
- Holding 0DTE past 3:30 PM as a buyer = theta curve goes near-vertical.
- Selling naked 0DTE options = one black swan ends the account.
- Chasing a missed ORB entry 30 minutes after breakout = entry is invalidated.

---

## BOT IMPLEMENTATION PRIORITY ORDER

### Phase 1: Shadow / Paper Only

1. **0DTE ORB shadow lane** — implement Strategy A as a paper-only scanner.
   - MWF gate at scheduler level.
   - 5-min opening range recorder (9:30–9:35).
   - ATM strike selector at first breakout candle close.
   - +100% / -50% / 3:30 PM exit logic.
   - Log: execution_lane=ORB_0DTE_paper, entry_time, breakout_direction, option_premium, exit_reason, pnl_pct.

2. **Day type classifier** — pre-market signal (runs at 9:15 AM ET):
   - Inputs: overnight futures gap %, economic calendar events, prior day's TICK range.
   - Output: trend_day_probability (0–1). Log daily. Gate aggressive strategies.

3. **VWAP tracker** — intraday VWAP calculation on SPY. Log pullback touches and rejections.
   - Needed by both ORB filter and VWAP scalp strategy.

### Phase 2: Promote to Paper Execution (after 30+ shadow signals)

4. **Put credit spread paper lane** — Strategy B.
   - Only opens when SPY > 50-day MA.
   - 30–45 DTE entry window.
   - 0.15–0.20 delta short strike selector.
   - $5-wide spread.
   - 50% profit target closer.
   - 2x loss exit gate.
   - Expiration-week blocker (no new entries or holds inside 5 DTE).

### Phase 3: Evidence Gate

- 50+ ORB paper signals before any live consideration.
- Profit factor > 1.2 on paper lane.
- Max drawdown < 15% on paper lane.
- Human approval required before any live execution.

---

## RISK MANAGEMENT RULES (NON-NEGOTIABLE)

- Never risk more than 2% of account per 0DTE directional trade.
- Never risk more than 5% of account per credit spread.
- Max 3 concurrent SPY positions.
- Daily loss limit: stop trading at -5% account value in one day.
- No revenge trading after daily stop hit.
- Credit spreads: always close at 50% profit. Always exit at 2x loss. Never hold expiration week.
- 0DTE: 2:1 payoff minimum required. Time-stop at 3:30 PM, no exceptions.
- Win rate is secondary. Payoff ratio is primary. A 40% win rate with 2:1 payoff is profitable. A 90% win rate with 0.1:1 is a loss.

---

## Key Sources

- options.cafe 0DTE ORB backtest: exact rules and 303-trade dataset
- options.cafe SPY put credit spread backtest: 156 trades, 2022–2026
- tradealgo.com 0DTE framework
- quantvps.com SPY options scalping guide
- Adam Mancini Substack / X: level-to-level methodology
- marketxls.com 0DTE complete playbook
- daytradingtoolkit.com trend vs range classification
- daystoexpiry.com 0DTE theta decay curve analysis

---

## Hard Stops for Codex

- Do not implement any live order submission for SPY options without 50+ paper signals and human approval.
- Do not lower the 2:1 payoff minimum for ORB strategy.
- Do not remove the 50-day MA filter from the credit spread strategy.
- Do not add 0DTE entries after 3:30 PM ET.
- Do not implement naked 0DTE option selling at any position size.
- Do not trade Tuesday or Thursday on the ORB strategy — backtested underperformance.
- Do not skip the day-type classifier — wrong classification is the primary loss cause.
