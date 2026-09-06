param([string]$PythonPath)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir
Set-Location $projectRoot

$logDir = Join-Path $HOME ".vibe-trading\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logPath = Join-Path $logDir "spy-move-ledger.log"

$ErrorActionPreference = "Continue"
# Application Control may block the project venv. Prefer the installed Python
# launcher; it has the same dependencies on this workstation and works from
# Task Scheduler without requiring a policy exception.
$python = if ($PythonPath -and (Test-Path -LiteralPath $PythonPath)) { $PythonPath } else { (Get-Command python.exe -ErrorAction SilentlyContinue).Source }
if (-not $python) { $python = (Get-Command py.exe -ErrorAction SilentlyContinue).Source }
$exitCode = 1
if ($python) {
    & $python scripts/spy_move_ledger.py *>> $logPath
    if ($LASTEXITCODE -ne $null) { $exitCode = $LASTEXITCODE }
}
$ErrorActionPreference = "Stop"
if ($exitCode -ne 0) {
    Write-Warning "spy_move_ledger exited $exitCode; see $logPath"
    exit 0  # fail-open: never block downstream on data-source hiccups
}
exit 0
