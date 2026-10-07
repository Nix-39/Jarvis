<#
.SYNOPSIS
    Installs the Yggdrasil desktop app: a desktop shortcut with the Yggdrasil
    icon, and autostart at login (hidden in the system tray).
    Normal user rights - no administrator needed.

.EXAMPLE
    .\scripts\install_desktop.ps1              # install or update
    .\scripts\install_desktop.ps1 -Uninstall   # remove shortcut and autostart
#>
param([switch]$Uninstall)

$ErrorActionPreference = 'Stop'
$TaskName    = 'Yggdrasil Desktop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PythonW     = Join-Path $ProjectRoot '.venv\Scripts\pythonw.exe'
$Icon        = Join-Path $ProjectRoot 'ui\assets\yggdrasil.ico'
$Shortcut    = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Yggdrasil.lnk'
$User        = "$env:USERDOMAIN\$env:USERNAME"

if ($Uninstall) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Remove-Item $Shortcut -ErrorAction SilentlyContinue
    Write-Host "Removed '$TaskName' and the desktop shortcut."
    return
}

if (-not (Test-Path $PythonW)) { throw "Could not find $PythonW - create the virtual environment first." }

# Desktop shortcut (opens the window, or brings an already running one forward)
$shell = New-Object -ComObject WScript.Shell
$lnk = $shell.CreateShortcut($Shortcut)
$lnk.TargetPath       = $PythonW
$lnk.Arguments        = '-m clients.desktop'
$lnk.WorkingDirectory = $ProjectRoot
$lnk.IconLocation     = "$Icon,0"
$lnk.Description      = 'Yggdrasil'
$lnk.Save()
Write-Host "Created desktop shortcut: $Shortcut"

# Autostart at login, hidden in the tray (after Jarvis Core has had a head start)
$action    = New-ScheduledTaskAction -Execute $PythonW -Argument '-m clients.desktop --hidden' -WorkingDirectory $ProjectRoot
$trigger   = New-ScheduledTaskTrigger -AtLogOn -User $User
$trigger.Delay = 'PT40S'
$principal = New-ScheduledTaskPrincipal -UserId $User -LogonType Interactive -RunLevel Limited
$settings  = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
                -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal `
    -Settings $settings -Description 'Yggdrasil desktop app (tray icon, Ctrl+Alt+J).' -Force | Out-Null
Write-Host "Registered '$TaskName' - starts hidden in the tray at every login."
Write-Host "Open it now: double-click the Yggdrasil icon on the desktop (or press Ctrl+Alt+J once it runs)."
