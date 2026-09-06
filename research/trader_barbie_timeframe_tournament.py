#!/usr/bin/env python3
"""Walk-forward, multiple-testing-controlled timeframe tournament."""
from __future__ import annotations
import argparse,json,math,sys
from datetime import timedelta
from pathlib import Path
from statistics import NormalDist
from typing import Any
TIMEFRAMES=(5,10,15,30,60)
COARSE_EXTENSION=(90,120,240)
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from research import trader_barbie_composite_lab as base
DEFAULT_OUT=ROOT/"data"/"trader_barbie_timeframe_tournament.json"

def inference(rows:list[dict[str,Any]])->dict[str,Any]:
    m=base.metrics(rows); vals=[float(r["net_r"]) for r in rows]
    if len(vals)<2: return {**m,"one_sided_p_value":None}
    avg=sum(vals)/len(vals); var=sum((v-avg)**2 for v in vals)/(len(vals)-1); se=math.sqrt(var/len(vals)) if var>0 else 0
    z=avg/se if se else 0; return {**m,"one_sided_p_value":1-NormalDist().cdf(z)}

def evaluate(path:Path,timeframe:int)->dict[str,Any]:
    bars=base.load_bars(path,timeframe); n=len(bars); boundaries=(int(n*.40),int(n*.60),int(n*.80),n); folds=[]
    for fold,(train_end,test_end) in enumerate(zip(boundaries[:-1],boundaries[1:]),1):
        test=bars.iloc[max(0,train_end-21):test_end].copy(); rows=base.simulate(test,base.signals(test)); folds.append({"fold":fold,"train_rows":train_end,"test_rows":test_end-train_end,"metrics":inference(rows)})
    all_rows=[]
    for f,(train_end,test_end) in zip(folds,zip(boundaries[:-1],boundaries[1:])):
        test=bars.iloc[max(0,train_end-21):test_end].copy(); all_rows.extend(base.simulate(test,base.signals(test)))
    total=inference(all_rows); positive=sum((f["metrics"]["expectancy_r"] or 0)>0 for f in folds); alpha=.05/len(TIMEFRAMES)
    gates={"min_50_trades":total["trades"]>=50,"positive_expectancy":(total["expectancy_r"] or 0)>0,"profit_factor_above_one":(total["profit_factor"] or 0)>1,"positive_two_of_three_folds":positive>=2,"bonferroni_significant":total["one_sided_p_value"] is not None and total["one_sided_p_value"]<alpha}
    return {"timeframe_minutes":timeframe,"folds":folds,"aggregate":total,"gates":gates,"forward_shadow_candidate":all(gates.values())}

def context_sweeps(path:Path)->list[dict[str,Any]]:
    bars=base.load_bars(path,15); x=bars.copy()
    x["bsl"]=x.high.shift(1).rolling(20,min_periods=20).max(); x["ssl"]=x.low.shift(1).rolling(20,min_periods=20).min(); x["ce"]=(x.bsl+x.ssl)/2
    bull=(x.low<x.ssl)&(x.close>x.ssl)&(x.close<=x.ce); bear=(x.high>x.bsl)&(x.close<x.bsl)&(x.close>=x.ce)
    out=[]
    for _,r in x[bull|bear].iterrows(): out.append({"timestamp":r.timestamp,"side":1 if bool(bull.loc[r.name]) else -1,"stop":float(r.low if bool(bull.loc[r.name]) else r.high)})
    return out

def decoupled_rows(path:Path,timeframe:int)->list[dict[str,Any]]:
    bars=base.load_bars(path,timeframe); sweeps=context_sweeps(path); rows=[]
    for s in sweeps:
        candidates=bars[(bars.timestamp>s["timestamp"])&(bars.timestamp<=s["timestamp"]+timedelta(minutes=max(60,timeframe*2)))]
        confirm_i=None
        for i in candidates.index:
            if i<=0: continue
            cur,prev=bars.loc[i],bars.loc[i-1]
            ok=(cur.high>prev.high and cur.low>=prev.low) if s["side"]>0 else (cur.low<prev.low and cur.high<=prev.high)
            if ok: confirm_i=i; break
        if confirm_i is None or confirm_i+1>=len(bars): continue
        entry=float(bars.loc[confirm_i+1,"open"]); risk=s["side"]*(entry-s["stop"])
        if risk<=0: continue
        target=entry+s["side"]*2*risk; exit_price=float(bars.iloc[min(confirm_i+13,len(bars)-1)].close); reason="time"
        for _,b in bars.iloc[confirm_i+1:min(confirm_i+14,len(bars))].iterrows():
            stop_hit=b.low<=s["stop"] if s["side"]>0 else b.high>=s["stop"]; target_hit=b.high>=target if s["side"]>0 else b.low<=target
            if stop_hit: exit_price=s["stop"]; reason="stop"; break
            if target_hit: exit_price=target; reason="target"; break
        gross=s["side"]*(exit_price-entry)/risk; rows.append({"timestamp":bars.loc[confirm_i,"timestamp"].isoformat(),"net_r":gross-(entry*.0002/risk),"gross_r":gross,"reason":reason})
    return rows

def evaluate_decoupled(path:Path,timeframe:int)->dict[str,Any]:
    rows=decoupled_rows(path,timeframe); stamps=sorted(r["timestamp"] for r in rows)
    folds=[]
    for fold,(lo,hi) in enumerate(((.4,.6),(.6,.8),(.8,1.0)),1):
        a=int(len(stamps)*lo); b=int(len(stamps)*hi); selected=rows[a:b]; folds.append({"fold":fold,"metrics":inference(selected)})
    total=inference([r for f in range(3) for r in rows[int(len(rows)*(.4+.2*f)):int(len(rows)*(.6+.2*f))]])
    positive=sum((f["metrics"]["expectancy_r"] or 0)>0 for f in folds); alpha=.05/len(TIMEFRAMES)
    gates={"min_50_trades":total["trades"]>=50,"positive_expectancy":(total["expectancy_r"] or 0)>0,"profit_factor_above_one":(total["profit_factor"] or 0)>1,"positive_two_of_three_folds":positive>=2,"bonferroni_significant":total["one_sided_p_value"] is not None and total["one_sided_p_value"]<alpha}
    return {"entry_timeframe_minutes":timeframe,"context_timeframe_minutes":15,"folds":folds,"aggregate":total,"gates":gates,"forward_shadow_candidate":all(gates.values())}

def run(paths:list[Path])->dict[str,Any]:
    markets=[]
    for path in paths: markets.append({"source":str(path),"timeframes":[evaluate(path,t) for t in TIMEFRAMES],"fixed_15m_context_entry_timeframes":[evaluate_decoupled(path,t) for t in TIMEFRAMES],"exploratory_coarse_extension":[{**evaluate_decoupled(path,t),"selection_contaminated":True,"promotion_eligible":False} for t in COARSE_EXTENSION]})
    return {"schema_version":1,"mode":"shadow_research_only","execution_enabled":False,"rank_effect":"none","preregistration":"TRADER_BARBIE_TIMEFRAME_TOURNAMENT_PREREGISTRATION_2026-08-30.md","candidate_timeframes":list(TIMEFRAMES),"coarse_extension_timeframes":list(COARSE_EXTENSION),"bonferroni_alpha":.05/len(TIMEFRAMES),"markets":markets}

def main()->int:
    p=argparse.ArgumentParser(); p.add_argument("--input",type=Path,action="append",required=True); p.add_argument("--output",type=Path,default=DEFAULT_OUT); p.add_argument("--print",action="store_true"); a=p.parse_args(); report=run(a.input); a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    if a.print:
        for m in report["markets"]:
            print(m["source"]); [print(t["timeframe_minutes"],t["aggregate"],t["forward_shadow_candidate"]) for t in m["timeframes"]]
            print("fixed 15m context"); [print(t["entry_timeframe_minutes"],t["aggregate"],t["forward_shadow_candidate"]) for t in m["fixed_15m_context_entry_timeframes"]]
            print("coarse extension (selection-contaminated)"); [print(t["entry_timeframe_minutes"],t["aggregate"],t["forward_shadow_candidate"]) for t in m["exploratory_coarse_extension"]]
    return 0
if __name__=="__main__": raise SystemExit(main())
