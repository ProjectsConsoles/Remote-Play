@echo off
REM ============================================================
REM  iniciar_servidor.bat - abre la interfaz grafica del servidor
REM ============================================================
REM  Doble clic aqui. Sale una ventanita que pide la IP de la Deck
REM  (con las ultimas usadas en una lista) y la resolucion, y ya.
REM
REM  El servidor queda corriendo OCULTO, sin ventana negra. Se
REM  puede cerrar la ventanita y sigue transmitiendo. Para
REM  detenerlo o cambiar de resolucion, abrir esto de nuevo: al
REM  iniciar mata sola la instancia anterior.
REM
REM  El "start" con ventana oculta evita que quede una consola
REM  vacia detras mientras la interfaz esta abierta.
REM
REM  Si algo falla y no se ve el error, abrir start_server_stream.bat
REM  directo: ese si muestra la consola con todo lo que pasa.
REM ============================================================

start "" powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0start_server_gui.ps1"
