from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import market_force_score as mfs


def _write(path: Path, row: dict) -> None:
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")


def test_trend_force_scores_opening_range_bias() -> None:
    force = mfs.trend_force({"aggregate": {"bias": "bearish_breadth", "breadth_score": -0.6}})

    assert force["name"] == "trend"
    assert force["score"] == -2.0
    assert force["direction"] == "bearish"


def test_gex_negative_gamma_amplifies_existing_trend() -> None:
    force = mfs.gex_force(
        {
            "scans": [
                {"status": "ok", "expiry_filter": "0dte", "size_source": "open_interest", "open_interest_coverage": 0.9, "net_gex_regime": "negative"},
                {"status": "ok", "expiry_filter": "0dte", "size_source": "open_interest", "open_interest_coverage": 0.9, "net_gex_regime": "negative"},
                {"status": "ok", "expiry_filter": "0dte", "size_source": "open_interest", "open_interest_coverage": 0.9, "net_gex_regime": "positive"},
            ]
        },
        trend_score=-2.0,
    )

    assert force["score"] == -1.0
    assert force["status"] == "trend_amplifier"


def test_gex_force_rejects_legacy_all_expiry_or_quote_size_rows() -> None:
    force = mfs.gex_force(
        {
            "scans": [
                {"status": "ok", "expiry_filter": "all", "net_gex_regime": "negative"},
                {"status": "ok", "expiry_filter": "0dte", "size_source": "ask_size_proxy", "open_interest_coverage": 1.0, "net_gex_regime": "negative"},
            ]
        },
        trend_score=-2.0,
    )

    assert force["score"] == 0.0
    assert force["status"] == "unavailable"


def test_momentum_force_votes_from_primary_and_comparison_actions() -> None:
    force = mfs.momentum_force(
        {"primary": {"action": "hold_long"}, "comparison": {"action": "flat"}},
        {"primary": {"action": "enter_short"}},
        None,
    )

    assert force["status"] == "ok"
    assert force["score"] == 0.0


def test_institutional_force_penalizes_distribution_regime() -> None:
    force = mfs.institutional_force({"aggregate": {"regime": "high", "max_distribution_days": 5}})

    assert force["name"] == "institutional"
    assert force["score"] == -1.5
    assert force["direction"] == "bearish"


def test_breadth_force_uses_market_breadth_score() -> None:
    force = mfs.breadth_force({"force_score": 1.75, "breadth": {"uptrend_status": "confirmed_uptrend"}})

    assert force["name"] == "breadth"
    assert force["score"] == 1.75
    assert force["direction"] == "bullish"


def test_sector_rotation_force_uses_rotation_score() -> None:
    force = mfs.sector_rotation_force({"force_score": -1.5, "rotation": {"leadership": "defensive_rotation"}})

    assert force["name"] == "sector_rotation"
    assert force["score"] == -1.5
    assert force["direction"] == "bearish"


def test_build_score_combines_forces_and_stays_read_only(tmp_path: Path, monkeypatch) -> None:
    paths = {name: tmp_path / f"{name}.jsonl" for name in mfs.SOURCE_PATHS}
    _write(paths["opening_range"], {"date": "2026-06-30", "aggregate": {"bias": "bullish_breadth"}})
    _write(paths["gex"], {"date": "2026-06-30", "scans": [{"status": "ok", "expiry_filter": "0dte", "size_source": "open_interest", "open_interest_coverage": 1.0, "net_gex_regime": "negative"}]})
    _write(paths["ivr"], {"date": "2026-06-30", "scans": [{"status": "accumulating", "ivr": None}]})
    _write(paths["preopen_sentiment"], {"date": "2026-06-30", "aggregate": {"bias": "bullish"}})
    _write(paths["social_trending"], {"date": "2026-06-30", "symbols": [{"symbol": "NVDA", "action": "watch_context"}]})
    _write(paths["relative_volume"], {"date": "2026-06-30", "unusual_symbols": [{"symbol": "NVDA", "price_change_pct": 2.5}]})
    _write(paths["distribution_days"], {"date": "2026-06-30", "aggregate": {"regime": "normal"}})
    _write(paths["market_breadth"], {"date": "2026-06-30", "force_score": 2.0, "breadth": {"uptrend_status": "confirmed_uptrend"}})
    _write(paths["sector_rotation"], {"date": "2026-06-30", "force_score": 1.5, "rotation": {"leadership": "risk_on_leadership"}})
    _write(paths["ttm_squeeze"], {"date": "2026-06-30", "primary": {"action": "hold_long"}})
    _write(paths["wavetrend"], {"date": "2026-06-30", "primary": {"action": "flat"}})
    _write(paths["smc"], {"date": "2026-06-30", "primary": {"action": "flat"}})
    monkeypatch.setattr(mfs, "risk_veto", lambda: {"active": False, "files": [], "status": "clear"})

    score = mfs.build_score(day="2026-06-30", paths=paths)

    assert score["mode"] == "read_only"
    assert score["execution_enabled"] is False
    assert score["classification"] == "bullish_confirmation"
    assert score["total_score"] >= 5.0
    assert score["coverage"]["available_forces"] == 8


def test_append_log_writes_jsonl(tmp_path: Path) -> None:
    path = tmp_path / "force.jsonl"
    entry = {"date": "2026-06-30", "provider": "market_force_score"}

    mfs.append_log(entry, path)

    assert json.loads(path.read_text(encoding="utf-8").strip()) == entry
