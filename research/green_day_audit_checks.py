#!/usr/bin/env python3
"""One-shot adversarial checks for green_day_htf_ltf_lab (read-only)."""
from __future__ import annotations

import json
import sys
from datetime import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.green_day_htf_ltf_lab import (  # noqa: E402
    MINUTE_PATH, _complete_session, build_htf_table, load_daily, asof_states,
)

out: dict = {}

# 1. Minute parquet timezone and coverage sanity.
minute = pd.read_parquet(MINUTE_PATH)
idx = pd.to_datetime(minute.index)
out["minute_index_tz"] = str(idx.tz)
out["minute_range"] = [str(idx.min()), str(idx.max())]
sample_day = idx[len(idx) // 2].date()
day_rows = minute[idx.date == sample_day]
times = sorted({t.strftime("%H:%M") for t in pd.to_datetime(day_rows.index).time})
out["sample_day"] = str(sample_day)
out["sample_first_last_bar"] = [times[0], times[-1]] if times else None

# 2. Daily cache freshness for SPY.
spy_daily = load_daily("SPY")
out["spy_daily_range"] = [str(spy_daily.index.min().date()), str(spy_daily.index.max().date())]

# 3. HTF as-of: prove Friday session never sees its own week and mid-month
# session never sees the current month.
htf = build_htf_table(spy_daily)
fri = asof_states(htf, "2026-07-17")          # a Friday
out["friday_weekly_label_source_max"] = str(htf["weekly"].index[htf["weekly"].index < pd.Timestamp("2026-07-17")].max().date())
mid = asof_states(htf, "2026-07-10")
out["midmonth_monthly_label_source_max"] = str(htf["monthly"].index[htf["monthly"].index < pd.Timestamp("2026-07-10")].max().date())
out["friday_states"] = fri
out["midmonth_states"] = mid

# 4. Selection bias: included (complete) vs excluded sessions.
m = minute.copy()
if m.index.tz is None:
    m.index = pd.to_datetime(m.index).tz_localize("America/New_York")
else:
    m.index = pd.to_datetime(m.index).tz_convert("America/New_York")
m.columns = [c.lower() for c in m.columns]
included, excluded = [], []
for day, raw in m.groupby(m.index.date):
    rth = raw.between_time("09:30", "15:59").sort_index()
    if rth.empty:
        continue
    o = float(rth["open"].iloc[0])
    stats = {
        "range_pct": (float(rth["high"].max()) - float(rth["low"].min())) / o * 100,
        "volume": float(rth["volume"].sum()),
        "bars": len(rth),
        "abs_close_ret_pct": abs(float(rth["close"].iloc[-1]) / o - 1) * 100,
    }
    (included if _complete_session(rth) else excluded).append(stats)


def agg(rows):
    if not rows:
        return None
    return {
        "sessions": len(rows),
        "mean_range_pct": round(float(np.mean([r["range_pct"] for r in rows])), 3),
        "mean_abs_close_ret_pct": round(float(np.mean([r["abs_close_ret_pct"] for r in rows])), 3),
        "median_volume": round(float(np.median([r["volume"] for r in rows])), 0),
        "mean_bars": round(float(np.mean([r["bars"] for r in rows])), 1),
    }


out["included_sessions"] = agg(included)
out["excluded_sessions"] = agg(excluded)

print(json.dumps(out, indent=2))
