# Shared Task Queue

Last updated: 2026-07-19 (MES Databento validation complete — all tested MES families rejected)

---

## THE REAL GATE

**Do not fund or switch the Flip Bot broker until read-only broker discovery, real-time options quote quality, paper/sandbox order flow, reconciliation, and execution audit all pass.**

Current Flip Bot broker baseline:
- Canonical handoff: `CODEx_CLAUDE_COLLAB/CODEX_HANDOFF_2026-07-16_FLIP_BOT_BROKER_SELECTION.md`
- Research mirror: `research/broker_selection_flip_bot_2026-07-16.md`
- First funded venue preference: Webull OpenAPI if approved and quote quality is adequate.
- Fallback: Tradier Pro, then Tradier Lite.
- Alpaca remains the best current paper/development venue, but the USD 99/month real-time data plan is likely too expensive for a USD 1,000 first funded account.
- Robinhood is blocked until its connected MCP exposes usable read-only tools; Robinhood Legend does not solve bot execution.

**Do not open a Topstep Combine until 30+ forward shadow signals are logged and resolved.**

**Do not copy Kalshi/Polymarket traders with real money until public/exported trade history passes scoring.**

Accepted history sources:
- `public_wallet`
- `exported_history`
- `public_profile` with `visibility_state == "visible"` and closed-position P&L

Blocked sources:
- `public_leaderboard` only
- social screenshots
- hidden trade histories
- viral P&L without win rate/drawdown/profit factor

Run daily after market close:
```powershell
uv run --no-project --with yfinance python scripts/update_signal_outcomes.py
uv run --no-project --with yfinance python scripts/view_shadow_signals.py
```

---

## DONE — MES Databento Deep Validation (2026-07-19)

Supersedes the yfinance-based MES plans and the old `st80 tol8 partial gap
VIX 16-24` candidate below. Full reports:

- `research/MES_DATABENTO_VALIDATION_RESULTS_2026-07-19.md`
- `research/MES_ROLLING_AND_NEW_FAMILY_RESULTS_2026-07-19.md`
- Handoff: `CODEx_CLAUDE_COLLAB/CLAUDE_CODE_HANDOFF_2026-07-19_DATABENTO_MES_VALIDATION.md`

Data: 440,638 one-minute RTH bars, 1,148 MES sessions (2022-01-03 to
2026-07-17) from Databento `GLBX.MDP3` continuous `MES.v.0`. Roll-transition
sessions (18) now correctly excluded — each `instrument_id` change maps to the
first subsequent RTH session actually present in the data, fixing the
Sunday/overnight roll contamination. Session completeness audited against the
`CME Globex Equity` exchange calendar (0 unexplained incomplete sessions).
Corrected CSV SHA256:
`0A0840B9056F50523DC0360EADECB6D0499FCB75EF5E9FEEEBEA1306979BE9E6`

Outcomes (all research-only, all rejected):

- 4,800-config ORB/pullback executable search: 5 development survivors,
  1 selection survivor; frozen ORB failed final test ($12, PF 1.02, DD $336;
  -$76 and PF 0.91 at doubled costs).
- Rolling 126-session diagnosis: profitable in only 5/10 windows.
- Preregistered close-momentum family: 0/8 development survivors.
- Preregistered close-reversal: failed selection (-$474.50, PF 0.83).

Decisions in force:

- No deployable MES edge found. Do not tune further against the consumed
  2022-2026 final period — that would be backtest mining.
- MES/Topstep execution stays disabled (`VibeTradingNinjaTraderMESSim` task
  is `Disabled`). No Combine purchase.
- Next genuinely new MES evidence must come from forward data or order-flow
  data with a preregistered hypothesis.
- Focused suite: 61 passed (fetch/search/stress/replay + close-momentum +
  close-reversal tests).

---

## Status: What Is Running Now

### Kalshi / Prediction-Market Copy-Trader Diligence
- File: `strategies/kalshi_profile_scraper.py`
- Report: `C:\Users\kenne\.vibe-trading\reports\kalshi-profile-scraper-report.json`
- Profiles: `C:\Users\kenne\.vibe-trading\copy-trader-profiles.json`
- Watchlist report: `C:\Users\kenne\.vibe-trading\reports\copy-trader-watchlist.json`
- Public endpoints discovered:
  - `https://api.elections.kalshi.com/v1/social/profile/metrics?nickname=<handle>`
  - `https://api.elections.kalshi.com/v1/social/profile/holdings?nickname=<handle>&closed_positions=true&limit=100`
  - `https://api.elections.kalshi.com/v1/social/trades?nickname=<handle>&page_size=50`
- Current live finding:
  - `lad.`: huge public leaderboard P&L, but holdings hidden -> review only.
  - `weatherman.allday`: holdings visible, but sampled metrics are poor -> review only, no copy.

Run for a candidate:
```powershell
python strategies\kalshi_profile_scraper.py --username <handle> --max-pages 5 --append-profiles --print
python scripts\copy_trader_watchlist_report.py --print
```

Latest focused verification:
```powershell
uv run --no-project --with pytest --with requests --with python-dotenv python -m pytest agent\tests\test_kalshi_profile_scraper.py agent\tests\test_copy_trader_watchlist.py agent\tests\test_trade_history_importer.py -q
```

Result: `32 passed`

### Shadow Scanner (Task Scheduler)
- File: `strategies/shadow_pullback_signal.py`
- Schedule: weekdays 9:30-14:30 Central (10:30-15:30 ET), every 60 min
- Setup script: `scripts/setup_task_scheduler.ps1` (run once as Administrator)
- Log: `C:\Users\kenne\.vibe-trading\logs\shadow-scanner.log`
- Active config:
  - Signal type: first pullback to ORB level
  - Tolerance: 8 ticks (2 NQ pts)
  - Stop: 80 ticks (20 NQ pts)
  - Gap bias: enabled (only long on gap-up, short on gap-down)
  - VIX gate: 16-24 (skip chop days and news days)

### Best Backtest Candidate (SUPERSEDED 2026-07-19 — see MES Databento section)
Config: `st80 tol8 partial gap VIX 16-24`
- Train: 7 trades, 85.7% WR, exp $31.00/trade, 1 violation
- OOS: 3 trades, 100% WR, exp $74.00/trade, 1 violation
- Confidence limited: 3 OOS trades is not a significant sample

---

## DONE — Backtester Infrastructure

All tests: **54 passed** (clean compile)

```powershell
uv run --no-project --with pytest python -m pytest agent/tests/test_topstep_replay_backtester.py agent/tests/test_topstep_prop_bot.py agent/tests/test_strategy_safety_layers.py -q
```

### Backtester features built (all optional flags)
- ORB signal (`--signal-type orb`)
- First-pullback signal (`--signal-type pullback`)
- Fixed stop override (`--fixed-stop-ticks`)
- Daily 20-SMA trend filter (`--require-daily-trend-confirm`)
- Opening gap bias (`--require-opening-gap-bias`)
- EMA confluence filter (`--require-ema-confirm`)
- Live VWAP-at-entry filter (`--require-live-vwap-confirm`)
- Volume confirmation (`--require-volume-confirm`)
- Prior-day key-level proximity (`--require-key-level-proximity`)
- Break-of-structure confirmation (`--require-bos-confirm`)
- VIX range filter (`--require-vix-range --vix-min 16 --vix-max 24`)
- Partial exit model (`--exit-model partial_1r_be_2r`)
- Full exit model (`--exit-model full_target_stop`)
- Train/OOS split (`--train-end YYYY-MM-DD`)
- Consistency penalty scoring (`--consistency-penalty`)

### Scripts built
- `scripts/fetch_nq_yfinance.py` — fetch NQ=F historical bars
- `scripts/sweep_5m.py` — 5m parameter sweep
- `scripts/sweep_train.py` — train-only sweep ranked by consistency_adjusted_score
- `scripts/setup_task_scheduler.ps1` — Task Scheduler one-time setup
- `scripts/view_shadow_signals.py` — shadow journal viewer
- `scripts/update_signal_outcomes.py` — fetch bars, resolve signals to win/loss, append outcomes

### Data files
- `examples/nq_1m_7d.csv` — 4 trading days, 1m bars
- `examples/nq_5m_60d.csv` — 48 trading days, 5m bars
- `examples/nq_15m_60d.csv` — 48 trading days, 15m bars
- `examples/nq_1h_730d.csv` — 597 trading days, 1h bars (best free source)
- `examples/nq_1d_max.csv` — 26 years, daily bars
- `examples/es_1h_730d.csv` — 598 trading days, 1h ES=F bars
- `examples/vix_daily.csv` — 9,185 days of VIX daily closes

---

## DONE — Key Research Findings

### Why 1h/730d is the only statistically meaningful free dataset
- 5m/60d: max 4-11 trades per config → too small to distinguish edge from noise
- 1h/730d: 40 in-sample trades, 15 OOS trades → borderline but usable
- Polygon.io $29/mo unlocks 2yr of 1m data → 150+ OOS trades → real validation

### Why BOS fires on 5m but not 1h
- 1h bars are too coarse: breakout → pullback can happen inside a single candle
- 5m data: BOS fires 3 times on 48 days (proof of concept, too few to validate)

### Why MES needs its own sweep
- MES tracks ES=F, not NQ=F
- NQ parameters on ES data produced only 7 trades across 598 days
- MES parameter sweep requires dedicated ES data run

### Why profitable traders look better than our backtest
- They use 1m/5m execution bars with 8-15 tick stops (not 1h approximation)
- They watch DOM/order flow at entry (invisible in OHLC bars)
- They skip bad-regime days discretionarily
- Survivorship bias: 16.8% pass Topstep Combine, 33% of funded get paid = ~3% overall

---

## P0: Forward-Test Accumulation (ACTIVE — time-gated)

**Owner: Kenny + automated scanner**

Gate: 30+ resolved shadow signals before any Topstep spend.

Daily workflow:
```powershell
# After 15:30 ET each trading day:
uv run --no-project --with yfinance python scripts/update_signal_outcomes.py
uv run --no-project --with yfinance python scripts/view_shadow_signals.py
```

If forward-test WR ≥ 50% over 30+ signals: consider Topstep Combine.
If forward-test WR < 40%: re-run full train sweep, find new best config, reset.

---

## P0: View Shadow Signals — Outcome Join (Codex next)

The viewer shows signals and outcomes as separate rows.
Codex must update `scripts/view_shadow_signals.py` to join outcome records to their
parent signals by `signal_id = created_at`.

Changes needed:
- Add `load_outcomes(journal)` returning `dict[signal_id, outcome_record]`
- In `to_row()`, look up and merge outcome for each signal
- Update `print_summary()` to show forward-test win rate and total P&L from resolved signals only
- Keep `--json` output consistent

---

## P1: Premarket High/Low Key Levels (Codex)

Adds premarket high and low to the key-level proximity filter.
Profitable MNQ traders watch premarket H/L as support/resistance.

Implementation in `strategies/topstep_replay_backtester.py`:
- Extend `build_prior_day_levels()` to also fetch premarket bars
- Use `yf.Ticker("NQ=F").history(period="5d", interval="1h", prepost=True)`
- Filter for bars where `ts.time() < RTH_START` on the prior day
- Add `premarket_high` and `premarket_low` to the levels dict
- These 2 additional levels feed through the existing key-level proximity filter

---

## P1: A+ Setup Quality Scorer (Codex)

Implement composite setup gate instead of individual boolean flags.

Design:
- `quality_score_min: int = 0` in `BacktestConfig`
- Score = count of filters that passed: gap_bias (1pt) + vix_in_range (1pt) + key_level_near (1pt) + trend_sma (1pt)
- Signal blocked when quality_score < quality_score_min
- CLI: `--quality-score-min 3` to require 3/4 filters aligned
- Tests: verify score calculated correctly, verify blocking at threshold

Expected: high selectivity (A+ only) → fewer trades but higher WR and fewer violations.

---

## P1: 10am Entry Window Test (Codex)

`--start-hour 10 --start-minute 30` already supported by backtester.

On 1h data this is irrelevant (all pullback entries happen at 11:30+).
On 5m data it matters — test on `examples/nq_5m_60d.csv` with `rm6`:

```powershell
python strategies/topstep_replay_backtester.py `
  --csv examples/nq_5m_60d.csv `
  --symbol MNQ `
  --signal-type pullback `
  --range-minutes 6 `
  --min-breakout-points 5.0 `
  --reward-risk 2.0 `
  --pullback-stop-ticks 8 `
  --pullback-tolerance-ticks 8 `
  --start-hour 10 --start-minute 30 `
  --require-opening-gap-bias `
  --require-vix-range `
  --slippage-ticks 1 --commission 4.00
```

Compare trade count and quality vs. default start time.

---

## P1: Dashboard Integration

Add prop-bot section to existing trading dashboard:
- Forward-test signal count (open/resolved)
- Forward-test win rate
- Best config OOS expectancy
- Current VIX (in/out of range)
- Today gap direction
- Combine-readiness status: `not_ready / watching / paper_ready / combine_ready`

---

## P2: MES Parameter Sweep (DONE 2026-07-19 via Databento — rejected)

Superseded by the Databento deep validation (see top section). The planned
`es_1h_730d.csv` sweep is obsolete: 4.5 years of true 1-minute MES data were
purchased, normalized, and searched. No candidate passed the promotion gates.
Do not rerun sweeps on this consumed dataset.

---

## P1: Polymarket Wallet Replication Lane (started 2026-07-19)

The only "find and replicate profitable traders" path with unfakeable data:
on-chain Polymarket wallets. Built so far:

- `strategies/polymarket_wallet_discovery.py` - pulls the public profit
  leaderboard (`data-api.polymarket.com/v1/leaderboard`), keeps wallets
  persistent across windows, scores them through the existing
  `polymarket_wallet_tracker.py` pipeline. Read-only, no keys, no orders.
- First live run: 50 wallets discovered, 8 scored.

Known data-quality issues before any status is trusted:

1. Closed-positions endpoint only returns winners - wallets scored from it
   show fake 100% win rates ("paper_watch confidence 10" = survivorship
   artifact, NOT a real signal).
2. Activity rows carry no realized PnL - wallets scored from them show
   fake 0% win rates (false rejects).
3. Leaderboard window parameter needs verification (month == all-time in
   the first run).

Next steps (Codex or Claude):

1. Build FIFO realized-PnL reconstruction from raw activity buy/sell rows
   so scoring uses true per-position outcomes, losses included.
2. Verify leaderboard window values; only then does the persistence filter
   mean anything.
3. Re-score; anything genuinely passing copy-trader gates goes to
   paper_watch shadow logging only. No real-money copying without Kenny.

## P1: MES Order-Flow Edge Research (data purchased 2026-07-19)

Kenny approved the bbo-1s purchase: MES.v.0 1-second best bid/offer,
2024-01-01 to 2026-07-19, ~$66 from remaining signup credits (no card).
Downloader: `scripts/fetch_databento_bbo.py` (cost-guarded, cache-aware).
Manifest: `data/databento_bbo_manifest.json`.

Purpose: the only edge class not yet tested is order-flow. Quote data
enables preregisterable intraday hypotheses that could eventually support
a Topstep-compatible strategy (the three passing lanes cannot - they hold
multi-day and Topstep flattens daily).

Rules before any test (same discipline as everything else):

1. Preregister hypotheses in a dated Markdown file BEFORE analyzing the
   data. Candidate families: bid/ask size imbalance predicting short-term
   direction; spread-widening as volatility/regime signal; quote-pressure
   confirmation filter for existing frozen intraday candidates.
2. 70/15/15 chronological splits, doubled-cost stress, same promotion
   gates. The 2024-2026 window overlaps the consumed OHLC final period -
   treat any full-sample pass as historical evidence only; forward
   simulation still required.
3. No Topstep spend until an order-flow candidate passes historical gates
   AND accumulates 30+ forward shadow signals.

Estimates for future upgrades (not approved): trades 2025-2026 $206,
mbp-1 1yr $340, mbp-10 3.5mo $163.

## P2: Polygon.io Data Unlock (Kenny decision)

Cost: $29/month
Unlocks: 2 years of 1-minute NQ=F bars
Impact: 150+ OOS trades → statistically valid BOS/5m validation

If approved, Codex builds `scripts/fetch_nq_polygon.py`:
- Uses Polygon REST API `/v2/aggs/ticker/{ticker}/range/{multiplier}/{timespan}/{from}/{to}`
- Outputs same CSV schema as yfinance scripts (timestamp, open, high, low, close, volume)
- Plugs directly into existing backtester — no strategy changes needed

Gate: approve only after 30+ forward signals confirm positive edge.

---

## P2: Topstep Practice Workflow

After forward-test confirms positive WR over 30+ signals:
- Document exact Topstep Combine account setup steps
- Confirm current rules (consistency, drawdown, daily loss)
- Update `rules/prop_firms/topstep_topstepx_api.json` with current limits
- Create daily practice-account checklist

---

## Confidence Scores (end of 2026-06-22)

- Backtester reliability: 9.3/10
- Strategy profit confidence: 5.8/10
- Forward-test confidence: 1.5/10 (0 signals logged yet — scanner just started)
- Combine-readiness: 3.0/10

**Confidence will not improve until forward signals accumulate. Time is the next variable.**
