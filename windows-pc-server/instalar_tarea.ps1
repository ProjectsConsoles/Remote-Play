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

# Acceso directo en el escritorio: arranca el servidor (por la tarea) o, si ya corre, muestra su ventana
$escritorio = [Environment]::GetFolderPath('Desktop')
$acceso = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $escritorio 'Remote Play - Servidor de PC.lnk'))
$acceso.TargetPath = $pythonw
$acceso.Arguments = "`"$carpeta\abrir_servidor.pyw`""
$acceso.WorkingDirectory = $carpeta
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
