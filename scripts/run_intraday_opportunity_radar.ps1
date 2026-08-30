$ErrorActionPreference = "Stop"
$WorkingDir = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$LogDir = "C:\Users\kenne\.vibe-trading\logs"
$LogPath = Join-Path $LogDir "intraday-opportunity-radar.log"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Set-Location $WorkingDir

try {
    python scripts\intraday_opportunity_radar.py *>> $LogPath
    if ($LASTEXITCODE -ne 0) { throw "intraday radar exited $LASTEXITCODE" }
    python scripts\spy_level_reaction_shadow.py *>> $LogPath
    if ($LASTEXITCODE -ne 0) { throw "SPY mapped-level reaction monitor exited $LASTEXITCODE" }
    python scripts\spy_level_reaction_outcome_report.py *>> $LogPath
    if ($LASTEXITCODE -ne 0) { throw "SPY mapped-level outcome resolver exited $LASTEXITCODE" }
    python scripts\simple_price_action_alerts.py --alert *>> $LogPath
    if ($LASTEXITCODE -ne 0) { throw "simple price action alerts exited $LASTEXITCODE" }
    python scripts\daily_move_coverage_review.py *>> $LogPath
    if ($LASTEXITCODE -ne 0) { throw "move coverage review exited $LASTEXITCODE" }
} catch {
    "$(Get-Date -Format o) ERROR $($_.Exception.Message)" | Add-Content -LiteralPath $LogPath
    throw
}
