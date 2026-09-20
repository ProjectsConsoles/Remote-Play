package com.projectsconsoles.remoteplay

import android.app.Activity
import android.content.Context
import android.graphics.Color
import android.net.wifi.WifiManager
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.view.KeyEvent
import android.view.MotionEvent
import android.view.SurfaceHolder
import android.view.SurfaceView
import android.view.View
import android.view.WindowManager
import android.widget.FrameLayout
import android.widget.TextView
import android.widget.Toast
import java.util.Locale

/**
 * Streaming: recibe video+audio del servidor y manda el mando al ESP32.
 *
 * Todo se arranca cuando la superficie de video existe y se detiene cuando desaparece (Home, apagar
 * pantalla, salir), asi nunca queda un decodificador ni un socket colgado. "Solo control" no usa
 * video: solo manda el mando, con la pantalla al minimo de brillo.
 *
 * Salir: L1 + R1 + SELECT + START a la vez (como en la Deck), o el gesto/boton Atras del sistema.
 * Tocar la pantalla muestra u oculta las estadisticas.
 */
class StreamActivity : Activity(), SurfaceHolder.Callback {

    private lateinit var prefs: Prefs
    private val estado = GamepadState()
    private lateinit var mando: GamepadInput

    private lateinit var contenedor: FrameLayout
    private var superficie: SurfaceView? = null
    private lateinit var aviso: TextView
    private lateinit var estadisticas: TextView

    private var soloControl = false
    private var video: VideoPlayer? = null
    private var audio: AudioPlayer? = null
    private var demux: TsDemuxer? = null
    private var receptor: StreamReceiver? = null
    private var envio: InputSender? = null
    private var wifi: WifiManager.WifiLock? = null

    private var anchoVideo = 1280
    private var altoVideo = 720
    private var activo = false
    private var salio = false
    private var errorDeInicio: String? = null
    private var inicioNs = 0L
    private var verEstadisticas = false

    private val ui = Handler(Looper.getMainLooper())
    private val tic = object : Runnable {
        override fun run() {
            if (!activo) return
            actualizar()
            ui.postDelayed(this, 500)
        }
    }

    // para calcular tasas entre dos tics
    private var ultTicNs = 0L
    private var ultPaquetes = 0L
    private var ultBytes = 0L
    private var ultEnviados = 0L
    private var ultCuadros = 0L
    private var tasaPaquetes = 0.0
    private var tasaKbps = 0.0
    private var tasaMando = 0.0
    private var tasaCuadros = 0.0

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        prefs = Prefs(this)
        soloControl = intent.getBooleanExtra(EXTRA_SOLO_CONTROL, false)
        estado.zonaMuerta = prefs.zonaMuertaValor()
        mando = GamepadInput(estado)

        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        if (Build.VERSION.SDK_INT >= 28) {
            window.attributes.layoutInDisplayCutoutMode =
                WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES
        }
        if (soloControl) {
            val lp = window.attributes
            lp.screenBrightness = 0.01f
            window.attributes = lp
        }

        contenedor = FrameLayout(this)
        contenedor.setBackgroundColor(Color.BLACK)
        contenedor.addOnLayoutChangeListener { _, _, _, _, _, _, _, _, _ -> ajustarSuperficie() }
        contenedor.setOnClickListener {
            verEstadisticas = !verEstadisticas
            estadisticas.visibility = if (verEstadisticas) View.VISIBLE else View.GONE
            actualizar()
        }

        if (!soloControl) {
            val sv = SurfaceView(this)
            sv.holder.addCallback(this)
            superficie = sv
            contenedor.addView(sv, FrameLayout.LayoutParams(-1, -1, Gravity.CENTER))
        }

        aviso = TextView(this).also {
            it.setTextColor(Ui.TEXTO)
            it.textSize = 22f
            it.gravity = Gravity.CENTER
            it.setBackgroundColor(0x99000000.toInt())
            val p = Ui.dp(this, 20)
            it.setPadding(p, p, p, p)
        }
        contenedor.addView(aviso, FrameLayout.LayoutParams(-2, -2, Gravity.CENTER))

        estadisticas = TextView(this).also {
            it.setTextColor(Ui.OK)
            it.textSize = 13f
            it.typeface = android.graphics.Typeface.MONOSPACE
            it.setBackgroundColor(0xB0000000.toInt())
            val p = Ui.dp(this, 8)
            it.setPadding(p, p, p, p)
            it.visibility = View.GONE
        }
        contenedor.addView(estadisticas, FrameLayout.LayoutParams(-2, -2, Gravity.TOP or Gravity.START))

        setContentView(contenedor)
        Ui.inmersivo(this)
    }

    override fun onResume() {
        super.onResume()
        Ui.inmersivo(this)
        if (soloControl) iniciarTodo(null)
    }

    override fun onPause() {
        super.onPause()
        if (soloControl) detenerTodo()
    }

    override fun onDestroy() {
        detenerTodo()
        super.onDestroy()
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus) Ui.inmersivo(this) else mando.soltarTodo()
    }

    // ---- superficie de video -------------------------------------------------------------

    override fun surfaceCreated(holder: SurfaceHolder) {
        iniciarTodo(holder.surface)
    }

    override fun surfaceChanged(holder: SurfaceHolder, format: Int, width: Int, height: Int) {}

    override fun surfaceDestroyed(holder: SurfaceHolder) {
        detenerTodo()
    }

    private fun ajustarSuperficie() {
        val sv = superficie ?: return
        val cw = contenedor.width
        val ch = contenedor.height
        if (cw == 0 || ch == 0 || altoVideo == 0) return
        val proporcion = anchoVideo.toFloat() / altoVideo
        val contenedorMasAncho = cw.toFloat() / ch > proporcion
        var w = cw
        var h = ch
        when (prefs.ajusteImagen) {
            "estirar" -> {}
            "zoom" -> if (contenedorMasAncho) h = (cw / proporcion).toInt() else w = (ch * proporcion).toInt()
            else -> if (contenedorMasAncho) w = (ch * proporcion).toInt() else h = (cw / proporcion).toInt()
        }
        val lp = sv.layoutParams as FrameLayout.LayoutParams
        if (lp.width != w || lp.height != h) {
            lp.width = w
            lp.height = h
            lp.gravity = Gravity.CENTER
            sv.layoutParams = lp
        }
    }

    // ---- arranque / parada de todo ---------------------------------------------------------

    private fun iniciarTodo(superficieVideo: android.view.Surface?) {
        if (activo) return
        activo = true
        errorDeInicio = null
        inicioNs = System.nanoTime()
        ultTicNs = inicioNs
        ultPaquetes = 0; ultBytes = 0; ultEnviados = 0; ultCuadros = 0

        tomarBloqueoWifi()

        if (!soloControl && superficieVideo != null) {
            val v = VideoPlayer(superficieVideo) { w, h ->
                runOnUiThread {
                    anchoVideo = w
                    altoVideo = h
                    ajustarSuperficie()
                }
            }
            try {
                v.iniciar()
                video = v
            } catch (e: Exception) {
                errorDeInicio = "No se pudo iniciar el decodificador de video: ${e.message}"
            }

            val a = AudioPlayer()
            try {
                a.iniciar()
                audio = a
            } catch (e: Exception) {
                // sin audio se puede seguir jugando: solo se avisa en las estadisticas
                audio = null
            }

            val d = TsDemuxer(
                onVideo = { b, o, s, p -> video?.encolar(b, o, s, p) },
                onOpus = { b, o, s, p -> audio?.encolar(b, o, s, p) },
            )
            demux = d
            receptor = StreamReceiver(prefs.puertoVideo, d).also {
                it.alReanudar = { video?.reiniciarSincronia() }
                it.start()
            }
        }

        envio = InputSender(
            estado, prefs.esp32Ip, prefs.esp32Puerto, prefs.frecuenciaMando, prefs.acordePs,
        ).also { it.start() }

        ui.post(tic)
    }

    private fun detenerTodo() {
        if (!activo) return
        activo = false
        ui.removeCallbacks(tic)
        receptor?.let {
            it.detener()
            try {
                it.join(500)
            } catch (_: InterruptedException) {
            }
        }
        receptor = null
        envio?.detener()
        envio = null
        video?.detener()
        video = null
        audio?.detener()
        audio = null
        demux = null
        try {
            wifi?.release()
        } catch (_: Exception) {
        }
        wifi = null
        mando.soltarTodo()
    }

    @Suppress("DEPRECATION")
    private fun tomarBloqueoWifi() {
        try {
            val wm = applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
            val modo = if (Build.VERSION.SDK_INT >= 29) {
                WifiManager.WIFI_MODE_FULL_LOW_LATENCY
            } else {
                WifiManager.WIFI_MODE_FULL_HIGH_PERF
            }
            wifi = wm.createWifiLock(modo, "remoteplay").also {
                it.setReferenceCounted(false)
                it.acquire()
            }
        } catch (_: Exception) {
            // es una mejora, no un requisito
        }
    }

    // ---- avisos y estadisticas ---------------------------------------------------------------

    private fun actualizar() {
        val ahora = System.nanoTime()
        val dt = (ahora - ultTicNs) / 1e9
        val r = receptor
        val e = envio
        val v = video
        if (dt > 0.2) {
            if (r != null) {
                tasaPaquetes = (r.paquetes - ultPaquetes) / dt
                tasaKbps = (r.bytes - ultBytes) * 8 / 1000.0 / dt
                ultPaquetes = r.paquetes
                ultBytes = r.bytes
            }
            if (e != null) {
                tasaMando = (e.enviados - ultEnviados) / dt
                ultEnviados = e.enviados
            }
            if (v != null) {
                tasaCuadros = (v.cuadrosSalida - ultCuadros) / dt
                ultCuadros = v.cuadrosSalida
            }
            ultTicNs = ahora
        }

        val mensaje: String? = when {
            errorDeInicio != null -> errorDeInicio
            e?.ultimoError != null && e.enviados == 0L -> "No se puede mandar el mando: ${e.ultimoError}"
            soloControl -> "Solo control\nMandando el mando a ${prefs.esp32Ip}:${prefs.esp32Puerto}\n" +
                "Para salir: L1 + R1 + SELECT + START"
            r?.error != null -> r.error
            r == null || v == null -> null
            else -> {
                val silencio = if (r.paquetes == 0L) {
                    (ahora - inicioNs) / 1e9
                } else {
                    (ahora - r.ultimoPaqueteNs) / 1e9
                }
                when {
                    silencio >= prefs.segundosSinVideo -> {
                        salirConAviso("Sin video del servidor (${prefs.servidorIp}). Se cerro el streaming.")
                        null
                    }
                    r.paquetes == 0L -> "Esperando video de ${prefs.servidorIp}...\n" +
                        "${silencio.toInt()} s (se cierra a los ${prefs.segundosSinVideo} s)\n\n" +
                        "Si no llega: Configurar servidor -> Aplicar."
                    silencio > 1.0 -> "Sin video desde hace ${silencio.toInt()} s...\n" +
                        "(el servidor puede estar reiniciandose)"
                    !v.primerCuadro -> "Recibiendo datos, esperando la primera imagen..."
                    else -> null
                }
            }
        }
        if (mensaje == null) {
            aviso.visibility = View.GONE
        } else {
            aviso.text = mensaje
            aviso.visibility = View.VISIBLE
        }

        if (verEstadisticas) estadisticas.text = textoEstadisticas(r, e, v)
    }

    private fun textoEstadisticas(r: StreamReceiver?, e: InputSender?, v: VideoPlayer?): String {
        val l = Locale.US
        val sb = StringBuilder()
        sb.append("Remote Play Android ").append(Ui.version(this)).append('\n')
        if (r != null) {
            sb.append(String.format(l, "red    %.0f pkt/s  %.0f kb/s  total %d\n", tasaPaquetes, tasaKbps, r.paquetes))
        }
        val d = demux
        if (d != null) {
            sb.append(
                String.format(
                    l, "ts     video pid %d  opus pid %d  resync %d\n",
                    d.videoPid, d.opusPid, d.resincronizaciones,
                ),
            )
        }
        if (v != null) {
            sb.append(
                String.format(
                    l, "video  %dx%d  %.0f fps  dentro %d  fuera %d  tirados %d  err %d\n",
                    anchoVideo, altoVideo, tasaCuadros, v.cuadrosEntrada, v.cuadrosSalida, v.descartados, v.errores,
                ),
            )
            v.ultimoError?.let { sb.append("       ultimo error: ").append(it).append('\n') }
        }
        val a = audio
        sb.append(
            if (a != null) {
                String.format(l, "audio  opus %d  tirados %d  err %d\n", a.paquetesEntrada, a.descartados, a.errores)
            } else if (!soloControl) {
                "audio  NO disponible\n"
            } else {
                ""
            },
        )
        if (e != null) {
            sb.append(String.format(l, "mando  %.0f Hz  enviados %d  err %d\n", tasaMando, e.enviados, e.errores))
            e.ultimoError?.let { sb.append("       ultimo error: ").append(it).append('\n') }
        }
        sb.append(
            String.format(
                l, "botones 0x%04X  L2 %.2f  R2 %.2f\n",
                estado.botones, estado.l2, estado.r2,
            ),
        )
        sb.append(
            String.format(
                l, "sticks  L(%.2f, %.2f)  R(%.2f, %.2f)  dpad(%d, %d)",
                estado.lx, estado.ly, estado.rx, estado.ry, estado.dpadX(), estado.dpadY(),
            ),
        )
        return sb.toString()
    }

    private fun salirConAviso(texto: String) {
        if (salio) return
        salio = true
        Toast.makeText(applicationContext, texto, Toast.LENGTH_LONG).show()
        finish()
    }

    // ---- mando -------------------------------------------------------------------------------

    override fun dispatchKeyEvent(event: KeyEvent): Boolean {
        if (mando.alTecla(event)) {
            if (estado.acordeDeSalida() && !salio) {
                salio = true
                finish()
            }
            return true
        }
        return super.dispatchKeyEvent(event)
    }

    override fun dispatchGenericMotionEvent(event: MotionEvent): Boolean {
        if (mando.alMovimiento(event)) return true
        return super.dispatchGenericMotionEvent(event)
    }

    companion object {
        const val EXTRA_SOLO_CONTROL = "solo_control"
    }
}
