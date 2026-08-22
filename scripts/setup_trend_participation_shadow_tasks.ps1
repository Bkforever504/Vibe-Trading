$ErrorActionPreference = "Stop"

$Repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$Runner = Join-Path $Repo "scripts\run_trend_participation_shadow.ps1"
$PowerShell = (Get-Command powershell.exe -ErrorAction Stop).Source
$TaskPath = "\VibeTrade\"

function New-ShadowAction([string]$Mode) {
    New-ScheduledTaskAction `
        -Execute $PowerShell `
        -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$Runner`" -Mode $Mode"
}

$Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit ([System.TimeSpan]::FromMinutes(10)) `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable
$Principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Limited

$EntryName = "TrendParticipationShadowEntry"
$EntryTriggers = @(
    New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At "8:47AM"
    New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At "2:02PM"
)
Unregister-ScheduledTask -TaskName $EntryName -TaskPath $TaskPath -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName $EntryName -TaskPath $TaskPath `
    -Action (New-ShadowAction "entry") -Trigger $EntryTriggers -Settings $Settings -Principal $Principal `
    -Description "Forward-only defined-risk trend participation shadow entries. No orders." | Out-Null

$MonitorName = "TrendParticipationShadowMonitor"
$MonitorTrigger = New-ScheduledTaskTrigger `
    -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At "8:50AM"
Unregister-ScheduledTask -TaskName $MonitorName -TaskPath $TaskPath -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName $MonitorName -TaskPath $TaskPath `
    -Action (New-ShadowAction "monitor") -Trigger $MonitorTrigger -Settings $Settings -Principal $Principal `
    -Description "Executable quote monitor for trend participation shadow candidates. No orders." | Out-Null

[xml]$TaskXml = Export-ScheduledTask -TaskName $MonitorName -TaskPath $TaskPath
$Namespace = $TaskXml.DocumentElement.NamespaceURI
$NamespaceManager = New-Object System.Xml.XmlNamespaceManager($TaskXml.NameTable)
$NamespaceManager.AddNamespace("task", $Namespace)
$CalendarTrigger = $TaskXml.SelectSingleNode("/task:Task/task:Triggers/task:CalendarTrigger", $NamespaceManager)
$StartBoundary = $CalendarTrigger.SelectSingleNode("task:StartBoundary", $NamespaceManager)
$Repetition = $TaskXml.CreateElement("Repetition", $Namespace)
foreach ($Item in @(
    @("Interval", "PT5M"),
    @("Duration", "PT6H5M"),
    @("StopAtDurationEnd", "false")
)) {
    $Node = $TaskXml.CreateElement($Item[0], $Namespace)
    $Node.InnerText = $Item[1]
    [void]$Repetition.AppendChild($Node)
}
[void]$CalendarTrigger.InsertBefore($Repetition, $StartBoundary)
Register-ScheduledTask -TaskName $MonitorName -TaskPath $TaskPath -Xml $TaskXml.OuterXml -Force | Out-Null

Write-Host "Registered $TaskPath$EntryName at 8:47AM and 2:02PM Central."
Write-Host "Registered $TaskPath$MonitorName every five minutes from 8:50AM through 2:55PM Central."
Write-Host "Both tasks are shadow-only and cannot submit orders."

