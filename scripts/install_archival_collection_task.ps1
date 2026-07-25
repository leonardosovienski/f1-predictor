param()

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $projectRoot ".venv\Scripts\python.exe"
$entrypoint = Join-Path $projectRoot "scripts\run_archival_collection.py"
$workspace = Split-Path -Parent $projectRoot
$runner = Join-Path $workspace "tools\operational_runner.py"
$runtime = Join-Path $env:LOCALAPPDATA "predictor-tools\runtime\f1-predictor\f1-archival-collection"
if (-not (Test-Path -LiteralPath $pythonExe) -or -not (Test-Path -LiteralPath $entrypoint) -or -not (Test-Path -LiteralPath $runner)) { throw "archival collection operational entrypoint unavailable" }

New-Item -ItemType Directory -Force -Path $runtime | Out-Null
$status = Join-Path $runtime "f1-archival-collection.consumer-status.json"
$actionArgs = @(
    ('"{0}"' -f $runner), '--task', 'f1-archival-collection', '--project', 'f1-predictor',
    '--cwd', ('"{0}"' -f $projectRoot), '--log', ('"{0}"' -f (Join-Path $runtime 'f1-archival-collection.log')),
    '--heartbeat', ('"{0}"' -f (Join-Path $runtime 'f1-archival-collection.heartbeat.json')),
    '--event-log', ('"{0}"' -f (Join-Path $runtime 'f1-archival-collection.events.jsonl')),
    '--lock', ('"{0}"' -f (Join-Path $runtime 'f1-archival-collection.lock')),
    '--lock-stale-after', '900', '--timeout', '300', '--provenance-mode', 'strict',
    '--consumer-status-json', ('"{0}"' -f $status), '--',
    ('"{0}"' -f $pythonExe), '-X', 'utf8', ('"{0}"' -f $entrypoint), '--status-output', ('"{0}"' -f $status)
)

$action = New-ScheduledTaskAction -Execute ((& py -3.13 -c "import sys; print(sys.executable)").Trim()) -Argument ($actionArgs -join ' ') -WorkingDirectory $projectRoot
$friday = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Friday -At 18:00
$sunday = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At 18:00
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 15)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName "f1-archival-collection" -Action $action -Trigger @($friday, $sunday) -Settings $settings -Principal $principal -Description "Calendar-aware F1 COLLECTION_ONLY through operational_runner; no H8/H2H/model/gate" -Force | Out-Null
Get-ScheduledTask -TaskName "f1-archival-collection" | Select-Object TaskName,State,TaskPath
