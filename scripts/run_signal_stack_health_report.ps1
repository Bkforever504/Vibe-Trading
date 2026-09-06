param([string]$PythonPath)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir

Set-Location $projectRoot
$python = if ($PythonPath -and (Test-Path -LiteralPath $PythonPath)) {
    $PythonPath
} else {
    (Get-Command python.exe -ErrorAction SilentlyContinue).Source
}
if (-not $python) { $python = (Get-Command py.exe -ErrorAction SilentlyContinue).Source }
if (-not $python) { throw "No policy-allowed Python interpreter was found." }

& $python scripts/signal_stack_health_report.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

# Record the five-session operational prerequisite after the health snapshot.
# This report is read-only and can never authorize an order.
& $python scripts/operational_readiness_gate.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
