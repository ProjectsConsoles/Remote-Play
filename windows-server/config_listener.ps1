# ============================================================
#  config_listener.ps1 - deja configurar el servidor desde la Deck
# ============================================================
#  Escucha UDP en el puerto 9200 (PS3RP_CONFIG_PORT) y entiende dos
#  comandos, mandados como JSON en un solo datagrama:
#
#    {"cmd":"get_config"}
#      -> responde con la config actual (ip, modo, corriendo, modos
#         validos) para que la pantalla de la Deck sepa que mostrar
#         al abrirse.
#
#    {"cmd":"set_config","ip":"192.168.0.141","modo":"mjpeg720"}
#      -> si el servidor YA esta corriendo, lo reinicia con la config
#         nueva (usa Iniciar-Servidor, que detiene + arranca - el
#         mismo camino que el boton Iniciar de la ventana). Si NO
#         esta corriendo, solo GUARDA la config para la proxima vez
#         que se le de Iniciar (no arranca nada de la nada: eso lo
#         sigue decidiendo el usuario en la PC).
#
#  Responde siempre al MISMO puerto+IP de quien mando el paquete
#  (patron pedido/respuesta UDP simple, sin conexion).
#
#  POR QUE UN PROCESO APARTE (no dentro de start_server_gui.ps1):
#  la ventana se puede cerrar y el motor sigue transmitiendo (ver la
#  nota de start_server_gui.ps1) - si el escucha viviera solo dentro
#  del proceso de la ventana, cerrar la ventana tambien apagaria la
#  posibilidad de configurar en remoto. Este script no depende de
#  ninguna ventana: lo lanza server_launcher.py junto con la GUI y
#  se queda corriendo indefinidamente.
#
#  Reutiliza server_engine_lib.ps1 para todo lo que toca al motor -
#  ver la nota de esa libreria sobre por que no se reimplementa nada
#  de ffmpeg aqui tampoco.
# ============================================================

$Aqui = $PSScriptRoot
. (Join-Path $Aqui "server_engine_lib.ps1")

$PuertoConfig = 9200
$LogArchivo = Join-Path $Aqui "logs\config_listener.log"
New-Item -ItemType Directory -Force -Path (Join-Path $Aqui "logs") | Out-Null

function Log($msg) {
    $linea = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $msg"
    Add-Content -Path $LogArchivo -Value $linea -Encoding UTF8
}

Log "=== config_listener arrancando en el puerto $PuertoConfig ==="

$udp = New-Object System.Net.Sockets.UdpClient($PuertoConfig)
$origen = New-Object System.Net.IPEndPoint([System.Net.IPAddress]::Any, 0)

function Enviar-Respuesta($obj, [System.Net.IPEndPoint]$destino) {
    $json = $obj | ConvertTo-Json -Compress
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
    [void]$udp.Send($bytes, $bytes.Length, $destino)
}

function Estado-Actual {
    # [string](...) explicito (2026-09-11): Get-Content devuelve el texto
    # decorado con propiedades ETS (PSPath, PSParentPath, etc.), y sin este
    # cast ConvertTo-Json serializa TODO ese objeto en vez del texto plano -
    # medido contra la Deck real: $resp.ip llegaba como un diccionario con
    # rutas de archivo adentro, no como "192.168.0.141".
    $ipActual = ""
    if (Test-Path $ArchivoIp) { $ipActual = [string](Get-Content $ArchivoIp -First 1 -ErrorAction SilentlyContinue) }
    $modoActual = ""
    if (Test-Path $ArchivoModo) { $modoActual = [string](Get-Content $ArchivoModo -First 1 -ErrorAction SilentlyContinue) }
    return [pscustomobject]@{
        ok        = $true
        ip        = $ipActual
        modo      = $modoActual
        corriendo = (Servidor-Corriendo)
        modos     = @($Modos | ForEach-Object { $_.Clave })
    }
}

while ($true) {
    try {
        $bytes = $udp.Receive([ref]$origen)
        $texto = [System.Text.Encoding]::UTF8.GetString($bytes)
        Log "recibido de $($origen.Address):$($origen.Port) -> $texto"

        $cmd = $null
        try { $cmd = $texto | ConvertFrom-Json } catch {
            Log "JSON invalido: $($_.Exception.Message)"
            Enviar-Respuesta ([pscustomobject]@{ ok = $false; error = "JSON invalido" }) $origen
            continue
        }

        switch ($cmd.cmd) {
            "get_config" {
                Enviar-Respuesta (Estado-Actual) $origen
            }
            "set_config" {
                $ip = "$($cmd.ip)"
                $modo = "$($cmd.modo)"

                if ($ip -notmatch $RegexIp) {
                    Enviar-Respuesta ([pscustomobject]@{ ok = $false; error = "IP invalida: $ip" }) $origen
                    continue
                }
                if (-not (Modo-Valido $modo)) {
                    Enviar-Respuesta ([pscustomobject]@{ ok = $false; error = "modo invalido: $modo" }) $origen
                    continue
                }

                if (Servidor-Corriendo) {
                    Log "servidor corriendo -> reiniciando con ip=$ip modo=$modo"
                    $arranco = Iniciar-Servidor $ip $modo
                    if ($arranco) {
                        Enviar-Respuesta ([pscustomobject]@{ ok = $true; aplicado = "reiniciado"; ip = $ip; modo = $modo }) $origen
                    } else {
                        Enviar-Respuesta ([pscustomobject]@{ ok = $false; error = "se guardo pero no arranco en 15s - revisa la capturadora" }) $origen
                    }
                } else {
                    Log "servidor detenido -> guardando ip=$ip modo=$modo para la proxima"
                    [void](Guardar-Configuracion $ip $modo)
                    Enviar-Respuesta ([pscustomobject]@{ ok = $true; aplicado = "guardado_para_proxima_vez"; ip = $ip; modo = $modo }) $origen
                }
            }
            default {
                Enviar-Respuesta ([pscustomobject]@{ ok = $false; error = "comando desconocido: $($cmd.cmd)" }) $origen
            }
        }
    } catch {
        Log "ERROR en el bucle principal: $($_.Exception.Message)"
        Start-Sleep -Seconds 1
    }
}
