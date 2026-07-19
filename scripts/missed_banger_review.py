#!/usr/bin/env python3
"""
Read-only missed banger review.

For each social observation in the arb log, checks whether:
  1. Symbol was in the deep liquid universe (scanner coverage)
  2. Symbol passed the options liquidity gate (flip_shadow_eligible)
  3. Symbol appeared in flip shadow candidate log (bot saw a setup)
  4. What the actual price move was after the observation (via yfinance)

Output:
  data/missed_banger_review_log.jsonl
  ~/.vibe-trading/reports/missed-banger-review.json

No trading. No orders. Safe to run any time.
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Paths
SOCIAL_OBS_PATH  = Path.home() / ".vibe-trading" / "social-arb-observations.json"
DEEP_SCAN_LOG    = ROOT / "data" / "deep_liquid_universe_scan_log.jsonl"
LIQUIDITY_LOG    = ROOT / "data" / "options_liquidity_feasibility_log.jsonl"
FLIP_SHADOW_LOG  = ROOT / "data" / "flip_shadow_candidates_log.jsonl"
LOG_PATH         = ROOT / "data" / "missed_banger_review_log.jsonl"
REPORT_PATH      = Path.home() / ".vibe-trading" / "reports" / "missed-banger-review.json"

BANGER_MOVE_PCT  = 5.0    # 1-day move >= this % = "banger"
LOOKBACK_DAYS    = 30     # only review observations within this window


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------

def _load_jsonl_last(path: Path) -> dict | None:
    if not path.exists():
        return None
    for line in reversed(path.read_text(encoding="utf-8").splitlines()):
        line = line.strip()
        if line:
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    return None


def _load_jsonl_all(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
            if isinstance(row, dict):
                rows.append(row)
        except json.JSONDecodeError:
            continue
    return rows


def _load_social_observations(cutoff: date) -> list[dict]:
    if not SOCIAL_OBS_PATH.exists():
        return []
    try:
        data = json.loads(SOCIAL_OBS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    obs = data if isinstance(data, list) else data.get("observations", [])
    cutoff_str = cutoff.isoformat()
    return [
        o for o in obs
        if isinstance(o, dict)
        and str(o.get("date", o.get("observed_at", "")[:10])) >= cutoff_str
    ]


def _deep_scan_universe(rows: list[dict]) -> set[str]:
    syms: set[str] = set()
    for row in rows:
        for scan in row.get("scans", []):
            if isinstance(scan, dict):
                syms.add(str(scan.get("symbol", "")).upper())
        for sym in row.get("candidates", []):
            if isinstance(sym, str):
                syms.add(sym.upper())
    return syms


def _liquidity_qualified(rows: list[dict]) -> set[str]:
    syms: set[str] = set()
    for row in rows:
        for result in row.get("results", []):
            if isinstance(result, dict) and result.get("flip_shadow_eligible"):
                syms.add(str(result.get("symbol", "")).upper())
    return syms


def _flip_shadow_seen(rows: list[dict]) -> set[str]:
    syms: set[str] = set()
    for row in rows:
        sym = str(row.get("symbol", "")).upper()
        if sym:
            syms.add(sym)
        for cand in row.get("candidates", []):
            if isinstance(cand, dict):
                s = str(cand.get("symbol", "")).upper()
                if s:
                    syms.add(s)
    return syms


# ---------------------------------------------------------------------------
# Price move fetch
# ---------------------------------------------------------------------------

def _fetch_one_day_move(sym: str, obs_date_str: str) -> float | None:
    try:
        import yfinance as yf
        obs_date = date.fromisoformat(obs_date_str)
        end = obs_date + timedelta(days=3)
        t = yf.Ticker(sym)
        hist = t.history(start=obs_date_str, end=end.isoformat())
        if hist.empty or len(hist) < 2:
            return None
        open_px = float(hist["Open"].iloc[0])
        close_px = float(hist["Close"].iloc[0])
        if open_px <= 0:
            return None
        return round((close_px - open_px) / open_px * 100, 2)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Core review
# ---------------------------------------------------------------------------

def _classify_miss(
    sym: str,
    in_deep_scan: bool,
    liquidity_eligible: bool,
    bot_saw_setup: bool,
    move_pct: float | None,
) -> str:
    is_banger = move_pct is not None and abs(move_pct) >= BANGER_MOVE_PCT
    if not is_banger:
        return "not_a_banger"
    if bot_saw_setup:
        return "bot_covered"
    if not in_deep_scan:
        return "universe_gap"
    if not liquidity_eligible:
        return "liquidity_gate_blocked"
    return "setup_not_triggered"


def build_report(today: date | None = None) -> dict[str, Any]:
    today = today or date.today()
    cutoff = today - timedelta(days=LOOKBACK_DAYS)

    observations = _load_social_observations(cutoff)
    deep_rows     = _load_jsonl_all(DEEP_SCAN_LOG)
    liq_rows      = _load_jsonl_all(LIQUIDITY_LOG)
    shadow_rows   = _load_jsonl_all(FLIP_SHADOW_LOG)

    deep_universe  = _deep_scan_universe(deep_rows)
    liq_qualified  = _liquidity_qualified(liq_rows)
    bot_saw        = _flip_shadow_seen(shadow_rows)

    reviews: list[dict] = []
    seen: set[str] = set()

    for obs in observations:
        sym = str(obs.get("ticker", obs.get("symbol", ""))).upper()
        if not sym or sym in seen:
            continue
        seen.add(sym)

        obs_date = str(obs.get("date", obs.get("observed_at", "")[:10]))
        in_deep   = sym in deep_universe
        liq_ok    = sym in liq_qualified
        bot_ok    = sym in bot_saw
        move_pct  = _fetch_one_day_move(sym, obs_date) if obs_date else None
        verdict   = _classify_miss(sym, in_deep, liq_ok, bot_ok, move_pct)

        reviews.append({
            "symbol":              sym,
            "obs_date":            obs_date,
            "source":              obs.get("source", "unknown"),
            "mode":                obs.get("mode", "unknown"),
            "in_deep_scan_universe": in_deep,
            "liquidity_gate_eligible": liq_ok,
            "bot_saw_setup":       bot_ok,
            "one_day_move_pct":    move_pct,
            "is_banger":           move_pct is not None and abs(move_pct) >= BANGER_MOVE_PCT,
            "verdict":             verdict,
            "obs_note":            obs.get("notes", obs.get("note", "")),
        })

    bangers       = [r for r in reviews if r["is_banger"]]
    missed        = [r for r in bangers if r["verdict"] != "bot_covered"]
    universe_gaps = [r for r in missed if r["verdict"] == "universe_gap"]
    liq_blocks    = [r for r in missed if r["verdict"] == "liquidity_gate_blocked"]
    setup_misses  = [r for r in missed if r["verdict"] == "setup_not_triggered"]

    return {
        "date":           today.isoformat(),
        "generated_at":   datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "execution_mode": "read_only",
        "lookback_days":  LOOKBACK_DAYS,
        "banger_threshold_pct": BANGER_MOVE_PCT,
        "summary": {
            "observations_reviewed": len(reviews),
            "bangers_found":         len(bangers),
            "bot_covered":           len(bangers) - len(missed),
            "missed_bangers":        len(missed),
            "universe_gaps":         len(universe_gaps),
            "liquidity_blocked":     len(liq_blocks),
            "setup_not_triggered":   len(setup_misses),
        },
        "missed_bangers":   missed,
        "bot_covered":      [r for r in bangers if r["verdict"] == "bot_covered"],
        "not_bangers":      [r for r in reviews if not r["is_banger"]],
        "all_reviews":      reviews,
    }


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def log_report(report: dict, log_path: Path = LOG_PATH) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    if log_path.exists():
        for line in log_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                if isinstance(row, dict):
                    rows.append(row)
            except json.JSONDecodeError:
                continue
    today_str = report.get("date", "")
    deduped = [r for r in rows if r.get("date") != today_str]
    deduped.append(report)
    log_path.write_text("".join(json.dumps(r) + "\n" for r in deduped), encoding="utf-8")


def write_report(report: dict, path: Path = REPORT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_last_report(log_path: Path = LOG_PATH) -> dict | None:
    return _load_jsonl_last(log_path)


# ---------------------------------------------------------------------------
# Print
# ---------------------------------------------------------------------------

def print_report(report: dict) -> None:
    s = report["summary"]
    print(f"\nMissed Banger Review | {report['date']} | lookback={report['lookback_days']}d")
    print("=" * 68)
    print(
        f"Reviewed={s['observations_reviewed']}  Bangers={s['bangers_found']}  "
        f"Bot_covered={s['bot_covered']}  Missed={s['missed_bangers']}"
    )
    if s["missed_bangers"]:
        print(f"\nMissed ({s['missed_bangers']}):")
        for r in report["missed_bangers"]:
            move = f"{r['one_day_move_pct']:+.1f}%" if r["one_day_move_pct"] is not None else "n/a"
            print(
                f"  {r['symbol']:<6} {r['obs_date']}  move={move:<8} "
                f"verdict={r['verdict']}  src={r['source']}"
            )
        print(f"\n  Universe gaps:      {s['universe_gaps']}  → add to deep scan universe")
        print(f"  Liquidity blocked:  {s['liquidity_blocked']}  → gate correct, monitor")
        print(f"  Setup not triggered:{s['setup_not_triggered']}  → review entry conditions")
    else:
        print("No missed bangers in lookback window.")
    print(f"\nJSON: {REPORT_PATH}\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Missed banger review. Read-only.")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()

    print(f"Loading social observations (last {LOOKBACK_DAYS} days)...")
    report = build_report()
    print_report(report)
    if not args.no_write:
        log_report(report)
        write_report(report)
        print(f"Logged to {LOG_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
