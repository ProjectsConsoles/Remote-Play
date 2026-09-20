package com.projectsconsoles.remoteplay

import android.content.Intent
import android.graphics.drawable.GradientDrawable
import android.os.Bundle
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView

/**
 * Menu principal en mosaicos, como el de la Deck: arriba lo de jugar (Streaming, Solo control),
 * debajo lo de configurar, y abajo Info y Salir. Una tira de estado avisa como esta el servidor.
 */
class MainActivity : PantallaActivity() {

    // Es la pantalla de inicio: B no la cierra.
    override val volverConB: Boolean = false

    private lateinit var prefs: Prefs
    private lateinit var estadoRed: TextView
    private lateinit var estadoServidor: TextView
    private lateinit var punto: GradientDrawable
    private var consulta = 0

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        prefs = Prefs(this)

        // Pantallas bajitas (celular en horizontal): todo un poco mas chico para que quepa sin scroll.
        val compacto = resources.configuration.screenHeightDp < 500
        val margen = Ui.dp(this, if (compacto) 10 else 20)

        val raiz = LinearLayout(this)
        raiz.orientation = LinearLayout.VERTICAL
        raiz.clipChildren = false
        raiz.clipToPadding = false // el mosaico enfocado se agranda y no debe recortarse en el borde
        raiz.setPadding(margen, margen, margen, margen)
        raiz.layoutParams = ViewGroup.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT,
        )

        // --- cabecera: titulo a la izquierda, red a la derecha ---
        val cabecera = LinearLayout(this)
        cabecera.orientation = LinearLayout.HORIZONTAL
        cabecera.gravity = Gravity.CENTER_VERTICAL
        val titulo = TextView(this)
        titulo.text = "Remote Play"
        titulo.setTextColor(Ui.TEXTO)
        titulo.textSize = if (compacto) 22f else 30f
        titulo.setTypeface(titulo.typeface, android.graphics.Typeface.BOLD)
        cabecera.addView(titulo, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        estadoRed = TextView(this)
        estadoRed.setTextColor(Ui.TENUE)
        estadoRed.textSize = if (compacto) 11f else 13f
        estadoRed.gravity = Gravity.END
        estadoRed.text = "v${Ui.version(this)}"
        cabecera.addView(estadoRed, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1.4f))
        raiz.addView(cabecera)

        // --- tira de estado del servidor ---
        val tira = LinearLayout(this)
        tira.orientation = LinearLayout.HORIZONTAL
        tira.gravity = Gravity.CENTER_VERTICAL
        val fondoTira = GradientDrawable()
        fondoTira.cornerRadius = Ui.dp(this, 12).toFloat()
        fondoTira.setColor(Ui.PANEL)
        tira.background = fondoTira
        tira.setPadding(Ui.dp(this, 14), Ui.dp(this, if (compacto) 6 else 10), Ui.dp(this, 14), Ui.dp(this, if (compacto) 6 else 10))
        val vistaPunto = View(this)
        punto = GradientDrawable()
        punto.shape = GradientDrawable.OVAL
        punto.setColor(Ui.TENUE)
        vistaPunto.background = punto
        tira.addView(vistaPunto, LinearLayout.LayoutParams(Ui.dp(this, 12), Ui.dp(this, 12)).also {
            it.marginEnd = Ui.dp(this, 12)
        })
        estadoServidor = TextView(this)
        estadoServidor.setTextColor(Ui.TEXTO)
        estadoServidor.textSize = if (compacto) 12f else 15f
        estadoServidor.text = "Servidor ${prefs.servidorIp}: consultando..."
        tira.addView(estadoServidor, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        raiz.addView(
            tira,
            LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
                .also {
                    it.topMargin = Ui.dp(this, if (compacto) 4 else 8)
                    it.bottomMargin = Ui.dp(this, if (compacto) 4 else 8)
                },
        )

        // --- mosaicos 2x2 ---
        val streaming = Ui.mosaico(
            this, R.drawable.ic_play, "Streaming", "Video y audio de la consola + el mando",
            0xFF2D6CDF.toInt(), compacto,
        ) { startActivity(Intent(this, StreamActivity::class.java)) }
        val soloControl = Ui.mosaico(
            this, R.drawable.ic_gamepad, "Solo control", "La tableta es solo el mando",
            0xFF3F8F4A.toInt(), compacto,
        ) {
            startActivity(Intent(this, StreamActivity::class.java).putExtra(StreamActivity.EXTRA_SOLO_CONTROL, true))
        }
        val servidor = Ui.mosaico(
            this, R.drawable.ic_server, "Configurar servidor", "Modo de captura y estado de la PC",
            0xFF8E5FD6.toInt(), compacto,
        ) { startActivity(Intent(this, ServerConfigActivity::class.java)) }
        val cliente = Ui.mosaico(
            this, R.drawable.ic_settings, "Configurar cliente", "IP del ESP32, mando e imagen",
            0xFFC07D2F.toInt(), compacto,
        ) { startActivity(Intent(this, ClientConfigActivity::class.java)) }

        raiz.addView(fila(streaming, soloControl))
        raiz.addView(fila(servidor, cliente))

        // --- pie: Info y Salir ---
        val pie = LinearLayout(this)
        pie.orientation = LinearLayout.HORIZONTAL
        pie.gravity = Gravity.CENTER
        pie.addView(Ui.botonIcono(this, R.drawable.ic_info, "Info: colores del ESP32", 0xFF2A3441.toInt()) {
            startActivity(Intent(this, InfoActivity::class.java))
        })
        pie.addView(Ui.botonIcono(this, R.drawable.ic_exit, "Salir", 0xFF7A2E2E.toInt()) { finishAffinity() })
        raiz.addView(
            pie,
            LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
                .also { it.topMargin = Ui.dp(this, 4) },
        )

        // ScrollView solo como red de seguridad si la pantalla es aun mas bajita.
        val scroll = ScrollView(this)
        scroll.setBackgroundColor(Ui.FONDO)
        scroll.isFillViewport = true
        scroll.clipChildren = false
        scroll.addView(raiz)
        setContentView(scroll)
        streaming.requestFocus()
    }

    /** Una fila de dos mosaicos que se reparten el ancho y, entre las dos filas, el alto. */
    private fun fila(a: View, b: View): LinearLayout {
        val f = LinearLayout(this)
        f.orientation = LinearLayout.HORIZONTAL
        f.clipChildren = false
        val m = Ui.dp(this, if (resources.configuration.screenHeightDp < 500) 4 else 6)
        f.addView(a, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.MATCH_PARENT, 1f).also { it.setMargins(m, m, m, m) })
        f.addView(b, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.MATCH_PARENT, 1f).also { it.setMargins(m, m, m, m) })
        f.layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f)
        return f
    }

    override fun onResume() {
        super.onResume()
        refrescarEstado()
    }

    private fun refrescarEstado() {
        val ipServidor = prefs.servidorIp
        val miConsulta = ++consulta
        pintar(Ui.TENUE, "Servidor $ipServidor: consultando...")
        Thread {
            val miIp = Net.ipLocal()
            val resp = ServerClient.obtenerConfig(ipServidor)
            runOnUiThread {
                if (isDestroyed || miConsulta != consulta) return@runOnUiThread
                estadoRed.text = "Tableta ${miIp ?: "sin red"}  ·  ESP32 ${prefs.esp32Ip}:${prefs.esp32Puerto}  ·  v${Ui.version(this)}"
                pintarServidor(ipServidor, miIp, resp)
            }
        }.start()
    }

    private fun pintar(color: Int, texto: String) {
        punto.setColor(color)
        estadoServidor.text = texto
    }

    private fun pintarServidor(ipServidor: String, miIp: String?, resp: ServerClient.Resp) {
        when (resp) {
            is ServerClient.Resp.Error -> pintar(
                Ui.ERROR,
                "Servidor $ipServidor: sin respuesta. ¿Prendido y en la misma red?",
            )
            is ServerClient.Resp.Ok -> {
                val j = resp.json
                val corriendo = j.optBoolean("corriendo", false)
                val transmitiendo = j.optBoolean("transmitiendo", corriendo)
                val destino = j.optString("ip", "")
                val modo = j.optString("modo", "?")
                when {
                    !corriendo -> pintar(
                        Ui.AVISO,
                        "Servidor $ipServidor: detenido (modo $modo). Enciéndelo en la PC o aplica la configuración.",
                    )
                    !transmitiendo -> pintar(
                        Ui.AVISO,
                        "Servidor $ipServidor: corriendo pero SIN transmitir. Revisa la capturadora.",
                    )
                    miIp != null && destino.isNotEmpty() && destino != miIp -> pintar(
                        Ui.AVISO,
                        "Servidor $ipServidor: transmite a $destino, no a esta tableta ($miIp). Entra a Configurar servidor y aplica.",
                    )
                    else -> pintar(Ui.OK, "Servidor $ipServidor: transmitiendo a $destino ($modo)")
                }
            }
        }
    }
}
