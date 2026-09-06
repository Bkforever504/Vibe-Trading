#!/usr/bin/env python3
"""Fail-closed audit of headline strategy statistics and optional trade ledgers."""
from __future__ import annotations
import argparse,csv,json,math
from pathlib import Path
from typing import Any

def audit_claims(claims:list[dict[str,Any]], trade_rows:list[dict[str,Any]]|None=None)->dict[str,Any]:
    trades=trade_rows or []; required={"timestamp","entry","exit","side","size"}; ledger_complete=bool(trades) and all(required.issubset(r) for r in trades)
    findings=[]
    for c in claims:
        ret=float(c.get("return_pct",0) or 0); sharpe=float(c.get("sharpe",0) or 0); dd=float(c.get("max_drawdown_pct",0) or 0)
        flags=[]
        if ret>1000: flags.append("extreme_return_requires_compounding_and_leverage_reconstruction")
        if sharpe>3: flags.append("high_sharpe_requires_independent_holdout")
        if ret>10000 and abs(dd)<10: flags.append("return_drawdown_combination_requires_fill_and_equity_curve_audit")
        if not ledger_complete: flags.append("underlying_trade_ledger_unavailable")
        findings.append({"strategy":c.get("strategy") or c.get("file"),"status":"unverified" if flags else "reviewable","flags":flags})
    return {"schema_version":1,"mode":"research_audit","execution_enabled":False,"claim_count":len(claims),"trade_ledger_complete":ledger_complete,"findings":findings,"verdict":"insufficient_evidence" if not ledger_complete else "requires_recalculation","required_next":["causal_timestamp_check","fee_slippage_replay","chronological_holdout","fixed_notional_and_noncompounded_comparison","same_bar_stop_target_conservative_resolution"]}

def main()->int:
    p=argparse.ArgumentParser(); p.add_argument("--claims",type=Path,required=True); p.add_argument("--trades",type=Path); p.add_argument("--output",type=Path,required=True); a=p.parse_args(); claims=json.loads(a.claims.read_text(encoding="utf-8")); trades=None
    if a.trades: trades=list(csv.DictReader(a.trades.open(encoding="utf-8-sig"))) if a.trades.suffix.lower()==".csv" else json.loads(a.trades.read_text(encoding="utf-8"))
    a.output.write_text(json.dumps(audit_claims(claims,trades),indent=2)+"\n",encoding="utf-8"); return 0
if __name__=="__main__": raise SystemExit(main())
