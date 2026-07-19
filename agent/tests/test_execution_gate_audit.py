from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import execution_gate_audit as audit


def test_audit_blocks_order_pattern_in_context_script(tmp_path: Path) -> None:
    script = tmp_path / "context.py"
    script.write_text('requests.post("/v2/orders")\n', encoding="utf-8")
    registry = {
        "policy": {"known_order_capable_scripts": []},
        "signals": [
            {
                "id": "context",
                "script": str(script),
                "can_submit_orders": False,
                "execution_enabled": False,
            }
        ],
    }

    report = audit.audit_registry(registry, root=tmp_path)

    assert report["passed"] is False
    assert report["issues"][0]["issue"] == "order_patterns_in_non_execution_signal"


def test_audit_allows_known_order_capable_script(tmp_path: Path) -> None:
    script = tmp_path / "bot.py"
    script.write_text('requests.post("/v2/orders")\n', encoding="utf-8")
    registry = {
        "policy": {"known_order_capable_scripts": [str(script)]},
        "signals": [
            {
                "id": "bot",
                "script": str(script),
                "can_submit_orders": True,
                "execution_enabled": True,
            }
        ],
    }

    report = audit.audit_registry(registry, root=tmp_path)

    assert report["passed"] is True


def test_registry_file_is_valid_json() -> None:
    payload = audit.load_registry(ROOT / "research" / "signal_registry.json")

    assert payload["signals"]
    assert "known_order_capable_scripts" in payload["policy"]
