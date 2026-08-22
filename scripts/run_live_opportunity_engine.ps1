$ErrorActionPreference = "Stop"
$WorkingDir = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$LogPath = "C:\Users\kenne\.vibe-trading\logs\live-opportunity-engine.log"

Set-Location -LiteralPath $WorkingDir
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $LogPath) | Out-Null

# This process consumes market data only. It contains no broker order client.
python scripts\live_opportunity_engine.py --stream 2>&1 |
    Tee-Object -FilePath $LogPath -Append

if ($LASTEXITCODE -ne 0) {
    throw "live_opportunity_engine failed with exit code $LASTEXITCODE"
}
