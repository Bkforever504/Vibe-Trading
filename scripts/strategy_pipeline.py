#!/usr/bin/env python3
"""Research-only strategy intake, validation, and evidence pipeline."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.strategy_adapter_safety import validate_adapter_source
from research.strategy_language import interpret_description
from research.strategy_pipeline import packet_id, validate_packet, write_packet_atomic
from research.strategy_run_cards import build_run_card, write_run_card
from research.strategy_trial_bridge import ledger_trial_from_run_card
from scripts.edge_trial_ledger import LEDGER_PATH, record_trial


PACKET_DIR = ROOT / "research" / "strategy_packets" / "generated"
RUN_CARD_DIR = Path.home() / ".vibe-trading" / "strategy-runs"


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _git_version() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def _slug(value: str) -> str:
    result = "".join(character.lower() if character.isalnum() else "-" for character in value)
    return "-".join(part for part in result.split("-") if part) or "strategy"


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _intake(args: argparse.Namespace) -> int:
    interpretation = interpret_description(args.describe)
    research_values = {
        "dataset_start": args.dataset_start,
        "dataset_end": args.dataset_end,
        "oos_start": args.oos_start,
        "oos_end": args.oos_end,
        "benchmark": args.benchmark or interpretation.fields.get("benchmark"),
        "cost_model": args.cost_model or interpretation.fields.get("cost_model"),
    }
    research_missing = [f"research.{key}" for key, value in research_values.items() if not value]
    if interpretation.status != "ready_for_validation" or research_missing:
        payload = {
            "provider": "strategy_pipeline",
            "status": "needs_rules",
            "name": args.name,
            "missing_fields": list(interpretation.missing_fields) + research_missing,
            "ambiguities": list(interpretation.ambiguities),
            "interpreted_fields": interpretation.fields,
            "execution_enabled": False,
            "can_submit_orders": False,
        }
        _emit(payload)
        return 2

    fields = interpretation.fields
    packet = {
        "schema_version": 1,
        "name": args.name,
        "thesis": args.describe,
        "market": {
            "asset_class": args.asset_class,
            "symbols": fields["symbols"],
            "timeframe": fields["timeframe"],
            "timezone": args.timezone,
        },
        "rules": fields["rules"],
        "data": {
            "bars": [fields["timeframe"]],
            "point_in_time_required": True,
        },
        "research": research_values,
        "provenance": {"original_prompt": args.describe, "source": args.source},
        "authority": {
            "mode": "research_only",
            "execution_enabled": False,
            "can_submit_orders": False,
            "promotion_requires_human_approval": True,
        },
    }
    validation = validate_packet(packet)
    if not validation.valid:
        _emit({
            "provider": "strategy_pipeline",
            "status": "validation_failed",
            "errors": list(validation.errors),
            "execution_enabled": False,
            "can_submit_orders": False,
        })
        return 2
    identifier = packet_id(packet)
    destination = args.out_dir / f"{_slug(args.name)}-{identifier}.json"
    write_packet_atomic(packet, destination)
    _emit({
        "provider": "strategy_pipeline",
        "status": "packet_created",
        "packet_id": identifier,
        "path": str(destination),
        "execution_enabled": False,
        "can_submit_orders": False,
    })
    return 0


def _validate(args: argparse.Namespace) -> int:
    packet = _load_object(args.packet)
    validation = validate_packet(packet)
    safety = None
    if args.adapter_source:
        safety = validate_adapter_source(args.adapter_source.read_text(encoding="utf-8-sig"))
    errors = list(validation.errors)
    if safety and not safety.safe:
        errors.extend(safety.errors)
    valid = validation.valid and (safety is None or safety.safe)
    card = build_run_card(
        packet_id(packet),
        packet,
        {"valid": valid, "errors": sorted(set(errors))},
        None,
        code_version=_git_version(),
    )
    path = write_run_card(card, args.run_card_dir)
    payload = {**card, "path": str(path)}
    _emit(payload)
    if safety and not safety.safe:
        return 3
    return 0 if valid else 2


def _run(args: argparse.Namespace) -> int:
    packet = _load_object(args.packet)
    validation = validate_packet(packet)
    errors = list(validation.errors)
    if args.adapter_source:
        safety = validate_adapter_source(args.adapter_source.read_text(encoding="utf-8-sig"))
        errors.extend(safety.errors)
    valid = validation.valid and not errors
    metrics = _load_object(args.metrics)
    provenance = _load_object(args.dataset_provenance)
    card = build_run_card(
        packet_id(packet),
        packet,
        {"valid": valid, "errors": sorted(set(errors))},
        metrics,
        code_version=_git_version(),
        dataset_provenance=provenance,
    )
    path = write_run_card(card, args.run_card_dir)
    payload: dict[str, Any] = {**card, "path": str(path), "ledger_recorded": False}
    if card["status"] == "research_complete":
        trial = ledger_trial_from_run_card(card)
        payload["ledger"] = record_trial(trial, args.ledger_path)
        payload["ledger_recorded"] = bool(payload["ledger"].get("recorded"))
    _emit(payload)
    if errors:
        return 3 if args.adapter_source else 2
    return 0 if card["status"] == "research_complete" else 4


def _show(args: argparse.Namespace) -> int:
    path = args.run_card_dir / f"{args.run_id}.json"
    _emit(_load_object(path))
    return 0


def _list(args: argparse.Namespace) -> int:
    rows = []
    for path in sorted(args.run_card_dir.glob("*.json")) if args.run_card_dir.exists() else []:
        try:
            card = _load_object(path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if args.status and card.get("status") != args.status:
            continue
        rows.append({
            "run_id": card.get("run_id"),
            "packet_id": card.get("packet_id"),
            "status": card.get("status"),
            "path": str(path),
        })
    _emit({
        "provider": "strategy_pipeline",
        "count": len(rows),
        "runs": rows,
        "execution_enabled": False,
        "can_submit_orders": False,
    })
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    intake = subparsers.add_parser("intake", help="Create a research strategy packet.")
    intake.add_argument("--describe", required=True)
    intake.add_argument("--name", required=True)
    intake.add_argument("--out-dir", type=Path, default=PACKET_DIR)
    intake.add_argument("--asset-class", default="equity_options")
    intake.add_argument("--timezone", default="America/New_York")
    intake.add_argument("--source", default="user_prompt")
    intake.add_argument("--dataset-start")
    intake.add_argument("--dataset-end")
    intake.add_argument("--oos-start")
    intake.add_argument("--oos-end")
    intake.add_argument("--benchmark")
    intake.add_argument("--cost-model")
    intake.set_defaults(handler=_intake)

    validate = subparsers.add_parser("validate", help="Validate a packet and optional adapter.")
    validate.add_argument("--packet", type=Path, required=True)
    validate.add_argument("--adapter-source", type=Path)
    validate.add_argument("--run-card-dir", type=Path, default=RUN_CARD_DIR)
    validate.add_argument("--print", action="store_true", dest="do_print")
    validate.set_defaults(handler=_validate)

    run = subparsers.add_parser("run", help="Record explicit completed research evidence.")
    run.add_argument("--packet", type=Path, required=True)
    run.add_argument("--metrics", type=Path, required=True)
    run.add_argument("--dataset-provenance", type=Path, required=True)
    run.add_argument("--adapter-source", type=Path)
    run.add_argument("--run-card-dir", type=Path, default=RUN_CARD_DIR)
    run.add_argument("--ledger-path", type=Path, default=LEDGER_PATH)
    run.add_argument("--print", action="store_true", dest="do_print")
    run.set_defaults(handler=_run)

    show = subparsers.add_parser("show", help="Show a run card.")
    show.add_argument("--run-id", required=True)
    show.add_argument("--run-card-dir", type=Path, default=RUN_CARD_DIR)
    show.set_defaults(handler=_show)

    listing = subparsers.add_parser("list", help="List run cards.")
    listing.add_argument("--status")
    listing.add_argument("--run-card-dir", type=Path, default=RUN_CARD_DIR)
    listing.set_defaults(handler=_list)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return int(args.handler(args))
    except (FileNotFoundError, FileExistsError, ValueError, json.JSONDecodeError) as exc:
        _emit({
            "provider": "strategy_pipeline",
            "status": "error",
            "error": str(exc),
            "execution_enabled": False,
            "can_submit_orders": False,
        })
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
