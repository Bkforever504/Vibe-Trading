$ErrorActionPreference = "Stop"
$repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$log = Join-Path $env:USERPROFILE ".vibe-trading\logs\strat-30m-continuation-shadow.log"
New-Item -ItemType Directory -Force -Path (Split-Path $log) | Out-Null
Set-Location $repo
python scripts\strat_30m_continuation_shadow.py --print *>> $log
