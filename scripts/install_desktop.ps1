<#
.SYNOPSIS
    Installs the Yggdrasil desktop app: shortcuts on the desktop and in the
    Start menu with the Yggdrasil icon, and autostart at login (hidden in the
    system tray). Normal user rights - no administrator needed.

    The shortcuts carry the app id "Yggdrasil.Desktop" (the same id the app
    gives its window). That is how Windows knows the window belongs to the
    shortcut: pinning it to the taskbar then keeps the Yggdrasil icon and
    starts the app, instead of showing the Python icon.

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
$StartMenu   = Join-Path ([Environment]::GetFolderPath('Programs')) 'Yggdrasil.lnk'
$AppId       = 'Yggdrasil.Desktop'   # must match clients/desktop.py
$User        = "$env:USERDOMAIN\$env:USERNAME"

if ($Uninstall) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Remove-Item $Shortcut, $StartMenu -ErrorAction SilentlyContinue
    Write-Host "Removed '$TaskName' and the shortcuts."
    return
}

if (-not (Test-Path $PythonW)) { throw "Could not find $PythonW - create the virtual environment first." }

# Shortcuts with an AppUserModelID. WScript.Shell cannot set that property,
# so a small C# helper writes the shortcut through the Windows shell API.
if (-not ('YggShortcut' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;
using System.Text;

public static class YggShortcut {
    [ComImport, Guid("00021401-0000-0000-C000-000000000046")]
    private class CShellLink { }

    [ComImport, InterfaceType(ComInterfaceType.InterfaceIsIUnknown), Guid("000214F9-0000-0000-C000-000000000046")]
    private interface IShellLinkW {
        void GetPath([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder file, int max, IntPtr data, uint flags);
        void GetIDList(out IntPtr pidl);
        void SetIDList(IntPtr pidl);
        void GetDescription([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder name, int max);
        void SetDescription([MarshalAs(UnmanagedType.LPWStr)] string name);
        void GetWorkingDirectory([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder dir, int max);
        void SetWorkingDirectory([MarshalAs(UnmanagedType.LPWStr)] string dir);
        void GetArguments([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder args, int max);
        void SetArguments([MarshalAs(UnmanagedType.LPWStr)] string args);
        void GetHotkey(out short key);
        void SetHotkey(short key);
        void GetShowCmd(out int cmd);
        void SetShowCmd(int cmd);
        void GetIconLocation([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder path, int max, out int index);
        void SetIconLocation([MarshalAs(UnmanagedType.LPWStr)] string path, int index);
        void SetRelativePath([MarshalAs(UnmanagedType.LPWStr)] string path, uint reserved);
        void Resolve(IntPtr hwnd, uint flags);
        void SetPath([MarshalAs(UnmanagedType.LPWStr)] string file);
    }

    [StructLayout(LayoutKind.Sequential, Pack = 4)]
    private struct PropertyKey { public Guid FormatId; public uint PropertyId; }

    [StructLayout(LayoutKind.Sequential)]
    private struct PropVariant { public ushort vt; public ushort r1; public ushort r2; public ushort r3; public IntPtr p; public IntPtr p2; }

    [ComImport, InterfaceType(ComInterfaceType.InterfaceIsIUnknown), Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99")]
    private interface IPropertyStore {
        void GetCount(out uint count);
        void GetAt(uint index, out PropertyKey key);
        void GetValue(ref PropertyKey key, out PropVariant value);
        void SetValue(ref PropertyKey key, ref PropVariant value);
        void Commit();
    }

    public static void Save(string path, string target, string args, string workDir, string icon, string description, string appId) {
        IShellLinkW link = (IShellLinkW)new CShellLink();
        link.SetPath(target);
        link.SetArguments(args);
        link.SetWorkingDirectory(workDir);
        link.SetIconLocation(icon, 0);
        link.SetDescription(description);

        PropertyKey key = new PropertyKey();
        key.FormatId = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3");   // PKEY_AppUserModel_ID
        key.PropertyId = 5;
        PropVariant value = new PropVariant();
        value.vt = 31;                                                    // VT_LPWSTR
        value.p = Marshal.StringToCoTaskMemUni(appId);
        try {
            IPropertyStore store = (IPropertyStore)link;
            store.SetValue(ref key, ref value);
            store.Commit();
        } finally {
            Marshal.FreeCoTaskMem(value.p);
        }
        ((IPersistFile)link).Save(path, true);
    }
}
'@
}

# Desktop + Start menu shortcut (opens the window, or brings an already running one forward)
foreach ($path in @($Shortcut, $StartMenu)) {
    try {
        [YggShortcut]::Save($path, $PythonW, '-m clients.desktop', $ProjectRoot, $Icon, 'Yggdrasil', $AppId)
        Write-Host "Created shortcut: $path"
    } catch {
        # Fallback: a plain shortcut (works, but a pinned taskbar icon may show Python's icon)
        Write-Warning "Could not set the app id on $path ($($_.Exception.Message)) - creating a plain shortcut."
        $lnk = (New-Object -ComObject WScript.Shell).CreateShortcut($path)
        $lnk.TargetPath = $PythonW; $lnk.Arguments = '-m clients.desktop'; $lnk.WorkingDirectory = $ProjectRoot
        $lnk.IconLocation = "$Icon,0"; $lnk.Description = 'Yggdrasil'; $lnk.Save()
    }
}

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
