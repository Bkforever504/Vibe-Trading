Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$env:PYTHONPATH = $repo
$env:ALPACA_PAPER = "true"
Set-Location $repo
python strategies\spy_weekend_vol.py `
    --state "$repo\data\spy_weekend_vol_state.json" `
    --ledger "$repo\data\spy_weekend_vol_ledger.jsonl" `
    --out "$repo\data\spy_weekend_vol_decision.json"
exit $LASTEXITCODE
