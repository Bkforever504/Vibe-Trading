from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from scripts import mnq_smt_family_shadow as family


def _frame(index: pd.DatetimeIndex, rows: list[dict[str, float]]) -> pd.DataFrame:
    return pd.DataFrame(rows, index=index)


def _pdl_fixture() -> tuple[pd.DataFrame, datetime]:
    prior = pd.date_range("2026-08-21 09:30", periods=2, freq="5min", tz=family.ET)
    current = pd.date_range("2026-08-24 09:30", periods=21, freq="5min", tz=family.ET)
    rows = [
        {"Open": 101.0, "High": 102.0, "Low": 100.0, "Close": 101.0, "Volume": 100.0},
        {"Open": 101.0, "High": 103.0, "Low": 100.5, "Close": 102.0, "Volume": 100.0},
    ]
    rows.extend(
        {"Open": 101.5, "High": 102.0, "Low": 100.5, "Close": 101.5, "Volume": 100.0}
        for _ in range(20)
    )
    rows.append({"Open": 100.2, "High": 101.0, "Low": 99.0, "Close": 100.6, "Volume": 200.0})
    frame = _frame(prior.append(current), rows)
    return frame, current[-1].to_pydatetime() + timedelta(minutes=5)


def test_frozen_configs_cover_four_independent_ablation_logs() -> None:
    assert set(family.STRATEGY_CONFIGS) == {
        "mnq-smt-cisd-fvg-v1",
        "mnq-pdl-rejection-v1",
        "mnq-smt-only-v1",
        "mnq-cisd-only-v1",
    }
    assert len({config.log_path for config in family.STRATEGY_CONFIGS.values()}) == 4
    assert all(config.spec_hash.startswith("sha256:") for config in family.STRATEGY_CONFIGS.values())
    assert all("executable_futures_bbo_required" in config.evidence_blockers for config in family.STRATEGY_CONFIGS.values())


def test_completed_bar_gate_excludes_still_forming_bar() -> None:
    index = pd.date_range("2026-08-24 09:30", periods=2, freq="5min", tz=family.ET)
    rows = [{"Open": 1, "High": 2, "Low": 0, "Close": 1, "Volume": 1}] * 2
    bars = _frame(index, rows)
    as_of = datetime(2026, 8, 24, 9, 39, tzinfo=family.ET)
    completed = family.completed_bars(bars, as_of=as_of, interval=timedelta(minutes=5))
    assert list(completed.index) == [index[0]]


def test_pdl_rejection_fixture_builds_specific_entry_stop_and_targets() -> None:
    bars, _as_of = _pdl_fixture()
    decision = family.detect_pdl_rejection(bars, date(2026, 8, 24))
    assert decision["should_enter"] is True
    plan = decision["plan"]
    assert plan["direction"] == "long"
    assert plan["entry_price"] == 100.6
    assert plan["stop_price"] == 98.75
    assert plan["t1_price"] > plan["entry_price"]
    assert plan["t2_price"] > plan["t1_price"]


def test_prior_rth_levels_skip_sunday_evening_only_calendar_date() -> None:
    friday = pd.DatetimeIndex([
        pd.Timestamp("2026-08-21 09:30", tz=family.ET),
        pd.Timestamp("2026-08-21 15:55", tz=family.ET),
    ])
    sunday = pd.DatetimeIndex([pd.Timestamp("2026-08-23 18:00", tz=family.ET)])
    bars = _frame(friday.append(sunday), [
        {"Open": 100, "High": 103, "Low": 99, "Close": 102, "Volume": 100},
        {"Open": 102, "High": 104, "Low": 100, "Close": 103, "Volume": 100},
        {"Open": 103, "High": 105, "Low": 102, "Close": 104, "Volume": 100},
    ])
    levels = family.prior_day_levels(bars, date(2026, 8, 24))
    assert levels == {"session_date": "2026-08-21", "pdh": 104.0, "pdl": 99.0}


def test_smt_only_and_cisd_only_fixtures_trigger() -> None:
    hourly = pd.date_range("2026-08-24 09:30", periods=2, freq="h", tz=family.ET)
    mnq = _frame(hourly, [
        {"Open": 100, "High": 102, "Low": 100, "Close": 101, "Volume": 100},
        {"Open": 100, "High": 101, "Low": 98, "Close": 99, "Volume": 100},
    ])
    es = _frame(hourly, [
        {"Open": 100, "High": 102, "Low": 100, "Close": 101, "Volume": 100},
        {"Open": 100, "High": 102, "Low": 100.5, "Close": 100, "Volume": 100},
    ])
    smt = family.detect_smt_only(mnq, es, date(2026, 8, 24))
    assert smt["should_enter"] is True
    assert smt["plan"]["direction"] == "long"

    index = pd.date_range("2026-08-24 09:30", periods=21, freq="5min", tz=family.ET)
    rows = [
        {"Open": 102, "High": 105, "Low": 100, "Close": 102, "Volume": 100}
        for _ in index
    ]
    rows[10] = {"Open": 104, "High": 110, "Low": 101, "Close": 104, "Volume": 100}
    rows[11] = {"Open": 102, "High": 104, "Low": 99, "Close": 102, "Volume": 100}
    rows[20] = {"Open": 101, "High": 112, "Low": 98, "Close": 111, "Volume": 200}
    cisd = family.detect_cisd_only(_frame(index, rows), date(2026, 8, 24))
    assert cisd["should_enter"] is True
    assert cisd["plan"]["direction"] == "long"


def test_composite_enforces_smt_then_cisd_then_retrace(monkeypatch) -> None:
    index = pd.date_range("2026-08-24 09:30", periods=8, freq="5min", tz=family.ET)
    rows = [
        {"Open": 104, "High": 105, "Low": 103, "Close": 104, "Volume": 100}
        for _ in index
    ]
    rows[5] = {"Open": 101.0, "High": 102.0, "Low": 99.0, "Close": 101.5, "Volume": 150}
    five = _frame(index, rows)
    smt_actionable = index[2].to_pydatetime()
    monkeypatch.setattr(family, "_smt_candidates", lambda *_args, **_kwargs: [{
        "direction": "long", "level_name": "PDL", "level_price": 100.0,
        "bar_timestamp": index[0].to_pydatetime(), "actionable_at": smt_actionable,
        "magnitude": 0.002,
    }])
    monkeypatch.setattr(family, "_cisd_candidates", lambda _rows: [{
        "direction": "long", "bar_timestamp": index[3].to_pydatetime(),
        "actionable_at": index[4].to_pydatetime(), "row": rows[3], "position": 3,
        "pivot_price": 100.0,
    }])
    monkeypatch.setattr(family, "_fvg_zones", lambda *_args: [{
        "type": "fvg", "low": 100.0, "high": 102.0, "formed_at": index[3].isoformat(),
    }])
    monkeypatch.setattr(family, "_order_block", lambda *_args: None)
    decision = family.detect_composite(five, five, five, date(2026, 8, 24))
    assert decision["should_enter"] is True
    trigger = decision["plan"]["trigger"]
    assert trigger["smt_actionable_at"] < trigger["cisd_actionable_at"] < decision["plan"]["actionable_at"]


def test_resolver_uses_adverse_first_when_stop_and_target_share_bar() -> None:
    actionable = datetime(2026, 8, 24, 10, 0, tzinfo=family.ET)
    bars = _frame(
        pd.DatetimeIndex([actionable]),
        [{"Open": 100, "High": 104, "Low": 97, "Close": 102, "Volume": 100}],
    )
    plan = {
        "actionable_at": actionable.isoformat(), "direction": "long",
        "entry_price": 100.0, "stop_price": 98.0, "t1_price": 102.0,
        "t2_price": 104.0, "stop_distance_pts": 2.0,
    }
    result = family.resolve_plan(bars, plan, as_of=actionable + timedelta(minutes=5))
    assert result is not None
    assert result["exit_reason"] == "stop_before_t1"
    assert result["outcome"] == "loss"


def test_entry_logging_is_idempotent_for_same_frozen_signal(tmp_path: Path, monkeypatch) -> None:
    bars, as_of = _pdl_fixture()
    monkeypatch.setattr(family, "download_family_data", lambda: {
        "mnq_5m": bars, "mnq_1h": bars, "nq_1h": bars, "mes_1h": bars, "es_1h": bars,
    })
    path = tmp_path / "pdl.jsonl"
    config = family.STRATEGY_CONFIGS["mnq-pdl-rejection-v1"]
    assert family.run_entry(config, as_of=as_of, log_path=path) == 0
    assert family.run_entry(config, as_of=as_of, log_path=path) == 0
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["should_enter"] is True
    assert rows[0]["execution_enabled"] is False
    assert rows[0]["can_submit_orders"] is False
    assert rows[0]["promotion_eligible"] is False
