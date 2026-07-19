param(
    [string]$Output = "$env:USERPROFILE\.vibe-trading\dashboard.html"
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $repo

python scripts\generate_dashboard.py --output $Output
