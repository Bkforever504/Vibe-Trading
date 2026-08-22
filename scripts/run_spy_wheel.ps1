Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$env:PYTHONPATH = $repo
$env:ALPACA_PAPER = "true"
Set-Location $repo
python strategies\spy_wheel.py `
    --state "$repo\data\spy_wheel_state.json" `
    --ledger "$repo\data\spy_wheel_ledger.jsonl" `
    --out "$repo\data\spy_wheel_decision.json"
exit $LASTEXITCODE
