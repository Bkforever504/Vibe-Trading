$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
python scripts/zero_dte_entry_feature_edge_report.py
