# Strategy Comparison Matrix — Strategy 1 vs 2 vs 3

**Date:** 2026-08-22
**Purpose:** Side-by-side comparison of the three highest-conviction strategies so Kenny can allocate attention, capital, and dashboard real estate rationally.

---

## 1. Strategy Slate

| # | Name | Status | File |
|---|---|---|---|
| **1** | MES ORB 09:32 ET VIX-filtered | Frozen 2026-08-22 | `research/FROZEN_STRATEGY_1_2026-08-22.md` |
| **2** | IWM Iron Condor 16-delta 30-45DTE + Bull Put Spread 25-delta 7-14DTE | Already live (paper) since 2026-06 | `strategies/iwm_options_bot.py` + `CLAUDE.md` playbook |
| **3** | MES Reopen 17:00 CT Overnight Drift | Frozen 2026-08-22 | `research/FROZEN_STRATEGY_3_2026-08-22.md` |

---

## 2. Head-to-Head Matrix

| Dimension | Strategy 1 (MES ORB) | Strategy 2 (IWM Options) | Strategy 3 (MES Reopen) |
|---|---|---|---|
| **Instrument** | MES futures | IWM ETF options (also SPY/QQQ/TSLA/NVDA/AAPL/PLTR) | MES futures |
| **Timeframe** | 2m + 5m intraday | Multi-day (7-45 DTE) | 30m ETH overnight |
| **Session** | RTH 09:30–12:00 ET | RTH entry, hold multi-day | ETH 17:00 CT → 08:30 ET |
| **Hold time** | 15 min – 2.5 hrs | 7-45 days | 12-15 hrs overnight |
| **Direction** | Both long/short via breakout | Neutral (IC) + directional (BPS) | Both, biased to RTH-close direction |
| **Win rate target** | ≥ 60% (Chuk 2025: 65.4%) | 75-80% (options theta harvest) | ≥ 55% |
| **Avg R** | 1.8R | ~0.4R per trade but high freq compounds | 1.3R |
| **Trades per week** | 3 (Mon/Wed/Fri only) | 5-15 across 7 symbols | 5 (Mon-Fri ETH sessions) |
| **Risk per trade** | 0.75% equity | 1-2% max loss (spread width – credit) | 0.5% equity |
| **Capital efficiency** | High (futures leverage) | Medium (options premium tied up as buying power) | High (futures leverage) |
| **Overnight gap risk** | None (flat 12:00 ET) | High (multi-day exposure) | High (holds through overnight) |
| **Macro-event vulnerability** | Filtered out (skip macro days) | Vulnerable (multi-day means always in front of something) | Filtered (skip macro tomorrow) |
| **Regime dependency** | VIX 15-25 + trend HMM | VIX 15-40 + PCR + IVR gates | VIX 12-28 + Hurst > 0.52 |
| **Broker requirement** | Futures broker (NinjaTrader, Interactive Brokers, TopstepX) | Options broker (Alpaca paper, Robinhood live) | Futures broker |
| **Minimum account** | $2,500 | $200 (currently running) | $3,000 |
| **Kill trigger** | 5 consecutive losses / DD > 12% | Existing bot's soft-stop logic | 4 consecutive losses / DD > 10% / 2 gap losses ≥ 3R |
| **Time-to-signal from freeze** | 1 trading day (Monday 09:32 ET fires) | Already live | 1 trading day (Monday 17:00 CT fires) |

---

## 3. Portfolio Correlation

- **Strategy 1 ↔ Strategy 3:** Same underlying (MES). Directionally may correlate on trend days but temporally uncorrelated (day vs overnight). Position them as complementary, not additive.
- **Strategy 1 ↔ Strategy 2:** Weak. Different instrument (MES futures vs IWM/SPY options), different holding period. Uncorrelated is good — diversifies portfolio.
- **Strategy 2 ↔ Strategy 3:** Weak. IWM cash vs MES futures overnight. Some macro-day correlation but structural setups differ.

**Portfolio-level risk allocation (recommended split by account risk budget):**
- Strategy 2 (already live, proven paper): 40% of daily risk budget
- Strategy 1 (highest expectancy, cleanest gate): 40%
- Strategy 3 (overnight, needs more evidence): 20%

If daily risk budget is 3% of equity, allocation: S2 = 1.2%, S1 = 1.2%, S3 = 0.6%. Fits within all 3 spec per-trade caps.

---

## 4. Which Strategy Wins on Which Dimension

| Dimension | Winner | Runner-up |
|---|---|---|
| Highest expected R per trade | S1 (1.8R) | S3 (1.3R) |
| Highest win rate | S2 (75-80% theta harvest) | S1 (60-65%) |
| Highest frequency | S2 (multi-symbol, 5-15/wk) | S1/S3 (3-5/wk each) |
| Lowest capital requirement | S2 ($200 min) | S1 ($2.5K min) |
| Lowest overnight risk | S1 (flat by 12:00 ET) | — |
| Cleanest gate rules | S1 (Chuk 2025 externally validated) | S3 (in-sample only, needs OOS) |
| Fastest promotion path | S1 (60 trades × 3/wk = 20 weeks) | S3 (80 trades × 5/wk = 16 weeks) |
| Already producing signal | S2 (live paper since June) | — |
| Most robust to regime shift | S2 (multi-symbol, multi-strategy internal diversification) | S1 (single instrument, single setup) |

---

## 5. Recommended Focus Order

1. **Strategy 2 (existing IWM options bot)** — keep running paper. Formalize as frozen spec (`research/FROZEN_STRATEGY_2_2026-08-22.md` — currently skeleton) to bring under same governance as S1/S3. This work is low-effort (rules already in `iwm_options_bot.py`, just document them).
2. **Strategy 1 (MES ORB)** — highest expected R + externally validated basis. Watch first live signal Monday 09:32 ET. Verify grader emits candidate + graded correctly.
3. **Strategy 3 (MES reopen)** — start shadow immediately. 80-trade gate takes ~16 weeks. Watch first ETH signal Monday 17:00 CT. Accept that this needs more evidence before any promotion talk.

---

## 6. Kill / Deprecate Watch

**S1:** if VIX regime shifts to VIX > 30 for 20+ sessions, entire strategy dormant per §7 kill criteria — VIX regime shift means Chuk 2025's base rate no longer applies.

**S2:** existing bot already has kill logic (6-layer filter). Add per-strategy kill triggers to `iwm_options_bot.py` as part of Strategy 2 formalization.

**S3:** if 2 overnight gaps ≥ 3R hit within 15 sessions, immediate shadow-only halt. Structural regime break (Fed leak, geopolitical shock) invalidates drift assumption.

---

## 7. Dashboard Real Estate Recommendation

**Detection tab → Frozen Strategies section**, cards in this order (top to bottom):
1. **Strategy 2 — IWM Options (LIVE)** — green tag "already producing" + link to bot log
2. **Strategy 1 — MES ORB (WATCH)** — yellow tag "first signal Monday 09:32 ET" + gate progress bar
3. **Strategy 3 — MES Reopen (WATCH ETH)** — yellow tag + "overnight risk" warning icon + gate progress bar

Each card shows:
- Live gate progress (n_trades / target, win rate w/ Wilson band, avg R, Brier skill)
- Last signal timestamp + grade
- Cumulative shadow P&L (if any)
- Days until promotion-eligible

---

## 8. What This Comparison Does NOT Tell You

- **Live edge.** All numbers above are hypothesis / backtest / externally-published. Only shadow data validates.
- **Regime durability.** All three strategies assume 2026 tape stays roughly similar to 2022-2026. Regime shift (e.g., sustained VIX > 35) invalidates all filters simultaneously.
- **Broker slippage.** Backtest slippage assumptions (1-2 ticks) may underestimate real fills, especially S3 ETH.
- **Concurrency.** If S1 and S3 both fire on same MES contract same day (unlikely per session rules), portfolio correlation math becomes non-linear.

---

**Decision required from Kenny:** none right now — this matrix is for allocation clarity. Just watch first signals Monday and adjust after 10 sessions of shadow data.
