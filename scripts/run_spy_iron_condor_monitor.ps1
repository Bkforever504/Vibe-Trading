Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$stateFile = "$repo\data\spy_iron_condor_state.json"
if (-not (Test-Path $stateFile)) { Write-Host "No open iron condor position"; exit 0 }
$env:PYTHONPATH = $repo
Set-Location $repo
python strategies\spy_iron_condor.py --check `
    --state "$stateFile" `
    --ledger "$repo\data\spy_iron_condor_ledger.jsonl" `
    --out "$repo\data\spy_iron_condor_monitor_decision.json"
exit $LASTEXITCODE
