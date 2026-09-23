package com.projectsconsoles.remoteplay

import android.graphics.Color
import android.os.Bundle
import android.view.ViewGroup
import android.widget.LinearLayout
import android.widget.ScrollView

/** Colores del LED del ESP32-S3 (selector de modo): cuatro mosaicos, cada uno del color real del LED. */
class InfoActivity : PantallaActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

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
                "Con la placa ya encendida (nunca al conectarla o resetearla), mantén BOOT ~1.5 s. " +
                    "El LED cicla de color cada ~0.7 s; suelta el botón en el color que corresponda.",
                Ui.TENUE, if (compacto) 12f else 16f,
            ),
        )

        val oscuro = 0xFF1B1B1B.toInt()
        val tam = if (compacto) 20f else 30f
        fun led(icono: Int, color: Int, nombre: String, consola: String, texto: Int = Color.WHITE) =
            Ui.mosaico(this, icono, nombre, consola, color, compacto, texto, interactivo = false, tamTitulo = tam)

        raiz.addView(
            Ui.cuadricula(
                this, compacto,
                listOf(
                    listOf(
                        led(R.drawable.ic_console_ps3, 0xFFD4B106.toInt(), "Amarillo", "PS3", oscuro),
                        led(R.drawable.ic_console_ps2, 0xFF2D6CDF.toInt(), "Azul", "PS2 / OPL"),
                        led(R.drawable.ic_console_xbox360, 0xFF8E5FD6.toInt(), "Morado", "Xbox 360"),
                        led(R.drawable.ic_console_xboxclasico, 0xFF2FA84F.toInt(), "Verde", "Xbox clásico"),
                    ),
                ),
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
