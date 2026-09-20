package com.projectsconsoles.remoteplay

/**
 * Demultiplexor MPEG-TS minimo para el stream del servidor (H.264 + Opus).
 *
 * Se escribio a mano, en vez de usar una libreria, por LATENCIA: hay que entregar cada cuadro al
 * decodificador apenas llega. Lo que se midio en una captura real hecha con los mismos ajustes del
 * servidor (`-pes_payload_size 0`, `-flush_packets 1`, Opus de 5 ms):
 *
 *  - Video: PID de tipo 0x1B. TODOS los PES traen longitud 0 ("sin limite": es el default del muxer
 *    de ffmpeg, `omit_video_pes_length`), asi que la longitud no dice donde termina un cuadro. Lo que
 *    si lo dice: el ULTIMO paquete TS de cada PES lleva un "adaptation field" de relleno, sin reloj
 *    PCR. Detectarlo permite entregar el cuadro en el acto en vez de esperar al inicio del siguiente
 *    (16 ms a 60 fps). Si algun cuadro no terminara con relleno, igual se entrega cuando llega el
 *    PES siguiente (o con [flush]); nunca se pierde.
 *  - Audio: PID de tipo 0x06 con el descriptor de registro "Opus". Cada PES trae su longitud y va
 *    en un solo paquete TS. El payload lleva la cabecera de control de Opus en MPEG-TS: 0x7F, luego
 *    0b111SExxx (S = recorte de arranque, E = recorte de final), el tamano (suma de bytes hasta uno
 *    distinto de 0xFF), 2 bytes por cada recorte, y el paquete Opus.
 *
 * Los callbacks se llaman en el mismo hilo que [feed] y reciben el buffer INTERNO: quien los use
 * debe copiarlo antes de volver.
 */
class TsDemuxer(
    private val onVideo: (buf: ByteArray, offset: Int, size: Int, ptsUs: Long) -> Unit,
    private val onOpus: (buf: ByteArray, offset: Int, size: Int, ptsUs: Long) -> Unit,
    /** false = solo termina un cuadro al llegar el PES siguiente (para probar que ambos caminos dan lo mismo). */
    private val detectarRellenoDeFin: Boolean = true,
) {
    private var pmtPid = -1
    var videoPid = -1
        private set
    var opusPid = -1
        private set

    var paquetesTs = 0L
        private set
    var resincronizaciones = 0L
        private set
    var cuadrosVideo = 0L
        private set
    var paquetesOpus = 0L
        private set

    private class Pes {
        var buf = ByteArray(1 shl 16)
        var len = 0
        var active = false
        var hdrParsed = false
        var expected = -1
        var payloadOff = 0
        var ptsUs = -1L

        fun reset() {
            len = 0; active = false; hdrParsed = false; expected = -1; payloadOff = 0; ptsUs = -1L
        }

        fun append(d: ByteArray, off: Int, n: Int) {
            if (len + n > buf.size) buf = buf.copyOf(maxOf(buf.size * 2, len + n))
            System.arraycopy(d, off, buf, len, n)
            len += n
        }
    }

    private val videoPes = Pes()
    private val audioPes = Pes()

    /** Procesa bytes de red (un datagrama trae normalmente 7 paquetes TS de 188 bytes). */
    fun feed(data: ByteArray, offset: Int, length: Int) {
        var p = offset
        val end = offset + length
        while (p + TS_SIZE <= end) {
            if (data[p] != SYNC) {
                p++
                resincronizaciones++
                continue
            }
            paquete(data, p)
            p += TS_SIZE
        }
    }

    /** Entrega el cuadro que quede a medias (PES sin longitud que no termino con relleno). */
    fun flush() {
        if (videoPes.active && videoPes.hdrParsed) {
            terminar(videoPes, true)
            videoPes.active = false
        }
    }

    /** Olvida lo que estaba armando (tras un corte largo de red). */
    fun descartar() {
        videoPes.reset()
        audioPes.reset()
    }

    private fun u8(b: Byte) = b.toInt() and 0xFF

    private fun paquete(d: ByteArray, o: Int) {
        paquetesTs++
        val b1 = u8(d[o + 1])
        if ((b1 and 0x80) != 0) return // transport_error_indicator
        val pusi = (b1 and 0x40) != 0
        val pid = ((b1 and 0x1F) shl 8) or u8(d[o + 2])
        val afc = (u8(d[o + 3]) shr 4) and 3
        var off = o + 4
        var rellenoDeFin = false
        if ((afc and 2) != 0) {
            val afLen = u8(d[off])
            val flags = if (afLen > 0) u8(d[off + 1]) else 0
            // Relleno de fin de PES: adaptation field SIN PCR (0x10) en un paquete que no inicia PES.
            rellenoDeFin = !pusi && (flags and 0x10) == 0
            off += 1 + afLen
        }
        if ((afc and 1) == 0) return
        val n = o + TS_SIZE - off
        if (n <= 0) return
        when (pid) {
            0 -> if (pmtPid < 0) tablaPat(d, off, n, pusi)
            pmtPid -> tablaPmt(d, off, n, pusi)
            videoPid -> pes(videoPes, true, d, off, n, pusi, rellenoDeFin)
            opusPid -> pes(audioPes, false, d, off, n, pusi, rellenoDeFin)
        }
    }

    private fun tablaPat(d: ByteArray, off: Int, n: Int, pusi: Boolean) {
        if (!pusi) return
        val limite = off + n
        val p = off + 1 + u8(d[off])
        if (p + 8 > limite || u8(d[p]) != 0x00) return
        val secLen = ((u8(d[p + 1]) and 0x0F) shl 8) or u8(d[p + 2])
        var q = p + 8
        val fin = minOf(p + 3 + secLen - 4, limite)
        while (q + 4 <= fin) {
            val programa = (u8(d[q]) shl 8) or u8(d[q + 1])
            val pid = ((u8(d[q + 2]) and 0x1F) shl 8) or u8(d[q + 3])
            if (programa != 0) {
                pmtPid = pid
                return
            }
            q += 4
        }
    }

    private fun tablaPmt(d: ByteArray, off: Int, n: Int, pusi: Boolean) {
        if (!pusi) return
        val limite = off + n
        val p = off + 1 + u8(d[off])
        if (p + 12 > limite || u8(d[p]) != 0x02) return
        val secLen = ((u8(d[p + 1]) and 0x0F) shl 8) or u8(d[p + 2])
        val infoLen = ((u8(d[p + 10]) and 0x0F) shl 8) or u8(d[p + 11])
        var q = p + 12 + infoLen
        val fin = minOf(p + 3 + secLen - 4, limite)
        while (q + 5 <= fin) {
            val tipo = u8(d[q])
            val pid = ((u8(d[q + 1]) and 0x1F) shl 8) or u8(d[q + 2])
            val il = ((u8(d[q + 3]) and 0x0F) shl 8) or u8(d[q + 4])
            if (tipo == 0x1B && videoPid < 0) {
                videoPid = pid
            } else if (tipo == 0x06 && opusPid < 0 && esOpus(d, q + 5, minOf(il, fin - (q + 5)))) {
                opusPid = pid
            }
            q += 5 + il
        }
    }

    /** Descriptor de registro (tag 0x05) con el identificador "Opus". */
    private fun esOpus(d: ByteArray, off: Int, len: Int): Boolean {
        var p = off
        val fin = off + len
        while (p + 2 <= fin) {
            val tag = u8(d[p])
            val l = u8(d[p + 1])
            if (tag == 0x05 && l >= 4 && p + 6 <= fin &&
                d[p + 2] == 'O'.code.toByte() && d[p + 3] == 'p'.code.toByte() &&
                d[p + 4] == 'u'.code.toByte() && d[p + 5] == 's'.code.toByte()
            ) return true
            p += 2 + l
        }
        return false
    }

    private fun pes(s: Pes, video: Boolean, d: ByteArray, off: Int, n: Int, pusi: Boolean, rellenoDeFin: Boolean) {
        if (pusi) {
            // Un PES sin longitud termina al empezar el siguiente.
            if (s.active && s.hdrParsed) terminar(s, video)
            s.reset()
            s.active = true
        } else if (!s.active) {
            return
        }
        s.append(d, off, n)
        if (!s.hdrParsed) cabecera(s)
        if (!s.active || !s.hdrParsed) return
        if (s.expected > 0) {
            if (s.len >= s.expected) {
                terminar(s, video)
                s.active = false
            }
        } else if (detectarRellenoDeFin && rellenoDeFin) {
            terminar(s, video)
            s.active = false
        }
    }

    private fun cabecera(s: Pes) {
        if (s.len < 9) return
        val b = s.buf
        if (b[0].toInt() != 0 || b[1].toInt() != 0 || b[2].toInt() != 1) {
            s.active = false // no es un PES valido: se ignora hasta el proximo inicio
            return
        }
        val hl = u8(b[8])
        if (s.len < 9 + hl) return
        if ((u8(b[7]) and 0x80) != 0 && hl >= 5) {
            val pts = ((u8(b[9]) shr 1).toLong() and 7L shl 30) or
                (u8(b[10]).toLong() shl 22) or
                ((u8(b[11]) shr 1).toLong() shl 15) or
                (u8(b[12]).toLong() shl 7) or
                (u8(b[13]) shr 1).toLong()
            s.ptsUs = pts * 1000L / 90L
        }
        val plen = (u8(b[4]) shl 8) or u8(b[5])
        s.expected = if (plen > 0) plen + 6 else -1
        s.payloadOff = 9 + hl
        s.hdrParsed = true
    }

    private fun terminar(s: Pes, video: Boolean) {
        if (!s.hdrParsed) return
        val fin = if (s.expected > 0) minOf(s.len, s.expected) else s.len
        val size = fin - s.payloadOff
        if (size <= 0) return
        if (video) {
            cuadrosVideo++
            onVideo(s.buf, s.payloadOff, size, s.ptsUs)
        } else {
            unidadesOpus(s.buf, s.payloadOff, fin, s.ptsUs)
        }
    }

    private fun unidadesOpus(b: ByteArray, inicio: Int, fin: Int, pts: Long) {
        var p = inicio
        while (p + 3 <= fin) {
            if (u8(b[p]) != 0x7F || (u8(b[p + 1]) and 0xE0) != 0xE0) return // desalineado
            val flags = u8(b[p + 1])
            p += 2
            var size = 0
            while (p < fin) {
                val v = u8(b[p++])
                size += v
                if (v != 0xFF) break
            }
            if ((flags and 0x10) != 0) p += 2 // recorte de arranque
            if ((flags and 0x08) != 0) p += 2 // recorte de final
            if ((flags and 0x04) != 0 && p < fin) p += 1 + u8(b[p]) // extension de control
            if (size <= 0 || p + size > fin) return
            paquetesOpus++
            onOpus(b, p, size, pts)
            p += size
        }
    }

    companion object {
        const val TS_SIZE = 188
        private const val SYNC: Byte = 0x47
    }
}
