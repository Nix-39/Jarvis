<#
.SYNOPSIS
    Registers Jarvis Core to start automatically at login, without a window,
    with normal user rights (no administrator privileges).

    Jarvis Core runs the reminders, the Telegram bot and the local API
    (127.0.0.1 only). It replaces the older "Jarvis Scheduler" task, which
    this script removes.

.EXAMPLE
    .\scripts\install_core.ps1              # install or update, and start now
    .\scripts\install_core.ps1 -Uninstall   # stop and remove
#>
param([switch]$Uninstall)

$ErrorActionPreference = 'Stop'
$TaskName    = 'Jarvis Core'
$OldTaskName = 'Jarvis Scheduler'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PythonW     = Join-Path $ProjectRoot '.venv\Scripts\pythonw.exe'
$User        = "$env:USERDOMAIN\$env:USERNAME"

function Remove-JarvisTask($Name) {
    if (Get-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue) {
        Stop-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $Name -Confirm:$false
        Write-Host "Removed '$Name'."
    }
}

# The old standalone scheduler is now part of Jarvis Core.
Remove-JarvisTask $OldTaskName

if ($Uninstall) {
    Remove-JarvisTask $TaskName
    return
}

if (-not (Test-Path $PythonW)) {
    throw "Could not find $PythonW - create the virtual environment first."
}

# Stop a running copy so the new one can take the single-instance lock.
Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
$manual = Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" |
    Where-Object { $_.CommandLine -like '*core.jarvis_core*' -or $_.CommandLine -like '*core.scheduler*' }
if ($manual) {
    Write-Host "Stopping Jarvis processes started by hand: $($manual.ProcessId -join ', ')"
    $manual | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 2
}

$action    = New-ScheduledTaskAction -Execute $PythonW -Argument '-m core.jarvis_core' -WorkingDirectory $ProjectRoot
$trigger   = New-ScheduledTaskTrigger -AtLogOn -User $User
$trigger.Delay = 'PT20S'   # give Ollama and Docker a head start (Jarvis also waits for Ollama itself)
$principal = New-ScheduledTaskPrincipal -UserId $User -LogonType Interactive -RunLevel Limited
$settings  = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
                -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -StartWhenAvailable `
                -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal `
    -Settings $settings -Description 'Jarvis Core - reminders, Telegram bot and local API (127.0.0.1).' -Force | Out-Null

Start-ScheduledTask -TaskName $TaskName
Write-Host "Installed and started '$TaskName'. It starts automatically at every login."

# The API answers within seconds; the brain may need longer (Ollama, memory sync).
for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Seconds 1
    try {
        $health = Invoke-RestMethod 'http://127.0.0.1:8765/health' -TimeoutSec 2
        if ($health.ready) { Write-Host "Jarvis Core is online." -ForegroundColor Green }
        else { Write-Host "Jarvis Core is starting (waiting for Ollama / syncing memory)." -ForegroundColor Yellow }
        break
    } catch { }
}
if (-not $health) { Write-Host "No answer yet - see logs\jarvis_core.log" -ForegroundColor Yellow }
Write-Host "Logs: $ProjectRoot\logs\jarvis_core.log"
