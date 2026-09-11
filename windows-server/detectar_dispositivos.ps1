# ============================================================
#  Detecta los nombres DirectShow de la capturadora HDMI
# ============================================================
#  Lo llama start_server_stream.bat antes de arrancar ffmpeg.
#  Deja el resultado en tres archivos dentro de %TEMP%, porque el
#  .bat los lee con "set /p VAR=<archivo" y asi no tiene que parsear
#  nada (los nombres traen espacios y parentesis, que en cmd son un
#  campo minado):
#
#    ps3rp_video.txt  - nombre del dispositivo de video, o no existe
#    ps3rp_audio.txt  - nombre del dispositivo de audio, o no existe
#    ps3rp_dshow.txt  - el listado completo, para mostrarlo si falla
#
#  POR QUE EXISTE ESTO (2026-08-29): los nombres estaban clavados
#  como video="USB Video" y audio="Interfaz de sonido digital (USB
#  Digital Audio)". Windows le cambia el nombre a la interfaz de
#  audio si la capturadora se enchufa en OTRO puerto USB: le mete un
#  numero adelante y queda "Interfaz de sonido digital (2- USB
#  Digital Audio)". El nombre clavado deja de existir y ffmpeg ni
#  arranca:
#      Could not find audio only device with name [Interfaz de
#      sonido digital (USB Digital Audio)] among source devices of
#      type audio.
#      Error opening input files: I/O error
#
#  Por eso aqui se elige por PEDAZO del nombre y no por el nombre
#  completo: eso es justo lo que sobrevive al "2- ".
#
#  OJO: start_server_stream.ps1 (la version compilable a .exe) trae
#  su propia copia de esta logica adentro, porque tiene que poder
#  correr sola como un solo .exe. Si tocas los patrones de abajo,
#  tocalos alla tambien.
# ============================================================

param(
  [string]$Ffmpeg = $null
)

# Misma cadena de respaldo que start_server_stream.ps1: $PSScriptRoot
# puede venir vacio segun como se invoque el script.
$ScriptDir = $PSScriptRoot
if ([string]::IsNullOrEmpty($ScriptDir)) { $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path }
if ([string]::IsNullOrEmpty($ScriptDir)) { $ScriptDir = (Get-Location).Path }
if ([string]::IsNullOrEmpty($Ffmpeg)) {
  $Ffmpeg = Join-Path $ScriptDir "ffmpeg-9.0.1-full_build\bin\ffmpeg.exe"
}

$ArchivoVideo   = Join-Path $env:TEMP "ps3rp_video.txt"
$ArchivoAudio   = Join-Path $env:TEMP "ps3rp_audio.txt"
$ArchivoListado = Join-Path $env:TEMP "ps3rp_dshow.txt"

# Borrar los de la corrida anterior ANTES de nada: si esta vez no se
# encuentra la capturadora, el .bat no debe leer el nombre viejo y
# creer que todo esta bien.
Remove-Item $ArchivoVideo, $ArchivoAudio, $ArchivoListado -Force -ErrorAction SilentlyContinue

if (-not (Test-Path $Ffmpeg)) {
  Set-Content -Path $ArchivoListado -Value "No se encontro ffmpeg en: $Ffmpeg" -Encoding Oem
  exit 1
}

# ffmpeg escupe el listado por stderr y termina con codigo de error
# (es lo normal con -list_devices, no es una falla).
$Listado = (& $Ffmpeg -hide_banner -list_devices true -f dshow -i dummy 2>&1 | Out-String)
Set-Content -Path $ArchivoListado -Value $Listado -Encoding Oem

# ------------------------------------------------------------
#  Parseo del listado
# ------------------------------------------------------------
#  Se banca los dos formatos que fue teniendo ffmpeg, porque el
#  ffmpeg de esta carpeta se puede actualizar:
#
#    ffmpeg viejo (sin sufijo, hay que mirar el encabezado):
#      [dshow @ ...] DirectShow video devices
#      [dshow @ ...]  "USB Video"
#      [dshow @ ...]     Alternative name "@device_pnp_..."
#
#    ffmpeg nuevo (cada linea dice de que tipo es):
#      [dshow @ ...] "USB Video" (video)
#
#  Las lineas "Alternative name" tambien traen comillas, asi que se
#  descartan aparte o se colarian como si fueran dispositivos.
$Videos = New-Object System.Collections.ArrayList
$Audios = New-Object System.Collections.ArrayList
$Seccion = ""

foreach ($Linea in ($Listado -split "`r?`n")) {
  if ($Linea -match "DirectShow video devices") { $Seccion = "video"; continue }
  if ($Linea -match "DirectShow audio devices") { $Seccion = "audio"; continue }
  if ($Linea -match "Alternative name")         { continue }

  $M = [regex]::Match($Linea, '"([^"]+)"')
  if (-not $M.Success) { continue }

  $Tipo = $Seccion
  if     ($Linea -match "\(video\)\s*$") { $Tipo = "video" }
  elseif ($Linea -match "\(audio\)\s*$") { $Tipo = "audio" }

  if     ($Tipo -eq "video") { [void]$Videos.Add($M.Groups[1].Value) }
  elseif ($Tipo -eq "audio") { [void]$Audios.Add($M.Groups[1].Value) }
}

# Se prueban los patrones en orden y gana el primero que pegue: asi
# "USB Digital Audio" le gana a cualquier otra cosa que tambien diga
# "Digital Audio" (una entrada S/PDIF de la placa madre, por ejemplo).
function Elegir($Nombres, $Patrones) {
  foreach ($P in $Patrones) {
    $Hit = $Nombres | Where-Object { $_ -like $P } | Select-Object -First 1
    if ($Hit) { return $Hit }
  }
  return $null
}

$VideoDev = Elegir $Videos @("*USB Video*")
$AudioDev = Elegir $Audios @("*USB Digital Audio*", "*Digital Audio*")

# Si no hay match NO se escribe el archivo. El .bat lo toma como
# "no esta la capturadora" y corta. Es a proposito: caer al microfono
# de la PC seria peor que fallar, porque el stream arrancaria "bien"
# y recien te darias cuenta al oirlo.
# Se escriben CON salto de linea al final (o sea, sin -NoNewline) a
# proposito: "set /p VAR=<archivo" del lado del .bat lee HASTA el
# salto de linea, y si el archivo no lo tiene se come el ultimo
# caracter. Probado: sin salto, "USB Video" llega como "USB Vide" y
# "...(2- USB Digital Audio)" pierde el parentesis final - ffmpeg
# entonces no encuentra el dispositivo y el error se ve identico al
# que esto vino a arreglar. El salto no se cuela en la variable: es
# justo lo que set /p usa para saber donde termina.
if ($VideoDev) { Set-Content -Path $ArchivoVideo -Value $VideoDev -Encoding Oem }
if ($AudioDev) { Set-Content -Path $ArchivoAudio -Value $AudioDev -Encoding Oem }

if ($VideoDev -and $AudioDev) { exit 0 } else { exit 1 }
