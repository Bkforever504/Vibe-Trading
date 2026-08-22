from datetime import date

import pandas as pd

from research.momentum_edge_ensemble_lab import ALL_SYMBOLS
from scripts.momentum_edge_ensemble_shadow import build_decision, write_idempotent


def _prices(rows=320):
    index = pd.bdate_range("2025-01-02", periods=rows)
    return pd.DataFrame({
        symbol: [100.0 * (1.0005 + position * 0.00001) ** day for day in range(rows)]
        for position, symbol in enumerate(ALL_SYMBOLS)
    }, index=index)


def test_shadow_decision_has_no_execution_authority():
    decision = build_decision(_prices(), generated_on=date(2026, 8, 17))

    assert decision["execution_enabled"] is False
    assert decision["can_submit_orders"] is False
    assert decision["promotion_eligible"] is False
    assert decision["maximum_asset_weight"] <= 0.35
    assert sum(decision["allocations"].values()) + decision["cash_weight"] <= 1.000001


def test_shadow_log_replaces_same_signal_date(tmp_path):
    path = tmp_path / "shadow.jsonl"
    first = {"signal_asof": "2026-08-14", "value": 1}
    second = {"signal_asof": "2026-08-14", "value": 2}

    write_idempotent(first, path)
    write_idempotent(second, path)

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert '"value": 2' in lines[0]
