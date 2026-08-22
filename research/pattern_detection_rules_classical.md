# Pattern Detection Rules — Classical, Candlestick, Volume, Session

**Companion to:** `CODEx_CLAUDE_COLLAB/CLAUDE_HANDOFF_PATTERN_GRADER_2026-08-22.md`
**Purpose:** Machine-implementable geometric detection rules for every non-SMC/Wyckoff pattern the grader recognizes.
**Notation:** `H[i]`, `L[i]`, `C[i]`, `O[i]`, `V[i]` = high/low/close/open/volume at bar i (i=0 current). `ATR14 = ATR(14)`. `RVOL = V[i] / mean(V[i-20..i-1])`.

---

## 0. Family Ranking — Implementation Priority

Score = base-rate edge × frequency × ease of detection.

| Rank | Family | Base rate | Frequency | Detection | Score | Build first? |
|---|---|---|---|---|---|---|
| 1 | ORB 0DTE (5/15/30m) | 46.8% raw → 65.4% filtered (Chuk 2025) | Daily | Trivial | 9.6 | Yes |
| 2 | Anchored VWAP + bands | High regime-agnostic | 3-5×/day | Easy | 9.3 | Yes |
| 3 | Bull/Bear flag | 68-71% (Bulkowski) | Daily | Medium | 8.7 | Yes |
| 4 | Volume Profile POC/VAH/VAL rejection | High institutional | Daily | Medium | 8.5 | Yes |
| 5 | Inverse H&S | 89% success / 11% failure (Bulkowski) | 2-4×/mo/name | Medium-hard | 7.9 | Yes |
| 6 | Ascending triangle (bull mkt) | 63-70% | Weekly | Medium | 7.6 | Yes |
| 7 | Double bottom | 64% success / 4% break-even fail | Monthly | Easy | 7.3 | Yes |
| 8 | H&S top | 61% bear / 39% fail bull | Monthly | Medium | 6.5 | Later |
| 9 | Engulfing (context-gated) | 55-60% w/ trend+RVOL | Very frequent | Trivial | 6.4 | Yes |
| 10 | Cup & handle | 68% success, 27-day formation | Rare | Hard | 5.8 | Later |
| 11 | Wedges | 62-68%, high false-break | Weekly | Hard | 5.5 | Later |
| 12 | Rounded bottom | 79% but ~5/yr per name | Very rare | Hard | 4.9 | Deprioritize |

Sources: Bulkowski *Encyclopedia of Chart Patterns* 3rd ed.; Lo/Mamaysky/Wang 2000 *J. Finance*; Kirkpatrick & Dahlquist *Technical Analysis* 3rd ed.; Chuk 2025 SSRN 6355218.

---

## A. Classical Chart Patterns

### A1. Head & Shoulders Top (bearish)
- **Detect:** Three swing highs `H_L, H_H, H_R` where `H_H > H_L` AND `H_H > H_R` AND `|H_L - H_R| / H_H < 0.03`. Neckline = line through the two intervening swing lows `N_L, N_R`. Time symmetry: `|dist(H_L,H_H) - dist(H_H,H_R)| / avg < 0.30`.
- **Volume rule:** `V(H_L) > V(H_H) > V(H_R)` (declining through peaks — required). RVOL on neckline break ≥ 1.5.
- **Trigger:** `C < neckline(t) - 0.1*ATR14` on close.
- **Stop:** Above right shoulder + 0.25*ATR.
- **Target:** `neckline - (H_H - neckline)` (1:1 measured move). Partials at 0.5×.
- **Invalidation:** Close back above neckline within 3 bars.
- **Base rate:** 39% failure bull, 19% failure bear (Bulkowski). Avg decline 22%.
- **Regime:** Bear/distribution tops, high-vol. [2026: unreliable in strong uptrends — require SPY < 50D MA gate.]
- **Anti-pattern:** No volume divergence, right shoulder > head, or neckline break w/ RVOL < 1 → 61% failure.

### A2. Inverse Head & Shoulders (bullish)
- Mirror of A1 with swing lows. Volume rises through R shoulder + breakout.
- **Base rate:** 89% success, 11% failure — lowest failure of any bullish classical pattern (Bulkowski). Avg gain 38%.
- **Regime:** All regimes; especially base-building post-downtrend.
- **Anti-pattern:** Flat volume on breakout or breakout candle < 1 ATR range → treat as 40% base rate.

### A3. Double Top / Double Bottom
- **Detect DT:** Two highs `H1, H2` within 3% of each other, separated by 15-70 bars, intervening trough `T` with `(H1 - T)/H1 > 0.10`. Confirm on close below `T`.
- **Volume:** `V(H2) < V(H1)`; RVOL ≥ 1.3 on break of `T`.
- **Trigger:** Close < `T - 0.1*ATR`.
- **Stop:** Above H2 + 0.25*ATR.
- **Target:** `T - (H1 - T)`.
- **Base rates:** DT 65% success in bear, 34% failure in bull. DB 64% success, 4% break-even failure (Bulkowski).
- **Anti-pattern:** `V(H2) > V(H1)` = failed distribution → skip.

### A4. Triple Top / Bottom
- Same as A3 with 3 tests. Break-even failure rate drops to 10% (TB) — one of Bulkowski's most reliable.

### A5. Ascending / Descending / Symmetrical Triangles
- **Detect Asc:** Flat upper resistance (linreg slope on last N highs, `|m| < 0.05 * ATR / bar`) + rising lower support (positive slope, R² > 0.7). ≥ 5 touches (3 upper + 2 lower min). Apex within 20-100 bars.
- **Volume:** Contract through formation (`V_late / V_early < 0.7`); expand on breakout (RVOL ≥ 2.0). Volume dry-up mandatory — without it treat as range.
- **Trigger:** Close outside pattern by ≥ 0.15*ATR, within 75% of apex distance.
- **Stop:** Opposite side of triangle.
- **Target:** Height of pattern (widest point) projected from breakout.
- **Base rates:** Asc 63% up-break (bull), Desc 64% down-break, Sym 54% (direction not predictive).
- **Anti-pattern:** Breakout in last 25% of apex, or RVOL < 1.5 → 60%+ failure. Sym triangle w/ rising ATR is trend-continuation, not compression.

### A6. Rising / Falling Wedge
- **Detect Rising** (bearish): Both trend lines slope UP, upper slope < lower slope (converging), ≥ 5 touches, min 15 bars.
- **Volume:** Declining through wedge; breakout down on RVOL ≥ 1.5.
- **Trigger/Stop/Target:** Break of lower line; stop above last swing high; target = wedge height.
- **Base rate:** Rising wedge 68% bearish break, Falling 68% bullish (Bulkowski) — high whipsaw rate.
- **Anti-pattern:** ATR expanding inside wedge = trend, not exhaustion.

### A7. Bull Flag / Bear Flag
- **Detect Bull Flag:** Impulse = ≥ 3 consecutive bars, net move ≥ 3*ATR14, RVOL ≥ 2. Consolidation = 5-20 bars, pullback ≤ 38.2% Fib of impulse, channel slope slightly down (linreg m ∈ [-0.3, 0]*ATR), volume drops (`V_flag / V_pole < 0.6`).
- **Trigger:** Close above upper channel + 0.1*ATR; RVOL ≥ 1.5.
- **Stop:** Below flag low (or below 50% Fib of pole).
- **Target:** `breakout + length(pole)` (measured move).
- **Base rate:** 68% continuation, 4% break-even failure (Bulkowski; high-and-tight variant 39% avg gain).
- **Regime:** Trending; **best pattern in momentum tape**. [2026: works in current bull-tape SPX.]
- **Anti-pattern:** Pullback > 50% Fib, ATR rising in flag, or flag > 20 bars → 45%+ failure.

### A8. Pennant
- Like flag but symmetrical-triangle consolidation. Detection: require converging lines. Base rate ~55%, weaker than flag.

### A9. Cup & Handle
- **Detect:** U-shaped base, depth 12-33% off high, duration 7-65 weeks (daily). Handle = 1-4 week pullback ≤ 12% off cup rim.
- **Volume:** Contract in cup base; dry-up in handle; expand on rim breakout (RVOL ≥ 1.5).
- **Trigger:** Close above rim.
- **Target:** `rim + depth(cup)`.
- **Base rate:** 68% success, avg gain 34% (Bulkowski/O'Neil).
- **Anti-pattern:** V-shaped (no base), handle > 12% deep, or handle exceeds cup rim.

### A10. Rounded Bottom / Saucer
- **Detect:** Poly-2 fit on 40-100 bar lows, R² > 0.75, quadratic coeff > 0.
- **Base rate:** 79% success (Bulkowski), ~5/yr per name.

### A11. Rectangle / Range
- **Detect:** ≥ 4 touches each of parallel support/resistance, range ≥ 3*ATR, duration ≥ 10 bars.
- **Trigger:** Close outside + RVOL ≥ 2.
- **Target:** Range height projected.
- **Base rate:** 68% breakout continuation; false breakouts ~30%.
- **Anti-pattern:** RVOL < 1.5 on break, or immediate re-entry (3-bar rule).

---

## B. Candlestick Patterns (Context-Gated)

**Universal gate:** Every candlestick requires (i) explicit prior trend (5+ bars, ADX > 20 OR `|linreg slope| > 0.5*ATR`), (ii) confirmation candle in reversal direction, (iii) RVOL ≥ 1.2 on signal bar. Naked candlesticks are noise (Lo/Mamaysky/Wang 2000: no edge without conditioning).

Notation: `body = |C-O|`, `range = H-L`, `upper_shadow = H - max(O,C)`, `lower_shadow = min(O,C) - L`.

### B1. Bullish Engulfing (in downtrend)
- **Detect:** `C[1] < O[1]` AND `O[0] ≤ C[1]` AND `C[0] > O[1]` AND `body[0] > body[1] * 1.1`.
- **Confirm:** Next bar close > C[0]. Trigger on confirmation close.
- **Stop:** Below `L[0] - 0.25*ATR`. Target: 2R or nearest resistance.
- **Base rate:** 63% reversal (Bulkowski engulfing bottom); ~52% naked.

### B2. Bearish Engulfing — mirror B1.

### B3. Hammer (in downtrend)
- **Detect:** `lower_shadow ≥ 2*body` AND `upper_shadow ≤ 0.1*range` AND close in top 1/3.
- **Confirm:** Next close > `C[hammer]`.
- **Base rate:** 60% (Bulkowski).
- **Anti-pattern:** Same shape after uptrend = **Hanging Man** (bearish, 59%).

### B4. Shooting Star (in uptrend) — mirror hammer.

### B5. Inverted Hammer (after downtrend) — reversal. Anti = shooting star.

### B6. Morning Star (3-bar reversal, in downtrend)
- **Detect:** Bar[-2] large bearish body, Bar[-1] small body (star) gapping down, Bar[0] large bullish body closing ≥ midpoint of Bar[-2].
- **Base rate:** 78% reversal — one of strongest candle patterns (Bulkowski).

### B7. Evening Star — mirror. 72% reversal.

### B8. Three White Soldiers / Three Black Crows
- Three consecutive same-color candles, each opens within prior body, closes near high (low). ~78% continuation, rare.

### B9. Piercing Line / Dark Cloud Cover
- **Piercing:** Bar[-1] bear; bar[0] opens below `L[-1]`, closes > 50% into body[-1]. ~64%.
- **Dark Cloud:** mirror. Weaker than engulfing; require volume confirmation.

### B10. Tweezer Top/Bottom
- Two bars w/ matching highs (or lows) within 0.05*ATR. Requires prior trend + reversal candle. ~55%.

### B11. Marubozu
- `body / range > 0.95`. Continuation signal. Use as **filter**, not entry.

### B12. Doji Types
- **Long-legged:** `body / range < 0.1`, both shadows > 2*body → indecision at extremes.
- **Dragonfly:** `body / range < 0.1`, `upper_shadow < 0.1*range`, `lower_shadow > 0.6*range` → bullish reversal at support.
- **Gravestone:** mirror dragonfly → bearish at resistance.
- All require prior trend + confirmation.

### B13. Harami (inside bar)
- `body[0]` fully inside `body[-1]`, opposite color. Weakest reversal (~53%). Use only w/ S/R confluence.

---

## C. Volume-Based & Anchored Setups

### C1. Volume Profile Levels
- Bin traded volume by price (tick or 0.25pt for ES) over session (or N-day composite). Extract:
  - **POC** = argmax(volume-by-price)
  - **VA** = smallest contiguous range containing 70% of session volume; edges = **VAH**, **VAL**
  - **HVN** = local maxima above threshold (top 20%)
  - **LVN** = local minima below threshold (bottom 20%)

### C2. POC Rejection / Acceptance
- **Rejection:** Price approaches yesterday's POC (yPOC) from outside VA, prints reversal candle (B1-B7) within 0.25% of POC, RVOL ≥ 1.5 on rejection bar.
  - Entry: close of confirmation bar. Stop: beyond POC + 0.5*ATR. Target: prior VAH/VAL then opposite VA edge.
- **Acceptance:** Two consecutive 30m bars close *inside* opposite side of value area → trend day; ride to opposite VA edge or next HVN.

### C3. HVN / LVN Behavior
- **HVN:** acts as magnet + S/R. Fade first touch, follow-through on second.
- **LVN:** price traverses fast — use as breakout confirmation (skip through LVN = strong signal; getting stuck = failed break).

### C4. Anchored VWAP (aVWAP)
- **Anchors:** HOD, LOD, prior-day close, session open, earnings, FOMC, gap open, catalyst bar.
- **Compute:** `aVWAP(t) = Σ(Price_i * V_i) / Σ(V_i)` from anchor to t. `σ_bands = aVWAP ± k * stddev(price - aVWAP)`, k ∈ {1, 2, 3}.
- **Signal — mean-revert:** Price at ±2σ band, in-range regime (`ADX < 20`), reversal candle → entry back toward aVWAP. Stop = ±3σ. Target = aVWAP.
- **Signal — trend hold:** Pullback to aVWAP after impulse from anchor, RVOL ≥ 1.5, hammer/engulfing → continuation entry. Stop = 0.5*ATR below aVWAP.
- **[2026]:** Combined aVWAP + volume profile is the #1 institutional intraday stack per current futures trader consensus.

### C5. Cumulative Delta Divergence (proxy from up-tick/down-tick vol in Phase 1)
- `CVD(t) = Σ(aggressive_buy_vol - aggressive_sell_vol)`.
- **Bearish divergence:** New price high with lower CVD high → distribution. Combine w/ POC/aVWAP resistance = high-grade short.
- Source: Grimes, *Art & Science of Technical Analysis*.

### C6. Breakout with RVOL ≥ 2 Filter
- Any breakout of prior range/pattern requires `RVOL ≥ 2` on breakout bar AND next bar. Without this filter, breakouts fail ~50%; with it, success > 65% (Kirkpatrick & Dahlquist ch. 16).

### C7. Volume Dry-Up (VDU) Pre-Breakout
- 3+ bars with `V < 0.5 * mean(V[20..])` inside a base within 5% of pivot. Marks accumulation completion. Entry on pivot break w/ RVOL ≥ 2.

### C8. Climax Volume Reversal
- `V[0] > 3 * mean(V[20..])` AND `range[0] > 2 * ATR14` AND close in bottom (top) 25% of range after extended trend (≥ 8 bars).
- Entry: next-bar reversal candle. Stop: beyond climax H/L. Target: prior swing.
- **Base rate:** 60-65% (Wyckoff selling/buying climax).

---

## D. Session / Opening-Range Setups

### D1. ORB (5m / 15m / 30m / 60m)
- **Compute:** `[OR_H, OR_L] = [max(H), min(L)]` over first N minutes from 09:30 ET.
- **Trigger:** Close beyond OR by ≥ 0.1*ATR5m; RVOL ≥ 1.5.
- **Stop:** Opposite side of OR (or midpoint for tighter).
- **Target:** `OR_range` projected 1:1; scale at 0.5× and 1.5×.
- **Base rates [2026]:**
  - 5m ORB SPY: unfiltered 46.8% win, 1.8R avg; filtered (Mon/Wed/Fri + VIX 15-25 + no macro event) 65.4% (Chuk 2025 SSRN).
  - 15m ORB futures: ~55% w/ trend filter (Fisher).
- **Regime:** Best in normal-vol (VIX 12-25). Fails at VIX > 30 (whip) and VIX < 12 (no follow-through).
- **Anti-pattern:** OR < 0.3*ATR14 (compressed open, likely inside day). Skip. Also skip on macro-event days (CPI/FOMC).

### D2. Initial Balance (IB)
- **Def:** First 60m range (Market Profile). IB extension = price prints beyond IB later in session.
- **Signal:** **IB extension** w/ acceptance (2+ 30m closes beyond) = trend day continuation. **IB failure** = probe beyond, return, close inside → mean-revert to POC.
- **Entry IB failure:** On close back inside IB. Stop: beyond probe extreme. Target: opposite IB extreme or POC.

### D3. First-Hour Range Breakout
- Same as ORB 60m. Higher win rate than 5m but fewer signals.

### D4. Midday Drift
- 11:30-13:30 ET: low-volume grind. Fade extremes to VWAP; avoid breakout trades (low RVOL = fake).

### D5. MOC Imbalance
- Last 30 min: NYSE MOC imbalance data. `|imbalance| > $500M` w/ directional bias = ride into close. Requires broker feed.

### D6. Gap-and-Go vs Gap-Fade
- **Gap-and-go:** Gap ≥ 1% AND opens outside prior day VA AND first 5m closes in gap direction AND RVOL first 5m ≥ 3 → ride to next HVN.
- **Gap-fade:** Gap ≥ 1% AND opens *inside* prior day range (gap to VAH/VAL) AND first 15m fails to extend → fade to yPOC.
- **Rule:** Gap into prior VA = 70% fill probability by EOD; gap outside VA w/ volume = trend day (Dalton, *Mind Over Markets*).

---

## E. Multi-Timeframe Alignment

### E1. Alignment Grade Formula
For pattern P on TF `t`:

```
grade(P) = 0.5*strength(P, t)
         + 0.3*trend_agree(t_higher)
         + 0.2*trend_agree(t_lowest)
```

- `strength(P, t)` = normalized [0,1] score = base_rate × volume_conf × ATR_clean.
- `trend_agree(t_higher)` = 1 if 20EMA slope on next TF up (bull pattern) / down (bear pattern), else 0. TF ratio ~5× (5m↔1h, 1h↔D).
- `trend_agree(t_lowest)` = same on TF one level down (confirms trigger).

### E2. Weighting → Grade
| Grade | Threshold |
|---|---|
| ≥ 0.80 | A-setup: full size |
| 0.60-0.79 | B-setup: half size |
| 0.40-0.59 | C-setup: paper/skip |
| < 0.40 | Reject |

### E3. Classical MTF Combos
- **5m bull flag + 1h uptrend + D above 50MA** = highest-grade intraday continuation.
- **15m inverse H&S + D basing above 200MA + RVOL** = swing long.
- **Hourly double top + D at resistance + weekly RSI divergence** = swing short.
- **1m ORB break + 5m VWAP hold + 15m trend up** = 0DTE scalp.

---

## Anti-Pattern Summary

| Pattern | Anti-signature (skip) |
|---|---|
| H&S | No volume divergence; RS > head; break RVOL < 1 |
| Double top | `V(H2) > V(H1)` |
| Triangle | Break in last 25% of apex; RVOL < 1.5; ATR rising inside |
| Bull flag | Pullback > 50% Fib; ATR rising; > 20 bars |
| Wedge | ATR expanding inside |
| Cup & handle | V-shape; handle > 12% deep |
| Engulfing | No prior trend; RVOL < 1 |
| ORB | OR < 0.3*ATR; macro-event day; VIX > 30 |
| Gap-and-go | Gap into prior VA (fade instead) |
| POC rejection | Third+ test (breaks) |
| aVWAP mean-revert | ADX > 25 (trend regime — runs through) |

---

## Implementation Notes

- **Data:** Tick or 1m for ORB/aVWAP/CVD. 5m minimum for pattern engines. Volume profile needs session-boundary awareness (RTH vs ETH for ES).
- **Detection pipeline:** (1) swing-point detector (fractal or ZigZag w/ ATR threshold), (2) family matchers, (3) volume/regime gate, (4) MTF alignment scorer, (5) grade + alert.
- **Backtest first:** Bulkowski stats are stock-market cash-index; futures/0DTE differ. Compute own base rates per instrument × TF over ≥ 500 signals.
- **[2026 regime]:** Current tape favors ORB + aVWAP + flag continuations; H&S tops unreliable in QE-supported SPX. Re-fit filters quarterly.

**Primary sources:** Bulkowski *Encyclopedia of Chart Patterns* 3rd ed. (thepatternsite.com FailureRates); Kirkpatrick & Dahlquist *Technical Analysis* 3rd ed. ch. 15-17; Lo/Mamaysky/Wang 2000 "Foundations of Technical Analysis" *J. Finance* 55(4); Grimes *Art & Science of Technical Analysis*; Dalton *Mind Over Markets*; Chan *Quantitative Trading*; Chuk 2025 SSRN 6355218 (0DTE ORB regime-conditional).
