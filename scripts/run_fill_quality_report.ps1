Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
if ((Get-Date).DayOfWeek -in @('Saturday', 'Sunday')) { exit 0 }
Set-Location "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$logDir = Join-Path $HOME ".vibe-trading\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
& python scripts\fill_quality_report.py 2>&1 | Tee-Object -FilePath (Join-Path $logDir "fill-quality-report.log") -Append
if ($LASTEXITCODE -ne 0) { throw "Fill quality report exited $LASTEXITCODE" }

