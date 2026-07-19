#!/usr/bin/env python3
"""Read-only PCA market forces scanner.

Compresses a liquid equity universe into principal return forces so we can tell
whether a symbol is moving with the market/sector tape or showing idiosyncratic
residual behavior. Context only; no orders.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LOG_PATH = ROOT / "data" / "pca_market_forces_log.jsonl"
REPORT_PATH = Path.home() / ".vibe-trading" / "reports" / "pca-market-forces.json"
UNIVERSE = ["SPY", "QQQ", "IWM", "SMH", "XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "NVDA", "AAPL", "MSFT", "META", "TSLA"]
LOOKBACK_DAYS = 180


def _standardize(df: Any) -> Any:
    centered = df - df.mean()
    std = df.std(ddof=1).replace(0, 1)
    return centered / std


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _norm(a: list[float]) -> float:
    return math.sqrt(sum(x * x for x in a))


def _power_iteration(matrix: list[list[float]], iterations: int = 80) -> tuple[float, list[float]]:
    n = len(matrix)
    vector = [1.0 / math.sqrt(n)] * n
    for _ in range(iterations):
        nxt = [sum(matrix[i][j] * vector[j] for j in range(n)) for i in range(n)]
        scale = _norm(nxt)
        if scale == 0:
            break
        vector = [value / scale for value in nxt]
    mv = [sum(matrix[i][j] * vector[j] for j in range(n)) for i in range(n)]
    eigenvalue = _dot(vector, mv)
    return eigenvalue, vector


def pca_components(returns: Any, n_components: int = 3) -> list[dict[str, Any]]:
    z = _standardize(returns).dropna()
    corr = z.corr().fillna(0.0)
    matrix = corr.values.tolist()
    total_variance = max(1e-9, sum(matrix[i][i] for i in range(len(matrix))))
    components: list[dict[str, Any]] = []
    labels = list(corr.columns)
    working = [row[:] for row in matrix]
    for idx in range(min(n_components, len(labels))):
        eigenvalue, vector = _power_iteration(working)
        loadings = {label: round(weight, 4) for label, weight in zip(labels, vector)}
        sorted_loadings = sorted(loadings.items(), key=lambda item: abs(item[1]), reverse=True)
        components.append({
            "component": idx + 1,
            "eigenvalue": round(eigenvalue, 4),
            "explained_variance_pct": round(100 * eigenvalue / total_variance, 2),
            "top_loadings": [{"symbol": sym, "loading": val} for sym, val in sorted_loadings[:8]],
        })
        for i in range(len(working)):
            for j in range(len(working)):
                working[i][j] -= eigenvalue * vector[i] * vector[j]
    return components


def residual_scores(returns: Any, market_symbol: str = "SPY") -> list[dict[str, Any]]:
    import pandas as pd

    if market_symbol not in returns.columns:
        return []
    market = returns[market_symbol]
    rows = []
    for symbol in returns.columns:
        if symbol == market_symbol:
            continue
        series = returns[symbol]
        aligned = pd.concat([market, series], axis=1).dropna()
        if len(aligned) < 30:
            continue
        x = aligned.iloc[:, 0]
        y = aligned.iloc[:, 1]
        beta = float(((x - x.mean()) * (y - y.mean())).sum() / max(1e-9, ((x - x.mean()) ** 2).sum()))
        residual = y - beta * x
        latest_residual = float(residual.iloc[-1])
        sigma = float(residual.std(ddof=1) or 0.0)
        zscore = latest_residual / sigma if sigma else 0.0
        rows.append({
            "symbol": symbol,
            "beta_to_spy": round(beta, 3),
            "latest_residual_z": round(zscore, 3),
            "classification": "idiosyncratic_up" if zscore >= 1.5 else "idiosyncratic_down" if zscore <= -1.5 else "force_echo",
        })
    rows.sort(key=lambda row: abs(float(row["latest_residual_z"])), reverse=True)
    return rows


def fetch_returns(symbols: list[str], lookback_days: int) -> tuple[Any, str]:
    from scripts import market_data

    closes = market_data.fetch_close(symbols, lookback_days=lookback_days + 80)
    returns = closes.pct_change().dropna().tail(lookback_days)
    return returns, market_data.data_source()


def build_report(day: str | None = None, symbols: list[str] | None = None) -> dict[str, Any]:
    day = day or date.today().isoformat()
    symbols = symbols or UNIVERSE
    try:
        returns, source = fetch_returns(symbols, LOOKBACK_DAYS)
        components = pca_components(returns)
        residuals = residual_scores(returns)
        status = "ok"
        error = None
    except Exception as exc:
        source = "unavailable"
        components = []
        residuals = []
        status = "error"
        error = str(exc)[:180]
    first_var = components[0]["explained_variance_pct"] if components else None
    if first_var is None:
        force_regime = "unavailable"
    elif first_var >= 55:
        force_regime = "single_market_force_dominant"
    elif first_var >= 35:
        force_regime = "market_force_active"
    else:
        force_regime = "dispersed_idiosyncratic_tape"
    return {
        "date": day,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "provider": "pca_market_forces",
        "mode": "read_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "status": status,
        "error": error,
        "data_source": source,
        "lookback_days": LOOKBACK_DAYS,
        "symbols": symbols,
        "force_regime": force_regime,
        "components": components,
        "top_idiosyncratic": residuals[:10],
        "warnings": [
            "Context only. PCA force decomposition does not place orders.",
            "Use residuals to prioritize review, not to promote execution.",
        ],
    }


def append_log(report: dict[str, Any], path: Path = LOG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(report, separators=(",", ":"), default=str) + "\n")


def write_report(report: dict[str, Any], path: Path = REPORT_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return path


def print_report(report: dict[str, Any]) -> None:
    print("\nPCA Market Forces | read-only")
    print("=" * 72)
    print(f"status={report['status']} regime={report['force_regime']} source={report['data_source']}")
    for component in report["components"][:3]:
        top = ", ".join(f"{row['symbol']}:{row['loading']}" for row in component["top_loadings"][:4])
        print(f"PC{component['component']} var={component['explained_variance_pct']}% {top}")
    print("No orders placed.\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--print", action="store_true", dest="print_output")
    args = parser.parse_args()
    report = build_report(day=args.date)
    append_log(report, args.log_path)
    write_report(report, args.report_path)
    if args.print_output:
        print_report(report)
    else:
        print(f"PCA market forces logged to {args.log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
