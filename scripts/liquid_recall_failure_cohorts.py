#!/usr/bin/env python3
"""Turn liquid-universe recall failures into a frozen research queue."""
from __future__ import annotations
import json
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
VIBE = Path.home() / ".vibe-trading"
RECALL = VIBE / "reports" / "liquid-universe-recall.json"
RADAR_LOG = ROOT / "data" / "intraday_opportunity_radar_log.jsonl"
OUT = VIBE / "reports" / "liquid-recall-failure-cohorts.json"

def read(path: Path, default: Any) -> Any:
    try: return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError): return default

def build() -> dict[str, Any]:
    recall = read(RECALL, {}); day = str(recall.get("date") or "")[:10]
    try: snapshots = [json.loads(x) for x in RADAR_LOG.read_text(encoding="utf-8-sig").splitlines() if x.strip()]
    except (OSError, json.JSONDecodeError): snapshots=[]
    snapshots=[x for x in snapshots if isinstance(x,dict) and str(x.get("date") or "")[:10]==day]
    failures=[x for x in recall.get("moves") or [] if isinstance(x,dict) and x.get("classification") in {"discovered_only","opposing_confirmation"}]
    rows=[]; blockers=Counter(); setups=Counter(); hours=Counter()
    for move in failures:
        symbol,direction,end=move.get("symbol"),move.get("direction"),str(move.get("end_at") or "")
        candidates=[c for s in snapshots if str(s.get("as_of_et") or "")<=end for c in s.get("ranked_candidates") or [] if isinstance(c,dict) and c.get("symbol")==symbol and c.get("direction")==direction]
        candidate=candidates[0] if candidates else {}; why=[str(x) for x in candidate.get("blockers") or ["no_matching_directional_candidate"]]
        blockers.update(why); setups[str(candidate.get("setup") or "unconfirmed")]+=1; hours[end[11:13] or "unknown"]+=1
        rows.append({"symbol":symbol,"direction":direction,"chart_return_pct":move.get("return_pct"),"classification":move.get("classification"),"setup_at_move_end":candidate.get("setup"),"score_at_move_end":candidate.get("score"),"blockers":why,"move_end_at":end})
    return {"schema_version":1,"date":day,"mode":"failure_cohort_research_only","execution_enabled":False,"can_submit_orders":False,"summary":{"failure_count":len(rows),"minimum_sample_before_challenger_test":30,"sample_status":"ready_to_preregister_not_ready_to_promote" if len(rows)>=30 else "collect_more_sessions","top_blockers":blockers.most_common(8),"setup_counts":setups,"hour_counts":hours},"failures":rows,"next_experiment":"Preregister one ablation against the largest blocker cohort; retain completed-bar confirmation and compare against baseline over multiple sessions.","warnings":["A failure cohort is not evidence that its blocker should be removed.","No ranking, alert, sizing, or execution authority."]}

if __name__ == "__main__":
    report=build(); OUT.parent.mkdir(parents=True,exist_ok=True); OUT.write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8"); print(f"Liquid recall cohorts: failures={report['summary']['failure_count']} status={report['summary']['sample_status']}")
