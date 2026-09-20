package com.projectsconsoles.remoteplay

import android.os.Bundle
import android.view.ViewGroup
import android.widget.LinearLayout

/**
 * Ajustes de esta tableta en mosaicos (3x3, sin scroll). Los de lista (imagen, Hz, boton PS...) cambian
 * al siguiente valor con un toque o A; IP y puertos abren un cuadro para escribirlos. Todo se guarda
 * al instante.
 */
class ClientConfigActivity : PantallaActivity() {

    private lateinit var prefs: Prefs

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        prefs = Prefs(this)

        val compacto = resources.configuration.screenHeightDp < 500
        val margen = Ui.dp(this, if (compacto) 10 else 20)
        val azul = 0xFF2D6CDF.toInt()
        val naranja = 0xFFC07D2F.toInt()
        val verde = 0xFF3F8F4A.toInt()
        val morado = 0xFF8E5FD6.toInt()

        val raiz = LinearLayout(this)
        raiz.orientation = LinearLayout.VERTICAL
        raiz.clipChildren = false
        raiz.clipToPadding = false
        raiz.setPadding(margen, margen, margen, margen)
        raiz.addView(
            Ui.cabecera(this, "Configurar cliente", "Salir del streaming: L1 + R1 + SELECT + START", compacto),
        )

        val ip = Ui.mosaicoTexto(
            this, R.drawable.ic_wifi, "IP del ESP32-S3", prefs.esp32Ip, azul, compacto, esIp = true,
        ) { v -> Ui.ipValida(v).also { if (it) prefs.esp32Ip = v } }

        val puertoEsp = Ui.mosaicoTexto(
            this, R.drawable.ic_port, "Puerto del ESP32", prefs.esp32Puerto.toString(), azul, compacto, esIp = false,
        ) { v -> puerto(v)?.let { prefs.esp32Puerto = it; true } ?: false }

        val puertoVideo = Ui.mosaicoTexto(
            this, R.drawable.ic_play, "Puerto de video", prefs.puertoVideo.toString(), azul, compacto, esIp = false,
        ) { v -> puerto(v)?.let { prefs.puertoVideo = it; true } ?: false }

        val imagen = Ui.mosaicoCiclo(
            this, R.drawable.ic_image, "Ajuste de imagen",
            listOf("barras" to "Barras negras", "estirar" to "Estirar", "zoom" to "Llenar recortando"),
            { prefs.ajusteImagen }, naranja, compacto,
        ) { prefs.ajusteImagen = it }

        val hz = Ui.mosaicoCiclo(
            this, R.drawable.ic_speed, "Frecuencia del mando",
            listOf(60, 90, 120, 180, 250).map { it.toString() to "$it Hz" },
            { prefs.frecuenciaMando.toString() }, verde, compacto,
        ) { prefs.frecuenciaMando = it.toInt() }

        val botonPs = Ui.mosaicoCiclo(
            this, R.drawable.ic_gamepad, "Botón PS (acorde)",
            listOf(
                "SELECT+R1" to "SELECT + R1",
                "SELECT+L1" to "SELECT + L1",
                "SELECT+START" to "SELECT + START",
                "none" to "Ninguno (solo Guía)",
            ),
            { prefs.acordePs }, verde, compacto,
        ) { prefs.acordePs = it }

        val zona = Ui.mosaicoCiclo(
            this, R.drawable.ic_tune, "Zona muerta de sticks",
            listOf("nada" to "Ninguna", "medio" to "Media (6 %)", "alta" to "Alta (12 %)"),
            { prefs.zonaMuerta }, verde, compacto,
        ) { prefs.zonaMuerta = it }

        val sinVideo = Ui.mosaicoCiclo(
            this, R.drawable.ic_timer, "Cerrar si no hay video en",
            listOf(15, 25, 40, 60, 120).map { it.toString() to "$it s" },
            { prefs.segundosSinVideo.toString() }, morado, compacto,
        ) { prefs.segundosSinVideo = it.toInt() }

        val volver = Ui.mosaico(
            this, R.drawable.ic_back, "Volver", "Todo se guarda solo", 0xFF2A3441.toInt(), compacto,
            tamTitulo = if (compacto) 15f else 22f,
        ) { finish() }

        raiz.addView(
            Ui.cuadricula(
                this, compacto,
                listOf(
                    listOf(ip, puertoEsp, puertoVideo),
                    listOf(imagen, hz, botonPs),
                    listOf(zona, sinVideo, volver),
                ),
            ),
            LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f),
        )

        val scroll = android.widget.ScrollView(this)
        scroll.isFillViewport = true
        scroll.clipChildren = false
        scroll.clipToPadding = false
        scroll.addView(
            raiz,
            ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT),
        )
        setContentView(scroll)
        ip.requestFocus()
    }

    private fun puerto(s: String): Int? = s.toIntOrNull()?.takeIf { it in 1..65535 }
}
