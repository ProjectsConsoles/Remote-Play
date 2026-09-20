package com.projectsconsoles.remoteplay

import android.os.Bundle
import android.view.View
import android.view.ViewGroup
import android.widget.LinearLayout
import android.widget.ScrollView

/**
 * Configurar el servidor Windows en remoto (protocolo UDP 9200, el mismo de la Deck y la Ally), en
 * mosaicos: IP del servidor, IP de esta tableta y modo de captura; consultar, aplicar (reinicia el
 * servidor si esta corriendo) y apagar. Una tira arriba muestra el resultado de cada accion.
 */
class ServerConfigActivity : PantallaActivity() {

    private lateinit var prefs: Prefs
    private lateinit var tira: Ui.TiraEstado
    private lateinit var tileDestino: LinearLayout
    private lateinit var tileModo: LinearLayout
    private val acciones = mutableListOf<View>()
    private var modo = "mjpeg720"
    private var destino = ""
    private var ocupado = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        prefs = Prefs(this)

        val compacto = resources.configuration.screenHeightDp < 500
        val margen = Ui.dp(this, if (compacto) 10 else 20)
        val morado = 0xFF8E5FD6.toInt()
        val azul = 0xFF2D6CDF.toInt()

        val raiz = LinearLayout(this)
        raiz.orientation = LinearLayout.VERTICAL
        raiz.clipChildren = false
        raiz.clipToPadding = false
        raiz.setPadding(margen, margen, margen, margen)
        raiz.addView(Ui.cabecera(this, "Configurar servidor", "Cambia el modo de captura de la PC en remoto", compacto))

        tira = Ui.TiraEstado(this, compacto)
        tira.pintar(Ui.TENUE, "Consultando ${prefs.servidorIp}...")
        raiz.addView(
            tira.vista,
            LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
                .also {
                    it.topMargin = Ui.dp(this, if (compacto) 4 else 8)
                    it.bottomMargin = Ui.dp(this, if (compacto) 4 else 8)
                },
        )

        val tileServidor = Ui.mosaicoTexto(
            this, R.drawable.ic_server, "IP de la PC (servidor)", prefs.servidorIp, morado, compacto, esIp = true,
        ) { v -> Ui.ipValida(v).also { if (it) prefs.servidorIp = v } }

        tileDestino = Ui.mosaicoTexto(
            this, R.drawable.ic_wifi, "IP de esta tableta (destino del video)", "detectando...", morado, compacto,
            esIp = true, valorDialogo = { destino },
        ) { v -> Ui.ipValida(v).also { if (it) destino = v } }

        tileModo = Ui.mosaicoCiclo(
            this, R.drawable.ic_image, "Modo de captura", ServerClient.MODOS, { modo }, morado, compacto,
        ) { modo = it }

        val consultar = Ui.mosaico(
            this, R.drawable.ic_refresh, "Consultar", "Estado actual del servidor", azul, compacto,
            tamTitulo = if (compacto) 15f else 22f,
        ) { consultar() }
        val aplicar = Ui.mosaico(
            this, R.drawable.ic_check, "Aplicar", "Reinicia el servidor si está corriendo", 0xFF3F8F4A.toInt(), compacto,
            tamTitulo = if (compacto) 15f else 22f,
        ) { aplicar() }
        val apagar = Ui.mosaico(
            this, R.drawable.ic_power, "Apagar servidor", "Detiene la transmisión", 0xFFB03A3A.toInt(), compacto,
            tamTitulo = if (compacto) 15f else 22f,
        ) { apagar() }
        acciones += listOf(consultar, aplicar, apagar)

        raiz.addView(
            Ui.cuadricula(
                this, compacto,
                listOf(listOf(tileServidor, tileDestino, tileModo), listOf(consultar, aplicar, apagar)),
            ),
            LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f),
        )

        val pie = LinearLayout(this)
        pie.orientation = LinearLayout.HORIZONTAL
        pie.addView(Ui.botonIcono(this, R.drawable.ic_back, "Volver", 0xFF2A3441.toInt()) { finish() })
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
        consultar.requestFocus()

        Thread {
            val ip = Net.ipLocal()
            runOnUiThread {
                if (isDestroyed) return@runOnUiThread
                if (ip != null && destino.isEmpty()) {
                    destino = ip
                    Ui.textoTitulo(tileDestino).text = ip
                } else if (ip == null && destino.isEmpty()) {
                    Ui.textoTitulo(tileDestino).text = "no detectada: toca y escríbela"
                }
            }
        }.start()
        consultar()
    }

    private fun ocupar(mensaje: String) {
        ocupado = true
        acciones.forEach { Ui.habilitar(it, false) }
        tira.pintar(Ui.TENUE, mensaje)
    }

    private fun liberar() {
        ocupado = false
        acciones.forEach { Ui.habilitar(it, true) }
    }

    private fun consultar() {
        if (ocupado) return
        val ip = prefs.servidorIp
        ocupar("Consultando $ip...")
        Thread {
            val r = ServerClient.obtenerConfig(ip)
            runOnUiThread {
                if (isDestroyed) return@runOnUiThread
                liberar()
                when (r) {
                    is ServerClient.Resp.Error -> tira.pintar(Ui.AVISO, r.mensaje)
                    is ServerClient.Resp.Ok -> {
                        val j = r.json
                        val modoServidor = j.optString("modo", "")
                        ServerClient.MODOS.firstOrNull { it.first == modoServidor }?.let {
                            modo = it.first
                            Ui.textoTitulo(tileModo).text = it.second
                        }
                        val (color, estado) = when {
                            !j.optBoolean("corriendo", false) -> Ui.AVISO to "DETENIDO"
                            j.optBoolean("transmitiendo", true) -> Ui.OK to "TRANSMITIENDO"
                            else -> Ui.AVISO to "CORRIENDO pero sin transmitir (revisa la capturadora)"
                        }
                        tira.pintar(color, "Servidor $estado · manda a ${j.optString("ip", "?")} · modo ${j.optString("modo", "?")}")
                    }
                }
            }
        }.start()
    }

    private fun aplicar() {
        if (ocupado) return
        val ip = prefs.servidorIp
        val quien = destino
        if (quien.isEmpty()) {
            tira.pintar(Ui.ERROR, "Falta la IP de esta tableta: toca ese mosaico y escríbela.")
            return
        }
        ocupar("Aplicando en $ip (puede tardar hasta 20 s si reinicia el servidor)...")
        val modoElegido = modo
        Thread {
            val r = ServerClient.aplicarConfig(ip, quien, modoElegido)
            runOnUiThread {
                if (isDestroyed) return@runOnUiThread
                liberar()
                when (r) {
                    is ServerClient.Resp.Error -> tira.pintar(Ui.AVISO, r.mensaje)
                    is ServerClient.Resp.Ok -> {
                        val j = r.json
                        if (j.optBoolean("ok", false)) {
                            val como = when (j.optString("aplicado")) {
                                "reiniciado" -> "Servidor reiniciado con la config nueva"
                                "guardado_para_proxima_vez" ->
                                    "Guardado; el servidor estaba detenido, enciéndelo en la PC y usará esta config"
                                else -> "Aplicado"
                            }
                            tira.pintar(Ui.OK, "$como · manda a $quien · modo $modoElegido")
                        } else {
                            tira.pintar(Ui.ERROR, j.optString("error", "El servidor rechazó la config."))
                        }
                    }
                }
            }
        }.start()
    }

    private fun apagar() {
        if (ocupado) return
        val ip = prefs.servidorIp
        ocupar("Apagando el servidor en $ip...")
        Thread {
            val r = ServerClient.detenerServidor(ip)
            runOnUiThread {
                if (isDestroyed) return@runOnUiThread
                liberar()
                when (r) {
                    is ServerClient.Resp.Error -> tira.pintar(Ui.AVISO, r.mensaje)
                    is ServerClient.Resp.Ok -> {
                        val j = r.json
                        if (j.optBoolean("ok", false)) {
                            tira.pintar(
                                Ui.OK,
                                if (j.optString("aplicado") == "ya_estaba_detenido") "El servidor ya estaba detenido"
                                else "Servidor detenido",
                            )
                        } else {
                            tira.pintar(Ui.ERROR, j.optString("error", "No se pudo apagar."))
                        }
                    }
                }
            }
        }.start()
    }
}
