Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$env:PYTHONPATH = $repo
Set-Location $repo
python scripts\flip_execution_challenger_report.py --print
python research\causal_trade_replay_lab.py
python scripts\multitimeframe_pattern_memory.py
python research\paired_direction_decision_lab.py
python scripts\paired_direction_collection_health.py
