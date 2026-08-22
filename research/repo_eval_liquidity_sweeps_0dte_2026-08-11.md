# Research Evaluation: Liquidity Sweeps as Entry Filter for 0DTE SPY/QQQ Options
**Date:** 2026-08-11
**Analyst:** Claude Code (Sonnet 4.6)
**Type:** research_intake
**Execution Enabled:** false
**Follow-up from:** repo_eval_ict_smc_vwap_pivots_2026-08-11.md (Priority 9 — "worth isolating as standalone")

---

## VERDICT: TIMING TOOL (with conditional evidence of edge — not yet sufficient for live integration)

The phenomenon is real and measurable. The edge is directionally supported but not robustly quantified for SPY options specifically. Shadow-paper observation over 30 days is the correct next step before any filter integration.

---

## 1. PRECISE MECHANICAL DEFINITION

### What a Liquidity Sweep Is (Defensible Definition)

A liquidity sweep occurs when:
1. Price trades above a known structural high OR below a known structural low ("the sweep")
2. The sweep level holds for no more than N bars (typically 1-5 bars on 1m or 5m chart)
3. Price then closes back below (or above) the swept level within the same time window
4. The close constitutes the "confirmation candle" that signals the sweep failed

**Structural levels (ranked by institutional relevance):**
- Prior-day high (PDH) / prior-day low (PDL) — highest relevance, most widely watched
- Overnight session high / overnight session low (4:00 AM–9:30 AM ET)
- Opening range high / opening range low (first 5, 15, or 30 minutes of regular session)
- Prior session's VWAP as a reference (softer level)
- Weekly high/low (less relevant for 0DTE)

**The trap mechanic (why it creates an edge):**
- Retail breakout buyers enter on the breach of PDH/PDL
- Retail stop-loss orders from shorts cluster just above PDH (buy stops) and just below PDL (sell stops)
- Both are triggered by the sweep
- After that liquidity is consumed, price reverts — the trapped longs become forced sellers, accelerating the reversal
- This is the same mechanism as an "engineered liquidity run" in market microstructure literature

### Most Defensible Mechanical Form

```
BULLISH SWEEP SETUP (downward sweep of PDL, then reversal upward):
- Price_low_of_sweep_candle < PDL                (sweep occurred)
- Sweep_candle_close > PDL                        (close reclaimed above PDL)
- Sweep occurred within 9:35-10:30 ET window     (time filter)
- Reversal confirmation: next bar close > sweep_candle_close  (momentum confirmation)
- Volume on sweep candle >= 1.2x 20-bar avg volume  (participation confirmation)

BEARISH SWEEP SETUP (upward sweep of PDH, then reversal downward):
- Price_high_of_sweep_candle > PDH
- Sweep_candle_close < PDH
- Same time filter and volume filter apply
```

---

## 2. ACADEMIC AND QUANTITATIVE RESEARCH AUDIT

### Directly Relevant Papers

**Vlasiuk & Smirnov (2025) — "Push-Response Anomalies in High-Frequency S&P 500 Price Series"**
- arXiv: 2511.06177 / SSRN: 5724104
- Dataset: NBBO quote data for SPY, ~1,500 regular trading days (Jan 2018–Dec 2023)
- Finding: At short lags (1–5,000 ticks), expected responses cluster near zero (efficient). Beyond that range, **pronounced tails emerge**: larger historical "pushes" (directional moves) increasingly correlate with nonzero conditional responses, defying random walk
- Implication: Large, sharp intraday price pushes (i.e., a sweep move beyond a key level) are followed by non-random responses — consistent with the liquidity sweep reversal hypothesis
- Limitation: This is microstructure-level evidence (tick data) and does not isolate PDH/PDL sweeps specifically

**Zarattini, Aziz & Barbon (2024) — "Beat the Market: An Effective Intraday Momentum Strategy for S&P500 ETF (SPY)"**
- SSRN: 4824172 / Swiss Finance Institute Working Paper 24-97
- Dataset: SPY, 2007–early 2024
- Finding: Intraday momentum based on "abnormal demand/supply imbalance" with dynamic trailing stops produced:
  - Annualized return: **19.6%** net of costs
  - Sharpe ratio: **1.33**
  - Total return 2007–2024: **+1,985%**
- Relevance: The "abnormal imbalance" signal is conceptually similar to a failed breakout reversal — price pushes hard in one direction, then reverses on imbalance. Not a direct liquidity sweep backtest but the closest academically rigorous SPY study
- Limitation: Trend-following framing, not mean-reverting. The mechanism differs from a sweep-reversal entry

**No paper found that directly and rigorously backtests "prior-day-high sweep + reversal" on SPY with reported win rate, Sharpe, and holding period.**

This is the central gap. The phenomenon is theoretically supported and microstructure-consistent, but no peer-reviewed study isolates it with clean entry/exit rules on SPY.

### Adjacent Literature That Supports the Mechanism

- Stop clustering at round numbers and prior swing highs: well-documented in FX microstructure (Osler, 2003; Osler & Savaser, 2011). Directly analogous to stop clustering at PDH/PDL
- Liquidity imbalance and short-term reversals: Glosten & Milgrom (1985) market maker adverse selection framework; large directional moves that exhaust liquidity are followed by reversion as market makers widen and liquidity providers return
- NBBO-level evidence (Vlasiuk & Smirnov above): empirically observed in SPY at the tick level

### What the Research Says About False Breakouts Generally

From practitioner-quantified studies (not peer-reviewed, but mechanically defined):

| Source | Instrument | Setup | Win Rate | Notes |
|---|---|---|---|---|
| QuantVPS SFP analysis | SPY/crypto | Swing Failure Pattern + volume confirm | ~68% | 2,847 trades, 2022-2025, multi-asset |
| TradeThatSwing statistics | SPY | Opens inside prior range → tags PDH or PDL | **86%** | Directional stat, not a trade |
| TradeThatSwing statistics | SPY | Opens below PDL → returns to PDL | **71%** | Mean-reversion tendency |
| ES/NQ 5m chart (QuantVPS) | ES, NQ | Low-volume break reverting within 5 bars | 55-65% | w/ 1:1 to 1.5:1 RR |
| ORB failure (TOS Indicators backtest) | SPY | Opening range breakout — SPY-specific | ~50% | Near coin-flip, no edge on broad ETF |
| Quantish.io 0DTE SPX ORB (Sept 2025) | SPX | 60-min ORB credit spread, direction-following | **88.8% win rate** | Selling credit spreads in direction of breakout — OPPOSITE of sweep-reversal |

**Critical distinction:** The Quantish ORB result (88.8%) is for selling credit spreads IN THE DIRECTION of the breakout (momentum), not fading it. This confirms that confirmed ORBs have momentum, which means unconfirmed/failed breakouts (sweeps) are the outlier worth fading — but also means getting the "failed vs. confirmed" classification right is everything.

---

## 3. PRACTITIONER BACKTEST SUMMARY

### Key Empirical Statistics (SPY-Specific)

| Statistic | Value | Source | Confidence |
|---|---|---|---|
| SPY opens inside prior range, then tags PDH or PDL | 86% of days | TradeThatSwing.com | Medium (practitioner, large sample implied) |
| SPY opens below PDL, eventually returns above PDL | 71% | TradeThatSwing.com | Medium |
| ORB failure (SPY, 1:1 RR) win rate | ~50% | TOS Indicators 30-day backtest | Low (30-day only) |
| Swing Failure Pattern + volume confirm win rate | 55-68% | Multiple practitioner sources | Medium |
| False breakout low-vol reversal (ES/NQ 5m) | 55-65% | QuantVPS analysis | Medium |

### The 86% Statistic Deserves Scrutiny

"86% of the time, SPY tags PDH or PDL when it opens inside the prior range" — this is a directional tendency, NOT a trade edge. It tells you price will visit PDH or PDL, but not:
- Whether price will reverse at that level
- In what order (does it tag PDH first or PDL first?)
- How far past the level it goes before reversing
- What the RR is if you fade the tag

This is a **necessary condition for the setup occurring**, not evidence that fading the touch is profitable.

### Opening Range Breakout Failure on SPY

The ORB failure specifically on SPY (broad ETF) has been backtested to ~50% win rate — essentially random at 1:1 risk/reward. This is the **weakest** version of the sweep setup. The key variables that separate edge from noise:

1. **Volume at the sweep:** Low-volume sweeps revert at materially higher rates than high-volume sweeps
2. **Level quality:** PDH/PDL from prior regular session > overnight extremes > ORB high/low
3. **Time of day:** 9:35-10:30 ET sweeps have more trapped-trader fuel than midday sweeps
4. **Return speed:** A sweep that reclaims the level within 1-2 bars is stronger than one that grinds around the level for 10+ bars

---

## 4. 0DTE OPTIONS INTEGRATION ANALYSIS

### Scenario: Bullish Sweep Setup → Selling 0DTE Put Credit Spread

**Setup:** SPY sweeps below PDL at 9:45 AM, closes back above PDL within 2 bars, volume confirmed. Bullish reversal expected toward VWAP.

**Favorable asymmetry argument:**
- IV spikes briefly during the sweep (panic puts get bought)
- At the moment of reversal confirmation, you sell a put credit spread with the short leg at PDL or slightly below
- You're selling elevated IV into a reversal move — theta + delta both working in your favor
- VWAP is the natural target; if SPY is only 0.3-0.5% below VWAP, the spread likely expires worthless by close

**Ideal entry timing:** The bar AFTER sweep confirmation closes back above PDL. Not during the sweep (catching a falling knife). Not 30 minutes after (premium has compressed).

**The catastrophic loss scenario:**
This is the most important risk factor for options:

If the sweep is NOT a fake and SPY continues below PDL (actual breakdown), you are:
1. Long delta on a falling asset
2. Short gamma with 0DTE — the short put strike gets hit immediately
3. IV is expanding (hurts your short vega)
4. All three Greeks are moving against you simultaneously

A 0.5% move against the position on a 0DTE $5-wide spread can turn a $0.50 credit into a $4.50 debit — a 9:1 adverse outcome if wrong. **This is not a standard loss. This is a max-loss scenario.**

### Risk/Reward Math for 0DTE Put Credit Spread on Bullish Sweep

Assumptions:
- SPY at $550
- PDL at $548 (SPY swept to $547.80, closed back above $548)
- Sell $548/$543 put credit spread for $0.60 credit (at 9:47 AM, 0DTE)
- Max loss: $4.40 per spread (spread width - credit)
- Breakeven: $547.40

| Scenario | Probability (estimated) | P&L |
|---|---|---|
| SPY reverses, stays above $548 by close | 55-65% (based on SFP data) | +$0.60 (full credit) |
| SPY wavers, expires between $547.40 and $548 | 10-15% | -$0.00 to -$0.60 |
| SPY continues lower, breaks $543 | 25-35% | -$4.40 (max loss) |

**Expected value at 60% win, 30% max loss, 10% partial:**
EV = (0.60 × $0.60) + (0.10 × -$0.30) + (0.30 × -$4.40)
EV = $0.36 - $0.03 - $1.32 = **-$0.99**

This is negative expected value at 60% win rate because the payoff is asymmetric (1:7.3 reward-to-risk ratio). You need a win rate of approximately **88%** to break even at this payoff structure. The ORB credit spread study hitting 88.8% used confirmed breakouts (momentum), not reversal setups.

**Conclusion on options integration:** A raw liquidity sweep reversal signal is NOT sufficient to justify selling 0DTE credit spreads in isolation. The math doesn't work unless the win rate is near 85%+ — which requires heavy filtering (volume confirmation, level quality, time of day, VIX regime).

### Better Options Approach: Debit Spread or Directional

If the win rate on the reversal signal is 60-65%, a debit spread (long put spread for the bearish sweep, long call spread for the bullish sweep) has better EV:

- Buy $549/$552 call debit spread for $1.00 on a bullish sweep
- Max loss: $1.00 (controlled)
- Max gain: $2.00
- Breakeven: $550

EV = (0.60 × $2.00) + (0.40 × -$1.00) = $1.20 - $0.40 = **+$0.80**

This is positive EV and consistent with the risk profile. However, this requires directional confidence, not premium selling — a fundamentally different strategy from the existing 0DTE PM spread.

---

## 5. FALSIFIABLE SCANNER DEFINITION (Python-Ready)

### Data Requirements

All free via yfinance:
- `yfinance.download(ticker, period='5d', interval='1d')` → prior day OHLC for PDH/PDL
- `yfinance.download(ticker, period='1d', interval='1m')` → intraday 1-min bars for sweep detection
- Volume is included in yfinance 1-min data

### Scanner Logic

```python
import yfinance as yf
import pandas as pd
from datetime import datetime, time
import pytz

def detect_liquidity_sweep(ticker='SPY', sweep_window_start='09:35', sweep_window_end='10:30'):
    """
    Detects a liquidity sweep of prior day high or low with reversal confirmation.
    Returns: dict with sweep_type, sweep_candle_time, confirmation_candle_time,
             pdh, pdl, sweep_low/high, volume_ratio
    """
    et = pytz.timezone('America/New_York')
    
    # Get prior day OHLC
    daily = yf.download(ticker, period='5d', interval='1d', progress=False)
    pdh = float(daily['High'].iloc[-2])
    pdl = float(daily['Low'].iloc[-2])
    
    # Get today's 1-min data
    intraday = yf.download(ticker, period='1d', interval='1m', progress=False)
    intraday.index = intraday.index.tz_convert(et)
    
    # Filter to sweep window
    start_t = time(int(sweep_window_start.split(':')[0]), int(sweep_window_start.split(':')[1]))
    end_t = time(int(sweep_window_end.split(':')[0]), int(sweep_window_end.split(':')[1]))
    window = intraday.between_time(sweep_window_start, sweep_window_end)
    
    # Volume baseline: 20-bar average from first 20 bars of session
    vol_baseline = intraday.head(20)['Volume'].mean()
    
    results = []
    
    for i in range(1, len(window) - 1):
        bar = window.iloc[i]
        prev_bar = window.iloc[i - 1]
        next_bar = window.iloc[i + 1]
        
        bar_time = window.index[i]
        vol_ratio = bar['Volume'] / vol_baseline if vol_baseline > 0 else 0
        
        # BEARISH SWEEP: bar sweeps above PDH but closes back below it
        if bar['High'] > pdh and bar['Close'] < pdh:
            # Volume confirmation
            if vol_ratio >= 1.2:
                # Reversal confirmation: next bar closes lower
                if next_bar['Close'] < bar['Close']:
                    results.append({
                        'sweep_type': 'BEARISH',
                        'sweep_candle_time': bar_time,
                        'pdh': pdh,
                        'sweep_high': bar['High'],
                        'sweep_excess_pct': (bar['High'] - pdh) / pdh * 100,
                        'vol_ratio': round(vol_ratio, 2),
                        'signal': 'SHORT_SETUP'
                    })
        
        # BULLISH SWEEP: bar sweeps below PDL but closes back above it
        if bar['Low'] < pdl and bar['Close'] > pdl:
            if vol_ratio >= 1.2:
                if next_bar['Close'] > bar['Close']:
                    results.append({
                        'sweep_type': 'BULLISH',
                        'sweep_candle_time': bar_time,
                        'pdl': pdl,
                        'sweep_low': bar['Low'],
                        'sweep_excess_pct': (pdl - bar['Low']) / pdl * 100,
                        'vol_ratio': round(vol_ratio, 2),
                        'signal': 'LONG_SETUP'
                    })
    
    return results if results else None


def log_sweep_observation(result, vwap, spy_close_eod):
    """
    For shadow period logging: did the reversal actually reach VWAP?
    Call this at EOD with the day's VWAP and closing price.
    """
    if result is None:
        return
    for sweep in result:
        direction = 1 if sweep['sweep_type'] == 'BULLISH' else -1
        vwap_reached = (direction == 1 and spy_close_eod >= vwap) or \
                       (direction == -1 and spy_close_eod <= vwap)
        sweep['vwap_reached'] = vwap_reached
        sweep['spy_close_eod'] = spy_close_eod
        sweep['vwap'] = vwap
    return result
```

### Parameters to Optimize During Shadow Period

| Parameter | Baseline | Range to Test | Rationale |
|---|---|---|---|
| Sweep window (start) | 09:35 | 09:35 to 09:45 | First bar is often noise |
| Sweep window (end) | 10:30 | 10:00 to 11:00 | After 11:00, level relevance decays |
| Volume ratio threshold | 1.2x | 1.0x to 2.0x | Higher = stricter, fewer but better setups |
| Sweep excess (min) | 0.05% | 0.03% to 0.15% | Wicks too small = noise |
| Sweep excess (max) | 0.30% | 0.20% to 0.50% | Too large = real breakdown, not sweep |
| Reversal confirmation bars | 1 | 1 to 3 | More bars = more confirmation, later entry |
| VWAP distance at entry | any | within 0.5% of VWAP | Avoid sweeps far from VWAP anchor |

---

## 6. RISK FACTORS SPECIFIC TO OPTIONS

### Why Liquidity Sweeps Are More Dangerous for Options Than Equities

**1. Gamma amplification on 0DTE:**
The same 0.3% move that looks manageable in the underlying can wipe a 0DTE credit spread. Gamma on a 0DTE ATM option is 10-25× higher than a 30-DTE option. A failed reversal (actual breakdown) will cause P&L to crater faster than you can exit.

**2. Bid-ask slippage during sweep:**
At the moment of the sweep, bid-ask spreads on 0DTE options widen significantly (market makers reprice for the directional move). Entering a credit spread during peak sweep volatility means giving up 1-2% of the spread width just in slippage.

**3. IV expansion during sweep eats short vega:**
If you sell premium DURING the sweep (before confirmation), IV expansion works against you. Waiting for confirmation candle close mitigates this but means missing 30-60 seconds of premium at peak IV.

**4. Sweep failure masquerading as confirmation:**
The most dangerous scenario: price sweeps PDL, closes back above it (triggering your long signal), then sweeps again lower in the next bar. This "double tap" pattern is not rare in high-vol regimes and causes immediate max loss on a freshly entered 0DTE position.

**5. VIX regime dependency:**
In VIX > 25 environments, PDH/PDL sweeps are more likely to be genuine breakouts than false breakouts. The reversal probability estimated from normal-vol backtests likely does not hold in high-vol regimes. The existing bot already has a VIX 15-40 gate — the upper bound may need tightening for sweep-based entries (e.g., VIX < 25 for sweep fades).

---

## 7. INTEGRATION RECOMMENDATION

### What NOT to Do Immediately

- Do NOT add liquidity sweeps as a standalone entry signal for 0DTE credit spreads
- Do NOT wire sweep detection to any order-capable script
- The math at 60-65% win rate does NOT support credit spread entry (need ~88% WR)

### Shadow Scanner Plan (30-Day Observation)

Build a read-only logger that:
1. Runs daily after market close (or during session, shadow-only)
2. Scans for sweeps meeting the mechanical definition above
3. Logs: sweep_type, time, level, volume_ratio, sweep_excess_pct
4. At EOD, logs whether price reached VWAP within 2 hours of the sweep
5. After 30 days: calculate observed win rate, time-to-VWAP, false breakdown rate

**Decision gate after 30 days:**
- If observed win rate > 70% AND false breakdown rate < 20%: consider as 0DTE debit spread entry (NOT credit spread)
- If observed win rate < 65% or inconsistent: close the inquiry, reject for automation

### Where It Fits in Current Stack (If Evidence Materializes)

| Integration Point | How | Condition |
|---|---|---|
| 0DTE PM credit spread pre-filter | Require NO bearish sweep in prior 2 hours before selling puts | Negative filter only |
| 0DTE debit spread (new) | Enter long call/put debit spread on confirmed sweep reversal | Needs 70%+ shadow WR |
| Iron condor timing | Skip condor entry if sweep occurred within 60 min (elevated vol) | Negative filter |
| Theta harvester | Use sweep occurrence as "do not enter" signal for current session | Negative filter |

**The immediate and low-risk use case: use liquidity sweep detection as a NEGATIVE entry filter (veto gate) for existing strategies, not as a standalone entry signal.** If a bearish sweep of PDH has occurred within 2 hours, the market is not behaving as a normal mean-reverting session — skip the condor entry.

---

## EVALUATION SCORECARD

| Criterion | Score | Notes |
|---|---|---|
| Edge clarity | 2/5 | Directionally supported, not rigorously quantified for SPY options |
| Implementation complexity | 3/5 | Medium — scanner is buildable, but parameter optimization requires 30+ days of shadow data |
| Data availability | 5/5 | 100% free: yfinance 1-min + daily bars |
| Fit with current stack | 3/5 | Natural fit as a negative filter; requires new strategy type (debit spread) for positive use |
| **Overall** | **2.5/5** | **intake_shadow — 30-day observation before any code integration** |

---

## SIGNAL REGISTRY ENTRIES

Signal ID: `liquidity_sweep_scanner`
Status: `intake_shadow` (upgraded from `deferred` in prior eval)
Execution enabled: false

---

## SOURCES

- Vlasiuk & Smirnov (2025): https://arxiv.org/html/2511.06177
- Zarattini, Aziz & Barbon (2024): https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4824172
- Swiss Finance Institute Working Paper: https://www.sfi.ch/en/publications/n-24-97-beat-the-market-an-effective-intraday-momentum-strategy-for-s-p500-etf-spy
- Quantish.io 0DTE ORB backtest: https://blog.quantish.io/2025/09/09/0dte-spx-opening-range-breakouts/
- TradeThatSwing high-probability statistics: https://tradethatswing.com/high-probability-stock-market-statistics/
- QuantVPS Swing Failure Pattern: https://www.quantvps.com/blog/swing-failure-pattern-strategy
- TOS Indicators ORB backtest: https://tosindicators.com/research/opening-range-breakout-strategy-backtest-spy-vs-aapl
- LiquidityScan ICT definition: https://liquidityscan.io/blog/liquidity-sweep-explained-the-ict-stop-hunt
- QuantMacro paper review: https://quantmacro.substack.com/p/paper-review-an-effective-intraday
