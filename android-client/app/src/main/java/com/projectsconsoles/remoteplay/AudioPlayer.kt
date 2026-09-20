package com.projectsconsoles.remoteplay

import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioTrack
import android.media.MediaCodec
import android.media.MediaFormat
import android.os.Process
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * Decodifica el Opus con el decodificador del sistema y lo reproduce con un AudioTrack de baja
 * latencia. Sin reloj: el audio suena apenas llega (como el modo GStreamer de la Deck y la Ally).
 */
class AudioPlayer {
    private var codec: MediaCodec? = null
    private var track: AudioTrack? = null
    private var hiloSalida: Thread? = null
    @Volatile private var corriendo = false

    @Volatile var paquetesEntrada = 0L
    @Volatile var descartados = 0L
    @Volatile var errores = 0L
    @Volatile var ultimoError: String? = null

    fun iniciar() {
        val formato = MediaFormat.createAudioFormat(MediaFormat.MIMETYPE_AUDIO_OPUS, SAMPLE_RATE, CANALES)
        formato.setByteBuffer("csd-0", opusHead())
        formato.setByteBuffer("csd-1", nanosegundos(PRE_SKIP_NS))
        formato.setByteBuffer("csd-2", nanosegundos(SEEK_PRE_ROLL_NS))
        val c = MediaCodec.createDecoderByType(MediaFormat.MIMETYPE_AUDIO_OPUS)
        c.configure(formato, null, null, 0)
        c.start()
        codec = c

        val minimo = AudioTrack.getMinBufferSize(
            SAMPLE_RATE, AudioFormat.CHANNEL_OUT_STEREO, AudioFormat.ENCODING_PCM_16BIT,
        )
        // ~40 ms de buffer, o el minimo del dispositivo si es mayor (el mismo orden que buffer-time=40000 de la Deck)
        val bytes40ms = SAMPLE_RATE * CANALES * 2 * 40 / 1000
        val t = AudioTrack.Builder()
            .setAudioAttributes(
                AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_GAME)
                    .setContentType(AudioAttributes.CONTENT_TYPE_MOVIE)
                    .build(),
            )
            .setAudioFormat(
                AudioFormat.Builder()
                    .setSampleRate(SAMPLE_RATE)
                    .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                    .setChannelMask(AudioFormat.CHANNEL_OUT_STEREO)
                    .build(),
            )
            .setBufferSizeInBytes(maxOf(minimo, bytes40ms))
            .setTransferMode(AudioTrack.MODE_STREAM)
            .setPerformanceMode(AudioTrack.PERFORMANCE_MODE_LOW_LATENCY)
            .build()
        t.play()
        track = t

        corriendo = true
        hiloSalida = Thread({ bucleSalida(c, t) }, "audio-salida").also { it.start() }
    }

    /** Un paquete Opus. Se llama desde el hilo de red; el buffer se copia aca mismo. */
    fun encolar(buf: ByteArray, off: Int, size: Int, ptsUs: Long) {
        val c = codec ?: return
        try {
            val i = c.dequeueInputBuffer(0)
            if (i < 0) {
                descartados++
                return
            }
            val entrada = c.getInputBuffer(i) ?: return
            entrada.clear()
            entrada.put(buf, off, size)
            c.queueInputBuffer(i, 0, size, ptsUs, 0)
            paquetesEntrada++
        } catch (e: Exception) {
            errores++
            ultimoError = e.message
        }
    }

    private fun bucleSalida(c: MediaCodec, t: AudioTrack) {
        Process.setThreadPriority(Process.THREAD_PRIORITY_URGENT_AUDIO)
        val info = MediaCodec.BufferInfo()
        while (corriendo) {
            try {
                val i = c.dequeueOutputBuffer(info, 10_000)
                if (i >= 0) {
                    val salida = c.getOutputBuffer(i)
                    if (salida != null && info.size > 0) {
                        salida.position(info.offset)
                        salida.limit(info.offset + info.size)
                        t.write(salida, info.size, AudioTrack.WRITE_BLOCKING)
                    }
                    c.releaseOutputBuffer(i, false)
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
            track?.stop()
        } catch (_: Exception) {
        }
        try {
            track?.release()
        } catch (_: Exception) {
        }
        try {
            codec?.stop()
        } catch (_: Exception) {
        }
        try {
            codec?.release()
        } catch (_: Exception) {
        }
        track = null
        codec = null
    }

    companion object {
        const val SAMPLE_RATE = 48000
        const val CANALES = 2

        /**
         * Retraso de arranque del codificador (libopus con `-application lowdelay`): 120 muestras a
         * 48 kHz = 2.5 ms. El primer paquete del stream lo trae como "recorte de arranque" (120).
         */
        const val PRE_SKIP_MUESTRAS = 120
        const val PRE_SKIP_NS = PRE_SKIP_MUESTRAS * 1_000_000_000L / SAMPLE_RATE
        const val SEEK_PRE_ROLL_NS = 80_000_000L

        /** Cabecera "OpusHead" (19 bytes) que el decodificador de Android espera como csd-0. */
        fun opusHead(): ByteBuffer {
            val b = ByteBuffer.allocate(19).order(ByteOrder.LITTLE_ENDIAN)
            b.put("OpusHead".toByteArray(Charsets.US_ASCII))
            b.put(1)                          // version
            b.put(CANALES.toByte())           // canales
            b.putShort(PRE_SKIP_MUESTRAS.toShort())
            b.putInt(SAMPLE_RATE)             // frecuencia de entrada original
            b.putShort(0)                     // ganancia
            b.put(0)                          // familia de mapeo de canales
            b.flip()
            return b
        }

        /** csd-1 y csd-2: un long con nanosegundos, en el orden de bytes nativo. */
        fun nanosegundos(ns: Long): ByteBuffer {
            val b = ByteBuffer.allocate(8).order(ByteOrder.nativeOrder())
            b.putLong(ns)
            b.flip()
            return b
        }
    }
}
