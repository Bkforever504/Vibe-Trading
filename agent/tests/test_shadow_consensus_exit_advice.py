from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_exit_advice_detects_directional_playbook_flip(tmp_path) -> None:
    from strategies import shadow_consensus

    report = tmp_path / "shadow-consensus-gate.json"
    report.write_text(
        json.dumps(
            {
                "decisions": [
                    {
                        "symbol": "SPY",
                        "recommendation": "needs_review",
                        "options_playbook": "directional_long_put",
                        "blockers": [],
                        "reasons": ["Bearish playbook selected."],
                        "shadow_exit_control_eligible": True,
                    }
                ],
                "portfolio_kill_switch": {"active": False},
            }
        ),
        encoding="utf-8",
    )

    advice = shadow_consensus.exit_advice("SPY", "CALL", report_path=report, enabled=True)

    assert advice["action"] == "review_exit"
    assert "shadow_direction_flip" in advice["blockers"]


def test_exit_advice_keeps_unpromoted_direction_flip_advisory(tmp_path) -> None:
    from strategies import shadow_consensus

    report = tmp_path / "shadow-consensus-gate.json"
    report.write_text(json.dumps({"decisions": [{
        "symbol": "SPY", "recommendation": "stand_aside", "options_playbook": "directional_long_put",
        "blockers": [], "reasons": [], "shadow_exit_control_eligible": False,
    }], "portfolio_kill_switch": {"active": False}}), encoding="utf-8")

    advice = shadow_consensus.exit_advice("SPY", "CALL", report_path=report, enabled=True)

    assert advice["action"] == "hold"
    assert advice["review_recommended"] is True
    assert "shadow_exit_not_oos_ready" in advice["blockers"]
