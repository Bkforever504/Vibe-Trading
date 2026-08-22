Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$env:PYTHONPATH = $repo
$env:ALPACA_PAPER = "true"
Set-Location $repo
python strategies\spy_0dte_pm_spread.py `
    --state "$repo\data\spy_0dte_pm_state.json" `
    --ledger "$repo\data\spy_0dte_pm_ledger.jsonl" `
    --out "$repo\data\spy_0dte_pm_decision.json"
exit $LASTEXITCODE
