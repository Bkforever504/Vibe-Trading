# Claude Code Handoff: Full System Improvement Brief

Date: 2026-07-17 CT
Author: Claude Code
Repo: C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading
Audience: Next AI session (Claude Opus / Fable 5 or equivalent)

This is a go-above-and-beyond brief. Read every section. Do not start implementing until
you understand the full system. Then attack the highest-leverage improvements first.

---

## WHO KENNY IS AND WHAT THIS IS

Kenny is building an automated trading system from scratch. Starting capital: ~$1,000.
Goal: consistent income from options/futures trading via bots, not discretionary trading.

He is not a professional trader. He is a builder who learns fast, takes feedback seriously,
and has been executing disciplined evidence-first bot development for months. He does not
want to lose money. He does want the bots to be smarter than anything he could build alone.

The system has multiple concurrent strategies running in paper/shadow mode, a learning loop,
and strict safety gates before any live capital is deployed.

---

## SYSTEM ARCHITECTURE OVERVIEW

```
Vibe-Trading/
├── strategies/           # Bot logic
│   ├── flip_bot.py       # PRIMARY: SPY 0DTE options bot (Alpaca paper)
│   ├── spy_noise_area.py # SPY Noise Area + VWAP model (14-session deterministic)
│   ├── flip_shadow_setup_challengers.py  # Forward shadow learner
│   ├── kalshi_weather_bot.py             # Kalshi temperature markets (paper)
│   ├── kalshi_weather_execution.py       # DORMANT: authenticated order adapter
│   ├── polymarket_weather_bot.py         # US-geoblocked, paper research only
│   ├── kalshi_profile_scraper.py         # Copy-trader diligence
│   └── shadow_pullback_signal.py         # NQ/MNQ futures shadow scanner
│
├── scripts/              # Reports, readiness gates, scheduled tasks
│   ├── flip_bot_learning_report.py       # Lesson extraction from closed trades
│   ├── loop_closure_report.py            # Cause/hypothesis/counterfactual tracker
│   ├── flip_exit_quality_report.py       # Exit taxonomy analysis
│   ├── flip_execution_challenger_report.py # ATM vs ITM vs OTM comparison
│   ├── elite_bot_readiness_scorecard.py  # Live readiness gate
│   ├── signal_stack_health_report.py     # System health (55/55 schedules)
│   ├── execution_gate_audit.py           # Safety gate audit (100 signals, 0 issues)
│   ├── risk_fail_closed_proof.py         # Reconciliation proof (4/4)
│   ├── kalshi_weather_readiness.py       # Weather bot live gate
│   └── generate_dashboard.py            # HTML dashboard
│
├── agent/tests/          # 3,894 passing tests (7 known Futu/mootdx isolation failures)
├── research/             # Strategy packets, signal registry, broker research
│   ├── signal_registry.json              # Pre-registered setups before evaluation
│   ├── strategy_adapter_safety.py        # AST checker blocks unsafe adapter code
│   └── broker_selection_flip_bot_2026-07-16.md
│
├── data/
│   └── trade_lesson_ledger.jsonl         # Canonical lesson ledger (no duplicates)
│
└── CODEx_CLAUDE_COLLAB/  # All handoffs, task queue, decisions
    ├── TASK_QUEUE.md
    └── [all handoff files]
```

---

## ACTIVE STRATEGIES — CURRENT STATE

### 1. Flip Bot — SPY 0DTE ORB + Noise Area (PRIMARY)

**File:** `strategies/flip_bot.py`
**Broker:** Alpaca paper (ALPACA_PAPER=true enforced)
**Status:** Active. Paper execution running. 11 post-hardening trades.

**Current baseline:** $2,451 net profit, 72.7% win rate, 6.19 profit factor, $472 max drawdown.

**What it does:**
- Monitors every 15 minutes (corrected from one-shot 9:35 scan)
- ORB: defines 9:30–9:35 opening range, waits for breakout + retest + hold + freshness
- Noise Area: 14-session band model, VWAP confirmation, fallback when ORB has no valid candidate
- Entry priority: ORB first, Noise Area only when no ORB candidate exists

**Critical fixes from this week:**
- `retest_stale` now correctly blocks stale continuation entries
- 1.5× ORB extension hard-blocks late chases without fresh retest
- Trend signals require completed candles + genuine VWAP/50EMA pullback touch
- ORB state has authority over the trend lane (not just logged)
- 3% slippage cap added

**Today's specific failure (2026-07-17):**
- Bot bought 747 CALL at $1.32 at 12:00 ET
- ORB said `retest_stale`, consensus said `stand_aside` — both correct
- Score system gave 9/10 bullish and overrode both signals
- SPY was 2.64× ORB width above ORB high — a momentum chase, not an ORB setup
- Contract stopped at $0.725, -$119 loss
- The 746 PUT (correct direction after reversal) went $0.90 → $4.65
- Fixes installed, same entry now correctly rejected as `trend_orb_extension_without_fresh_retest`

**Paper challengers (1-contract cap each):**
```
FLIP_PAPER_CHALLENGER_SYMBOLS = "RIVN,AAPL,NVDA,QQQ"
```
IWM removed — single +82.8% outlier masked -16.48% average.

**Contract selection research in progress:**
- ATM: -8.77% avg (old mixed lifecycles — not SPY-specific verdict)
- OTM-1: -9.63% avg
- OTM-2: -17.64% avg
- ITM 0.60-delta: challenger running, no data yet
- Verdict: avoid OTM proven. ATM current execution. ITM 0.60-delta to prove.

**Shadow reversal learner:**
- `flip_shadow_setup_challengers.py` line 215
- Today's PUT reversal identified: entry proxy 746.57, stop 747.451, target 742.62
- Target reached 3:15 ET, stop survived at 747.27
- Registered in `research/signal_registry.json` line 2021 BEFORE evaluation
- Shadow-only until 15–20 underlying replays accumulate

**Learning loop (just wired this week):**
- 19:15 postmortem → 19:19 learning report → 19:59 loop closure → 20:03 readiness
- `data/trade_lesson_ledger.jsonl`: 2 open lessons, 0 auto-behavior-changes
- Contradiction gate: bad lessons rejected before persisting
- Counterfactual required before any lesson closes and changes behavior
- Health monitoring: `signal_stack_health_report.py` line 207

**Scheduled tasks:** 55/55 aligned and Ready.

---

### 2. Kalshi Weather Bot (paper, 13 cities)

**File:** `strategies/kalshi_weather_bot.py`
**Status:** Running every 15 minutes. 0 finalized closures. 0/200 needed for promotion.

**What it does:**
- Scans 13 daily-high temperature series (KXHIGH: NYC, Chicago, Miami, Austin, Boston,
  Denver, Atlanta, Minneapolis, Phoenix, Dallas, Houston, Seattle, OKC)
- 3-model ensemble: GFS GEFS (31 members) + ECMWF IFS (51 members) + ICON
- Requires all 3 families + 20 total members
- Minimum 10% fee-adjusted edge in every model family
- Max family probability disagreement: 0.20
- Selects 1 best bucket per city-day (avoids counting correlated ladder buckets)
- Paper only: 1 contract, max $15 daily aggregate paper risk
- Settlement from exact NWS ASOS station coordinates (not city center — ~1°F offset)

**Live gate:** 200 independent closures, 14 target dates, profit factor ≥1.25,
Brier skill > market, drawdown ≤25% risk, positive net P&L. Human approval required.

**Authenticated adapter:** `strategies/kalshi_weather_execution.py` — DORMANT.
Not imported, not scheduled. Requires KALSHI_ENABLE_LIVE_TRADING=true + explicit ack.

---

### 3. NQ/MNQ Futures Shadow Scanner

**File:** `strategies/shadow_pullback_signal.py`
**Status:** Running weekdays 9:30–14:30 CT (10:30–15:30 ET), every 60 min.
**Gate:** 30+ resolved signals before Topstep Combine spend.

**Best backtest config (not combine-ready):**
- `st80 tol8 partial gap VIX 16-24`
- Train: 7 trades, 85.7% WR, exp $31/trade
- OOS: 3 trades, 100% WR — too small to validate

**Key finding:** Backtester uses 1h bars; real traders use 1m/5m bars with DOM/order flow.
The gap between model and reality is real. 1h approximation understates edge AND errors.

---

### 4. Kalshi Copy-Trader Diligence

**File:** `strategies/kalshi_profile_scraper.py`
**Status:** Active. 32 tests passing.

**Key finding:** Top Kalshi leaderboard traders systematically hide position history.
Serious traders opt out of public profiles. Only weak traders are visible.
Current candidates: both in "review only" state (hidden or poor metrics).

**Accepted evidence sources:** public_wallet, exported_history, public_profile with
visible closed-position P&L. Blocked: leaderboard-only, screenshots, viral P&L posts.

---

## BROKER DECISION (DO NOT CHANGE WITHOUT EVIDENCE)

**File:** `CODEx_CLAUDE_COLLAB/CODEX_HANDOFF_2026-07-16_FLIP_BOT_BROKER_SELECTION.md`

Current paper/dev: Alpaca (keep, already integrated)
First funded ($1,000) priority order:
1. Webull OpenAPI — if API approval granted and real-time options data confirmed
2. Tradier Pro — $10/month, commission-free options, clean REST API
3. Tradier Lite — $0/month, $0.35/contract

Alpaca live: blocked by $99/month OPRA data plan (9.9% of $1K account before any trade).
IBKR: correct long-term choice, too complex for first $1K launch.
Robinhood: MCP connected but exposes zero usable tools — blocked until read-only works.

**Critical Webull note:** Credential rotation required (default 1-day, max 7-day key validity).
Auto-refresh or alert must be built before any live use. A failed 0DTE entry from expired
credentials at 9:35 AM is a real failure mode.

---

## WHAT IS ACTUALLY BROKEN OR INCOMPLETE

### HIGH PRIORITY

**1. Failed-Breakout Reversal Setup — Missing**
The biggest gap exposed 2026-07-17. SPY extended to 2.64× ORB width, reversed sharply.
The bot had no reversal setup, so it either chased the wrong direction or stayed flat.
The reversal learner is now shadow-only. Need:
- Detect ORB extension losing momentum (price stalls near 1.5–2× ORB extension)
- Reject stale continuation entries (already done)
- Evaluate PUT after confirmed reversal evidence (first lower high, VWAP break)
- NOT a lottery PUT entry — underlying reversal with controlled risk

**2. Shadow Outcome Join Missing**
`scripts/view_shadow_signals.py` shows signals and outcomes as separate rows.
Needs: `load_outcomes()` → join by `signal_id = created_at` → merged display.
`print_summary()` must show forward-test win rate from resolved signals only.

**3. 20+ ORB/Noise Area paths needed before any promotion**
Currently: 11 post-hardening trades total. Need 20+ per setup type:
- `0dte` with `orb_entry_pattern=breakout_retest`
- `noise_area_vwap`
- `15min_orb_shadow`
- `failed_level_sweep_shadow`

**4. Webull adapter not built**
Broker decision made. Adapter abstraction not implemented.
Required interface before any funded broker:
- quote snapshot
- option chain lookup
- order preview/dry run
- single-leg buy-to-open
- close position
- account buying power
- positions/orders reconciliation

**5. Day-type classifier not premarket**
Trend day vs range day classification currently implicit.
Should be a scored premarket signal (runs 9:15 AM ET):
- Inputs: overnight futures gap %, economic calendar events, TICK range prior session
- Output: trend_day_probability (0–1), logged daily
- Gates aggressive strategies (don't run Noise Area on confirmed trend days)

### MEDIUM PRIORITY

**6. ITM 0.60-delta vs ATM evidence gap**
Challenger telemetry running but 0 data points specifically from SPY ORB setups.
Need 20 ORB-specific observations before comparing ATM vs ITM execution quality.

**7. NVDA -$67 lesson — counterfactual pending**
Put-spread directional failure on 2026-07-17. Three possible causes: wrong direction,
wrong spread width, wrong stop timing. Ledger requires counterfactual before behavior change.
Do not change NVDA spread logic until the cause is isolated.

**8. SPY time-bucket gate not ready**
Research shows 12:00 ET best time bucket (+24.21% expectancy, n=19).
n=19 is below the 30+ sample threshold required to gate entries by time.
Do not add a time-bucket filter yet. Collect more data first.

**9. 7 Futu/Mootdx test isolation failures**
These fail in full suite due to mock pollution from test-order dependency.
Both files pass independently (50/50). Not blocking anything, but should be fixed
cleanly rather than left as permanent noise in the full suite output.

---

## WHAT GOES ABOVE AND BEYOND

This section is for the ambitious build. These are not required today but are the
difference between a basic bot and a professional-grade system.

### A. Real-Time Market Intelligence Layer

The bot currently makes decisions from OHLC bars and Alpaca snapshots.
What professional traders actually use:
- **NYSE TICK** — market-wide order flow sentiment. TICK > +800 = institutional buying surge.
  TICK < -800 = institutional selling surge. Bot should request NYSE TICK from data provider
  and incorporate into ORB trend-day classification and entry confirmation.
- **GEX (Gamma Exposure) levels** — where market makers must hedge as SPY moves.
  High-GEX strikes create magnetic price behavior. Tools: SpotGamma, SqueezeMetrics, or
  estimate from options chain open interest. These are mechanical support/resistance levels
  invisible to standard charting. Bot should respect GEX walls as resistance/support.
- **VIX term structure** — VIX vs VIX3M vs VIX6M. Contango = calm, backwardation = fear.
  Contango favors credit selling; backwardation means heightened reversal risk for 0DTE buyers.

### B. ORB Retest Quality Scoring

Currently: retest is binary (valid/stale). Better:
Score each retest on:
- Time since breakout (fresher = better)
- Distance from ORB level (closer = better)
- Volume on the test candle (lower = better — exhaustion test)
- TICK reading at touch (positive = bull support, negative = bear rejection)
- Number of times ORB level was tested (first test strongest)
Composite score 0–10. Only execute A-quality retests (≥7). Shadow B-quality (4–6).
Log C-quality (< 4) as rejected with reason.

### C. Adaptive Contract Selection

Research says ATM for 0DTE ORB. But optimal strike varies with:
- VIX level (high VIX = wide spreads favor ITM; low VIX = ATM tighter)
- Distance from ORB breakout (early retest = ATM; late confirmation = ITM for more intrinsic)
- Time of day (9:35–11:00 AM: ATM fine; 11:00 AM+: ITM preferred — less theta risk)
Build a strike selection policy that responds to these inputs rather than always ATM.
Shadow each choice before executing.

### D. Lesson Ledger → Hypothesis Testing Pipeline

Current lesson ledger: records lessons, requires counterfactual, blocks auto-change.
Next level: when a counterfactual trial has 10+ forward examples, automatically
generate a statistical test (win rate comparison, payoff ratio comparison) and produce
a recommendation with confidence interval. Human still approves, but now has data-backed
recommendation rather than just a hypothesis.

### E. Failed-Breakout Reversal Setup (Full Implementation)

This is the biggest alpha gap identified today. Full specification:

**Entry conditions:**
1. SPY breaks ORB high/low (confirmed breakout)
2. Extension reaches 1.5–2.5× ORB width
3. SPY forms a lower high (for long breakout → reversal to puts) or higher low
4. First candle closes back inside the 1.5× extension zone
5. VWAP confirms: long-side reversal requires close below VWAP
6. Volume on reversal candle > volume on extension candle (distribution signal)

**Strike selection for reversal:**
- ATM at moment of reversal confirmation (not at the peak — that's lottery timing)
- One contract only in paper phase

**Exit:**
- Profit target: 75% of remaining intraday range to ORB level
- Stop: re-break of the reversal confirmation candle high
- Time stop: 3:30 PM ET

**Shadow requirement:** 15 underlying replays before paper execution.
**Paper requirement:** 20 paper trades before any promotion discussion.

### F. Multi-Timeframe Confirmation

Current ORB is single-timeframe (5-min). Professional edge adds:
- 15-min chart: is this a 15-min ORB alignment day? If 5-min and 15-min ORB agree on direction → higher quality.
- Daily chart: is SPY above/below key daily levels (prior day high/low, weekly VWAP)?
  Setups aligned with daily structure outperform counter-structure setups significantly.
- Pre-market: pre-market high/low are key intraday S/R. ORB breakout toward pre-market
  high has higher hit rate than breakout into open space.

### G. Weather Bot Calibration Tracker

Currently 0 closed positions. When closures start:
- Brier score by city, by lead time bucket, by model family
- Near-miss tracker (5–9.9% edge vs 10%+ edge cohort comparison)
- Forecast vintage telemetry (model run age and lead time without lookahead)
- Reliability curves: does the model's stated probability match actual frequency?
A model saying "70% chance above 95°F" should be right 70% of the time. Track this.

### H. Broker Adapter Abstraction Layer

Build once, plug in any broker:
```python
class BrokerAdapter(ABC):
    def get_quote(self, symbol: str, expiry: date, strike: float, right: str) -> OptionQuote
    def get_chain(self, symbol: str, expiry: date) -> List[OptionQuote]
    def preview_order(self, order: OrderRequest) -> OrderPreview
    def submit_order(self, order: OrderRequest) -> OrderResult
    def get_position(self, symbol: str) -> Optional[Position]
    def get_positions(self) -> List[Position]
    def get_buying_power(self) -> float
    def reconcile(self) -> ReconciliationResult
```

Implement:
1. `AlpacaBrokerAdapter` — already effectively exists, formalize it
2. `WebullBrokerAdapter` — next adapter to build (pending API approval)
3. `TradierBrokerAdapter` — parallel/fallback

Each adapter: paper mode, sandbox mode, live mode. Each mode has explicit flag requirement.
Credential rotation handler for Webull (1-day/7-day key validity).

### I. Live Readiness Dashboard

HTML dashboard (`scripts/generate_dashboard.py`) exists but is basic.
Upgrade to show:
- Per-strategy evidence state (paper trades completed, win rate, profit factor, max drawdown)
- Gate status checklist: which requirements have been met, which remain
- Lesson ledger status: open lessons, pending counterfactuals
- Health indicators: schedule alignment, last audit result, staleness alerts
- Broker readiness: which adapters are built/tested/approved
- Capital adequacy: at current strike prices and 2% sizing, how many trades until ruin?

---

## CRITICAL SAFETY INVARIANTS — NEVER WEAKEN

These are documented but worth repeating explicitly:

1. `ALPACA_PAPER=true` must be confirmed before any intraday entry scan runs.
2. No recurring intraday execution outside paper mode. Hard block, not soft warning.
3. No advisory module (GEX, social signals, AI forecasts) gets hard-veto authority.
   Only two hard blocks exist: portfolio_kill_switch_active and options_liquidity_blocked.
4. Lesson ledger cannot automatically change live execution or weaken safety gates.
5. No live order submission without: 50+ paper signals + profit factor ≥1.2 + drawdown <15% + human approval.
6. No credit-spread promotion from one good paper result. Distribution required.
7. No Kalshi live execution: 200 independent closures + all readiness criteria + human approval.
8. No copy-trader live: requires public_wallet or exported_history — leaderboard-only blocked.
9. No funded broker switch until: read-only discovery works, real-time quote quality confirmed,
   sandbox order flow tested, reconciliation passes, execution audit passes.
10. Webull credential rotation must be automated before any live use.

---

## VERIFICATION COMMANDS (RUN BEFORE ANY CHANGE, AFTER ANY CHANGE)

```powershell
cd C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading

# Core Flip Bot tests
python -m pytest agent/tests/test_flip_bot_safety.py agent/tests/test_spy_noise_area.py agent/tests/test_flip_noise_area_paper.py -q

# Execution gate
python scripts/execution_gate_audit.py --print
# Expected: passed=True, 100 signals, 0 issues

# Risk proof
python scripts/risk_fail_closed_proof.py --print
# Expected: 4/4 passed

# Health
python scripts/signal_stack_health_report.py --no-write
# Expected: OK=38+ STALE=0 MISSING=0 ERROR=0

# Schedule alignment
Get-ScheduledTask -TaskPath '\VibeTrade\' | Format-Table TaskName,State
# Expected: all Ready

# Full focused suite
python -m pytest agent/tests -k 'flip or spy_noise_area' -q
# Expected: 169 passed
```

---

## RECOMMENDED ATTACK ORDER

Start here. Each item builds on the prior.

1. **Shadow outcome join** (`scripts/view_shadow_signals.py`) — simplest, enables all future analysis
2. **Day-type classifier** (premarket signal, 9:15 AM ET) — gates aggressive strategies correctly
3. **ORB retest quality scorer** (0–10 score, A/B/C grades) — raises entry bar without reducing edge
4. **Failed-breakout reversal setup** (shadow only first, full spec above) — biggest alpha gap
5. **Broker adapter abstraction** (define interface, implement Webull as first adapter)
6. **Webull credential rotation handler** (operational requirement before any live use)
7. **Multi-timeframe confirmation** (15-min + daily structure layer on ORB entries)
8. **ITM 0.60-delta vs ATM comparison** (after 20+ ORB setups accumulate)
9. **Lesson ledger → hypothesis testing pipeline** (statistical test from counterfactual trials)
10. **Live readiness dashboard upgrade** (visibility into all gates simultaneously)

---

## FILES TO READ FIRST (IN THIS ORDER)

1. `CODEx_CLAUDE_COLLAB/TASK_QUEUE.md` — current priority queue
2. `CODEx_CLAUDE_COLLAB/CODEX_HANDOFF_2026-07-16_FLIP_BOT_BROKER_SELECTION.md` — broker decision
3. `CODEx_CLAUDE_COLLAB/CLAUDE_CODE_HANDOFF_2026-07-16_SPY_TRADING_MASTERY_RESEARCH.md` — strategy research
4. `CODEx_CLAUDE_COLLAB/CLAUDE_CODE_HANDOFF_2026-07-16_SPY_NOISE_AREA_INTRADAY_EXECUTION.md` — current build state
5. `CODEx_CLAUDE_COLLAB/CLAUDE_CODE_HANDOFF_2026-07-16_FLIP_PAPER_CHALLENGER_PROMOTION.md` — challenger state
6. `strategies/flip_bot.py` — primary bot (start at line 588 for ORB fix, line 1389 for Noise Area)
7. `strategies/spy_noise_area.py` — Noise Area model
8. `strategies/flip_shadow_setup_challengers.py` — reversal learner (line 215)
9. `scripts/flip_bot_learning_report.py` — lesson extraction (line 224)
10. `scripts/loop_closure_report.py` — loop closure (line 269)
11. `data/trade_lesson_ledger.jsonl` — 2 open lessons

---

## THE NORTH STAR

This system exists to generate consistent, evidence-based trading income for Kenny.
Not lottery tickets. Not one-trade wins. Consistent edge with controlled risk.

Every improvement should make the system:
- More selective (better entry quality, not more trades)
- More self-aware (better learning from every outcome)
- More robust (fails closed on every unexpected condition)
- More transparent (Kenny can always see why any decision was made)

Do not add complexity without clear evidence it improves edge.
Do not soften safety gates to capture more trades.
Do not auto-promote strategies — every promotion requires human eyes on the data.

Go build something excellent.
