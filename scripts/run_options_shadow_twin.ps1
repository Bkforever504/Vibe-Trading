$ErrorActionPreference = "Stop"

$Repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$LogDir = "C:\Users\kenne\.vibe-trading\logs"
$LogPath = Join-Path $LogDir "options-shadow-twin.log"
$Python = (Get-Command python -ErrorAction Stop).Source

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Push-Location $Repo
try {
    & $Python "scripts/options_shadow_twin.py" 2>&1 |
        Out-File -FilePath $LogPath -Append -Encoding utf8
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
