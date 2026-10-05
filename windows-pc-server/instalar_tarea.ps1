# Instala el servidor de PC (pc_server.py) en esta PC: librerias de Python, firewall y la tarea programada
# que lo arranca EN LA SESION DEL USUARIO al iniciar sesion (ddagrab no captura desde SSH / sesion 0).
# Correr como administrador desde la carpeta donde esta pc_server.py. Se puede repetir sin problema.
# Requisitos ya instalados: Python 3.12 (python.org, para todos los usuarios), ffmpeg (winget Gyan.FFmpeg)
# y el driver ViGEmBus (control de Xbox virtual).

$ErrorActionPreference = 'Stop'
$carpeta = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = 'C:\Program Files\Python312\python.exe'
$pythonw = 'C:\Program Files\Python312\pythonw.exe'

& $python -m pip install --quiet --disable-pip-version-check vgamepad pyaudiowpatch pycaw pystray pillow
if ($LASTEXITCODE -ne 0) { throw 'fallo pip install' }

# Firewall: la tableta le habla por UDP 9200 (config) y 9000 (mando). Solo red local.
foreach ($p in 9200, 9000) {
    Remove-NetFirewallRule -Name "PS3RP-PC-$p" -ErrorAction SilentlyContinue
    New-NetFirewallRule -Name "PS3RP-PC-$p" -DisplayName "PS3RP servidor de PC (UDP $p)" -Direction Inbound `
        -Protocol UDP -LocalPort $p -RemoteAddress LocalSubnet -Action Allow -Profile Any | Out-Null
}

# Lanzador unico (2026-10-05): "Iniciar Servidor Remote Play.exe" (windows-server/server_launcher.py) junto a
# este archivo o en la carpeta de arriba. Si esta, la tarea y el acceso directo lo usan a EL: arranca el tipo de
# servidor guardado en tipo_servidor.txt (consolas o PC) y se cambia desde la ventana del servidor. Si no esta,
# todo queda como antes (pc_server.py directo).
$lanzador = @("$carpeta\Iniciar Servidor Remote Play.exe", "$(Split-Path -Parent $carpeta)\Iniciar Servidor Remote Play.exe") |
    Where-Object { Test-Path $_ } | Select-Object -First 1
if ($lanzador) {
    $tipo = Join-Path (Split-Path -Parent $lanzador) 'tipo_servidor.txt'
    if (-not (Test-Path $tipo)) { Set-Content -Path $tipo -Value 'pc' -Encoding ASCII }   # esta PC: juegos
}

# Tarea: al iniciar sesion del usuario, sin ventana, reiniciandose si se cae.
$usuario = (Get-CimInstance Win32_ComputerSystem).UserName
if (-not $usuario) { $usuario = "$env:USERDOMAIN\$env:USERNAME" }
if ($lanzador) {
    $accion = New-ScheduledTaskAction -Execute $lanzador -Argument '--inicio' -WorkingDirectory (Split-Path -Parent $lanzador)
} else {
    $accion = New-ScheduledTaskAction -Execute $pythonw -Argument "`"$carpeta\pc_server.py`"" -WorkingDirectory $carpeta
}
$disparo = New-ScheduledTaskTrigger -AtLogOn -User $usuario
$ajustes = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 99 -RestartInterval (New-TimeSpan -Minutes 1)
$quien = New-ScheduledTaskPrincipal -UserId $usuario -LogonType Interactive -RunLevel Highest
Register-ScheduledTask -TaskName 'PS3RP PC Server' -Action $accion -Trigger $disparo -Settings $ajustes `
    -Principal $quien -Force | Out-Null

# Acceso directo en el escritorio: arranca el servidor o, si ya corre, muestra su ventana
$escritorio = [Environment]::GetFolderPath('Desktop')
$acceso = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $escritorio 'Remote Play - Servidor de PC.lnk'))
if ($lanzador) {
    $acceso.TargetPath = $lanzador
    $acceso.Arguments = ''
    $acceso.WorkingDirectory = Split-Path -Parent $lanzador
} else {
    $acceso.TargetPath = $pythonw
    $acceso.Arguments = "`"$carpeta\abrir_servidor.pyw`""
    $acceso.WorkingDirectory = $carpeta
}
$acceso.IconLocation = "$carpeta\icono.ico,0"
$acceso.Description = 'Inicia el servidor de PC de Remote Play o muestra su ventana'
$acceso.Save()

# Arrancarlo ya (si habia uno corriendo, se reemplaza)
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" | Where-Object { $_.CommandLine -like '*pc_server.py*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
# y su ffmpeg: no muere con el y seguiria mandando video a la tableta (el servidor nuevo tambien lo revisa)
Get-CimInstance Win32_Process -Filter "Name='ffmpeg.exe'" | Where-Object { $_.CommandLine -like '*ffmpeg_progreso.log*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
# sin esta pausa Windows todavia da la tarea por "en ejecucion" e ignora el arranque (quedaba sin servidor)
Start-Sleep -Seconds 2
Start-ScheduledTask -TaskName 'PS3RP PC Server'
Start-Sleep -Seconds 3
$vivo = Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" | Where-Object { $_.CommandLine -like '*pc_server.py*' }
"Tarea instalada para $usuario. Servidor corriendo: $([bool]$vivo)"
