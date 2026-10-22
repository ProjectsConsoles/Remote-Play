package com.projectsconsoles.remoteplay

import org.json.JSONObject
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.util.concurrent.Executors

/**
 * Calidad adaptativa del servidor de PC (2026-10-22): cada 0.5 s le cuenta a la PC como esta llegando el
 * video (comando "red" al puerto 9200, sin respuesta). Si se pierden paquetes o los cuadros llegan
 * desparejos, la PC baja la calidad un rato en vez de que la imagen se congele (pc_server.ControlCalidad).
 */
class ReporteRed(private val ip: String) {
    // la red no puede ir en el hilo de la interfaz: un solo hilo de fondo, en orden
    private val hilo = Executors.newSingleThreadExecutor()
    private var sock: DatagramSocket? = null

    fun mandar(perdidos: Long, jitterMs: Double, entradaMaxMs: Double, kbps: Double) {
        val datos = JSONObject()
            .put("cmd", "red")
            .put("perdidos", perdidos)
            .put("jitter_ms", jitterMs)
            .put("entrada_ms", entradaMaxMs)
            .put("kbps", kbps)
            .toString().toByteArray(Charsets.UTF_8)
        try {
            hilo.execute {
                try {
                    val s = sock ?: DatagramSocket().also { sock = it }
                    s.send(DatagramPacket(datos, datos.size, InetAddress.getByName(ip), ServerClient.PUERTO))
                } catch (_: Exception) {
                    // un reporte perdido no importa: llega otro en medio segundo
                }
            }
        } catch (_: Exception) {
            // ya cerrado
        }
    }

    fun cerrar() {
        try {
            hilo.execute { sock?.close() }
        } catch (_: Exception) {
        }
        hilo.shutdown()
    }
}
