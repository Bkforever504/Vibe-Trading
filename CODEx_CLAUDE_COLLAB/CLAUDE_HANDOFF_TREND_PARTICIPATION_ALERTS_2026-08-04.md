# Claude Handoff — 2026-08-04 Trend Participation Shadow + Alert Gap

Project: `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading`

## Session Summary

Aug 4 was a record-risk-on / all-time-high day. Short-premium bots (IWM Options Bot, Flip Bot short side) correctly stood aside — IV was below realized vol for SPY, QQQ, TSLA, NVDA, AAPL, PLTR. The engines did their job. The gap: no bullish debit spread lane existed to capture aligned trend days.

Kenny's directive: "If you can't find the edge, create it. We have to be alerted on all the big moves."

## What Codex Built Today

### `scripts/trend_participation_shadow.py`

Forward-only call debit spread shadow lane. Key facts:

- Symbols: `SPY`, `QQQ`, `NVDA`
- Strategy: call debit spread, 7–21 DTE, long delta 0.50–0.70, short delta 0.25–0.40
- Max debit: `$250` per spread (1 contract)
- Profit target: 50% of max profit
- Stop: 50% of debit paid
- Hard exits: 7-day calendar max, or 2 DTE
- Entry gates (ALL required):
  - `htf.primary_bias == "bullish"` AND `htf.intraday_alignment == "aligned"`
  - `opening.state == "above_opening_range"`
  - `force.classification in {"bullish", "bullish_lean"}`
  - `force.risk_veto.active == False`
  - No high-impact catalyst or caution window today
- `execution_enabled = False` / `can_submit_orders = False` — hard-coded, no order path
- Evidence start: `2026-08-05` (Aug 4 permanently excluded as design day)
- Promotion gate: 60 dev + 30 chronological holdout outcomes under doubled fees
- Logs to: `data/trend_participation_shadow_log.jsonl`
- Report to: `~/.vibe-trading/reports/trend-participation-shadow.json`

Entry scheduler: `8:47 AM CT` and `2:02 PM CT`
Monitor scheduler: every 5 min, `8:50 AM–2:55 PM CT`
Schedule governance: 59/59 aligned. Both Task Scheduler smoke runs returned 0.

### `research/ATH_MISSED_OPPORTUNITY_POSTMORTEM_2026-08-04.md`

Root cause analysis. Key conclusion: short-premium engine was correct to stand aside (IV < RV). Gap was candidate-generation coverage for bullish debit structures. Trend participation shadow closes that coverage gap.

### `research/TREND_PARTICIPATION_SHADOW_PREREGISTRATION_2026-08-04.md`

Formal preregistration document with evidence boundary, promotion criteria, and what this does/does not prove.

## THE CRITICAL MISSING PIECE — Discord Alerts

**Kenny's core request is NOT yet implemented: real-time alerts on big moves.**

The shadow scanner generates candidates in JSONL but sends zero Discord notifications. Kenny has no way to know when the system sees a high-conviction bullish setup forming.

### What to build next session (P0)

Add Discord alert in `scripts/trend_participation_shadow.py` when `build_entry_report()` produces a qualified candidate.

Alert pattern (same as `strategies/iwm_options_bot.py` / `strategies/flip_bot.py`):

```python
import requests

DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "")

def _send_discord_alert(message: str) -> None:
    if not DISCORD_WEBHOOK:
        return
    try:
        requests.post(DISCORD_WEBHOOK, json={"content": message}, timeout=5)
    except Exception:
        pass
```

Alert fields to include per candidate:
- Symbol
- Strategy (call debit spread)
- Entry debit / max loss in dollars
- Reward/risk ratio
- What fired it: which gates passed (opening range breakout, HTF aligned, market force score)
- Shadow-only disclaimer

Example message format:
```
@everyone SHADOW ALERT [SPY] Call Debit Spread candidate
Entry debit: $1.42 | Max loss: $142 | R/R: 2.08
Gates: HTF bullish+aligned | Above opening range | Market force bullish-lean
SHADOW ONLY — no order submitted. Evidence building.
```

Also consider: a **morning regime alert** (separate from candidate alerts) that fires at `9:31 AM CT` when:
- Market force = bullish or bullish_lean
- SPY above opening range
- HTF aligned bullish

This gives Kenny situational awareness even before a spread qualifies.

### Where to add it

File: `scripts/trend_participation_shadow.py`
Function: `build_entry_report()` — after the `_append(row, log_path)` call for each candidate

Also add monitor alert when a candidate hits profit target or stop (same as IWM bot close alerts).

## Existing Discord Webhook Reference

Webhook URL stored in `agent/.env` as `DISCORD_WEBHOOK_URL`. Load via:
```python
from dotenv import load_dotenv
load_dotenv(ROOT / "agent" / ".env")
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "")
```

Pattern used in `strategies/iwm_options_bot.py` lines ~60–80 for reference.

## Account Status (Aug 4 EOD)

From prior session context:
- Equity: `$89,601.06`
- No open IWM options positions
- No open Flip Bot trades
- Execution audit: `passed=True`, `issues=0`, `warnings=1` (concentration monitor read-only Alpaca — expected)

## Signal Registry Status

- 56 signals registered (was 54, grew with challenge simulator + shadow candidates)
- 2 execution-capable: `flip_bot.py` (paper), `iwm_options_bot.py` (paper)
- `trend_participation_shadow.py` should be registered as `shadow_candidate` / `read_only`

## Do Not Do

- Do not wire trend participation shadow to live orders
- Do not promote based on Aug 4 day (excluded as design day)
- Do not loosen short-premium gates because of ATH day — the bots were correct to stand aside
- Do not add X API credentials or PMXT without explicit Kenny approval
- Do not commit `agent/.env`

## Priority Queue for Next Session

**P0 (do first):**
1. Add Discord alert to `trend_participation_shadow.py` when candidate qualifies
2. Add monitor close alert (profit target hit / stop hit)
3. Optional: morning regime alert at 9:31 AM CT when force=bullish + SPY above range

**P1:**
1. Register `trend_participation_shadow.py` in `research/signal_registry.json` as `shadow_candidate`
2. Run `scripts/execution_gate_audit.py --print` to confirm issues=0 after alert wiring
3. Add trend participation to `scripts/signal_stack_grades.py` and daily CSV export

**P2:**
1. IAF 10-date replay comparison for `iaf_qqq_gld_probe.py`
2. Monitor CBOE VIX source for 5+ days to confirm daily freshness
3. Hurst calibration check after 30 days (if SPY consistently higher H than QQQ/IWM in bull markets → switch to log-return differences)

## Commands

Run entry (manual test):
```powershell
cd "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
uv run --no-project --with alpaca-py --with yfinance --with pandas python scripts\trend_participation_shadow.py --mode entry --print
```

Run monitor:
```powershell
uv run --no-project --with alpaca-py --with yfinance --with pandas python scripts\trend_participation_shadow.py --mode monitor --print
```

Run execution audit:
```powershell
uv run --no-project python scripts\execution_gate_audit.py --print --fail-on-issues
```

Check today logs:
```powershell
Get-Content C:\Users\kenne\.vibe-trading\logs\options-bot.log -Tail 80
Get-Content C:\Users\kenne\.vibe-trading\logs\flip-bot.log -Tail 80
Get-Content C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading\data\trend_participation_shadow_log.jsonl
```

## Bottom Line

Codex correctly identified the payoff coverage gap and built the right shadow lane. The short-premium bots did their job on Aug 4 — don't second-guess those gates. The missing piece is pure: **Discord alerts so Kenny gets pinged when the system sees a qualified bullish setup**. That's a 30-minute build. Next session: wire the alerts, run the audit, ship it.
