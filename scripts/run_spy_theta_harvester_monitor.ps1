Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$env:PYTHONPATH = $repo
$env:ALPACA_PAPER = "true"
$env:THETA_LIVE_EXECUTION = ""
Set-Location $repo
python strategies\spy_theta_harvester.py `
    --check `
    --state "$repo\data\theta_harvester_state.json" `
    --out "$repo\data\theta_harvester_monitor_decision.json" `
    --ledger "$repo\data\theta_harvester_ledger.jsonl"
exit $LASTEXITCODE
