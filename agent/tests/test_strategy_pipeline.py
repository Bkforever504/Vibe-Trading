import copy
import json
import subprocess
import sys
from pathlib import Path

from research.strategy_language import interpret_description
from research.strategy_pipeline import packet_id, validate_packet


def _packet():
    return {
        "schema_version": 1,
        "name": "SPY 30m continuation",
        "thesis": "Enter after a confirmed first-30-minute range break.",
        "market": {
            "asset_class": "equity_options",
            "symbols": ["SPY"],
            "timeframe": "1m",
            "timezone": "America/New_York",
        },
        "rules": {
            "setup": "completed 30-minute opening range",
            "entry": "close above opening-range high",
            "stop": "opening-range low",
            "targets": ["2R"],
            "exit": "stop, target, or 15:45 ET",
            "sizing": "fixed paper unit",
            "session": "09:30-15:45 ET",
        },
        "data": {"bars": ["1m", "1d"], "point_in_time_required": True},
        "research": {
            "dataset_start": "2025-01-01",
            "dataset_end": "2025-12-31",
            "oos_start": "2025-10-01",
            "oos_end": "2025-12-31",
            "benchmark": "SPY",
            "cost_model": "options_quote_mid_plus_half_spread",
        },
        "provenance": {"original_prompt": "explicit test prompt", "source": "test"},
        "authority": {
            "mode": "research_only",
            "execution_enabled": False,
            "can_submit_orders": False,
            "promotion_requires_human_approval": True,
        },
    }


def test_packet_id_is_stable_and_ignores_runtime_metadata():
    left = _packet()
    right = {**_packet(), "created_at": "2026-07-15T18:00:00Z"}
    assert packet_id(left) == packet_id(right)


def test_rule_change_creates_new_packet_id():
    changed = copy.deepcopy(_packet())
    changed["rules"]["targets"] = ["3R"]
    assert packet_id(_packet()) != packet_id(changed)


def test_missing_stop_fails_closed():
    packet = _packet()
    packet["rules"]["stop"] = ""
    result = validate_packet(packet)
    assert result.valid is False
    assert "missing_rules.stop" in result.errors


def test_authority_must_be_research_only():
    packet = _packet()
    packet["authority"]["execution_enabled"] = True
    result = validate_packet(packet)
    assert result.valid is False
    assert "authority.execution_enabled_must_be_false" in result.errors


def test_explicit_labeled_description_builds_complete_rules():
    result = interpret_description(
        "symbol: SPY; timeframe: 1m; setup: first 30 minute range complete; "
        "entry: close above range high; stop: range low; target: 2R; "
        "exit: stop, target, or 15:45 ET; sizing: fixed paper unit; "
        "session: 09:30-15:45 ET"
    )
    assert result.status == "ready_for_validation"
    assert result.fields["symbols"] == ["SPY"]
    assert result.fields["rules"]["targets"] == ["2R"]


def test_unlabeled_promo_language_never_invents_risk_rules():
    result = interpret_description("Buy SPY calls when it looks ready to explode.")
    assert result.status == "needs_rules"
    assert "stop" in result.missing_fields
    assert "exit" in result.missing_fields
    assert result.fields.get("stop") is None


def test_unknown_clause_is_preserved_as_ambiguity():
    result = interpret_description(
        "symbol: SPY; timeframe: 1m; setup: range; entry: break; stop: low; "
        "target: 2R; exit: target or stop; sizing: fixed; session: regular; magic: high"
    )
    assert result.status == "needs_rules"
    assert result.ambiguities == ("unsupported_clause.magic",)


def test_cli_has_no_live_or_execute_command():
    result = subprocess.run(
        [sys.executable, "scripts/strategy_pipeline.py", "--help"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "intake" in result.stdout
    assert "validate" in result.stdout
    assert "run" in result.stdout
    assert " live" not in result.stdout.lower()
    assert "execute" not in result.stdout.lower()


def test_cli_intake_returns_needs_rules_without_inventing_fields(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "scripts/strategy_pipeline.py",
            "intake",
            "--describe",
            "Buy SPY calls when ready",
            "--name",
            "draft",
            "--out-dir",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    payload = json.loads(result.stdout)
    assert result.returncode == 2
    assert payload["status"] == "needs_rules"
    assert payload["execution_enabled"] is False
    assert payload["can_submit_orders"] is False
    assert list(tmp_path.iterdir()) == []


def test_strat_packet_links_existing_shadow_implementation():
    packet = json.loads(
        Path("research/strategy_packets/strat_30m_continuation_v1.json").read_text(encoding="utf-8")
    )
    assert validate_packet(packet).valid is True
    assert packet["adapter"]["module"] == "strategies.strat_30m_continuation"
    assert packet["adapter"]["callable"] == "evaluate_strat_30m"
    assert packet["monitor"]["script"] == "scripts/strat_30m_continuation_shadow.py"
    assert packet["authority"]["mode"] == "research_only"
    assert packet["research"]["evidence_type"] == "underlying_counterfactual"
