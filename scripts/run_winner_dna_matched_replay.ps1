$ErrorActionPreference = "Stop"

$Repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$LogDir = "C:\Users\kenne\.vibe-trading\logs"
$LogPath = Join-Path $LogDir "winner-dna-matched-replay.log"
$Uv = (Get-Command uv -ErrorAction Stop).Source

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Push-Location $Repo
try {
    & $Uv run --no-project --with pandas --with numpy --with pyarrow `
        python "research/winner_dna_matched_replay.py" 2>&1 |
        Out-File -FilePath $LogPath -Append -Encoding utf8
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}

