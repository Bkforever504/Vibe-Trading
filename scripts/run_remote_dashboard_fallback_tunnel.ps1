$ErrorActionPreference = "Continue"

$StateDir = Join-Path $env:USERPROFILE ".vibe-trading"
$UrlFile = Join-Path $StateDir "remote-dashboard-url.txt"
$LogFile = Join-Path $StateDir "localhost-run-remote-dashboard.log"
$Ssh = (Get-Command ssh.exe -ErrorAction Stop).Source

New-Item -ItemType Directory -Path $StateDir -Force | Out-Null

while ($true) {
    Remove-Item -LiteralPath $LogFile -Force -ErrorAction SilentlyContinue
    & $Ssh -tt `
        -o StrictHostKeyChecking=no `
        -o ServerAliveInterval=30 `
        -o ServerAliveCountMax=3 `
        -o ExitOnForwardFailure=yes `
        -R 80:127.0.0.1:8898 `
        nokey@localhost.run 2>&1 | ForEach-Object {
            $line = [string]$_
            Add-Content -LiteralPath $LogFile -Value $line -Encoding utf8
            $match = [regex]::Match($line, "https://[a-z0-9]+\.lhr\.life")
            if ($match.Success) {
                # The localhost.run tunnel is secondary. Never let it replace a
                # healthy primary Cloudflare URL while cloudflared is running.
                $primaryTunnel = Get-Process cloudflared -ErrorAction SilentlyContinue
                if (-not $primaryTunnel) {
                    $match.Value | Set-Content -LiteralPath $UrlFile -Encoding ascii
                }
            }
        }
    Start-Sleep -Seconds 10
}
