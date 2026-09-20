package com.projectsconsoles.remoteplay

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.Locale

class GamepadStateTest {

    private fun estado() = GamepadState()

    @Test
    fun jsonEnReposoTieneElFormatoQueEsperaElFirmware() {
        val j = estado().toJson(null, 0L, 12.5)
        // mismas claves que los clientes de la Deck y la Ally (ver ds3_controller.ino)
        for (k in listOf(
            "LSTICK_X", "LSTICK_Y", "RSTICK_X", "RSTICK_Y", "L2_ANALOG", "R2_ANALOG",
            "A", "B", "X", "Y", "L1", "R1", "L2_CLICK", "R2_CLICK", "SELECT", "START",
            "L3_CLICK", "R3_CLICK", "STEAM", "dpad",
        )) assertTrue("falta $k en $j", j.contains("\"$k\""))
        // el gatillo en reposo vale -1.0
        assertTrue(j, j.contains("\"L2_ANALOG\":-1.0"))
        assertTrue(j, j.contains("\"R2_ANALOG\":-1.0"))
        assertTrue(j, j.contains("\"A\":0"))
        assertTrue(j, j.contains("\"dpad\":{\"x\":0,\"y\":0}"))
    }

    @Test
    fun unBotonPresionadoSaleEnUno() {
        val s = estado()
        s.boton(Btn.A, true)
        s.boton(Btn.L1, true)
        val j = s.toJson(null, 0L, 0.0)
        assertTrue(j.contains("\"A\":1"))
        assertTrue(j.contains("\"L1\":1"))
        assertTrue(j.contains("\"B\":0"))
        s.boton(Btn.A, false)
        assertTrue(s.toJson(null, 0L, 0.0).contains("\"A\":0"))
    }

    @Test
    fun laCruzetaArribaEsPositivaYElHatDeAndroidVaAlReves() {
        val s = estado()
        s.dpadTecla(1, true) // tecla ARRIBA
        assertEquals(1, s.dpadY())
        s.dpadTecla(1, false)
        s.hatY = -1f // en Android el HAT_Y hacia arriba es negativo
        assertEquals(1, s.dpadY())
        s.hatY = 1f
        assertEquals(-1, s.dpadY())
        s.hatX = 1f
        assertEquals(1, s.dpadX())
    }

    @Test
    fun losGatillosSePasanDeCeroUnoAMenosUnoUno() {
        val s = estado()
        s.l2 = 1f
        s.r2 = 0.5f
        val j = s.toJson(null, 0L, 0.0)
        assertTrue(j, j.contains("\"L2_ANALOG\":1.0"))
        assertTrue(j, j.contains("\"R2_ANALOG\":0.0"))
        // a fondo cuenta como click digital; a medias (0.5 > 0.3) tambien
        assertTrue(j.contains("\"L2_CLICK\":1"))
        assertTrue(j.contains("\"R2_CLICK\":1"))
        s.r2 = 0.1f
        assertTrue(s.toJson(null, 0L, 0.0).contains("\"R2_CLICK\":0"))
    }

    @Test
    fun laZonaMuertaAnulaElDeslizamientoPequeno() {
        val s = estado()
        s.zonaMuerta = 0.06f
        s.lx = 0.05f
        s.ly = -0.5f
        val j = s.toJson(null, 0L, 0.0)
        assertTrue(j, j.contains("\"LSTICK_X\":0.0"))
        assertTrue(j, j.contains("\"LSTICK_Y\":-0.5"))
    }

    @Test
    fun elFormatoNoDependeDelIdiomaDelTelefono() {
        val antes = Locale.getDefault()
        try {
            Locale.setDefault(Locale("es", "MX"))
            val s = estado()
            s.lx = 0.25f
            assertTrue(s.toJson(null, 0L, 1.5).contains("\"LSTICK_X\":0.25"))
            Locale.setDefault(Locale("de", "DE"))
            assertTrue(s.toJson(null, 0L, 1.5).contains("\"LSTICK_X\":0.25"))
        } finally {
            Locale.setDefault(antes)
        }
    }

    @Test
    fun acordePsSelectMasR1FormaElBotonPsYNoPasaElAncla() {
        val s = estado()
        val chord = PsChord(PsChord.DEFECTO)
        var t = 1_000_000_000L
        // SELECT solo: se retiene 80 ms por si R1 llega tarde
        s.boton(Btn.SELECT, true)
        var j = s.toJson(chord, t, 0.0)
        assertTrue(j, j.contains("\"SELECT\":0"))
        // R1 llega dentro de la ventana: es el acorde -> PS, y SELECT sigue sin pasar
        t += 30_000_000L
        s.boton(Btn.R1, true)
        j = s.toJson(chord, t, 0.0)
        assertTrue(j, j.contains("\"STEAM\":1"))
        assertTrue(j, j.contains("\"SELECT\":0"))
        // soltar todo reinicia el acorde
        s.boton(Btn.SELECT, false)
        s.boton(Btn.R1, false)
        t += 30_000_000L
        j = s.toJson(chord, t, 0.0)
        assertTrue(j, j.contains("\"STEAM\":0"))
    }

    @Test
    fun selectSoloPasaDespuesDeLaVentanaDeGuarda() {
        val s = estado()
        val chord = PsChord(PsChord.DEFECTO)
        var t = 5_000_000_000L
        s.boton(Btn.SELECT, true)
        assertTrue(s.toJson(chord, t, 0.0).contains("\"SELECT\":0"))
        t += 100_000_000L // pasaron 100 ms > 80 ms
        assertTrue(s.toJson(chord, t, 0.0).contains("\"SELECT\":1"))
    }

    @Test
    fun sinAcordeConfiguradoNoSeTocaNada() {
        val chord = PsChord("none")
        assertFalse(chord.activo)
        val s = estado()
        s.boton(Btn.SELECT, true)
        assertTrue(s.toJson(chord, 0L, 0.0).contains("\"SELECT\":1"))
    }

    @Test
    fun elAcordeDeSalidaNecesitaLosCuatroBotones() {
        val s = estado()
        s.boton(Btn.L1, true); s.boton(Btn.R1, true); s.boton(Btn.SELECT, true)
        assertFalse(s.acordeDeSalida())
        s.boton(Btn.START, true)
        assertTrue(s.acordeDeSalida())
    }
}
