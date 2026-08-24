# Master one-time administrator setup for MES v2 + equity scout operations.
# This does not register, modify, or enable any live-order task.
param(
    [switch]$SkipProducerRefresh,
    [switch]$SkipDiscordConfirmation
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ((Get-TimeZone).Id -ne "Central Standard Time") {
    throw "Master trading alert registration requires Central Standard Time."
}

$repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
Set-Location $repo

& "$repo\scripts\register_mes_v2_shadow_tasks.ps1"
& "$repo\scripts\register_equity_orb_scout_v1_task.ps1"
& "$repo\scripts\register_equity_orb_scout_v2_task.ps1"
& "$repo\scripts\register_shadow_ops_tasks.ps1"
& "$repo\scripts\register_monday_checkin_task.ps1"

if (-not $SkipProducerRefresh) {
    foreach ($producer in @("HMMRegimeScanner", "MarketCatalystCalendar", "BotStatusSnapshot")) {
        Start-ScheduledTask -TaskPath "\VibeTrade\" -TaskName $producer
    }
    $deadline = (Get-Date).AddMinutes(3)
    do {
        Start-Sleep -Seconds 2
        $running = @(
            Get-ScheduledTask -TaskPath "\VibeTrade\" -TaskName "HMMRegimeScanner", "MarketCatalystCalendar", "BotStatusSnapshot" |
                Where-Object { $_.State -eq "Running" }
        )
    } while ($running.Count -gt 0 -and (Get-Date) -lt $deadline)
    if ($running.Count -gt 0) {
        throw "Producer refresh exceeded the three-minute setup limit."
    }
}

$expected = @(
    "MesOrb0932V2Entry",
    "MesOrb0932V2Resolve",
    "MesReopenDriftV2Entry",
    "MesReopenDriftV2Resolve",
    "MesV2DatabentoRegrade",
    "EquityOrbScoutV1Entry",
    "EquityOrbScoutV1Resolve",
    "EquityOrbScoutV2Entry",
    "EquityOrbScoutV2Resolve",
    "HMMRegimeScanner",
    "ShadowSystemHeartbeat",
    "SundayShadowPreflight",
    "EodShadowCheckin"
)
$bad = @()
foreach ($name in $expected) {
    $task = Get-ScheduledTask -TaskPath "\VibeTrade\" -TaskName $name -ErrorAction SilentlyContinue
    if ($null -eq $task -or $task.State -notin @("Ready", "Running")) {
        $bad += $name
    }
}
if ($bad.Count -gt 0) {
    throw "Missing or unhealthy scheduled tasks: $($bad -join ', ')"
}

foreach ($scanner in @("mes-orb-v2", "mes-reopen-v2", "equity-orb-scout-v1", "equity-orb-scout-v2")) {
    python scripts\shadow_alert_runner.py --scanner $scanner --mode entry --smoke
    if ($LASTEXITCODE -ne 0) { throw "Smoke failed: $scanner" }
}

python scripts\shadow_system_heartbeat.py --no-notify
$heartbeatCode = $LASTEXITCODE
python scripts\sunday_shadow_preflight.py --no-network --no-notify
$preflightCode = $LASTEXITCODE

$summary = "Trading alert system registered: 13 shadow/monitoring tasks Ready; scanner smoke PASS; heartbeat exit=$heartbeatCode; preflight exit=$preflightCode; no order authority."
Write-Host $summary
if (-not $SkipDiscordConfirmation) {
    python -m agent.notifier --message $summary
}
