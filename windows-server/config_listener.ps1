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

# Auto-matar la instancia anterior al arrancar (2026-09-11, pedido explicito
# tras un bug real en produccion): este proceso se lanza con
# CREATE_BREAKAWAY_FROM_JOB desde server_launcher.py para que sobreviva a
# quien lo lanzo - pero eso mismo significa que si algo sale mal (una version
# vieja con un bug, o un reinicio manual sin cerrar bien) el proceso viejo
# puede quedar corriendo para siempre, indetectable desde fuera (nada anuncia
# que es "el config_listener viejo") y a veces IMPOSIBLE de matar por SSH si
# la sesion que lo lanzo no es la misma con la que se intenta pararlo -
# confirmado en vivo: un PID asi devolvia "Acceso denegado" al pedirle
# Stop-Process, mientras seguia rellenando el log de errores para siempre.
# La unica limpieza confiable es que CADA arranque nuevo mate al anterior EL
# MISMO, con sus propios permisos (mismo usuario que lo lanzo la vez pasada,
# asi que Stop-Process si le alcanza). Se guarda el PID propio en un archivo
# y, si ya habia uno vivo, se le pide que se detenga antes de tocar el
# socket - asi nunca hay dos instancias peleando (o zombies) por el puerto.
$ArchivoListenerPid = Join-Path $Aqui "logs\config_listener.pid"
if (Test-Path $ArchivoListenerPid) {
    $pidAnterior = Get-Content $ArchivoListenerPid -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($pidAnterior) {
        $procAnterior = Get-Process -Id $pidAnterior -ErrorAction SilentlyContinue
        if ($procAnterior -and $procAnterior.ProcessName -eq "powershell") {
            try {
                Stop-Process -Id $pidAnterior -Force -ErrorAction Stop
                Log "Instancia anterior (PID $pidAnterior) detenida al arrancar."
            } catch {
                Log "No se pudo detener la instancia anterior (PID $pidAnterior): $($_.Exception.Message)"
            }
        }
    }
}
Set-Content -Path $ArchivoListenerPid -Value $PID -Encoding Ascii

Log "=== config_listener arrancando en el puerto $PuertoConfig (PID $PID) ==="

# try/catch explicito (2026-09-11, bug real encontrado con hardware real):
# si el puerto ya esta tomado (otra instancia de este mismo script sigue
# viva - normal si el usuario reabre el lanzador sin haber cerrado sesion
# de Windows antes), New-Object lanza una excepcion NO terminante por
# default en PowerShell. Sin este try/catch, la excepcion se perdia en
# silencio (stderr va a DEVNULL desde server_launcher.py) y $udp quedaba
# $null - el bucle de abajo entraba igual y explotaba PARA SIEMPRE, una vez
# por segundo, con "No se puede llamar a un metodo en una expresion con
# valor NULL", sin dar ninguna pista de la causa real. Ahora se detecta y
# se sale con un mensaje claro: no hace falta arreglar nada, ya hay un
# listener corriendo.
try {
    $udp = New-Object System.Net.Sockets.UdpClient($PuertoConfig)
} catch {
    Log "No se pudo tomar el puerto $PuertoConfig (probablemente ya hay otro config_listener corriendo): $($_.Exception.Message)"
    exit 1
}
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
    # transmitiendo (2026-09-11): "corriendo" solo dice que EXISTE un proceso
    # ffmpeg, y eso puede mentir feo - un ffmpeg colgado por la capturadora
    # ocupada existe pero no manda un solo paquete. Los clientes usan este
    # campo nuevo para no lanzarse a esperar un video que no va a llegar (y
    # los que no lo conozcan simplemente lo ignoran, sin romperse).
    return [pscustomobject]@{
        ok            = $true
        ip            = $ipActual
        modo          = $modoActual
        corriendo     = (Servidor-Corriendo)
        transmitiendo = (Servidor-Transmitiendo)
        modos         = @($Modos | ForEach-Object { $_.Clave })
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
            "stop_server" {
                # Apagar sin reiniciar (2026-09-17, pedido en los dos
                # clientes): a diferencia de set_config (que siempre vuelve
                # a arrancar), esto solo detiene el motor si estaba
                # corriendo - Detener-Servidor ya existe en
                # server_engine_lib.ps1 (lo usa Iniciar-Servidor antes de
                # cada reinicio), no hace falta logica nueva del lado de
                # Windows.
                if (Servidor-Corriendo) {
                    Log "deteniendo servidor por pedido remoto"
                    [void](Detener-Servidor)
                    Enviar-Respuesta ([pscustomobject]@{ ok = $true; aplicado = "detenido" }) $origen
                } else {
                    Enviar-Respuesta ([pscustomobject]@{ ok = $true; aplicado = "ya_estaba_detenido" }) $origen
                }
            }
            default {
                Enviar-Respuesta ([pscustomobject]@{ ok = $false; error = "comando desconocido: $($cmd.cmd)" }) $origen
            }
        }
    } catch {
        $detalle = $_.Exception.GetType().FullName
        $interna = if ($_.Exception.InnerException) { " | interna: $($_.Exception.InnerException.GetType().FullName) -- $($_.Exception.InnerException.Message)" } else { "" }
        Log "ERROR en el bucle principal [linea $($_.InvocationInfo.ScriptLineNumber)] ($detalle): $($_.Exception.Message)$interna | udp null? $($udp -eq $null)"
        Start-Sleep -Seconds 1
    }
}
