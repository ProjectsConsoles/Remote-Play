package com.projectsconsoles.remoteplay

import android.os.Process
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetSocketAddress
import java.net.SocketTimeoutException

/** Recibe el video/audio por UDP y se lo pasa al demultiplexor. */
class StreamReceiver(
    private val puerto: Int,
    private val demux: TsDemuxer,
) : Thread("stream-rx") {

    @Volatile var corriendo = true
    @Volatile var ultimoPaqueteNs = System.nanoTime()
    @Volatile var paquetes = 0L
    @Volatile var bytes = 0L
    @Volatile var error: String? = null

    /** Se llama (desde este hilo) al volver a llegar datos tras un corte de mas de 1 s. */
    @Volatile var alReanudar: (() -> Unit)? = null

    override fun run() {
        Process.setThreadPriority(Process.THREAD_PRIORITY_URGENT_DISPLAY)
        var sock: DatagramSocket? = null
        try {
            sock = DatagramSocket(null).apply {
                reuseAddress = true
                receiveBufferSize = 1 shl 20
                bind(InetSocketAddress(puerto))
                soTimeout = 200
            }
            val buf = ByteArray(2048)
            val pkt = DatagramPacket(buf, buf.size)
            while (corriendo) {
                pkt.length = buf.size
                try {
                    sock.receive(pkt)
                } catch (_: SocketTimeoutException) {
                    continue
                }
                val ahora = System.nanoTime()
                if (paquetes > 0 && ahora - ultimoPaqueteNs > HUECO_NS) {
                    // Corte largo (p. ej. el servidor se reinicio): lo armado a medias ya no sirve
                    // y el video debe reanudar en el proximo IDR.
                    demux.descartar()
                    alReanudar?.invoke()
                }
                ultimoPaqueteNs = ahora
                paquetes++
                bytes += pkt.length
                demux.feed(buf, 0, pkt.length)
            }
        } catch (e: Exception) {
            error = "No se pudo abrir el puerto UDP $puerto: ${e.message}"
        } finally {
            sock?.close()
        }
    }

    fun detener() {
        corriendo = false
        interrupt()
    }

    companion object {
        private const val HUECO_NS = 1_000_000_000L
    }
}
