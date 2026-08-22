param(
    [ValidateSet("premarket", "intraday", "eod")]
    [string]$Period = "premarket"
)

$ErrorActionPreference = "Stop"
$WorkingDir = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$LogPath = "C:\Users\kenne\.vibe-trading\logs\daily-opportunity-brief.log"

Set-Location -LiteralPath $WorkingDir
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $LogPath) | Out-Null

if ($Period -eq "premarket") {
    $RadarPath = "C:\Users\kenne\.vibe-trading\reports\intraday-opportunity-radar.json"
    $Symbols = @("SPY", "QQQ", "IWM", "AAPL", "MSFT", "NVDA", "AMD", "AMZN", "META", "TSLA")
    if (Test-Path -LiteralPath $RadarPath) {
        try {
            $Radar = Get-Content -LiteralPath $RadarPath -Raw | ConvertFrom-Json
            $Discovered = @($Radar.ranked_candidates | Select-Object -First 20 | ForEach-Object { $_.symbol })
            $Symbols = @($Symbols + $Discovered | Where-Object { $_ } | Sort-Object -Unique)
        } catch {
            Write-Warning "Could not read prior radar symbols; using the liquid fallback universe."
        }
    }
    python scripts\sec_catalyst_feed.py --symbols ($Symbols -join ",") 2>&1 |
        Tee-Object -FilePath $LogPath -Append
    if ($LASTEXITCODE -ne 0) {
        throw "SEC catalyst refresh failed with exit code $LASTEXITCODE"
    }
}

# Refresh the read-only projection before each brief. The live stream replaces
# this fallback during market hours.
python scripts\live_opportunity_engine.py 2>&1 |
    Tee-Object -FilePath $LogPath -Append
if ($LASTEXITCODE -ne 0) {
    throw "live opportunity fallback failed with exit code $LASTEXITCODE"
}

python scripts\daily_opportunity_brief.py --period $Period 2>&1 |
    Tee-Object -FilePath $LogPath -Append
if ($LASTEXITCODE -ne 0) {
    throw "daily opportunity brief failed with exit code $LASTEXITCODE"
}
