package com.projectsconsoles.remoteplay

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Prueba el demultiplexor contra una captura REAL: 2 s de video 1280x720 a 60 fps (H.264, IDR cada
 * 30) y audio Opus de 5 ms, empaquetados con los mismos flags de muxer que el servidor
 * (`-muxdelay 0 -muxpreload 0 -flush_packets 1 -max_interleave_delta 0 -pes_payload_size 0`).
 */
class TsDemuxerTest {

    private class Cuadro(val bytes: ByteArray, val pts: Long)

    private fun muestra(): ByteArray =
        javaClass.getResourceAsStream("/muestra_x264_opus.ts")!!.use { it.readBytes() }

    private class Resultado(val video: List<Cuadro>, val opus: List<Cuadro>, val demux: TsDemuxer)

    private fun demultiplexar(
        datos: ByteArray,
        trozo: Int,
        detectarRelleno: Boolean,
        alFinal: Boolean = true,
        prefijo: ByteArray = ByteArray(0),
    ): Resultado {
        val video = ArrayList<Cuadro>()
        val opus = ArrayList<Cuadro>()
        val d = TsDemuxer(
            onVideo = { b, o, n, pts -> video.add(Cuadro(b.copyOfRange(o, o + n), pts)) },
            onOpus = { b, o, n, pts -> opus.add(Cuadro(b.copyOfRange(o, o + n), pts)) },
            detectarRellenoDeFin = detectarRelleno,
        )
        // La basura llega como un datagrama aparte: en la red cada datagrama trae paquetes TS enteros.
        if (prefijo.isNotEmpty()) d.feed(prefijo, 0, prefijo.size)
        var p = 0
        while (p < datos.size) {
            val n = minOf(trozo, datos.size - p)
            d.feed(datos, p, n)
            p += n
        }
        if (alFinal) d.flush()
        return Resultado(video, opus, d)
    }

    /** NAL types presentes en un cuadro Annex-B. */
    private fun nals(b: ByteArray): Set<Int> {
        val r = HashSet<Int>()
        var i = 0
        while (i + 3 < b.size) {
            if (b[i].toInt() == 0 && b[i + 1].toInt() == 0 &&
                (b[i + 2].toInt() == 1 || (b[i + 2].toInt() == 0 && b[i + 3].toInt() == 1))
            ) {
                val s = if (b[i + 2].toInt() == 1) i + 3 else i + 4
                if (s < b.size) r.add(b[s].toInt() and 0x1F)
                i = s
            } else {
                i++
            }
        }
        return r
    }

    @Test
    fun encuentraLosPidsDelProgramaReal() {
        val r = demultiplexar(muestra(), 1316, true)
        assertEquals(256, r.demux.videoPid)
        assertEquals(257, r.demux.opusPid)
        assertEquals(0L, r.demux.resincronizaciones)
    }

    @Test
    fun entregaTodosLosCuadrosDeVideo() {
        val r = demultiplexar(muestra(), 1316, true)
        assertEquals(120, r.video.size) // 2 s a 60 fps
        // cada cuadro empieza con un delimitador de acceso (NAL 9) que agrega el muxer
        assertTrue(r.video.all { 9 in nals(it.bytes) })
        // el primero trae SPS(7) + PPS(8) + IDR(5), o el decodificador no podria arrancar
        val primero = nals(r.video[0].bytes)
        assertTrue("SPS/PPS/IDR en el primero: $primero", primero.containsAll(listOf(7, 8, 5)))
        // IDR cada 30 cuadros
        val idr = r.video.withIndex().filter { 5 in nals(it.value.bytes) }.map { it.index }
        assertEquals(listOf(0, 30, 60, 90), idr)
    }

    @Test
    fun laMarcaDeTiempoAvanzaUnaVezPorCuadro() {
        val r = demultiplexar(muestra(), 1316, true)
        val pts = r.video.map { it.pts }
        assertTrue(pts.all { it >= 0 })
        for (i in 1 until pts.size) {
            val dt = pts[i] - pts[i - 1]
            // 16.67 ms a 60 fps, con tolerancia por el redondeo a 90 kHz
            assertTrue("dt=$dt en el cuadro $i", dt in 16_000L..17_500L)
        }
    }

    @Test
    fun detectarElRellenoDeFinDaLoMismoQueEsperarAlPesSiguiente() {
        val rapido = demultiplexar(muestra(), 1316, true)
        val lento = demultiplexar(muestra(), 1316, false)
        assertEquals(lento.video.size, rapido.video.size)
        for (i in rapido.video.indices) {
            assertArrayEquals("cuadro $i", lento.video[i].bytes, rapido.video[i].bytes)
            assertEquals(lento.video[i].pts, rapido.video[i].pts)
        }
    }

    @Test
    fun elRellenoDeFinEntregaCadaCuadroSinEsperarAlSiguiente() {
        // Sin flush() final: si el relleno funciona, TODOS los cuadros ya salieron (con el camino
        // lento faltaria el ultimo, que espera a un PES siguiente que nunca llega).
        val rapido = demultiplexar(muestra(), 1316, true, alFinal = false)
        val lento = demultiplexar(muestra(), 1316, false, alFinal = false)
        assertEquals(120, rapido.video.size)
        assertEquals(119, lento.video.size)
    }

    @Test
    fun noDependeDeComoLleguenLosDatagramas() {
        val a = demultiplexar(muestra(), 1316, true)
        val b = demultiplexar(muestra(), 188, true)
        val c = demultiplexar(muestra(), 188 * 3, true)
        assertEquals(a.video.size, b.video.size)
        assertEquals(a.video.size, c.video.size)
        assertEquals(a.opus.size, b.opus.size)
        for (i in a.video.indices) assertArrayEquals(a.video[i].bytes, c.video[i].bytes)
    }

    @Test
    fun extraePaquetesOpusValidos() {
        val r = demultiplexar(muestra(), 1316, true)
        assertTrue("paquetes Opus: ${r.opus.size}", r.opus.size in 395..405) // 5 ms -> ~400 en 2 s
        assertTrue(r.opus.all { it.bytes.size in 1..400 })
        // el primer byte de un paquete Opus es el TOC: config 16..31 = CELT (baja latencia)
        assertTrue(r.opus.all { ((it.bytes[0].toInt() and 0xFF) shr 3) in 16..31 })
    }

    @Test
    fun ignoraBasuraAlPrincipio() {
        val r = demultiplexar(muestra(), 1316, true, prefijo = ByteArray(250) { 0x11 })
        assertEquals(120, r.video.size)
        assertTrue(r.demux.resincronizaciones > 0)
    }
}
