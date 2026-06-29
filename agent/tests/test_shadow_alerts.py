from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.shadow_alerts import format_alert, should_alert


def test_should_alert_on_fresh_enter_long() -> None:
    entry = {
        "date": "2026-06-29",
        "primary_setup": {"action": "enter_long", "name": "rsi2", "confidence": 9.1},
    }

    assert should_alert(entry, prev=None) is True


def test_should_not_alert_when_same_date_already_logged() -> None:
    entry = {
        "date": "2026-06-29",
        "primary_setup": {"action": "enter_long", "name": "rsi2", "confidence": 9.1},
    }
    prev = {"date": "2026-06-29"}

    assert should_alert(entry, prev=prev) is False


def test_should_alert_on_rotation_and_rebalance() -> None:
    assert should_alert({"date": "2026-06-29", "action": "rotate_to_gld"}, prev={"date": "2026-06-22"}) is True
    assert should_alert({"date": "2026-06-29", "action": "rebalance"}, prev={"date": "2026-06-22"}) is True


def test_format_alert_includes_vix_context_and_shadow_only_note() -> None:
    entry = {
        "date": "2026-06-29",
        "execution_mode": "shadow_only",
        "data_source": "alpaca",
        "symbol": "QQQ",
        "vix_context": {"close": 21.34, "regime": "elevated"},
        "primary_setup": {
            "action": "enter_long",
            "name": "rsi2_prior_high_source",
            "confidence": 8.7,
        },
    }

    text = format_alert("RSI-2 QQQ", entry)

    assert "RSI-2 QQQ" in text
    assert "VIX" in text
    assert "21.34" in text
    assert "No orders placed" in text
