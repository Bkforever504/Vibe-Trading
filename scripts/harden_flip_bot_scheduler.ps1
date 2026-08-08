Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$taskNames = @(
    "Flip-Bot-Entry",
    "Flip-Bot-Monitor",
    "Flip-Bot-Monitor-5m-A",
    "Flip-Bot-Monitor-5m-B"
)

$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 20) `
    -StartWhenAvailable `
    -WakeToRun `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

foreach ($taskName in $taskNames) {
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction Stop
    Set-ScheduledTask `
        -TaskName $task.TaskName `
        -TaskPath $task.TaskPath `
        -Settings $settings | Out-Null
}

foreach ($taskName in $taskNames) {
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction Stop
    [pscustomobject]@{
        Task = $task.TaskName
        State = $task.State
        MultipleInstances = $task.Settings.MultipleInstances
        ExecutionTimeLimit = $task.Settings.ExecutionTimeLimit
        StartWhenAvailable = $task.Settings.StartWhenAvailable
        WakeToRun = $task.Settings.WakeToRun
        DisallowStartOnBattery = $task.Settings.DisallowStartIfOnBatteries
        StopOnBattery = $task.Settings.StopIfGoingOnBatteries
    }
}
