$ErrorActionPreference = "Stop"
$Repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
Set-Location $Repo
$LogPath = "C:\Users\kenne\.vibe-trading\logs\event-gap-continuation-shadow.log"
$env:UV_CACHE_DIR = "C:\Users\kenne\.vibe-trading\cache\uv"
New-Item -ItemType Directory -Force -Path (Split-Path $LogPath) | Out-Null
New-Item -ItemType Directory -Force -Path $env:UV_CACHE_DIR | Out-Null

uv run --no-project --with yfinance python scripts/event_gap_continuation_shadow.py 2>&1 |
    Tee-Object -FilePath $LogPath -Append
if ($LASTEXITCODE -ne 0) {
    throw "event_gap_continuation_shadow failed with exit code $LASTEXITCODE"
}

uv run --no-project python scripts/trade_signal_generator.py 2>&1 |
    Tee-Object -FilePath $LogPath -Append
if ($LASTEXITCODE -ne 0) {
    throw "trade_signal_generator failed with exit code $LASTEXITCODE"
}
