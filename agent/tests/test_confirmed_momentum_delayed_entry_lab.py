from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research import confirmed_momentum_delayed_entry_lab as lab


def _write(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def _lifecycle(*, first_return: float, first_ask: float | None = 1.10) -> list[dict]:
    base = {
        "lifecycle_id": "2026-08-18|SPY|CALL|0dte|09:30",
        "date": "2026-08-18",
        "symbol": "SPY",
    }
    return [
        {**base, "scanned_at": "2026-08-18T14:30:00Z", "event_type": "shadow_entry", "entry_price_est": 1.0},
        {
            **base,
            "scanned_at": "2026-08-18T14:35:00Z",
            "event_type": "shadow_mark",
            "selection_bid": 1.05,
            "selection_ask": first_ask,
            "return_pct_at_mark": first_return,
        },
        {
            **base,
            "scanned_at": "2026-08-18T14:40:00Z",
            "event_type": "shadow_mark",
            "selection_bid": 1.50,
            "selection_ask": 1.55,
            "return_pct_at_mark": 50.0,
        },
        {
            **base,
            "scanned_at": "2026-08-18T14:45:00Z",
            "event_type": "shadow_exit",
            "selection_bid": 1.30,
            "selection_ask": 1.35,
            "return_pct_at_mark": 30.0,
            "mark_reason": "hard_close",
        },
    ]


def test_delayed_entry_uses_confirmation_ask_and_later_bid(tmp_path: Path) -> None:
    path = tmp_path / "log.jsonl"
    _write(path, _lifecycle(first_return=5.0))

    life = lab.load_lifecycles(path)[0]
    outcome, status = lab.replay(life)

    assert status == "eligible"
    assert outcome is not None
    assert outcome.entry_ask == 1.10
    assert outcome.exit_bid == 1.30
    assert outcome.exit_reason == "profit_protect"
    assert outcome.raw_return_pct == 18.181818


def test_delayed_entry_rejects_unconfirmed_or_missing_ask(tmp_path: Path) -> None:
    negative = tmp_path / "negative.jsonl"
    missing = tmp_path / "missing.jsonl"
    _write(negative, _lifecycle(first_return=0.0))
    _write(missing, _lifecycle(first_return=5.0, first_ask=None))

    assert lab.replay(lab.load_lifecycles(negative)[0])[1] == "momentum_not_confirmed"
    assert lab.replay(lab.load_lifecycles(missing)[0])[1] == "missing_confirmation_ask"


def test_report_keeps_forward_pass_from_enabling_execution(tmp_path: Path) -> None:
    path = tmp_path / "log.jsonl"
    _write(path, _lifecycle(first_return=5.0))

    report = lab.build_report(path)

    assert report["forward_evidence"]["baseline"]["trades"] == 1
    assert report["paper_execution_enabled"] is False
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False
