---
name: vibe-trading-shadow-scanners
description: Use when adding or modifying read-only scanners, shadow loggers, signal registry entries, evidence collection, or promotion gates.
---

# Vibe-Trading Shadow Scanners

## What Shadow Scanners Do
Log hypotheses and market observations **without placing orders**. They build the evidence record needed to promote a signal to execution.

## Promotion Gate
A signal cannot reach execution until:
- 30 trading days of shadow logs
- 10+ shadow samples for the specific symbol
- Entry in `rules/signal_promotion_rules.md`
- Manual review and explicit approval

**Gate failure ≠ remove from shadow.** Keep logging. The evidence window must fill.

## Adding a New Scanner — Checklist
1. Add script to `scripts/<name>_shadow_logger.py`
2. Log to `data/<name>_log.jsonl` (append, never overwrite)
3. Write report to `~/.vibe-trading/reports/<name>.json`
4. Add to `research/signal_registry.json` with `execution_enabled: false`
5. Add health entry to `scripts/signal_stack_health_report.py` SIGNALS list
6. Add PS1 runner to `scripts/run_<name>.ps1`
7. Register Windows Task Scheduler task under `\VibeTrade\`
8. Write at least 2 tests in `agent/tests/test_<name>.py`
9. Run `python scripts/execution_gate_audit.py --print` — must still pass

## Market-Closed Guard (required for all intraday scanners)
```python
_NYSE_HOLIDAYS = { date(2026, 7, 4), date(2026, 9, 7), ... }

def _is_market_closed(d: date) -> bool:
    return d.weekday() >= 5 or d in _NYSE_HOLIDAYS

def build_report(...):
    if _is_market_closed(trading_day):
        return {"status": "market_closed", "scans": [], "execution_enabled": False}
```
Added to `opening_range_breadth_scanner.py` and `premarket_ema_retest_shadow_logger.py` after July 4/5 errors.

## Health Check Staleness Rule
`scripts/signal_stack_health_report.py` uses `_last_weekday(today)` as staleness cutoff.
- Saturday → Friday cutoff (Friday's run = ok, not stale)
- Sunday → Friday cutoff
- Prevents weekend false-alarm STALE=31 flood

## Active Shadow Scanners (as of 2026-07-06)
38 signals tracked. Run `python scripts/signal_stack_health_report.py --no-write` for full list.

## Red Flags
- Scanner that appends to log but never writes to `~/.vibe-trading/reports/` — health checker can't find it.
- Scanner missing `execution_enabled: False` in output dict.
- Scanner that raises on weekends/holidays instead of returning `market_closed`.
