# ============================================================
#  start_server_gui.ps1 - interfaz grafica del servidor
# ============================================================
#  Pide dos cosas y nada mas: a que IP mandar el video y en que
#  resolucion. Despues lanza start_server_stream.bat de siempre,
#  con la ventana OCULTA, pasandole la eleccion por variables de
#  entorno (PS3RP_IP, PS3RP_MODO, PS3RP_GUI) que el .bat ya sabe
#  leer.
#
#  POR QUE NO REIMPLEMENTA FFMPEG: toda la sintonia de latencia
#  del proyecto (tune ull, bufsize, audio_buffer_size, wallclock
#  timestamps, etc.) vive comentada y justificada dentro del
#  .bat. Duplicarla aqui garantizaria que un dia las dos copias
#  se separen y nadie sepa cual manda. Esta interfaz es solo la
#  puerta de entrada; el motor sigue siendo el .bat.
#
#  QUE SE PIERDE AL OCULTAR LA VENTANA: la linea de estado de
#  ffmpeg en vivo (fps, speed). No se pierde el diagnostico: eso
#  ya se venia guardando igual en logs\progreso-<fecha>.log y
#  logs\ffmpeg-<fecha>.log, que revisar_log.bat resume. Por eso
#  se puede ocultar sin quedarse ciego.
#
#  No necesita instalar nada: WinForms viene con Windows.
#  Se abre con iniciar_servidor.bat (doble clic).
# ============================================================

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

$Aqui        = Split-Path -Parent $MyInvocation.MyCommand.Path
$Bat         = Join-Path $Aqui "start_server_stream.bat"
$FfmpegExe   = Join-Path $Aqui "ffmpeg-9.0.1-full_build\bin\ffmpeg.exe"
$ArchivoIps  = Join-Path $Aqui "deck_ips.txt"    # historial (varias)
$ArchivoIp   = Join-Path $Aqui "deck_ip.txt"     # ultima, la que ya usaba el .bat
$ArchivoModo = Join-Path $Aqui "deck_modo.txt"   # ultimo modo elegido
$ArchivoPid  = Join-Path $Aqui "servidor.pid"    # PID del cmd oculto en curso

$RegexIp = '^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$'

if (-not (Test-Path $Bat)) {
    [System.Windows.Forms.MessageBox]::Show(
        "No encontre start_server_stream.bat en:`n$Aqui`n`nLos dos archivos tienen que estar en la misma carpeta.",
        "Remote Play", "OK", "Error") | Out-Null
    exit 1
}

# ------------------------------------------------------------
#  Encontrar y detener el servidor en curso
# ------------------------------------------------------------
#  Se busca por RUTA del ejecutable, no por nombre: asi solo se
#  toca el ffmpeg que vive en esta carpeta y nunca otro ffmpeg
#  que el usuario tenga abierto para cualquier otra cosa.
#  Get-Process y no Get-CimInstance Win32_Process (2026-09-11):
#  WMI contesta "Acceso denegado" en esta maquina, y como la
#  llamada llevaba -ErrorAction SilentlyContinue el error se
#  tragaba en silencio. Resultado: esta funcion devolvia SIEMPRE
#  vacio, Servidor-Corriendo daba False aunque ffmpeg estuviera
#  transmitiendo, y la interfaz mostraba "no arranco en 15
#  segundos" en CADA arranque, incluidos los exitosos.
#  Get-Process no necesita WMI ni permisos especiales y permite
#  el mismo filtro por ruta (.Path en vez de .ExecutablePath).
function Procesos-Servidor {
    $todos = @(Get-Process -Name 'ffmpeg' -ErrorAction SilentlyContinue)
    if ($todos.Count -eq 0) { return @() }

    # Filtrar por ruta del ejecutable MIENTRAS SE PUEDA. Leer .Path abre el
    # proceso, y segun la sesion de Windows y los permisos eso falla (medido
    # 2026-09-11: en una sesion RDP devolvia vacio aunque ffmpeg SI estuviera
    # transmitiendo a 59 fps). Esa lectura fallida dejaba la lista vacia y la
    # interfaz declaraba 'no arranco' en arranques perfectamente exitosos.
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

    # 1) El arbol del cmd que lanzamos, por el PID que guardamos.
    #    Hace falta /T: matar el cmd solo NO se lleva al ffmpeg
    #    hijo, que quedaria transmitiendo por su cuenta.
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

    # 2) Red de seguridad: cualquier ffmpeg de esta carpeta que
    #    haya quedado huerfano (por ejemplo si se reinicio la
    #    interfaz o se perdio el archivo de PID).
    foreach ($p in (Procesos-Servidor)) {
        & taskkill.exe /PID $p.Id /T /F 2>&1 | Out-Null
        $mato = $true
    }

    return $mato
}

# ------------------------------------------------------------
#  Historial de IPs
# ------------------------------------------------------------
#  Se juntan las dos fuentes: el historial propio de esta
#  interfaz y el deck_ip.txt que escribe el .bat cuando lo abren
#  a mano. Asi una IP tecleada en la consola tambien aparece
#  despues en el combo, sin sincronizar nada.
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
    # La elegida queda primera; el resto detras, sin repetir. Se
    # cortan a 8 para que el combo no se vuelva un basurero.
    # El @() de afuera importa: sin el, si no hay previas, la suma
    # con $null mete un elemento vacio y el archivo queda con una
    # linea en blanco arriba.
    $previas = @(Leer-Ips | Where-Object { $_ -ne $ip })
    $nuevas  = @(@($ip) + $previas | Select-Object -First 8)
    Set-Content -Path $ArchivoIps -Value $nuevas -Encoding Ascii
    Set-Content -Path $ArchivoIp  -Value $ip     -Encoding Ascii
}

# ------------------------------------------------------------
#  Modos de captura
# ------------------------------------------------------------
#  Las claves (mjpeg720, etc.) tienen que coincidir con la tabla
#  de modos de start_server_stream.bat. Los fps de cada uno NO
#  son inventados: salen del listado real de la capturadora,
#  medido con listar_modos.bat (ver listar_modos_log.txt).
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

# ------------------------------------------------------------
#  Ventana
# ------------------------------------------------------------
$form                 = New-Object System.Windows.Forms.Form
$form.Text            = "Remote Play - Servidor"
$form.Size            = New-Object System.Drawing.Size(520, 470)
$form.StartPosition   = "CenterScreen"
$form.FormBorderStyle = "FixedDialog"
$form.MaximizeBox     = $false
$form.Font            = New-Object System.Drawing.Font("Segoe UI", 9)

$lblEstado           = New-Object System.Windows.Forms.Label
$lblEstado.Location  = New-Object System.Drawing.Point(20, 18)
$lblEstado.Size      = New-Object System.Drawing.Size(460, 26)
$lblEstado.TextAlign = "MiddleCenter"
$lblEstado.BorderStyle = "FixedSingle"
$lblEstado.Font      = New-Object System.Drawing.Font("Segoe UI", 9, [System.Drawing.FontStyle]::Bold)
$form.Controls.Add($lblEstado)

$lblIp          = New-Object System.Windows.Forms.Label
$lblIp.Text     = "IP de la Steam Deck"
$lblIp.Location = New-Object System.Drawing.Point(20, 60)
$lblIp.Size     = New-Object System.Drawing.Size(300, 20)
$form.Controls.Add($lblIp)

# DropDown (no DropDownList) a proposito: lista las guardadas
# pero deja escribir una nueva encima.
$cmbIp               = New-Object System.Windows.Forms.ComboBox
$cmbIp.Location      = New-Object System.Drawing.Point(20, 82)
$cmbIp.Size          = New-Object System.Drawing.Size(460, 24)
$cmbIp.DropDownStyle = "DropDown"
foreach ($ip in (Leer-Ips)) { [void]$cmbIp.Items.Add($ip) }
$cmbIp.SelectedIndex = 0
$form.Controls.Add($cmbIp)

$lblPista           = New-Object System.Windows.Forms.Label
$lblPista.Text      = "Elige una guardada o escribe otra. Para verla en la Deck:  ip -4 addr show wlan0"
$lblPista.Location  = New-Object System.Drawing.Point(20, 110)
$lblPista.Size      = New-Object System.Drawing.Size(460, 18)
$lblPista.ForeColor = [System.Drawing.Color]::DimGray
$form.Controls.Add($lblPista)

$lblModo          = New-Object System.Windows.Forms.Label
$lblModo.Text     = "Resolucion / modo de captura"
$lblModo.Location = New-Object System.Drawing.Point(20, 145)
$lblModo.Size     = New-Object System.Drawing.Size(300, 20)
$form.Controls.Add($lblModo)

$cmbModo               = New-Object System.Windows.Forms.ComboBox
$cmbModo.Location      = New-Object System.Drawing.Point(20, 167)
$cmbModo.Size          = New-Object System.Drawing.Size(460, 24)
$cmbModo.DropDownStyle = "DropDownList"
foreach ($m in $Modos) { [void]$cmbModo.Items.Add($m.Nombre) }
$form.Controls.Add($cmbModo)

# Cajita que explica el modo seleccionado. Es el lugar donde vive
# el "por que" de cada opcion, para no elegir a ciegas ni tener
# que abrir el .bat a leer comentarios.
$txtAyuda             = New-Object System.Windows.Forms.TextBox
$txtAyuda.Location    = New-Object System.Drawing.Point(20, 199)
$txtAyuda.Size        = New-Object System.Drawing.Size(460, 68)
$txtAyuda.Multiline   = $true
$txtAyuda.ReadOnly    = $true
$txtAyuda.BorderStyle = "FixedSingle"
$txtAyuda.BackColor   = [System.Drawing.Color]::WhiteSmoke
$form.Controls.Add($txtAyuda)

$cmbModo.Add_SelectedIndexChanged({
    $txtAyuda.Text = $Modos[$cmbModo.SelectedIndex].Ayuda
})

# Preseleccion: el ultimo modo usado, o el recomendado.
$indice = 0
if (Test-Path $ArchivoModo) {
    $guardado = (Get-Content $ArchivoModo -First 1 -ErrorAction SilentlyContinue)
    if ($guardado) {
        $guardado = $guardado.Trim()
        for ($i = 0; $i -lt $Modos.Count; $i++) {
            if ($Modos[$i].Clave -eq $guardado) { $indice = $i }
        }
    }
}
$cmbModo.SelectedIndex = $indice

$lblNota           = New-Object System.Windows.Forms.Label
$lblNota.Text      = "El servidor corre oculto, sin ventana negra. Puedes cerrar esta ventana y sigue transmitiendo. Al iniciar de nuevo, la instancia anterior se cierra sola."
$lblNota.Location  = New-Object System.Drawing.Point(20, 277)
$lblNota.Size      = New-Object System.Drawing.Size(460, 50)
$lblNota.ForeColor = [System.Drawing.Color]::DimGray
$form.Controls.Add($lblNota)

$btnIniciar          = New-Object System.Windows.Forms.Button
$btnIniciar.Location = New-Object System.Drawing.Point(20, 340)
$btnIniciar.Size     = New-Object System.Drawing.Size(180, 36)
$form.Controls.Add($btnIniciar)
$form.AcceptButton = $btnIniciar

$btnDetener          = New-Object System.Windows.Forms.Button
$btnDetener.Text     = "Detener servidor"
$btnDetener.Location = New-Object System.Drawing.Point(212, 340)
$btnDetener.Size     = New-Object System.Drawing.Size(150, 36)
$form.Controls.Add($btnDetener)

$btnCerrar          = New-Object System.Windows.Forms.Button
$btnCerrar.Text     = "Cerrar"
$btnCerrar.Location = New-Object System.Drawing.Point(374, 340)
$btnCerrar.Size     = New-Object System.Drawing.Size(106, 36)
$btnCerrar.Add_Click({ $form.Close() })
$form.Controls.Add($btnCerrar)
$form.CancelButton = $btnCerrar

$lblLogs           = New-Object System.Windows.Forms.LinkLabel
$lblLogs.Text      = "Ver los logs de la ultima corrida"
$lblLogs.Location  = New-Object System.Drawing.Point(20, 388)
$lblLogs.Size      = New-Object System.Drawing.Size(300, 20)
$lblLogs.Add_LinkClicked({
    $carpeta = Join-Path $Aqui "logs"
    if (Test-Path $carpeta) { Start-Process explorer.exe $carpeta }
    else {
        [System.Windows.Forms.MessageBox]::Show(
            "Todavia no hay logs: se crean en la primera corrida.",
            "Remote Play", "OK", "Information") | Out-Null
    }
})
$form.Controls.Add($lblLogs)

function Refrescar-Estado {
    if (Servidor-Corriendo) {
        $lblEstado.Text      = "SERVIDOR CORRIENDO  (oculto, en segundo plano)"
        $lblEstado.BackColor = [System.Drawing.Color]::FromArgb(215, 244, 215)
        $lblEstado.ForeColor = [System.Drawing.Color]::DarkGreen
        $btnIniciar.Text     = "Reiniciar servidor"
        $btnDetener.Enabled  = $true
    } else {
        $lblEstado.Text      = "Detenido"
        $lblEstado.BackColor = [System.Drawing.Color]::FromArgb(240, 240, 240)
        $lblEstado.ForeColor = [System.Drawing.Color]::DimGray
        $btnIniciar.Text     = "Iniciar servidor"
        $btnDetener.Enabled  = $false
    }
}

$btnDetener.Add_Click({
    if (Detener-Servidor) {
        Refrescar-Estado
    } else {
        Refrescar-Estado
        [System.Windows.Forms.MessageBox]::Show(
            "No habia ningun servidor corriendo.",
            "Remote Play", "OK", "Information") | Out-Null
    }
})

$btnIniciar.Add_Click({
    $ip = $cmbIp.Text.Trim()

    # Misma validacion floja que el .bat: 4 grupos de digitos. No
    # valida rangos, solo atrapa dedazos. Vale la pena atraparlos
    # aqui porque una IP mal escrita no da NINGUN error visible:
    # ffmpeg manda UDP feliz al vacio y en la Deck se ve pantalla
    # negra, que es de lo que mas costo darse cuenta en su momento.
    if ($ip -notmatch $RegexIp) {
        [System.Windows.Forms.MessageBox]::Show(
            "`"$ip`" no parece una IP.`n`nTiene que ser algo como 192.168.0.141",
            "IP invalida", "OK", "Warning") | Out-Null
        return
    }

    $modo = $Modos[$cmbModo.SelectedIndex].Clave

    $btnIniciar.Enabled = $false
    $btnDetener.Enabled = $false
    $lblEstado.Text      = "Cerrando la instancia anterior..."
    $lblEstado.BackColor = [System.Drawing.Color]::FromArgb(255, 246, 214)
    $lblEstado.ForeColor = [System.Drawing.Color]::DarkGoldenrod
    [System.Windows.Forms.Application]::DoEvents()

    [void](Detener-Servidor)

    # La capturadora no siempre se libera al instante despues de
    # matar al ffmpeg anterior; si el nuevo la abre demasiado
    # pronto, dshow contesta "device in use" y el arranque falla.
    Start-Sleep -Milliseconds 900

    Guardar-Ip $ip
    Set-Content -Path $ArchivoModo -Value $modo -Encoding Ascii

    # Los procesos hijos heredan el entorno del padre, asi que con
    # esto alcanza para que el .bat las vea.
    $env:PS3RP_IP   = $ip
    $env:PS3RP_MODO = $modo
    $env:PS3RP_GUI  = "1"

    $lblEstado.Text = "Iniciando..."
    [System.Windows.Forms.Application]::DoEvents()

    $proc = Start-Process -FilePath $Bat -WorkingDirectory $Aqui -WindowStyle Hidden -PassThru
    Set-Content -Path $ArchivoPid -Value $proc.Id -Encoding Ascii

    # Esperar a que ffmpeg aparezca de verdad. No es capricho:
    # abrir la capturadora en MJPEG tarda varios segundos, y antes
    # de eso el .bat todavia esta detectando dispositivos con
    # PowerShell. Sin esta espera, la interfaz diria "corriendo"
    # aunque hubiera fallado. Se usa DoEvents en vez de un
    # Start-Sleep largo para que la ventana no se congele.
    $arranco = $false
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Milliseconds 500
        [System.Windows.Forms.Application]::DoEvents()
        if (Servidor-Corriendo) { $arranco = $true; break }
    }

    $btnIniciar.Enabled = $true
    Refrescar-Estado

    if (-not $arranco) {
        # Dejar rastro de POR QUE se concluyo que no arranco, para poder
        # diagnosticarlo despues sin tener que reproducirlo en vivo.
        try {
            $dbg = @()
            $dbg += "fecha: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
            $dbg += "sesion de esta ventana: $((Get-Process -Id $PID).SessionId)"
            $procs = @(Get-Process -Name 'ffmpeg' -ErrorAction SilentlyContinue)
            $dbg += "Get-Process ffmpeg encontro: $($procs.Count)"
            foreach ($q in $procs) {
                $ruta = 'NO SE PUDO LEER'
                try { if ($q.Path) { $ruta = $q.Path } } catch { $ruta = "ERROR: $($_.Exception.Message)" }
                $dbg += "  pid=$($q.Id) sesion=$($q.SessionId) ruta=$ruta"
            }
            $dbg += "FfmpegExe esperado: $FfmpegExe"
            $dbg += "Procesos-Servidor devolvio: $((Procesos-Servidor | Measure-Object).Count)"
            $ultimo = Get-ChildItem "$Aqui\logs\progreso-*.log" -ErrorAction SilentlyContinue |
                      Sort-Object LastWriteTime -Descending | Select-Object -First 1
            if ($ultimo) { $dbg += "ultimo progreso log: $($ultimo.Name) $($ultimo.Length) bytes, $($ultimo.LastWriteTime)" }
            $dbg -join "`r`n" | Set-Content "$Aqui\diagnostico_no_arranco.txt" -Encoding UTF8
        } catch { }

        $lblEstado.Text      = "No arranco"
        $lblEstado.BackColor = [System.Drawing.Color]::FromArgb(255, 224, 224)
        $lblEstado.ForeColor = [System.Drawing.Color]::DarkRed
        [System.Windows.Forms.MessageBox]::Show(
            "El servidor no llego a arrancar en 15 segundos.`n`nLo mas comun es que la capturadora este desconectada o que Windows le haya cambiado el nombre al cambiarla de puerto USB.`n`nRevisa los logs con el enlace de abajo, o abre start_server_stream.bat a mano (con la ventana visible) para ver el error.",
            "Remote Play", "OK", "Warning") | Out-Null
    }
})

Refrescar-Estado
[void]$form.ShowDialog()
