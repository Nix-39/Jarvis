<#
.SYNOPSIS
    Registers the Jarvis background scheduler to start automatically at login,
    without a window, with normal user rights (no administrator privileges).

.EXAMPLE
    .\scripts\install_scheduler.ps1              # install or update, and start now
    .\scripts\install_scheduler.ps1 -Uninstall   # stop and remove
#>
param([switch]$Uninstall)

$ErrorActionPreference = 'Stop'
$TaskName    = 'Jarvis Scheduler'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PythonW     = Join-Path $ProjectRoot '.venv\Scripts\pythonw.exe'
$User        = "$env:USERDOMAIN\$env:USERNAME"

if ($Uninstall) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Removed '$TaskName'."
    return
}

if (-not (Test-Path $PythonW)) {
    throw "Could not find $PythonW - create the virtual environment first."
}

$action    = New-ScheduledTaskAction -Execute $PythonW -Argument '-m core.scheduler' -WorkingDirectory $ProjectRoot
$trigger   = New-ScheduledTaskTrigger -AtLogOn -User $User
$principal = New-ScheduledTaskPrincipal -UserId $User -LogonType Interactive -RunLevel Limited
$settings  = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
                -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew `
                -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal `
    -Settings $settings -Description 'Jarvis background scheduler - delivers reminders.' -Force | Out-Null

Start-ScheduledTask -TaskName $TaskName
Write-Host "Installed and started '$TaskName'. It starts automatically at every login."
Write-Host "Logs: $ProjectRoot\logs\jarvis_scheduler.log"
