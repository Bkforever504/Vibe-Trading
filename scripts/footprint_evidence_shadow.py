#!/usr/bin/env python3
"""Normalize footprint/volume-profile evidence for shadow evaluation only.

Native TradingView footprint rows and exchange-normalized rows are accepted;
geometric/intrabar estimates are explicitly labelled ``proxy``.  This module
never changes a rank, creates an alert, or assumes a fill.
"""
from __future__ import annotations

import argparse, json, math, os
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "data" / "footprint_evidence.jsonl"
DEFAULT_OUTPUT = Path.home() / ".vibe-trading" / "reports" / "footprint-evidence-shadow.json"

def _rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists(): return []
    out=[]
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        try:
            x=json.loads(line)
            if isinstance(x, dict): out.append(x)
        except json.JSONDecodeError: continue
    return out

def _num(x: Any) -> float | None:
    try:
        y=float(x); return y if math.isfinite(y) else None
    except (TypeError, ValueError): return None

def normalize(row: Mapping[str, Any]) -> dict[str, Any]:
    buy=_num(row.get("buy_volume", row.get("buy")))
    sell=_num(row.get("sell_volume", row.get("sell")))
    total=_num(row.get("total_volume", row.get("total")))
    if total is None and buy is not None and sell is not None: total=buy+sell
    delta=(buy-sell) if buy is not None and sell is not None else None
    delta_pct=(100.0*delta/total) if delta is not None and total and total>0 else None
    source=str(row.get("source") or row.get("engine") or "unknown").lower()
    quality="native" if source in {"native", "footprint", "opra", "mbo", "mbp10"} else "proxy" if source in {"geometric", "intrabar", "estimated", "proxy"} else "unknown"
    imbalances=row.get("imbalances", row.get("imbalance_count", 0))
    try: imbalances=int(imbalances)
    except (TypeError, ValueError): imbalances=0
    return {
        "timestamp": row.get("timestamp") or row.get("as_of") or row.get("as_of_et"),
        "symbol": str(row.get("symbol") or "").upper(),
        "source": source, "source_quality": quality,
        "buy_volume": buy, "sell_volume": sell, "total_volume": total,
        "delta": delta, "delta_pct": delta_pct,
        "poc": _num(row.get("poc") or row.get("dashboard_poc")),
        "vah": _num(row.get("vah")), "val": _num(row.get("val")),
        "imbalances": max(0, imbalances),
        "absorption": bool(row.get("absorption") or row.get("failed_auction")),
        "delta_divergence": bool(row.get("delta_divergence")),
        "rank_effect": "none",
        "execution_enabled": False, "can_submit_orders": False,
    }

def build_report(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    normalized=[normalize(r) for r in rows]
    native=sum(r["source_quality"]=="native" for r in normalized)
    proxy=sum(r["source_quality"]=="proxy" for r in normalized)
    return {
        "schema_version": 1, "provider": "footprint_evidence_shadow",
        "mode": "shadow_only", "execution_enabled": False, "can_submit_orders": False,
        "operational_health": "ok" if normalized else "unavailable",
        "coverage": {"rows_received": len(normalized), "native_rows": native, "proxy_rows": proxy},
        "preregistration": {"rank_effect": "none", "proxy_data_allowed_for": ["research", "confirmation_comparison"], "native_required_for_promotion": True},
        "rows": normalized,
        "warnings": ["Footprint is confirmation evidence only; it does not create or rank A+ setups.", "Geometric/intrabar values are estimates and are never treated as native order-flow truth.", "Promotion requires out-of-sample improvement against the existing stack."],
    }

def main() -> int:
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("--input",type=Path,default=DEFAULT_INPUT); p.add_argument("--output",type=Path,default=DEFAULT_OUTPUT); p.add_argument("--print",action="store_true",dest="do_print"); a=p.parse_args()
    report=build_report(_rows(a.input)); a.output.parent.mkdir(parents=True,exist_ok=True); tmp=a.output.with_suffix(a.output.suffix+f".{os.getpid()}.tmp"); tmp.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8"); os.replace(tmp,a.output)
    if a.do_print: print(json.dumps(report,indent=2,sort_keys=True))
    return 0
if __name__ == "__main__": raise SystemExit(main())
