@echo off
setlocal
REM ============================================================
REM  listar_modos.bat - lista TODOS los modos que ofrece la
REM  capturadora (resolucion, fps y formato de pixel).
REM
REM  Doble clic y listo. Deja el resultado en
REM  listar_modos_log.txt, junto a este archivo, para poder
REM  leerlo por SMB desde la Deck sin dictarlo a mano.
REM
REM  PARA QUE SIRVE: la pregunta abierta es si esta capturadora
REM  ofrece algun modo SIN COMPRIMIR (yuyv422) que sostenga 60
REM  fps. Lo ya medido (anotado en start_server_stream.bat) es
REM  que sin comprimir tope a 10 fps en 1080p y 25 fps en 720p,
REM  pero nunca se miraron las resoluciones mas chicas.
REM
REM  POR QUE NO ALCANZA CON medir_latencia.bat: su v3 dejo de
REM  listar los modos (lo hacian la v1/v2) y ademas TRUNCA su
REM  log en cada corrida con ">", asi que el listado viejo se
REM  perdio.
REM
REM  NOTA DE FFMPEG: con "-list_options true" ffmpeg SIEMPRE
REM  termina con "Immediate exit requested" y codigo de error.
REM  ES NORMAL - asi es como dshow entrega el listado, no es
REM  una falla. Por eso este .bat no revisa el ERRORLEVEL.
REM ============================================================

set FFMPEG=%~dp0ffmpeg-9.0.1-full_build\bin\ffmpeg.exe
set LOG=%~dp0listar_modos_log.txt

if not exist "%FFMPEG%" goto falta_ffmpeg

REM  El nombre del dispositivo NO va clavado: Windows lo renombra
REM  al cambiar de puerto USB. Se busca por pedazo, igual que en
REM  start_server_stream.bat, reusando el mismo detector.
set "F_VIDEO=%TEMP%\ps3rp_video.txt"
set "F_LISTA=%TEMP%\ps3rp_dshow.txt"
set "VIDEO_DEV="

echo.
echo  Buscando la capturadora...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0detectar_dispositivos.ps1" >nul 2>&1
if exist "%F_VIDEO%" set /p VIDEO_DEV=<"%F_VIDEO%"

if not defined VIDEO_DEV goto sin_video

echo  Capturadora: %VIDEO_DEV%
echo.
echo  Listando modos (tarda unos segundos, es normal)...

echo === listar_modos %DATE% %TIME% === > "%LOG%"
echo Dispositivo: %VIDEO_DEV% >> "%LOG%"
echo. >> "%LOG%"
"%FFMPEG%" -hide_banner -f dshow -list_options true -i video="%VIDEO_DEV%" >> "%LOG%" 2>&1

echo.
echo ============================================================
type "%LOG%"
echo ============================================================
echo.
echo  Guardado en: %LOG%
echo.
echo  Recordatorio: el "Immediate exit requested" del final es
echo  NORMAL, no es un error.
echo.
pause
exit /b 0

:sin_video
echo.
echo  ERROR: no encontre la capturadora entre los dispositivos de
echo  video. Esto es lo que si vio ffmpeg:
echo.
if exist "%F_LISTA%" type "%F_LISTA%"
echo.
echo  Revisa que la capturadora este conectada y que
echo  detectar_dispositivos.ps1 este en esta misma carpeta.
echo.
pause
exit /b 1

:falta_ffmpeg
echo.
echo  ERROR: no encontre ffmpeg.exe en:
echo    %FFMPEG%
echo.
echo  Deberia estar junto a ffplay.exe, en la carpeta
echo  ffmpeg-9.0.1-full_build\bin
echo.
pause
exit /b 1
