package com.projectsconsoles.remoteplay

import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.View
import android.view.ViewGroup
import android.widget.LinearLayout
import android.widget.ScrollView

/**
 * Menu aparte para el streaming de juegos de PC (pedido 2026-11-16): antes vivia abajo en "¿Qué consola?".
 * Jugar, Reiniciar Steam (nuevo), Reiniciar servidor de PC y la IP de la PC. La tira de arriba dice como
 * esta el servidor de la PC y, con el foco, que hace cada tarjeta.
 */
class PcActivity : PantallaActivity() {

    private lateinit var prefs: Prefs
    private lateinit var tira: Ui.TiraEstado
    private var ocupado = false
    private var consulta = 0
    private val estados = HashMap<View, Pair<Int, String>>()
    private val principal = Handler(Looper.getMainLooper())

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        prefs = Prefs(this)

        val compacto = resources.configuration.screenHeightDp < 500
        val margen = Ui.dp(this, if (compacto) 10 else 20)
        val raiz = LinearLayout(this)
        raiz.orientation = LinearLayout.VERTICAL
        raiz.clipChildren = false
        raiz.clipToPadding = false
        raiz.setPadding(margen, margen, margen, margen)
        raiz.addView(Ui.cabecera(this, "PC", "Juegos de Windows en la tableta", compacto))
        tira = Ui.TiraEstado(this, compacto)
        raiz.addView(
            tira.vista,
            LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
                .also {
                    it.topMargin = Ui.dp(this, if (compacto) 4 else 8)
                    it.bottomMargin = Ui.dp(this, if (compacto) 4 else 8)
                },
        )

        val jugar = Ui.mosaico(
            this, R.drawable.ic_play, "Jugar en la PC", "Transmite la pantalla; el mando llega como control de Xbox",
            0xFF2D6CDF.toInt(), compacto,
        ) { jugar() }
        estados[jugar] = Ui.TENUE to "Le pide a la PC que transmita a esta tableta y arranca el streaming."

        val steam = Ui.mosaico(
            this, R.drawable.ic_refresh, "Reiniciar Steam", "Si en la tableta se ve negro y en la PC sí",
            0xFF2A6F97.toInt(), compacto,
        ) { reiniciarSteam() }
        estados[steam] = Ui.TENUE to "Cierra Steam en la PC y lo abre en Big Picture (~30 s). Sin levantarse a la laptop."

        val servidor = Ui.mosaico(
            this, R.drawable.ic_server, "Reiniciar servidor", "Si se trabó la imagen o el control",
            0xFF8A4B14.toInt(), compacto,
        ) { reiniciarServidor() }
        estados[servidor] = Ui.TENUE to "Deja el servidor de la PC como recién abierto. Luego elige Jugar otra vez."

        val ip = Ui.mosaicoTexto(
            this, R.drawable.ic_computer, "IP de la PC", prefs.pcIp, 0xFF3F8F4A.toInt(), compacto, esIp = true,
        ) { v -> Ui.ipValida(v).also { if (it) { prefs.pcIp = v; refrescarEstado() } } }
        estados[ip] = Ui.TENUE to "La laptop con el servidor de PC. Se guarda sola."

        val volver = Ui.mosaico(
            this, R.drawable.ic_back, "Volver", "Al menú", 0xFF2A3441.toInt(), compacto,
            tamTitulo = if (compacto) 15f else 22f,
        ) { finish() }
        estados[volver] = Ui.TENUE to "Volver al menú."

        raiz.addView(
            Ui.cuadricula(this, compacto, listOf(listOf(jugar, steam, servidor), listOf(ip, volver))),
            LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f),
        )

        val scroll = ScrollView(this)
        scroll.isFillViewport = true
        scroll.clipChildren = false
        scroll.clipToPadding = false
        scroll.addView(raiz, ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))
        setContentView(scroll)

        scroll.viewTreeObserver.addOnGlobalFocusChangeListener { _, nueva ->
            if (!ocupado) estados[nueva]?.let { tira.pintar(it.first, it.second) }
        }
        jugar.requestFocus()
    }

    override fun onResume() {
        super.onResume()
        refrescarEstado()
    }

    override fun onDestroy() {
        principal.removeCallbacksAndMessages(null)
        super.onDestroy()
    }

    private fun refrescarEstado() {
        if (ocupado) return
        val ipPc = prefs.pcIp
        val miConsulta = ++consulta
        tira.pintar(Ui.TENUE, "PC $ipPc: consultando...")
        Thread {
            val r = ServerClient.obtenerConfig(ipPc)
            runOnUiThread {
                if (isDestroyed || ocupado || miConsulta != consulta) return@runOnUiThread
                when (r) {
                    is ServerClient.Resp.Error ->
                        tira.pintar(Ui.AVISO, "PC $ipPc: sin respuesta. ¿Prendida y con el servidor de PC corriendo?")
                    is ServerClient.Resp.Ok ->
                        if (r.json.optBoolean("corriendo", false)) {
                            tira.pintar(Ui.OK, "PC $ipPc: lista, transmitiendo a ${r.json.optString("ip", "?")}.")
                        } else {
                            tira.pintar(Ui.OK, "PC $ipPc: lista.")
                        }
                }
            }
        }.start()
    }

    /** Le pide a la PC (UDP 9200) que transmita a esta tableta y abre el streaming con el mando a la PC. */
    private fun jugar() {
        if (ocupado) return
        ocupado = true
        val ipPc = prefs.pcIp
        tira.pintar(Ui.TENUE, "Pidiéndole a la PC ($ipPc) que transmita a esta tableta...")
        Thread {
            val miIp = Net.ipLocal()
            // get_config primero (3 s): si la PC no responde se avisa rapido, sin esperar los 20 s de set_config.
            val resp = when {
                miIp == null -> null
                ServerClient.obtenerConfig(ipPc) is ServerClient.Resp.Error -> ServerClient.Resp.Error("sin respuesta")
                else -> ServerClient.aplicarConfig(ipPc, miIp, "pc")
            }
            runOnUiThread {
                if (isDestroyed) return@runOnUiThread
                when {
                    miIp == null -> {
                        ocupado = false
                        tira.pintar(Ui.ERROR, "Esta tableta no tiene red.")
                    }
                    resp is ServerClient.Resp.Error -> {
                        ocupado = false
                        tira.pintar(Ui.AVISO, "La PC $ipPc no responde. ¿Está prendida y con el servidor de PC corriendo?")
                    }
                    else -> {
                        tira.pintar(Ui.OK, "PC lista: arrancando el streaming...")
                        ocupado = false
                        startActivity(
                            Intent(this, StreamActivity::class.java)
                                .putExtra(StreamActivity.EXTRA_CONTROL_IP, ipPc)
                                .putExtra(StreamActivity.EXTRA_CONTROL_PUERTO, PUERTO_CONTROL_PC)
                                .putExtra(StreamActivity.EXTRA_FUENTE, "PC $ipPc")
                                .putExtra(StreamActivity.EXTRA_TACTIL_PC, true)
                                .putExtra(StreamActivity.EXTRA_REPORTAR_RED, true),
                        )
                    }
                }
            }
        }.start()
    }

    private fun reiniciarServidor() {
        if (ocupado) return
        ocupado = true
        val ipPc = prefs.pcIp
        tira.pintar(Ui.TENUE, "Reiniciando el servidor de la PC ($ipPc)...")
        Thread {
            val resp = ServerClient.reiniciarServidorPc(ipPc)
            runOnUiThread {
                if (isDestroyed) return@runOnUiThread
                ocupado = false
                when {
                    resp is ServerClient.Resp.Error ->
                        tira.pintar(Ui.AVISO, "La PC $ipPc no responde. ¿Está prendida y con el servidor de PC corriendo?")
                    resp is ServerClient.Resp.Ok && !resp.json.optBoolean("ok", false) ->
                        tira.pintar(Ui.ERROR, "La PC no pudo reiniciar: ${resp.json.optString("error", "servidor viejo, sin este comando")}")
                    else -> tira.pintar(Ui.OK, "Servidor de PC reiniciado. Elige Jugar para volver a jugar.")
                }
            }
        }.start()
    }

    /** Pedido 2026-11-16: Steam a veces solo se ve en la laptop; cerrarlo y abrirlo lo compone. */
    private fun reiniciarSteam() {
        if (ocupado) return
        ocupado = true
        val ipPc = prefs.pcIp
        tira.pintar(Ui.TENUE, "Pidiéndole a la PC ($ipPc) que reinicie Steam...")
        Thread {
            val resp = ServerClient.reiniciarSteamPc(ipPc)
            runOnUiThread {
                if (isDestroyed) return@runOnUiThread
                when {
                    resp is ServerClient.Resp.Error -> {
                        ocupado = false
                        tira.pintar(Ui.AVISO, "La PC $ipPc no responde. ¿Está prendida y con el servidor de PC corriendo?")
                    }
                    resp is ServerClient.Resp.Ok && !resp.json.optBoolean("ok", false) -> {
                        ocupado = false
                        tira.pintar(Ui.ERROR, "La PC no reconoce el comando: actualiza el servidor de PC.")
                    }
                    else -> seguirSteam(System.currentTimeMillis())
                }
            }
        }.start()
    }

    /** Pregunta cada 2 s como va el reinicio de Steam (get_config -> "steam"), hasta 90 s. */
    private fun seguirSteam(inicio: Long) {
        val ipPc = prefs.pcIp
        Thread {
            val r = ServerClient.obtenerConfig(ipPc)
            runOnUiThread {
                if (isDestroyed) return@runOnUiThread
                val estado = (r as? ServerClient.Resp.Ok)?.json?.optString("steam", "") ?: ""
                val seg = (System.currentTimeMillis() - inicio) / 1000
                when {
                    estado == "listo" -> {
                        ocupado = false
                        tira.pintar(Ui.OK, "Steam reiniciado. Big Picture tarda unos segundos más en salir; luego elige Jugar.")
                    }
                    estado.startsWith("error") -> {
                        ocupado = false
                        tira.pintar(Ui.ERROR, "No se pudo reiniciar Steam: ${estado.removePrefix("error:").trim()}")
                    }
                    seg > 90 -> {
                        ocupado = false
                        tira.pintar(Ui.AVISO, "Steam sigue sin terminar de reiniciar tras 90 s. Revisa la laptop.")
                    }
                    else -> {
                        val paso = when (estado) {
                            "cerrando" -> "cerrando Steam"
                            "abriendo" -> "abriendo Steam en Big Picture"
                            else -> "esperando a la PC"
                        }
                        tira.pintar(Consolas.AMARILLO_AVISO, "Reiniciando Steam: $paso... (${seg} s)")
                        principal.postDelayed({ if (!isDestroyed) seguirSteam(inicio) }, 2000)
                    }
                }
            }
        }.start()
    }

    companion object {
        /** Puerto UDP donde el servidor de PC recibe el mando (el mismo JSON que el ESP32). */
        const val PUERTO_CONTROL_PC = 9000
    }
}
