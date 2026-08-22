#!/usr/bin/env python3
"""Classify clean closed-trade losses into testable failure modes.

Read-only. The report can generate countermeasure preregistration templates,
but it cannot change a strategy, enable execution, or promote an edge.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import lifecycle_normalizer as canon  # noqa: E402
from scripts.closed_trade_postmortem import dedupe_options_trade_records  # noqa: E402

VIBE_HOME = Path.home() / ".vibe-trading"
FLIP_PATH = VIBE_HOME / "flip-trades.json"
OPTIONS_PATH = VIBE_HOME / "options-trades.json"
TOPSTEP_PATH = VIBE_HOME / "ninjatrader-sim-oif-journal.jsonl"
MISTAKE_LEDGER_PATH = ROOT / "data" / "self_learning_mistake_ledger.jsonl"
REPORT_PATH = VIBE_HOME / "reports" / "failure-taxonomy.json"

CATEGORIES = (
    "COST_CONSUMED_EDGE",
    "WRONG_DIRECTION",
    "CORRECT_DIR_EARLY",
    "STOP_TOO_TIGHT",
    "REGIME_MISMATCH",
    "EXECUTION_SLIPPAGE",
    "UNKNOWN_LOSS",
)
SYSTEMATIC_MIN_INSTANCES = 10
SLIPPAGE_THRESHOLD_PCT = 5.0

COUNTERMEASURES = {
    "COST_CONSUMED_EDGE": (
        "Test a frozen maximum spread-to-expected-move gate using executable "
        "NBBO fills and doubled cost stress."
    ),
    "WRONG_DIRECTION": (
        "Test a direction gate that requires higher-timeframe and point-in-time "
        "underlying confirmation before entry."
    ),
    "CORRECT_DIR_EARLY": (
        "Test waiting for the frozen confirmation or retest trigger without "
        "changing the underlying directional thesis."
    ),
    "STOP_TOO_TIGHT": (
        "Test a volatility-scaled stop against the frozen baseline while "
        "holding account risk constant."
    ),
    "REGIME_MISMATCH": (
        "Test a frozen regime eligibility map and abstain when the strategy's "
        "documented regime is absent."
    ),
    "EXECUTION_SLIPPAGE": (
        "Test a maximum fill-versus-mid slippage gate with cancel-on-breach."
    ),
    "UNKNOWN_LOSS": (
        "Improve point-in-time telemetry before proposing a countermeasure."
    ),
}


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return default


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _number(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _nested(raw: dict[str, Any], *path: str) -> Any:
    value: Any = raw
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _first_number(raw: dict[str, Any], names: tuple[str, ...]) -> float | None:
    for name in names:
        value = _number(raw.get(name))
        if value is not None:
            return value
    return None


def _feature_snapshot(raw: dict[str, Any]) -> dict[str, Any]:
    quality = raw.get("entry_quality")
    if isinstance(quality, dict) and isinstance(quality.get("feature_snapshot"), dict):
        return quality["feature_snapshot"]
    snapshot = raw.get("feature_snapshot")
    return snapshot if isinstance(snapshot, dict) else {}


def vix_tier(value: float | None) -> str:
    if value is None:
        return "unknown"
    if value < 15:
        return "low"
    if value < 25:
        return "medium"
    if value < 40:
        return "high"
    return "extreme"


def _parse_entry(raw: dict[str, Any]) -> datetime | None:
    value = (
        raw.get("entry_at")
        or raw.get("opened_at")
        or raw.get("entry_time")
        or raw.get("timestamp")
    )
    if not value:
        return None
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=ZoneInfo("America/New_York"))
    return stamp.astimezone(ZoneInfo("America/New_York"))


def session_phase(raw: dict[str, Any]) -> str:
    stamp = _parse_entry(raw)
    if stamp is None:
        return "unknown"
    minute = stamp.hour * 60 + stamp.minute
    if minute < 9 * 60 + 30:
        return "pre_open"
    if minute < 11 * 60 + 30:
        return "morning"
    if minute < 13 * 60 + 30:
        return "midday"
    return "afternoon"


def _entry_date(raw: dict[str, Any]) -> str | None:
    stamp = _parse_entry(raw)
    if stamp is not None:
        return stamp.date().isoformat()
    value = raw.get("entry_date") or raw.get("session_date") or raw.get("date")
    return str(value)[:10] if value else None


def _dte(raw: dict[str, Any]) -> int | None:
    explicit = _number(raw.get("dte"))
    if explicit is not None:
        return max(0, int(explicit))
    expiry = raw.get("expiry")
    entry = _entry_date(raw)
    if not expiry or not entry:
        return None
    try:
        return max(
            0,
            (
                datetime.fromisoformat(str(expiry)[:10]).date()
                - datetime.fromisoformat(entry).date()
            ).days,
        )
    except ValueError:
        return None


def dte_bucket(raw: dict[str, Any]) -> str:
    dte = _dte(raw)
    if dte is None:
        return "unknown"
    if dte == 0:
        return "0dte"
    if dte == 1:
        return "1dte"
    if dte == 2:
        return "2dte"
    if dte <= 7:
        return "3_7dte"
    if dte <= 30:
        return "7_30dte"
    if dte <= 45:
        return "30_45dte"
    return "over_45dte"


def regime_tags(raw: dict[str, Any]) -> dict[str, Any]:
    features = _feature_snapshot(raw)
    vix = _number(raw.get("vix_at_entry"))
    if vix is None:
        vix = _number(features.get("vix_at_entry"))
    trend_score = _number(raw.get("trend_score_at_entry"))
    if trend_score is None:
        trend_score = _number(features.get("trend_score_at_entry"))
    return {
        "vix_tier": vix_tier(vix),
        "vix_at_entry": vix,
        "trend_score_at_entry": int(trend_score) if trend_score is not None else None,
        "session_phase": session_phase(raw),
        "dte_bucket": dte_bucket(raw),
        "day_type": raw.get("day_type") or features.get("day_type") or "unknown",
    }


def _underlying_change(raw: dict[str, Any]) -> float | None:
    return _first_number(
        raw,
        (
            "underlying_change_pct",
            "underlying_return_pct",
            "underlying_move_pct",
            "underlying_change",
        ),
    )


def _cost_consumed_edge(raw: dict[str, Any]) -> bool:
    if raw.get("cost_consumed_edge") is True:
        return True
    cost = _first_number(
        raw,
        (
            "nbbo_round_trip_cost_dollars",
            "estimated_spread_cost_dollars",
            "transaction_cost_dollars",
            "spread_cost_dollars",
        ),
    )
    gross_edge = _first_number(
        raw,
        ("gross_edge_dollars", "underlying_move_dollars", "pre_cost_pnl_dollars"),
    )
    if cost is not None and gross_edge is not None:
        return cost > 0 and abs(cost) >= abs(gross_edge)
    spread_pct = _first_number(
        raw, ("nbbo_spread_pct", "entry_spread_pct", "round_trip_spread_pct")
    )
    move_pct = _underlying_change(raw)
    return (
        spread_pct is not None
        and move_pct is not None
        and spread_pct > 0
        and spread_pct >= abs(move_pct)
    )


def _entry_was_unconfirmed(raw: dict[str, Any]) -> bool:
    if raw.get("entry_before_confirmation") is True:
        return True
    if raw.get("signal_confirmed_at_entry") is False:
        return True
    features = _feature_snapshot(raw)
    status = str(
        raw.get("orb_retest_status")
        or features.get("orb_retest_status")
        or ""
    ).lower()
    return status in {
        "awaiting_retest",
        "breakout_unconfirmed",
        "confirmation_pending",
    }


def _recovered_after_stop(raw: dict[str, Any], direction: str) -> bool:
    if raw.get("recovered_after_stop") is True:
        return True
    post_exit = _number(raw.get("post_exit_underlying_change_pct"))
    return (
        post_exit is not None
        and canon.underlying_move_is_favorable(direction, post_exit) is True
    )


def _regime_mismatch(raw: dict[str, Any], strategy: str) -> bool:
    if raw.get("regime_mismatch") is True:
        return True
    features = _feature_snapshot(raw)
    if str(features.get("shadow_consensus_recommendation") or "").lower() == "stand_aside":
        return True
    expected = str(raw.get("strategy_expected_regime") or "").lower()
    observed = str(raw.get("market_regime") or features.get("day_type") or "").lower()
    if expected and observed and expected != observed:
        return True
    if strategy == "iron_condor" and observed in {"trend", "trending"}:
        return True
    if strategy in {"bull_trend", "bear_trend"} and observed in {
        "range", "ranging", "chop", "choppy"
    }:
        return True
    return False


def _entry_slippage_pct(raw: dict[str, Any], family: str) -> float | None:
    value = _number(raw.get("entry_slippage_pct"))
    if value is None:
        value = _number(_nested(raw, "entry_quality", "slippage_pct"))
    if value is not None:
        return value
    if family == canon.OPTIONS_FAMILY:
        submitted = _number(raw.get("submitted_limit_credit"))
        actual = _number(raw.get("entry_filled_avg_price"))
        if submitted and actual is not None:
            return (submitted - actual) / submitted * 100
    return None


def classify_loss(
    raw: dict[str, Any],
    view: dict[str, Any],
) -> tuple[str, str]:
    """Apply mutually exclusive failure categories in the frozen order."""
    if float(view.get("pnl_dollars") or 0.0) >= 0:
        raise ValueError("classify_loss requires a negative canonical P&L")
    family = str(view.get("bot_family") or "")
    direction = str(view.get("direction") or canon.UNKNOWN)
    strategy = str(view.get("strategy_family") or raw.get("strategy") or "")

    if "option" in str(view.get("instrument_type") or "") and _cost_consumed_edge(raw):
        return "COST_CONSUMED_EDGE", "observed spread/cost equaled or exceeded the gross move"

    underlying_change = _underlying_change(raw)
    if (
        underlying_change is not None
        and canon.underlying_move_is_favorable(direction, underlying_change) is False
    ):
        return "WRONG_DIRECTION", "underlying moved against the canonical position direction"

    if (
        underlying_change is not None
        and canon.underlying_move_is_favorable(direction, underlying_change) is True
        and _entry_was_unconfirmed(raw)
    ):
        return "CORRECT_DIR_EARLY", "direction was favorable but entry preceded confirmation"

    close_reason = str(
        raw.get("closing_reason") or raw.get("exit_reason") or ""
    ).lower()
    if "stop" in close_reason and _recovered_after_stop(raw, direction):
        return "STOP_TOO_TIGHT", "stop fired before a documented favorable recovery"

    if _regime_mismatch(raw, strategy):
        return "REGIME_MISMATCH", "entry telemetry conflicted with the strategy regime"

    slippage = _entry_slippage_pct(raw, family)
    if slippage is not None and slippage >= SLIPPAGE_THRESHOLD_PCT:
        return "EXECUTION_SLIPPAGE", f"entry slippage {slippage:.2f}% exceeded threshold"

    return "UNKNOWN_LOSS", "insufficient point-in-time evidence for a causal label"


def _mistake_index(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = str(row.get("trade_id") or "")
        if key and isinstance(row.get("context"), dict):
            result[key] = row["context"]
    return result


def _enrich(raw: dict[str, Any], mistake_context: dict[str, Any] | None) -> dict[str, Any]:
    if not mistake_context:
        return dict(raw)
    merged = dict(raw)
    merged["mistake_context"] = mistake_context
    for key, value in mistake_context.items():
        merged.setdefault(key, value)
    return merged


def _source_records(
    flip_path: Path,
    options_path: Path,
    topstep_path: Path,
    mistake_rows: list[dict[str, Any]],
) -> tuple[list[tuple[dict[str, Any], dict[str, Any], str]], dict[str, int]]:
    mistake_by_id = _mistake_index(mistake_rows)
    records: list[tuple[dict[str, Any], dict[str, Any], str]] = []
    source_counts: Counter[str] = Counter()

    flip = _read_json(flip_path, [])
    for raw in flip if isinstance(flip, list) else []:
        if not isinstance(raw, dict) or raw.get("status") != "closed":
            continue
        enriched = _enrich(raw, mistake_by_id.get(str(raw.get("id") or "")))
        records.append((enriched, canon.normalize_flip_trade(enriched), "flip-trades.json"))
        source_counts["flip_closed"] += 1

    payload = _read_json(options_path, {})
    option_rows = payload.get("trades", []) if isinstance(payload, dict) else []
    for raw in dedupe_options_trade_records(option_rows or []):
        if not isinstance(raw, dict) or raw.get("status") != "closed":
            continue
        enriched = _enrich(raw, mistake_by_id.get(str(raw.get("id") or "")))
        records.append((
            enriched,
            canon.normalize_options_trade(enriched),
            "options-trades.json",
        ))
        source_counts["options_closed_deduplicated"] += 1

    for raw in _read_jsonl(topstep_path):
        if str(raw.get("status") or "").lower() not in {
            "closed", "trade_closed", "filled_exit"
        }:
            continue
        enriched = _enrich(raw, mistake_by_id.get(str(raw.get("id") or "")))
        records.append((
            enriched,
            canon.normalize_topstep_trade(enriched),
            "ninjatrader-sim-oif-journal.jsonl",
        ))
        source_counts["topstep_closed"] += 1

    source_counts["mistake_ledger_rows"] = len(mistake_rows)
    source_counts["mistake_context_links"] = sum(
        1 for raw, _, _ in records if raw.get("mistake_context")
    )
    return records, dict(source_counts)


def summarize_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_category: dict[str, Any] = {}
    for category in CATEGORIES:
        selected = [row for row in records if row["category"] == category]
        independent = {
            row.get("date") or row.get("trade_id")
            for row in selected
            if row.get("date") or row.get("trade_id")
        }
        regimes = Counter(
            f"vix={row['regime']['vix_tier']}|"
            f"session={row['regime']['session_phase']}|"
            f"dte={row['regime']['dte_bucket']}"
            for row in selected
        )
        systematic = len(independent) >= SYSTEMATIC_MIN_INSTANCES
        by_category[category] = {
            "count": len(selected),
            "pct_of_losses": round(len(selected) / len(records), 4) if records else 0.0,
            "independent_instance_count": len(independent),
            "systematic": systematic,
            "top_regime": regimes.most_common(1)[0][0] if regimes else None,
            "countermeasure_template": (
                {
                    "hypothesis": COUNTERMEASURES[category],
                    "pre_register_before": "first_forward_signal",
                    "shadow_min_independent_dates": 30,
                    "promotion_authority": "human_only",
                }
                if systematic else None
            ),
        }
    return by_category


def build_report(
    flip_path: Path = FLIP_PATH,
    options_path: Path = OPTIONS_PATH,
    topstep_path: Path = TOPSTEP_PATH,
    ledger_path: Path = MISTAKE_LEDGER_PATH,
) -> dict[str, Any]:
    mistake_rows = _read_jsonl(ledger_path)
    source, source_counts = _source_records(
        flip_path, options_path, topstep_path, mistake_rows
    )
    excluded = [view for _, view, _ in source if view["quarantined"]]
    losses: list[dict[str, Any]] = []
    for raw, view, source_name in source:
        if view["quarantined"] or view.get("outcome_status") != "loss":
            continue
        category, reason = classify_loss(raw, view)
        day = (
            view.get("entry_date")
            or _entry_date(raw)
            or view.get("exit_date")
        )
        losses.append({
            "trade_id": view.get("trade_id"),
            "date": str(day)[:10] if day else None,
            "source": source_name,
            "bot_family": view.get("bot_family"),
            "symbol": view.get("symbol"),
            "strategy": view.get("strategy_family"),
            "direction": view.get("direction"),
            "pnl_dollars": view.get("pnl_dollars"),
            "pnl_source": view.get("pnl_source", raw.get("pnl_source") or canon.UNKNOWN),
            "category": category,
            "classification_reason": reason,
            "regime": regime_tags(raw),
        })
    by_category = summarize_records(losses)
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "provider": "failure_taxonomy",
        "mode": "read_only_diagnosis",
        "execution_enabled": False,
        "can_submit_orders": False,
        "source_counts": source_counts,
        "total_closed": len(source),
        "total_losses": len(losses),
        "excluded_quarantined": len(excluded),
        "excluded_quarantine_reasons": dict(Counter(
            reason for view in excluded for reason in view["unknown_reasons"]
        )),
        "by_category": by_category,
        "promotion_candidates": [],
        "records": losses,
        "invariants": {
            "categories_mutually_exclusive": (
                sum(row["count"] for row in by_category.values()) == len(losses)
            ),
            "systematic_min_independent_instances": SYSTEMATIC_MIN_INSTANCES,
            "countermeasures_are_templates_only": True,
            "human_only_promotion": True,
        },
        "warnings": [
            "Missing point-in-time telemetry is classified UNKNOWN_LOSS, never guessed.",
            "Legacy options records without fill-derived P&L are excluded.",
            "A systematic category nominates a preregistration template only.",
            "No category can change production behavior or submit an order.",
        ],
    }


def write_report(report: dict[str, Any], path: Path = REPORT_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--flip-path", type=Path, default=FLIP_PATH)
    parser.add_argument("--options-path", type=Path, default=OPTIONS_PATH)
    parser.add_argument("--topstep-path", type=Path, default=TOPSTEP_PATH)
    parser.add_argument("--ledger-path", type=Path, default=MISTAKE_LEDGER_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--print", action="store_true", dest="do_print")
    args = parser.parse_args()
    report = build_report(
        args.flip_path, args.options_path, args.topstep_path, args.ledger_path
    )
    if not args.no_write:
        write_report(report, args.report_path)
    if args.do_print:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(json.dumps({
            "total_closed": report["total_closed"],
            "total_losses": report["total_losses"],
            "excluded_quarantined": report["excluded_quarantined"],
            "category_counts": {
                name: row["count"] for name, row in report["by_category"].items()
            },
            "promotion_candidates": report["promotion_candidates"],
        }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

