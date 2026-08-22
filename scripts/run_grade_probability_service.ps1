Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Set-Location "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
& python scripts\grade_probability_service.py
if ($LASTEXITCODE -ne 0) { throw "grade_probability_service exited $LASTEXITCODE" }
