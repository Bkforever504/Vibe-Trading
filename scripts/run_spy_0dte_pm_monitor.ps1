Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$stateFile = "$repo\data\spy_0dte_pm_state.json"
if (-not (Test-Path $stateFile)) { Write-Host "No open 0DTE PM position"; exit 0 }
$env:PYTHONPATH = $repo
Set-Location $repo
python strategies\spy_0dte_pm_spread.py --check `
    --state "$stateFile" `
    --ledger "$repo\data\spy_0dte_pm_ledger.jsonl" `
    --out "$repo\data\spy_0dte_pm_monitor_decision.json"
exit $LASTEXITCODE
