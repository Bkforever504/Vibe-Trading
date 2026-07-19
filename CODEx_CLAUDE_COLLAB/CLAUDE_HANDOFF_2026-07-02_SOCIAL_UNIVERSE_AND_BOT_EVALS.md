# Claude Handoff - 2026-07-02 Social Universe Upgrade + Bot Evaluation

Project folder:
`C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading`

Purpose:
Kenny sent multiple X screenshots from options alert traders/account-flip communities. Codex upgraded the social/options discovery layer so those names feed the watchlist and deep liquid scanner as **unverified, context-only observations**, not execution signals.

## Current Safety State

Hard rule:
Do **not** promote any screenshot/social ticker to execution. Everything below is watchlist/shadow/context only.

Latest checks run by Codex:
- Focused tests: `17 passed`
- Execution gate audit: `passed=True`, `registered_signal_count=63`, `issue_count=0`, `warning_count=1`
- Only audit warning: `portfolio_concentration_monitor.py` uses Alpaca read-only account/position reads; verify it stays read-only.
- Latest signal stack health: `OK=36`, `STALE=0`, `MISSING=0`, `ERROR=0`

Note:
`daily-eod-summary.json` still showed an older `ok=24/stale=12` snapshot and one schedule-alignment issue. The later `signal_stack_health_report.py` run showed all green (`OK=36`). Claude should re-run both before drawing conclusions.

## Files Changed / Relevant

Codex touched:
- `strategies/social_arbitrage_watchlist.py`
- `scripts/deep_liquid_universe_scanner.py`
- `agent/tests/test_social_arbitrage_watchlist.py`
- `agent/tests/test_deep_liquid_universe_scanner.py`

Runtime data updated:
- `C:\Users\kenne\.vibe-trading\social-arb-observations.json`
- `C:\Users\kenne\.vibe-trading\reports\social-arbitrage-watchlist.json`
- `C:\Users\kenne\.vibe-trading\reports\weekly-hot-instruments.json`
- `C:\Users\kenne\.vibe-trading\reports\deep-liquid-universe-scan.json`

## What Codex Built Today

### 1. Generic Cashtag Intake

`strategies/social_arbitrage_watchlist.py` now:
- Extracts explicit cashtags from any observation, e.g. `$MCD`, `$ABBV`, `$TDOC`, `$KVUE`, `$REGN`.
- Maps index-option mentions:
  - `$SPX` / `$SPXW` -> `SPY` proxy for equity-options context.
- Ignores crypto-style cashtags (`BTC`, `ETH`, etc.) for this stock/options layer.
- Prevents one post from double-counting the same ticker if it contains both `QQQ` and `$QQQ`.
- Preserves known mapped themes. Example: `$FRMM` remains `social squeeze watch`, not generic `explicit social ticker`.

### 2. Wider Deep Liquid Universe

`scripts/deep_liquid_universe_scanner.py` now includes more competitor/alert-room names:
- Previously added: `MCD`, `LTH`, `BMY`, `KVUE`, `TDOC`, `IBM`, `PATH`, `AUR`, `L`
- Added this pass: `REGN`, `RDDT`, `LYFT`

VIX is intentionally **not** treated as a normal tradeable equity candidate. It was added as a social-arb keyword theme only:
- ticker: `VIX`
- theme: `volatility regime`
- note: regime context only; no equity-options execution.

### 3. Manual Screenshot Observations Ingested

Codex appended manual observations from Kenny's screenshots as:
- `source = x_manual_competitor_screenshot`
- `mode = context_only`
- `execution_enabled = false`
- notes clearly say unverified P&L claim; never an execution signal by itself.

New screenshot tickers ingested:
- First wave: `NVDA`, `SPY`, `TSLA`, `MCD`, `ABBV`, `AAPL`, `LTH`, `MSFT`, `L`, `IBM`, `TDOC`, `QQQ`, `BMY`, `GOOGL`, `KVUE`, `JNJ`, `HOOD`, `AUR`, `PATH`
- Second wave: `REGN`, `JNJ`, `LLY`, `VIX`, `SPY`, `DDOG`, `META`, `IBM`, `HOOD`, `CRWD`, `MCD`, `NFLX`, `RIVN`, `RDDT`, `LYFT`, `COIN`, `MRNA`

Important interpretation:
- `$STRAT` in the screenshot was treated as "The Strat" method/community, not a stock ticker. Do not add `STRAT` as a tradeable symbol unless separately verified.

## Current Bot / Account Stats From Reports

Latest `bot-status-snapshot.json`:
- Account equity: `$90,698.41`
- Day change: `+$1,153.10`
- Buying power: `$350,465.64`
- Market Force: `bullish_lean`, score `2.0`, confidence `10.0`
- Exposure posture: `cautious`
- Portfolio concentration: `elevated`
  - position_count: `9`
  - gross_pct_equity: `4.309%`
  - net_directional_beta_pct_equity: `-0.162%`
  - warning: `many_underlyings_open`
- Flip trades: total `8`, open `0`, closed `8`
- IWM options trades: total `7`, open `3`, closed `4`
- Guard blocks: Alpaca `173`, Kalshi `12`
- Outcome verdict: `posture_helpful`, review_score `7.5`

Latest `daily-eod-summary.json`:
- Report date: `2026-07-02`
- Verdict: `watch`
- CSV realized P&L: `+$1,745.00`
- Trade events: `6`
- Guard blocks: `16`
- Guard reasons:
  - duplicate_symbol_exposure: `10`
  - confidence_below_minimum: `6`
- Needs review queue: `4`, all medium
  - contracts_above_limit: `2`
  - notional_above_limit: `2`

Latest `signal-stack-grades.json`:
- item_count: `38`
- ops grades: `A=32`, `B=5`, `D=1`
- evidence grades: `C=2`, `D=7`, `F=29`
- maturity: `log_building=35`, `needs_more_signals=3`
- promotion_ready_count: `0`

Top grade/evidence notes:
- Market Force Score: grade `C`, ops `A`, sample_count `9`, context-only.
- IWM Options Bot: grade `C`, ops `A`, sample_count `7`, avg_confidence `8.67`, not promotion-ready.
- Social Trending: grade `D`, ops `A`, sample_count `22`, still needs more signal events.
- Flip Shadow Candidates: grade `D`, ops `A`, sample_count `106`, needs more signal events.
- Flip Bot: grade `F` despite high win rate because total P&L field is still negative from earlier oversized loss.
  - sample_count `8`
  - win_rate `0.875`
  - total_pnl `-8702.0`
  - max_drawdown_dollars `-11557.5`
  - warnings include `negative_pnl`, `guard_blocks=149`, `not_enough_samples`
  - This deserves evaluation, not panic. Recent trades have been profitable, but the historical oversized loss still dominates the metric.

Challenge account simulator:
- Conservative 2% risk:
  - start `$1,000`
  - end `$1,075.28`
  - net return `+7.528%`
  - max drawdown `1.329%`
  - win rate `87.5%`
- Aggressive 5% risk:
  - end `$1,195.59`
  - net return `+19.559%`
  - max drawdown `3.323%`
- Flip-challenge 10% risk:
  - end `$1,416.48`
  - net return `+41.648%`
  - max drawdown `6.647%`
- Stress 20% risk:
  - end `$1,938.38`
  - net return `+93.838%`
  - max drawdown `13.294%`
- All simulator modes are read-only; do not use them as leverage approval.

## Current Hot Instrument Readout

Latest weekly hot instruments:
- candidate_count: `260`
- priority_count: `4`
- research_only_count: `48`
- promotion_rule: no promotion without 30 trading days and 10 completed shadow samples.

Top priority shadow review:
1. `TSLA`
   - hot_score `12.75`
   - action `priority_shadow_review`
   - social_days `3`, social_slots `9`
   - shadow_completed `16`
   - shadow_win_rate `0.75`
   - best_shadow_return `1610.53%`
   - total_hypothetical_pnl `11480`
2. `QQQ`
   - hot_score `10.2`
   - action `priority_shadow_review`
   - shadow_completed `20`
   - shadow_win_rate `0.8`
   - best_shadow_return `175.36%`
   - total_hypothetical_pnl `7005`
3. `NVDA`
   - hot_score `9.5`
   - action `priority_shadow_review`
   - shadow_completed `12`
   - shadow_win_rate `0.667`
   - best_shadow_return `1026.09%`
   - total_hypothetical_pnl `3470`

Watch context names surfaced:
- `NBIS`, `AMAT`, `ORCL`, `INTC`, `META`, `APLD`, `HOOD`, `CRWV`, `IREN`

Manual screenshot names with watch/observe context:
- `META`, `HOOD`, `COIN`, `SPY`, `AAPL`, `AUR`, `TDOC`, etc.

## Deep Liquid Scanner Readout

Focused scan on second-wave names:
- source: Alpaca
- symbols: `17`
- ok: `16`
- candidates: `6`

Deep scanner candidates:
1. `RDDT`
   - deep_score `10.0`
   - one_day `+13.93%`
   - five_day `+23.046%`
   - twenty_day `+16.928%`
   - relative_volume `2.03`
   - recommendation `shadow_review_candidate`
2. `META`
   - deep_score `8.25`
   - one_day `+8.809%`
   - relative_volume `2.47`
   - social_slots `11`
   - recommendation `shadow_review_candidate`
3. `MRNA`
   - deep_score `8.25`
   - twenty_day `+58.852%`
   - social_slots `2`
   - recommendation `shadow_review_candidate`
4. `HOOD`
   - deep_score `7.5`
   - twenty_day `+23.242%`
   - social_slots `4`
   - recommendation `shadow_review_candidate`
5. `COIN`
   - deep_score `7.5`
   - one_day `+8.927%`
   - relative_volume `1.368`
   - recommendation `shadow_review_candidate`
6. `RIVN`
   - deep_score `6.0`
   - five_day `+17.35%`
   - social_slots `4`
   - recommendation `shadow_review_candidate`

Deep scanner watch context:
- `NFLX`, `IBM`, `DDOG`, `LLY`, `JNJ`, `MCD`, `CRWD`, `SPY`, `REGN`

Rejected/blocked:
- `LYFT` rejected for Flip Bot due to price below minimum (`close=14.83`, `price_below_minimum`)
- `VIX` unavailable from Alpaca equity data; expected. Treat as regime context only.

## Claude Evaluation Requests

Please evaluate:

1. Bot performance and risk:
   - Is Flip Bot's recent 7/8 win run enough to change anything? Codex says no; still needs more samples because historical oversized loss remains material.
   - Are the three open IWM options trades within intended risk and stop/profit rules?
   - Does elevated concentration (`9 positions`, `4.309%` gross option exposure) require any adjustment or just observation?

2. Social/universe layer:
   - Validate that generic cashtag mapping is correct and does not over-score single-source screenshots.
   - Confirm `VIX` stays regime-only.
   - Confirm `STRAT` should remain excluded as a stock ticker.
   - Decide whether `RDDT`, `META`, `MRNA`, `HOOD`, `COIN`, `RIVN` should get Flip shadow candidate logging like `QQQ/IWM/NVDA/TSLA/AAPL`, or remain deep-scan watch context until more evidence.

3. Schedule / health:
   - Re-run:
     `uv run --no-project python scripts\signal_stack_health_report.py`
     `uv run --no-project python scripts\daily_eod_summary.py`
     `uv run --no-project python scripts\market_schedule_alignment.py --print` if available.
   - Resolve whether the older EOD schedule-alignment issue is stale or real.

4. Testing:
   - Codex ran:
     `uv run --no-project --with pytest --with pandas python -m pytest -q agent\tests\test_social_arbitrage_watchlist.py agent\tests\test_deep_liquid_universe_scanner.py agent\tests\test_weekly_hot_instrument_report.py`
   - Result: `17 passed`
   - Please run any broader focused suite you think is necessary before committing/evaluating.

5. Upgrade ideas, guarded:
   - Best next upgrade might be an automatic "options liquidity feasibility" check for deep candidates before adding them to Flip shadow candidates.
   - For each candidate, check option chain existence, 0DTE/weekly spread, minimum open interest/volume, and max contract price for small-account challenges.
   - Keep it read-only and log-only.

## Bottom Line

The system is now catching the same tickers the X option-flip crowd is posting, but it is not copying them blindly.

Current strongest names:
- Execution universe / priority shadow: `TSLA`, `QQQ`, `NVDA`
- Deep liquid watch: `RDDT`, `META`, `MRNA`, `HOOD`, `COIN`, `RIVN`
- Regime clue: `VIX below 16` claim should be compared against our RV/IV, VIX, Hurst, and Market Force logs before becoming any rule.

No live execution changes were made.
No bot risk settings were changed.
All screenshot-derived data is context-only.

## Codex Follow-Up After Claude Review

Claude's recommendation was accepted:
- Add `META` to `strategies/flip_bot.py::SHADOW_CANDIDATES`.
- Update `agent/tests/test_flip_bot_safety.py` to assert `META` is included.
- Update `research/signal_registry.json` so `flip_shadow_candidates` now documents:
  `QQQ/IWM/NVDA/TSLA/AAPL/META`

Verification after the change:
- `uv run --no-project --with pytest --with requests --with python-dotenv --with yfinance --with pandas python -m pytest -q agent\tests\test_social_arbitrage_watchlist.py agent\tests\test_deep_liquid_universe_scanner.py agent\tests\test_weekly_hot_instrument_report.py agent\tests\test_mfi_shadow_logger.py agent\tests\test_flip_bot_safety.py`
- Result: `40 passed`
- `uv run --no-project python scripts\execution_gate_audit.py --print`
- Result: `passed=True`, `issue_count=0`, `warning_count=1`
- Import sanity check:
  `SHADOW_CANDIDATES = QQQ,IWM,NVDA,TSLA,AAPL,META`
  `LIVE_EXECUTION_ENABLED = False`

This is shadow-only. No broker submission path was changed.
