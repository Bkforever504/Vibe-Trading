"""One-shot schema extension for the signal registry; preserves prior values."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.governance.trial_ledger import family_for

REGISTRY = ROOT / "research" / "signal_registry.json"


def migrate(registry: dict) -> dict:
    for signal in registry.get("signals") or []:
        family = signal.get("family_key") or family_for(
            str(signal.get("id") or ""),
            descriptor=f"{signal.get('name', '')} {signal.get('script', '')} {signal.get('notes', '')}",
        )
        signal["family_key"] = family
        signal["family_assignment_review_required"] = True
        existing = signal.get("promotion_gate") if isinstance(signal.get("promotion_gate"), dict) else {}
        signal["promotion_gate"] = {
            "min_outcomes": existing.get("min_outcomes", 30),
            "min_deflated_sharpe": existing.get("min_deflated_sharpe"),
            "min_psr": existing.get("min_psr", 0.95),
            "max_pbo": existing.get("max_pbo", 0.5),
            "family_key": family,
            "requires_human_review": True,
            **{key: value for key, value in existing.items() if key not in {
                "min_outcomes", "min_deflated_sharpe", "min_psr", "max_pbo", "family_key", "requires_human_review"}},
        }
    registry["statistical_gate_schema_version"] = 1
    registry["family_assignment_review_status"] = "pending_human_review"
    return registry


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=REGISTRY)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    value = migrate(json.loads(args.registry.read_text(encoding="utf-8")))
    if args.write:
        temporary = args.registry.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        temporary.replace(args.registry)
    print(json.dumps({"signals": len(value.get("signals") or []), "write": args.write,
                      "family_review": value["family_assignment_review_status"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
