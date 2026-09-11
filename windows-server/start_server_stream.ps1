# ============================================================
#  PS3 Remote Play - Servidor de video + audio (Windows + Nvidia)
# ============================================================
#  Version PowerShell de start_server_stream.bat, pensada para
#  compilarse a .exe con ps2exe (ver README_exe.txt en esta misma
#  carpeta para los 2 comandos que la generan).
#
#  Captura la PS3 desde la capturadora HDMI ("USB Video" + audio
#  digital), codifica el video en H.264 con NVENC y el audio en
#  AAC, y transmite AMBOS muxeados en un solo stream MPEG-TS por
#  UN puerto UDP a la Steam Deck (coincide con lo que espera
#  start_client_stream.sh del lado del Deck).
#
#  Toda la sintonia de abajo (tune ull, delay 0, audio_buffer_size,
#  etc.) es para minimizar el input lag boton->pantalla, que es lo
#  que mas importa para poder jugar. Ver notas puntuales al final
#  antes de tocar valores.
#
#  Cada corrida deja dos logs en la carpeta "logs" de al lado.
#  Para leerlos sin bucear: revisar_log.bat. La explicacion de por
#  que son dos y que se mira en cada uno esta en el bloque de logs
#  de start_server_stream.bat, que es el espejo de esto.
# ============================================================

$DeckPort = 5000

# $PSScriptRoot apunta a la carpeta donde vive el .ps1 (o el .exe
# compilado con ps2exe), no a una carpeta temporal - a diferencia
# de un autoextraible (iexpress), esto sigue funcionando bien
# donde sea que quede instalado/copiado.
# ps2exe puede dejar $PSScriptRoot vacio al procesar el script para
# compilarlo (no al correr el .exe ya compilado), asi que hay que
# tener un respaldo o falla la compilacion.
$ScriptDir = $PSScriptRoot
if ([string]::IsNullOrEmpty($ScriptDir)) { $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path }
if ([string]::IsNullOrEmpty($ScriptDir)) { $ScriptDir = Get-Location }
$Ffmpeg = Join-Path $ScriptDir "ffmpeg-9.0.1-full_build\bin\ffmpeg.exe"

# ------------------------------------------------------------
#  IP de la Steam Deck - se pregunta al arrancar
# ------------------------------------------------------------
#  El video va EMPUJADO de esta PC hacia la Deck: la Deck solo se
#  sienta a escuchar en udp://@:5000 y acepta de quien sea, asi que
#  nunca necesita saber la IP de esta PC. La unica IP que tiene que
#  estar bien es la de la Deck, y vive aqui.
#
#  Antes estaba clavada como 192.168.0.141. El problema: si la Deck
#  cambia de IP (por ejemplo al pasarse de la red de 2.4GHz a la de
#  5GHz), ffmpeg sigue disparando a la IP vieja, NO da ningun error
#  - manda UDP feliz a un destino que no existe - y del lado del
#  Deck solo se ve pantalla negra. Paso el 2026-08-28 y costo un
#  rato darse cuenta, porque el cliente arranca bien y no se queja.
#
#  La ultima IP usada queda guardada en deck_ip.txt (al lado de
#  este script) y se ofrece como default: Enter la acepta.
#
#  Para ver la IP actual de la Deck, en una terminal del Deck:
#      ip -4 addr show wlan0
$IpFile = Join-Path $ScriptDir "deck_ip.txt"

$DeckIpDef = "192.168.0.141"
if (Test-Path $IpFile) {
  $guardada = (Get-Content $IpFile -TotalCount 1)
  if (-not [string]::IsNullOrWhiteSpace($guardada)) { $DeckIpDef = $guardada.Trim() }
}

# Validacion minima: 4 grupos de digitos separados por puntos. No
# valida rangos (256.1.1.1 pasa) - solo atrapa dedazos como una IP a
# medias o con una letra, que si no se notarian hasta ver la pantalla
# negra otra vez.
do {
  $entrada = Read-Host "  IP de la Steam Deck [$DeckIpDef], o Enter para usar esa"
  if ([string]::IsNullOrWhiteSpace($entrada)) { $DeckIp = $DeckIpDef } else { $DeckIp = $entrada.Trim() }
  if ($DeckIp -notmatch '^\d+\.\d+\.\d+\.\d+$') {
    Write-Host "  `"$DeckIp`" no parece una IP. Intenta de nuevo."
    $ok = $false
  } else {
    $ok = $true
  }
} until ($ok)

# Se guarda CON salto de linea al final (sin -NoNewline) porque este
# mismo archivo lo lee tambien start_server_stream.bat con
# "set /p DECK_IP_DEF=<archivo", y set /p lee HASTA el salto: si el
# archivo no lo tiene, se come el ultimo caracter y la IP vuelve como
# 192.168.0.14 en vez de 192.168.0.141 - pasa la validacion igual y
# es otra vez pantalla negra sin ningun error.
Set-Content -Path $IpFile -Value $DeckIp -Encoding ASCII

# ------------------------------------------------------------
#  Nombres de la capturadora - ya no van clavados
# ------------------------------------------------------------
#  Antes esto decia, tal cual:
#      -i 'video=USB Video:audio=Interfaz de sonido digital (USB Digital Audio)'
#
#  El problema (paso el 2026-08-29): Windows le cambia el nombre a
#  la interfaz de audio de la capturadora si se enchufa en OTRO
#  puerto USB - le mete un numero adelante y queda como "Interfaz de
#  sonido digital (2- USB Digital Audio)". El nombre clavado deja de
#  existir y ffmpeg ni arranca ("Could not find audio only device
#  with name [...]" / "Error opening input files: I/O error").
#
#  Ahora el nombre se busca cada vez, por PEDAZO ("USB Video",
#  "USB Digital Audio"), que es lo que sobrevive al "2- ".
#
#  OJO: esto esta duplicado a proposito con detectar_dispositivos.ps1
#  (que es el que usa start_server_stream.bat). Aca va inline porque
#  este .ps1 se compila a un .exe suelto con ps2exe y no puede
#  depender de otro archivo al lado. Si cambias los patrones,
#  cambialos en los dos.
$Listado = (& $Ffmpeg -hide_banner -list_devices true -f dshow -i dummy 2>&1 | Out-String)

#  Se banca los dos formatos que fue teniendo ffmpeg:
#    viejo: el tipo sale en un encabezado ("DirectShow video devices")
#           y despues las lineas con el nombre entre comillas
#    nuevo: cada linea trae el tipo al final -> "USB Video" (video)
#  Las lineas "Alternative name" tambien traen comillas, asi que hay
#  que descartarlas o se colarian como si fueran dispositivos.
$Videos  = New-Object System.Collections.ArrayList
$Audios  = New-Object System.Collections.ArrayList
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

#  Gana el primer patron que pegue: asi "USB Digital Audio" le gana a
#  cualquier otra cosa que tambien diga "Digital Audio" (una entrada
#  S/PDIF de la placa madre, por ejemplo).
function Elegir($Nombres, $Patrones) {
  foreach ($P in $Patrones) {
    $Hit = $Nombres | Where-Object { $_ -like $P } | Select-Object -First 1
    if ($Hit) { return $Hit }
  }
  return $null
}

$VideoDev = Elegir $Videos @("*USB Video*")
$AudioDev = Elegir $Audios @("*USB Digital Audio*", "*Digital Audio*")

#  Si falta alguno se CORTA, no se agarra otro dispositivo cualquiera:
#  caer al microfono de la PC seria peor que fallar, porque el stream
#  arrancaria "bien" y recien te darias cuenta al oirlo.
if ((-not $VideoDev) -or (-not $AudioDev)) {
  Write-Host ""
  Write-Host "============================================================"
  Write-Host "  ERROR: no se encontro la capturadora"
  Write-Host "============================================================"
  if (-not $VideoDev) { Write-Host '   - No hay ningun dispositivo de VIDEO con "USB Video" en el nombre.' }
  if (-not $AudioDev) { Write-Host '   - No hay ningun dispositivo de AUDIO con "Digital Audio" en el nombre.' }
  Write-Host ""
  Write-Host "  Esto es todo lo que Windows ofrece ahora mismo:"
  Write-Host ""
  Write-Host $Listado
  Write-Host "  Que revisar, en este orden:"
  Write-Host "    1) Que la capturadora este enchufada. Cambiarla de puerto USB"
  Write-Host "       tambien vale: el nombre puede cambiar, pero esto ya lo aguanta."
  Write-Host "    2) Que no la tenga tomada otro programa: OBS, Discord, el propio"
  Write-Host "       Remote Play, o un ffmpeg que quedo colgado de una corrida anterior."
  Write-Host "    3) Administrador de dispositivos: que no aparezca con el"
  Write-Host "       triangulito amarillo."
  Write-Host ""
  Read-Host "  Enter para cerrar"
  exit 1
}

Write-Host ""
Write-Host "  Capturadora video: $VideoDev"
Write-Host "  Capturadora audio: $AudioDev"

Write-Host ""
Write-Host "  Mandando video a ${DeckIp}:${DeckPort}"
Write-Host ""

#  Logs de la corrida. Espejo del bloque del .bat; la explicacion
#  larga (por que hacen falta LOS DOS archivos, por que level=32 y
#  no el debug del default, por que el Push-Location) esta alla.
#  Resumen: FFREPORT deja los avisos - incluido "real-time buffer
#  ... full", que es dshow avisando que se le llena la cola - y
#  -progress deja la serie de fps/speed/cuadros tirados, que el
#  report NO trae (ahi solo aparece el fps del resumen final).
$LogDir = Join-Path $ScriptDir "logs"
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$env:FFREPORT = "file=ffmpeg-$Stamp.log:level=32"
Write-Host "  Logs de esta corrida, en $LogDir"
Write-Host "    ffmpeg-$Stamp.log     - avisos y errores"
Write-Host "    progreso-$Stamp.log   - fps, speed, cuadros tirados"
Write-Host "  Para leerlos sin bucear: revisar_log.bat"
Write-Host ""

#  Parados en la carpeta de logs, los nombres quedan relativos y
#  FFREPORT no tiene que lidiar con el ":" de "C:\" (usa ese mismo
#  caracter para separar sus opciones).
Push-Location $LogDir

& $Ffmpeg `
  -stats_period 2 -progress "progreso-$Stamp.log" `
  -f dshow -video_size 1280x720 -framerate 60 -vcodec mjpeg `
  -use_wallclock_as_timestamps 1 `
  -audio_buffer_size 50 -rtbufsize 512k `
  -i ("video={0}:audio={1}" -f $VideoDev, $AudioDev) `
  -vf format=nv12 `
  -c:v h264_nvenc -preset p1 -tune ull -zerolatency 1 -rc cbr -b:v 5M -maxrate 5M -bufsize 250k `
  -g 30 -bf 0 -rc-lookahead 0 -delay 0 `
  -af aresample=async=1000 `
  -c:a aac -b:a 96k -ar 48000 -ac 2 `
  -f mpegts -muxdelay 0 -muxpreload 0 -flush_packets 1 -max_interleave_delta 0 `
  "udp://${DeckIp}:${DeckPort}?pkt_size=1316&connect=0"

Pop-Location

#
# -rtbufsize 512k : tope del buffer de captura en tiempo real de
#   dshow, o sea la cola de cuadros que ffmpeg deja acumular ENTRE
#   la capturadora y el encoder. El default de ffmpeg son 3041280
#   bytes (~2.9 MB). A 720p60 en MJPEG un cuadro pesa entre 80 y
#   250 KB segun lo cargada que este la escena, asi que ese default
#   son entre 12 y 35 CUADROS de cola: 200 a 580 ms de retraso que
#   se generan aca y que ninguna perilla del lado del Deck puede
#   tocar.
#
#   Y no se llena parejo: se llena cuando la PC no le gana a la
#   capturadora, que es justo lo que pasa al entrar a un JUEGO
#   (escena complicada -> el MJPEG pesa mas -> tarda mas en
#   decodificarse -> la cola crece y se queda arriba). Encaja con el
#   sintoma de 'hay mas lag cuando abro un juego' que en el XMB, que
#   es una pantalla casi quieta.
#
#   Si la PC no llega, ahora TIRA cuadros en vez de acumular
#   retraso, y lo dice en el log: 'real-time buffer ... full ...
#   frame dropped!'. Que aparezca ese aviso no es el problema, es el
#   diagnostico - revisar_log.bat lo cuenta.
#
#   HISTORIA DEL VALOR (para no volver a probar a ciegas):
#     default (2.9 MB) -> 12 a 35 cuadros de cola. Era lo que habia.
#     512k (~2-5 cuadros) -> el usuario confirmo 'ya mejoro mucho'
#        en Modo Juego. VALOR CONOCIDO BUENO: si algo sale mal,
#        volver aca, no al default.
#     256k (~1-3 cuadros) -> se probo y se sintio IGUAL que 512k, o
#        sea que en 512k la cola ya no se llenaba. Se volvio a 512k
#        por ser el valor confirmado. No apretar mas: no rinde.
#  AJUSTE (2026-08-29): -bufsize bajado de 700k a 250k. bufsize es
#    el tamano del buffer virtual del rate control (VBV): 700k a
#    5 Mbps son ~140ms de margen que NVENC se permite gastar en un
#    solo frame. Ese margen se traduce en rafagas grandes cruzando
#    la wifi (encolamiento = jitter = lag) y en NALs mas grandes,
#    que es justo lo que hace que perder UN paquete UDP corrompa
#    todo el frame (los "non-existing PPS 0" del log del Deck).
#    250k son ~3 frames a 60fps (5M/60 = ~83k por frame), que es el
#    rango tipico de baja latencia. Efecto secundario esperado: en
#    cambios de escena bruscos el bitrate no puede dispararse, asi
#    que puede verse un pelin mas blando por un instante. Si se ve
#    notoriamente peor y el lag no bajo, volver a 700k.

#
# -max_interleave_delta 0 : el muxer de mpegts, por default, NO
#   escribe un cuadro de video hasta tener un paquete de AUDIO que
#   lo cubra en el tiempo, para dejar los dos streams bien
#   intercalados. Con un archivo eso es prolijo; con una
#   transmision en vivo es retraso puro: el audio de la
#   capturadora llega en bloques (-audio_buffer_size 50, mas los
#   1024 samples que junta el AAC), asi que cada cuadro de video se
#   queda esperando ~25-70 ms EN LA PC antes de salir a la red.
#   Con 0 se apaga esa espera y cada paquete sale apenas esta listo.
#
#   POR QUE ESTE ES EL SOSPECHOSO BUENO AHORA: la vista previa local
#   de la capturadora (medir_latencia.bat) se siente inmediata, y esa
#   vista previa NO pasa por el encoder ni por el muxer ni por la
#   red. O sea que todo lo que esta entre NVENC y el Deck sigue sin
#   medirse, y esta espera del muxer vive justo ahi. Tambien encaja
#   con la vieja observacion de que 'sin audio la imagen es
#   inmediata': sin audio no hay con quien intercalar, y el muxer
#   deja de esperar.
#
#   -muxdelay 0 / -muxpreload 0 (que ya estaban) NO cubren esto: son
#   otra cosa, el retardo de arranque del muxer, no el intercalado.
#
#
# -use_wallclock_as_timestamps 1 : lo que hace que el aresample de
#   arriba pueda hacer su trabajo.
#
#   aresample=async solo corrige contra las MARCAS DE TIEMPO. Si el
#   demuxer numera las muestras para armar el PTS en vez de anotar la
#   hora real de llegada, la linea de tiempo del audio le parece
#   perfecta - la deriva esta ahi pero es invisible, y el filtro no
#   corrige nada. Que es exactamente lo que paso: se puso async=1000
#   y el audio siguio desfasandose igual.
#
#   Con esto cada paquete se marca con la hora a la que llego de
#   verdad, asi que la deriva del reloj de la capturadora aparece en
#   los timestamps y el aresample la puede absorber.
#
#   RIESGO A VIGILAR: esto tambien afecta al video. Las marcas pasan
#   a tener el jitter de llegada, y como la salida es a 60fps fijos,
#   ffmpeg podria empezar a duplicar o tirar cuadros para cuadrar.
#   Eso se ve en el log de progreso como dup_frames o drop_frames
#   distintos de cero (revisar_log.bat los muestra), y en pantalla
#   como tironeo. Si aparece, se quita esta linea y volvemos a
#   pensar - el aresample de arriba se puede quedar, no molesta.

# -af aresample=async=1000 : arreglo de la DERIVA del audio.
#
#   El sintoma: despues de un rato el audio se va desfasando del
#   video, y se compone reiniciando el server. Ese 'se compone
#   reiniciando' es justamente la firma del problema.
#
#   La causa: el reloj de audio de la capturadora no corre exacto a
#   48000 Hz (ninguno lo hace; se van unas partes por millon). El
#   encoder AAC no le hace caso a la hora a la que llega cada
#   bloque: numera las muestras y de ahi saca el PTS. Asi que si el
#   aparato entrega 48001 muestras por segundo en vez de 48000, cada
#   segundo el audio se corre un poquito, y ESO SE ACUMULA - no se
#   nota en un minuto y es obvio en veinte. Reiniciar el server pone
#   la cuenta de muestras en cero otra vez, por eso 'se arregla'.
#
#   aresample=async=1000 le da permiso al remuestreador para estirar
#   o encoger hasta 1000 muestras por segundo con tal de que el audio
#   siga pegado a las marcas de tiempo con las que entro. La deriva
#   se absorbe sobre la marcha en vez de acumularse.
#
#   No agrega latencia: no guarda nada, solo ajusta el paso. Si
#   alguna vez se llegara a oir el ajuste (no deberia, son partes por
#   millon), bajarlo a async=100. Quitarlo del todo devuelve la
#   deriva.
# -audio_buffer_size 50 : la interfaz de audio USB de la
#   capturadora usaba un buffer de captura grande por default en
#   DirectShow/Windows, lo que atrasaba el audio respecto al
#   video. Este flag le pide al driver un buffer chico (en ms)
#   para bajar esa latencia en el origen. Si el driver del
#   dispositivo ignora el valor pedido, no hace nada (algunos no
#   lo respetan) - probado y funciona con esta capturadora.
#
#   IMPORTANTE: no intentar arreglar el desfase audio/video con
#   -itsoffset separando video y audio en dos -i distintos. Ya se
#   probo: obliga al muxer a esperar el audio (que sigue llegando
#   tarde de verdad, el offset solo cambia la etiqueta de tiempo)
#   antes de poder escribir el video, y el input lag empeora en
#   vez de mejorar. Tampoco forzar -sync video del lado del
#   cliente como sustituto: eso hace que ffplay reintente
#   resamplear el audio sin parar contra un hueco que nunca se
#   cierra, y se escucha cortado. La solucion real es bajar la
#   latencia real de captura del audio (este flag), no mentir
#   sobre sus timestamps ni forzar el reloj de reproduccion.
#
# -tune ull -zerolatency 1 -rc-lookahead 0 -delay 0 : evitan que
#   NVENC acumule frames en buffer interno antes de soltarlos.
#   Con 60fps eso solo podia sumar decenas/cientos de ms.
#
# -muxdelay 0 -muxpreload 0 -flush_packets 1 : el muxer mpegts
#   por default puede retener paquetes hasta 0.7s (-muxdelay) para
#   interleavear streams "prolijo". Sin esto, ese delay se suma
#   solo, aunque el resto de la cadena este bien afinada.
#
# PRUEBA (2026-08-23): bajado de 1920x1080/8M a 1280x720/5M (ver el
#   comentario con el mismo fechado en start_server_stream.bat para
#   el detalle completo - evidencia en el log del Deck de una rafaga
#   de perdida de paquetes/wifi que corrompio frames seguidos, no un
#   problema de CPU). Si hay que revertir, los valores originales
#   eran -vf format=nv12 y -b:v 8M -maxrate 8M -bufsize 1M.
#
# PRUEBA (2026-08-23): audio -b:a bajado de 128k a 96k por cortes
#   ocasionales de audio con 720p/5M (ver el comentario con el mismo
#   fechado en start_server_stream.bat para el detalle completo - esto
#   ahorra poco ancho de banda total, solo ayuda si el corte es un
#   paquete UDP que justo le toca al audio). Revertir a 128k si no
#   ayuda con los cortes y se nota peor el audio.

Read-Host "ffmpeg termino (o fallo). Presiona Enter para cerrar"
