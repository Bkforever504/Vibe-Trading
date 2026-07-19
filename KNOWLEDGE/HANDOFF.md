# Options Bot - Full Knowledge Handoff

**For:** Claude Code / Codex  
**Owner:** Kenny  
**Last updated:** 2026-06-18  

Start prompt for next session:

> Read `CLAUDE.md` and `KNOWLEDGE/HANDOFF.md`, then continue from the priority list. Do not assume the bot is safe for live money until it has paper-traded for 30+ days and been backtested.

---

## What Was Done This Session (2026-06-18)

### Morning Preflight (2026-06-18, 6:23am CT)

- Re-ran syntax checks for `strategies/flip_bot.py`, `strategies/flip_scanner.py`, `strategies/iwm_options_bot.py`, `strategies/backtest.py`, and `strategies/pnl_tracker.py`; all compiled cleanly.
- Confirmed `ALPACA_PAPER=true`.
- Confirmed `ACCOUNT_SIZE_OVERRIDE=5000` for paper observation.
- Confirmed Alpaca paper API connectivity:
  - `/v2/clock` returned `200`.
  - `/v2/account` returned `200`, account status `ACTIVE`.
  - Options approval/trading level reported as `3`.
  - `/v2/positions` returned the 4 existing IWM option legs.
- Confirmed Alpaca options snapshot endpoint works for the 4 current IWM option symbols; all returned bid/ask data.
- Confirmed flip bot status: `PAPER`, `0` open trades, `0` closed trades.
- Confirmed `flip-trades.json` does not exist yet, which is expected because no flip trades have opened.
- Confirmed `options-trades.json` does not exist yet; existing IWM legs are legacy/untracked and remain protected from leg-by-leg auto-close.
- Confirmed scheduled tasks:
  - `Flip-Bot-Entry` next run: `2026-06-18 8:35am CT`.
  - `Flip-Bot-Monitor` next run: `2026-06-18 8:45am CT`.
  - `IWM-Bot-Entry` next run: `2026-06-18 9:45am CT`.
  - `IWM-Bot-Monitor` next run: `2026-06-18 10:00am CT`.
- Ran `python strategies\flip_scanner.py --account 5000 --no-save`; scanner showed a SPY gap signal and affordability under the `$5K` paper setting.
- Important: this is for paper observation only. With `--account 200`, the same style of SPY setup is not affordable under the risk cap and should not be forced live.

### New Bot: Flip Bot (small-account directional options)

Kenny's goal is to grow $200 real money into meaningful capital via directional option buying. Separate from premium-selling bot. Researched what works for small accounts and built full automation.

**Three strategies implemented:**

**1. 0DTE Catalyst Scalp**
- Buy ATM SPY call/put on FOMC, CPI, or pre-market gap >0.75% days only
- Entry: 9:30-10:00am ET window only
- Exit: +75% profit OR -50% stop OR 1:45pm hard cutoff (theta destroys 0DTE after 2pm)
- Research win rate: ~40-45%, winners 2-5x size of losers

**2. Earnings Lotto**
- Buy OTM call 2-4 days before earnings WHEN hist avg move > implied move (ratio >1.1)
- Close DAY BEFORE earnings print — never hold through announcement (IV crush kills even correct direction)
- Skip when implied move > historical (options overpriced)

**3. Momentum Breakout**
- Stock breaks 20-day high on 2.5x+ avg volume
- Buy 1-2 strikes OTM weekly call same day
- Exit: +75%, -50%, or 3-day max hold

**PDT Rule workaround for live trading:** Use CASH account on Robinhood/Webull. No $25K minimum, no 3-trade/week limit. Options settle T+1.

### New Files

| File | Purpose |
|---|---|
| `strategies/flip_bot.py` | Automated flip bot — `--entry` (9:15am) and `--monitor` (every 15min) |
| `strategies/flip_scanner.py` | Manual morning research — run before market to see GO/NO-GO |
| `strategies/catalyst_scanner.py` | Deep earnings/UOA scanner — run for weekly research |

### New Task Scheduler Tasks

| Task | Time | Command |
|---|---|---|
| Flip-Bot-Entry | 8:35am CT Mon-Fri | `python flip_bot.py --entry` |
| Flip-Bot-Monitor | 8:45am CT, every 15min for 7 hours Mon-Fri | `python flip_bot.py --monitor` |

Codex corrected these times because the original 9:15am CT entry was 10:15am ET, too late for the bot's own 9:30-10:00am ET 0DTE entry window.

### Config Change

`ACCOUNT_SIZE_OVERRIDE=5000` in `agent/.env` — was 200, raised to 5000 so paper trades actually fire and behavior is observable. Change to 200 when going live.

### Flip Bot State File

`~/.vibe-trading/flip-trades.json` — tracks open/closed flip trades separately from premium-selling bot's `options-trades.json`.

### Flip Bot Log

`~/.vibe-trading/logs/flip-bot.log`

### Discipline Rules Baked Into Bot

- Max 25% account risk per trade
- +75% profit target (set immediately after fill)
- -50% hard stop
- Max 2 open flip trades at once
- 0DTE hard close at 1:45pm ET
- Earnings hard close day before print
- Breakout max 3-day hold
- Entry and monitor now check Alpaca market clock before trading.
- `--account` now overrides `FLIP_ACCOUNT_SIZE_OVERRIDE` / `ACCOUNT_SIZE_OVERRIDE` for manual scanner and bot test runs.
- Scanner now labels a signal as `SIGNAL / NOT AFFORDABLE` when the account cannot afford one contract under the risk cap.

### Research: Traders Kenny Referenced

Researched Dontez Akram, JRGREATNESS, TWP Official, Aristotle Trades, callme100k, lovvekae, icurlycae, Vincent Kaiser. All are content creators selling courses/signals. Their actual strategy is directional option buying (what flip_bot does). They show wins, hide losses. Flip_bot systematizes their approach with enforced discipline rules they don't teach.

### Backtest Results

| Symbol | Strategy | Days | Win Rate | Expectancy/trade |
|---|---|---|---|---|
| IWM | ps (premium sell) | 252 | 80% | -$6.34 (small sample) |
| IWM | ps | 504 | 82.4% | +$19.89 |
| SOFI | ps | 504 | 0% | -$62.91 — REMOVED |
| F | ps | 504 | — | 0 trades — REMOVED |

SOFI and F removed — IV too low for premium selling strategy.

### What Codex Should Verify

1. `flip_bot.py` OCC symbol builder `_occ()` — confirm format matches Alpaca's expected option symbol format
2. `flip_bot.py` `_option_mid()` — uses Alpaca options snapshot endpoint. Verify this endpoint is accessible on paper account and returns real-time data
3. `flip_bot.py` order submission — single-leg buy order body. Confirm Alpaca paper account accepts options buy orders in this format
4. `flip_scanner.py` — run manually and verify it produces sensible output with real yfinance data
5. Task Scheduler tasks Flip-Bot-Entry and Flip-Bot-Monitor — verify they show correct python path and argument in Task Scheduler UI

---

## What Was Done Earlier (2026-06-17)

- Fixed the iron condor same-expiry bug.
- Replaced unsafe leg-by-leg profit/stop monitoring with grouped trade tracking for new multi-leg trades.
- Added stop-loss handling at -200% of collected credit at the trade-group level.
- Added an `ACCOUNT_SIZE_OVERRIDE` env setting so paper trading can mimic Kenny's real starting account size instead of the full $100K paper balance.
- Changed per-trade risk sizing from forced minimum one contract to "skip if the risk budget cannot afford one contract."
- Added minimum credit quality filters: `MIN_NET_CREDIT` and `MIN_CREDIT_TO_RISK`.
- Added time-based grouped exit signals: iron condors manage at `IC_DTE_MANAGE_DAYS=21`, put spreads manage at `PS_DTE_MANAGE_DAYS=2`.
- Added a live-trading confirmation gate: `CONFIRM_LIVE_TRADING=I_UNDERSTAND_THE_RISK` is required before live mode can run.
- Changed Alpaca clock failure behavior to fail closed unless `FAIL_OPEN_MARKET_CHECK=true`.
- Ran `last30days` research on automated options bots and small-account credit spread risk controls. Output was thin but consistent: recent trader discussion emphasizes risk/reward discipline, paper/replay logging, not adding to losing trades, and automation as a discipline tool rather than a prediction engine.
- Added daily loss kill switch controls: `MAX_DAILY_LOSS_PCT` and `CLOSE_ON_DAILY_LOSS`.
- Added option liquidity filter: `MAX_BID_ASK_PCT`.
- Added `REQUIRE_MANUAL_APPROVAL`, defaulting to `false` in paper and `true` in live mode.
- Broadened platform research attempts across X/Twitter, YouTube, TikTok, Instagram, Threads, and Facebook. Direct access was limited by missing API/cookie providers and platform blocking, but public search snippets reinforced the same pattern: automated trading content emphasizes defined risk, stop fixes, small sizing, paper testing, and consistent rules over "secret" entries.
- Added anti-stacking controls: `MAX_OPEN_TRADES_PER_UNDERLYING` and `MAX_NEW_TRADES_PER_SYMBOL_PER_RUN`.
- Added structured decision log file: `C:\Users\kenne\.vibe-trading\logs\options-decisions.jsonl`.
- Reviewed and hardened `strategies/backtest.py`.
- Backtest now models account size, 2% risk sizing, minimum credit/risk, slippage, commissions, time exits, and full forward-data requirements.
- Backtest now prints top skip reasons so "no trades" is actionable.
- Backtest report now includes return percentage, profit factor, expectancy per trade, max drawdown, and max consecutive loss streak. This keeps the analysis focused on survival and expectancy instead of win rate alone.
- Smoke result: `IWM` put spread over 252 days with `$200` account generated no trades because the risk budget cannot afford one contract. This is correct and expected.
- Smoke result: `IWM` put spread over 252 days with `$50,000` account produced 5 trades, 80% win rate, about `-$31.70` total P&L, `-0.06%` return, `0.95` profit factor, `-$6.34/trade` expectancy, and `1.25%` max drawdown after modeled friction and one stop-loss. This proves high win rate is not enough.
- Fixed `strategies/pnl_tracker.py` so multi-leg orders are netted as one order event instead of counting every leg as a separate fake win/loss.
- Added Alpaca order retry handling for 429/5xx errors with Discord alert on final failure.
- Added wheel phase tracking in `options-trades.json`: cash-secured-put phase vs covered-call phase after 100+ shares are detected.
- Verified Groq is not used by the standalone strategy scripts. The placeholder key only matters for the broader Vibe-Trading agent/LLM UI, not `iwm_options_bot.py`, `backtest.py`, or `pnl_tracker.py`.
- Sent a Discord webhook test alert from Codex; Discord returned HTTP 204 success. Kenny confirmed the phone received the notification.
- Added market-hours guard using Alpaca `/v2/clock`.
- Added VIX filter: trade only when VIX is 15-40.
- Added 20-day SMA filter for put spreads and cash-secured puts.
- Added put/call ratio filter: skip if PCR > 2.0.
- Added earnings skip window: 5 days.
- Added Discord alerts with `@everyone` for entries, profit target exits, and stop-loss exits.
- Added/verified `strategies/pnl_tracker.py`.
- Fixed Windows Task Scheduler crash caused by `>> log.log 2>&1` being passed directly to Python instead of a shell.
- Confirmed bot now logs through Python `FileHandler` to `C:\Users\kenne\.vibe-trading\logs\options-bot.log`.
- Documented the current IWM iron condor position and next operational checks.

---

## What Was Built

Automated multi-symbol options trading bot on Kenny's Alpaca paper account.

The bot scans seven symbols, supports multiple premium-selling strategies, applies safety filters before entries, records new multi-leg trades into a local state file, and monitors tracked trade groups for profit targets or stop-losses.

### Files

- `strategies/iwm_options_bot.py` - main bot.
- `strategies/backtest.py` - replay/backtest engine.
- `strategies/pnl_tracker.py` - P&L report script.
- `agent/.env` - Groq, Alpaca, Discord, and environment settings.
- `C:\Users\kenne\.vibe-trading\options-trades.json` - local state file for newly opened multi-leg trade groups.
- `C:\Users\kenne\.vibe-trading\logs\options-bot.log` - live append-only bot log.
- `C:\Users\kenne\.vibe-trading\logs\options-decisions.jsonl` - structured audit trail for submitted trade candidates and key skip/cap decisions.
- `KNOWLEDGE/HANDOFF.md` - this handoff.

### Windows Scheduled Tasks

- `IWM-Bot-Entry` - 9:45am CT Monday-Friday.
- `IWM-Bot-Monitor` - hourly 10am-3pm CT Monday-Friday.

Task Scheduler now calls Python directly without shell redirect arguments. File logging is handled inside the bot.

---

## Strategies

### Strategy 1: Iron Condor

Symbols: `IWM`, `TSLA`

- Sell 16-delta put.
- Buy lower put wing below the short put.
- Sell 16-delta call.
- Buy upper call wing above the short call.
- All four legs must use the same expiry.
- DTE: 30-45 days.
- Entry filters: market open, VIX 15-40, IV Rank > 30, no earnings within 5 days, PCR < 2.0, and relevant trend checks.
- Exit: 50% profit target or -200% stop-loss.

### Strategy 2: Put Credit Spread

Symbols: all configured symbols.

- Sell 25-delta put.
- Buy lower put wing with same expiry.
- Spread width: `$3` default.
- Width override: `$5` for `SPY`, `QQQ`, `TSLA`, `AAPL`.
- DTE: 7-14 days.
- Entry filters: same safety stack as above.
- Exit: 50% profit target or -200% stop-loss.

### Strategy 3: Wheel

Symbols: `NVDA`, `AAPL`

- Sell 30-delta cash-secured put, 21-35 DTE.
- If assigned, hold 100 shares.
- Sell 30-delta covered call, 21-35 DTE.
- If called away, restart cash-secured put cycle.
- Earnings skip is mandatory.

---

## Symbol Config

```python
SYMBOLS = {
    "IWM":  ["ic", "ps"],
    "SPY":  ["ps"],
    "QQQ":  ["ps"],
    "TSLA": ["ic", "ps"],
    "NVDA": ["ps", "wheel"],
    "AAPL": ["ps", "wheel"],
    "PLTR": ["ps"],
}

PS_WIDTH_OVERRIDE = {"SPY": 5.0, "QQQ": 5.0, "TSLA": 5.0, "AAPL": 5.0}
```

---

## Entry Filter Stack

All checks run before new entries:

```text
1. _market_is_open()     - Alpaca /v2/clock, skip if closed
2. _vix_in_range()       - skip if VIX < 15 or VIX > 40
3. iv_rank(sym)          - skip if IV Rank < 30
4. _has_earnings_soon()  - skip if earnings are within 5 days
5. _pcr_ok(sym)          - skip if put/call ratio > 2.0
6. _above_20sma(sym)     - skip put spreads/CSPs if below 20-day SMA
```

---

## Safety Caps

```python
MAX_ACCOUNT_RISK_PCT = 0.02
MAX_OPEN_TRADES      = 8
MAX_TRADES_PER_DAY   = 5
IV_RANK_MIN          = 30.0
MIN_NET_CREDIT       = 0.10
MIN_CREDIT_TO_RISK   = 0.20
MAX_WHEEL_ALLOC_PCT  = 0.20
ACCOUNT_SIZE_OVERRIDE = 0
AUTO_CLOSE_GROUPS    = true for paper, false for live unless explicitly enabled
IC_DTE_MANAGE_DAYS  = 21
PS_DTE_MANAGE_DAYS  = 2
MAX_DAILY_LOSS_PCT  = 0.03
CLOSE_ON_DAILY_LOSS = false
MAX_BID_ASK_PCT     = 0.35
REQUIRE_MANUAL_APPROVAL = false for paper, true for live
MAX_OPEN_TRADES_PER_UNDERLYING = 1
MAX_NEW_TRADES_PER_SYMBOL_PER_RUN = 1
VIX_MIN              = 15.0
VIX_MAX              = 40.0
PCR_MAX              = 2.0
EARNINGS_SKIP_DAYS   = 5
STOP_LOSS_PCT        = -2.0
```

Important: these caps are for paper-trading validation. The bot now skips trades that exceed the configured risk budget instead of forcing one contract. Do not go live until the bot has been watched, backtested, and paper-traded.

Recommended small-account paper simulation:

```env
ACCOUNT_SIZE_OVERRIDE=200
```

This makes the $100K Alpaca paper account behave like Kenny's real starting bankroll for sizing decisions. Expect most spreads and all cash-secured puts to skip at this size; that is the point.

---

## Alerts

Discord webhook is configured in `agent/.env` as `DISCORD_WEBHOOK_URL`.

The bot sends `@everyone` alerts on:

- Trade submitted.
- Profit target hit.
- Stop-loss hit.

---

## Current State

| Item | Status |
| --- | --- |
| Alpaca paper account | Active, $100K virtual |
| Bot automation | Fixed and running through Task Scheduler |
| Task Scheduler bug | Fixed on 2026-06-17 |
| File logging | Active at `C:\Users\kenne\.vibe-trading\logs\options-bot.log` |
| Open positions | IWM iron condor from earlier session |
| Iron condor same-expiry bug | Fixed |
| Stop-loss | Added at -200% of credit for tracked trade groups |
| Unsafe leg-by-leg closes | Disabled for untracked positions |
| Trade group state file | Added at `C:\Users\kenne\.vibe-trading\options-trades.json` |
| Live trading confirmation gate | Added |
| Small-account paper sizing override | Added |
| Daily loss kill switch | Added |
| Bid/ask liquidity filter | Added |
| Manual approval mode | Added, defaults on for live |
| Anti-stacking per underlying | Added |
| Decision audit log | Added |
| Market-hours check | Added |
| VIX filter | Added |
| 20-day SMA filter | Added |
| PCR sentiment filter | Added |
| Earnings skip | Added |
| Discord alerts | Added |
| Discord webhook test | Sent successfully; confirm phone notification |
| P&L tracker | Added |
| Groq LLM key | Not required for standalone options bot scripts; only relevant to agent/LLM UI |
| Robinhood OAuth | Not done; stocks-only MCP currently |
| Backtest | Built and hardened; still approximate because it uses OHLCV plus Black-Scholes, not real historical option chains |

---

## Open Positions As Of 2026-06-17 Evening

IWM iron condor placed from earlier session:

- Short IWM 2026-07-24 $313 call, qty -2, P&L about +$32.
- Long IWM 2026-07-24 $315 call, qty +2, P&L about -$62.
- Long IWM 2026-07-31 $268 put, qty +2, P&L about +$114.
- Short IWM 2026-07-31 $270 put, qty -2, P&L about -$180.
- Net: about -$96 unrealized.

Note: this current open position still appears to have mixed expiries from before the same-expiry bug was fixed. Treat it as a legacy paper-trade position. It is not in the new grouped trade state file, so the bot will log it as `UNTRACKED` and will not auto-close individual legs. Manage it manually or close the whole structure deliberately.

---

## Architecture

```text
Kenny's PC
|-- Vibe-Trading/
|   |-- agent/.env
|   |-- strategies/
|   |   |-- iwm_options_bot.py
|   |   `-- pnl_tracker.py
|   `-- KNOWLEDGE/
|       `-- HANDOFF.md
|
|-- Task Scheduler
|   |-- IWM-Bot-Entry    -> 9:45am CT Mon-Fri
|   `-- IWM-Bot-Monitor  -> hourly 10am-3pm CT
|
|-- Logs
|   `-- C:\Users\kenne\.vibe-trading\logs\options-bot.log
|
`-- Alpaca Paper Account
```

---

## Task Scheduler Bug Fixed 2026-06-17

Problem:

The scheduled tasks had `>> log.log 2>&1` appended to the command. Task Scheduler was running Python directly, not through a shell, so those redirect tokens were passed to `argparse` as literal arguments. Python exited with code 2 and the bot did not run during market hours.

Fix:

Removed redirect arguments from both scheduled tasks using PowerShell `Set-ScheduledTask`. The bot now logs internally through Python logging.

---

## Commands Reference

```powershell
# Run bot across all symbols and strategies
python strategies/iwm_options_bot.py

# Single symbol
python strategies/iwm_options_bot.py --symbol NVDA

# Single strategy
python strategies/iwm_options_bot.py --strategy ic
python strategies/iwm_options_bot.py --strategy ps
python strategies/iwm_options_bot.py --strategy wheel

# Monitor/close only
python strategies/iwm_options_bot.py --monitor-only

# Paper-test as if the account only has $200
$env:ACCOUNT_SIZE_OVERRIDE="200"
python strategies/iwm_options_bot.py

# P&L report
python strategies/pnl_tracker.py --days 1
python strategies/pnl_tracker.py --days 30

# Watch live log
Get-Content "C:\Users\kenne\.vibe-trading\logs\options-bot.log" -Tail 50 -Wait
```

---

## Next Steps Priority Order

### 1. Watch First Real Multi-Symbol Run

Date: 2026-06-18 at 9:45am CT.

The bot should scan all seven symbols with all filters active. Watch Discord alerts and `options-bot.log`.

Confirm these lines appear during the run:

- `Account equity override active`
- `Daily risk: start=... actual=...`
- Any skipped trades should name the reason: risk budget, credit quality, liquidity, market filter, or daily loss guard.
- Check `C:\Users\kenne\.vibe-trading\logs\options-decisions.jsonl` after the run to see which candidates were submitted or blocked by exposure/per-run caps.

### 2. Verify Future Iron Condors Use One Expiry

Because the current open IWM condor is a legacy mixed-expiry paper position, verify the next generated IC candidate has all four legs on the same expiry before trusting the fix.

### 3. Validate Backtest Against Real Option Behavior

`strategies/backtest.py` is built and useful for directionally honest testing, but it is still an approximation because it uses OHLCV plus Black-Scholes instead of real historical option chains.

Before live money, validate it against:

- Entry frequency.
- Win rate.
- Max drawdown.
- Stop-loss behavior.
- 50% profit target behavior.
- Account growth with realistic commissions and slippage.
- Paper-trade fills from Alpaca.
- Real option bid/ask spreads around candidate strikes.

Future upgrade: use QuantConnect LEAN or a historical options data provider to replay actual option chains instead of modeled prices.

### 5. Paper Trade 30+ Days Minimum

Do not go live until:

- At least 30 days of paper trading.
- No broken order construction.
- No bad scheduler behavior.
- P&L tracker matches Alpaca.
- Exit logic has been observed in real market conditions.

### 6. Live Trading Later

Only after validation:

```env
ALPACA_PAPER=false
```

Live keys must come from Alpaca live account, not paper keys.

### 7. Robinhood OAuth Later

When ready:

```powershell
vibe-trading provider login robinhood
```

---

## Kenny's Goal And Reality Check

- Desired target: eventually $200+/day.
- Starting capital: $200 real money after paper validation.
- Realistic with $200: very limited. One defined-risk spread or IWM iron condor at a time.
- Meaningful daily income likely requires $2K-$5K+ and proven risk controls.
- First objective: avoid blowing up the account.

---

## Strategy Research Notes

| Strategy | Expected Win Rate | Notes |
| --- | --- | --- |
| 16-delta iron condor | 70-82% | Tastytrade-style premium selling research |
| SPY put credit spread | Reported 93% | Needs independent backtest before trust |
| General put credit spread | 70-80% | Highly dependent on regime and exits |
| Wheel | Steady income pattern | Assignment risk and capital requirements matter |
| Buying options long | Often 40-50% or worse | Not suitable as primary small-account strategy |

Core rules:

- Sell options, do not buy 0DTE lottery tickets.
- Close winners at 50% profit.
- Trade when IV Rank > 30.
- VIX sweet spot: 15-40.
- Sell puts only when price is above 20-day SMA.
- Skip if PCR > 2.0.
- Skip earnings.
- Respect stop-loss.

---

## Resources To Follow

- Tastytrade - premium selling education.
- Moon Dev - automated trading bots and open-source trading content.
- Humbled Trader - realistic beginner trading lessons.
- InTheMoney / Adam - options mechanics.
- Unusual Whales - options flow context.
- QuantConnect - backtesting and validation.

---

## Related Repos On Kenny's Desktop

| Repo | Path | Purpose |
| --- | --- | --- |
| Vibe-Trading | `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading` | Main bot |
| TradingAgents | `C:\Users\kenne\Desktop\MAILK-Repos\TradingAgents` | Multi-agent LLM research |
| FinceptTerminal | `C:\Users\kenne\Desktop\MAILK-Repos\FinceptTerminal` | C++20 terminal, many brokers |
