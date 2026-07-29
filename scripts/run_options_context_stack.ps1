Set-StrictMode -Version Latest
$ErrorActionPreference = "Continue"
$repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$env:PYTHONPATH = $repo
Set-Location $repo

$symbols = "SPY,QQQ,IWM,NVDA,AAPL,TSLA,PLTR"
$failedSteps = @()

Write-Host "Refreshing GARCH volatility risk..."
python scripts\garch_volatility_risk.py --symbols $symbols --print
if ($LASTEXITCODE -ne 0) {
  $failedSteps += "garch_volatility_risk"
  Write-Warning "GARCH refresh failed."
}

Write-Host "Refreshing options liquidation heatmap..."
python scripts\options_liquidation_heatmap.py SPY QQQ IWM NVDA AAPL TSLA PLTR
if ($LASTEXITCODE -ne 0) {
  $failedSteps += "options_liquidation_heatmap"
  Write-Warning "Options liquidation heatmap refresh failed."
}

Write-Host "Refreshing adaptive options shadow playbook..."
python scripts\adaptive_options_shadow_playbook.py --symbols $symbols
if ($LASTEXITCODE -ne 0) {
  $failedSteps += "adaptive_options_shadow_playbook"
  Write-Warning "Adaptive options playbook refresh failed."
}

Write-Host "Refreshing options quant risk budget..."
python scripts\options_quant_risk_budget.py --print
if ($LASTEXITCODE -ne 0) {
  $failedSteps += "options_quant_risk_budget"
  Write-Warning "Options quant risk budget refresh failed."
}

if ($failedSteps.Count -gt 0) {
  Write-Warning "Options context refresh failed: $($failedSteps -join ', '). Entry must not run on stale context."
  exit 1
}

exit 0
