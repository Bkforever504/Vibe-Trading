from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import closed_trade_postmortem as post


def test_score_flip_trade_penalizes_oversized_loser(monkeypatch) -> None:
    monkeypatch.setattr(post, "_latest_force_for_day", lambda day: {"classification": "bearish_confirmation"})
    trade = {
        "id": "t1",
        "strategy": "0dte",
        "symbol": "SPY",
        "right": "PUT",
        "contracts": 69,
        "pnl": -1000,
        "exit_reason": "STOP LOSS",
        "exit_date": "2026-06-30",
        "option_symbol": "SPYPUT",
    }

    result = post.score_flip_trade(trade)

    assert result["score"] <= 4
    assert result["grade"] in {"C", "D"}
    assert any("oversized" in reason for reason in result["reasons"])
    assert result["pnl_explanation"]["outcome"] == "loss"
    assert result["pnl_explanation"]["risk_lesson"] == "oversized versus current cap"


def test_score_flip_trade_explains_profit_giveback(monkeypatch) -> None:
    monkeypatch.setattr(post, "_latest_force_for_day", lambda day: {"classification": "bullish_confirmation"})
    trade = {
        "id": "t2",
        "strategy": "bull_trend",
        "symbol": "SPY",
        "right": "CALL",
        "contracts": 5,
        "entry_price": 0.78,
        "exit_price": 0.915,
        "best_pnl_pct": 66.03,
        "pnl": 67.5,
        "exit_reason": "PROFIT PROTECT +17.3% (best +66.0%)",
        "exit_date": "2026-07-06",
        "option_symbol": "SPYCALL",
    }

    result = post.score_flip_trade(trade)

    quality = result["pnl_explanation"]["exit_quality"]
    assert quality["giveback_pct"] == 48.72
    assert quality["capture_efficiency"] == 0.262
    assert "tighten profit-capture" in result["pnl_explanation"]["next_action"]
    assert result["pnl_explanation"]["pnl_source"] == "legacy_record_unverified_fill"


def test_score_flip_loss_after_green_excursion_does_not_emit_capture_gap(monkeypatch) -> None:
    monkeypatch.setattr(post, "_latest_force_for_day", lambda day: {"classification": "bearish_confirmation"})
    trade = {
        "id": "loss-after-green", "strategy": "0dte", "symbol": "SPY", "right": "CALL",
        "contracts": 1, "entry_price": 1.0, "exit_price": 0.6217,
        "best_pnl_pct": 12.61, "pnl": -37.83, "exit_reason": "STOP LOSS -37.8%",
        "exit_date": "2026-07-16", "option_symbol": "SPYCALL",
    }

    quality = post.score_flip_trade(trade)["pnl_explanation"]["exit_quality"]

    assert quality["exit_quality_classification"] == "stop_loss_after_favorable_excursion"
    assert quality["capture_efficiency"] is None
    assert quality["giveback_pct"] is None
    assert quality["favorable_excursion_surrendered_pct"] == 50.44


def test_score_flip_fast_stopout_labels_entry_regime_failure(monkeypatch) -> None:
    monkeypatch.setattr(post, "_latest_force_for_day", lambda day: {"classification": "bullish_confirmation"})
    trade = {
        "id": "fast-stop",
        "strategy": "bull_trend",
        "symbol": "SPY",
        "right": "CALL",
        "contracts": 2,
        "entry_price": 1.32,
        "exit_price": 0.725,
        "best_pnl_pct": 0.0,
        "pnl": -119.0,
        "exit_reason": "STOP LOSS -45.1%",
        "entry_at": "2026-07-17T16:00:24Z",
        "exit_at": "2026-07-17T16:05:04Z",
        "exit_date": "2026-07-17",
        "option_symbol": "SPYCALL",
    }

    explanation = post.score_flip_trade(trade)["pnl_explanation"]

    assert explanation["exit_quality"]["exit_quality_classification"] == "stop_loss_no_favorable_excursion"
    assert explanation["exit_quality"]["hold_minutes"] == 4.67
    assert "entry/regime failure" in explanation["primary_driver"]
    assert "consensus says stand_aside" in explanation["next_action"]


def test_score_iwm_trade_excludes_close_reason_estimate(monkeypatch) -> None:
    monkeypatch.setattr(post, "_latest_force_for_day", lambda day: {"classification": "bullish_confirmation"})
    trade = {
        "id": "i1",
        "strategy": "put_spread",
        "underlying": "IWM",
        "status": "closed",
        "closed_at": "2026-06-30T20:00:00Z",
        "closing_reason": "profit target hit: +55.8% of credit",
        "net_credit": 0.52,
        "qty": 3,
        "stop_loss_pct": -1.0,
        "candidate_confidence": {"score": 9, "credit_to_risk": 0.21, "reasons": ["acceptable credit/risk"]},
        "label": "Put Spread [IWM]",
    }

    result = post.score_iwm_trade(trade)

    assert result["score"] >= 8
    assert result["grade"] == "A"
    assert result["pnl"] is None
    assert result["pnl_estimated"] is False
    assert result["evidence_eligible"] is False
    assert result["pnl_explanation"]["outcome"] == "unknown"
    assert result["pnl_explanation"]["pnl_source"] == "unresolved_close_reason_not_accepted_as_pnl"


def test_score_iwm_trade_does_not_turn_stop_text_into_pnl(monkeypatch) -> None:
    monkeypatch.setattr(post, "_latest_force_for_day", lambda day: {"classification": "bearish_lean"})
    trade = {
        "id": "i2",
        "strategy": "put_spread",
        "underlying": "AAPL",
        "status": "closed",
        "closed_at": "2026-07-02T20:00:00Z",
        "closing_reason": "stop loss hit: -106.9% of credit",
        "net_credit": 0.87,
        "qty": 3,
        "stop_loss_pct": -1.0,
        "candidate_confidence": {"score": 9, "credit_to_risk": 0.2107, "reasons": ["underlying above trend filter"]},
        "label": "Put Spread [AAPL]",
    }

    result = post.score_iwm_trade(trade)

    assert result["pnl"] is None
    assert result["evidence_eligible"] is False
    assert result["pnl_explanation"]["outcome"] == "unknown"
    assert "realized option P/L is not available" in result["pnl_explanation"]["primary_driver"]


def test_score_iwm_trade_accepts_fill_derived_pnl(monkeypatch) -> None:
    monkeypatch.setattr(post, "_latest_force_for_day", lambda day: {"classification": "bullish_confirmation"})
    trade = {
        "id": "i3",
        "strategy": "put_spread",
        "underlying": "IWM",
        "status": "closed",
        "closed_at": "2026-06-30T20:00:00Z",
        "closing_reason": "profit target",
        "net_credit": 0.50,
        "closing_filled_avg_price": 0.10,
        "max_risk_per_contract": 150.0,
        "qty": 2,
        "stop_loss_pct": -1.0,
    }

    result = post.score_iwm_trade(trade)

    assert result["pnl"] == 80.0
    assert result["evidence_eligible"] is True
    assert result["pnl_explanation"]["pnl_source"] == "realized_or_fill_derived"


def test_build_report_reads_closed_trades(monkeypatch, tmp_path: Path) -> None:
    flip_path = tmp_path / "flip-trades.json"
    options_path = tmp_path / "options-trades.json"
    flip_path.write_text(json.dumps([{"id": "t1", "status": "closed", "exit_date": "2026-06-30", "contracts": 1, "pnl": 10}]), encoding="utf-8")
    options_path.write_text(json.dumps({"trades": []}), encoding="utf-8")
    monkeypatch.setattr(post, "VIBE_HOME", tmp_path)
    monkeypatch.setattr(post, "_latest_force_for_day", lambda day: None)

    report = post.build_report(day="2026-06-30")

    assert report["execution_enabled"] is False
    assert report["closed_trade_count"] == 1


def test_append_log_writes_jsonl(tmp_path: Path) -> None:
    path = tmp_path / "postmortem.jsonl"
    report = {"date": "2026-06-30", "provider": "closed_trade_postmortem"}

    post.append_log(report, path)

    assert json.loads(path.read_text(encoding="utf-8").strip()) == report


def test_collect_closed_options_dedupes_shared_order_id(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "flip-trades.json").write_text("[]", encoding="utf-8")
    (tmp_path / "options-trades.json").write_text(json.dumps({"trades": [
        {"id": "recovered-o1", "order_id": "o1", "status": "closed", "closed_at": "2026-07-13T15:00:00Z", "net_credit": 0.5},
        {"id": "original", "order_id": "o1", "status": "closed", "closed_at": "2026-07-13T15:00:00Z", "closing_reason": "profit target", "net_credit": 0.5, "pnl": 50},
    ]}), encoding="utf-8")
    monkeypatch.setattr(post, "VIBE_HOME", tmp_path)
    monkeypatch.setattr(post, "_latest_force_for_day", lambda day: None)

    rows = post.collect_closed_trades(day="2026-07-13")

    assert len(rows) == 1
    assert rows[0]["trade_id"] == "original"
