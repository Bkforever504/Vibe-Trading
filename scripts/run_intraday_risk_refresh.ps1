$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir
$logPath = Join-Path $HOME ".vibe-trading\logs\intraday-risk-refresh-task.log"

Set-Location $projectRoot
$stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
"[$stamp] intraday_risk_refresh start" | Add-Content -Path $logPath
python scripts/intraday_risk_refresh.py *>&1 | Add-Content -Path $logPath
$code = $LASTEXITCODE
"[$stamp] intraday_risk_refresh exit=$code" | Add-Content -Path $logPath
exit $code
