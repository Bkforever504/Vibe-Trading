$ErrorActionPreference = "Stop"
$StateDir = Join-Path $env:USERPROFILE ".vibe-trading"
$UrlPath = Join-Path $StateDir "remote-dashboard-url.txt"
$TokenPath = Join-Path $StateDir "remote-dashboard-token.txt"

foreach ($Path in @($UrlPath, $TokenPath)) {
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Required remote-dashboard state is missing: $Path"
    }
}

$Url = (Get-Content -LiteralPath $UrlPath -Raw).Trim().TrimEnd("/")
$Token = (Get-Content -LiteralPath $TokenPath -Raw).Trim()
if (-not $Url.StartsWith("https://") -or $Token.Length -lt 24) {
    throw "Remote-dashboard URL or token is invalid."
}

$PairingUrl = "$Url/?token=$([uri]::EscapeDataString($Token))"
Set-Clipboard -Value $PairingUrl
Write-Host "Fresh remote-dashboard pairing URL copied to the clipboard."
Write-Host "Treat it like a password; do not paste it into logs or source control."
