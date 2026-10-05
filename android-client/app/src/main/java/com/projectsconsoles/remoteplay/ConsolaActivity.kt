package com.projectsconsoles.remoteplay

import android.content.Intent
import android.graphics.Color
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.View
import android.view.ViewGroup
import android.widget.LinearLayout
import android.widget.ScrollView

/**
 * "¿Qué consola?" (2026-10-04, como la Deck y la Ally): la abren Streaming y Solo control.
 *
 * Elegir PS3/PS2/Xbox 360/Xbox clasico le manda su modo al ESP32 en ese momento (siempre se reinicia,
 * ~2-4 s sin control en la consola) y sigue a StreamActivity; en streaming primero se verifica que el
 * servidor este transmitiendo a esta tableta. Solo en Streaming: PS4/PS5 y Xbox One/Series, que abren
 * otra app (ver Consolas.PS / Consolas.XBOX). Una fila por marca, de la mas nueva a la mas vieja; el
 * foco arranca en la mas actual. Info del ESP32 sigue como respaldo.
 */
class ConsolaActivity : PantallaActivity() {

    private lateinit var prefs: Prefs
    private lateinit var tira: Ui.TiraEstado
    private var soloControl = false
    private var saliendo = false
    private val estados = HashMap<View, Pair<Int, String>>()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        prefs = Prefs(this)
        soloControl = intent.getBooleanExtra(EXTRA_SOLO_CONTROL, false)

        val compacto = resources.configuration.screenHeightDp < 500
        val margen = Ui.dp(this, if (compacto) 10 else 20)
        val raiz = LinearLayout(this)
        raiz.orientation = LinearLayout.VERTICAL
        raiz.clipChildren = false
        raiz.clipToPadding = false
        raiz.setPadding(margen, margen, margen, margen)
        raiz.addView(Ui.cabecera(this, "¿Qué consola?", if (soloControl) "Solo control" else "Streaming", compacto))
        tira = Ui.TiraEstado(this, compacto)
        raiz.addView(
            tira.vista,
            LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
                .also {
                    it.topMargin = Ui.dp(this, if (compacto) 4 else 8)
                    it.bottomMargin = Ui.dp(this, if (compacto) 4 else 8)
                },
        )

        val tam = if (compacto) 20f else 28f
        val ancho = if (compacto) 90 else 140

        fun led(i: Int): View {
            val l = Consolas.LEDS[i]
            val t = Ui.mosaico(
                this, l.icono, l.consola, "Capturadora + ESP32 (LED ${l.nombreColor.lowercase()})", l.color, compacto,
                Color.WHITE, tamTitulo = tam, anchoIconoDp = ancho,
            ) { elegirEsp32(l) }
            estados[t] = Ui.TENUE to "${l.consola}: el ESP32 se configura solo al elegirla (se reinicia ~2 s)."
            return t
        }

        fun app(a: Consolas.App): View {
            val inst = Consolas.instalada(this, a)
            val t = Ui.mosaico(
                this, a.icono, a.titulo, if (inst != null) "${inst.second} (Remote Play)." else "No está instalado.",
                if (inst != null) a.color else Consolas.apagado(a.color), compacto, Color.WHITE,
                // El logo de Xbox es cuadrado (mas alto que el de PS al mismo ancho): mas angosto para
                // que no empuje el texto fuera de la tarjeta.
                tamTitulo = tam, anchoIconoDp = if (a === Consolas.XBOX) (if (compacto) 44 else 66) else (if (compacto) 60 else 90),
            ) { elegirApp(a) }
            estados[t] = if (inst != null) Ui.OK to "${inst.second} listo." else Ui.AVISO to "${a.titulo}: no está instalado. ${a.sugerencia.replaceFirstChar { it.uppercase() }}."
            return t
        }

        val filas = if (soloControl) {
            listOf(listOf(led(0), led(1)), listOf(led(2), led(3)))
        } else {
            listOf(listOf(app(Consolas.PS), led(0), led(1)), listOf(app(Consolas.XBOX), led(2), led(3)))
        }
        raiz.addView(Ui.cuadricula(this, compacto, filas), LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))

        val pie = LinearLayout(this)
        pie.orientation = LinearLayout.HORIZONTAL
        if (!soloControl) {
            // PC con juegos (2026-10-04): la PC transmite su propia pantalla y recibe el mando como un
            // control de Xbox virtual. Va abajo, ancho, para no achicar las tarjetas de consola.
            val pc = Ui.botonIcono(this, R.drawable.ic_computer, "PC (juegos de Windows)", 0xFF2D6CDF.toInt()) { elegirPc() }
            estados[pc] = Ui.TENUE to "PC ${prefs.pcIp}: transmite su pantalla y el mando llega como control de Xbox (cámbiala en Configurar cliente)."
            pie.addView(pc)
        }
        val volver = Ui.botonIcono(this, R.drawable.ic_back, "Volver", 0xFF2A3441.toInt()) { finish() }
        estados[volver] = Ui.TENUE to "Volver al menú."
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
        scroll.addView(raiz, ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))
        setContentView(scroll)

        // La tira dice el estado de lo que tiene el foco (el mosaico ya usa su OnFocusChangeListener
        // para agrandarse, por eso se escucha el cambio de foco de toda la ventana).
        scroll.viewTreeObserver.addOnGlobalFocusChangeListener { _, nueva ->
            if (!saliendo) estados[nueva]?.let { tira.pintar(it.first, it.second) }
        }
        val primero = filas[0][0]
        primero.requestFocus()
        estados[primero]?.let { tira.pintar(it.first, it.second) }
    }

    private fun elegirEsp32(l: Consolas.Led) {
        if (saliendo) return
        saliendo = true
        if (soloControl) {
            mandarYSeguir(l)
            return
        }
        // Primero el servidor: si no esta listo no tiene caso reiniciar el ESP32.
        tira.pintar(Ui.TENUE, "Verificando el servidor...")
        val ipServidor = prefs.servidorIp
        Thread {
            val miIp = Net.ipLocal()
            val problema = when (val r = ServerClient.obtenerConfig(ipServidor)) {
                is ServerClient.Resp.Error -> "el servidor $ipServidor no responde. ¿Prendido y en la misma red?"
                is ServerClient.Resp.Ok -> {
                    val j = r.json
                    val corriendo = j.optBoolean("corriendo", false)
                    val destino = j.optString("ip", "")
                    when {
                        !corriendo -> "el servidor $ipServidor no está transmitiendo. Enciéndelo en la PC."
                        !j.optBoolean("transmitiendo", corriendo) -> "el servidor está prendido pero sin video (revisa la capturadora)."
                        miIp != null && destino.isNotEmpty() && destino != miIp ->
                            "el servidor transmite a $destino, no a esta tableta ($miIp). Entra a Configurar servidor y aplica."
                        else -> null
                    }
                }
            }
            runOnUiThread {
                if (isDestroyed) return@runOnUiThread
                if (problema != null) {
                    saliendo = false
                    tira.pintar(Ui.AVISO, "No se puede iniciar streaming: $problema")
                } else {
                    mandarYSeguir(l)
                }
            }
        }.start()
    }

    private fun mandarYSeguir(l: Consolas.Led) {
        Consolas.enviarModo(this, prefs, l.modo) { ok ->
            val sigue = if (soloControl) "solo control" else "el streaming"
            if (ok) {
                tira.pintar(Consolas.AMARILLO_AVISO, "ESP32 en modo ${l.consola}: se reinicia (~2 s) y arranca $sigue...")
            } else {
                tira.pintar(Ui.AVISO, "No pude mandar el modo ${l.consola} al ESP32; sigo igual (revisa Info si el control no responde).")
            }
            // Lo justo para leer el mensaje; al terminar el streaming se vuelve al menu principal.
            Handler(Looper.getMainLooper()).postDelayed({
                if (isDestroyed) return@postDelayed
                startActivity(Intent(this, StreamActivity::class.java).putExtra(StreamActivity.EXTRA_SOLO_CONTROL, soloControl))
                finish()
            }, 900)
        }
    }

    /**
     * PC: le pide a la PC (mismo protocolo UDP 9200 que el servidor de la capturadora) que transmita a
     * esta tableta y abre el streaming con el mando apuntando a la PC. Sin ESP32.
     */
    private fun elegirPc() {
        if (saliendo) return
        saliendo = true
        val ipPc = prefs.pcIp
        tira.pintar(Ui.TENUE, "Pidiéndole a la PC ($ipPc) que transmita a esta tableta...")
        Thread {
            val miIp = Net.ipLocal()
            // Primero get_config (3 s de espera): si la PC no tiene el servidor corriendo se avisa rapido,
            // en vez de esperar los 20 s de set_config.
            val resp = when {
                miIp == null -> null
                ServerClient.obtenerConfig(ipPc) is ServerClient.Resp.Error -> ServerClient.Resp.Error("sin respuesta")
                else -> ServerClient.aplicarConfig(ipPc, miIp, "pc")
            }
            runOnUiThread {
                if (isDestroyed) return@runOnUiThread
                when {
                    miIp == null -> {
                        saliendo = false
                        tira.pintar(Ui.ERROR, "Esta tableta no tiene red.")
                    }
                    resp is ServerClient.Resp.Error -> {
                        saliendo = false
                        tira.pintar(Ui.AVISO, "La PC $ipPc no responde. ¿Está prendida y con el servidor de PC corriendo?")
                    }
                    else -> {
                        tira.pintar(Ui.OK, "PC lista: arrancando el streaming...")
                        startActivity(
                            Intent(this, StreamActivity::class.java)
                                .putExtra(StreamActivity.EXTRA_CONTROL_IP, ipPc)
                                .putExtra(StreamActivity.EXTRA_CONTROL_PUERTO, PUERTO_CONTROL_PC)
                                .putExtra(StreamActivity.EXTRA_FUENTE, "PC $ipPc")
                                .putExtra(StreamActivity.EXTRA_TACTIL_PC, true),
                        )
                        finish()
                    }
                }
            }
        }.start()
    }

    private fun elegirApp(a: Consolas.App) {
        if (saliendo) return
        val inst = Consolas.instalada(this, a) // otra vez: pudo instalarse con esta pantalla abierta
        if (inst == null) {
            tira.pintar(Ui.ERROR, "No se puede abrir: ${a.titulo} no está instalado. ${a.sugerencia.replaceFirstChar { it.uppercase() }}.")
            return
        }
        // Se abre encima de esta pantalla: al salir de la otra app (atras) se regresa aqui.
        if (!Consolas.abrir(this, inst.first)) tira.pintar(Ui.ERROR, "No se pudo abrir ${inst.second}.")
    }

    companion object {
        const val EXTRA_SOLO_CONTROL = "solo_control"

        /** Puerto UDP donde el servidor de PC recibe el mando (el mismo JSON que el ESP32). */
        const val PUERTO_CONTROL_PC = 9000
    }
}
