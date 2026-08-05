param(
    [ValidateSet("entry", "monitor", "morning")]
    [string]$Mode = "entry"
)

$ErrorActionPreference = "Stop"
$Repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$LogDir = "C:\Users\kenne\.vibe-trading\logs"
$LogPath = Join-Path $LogDir "trend-participation-shadow.log"
$Python = (Get-Command python -ErrorAction Stop).Source

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Push-Location $Repo
try {
    & $Python "scripts/trend_participation_shadow.py" --mode $Mode 2>&1 |
        Out-File -FilePath $LogPath -Append -Encoding utf8
    if ($LASTEXITCODE -ne 0) {
        throw "Trend participation shadow $Mode failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}

