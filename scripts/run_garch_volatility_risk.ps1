$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
Set-Location $ProjectRoot

uv run --no-project `
  --with arch `
  --with alpaca-py `
  --with numpy `
  --with pandas `
  --with python-dotenv `
  --with yfinance `
  python scripts\garch_volatility_risk.py --print
