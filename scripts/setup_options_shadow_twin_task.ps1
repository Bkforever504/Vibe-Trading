$ErrorActionPreference = "Stop"

$TaskName = "VibeTradingOptionsShadowTwin"
$Repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$Runner = Join-Path $Repo "scripts\run_options_shadow_twin.ps1"
$PowerShell = (Get-Command powershell.exe -ErrorAction Stop).Source

$Action = New-ScheduledTaskAction `
    -Execute $PowerShell `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$Runner`""

# Central and Eastern US daylight rules move together. These local Central
# triggers cover 09:45 through 15:45 America/New_York.
$Trigger = New-ScheduledTaskTrigger `
    -Weekly `
    -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday `
    -At "8:45AM"

$Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit ([System.TimeSpan]::FromMinutes(10)) `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable

$Principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Limited

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Principal $Principal `
    -Description "Read-only options candidate shadow twin. No order endpoints." | Out-Null

# New-ScheduledTaskTrigger cannot express repetition on a weekly trigger, but
# the Task Scheduler schema supports it. Add the one-minute repetition to the
# registered weekly calendar trigger and register the validated XML back.
[xml]$TaskXml = Export-ScheduledTask -TaskName $TaskName
$Namespace = $TaskXml.DocumentElement.NamespaceURI
$NamespaceManager = New-Object System.Xml.XmlNamespaceManager($TaskXml.NameTable)
$NamespaceManager.AddNamespace("task", $Namespace)
$CalendarTrigger = $TaskXml.SelectSingleNode(
    "/task:Task/task:Triggers/task:CalendarTrigger",
    $NamespaceManager
)
$StartBoundary = $CalendarTrigger.SelectSingleNode("task:StartBoundary", $NamespaceManager)
$Repetition = $TaskXml.CreateElement("Repetition", $Namespace)
foreach ($Item in @(
    @("Interval", "PT1M"),
    @("Duration", "PT6H10M"),
    @("StopAtDurationEnd", "false")
)) {
    $Node = $TaskXml.CreateElement($Item[0], $Namespace)
    $Node.InnerText = $Item[1]
    [void]$Repetition.AppendChild($Node)
}
[void]$CalendarTrigger.InsertBefore($Repetition, $StartBoundary)
Register-ScheduledTask -TaskName $TaskName -Xml $TaskXml.OuterXml -Force | Out-Null

Write-Host "Task registered: $TaskName"
Write-Host "Runs weekdays every minute from 8:45AM through 2:55PM Central."
Write-Host "No order endpoints are imported or called."
