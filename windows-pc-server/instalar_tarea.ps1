# Instala el servidor de PC (pc_server.py) en esta PC: librerias de Python, firewall y la tarea programada
# que lo arranca EN LA SESION DEL USUARIO al iniciar sesion (ddagrab no captura desde SSH / sesion 0).
# Correr como administrador desde la carpeta donde esta pc_server.py. Se puede repetir sin problema.
# Requisitos ya instalados: Python 3.12 (python.org, para todos los usuarios), ffmpeg (winget Gyan.FFmpeg)
# y el driver ViGEmBus (control de Xbox virtual).

$ErrorActionPreference = 'Stop'
$carpeta = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = 'C:\Program Files\Python312\python.exe'
$pythonw = 'C:\Program Files\Python312\pythonw.exe'

& $python -m pip install --quiet --disable-pip-version-check vgamepad pyaudiowpatch
if ($LASTEXITCODE -ne 0) { throw 'fallo pip install' }

# Firewall: la tableta le habla por UDP 9200 (config) y 9000 (mando). Solo red local.
foreach ($p in 9200, 9000) {
    Remove-NetFirewallRule -Name "PS3RP-PC-$p" -ErrorAction SilentlyContinue
    New-NetFirewallRule -Name "PS3RP-PC-$p" -DisplayName "PS3RP servidor de PC (UDP $p)" -Direction Inbound `
        -Protocol UDP -LocalPort $p -RemoteAddress LocalSubnet -Action Allow -Profile Any | Out-Null
}

# Tarea: al iniciar sesion del usuario, sin ventana (pythonw), reiniciandose si se cae.
$usuario = (Get-CimInstance Win32_ComputerSystem).UserName
if (-not $usuario) { $usuario = "$env:USERDOMAIN\$env:USERNAME" }
$accion = New-ScheduledTaskAction -Execute $pythonw -Argument "`"$carpeta\pc_server.py`"" -WorkingDirectory $carpeta
$disparo = New-ScheduledTaskTrigger -AtLogOn -User $usuario
$ajustes = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 99 -RestartInterval (New-TimeSpan -Minutes 1)
$quien = New-ScheduledTaskPrincipal -UserId $usuario -LogonType Interactive -RunLevel Highest
Register-ScheduledTask -TaskName 'PS3RP PC Server' -Action $accion -Trigger $disparo -Settings $ajustes `
    -Principal $quien -Force | Out-Null

# Arrancarlo ya (si habia uno corriendo, se reemplaza)
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" | Where-Object { $_.CommandLine -like '*pc_server.py*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Start-ScheduledTask -TaskName 'PS3RP PC Server'
Start-Sleep -Seconds 3
$vivo = Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" | Where-Object { $_.CommandLine -like '*pc_server.py*' }
"Tarea instalada para $usuario. Servidor corriendo: $([bool]$vivo)"
