param()

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $projectRoot ".venv\Scripts\python.exe"
$entrypoint = Join-Path $projectRoot "scripts\run_archival_collection.py"
if (-not (Test-Path -LiteralPath $pythonExe) -or -not (Test-Path -LiteralPath $entrypoint)) { throw "archival collection entrypoint unavailable" }

$action = New-ScheduledTaskAction -Execute $pythonExe -Argument ('-X utf8 "' + $entrypoint + '"') -WorkingDirectory $projectRoot
$friday = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Friday -At 18:00
$sunday = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At 18:00
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 15)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName "f1-archival-collection" -Action $action -Trigger @($friday, $sunday) -Settings $settings -Principal $principal -Description "Calendar-aware F1 COLLECTION_ONLY archive; no H8/H2H/model/gate" -Force | Out-Null
Get-ScheduledTask -TaskName "f1-archival-collection" | Select-Object TaskName,State,TaskPath
