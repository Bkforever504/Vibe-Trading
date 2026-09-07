from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
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


def test_rejected_research_entry_without_script_is_a_warning(tmp_path: Path) -> None:
    registry = {
        "policy": {},
        "signals": [{
            "id": "rejected_idea",
            "script": "",
            "status": "rejected",
            "can_submit_orders": False,
            "execution_enabled": False,
        }],
    }

    report = audit.audit_registry(registry, root=tmp_path)

    assert report["passed"] is True
    assert report["warnings"][0]["issue"] == "rejected_registry_entry_has_no_script"


def test_repository_static_execution_gate_audit_passes(monkeypatch) -> None:
    now = datetime(2026, 9, 7, tzinfo=timezone.utc)
    # Static repository test: operational evidence freshness is tested below.
    # Never refresh real gate histories just to make a unit test green.
    monkeypatch.setattr(audit, "_latest_gate_row", lambda path: {"evaluated_at": now.isoformat()})
    report = audit.audit_registry(audit.load_registry(ROOT / "research" / "signal_registry.json"), now=now)

    assert report["passed"] is True, report["issues"]


def test_promoted_signal_requires_real_recent_gate_evidence(tmp_path) -> None:
    now = datetime(2026, 9, 7, tzinfo=timezone.utc)
    script = tmp_path / "shadow.py"
    script.write_text("# no orders\n", encoding="utf-8")
    registry = {"policy": {}, "signals": [{"id": "candidate", "script": str(script),
        "status": "execution_capable_paper", "execution_enabled": False, "can_submit_orders": False}]}
    history = tmp_path / "data/governance/gate_history/candidate.jsonl"
    history.parent.mkdir(parents=True)
    for stamp, passes in [(None, False), (now - timedelta(hours=25), False),
                           (now + timedelta(seconds=1), False), (now, True)]:
        history.write_text(json.dumps({"evaluated_at": stamp.isoformat() if stamp else None}) + "\n", encoding="utf-8")
        report = audit.audit_registry(registry, root=tmp_path, now=now)
        assert report["passed"] is passes
        if not passes:
            assert report["issues"][0]["issue"] == "promoted_signal_gate_history_missing_or_stale_24h"


def test_new_execution_evidence_modules_have_narrow_non_execution_allowlist() -> None:
    assert audit.BUILTIN_NON_EXECUTION_EVIDENCE == {
        "scripts/broker_fill_observer.py",
        "scripts/manual_execution_quality.py",
    }
