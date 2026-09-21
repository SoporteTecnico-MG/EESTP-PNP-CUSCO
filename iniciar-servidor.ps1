$ErrorActionPreference = 'Stop'
$projectPath = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $projectPath 'venv\Scripts\python.exe'

function Test-PortOpen {
    param([string]$HostName, [int]$Port)
    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $conn = $client.BeginConnect($HostName, $Port, $null, $null)
        if (-not $conn.AsyncWaitHandle.WaitOne(800, $false)) { return $false }
        $client.EndConnect($conn)
        return $true
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

if (Test-PortOpen -HostName '127.0.0.1' -Port 8000) {
    Write-Host "El puerto 8000 ya esta ocupado."
    Write-Host "Verificando si es este mismo sistema (Control Docentes) o algo distinto que quedo colgado..."

    $propios = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -and $_.CommandLine -like "*$projectPath*runserver*" }

    if ($propios) {
        Write-Host ""
        Write-Host "Ya hay un servidor de Control Docentes corriendo (quedo abierto de antes)."
        Write-Host "No hace falta abrir otro. Accede en:"
        Write-Host "  Este equipo:  http://127.0.0.1:8000/admin/"
        Write-Host "  Red local:    http://$((Get-NetIPAddress -AddressFamily IPv4 -InterfaceAlias 'Ethernet' -ErrorAction SilentlyContinue).IPAddress):8000/admin/"
        exit 0
    } else {
        Write-Host ""
        Write-Host "El puerto 8000 lo esta usando OTRO programa (no Control Docentes)."
        Write-Host "Cierra ese programa o avisa para revisarlo - no se puede arrancar el servidor mientras tanto."
        exit 1
    }
}

Write-Host "Iniciando el servidor de Control Docentes..."
Write-Host "No cierres esta ventana mientras uses el sistema."
Write-Host ""
Write-Host "Accede desde este mismo equipo en: http://127.0.0.1:8000/admin/"
$lan = (Get-NetIPAddress -AddressFamily IPv4 -InterfaceAlias 'Ethernet' -ErrorAction SilentlyContinue).IPAddress
if ($lan) {
    Write-Host "Accede desde otra computadora de la red en: http://$($lan):8000/admin/"
}
Write-Host ""

Set-Location $projectPath
& $python manage.py runserver 0.0.0.0:8000
