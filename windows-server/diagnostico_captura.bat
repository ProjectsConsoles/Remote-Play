@echo off
REM ============================================================
REM  Diagnostico de la capturadora HDMI (lado PC)
REM ============================================================
REM  Se hizo el 2026-08-28 porque start_server_stream.bat corria
REM  15 minutos sin errores pero al Deck no le llegaba NI UN
REM  paquete UDP (medido del lado del Deck: 0 paquetes en 10s,
REM  con la IP correcta, ping OK y firewall abierto). Eso apunta
REM  a que ffmpeg esta vivo pero la entrada dshow no le entrega
REM  frames. Esto lo confirma sin tocar el script de produccion.
REM
REM  Doble clic y copiar TODA la salida.
REM ============================================================

set FFMPEG=%~dp0ffmpeg-9.0.1-full_build\bin\ffmpeg.exe

echo.
echo ============================================================
echo  1) Dispositivos DirectShow que ve el sistema
echo ============================================================
echo  (Aqui deben aparecer un dispositivo de video con "USB Video"
echo   en el nombre y uno de audio con "Digital Audio". No hace
echo   falta que el nombre sea identico al de siempre: desde el
echo   2026-08-29 el script de produccion los busca por pedazo del
echo   nombre, porque Windows les mete un "2- " adelante cuando la
echo   capturadora cambia de puerto USB.)
echo.
"%FFMPEG%" -hide_banner -list_devices true -f dshow -i dummy 2>&1

echo.
echo ============================================================
echo  2) Captura de prueba de 5 segundos (no manda nada por red)
echo ============================================================
echo  Lo que importa es la linea de estado: frame= y fps=.
echo    - frame subiendo y fps cerca de 60  -^> la captura esta bien
echo    - frame en 0 o casi                 -^> no hay senal HDMI
echo      (PS3 apagada, cable, o el dispositivo ocupado por otro
echo       programa como OBS o el propio Remote Play)
echo.
REM  El nombre del dispositivo NO va clavado: se lo pide a
REM  detectar_dispositivos.ps1 (al lado de este .bat), igual que
REM  start_server_stream.bat. Windows le cambia el nombre a la
REM  interfaz de audio de la capturadora si se enchufa en otro puerto
REM  USB ("Interfaz de sonido digital (2- USB Digital Audio)"), asi
REM  que buscarlo cada vez es lo unico que no se rompe solo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0detectar_dispositivos.ps1" >nul 2>&1
set "VIDEO_DEV="
set "AUDIO_DEV="
if exist "%TEMP%\ps3rp_video.txt" set /p VIDEO_DEV=<"%TEMP%\ps3rp_video.txt"
if exist "%TEMP%\ps3rp_audio.txt" set /p AUDIO_DEV=<"%TEMP%\ps3rp_audio.txt"

if not defined VIDEO_DEV (
  echo  ERROR: ningun dispositivo de video con "USB Video" en el nombre.
  echo  Mira el listado de arriba.
  pause
  exit /b 1
)
echo  Capturadora de video detectada: %VIDEO_DEV%
echo.
"%FFMPEG%" -hide_banner -f dshow -video_size 1920x1080 -framerate 60 -vcodec mjpeg -i video="%VIDEO_DEV%" -t 5 -f null NUL

echo.
echo ============================================================
echo  Listo. Copia todo lo de arriba y pasalo.
echo ============================================================
pause
