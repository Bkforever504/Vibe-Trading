Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Set-Location "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"

uv run --no-project --with yfinance --with pandas --with numpy python scripts\sunday_shadow_preflight.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
