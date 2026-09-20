package com.projectsconsoles.remoteplay

/** Botones digitales, con los MISMOS nombres que espera el firmware del ESP32 (ver `nombres`). */
object Btn {
    const val A = 1 shl 0
    const val B = 1 shl 1
    const val X = 1 shl 2
    const val Y = 1 shl 3
    const val L1 = 1 shl 4
    const val R1 = 1 shl 5
    const val SELECT = 1 shl 6
    const val START = 1 shl 7
    const val STEAM = 1 shl 8   // boton PS / guia
    const val L3 = 1 shl 9
    const val R3 = 1 shl 10
    const val L2 = 1 shl 11     // "click" digital del gatillo
    const val R2 = 1 shl 12

    /** Nombre en el JSON -> bit. El orden es el del contrato del cliente de la Deck y la Ally. */
    val nombres: List<Pair<String, Int>> = listOf(
        "A" to A, "B" to B, "X" to X, "Y" to Y,
        "L1" to L1, "R1" to R1, "L2_CLICK" to L2, "R2_CLICK" to R2,
        "SELECT" to SELECT, "START" to START, "L3_CLICK" to L3, "R3_CLICK" to R3,
        "STEAM" to STEAM,
    )

    fun bitDe(nombre: String): Int = nombres.firstOrNull { it.first == nombre.trim().uppercase() }?.second
        ?: nombres.firstOrNull { it.first == nombre.trim().uppercase() + "_CLICK" }?.second
        ?: 0
}

/**
 * Boton PS por acorde (SELECT+R1 por defecto), igual que `apply_ps_chord` de la Deck y la Ally:
 * el ancla (primer boton) se retiene 80 ms por si el otro llega tarde, y mientras dure el acorde no
 * se le pasa al ESP32 (para que un R1 del acorde no dispare en el juego).
 */
class PsChord(spec: String) {
    private val bits: IntArray = parsear(spec)
    private var singleSince = 0L
    private var latched = false

    val activo: Boolean get() = bits.isNotEmpty()

    fun aplicar(botones: Int, ahoraNs: Long): Int {
        if (bits.isEmpty()) return botones
        val ancla = bits[0]
        val presionados = bits.map { (botones and it) != 0 }
        val combo = presionados.all { it }
        val anclaSola = (botones and ancla) != 0 && !combo
        if (combo) {
            latched = true
            singleSince = 0L
        } else if (presionados.none { it }) {
            latched = false
            singleSince = 0L
        } else if (anclaSola && singleSince == 0L) {
            singleSince = ahoraNs
        }
        var r = botones
        if (combo) r = r or Btn.STEAM
        if (latched) return r and ancla.inv()
        if (singleSince != 0L && (ahoraNs - singleSince) < GUARDA_NS) r = r and ancla.inv()
        return r
    }

    companion object {
        const val GUARDA_NS = 80_000_000L
        const val DEFECTO = "SELECT+R1"

        fun parsear(spec: String): IntArray {
            val s = spec.trim()
            if (s.isEmpty() || s.lowercase() in setOf("none", "no", "0", "off")) return IntArray(0)
            return s.split("+").map { Btn.bitDe(it) }.filter { it != 0 }.toIntArray()
        }
    }
}

/**
 * Estado del mando. Lo escribe el hilo de la interfaz (eventos de Android) y lo lee el hilo que
 * manda al ESP32; por eso los campos son @Volatile. Kotlin puro: se prueba en la JVM.
 *
 * Convenciones (las mismas que las de la Deck/Ally, que es lo que entiende el firmware):
 *  - sticks en -1..1, ARRIBA = negativo (SDL/Android coinciden);
 *  - gatillos analogicos en -1..1 con el reposo en -1;
 *  - cruceta: x derecha = +1, y ARRIBA = +1.
 */
class GamepadState {
    @Volatile var botones = 0
    @Volatile var dpadTeclas = 0        // bits 1=arriba 2=abajo 4=izq 8=der, por eventos de tecla
    @Volatile var hatX = 0f
    @Volatile var hatY = 0f             // en Android el HAT_Y ARRIBA es negativo
    @Volatile var lx = 0f
    @Volatile var ly = 0f
    @Volatile var rx = 0f
    @Volatile var ry = 0f
    @Volatile var l2 = 0f               // 0..1
    @Volatile var r2 = 0f
    @Volatile var zonaMuerta = 0f

    private val cerrojo = Any()

    fun boton(bit: Int, presionado: Boolean) {
        synchronized(cerrojo) {
            botones = if (presionado) botones or bit else botones and bit.inv()
        }
    }

    fun dpadTecla(bit: Int, presionado: Boolean) {
        synchronized(cerrojo) {
            dpadTeclas = if (presionado) dpadTeclas or bit else dpadTeclas and bit.inv()
        }
    }

    /** L1 + R1 + SELECT + START a la vez: acorde de salida del streaming. */
    fun acordeDeSalida(): Boolean {
        val m = Btn.L1 or Btn.R1 or Btn.SELECT or Btn.START
        return (botones and m) == m
    }

    fun dpadX(): Int {
        var x = 0
        if ((dpadTeclas and 8) != 0 || hatX > 0.5f) x += 1
        if ((dpadTeclas and 4) != 0 || hatX < -0.5f) x -= 1
        return x
    }

    fun dpadY(): Int {
        var y = 0
        if ((dpadTeclas and 1) != 0 || hatY < -0.5f) y += 1
        if ((dpadTeclas and 2) != 0 || hatY > 0.5f) y -= 1
        return y
    }

    /** Botones efectivos: agrega los "clicks" de gatillo y aplica el acorde de PS. */
    fun botonesEfectivos(chord: PsChord?, ahoraNs: Long): Int {
        var b = botones
        if (l2 > UMBRAL_GATILLO) b = b or Btn.L2
        if (r2 > UMBRAL_GATILLO) b = b or Btn.R2
        if (chord != null) b = chord.aplicar(b, ahoraNs)
        return b
    }

    fun toJson(chord: PsChord?, ahoraNs: Long, segundos: Double): String {
        val b = botonesEfectivos(chord, ahoraNs)
        val sb = StringBuilder(420)
        sb.append("{\"t\":").append(segundos)
        sb.append(",\"axes\":{")
        sb.append("\"LSTICK_X\":").append(f(eje(lx)))
        sb.append(",\"LSTICK_Y\":").append(f(eje(ly)))
        sb.append(",\"L2_ANALOG\":").append(f(l2 * 2f - 1f))
        sb.append(",\"RSTICK_X\":").append(f(eje(rx)))
        sb.append(",\"RSTICK_Y\":").append(f(eje(ry)))
        sb.append(",\"R2_ANALOG\":").append(f(r2 * 2f - 1f))
        sb.append("},\"buttons\":{")
        var primero = true
        for ((nombre, bit) in Btn.nombres) {
            if (!primero) sb.append(',')
            primero = false
            sb.append('"').append(nombre).append("\":").append(if ((b and bit) != 0) 1 else 0)
        }
        sb.append("},\"dpad\":{\"x\":").append(dpadX()).append(",\"y\":").append(dpadY()).append("}}")
        return sb.toString()
    }

    private fun eje(v: Float): Float {
        val z = zonaMuerta
        return if (v > -z && v < z) 0f else v.coerceIn(-1f, 1f)
    }

    /** Numero sin notacion cientifica ni coma decimal, sea cual sea el idioma del telefono. */
    private fun f(v: Float): String {
        val r = Math.round(v * 10000f) / 10000f
        return if (r == 0f) "0.0" else r.toString()
    }

    companion object {
        /** Cuanto hay que apretar el gatillo (0..1) para contar como "click" de L2/R2. */
        const val UMBRAL_GATILLO = 0.3f
    }
}
