from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import clear_iwm_residual_position as clear


def _reconciliation(path: Path, qty: float = 2.0) -> Path:
    path.write_text(json.dumps({
        "broker_positions": [
            {
                "symbol": "IWM260807C00315000",
                "qty": qty,
                "avg_entry_price": 1.04,
                "current_price": 0.02,
                "market_value": 4.0,
                "unrealized_pl": -204.0,
            }
        ],
        "position_source": {"provider": "alpaca_live_read_only"},
    }), encoding="utf-8")
    return path


def test_clearance_plan_defaults_to_dry_run_and_exact_close_action(tmp_path: Path) -> None:
    report = _reconciliation(tmp_path / "reconciliation.json")

    plan = clear.build_clearance_plan(reconciliation_path=report)

    assert plan["execution_enabled"] is False
    assert plan["can_submit_orders"] is False
    assert plan["clearance_ready"] is True
    assert plan["planned_broker_action"] == {
        "action": "close_position",
        "symbol": "IWM260807C00315000",
        "qty": 2,
        "effect": "sell_to_close long residual option contracts",
        "submitter": "alpaca.trading.client.TradingClient.close_position",
    }
    assert plan["confirmation_phrase"] == "CLOSE IWM260807C00315000"


def test_clearance_plan_refuses_quantity_mismatch(tmp_path: Path) -> None:
    report = _reconciliation(tmp_path / "reconciliation.json", qty=1.0)

    plan = clear.build_clearance_plan(reconciliation_path=report)

    assert plan["clearance_ready"] is False
    assert plan["planned_broker_action"] is None
    assert "qty mismatch" in plan["issues"][0]


def test_main_execute_requires_confirmation_phrase(tmp_path: Path, monkeypatch) -> None:
    report = _reconciliation(tmp_path / "reconciliation.json")
    output = tmp_path / "clearance.json"
    calls = []
    monkeypatch.setattr(clear, "execute_clearance", lambda *_args: calls.append(_args))

    code = clear.main([
        "--reconciliation", str(report),
        "--output", str(output),
        "--execute",
        "--confirm", "wrong",
    ])

    assert code == 2
    assert calls == []
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["execution_attempt"]["submitted"] is False


def test_main_execute_calls_broker_only_after_confirmation(tmp_path: Path, monkeypatch) -> None:
    report = _reconciliation(tmp_path / "reconciliation.json")
    output = tmp_path / "clearance.json"
    calls = []

    def fake_execute(symbol: str, expected_qty: int) -> dict:
        calls.append((symbol, expected_qty))
        return {"submitted": True, "broker_response": "ok"}

    monkeypatch.setattr(clear, "execute_clearance", fake_execute)

    code = clear.main([
        "--reconciliation", str(report),
        "--output", str(output),
        "--execute",
        "--confirm", "CLOSE IWM260807C00315000",
    ])

    assert code == 0
    assert calls == [("IWM260807C00315000", 2)]
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["execution_attempt"]["submitted"] is True


def test_execute_clearance_returns_broker_failure_without_crashing(monkeypatch) -> None:
    class FailingClient:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def close_position(self, _symbol: str) -> None:
            raise RuntimeError("market closed")

    monkeypatch.setenv("ALPACA_API_KEY", "key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "secret")
    monkeypatch.setattr(clear, "_live_position", lambda _symbol: (
        {"symbol": "IWM260807C00315000", "qty": 2.0},
        {"provider": "test"},
    ))
    monkeypatch.setitem(sys.modules, "alpaca.trading.client", type("M", (), {"TradingClient": FailingClient}))

    result = clear.execute_clearance("IWM260807C00315000", 2)

    assert result["submitted"] is False
    assert "market closed" in result["issues"][0]
