<#
.SYNOPSIS
    Restarts Jarvis Core, for example after changing .env.

    Stop-ScheduledTask alone is not enough: the venv's pythonw.exe is a small
    launcher that starts the real Python as a child process, and that child
    keeps running (and keeps the single-instance lock). This script stops both.

.EXAMPLE
    .\scripts\restart_core.ps1          # restart
    .\scripts\restart_core.ps1 -Stop    # stop only
#>
param([switch]$Stop)

$TaskName = 'Jarvis Core'

Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
$procs = Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" |
    Where-Object { $_.CommandLine -like '*core.jarvis_core*' }
if ($procs) {
    $procs | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Write-Host "Stopped Jarvis Core (process $($procs.ProcessId -join ', '))."
}

if ($Stop) { return }

Start-Sleep -Seconds 2
if (-not (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue)) {
    throw "Task '$TaskName' is missing - run .\scripts\install_core.ps1 first."
}
Start-ScheduledTask -TaskName $TaskName
Write-Host "Started '$TaskName'. Waiting for it to come online (up to 2 minutes)..."

for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 2
    try {
        $health = Invoke-RestMethod 'http://127.0.0.1:8765/health' -TimeoutSec 2
        if ($health.ready) { Write-Host "Jarvis Core is online." -ForegroundColor Green; return }
    } catch { }
}
Write-Host "Not online yet - see logs\jarvis_core.log" -ForegroundColor Yellow
