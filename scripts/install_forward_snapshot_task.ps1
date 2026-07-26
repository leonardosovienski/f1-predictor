param([switch]$RunNow)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
# pythonw.exe, nao python.exe: esta tarefa dispara de 15 em 15 minutos sob
# LogonType Interactive, e python.exe e do subsistema de CONSOLE — abriria uma
# janela preta na tela do dono a cada disparo, em C:\Windows\System32. Todas as
# demais tarefas do ecossistema ja usam pythonw; esta ficou para tras porque
# esta Disabled desde 23/07 e ninguem a viu rodar. Corrigido em 2026-07-26,
# ANTES de uma eventual reabertura em 2027 — o gate H8 e aritmeticamente
# impossivel em 2026, entao a proxima vez que isto rodar sera daqui a meses e
# o defeito teria voltado silenciosamente.
$pythonExe = Join-Path $projectRoot ".venv\Scripts\pythonw.exe"
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
