package com.projectsconsoles.remoteplay

import android.content.Intent
import android.os.Bundle
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
    private lateinit var cabecera: LinearLayout
    private lateinit var tira: Ui.TiraEstado
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

        cabecera = Ui.cabecera(this, "Remote Play", "v${Ui.version(this)}", compacto)
        raiz.addView(cabecera)

        tira = Ui.TiraEstado(this, compacto)
        tira.pintar(Ui.TENUE, "Servidor ${prefs.servidorIp}: consultando...")
        raiz.addView(
            tira.vista,
            LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
                .also {
                    it.topMargin = Ui.dp(this, if (compacto) 4 else 8)
                    it.bottomMargin = Ui.dp(this, if (compacto) 4 else 8)
                },
        )

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

        raiz.addView(
            Ui.cuadricula(this, compacto, listOf(listOf(streaming, soloControl), listOf(servidor, cliente))),
            LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f),
        )

        val pie = LinearLayout(this)
        pie.orientation = LinearLayout.HORIZONTAL
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
        scroll.isFillViewport = true
        scroll.clipChildren = false
        scroll.clipToPadding = false
        scroll.addView(raiz)
        setContentView(scroll)
        streaming.requestFocus()
    }

    override fun onResume() {
        super.onResume()
        refrescarEstado()
    }

    private fun refrescarEstado() {
        val ipServidor = prefs.servidorIp
        val miConsulta = ++consulta
        tira.pintar(Ui.TENUE, "Servidor $ipServidor: consultando...")
        Thread {
            val miIp = Net.ipLocal()
            val resp = ServerClient.obtenerConfig(ipServidor)
            runOnUiThread {
                if (isDestroyed || miConsulta != consulta) return@runOnUiThread
                (cabecera.getChildAt(1) as TextView).text =
                    "Tableta ${miIp ?: "sin red"}  ·  ESP32 ${prefs.esp32Ip}:${prefs.esp32Puerto}  ·  v${Ui.version(this)}"
                pintarServidor(ipServidor, miIp, resp)
            }
        }.start()
    }

    private fun pintarServidor(ipServidor: String, miIp: String?, resp: ServerClient.Resp) {
        when (resp) {
            is ServerClient.Resp.Error -> tira.pintar(
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
                    !corriendo -> tira.pintar(
                        Ui.AVISO,
                        "Servidor $ipServidor: detenido (modo $modo). Enciéndelo en la PC o aplica la configuración.",
                    )
                    !transmitiendo -> tira.pintar(
                        Ui.AVISO,
                        "Servidor $ipServidor: corriendo pero SIN transmitir. Revisa la capturadora.",
                    )
                    miIp != null && destino.isNotEmpty() && destino != miIp -> tira.pintar(
                        Ui.AVISO,
                        "Servidor $ipServidor: transmite a $destino, no a esta tableta ($miIp). Entra a Configurar servidor y aplica.",
                    )
                    else -> tira.pintar(Ui.OK, "Servidor $ipServidor: transmitiendo a $destino ($modo)")
                }
            }
        }
    }
}
