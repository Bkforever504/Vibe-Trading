from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_pattern_taxonomy_is_manual_only_and_labels_data_availability() -> None:
    payload = json.loads((ROOT / "research" / "pattern_taxonomy.json").read_text(encoding="utf-8"))

    assert payload["authority"] == {"execution_enabled": False, "can_submit_orders": False}
    assert len(payload["patterns"]) == 18
    assert len({row["id"] for row in payload["patterns"]}) == 18
    for row in payload["patterns"]:
        assert row["family"]
        assert row["implementation_status"]
        assert row["entry_trigger"]
        assert row["invalidation"]
        assert row["required_data"]
        assert row["source_labels"]


def test_unavailable_microstructure_is_not_misrepresented_as_live() -> None:
    payload = json.loads((ROOT / "research" / "pattern_taxonomy.json").read_text(encoding="utf-8"))
    rows = {row["id"]: row for row in payload["patterns"]}

    assert rows["delta_divergence_proxy"]["implementation_status"].startswith("unavailable")
    assert rows["gex_flip"]["implementation_status"].startswith("unavailable")
