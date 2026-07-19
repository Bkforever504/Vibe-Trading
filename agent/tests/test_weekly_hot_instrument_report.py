from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import weekly_hot_instrument_report as report


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def test_weekly_hot_report_combines_social_and_shadow_pnl(tmp_path: Path, monkeypatch) -> None:
    social_log = tmp_path / "social.jsonl"
    shadow_eval_log = tmp_path / "shadow_eval.jsonl"

    _write_jsonl(
        social_log,
        [
            {
                "date": "2026-07-01",
                "intraday_scan_index": 0,
                "symbols": [
                    {
                        "symbol": "TSLA",
                        "rank": 1,
                        "trending_score": 9.5,
                        "bucket": "ev_batteries",
                        "action": "watch_context",
                    },
                    {
                        "symbol": "FRMM",
                        "rank": 2,
                        "trending_score": 8.0,
                        "bucket": "social_squeeze_watch",
                        "action": "context_only",
                        "noise_flags": ["small-cap trend; high pump/fade risk"],
                    },
                ],
            },
            {
                "date": "2026-07-02",
                "intraday_scan_index": 1,
                "symbols": [
                    {
                        "symbol": "TSLA",
                        "rank": 3,
                        "trending_score": 7.0,
                        "bucket": "ev_batteries",
                        "action": "watch_context",
                    }
                ],
            },
        ],
    )
    _write_jsonl(
        shadow_eval_log,
        [
            {
                "date": "2026-07-02",
                "provider": "flip_shadow_pnl_evaluator",
                "execution_enabled": False,
                "by_symbol": {
                    "TSLA": {
                        "sample_count": 4,
                        "completed_count": 3,
                        "win_rate": 0.667,
                        "expectancy_return_pct": 12.5,
                        "best_return_pct": 1610.53,
                        "total_hypothetical_pnl": 3045.0,
                    },
                    "IWM": {
                        "sample_count": 3,
                        "completed_count": 3,
                        "win_rate": 1.0,
                        "expectancy_return_pct": 8.0,
                        "best_return_pct": 55.26,
                        "total_hypothetical_pnl": 335.0,
                    },
                },
            }
        ],
    )
    monkeypatch.setattr(report, "_cutoff_date", lambda days, today=None: "2026-06-26")

    built = report.build_report(
        social_log_path=social_log,
        shadow_eval_log_path=shadow_eval_log,
        social_arb_observations_path=tmp_path / "missing-social-arb.json",
        deep_universe_log_path=tmp_path / "missing-deep.jsonl",
        days=7,
        today="2026-07-02",
    )

    assert built["execution_enabled"] is False
    assert built["lookback_days"] == 7
    assert built["candidate_count"] == 3
    tsla = built["hot_instruments"][0]
    assert tsla["symbol"] == "TSLA"
    assert tsla["social_day_count"] == 2
    assert tsla["social_slot_count"] == 2
    assert tsla["shadow_completed_count"] == 3
    assert tsla["shadow_win_rate"] == 0.667
    assert tsla["shadow_expectancy_return_pct"] == 12.5
    assert tsla["action"] == "priority_shadow_review"
    assert "options/liquidity shadow evidence is building" in tsla["reasons"]
    frmm = next(item for item in built["hot_instruments"] if item["symbol"] == "FRMM")
    assert frmm["action"] == "research_only"
    assert any("small-cap" in flag for flag in frmm["risk_flags"])


def test_weekly_hot_report_stays_empty_without_logs(tmp_path: Path) -> None:
    built = report.build_report(
        social_log_path=tmp_path / "missing-social.jsonl",
        shadow_eval_log_path=tmp_path / "missing-shadow.jsonl",
        social_arb_observations_path=tmp_path / "missing-social-arb.json",
        deep_universe_log_path=tmp_path / "missing-deep.jsonl",
        days=7,
        today="2026-07-02",
    )

    assert built["candidate_count"] == 0
    assert built["hot_instruments"] == []
    assert built["mode"] == "read_only"


def test_weekly_hot_report_includes_manual_social_arbitrage_observations(tmp_path: Path, monkeypatch) -> None:
    social_arb_path = tmp_path / "social-arb-observations.json"
    social_arb_path.write_text(
        json.dumps(
            [
                {
                    "source": "x_manual",
                    "platform": "x",
                    "keyword": "FRMM",
                    "caption": "$FRMM short squeeze chatter from X and Reddit",
                    "observed_at": "2026-07-02",
                    "views": 601,
                }
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(report, "_cutoff_date", lambda days, today=None: "2026-06-26")

    built = report.build_report(
        social_log_path=tmp_path / "missing-social.jsonl",
        shadow_eval_log_path=tmp_path / "missing-shadow.jsonl",
        social_arb_observations_path=social_arb_path,
        deep_universe_log_path=tmp_path / "missing-deep.jsonl",
        days=7,
        today="2026-07-02",
    )

    assert built["candidate_count"] == 1
    frmm = built["hot_instruments"][0]
    assert frmm["symbol"] == "FRMM"
    assert frmm["bucket"] == "social_squeeze_watch"
    assert frmm["social_arb_source_count"] == 1
    assert frmm["action"] == "research_only"
    assert any("manual social observation" in reason for reason in frmm["reasons"])
    assert built["manual_social_instruments"][0]["symbol"] == "FRMM"


def test_weekly_hot_report_includes_deep_universe_candidates(tmp_path: Path, monkeypatch) -> None:
    deep_log = tmp_path / "deep.jsonl"
    _write_jsonl(
        deep_log,
        [
            {
                "date": "2026-07-02",
                "provider": "deep_liquid_universe_scanner",
                "execution_enabled": False,
                "top_candidates": [
                    {
                        "symbol": "AAPL",
                        "deep_score": 8.75,
                        "recommendation": "shadow_review_candidate",
                        "relative_volume": 2.2,
                        "one_day_pct": 3.5,
                        "twenty_day_pct": 9.1,
                        "reasons": ["persistent social attention", "high relative volume"],
                    }
                ],
            }
        ],
    )
    monkeypatch.setattr(report, "_cutoff_date", lambda days, today=None: "2026-06-26")

    built = report.build_report(
        social_log_path=tmp_path / "missing-social.jsonl",
        shadow_eval_log_path=tmp_path / "missing-shadow.jsonl",
        social_arb_observations_path=tmp_path / "missing-social-arb.json",
        deep_universe_log_path=deep_log,
        days=7,
        today="2026-07-02",
    )

    assert built["candidate_count"] == 1
    aapl = built["hot_instruments"][0]
    assert aapl["symbol"] == "AAPL"
    assert aapl["deep_universe_score"] == 8.75
    assert aapl["action"] == "watch_context"
    assert any("deep liquid universe scan" in reason for reason in aapl["reasons"])


def test_weekly_hot_report_does_not_double_count_cumulative_shadow_reports(tmp_path: Path, monkeypatch) -> None:
    shadow_log = tmp_path / "shadow.jsonl"
    _write_jsonl(
        shadow_log,
        [
            {"date": "2026-07-01", "timestamp": "2026-07-01T20:00:00Z", "by_symbol": {"QQQ": {"sample_count": 4, "completed_count": 4, "winner_count": 3, "expectancy_return_pct": 4.0}}},
            {"date": "2026-07-02", "timestamp": "2026-07-02T20:00:00Z", "by_symbol": {"QQQ": {"sample_count": 5, "completed_count": 5, "winner_count": 4, "expectancy_return_pct": 5.0}}},
        ],
    )
    monkeypatch.setattr(report, "_cutoff_date", lambda days, today=None: "2026-06-26")
    built = report.build_report(
        social_log_path=tmp_path / "missing-social.jsonl",
        shadow_eval_log_path=shadow_log,
        social_arb_observations_path=tmp_path / "missing-social-arb.json",
        deep_universe_log_path=tmp_path / "missing-deep.jsonl",
        today="2026-07-02",
    )
    qqq = built["hot_instruments"][0]
    assert qqq["shadow_sample_count"] == 5
    assert qqq["shadow_completed_count"] == 5
    assert qqq["shadow_expectancy_return_pct"] == 5.0


def test_high_win_rate_negative_expectancy_is_not_priority(tmp_path: Path, monkeypatch) -> None:
    shadow_log = tmp_path / "shadow.jsonl"
    _write_jsonl(
        shadow_log,
        [{"date": "2026-07-02", "by_symbol": {"TSLA": {"sample_count": 10, "completed_count": 10, "winner_count": 7, "win_rate": 0.7, "expectancy_return_pct": -6.0}}}],
    )
    monkeypatch.setattr(report, "_cutoff_date", lambda days, today=None: "2026-06-26")
    built = report.build_report(
        social_log_path=tmp_path / "missing-social.jsonl",
        shadow_eval_log_path=shadow_log,
        social_arb_observations_path=tmp_path / "missing-social-arb.json",
        deep_universe_log_path=tmp_path / "missing-deep.jsonl",
        today="2026-07-02",
    )
    tsla = built["hot_instruments"][0]
    assert tsla["shadow_win_rate"] == 0.7
    assert tsla["shadow_expectancy_return_pct"] == -6.0
    assert tsla["action"] != "priority_shadow_review"
    assert "shadow expectancy is non-positive" in tsla["reasons"]


def test_weekly_hot_report_blocks_explicit_illiquid_option_chain(tmp_path: Path) -> None:
    social_log = tmp_path / "social.jsonl"
    liquidity_report = tmp_path / "liquidity.json"
    _write_jsonl(
        social_log,
        [{"date": "2026-07-11", "intraday_scan_index": 0, "symbols": [{"symbol": "TSLA", "rank": 1, "trending_score": 10.0}]}],
    )
    liquidity_report.write_text(
        json.dumps(
            {
                "date": "2026-07-11",
                "results": [
                    {
                        "symbol": "TSLA",
                        "status": "ok",
                        "verdict": "not_qualified",
                        "has_weekly": True,
                        "spread_ok": False,
                        "volume_ok": True,
                        "price_ok": True,
                        "atm_spread_pct": 32.0,
                        "atm_volume_min": 2500,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    built = report.build_report(
        social_log_path=social_log,
        shadow_eval_log_path=tmp_path / "missing-shadow.jsonl",
        social_arb_observations_path=tmp_path / "missing-social-arb.json",
        deep_universe_log_path=tmp_path / "missing-deep.jsonl",
        options_liquidity_report_path=liquidity_report,
        today="2026-07-11",
    )

    tsla = next(item for item in built["hot_instruments"] if item["symbol"] == "TSLA")
    assert tsla["options_liquidity_checked"] is True
    assert tsla["options_execution_quality_ok"] is False
    assert tsla["action"] == "research_only"
    assert "options_spread_above_threshold" in tsla["risk_flags"]


def test_weekly_hot_report_records_executable_option_chain(tmp_path: Path) -> None:
    liquidity_report = tmp_path / "liquidity.json"
    liquidity_report.write_text(
        json.dumps(
            {
                "date": "2026-07-11",
                "results": [
                    {
                        "symbol": "SPY",
                        "status": "ok",
                        "verdict": "borderline",
                        "has_0dte": True,
                        "spread_ok": True,
                        "volume_ok": True,
                        "price_ok": True,
                        "atm_spread_pct": 1.2,
                        "atm_volume_min": 43000,
                        "atm_oi_min": 428,
                        "atm_price_per_contract": 169.0,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    built = report.build_report(
        social_log_path=tmp_path / "missing-social.jsonl",
        shadow_eval_log_path=tmp_path / "missing-shadow.jsonl",
        social_arb_observations_path=tmp_path / "missing-social-arb.json",
        deep_universe_log_path=tmp_path / "missing-deep.jsonl",
        options_liquidity_report_path=liquidity_report,
        today="2026-07-11",
    )

    spy = built["hot_instruments"][0]
    assert spy["symbol"] == "SPY"
    assert spy["options_execution_quality_ok"] is True
    assert spy["options_atm_volume_min"] == 43000
    assert "current option chain has executable spread, volume, and price" in spy["reasons"]
    assert [item["symbol"] for item in built["verifier_instruments"]] == ["SPY"]
