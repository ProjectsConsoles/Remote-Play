package com.projectsconsoles.remoteplay

import android.content.Context

/** Ajustes del cliente. Mismos nombres y valores por defecto que las PS3RP_* de la Deck y la Ally. */
class Prefs(ctx: Context) {
    private val sp = ctx.getSharedPreferences("remoteplay", Context.MODE_PRIVATE)

    private fun s(k: String, d: String) = sp.getString(k, d) ?: d
    private fun i(k: String, d: Int) = sp.getInt(k, d)

    var esp32Ip: String
        get() = s("esp32_ip", "192.168.0.40")
        set(v) = sp.edit().putString("esp32_ip", v.trim()).apply()

    var esp32Puerto: Int
        get() = i("esp32_puerto", 9000)
        set(v) = sp.edit().putInt("esp32_puerto", v).apply()

    var servidorIp: String
        get() = s("servidor_ip", "192.168.0.90")
        set(v) = sp.edit().putString("servidor_ip", v.trim()).apply()

    var puertoVideo: Int
        get() = i("puerto_video", 5000)
        set(v) = sp.edit().putInt("puerto_video", v).apply()

    var frecuenciaMando: Int
        get() = i("frecuencia_mando", 120)
        set(v) = sp.edit().putInt("frecuencia_mando", v.coerceIn(30, 250)).apply()

    var acordePs: String
        get() = s("acorde_ps", PsChord.DEFECTO)
        set(v) = sp.edit().putString("acorde_ps", v.trim()).apply()

    /** "barras" | "estirar" | "zoom" */
    var ajusteImagen: String
        get() = s("ajuste_imagen", "barras")
        set(v) = sp.edit().putString("ajuste_imagen", v).apply()

    /** "nada" | "medio" | "alta" */
    var zonaMuerta: String
        get() = s("zona_muerta", "nada")
        set(v) = sp.edit().putString("zona_muerta", v).apply()

    var segundosSinVideo: Int
        get() = i("segundos_sin_video", 25)
        set(v) = sp.edit().putInt("segundos_sin_video", v.coerceIn(5, 120)).apply()

    fun zonaMuertaValor(): Float = when (zonaMuerta) {
        "medio" -> 0.06f
        "alta" -> 0.12f
        else -> 0f
    }

    companion object {
        val AJUSTES_IMAGEN = listOf("barras", "estirar", "zoom")
        val ZONAS_MUERTAS = listOf("nada", "medio", "alta")
    }
}
