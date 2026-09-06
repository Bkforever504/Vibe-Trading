$ErrorActionPreference = "Stop"
$WorkingDir = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $env:USERPROFILE ".vibe-trading\logs"
$LogPath = Join-Path $LogDir "cisd-retest-shadow.log"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Set-Location $WorkingDir

python scripts\cisd_retest_shadow.py --live-shadow 2>&1 | Out-File -LiteralPath $LogPath -Append -Encoding utf8
if ($LASTEXITCODE -ne 0) {
    throw "CISD retest shadow failed honestly with exit code $LASTEXITCODE"
}
