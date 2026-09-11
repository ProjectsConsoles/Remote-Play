@echo off
REM ============================================================
REM  build_launcher.bat - recompila "Iniciar Servidor Remote Play.exe"
REM ============================================================
REM  server_launcher.py se compila con PyInstaller a un .exe --onefile
REM  --windowed (ver los comentarios largos en ese archivo sobre por que
REM  necesita --windowed, CREATE_BREAKAWAY_FROM_JOB y descriptores DEVNULL
REM  explicitos). Este script no existia antes (el .exe se venia
REM  compilando a mano); se agrega ahora sobre todo para que el --icon
REM  quede fijo y no se pierda la proxima vez que haga falta recompilar.
REM
REM  Requiere PyInstaller instalado en el Python que se use para correr
REM  esto:   pip install pyinstaller
REM
REM  Uso: doble clic, o "build_launcher.bat" desde esta misma carpeta.
REM  El .exe resultante queda en esta carpeta (--distpath .), listo para
REM  pinear al taskbar o correr con doble clic.
REM ============================================================

cd /d "%~dp0"

pyinstaller --onefile --windowed ^
    --icon "server_icon.ico" ^
    --name "Iniciar Servidor Remote Play" ^
    --distpath . ^
    server_launcher.py

echo.
echo Listo. Si no hubo errores arriba, el .exe quedo actualizado en esta carpeta.
pause
