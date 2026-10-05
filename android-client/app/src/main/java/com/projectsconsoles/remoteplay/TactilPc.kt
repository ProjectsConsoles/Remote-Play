package com.projectsconsoles.remoteplay

import android.view.MotionEvent
import android.view.View
import org.json.JSONObject
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.util.concurrent.Executors
import kotlin.math.abs
import kotlin.math.hypot

/**
 * Modo PC (2026-10-05): tocar la imagen en la tableta = usar el mouse de la PC. Se pone como
 * OnTouchListener de la SurfaceView del video, que ya mide exactamente lo que se ve del video (con
 * barras o recorte, ver StreamActivity.ajustarSuperficie), asi que x/ancho y y/alto del toque son la
 * posicion en la pantalla de la PC (0..1).
 *
 * Gestos:
 *   un dedo, tocar y soltar      -> clic izquierdo ahi
 *   un dedo, arrastrar           -> arrastrar (boton izquierdo apretado)
 *   dos dedos, tocar y soltar    -> clic derecho donde puso el primer dedo
 *   dos dedos, deslizar arriba/abajo -> scroll
 *
 * Manda {"mouse": {"ev": ..., "x": .., "y": ..}} por UDP al mismo puerto del mando de la PC (pc_server.py).
 */
class TactilPc(ip: String, private val puerto: Int, private val umbralPx: Float) : View.OnTouchListener {

    private val envio = Executors.newSingleThreadExecutor()
    private val destino = lazy { InetAddress.getByName(ip) }
    private val socket = lazy { DatagramSocket() }

    private var x0 = 0f
    private var y0 = 0f
    private var arrastrando = false
    private var dosDedos = false
    private var movioDosDedos = false
    private var yDosDedos = 0f
    private var scrollAcumulado = 0f

    private fun mandar(ev: String, x: Float = -1f, y: Float = -1f, d: Int = 0) {
        val j = JSONObject().put("ev", ev)
        if (x >= 0f) j.put("x", x.coerceIn(0f, 1f).toDouble()).put("y", y.coerceIn(0f, 1f).toDouble())
        if (d != 0) j.put("d", d)
        val datos = JSONObject().put("mouse", j).toString().toByteArray(Charsets.US_ASCII)
        envio.execute {
            try {
                socket.value.send(DatagramPacket(datos, datos.size, destino.value, puerto))
            } catch (_: Exception) {
            }
        }
    }

    override fun onTouch(v: View, e: MotionEvent): Boolean {
        val w = v.width.toFloat().coerceAtLeast(1f)
        val h = v.height.toFloat().coerceAtLeast(1f)
        when (e.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                x0 = e.x; y0 = e.y
                arrastrando = false; dosDedos = false; movioDosDedos = false
                mandar("mover", e.x / w, e.y / h)
            }
            MotionEvent.ACTION_POINTER_DOWN -> {
                if (!arrastrando && e.pointerCount == 2) {
                    dosDedos = true
                    yDosDedos = (e.getY(0) + e.getY(1)) / 2
                    scrollAcumulado = 0f
                }
            }
            MotionEvent.ACTION_MOVE -> {
                if (dosDedos && e.pointerCount >= 2) {
                    val y = (e.getY(0) + e.getY(1)) / 2
                    scrollAcumulado += y - yDosDedos
                    yDosDedos = y
                    val paso = umbralPx * 2
                    // dedos hacia abajo = contenido baja = rueda hacia arriba (como en el celular)
                    while (abs(scrollAcumulado) >= paso) {
                        movioDosDedos = true
                        val arriba = scrollAcumulado > 0
                        mandar("scroll", d = if (arriba) 1 else -1)
                        scrollAcumulado += if (arriba) -paso else paso
                    }
                } else if (!dosDedos) {
                    if (!arrastrando && hypot(e.x - x0, e.y - y0) > umbralPx) {
                        arrastrando = true
                        mandar("izq_abajo", x0 / w, y0 / h)
                    }
                    if (arrastrando) mandar("mover", e.x / w, e.y / h)
                }
            }
            MotionEvent.ACTION_UP -> {
                when {
                    arrastrando -> mandar("izq_arriba", e.x / w, e.y / h)
                    dosDedos -> if (!movioDosDedos) mandar("clic_der", x0 / w, y0 / h)
                    else -> mandar("clic", x0 / w, y0 / h)
                }
                arrastrando = false; dosDedos = false
            }
            MotionEvent.ACTION_CANCEL -> {
                if (arrastrando) mandar("izq_arriba")
                arrastrando = false; dosDedos = false
            }
        }
        return true
    }

    fun cerrar() {
        envio.execute { if (socket.isInitialized()) socket.value.close() }
        envio.shutdown()
    }
}
