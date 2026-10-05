package com.projectsconsoles.remoteplay

import android.media.MediaCodec
import android.media.MediaFormat
import android.os.Build
import android.os.Process
import android.view.Surface

/**
 * Decodifica el H.264 con el decodificador de hardware y lo dibuja en la superficie.
 *
 * Igual que el modo GStreamer de la Deck y la Ally: nada espera a un reloj. Cada cuadro se entrega
 * apenas llega y se dibuja apenas sale, y si el decodificador no tiene lugar para uno nuevo se
 * TIRA (y se espera al siguiente cuadro con SPS/PPS, ver [puedeArrancar]) en vez de acumular retraso.
 */
class VideoPlayer(
    private val superficie: Surface,
    private val alCambiarTamano: (ancho: Int, alto: Int) -> Unit,
) {
    private var codec: MediaCodec? = null
    private var hiloSalida: Thread? = null
    @Volatile private var corriendo = false
    private var sincronizado = false

    @Volatile var cuadrosEntrada = 0L
    @Volatile var cuadrosSalida = 0L
    @Volatile var descartados = 0L
    @Volatile var errores = 0L
    @Volatile var primerCuadro = false
    @Volatile var ultimoError: String? = null

    // Para ubicar las caidas de fps: el mayor hueco entre cuadros desde la ultima lectura, al ENTRAR
    // al decodificador (lo que llega de la red/servidor) y al SALIR a la pantalla. Si solo crece el de
    // salida, el cuello es el decodificador; si crecen los dos, viene de antes (red o captura).
    @Volatile var huecoEntradaMaxNs = 0L
    @Volatile var huecoSalidaMaxNs = 0L
    /** Cuadros dibujados mas de [TIRON_NS] despues del anterior (se ven como un tiron). */
    @Volatile var tirones = 0L
    private var ultEntradaNs = 0L
    private var ultSalidaNs = 0L

    fun iniciar() {
        val formato = MediaFormat.createVideoFormat(MediaFormat.MIMETYPE_VIDEO_AVC, 1280, 720)
        formato.setInteger(MediaFormat.KEY_MAX_INPUT_SIZE, 1 shl 20)
        formato.setInteger(MediaFormat.KEY_PRIORITY, 0) // tiempo real
        formato.setInteger(MediaFormat.KEY_OPERATING_RATE, 120)
        if (Build.VERSION.SDK_INT >= 30) formato.setInteger(MediaFormat.KEY_LOW_LATENCY, 1)
        // Qualcomm (Snapdragon): modo de baja latencia del decodificador; los demas lo ignoran.
        try {
            formato.setInteger("vendor.qti-ext-dec-low-latency.enable", 1)
        } catch (_: Exception) {
        }
        val c = MediaCodec.createDecoderByType(MediaFormat.MIMETYPE_VIDEO_AVC)
        c.configure(formato, superficie, null, 0)
        c.start()
        codec = c
        corriendo = true
        hiloSalida = Thread({ bucleSalida(c) }, "video-salida").also { it.start() }
    }

    /** Se llama desde el hilo de red. El buffer se copia aca mismo. */
    fun encolar(buf: ByteArray, off: Int, size: Int, ptsUs: Long) {
        val c = codec ?: return
        if (!sincronizado) {
            if (!puedeArrancar(buf, off, size)) return
            sincronizado = true
        }
        try {
            val i = c.dequeueInputBuffer(0)
            if (i < 0) {
                descartados++
                sincronizado = false // se perdio un cuadro: reanudar en el proximo que traiga SPS/PPS
                return
            }
            val entrada = c.getInputBuffer(i) ?: return
            entrada.clear()
            if (size > entrada.capacity()) {
                c.queueInputBuffer(i, 0, 0, ptsUs, 0)
                descartados++
                sincronizado = false
                return
            }
            entrada.put(buf, off, size)
            c.queueInputBuffer(i, 0, size, ptsUs, 0)
            cuadrosEntrada++
            val t = System.nanoTime()
            if (ultEntradaNs != 0L && t - ultEntradaNs > huecoEntradaMaxNs) huecoEntradaMaxNs = t - ultEntradaNs
            ultEntradaNs = t
        } catch (e: Exception) {
            errores++
            ultimoError = e.message
            sincronizado = false
        }
    }

    /** Tras un corte largo de red: descartar lo que haya y esperar al proximo cuadro con SPS/PPS. */
    fun reiniciarSincronia() {
        sincronizado = false
    }

    private fun bucleSalida(c: MediaCodec) {
        Process.setThreadPriority(Process.THREAD_PRIORITY_URGENT_DISPLAY)
        val info = MediaCodec.BufferInfo()
        while (corriendo) {
            try {
                val i = c.dequeueOutputBuffer(info, 10_000)
                when {
                    i >= 0 -> {
                        c.releaseOutputBuffer(i, true) // dibujar de inmediato
                        cuadrosSalida++
                        primerCuadro = true
                        val t = System.nanoTime()
                        if (ultSalidaNs != 0L) {
                            val h = t - ultSalidaNs
                            if (h > huecoSalidaMaxNs) huecoSalidaMaxNs = h
                            if (h > TIRON_NS) tirones++
                        }
                        ultSalidaNs = t
                    }
                    i == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED -> {
                        val f = c.outputFormat
                        var w = f.getInteger(MediaFormat.KEY_WIDTH)
                        var h = f.getInteger(MediaFormat.KEY_HEIGHT)
                        // el decodificador puede dar 1088 para 1080: se recorta con estos campos
                        if (f.containsKey("crop-left") && f.containsKey("crop-right") &&
                            f.containsKey("crop-top") && f.containsKey("crop-bottom")
                        ) {
                            w = f.getInteger("crop-right") - f.getInteger("crop-left") + 1
                            h = f.getInteger("crop-bottom") - f.getInteger("crop-top") + 1
                        }
                        alCambiarTamano(w, h)
                    }
                }
            } catch (e: Exception) {
                if (corriendo) {
                    errores++
                    ultimoError = e.message
                }
                break
            }
        }
    }

    fun detener() {
        corriendo = false
        try {
            hiloSalida?.join(500)
        } catch (_: InterruptedException) {
        }
        try {
            codec?.stop()
        } catch (_: Exception) {
        }
        try {
            codec?.release()
        } catch (_: Exception) {
        }
        codec = null
    }

    companion object {
        const val TIRON_NS = 50_000_000L

        /**
         * El decodificador puede (re)arrancar en este cuadro: trae la configuracion del video (SPS = NAL 7
         * y PPS = NAL 8). Con GOP normal eso solo viene en los IDR. Con intra-refresh (servidores desde
         * 2026-10-05) solo el PRIMER cuadro es IDR, pero el servidor repite SPS/PPS en todos: exigir un IDR
         * dejaba la imagen congelada para siempre tras cualquier corte (p. ej. la pantalla de la PC quieta
         * unos segundos) aunque el video siguiera llegando. Arrancando aca la imagen se limpia sola en lo
         * que dura un ciclo de refresco (menos de 1 s).
         */
        fun puedeArrancar(b: ByteArray, off: Int, size: Int): Boolean {
            var sps = false
            var pps = false
            var i = off
            val fin = off + size - 3
            while (i < fin) {
                if (b[i].toInt() == 0 && b[i + 1].toInt() == 0 && b[i + 2].toInt() == 1) {
                    val tipo = b[i + 3].toInt() and 0x1F
                    if (tipo == 7) sps = true
                    if (tipo == 8) pps = true
                    if (sps && pps) return true
                    i += 3
                } else {
                    i++
                }
            }
            return false
        }
    }
}
