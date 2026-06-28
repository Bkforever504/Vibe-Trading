from pathlib import Path

import pandas as pd
import pytest

from research.pine_strategy_lab import (
    BacktestMetrics,
    PineStrategyIdea,
    RedFlagReport,
    evaluate_candidate,
    load_manifest_evaluations,
    parse_pine_strategy,
    scan_pine_red_flags,
    write_candidate_report,
)
from research.pine_strategy_lab_backtest import _equity_curve, _metrics_from_equity


def test_parse_pine_strategy_extracts_safe_metadata():
    source = """//@version=5
// License: MIT
// Source: https://example.com/open-strategy
strategy("VWAP ORB Pullback", overlay=true)
ema50 = ta.ema(close, 50)
vwap = ta.vwap(hlc3)
"""

    idea = parse_pine_strategy(source)

    assert idea.name == "VWAP ORB Pullback"
    assert idea.license == "MIT"
    assert idea.source_url == "https://example.com/open-strategy"
    assert idea.indicators == ["EMA", "VWAP"]
    assert idea.is_open_source is True


def test_evaluate_candidate_rejects_hype_backtest_even_with_large_return():
    idea = PineStrategyIdea(name="Moonshot", license="MIT", source_url="https://example.com", indicators=["VWAP"])
    metrics = BacktestMetrics(
        total_return_pct=2_000_000.0,
        profit_factor=120.0,
        max_drawdown_pct=4.0,
        trade_count=18,
        out_of_sample_profit_factor=0.9,
        walk_forward_pass_rate=0.25,
    )

    result = evaluate_candidate(idea, metrics)

    assert result.status == "rejected"
    assert result.confidence_score < 5
    assert "too few trades" in result.reject_reasons
    assert "profit factor is suspiciously high" in result.reject_reasons
    assert "weak out-of-sample profit factor" in result.reject_reasons
    assert "weak walk-forward pass rate" in result.reject_reasons


def test_evaluate_candidate_promotes_robust_paper_candidate():
    idea = PineStrategyIdea(name="VWAP Pullback", license="MIT", source_url="https://example.com", indicators=["EMA", "VWAP"])
    metrics = BacktestMetrics(
        total_return_pct=48.0,
        profit_factor=1.82,
        max_drawdown_pct=7.5,
        trade_count=145,
        out_of_sample_profit_factor=1.34,
        walk_forward_pass_rate=0.72,
    )

    result = evaluate_candidate(idea, metrics)

    assert result.status == "paper_candidate"
    assert result.confidence_score >= 7
    assert result.reject_reasons == []


def test_write_candidate_report_sorts_by_confidence_and_flags_rejections(tmp_path: Path):
    strong = evaluate_candidate(
        PineStrategyIdea(name="Strong", license="MIT", indicators=["ORB"]),
        BacktestMetrics(35.0, 1.7, 6.0, 120, 1.3, 0.75),
    )
    weak = evaluate_candidate(
        PineStrategyIdea(name="Weak", license="unknown", indicators=["RSI"]),
        BacktestMetrics(500.0, 12.0, 35.0, 9, 0.7, 0.1),
    )

    out = tmp_path / "report.md"
    write_candidate_report([weak, strong], out)

    text = out.read_text(encoding="utf-8")
    assert text.index("Strong") < text.index("Weak")
    assert "| Strong | paper_candidate |" in text
    assert "| Weak | rejected |" in text
    assert "unknown or non-open-source license" in text


def test_load_manifest_evaluations_reads_pine_files_and_metrics(tmp_path: Path):
    pine_file = tmp_path / "vwap.pine"
    pine_file.write_text(
        """//@version=5
// License: MIT
strategy("VWAP Candidate")
vwap = ta.vwap(hlc3)
""",
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        """
[
  {
    "pine_file": "vwap.pine",
    "metrics": {
      "total_return_pct": 41.5,
      "profit_factor": 1.65,
      "max_drawdown_pct": 8.2,
      "trade_count": 88,
      "out_of_sample_profit_factor": 1.22,
      "walk_forward_pass_rate": 0.66
    }
  }
]
""",
        encoding="utf-8",
    )

    evaluations = load_manifest_evaluations(manifest)

    assert len(evaluations) == 1
    assert evaluations[0].idea.name == "VWAP Candidate"
    assert evaluations[0].idea.indicators == ["VWAP"]
    assert evaluations[0].status == "paper_candidate"


# ── Red-flag scanner ───────────────────────────────────────────────────────────

_CLEAN = """//@version=5
// @license MIT
strategy("Clean", overlay=true, commission_type=strategy.commission.percent, commission_value=0.1, slippage=2)
ema = ta.ema(close, 20)
if close > ema
    strategy.entry("L", strategy.long)
"""

_LOOKAHEAD = """//@version=5
// @license MIT
strategy("Lookahead Trap", overlay=true)
htf = request.security("SPY", "D", close, barmerge.gaps_off, barmerge.lookahead_on)
if close > htf
    strategy.entry("L", strategy.long)
"""

_WARN_MULTI = """//@version=5
// @license MIT
strategy("Warn Multi", overlay=true)
htf = request.security("QQQ", "W", close)
ph  = ta.pivothigh(high, 3, 3)
if close > htf
    strategy.entry("L", strategy.long)
"""


def test_scan_clean_strategy_has_no_critical_flags():
    report = scan_pine_red_flags(_CLEAN)
    assert not report.has_critical
    assert not any(f.flag_id == "no_commission" for f in report.warning_flags)
    assert not any(f.flag_id == "no_slippage" for f in report.warning_flags)


def test_scan_detects_lookahead_on_as_critical():
    report = scan_pine_red_flags(_LOOKAHEAD)
    assert report.has_critical
    ids = [f.flag_id for f in report.critical_flags]
    assert "lookahead_on" in ids


def test_scan_detects_request_security_as_warning():
    report = scan_pine_red_flags(_LOOKAHEAD)
    ids = [f.flag_id for f in report.warning_flags]
    assert "request_security" in ids


def test_scan_detects_missing_commission_and_slippage():
    source = "//@version=5\n// @license MIT\nstrategy('NoSettings', overlay=true)\nif close > 0\n    strategy.entry('L', strategy.long)\n"
    report = scan_pine_red_flags(source)
    ids = [f.flag_id for f in report.warning_flags]
    assert "no_commission" in ids
    assert "no_slippage" in ids


def test_scan_detects_process_orders_on_close():
    source = "//@version=5\nstrategy('X', overlay=true, process_orders_on_close=true)\n"
    report = scan_pine_red_flags(source)
    ids = [f.flag_id for f in report.warning_flags]
    assert "process_orders_on_close" in ids


def test_scan_detects_calc_on_every_tick():
    source = "//@version=5\nstrategy('X', overlay=true, calc_on_every_tick=true)\n"
    report = scan_pine_red_flags(source)
    ids = [f.flag_id for f in report.warning_flags]
    assert "calc_on_every_tick" in ids


def test_scan_detects_pivot_repaint():
    report = scan_pine_red_flags(_WARN_MULTI)
    ids = [f.flag_id for f in report.warning_flags]
    assert "pivot_repaint" in ids


def test_scan_detects_fill_on_price_change():
    source = "//@version=5\n// @license MIT\nstrategy('X', overlay=true, fill_orders_on_price_change=true)\n"
    report = scan_pine_red_flags(source)
    ids = [f.flag_id for f in report.warning_flags]
    assert "fill_on_price_change" in ids


def test_scan_detects_pine_v6():
    source = "//@version=6\n// @license MIT\nstrategy('X', overlay=true)\n"
    report = scan_pine_red_flags(source)
    ids = [f.flag_id for f in report.warning_flags]
    assert "pine_v6" in ids


def test_scan_v6_is_warning_not_critical():
    source = "//@version=6\n// @license MIT\nstrategy('X', overlay=true)\n"
    report = scan_pine_red_flags(source)
    assert not report.has_critical
    assert any(f.flag_id == "pine_v6" for f in report.warning_flags)


def test_evaluate_critical_redflag_causes_rejection():
    idea = PineStrategyIdea(name="Trap", license="MIT")
    metrics = BacktestMetrics(50.0, 1.8, 8.0, 100, 1.3, 0.70)
    # Would pass on metrics alone — critical flag must force rejection
    report = scan_pine_red_flags(_LOOKAHEAD)
    result = evaluate_candidate(idea, metrics, red_flags=report)
    assert result.status == "rejected"
    assert any("[repaint]" in r for r in result.reject_reasons)


def test_evaluate_warnings_lower_score_but_dont_reject():
    idea = PineStrategyIdea(name="Warn", license="MIT")
    metrics = BacktestMetrics(50.0, 1.8, 8.0, 100, 1.3, 0.70)
    clean_result = evaluate_candidate(idea, metrics)
    warn_report = scan_pine_red_flags(_WARN_MULTI)
    warn_result = evaluate_candidate(idea, metrics, red_flags=warn_report)
    assert warn_result.status == "paper_candidate"
    assert warn_result.confidence_score < clean_result.confidence_score
    assert len(warn_result.red_flag_warnings) > 0


def test_write_report_includes_red_flag_column(tmp_path: Path):
    idea = PineStrategyIdea(name="Flagged", license="MIT")
    metrics = BacktestMetrics(50.0, 1.8, 8.0, 100, 1.3, 0.70)
    report = scan_pine_red_flags(_WARN_MULTI)
    result = evaluate_candidate(idea, metrics, red_flags=report)
    out = tmp_path / "report.md"
    write_candidate_report([result], out)
    text = out.read_text(encoding="utf-8")
    assert "Red Flag Warnings" in text
    assert "pivot_repaint" in text or "pivothigh" in text or "pivot" in text.lower()


def test_load_manifest_runs_scanner_on_pine_files(tmp_path: Path):
    pine = tmp_path / "trap.pine"
    pine.write_text(_LOOKAHEAD, encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        '[{"pine_file": "trap.pine", "metrics": {"total_return_pct": 50.0, "profit_factor": 1.8, '
        '"max_drawdown_pct": 8.0, "trade_count": 100, "out_of_sample_profit_factor": 1.3, '
        '"walk_forward_pass_rate": 0.70}}]',
        encoding="utf-8",
    )
    evaluations = load_manifest_evaluations(manifest)
    assert evaluations[0].status == "rejected"
    assert any("[repaint]" in r for r in evaluations[0].reject_reasons)


def test_backtest_metrics_use_completed_trade_pnl_not_bar_returns():
    idx = pd.date_range("2024-01-01", periods=6, freq="D")
    ohlcv = pd.DataFrame(
        {
            "open": [100, 110, 105, 107, 103, 110],
            "high": [100, 110, 105, 107, 103, 110],
            "low": [100, 110, 105, 107, 103, 110],
            "close": [100, 110, 105, 107, 103, 110],
            "volume": [1_000] * 6,
        },
        index=idx,
    )
    signals = pd.Series([1, 1, 0, -1, -1, 0], index=idx)

    equity = _equity_curve(ohlcv, signals, slippage_pct=0.0, commission_pct=0.0)
    metrics = _metrics_from_equity(equity, signals)

    assert metrics["trade_count"] == 2
    assert metrics["profit_factor"] == pytest.approx(1.511, rel=1e-3)
    assert metrics["avg_win_pct"] == pytest.approx(5.0, rel=1e-3)
    assert metrics["avg_loss_pct"] == pytest.approx(-3.309, rel=1e-3)
    assert metrics["expectancy_pct"] == pytest.approx(0.844, rel=1e-3)
    assert metrics["max_consecutive_losses"] == 1
    assert metrics["time_in_market_pct"] == pytest.approx(66.667, rel=1e-3)
    assert metrics["win_rate_pct"] == pytest.approx(50.0, rel=1e-3)
    assert metrics["sharpe_ratio"] > 0        # positive return → positive Sharpe
    assert metrics["calmar_ratio"] > 0        # positive return → positive Calmar
