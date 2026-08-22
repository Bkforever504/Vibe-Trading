from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from scripts.shadow_outcome_resolver import LEDGER_NAMES, run_once


NOW = datetime(2026, 8, 20, 20, 30, tzinfo=timezone.utc)


def test_fixed_bars_quotes_calendar_bundle_replays_byte_for_byte(tmp_path: Path) -> None:
    rows = [
        {
            "type": "candidate",
            "candidate_id": "fixed-plan",
            "created_at": "2026-08-20T14:30:00Z",
            "entry_ask": 1.0,
            "max_risk_per_contract": 100,
            "bars": [{"ts": "2026-08-20T14:30:00Z", "close": 770.0}],
            "calendar": [{"date": "2026-08-20", "event": "none"}],
        },
        {"type": "mark", "candidate_id": "fixed-plan", "timestamp": "2026-08-20T14:35:00Z", "executable_bid": 1.2, "quote": {"bid": 1.2, "ask": 1.25}},
        {"type": "outcome", "candidate_id": "fixed-plan", "resolved_at": "2026-08-20T14:40:00Z", "exit_fill_executable": 1.2, "pnl_before_fees": 20},
    ]
    ledger = tmp_path / LEDGER_NAMES[0]
    ledger.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    output = tmp_path / "shadow_outcomes.jsonl"

    run_once(data_dir=tmp_path, output_path=output, now=NOW)
    first = output.read_bytes()
    run_once(data_dir=tmp_path, output_path=output, now=NOW)

    assert output.read_bytes() == first
    assert json.loads(first.decode("utf-8"))["outcome_r"] == 0.2

