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

# Si esta tarea corre a las 23:00 en punto, el dia de hoy ya termino (la
# ultima hora pedagogica es 18:10) y se puede cerrar directamente. Pero si
# la PC estuvo apagada anoche, Task Scheduler la ejecuta recien cuando se
# prende de nuevo (a veces en la manana siguiente) - en ese caso NO hay que
# cerrar "hoy" (las clases del dia todavia no pasan), sino los dias
# anteriores que se saltaron. Por eso: antes de las 20:00 se cierra hasta
# AYER; despues de las 20:00 (el caso normal) se cierra hasta HOY. En
# ambos casos se cubren los ultimos 14 dias para que, si la PC estuvo
# apagada varios dias seguidos, se recuperen todos de una vez (cerrar_dia
# es seguro de repetir: no toca lo ya corregido a mano).
$ahora = Get-Date
if ($ahora.Hour -ge 20) {
    $hasta = $ahora.Date
} else {
    $hasta = $ahora.Date.AddDays(-1)
}
$desde = $hasta.AddDays(-13)

& $python manage.py cerrar_dia --desde $desde.ToString('dd/MM/yyyy') --hasta $hasta.ToString('dd/MM/yyyy') 2>&1 |
    Out-File -FilePath $logFile -Append -Encoding utf8
