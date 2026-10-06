<#
.SYNOPSIS
    Checks that everything Jarvis depends on starts automatically at login,
    and whether each part is running right now.

.EXAMPLE
    .\scripts\check_autostart.ps1
#>

function Report($Name, $Good, $Detail) {
    if ($Good) { Write-Host "[OK]   $Name" -ForegroundColor Green -NoNewline }
    else       { Write-Host "[FAIL] $Name" -ForegroundColor Red -NoNewline }
    if ($Detail) { Write-Host " - $Detail" } else { Write-Host "" }
}

Write-Host ""
Write-Host "== Autostart ==" -ForegroundColor Cyan

# Ollama: shortcut in a Startup folder or an entry in the Run registry key
$startupDirs = @([Environment]::GetFolderPath('Startup'), [Environment]::GetFolderPath('CommonStartup'))
$ollamaLink  = $startupDirs | ForEach-Object { Get-ChildItem $_ -Filter '*ollama*' -ErrorAction SilentlyContinue }
$runKey      = Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' -ErrorAction SilentlyContinue
$ollamaRun   = $runKey.PSObject.Properties | Where-Object { $_.Name -like '*ollama*' }
$ollamaWhere = if ($ollamaLink) { "shortcut in Startup folder" } elseif ($ollamaRun) { "registry Run key" } else { "no autostart entry found" }
Report 'Ollama starts at login' ([bool]($ollamaLink -or $ollamaRun)) $ollamaWhere

# Docker Desktop: "Start Docker Desktop when you sign in"
$dockerAuto = $false
foreach ($file in "$env:APPDATA\Docker\settings-store.json", "$env:APPDATA\Docker\settings.json") {
    if (Test-Path $file) {
        $json = Get-Content $file -Raw | ConvertFrom-Json
        if ($json.AutoStart -eq $true -or $json.autoStart -eq $true) { $dockerAuto = $true }
    }
}
$dockerHint = if ($dockerAuto) { $null } else { 'Docker Desktop > Settings > General > Start Docker Desktop when you sign in' }
Report 'Docker Desktop starts at login' $dockerAuto $dockerHint

# SearXNG container restart policy
$policy = docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' jarvis-searxng 2>$null
Report 'SearXNG container restarts automatically' ($policy -in @('unless-stopped', 'always')) "restart policy: $policy"

# Jarvis Core task (replaces the old 'Jarvis Scheduler' task)
$task = Get-ScheduledTask -TaskName 'Jarvis Core' -ErrorAction SilentlyContinue
$taskDetail = if ($task) { "state: $($task.State)" } else { 'run .\scripts\install_core.ps1' }
Report 'Jarvis Core task registered' ([bool]$task) $taskDetail

$oldTask = Get-ScheduledTask -TaskName 'Jarvis Scheduler' -ErrorAction SilentlyContinue
if ($oldTask) { Report 'Old Jarvis Scheduler task removed' $false 'run .\scripts\install_core.ps1' }

# Telegram (optional): token and chat id present in .env (values are not shown)
$envFile = Join-Path (Split-Path -Parent $PSScriptRoot) '.env'
$hasToken = [bool](Select-String -Path $envFile -Pattern '^\s*TELEGRAM_BOT_TOKEN\s*=\s*\S' -Quiet -ErrorAction SilentlyContinue)
$hasChat  = [bool](Select-String -Path $envFile -Pattern '^\s*TELEGRAM_CHAT_ID\s*=\s*\S' -Quiet -ErrorAction SilentlyContinue)
$tgDetail = if ($hasToken -and $hasChat) { 'token and chat id set' } elseif ($hasToken) { 'chat id missing - send /start to the bot' } else { 'optional - no bot token in .env' }
Report 'Telegram configured' ($hasToken -and $hasChat) $tgDetail

Write-Host ""
Write-Host "== Running right now ==" -ForegroundColor Cyan

try {
    $version = Invoke-RestMethod 'http://127.0.0.1:11434/api/version' -TimeoutSec 3
    Report 'Ollama responds' $true "version $($version.version)"
} catch { Report 'Ollama responds' $false 'not running' }

try {
    Invoke-WebRequest 'http://127.0.0.1:8888/healthz' -TimeoutSec 3 -UseBasicParsing | Out-Null
    Report 'SearXNG responds' $true
} catch { Report 'SearXNG responds' $false 'start Docker Desktop' }

$proc = Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" | Where-Object { $_.CommandLine -like '*core.jarvis_core*' }
Report 'Jarvis Core process running' ([bool]$proc)

try {
    $health = Invoke-RestMethod 'http://127.0.0.1:8765/health' -TimeoutSec 3
    $state = if ($health.ready) { 'online' } else { 'starting (waiting for Ollama / syncing memory)' }
    Report 'Jarvis Core API responds (127.0.0.1 only)' $true $state
} catch { Report 'Jarvis Core API responds (127.0.0.1 only)' $false 'see logs\jarvis_core.log' }
Write-Host ""
