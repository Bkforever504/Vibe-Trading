$ErrorActionPreference = "Stop"
$WorkingDir = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$ReportDir = "$env:USERPROFILE\.vibe-trading\reports"

Set-Location -LiteralPath $WorkingDir

# Read-only preparation sequence. Each producer persists its own evidence; the
# final gate is intentionally allowed to be BLOCKED without failing the task.
python scripts\ftfc_continuity_shadow.py
if ($LASTEXITCODE -ne 0) { throw "FTFC continuity screen exited $LASTEXITCODE" }

python scripts\intraday_opportunity_radar.py
if ($LASTEXITCODE -ne 0) { throw "pre-open radar exited $LASTEXITCODE" }

python scripts\intraday_sector_posture.py
if ($LASTEXITCODE -ne 0) { throw "pre-open sector posture exited $LASTEXITCODE" }

$RadarPath = Join-Path $ReportDir "intraday-opportunity-radar.json"
$Radar = Get-Content -LiteralPath $RadarPath -Raw | ConvertFrom-Json
$Symbols = @($Radar.ranked_candidates | ForEach-Object { $_.symbol } | Where-Object { $_ } | Sort-Object -Unique)

python scripts\intraday_rvol_baseline.py --from-radar $RadarPath
if ($LASTEXITCODE -ne 0) { throw "pre-open RVOL baseline exited $LASTEXITCODE" }

python scripts\sec_catalyst_feed.py --symbols ($Symbols -join ",")
if ($LASTEXITCODE -ne 0) { throw "pre-open SEC catalyst feed exited $LASTEXITCODE" }

python scripts\refresh_intraday_radar_context.py --radar-path $RadarPath
if ($LASTEXITCODE -ne 0) { throw "pre-open radar context refresh exited $LASTEXITCODE" }

python scripts\intraday_trade_lifecycle_shadow.py --radar-path $RadarPath
if ($LASTEXITCODE -ne 0) { throw "pre-open lifecycle shadow exited $LASTEXITCODE" }

python scripts\generate_dashboard.py
if ($LASTEXITCODE -ne 0) { throw "dashboard generation exited $LASTEXITCODE" }

python scripts\premarket_operational_readiness.py
if ($LASTEXITCODE -ne 0) { throw "pre-open readiness gate exited $LASTEXITCODE" }
