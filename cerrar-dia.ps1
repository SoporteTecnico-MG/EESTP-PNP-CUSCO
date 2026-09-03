$ErrorActionPreference = 'Stop'
$projectPath = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $projectPath 'venv\Scripts\python.exe'
$logsPath = Join-Path $projectPath 'logs'

if (-not (Test-Path $logsPath)) {
    New-Item -ItemType Directory -Path $logsPath | Out-Null
}

$logFile = Join-Path $logsPath 'cerrar-dia.log'
$timestamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
Add-Content -Path $logFile -Value "--- $timestamp ---"

Set-Location $projectPath
& $python manage.py cerrar_dia 2>&1 | Out-File -FilePath $logFile -Append -Encoding utf8
