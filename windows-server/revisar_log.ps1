# ============================================================
#  PS3 Remote Play - Lector de los logs del servidor
# ============================================================
#  Resume la ULTIMA corrida de ffmpeg (carpeta "logs") para
#  contestar una sola pregunta:
#
#      la capturadora MJPEG a 720p60, le esta ganando a esta PC?
#
#  Si el MJPEG no se decodifica a tiempo, los cuadros se apilan en
#  el buffer de dshow ANTES de llegar a NVENC. Eso son cientos de
#  ms de lag generados AQUI, que ninguna perilla del lado del Deck
#  puede tocar. Se delata de dos formas, y las dos se miran abajo:
#    - fps por debajo de 60, o speed por debajo de 1x;
#    - el aviso "real-time buffer ... full ... frame dropped!", que
#      es dshow diciendo literalmente que se le llena la cola.
#
#  Lee los DOS archivos que deja cada corrida, porque cada uno
#  tiene la mitad de la respuesta (ver la nota larga en
#  start_server_stream.bat):
#    progreso-<fecha>.log -> los numeros, un bloque cada 2s
#    ffmpeg-<fecha>.log   -> los avisos y errores
#
#  Existe porque el crudo son miles de lineas y la pregunta se
#  contesta con tres numeros. Doble clic en revisar_log.bat.
#  Solo lee: no toca el stream ni la configuracion.
# ============================================================

$Dir = Join-Path $PSScriptRoot "logs"
if (-not (Test-Path $Dir)) {
  Write-Host ""
  Write-Host "  No hay carpeta 'logs' todavia: corre start_server_stream.bat una vez."
  exit 1
}

$Prog = Get-ChildItem -Path $Dir -Filter "progreso-*.log" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $Prog) {
  Write-Host ""
  Write-Host "  No hay ningun progreso-*.log: corre start_server_stream.bat una vez."
  Write-Host "  (Si ya corriste y no aparece, el .bat puede ser una version vieja"
  Write-Host "   sin -progress; volver a bajarlo del repo del Deck.)"
  exit 1
}

#  El log de avisos de la MISMA corrida: comparten la fecha del
#  nombre, asi que se arma cambiandole el prefijo.
$Stamp  = $Prog.BaseName -replace '^progreso-', ''
$Avisos = Join-Path $Dir ("ffmpeg-{0}.log" -f $Stamp)

#  Formato de -progress: bloques de clave=valor, uno por periodo.
$Fps    = New-Object System.Collections.ArrayList
$Speed  = New-Object System.Collections.ArrayList
$Drop   = 0
$Dup    = 0
foreach ($L in (Get-Content $Prog.FullName)) {
  if ($L -match '^fps=([0-9.]+)')         { [void]$Fps.Add([double]$Matches[1]) }
  elseif ($L -match '^speed=\s*([0-9.]+)x') { [void]$Speed.Add([double]$Matches[1]) }
  elseif ($L -match '^drop_frames=(\d+)') { $Drop = [int]$Matches[1] }
  elseif ($L -match '^dup_frames=(\d+)')  { $Dup  = [int]$Matches[1] }
}

#  Los primeros segundos siempre salen raros (arranque de NVENC,
#  primer keyframe, y el fps que ffmpeg promedia desde cero).
#  Contarlos haria ver un problema donde no lo hay.
$Descartar = [Math]::Min(3, $Fps.Count)
if ($Fps.Count -gt $Descartar) { $Fps = @($Fps[$Descartar..($Fps.Count - 1)]) }

$Buffer = 0
if (Test-Path $Avisos) {
  $Buffer = ([regex]::Matches((Get-Content $Avisos -Raw), 'real-time buffer')).Count
}

Write-Host ""
Write-Host "============================================================"
Write-Host "  Ultima corrida: $Stamp"
Write-Host "  ($($Prog.LastWriteTime))"
Write-Host "============================================================"
Write-Host ""

if ($Fps.Count -eq 0) {
  Write-Host "  El archivo de progreso esta vacio: ffmpeg no llego a transmitir."
  Write-Host "  Mirar el final de: $Avisos"
  Write-Host ""
  exit 0
}

$Orden   = @($Fps | Sort-Object)
$Mediana = $Orden[[int]($Orden.Count / 2)]
$Minimo  = $Orden[0]
$Bajos   = @($Fps | Where-Object { $_ -lt 58 }).Count
$Pct     = [Math]::Round(100 * $Bajos / $Fps.Count, 1)
$Minutos = [Math]::Round($Fps.Count * 2 / 60, 1)

Write-Host ("  Muestras            : {0}  (una cada 2s = ~{1} min)" -f $Fps.Count, $Minutos)
Write-Host ("  fps mediano         : {0}" -f $Mediana)
Write-Host ("  fps minimo          : {0}" -f $Minimo)
Write-Host ("  Muestras bajo 58 fps: {0}  ({1}%)" -f $Bajos, $Pct)
if ($Speed.Count -gt 0) {
  Write-Host ("  speed minimo        : {0}x" -f (@($Speed | Sort-Object)[0]))
}
Write-Host ("  Cuadros tirados     : {0}   (duplicados: {1})" -f $Drop, $Dup)
Write-Host ("  Avisos 'real-time buffer': {0}" -f $Buffer)

Write-Host ""
Write-Host "------------------------------------------------------------"
if ($Buffer -gt 0) {
  Write-Host "  VEREDICTO: la captura NO da abasto."
  Write-Host ""
  Write-Host "  dshow avisa que se le llena el buffer, o sea que los cuadros"
  Write-Host "  se apilan ANTES de NVENC. Ese retraso se genera en esta PC y"
  Write-Host "  no hay perilla del Deck que lo arregle. Que probar, en orden:"
  Write-Host "    1) Cerrar lo que compita por CPU o USB (OBS, navegador...)."
  Write-Host "    2) Capturar a 30 fps (-framerate 30) y ver si el aviso"
  Write-Host "       desaparece: eso confirma que era el decode de MJPEG."
  Write-Host "    3) Otro puerto USB, de preferencia de otro controlador."
} elseif ($Mediana -lt 58) {
  Write-Host "  VEREDICTO: no se sostienen los 60 fps."
  Write-Host ""
  Write-Host "  Sin avisos de dshow, asi que la cola no esta en la captura"
  Write-Host "  sino mas adelante (decode de MJPEG o NVENC). Mirar el uso de"
  Write-Host "  CPU mientras corre; si esta al tope, es el MJPEG."
} else {
  Write-Host "  VEREDICTO: la captura va al dia (60 fps, sin avisos)."
  Write-Host ""
  Write-Host "  El cuello de botella NO esta en esta PC. Lo que queda por"
  Write-Host "  medir es el piso de la capturadora en si: abrirla directo con"
  Write-Host "  ffplay (sin red y sin NVENC) y sacarle una foto con el celular"
  Write-Host "  junto a la TV con la salida real del PS3. Esa diferencia es"
  Write-Host "  latencia irreducible del aparato; las capturadoras MJPEG por"
  Write-Host "  USB suelen meter 60-120 ms ellas solas."
}
Write-Host "------------------------------------------------------------"
Write-Host ""
Write-Host "  Crudo: $($Prog.FullName)"
Write-Host "         $Avisos"
Write-Host ""
