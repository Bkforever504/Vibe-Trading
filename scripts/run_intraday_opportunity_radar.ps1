$ErrorActionPreference = "Stop"
$WorkingDir = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$LogDir = "C:\Users\kenne\.vibe-trading\logs"
$LogPath = Join-Path $LogDir "intraday-opportunity-radar.log"
$HealthDir = "C:\Users\kenne\.vibe-trading\health"
$HealthPath = Join-Path $HealthDir "radar_wrapper.json"
$RadarLog = Join-Path $WorkingDir "data\intraday_opportunity_radar_log.jsonl"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
New-Item -ItemType Directory -Force -Path $HealthDir | Out-Null
Set-Location $WorkingDir

function Write-Health {
    param([string]$status, [string]$detail, [int]$rowDelta = 0)
    $obj = [ordered]@{
        as_of         = (Get-Date).ToUniversalTime().ToString('o')
        status        = $status
        detail        = $detail
        row_delta     = $rowDelta
        script        = 'run_intraday_opportunity_radar.ps1'
    }
    ($obj | ConvertTo-Json -Compress) | Set-Content -LiteralPath $HealthPath -Encoding utf8
}

function Log-Line {
    param([string]$line)
    $stamp = (Get-Date).ToString('o')
    "$stamp $line" | Add-Content -LiteralPath $LogPath -Encoding utf8
}

$preRows = if (Test-Path $RadarLog) { (Get-Content $RadarLog).Count } else { 0 }
Log-Line "START pre_rows=$preRows"
$RunEnvelopeId = $null
$RunEnvelopeStartedAt = $null
$DailyMapFailure = $null
try {
    $RunEnvelopeJson = & python scripts\operational_run_envelope.py start --component intraday-opportunity-radar --scheduled-for ((Get-Date).ToUniversalTime().ToString('o')) --input-count $preRows
    if ($LASTEXITCODE -ne 0) { throw "run envelope start exited $LASTEXITCODE" }
    $RunEnvelope = $RunEnvelopeJson | ConvertFrom-Json
    $RunEnvelopeId = $RunEnvelope.run_id
    $RunEnvelopeStartedAt = [datetimeoffset]::Parse($RunEnvelope.started_at)
    Log-Line "RUN_ENVELOPE start run_id=$RunEnvelopeId"
} catch {
    # Observability failure stays visible but cannot suppress shadow alerts.
    Log-Line "WARN run_envelope_start $($_.Exception.Message)"
}

try {
    Log-Line "STEP intraday_opportunity_radar"
    python scripts\intraday_opportunity_radar.py 2>&1 | Out-File -LiteralPath $LogPath -Append -Encoding utf8
    if ($LASTEXITCODE -ne 0) { throw "intraday radar exited $LASTEXITCODE" }

    # Daily context and completed 3-minute reactions feed the governed lane.
    # Direct duplicate map alerts are disabled here. Failures remain visible,
    # while the independent 5-minute radar and governed alert lane continue.
    try {
        Log-Line "STEP daily_level_map_shadow"
        python scripts\daily_level_map_shadow.py 2>&1 | Out-File -LiteralPath $LogPath -Append -Encoding utf8
        if ($LASTEXITCODE -ne 0) { throw "daily level-map shadow exited $LASTEXITCODE" }
        $DailyMapPath = "$env:USERPROFILE\.vibe-trading\reports\daily-level-map-shadow.json"
        if (-not (Test-Path -LiteralPath $DailyMapPath)) { throw 'daily level-map report missing' }
        $DailyMapCheck = Get-Content -LiteralPath $DailyMapPath -Raw | ConvertFrom-Json
        if ($DailyMapCheck.schema_version -ne 'daily-level-map-shadow-v1') { throw 'daily level-map schema invalid' }
        if ($DailyMapCheck.shadow_only -ne $true -or $DailyMapCheck.execution_enabled -ne $false -or $DailyMapCheck.can_submit_orders -ne $false) {
            throw 'daily level-map authority contract invalid'
        }
        if ($DailyMapCheck.status -ne 'ok') { $DailyMapFailure = "daily level-map status=$($DailyMapCheck.status)" }
    } catch {
        $DailyMapFailure = $_.Exception.Message
        Log-Line "WARN daily_level_map_shadow $DailyMapFailure"
    }

    Log-Line "STEP simple_price_action_alerts"
    python scripts\simple_price_action_alerts.py 2>&1 | Out-File -LiteralPath $LogPath -Append -Encoding utf8
    if ($LASTEXITCODE -ne 0) { throw "candidate normalization exited $LASTEXITCODE" }

    Log-Line "STEP institutional_confluence_shadow"
    python scripts\institutional_confluence_shadow.py 2>&1 | Out-File -LiteralPath $LogPath -Append -Encoding utf8
    if ($LASTEXITCODE -ne 0) { throw "institutional confluence shadow exited $LASTEXITCODE" }

    Log-Line "STEP governed_shadow_decision"
    python scripts\governed_shadow_decision.py 2>&1 | Out-File -LiteralPath $LogPath -Append -Encoding utf8
    if ($LASTEXITCODE -ne 0) { throw "governed shadow decision exited $LASTEXITCODE" }

    Log-Line "STEP governed_shadow_alert"
    python scripts\governed_shadow_alert.py --send 2>&1 | Out-File -LiteralPath $LogPath -Append -Encoding utf8
    if ($LASTEXITCODE -ne 0) { throw "governed shadow alert exited $LASTEXITCODE" }

    # Preserve accepted AND rejected candidates plus final quote checks before
    # the next scanner refresh overwrites the reports. Never on the send path.
    python scripts\scanner_evidence_snapshot.py 2>&1 | Out-File -LiteralPath $LogPath -Append -Encoding utf8
    if ($LASTEXITCODE -ne 0) { Log-Line "WARN scanner evidence snapshot exited=$LASTEXITCODE" }

    Log-Line "STEP governed_shadow_lifecycle"
    python scripts\governed_shadow_lifecycle.py 2>&1 | Out-File -LiteralPath $LogPath -Append -Encoding utf8
    if ($LASTEXITCODE -ne 0) { throw "governed shadow lifecycle exited $LASTEXITCODE" }

    Log-Line "STEP governed_shadow_outcome"
    python scripts\governed_shadow_outcome.py 2>&1 | Out-File -LiteralPath $LogPath -Append -Encoding utf8
    if ($LASTEXITCODE -ne 0) { throw "governed shadow outcome reconciliation exited $LASTEXITCODE" }

    Log-Line "STEP governed_shadow_rule_update"
    python scripts\governed_shadow_rule_update.py 2>&1 | Out-File -LiteralPath $LogPath -Append -Encoding utf8
    if ($LASTEXITCODE -ne 0) { throw "governed shadow rule update exited $LASTEXITCODE" }

    Log-Line "STEP post_delivery_grade_calibrator"
    python scripts\post_delivery_grade_calibrator.py 2>&1 | Out-File -LiteralPath $LogPath -Append -Encoding utf8
    if ($LASTEXITCODE -ne 0) { throw "post-delivery grade nomination exited $LASTEXITCODE" }

    Log-Line "STEP execution_readiness_scorecard"
    python scripts\execution_readiness_scorecard.py 2>&1 | Out-File -LiteralPath $LogPath -Append -Encoding utf8
    if ($LASTEXITCODE -ne 0) { throw "execution readiness scorecard exited $LASTEXITCODE" }

    Log-Line "STEP generate_dashboard_core"
    python scripts\generate_dashboard.py 2>&1 | Out-File -LiteralPath $LogPath -Append -Encoding utf8
    if ($LASTEXITCODE -ne 0) { throw "core dashboard generation exited $LASTEXITCODE" }

    # Best-effort research and accountability enrich the next snapshot. Their
    # health is logged, but a failure cannot take the real-time core offline.
    try {
    Log-Line "STEP donchian_expansion_shadow"
    python scripts\donchian_expansion_shadow.py 2>&1 | Out-File -LiteralPath $LogPath -Append -Encoding utf8
    if ($LASTEXITCODE -ne 0) { Log-Line "WARN donchian_expansion_shadow exited=$LASTEXITCODE" }
    Log-Line "STEP donchian_expansion_forward_shadow"
    python scripts\donchian_expansion_forward_shadow.py 2>&1 | Out-File -LiteralPath $LogPath -Append -Encoding utf8
    if ($LASTEXITCODE -ne 0) { Log-Line "WARN donchian_expansion_forward_shadow exited=$LASTEXITCODE" }
    Log-Line "STEP spy_level_reaction_shadow"
    python scripts\spy_level_reaction_shadow.py 2>&1 | Out-File -LiteralPath $LogPath -Append -Encoding utf8
    if ($LASTEXITCODE -ne 0) { Log-Line "WARN spy_level_reaction_shadow exited=$LASTEXITCODE" }
    Log-Line "STEP spy_level_reaction_outcome_report"
    python scripts\spy_level_reaction_outcome_report.py 2>&1 | Out-File -LiteralPath $LogPath -Append -Encoding utf8
    if ($LASTEXITCODE -ne 0) { Log-Line "WARN spy_level_reaction_outcome_report exited=$LASTEXITCODE" }

    # Macro releases remain a veto for ordinary ORB. This separate frozen
    # study only captures the completed 10:00 ET JOLTS+ISM reaction to a
    # 30-minute SPY range; it has no alert, rank, or execution authority.
    Log-Line "STEP macro_release_30m_orb_shadow"
    python scripts\macro_release_30m_orb_shadow.py 2>&1 | Out-File -LiteralPath $LogPath -Append -Encoding utf8
    if ($LASTEXITCODE -ne 0) { throw "macro release 30m ORB shadow exited $LASTEXITCODE" }

    Log-Line "STEP intraday_sector_posture"
    python scripts\intraday_sector_posture.py 2>&1 | Out-File -LiteralPath $LogPath -Append -Encoding utf8
    if ($LASTEXITCODE -ne 0) { throw "intraday sector posture exited $LASTEXITCODE" }

    # Refresh public primary-source filing provenance for the same radar
    # universe. SEC identity is mandatory; the adapter writes a disabled report
    # instead of fabricating a catalyst when it has not been configured.
    $RadarPath = "$env:USERPROFILE\.vibe-trading\reports\intraday-opportunity-radar.json"
    $Radar = Get-Content -LiteralPath $RadarPath -Raw | ConvertFrom-Json
    $SecSymbols = @($Radar.ranked_candidates | ForEach-Object { $_.symbol } | Where-Object { $_ } | Sort-Object -Unique)
    Log-Line "STEP sec_catalyst_feed symbols=$($SecSymbols.Count)"
    python scripts\sec_catalyst_feed.py --symbols ($SecSymbols -join ",") 2>&1 | Out-File -LiteralPath $LogPath -Append -Encoding utf8
    if ($LASTEXITCODE -ne 0) { throw "SEC catalyst feed exited $LASTEXITCODE" }

    # Build the same-clock-time cumulative IEX-volume baseline once per ET
    # session from the current radar universe. Subsequent cadence runs reuse
    # that session's cache; it has context-only authority.
    Log-Line "STEP intraday_rvol_baseline"
    python scripts\intraday_rvol_baseline.py --from-radar "$env:USERPROFILE\.vibe-trading\reports\intraday-opportunity-radar.json" 2>&1 | Out-File -LiteralPath $LogPath -Append -Encoding utf8
    if ($LASTEXITCODE -ne 0) { throw "intraday RVOL baseline exited $LASTEXITCODE" }

    # Context is fetched after discovery. Refresh it into this exact snapshot
    # before any downstream dashboard consumes it; this cannot alter rank,
    # alert, sizing, or execution authority.
    Log-Line "STEP refresh_intraday_radar_context"
    python scripts\refresh_intraday_radar_context.py 2>&1 | Out-File -LiteralPath $LogPath -Append -Encoding utf8
    if ($LASTEXITCODE -ne 0) { throw "radar context refresh exited $LASTEXITCODE" }

    # Captures the new contextual inside-bar and 4H-to-15m FVG hypotheses as
    # completed-bar research observations. It cannot alter rank, alerts,
    # sizing, or execution and remains separate from validated families.
    Log-Line "STEP contextual_pattern_observation"
    python scripts\contextual_pattern_observation.py 2>&1 | Out-File -LiteralPath $LogPath -Append -Encoding utf8
    if ($LASTEXITCODE -ne 0) { throw "contextual pattern observation exited $LASTEXITCODE" }

    Log-Line "STEP daily_move_coverage_review"
    python scripts\daily_move_coverage_review.py 2>&1 | Out-File -LiteralPath $LogPath -Append -Encoding utf8
    if ($LASTEXITCODE -ne 0) { throw "move coverage review exited $LASTEXITCODE" }

    # Join scanner coverage, persistent alert transitions, delivery health,
    # and retained pattern lessons into one no-execution accountability row.
    Log-Line "STEP continuous_improvement_scorecard"
    python scripts\continuous_improvement_scorecard.py 2>&1 | Out-File -LiteralPath $LogPath -Append -Encoding utf8
    if ($LASTEXITCODE -ne 0) { throw "continuous improvement scorecard exited $LASTEXITCODE" }

    Log-Line "STEP wolves_bbr_shadow"
    python scripts\wolves_bbr_shadow.py 2>&1 | Out-File -LiteralPath $LogPath -Append -Encoding utf8
    if ($LASTEXITCODE -ne 0) { throw "Wolves BBR shadow audit exited $LASTEXITCODE" }

    Log-Line "STEP banks_821_control_shadow"
    python scripts\banks_821_control_shadow.py 2>&1 | Out-File -LiteralPath $LogPath -Append -Encoding utf8
    if ($LASTEXITCODE -ne 0) { throw "Banks 8/21 shadow audit exited $LASTEXITCODE" }

    Log-Line "STEP liquid_signal_chart_audit"
    python scripts\liquid_signal_chart_audit.py 2>&1 | Out-File -LiteralPath $LogPath -Append -Encoding utf8
    if ($LASTEXITCODE -ne 0) { throw "liquid signal chart audit exited $LASTEXITCODE" }

    Log-Line "STEP liquid_universe_recall"
    python scripts\liquid_universe_recall.py 2>&1 | Out-File -LiteralPath $LogPath -Append -Encoding utf8
    if ($LASTEXITCODE -ne 0) { throw "liquid universe recall audit exited $LASTEXITCODE" }

    Log-Line "STEP liquid_recall_failure_cohorts"
    python scripts\liquid_recall_failure_cohorts.py 2>&1 | Out-File -LiteralPath $LogPath -Append -Encoding utf8
    if ($LASTEXITCODE -ne 0) { throw "liquid recall failure cohort analyzer exited $LASTEXITCODE" }

    } catch {
        Log-Line "WARN optional_research $($_.Exception.Message)"
    }

    $postRows = if (Test-Path $RadarLog) { (Get-Content $RadarLog).Count } else { 0 }
    $delta = $postRows - $preRows
    Log-Line "END post_rows=$postRows delta=$delta"
    if ($delta -lt 1) {
        Log-Line "HEALTH silent_failure: exit 0 but no radar_log row appended"
    }

    if ($RunEnvelopeId) {
        $RadarReportPath = "$env:USERPROFILE\.vibe-trading\reports\intraday-opportunity-radar.json"
        $AlertReportPath = "$env:USERPROFILE\.vibe-trading\reports\governed-shadow-alert-delivery.json"
        $DailyMapReportPath = "$env:USERPROFILE\.vibe-trading\reports\daily-level-map-shadow.json"
        $DataAsOf = $null
        $AlertsAttempted = 0
        $AlertsDelivered = 0
        $EnvelopeStatus = if ($delta -lt 1) { 'silent_failure' } else { 'success' }
        $EnvelopeFailureClass = if ($delta -lt 1) { 'silent_failure' } else { $null }
        $EnvelopeError = if ($delta -lt 1) { 'python exit 0 but no radar row appended' } else { '' }
        $EnvelopeNextAction = if ($delta -lt 1) { 'inspect radar append contract' } else { 'none' }
        if (Test-Path -LiteralPath $RadarReportPath) {
            try {
                $RadarReport = Get-Content -LiteralPath $RadarReportPath -Raw | ConvertFrom-Json
                $DataAsOf = $RadarReport.generated_at
                if (-not $DataAsOf) { throw 'radar generated_at missing' }
            } catch {
                $EnvelopeStatus = 'malformed_output'
                $EnvelopeFailureClass = 'malformed_output'
                $EnvelopeError = "radar report invalid: $($_.Exception.Message)"
                $EnvelopeNextAction = 'inspect radar report schema'
            }
        } else {
            $EnvelopeStatus = 'malformed_output'
            $EnvelopeFailureClass = 'malformed_output'
            $EnvelopeError = 'radar report missing after scanner run'
            $EnvelopeNextAction = 'restore radar report production'
        }
        if (Test-Path -LiteralPath $AlertReportPath) {
            try {
                $AlertReport = Get-Content -LiteralPath $AlertReportPath -Raw | ConvertFrom-Json
                $RequiredAlertFields = @('generated_at', 'send_enabled', 'events', 'alerts_sent', 'delivery_failures', 'pending_delivery', 'stale_skipped')
                foreach ($Field in $RequiredAlertFields) {
                    if ($null -eq $AlertReport.PSObject.Properties[$Field]) { throw "alert report missing field: $Field" }
                }
                $AlertGeneratedAt = [datetimeoffset]::Parse($AlertReport.generated_at)
                if ($RunEnvelopeStartedAt -and $AlertGeneratedAt -lt $RunEnvelopeStartedAt) { throw 'alert report predates this run' }
                if ($AlertReport.send_enabled -isnot [bool] -or $AlertReport.send_enabled -ne $true) { throw 'alert send mode was not enabled' }
                foreach ($Field in @('alerts_sent', 'delivery_failures', 'pending_delivery', 'stale_skipped')) {
                    $ParsedCount = 0
                    if (-not [int]::TryParse([string]$AlertReport.$Field, [ref]$ParsedCount) -or $ParsedCount -lt 0) {
                        throw "alert report invalid nonnegative count: $Field"
                    }
                }
                if ($AlertReport.events -is [string] -or $AlertReport.events -isnot [System.Collections.IEnumerable]) {
                    throw 'alert report events must be an array'
                }
                $EventRows = @($AlertReport.events)
                foreach ($EventRow in $EventRows) {
                    if ($null -eq $EventRow.PSObject.Properties['delivered'] -or $EventRow.delivered -isnot [bool]) {
                        throw 'alert report event missing Boolean delivered state'
                    }
                }
                $AlertsAttempted = $EventRows.Count
                $AlertsDelivered = [int]($AlertReport.alerts_sent)
                $DeliveredEvents = @($EventRows | Where-Object { $_.delivered -eq $true }).Count
                $FailedEvents = @($EventRows | Where-Object { $_.delivered -eq $false }).Count
                if ($AlertsDelivered -ne $DeliveredEvents -or [int]($AlertReport.delivery_failures) -ne $FailedEvents) {
                    throw 'alert report event counts do not reconcile'
                }
                if ([int]($AlertReport.delivery_failures) -gt 0 -or [int]($AlertReport.pending_delivery) -gt 0) {
                    $EnvelopeStatus = 'delivery_failure'
                    $EnvelopeFailureClass = 'delivery_failure'
                    $EnvelopeError = "alert delivery failures=$($AlertReport.delivery_failures) pending=$($AlertReport.pending_delivery)"
                    $EnvelopeNextAction = 'retry undelivered fresh shadow alerts'
                } elseif ([int]($AlertReport.stale_skipped) -gt 0) {
                    $EnvelopeStatus = 'stale'
                    $EnvelopeFailureClass = 'stale_input'
                    $EnvelopeError = "stale shadow alerts skipped=$($AlertReport.stale_skipped)"
                    $EnvelopeNextAction = 'inspect upstream alert latency'
                }
            } catch {
                $EnvelopeStatus = 'malformed_output'
                $EnvelopeFailureClass = 'malformed_output'
                $EnvelopeError = "alert delivery report invalid: $($_.Exception.Message)"
                $EnvelopeNextAction = 'inspect alert delivery evidence'
            }
        } else {
            $EnvelopeStatus = 'malformed_output'
            $EnvelopeFailureClass = 'malformed_output'
            $EnvelopeError = 'alert delivery report missing after alert step'
            $EnvelopeNextAction = 'restore alert delivery reporting'
        }
        if (Test-Path -LiteralPath $DailyMapReportPath) {
            try {
                $DailyMapReport = Get-Content -LiteralPath $DailyMapReportPath -Raw | ConvertFrom-Json
                foreach ($Field in @('generated_at', 'status', 'notification_attempts', 'alerts_sent', 'notification_failures', 'pending_delivery')) {
                    if ($null -eq $DailyMapReport.PSObject.Properties[$Field]) { throw "daily map report missing field: $Field" }
                }
                $DailyMapGeneratedAt = [datetimeoffset]::Parse($DailyMapReport.generated_at)
                if ($RunEnvelopeStartedAt -and $DailyMapGeneratedAt -lt $RunEnvelopeStartedAt) { throw 'daily map report predates this run' }
                $MapAttempted = [int]($DailyMapReport.notification_attempts)
                $MapDelivered = [int]($DailyMapReport.alerts_sent)
                $MapFailed = [int]($DailyMapReport.notification_failures)
                if ($MapAttempted -lt 0 -or $MapDelivered -lt 0 -or $MapFailed -lt 0 -or $MapDelivered + $MapFailed -ne $MapAttempted) {
                    throw 'daily map alert counts do not reconcile'
                }
                $AlertsAttempted += $MapAttempted
                $AlertsDelivered += $MapDelivered
                if ($MapFailed -gt 0 -or [int]($DailyMapReport.pending_delivery) -gt 0) {
                    $EnvelopeStatus = 'delivery_failure'
                    $EnvelopeFailureClass = 'delivery_failure'
                    $EnvelopeError = "daily map delivery failures=$MapFailed pending=$($DailyMapReport.pending_delivery)"
                    $EnvelopeNextAction = 'retry undelivered mapped-level transitions'
                } elseif ($DailyMapReport.status -ne 'ok' -and $EnvelopeStatus -eq 'success') {
                    $EnvelopeStatus = 'partial'
                    $EnvelopeFailureClass = 'partial_universe'
                    $EnvelopeError = "daily level-map status=$($DailyMapReport.status)"
                    $EnvelopeNextAction = 'inspect daily-map market data coverage'
                }
            } catch {
                $EnvelopeStatus = 'malformed_output'
                $EnvelopeFailureClass = 'malformed_output'
                $EnvelopeError = "daily map report invalid: $($_.Exception.Message)"
                $EnvelopeNextAction = 'inspect daily-map report and alert evidence'
            }
        } elseif ($DailyMapFailure) {
            $EnvelopeStatus = 'malformed_output'
            $EnvelopeFailureClass = 'malformed_output'
            $EnvelopeError = "daily map unavailable: $DailyMapFailure"
            $EnvelopeNextAction = 'restore daily-map report production'
        }
        $EnvelopeArgs = @(
            'scripts\operational_run_envelope.py', 'finish',
            '--component', 'intraday-opportunity-radar', '--run-id', $RunEnvelopeId,
            '--status', $EnvelopeStatus, '--exit-code', '0',
            '--input-count', "$preRows", '--output-count', "$delta",
            '--alerts-attempted', "$AlertsAttempted", '--alerts-delivered', "$AlertsDelivered"
        )
        if ($DataAsOf) { $EnvelopeArgs += @('--data-as-of', "$DataAsOf") }
        if ($EnvelopeFailureClass) {
            $EnvelopeArgs += @('--failure-class', $EnvelopeFailureClass, '--next-action', $EnvelopeNextAction, '--error', $EnvelopeError)
        }
        & python @EnvelopeArgs 2>&1 | Out-File -LiteralPath $LogPath -Append -Encoding utf8
        if ($LASTEXITCODE -ne 0) {
            Log-Line "WARN run_envelope_finish exited=$LASTEXITCODE"
            Write-Health -status 'observability_failure' -detail "run envelope finish exited $LASTEXITCODE" -rowDelta $delta
        } else {
            Write-Health -status $EnvelopeStatus -detail $EnvelopeNextAction -rowDelta $delta
        }
    } else {
        Write-Health -status 'observability_failure' -detail 'run envelope did not start' -rowDelta $delta
    }

    Log-Line "STEP generate_dashboard_final"
    python scripts\generate_dashboard.py 2>&1 | Out-File -LiteralPath $LogPath -Append -Encoding utf8
    if ($LASTEXITCODE -ne 0) { throw "dashboard generation exited $LASTEXITCODE" }
} catch {
    Log-Line "ERROR $($_.Exception.Message)"
    Write-Health -status 'error' -detail $_.Exception.Message -rowDelta 0
    if ($RunEnvelopeId) {
        & python scripts\operational_run_envelope.py finish --component intraday-opportunity-radar --run-id $RunEnvelopeId --status error --exit-code 1 --retryable --next-action 'allow next scheduled retry and inspect component evidence' --error $_.Exception.Message 2>&1 | Out-File -LiteralPath $LogPath -Append -Encoding utf8
    }
    throw
}
