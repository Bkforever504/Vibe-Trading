# Register one low-noise, shadow-only MNQ family cycle every completed RTH five-minute bar.
# First run: 08:35 CT (09:35 ET). Last run: 15:35 CT (16:35 ET),
# allowing the frozen 16:30 ET time exit to resolve on the first completed bar.
$ErrorActionPreference = "Stop"

if ((Get-TimeZone).Id -ne "Central Standard Time") {
    throw "MNQ SMT family task registration requires Central Standard Time."
}

$repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$runner = "$repo\scripts\run_mnq_smt_family_shadow.ps1"
$taskPath = "\VibeTrade\"
$taskName = "MnqSmtCisdFamilyShadow"

$service = New-Object -ComObject "Schedule.Service"
$service.Connect()
$rootFolder = $service.GetFolder("\")
try {
    $null = $service.GetFolder("\VibeTrade")
} catch {
    $null = $rootFolder.CreateFolder("VibeTrade")
}

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$runner`" -Mode cycle"
$trigger = New-ScheduledTaskTrigger `
    -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At "08:35"
$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable

Register-ScheduledTask `
    -TaskName $taskName `
    -TaskPath "\VibeTrade\" `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -RunLevel Limited `
    -Description "Four independent MNQ SMT/CISD shadow ablations. Qualified entries/exits/errors only; no orders." `
    -Force | Out-Null

# ScheduledTasks has no public repetition constructor, so add the five-minute window through task XML.
[xml]$taskXml = Export-ScheduledTask -TaskName $taskName -TaskPath $taskPath
$namespace = $taskXml.DocumentElement.NamespaceURI
$manager = New-Object System.Xml.XmlNamespaceManager($taskXml.NameTable)
$manager.AddNamespace("task", $namespace)
$calendar = $taskXml.SelectSingleNode("/task:Task/task:Triggers/task:CalendarTrigger", $manager)
$startBoundary = $calendar.SelectSingleNode("task:StartBoundary", $manager)
$repetition = $taskXml.CreateElement("Repetition", $namespace)
foreach ($item in @(
    @("Interval", "PT5M"),
    @("Duration", "PT7H"),
    @("StopAtDurationEnd", "false")
)) {
    $node = $taskXml.CreateElement($item[0], $namespace)
    $node.InnerText = $item[1]
    [void]$repetition.AppendChild($node)
}
[void]$calendar.InsertBefore($repetition, $startBoundary)
Register-ScheduledTask -TaskName $taskName -TaskPath $taskPath -Xml $taskXml.OuterXml -Force | Out-Null

Write-Host "Registered $taskPath$taskName every five minutes from 08:35 through 15:35 CT, weekdays."
Write-Host "Shadow evidence only. execution_enabled=false; can_submit_orders=false."
