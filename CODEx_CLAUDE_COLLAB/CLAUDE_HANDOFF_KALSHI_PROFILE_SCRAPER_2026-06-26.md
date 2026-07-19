# Claude Handoff - Kalshi Public Profile Scraper

Date: 2026-06-26
Project: `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading`
Mode: paper-only / read-only research. No live copy execution.

## What Codex Implemented

### New Kalshi Public Profile Scraper

File:
`strategies/kalshi_profile_scraper.py`

Purpose:
- Read public Kalshi social profile data without logging in.
- Pull public metrics and public closed holdings.
- Convert closed holdings into `NormalisedTrade` objects.
- Feed those trades into `derive_all_metrics()`.
- Upsert scored profiles into `C:\Users\kenne\.vibe-trading\copy-trader-profiles.json`.

Discovered public endpoints from Chrome/network/app chunk inspection:
- `https://api.elections.kalshi.com/v1/social/profile/metrics?nickname=<handle>`
- `https://api.elections.kalshi.com/v1/social/profile/holdings?nickname=<handle>&closed_positions=true&limit=100`
- `https://api.elections.kalshi.com/v1/social/trades?nickname=<handle>&page_size=50`

Important endpoint behavior:
- Many top leaderboard accounts expose only aggregate metrics and hide holdings/trades.
- Hidden response example: `visibility_state: "hidden"`, empty holdings/trades.
- Visible response example: `weatherman.allday` exposes closed holdings.

### Copy-Trader Scoring Update

File:
`strategies/copy_trader_watchlist.py`

Change:
- `source == "public_profile"` now earns the same "real public history" credit as public wallets/exported history, with reason:
  `public profile history`
- `source == "public_leaderboard"` remains guarded:
  - flag: `missing exported trade history`
  - flag: `public leaderboard lacks win rate`

This preserves the key safety rule:
Leaderboard screenshots are not copyable edge. Public closed-position/trade history can be scored.

## Tests Added / Updated

New:
`agent/tests/test_kalshi_profile_scraper.py`

Covers:
- `holding_to_trades()` converts Kalshi closed holdings into `NormalisedTrade`
- PnL unit conversion: Kalshi social PnL value / 10,000 = dollars
- Event ticker date parsing, e.g. `KXHIGHTSATX-26JUN26-B92.5` -> `2026-06-26`
- `build_profile_report()` computes win rate as `count(pnl > 0) / len(closed positions)`
- `upsert_kalshi_public_profile()` writes verified public profile history

Updated:
`agent/tests/test_copy_trader_watchlist.py`

Added:
- `test_public_profile_history_counts_as_public_platform_history`

Verification command:
```powershell
uv run --no-project --with pytest --with requests --with python-dotenv python -m pytest agent\tests\test_kalshi_profile_scraper.py agent\tests\test_copy_trader_watchlist.py agent\tests\test_trade_history_importer.py -q
```

Result:
`32 passed`

## Live Read-Only Findings

Command:
```powershell
python strategies\kalshi_profile_scraper.py --username weatherman.allday --max-pages 3 --append-profiles --print
```

Result:
- `visibility_state`: `visible`
- sampled closed holdings: `300`
- win rate: `0.01`
- realized P&L from visible closed holdings: `-$2,730.65`
- profit factor: `0.0792`
- trade frequency: `hyperactive`

Copy-trader report correctly blocks it:
- status: `review`
- risk flags:
  - `edge too small after fees`
  - `overtrading risk`
- suggested copy size: `$0`

Command:
```powershell
python strategies\kalshi_profile_scraper.py --username lad. --max-pages 1 --print
```

Result:
- Aggregate metrics visible
- `visibility_state`: `hidden`
- No closed holdings returned
- Do not approve for copying based on leaderboard P&L alone.

## Runtime Files Updated

Updated by live read-only run:
- `C:\Users\kenne\.vibe-trading\copy-trader-profiles.json`
- `C:\Users\kenne\.vibe-trading\reports\kalshi-profile-scraper-report.json`
- `C:\Users\kenne\.vibe-trading\reports\copy-trader-watchlist.json`

## Claude Next Tasks

### P0 - Validate More Public Kalshi Profiles

Find public profiles with visible closed holdings/trades. Use the leaderboard to identify candidates, but only trust profiles where:
- `visibility_state == "visible"`
- `trades >= 100`
- `win_rate >= 0.55`
- `profit_factor >= 1.2`, ideally `>= 1.5`
- `trade_frequency` is `selective` or `moderate`
- no `edge too small after fees` or `overtrading risk` flags

Run:
```powershell
python strategies\kalshi_profile_scraper.py --username <handle> --max-pages 5 --append-profiles --print
python scripts\copy_trader_watchlist_report.py --print
```

### P0 - Do Not Follow/Copy Automatically

No live following, no auto-copy execution, no Kalshi trading. Only paper-watch candidates with verified public/exported history.

### P1 - Add Batch Import Script

Recommended file:
`scripts/kalshi_profile_scraper_report.py`

Useful CLI:
```powershell
python scripts\kalshi_profile_scraper_report.py --usernames lad.,weatherman.allday,user.x --append-profiles --print
```

The strategy module already has a single-user CLI, so this is convenience only.

### P1 - Improve Hidden Profile Reporting

If `visibility_state == "hidden"` and aggregate P&L is high, add explicit report field:
```json
"copy_status": "blocked_hidden_history"
```

Reason:
High public P&L without public closed-position P&L cannot produce a real win rate or drawdown.

## Safety Notes

- Do not use private keys or Kalshi API trading credentials for this scraper.
- Do not click `Follow` in Chrome without Kenny's explicit action-time confirmation.
- Do not approve copy trading from:
  - viral screenshots
  - raw leaderboard P&L
  - hidden trade histories
  - accounts with hyperactive frequency or negative visible edge

Current confidence:
- Kalshi endpoint discovery: 9/10
- Scraper correctness for visible holdings: 8.5/10
- Copy-trader safety gate: 9/10
- Any specific Kalshi trader copy-readiness: low until we find visible profiles with strong metrics
