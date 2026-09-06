#!/usr/bin/env python3
"""Preregistered STRAT/SMC/ICT composite backtest; shadow research only."""
from __future__ import annotations
import argparse, json, math
from pathlib import Path
from typing import Any
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
DEFAULT_OUT=ROOT/"data"/"trader_barbie_composite_results.json"

def load_bars(path: Path, timeframe_minutes: int = 15) -> pd.DataFrame:
    df=pd.read_parquet(path) if path.suffix.lower()==".parquet" else pd.read_csv(path)
    cols={c.lower():c for c in df.columns}
    t=next((cols[k] for k in ("timestamp","datetime","date","time") if k in cols),None)
    if t is None and isinstance(df.index, pd.DatetimeIndex):
        out=pd.DataFrame({"timestamp":pd.to_datetime(df.index,utc=True).to_numpy()})
    elif t is not None:
        out=pd.DataFrame({"timestamp":pd.to_datetime(df[t],utc=True)})
    else:
        raise ValueError("timestamp column or DatetimeIndex required")
    for k in ("open","high","low","close"):
        if k not in cols: raise ValueError(f"{k} column required")
        out[k]=pd.to_numeric(df[cols[k]],errors="coerce").to_numpy()
    if timeframe_minutes < 5 or timeframe_minutes % 5:
        raise ValueError("timeframe must be a multiple of the 5-minute source resolution")
    return out.dropna().sort_values("timestamp").drop_duplicates("timestamp").set_index("timestamp").resample(f"{timeframe_minutes}min").agg({"open":"first","high":"max","low":"min","close":"last"}).dropna().reset_index()

def signals(bars: pd.DataFrame) -> pd.DataFrame:
    x=bars.copy(); prev=x.shift(1)
    x["prior_bsl"]=x["high"].shift(1).rolling(20,min_periods=20).max()
    x["prior_ssl"]=x["low"].shift(1).rolling(20,min_periods=20).min()
    rh=x["high"].shift(1).rolling(20,min_periods=20).max(); rl=x["low"].shift(1).rolling(20,min_periods=20).min(); x["ce"]=(rh+rl)/2
    two_up=(x.high>prev.high)&(x.low>=prev.low); two_down=(x.low<prev.low)&(x.high<=prev.high)
    bull_sweep=(x.low<x.prior_ssl)&(x.close>x.prior_ssl)&(x.close<=x.ce)
    bear_sweep=(x.high>x.prior_bsl)&(x.close<x.prior_bsl)&(x.close>=x.ce)
    bull=bull_sweep.shift(1,fill_value=False)&two_up
    bear=bear_sweep.shift(1,fill_value=False)&two_down
    x["side"]=0; x.loc[bull,"side"]=1; x.loc[bear,"side"]=-1
    return x[x.side!=0].copy()

def simulate(bars: pd.DataFrame, sigs: pd.DataFrame, cost_bps: float=2.0) -> list[dict[str,Any]]:
    by_ts={t:i for i,t in enumerate(bars.timestamp)}; out=[]
    for _,s in sigs.iterrows():
        i=by_ts.get(s.timestamp); side=int(s.side)
        if i is None or i+1>=len(bars): continue
        entry=float(bars.iloc[i+1].open); sweep=bars.iloc[i-1]; stop=float(sweep.low if side>0 else sweep.high); risk=side*(entry-stop)
        if risk<=0: continue
        target=entry+side*2*risk; exit_price=float(bars.iloc[min(i+13,len(bars)-1)].close); reason="time"
        for _,b in bars.iloc[i+1:min(i+14,len(bars))].iterrows():
            stop_hit=b.low<=stop if side>0 else b.high>=stop; target_hit=b.high>=target if side>0 else b.low<=target
            if stop_hit: exit_price=stop; reason="stop"; break
            if target_hit: exit_price=target; reason="target"; break
        gross_r=side*(exit_price-entry)/risk; cost_r=(entry*cost_bps/10000)/risk
        out.append({"timestamp":s.timestamp.isoformat(),"side":side,"entry":entry,"stop":stop,"target":target,"gross_r":gross_r,"net_r":gross_r-cost_r,"reason":reason})
    return out

def metrics(rows:list[dict[str,Any]])->dict[str,Any]:
    vals=[r["net_r"] for r in rows]; wins=[v for v in vals if v>0]; losses=[v for v in vals if v<=0]
    return {"trades":len(vals),"expectancy_r":sum(vals)/len(vals) if vals else None,"win_rate":len(wins)/len(vals) if vals else None,"profit_factor":sum(wins)/abs(sum(losses)) if losses and sum(losses)!=0 else None,"total_r":sum(vals)}

def run(path:Path, timeframe_minutes:int=15)->dict[str,Any]:
    bars=load_bars(path,timeframe_minutes); cut=int(len(bars)*.7); dev=bars.iloc[:cut].copy(); hold=bars.iloc[max(0,cut-21):].copy()
    dev_rows=simulate(dev,signals(dev)); hold_rows=simulate(hold,signals(hold))
    return {"schema_version":1,"mode":"shadow_research_only","execution_enabled":False,"rank_effect":"none","source":str(path),"timeframe_minutes":timeframe_minutes,"rules":"TRADER_BARBIE_COMPOSITE_PREREGISTRATION_2026-08-30.md","development":metrics(dev_rows),"holdout":metrics(hold_rows),"promotion_eligible":False,"promotion_blockers":["requires_50_signals_10_dates_15_holdout","requires_comparison_to_baseline_recall_and_regret"],"trades":{"development":dev_rows,"holdout":hold_rows}}

def main()->int:
    p=argparse.ArgumentParser(); p.add_argument("--input",type=Path,required=True); p.add_argument("--timeframe-minutes",type=int,default=15); p.add_argument("--output",type=Path,default=DEFAULT_OUT); p.add_argument("--print",action="store_true"); a=p.parse_args(); report=run(a.input,a.timeframe_minutes); a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8"); print(json.dumps(report["holdout"],indent=2)) if a.print else None; return 0
if __name__=="__main__": raise SystemExit(main())
