# Claude Code Handoff: SPY Research Findings → Build Spec

Date: 2026-07-17 CT
Author: Claude Code
Repo: C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading

## What This Is

Kenny ran multi-source research (academic papers, social media, broker data) on how
profitable SPY/SPX traders actually operate. The findings directly map to four build
targets. This handoff converts the research into exact implementation specs.

Do not change anything that is currently working. The current ORB breakout-retest
paper execution is correct and should remain untouched. Build around it.

---

## Research Summary (Key Points Only)

### What the evidence actually says

**Break-and-retest is the strongest research-backed signal.**
A 2017–2024 QQQ 1-minute study found retest timing had the strongest association with
continuation. Large pre-retest extensions reduced continuation probability. This supports
the 1.5× ORB extension block already installed and confirms: fresh controlled retest >
extended-then-retest.
Source: SSRN retest study (exploratory, not peer-reviewed — use to strengthen telemetry
and ranking, not as an unconditional hard gate).

**ORB has real academic backing.**
SPY intraday momentum (2007–early 2024): 19.6% annualized return, 1.33 Sharpe from
abnormal demand/supply signals with dynamic trailing stops. This was underlying SPY,
not 0DTE contracts. The underlying edge is real. Options amplify it — for better and worse.

**Social consensus is consistent across platforms.**
Repeatedly cited: 5/15/30-min ORBs, candle-close confirmation (never wick-only), retest
and hold, PDH/PDL, VWAP, volume, avoiding late entries. One specific discussion: 10-min
PDH/PDL break-and-retest. Another: ORB + VWAP + volume as the three primary tools.

**Afternoon is different territory.**
Theta + lower volume punish slow afternoon moves. Afternoon entries only defensible on:
- Exceptional trending day (trend has not broken down)
- Confirmed failed-extension reversal (not chasing continuation)
Normal afternoon continuation trades underperform. Our noon CALL loss on 2026-07-17 is
a textbook example.

**GEX is advisory only, not a directional oracle.**
Cboe estimates net 0DTE market-maker hedging at ~0.2% of SPX daily liquidity. GEX levels
improve context. They cannot reliably predict direction alone. Keep advisory.

**Fixed targets bank wins but miss runners.**
Dynamic trailing stops have stronger long-run evidence. Current bot has ratchet at +40%
with tightening floor — directionally correct. The open question is whether a structural
trail (behind VWAP, last pullback, or last 5-min bar close) outperforms the current
percentage ratchet. This is a shadow comparison question, not a change today.

### What the bot already has (do not duplicate)
- Fresh 5-min ORB breakout-retest detection
- 15-min ORB challenger
- PDH/PDL and extension-reversal challengers
- VWAP, EMA, breadth, expected-move, ATR, volume, VIX, quote-quality telemetry
- Runner ratchet, stop-loss, path telemetry, missed-trade analysis
- Shadow lifecycle capacity per strategy

### The four missing competitive jumps (build these, in order)

1. Point-in-time day-type router — continuation vs reversal
2. Retest quality scoring — timing, max pre-retest excursion, hold quality
3. Shadow exit tournament — fixed target vs current ratchet vs structural trail
4. Contract ranking — delta + spread + quote age + expected-move room + premium expansion

---

## BUILD 1: Day-Type Router (Highest Priority)

### Why

The July 17 loss was caused by a continuation entry on what turned out to be a
failed-extension reversal day. The bot had no mechanism to route to the correct
strategy for the day type. This is the strategic gap that costs the most.

The academic SPY intraday momentum paper additionally shows the first 30 minutes
can predict the final 30 minutes — supporting explicit opening-state classification.

### What to build

**File:** `strategies/flip_day_type_router.py` (new file)
**Called by:** `flip_bot.py` premarket scan and intraday entry selection

**Inputs (point-in-time, no lookahead):**
```python
@dataclass
class DayTypeSignals:
    overnight_futures_gap_pct: float      # (SPY open - prior close) / prior close
    econ_calendar_high_impact: bool       # FOMC, CPI, NFP, major earnings in SPY index
    prior_session_tick_range: tuple       # (tick_low, tick_high) from prior session
    spy_vs_vwap_at_930: float             # SPY open relative to VWAP at first bar
    orb_range_pct: float                  # ORB range as % of SPY price (5-min)
    adx_5min: float                       # ADX on 5-min at 10:00 ET
    vix_current: float
```

**Output:**
```python
@dataclass
class DayTypeResult:
    day_type: Literal["trend", "range", "failed_extension", "unknown"]
    trend_probability: float              # 0.0 to 1.0
    reversal_probability: float           # 0.0 to 1.0
    confidence: Literal["high", "medium", "low"]
    signals_supporting: list[str]         # human-readable list of signals that fired
    signals_conflicting: list[str]
    recommended_strategy: Literal["orb_continuation", "orb_extension_reversal", "flat", "observe"]
    classification_time_et: str           # ISO timestamp
```

**Classification rules:**

Trend day (high confidence) — requires 3+ of:
- overnight_futures_gap_pct > 0.5% (absolute value)
- econ_calendar_high_impact = True
- adx_5min > 25 at 10:00 ET
- orb_range_pct > 0.4% (large opening range)
- spy_vs_vwap_at_930: gap open well above or below VWAP

Failed-extension day (high confidence) — requires:
- SPY extended ≥ 1.5× ORB range beyond ORB high/low
- Extension stalled (price trading below extension peak for 2+ candles)
- First lower high formed (for long-side extension)
- VWAP below current price (for long-side extension reversal)
This matches the July 17 setup exactly.

Range day — requires:
- No gap > 0.3%
- adx_5min < 20
- orb_range_pct < 0.25%
- TICK staying between -400 and +400 through first hour

Unknown — default when signals conflict. Recommended strategy: observe.

**Strategy routing:**

| Day Type | Primary Strategy | Fallback |
|---|---|---|
| trend | orb_continuation | flat if no valid retest |
| range | flat or noise_area_vwap | — |
| failed_extension | orb_extension_reversal | flat |
| unknown | observe | flat |

**Integration points:**
- Run at 10:00 ET (after first 30 minutes of price discovery)
- Update once at 11:30 ET if initial classification was `unknown` or `low` confidence
- Log to `flip-decisions.jsonl` with field `day_type_classification`
- `flip_bot.py` `run_entry()` reads day_type_result before strategy selection
- Do NOT let day_type_router veto an existing position — only gates new entries

**Tests required:**
- Trend day signals → trend classification
- Failed extension signals → failed_extension classification
- Conflicting signals → unknown classification with observe recommendation
- Router correctly routes to orb_extension_reversal on failed_extension day
- Router does not affect open position management

---

## BUILD 2: Retest Quality Scorer

### Why

The QQQ study confirms: retest timing and pre-retest extension size are the two
strongest predictors of continuation probability. Currently we track retest validity
(fresh/stale). We do not score retest quality within the valid range.

### What to build

**Add to:** `strategies/flip_bot.py` ORB retest evaluation block (near line 588)
**New dataclass:**

```python
@dataclass
class RetestQualityScore:
    raw_score: float              # 0.0 to 10.0
    grade: Literal["A", "B", "C", "rejected"]
    pre_retest_extension_pct: float    # how far price ran before retest (as % of ORB range)
    minutes_since_breakout: int
    candles_at_level: int              # how many candles tested the level
    volume_on_test_vs_breakout: float  # ratio: test volume / breakout volume
    tick_at_touch: int                 # NYSE TICK reading at retest candle (if available)
    vwap_aligned: bool
    ema_aligned: bool
    details: dict[str, float]          # all component scores for telemetry
```

**Scoring components (each 0–2 points, max 10):**

| Component | 2 pts | 1 pt | 0 pts |
|---|---|---|---|
| Pre-retest extension | < 0.8× ORB range | 0.8–1.5× | > 1.5× |
| Time since breakout | < 8 min | 8–20 min | > 20 min |
| Volume on test | < 60% of breakout vol | 60–90% | > 90% |
| VWAP alignment | aligned | neutral | opposed |
| EMA alignment | aligned | neutral | opposed |

**Grades:**
- A: score ≥ 7.5 → execute (paper)
- B: score 4.5–7.4 → shadow only
- C: score < 4.5 → reject, log reason

**Log fields to add to `flip-decisions.jsonl`:**
```json
{
  "retest_quality_score": 8.2,
  "retest_grade": "A",
  "pre_retest_extension_pct": 0.6,
  "minutes_since_breakout": 5,
  "retest_volume_ratio": 0.45
}
```

**Important:** Do not make A-grade required immediately. Shadow both A and B,
execute only A, for the first 30 entries. Then compare outcomes by grade to
validate the thresholds before enforcing.

---

## BUILD 3: Shadow Exit Tournament

### Why

Current ratchet: +40% protection arms, floor tightens as gains increase.
Research shows dynamic structural trailing has stronger long-run evidence.
Question: does our ratchet or a structural trail capture more P&L on winners?
This is a shadow comparison question. Do not change live execution.

### What to build

**Add to:** `strategies/flip_shadow_setup_challengers.py`

For each paper execution that enters a position, the shadow exit tournament records
three parallel hypothetical exit paths:

**Path A: Current ratchet** (what the bot actually does — copy the exact logic)
**Path B: Structural trail — VWAP stop**
- After +20% gain: trail stop to VWAP at time of trailing
- Update every 5-min candle: if SPY crosses VWAP against position, record exit
**Path C: Last 5-min bar close trail**
- After +20% gain: trail stop to prior 5-min candle close
- Update every 5-min close

Record for each path:
```json
{
  "path": "structural_vwap_trail",
  "hypothetical_exit_pct": 82.4,
  "hypothetical_exit_time": "13:45",
  "exit_trigger": "vwap_cross",
  "actual_outcome_comparison": "+$47 vs current ratchet +$31"
}
```

**Comparison report:** After 20+ completed trades with all three paths, generate:
- Average exit % by path
- Median exit % by path
- % of trades where each path outperformed
- Largest winner by path (does the trail capture the big moves?)

Do not change execution until the tournament has 20+ completed comparisons
AND one path shows statistically meaningful outperformance.

---

## BUILD 4: Contract Ranking Score

### Why

Current selection: ATM or single strike. Research and shadow data both show
contract selection materially affects outcomes. Need a systematic ranking.

### What to build

**Add to:** `strategies/flip_bot.py` contract selection block

**Contract candidate evaluation:**

For each candidate strike, compute:

```python
@dataclass
class ContractRank:
    strike: float
    right: str
    delta: float
    spread_pct: float          # (ask - bid) / midpoint
    quote_age_seconds: int
    expected_move_room: float  # distance from strike to 1σ expected move
    premium_expansion_pct: float  # how much premium already expanded from open
    composite_score: float     # 0–100
    rank: int                  # 1 = best
    disqualified: bool
    disqualify_reason: str
```

**Scoring (100 points total):**

| Criterion | Weight | Best | Worst |
|---|---|---|---|
| Delta (0DTE buy) | 25 pts | 0.45–0.55 ATM | < 0.20 or > 0.85 |
| Spread % | 25 pts | < 3% | > 15% |
| Quote age | 20 pts | < 5 seconds | > 30 seconds |
| Expected move room | 15 pts | 0.5–1.5σ from strike | beyond 2σ |
| Premium expansion | 15 pts | < 30% expanded | > 100% expanded |

**Disqualification (automatic reject regardless of score):**
- spread_pct > 20%
- quote_age_seconds > 60
- delta < 0.10 (too far OTM — shadow data confirms OTM-1 and OTM-2 underperform)
- premium already expanded > 150% from open (chasing an extended premium)

**Current shadow challenger context:**
- ATM: -8.77% avg (old mixed lifecycles — not SPY ORB specific)
- OTM-1: -9.63% avg — disqualify
- OTM-2: -17.64% avg — disqualify
- ITM 0.60-delta: challenger running, no ORB-specific data yet

The contract ranker formalizes what the shadow data already suggests. ATM scores highest
in most conditions. ITM 0.60-delta scores higher when premium is already expanded or
spread is tight ITM.

---

## BUILD 5: Staleness Alarms (Small, High Value)

### Why

Identified gap: no alarm when a strategy has zero completed lifecycles or no execution
opportunities for several sessions. A broken setup builder can silently produce zero
entries and the bot looks healthy on the outside.

### What to build

**Add to:** `scripts/signal_stack_health_report.py`

```python
STALENESS_THRESHOLDS = {
    "orb_continuation": {"max_days_without_entry": 5, "max_days_without_close": 10},
    "noise_area_vwap": {"max_days_without_entry": 7, "max_days_without_close": 14},
    "orb_extension_reversal": {"max_days_without_entry": 7},
    "paper_challenger": {"max_days_without_entry": 5},
}
```

Health report adds:
```json
{
  "strategy_staleness": {
    "orb_continuation": {"days_since_last_entry": 2, "alert": false},
    "orb_extension_reversal": {"days_since_last_entry": 0, "note": "new strategy"},
    "noise_area_vwap": {"days_since_last_entry": 1, "alert": false}
  }
}
```

If any strategy exceeds threshold: `ALERT` in health report, log reason for review.
Do not auto-disable. Alert only — human investigates.

---

## WHAT NOT TO CHANGE

- Current ORB breakout-retest paper execution logic — do not touch
- 1.5× extension hard block — keep, research confirms this is correct
- Safety gates: kill switch, daily loss, spread cap, reconciliation, position limits
- Lesson ledger contradiction filter and counterfactual requirement
- GEX, social signals, AI forecasts remain advisory only (Cboe confirms GEX ≠ directional oracle)
- No live execution changes

---

## VERIFICATION AFTER EACH BUILD

```powershell
cd C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading

# After Build 1 (day-type router)
python -m pytest agent/tests/test_flip_day_type_router.py -v
python -m pytest agent/tests/test_flip_bot_safety.py -q

# After Build 2 (retest quality)
python -m pytest agent/tests/test_flip_bot_safety.py agent/tests/test_spy_noise_area.py -q

# After all builds
python scripts/execution_gate_audit.py --print
python scripts/risk_fail_closed_proof.py --print
python -m pytest agent/tests -k 'flip or spy_noise_area' -q
# Expected: 169+ passed
```

---

## PRIORITY ORDER

1. Day-type router (Build 1) — routes the bot to correct strategy for each day
2. Retest quality scorer (Build 2) — raises entry bar, reduces bad entries
3. Staleness alarms (Build 5) — small, quick, high visibility value
4. Contract ranking (Build 4) — formalizes what shadow data already shows
5. Shadow exit tournament (Build 3) — longer to accumulate data, start running now

Build 1 + 2 are the July 17 fix generalized. Build 3 is the long-term exit research.
Build 4 formalizes existing evidence. Build 5 is operational safety.

---

## ONE LINE PER BUILD FOR CLARITY

Build 1: Tell the bot what kind of day it is before it decides what to trade.
Build 2: Score every retest so A-quality entries execute and B/C stay in shadow.
Build 3: Race three exit strategies in shadow to find which captures the most P&L.
Build 4: Pick the best contract on every entry, not just ATM by default.
Build 5: Alert when any strategy goes silent for too long.
