@echo off
REM ============================================================
REM  PS3 Remote Play - Revisar el log del servidor
REM ============================================================
REM  Doble clic aca despues de jugar un rato. Resume la ultima
REM  corrida y dice si la capturadora le esta ganando a esta PC
REM  (fps por debajo de 60, o el aviso de buffer lleno de dshow).
REM
REM  Solo lee: no toca el stream ni la configuracion.
REM ============================================================

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0revisar_log.ps1"

pause
