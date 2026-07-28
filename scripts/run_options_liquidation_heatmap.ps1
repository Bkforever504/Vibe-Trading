$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $repo
uv run --no-project --with yfinance --with pandas python scripts\options_liquidation_heatmap.py SPY QQQ IWM NVDA AAPL TSLA PLTR
