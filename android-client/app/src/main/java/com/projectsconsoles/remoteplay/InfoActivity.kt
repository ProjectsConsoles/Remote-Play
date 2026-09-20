package com.projectsconsoles.remoteplay

import android.os.Bundle
import android.view.Gravity
import android.widget.LinearLayout

/** Colores del LED del ESP32-S3 (selector de modo). Los mismos que la pantalla de la Deck. */
class InfoActivity : PantallaActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val p = Ui.Pantalla(this)
        p.agregar(Ui.titulo(this, "Selector de modo del ESP32-S3"))
        p.agregar(
            Ui.texto(
                this,
                "Con la placa ya encendida (nunca al conectarla o resetearla), mantén BOOT ~1.5 s. " +
                    "El LED cicla de color cada ~0.7 s; suelta el botón en el color que corresponda.",
            ),
        )

        val colores = listOf(
            Triple(0xFFD4B106.toInt(), "Amarillo", "PS3"),
            Triple(0xFF2D6CDF.toInt(), "Azul", "PS2 / OPL"),
            Triple(0xFF8E5FD6.toInt(), "Morado", "Xbox 360"),
            Triple(0xFF2FA84F.toInt(), "Verde", "Xbox clásico"),
        )
        for ((color, nombre, consola) in colores) {
            val fila = LinearLayout(this)
            fila.orientation = LinearLayout.HORIZONTAL
            fila.gravity = Gravity.CENTER_VERTICAL
            fila.setPadding(0, Ui.dp(this, 10), 0, Ui.dp(this, 10))
            fila.addView(Ui.puntoDeColor(this, color))
            val textos = LinearLayout(this)
            textos.orientation = LinearLayout.VERTICAL
            textos.setPadding(Ui.dp(this, 18), 0, 0, 0)
            textos.addView(Ui.texto(this, nombre, Ui.TEXTO, 20f))
            textos.addView(Ui.texto(this, consola, Ui.TENUE, 16f))
            fila.addView(textos)
            p.agregar(fila)
        }

        p.agregar(Ui.texto(this, "El modo elegido queda guardado en la placa hasta que se cambie a mano."))
        val volver = p.agregar(Ui.boton(this, "Volver", 0xFF2A3441.toInt()) { finish() })

        setContentView(p.raiz)
        volver.requestFocus()
    }
}
