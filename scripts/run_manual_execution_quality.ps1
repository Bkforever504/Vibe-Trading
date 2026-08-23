Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repo

& python scripts\manual_execution_quality.py
if ($LASTEXITCODE -ne 0) { throw "manual_execution_quality exited $LASTEXITCODE" }
