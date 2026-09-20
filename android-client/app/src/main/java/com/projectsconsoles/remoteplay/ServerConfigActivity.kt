package com.projectsconsoles.remoteplay

import android.os.Bundle
import android.widget.Button
import android.widget.EditText
import android.widget.TextView

/**
 * Configurar el servidor Windows en remoto (protocolo UDP 9200, el mismo de la Deck y la Ally):
 * consultar, aplicar modo + IP de esta tableta (reinicia el servidor si esta corriendo) y apagarlo.
 */
class ServerConfigActivity : PantallaActivity() {

    private lateinit var prefs: Prefs
    private lateinit var campoServidor: EditText
    private lateinit var campoDestino: EditText
    private lateinit var botonModo: Button
    private lateinit var resultado: TextView
    private val botones = mutableListOf<Button>()
    private var modo = "mjpeg720"
    private var ocupado = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        prefs = Prefs(this)

        val p = Ui.Pantalla(this)
        p.agregar(Ui.titulo(this, "Configurar servidor"))

        p.agregar(Ui.texto(this, "IP de la PC Windows (servidor)"))
        campoServidor = p.agregar(Ui.campo(this, prefs.servidorIp, soloIp = true))

        p.agregar(Ui.texto(this, "IP de esta tableta (a donde el servidor manda el video)"))
        campoDestino = p.agregar(Ui.campo(this, "", soloIp = true))
        campoDestino.hint = "detectando..."

        botonModo = p.agregar(
            Ui.opcion(this, "Modo de captura", ServerClient.MODOS, modo) { modo = it },
        )

        botones += p.agregar(Ui.boton(this, "Consultar servidor") { consultar() })
        botones += p.agregar(
            Ui.boton(this, "Aplicar (reinicia el servidor si está corriendo)", 0xFF3F8F4A.toInt()) { aplicar() },
        )
        botones += p.agregar(Ui.boton(this, "Apagar servidor", 0xFF7A2E2E.toInt()) { apagar() })
        p.agregar(Ui.boton(this, "Volver", 0xFF2A3441.toInt()) { finish() })

        resultado = p.agregar(Ui.texto(this, "", Ui.TEXTO, 16f))

        setContentView(p.raiz)

        Thread {
            val ip = Net.ipLocal()
            runOnUiThread {
                if (isDestroyed) return@runOnUiThread
                if (ip != null && campoDestino.text.isNullOrBlank()) campoDestino.setText(ip)
                if (ip == null) campoDestino.hint = "no se detectó, escríbela"
            }
        }.start()
        consultar()
    }

    override fun onPause() {
        super.onPause()
        guardarIp()
    }

    private fun guardarIp() {
        val ip = campoServidor.text.toString().trim()
        if (ip.isNotEmpty()) prefs.servidorIp = ip
    }

    private fun ocupar(mensaje: String) {
        ocupado = true
        botones.forEach { it.isEnabled = false }
        resultado.setTextColor(Ui.TENUE)
        resultado.text = mensaje
    }

    private fun liberar() {
        ocupado = false
        botones.forEach { it.isEnabled = true }
    }

    private fun mostrar(texto: String, color: Int) {
        resultado.setTextColor(color)
        resultado.text = texto
    }

    private fun consultar() {
        if (ocupado) return
        guardarIp()
        val ip = prefs.servidorIp
        ocupar("Consultando $ip...")
        Thread {
            val r = ServerClient.obtenerConfig(ip)
            runOnUiThread {
                if (isDestroyed) return@runOnUiThread
                liberar()
                when (r) {
                    is ServerClient.Resp.Error -> mostrar(r.mensaje, Ui.AVISO)
                    is ServerClient.Resp.Ok -> {
                        val j = r.json
                        val modoServidor = j.optString("modo", "")
                        if (ServerClient.MODOS.any { it.first == modoServidor }) {
                            modo = modoServidor
                            reemplazarBotonModo()
                        }
                        val estado = when {
                            !j.optBoolean("corriendo", false) -> "DETENIDO"
                            j.optBoolean("transmitiendo", true) -> "TRANSMITIENDO"
                            else -> "CORRIENDO pero sin transmitir (revisa la capturadora)"
                        }
                        mostrar(
                            "Servidor: $estado\nManda a: ${j.optString("ip", "?")}\nModo: ${j.optString("modo", "?")}",
                            if (estado == "TRANSMITIENDO") Ui.OK else Ui.AVISO,
                        )
                    }
                }
            }
        }.start()
    }

    /** El boton cicla por dentro y no expone su indice: se cambia por uno nuevo con el modo actual. */
    private fun reemplazarBotonModo() {
        val padre = botonModo.parent as android.view.ViewGroup
        val pos = padre.indexOfChild(botonModo)
        padre.removeView(botonModo)
        botonModo = Ui.opcion(this, "Modo de captura", ServerClient.MODOS, modo) { modo = it }
        padre.addView(botonModo, pos)
    }

    private fun aplicar() {
        if (ocupado) return
        guardarIp()
        val ip = prefs.servidorIp
        val destino = campoDestino.text.toString().trim()
        if (destino.isEmpty()) {
            mostrar("Falta la IP de esta tableta.", Ui.ERROR)
            return
        }
        ocupar("Aplicando en $ip (puede tardar hasta 20 s si reinicia el servidor)...")
        val modoElegido = modo
        Thread {
            val r = ServerClient.aplicarConfig(ip, destino, modoElegido)
            runOnUiThread {
                if (isDestroyed) return@runOnUiThread
                liberar()
                when (r) {
                    is ServerClient.Resp.Error -> mostrar(r.mensaje, Ui.AVISO)
                    is ServerClient.Resp.Ok -> {
                        val j = r.json
                        if (j.optBoolean("ok", false)) {
                            val como = when (j.optString("aplicado")) {
                                "reiniciado" -> "Servidor reiniciado con la config nueva."
                                "guardado_para_proxima_vez" ->
                                    "Guardado. El servidor estaba detenido: enciéndelo en la PC y usará esta config."
                                else -> "Aplicado."
                            }
                            mostrar("$como\nManda a $destino, modo $modoElegido.", Ui.OK)
                        } else {
                            mostrar(j.optString("error", "El servidor rechazó la config."), Ui.ERROR)
                        }
                    }
                }
            }
        }.start()
    }

    private fun apagar() {
        if (ocupado) return
        guardarIp()
        val ip = prefs.servidorIp
        ocupar("Apagando el servidor en $ip...")
        Thread {
            val r = ServerClient.detenerServidor(ip)
            runOnUiThread {
                if (isDestroyed) return@runOnUiThread
                liberar()
                when (r) {
                    is ServerClient.Resp.Error -> mostrar(r.mensaje, Ui.AVISO)
                    is ServerClient.Resp.Ok -> {
                        val j = r.json
                        if (j.optBoolean("ok", false)) {
                            mostrar(
                                if (j.optString("aplicado") == "ya_estaba_detenido") "El servidor ya estaba detenido."
                                else "Servidor detenido.",
                                Ui.OK,
                            )
                        } else {
                            mostrar(j.optString("error", "No se pudo apagar."), Ui.ERROR)
                        }
                    }
                }
            }
        }.start()
    }
}
