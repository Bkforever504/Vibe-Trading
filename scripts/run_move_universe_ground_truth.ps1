Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Set-Location "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
& python scripts\move_universe_ground_truth.py
if ($LASTEXITCODE -ne 0) { throw "move_universe_ground_truth exited $LASTEXITCODE" }
