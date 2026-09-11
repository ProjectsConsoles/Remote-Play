# ============================================================
#  server_engine_lib.ps1 - logica compartida del motor del servidor
# ============================================================
#  Extraido de start_server_gui.ps1 (2026-09-11) para que
#  config_listener.ps1 (el nuevo escucha de configuracion remota
#  desde la Deck) pueda arrancar/detener el mismo motor SIN
#  duplicar la logica - la misma razon por la que start_server_gui.ps1
#  nunca reimplemento ffmpeg: dos copias de esto mismo garantizan que
#  un dia se separen y nadie sepa cual manda.
#
#  Se carga con dot-sourcing: . "$PSScriptRoot\server_engine_lib.ps1"
#  Define variables y funciones en el scope de quien lo carga.
# ============================================================

$Aqui        = $PSScriptRoot
$Bat         = Join-Path $Aqui "start_server_stream.bat"
$FfmpegExe   = Join-Path $Aqui "ffmpeg-9.0.1-full_build\bin\ffmpeg.exe"
$ArchivoIps  = Join-Path $Aqui "deck_ips.txt"    # historial (varias)
$ArchivoIp   = Join-Path $Aqui "deck_ip.txt"     # ultima, la que ya usaba el .bat
$ArchivoModo = Join-Path $Aqui "deck_modo.txt"   # ultimo modo elegido
$ArchivoPid  = Join-Path $Aqui "servidor.pid"    # PID del cmd oculto en curso

$RegexIp = '^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$'

# ------------------------------------------------------------
#  Modos de captura (las Claves tienen que coincidir con la tabla
#  de start_server_stream.bat)
# ------------------------------------------------------------
$Modos = @(
    [pscustomobject]@{
        Clave  = "mjpeg720"
        Nombre = "1280x720  -  MJPEG  (recomendado)"
        Ayuda  = "El modo de siempre y el unico probado a fondo: 60 fps estables, ~6 Mbps de wifi. Si dudas, este."
    }
    [pscustomobject]@{
        Clave  = "mjpeg1080"
        Nombre = "1920x1080  -  MJPEG  (mas nitido)"
        Ayuda  = "Imagen mas definida, pero sube a 8 Mbps y la capturadora comprime el doble de pixeles. Sin probar: si aparecen tirones o cortes de audio, vuelve a 720p."
    }
    [pscustomobject]@{
        Clave  = "crudo480"
        Nombre = "720x480  -  SIN COMPRIMIR  (prueba)"
        Ayuda  = "Prueba de latencia: se salta el MJPEG. Ojo, manda 5x mas bytes por el USB 2.0 y baja a 480p. Despues revisa con revisar_log.bat que haya sostenido 60 fps."
    }
    [pscustomobject]@{
        Clave  = "crudo640"
        Nombre = "640x480  -  SIN COMPRIMIR  (prueba)"
        Ayuda  = "Igual que el anterior pero pide menos por el USB (37 MB/s contra 41). Si el de 720x480 no sostiene 60 fps, prueba con este."
    }
)

function Modo-Valido($clave) {
    return [bool]($Modos | Where-Object { $_.Clave -eq $clave })
}

# ------------------------------------------------------------
#  Encontrar y detener el servidor en curso
# ------------------------------------------------------------
#  Se busca por RUTA del ejecutable, no por nombre: asi solo se
#  toca el ffmpeg que vive en esta carpeta y nunca otro ffmpeg
#  que el usuario tenga abierto para cualquier otra cosa.
#  Get-Process y no Get-CimInstance Win32_Process (2026-09-11):
#  WMI contesta "Acceso denegado" en esta maquina, y ademas
#  .Path puede fallar de sesion en sesion (RDP) - ver el fallback.
function Procesos-Servidor {
    $todos = @(Get-Process -Name 'ffmpeg' -ErrorAction SilentlyContinue)
    if ($todos.Count -eq 0) { return @() }

    $mios = @($todos | Where-Object {
        $ruta = $null
        try { $ruta = $_.Path } catch { $ruta = $null }
        $ruta -and ($ruta -ieq $FfmpegExe)
    })
    if ($mios.Count -gt 0) { return $mios }

    # Si no se pudo leer la ruta de NINGUNO, no quedarse ciego: es preferible
    # contar un ffmpeg ajeno (raro, y a lo sumo molesta al detener) antes que
    # reportar un fallo falso en cada arranque.
    return $todos
}

function Servidor-Corriendo {
    return ((Procesos-Servidor | Measure-Object).Count -gt 0)
}

function Detener-Servidor {
    $mato = $false

    if (Test-Path $ArchivoPid) {
        $guardado = (Get-Content $ArchivoPid -First 1 -ErrorAction SilentlyContinue)
        if ($guardado -and $guardado.Trim() -match '^\d+$') {
            $elPid = $guardado.Trim()
            if (Get-Process -Id ([int]$elPid) -ErrorAction SilentlyContinue) {
                & taskkill.exe /PID $elPid /T /F 2>&1 | Out-Null
                $mato = $true
            }
        }
        Remove-Item $ArchivoPid -Force -ErrorAction SilentlyContinue
    }

    foreach ($p in (Procesos-Servidor)) {
        & taskkill.exe /PID $p.Id /T /F 2>&1 | Out-Null
        $mato = $true
    }

    return $mato
}

# ------------------------------------------------------------
#  Historial de IPs
# ------------------------------------------------------------
function Leer-Ips {
    $lista = New-Object System.Collections.Generic.List[string]
    foreach ($archivo in @($ArchivoIps, $ArchivoIp)) {
        if (Test-Path $archivo) {
            foreach ($linea in (Get-Content $archivo -ErrorAction SilentlyContinue)) {
                $ip = $linea.Trim()
                if ($ip -match $RegexIp -and -not $lista.Contains($ip)) { $lista.Add($ip) }
            }
        }
    }
    if ($lista.Count -eq 0) { $lista.Add("192.168.0.141") }
    return $lista
}

function Guardar-Ip($ip) {
    $previas = @(Leer-Ips | Where-Object { $_ -ne $ip })
    $nuevas  = @(@($ip) + $previas | Select-Object -First 8)
    Set-Content -Path $ArchivoIps -Value $nuevas -Encoding Ascii
    Set-Content -Path $ArchivoIp  -Value $ip     -Encoding Ascii
}

# ------------------------------------------------------------
#  Arrancar el servidor (extraido del handler de $btnIniciar)
# ------------------------------------------------------------
#  $avisar es un scriptblock opcional para reportar progreso (lo usa
#  el GUI para actualizar su label; config_listener.ps1 lo puede dejar
#  vacio). Devuelve $true si ffmpeg llego a arrancar de verdad.
function Iniciar-Servidor($ip, $modo, [scriptblock]$avisar = {}) {
    if (-not (Modo-Valido $modo)) {
        & $avisar "modo invalido: $modo"
        return $false
    }
    if ($ip -notmatch $RegexIp) {
        & $avisar "IP invalida: $ip"
        return $false
    }

    & $avisar "Cerrando la instancia anterior..."
    [void](Detener-Servidor)

    # La capturadora no siempre se libera al instante despues de matar al
    # ffmpeg anterior; si el nuevo la abre demasiado pronto, dshow contesta
    # "device in use" y el arranque falla.
    Start-Sleep -Milliseconds 900

    Guardar-Ip $ip
    Set-Content -Path $ArchivoModo -Value $modo -Encoding Ascii

    $env:PS3RP_IP   = $ip
    $env:PS3RP_MODO = $modo
    $env:PS3RP_GUI  = "1"

    & $avisar "Iniciando..."
    $proc = Start-Process -FilePath $Bat -WorkingDirectory $Aqui -WindowStyle Hidden -PassThru
    Set-Content -Path $ArchivoPid -Value $proc.Id -Encoding Ascii

    $arranco = $false
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Milliseconds 500
        if (Servidor-Corriendo) { $arranco = $true; break }
    }

    if ($arranco) { & $avisar "Servidor corriendo." }
    else { & $avisar "No arranco en 15 segundos." }

    return $arranco
}

# ------------------------------------------------------------
#  Guardar SOLO la configuracion (sin arrancar nada) - para cuando
#  el servidor no esta corriendo y config_listener.ps1 solo necesita
#  dejarla lista para la proxima vez que el usuario le de Iniciar.
# ------------------------------------------------------------
function Guardar-Configuracion($ip, $modo) {
    if (-not (Modo-Valido $modo)) { return $false }
    if ($ip -notmatch $RegexIp) { return $false }
    Guardar-Ip $ip
    Set-Content -Path $ArchivoModo -Value $modo -Encoding Ascii
    return $true
}
