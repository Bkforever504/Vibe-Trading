Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Set-Location "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$date = Get-Date -Format "yyyy-MM-dd"
& python scripts\detection_scorecard.py --date $date
if ($LASTEXITCODE -ne 0) { throw "detection_scorecard exited $LASTEXITCODE" }
