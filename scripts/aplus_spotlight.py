#!/usr/bin/env python3
"""A+ setup spotlight — fire loud Discord + dashboard signal when confirmed A+ setups appear.

Reads intraday opportunity radar log, finds fresh actionable A+ setups
(grade A, score >= 93, confirmation_stage == completed_5m_confirmed,
actionable_for_ranking True, complete geometry), and sends a red-bordered
Discord embed with @here mention and rich fields.

Tracks previously-alerted (symbol, direction, setup, trigger, invalidation)
tuples in a state file so the same setup is not re-alerted every run.

Read-only. No order authority.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.notifier import send_discord_embed

RADAR_LOG = ROOT / "data" / "intraday_opportunity_radar_log.jsonl"
SPOTLIGHT_LOG = ROOT / "data" / "aplus_spotlight_log.jsonl"
SPOTLIGHT_REPORT = Path.home() / ".vibe-trading" / "reports" / "aplus-spotlight.json"
ALERTED_STATE = Path.home() / ".vibe-trading" / "state" / "aplus_alerted.json"

BPLUS_LOG = ROOT / "data" / "bplus_spotlight_log.jsonl"
BPLUS_REPORT = Path.home() / ".vibe-trading" / "reports" / "bplus-spotlight.json"
BPLUS_ALERTED_STATE = Path.home() / ".vibe-trading" / "state" / "bplus_alerted.json"

MIN_SCORE = 93.0
MAX_SIGNAL_AGE_MINUTES = 15.0
EMBED_COLOR_APLUS = 0xE53935  # red — highest attention
EMBED_COLOR_BPLUS = 0xFFB300  # amber — high attention, secondary tier
CONFIRMED_STATES = {"bullish_confirmed", "bearish_confirmed"}
ET = ZoneInfo("America/New_York")

TIERS: dict[str, dict[str, Any]] = {
    "aplus": {
        "label": "A+",
        "min_score": 93.0,
        "allowed_grades": {"A"},
        "color": EMBED_COLOR_APLUS,
        "content_prefix": "@here  ★ **A+ TRADE ALERT** ★",
        "title_prefix": "🚨  A+ SETUP",
        "state_path": ALERTED_STATE,
        "log_path": SPOTLIGHT_LOG,
        "report_path": SPOTLIGHT_REPORT,
        "provider": "aplus_spotlight",
    },
    "bplus": {
        "label": "B+",
        "min_score": 75.0,
        "allowed_grades": {"B+", "A-"},
        "color": EMBED_COLOR_BPLUS,
        "content_prefix": "★ **B+ trade watch** ★",
        "title_prefix": "⚡  B+ SETUP",
        "state_path": BPLUS_ALERTED_STATE,
        "log_path": BPLUS_LOG,
        "report_path": BPLUS_REPORT,
        "provider": "bplus_spotlight",
    },
}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _walk_candidates(obj: Any) -> Iterable[dict[str, Any]]:
    if isinstance(obj, dict):
        if obj.get("symbol") and obj.get("grade") and obj.get("score") is not None:
            yield obj
            return
        for value in obj.values():
            yield from _walk_candidates(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _walk_candidates(value)


def _parse_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ET)
    return parsed


def _is_recent(value: Any, *, now: datetime, max_age_minutes: float) -> bool:
    observed = _parse_timestamp(value)
    if observed is None:
        return False
    age_minutes = (now.astimezone(timezone.utc) - observed.astimezone(timezone.utc)).total_seconds() / 60.0
    return -2.0 <= age_minutes <= max_age_minutes


def _is_tier_actionable(row: Mapping[str, Any], tier: Mapping[str, Any]) -> bool:
    grade = str(row.get("grade") or "").upper()
    if grade not in {g.upper() for g in tier["allowed_grades"]}:
        return False
    score = row.get("score")
    if not isinstance(score, (int, float)) or float(score) < float(tier["min_score"]):
        return False
    if not row.get("actionable_for_ranking"):
        return False
    if str(row.get("confirmation_stage") or "") != "completed_5m_confirmed":
        return False
    pac = row.get("price_action_confirmation") or {}
    if isinstance(pac, dict) and str(pac.get("state") or "") not in CONFIRMED_STATES:
        return False
    entry, invalidation, target = _extract_levels(row)
    if entry is None or invalidation is None or target is None:
        return False
    if not all(math.isfinite(level) for level in (entry, invalidation, target)):
        return False
    direction = str(row.get("direction") or "").lower()
    if direction.startswith("bull"):
        return invalidation < entry < target
    if direction.startswith("bear"):
        return target < entry < invalidation
    return False


def _is_aplus_actionable(row: Mapping[str, Any]) -> bool:
    return _is_tier_actionable(row, TIERS["aplus"])


def _extract_levels(row: Mapping[str, Any]) -> tuple[float | None, float | None, float | None]:
    tl = row.get("trade_levels") or {}
    entry = row.get("entry") if row.get("entry") is not None else tl.get("confirmation_trigger")
    invalidation = row.get("invalidation") if row.get("invalidation") is not None else tl.get("invalidation")
    target = row.get("target") if row.get("target") is not None else tl.get("target_2r")
    try:
        return (
            float(entry) if entry is not None else None,
            float(invalidation) if invalidation is not None else None,
            float(target) if target is not None else None,
        )
    except (TypeError, ValueError):
        return (None, None, None)


def _fingerprint(row: Mapping[str, Any]) -> str:
    entry, invalidation, _ = _extract_levels(row)
    confirmation = row.get("price_action_confirmation") or {}
    completed_at = confirmation.get("bar_completed_at") if isinstance(confirmation, Mapping) else None
    return "|".join(
        [
            str(row.get("symbol") or "").upper(),
            str(row.get("direction") or "").lower(),
            str(row.get("setup") or ""),
            f"{entry:.4f}" if entry is not None else "",
            f"{invalidation:.4f}" if invalidation is not None else "",
            str(completed_at or ""),
        ]
    )


def _load_alerted(now: datetime | None = None, state_path: Path = ALERTED_STATE) -> set[str]:
    if not state_path.exists():
        return set()
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return set()
    today = (now or datetime.now(ET)).astimezone(ET).date().isoformat()
    if str(data.get("date")) != today:
        return set()
    return set(data.get("fingerprints", []))


def _atomic_write_json(path: Path, payload: Mapping[str, Any], *, indent: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=indent)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _save_alerted(fingerprints: set[str], now: datetime | None = None, state_path: Path = ALERTED_STATE) -> None:
    today = (now or datetime.now(ET)).astimezone(ET).date().isoformat()
    _atomic_write_json(state_path, {"date": today, "fingerprints": sorted(fingerprints)})


def collect_fresh_for_tier(
    tier: Mapping[str, Any],
    radar_log: Path = RADAR_LOG,
    already_alerted: set[str] | None = None,
    *,
    now: datetime | None = None,
    max_age_minutes: float = MAX_SIGNAL_AGE_MINUTES,
    excluded_fingerprints: set[str] | None = None,
) -> list[dict[str, Any]]:
    already_alerted = already_alerted or set()
    excluded_fingerprints = excluded_fingerprints or set()
    now = (now or datetime.now(ET)).astimezone(ET)
    today = now.date().isoformat()
    reports = _read_jsonl(radar_log)
    seen_fp: set[str] = set()
    fresh: list[dict[str, Any]] = []
    for report in reversed(reports):
        as_of = str(report.get("as_of_et") or report.get("timestamp") or "")
        if not as_of.startswith(today):
            continue
        if not _is_recent(as_of, now=now, max_age_minutes=max_age_minutes):
            continue
        for candidate in _walk_candidates(report):
            if not _is_tier_actionable(candidate, tier):
                continue
            confirmation = candidate.get("price_action_confirmation") or {}
            completed_at = confirmation.get("bar_completed_at") if isinstance(confirmation, Mapping) else None
            if not _is_recent(completed_at, now=now, max_age_minutes=max_age_minutes):
                continue
            fp = _fingerprint(candidate)
            if not fp or fp in seen_fp or fp in already_alerted or fp in excluded_fingerprints:
                continue
            seen_fp.add(fp)
            entry, invalidation, target = _extract_levels(candidate)
            fresh.append(
                {
                    "fingerprint": fp,
                    "tier": tier["label"],
                    "symbol": str(candidate.get("symbol") or "").upper(),
                    "grade": str(candidate.get("grade") or ""),
                    "direction": str(candidate.get("direction") or ""),
                    "setup": str(candidate.get("setup") or ""),
                    "score": float(candidate.get("score") or 0.0),
                    "ranking_score": candidate.get("ranking_score"),
                    "entry": entry,
                    "invalidation": invalidation,
                    "target": target,
                    "risk_per_share": abs(entry - invalidation) if entry is not None and invalidation is not None else None,
                    "reward_per_share": abs(target - entry) if entry is not None and target is not None else None,
                    "as_of": as_of,
                    "catalyst_headlines": candidate.get("catalyst_headlines") or [],
                    "avg_dollar_volume_20d": candidate.get("avg_dollar_volume_20d"),
                    "state": candidate.get("state"),
                    "confirmation_stage": candidate.get("confirmation_stage"),
                    "confirmation_completed_at": completed_at,
                    "market_context": candidate.get("market_context") if isinstance(candidate.get("market_context"), dict) else {},
                }
            )
    fresh.sort(key=lambda row: (-(row.get("ranking_score") or row.get("score") or 0.0), row["symbol"]))
    return fresh


def collect_fresh_aplus(
    radar_log: Path = RADAR_LOG,
    already_alerted: set[str] | None = None,
    *,
    now: datetime | None = None,
    max_age_minutes: float = MAX_SIGNAL_AGE_MINUTES,
) -> list[dict[str, Any]]:
    return collect_fresh_for_tier(
        TIERS["aplus"],
        radar_log=radar_log,
        already_alerted=already_alerted,
        now=now,
        max_age_minutes=max_age_minutes,
    )


def _direction_emoji(direction: str) -> str:
    d = direction.lower()
    if d.startswith("bull"):
        return "▲"
    if d.startswith("bear"):
        return "▼"
    return "◆"


def format_setup_fields(setup: Mapping[str, Any]) -> list[dict[str, Any]]:
    entry = setup.get("entry")
    stop = setup.get("invalidation")
    target = setup.get("target")
    risk = setup.get("risk_per_share")
    reward = setup.get("reward_per_share")
    rr = (reward / risk) if risk and reward else None
    catalyst_lines = []
    for headline in (setup.get("catalyst_headlines") or [])[:2]:
        if isinstance(headline, dict):
            catalyst_lines.append(str(headline.get("headline") or headline.get("title") or ""))
        else:
            catalyst_lines.append(str(headline))
    catalyst = " · ".join(line for line in catalyst_lines if line) or "no headline"
    grade_display = setup.get("grade") or setup.get("tier") or "?"
    context = setup.get("market_context") if isinstance(setup.get("market_context"), Mapping) else {}
    sector = str(context.get("sector_etf") or context.get("sector") or "unavailable")
    sector_alignment = str(context.get("sector_alignment") or "unavailable")
    qqq_spy = context.get("qqq_vs_spy_pct")
    qqq_regime = str(context.get("qqq_spy_regime") or "unavailable")
    context_value = (
        f"```\nSector {sector} · {sector_alignment}\nQQQ-SPY {float(qqq_spy):+.3f}% · {qqq_regime}\n```"
        if isinstance(qqq_spy, (int, float))
        else f"```\nSector {sector} · {sector_alignment}\nQQQ-SPY unavailable\n```"
    )
    return [
        {
            "name": "Entry / Stop / Target",
            "value": (
                f"```\nEntry  {entry:.2f}\nStop   {stop:.2f}\nTarget {target:.2f}\n```"
                if entry is not None and stop is not None and target is not None
                else "levels_missing"
            ),
            "inline": True,
        },
        {
            "name": "Risk / Reward",
            "value": (
                f"```\nRisk  ${risk:.2f}/sh\nRew   ${reward:.2f}/sh\nR:R   {rr:.2f}\n```"
                if risk and reward and rr
                else "rr_unavailable"
            ),
            "inline": True,
        },
        {
            "name": "Score",
            "value": f"```\ngrade  {grade_display}\nscore  {setup['score']:.1f}\nrank   {setup.get('ranking_score') or '-'}\n```",
            "inline": True,
        },
        {"name": "Market Context", "value": context_value, "inline": False},
        {"name": "Catalyst", "value": f"_{catalyst}_"[:1024], "inline": False},
    ]


def send_spotlight(
    setups: list[dict[str, Any]],
    mention: bool = True,
    *,
    tier: Mapping[str, Any] = TIERS["aplus"],
) -> dict[str, Any]:
    if not setups:
        return {"status": "no_new_setups", "sent": 0}
    sent = 0
    results = []
    for setup in setups:
        arrow = _direction_emoji(setup["direction"])
        title = (
            f"{tier['title_prefix']}  {arrow}  {setup['symbol']}  ·  "
            f"{setup['setup'].replace('_', ' ').title()}"
        )
        description = (
            f"**{setup['symbol']}** · **{setup['direction'].upper()}** · confirmed 5m · "
            f"score **{setup['score']:.1f}**\n"
            f"_State: {setup.get('state', '?')} · {setup.get('confirmation_stage', '?')}_"
        )
        result = send_discord_embed(
            title=title,
            description=description,
            color=tier["color"],
            fields=format_setup_fields(setup),
            content=tier["content_prefix"] if mention else "",
            allow_mentions=mention,
        )
        results.append({"fingerprint": setup["fingerprint"], "symbol": setup["symbol"], "result": result})
        if result.get("sent"):
            sent += 1
    return {"status": "sent", "sent": sent, "attempts": len(setups), "results": results}


def successful_fingerprints(
    setups: Iterable[Mapping[str, Any]], send_result: Mapping[str, Any]
) -> set[str]:
    attempted = {str(setup.get("fingerprint") or "") for setup in setups}
    delivered: set[str] = set()
    for item in send_result.get("results") or []:
        if not isinstance(item, Mapping) or not isinstance(item.get("result"), Mapping):
            continue
        fingerprint = str(item.get("fingerprint") or "")
        if fingerprint in attempted and item["result"].get("sent") is True:
            delivered.add(fingerprint)
    return delivered


def append_log(
    fresh: list[dict[str, Any]],
    send_result: Mapping[str, Any],
    *,
    tier: Mapping[str, Any] = TIERS["aplus"],
) -> None:
    log_path: Path = tier["log_path"]
    log_path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "date": datetime.now(ET).date().isoformat(),
        "provider": tier["provider"],
        "tier": tier["label"],
        "mode": "read_only",
        "execution_enabled": False,
        "setup_count": len(fresh),
        "setups": fresh,
        "notification": {k: v for k, v in send_result.items() if k != "results"},
    }
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, separators=(",", ":")) + "\n")


def write_report(
    fresh: list[dict[str, Any]],
    *,
    tier: Mapping[str, Any] = TIERS["aplus"],
) -> Path:
    report_path: Path = tier["report_path"]
    report_path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "date": datetime.now(ET).date().isoformat(),
        "provider": tier["provider"],
        "tier": tier["label"],
        "mode": "read_only",
        "setup_count": len(fresh),
        "setups": fresh,
    }
    _atomic_write_json(report_path, payload, indent=2)
    return report_path


def _run_tier(
    tier: Mapping[str, Any],
    *,
    now: datetime,
    dry_run: bool,
    mention: bool,
    excluded_fingerprints: set[str],
) -> dict[str, Any]:
    alerted = _load_alerted(now, state_path=tier["state_path"])
    live = collect_fresh_for_tier(
        tier,
        now=now,
        excluded_fingerprints=excluded_fingerprints,
    )
    fresh = [setup for setup in live if setup["fingerprint"] not in alerted]
    if dry_run or not fresh:
        send_result = {
            "status": "dry_run" if dry_run else "no_new_setups",
            "sent": 0,
            "attempts": len(fresh),
        }
    else:
        send_result = send_spotlight(fresh, mention=mention, tier=tier)
        alerted.update(successful_fingerprints(fresh, send_result))
        _save_alerted(alerted, now, state_path=tier["state_path"])

    append_log(fresh, send_result, tier=tier)
    write_report(live, tier=tier)
    return {
        "tier": tier["label"],
        "live_setups": len(live),
        "fresh_setups": len(fresh),
        "notification": send_result,
        "live_fingerprints": {setup["fingerprint"] for setup in live},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Detect but do not post to Discord.")
    parser.add_argument("--no-mention", action="store_true", help="Suppress @here mention.")
    parser.add_argument("--print", action="store_true", help="Print JSON summary to stdout.")
    parser.add_argument(
        "--tier",
        choices=("aplus", "bplus", "all"),
        default="all",
        help="Which spotlight tier(s) to evaluate.",
    )
    args = parser.parse_args()

    now = datetime.now(ET)
    tier_order = ("aplus", "bplus") if args.tier == "all" else (args.tier,)

    summary: dict[str, Any] = {"date": now.date().isoformat(), "tiers": {}}
    # A+ hits take priority; suppress a duplicate B+ alert on the same setup.
    excluded_fingerprints: set[str] = set()
    for tier_key in tier_order:
        tier = TIERS[tier_key]
        # B+ requires B+/A- grades, so A+ collisions are already impossible;
        # still pass excluded_fingerprints for symmetry and future-proofing.
        result = _run_tier(
            tier,
            now=now,
            dry_run=args.dry_run,
            mention=not args.no_mention,
            excluded_fingerprints=excluded_fingerprints,
        )
        excluded_fingerprints |= result.pop("live_fingerprints")
        summary["tiers"][tier_key] = result

    if args.print:
        print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
