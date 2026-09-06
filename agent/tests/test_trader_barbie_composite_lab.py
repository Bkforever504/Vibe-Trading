from pathlib import Path
import sys
import pandas as pd

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from research import trader_barbie_composite_lab as lab
from research import trader_barbie_timeframe_tournament as tournament

def test_signal_is_confirmation_after_sweep():
    times=pd.date_range("2026-01-02 14:30",periods=24,freq="15min",tz="UTC")
    bars=pd.DataFrame({"timestamp":times,"open":[100.0]*24,"high":[101.0]*24,"low":[99.0]*24,"close":[100.0]*24})
    bars.loc[20,["open","high","low","close"]]=[100,100.2,98.5,99.5]
    bars.loc[21,["open","high","low","close"]]=[99.5,101.3,99.0,101.0]
    result=lab.signals(bars)
    assert len(result)==1 and int(result.iloc[0].side)==1

def test_metrics_empty_fail_closed():
    assert lab.metrics([])["expectancy_r"] is None

def test_timeframe_family_is_frozen_and_resolution_safe():
    assert tournament.TIMEFRAMES == (5,10,15,30,60)
    assert tournament.COARSE_EXTENSION == (90,120,240)
