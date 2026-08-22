Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$env:PYTHONPATH = $repo
$env:ALPACA_PAPER = "true"
Set-Location $repo
python strategies\vix_call_hedge.py `
    --state "$repo\data\vix_call_hedge_state.json" `
    --ledger "$repo\data\vix_call_hedge_ledger.jsonl" `
    --out "$repo\data\vix_call_hedge_decision.json"
exit $LASTEXITCODE
