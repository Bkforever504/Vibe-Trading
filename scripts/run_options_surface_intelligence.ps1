$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $repo
uv run --no-project --with yfinance --with pandas python scripts\options_surface_intelligence.py
