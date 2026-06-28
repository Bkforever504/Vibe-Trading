from __future__ import annotations

from pathlib import Path

from research.pine_source_scanner import scan_pine_source_dir, write_pine_source_report


def test_scan_pine_source_dir_counts_scripts_and_red_flags(tmp_path: Path) -> None:
    clean = tmp_path / "oscillators" / "clean_rsi.pine"
    clean.parent.mkdir()
    clean.write_text(
        "//@version=4\n"
        "// Clean RSI script may be freely distributed under the terms of the GPL-3.0 license.\n"
        "study('Clean RSI')\n"
        "r = rsi(close, 14)\n",
        encoding="utf-8",
    )
    trap = tmp_path / "statistics" / "lookahead.pine"
    trap.parent.mkdir()
    trap.write_text(
        "//@version=4\n"
        "// Lookahead script may be freely distributed under the terms of the GPL-3.0 license.\n"
        "study('Lookahead')\n"
        "x = security('SPY', timeframe.period, close, barmerge.gaps_off, barmerge.lookahead_on)\n",
        encoding="utf-8",
    )

    summary = scan_pine_source_dir(tmp_path)

    assert summary.total_files == 2
    assert summary.indicator_files == 2
    assert summary.strategy_files == 0
    assert summary.critical_files == 1
    assert summary.warning_files == 1
    assert summary.clean_files == 1
    assert summary.rows[0].relative_path == "oscillators/clean_rsi.pine"
    assert summary.rows[1].critical_flags == ["lookahead_on"]
    assert "legacy_security" in summary.rows[1].warning_flags


def test_write_pine_source_report_includes_candidate_queue(tmp_path: Path) -> None:
    source = tmp_path / "movings" / "adaptive_ma.pine"
    source.parent.mkdir()
    source.write_text(
        "//@version=4\n"
        "// Adaptive MA script may be freely distributed under the terms of the GPL-3.0 license.\n"
        "study('Adaptive MA', overlay=true)\n"
        "plot(ema(close, 20))\n",
        encoding="utf-8",
    )

    summary = scan_pine_source_dir(tmp_path)
    out = tmp_path / "report.md"
    write_pine_source_report(summary, out)

    text = out.read_text(encoding="utf-8")
    assert "Pine Source Scan Report" in text
    assert "adaptive_ma.pine" in text
    assert "Translation Queue" in text


def test_write_pine_source_report_includes_noncritical_strategy_review_queue(tmp_path: Path) -> None:
    source = tmp_path / "strategies" / "momentum" / "macd_strategy.pine"
    source.parent.mkdir(parents=True)
    source.write_text(
        "//@version=5\n"
        "// @license MIT\n"
        "strategy('MACD Strategy', commission_type=strategy.commission.percent, commission_value=0.1)\n"
        "if close > ta.ema(close, 20)\n"
        "    strategy.entry('L', strategy.long)\n",
        encoding="utf-8",
    )

    summary = scan_pine_source_dir(tmp_path)
    out = tmp_path / "report.md"
    write_pine_source_report(summary, out)

    text = out.read_text(encoding="utf-8")
    assert "Strategy Review Queue" in text
    assert "macd_strategy.pine" in text
    assert "no_slippage" in text
