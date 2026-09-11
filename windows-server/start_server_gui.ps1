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
#
#  2026-09-11: la logica de arranque/parada/config vive ahora en
#  server_engine_lib.ps1 (compartida con config_listener.ps1, el
#  escucha que deja configurar esto mismo desde la Deck) - ver ese
#  archivo para Procesos-Servidor/Servidor-Corriendo/Detener-Servidor/
#  Iniciar-Servidor/$Modos. Esta ventana ya no define nada de eso.
# ============================================================

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

$Aqui = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $Aqui "server_engine_lib.ps1")

if (-not (Test-Path $Bat)) {
    [System.Windows.Forms.MessageBox]::Show(
        "No encontre start_server_stream.bat en:`n$Aqui`n`nLos dos archivos tienen que estar en la misma carpeta.",
        "Remote Play", "OK", "Error") | Out-Null
    exit 1
}

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

# Icono real del proyecto (2026-09-11), el mismo de branding/deck-client -
# antes la ventana usaba el icono generico de PowerShell.
$IconoArchivo = Join-Path $Aqui "server_icon.ico"
if (Test-Path $IconoArchivo) {
    try { $form.Icon = New-Object System.Drawing.Icon($IconoArchivo) } catch {}
}

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
$lblNota.Text      = "El servidor corre oculto, sin ventana negra. Puedes cerrar esta ventana y sigue transmitiendo. Al iniciar de nuevo, la instancia anterior se cierra sola. Tambien se puede configurar en remoto desde el menu de la Deck."
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
    # Cierra la ventana tambien (2026-09-11, pedido explicito): antes solo
    # actualizaba el estado y se quedaba abierta con el boton ya deshabilitado
    # - "Detener servidor" ahora es un stop-y-cierra, igual de directo que el
    # boton "Cerrar" pero deteniendo el motor primero.
    if (Detener-Servidor) {
        $form.Close()
    } else {
        Refrescar-Estado
        [System.Windows.Forms.MessageBox]::Show(
            "No habia ningun servidor corriendo.",
            "Remote Play", "OK", "Information") | Out-Null
        $form.Close()
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

    $avisar = {
        param($msg)
        $lblEstado.Text      = $msg
        $lblEstado.BackColor = [System.Drawing.Color]::FromArgb(255, 246, 214)
        $lblEstado.ForeColor = [System.Drawing.Color]::DarkGoldenrod
        [System.Windows.Forms.Application]::DoEvents()
    }

    $arranco = Iniciar-Servidor $ip $modo $avisar

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

# Refresco de config aplicada en remoto (2026-09-11): config_listener.ps1
# corre en OTRO proceso, asi que si la Deck cambia el modo/IP mientras esta
# ventana esta abierta, deck_modo.txt/deck_ip.txt cambian en disco pero esta
# GUI (que solo leyo esos archivos UNA vez, al abrir) se queda mostrando lo
# viejo aunque el cambio remoto se haya aplicado bien de verdad - "no se
# actualiza el combo, a pesar de que se aplique bien la configuracion"
# (reportado el mismo dia). Un timer cada 2s vuelve a leer esos archivos y
# sincroniza el combo/la IP si cambiaron desde la ultima vuelta - sin pisar
# el cuadro de IP mientras el usuario lo esta editando a mano (-not Focused).
$script:UltimoModoVisto = $Modos[$cmbModo.SelectedIndex].Clave
$script:UltimaIpVista   = $cmbIp.Text

$timerRefrescoRemoto = New-Object System.Windows.Forms.Timer
$timerRefrescoRemoto.Interval = 2000
$timerRefrescoRemoto.Add_Tick({
    $modoActual = $null
    if (Test-Path $ArchivoModo) { $modoActual = (Get-Content $ArchivoModo -First 1 -ErrorAction SilentlyContinue) }
    if ($modoActual) {
        $modoActual = $modoActual.Trim()
        if ($modoActual -ne $script:UltimoModoVisto) {
            $script:UltimoModoVisto = $modoActual
            for ($i = 0; $i -lt $Modos.Count; $i++) {
                if ($Modos[$i].Clave -eq $modoActual) {
                    $cmbModo.SelectedIndex = $i
                    break
                }
            }
        }
    }

    $ipActual = $null
    if (Test-Path $ArchivoIp) { $ipActual = (Get-Content $ArchivoIp -First 1 -ErrorAction SilentlyContinue) }
    if ($ipActual) {
        $ipActual = $ipActual.Trim()
        if ($ipActual -ne $script:UltimaIpVista) {
            $script:UltimaIpVista = $ipActual
            if (-not $cmbIp.Focused) { $cmbIp.Text = $ipActual }
        }
    }

    Refrescar-Estado
})
$timerRefrescoRemoto.Start()

Refrescar-Estado
[void]$form.ShowDialog()
