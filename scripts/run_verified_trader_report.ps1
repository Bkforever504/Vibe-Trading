$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir
$logDir = Join-Path $HOME ".vibe-trading\logs"
$logPath = Join-Path $logDir "verified-trader-report.log"

New-Item -ItemType Directory -Force -Path $logDir | Out-Null
Set-Location $projectRoot

python scripts/verified_trader_intake.py report *>&1 |
    Out-File -FilePath $logPath -Append -Encoding utf8
