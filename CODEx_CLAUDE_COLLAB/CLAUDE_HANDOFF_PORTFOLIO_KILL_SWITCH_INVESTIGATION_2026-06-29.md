# Claude Handoff - Portfolio Kill Switch Investigation 2026-06-29

## Context
Kenny asked whether the bot caught the large QQQ/SPY call move shown on social media. Codex verified: yes, the Flip Bot caught the same bull trend via SPY calls, but a portfolio kill switch triggered too early and blocked additional entries after the initial trade.

## Confirmed Bot Outcome
Flip Bot trade on 2026-06-29:
- Entry: SPY260629C00738000, buy 5 contracts
- Entry time: 2026-06-29 10:00:09 CT approx / 15:00:09Z
- Fill: USD 1.34
- Exit: sell 5 contracts
- Exit time: 2026-06-29 12:15:11 CT approx / 17:15:11Z
- Alpaca order avg exit: USD 2.37; bot logged mid/exit USD 2.41
- Bot logged PnL: +USD 535.00, +79.9%, profit target hit

The bot saw QQQ correctly:
- Around 10:00 CT: Bull trend SPY=9/10, QQQ=9/10, breadth confirmed ['SPY','QQQ']
- It executed SPY as the trade vehicle, not QQQ.

## Current Alpaca State Checked By Codex
- Equity after trade: around USD 88,756.14
- Open orders: 0
- Open positions: IWM put spread legs only
- IWM spread at last check was small net positive by leg unrealized PnL, and options bot log showed +USD 24 / +15.4% of credit at 15:00 CT.

## Why Entries Were Blocked
Portfolio kill switch file exists:
C:\Users\kenne\.vibe-trading\PORTFOLIO_KILL_SWITCH.json

Payload:
- daily_pnl_dollars: -112.0
- max_daily_loss_dollars: 50.0
- triggered_at: 2026-06-29T15:05:15Z
- source: portfolio_monitor
- manual_reset_required: true

Portfolio monitor log:
- 09:50 CT: Portfolio PnL today: -USD 24.00, limit -USD 50.00
- 10:05 CT: Portfolio PnL today: -USD 112.00, equity USD 88,037.24, limit -USD 50.00
- 10:05 CT: monitor exit=2, kill switch created
- 10:20 onward: monitor reports kill switch already active

Flip Bot after that:
- Continued monitoring open SPY call
- Still exited SPY winner at profit target
- Opening entries were blocked by portfolio_kill_switch

Important: this was not a missed signal. It was a risk gate blocking add-on/re-entry after a temporary unrealized drawdown.

## Root Cause Assessment
### Strategic / Configuration Root Cause
PORTFOLIO_MAX_DAILY_LOSS_DOLLARS=50 is too tight for an approximately USD 88k Alpaca paper account and options strategies.

At 10:00 CT the bot opened 5 SPY 0DTE calls at USD 1.34. At 10:15 the same contract was temporarily down about -20.5% in bot logs, while the IWM spread was also fluctuating. A temporary unrealized drawdown in options marks was enough to breach a USD 50 absolute loss limit. Later the SPY contract recovered and hit profit target.

Recommended paper kill switch range:
- Minimum practical: USD 500
- Better for current paper equity: 0.75%-1.0% of equity, about USD 660-880
- Still keep per-trade risk caps and bot-level guards intact.

### Code-Level Bug / Design Flaw
strategies/portfolio_monitor.py imports from strategies.portfolio_guard before calling load_repo_env().

Current order:
1. imports portfolio_guard constants
2. computes PORTFOLIO_MAX_DAILY_LOSS_DOLLARS inside portfolio_guard from process env/default
3. only later calls load_repo_env()

Impact: changing gent/.env may not affect the imported constant if the process env did not already contain it. Today it matched the default/env at 50, but this must be fixed before relying on env changes.

Fix direction:
- Load gent/.env before importing PORTFOLIO_MAX_DAILY_LOSS_DOLLARS, or
- Better: make portfolio_guard read the env dynamically through a function like portfolio_max_daily_loss_dollars() instead of a module import-time constant.

## Recommended P0 Fixes For Claude
1. Fix env load ordering / dynamic config:
   - In strategies/portfolio_guard.py, replace import-time constant usage with a function:
     def portfolio_max_daily_loss_dollars() -> float: return float(os.getenv('PORTFOLIO_MAX_DAILY_LOSS_DOLLARS', '50.0'))
   - Make 	rigger_portfolio_kill() and check_and_maybe_kill() use the function unless explicit override supplied.
   - Update tests.

2. Change default paper portfolio loss limit:
   - In gent/.env, set PORTFOLIO_MAX_DAILY_LOSS_DOLLARS=750 for current approximately USD 88k paper account.
   - If you want more conservative: USD 500.
   - Do not use USD 50 for options paper trading unless account size is near USD 5k.

3. Add a same-day recovery-aware option before blocking fresh entries:
   Conservative variant:
   - Keep kill switch hard once triggered, but only trigger after two consecutive monitor polls below threshold OR a larger emergency threshold.
   Example:
   - soft warning at -USD 500
   - hard kill at -USD 750 sustained across 2 polls or immediate emergency kill at -USD 1,500
   This prevents one bad option mark from freezing a profitable trend day.

4. Improve portfolio monitor log output:
   - Log current open positions and unrealized PnL when kill switch triggers.
   - Log source: Alpaca portfolio history latest equity vs account equity.
   - Current PowerShell wrapper prints uv : ... NativeCommandError noise when Python logs warnings to stderr. Clean wrapper so warnings do not look like task failures.

5. Add dashboard panel:
   - Show portfolio kill switch active/inactive
   - Show trigger reason, daily PnL, threshold, triggered_at
   - Show reset instruction
   The dashboard already has bot execution status, but this incident shows the portfolio kill state needs first-class visibility.

## Manual Reset Warning
Do NOT delete PORTFOLIO_KILL_SWITCH.json blindly while market is open. Review open positions first. Today market is after close, so tomorrow morning reset may be appropriate after updating the limit/config. If reset is needed: delete the file after confirming no unwanted open orders and acceptable positions.

## Additional Observation
The IWM options bot correctly opened a new IWM put spread at 09:45 CT:
- IWM 289/286 put spread
- Qty 3
- Credit USD 0.52, total credit USD 156
- Confidence 9/10
- Stop loss pct -1.0
It was not the cause of a realized loss; it contributed mark-to-market volatility but later was positive.

## Bottom Line
The bot caught the day and made money. The blocker was not signal quality. The blocker was an overly tight, absolute, unrealized-PnL portfolio kill switch plus import-time env config fragility.
