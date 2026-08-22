Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$env:PYTHONPATH = $repo
Set-Location $repo
python scripts\liquidity_sweep_scanner.py `
    --symbol SPY `
    --ledger "$repo\data\liquidity_sweep_ledger.jsonl" `
    --out "$repo\data\liquidity_sweep_context.json"
exit $LASTEXITCODE
