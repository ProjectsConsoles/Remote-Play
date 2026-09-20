package com.projectsconsoles.remoteplay

import org.json.JSONObject
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.Inet4Address
import java.net.InetAddress
import java.net.NetworkInterface
import java.net.SocketTimeoutException

object Net {
    /** IP de esta tableta en la red local, o null. Se llama desde un hilo de fondo. */
    fun ipLocal(): String? {
        // El truco del socket UDP "conectado": no manda nada, solo deja que el sistema elija la interfaz.
        try {
            DatagramSocket().use { s ->
                s.connect(InetAddress.getByName("8.8.8.8"), 53)
                val ip = s.localAddress?.hostAddress
                if (ip != null && ip != "0.0.0.0") return ip
            }
        } catch (_: Exception) {
        }
        try {
            for (ni in NetworkInterface.getNetworkInterfaces()) {
                if (!ni.isUp || ni.isLoopback) continue
                for (a in ni.inetAddresses) {
                    if (a is Inet4Address && !a.isLoopbackAddress) return a.hostAddress
                }
            }
        } catch (_: Exception) {
        }
        return null
    }
}

/** Protocolo de configuracion del servidor Windows (config_listener.ps1): un JSON por datagrama, UDP 9200. */
object ServerClient {
    const val PUERTO = 9200
    private const val TIMEOUT_MS = 3000
    /** set_config con el servidor corriendo lo reinicia de verdad y puede tardar (ver server_udp.py). */
    private const val TIMEOUT_APLICAR_MS = 20000

    sealed class Resp {
        class Ok(val json: JSONObject) : Resp()
        class Error(val mensaje: String) : Resp()
    }

    private fun preguntar(ip: String, cmd: JSONObject, timeoutMs: Int): Resp {
        return try {
            DatagramSocket().use { s ->
                s.soTimeout = timeoutMs
                val out = cmd.toString().toByteArray(Charsets.UTF_8)
                s.send(DatagramPacket(out, out.size, InetAddress.getByName(ip), PUERTO))
                val buf = ByteArray(4096)
                val p = DatagramPacket(buf, buf.size)
                s.receive(p)
                Resp.Ok(JSONObject(String(p.data, 0, p.length, Charsets.UTF_8)))
            }
        } catch (_: SocketTimeoutException) {
            Resp.Error("Sin respuesta del servidor (timeout). ¿Esta prendido y en la misma red?")
        } catch (e: Exception) {
            Resp.Error("Error de red: ${e.message}")
        }
    }

    fun obtenerConfig(ip: String) = preguntar(ip, JSONObject().put("cmd", "get_config"), TIMEOUT_MS)

    fun aplicarConfig(ip: String, ipDeEsteEquipo: String, modo: String) = preguntar(
        ip,
        JSONObject().put("cmd", "set_config").put("ip", ipDeEsteEquipo).put("modo", modo),
        TIMEOUT_APLICAR_MS,
    )

    fun detenerServidor(ip: String) = preguntar(ip, JSONObject().put("cmd", "stop_server"), TIMEOUT_APLICAR_MS)

    /** clave del servidor -> nombre para mostrar (los mismos de la Deck). */
    val MODOS: List<Pair<String, String>> = listOf(
        "mjpeg720" to "1280x720 - MJPEG (recomendado)",
        "mjpeg1080" to "1920x1080 - MJPEG (mas nitido)",
        "crudo480" to "720x480 - SIN COMPRIMIR (prueba)",
        "crudo640" to "640x480 - SIN COMPRIMIR (prueba)",
        "crudo720" to "1280x720 - SIN COMPRIMIR (Hagibis)",
    )
}
