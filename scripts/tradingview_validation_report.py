#!/usr/bin/env python3
"""Read-only TradingView Desktop validation report.

This uses the local `tv` CLI from tradingview-mcp. It is for chart-side
validation only; delayed TradingView data must not be treated as an execution
feed.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

RUNTIME_DIR = Path.home() / ".vibe-trading"
REPORT_DIR = RUNTIME_DIR / "reports"


def _tv_command() -> str:
    found = shutil.which("tv") or shutil.which("tv.cmd")
    if found:
        return found
    appdata = os.getenv("APPDATA")
    if appdata:
        candidate = Path(appdata) / "npm" / "tv.cmd"
        if candidate.exists():
            return str(candidate)
    local = Path(__file__).resolve().parents[1] / "tools" / "tradingview-mcp" / "src" / "cli" / "index.js"
    if local.exists():
        return str(local)
    return "tv"


def _run_tv_json(args: list[str]) -> dict[str, Any]:
    command = _tv_command()
    call = ["node", command, *args] if command.endswith("index.js") else [command, *args]
    try:
        proc = subprocess.run(
            call,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except FileNotFoundError:
        return {"success": False, "error": "tv CLI not found. Run npm link in tools/tradingview-mcp."}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"tv {' '.join(args)} timed out"}

    text = (proc.stdout or proc.stderr or "").strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {"success": False, "error": text or f"tv {' '.join(args)} exited {proc.returncode}"}
    if proc.returncode != 0 and data.get("success") is not False:
        data["success"] = False
        data["exit_code"] = proc.returncode
    return data


def build_report(*, status: dict[str, Any], quote: dict[str, Any], ohlcv: dict[str, Any]) -> dict[str, Any]:
    symbol = str(status.get("chart_symbol") or quote.get("symbol") or "")
    connected = bool(status.get("success") and status.get("cdp_connected"))
    is_delayed = "_DL:" in symbol or symbol.endswith("_DL")

    open_ = _safe_float(ohlcv.get("open"))
    close = _safe_float(ohlcv.get("close") if ohlcv.get("close") is not None else quote.get("close"))
    bias = "unknown"
    if open_ is not None and close is not None:
        if close < open_:
            bias = "bearish"
        elif close > open_:
            bias = "bullish"
        else:
            bias = "flat"

    warnings: list[str] = []
    if not connected:
        warnings.append("TradingView bridge is not connected")
    if is_delayed:
        warnings.append("TradingView symbol is delayed; use for validation only, not execution")
    if str(quote.get("type") or "") == "futures" and not is_delayed:
        warnings.append("Confirm CME real-time entitlement before treating this as live futures data")

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "provider": "tradingview_desktop_mcp",
        "connected": connected,
        "symbol": symbol,
        "timeframe": str(status.get("chart_resolution") or ""),
        "description": quote.get("description"),
        "instrument_type": quote.get("type"),
        "is_delayed": is_delayed,
        "quote": quote,
        "ohlcv_summary": ohlcv,
        "bias": bias,
        "warnings": warnings,
    }


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def write_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build TradingView Desktop validation report")
    parser.add_argument("--out", type=Path, default=REPORT_DIR / "tradingview-validation.json")
    parser.add_argument("--print", action="store_true", help="Print report JSON to stdout")
    args = parser.parse_args()

    status = _run_tv_json(["status"])
    quote = _run_tv_json(["quote"])
    ohlcv = _run_tv_json(["ohlcv", "--summary"])
    report = build_report(status=status, quote=quote, ohlcv=ohlcv)
    write_report(report, args.out)
    if args.print:
        print(json.dumps(report, indent=2))
    else:
        print(f"TradingView validation report written to: {args.out}")
    return 0 if report["connected"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
