Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Set-Location "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$date = Get-Date -Format "yyyy-MM-dd"
& python scripts\universe_coverage_delta.py --date $date
if ($LASTEXITCODE -ne 0) { throw "universe_coverage_delta exited $LASTEXITCODE" }
