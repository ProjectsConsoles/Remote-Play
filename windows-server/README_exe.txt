Como generar start_server_stream.exe
=====================================

Se compila el .ps1 con ps2exe (modulo oficial de PowerShell Gallery,
gratis y de codigo abierto). Se hace UNA sola vez; si despues editas
el .ps1, repetis solo el paso 2.

1) Abrir PowerShell normal (no hace falta ser administrador) en esta
   carpeta y correr, una sola vez:

     Install-Module -Name ps2exe -Scope CurrentUser -Force

   (Si pregunta por un repositorio no confiable / NuGet provider,
   aceptar con "S"/"Y".)

2) Compilar:
     Set-ExecutionPolicy -ExecutionPolicy Bypass -Scope Process -Force
     Invoke-ps2exe .\start_server_stream.ps1 .\start_server_stream.exe

   Esto genera start_server_stream.exe en la misma carpeta, al lado
   de ffmpeg-9.0.1-full_build. El .exe tiene que quedar en esa misma
   carpeta (usa una ruta relativa a si mismo para encontrar ffmpeg).

3) Doble click en start_server_stream.exe para correrlo. Deja una
   consola abierta con la salida de ffmpeg (para ver errores); al
   cerrarla se corta el stream.

Si mas adelante queres que no muestre consola (ventana totalmente
invisible), se recompila agregando -noConsole al comando del paso 2 -
pero entonces no vas a poder ver errores de ffmpeg si algo falla, asi
que dejalo con consola mientras sigamos ajustando cosas.
