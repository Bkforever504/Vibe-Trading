$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$logDir = Join-Path $HOME ".vibe-trading\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
Set-Location $repo
. (Join-Path $PSScriptRoot "resolve_vibe_python.ps1")
$Python = Get-VibePython

& $Python strategies\micro_momentum_paper_bot.py --execute-paper *>> (Join-Path $logDir "micro-momentum-paper.log")
