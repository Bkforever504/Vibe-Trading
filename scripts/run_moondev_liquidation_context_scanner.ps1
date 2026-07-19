$ErrorActionPreference = "Stop"
Set-Location "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
uv run --no-project python scripts\moondev_liquidation_context_scanner.py --timeframe 1h --hours 24 --min-poly-usd 5000 --print
