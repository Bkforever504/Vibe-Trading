$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir
$logDir = Join-Path $HOME ".vibe-trading\logs"
$logPath = Join-Path $logDir "liquid-options-edge-shadow.log"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
Set-Location $projectRoot
. (Join-Path $scriptDir "resolve_vibe_python.ps1")
$Python = Get-VibePython
$ErrorActionPreference = "Continue"
& $Python scripts/liquid_options_edge_shadow.py *>> $logPath
$exitCode = $LASTEXITCODE
$ErrorActionPreference = "Stop"
if ($exitCode -ne 0) {
    throw "liquid_options_edge_shadow exited with code $exitCode; see $logPath"
}
exit 0
