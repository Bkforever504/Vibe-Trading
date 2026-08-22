$ErrorActionPreference = "Stop"
Set-Location "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$LogPath = "C:\Users\kenne\.vibe-trading\logs\premarket-opportunity-radar.log"
New-Item -ItemType Directory -Force -Path (Split-Path $LogPath) | Out-Null
uv run --no-project --with pandas --with yfinance --with alpaca-py python scripts/bottom_reversal_investigator.py 2>&1 |
    Tee-Object -FilePath $LogPath -Append
if ($LASTEXITCODE -ne 0) {
    throw "bottom_reversal_investigator failed with exit code $LASTEXITCODE"
}
uv run --no-project --with pandas --with yfinance --with alpaca-py python scripts/bottom_reversal_forward_tracker.py 2>&1 |
    Tee-Object -FilePath $LogPath -Append
if ($LASTEXITCODE -ne 0) {
    throw "bottom_reversal_forward_tracker failed with exit code $LASTEXITCODE"
}
uv run --no-project --with pandas --with requests python scripts/premarket_opportunity_radar.py 2>&1 |
    Tee-Object -FilePath $LogPath -Append
if ($LASTEXITCODE -ne 0) {
    throw "premarket_opportunity_radar failed with exit code $LASTEXITCODE"
}
uv run --no-project python scripts/trade_signal_generator.py --no-alert 2>&1 |
    Tee-Object -FilePath $LogPath -Append
if ($LASTEXITCODE -ne 0) {
    throw "trade_signal_generator failed with exit code $LASTEXITCODE"
}
