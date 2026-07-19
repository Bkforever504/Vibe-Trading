$ErrorActionPreference = "Stop"
$repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$log = Join-Path $env:USERPROFILE ".vibe-trading\logs\czt-order-flow-shadow.log"
New-Item -ItemType Directory -Force -Path (Split-Path $log) | Out-Null
Set-Location $repo
python scripts\czt_order_flow_shadow.py --print *>> $log
