@echo off
REM ============================================================
REM  Medir el PISO de latencia de la capturadora (lado PC)
REM ============================================================
REM  Se hizo el 2026-08-29 porque el pipeline completo ya funciona
REM  pero queda un lag de ~200-300ms boton->pantalla en la Deck.
REM
REM  La pregunta que responde: de esos 200-300ms, cuantos son de la
REM  CAPTURADORA (irreparables por software) y cuantos se agregan
REM  despues (encode + wifi + Deck)?
REM
REM  HISTORIA DE ESTE ARCHIVO (para no repetir los errores):
REM   - v1 corria ffplay con "-loglevel warning", que se traga hasta
REM     los errores fatales de apertura del dispositivo: si la
REM     capturadora no se podia abrir, moria mudo y parecia que "no
REM     pasaba nada". Ahora se usa -loglevel info y se guarda todo en
REM     medir_latencia_log.txt (al lado de este .bat).
REM   - v2 agrego un listado de modos paginado con "| more". El
REM     paginador se queda esperando teclas y el script NUNCA llegaba
REM     a abrir ffplay - otra vez "no sale nada". Se quito el more, y
REM     de paso el listado entero: ese dato YA se obtuvo el
REM     2026-08-29 y quedo anotado abajo. Nada de paginadores aqui.
REM
REM  RESULTADO YA OBTENIDO DEL LISTADO DE MODOS (2026-08-29):
REM     mjpeg    1280x720  hasta 60 fps   <- se usa este
REM     mjpeg    1920x1080 hasta 60 fps
REM     yuyv422  1280x720  hasta 25 fps   (sin comprimir = muy lento)
REM     yuyv422  1920x1080 hasta 10 fps
REM   O sea: la capturadora SI da 720p60 nativo (por eso
REM   start_server_stream.bat ya no reescala con la CPU), y sin
REM   comprimir no alcanza 60 fps a ninguna resolucion util, asi que
REM   MJPEG es obligatorio aunque su compresion sea justo lo que
REM   pone el piso de latencia.
REM ============================================================

set FFPLAY=%~dp0ffmpeg-9.0.1-full_build\bin\ffplay.exe
set LOG=%~dp0medir_latencia_log.txt
set DEV=USB Video

if not exist "%FFPLAY%" goto falta_ffplay

echo.
echo ============================================================
echo  Vista previa local: sin red, sin encode, sin audio
echo ============================================================
echo  ANTES DE SEGUIR: cierra start_server_stream.bat si esta
echo  corriendo. Windows deja abrir la capturadora a UN solo
echo  programa a la vez; si el servidor la tiene tomada, esta
echo  prueba no puede abrirla.
echo.
echo  Se va a abrir una ventana de 960x540 con lo que ve la
echo  capturadora, con la latencia mas baja posible. Esto es el
echo  PISO: la Deck NUNCA va a ir mas rapido que esta ventana.
echo.
echo  QUE HACER:
echo    - Mueve el cursor del menu de la PS3.
echo    - Compara ESTA ventana contra la tele donde esta la PS3.
echo    - Fijate si se siente instantanea o ya se nota el retraso.
echo.
echo  COMO SE LEE:
echo    - Si aqui YA se siente ~200ms, el cuello de botella es la
echo      capturadora MJPEG por USB2 y ningun ajuste de ffmpeg lo
echo      va a arreglar (toca MS2130 USB3 o Elgato Cam Link 4K).
echo    - Si aqui se siente casi instantanea, el retraso se mete
echo      en encode+wifi+Deck y SI se puede bajar por software.
echo.
echo  Si no ves la ventana, revisa la barra de tareas: puede
echo  abrirse detras de esta consola. Tarda un par de segundos.
echo.
echo  Para terminar: CIERRA LA VENTANA de video (no Ctrl+C aqui).
echo.
pause

echo === medir_latencia %DATE% %TIME% === > "%LOG%"
echo.
echo  Abriendo 1280x720 @60 mjpeg (el modo nativo de la capturadora)...
echo.
"%FFPLAY%" -hide_banner -loglevel info -an -x 960 -y 540 ^
  -window_title "PISO DE LATENCIA - capturadora sola" ^
  -fflags nobuffer -flags low_delay -framedrop ^
  -f dshow -video_size 1280x720 -framerate 60 -vcodec mjpeg ^
  -i video="%DEV%" 2>> "%LOG%"

echo.
echo ============================================================
echo  Salida de ffplay
echo ============================================================
type "%LOG%"
echo.
echo ============================================================
echo  Si la ventana SI se abrio: dime tu impresion del retraso.
echo  Si NO se abrio: el detalle esta arriba y en
echo  medir_latencia_log.txt, junto a este .bat.
echo ============================================================
pause
goto :eof

:falta_ffplay
echo.
echo  ERROR: no encontre ffplay.exe en:
echo    %FFPLAY%
echo  Deberia estar junto a ffmpeg.exe, en la carpeta
echo  ffmpeg-9.0.1-full_build\bin (verificado ahi el 2026-08-29).
echo.
pause
goto :eof
