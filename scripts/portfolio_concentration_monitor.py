"""Read-only portfolio concentration monitor for Alpaca positions.

Borrowed from the go-trader architecture idea: central risk should understand
portfolio direction/concentration, not just duplicate symbols.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

VIBE_HOME = Path.home() / ".vibe-trading"
LOG_PATH = ROOT / "data" / "portfolio_concentration_log.jsonl"
REPORT_PATH = VIBE_HOME / "reports" / "portfolio-concentration.json"

BETA_MAP = {
    "SPY": 1.0,
    "QQQ": 1.2,
    "IWM": 1.15,
    "TSLA": 1.8,
    "NVDA": 1.7,
    "AAPL": 1.1,
    "PLTR": 1.6,
}


def _load_env() -> None:
    env_path = ROOT / "agent" / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def _underlying(symbol: str) -> str:
    for root in sorted(BETA_MAP, key=len, reverse=True):
        if symbol.upper().startswith(root):
            return root
    return "".join(ch for ch in symbol.upper() if ch.isalpha())[:5] or symbol.upper()


def _option_direction(symbol: str, qty: float) -> str:
    # OCC-style symbols contain C/P after the YYMMDD date: SPY260630C00747000
    upper = symbol.upper()
    right = None
    for idx, ch in enumerate(upper):
        if ch.isdigit() and idx + 7 < len(upper):
            maybe = upper[idx + 6]
            if maybe in {"C", "P"}:
                right = maybe
                break
    if right == "C":
        return "bullish" if qty > 0 else "bearish"
    if right == "P":
        return "bearish" if qty > 0 else "bullish"
    return "long" if qty > 0 else "short"


def fetch_alpaca_snapshot() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    _load_env()
    try:
        from alpaca.trading.client import TradingClient
    except ImportError as exc:
        raise ImportError("alpaca-py required for live portfolio concentration") from exc
    client = TradingClient(os.environ.get("ALPACA_API_KEY"), os.environ.get("ALPACA_SECRET_KEY"), paper=True)
    account = client.get_account()
    positions = []
    for pos in client.get_all_positions():
        qty = float(pos.qty)
        symbol = str(pos.symbol)
        positions.append({
            "symbol": symbol,
            "underlying": _underlying(symbol),
            "qty": qty,
            "market_value": float(pos.market_value),
            "cost_basis": float(pos.cost_basis),
            "unrealized_pl": float(pos.unrealized_pl),
            "unrealized_plpc": float(pos.unrealized_plpc),
            "direction": _option_direction(symbol, qty),
            "asset_class": str(pos.asset_class),
        })
    account_row = {
        "equity": float(account.equity),
        "last_equity": float(account.last_equity),
        "day_change": round(float(account.equity) - float(account.last_equity), 2),
        "buying_power": float(account.buying_power),
    }
    return account_row, positions


def analyze_concentration(account: dict[str, Any], positions: list[dict[str, Any]]) -> dict[str, Any]:
    equity = float(account.get("equity") or 0.0)
    by_underlying: dict[str, dict[str, Any]] = {}
    directional_beta = 0.0
    gross_market_value = 0.0
    for pos in positions:
        underlying = str(pos["underlying"])
        notional = abs(float(pos.get("market_value") or 0.0))
        gross_market_value += notional
        direction = str(pos.get("direction"))
        signed = 1.0 if direction == "bullish" else -1.0 if direction == "bearish" else 0.0
        beta = BETA_MAP.get(underlying, 1.0)
        directional_beta += signed * notional * beta
        row = by_underlying.setdefault(underlying, {
            "underlying": underlying,
            "gross_market_value": 0.0,
            "net_directional_beta_dollars": 0.0,
            "position_count": 0,
            "unrealized_pl": 0.0,
            "directions": {},
        })
        row["gross_market_value"] += notional
        row["net_directional_beta_dollars"] += signed * notional * beta
        row["position_count"] += 1
        row["unrealized_pl"] += float(pos.get("unrealized_pl") or 0.0)
        row["directions"][direction] = row["directions"].get(direction, 0) + 1
    underlying_rows = sorted(by_underlying.values(), key=lambda row: abs(row["net_directional_beta_dollars"]), reverse=True)
    for row in underlying_rows:
        row["gross_market_value"] = round(row["gross_market_value"], 2)
        row["net_directional_beta_dollars"] = round(row["net_directional_beta_dollars"], 2)
        row["unrealized_pl"] = round(row["unrealized_pl"], 2)
        row["pct_equity_gross"] = round(row["gross_market_value"] / equity * 100.0, 3) if equity else 0.0
    directional_beta_pct = round(directional_beta / equity * 100.0, 3) if equity else 0.0
    gross_pct = round(gross_market_value / equity * 100.0, 3) if equity else 0.0
    warnings = []
    if abs(directional_beta_pct) >= 3:
        warnings.append("directional_beta_above_3pct_equity")
    if gross_pct >= 5:
        warnings.append("gross_option_value_above_5pct_equity")
    if len([row for row in underlying_rows if row["gross_market_value"] > 0]) >= 4:
        warnings.append("many_underlyings_open")
    risk_level = "high" if len(warnings) >= 2 else "elevated" if warnings else "normal"
    return {
        "equity": equity,
        "position_count": len(positions),
        "gross_market_value": round(gross_market_value, 2),
        "gross_pct_equity": gross_pct,
        "net_directional_beta_dollars": round(directional_beta, 2),
        "net_directional_beta_pct_equity": directional_beta_pct,
        "risk_level": risk_level,
        "warnings": warnings,
        "by_underlying": underlying_rows,
        "positions": positions,
    }


def build_report() -> dict[str, Any]:
    account, positions = fetch_alpaca_snapshot()
    concentration = analyze_concentration(account, positions)
    return {
        "date": datetime.now(timezone.utc).date().isoformat(),
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "provider": "portfolio_concentration_monitor",
        "mode": "read_only",
        "execution_enabled": False,
        "account": account,
        "concentration": concentration,
        "warnings": [
            "Read-only concentration report. No orders are placed.",
            "Thresholds are advisory until 30-day outcome data proves usefulness.",
        ],
    }


def append_log(report: dict[str, Any], log_path: Path = LOG_PATH) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(report, separators=(",", ":")) + "\n")


def write_report(report: dict[str, Any], report_path: Path = REPORT_PATH) -> Path:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report_path


def print_report(report: dict[str, Any]) -> None:
    conc = report["concentration"]
    print("\nPortfolio Concentration | read-only")
    print("=" * 72)
    print(
        f"risk={conc['risk_level']} positions={conc['position_count']} "
        f"gross=${conc['gross_market_value']} ({conc['gross_pct_equity']}%) "
        f"beta=${conc['net_directional_beta_dollars']} ({conc['net_directional_beta_pct_equity']}%)"
    )
    for row in conc["by_underlying"][:8]:
        print(
            f"{row['underlying']:<6} gross=${row['gross_market_value']:<8} "
            f"beta=${row['net_directional_beta_dollars']:<8} pnl=${row['unrealized_pl']:<8} dirs={row['directions']}"
        )
    print("No orders placed.\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Monitor current portfolio concentration.")
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--print", action="store_true", dest="print_output")
    args = parser.parse_args()
    report = build_report()
    append_log(report, args.log_path)
    write_report(report, args.report_path)
    if args.print_output:
        print_report(report)
    else:
        print(f"Portfolio concentration logged to {args.log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
