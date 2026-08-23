Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repo

& python scripts\broker_fill_observer.py --lookback-days 7 --max-pages 10 --page-size 100 --timeout-seconds 12
if ($LASTEXITCODE -ne 0) { throw "broker_fill_observer exited $LASTEXITCODE" }
