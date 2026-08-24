$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$StateDir = Join-Path $env:USERPROFILE ".vibe-trading"
$Frontend = Join-Path $RepoRoot "frontend\dist"
$Python = (Get-Command python -ErrorAction Stop).Source
$Cloudflared = Join-Path $StateDir "tools\cloudflared.exe"
$ApiKeyFile = Join-Path $StateDir "dashboard-api-key.txt"
$TokenFile = Join-Path $StateDir "remote-dashboard-token.txt"
$UrlFile = Join-Path $StateDir "remote-dashboard-url.txt"
$TunnelStdout = Join-Path $StateDir "cloudflared-remote-dashboard.out.log"
$TunnelStderr = Join-Path $StateDir "cloudflared-remote-dashboard.err.log"
$TunnelBackoffFile = Join-Path $StateDir "cloudflared-remote-dashboard-backoff.txt"
$SupervisorLog = Join-Path $StateDir "remote-dashboard-supervisor.log"

function Write-SupervisorLog([string]$Message) {
    $line = "$(Get-Date -Format o) $Message"
    Add-Content -LiteralPath $SupervisorLog -Value $line -Encoding utf8
}

function Test-Port([int]$Port) {
    return [bool](Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
}

function Start-Backend {
    if (Test-Port 8899) { return }
    $script = Join-Path $PSScriptRoot "run_live_trading_dashboard_backend.ps1"
    Start-Process -FilePath "powershell.exe" -ArgumentList @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $script
    ) -WindowStyle Hidden
    Write-SupervisorLog "Started dashboard backend on port 8899"
}

function Start-Gateway {
    if (Test-Port 8898) { return }
    $gateway = Join-Path $PSScriptRoot "remote_dashboard_gateway.py"
    Start-Process -FilePath $Python -ArgumentList @(
        $gateway,
        "--host", "127.0.0.1",
        "--port", "8898",
        "--frontend", $Frontend,
        "--backend", "http://127.0.0.1:8899",
        "--api-key-file", $ApiKeyFile,
        "--token-file", $TokenFile
    ) -WindowStyle Hidden
    Write-SupervisorLog "Started read-only dashboard gateway on port 8898"
}

function Test-RemoteTunnel {
    try {
        $metrics = Invoke-WebRequest -Uri "http://127.0.0.1:20241/metrics" -UseBasicParsing -TimeoutSec 5
        return $metrics.Content -match "(?m)^cloudflared_tunnel_ha_connections\s+1\s*$"
    } catch {
        return $false
    }
}

function Test-PublishedUrl {
    if (-not (Test-Path -LiteralPath $UrlFile)) { return $false }
    try {
        $published = [uri](Get-Content -LiteralPath $UrlFile -Raw).Trim()
        if ($published.Scheme -ne "https" -or -not $published.Host.EndsWith(".trycloudflare.com")) {
            return $false
        }
        # Windows can retain a negative DNS cache entry while a new Cloudflare
        # quick-tunnel hostname is already public. Query public resolvers so the
        # supervisor does not churn a healthy tunnel every 90 seconds.
        foreach ($resolver in @("1.1.1.1", "8.8.8.8")) {
            try {
                $answers = Resolve-DnsName -Name $published.Host -Type A -Server $resolver -DnsOnly -ErrorAction Stop
                if (@($answers | Where-Object { $_.IPAddress }).Count -gt 0) { return $true }
            } catch {
                continue
            }
        }
        return $false
    } catch {
        return $false
    }
}

function Test-TunnelGracePeriod {
    if (-not (Test-Path -LiteralPath $UrlFile)) { return $false }
    $age = (Get-Date) - (Get-Item -LiteralPath $UrlFile).LastWriteTime
    return $age.TotalSeconds -lt 90
}

function Start-Tunnel {
    if (Test-Path -LiteralPath $TunnelBackoffFile) {
        try {
            $retryAfter = [datetime]::Parse((Get-Content -LiteralPath $TunnelBackoffFile -Raw).Trim())
            if ((Get-Date) -lt $retryAfter) { return }
        } catch {
            Remove-Item -LiteralPath $TunnelBackoffFile -Force -ErrorAction SilentlyContinue
        }
    }

    $existing = Get-CimInstance Win32_Process -Filter "Name = 'cloudflared.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like "*127.0.0.1:8898*" }
    if ($existing -and ((Test-TunnelGracePeriod) -or ((Test-RemoteTunnel) -and (Test-PublishedUrl)))) { return }
    if ($existing) {
        $existing | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        Write-SupervisorLog "Replaced unresponsive Cloudflare quick tunnel"
        Start-Sleep -Seconds 1
    }

    foreach ($path in @($TunnelStdout, $TunnelStderr)) {
        if (Test-Path -LiteralPath $path) {
            Remove-Item -LiteralPath $path -Force
        }
    }
    Start-Process -FilePath $Cloudflared -ArgumentList @(
        "tunnel", "--url", "http://127.0.0.1:8898", "--no-autoupdate", "--loglevel", "info"
    ) -RedirectStandardOutput $TunnelStdout -RedirectStandardError $TunnelStderr -WindowStyle Hidden
    Write-SupervisorLog "Started Cloudflare quick tunnel"

    $deadline = (Get-Date).AddSeconds(30)
    do {
        Start-Sleep -Milliseconds 500
        $logs = @($TunnelStdout, $TunnelStderr) | Where-Object { Test-Path -LiteralPath $_ }
        if ($logs) {
            if (Select-String -Path $logs -Pattern "429 Too Many Requests|error code: 1015" -Quiet) {
                (Get-Date).AddMinutes(30).ToString("o") |
                    Set-Content -LiteralPath $TunnelBackoffFile -Encoding ascii
                Write-SupervisorLog "Cloudflare quick tunnel rate limited; backing off for 30 minutes"
                return
            }
            $match = Select-String -Path $logs -Pattern "https://[a-z0-9-]+\.trycloudflare\.com" |
                Select-Object -First 1
            if ($match -and $match.Matches.Count -gt 0) {
                $match.Matches[0].Value | Set-Content -LiteralPath $UrlFile -Encoding ascii
                Remove-Item -LiteralPath $TunnelBackoffFile -Force -ErrorAction SilentlyContinue
                Write-SupervisorLog "Published remote dashboard URL"
                return
            }
        }
    } while ((Get-Date) -lt $deadline)
    Write-SupervisorLog "Tunnel started but URL was not published within 30 seconds"
}

foreach ($required in @($Frontend, $Cloudflared, $ApiKeyFile, $TokenFile)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "Required dashboard dependency is missing: $required"
    }
}

Write-SupervisorLog "Dashboard supervisor started"
while ($true) {
    try {
        Start-Backend
        Start-Sleep -Seconds 2
        Start-Gateway
        Start-Sleep -Seconds 2
        Start-Tunnel
    } catch {
        Write-SupervisorLog "Supervisor recovery error: $($_.Exception.Message)"
    }
    Start-Sleep -Seconds 15
}
