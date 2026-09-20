package com.projectsconsoles.remoteplay

import android.os.Process
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.util.concurrent.locks.LockSupport

/**
 * Manda el estado del mando al ESP32 por UDP (un JSON por datagrama, como la Deck y la Ally), a la
 * frecuencia configurada (120 Hz por defecto: el firmware reporta cada ~8 ms).
 */
class InputSender(
    private val estado: GamepadState,
    private val ip: String,
    private val puerto: Int,
    private val hz: Int,
    acorde: String,
) : Thread("input-sender") {

    @Volatile var corriendo = true
    @Volatile var enviados = 0L
    @Volatile var errores = 0L
    @Volatile var ultimoError: String? = null

    private val chord = PsChord(acorde)

    override fun run() {
        Process.setThreadPriority(Process.THREAD_PRIORITY_URGENT_AUDIO)
        val destino = try {
            InetAddress.getByName(ip)
        } catch (e: Exception) {
            ultimoError = "IP del ESP32 invalida ($ip)"
            return
        }
        try {
            DatagramSocket().use { s ->
                s.trafficClass = 0xB8 // EF: prioridad baja latencia, si la red la respeta
                val periodo = 1_000_000_000L / hz.coerceIn(30, 250)
                val t0 = System.nanoTime()
                var siguiente = t0
                while (corriendo) {
                    val ahora = System.nanoTime()
                    val json = estado.toJson(chord, ahora, (ahora - t0) / 1e9)
                    val bytes = json.toByteArray(Charsets.US_ASCII)
                    try {
                        s.send(DatagramPacket(bytes, bytes.size, destino, puerto))
                        enviados++
                    } catch (e: Exception) {
                        errores++
                        ultimoError = e.message
                    }
                    siguiente += periodo
                    val espera = siguiente - System.nanoTime()
                    if (espera > 0) LockSupport.parkNanos(espera) else siguiente = System.nanoTime()
                }
            }
        } catch (e: Exception) {
            ultimoError = e.message
        }
    }

    fun detener() {
        corriendo = false
        interrupt()
    }
}
