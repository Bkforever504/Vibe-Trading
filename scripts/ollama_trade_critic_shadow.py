#!/usr/bin/env python3
"""Produce local Ollama critic cards for current governed shadow candidates."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.src.providers.ollama_shadow_critic import evaluate, input_digest
from scripts import governed_shadow_decision as governed

DEFAULT_OUTPUT = Path.home() / ".vibe-trading" / "reports" / "ollama-shadow-critic.json"


def build_report(
    *, model: str, base_url: str, timeout_seconds: float, previous: dict[str, Any] | None = None,
    max_new_evaluations: int = 2,
) -> dict[str, Any]:
    source = governed.build_report()
    previous = previous if isinstance(previous, dict) else {}
    prior_cards = {str(row.get("candidate_key")): row for row in previous.get("cards") or [] if isinstance(row, dict)}
    cards = []
    new_evaluations = 0
    def score(row: Any) -> float:
        try:
            return float((row.get("candidate") or {}).get("score") or 0) if isinstance(row, dict) else 0.0
        except (TypeError, ValueError):
            return 0.0
    decisions = sorted(
        source.get("decisions", []),
        key=score,
        reverse=True,
    )
    for decision in decisions:
        candidate = decision.get("candidate") or {}
        evidence = decision.get("evidence_cards") or []
        candidate_key = str(decision.get("candidate_key") or "")
        expected_hash = input_digest(candidate, evidence)
        prior = prior_cards.get(candidate_key, {})
        if prior.get("status") == "ok" and prior.get("model") == model and prior.get("input_hash") == expected_hash:
            result = dict(prior)
            result["cache_hit"] = True
        elif new_evaluations >= max(0, max_new_evaluations):
            result = {
                "provider": "ollama_local_shadow_critic", "generated_at": governed._utc_now(),
                "status": "deferred_capacity", "model": model, "model_digest": None,
                "input_hash": expected_hash, "response_hash": None, "latency_ms": None,
                "stance": None, "veto_reasons": [], "evidence_refs": [], "summary": None,
                "execution_enabled": False, "can_submit_orders": False, "authority": "shadow_veto_only",
                "error": "per_run_cpu_budget_exhausted", "cache_hit": False,
            }
        else:
            result = evaluate(candidate, evidence, model=model, base_url=base_url, timeout_seconds=timeout_seconds)
            result["cache_hit"] = False
            new_evaluations += 1
        result["candidate_key"] = candidate_key
        cards.append(result)
    return {
        "provider": "ollama_local_shadow_critic", "generated_at": governed._utc_now(), "mode": "shadow_only",
        "execution_enabled": False, "can_submit_orders": False, "cards": cards,
        "summary": {
            "candidates": len(cards), "new_evaluations": new_evaluations,
            "ok": sum(row["status"] == "ok" for row in cards),
            "veto": sum(row.get("stance") == "veto" for row in cards),
            "deferred_capacity": sum(row["status"] == "deferred_capacity" for row in cards),
        },
        "warnings": ["Ollama is veto-only and cannot remove deterministic blockers.", "Missing or invalid model output is never fabricated."],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=os.getenv("OLLAMA_SHADOW_MODEL", "qwen3:4b-instruct"))
    parser.add_argument("--base-url", default=os.getenv("OLLAMA_SHADOW_BASE_URL", "http://127.0.0.1:11434"))
    parser.add_argument("--timeout-seconds", type=float, default=float(os.getenv("OLLAMA_SHADOW_TIMEOUT_SECONDS", "30")))
    parser.add_argument("--max-new-evaluations", type=int, default=int(os.getenv("OLLAMA_SHADOW_MAX_NEW_EVALUATIONS", "2")))
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--print", action="store_true", dest="print_output")
    args = parser.parse_args()
    try:
        previous = json.loads(args.output.read_text(encoding="utf-8")) if args.output.exists() else {}
    except (OSError, json.JSONDecodeError):
        previous = {}
    report = build_report(
        model=args.model, base_url=args.base_url, timeout_seconds=args.timeout_seconds,
        previous=previous, max_new_evaluations=args.max_new_evaluations,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.print_output:
        print(json.dumps(report["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
