param([switch]$RunNow)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $projectRoot ".venv\Scripts\python.exe"
$entrypoint = Join-Path $projectRoot "scripts\capture_next_forward_snapshot.py"
$taskName = "f1-forward-snapshot"

if (-not (Test-Path -LiteralPath $pythonExe -PathType Leaf)) {
    throw "Python executable not found: $pythonExe"
}
if (-not (Test-Path -LiteralPath $entrypoint -PathType Leaf)) {
    throw "Snapshot entrypoint not found: $entrypoint"
}

$action = New-ScheduledTaskAction -Execute $pythonExe `
    -Argument ('-X utf8 "' + $entrypoint + '"') -WorkingDirectory $projectRoot
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(5) `
    -RepetitionInterval (New-TimeSpan -Minutes 15)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME `
    -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal `
    -Description "Forward-only F1 snapshot poller; publishes only post-quali/pre-race" `
    -Force | Out-Null
if ($RunNow) { Start-ScheduledTask -TaskName $taskName }
Get-ScheduledTask -TaskName $taskName | Select-Object TaskName,State,TaskPath
Get-ScheduledTaskInfo -TaskName $taskName |
    Select-Object LastRunTime,LastTaskResult,NextRunTime,NumberOfMissedRuns
