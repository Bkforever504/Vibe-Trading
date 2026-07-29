#!/usr/bin/env python3
"""Read-only quant risk budget for the Alpaca options bot.

This layer turns the useful parts of Kelly, Monte Carlo, Sharpe/Sortino,
GARCH, and option heat-map context into a conservative contract throttle. It
does not create direction signals and cannot submit orders.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import re
import sys
import tempfile
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

VIBE_HOME = Path.home() / ".vibe-trading"
DEFAULT_STATE_FILE = VIBE_HOME / "options-trades.json"
DEFAULT_GARCH_REPORT = VIBE_HOME / "reports" / "garch-volatility-risk.json"
DEFAULT_HEATMAP_REPORT = VIBE_HOME / "reports" / "options-liquidation-heatmap.json"
DEFAULT_OUTPUT = VIBE_HOME / "reports" / "options-quant-risk-budget.json"
LOG_PATH = ROOT / "data" / "options_quant_risk_budget_log.jsonl"

MIN_SAMPLE_FULL_WEIGHT = 30
BAYES_PRIOR_WINS = 2.0
BAYES_PRIOR_LOSSES = 2.0
MIN_PROVEN_GROUP_SAMPLES = 5
DEFAULT_EXPLORATION_RISK_FRACTION = 0.001
DEFAULT_EXPLORATION_MIN_CONFIDENCE = 9.0


def _utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        parsed = float(value)
        return parsed if math.isfinite(parsed) else default
    except (TypeError, ValueError):
        return default


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + f".tmp-{os.getpid()}-{datetime.now(timezone.utc).timestamp()}")
    try:
        temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temp, path)
        return path
    except OSError as exc:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
        payload.setdefault("warnings", []).append(f"Primary report path unavailable: {exc}")
        for fallback in (ROOT / "data" / path.name, Path(tempfile.gettempdir()) / path.name):
            try:
                fallback.parent.mkdir(parents=True, exist_ok=True)
                fallback.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
                return fallback
            except OSError as fallback_exc:
                payload.setdefault("warnings", []).append(f"Fallback report path unavailable: {fallback_exc}")
        return path


def _append_log(path: Path, payload: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n")
    except OSError:
        return


def _credit_basis(trade: dict[str, Any]) -> float:
    return abs(_safe_float(trade.get("net_credit"))) * max(1, int(_safe_float(trade.get("qty"), 1))) * 100.0


def realized_pnl_estimate(trade: dict[str, Any]) -> float | None:
    """Return best available closed-trade P/L estimate in dollars."""
    for key in ("realized_pnl_dollars", "pnl"):
        if trade.get(key) not in (None, ""):
            return _safe_float(trade.get(key))
    reason = str(trade.get("closing_reason") or trade.get("close_reason") or "")
    match = re.search(r"([+-]?\d+(?:\.\d+)?)%\s+of\s+credit", reason)
    basis = _credit_basis(trade)
    if match and basis > 0:
        return basis * float(match.group(1)) / 100.0
    return None


def _closed_trade_rows(state: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for trade in state.get("trades") or []:
        if not isinstance(trade, dict) or trade.get("status") != "closed":
            continue
        pnl = realized_pnl_estimate(trade)
        if pnl is None:
            continue
        risk = _safe_float(trade.get("max_risk_per_contract")) * max(1, int(_safe_float(trade.get("qty"), 1)))
        if risk <= 0:
            risk = _credit_basis(trade)
        rows.append({
            "symbol": str(trade.get("underlying") or "").upper() or "UNKNOWN",
            "strategy": str(trade.get("strategy") or "unknown"),
            "pnl": float(pnl),
            "risk": float(risk),
            "opened_at": trade.get("opened_at"),
            "closed_at": trade.get("closed_at"),
        })
    return rows


def _max_drawdown(values: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    worst = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        worst = min(worst, equity - peak)
    return worst


def _sharpe(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    var = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    stdev = math.sqrt(var)
    return mean / stdev if stdev > 0 else None


def _sortino(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    downside = [min(0.0, v) for v in values]
    downside_dev = math.sqrt(sum(v * v for v in downside) / len(values))
    return mean / downside_dev if downside_dev > 0 else None


def fractional_kelly(win_rate: float, avg_win: float, avg_loss: float) -> float:
    if avg_win <= 0 or avg_loss <= 0:
        return 0.0
    payoff = avg_win / avg_loss
    raw = win_rate - ((1.0 - win_rate) / payoff)
    return max(0.0, raw)


def monte_carlo_summary(
    pnls: list[float],
    *,
    paths: int = 2000,
    horizon: int = 50,
    seed: int = 1337,
) -> dict[str, Any]:
    if not pnls:
        return {"paths": 0, "horizon": horizon, "p95_drawdown_dollars": None, "loss_probability": None}
    rng = random.Random(seed)
    drawdowns: list[float] = []
    losses = 0
    for _ in range(paths):
        path = [rng.choice(pnls) for _ in range(horizon)]
        total = sum(path)
        if total < 0:
            losses += 1
        drawdowns.append(abs(_max_drawdown(path)))
    drawdowns.sort()
    idx = min(len(drawdowns) - 1, int(0.95 * len(drawdowns)))
    return {
        "paths": paths,
        "horizon": horizon,
        "p95_drawdown_dollars": round(drawdowns[idx], 2),
        "loss_probability": round(losses / paths, 4),
    }


def _garch_by_symbol(path: Path) -> dict[str, dict[str, Any]]:
    data = _load_json(path)
    rows = data.get("symbols") if isinstance(data, dict) else []
    return {
        str(row.get("symbol") or "").upper(): row
        for row in rows
        if isinstance(row, dict) and row.get("symbol")
    }


def _heat_by_symbol(path: Path) -> dict[str, dict[str, Any]]:
    data = _load_json(path)
    rows = data.get("results") if isinstance(data, dict) else []
    return {
        str(row.get("symbol") or "").upper(): row
        for row in rows
        if isinstance(row, dict) and row.get("symbol")
    }


def _heat_multiplier(row: dict[str, Any] | None) -> tuple[float, list[str]]:
    if not row or row.get("status") != "ok":
        return 1.0, ["heatmap_unavailable"]
    labels = {str(item) for item in (row.get("condition_labels") or [])}
    multiplier = 1.0
    reasons: list[str] = []
    if row.get("front_heat_state") == "near_major_heat_zone":
        multiplier *= 0.85
        reasons.append("near_major_options_heat_zone")
    if "call_oi_pressure" in labels or "put_oi_pressure" in labels:
        multiplier *= 0.90
        reasons.append("one_sided_open_interest_pressure")
    if "call_wall_dominant" in labels or "put_wall_dominant" in labels:
        multiplier *= 0.90
        reasons.append("dominant_wall_pin_or_reversal_risk")
    return max(0.25, multiplier), reasons or ["heatmap_normal"]


def _score_group(
    key: str,
    rows: list[dict[str, Any]],
    *,
    account_equity: float,
    max_risk_fraction: float,
    fractional_kelly_scalar: float,
    mc_paths: int,
    mc_horizon: int,
    garch_row: dict[str, Any] | None = None,
    heat_row: dict[str, Any] | None = None,
) -> dict[str, Any]:
    pnls = [float(row["pnl"]) for row in rows]
    wins = [p for p in pnls if p > 0]
    losses = [abs(p) for p in pnls if p < 0]
    n = len(pnls)
    win_rate = (len(wins) + BAYES_PRIOR_WINS) / (n + BAYES_PRIOR_WINS + BAYES_PRIOR_LOSSES) if n else 0.5
    avg_win = (sum(wins) / len(wins)) if wins else 0.0
    avg_loss = (sum(losses) / len(losses)) if losses else max(avg_win, 1.0)
    raw_kelly = fractional_kelly(win_rate, avg_win, avg_loss)
    sample_weight = min(1.0, n / MIN_SAMPLE_FULL_WEIGHT)
    kelly_cap = min(max_risk_fraction, raw_kelly * fractional_kelly_scalar * sample_weight)
    mc = monte_carlo_summary(pnls, paths=mc_paths, horizon=mc_horizon)
    mc_drawdown = _safe_float(mc.get("p95_drawdown_dollars"))
    mc_penalty = 1.0
    if account_equity > 0 and mc_drawdown > account_equity * 0.08:
        mc_penalty = 0.50
    elif account_equity > 0 and mc_drawdown > account_equity * 0.04:
        mc_penalty = 0.75
    garch_mult = 1.0
    garch_reason = "garch_unavailable"
    if garch_row:
        garch_mult = max(0.0, min(1.0, _safe_float(garch_row.get("position_size_multiplier"), 1.0)))
        garch_reason = str(garch_row.get("regime") or "garch_ok")
    heat_mult, heat_reasons = _heat_multiplier(heat_row)
    sharpe = _sharpe(pnls)
    sortino = _sortino(pnls)
    quality_penalty = 1.0
    if sortino is not None and sortino < 0:
        quality_penalty *= 0.5
    elif sortino is not None and sortino < 0.2:
        quality_penalty *= 0.75
    final_cap = max(0.0, min(max_risk_fraction, kelly_cap * mc_penalty * garch_mult * heat_mult * quality_penalty))
    return {
        "key": key,
        "sample_size": n,
        "wins": len(wins),
        "losses": len(losses),
        "bayesian_win_rate": round(win_rate, 4),
        "avg_win_dollars": round(avg_win, 2),
        "avg_loss_dollars": round(avg_loss, 2),
        "raw_kelly_fraction": round(raw_kelly, 6),
        "fractional_kelly_scalar": fractional_kelly_scalar,
        "sample_weight": round(sample_weight, 4),
        "kelly_risk_cap_fraction": round(kelly_cap, 6),
        "monte_carlo": mc,
        "monte_carlo_multiplier": mc_penalty,
        "garch_multiplier": round(garch_mult, 4),
        "garch_reason": garch_reason,
        "heatmap_multiplier": round(heat_mult, 4),
        "heatmap_reasons": heat_reasons,
        "sharpe_per_trade": round(sharpe, 4) if sharpe is not None else None,
        "sortino_per_trade": round(sortino, 4) if sortino is not None else None,
        "quality_multiplier": quality_penalty,
        "final_risk_cap_fraction": round(final_cap, 6),
        "final_risk_cap_dollars": round(final_cap * account_equity, 2),
        "action": "block_new_entries" if final_cap <= 0 else "allow_with_quant_size_cap",
    }


def build_report(
    *,
    state_file: Path = DEFAULT_STATE_FILE,
    garch_report: Path = DEFAULT_GARCH_REPORT,
    heatmap_report: Path = DEFAULT_HEATMAP_REPORT,
    account_equity: float = 100_000.0,
    max_risk_fraction: float = 0.01,
    fractional_kelly_scalar: float = 0.25,
    mc_paths: int = 2000,
    mc_horizon: int = 50,
) -> dict[str, Any]:
    state = _load_json(state_file)
    rows = _closed_trade_rows(state if isinstance(state, dict) else {"trades": []})
    garch = _garch_by_symbol(garch_report)
    heat = _heat_by_symbol(heatmap_report)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped["global"].append(row)
        grouped[f"symbol:{row['symbol']}"].append(row)
        grouped[f"strategy:{row['strategy']}"].append(row)
        grouped[f"symbol_strategy:{row['symbol']}:{row['strategy']}"].append(row)

    scored: dict[str, dict[str, Any]] = {}
    for key, group_rows in sorted(grouped.items()):
        symbol = None
        if key.startswith("symbol:"):
            symbol = key.split(":", 1)[1]
        elif key.startswith("symbol_strategy:"):
            symbol = key.split(":")[1]
        scored[key] = _score_group(
            key,
            group_rows,
            account_equity=account_equity,
            max_risk_fraction=max_risk_fraction,
            fractional_kelly_scalar=fractional_kelly_scalar,
            mc_paths=mc_paths,
            mc_horizon=mc_horizon,
            garch_row=garch.get(symbol or ""),
            heat_row=heat.get(symbol or ""),
        )
    return {
        "provider": "options_quant_risk_budget",
        "mode": "read_only_risk_allocator",
        "execution_enabled": False,
        "can_submit_orders": False,
        "date": date.today().isoformat(),
        "generated_at": _utc_now_text(),
        "state_file": str(state_file),
        "source_reports": {
            "garch": str(garch_report),
            "options_liquidation_heatmap": str(heatmap_report),
        },
        "parameters": {
            "account_equity": account_equity,
            "max_risk_fraction": max_risk_fraction,
            "fractional_kelly_scalar": fractional_kelly_scalar,
            "minimum_sample_full_weight": MIN_SAMPLE_FULL_WEIGHT,
            "monte_carlo_paths": mc_paths,
            "monte_carlo_horizon": mc_horizon,
        },
        "summary": {
            "closed_trade_samples": len(rows),
            "groups_scored": len(scored),
            "global_final_risk_cap_fraction": (scored.get("global") or {}).get("final_risk_cap_fraction"),
            "global_action": (scored.get("global") or {}).get("action"),
        },
        "groups": scored,
        "warnings": [
            "Kelly is shrunk for small samples and capped; it is not a promise of edge.",
            "Monte Carlo resamples observed trades and cannot see regimes absent from history.",
            "GARCH and heatmap context throttle size only; they are not direction signals.",
            "High-confidence new setups can receive a tiny exploration sleeve unless a proven symbol or strategy group is blocking.",
            "This report cannot submit, cancel, or modify broker orders.",
        ],
    }


def _find_group(report: dict[str, Any], symbol: str, strategy: str) -> dict[str, Any] | None:
    groups = report.get("groups") if isinstance(report, dict) else {}
    if not isinstance(groups, dict):
        return None
    keys = [
        f"symbol_strategy:{symbol.upper()}:{strategy}",
        f"symbol:{symbol.upper()}",
        f"strategy:{strategy}",
        "global",
    ]
    for key in keys:
        row = groups.get(key)
        if isinstance(row, dict):
            return row
    return None


def candidate_allocation(
    *,
    symbol: str,
    strategy: str,
    requested_qty: int,
    max_risk_per_contract: float,
    equity: float,
    confidence_score: float | None = None,
    report_path: Path = DEFAULT_OUTPUT,
    require_report: bool = False,
    exploration_risk_fraction: float | None = None,
    exploration_min_confidence: float | None = None,
) -> dict[str, Any]:
    if requested_qty <= 0:
        return {"allowed": False, "adjusted_qty": 0, "reason": "requested_qty_below_one"}
    if max_risk_per_contract <= 0 or equity <= 0:
        return {"allowed": False, "adjusted_qty": 0, "reason": "invalid_risk_or_equity"}
    report = _load_json(report_path)
    if not isinstance(report, dict):
        return {
            "allowed": not require_report,
            "adjusted_qty": requested_qty if not require_report else 0,
            "reason": "quant_risk_report_missing",
            "report_path": str(report_path),
        }
    group = _find_group(report, symbol, strategy)
    if not group:
        return {
            "allowed": not require_report,
            "adjusted_qty": requested_qty if not require_report else 0,
            "reason": "quant_risk_group_missing",
            "report_path": str(report_path),
        }
    cap = _safe_float(group.get("final_risk_cap_fraction"))
    exploration_cap = (
        _safe_float(os.getenv("OPTIONS_QUANT_EXPLORATION_RISK_FRACTION"), DEFAULT_EXPLORATION_RISK_FRACTION)
        if exploration_risk_fraction is None
        else max(0.0, exploration_risk_fraction)
    )
    min_exploration_conf = (
        _safe_float(os.getenv("OPTIONS_QUANT_EXPLORATION_MIN_CONFIDENCE"), DEFAULT_EXPLORATION_MIN_CONFIDENCE)
        if exploration_min_confidence is None
        else exploration_min_confidence
    )
    groups = report.get("groups") if isinstance(report.get("groups"), dict) else {}
    specific_keys = [
        f"symbol_strategy:{symbol.upper()}:{strategy}",
        f"symbol:{symbol.upper()}",
        f"strategy:{strategy}",
    ]
    proven_specific = [
        row for key in specific_keys
        if isinstance((row := groups.get(key)), dict)
        and _safe_float(row.get("sample_size")) >= MIN_PROVEN_GROUP_SAMPLES
    ]
    proven_block = any(_safe_float(row.get("final_risk_cap_fraction")) <= 0 for row in proven_specific)
    used_exploration = False
    if (
        cap <= 0
        and not proven_block
        and confidence_score is not None
        and confidence_score >= min_exploration_conf
        and exploration_cap > 0
    ):
        cap = min(exploration_cap, _safe_float(report.get("parameters", {}).get("max_risk_fraction"), exploration_cap))
        used_exploration = True
    if confidence_score is not None and confidence_score < 9:
        cap *= max(0.25, confidence_score / 10.0)
    allowed_qty = int((equity * cap) // max_risk_per_contract) if cap > 0 else 0
    adjusted = min(requested_qty, allowed_qty)
    return {
        "allowed": adjusted >= 1,
        "adjusted_qty": max(0, adjusted),
        "reason": (
            "quant_risk_exploration_cap"
            if used_exploration
            else "quant_risk_size_cap" if adjusted < requested_qty
            else "quant_risk_ok"
        ),
        "requested_qty": requested_qty,
        "allowed_qty_by_budget": allowed_qty,
        "risk_cap_fraction": round(cap, 6),
        "risk_cap_dollars": round(equity * cap, 2),
        "exploration_cap_used": used_exploration,
        "exploration_blocked_by_proven_group": proven_block,
        "max_risk_per_contract": round(max_risk_per_contract, 2),
        "selected_group": group.get("key"),
        "sample_size": group.get("sample_size"),
        "raw_kelly_fraction": group.get("raw_kelly_fraction"),
        "monte_carlo": group.get("monte_carlo"),
        "garch_multiplier": group.get("garch_multiplier"),
        "heatmap_multiplier": group.get("heatmap_multiplier"),
        "sortino_per_trade": group.get("sortino_per_trade"),
        "report_path": str(report_path),
    }


def print_report(report: dict[str, Any]) -> None:
    summary = report.get("summary", {})
    print("Options Quant Risk Budget | read-only")
    print("=" * 72)
    print(
        f"samples={summary.get('closed_trade_samples')} "
        f"groups={summary.get('groups_scored')} "
        f"global_cap={summary.get('global_final_risk_cap_fraction')}"
    )
    groups = report.get("groups") if isinstance(report.get("groups"), dict) else {}
    for key in ("global", "strategy:put_spread", "strategy:call_spread", "strategy:iron_condor"):
        row = groups.get(key)
        if row:
            print(
                f"{key:<28} n={row['sample_size']:<3} "
                f"kelly={row['raw_kelly_fraction']:<8} cap={row['final_risk_cap_fraction']:<8} "
                f"sortino={row['sortino_per_trade']}"
            )
    print("No orders placed. Output is a sizing throttle only.\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    account_override = _safe_float(os.getenv("ACCOUNT_SIZE_OVERRIDE"), 0.0)
    default_equity = account_override if account_override > 0 else 100000.0
    parser.add_argument("--state-file", type=Path, default=DEFAULT_STATE_FILE)
    parser.add_argument("--garch-report", type=Path, default=DEFAULT_GARCH_REPORT)
    parser.add_argument("--heatmap-report", type=Path, default=DEFAULT_HEATMAP_REPORT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--account-equity", type=float, default=default_equity)
    parser.add_argument("--max-risk-fraction", type=float, default=float(os.getenv("OPTIONS_QUANT_MAX_RISK_FRACTION", "0.01")))
    parser.add_argument("--fractional-kelly", type=float, default=float(os.getenv("OPTIONS_QUANT_FRACTIONAL_KELLY", "0.25")))
    parser.add_argument("--mc-paths", type=int, default=2000)
    parser.add_argument("--mc-horizon", type=int, default=50)
    parser.add_argument("--print", dest="do_print", action="store_true")
    args = parser.parse_args(argv)

    report = build_report(
        state_file=args.state_file,
        garch_report=args.garch_report,
        heatmap_report=args.heatmap_report,
        account_equity=args.account_equity,
        max_risk_fraction=args.max_risk_fraction,
        fractional_kelly_scalar=args.fractional_kelly,
        mc_paths=args.mc_paths,
        mc_horizon=args.mc_horizon,
    )
    written = _write_json(args.output, report)
    _append_log(LOG_PATH, report)
    if args.do_print:
        print_report(report)
    else:
        print(f"Options quant risk budget wrote {written}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
