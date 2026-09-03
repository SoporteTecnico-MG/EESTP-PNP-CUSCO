$ErrorActionPreference = 'Stop'
$projectPath = Split-Path -Parent $MyInvocation.MyCommand.Path
$backupsPath = Join-Path $projectPath 'backups'
$pgDump = 'C:\Program Files\PostgreSQL\17\bin\pg_dump.exe'

if (-not (Test-Path $backupsPath)) {
    New-Item -ItemType Directory -Path $backupsPath | Out-Null
}

# Lee DB_* del .env sin depender de python/decouple
$envFile = Join-Path $projectPath '.env'
$envVars = @{}
Get-Content $envFile | ForEach-Object {
    if ($_ -match '^\s*([A-Z_]+)\s*=\s*(.*)\s*$') {
        $envVars[$matches[1]] = $matches[2]
    }
}

$env:PGPASSWORD = $envVars['DB_PASSWORD']
$timestamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$outFile = Join-Path $backupsPath "controldocentes_$timestamp.dump"

& $pgDump -h $envVars['DB_HOST'] -p $envVars['DB_PORT'] -U $envVars['DB_USER'] -d $envVars['DB_NAME'] -F c -f $outFile

# Conserva solo los ultimos 30 respaldos para no llenar el disco
Get-ChildItem -Path $backupsPath -Filter 'controldocentes_*.dump' |
    Sort-Object LastWriteTime -Descending |
    Select-Object -Skip 30 |
    Remove-Item -Force
