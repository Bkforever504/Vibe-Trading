# One-shot repair: flip WakeToRun on every trading-related scheduled task so
# Modern Standby (lid-close, screen-off) cannot silently freeze the scanner
# stack. On 2026-08-26 the machine slept 10:13-12:28 CT and the shadow radar
# missed four qualified QQQ move windows because WakeToRun=false blocked the
# task from waking the box.
#
# Scope: any task whose TaskPath starts with a namespace we own OR whose
# TaskName matches a known trading prefix. Leaves unrelated Windows tasks
# untouched.
#
# Read-only preview by default. Pass -Apply to actually change settings.
param(
    [switch]$Apply,
    [switch]$IncludeDisabled
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$namespaces = @(
    '\VibeTrade\'
)
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$namePrefixes = @(
    'IntradayOpportunityRadar', 'DailyMoveCoverageReview',
    'VibeTrade', 'Flip-Bot', 'IWM-Bot', 'SPY-Theta-Harvester', 'SPY-Iron-Condor',
    'SPY-0DTE-PM', 'SPY-Wheel-Check', 'SPY-Weekend-Vol', 'VIX-Call-Hedge',
    'Portfolio-Theta-Dashboard', 'Liquidity-Sweep-Scanner', 'RSI2ShadowLogger',
    'KAMAShadowLogger', 'PatternGrader', 'CISD-PromotionTracker',
    'PromoteValidatedPatterns', 'VibeTradingOptionsShadowTwin',
    'VibeTradingShadowScanner', 'VibeTradingNightlyOptionsNBBOEvidence',
    'Flip-Bot-Event-Monitor', 'Flip-Bot-Entry', 'Flip-Bot-Monitor',
    'Flip-Bot-Exploration', 'Flip-Bot-Trend-Entry'
)

function Test-InScope($Task) {
    $Path = [string]$Task.TaskPath
    $Name = [string]$Task.TaskName
    foreach ($ns in $namespaces) {
        if ($Path -like "$ns*" -and $Path -ne '\') { return $true }
    }
    foreach ($prefix in $namePrefixes) {
        if ($Name -like "$prefix*") { return $true }
    }
    foreach ($action in $Task.Actions) {
        $arguments = if ($action.PSObject.Properties['Arguments']) { [string]$action.Arguments } else { '' }
        $workingDirectory = if ($action.PSObject.Properties['WorkingDirectory']) { [string]$action.WorkingDirectory } else { '' }
        if ($arguments -like "*$repoRoot*" -or $workingDirectory -like "$repoRoot*") {
            return $true
        }
    }
    return $false
}

$all = Get-ScheduledTask
$changed = 0
$skipped = 0
$already = 0
$results = @()

foreach ($task in $all) {
    $inScope = Test-InScope $task
    if (-not $inScope) { continue }
    if (-not $IncludeDisabled -and $task.State -eq 'Disabled') { $skipped++; continue }

    $current = $task.Settings.WakeToRun
    if ($current) {
        $already++
        $results += [pscustomobject]@{ TaskPath = $task.TaskPath; TaskName = $task.TaskName; Before = $true; After = $true; Action = 'already_enabled' }
        continue
    }

    if ($Apply) {
        $task.Settings.WakeToRun = $true
        Set-ScheduledTask -TaskName $task.TaskName -TaskPath $task.TaskPath -Settings $task.Settings | Out-Null
        $changed++
        $action = 'enabled'
    } else {
        $action = 'would_enable'
    }
    $results += [pscustomobject]@{ TaskPath = $task.TaskPath; TaskName = $task.TaskName; Before = $false; After = $true; Action = $action }
}

$results | Format-Table -AutoSize

$summary = [pscustomobject]@{
    apply_mode         = [bool]$Apply
    tasks_in_scope     = $results.Count
    already_enabled    = $already
    changed            = $changed
    skipped_disabled   = $skipped
}
$summary | Format-List

if (-not $Apply) {
    Write-Host "`nPreview only. Re-run with -Apply to change WakeToRun on the listed tasks." -ForegroundColor Yellow
    Write-Host "Note: this does not change the global AC sleep timeout; only the individual tasks' wake capability." -ForegroundColor Yellow
}
