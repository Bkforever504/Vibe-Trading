$ErrorActionPreference = "Stop"

$TaskName = "IWM-Bot-Monitor"
$Repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$Runner = Join-Path $Repo "scripts\run_iwm_bot_monitor.ps1"
$PowerShell = (Get-Command powershell.exe -ErrorAction Stop).Source

$Action = New-ScheduledTaskAction `
    -Execute $PowerShell `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$Runner`""

$Trigger = New-ScheduledTaskTrigger `
    -Weekly `
    -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday `
    -At "8:35AM"

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
    -Description "Paper-only IWM options position monitor and guarded close manager." | Out-Null

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
    @("Duration", "PT6H25M"),
    @("StopAtDurationEnd", "false")
)) {
    $Node = $TaskXml.CreateElement($Item[0], $Namespace)
    $Node.InnerText = $Item[1]
    [void]$Repetition.AppendChild($Node)
}
[void]$CalendarTrigger.InsertBefore($Repetition, $StartBoundary)
Register-ScheduledTask -TaskName $TaskName -Xml $TaskXml.OuterXml -Force | Out-Null

Write-Host "Task registered: $TaskName"
Write-Host "Runs weekdays every minute from 8:35AM through 3:00PM Central."
Write-Host "Runner pins ALPACA_PAPER=true; live close orders are disabled."
