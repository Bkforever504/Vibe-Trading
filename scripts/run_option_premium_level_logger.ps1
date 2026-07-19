$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
python scripts\option_premium_level_logger.py --symbols "SPY,QQQ,IWM,AAPL,NVDA"
