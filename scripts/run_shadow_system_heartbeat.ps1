Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Set-Location "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"

python scripts\shadow_system_heartbeat.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
