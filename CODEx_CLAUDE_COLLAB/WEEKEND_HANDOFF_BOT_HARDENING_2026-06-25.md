# Weekend Handoff - Bot Hardening Pass

Date: 2026-06-25 late evening CT
Project: `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading`

## Context

Claude fixed the flip bot account sizing so it now uses live Alpaca paper equity when no override is set. Kenny then asked Codex to harden everything before pausing work until Sunday.

Core goal: paper-first, no live capital rush, make tomorrow's bots safer and more complete.

## Implemented This Pass

### P0 - Options stop tightened

File:

- `strategies/iwm_options_bot.py`

Changes:

- `STOP_LOSS_PCT` changed from `-2.0` to `-1.0`.
- New helper `_trade_stop_loss_pct()` makes recovered/legacy groups use the safer `-100% of credit` stop even if old state has `stop_loss_pct: -2.0`.
- New helper `_mark_all_open_groups_closed_when_flat()` fixes ghost state after broker positions are flat.
- Ran monitor-only after close; actual local state now marks recovered IWM group `closed`.

Why:

- Today's recovered IWM group closed around `-211%` of credit.
- Future recovered groups should close at `-100%` of credit.

### P0 - Flip bot 2-leg spread execution wired

File:

- `strategies/flip_bot.py`

Changes:

- Added `_submit_spread(setup, max_notional)`.
- `run_entry()` now routes `bear_trend_spread` setups through `_submit_spread()` instead of buying only the long leg.
- State now records:
  - `short_option_symbol`
  - `short_strike`
  - `max_loss`
  - `max_gain`
- Added `_spread_mid(long_symbol, short_symbol)`.
- Added `_close_spread(trade)`.
- `run_monitor()` now monitors spread net debit and exits both legs together.

Why:

- Claude's spread fallback existed, but `run_entry()` only submitted `option_symbol`.
- That would have created naked directional long exposure rather than the intended defined-risk spread.

### Flip bot long trend support

File:

- `strategies/flip_bot.py`

Changes:

- Added `_vwap_50ema_bull_signal()`.
- Added `find_bull_trend_day(account)`.
- `run_entry()` now checks:
  1. bear trend
  2. bull trend
  3. 0DTE
  4. earnings
  5. breakouts

Bull trend requires:

- Breadth confirmation across SPY/QQQ/IWM, at least 2 of 3.
- Above VWAP.
- Above 50 EMA.
- 50 EMA sloping up.
- Green session.
- Not extended from VWAP.
- Pullback held trend.

### VIX term structure filter

File:

- `strategies/flip_bot.py`

Research sources used:

- Cboe VIX term structure page: `https://www.cboe.com/en/tradable-products/vix/term-structure/`
- Cboe discussion of VIX backwardation/contango: `https://www.cboe.com/insights/posts/inside-volatility-trading-is-vix-backwardation-necessarily-a-sign-of-a-future-down-market`
- VIXCentral term structure reference: `https://vixcentral.com/`

Changes:

- Added `_vix_term_structure_regime(vix, vix3m)`.
- Added `_vix_term_structure_direction_ok(direction, regime)`.
- Added `_fetch_vix_term_structure()` using free yfinance symbols:
  - `^VIX`
  - `^VIX3M`
- Bull trend entries are blocked in VIX backwardation.
- Bear trend entries remain allowed in backwardation because that is the fear regime the short setup is meant to capture.
- Fetch failure is fail-open with a warning, not a hard stop.

### Copy trader tightened

File:

- `strategies/copy_trader_watchlist.py`

Changes:

- `MAX_PRICE_DRIFT` tightened from `0.15` to `0.05`.
- Added `kelly_fraction(profile)`.
- `simulate_copy_signal()` now emits:
  - `kelly_fraction`
  - Kelly-capped `risk_pct`
- Still paper-only.

Result after report refresh:

- Polymarket example at 11.9% drift is now `skip`.
- Kalshi example at 8.3% drift is now `skip`.
- Solana example at 1.38% drift remains `paper_copy`.
- Invo screenshot example remains `reject`.

### Kalshi weather consensus gate

File:

- `strategies/kalshi_prediction_bot.py`

Changes:

- Added `WEATHER_MAX_SOURCE_DISAGREEMENT_F = 1.5`.
- Added `weather_consensus_fair_temperature(forecasts)`.
- It returns `allowed=false` when weather sources disagree by more than 1.5°F.

Purpose:

- Claude should wire NWS/Open-Meteo/other source forecasts through this before scoring weather markets.

## Local Runtime Refresh

Commands run:

```powershell
uv run --no-project --with alpaca-py --with yfinance --with python-dotenv --with numpy python strategies\iwm_options_bot.py --monitor-only
uv run --no-project --with requests --with python-dotenv python scripts\copy_trader_watchlist_report.py --print
uv run --no-project --with requests --with python-dotenv python strategies\trading_dashboard.py --days 5
```

Current dashboard state:

- Equity: `$88,217.71`
- No open positions.
- No open grouped option trades.
- Copy Trader Watchlist panel includes conviction/copy size.
- Kalshi Prediction Lab remains paper-only.

## Verification

Fresh verification:

```powershell
uv run --no-project --with pytest --with requests --with yfinance --with python-dotenv --with pandas --with alpaca-py python -m pytest agent\tests\test_flip_bot_safety.py agent\tests\test_flip_bear_trend.py agent\tests\test_iwm_options_confidence_gate.py agent\tests\test_copy_trader_watchlist.py agent\tests\test_kalshi_prediction_bot.py agent\tests\test_trading_dashboard.py agent\tests\test_tradingview_validation_report.py -q
```

Result:

```text
40 passed, 4 warnings in 9.10s
```

Warnings are deprecation warnings from dependencies / `datetime.utcnow()`, not test failures.

## Still Not Done

Do not claim these are complete yet:

1. Polymarket real wallet tracker via CLOB API.
2. Kalshi personal fills/history fetcher.
3. NWS/Open-Meteo live weather source wiring into `weather_consensus_fair_temperature()`.
4. MNQ per-bar diagnostic logging for missed 9/10 trend days.
5. More complete VIX futures curve using Cboe/VIXCentral data instead of only VIX vs VIX3M.
6. Live trading.

## Sunday Priority

1. Run tomorrow's logs and inspect whether flip spread/bull/bear logic fired correctly.
2. If a flip spread opened, confirm both legs exist and monitor reads spread net value.
3. Build Polymarket wallet tracker/importer.
4. Wire NWS weather forecast into Kalshi weather bot/lab.
5. Add MNQ scanner per-bar debug output.

## Safety Reminder

Everything remains paper-first. Do not enable live trading or private-key copy execution. The standard is still 30+ forward-test signals, clean rule compliance, and confidence near 9/10 before real money.
