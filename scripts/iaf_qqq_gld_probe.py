"""Read-only probe inspired by coding-kitties/investing-algorithm-framework.

This is intentionally *not* a live trading adapter. It gives us a small,
framework-style validation harness for the QQQ/GLD rotation candidate:

1. Recompute the signal from close data.
2. Produce backtest-style summary metrics.
3. Compare the latest result with our existing shadow logger.

If this probe proves useful, it can be expanded to run more strategy candidates
through a consistent reporting layer before anything is considered for trading.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.market_data import data_source, fetch_close
from scripts.qqq_gld_shadow_logger import (
    DEFENSIVE_SYMBOL,
    LOG_PATH as SHADOW_LOG_PATH,
    LOOKBACK_DAYS,
    PRIMARY_SYMBOL,
    compute_signal_from_close,
    load_last_entry,
)

REPORT_PATH = Path.home() / ".vibe-trading" / "reports" / "iaf-qqq-gld-probe.json"
SOURCE_REPO = "coding-kitties/investing-algorithm-framework"


def compute_rotation_backtest(close: pd.DataFrame, lookback_days: int = LOOKBACK_DAYS) -> dict[str, Any]:
    """Compute framework-style metrics for QQQ/GLD relative momentum."""
    _validate_close(close, lookback_days)
    close = close[[PRIMARY_SYMBOL, DEFENSIVE_SYMBOL]].dropna().copy()
    returns = close.pct_change().fillna(0.0)

    primary_momentum = close[PRIMARY_SYMBOL] / close[PRIMARY_SYMBOL].shift(lookback_days) - 1
    defensive_momentum = close[DEFENSIVE_SYMBOL] / close[DEFENSIVE_SYMBOL].shift(lookback_days) - 1
    selected = pd.Series(PRIMARY_SYMBOL, index=close.index)
    selected[defensive_momentum > primary_momentum] = DEFENSIVE_SYMBOL
    selected = selected.dropna()

    valid_idx = selected.index[lookback_days:]
    if len(valid_idx) < 2:
        raise ValueError("Insufficient post-lookback rows for probe backtest")

    selected = selected.loc[valid_idx]
    daily_strategy_returns = []
    for dt in valid_idx:
        sym = selected.loc[dt]
        daily_strategy_returns.append(float(returns.loc[dt, sym]))
    strategy_returns = pd.Series(daily_strategy_returns, index=valid_idx)
    equity = (1.0 + strategy_returns).cumprod()

    latest_close = close.loc[: valid_idx[-1]]
    latest = compute_signal_from_close(latest_close, lookback_days=lookback_days)
    latest["date"] = _date_str(valid_idx[-1])

    switches = selected.ne(selected.shift(1)).sum()
    trade_count = max(0, int(switches) - 1)
    return {
        "latest": latest,
        "summary": {
            "start_date": _date_str(valid_idx[0]),
            "end_date": _date_str(valid_idx[-1]),
            "bars": int(len(valid_idx)),
            "trade_count": trade_count,
            "total_return_pct": round(float((equity.iloc[-1] - 1.0) * 100), 3),
            "max_drawdown_pct": round(_max_drawdown_pct(equity), 3),
            "sharpe_ratio": round(_sharpe(strategy_returns), 3),
            "execution_enabled": False,
            "data_source": data_source(),
        },
        "holdings_tail": [
            {"date": _date_str(idx), "selected": str(sym)}
            for idx, sym in selected.tail(10).items()
        ],
    }


def compare_to_shadow_entry(
    close: pd.DataFrame,
    shadow_entry: dict[str, Any] | None,
    lookback_days: int = LOOKBACK_DAYS,
) -> dict[str, Any]:
    if not shadow_entry:
        return {"status": "no_shadow_entry", "message": "No QQQ/GLD shadow log entry found."}

    shadow_date = str(shadow_entry.get("date") or "")
    sliced = _slice_to_shadow_date(close, shadow_date)
    probe = compute_signal_from_close(sliced, lookback_days=lookback_days, as_of=shadow_date or None)

    selected_match = probe.get("selected") == shadow_entry.get("selected")
    action_match = probe.get("action") == shadow_entry.get("action")
    status = "match" if selected_match and action_match else "mismatch"
    return {
        "status": status,
        "shadow_date": shadow_date,
        "shadow_selected": shadow_entry.get("selected"),
        "probe_selected": probe.get("selected"),
        "shadow_action": shadow_entry.get("action"),
        "probe_action": probe.get("action"),
        "selected_match": selected_match,
        "action_match": action_match,
    }


def load_shadow_entries(path: Path = SHADOW_LOG_PATH) -> list[dict[str, Any]]:
    """Load all QQQ/GLD shadow entries for replay comparison."""
    if not path.exists():
        return []
    entries: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and row.get("date"):
            entries.append(row)
    return entries


def replay_shadow_entries(
    close: pd.DataFrame,
    shadow_entries: list[dict[str, Any]] | None,
    *,
    lookback_days: int = LOOKBACK_DAYS,
    limit: int = 10,
) -> dict[str, Any]:
    """Replay the most recent shadow entries and verify framework parity."""
    entries = sorted(shadow_entries or [], key=lambda row: str(row.get("date") or ""))[-limit:]
    results = [
        compare_to_shadow_entry(close, entry, lookback_days=lookback_days)
        for entry in entries
    ]
    checked = len(results)
    matches = sum(1 for row in results if row.get("status") == "match")
    mismatches = sum(1 for row in results if row.get("status") == "mismatch")
    if checked == 0:
        status = "no_entries"
    elif mismatches == 0:
        status = "pass"
    else:
        status = "fail"
    return {
        "status": status,
        "checked": checked,
        "matches": matches,
        "mismatches": mismatches,
        "required_matches_before_expansion": 10,
        "expansion_allowed": checked >= 10 and mismatches == 0,
        "results": results,
    }


def build_probe_report(
    close: pd.DataFrame,
    shadow_entry: dict[str, Any] | None,
    lookback_days: int = LOOKBACK_DAYS,
    shadow_entries: list[dict[str, Any]] | None = None,
    replay_limit: int = 10,
) -> dict[str, Any]:
    backtest = compute_rotation_backtest(close, lookback_days=lookback_days)
    comparison = compare_to_shadow_entry(close, shadow_entry, lookback_days=lookback_days)
    replay = replay_shadow_entries(
        close,
        shadow_entries if shadow_entries is not None else ([shadow_entry] if shadow_entry else []),
        lookback_days=lookback_days,
        limit=replay_limit,
    )
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_repo": SOURCE_REPO,
        "source_repo_url": "https://github.com/coding-kitties/investing-algorithm-framework",
        "integration_mode": "sandbox_probe",
        "execution_enabled": False,
        "live_trading_allowed": False,
        "strategy": "qqq_gld_40d_rotation",
        "symbols": [PRIMARY_SYMBOL, DEFENSIVE_SYMBOL],
        "lookback_days": lookback_days,
        "probe": backtest,
        "shadow_comparison": comparison,
        "shadow_replay": replay,
        "promotion_rules": {
            "requires_shadow_match": True,
            "requires_10_date_replay_match_before_expansion": True,
            "requires_no_execution_calls": True,
            "may_not_replace_existing_guard_stack": True,
        },
    }


def write_report(report: dict[str, Any], path: Path = REPORT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def print_report(report: dict[str, Any]) -> None:
    summary = report["probe"]["summary"]
    latest = report["probe"]["latest"]
    comparison = report["shadow_comparison"]
    print("\nInvesting Algorithm Framework Probe: QQQ/GLD")
    print("=" * 58)
    print(f"Mode: {report['integration_mode']} | execution_enabled={report['execution_enabled']}")
    print(f"Latest: {latest['date']} selected={latest['selected']} action={latest['action']}")
    print(
        "Backtest: "
        f"return={summary['total_return_pct']:+.2f}% "
        f"DD={summary['max_drawdown_pct']:.2f}% "
        f"Sharpe={summary['sharpe_ratio']:.2f} "
        f"trades={summary['trade_count']}"
    )
    print(f"Shadow comparison: {comparison['status']}")
    replay = report["shadow_replay"]
    print(
        "Shadow replay: "
        f"{replay['status']} checked={replay['checked']} "
        f"matches={replay['matches']} mismatches={replay['mismatches']}"
    )
    print(f"Report: {REPORT_PATH}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run read-only QQQ/GLD IAF-style probe.")
    parser.add_argument("--lookback-days", type=int, default=LOOKBACK_DAYS)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--print", action="store_true", dest="do_print")
    args = parser.parse_args()

    close = fetch_close([PRIMARY_SYMBOL, DEFENSIVE_SYMBOL], lookback_days=max(220, args.lookback_days * 8))
    shadow_entry = load_last_entry(SHADOW_LOG_PATH)
    shadow_entries = load_shadow_entries(SHADOW_LOG_PATH)
    report = build_probe_report(
        close,
        shadow_entry,
        lookback_days=args.lookback_days,
        shadow_entries=shadow_entries,
    )
    write_report(report, args.report_path)
    if args.do_print:
        print_report(report)
    return 0


def _validate_close(close: pd.DataFrame, lookback_days: int) -> None:
    missing = {PRIMARY_SYMBOL, DEFENSIVE_SYMBOL} - set(close.columns)
    if missing:
        raise ValueError(f"Close data missing symbols: {sorted(missing)}")
    if len(close.dropna()) < lookback_days + 3:
        raise ValueError(f"Insufficient bars: {len(close.dropna())} < {lookback_days + 3}")


def _slice_to_shadow_date(close: pd.DataFrame, shadow_date: str) -> pd.DataFrame:
    if not shadow_date:
        return close
    target = pd.Timestamp(shadow_date)
    sliced = close.loc[close.index <= target]
    return sliced if not sliced.empty else close


def _max_drawdown_pct(equity: pd.Series) -> float:
    running_max = equity.cummax()
    drawdown = equity / running_max - 1.0
    return abs(float(drawdown.min() * 100.0))


def _sharpe(strategy_returns: pd.Series) -> float:
    if len(strategy_returns) < 2:
        return 0.0
    std = float(strategy_returns.std(ddof=1))
    if std == 0 or math.isnan(std):
        return 0.0
    return float(strategy_returns.mean() / std * math.sqrt(252))


def _date_str(value: Any) -> str:
    return value.date().isoformat() if hasattr(value, "date") else str(value)[:10]


if __name__ == "__main__":
    raise SystemExit(main())
