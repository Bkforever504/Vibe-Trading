Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir
Set-Location $projectRoot

$logDir = Join-Path $HOME ".vibe-trading\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logPath = Join-Path $logDir "x-intake-scanner.log"

$ErrorActionPreference = "Continue"
& .venv/Scripts/python.exe scripts/x_intake_scanner.py --print *>> $logPath
$exitCode = $LASTEXITCODE
$ErrorActionPreference = "Stop"
if ($exitCode -ne 0) {
    Write-Warning "x_intake_scanner exited $exitCode; see $logPath"
    exit 0  # fail-open: never block downstream on X rate limits
}
exit 0
