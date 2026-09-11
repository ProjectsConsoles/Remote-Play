@echo off
REM ============================================================
REM  probar_modo_crudo.bat - atajo de un doble clic
REM ============================================================
REM  Arranca el servidor normal pero pidiendole a la capturadora
REM  video SIN COMPRIMIR a 720x480 en vez de MJPEG a 720p.
REM
REM  Es exactamente lo mismo que abrir una consola y escribir
REM  "start_server_stream.bat crudo"; existe solo para no tener
REM  que editar nada ni abrir la consola a mano.
REM
REM  Para volver a lo normal: cerrar esto y abrir
REM  start_server_stream.bat como siempre. No hay nada que
REM  revertir - este archivo no toca la configuracion.
REM
REM  El por que de la prueba y como leer el resultado estan
REM  explicados arriba de todo en start_server_stream.bat, en el
REM  bloque "PERILLA: modo de captura".
REM ============================================================

call "%~dp0start_server_stream.bat" crudo
