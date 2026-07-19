$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
python scripts/zero_dte_expected_move_context.py --print
