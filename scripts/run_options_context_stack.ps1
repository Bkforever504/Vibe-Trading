Set-StrictMode -Version Latest
$ErrorActionPreference = "Continue"
$repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$env:PYTHONPATH = $repo
Set-Location $repo

$symbols = "SPY,QQQ,IWM,NVDA,AAPL,TSLA,PLTR"

Write-Host "Refreshing GARCH volatility risk..."
python scripts\garch_volatility_risk.py --symbols $symbols --print
if ($LASTEXITCODE -ne 0) {
  Write-Warning "GARCH refresh failed; options bot will use its configured missing-report behavior."
}

Write-Host "Refreshing options liquidation heatmap..."
python scripts\options_liquidation_heatmap.py SPY QQQ IWM NVDA AAPL TSLA PLTR
if ($LASTEXITCODE -ne 0) {
  Write-Warning "Options liquidation heatmap refresh failed; adaptive playbook will use last available context."
}

Write-Host "Refreshing adaptive options shadow playbook..."
python scripts\adaptive_options_shadow_playbook.py --symbols $symbols
if ($LASTEXITCODE -ne 0) {
  Write-Warning "Adaptive options playbook refresh failed; entry gate remains strict."
}

exit 0
