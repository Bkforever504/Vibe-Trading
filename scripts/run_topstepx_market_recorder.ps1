$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# Topstep prohibits VPS, VPN, and remote-server API automation. This runner is
# intentionally local and read-only; the Python gate also requires the exact
# PERSONAL_DEVICE_CONFIRMED value before opening the market-data connection.
uv run --no-project python scripts/topstepx_market_recorder.py --seconds 7200
exit $LASTEXITCODE
