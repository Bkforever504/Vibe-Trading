# ICT (Inner Circle Trader / Michael Huddleston) Model — Deep Dive + Backtest Plan

**Date:** 2026-08-23
**Author:** Claude (session)
**Purpose:** Complete catalog of every ICT concept, honest evidence review, prioritized backtest plan, dashboard integration recommendation.
**Bottom line:** ICT is primarily a DESCRIPTIVE vocabulary. PREDICTIVE edge is largely unproven at any statistical rigor. Use as one weak feature in composite grader, NEVER as standalone entry trigger, and demand backtest proof before letting any single concept size positions.

---

## 0. Executive Summary — Why This Doc Exists

Kenny asked: "Can we backtest the ICT model and all of the ICT model concepts? Can it help the dashboard selection process?"

**Short answer:**
1. **Yes, we can backtest ICT concepts** — most are mechanizable if we commit to one strict labeling rule (which loses the "flexibility" ICT enthusiasts value, but that's the price of statistical honesty).
2. **Should we?** Only for the top 8 candidates ranked in §7. The other 30+ ICT concepts either lack rigorous formal definitions, or represent post-hoc labels for price action that already happened.
3. **Will it help dashboard selection?** Marginally, if used correctly. Existing grader already has CISD + BOS + CHoCH + OB + FVG + kill-zone + STRAT + 08:00-09:00 range + PDH/PDL/PWH/PWL. Adding more ICT concepts risks noise without adding signal. Backtest before adding.
4. **Founder credibility:** Michael Huddleston failed his 2016 Robbins World Cup attempt and has no verified live-account track record after 15+ years teaching + 2M+ YouTube subscribers. The "99.6% win rate" claim previously flagged by Codex is confirmed fabricated (no primary source exists).

**Recommendation:** Run the §7 backtest plan. Let evidence dictate which concepts feed the pattern grader. Reject any concept that fails to beat random-entry-in-same-window after realistic costs.

---

## 1. Complete ICT Concept Catalog

Organized by family. For each: definition, detection approximation, backtest-readiness rating (1-5: 5 = fully mechanical, 1 = requires human judgment), current implementation status in Vibe-Trading repo.

### Family A — Market Structure Primitives

| Concept | Definition | Detection rule | Backtest-ready | Repo status |
|---|---|---|---|---|
| Swing high/low | Fractal HL/HH | k=2 or k=3 fractal + ATR filter (Grimes 0.5×ATR) | 5 | ✅ shipped |
| BOS (Break of Structure) | Close beyond last confirmed swing in existing trend leg | Full-body close beyond level | 4 | ✅ shipped |
| MSS (Market Structure Shift) / CHoCH | First close < prior HL (bearish) after HH-HL-HH | Body close through structural pivot | 4 | ✅ shipped |
| Internal Range Liquidity (IRL) | Liquidity WITHIN current range | Equal highs/lows within range | 3 | Partial |
| External Range Liquidity (ERL) | Liquidity OUTSIDE current range | PDH/PWH/PMH extremes | 4 | ✅ shipped (PDH/PDL/PWH/PWL) |
| PD Array hierarchy | Premium/discount arrays ranked by HTF | Multi-TF Fib split of major swing | 3 | Not shipped |

### Family B — Institutional Order Flow (IOF)

| Concept | Definition | Detection rule | Backtest-ready | Repo status |
|---|---|---|---|---|
| Bullish IOF | Sequence of HH/HL supported by displacement + FVG | Composite: BOS + displacement + FVG left | 3 | Partial |
| Bearish IOF | Mirror | Composite | 3 | Partial |
| High-freq IOF | Intraday IOF (1-5m) | Same as above on intraday TF | 3 | Partial |
| Low-freq IOF | Multi-day IOF (1h-D) | Same on HTF | 3 | Partial |

### Family C — Order Blocks (OB)

| Concept | Definition | Detection rule | Backtest-ready | Repo status |
|---|---|---|---|---|
| Bullish OB | Last down-close candle before displacement leg up that created BOS | Programmatic: find last opposing-color candle before X-ATR impulse | 3 | ✅ shipped |
| Bearish OB | Mirror | Same | 3 | ✅ shipped |
| Breaker Block | OB that fails then price returns from opposite side | Detect: OB level breached, then re-tested from other side | 3 | ✅ shipped |
| Mitigation Block | Last up-close before down move that took liquidity | Same as OB but opposite polarity | 3 | Partial |
| Rejection Block | Wick-heavy candle w/ full body rejection at extreme | Wick-to-body ratio > 3, at prior HTF pivot | 3 | Not shipped |
| Propulsion Block | OB that has been re-tested + held once already | Retest count = 1, held | 3 | Not shipped |
| Vacuum Block | Range with no volume, high-velocity move through | Low-volume bar between two high-volume | 3 | Not shipped |
| Unfilled OB | OB not yet re-tested | Tracked age > N bars, untouched | 4 | Not shipped |
| Sponsored Candle | Wide-range bar w/ elevated volume anchoring OB | Range > 1.5×ATR + vol > 1.5×avg | 4 | Not shipped |

### Family D — FVG / Imbalance

| Concept | Definition | Detection rule | Backtest-ready | Repo status |
|---|---|---|---|---|
| FVG (BISI) | Bullish: candle1.high < candle3.low | 3-candle geometric | 5 | ✅ shipped |
| FVG (SIBI) | Bearish: candle1.low > candle3.high | Mirror | 5 | ✅ shipped |
| Balanced Price Range (BPR) | Two overlapping FVGs (bullish + bearish) | Detect overlap of two adjacent FVGs | 4 | Not shipped |
| Inefficient Price Delivery | Any unfilled FVG | Track FVG open until filled | 4 | Partial |
| Liquidity Void | Multi-candle no-trade zone | Sequence of thin-body wide bars | 3 | Not shipped |
| Volume Imbalance | Candle w/ vol > 3×avg + no wick opposing side | Vol + shape gate | 4 | Not shipped |
| Opening Gap | Gap between prior close + current open | trivial | 5 | ✅ shipped |
| NDOG (New Day Opening Gap) | Gap from prior day close to today's open | Session-boundary aware | 5 | Not shipped |
| NWOG (New Week Opening Gap) | Sunday open gap from Friday close | Session-boundary aware | 5 | Not shipped |
| Consequent Encroachment (CE) | 50% midpoint of FVG | trivial | 5 | ✅ shipped |
| Quadrant Theory | FVG split into 4 quadrants for entry precision | Divide FVG range by 4 | 5 | Not shipped |

### Family E — Liquidity

| Concept | Definition | Detection rule | Backtest-ready | Repo status |
|---|---|---|---|---|
| Buy-Side Liquidity (BSL) | Resting stops above equal highs | EQH cluster w/in 0.1×ATR | 4 | Partial |
| Sell-Side Liquidity (SSL) | Resting stops below equal lows | EQL cluster | 4 | Partial |
| Equal Highs / Equal Lows | 2+ swings within tolerance | Tolerance-based grouping | 5 | ✅ shipped |
| Trendline Liquidity | ≥3 touches of a trendline | Linear regression + touch count | 4 | Not shipped |
| Session H/L Liquidity | Highs/lows of Asian, London, NY sessions | Session-boundary aware | 4 | Not shipped |
| PDH/PDL/PWH/PWL | Previous day/week high/low | trivial | 5 | ✅ shipped |
| Asian Range Liquidity | High/low of Asian session (00:00-07:00 GMT) | Session boundary | 5 | Not shipped (equities/futures) |
| CBDR (Central Bank Dealers Range) | 14:00-20:00 GMT range | Session boundary | 5 | Not shipped |
| Liquidity Grab / Purge / Sweep / Run | Wick through liquidity + reclose | Sweep detection | 4 | ✅ shipped |

### Family F — Fibonacci / OTE / Standard Deviations

| Concept | Definition | Detection rule | Backtest-ready | Repo status |
|---|---|---|---|---|
| OTE 62-79% | Fib retracement zone 62-79% of BOS leg | Fib calc + range gate | 5 | Partial |
| Sweet Spot 70.5% | Midpoint of OTE zone | Fib | 5 | Not shipped |
| Standard Deviation Projections | -0.5, -1.0, -1.5, -2.0 Fib extensions | Fib | 5 | Not shipped |
| Symmetrical Price | Equal legs / measured moves | Range × 1.0 projection | 5 | Not shipped |
| PD Range / Equilibrium | 50% of major swing = equilibrium | Fib | 5 | Not shipped |
| Market Maker Models (MMBM/MMSM) | Consolidation → manipulation → distribution | 3-phase state machine | 3 | Not shipped |

### Family G — Kill Zones + Times

| Concept | Time (ET) | Detection | Backtest-ready | Repo status |
|---|---|---|---|---|
| Asian Kill Zone | 20:00-00:00 | Time filter | 5 | Not shipped |
| London Open KZ | 02:00-05:00 | Time filter | 5 | ✅ shipped |
| NY AM KZ | 07:00-10:00 | Time filter | 5 | ✅ shipped |
| London Close KZ | 10:00-12:00 | Time filter | 5 | ✅ shipped |
| Silver Bullet AM | 10:00-11:00 | Time filter | 5 | ✅ shipped |
| Silver Bullet PM | 14:00-15:00 | Time filter | 5 | ✅ shipped |
| NY Lunch | 12:00-13:00 | Time filter | 5 | Not shipped |
| Macro Times (15/45 past hr) | Every :15 + :45 | Time filter | 5 | Not shipped |
| True Day Open | 00:00 NY time | Time filter | 5 | Not shipped |
| CBDR range | 14:00-20:00 GMT | Time filter | 5 | Not shipped |

### Family H — Time-Based

| Concept | Definition | Detection | Backtest-ready | Repo status |
|---|---|---|---|---|
| PO3 (Power of 3) | Accumulation → manipulation → distribution phases | 3-phase state machine per session | 3 | Not shipped |
| True Day | 00:00 NY to 23:59 NY | Time filter | 5 | Not shipped |
| Quarterly Theory | Q1/Q2/Q3/Q4 of day = 6h blocks | Time filter | 5 | Not shipped |
| Weekly Profile | Monday-Friday setups | Day-of-week | 5 | Not shipped |
| Monthly Profile | Week 1/2/3/4 setups | Week-of-month | 5 | Not shipped |
| Seasonal Tendencies | Month-of-year tendencies | Month filter | 5 | Not shipped |

### Family I — Market Maker Models

| Concept | Definition | Detection | Backtest-ready | Repo status |
|---|---|---|---|---|
| MMBM (Market Maker Buy Model) | Consolidation below → manipulation down → distribution up | 3-phase state | 2 | Not shipped |
| MMSM (Market Maker Sell Model) | Mirror | 3-phase state | 2 | Not shipped |
| Judas Swing | Early session false move → reversal | Session-open extremum sweep + reversal | 4 | Not shipped |

### Family J — CISD / IFVG / Unicorn

| Concept | Definition | Detection | Backtest-ready | Repo status |
|---|---|---|---|---|
| CISD (Change in State of Delivery) | HTF FVG → 3rd candle range → sweep → IFVG → CISD sequence | Multi-stage state machine | 3 | ✅ shipped |
| IFVG (Inverse FVG) | FVG that gets inverted (traded through fully) | Detect FVG + full-body close through | 4 | ✅ shipped |
| Displacement | Wide-range full-body candle leaving FVG | ATR × body ratio | 5 | ✅ shipped |
| Engineering Liquidity | Move designed to sweep opposing liquidity | Sweep detection + prior consolidation | 3 | Not shipped |
| Unicorn Model | Breaker + FVG confluence, entry on retest | Two-detector confluence | 3 | Not shipped |

### Family K — HTF Concepts

| Concept | Definition | Detection | Backtest-ready | Repo status |
|---|---|---|---|---|
| Daily Bias | D-timeframe direction bias | 20/50 EMA slope on D | 5 | Partial |
| Weekly Bias | W-TF direction | Same on W | 5 | Not shipped |
| Monthly Bias | M-TF direction | Same on M | 5 | Not shipped |
| Quarterly Shift | Change in bias each quarter | Quarter over quarter comparison | 4 | Not shipped |
| Seasonal Templates | Historical monthly patterns | Month × instrument stats | 3 | Not shipped |
| Key Highs/Lows | Multi-year swing extremes | ATR-filtered swing detection HTF | 4 | Not shipped |

### Family L — Session Templates

| Concept | Definition | Detection | Backtest-ready | Repo status |
|---|---|---|---|---|
| Asian Range Template | Trade w/in Asian range | Session boundary + range calc | 4 | Not shipped |
| London Judas | Fake London-open move → NY reverse | Session sweep + reversal | 3 | Not shipped |
| NY Reversal | NY session opens against Asia/London bias | Session compare | 4 | Not shipped |
| NY AM Breakout | Break of London range in NY AM | Range + break detection | 5 | ✅ shipped (ORB) |
| PM Session Reversal | Afternoon reverses morning trend | Time + trend flip | 3 | Not shipped |
| EIA Template | Oil-specific pre/post release | Event calendar | 4 | Not shipped |
| FOMC Template | Fed-specific pre/post release | Event calendar | 4 | Not shipped |
| NFP Template | Jobs report specific | Event calendar | 4 | Not shipped |

### Family M — SMT Divergence

| Concept | Definition | Detection | Backtest-ready | Repo status |
|---|---|---|---|---|
| SMT ES vs NQ | Correlated pair diverges | Compare 5m closes | 5 | Not shipped |
| SMT EUR vs GBP | Same for FX | Compare | 5 | Not shipped |
| SMT DXY vs pairs | Dollar vs pair confirmation | Compare | 5 | Not shipped |

### Family N — Weekly / Daily Templates

| Concept | Definition | Detection | Backtest-ready | Repo status |
|---|---|---|---|---|
| Monday Range | Mon high/low = weekly liquidity magnet | Store Mon extremes | 5 | Not shipped |
| Tuesday Accumulation | Tue tends to accumulate | Day-of-week stat | 3 | Not shipped |
| Wednesday Distribution | Wed reversal | Day-of-week stat | 3 | Not shipped |
| Midweek Reversal | Wed-Thu direction flip | Day-of-week + trend flip | 3 | Not shipped |
| Friday Close | Position squaring | Time + volume | 3 | Not shipped |
| Sunday Open | Weekend gap play | Session boundary | 4 | Not shipped |

### Family O — Silver Bullet
Already covered in Family G. Setup: FVG in daily-bias direction after HTF liquidity sweep within 10-11 AM or 2-3 PM ET window.

### Family P — Turtle Soup
Best-attributed concept in ICT (actually predates ICT — originates from the original Turtle Trading rules). False breakout of prior day/week high/low → reversal. Backtestable, has some academic support.

### Family Q — Unicorn Model
Already in Family J. Breaker + FVG confluence entry.

### Family R — OTE
Already covered Family F. 62-79% Fib retracement of most recent BOS leg.

### Family S — Institutional Reference Points (IRPs)
Historical significant highs/lows (yearly, multi-year). Overlaps HTF concepts (Family K).

---

## 2. Repo Status Summary

**Shipped ICT concepts (14):**
BOS, CHoCH, FVG (BISI/SIBI), CE, OB (bull/bear), Breaker, Displacement, Sweep, Kill Zones (London Open + NY AM + London Close + Silver Bullet AM+PM), Equal Highs/Lows, PDH/PDL/PWH/PWL, CISD full sequence, IFVG, STRAT bar classification (from Aug 22 Codex work).

**Partial / needs upgrade (7):**
IOF composite, PD Array hierarchy, IRL/ERL, Mitigation Block, OTE, Daily Bias, Liquidity Grab labeling.

**Not shipped — potential value adds (17):**
BPR, Volume Imbalance, NDOG, NWOG, Quadrant Theory, Asian Range, CBDR, Session H/L Liquidity, Trendline Liquidity, Standard Deviation Projections, Symmetrical Price, PO3, Judas Swing, MMBM/MMSM, Turtle Soup, Unicorn, SMT Divergence, Quarterly Theory, Weekly/Monthly Profile, Seasonal Tendencies, Session Templates (London Judas, NY Reversal, PM Reversal, FOMC/NFP/EIA templates).

---

## 3. Evidence Review — Brutal Honesty

**Rigorous published backtests meeting the bar (n ≥ 200 trades, ≥ 6mo OOS, transparent methodology):** essentially ZERO.

**Founder credibility:**
- Michael Huddleston failed 2016 Robbins World Cup Trading Championship
- No verified myfxbook / audited account after 15+ years teaching
- Primary income = YouTube ad revenue (self-acknowledged)
- Re-entered Robbins 2024 without demonstrating profitability

**Fabricated claims flagged:**
- "99.6% win rate" — no primary source, confirmed fabricated in Codex Aug 22 work
- "Silver Bullet 70%+ win rate" — no published methodology
- "OTE 62-79% is statistically superior to other Fib zones" — no evidence
- "CISD sequence beats random in same window" — untested

**Concepts w/ SOME empirical support (independent of ICT branding):**
- Kill zone volatility clustering — real, documented in every intraday microstructure paper (BUT: volatility clustering ≠ directional edge)
- False breakout / stop-hunt reversion — some support (Lo/Mamaysky/Wang 2000, Kaufman)
- Session-anchored volume patterns — real
- Overnight gap tendencies — real

**Concepts w/ NO empirical support:**
- OTE specific 62-79% specialness
- Order block retest edge (fails multiple-testing correction per Aronson 2006)
- Silver Bullet directional edge
- PO3 predictive power (single OSF preprint, weak)
- All MMBM/MMSM claims
- Most CISD-family claims

**Meta-critique — "moving goalposts":**
Documented pattern: when signal fails, ICT community adds a new sub-concept (mitigation, breaker, inducement, IFVG, CISD, unicorn) to explain the failure. This unfalsifiability is the hallmark of a pseudo-scientific framework.

**Meta-critique — "descriptive vs predictive":**
ICT vocabulary is defensible as descriptive shorthand. Predictive edge claims require evidence. Distinguish sharply.

**Prop-firm ecosystem observation:**
Prop-firm coaches report ICT traders show "better market structure analysis" but "lack systematic execution and risk management." Translation: they can talk about the chart but they blow the challenge.

**Overall verdict:**
Would I spend real money on ICT-graded signals as standalone entry triggers? **No** — until §4 backtest plan produces evidence.
Would I use ICT concepts as descriptive layer in the pattern grader? **Yes** — carefully, as one weak feature in composite scoring, not as standalone.

---

## 4. Backtest Priority Ranking

Ranked by (mechanizability × plausibility × claimed-edge signal-to-noise). Highest priority first.

| Rank | Concept | Instrument | TF | Sample target | Benchmark | Falsification threshold |
|---|---|---|---|---|---|---|
| 1 | **Kill Zone directional bias (NY AM 09:30-11:00 ET)** | ES/MES/NQ/MNQ | 5m + 15m | 500 trades | Random-entry-same-window, buy/hold, VWAP mean-revert | Wilson LB win rate ≥ 0.53 vs random 0.50 (α=0.05) |
| 2 | **FVG fill probability within N bars** | ES + SPY | 1m/5m/15m | 1000+ FVGs | Random-gap-same-size | Fill rate ≥ 15pp above random baseline |
| 3 | **Judas Swing (session open false → reverse)** | ES + EURUSD | 15m | 300 trades | ORB, random-in-window | Wilson LB win rate ≥ 0.55 |
| 4 | **Turtle Soup (2-day breakout failure fade)** | ES + EURUSD | D | 200 trades | Donchian breakout | Sharpe ≥ 0.5 after costs |
| 5 | **OB retest edge** | ES | 15m | 400 trades | Random pullback in same trend | Wilson LB ≥ 0.53 |
| 6 | **OTE zone A/B/C test** (50% vs 62-79% vs 79-88%) | ES | 15m + 1h | 300 per zone | Cross-zone comparison | 62-79% zone win rate ≥ 5pp above other zones |
| 7 | **PO3 daily model** | EURUSD | D | 250 sessions | Previous-day continuation baseline | Directional prediction accuracy ≥ 55% |
| 8 | **CISD sequence** | ES + SPY | 5m + 15m | 400 sequences | Random-entry same regime | Wilson LB win rate ≥ 0.55 |
| 9 | **Silver Bullet direction** | ES | 1m + 5m | 300 SBs | Random-in-window (10-11 AM) | Wilson LB ≥ 0.55 |
| 10 | **SMT divergence ES vs NQ** | ES entry after SMT flag | 5m + 15m | 200 divergences | Random ES entry | Win rate ≥ 55% + avg R ≥ 1.5 |

**Statistical requirements (all backtests):**
- Sample size min 200 trades (~380 for α=0.05 power 0.8 vs 50% baseline)
- Out-of-sample holdout ≥ 6 months
- Transaction cost model: 1 tick slippage entry + exit, $0.35/side commission (MES) or $0.005/share (SPY)
- Report Wilson lower bound (95% CI) — NOT raw win rate
- Report Brier skill vs baseline (positive = better than random)
- Report Sharpe + Sortino + max DD
- Report all 3 benchmarks (random-in-window + buy/hold + momentum baseline)

**Kill criteria — a concept fails backtest if ANY of:**
- Wilson lower bound win rate ≤ baseline
- Sharpe < 0.3 after realistic costs
- Max DD > 20% of test window
- OOS performance < 50% of in-sample performance (overfitting)

---

## 5. Dashboard Integration Plan

**Principle:** Only backtest-passing concepts influence grade scoring. Pre-backtest concepts show as `governance_status: unvalidated_pattern_hypothesis` (matches existing Phase A ledger).

### 5.1 Pre-backtest (Phase 1)
- All 14 already-shipped concepts continue showing on dashboard as context
- No grade weight from unvalidated concepts
- CISD already correctly in `unvalidated_pattern_hypothesis` state — do NOT change

### 5.2 Post-backtest (Phase 2 — after Codex runs §4)
- Concepts that PASS backtest gate: flip `governance_status: validated_pattern`, add to grader confluence stack w/ measured `base_rate` from OOS results
- Concepts that FAIL backtest gate: flip `governance_status: rejected_pattern_hypothesis`, remove from dashboard entirely (or move to deprecated bin)
- Update `pattern_grade_scorer.py` §5 rubric: validated concepts contribute to Component 5 "Confluence Stack" (+25 per different-family confluence, max 100). Rejected concepts contribute zero.

### 5.3 New dashboard panel — "ICT Concept Scorecard"
- One row per backtested concept
- Columns: concept name, instrument, TF, backtest date, sample size, Wilson LB, Brier skill, Sharpe, verdict (VALIDATED / REJECTED / INSUFFICIENT DATA)
- Sort by Wilson LB descending
- Filter by family
- File location: `frontend/src/components/detection/ICTScorecardTab.tsx` (new)
- Data source: `~/.vibe-trading/reports/ict-backtest-scorecard.json` (produced by nightly `scripts/ict_backtest_aggregator.py`)

### 5.4 Grade contribution rules
- **Standalone A-grade from ICT alone:** NEVER. ICT concept + at least 2 non-ICT confluence detectors required.
- **B/C grade w/ ICT features:** allowed if backtested + validated concepts stack ≥ 2.
- **Regime gating:** ICT concepts only fire when regime composite (HMM + Hurst + GEX + RV/IV) matches concept's tested regime.

---

## 6. What NOT to Backtest (and why)

- **All post-hoc ICT terminology w/o mechanical definition:** MMBM/MMSM, Judas Swing "spirit", "Institutional Order Flow" as an aggregate concept. These aren't detectors — they're narratives. If we can't write a deterministic detection rule, backtest is meaningless.
- **Multi-stage sequences w/o strict labeling (except CISD which is already labeled):** Full "IPDA algorithmic" model — too many degrees of freedom, high overfitting risk.
- **Anything requiring subjective HTF bias determination:** if "daily bias" requires human judgment, quantify or skip.
- **"Sponsored candle" and vague quality descriptors:** need mechanical threshold or skip.

---

## 7. Codex Backtest Implementation Handoff

See separate file: `CODEx_CLAUDE_COLLAB/CODEX_PROMPT_ICT_BACKTEST_2026-08-23.md`

Summary of work:
1. Build `scripts/ict_backtest_engine.py` — parameterized backtest driver reading `research/ict_backtest_specs.json`
2. Build `scripts/ict_backtest_aggregator.py` — nightly rollup → `ict-backtest-scorecard.json`
3. Build `frontend/src/components/detection/ICTScorecardTab.tsx` — dashboard panel
4. Run all 10 §4 backtests in sequence
5. Update `research/pattern_taxonomy.json` — flip `governance_status` based on backtest outcomes
6. Register Windows Task Scheduler job for nightly aggregation
7. Tests + verification per §Test Suite in Codex prompt

**Non-negotiables preserved:** `execution_enabled=false`, `can_submit_orders=false`, no bot bodies edited, `execution_gate_audit.py` at 0 issues.

---

## 8. Key Sources

- Lo, Mamaysky, Wang (2000) *Foundations of Technical Analysis*, Journal of Finance 55(4), DOI 10.1111/0022-1082.00265
- Aronson (2006) *Evidence-Based Technical Analysis*, Wiley — cited for data-snooping bias correction
- Bajgrowicz & Scaillet (2012) *Technical trading revisited*, JFE — showed most technical edges disappear after multiple-testing correction
- Osipovich (OSF preprint) *A study to assess the validity of Michael Joe Huddleston's ICT Power Of 3*, https://ideas.repec.org/p/osf/osfxxx/7yw86.html
- Phidias Prop Firm critique: https://phidiaspropfirm.com/education/is-ict-legit
- Volity.io ICT concepts guide: https://volity.io/forex/inner-circle-trader-ict/
- ICTFVG GitHub reference: https://github.com/tickets2themoon/ICTFVG
- Grimes, *Art & Science of Technical Analysis* (2012) — for swing definition + ATR filter
- Al Brooks, *Trading Price Action: Trends* (2012) — for structural break definitions

---

## 9. Final Recommendation to Kenny

**Do:**
1. Continue using shipped ICT vocabulary as DESCRIPTIVE layer on dashboard (already done)
2. Fund Codex to run §4 top-10 backtests in Phase 2 work
3. Reject any concept that fails backtest gate
4. Never let a single ICT concept auto-execute a trade — always require 2+ confluence detectors + regime gate
5. Watch Monday first-live-signal cycle from frozen Strategy 1 (MES ORB) + Strategy 3 (MES reopen) — those are your actual A/B test of grader efficacy

**Do NOT:**
1. Believe any "99% win rate" ICT marketing (all fabricated)
2. Add more ICT concepts to dashboard without backtest evidence
3. Size positions based on ICT grade alone
4. Skip the OOS holdout in backtests
5. Confuse Michael Huddleston's YouTube subscriber count w/ evidence of edge

**Timeline:**
- Codex runs top-3 backtests (Kill Zone, FVG Fill Probability, Judas Swing) in ~1 week
- Remaining 7 backtests in ~2-3 weeks
- Dashboard ICT Scorecard tab live w/in 1 week
- Kenny reviews scorecard weekly, prunes rejected concepts

---

**END OF DEEP DIVE. Next: Codex backtest handoff prompt.**
