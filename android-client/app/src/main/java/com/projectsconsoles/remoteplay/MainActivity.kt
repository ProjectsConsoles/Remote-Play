package com.projectsconsoles.remoteplay

import android.content.Intent
import android.os.Bundle
import android.widget.TextView

/** Menu principal, igual en espiritu al de la Deck: Streaming, Solo control, configuraciones e info. */
class MainActivity : PantallaActivity() {

    // Es la pantalla de inicio: B no la cierra.
    override val volverConB: Boolean = false

    private lateinit var prefs: Prefs
    private lateinit var estadoRed: TextView
    private lateinit var estadoServidor: TextView
    private var consulta = 0

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        prefs = Prefs(this)

        val p = Ui.Pantalla(this)
        p.agregar(Ui.titulo(this, "Remote Play"))
        estadoRed = p.agregar(Ui.texto(this, "Tableta: buscando IP..."))
        estadoServidor = p.agregar(Ui.texto(this, "Servidor: consultando..."))

        val streaming = p.agregar(
            Ui.boton(this, "Streaming\nVideo y audio de la consola + el mando", 0xFF2D6CDF.toInt()) {
                startActivity(Intent(this, StreamActivity::class.java))
            },
        )
        p.agregar(
            Ui.boton(this, "Solo control\nLa tableta es solo el mando (pantalla al minimo)", 0xFF3F8F4A.toInt()) {
                startActivity(
                    Intent(this, StreamActivity::class.java).putExtra(StreamActivity.EXTRA_SOLO_CONTROL, true),
                )
            },
        )
        p.agregar(
            Ui.boton(this, "Configurar servidor\nModo de captura y estado de la PC Windows", 0xFF8E5FD6.toInt()) {
                startActivity(Intent(this, ServerConfigActivity::class.java))
            },
        )
        p.agregar(
            Ui.boton(this, "Configurar cliente\nIP del ESP32, mando, imagen", 0xFFC07D2F.toInt()) {
                startActivity(Intent(this, ClientConfigActivity::class.java))
            },
        )
        p.agregar(
            Ui.boton(this, "Info: colores del ESP32-S3", 0xFF2A3441.toInt()) {
                startActivity(Intent(this, InfoActivity::class.java))
            },
        )
        p.agregar(
            Ui.boton(this, "Salir", 0xFF7A2E2E.toInt()) { finishAffinity() },
        )
        p.agregar(Ui.texto(this, "Versión ${Ui.version(this)}", Ui.TENUE, 13f))

        setContentView(p.raiz)
        streaming.requestFocus()
    }

    override fun onResume() {
        super.onResume()
        refrescarEstado()
    }

    private fun refrescarEstado() {
        val ipServidor = prefs.servidorIp
        val miConsulta = ++consulta
        estadoServidor.setTextColor(Ui.TENUE)
        estadoServidor.text = "Servidor $ipServidor: consultando..."
        Thread {
            val miIp = Net.ipLocal()
            val resp = ServerClient.obtenerConfig(ipServidor)
            runOnUiThread {
                if (isDestroyed || miConsulta != consulta) return@runOnUiThread
                estadoRed.text = "Tableta: ${miIp ?: "sin red"}   ·   ESP32: ${prefs.esp32Ip}:${prefs.esp32Puerto}"
                pintarServidor(ipServidor, miIp, resp)
            }
        }.start()
    }

    private fun pintarServidor(ipServidor: String, miIp: String?, resp: ServerClient.Resp) {
        when (resp) {
            is ServerClient.Resp.Error -> {
                estadoServidor.setTextColor(Ui.AVISO)
                estadoServidor.text = "Servidor $ipServidor: sin respuesta.\n" +
                    "¿Está prendido y en la misma red? (Configurar servidor para cambiar la IP)"
            }
            is ServerClient.Resp.Ok -> {
                val j = resp.json
                val corriendo = j.optBoolean("corriendo", false)
                val transmitiendo = j.optBoolean("transmitiendo", corriendo)
                val destino = j.optString("ip", "")
                val modo = j.optString("modo", "?")
                when {
                    !corriendo -> {
                        estadoServidor.setTextColor(Ui.AVISO)
                        estadoServidor.text = "Servidor $ipServidor: detenido (modo $modo).\n" +
                            "Enciéndelo en la PC, o aplica la configuración."
                    }
                    !transmitiendo -> {
                        estadoServidor.setTextColor(Ui.AVISO)
                        estadoServidor.text = "Servidor $ipServidor: corriendo pero SIN transmitir.\n" +
                            "Revisa la capturadora."
                    }
                    miIp != null && destino.isNotEmpty() && destino != miIp -> {
                        estadoServidor.setTextColor(Ui.AVISO)
                        estadoServidor.text = "Servidor $ipServidor: transmite a $destino, no a esta tableta ($miIp).\n" +
                            "Entra a Configurar servidor y aplica."
                    }
                    else -> {
                        estadoServidor.setTextColor(Ui.OK)
                        estadoServidor.text = "Servidor $ipServidor: transmitiendo a $destino ($modo)."
                    }
                }
            }
        }
    }
}
