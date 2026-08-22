# Pattern Detection Rules — SMC/ICT, Wyckoff, Order Flow, Options Flow

**Companion to:** `CODEx_CLAUDE_COLLAB/CLAUDE_HANDOFF_PATTERN_GRADER_2026-08-22.md`
**Purpose:** Machine-implementable detection rules for market-structure, smart-money, Wyckoff, order-flow, and options-flow setups.

---

## 0. Setup Ranking — Implementation Priority

Score = (Edge 1-5) × (Freq 1-5) × (Detectability 1-5).

| Rank | Setup | Family | Edge | Freq | Detect | Score | Best TF |
|---|---|---|---|---|---|---|---|
| 1 | FVG retest in trend + displacement | ICT | 4 | 5 | 5 | 100 | 1m-15m |
| 2 | Liquidity sweep + CHoCH (LSCC) | SMC | 5 | 4 | 5 | 100 | 5m-1h |
| 3 | 0DTE gamma flip cross | Options | 5 | 5 | 4 | 100 | 1m-5m |
| 4 | Stacked footprint imbalance (3+) | Order flow | 4 | 5 | 5 | 100 | 1m-5m |
| 5 | Wyckoff spring + SOS | Wyckoff | 5 | 2 | 4 | 40 | 15m-daily |
| 6 | OTE (62-79%) into HTF OB | ICT | 4 | 4 | 4 | 64 | 5m-1h |
| 7 | Silver Bullet (10-11 AM ET) | ICT | 4 | 4 | 5 | 80 | 1m-5m |
| 8 | Delta divergence at swing extreme | Order flow | 4 | 4 | 4 | 64 | 1m-15m |
| 9 | London sweep → NY reversal | Session | 4 | 3 | 5 | 60 | 5m-15m |
| 10 | Breaker block retest | SMC | 4 | 3 | 4 | 48 | 15m-4h |
| 11 | Volume climax + absorption | Order flow | 4 | 3 | 3 | 36 | 1m-5m |
| 12 | Wyckoff UT/UTAD short | Wyckoff | 5 | 2 | 3 | 30 | 1h-daily |
| 13 | IV crush post-catalyst | Options | 4 | 3 | 5 | 60 | daily |
| 14 | Negative GEX trend day | Options | 5 | 2 | 5 | 50 | intraday |
| 15 | Equal highs/lows sweep | SMC | 3 | 5 | 5 | 75 | all |

---

## A. Market Structure Primitives

**Swing definition (fractal, canonical):**
- Swing high `H(i)`: `high[i] > high[i-k..i-1] AND high[i] > high[i+1..i+k]`. `k=2` (Bill Williams); `k=3` for 1m to filter noise.
- ATR filter (Grimes): reject swing if range from prior swing < 0.5 × ATR(14).

**BOS (Break of Structure):**
- Bullish BOS: close > last confirmed swing high in existing uptrend leg.
- Confirmation: full-body close beyond level; wick-only = invalid.
- Anti-pattern: BOS on low-vol drift w/ no displacement candle and no FVG behind = liquidity grab, not real BOS.

**CHoCH (Change of Character):**
- After HH-HL-HH sequence, first close < prior HL = bearish CHoCH.
- Regime-flip trigger; do NOT enter on CHoCH candle — wait for retest or displacement leg.

**Displacement candle:**
- Range ≥ 1.5 × ATR(20) AND body ≥ 60% of range AND close in top/bottom 25%.
- Must leave an FVG (§B) to qualify as "true displacement" per ICT.

**Liquidity pools:**
- Equal highs (EQH): 2+ swing highs within 0.1 × ATR of each other. Same for EQL.
- Trendline liquidity: ≥ 3 touches within tolerance.

**Stop run / sweep:**
- Bar prints high > EQH by ≥ 1 tick, closes back below EQH within same or next bar. Volume ≥ 1.5 × 20-bar avg.

Sources: ICT (Huddleston), Grimes 2012, Al Brooks *Trading Price Action: Trends*.

---

## B. Smart Money Concepts / ICT

| Setup | Detection | Entry | Stop | T1 | T2 | Invalid | Regime | Anti-pattern |
|---|---|---|---|---|---|---|---|---|
| **Bullish OB** | Last down-close candle before displacement leg up that created BOS | Limit at OB high (or 50% of OB) | 1 tick below OB low | Prior swing high | Next HTF liquidity pool | Full-body close below OB | Trending | OB formed w/o displacement or w/o leaving FVG |
| **Bearish OB** | Mirror | Limit at OB low (or 50%) | 1 tick above OB high | Prior swing low | Next HTF sell-side liq | Full-body close above | Trending | Same |
| **Breaker** | OB that fails then price returns from opposite side | Retest of failed OB | Beyond breaker high/low | Origin of move | Prior HTF liq | Close through breaker | Post-CHoCH | Deep-tested breaker (already mitigated) |
| **Mitigation block** | Last up-close before down move that took liquidity | Return to 50% of MB | Beyond MB extreme | Point of imbalance | HTF liq | Close beyond | Reversal | Confusing MB w/ OB (MB = opposite polarity of nearest OB) |
| **FVG (SIBI/BISI)** | 3-candle: `candle1.high < candle3.low` (bullish BISI) OR `candle1.low > candle3.high` (bearish SIBI) | Retest of FVG midpoint (Consequent Encroachment) | Beyond FVG opposite bound | Prior swing | HTF FVG | 50% fill w/o reaction | Post-displacement trend | FVG in chop — no directional bias |
| **OTE** | Fib 61.8-78.6% retrace of most recent BOS leg | Confluence w/ OB or FVG in OTE zone | Beyond fib 100% (origin) | Fib -0.5 extension | Fib -1.0 or HTF liq | Close beyond 100% | Trending, post-sweep | OTE in ranging market |
| **Inducement** | Minor liquidity taken BEFORE reaching true POI (deep OB/FVG) | Wait for sweep of inducement then react at HTF POI | Below HTF POI | Sweep origin | HTF opposing liq | HTF POI closed through | All | Entering on inducement itself = trapped |
| **Premium/Discount** | Split range from last major swing H to L; > 50% = premium, < 50% = discount | Sell arrays in premium, buy in discount | Range extreme | Range midline (equilibrium) | Opposite extreme | Range extreme breached w/ displacement | Balanced | Applying to unclear range |

**Kill zones (ET, ICT):**
- London: 02:00-05:00
- NY AM: 07:00-10:00
- Silver Bullet: 10:00-11:00 AND 14:00-15:00
- London Close: 10:00-12:00

**Silver Bullet entry:** FVG that forms during the 10-11 AM ET window in the direction of daily bias; enter on retest, stop beyond FVG, T1 at nearest liquidity.

Sources: Huddleston (ICT Mentorship 2016-2023), Cottle *Options Strategy Deconstructed* on liquidity concepts.

---

## C. Wyckoff

**Accumulation schematic (Weis/Hutson):**

| Phase | Events | Detection rule |
|---|---|---|
| A | PS, SC, AR, ST | SC = wide-range down bar, vol > 3× 20-bar avg, close in top 1/3. AR = rally ≥ 50% of SC range on lower vol. ST = retest SC low w/ vol ≤ 0.7 × SC vol |
| B | Building cause | Range-bound between AR high and ST low. Vol drying up on down-moves (Weis wave) |
| C | Spring / test | Spring: penetrates ST low by ≤ 0.5 × ATR, vol ≤ SC vol × 0.6, closes back inside range. Test: light-vol revisit of spring low |
| D | SOS, LPS | SOS: up-bar w/ range > 1.5× avg AND vol > 1.5× avg, closes near high, breaks TR resistance. LPS: pullback to broken resistance on light vol |
| E | Markup | Series of HH/HL; BUC = "back up to the creek" |

**Spring entry:**
- Detect: bar low < TR low, bar close > TR low, next bar close > spring bar high.
- Entry: close of confirming bar OR limit at spring midpoint.
- Stop: 1 tick below spring low.
- T1: TR high (creek). T2: measured move = TR height projected up from breakout.
- Invalid: close below spring low.

**Distribution mirror:** PSY, BC, AR, ST, UT, UTAD, SOW, LPSY.

**UTAD:** penetrates TR high, closes back inside, vol elevated but demand absorbed. Short at close of confirming down-bar; stop above UTAD high.

**Anti-pattern:** Spring formed w/o clear preceding TR (no PS/SC/AR) = just a wick. Requires phase A first.

Sources: Hutson *Charting the Stock Market: The Wyckoff Method*, Weis *Trades About to Happen*.

---

## D. Order Flow / Microstructure

| Setup | Rule | Entry | Stop | T | Notes |
|---|---|---|---|---|---|
| **Stacked imbalance** | ≥ 3 consecutive price levels with `bid×3 ≤ ask` (bullish) or `ask×3 ≤ bid` (bearish) | Retest of stack origin | Opposite side of stack | Next unfilled stack or HTF level | Bookmap/Sierra/Jigsaw; 3:1 ratio is Volman/DiNapoli standard. **Phase 2 — needs tick feed** |
| **Absorption** | Large size traded (> 3× avg cluster vol) at level, price does NOT move > 2 ticks | Fade into absorption after 2nd confirming bar | Beyond absorption bar high/low | Prior swing | Icebergs typical. **Phase 2** |
| **Delta divergence** (proxy OK in Phase 1) | Price makes new HH but CVD makes LH (or inverse) over ≥ 5 bars | Structural break in delta direction | Beyond price extreme | Prior structural pivot | Best at daily HOD/LOD |
| **Volume climax** | Bar vol > 3× 50-bar avg AND range > 2× ATR AND wick > 50% of range | Fade on next-bar failure to extend | Beyond climax extreme | 50% retrace of climax bar | Al Brooks "exhaustion bar" |
| **Iceberg** | Repeated fills at one price w/ tape prints ≥ 10× visible book size | Enter direction of iceberg after level holds | Just through iceberg level | Next liquidity pocket | Sierra Chart trade filter. **Phase 2** |
| **Sweep** | Price takes multiple levels (≥ 5 ticks) in ≤ 500ms w/ aggressive market orders | Fade if immediate rejection (< 2 sec) | Beyond sweep extreme | Sweep origin | HFT stop-run signature. **Phase 2** |
| **DOM spoof** | Large order (> 5× median) posted then pulled within 2 sec w/o fill; repeats | No trade — flag for caution | — | — | Regulatory grey; use as anti-signal. **Phase 2** |

Sources: Dalton *Mind Over Markets* (Market Profile), Volman *Understanding Price Action*, Peters/Bookmap docs, academic: Cont & Kukanov "Optimal order placement" (2017).

---

## E. Options Flow

| Setup | Detection | Trigger | Stop/Invalid | Target | Notes |
|---|---|---|---|---|---|
| **GEX flip** | Net dealer gamma crosses 0 (SpotGamma/MenthorQ feed) | Enter trend direction on close beyond flip level | Return to flip level | Next dealer wall | Above flip = mean-revert; below = trend-amplify |
| **Pos gamma pin** | Large 0DTE OI concentration at ATM strike, GEX > +$500M | Fade moves > 0.3% away from wall | 0.5% beyond wall | Wall strike | 14:00-15:30 ET most reliable |
| **Neg gamma trend** | GEX < -$1B AND price below flip | Trend-follow breakouts | Cross back above flip | Prior day extreme, or Vanna wall | Vol expansion regime |
| **0DTE pin risk** | Max OI strike within 0.5% of spot at 14:00 ET | Iron fly around max-OI strike | Break of expected move | Pin | Fails on macro news |
| **UOA + delta hedge** | Single-print > 500 contracts, > 3× ADV, ask-side, OTM | Follow flow direction after 30-min confirmation | Below/above signal bar | 1× expected move | Cheddar Flow / Unusual Whales |
| **IV crush** | Front-month IV > 1.5× 30-day realized, catalyst < 5 days | Short vega (calendar/iron condor) after event | Vega expansion post-event | 50% premium decay | Earnings, FOMC, CPI |
| **P/C ratio extreme** | Equity P/C < 0.5 (complacency) or > 1.2 (fear), z-score > 2 | Contrarian bias for next 3-5 days | Ratio normalizes | Mean reversion | CBOE daily data |

Sources: SpotGamma/MenthorQ 2026 research, Nasdaq/CBOE 0DTE studies (50-63% of SPX volume is 0DTE), Cottle *Options Trading: The Hidden Reality*, Sinclair *Volatility Trading*.

---

## F. Session / Macro Overlays

| Window (ET) | Setup | Rule |
|---|---|---|
| 02:00-05:00 | London sweep | Take out Asia range → often reverses in NY AM |
| 08:30 | News release | Suppress entries ±5 min; use IB range only after 09:30 |
| 09:30-10:00 | NY open reversal | Opening drive fails within 30 min → fade to VWAP |
| 10:00-11:00 | ICT Silver Bullet | First FVG in daily-bias direction |
| 14:00-15:00 | 2nd Silver Bullet | Same rule; often ties to gamma pin |
| 15:45-16:00 | MOC imbalance | > $500M imbalance from NYSE — fade to close only if same-direction as trend, else follow |
| 17:00 CT | MES reopen | Overnight ranges compress; ORB from 17:00-18:00 CT works on macro days |
| CPI/NFP/FOMC | Macro | No entries 15 min before; wait for first 5-min close after |

Sources: ICT kill zone doctrine, Dalton IB research, Larry Williams *Long-Term Secrets to Short-Term Trading*.

---

## G. Regime Detectors — Pattern Trust Map

| Detector | Compute | Regime signal | Trust these families |
|---|---|---|---|
| **HMM (2-state)** | Fit 2-state Gaussian HMM on log-returns + realized vol; use `hmmlearn` | State 0 = trend, State 1 = chop | Trend → SMC/ICT BOS, OB, OTE. Chop → mean-revert, gamma pin |
| **Hurst exponent** | R/S or DFA on log-returns, 100-bar window | H > 0.55 = trending, H < 0.45 = mean-revert, ~0.5 = random | Trend → displacement/FVG. MR → absorption/climax fades |
| **RV/IV ratio** | 20-day realized vol / VIX (or ATM IV) | > 1.0 = vol underpriced; < 0.7 = vol overpriced | > 1.0 → buy premium, breakout plays. < 0.7 → sell premium, IV crush |
| **VIX term structure** | VIX9D / VIX / VIX3M | Contango = calm; backwardation = stress | Contango → gamma pin, OTE. Backwardation → sweep + trend |
| **TRIN (Arms)** | `(adv/dec) / (adv_vol/dec_vol)` | > 2 = capitulation, < 0.5 = euphoria | Extremes → Wyckoff climax setups |
| **Breadth thrust** | Zweig: 10d EMA of `adv/(adv+dec)` crosses 0.40 → 0.615 in 10 days | Rare bullish signal | Multi-week trend-follow |
| **Dealer positioning** | GEX from options chain, dollar-gamma | Pos > +$1B = pin. Neg < -$1B = trend | Cross-reference with kill-zone entries |

**Composite pattern-trust matrix:**

| Regime | High-trust setups | Avoid |
|---|---|---|
| Trend + neg GEX + H > 0.55 | BOS + FVG, breaker, stacked imbalance | Spring, gamma pin |
| Chop + pos GEX + H < 0.45 | Gamma pin, absorption fade, OTE reversal at range extreme | Breakout, BOS |
| High vol + backwardation | London sweep, Wyckoff climax entries, delta divergence | Iron condors, IV shorts |
| Low vol + contango | 0DTE iron flies, pin plays, IV crush setups | Trend-follow breakouts |

---

## Universal Anti-Pattern Checklist (apply to every entry)

1. **BOS without displacement** — wick-only break, no FVG. Skip.
2. **OB without prior liquidity sweep** — untested demand, weak.
3. **FVG in chop** — no HTF bias. Skip.
4. **Spring without phase A** — just a wick, not Wyckoff.
5. **Stacked imbalance against HTF trend** — often a trap for continuation.
6. **Delta divergence in strong trend** — first divergence usually fails; wait for 2nd.
7. **Gamma pin on macro day** — pin breaks on news.
8. **Silver Bullet against daily bias** — countertrend SB has ~30% edge vs 60%+ w/ bias.
9. **UOA in dead-flow ticker** — need liquid underlying for hedging inference.
10. **Any setup in first 5 min post-08:30 release** — spread/slippage kills edge.

---

## 2026 Practitioner Signal (last 30 days)

- SMC works best as **OB + FVG + HTF liquidity sweep triple-confluence** per BackTrex/ChartingLens 2026 guides. Isolated OBs get broken.
- 0DTE now **50-63% of SPX volume** per SpotGamma 2026; **gamma flip is the pivotal intraday level**, not VWAP. Trade above/below flip differently.
- **Stacked imbalance (3+ levels)** is the highest-conviction footprint signal per United Daytraders; single imbalances are noise.
- **Wyckoff spring detection is being automated** (ChartMini, MQL5 article 22628) — edge shrinking on obvious daily-TF setups; intraday springs still work.
- **ES needs longer confirmation windows than NQ** for delta divergences per QuantVPS 2026.

---

## Implementation Order (for Codex)

1. Build market-structure primitives (§A) — everything else depends on this.
2. FVG + OB detection (§B, score 100, highest freq).
3. GEX ingestion (SpotGamma/MenthorQ or self-computed from CBOE chain).
4. Footprint imbalance engine (Phase 2 — needs tick data / Databento or Rithmic feed).
5. Wyckoff phase state machine (defer — lower freq).
6. Regime detector overlay (HMM + Hurst + GEX + RV/IV) — gates which detectors fire alerts.

Primary lineage: Huddleston (ICT), Weis/Hutson (Wyckoff), Dalton (Market Profile), Volman/Al Brooks (price action), Cottle/Sinclair (options), SpotGamma/MenthorQ (0DTE gamma), Cont & Kukanov (microstructure academic).
