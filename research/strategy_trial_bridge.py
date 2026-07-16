from __future__ import annotations

from typing import Any

from scripts.edge_trial_ledger import validate_trial


def ledger_trial_from_run_card(card: dict[str, Any]) -> dict[str, Any]:
    metrics = card.get("metrics")
    if card.get("status") != "research_complete" or not isinstance(metrics, dict) or not metrics:
        raise ValueError("completed research metrics required")
    packet = card.get("packet")
    if not isinstance(packet, dict):
        raise ValueError("strategy packet required")
    research = packet.get("research")
    if not isinstance(research, dict):
        raise ValueError("research contract required")
    provenance = packet.get("provenance") if isinstance(packet.get("provenance"), dict) else {}
    identifier = str(card.get("packet_id") or "")
    trial = {
        "edge_id": identifier,
        "hypothesis": packet.get("thesis"),
        "variant": identifier,
        "stage": "out_of_sample",
        "parameters": packet.get("parameters") or {},
        "dataset_start": research.get("dataset_start"),
        "dataset_end": research.get("dataset_end"),
        "oos_start": research.get("oos_start"),
        "oos_end": research.get("oos_end"),
        "cost_model": research.get("cost_model"),
        "metrics": dict(metrics),
        "source": provenance.get("source") or "strategy_pipeline",
        "code_version": card.get("code_version"),
        "run_id": card.get("run_id"),
        "execution_enabled": False,
        "can_submit_orders": False,
    }
    errors = validate_trial(trial)
    if errors:
        raise ValueError(";".join(errors))
    return trial
