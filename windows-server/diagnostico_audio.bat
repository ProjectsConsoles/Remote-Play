@echo off
REM ============================================================
REM  Diagnostico del AUDIO de la capturadora (lado PC)
REM ============================================================
REM  Se hizo el 2026-08-29 porque Shadow of the Colossus HD se oye
REM  con interferencia mientras que los otros dos juegos se oyen
REM  limpios, con EXACTAMENTE la misma cadena de captura/encode/red.
REM
REM  Que ya quedo descartado antes de escribir esto: el log del Deck
REM  (~/ps3rp_client.log) de esa sesion NO tiene ni un error de audio
REM  (ni "circular buffer overrun", ni errores de AAC) - solo 5
REM  errores de video en toda la corrida. Si el ruido lo metiera la
REM  red o el encode AAC, ahi habria rastro. No lo hay: el audio ya
REM  le llega sucio a ffmpeg desde la capturadora.
REM
REM  Y si el ruido depende del JUEGO y no del aparato, la sospecha
REM  numero uno es el FORMATO que el PS3 manda por HDMI. La PS3
REM  cambia de formato segun lo que pida el juego: los que salen en
REM  PCM estereo se oyen bien, y uno que pida Dolby Digital 5.1 (o
REM  LPCM de 6 canales) manda por HDMI algo que esta capturadora no
REM  sabe interpretar - lo entrega como si fueran muestras PCM y eso
REM  se oye como ruido/interferencia encima (o debajo) del sonido.
REM
REM  Doble clic CON EL JUEGO CORRIENDO Y SONANDO. Copiar toda la salida.
REM ============================================================

set FFMPEG=%~dp0ffmpeg-9.0.1-full_build\bin\ffmpeg.exe
set FFPLAY=%~dp0ffmpeg-9.0.1-full_build\bin\ffplay.exe
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

if not defined AUDIO_DEV (
  echo.
  echo  ERROR: no se encontro la interfaz de audio de la capturadora.
  echo  Corre diagnostico_captura.bat para ver que ofrece Windows.
  echo.
  pause
  exit /b 1
)
echo  Interfaz de audio detectada: %AUDIO_DEV%
set "DEV=audio=%AUDIO_DEV%"

echo.
echo ============================================================
echo  1) Que formatos ofrece la interfaz de audio digital
echo ============================================================
echo  Mirar "ch=" (canales) y "min s=/max s=" (frecuencia). Si la
echo  capturadora solo ofrece ch=2 y el juego manda 5.1, ahi esta.
echo.
"%FFMPEG%" -hide_banner -list_options true -f dshow -i "%DEV%" 2>&1

echo.
echo ============================================================
echo  2) Grabar 10 segundos de SOLO audio a un .wav
echo ============================================================
echo  Sale en captura_audio.wav, junto a este .bat. Se graba SIN
echo  comprimir (PCM), o sea tal cual entra: si este archivo ya se
echo  oye con interferencia, el problema esta ANTES del AAC y antes
echo  de la red - es el PS3 o la capturadora, y no hay perilla del
echo  lado del Deck que lo arregle.
echo.
"%FFMPEG%" -hide_banner -y -f dshow -audio_buffer_size 50 -i "%DEV%" -t 10 -c:a pcm_s16le "%~dp0captura_audio.wav"

echo.
echo ============================================================
echo  3) Escuchar la capturadora EN VIVO (sin red, sin encode)
echo ============================================================
echo  Se abre una ventanita con el medidor. Cerrala (o Ctrl+C) para
echo  terminar. Es la misma prueba que la 2 pero al oido.
echo.
"%FFPLAY%" -hide_banner -nodisp -f dshow -audio_buffer_size 50 -i "%DEV%"

echo.
echo ============================================================
echo  SI SE OYE SUCIO AQUI: cambiar el formato en el propio PS3.
echo    Ajustes -^> Ajustes de sonido -^> Ajustes de salida de audio
echo    -^> HDMI -^> Manual -^> dejar marcado SOLO
REM  (El "^>" es como el .bat escupe una flecha ">" sin redirigir.)
echo    "Linear PCM 2 canales 48 kHz" y DESMARCAR Dolby Digital 5.1
echo    y DTS. Asi el juego se ve obligado a mezclar a estereo el
echo    PS3 mismo, que es lo que esta capturadora si entiende.
echo  SI AQUI SE OYE LIMPIO: entonces el ruido lo mete la cadena de
echo    ffmpeg (subir -b:a de 96k a 128k en start_server_stream.bat)
echo    o la red, y hay que volver a mirar el log del Deck.
echo ============================================================
pause
