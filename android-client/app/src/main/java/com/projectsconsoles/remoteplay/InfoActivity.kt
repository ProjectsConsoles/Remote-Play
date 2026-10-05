package com.projectsconsoles.remoteplay

import android.graphics.Color
import android.os.Bundle
import android.view.ViewGroup
import android.widget.LinearLayout
import android.widget.ScrollView

/**
 * Colores del LED del ESP32-S3 (selector de modo): cuatro mosaicos, cada uno del color del LED. Desde
 * 2026-10-04 tambien ELIGEN el modo (A o toque manda {"set_modo": n} al ESP32, como en la Deck y la
 * Ally); sigue siendo el respaldo de "¿Qué consola?" si el comando no llego.
 */
class InfoActivity : PantallaActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val prefs = Prefs(this)

        val compacto = resources.configuration.screenHeightDp < 500
        val margen = Ui.dp(this, if (compacto) 10 else 20)

        val raiz = LinearLayout(this)
        raiz.orientation = LinearLayout.VERTICAL
        raiz.clipChildren = false
        raiz.clipToPadding = false
        raiz.setPadding(margen, margen, margen, margen)
        raiz.addView(Ui.cabecera(this, "Selector de modo del ESP32-S3", "", compacto))
        raiz.addView(
            Ui.texto(
                this,
                "Toca o elige con A el modo (el control se reinicia ~2 s). O en la placa ya encendida mantén BOOT " +
                    "~1.5 s: el LED cicla de color cada ~0.7 s; suelta el botón en el color que corresponda.",
                Ui.TENUE, if (compacto) 12f else 16f,
            ),
        )
        val tira = Ui.TiraEstado(this, compacto)
        tira.pintar(Ui.TENUE, "ESP32 en ${prefs.esp32Ip}:${prefs.esp32Puerto}")
        raiz.addView(
            tira.vista,
            LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
                .also { it.topMargin = Ui.dp(this, if (compacto) 4 else 8) },
        )

        val tam = if (compacto) 20f else 30f
        // Los logos de consola son wordmarks anchos y bajitos (no un icono cuadrado):
        // con el icono() cuadrado de siempre (52dp) se veian minusculos, igual que nos
        // paso primero en la Deck con el mismo problema.
        fun led(l: Consolas.Led) =
            Ui.mosaico(this, l.icono, l.nombreColor, l.consola, l.color, compacto, Color.WHITE, tamTitulo = tam,
                anchoIconoDp = if (compacto) 100 else 150) {
                Consolas.enviarModo(this, prefs, l.modo) { ok ->
                    if (ok) tira.pintar(Consolas.AMARILLO_AVISO, "Modo ${l.consola} enviado — el control se reinicia (~2 s)...")
                    else tira.pintar(Ui.ERROR, "No se pudo mandar al ESP32 (revisa la IP en Configurar cliente).")
                }
            }

        raiz.addView(
            Ui.cuadricula(
                this, compacto,
                listOf(Consolas.LEDS.map { led(it) }),
            ),
            LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f),
        )
        raiz.addView(
            Ui.texto(this, "El modo elegido queda guardado en la placa hasta que se cambie a mano.", Ui.TENUE, if (compacto) 12f else 15f),
        )
        val pie = LinearLayout(this)
        pie.orientation = LinearLayout.HORIZONTAL
        val volver = Ui.botonIcono(this, R.drawable.ic_back, "Volver", 0xFF2A3441.toInt()) { finish() }
        pie.addView(volver)
        raiz.addView(
            pie,
            LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
                .also { it.topMargin = Ui.dp(this, 4) },
        )

        val scroll = ScrollView(this)
        scroll.isFillViewport = true
        scroll.clipChildren = false
        scroll.clipToPadding = false
        scroll.addView(
            raiz,
            ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT),
        )
        setContentView(scroll)
        volver.requestFocus()
    }
}
