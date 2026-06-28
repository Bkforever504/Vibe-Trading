# Pine Strategy Candidates — Translation Queue

Sources: everget indicator library (commit 6019ffe, 196 clean files) + last30days community research (2026-06-28).

Verdict on everget repo: indicator idea library only. Zero strategies, 0 plug-and-play. Use as raw signal logic, then wrap explicit entry/exit/position rules around it and run through OOS/WF/PBO/DD gates.

---

## Priority 5: Candidates to translate first

### 1. MAMA/FAMA Crossover Trend System
**Source:** `movings/ehlers_mesa_adaptive_moving_averages.pine` (everget, GPL-3.0, clean)

**Why it's interesting:** MAMA adapts its smoothing alpha dynamically using the Hilbert Transform cycle measurement. Faster in trending markets (alpha up to 0.5), slower in ranging (alpha down to 0.05). FAMA uses half MAMA's alpha — the crossover marks confirmed cycle direction change. Zero fixed-period lag bias.

**Core logic (from Pine source):**
- Compute instantaneous cycle period via quadrature/in-phase Homodyne Discriminator
- `alpha = fastLimit / deltaPhase`, clamped to [slowLimit, fastLimit]
- `MAMA = alpha * price + (1 - alpha) * MAMA[1]`
- `FAMA = (alpha/2) * MAMA + (1 - alpha/2) * FAMA[1]`

**Explicit strategy rules:**
- Entry: `MAMA crosses above FAMA` on close
- Exit: `MAMA crosses below FAMA` on close
- Universe: same 10-ETF universe as momentum rotation
- Rebalance: daily (signal fires on crossover bar)
- No leverage; equal-weight the single selected ETF or go to cash

**Params to sweep:** fastLimit [0.3, 0.5] × slowLimit [0.04, 0.05, 0.08]

**Expected edge:** trend-following, adaptive lag. Orthogonal to momentum rotation (different signal construction).

---

### 2. KAMA Price-Slope Trend System
**Source:** `movings/kaufman_adaptive_moving_average.pine` (everget, GPL-3.0, clean)

**Why it's interesting:** Efficiency Ratio = directional_move / total_path. When ER is high (trending), KAMA behaves like a fast EMA. When ER is low (choppy), it barely moves. Avoids whipsaw in range-bound regimes.

**Core logic (from Pine source):**
```
er = abs(change(close, length)) / sum(abs(change(close)), length)
alpha = (er * (fast_alpha - slow_alpha) + slow_alpha)^2
KAMA = alpha * close + (1 - alpha) * KAMA[1]
```

**Explicit strategy rules:**
- Entry: `close crosses above KAMA` AND `KAMA > KAMA[5]` (slope positive)
- Exit: `close crosses below KAMA` OR `KAMA < KAMA[5]` (slope turned negative)
- Universe: same 10-ETF universe
- Rebalance: weekly (Monday close)
- Apply absolute momentum filter: skip entry if KAMA momentum_12m < 0

**Params to sweep:** length [10, 14, 20] × fastLength [2, 3] × slowLength [20, 30]

**Expected edge:** trend-following, volatility-adaptive. Lower whipsaw than fixed SMA. Addresses the 2022 regime failure of fixed-SMA strategies.

---

### 3. RSI-2 Mean Reversion (Connors)
**Source:** Community — `handiko/RSI-2-Stock-Trading-Strategy-Pinescript` (GitHub, last30days research)

**Why it's interesting:** Fires in range-bound pullback regimes — exactly when momentum rotation sits in cash. Zero regime overlap with existing strategies. Connors system is one of the most replicated mean-reversion edges in academic lit.

**Explicit strategy rules:**
- Long entry: `RSI(2, close) < threshold` AND `close > EMA(200)`
- Exit: `close > SMA(5)` (profit target) OR `close < EMA(200)` (stop)
- Position: equal-weight across all qualifying ETFs on entry signal
- Rebalance: daily scan

**Params to sweep:** RSI threshold [5, 10, 15] × EMA_trend [150, 200] × exit_sma [3, 5]

**Expected edge:** mean-reversion in uptrending assets; complement to momentum rotation by regime. Run on the same 10-ETF universe.

---

### 4. STARC Bands Breakout/Reversion
**Source:** `bands_and_channels/stoller_average_range_channels.pine` (everget, GPL-3.0, clean)

**Why it's interesting:** SMA ± (multiplier × ATR). Wider than Bollinger (uses ATR not stddev) so fewer false breakouts. Can run as breakout (buy upper touch) or reversion (buy lower band, sell upper band).

**Core logic:**
```
middle = SMA(close, length)
upper = middle + multiplier * ATR(atr_length)
lower = middle - multiplier * ATR(atr_length)
```

**Explicit strategy rules (reversion variant):**
- Entry long: `close < lower band` AND `RSI(14) < 40`
- Exit: `close > middle` (SMA)
- Position size: equal-weight

**Explicit strategy rules (breakout variant):**
- Entry long: `close breaks above upper band` with rising ATR (expanding volatility)
- Exit: `close falls below middle`

**Params to sweep:** length [14, 20] × multiplier [1.5, 2.0, 2.5] × mode [reversion, breakout]

**Expected edge:** volatility-adaptive band; reversion variant is orthogonal to trend strategies.

---

### 5. GeekTrade Volatility-Squeeze Momentum Breakout
**Source:** `grinay/geektrade-strategies` (GitHub, last30days research). Non-repainting, bar-close signals.

**Why it's interesting:** Detects compressed volatility (squeeze), waits for explosive breakout confirmed by volume + momentum direction. Explicit non-repainting guarantee. Already has documented crypto backtest metrics.

**Core logic (from repo description):**
- Volatility squeeze: ATR below N-period ATR average (compression detected)
- Breakout: close breaks highest_high or lowest_low of squeeze period
- Volume confirm: volume > volume_SMA(20)
- Momentum confirm: price direction matches breakout side

**Explicit strategy rules (adapted for ETF universe):**
- Entry long: `ATR(14) < ATR_SMA(50)` for 5+ bars (squeeze), then `close > highest(high, squeeze_period)`
- Volume filter: `volume > SMA(volume, 20) * 1.2`
- Exit: trailing stop at `highest_close - 2 * ATR(14)` OR fixed bars (N=10)
- Position: top-2 equal weight (mirrors momentum rotation sizing)

**Params to sweep:** squeeze_length [5, 10] × ATR mult [1.5, 2.0] × hold_bars [8, 10, 15]

**Expected edge:** breakout momentum, different trigger mechanism from price-return ranking. Captures gap-up/gap-down ETF moves.

---

## Translation order

| Priority | Candidate | Source | Regime | Translate next |
|---:|---|---|---|---|
| 1 | **Seykota Alt10** (Profit Targets) | trustdan/trend-following | Trend | YES — 76% cross-asset success (16/21), pre-validated, commission+slippage set |
| 2 | RSI-2 Mean Reversion | handiko/GitHub | Range-bound | YES — <50 lines, Connors academic edge, fastest port |
| 3 | **Seykota Alt45** (Dual-Momentum) | trustdan/trend-following | Trend | YES — 67% cross-asset (14/21), RSI gated adds |
| 4 | KAMA Price-Slope | everget | Trending | After Alt10/RSI-2 validate |
| 5 | Alorse RSI + EMA | alorse/momentum | Trend | After Alt10/RSI-2 validate |
| 6 | MAMA/FAMA Crossover | everget | Trending | After KAMA validates |
| 7 | Alorse MACD + BB + RSI | alorse/momentum | Momentum | After RSI+EMA validates |
| 8 | Squeeze Momentum | GeekTrade | Breakout | After KAMA/RSI-2 are through gates |
| 9 | STARC Bands Reversion | everget | Range-bound | After RSI-2 validates |

## What the community search added (last30days 2026-06-28)

- **Alorse/pinescript-strategies** (GitHub): 48 strategies pre-categorized into 14 momentum + 10 trend + 8 mean reversion. Scanned: 47 strategies, 2 critical (lookahead_on), 14 clean indicators.
- **TradingView Editors' Picks — Zeiierman ML RSI**: adaptive RSI with historical-analogue voting; potential drop-in replacement for RSI(2) in candidate 2 above.
- **r/TradingView BTC long/short**: community-shared Pine v5 strategy, 2.528 PF over 8-year backtest (unverified). Worth porting and running through scanner to validate claim.
- **Backtested community benchmark**: Editors'-Picks-tier strategies cluster at 1.5-2.5 PF, <20% DD per lunefi.com 2026 guide — maps directly to our gates (PF > 1.1, DD < 25%).

## New repos scanned (2026-06-28 batch 2)

### trustdan/trend-following-backtesting-strategies — GOLDMINE
**Local:** `research/pine_sources/trustdan-trend-following`
**Scan:** `research/pine_sources/trustdan_scan_report.md`
431 Pine v6 files. All Seykota-inspired Donchian breakout variants tested on SPY + 21 securities.
- **analysis.csv**: 294 real backtests with PF, Win Rate, Max DD, per security
- **Top cross-asset performers** (from analysis.csv, NOT just SPY):
  - Alt10 (Profit Targets): 16/21 profitable = 76% success
  - Alt45 (Dual-Momentum): 14/21 = 67% success
  - Alt46 (Sector-Adaptive): 13/21 = 62% success
  - Alt43 (Volatility-Adaptive): 13/21 = 62% success
- **Top SPY-only** (PF in filename): Alt31=1.474, Alt38=1.466, Alt34=1.396
- **Healthcare sector** best: 12/13 strategies profitable
- **Utilities sector** worst: 0/14 strategies profitable
- Scanner flags: `request_security` (optional market regime, default OFF) + `pine_v6` — neither is repaint
- Commission=0.005%, slippage=2 already set in all files. MPL-2.0 license.
- **Verdict: translate Alt10 and Alt45 next. Skip Alt31 (SPY-specific optimized).**

### LouisLetcher/quant-pine
**Local:** `research/pine_sources/louisletcher-quant-pine`
**Scan:** `research/pine_sources/louisletcher_scan_report.md`
4 files. 3 Pine v6 stock strategies (Bullish Engulfing, Inside Day, Stan Weinstein Stage 2).
Clean indicator: Connors RSI (indicator only, not a strategy).
Stan Weinstein is interesting for ETFs but pine_v6 + request_security + missing costs.
**Verdict: low priority. Skip for now.**

### krosenfeld7/pine_script_strategies
**Local:** `research/pine_sources/krosenfeld7-strategies`
**Scan:** `research/pine_sources/krosenfeld7_scan_report.md`
All `.txt` files (Pine v4) — scanner found 0 `.pine` files. Author labels RSI+MACD+BB as "Not Good."
Strategies present: 200EMA+Supertrend+Stochastic, MTF EMA+MACD, Triple EMA+Stochastic RSI, etc.
**Verdict: low priority. Author's own notes suggest poor results. Skip.**

## What NOT to translate

- Everget highlighters (calendar/time only — no price signal)
- Everget trailing_stops/* (all flagged pine_v6 — Chandelier Exit, SuperTrend, Parabolic SAR, HalfTrend, NRTR)
- `us_treasury_yields.pine` (flagged lookahead_on — CRITICAL repaint risk)
- LuxAlgo (premium, not open source)
- Basic EMA crossover (already swept and rejected in SMA rotation research)
- trustdan Alt31/Alt38/Alt34 as first ports — SPY-optimized, high overfit risk for multi-asset use
- krosenfeld7 strategies (author-labeled as not good, v4 txt files)
