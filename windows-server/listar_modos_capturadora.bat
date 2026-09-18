@echo off
REM ============================================================
REM  listar_modos_capturadora.bat
REM ============================================================
REM  Muestra TODAS las resoluciones/formatos que la capturadora HDMI
REM  conectada dice soportar (MJPEG y crudo/yuyv422), tal como los ve
REM  Windows. Util cuando se cambia de capturadora (2026-09-17): cada
REM  chip tiene un techo distinto de fps en modo sin comprimir - antes
REM  de asumir que un modo "crudo" sirve o no, revisa aca primero.
REM
REM  Doble clic. Pide el nombre EXACTO del dispositivo de video (el
REM  mismo que muestra detectar_dispositivos.ps1 o la ventana del
REM  servidor al arrancar).
REM ============================================================
setlocal
set /p DISPOSITIVO=Nombre exacto del dispositivo de video (ej. Hagibis):
"%~dp0ffmpeg-9.0.1-full_build\bin\ffmpeg.exe" -hide_banner -f dshow -list_options true -i video="%DISPOSITIVO%"
pause
