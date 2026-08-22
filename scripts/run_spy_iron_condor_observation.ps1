$ErrorActionPreference = "Stop"
$Repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$LogDir = "C:\Users\kenne\.vibe-trading\logs"
$LogPath = Join-Path $LogDir "spy-iron-condor-observation.log"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Push-Location $Repo
try {
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $output = python strategies/spy_iron_condor.py --observe-only 2>&1
    $exitCode = $LASTEXITCODE
    $ErrorActionPreference = $previousPreference
    $output | Out-File -FilePath $LogPath -Append -Encoding utf8
    exit $exitCode
}
finally {
    Pop-Location
}
