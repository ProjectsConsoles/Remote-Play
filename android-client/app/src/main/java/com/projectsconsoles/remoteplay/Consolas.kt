package com.projectsconsoles.remoteplay

import android.content.Context
import android.content.Intent
import android.graphics.Color
import org.json.JSONObject
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress

/**
 * Las consolas que se eligen en "¿Qué consola?" (2026-10-04, como la Deck y la Ally) y en Info.
 *
 * Las 4 del ESP32-S3 se configuran mandandole {"set_modo": n} por UDP: el firmware lo guarda en
 * flash y se reinicia (el control se desconecta de la consola ~2-4 s), igual que sosteniendo BOOT.
 * PS4/PS5 y Xbox One/Series son apps externas: traen su propio video, audio y mando, no usan el
 * servidor ni el ESP32 (y mientras estan al frente esta app no manda nada: el envio vive en
 * StreamActivity, que no esta abierta).
 */
object Consolas {

    /** [modo] = indice que entiende el firmware (0 PS3, 1 PS2, 2 Xbox 360, 3 Xbox clasico). */
    data class Led(val modo: Int, val color: Int, val nombreColor: String, val consola: String, val icono: Int)

    val LEDS = listOf(
        // PS3: mas oscuro que el LED real y texto blanco como su logo (contraste 2.1 -> 3.2, igual que la Deck).
        Led(0, 0xFFB88A00.toInt(), "Amarillo", "PS3", R.drawable.ic_console_ps3),
        Led(1, 0xFF2D6CDF.toInt(), "Azul", "PS2 / OPL", R.drawable.ic_console_ps2),
        Led(2, 0xFF8E5FD6.toInt(), "Morado", "Xbox 360", R.drawable.ic_console_xbox360),
        Led(3, 0xFF2FA84F.toInt(), "Verde", "Xbox clásico", R.drawable.ic_console_xboxclasico),
    )

    const val AZUL_PS = 0xFF0070D1.toInt()
    const val VERDE_XBOX = 0xFF107C10.toInt()
    const val AMARILLO_AVISO = 0xFFD4B106.toInt()

    /** Manda el modo al ESP32 en un hilo aparte (red en el hilo de la UI esta prohibida) y avisa en la UI. */
    fun enviarModo(ctx: android.app.Activity, prefs: Prefs, modo: Int, alTerminar: (Boolean) -> Unit) {
        val ip = prefs.esp32Ip
        val puerto = prefs.esp32Puerto
        Thread {
            val ok = try {
                DatagramSocket().use { s ->
                    val datos = JSONObject().put("set_modo", modo).toString().toByteArray(Charsets.US_ASCII)
                    s.send(DatagramPacket(datos, datos.size, InetAddress.getByName(ip), puerto))
                }
                true
            } catch (e: Exception) {
                false
            }
            ctx.runOnUiThread { if (!ctx.isDestroyed) alTerminar(ok) }
        }.start()
    }

    /**
     * Una app externa: se abre la primera de [paquetes] que este instalada. Los paquetes tambien van
     * en <queries> del AndroidManifest (desde Android 11 sin eso no se ven las otras apps).
     */
    data class App(val clave: String, val titulo: String, val color: Int, val icono: Int, val paquetes: List<Pair<String, String>>, val sugerencia: String)

    val PS = App(
        "ps", "PS4 / PS5", AZUL_PS, R.drawable.ic_console_ps,
        listOf("com.playstation.remoteplay" to "PS Remote Play", "com.metallic.chiaki" to "Chiaki"),
        "instala PS Remote Play (Sony, gratis) o Chiaki desde Play Store",
    )
    val XBOX = App(
        "xbox", "Xbox One / Series", VERDE_XBOX, R.drawable.ic_console_xbox,
        listOf("com.microsoft.xboxone.smartglass" to "Xbox", "com.studio08.xbgamestream" to "xbPlay"),
        "instala la app de Xbox (gratis, trae juego remoto) o xbPlay desde Play Store",
    )

    /** (paquete, nombre) de la primera app instalada, o null. */
    fun instalada(ctx: Context, app: App): Pair<String, String>? =
        app.paquetes.firstOrNull { ctx.packageManager.getLaunchIntentForPackage(it.first) != null }

    fun abrir(ctx: Context, paquete: String): Boolean {
        val i = ctx.packageManager.getLaunchIntentForPackage(paquete) ?: return false
        i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        ctx.startActivity(i)
        return true
    }

    /** Color atenuado para una app que no esta instalada. */
    fun apagado(color: Int): Int {
        val f = 0.6f
        val fondo = Ui.FONDO
        return Color.rgb(
            (Color.red(color) * (1 - f) + Color.red(fondo) * f).toInt(),
            (Color.green(color) * (1 - f) + Color.green(fondo) * f).toInt(),
            (Color.blue(color) * (1 - f) + Color.blue(fondo) * f).toInt(),
        )
    }
}
