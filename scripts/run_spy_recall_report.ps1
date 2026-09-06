param([string]$PythonPath)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir
Set-Location $projectRoot

$logDir = Join-Path $HOME ".vibe-trading\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logPath = Join-Path $logDir "spy-recall-report.log"

$ErrorActionPreference = "Continue"
# See run_spy_move_ledger.ps1: use a policy-allowed interpreter when the venv
# executable is blocked by Windows Application Control.
$python = if ($PythonPath -and (Test-Path -LiteralPath $PythonPath)) { $PythonPath } else { (Get-Command python.exe -ErrorAction SilentlyContinue).Source }
if (-not $python) { $python = (Get-Command py.exe -ErrorAction SilentlyContinue).Source }
$exitCode = 1
if ($python) {
    & $python scripts/spy_recall_report.py --days 5 --print-misses *>> $logPath
    if ($LASTEXITCODE -ne $null) { $exitCode = $LASTEXITCODE }
}
$ErrorActionPreference = "Stop"
if ($exitCode -ne 0) {
    Write-Warning "spy_recall_report exited $exitCode; see $logPath"
    exit 0
}
exit 0
