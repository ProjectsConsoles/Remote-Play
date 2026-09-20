package com.projectsconsoles.remoteplay

import android.app.Activity
import android.content.Context
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.graphics.drawable.StateListDrawable
import android.os.Build
import android.text.InputType
import android.text.method.DigitsKeyListener
import android.view.Gravity
import android.view.KeyEvent
import android.view.View
import android.view.ViewGroup
import android.view.WindowInsets
import android.view.WindowInsetsController
import android.view.inputmethod.EditorInfo
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView

/** Colores y piezas de interfaz hechas en codigo (sin XML), todas enfocables para navegar con el mando. */
object Ui {
    const val FONDO = 0xFF12161C.toInt()
    const val PANEL = 0xFF1E252E.toInt()
    const val TEXTO = 0xFFE9EEF3.toInt()
    const val TENUE = 0xFF93A1B0.toInt()
    const val ACENTO = 0xFF4DA3FF.toInt()
    const val OK = 0xFF3DDC84.toInt()
    const val AVISO = 0xFFFFB74D.toInt()
    const val ERROR = 0xFFFF6B6B.toInt()

    fun dp(ctx: Context, v: Int): Int = (v * ctx.resources.displayMetrics.density + 0.5f).toInt()

    fun version(ctx: Context): String = try {
        ctx.packageManager.getPackageInfo(ctx.packageName, 0).versionName ?: "?"
    } catch (_: Exception) {
        "?"
    }

    /** Fondo con borde: el borde blanco/azul grueso es lo que marca "aqui esta el foco" para el mando. */
    private fun fondoBoton(ctx: Context, relleno: Int, borde: Int, grosor: Int): GradientDrawable {
        val d = GradientDrawable()
        d.cornerRadius = dp(ctx, 10).toFloat()
        d.setColor(relleno)
        d.setStroke(dp(ctx, grosor), borde)
        return d
    }

    private fun estilo(ctx: Context, v: TextView, colorBase: Int) {
        val normal = fondoBoton(ctx, colorBase, colorBase, 3)
        val foco = fondoBoton(ctx, colorBase, Color.WHITE, 3)
        val sl = StateListDrawable()
        sl.addState(intArrayOf(android.R.attr.state_focused), foco)
        sl.addState(intArrayOf(android.R.attr.state_pressed), foco)
        sl.addState(intArrayOf(), normal)
        v.background = sl
        v.setTextColor(Color.WHITE)
        v.isAllCaps = false
        v.textSize = 18f
        v.gravity = Gravity.CENTER_VERTICAL or Gravity.START
        v.setPadding(dp(ctx, 18), dp(ctx, 12), dp(ctx, 18), dp(ctx, 12))
        v.minHeight = dp(ctx, 56)
        v.isFocusable = true
        v.isFocusableInTouchMode = false
        v.isClickable = true
        v.stateListAnimator = null
    }

    fun boton(ctx: Context, texto: String, color: Int = 0xFF2D6CDF.toInt(), alClic: () -> Unit): Button {
        val b = Button(ctx)
        b.text = texto
        estilo(ctx, b, color)
        b.setOnClickListener { alClic() }
        b.layoutParams = LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT,
        ).also { it.topMargin = dp(ctx, 10) }
        return b
    }

    /** Icono vectorial (res/drawable) teñido, ya dimensionado. */
    fun icono(ctx: Context, recurso: Int, ladoDp: Int, color: Int = Color.WHITE): android.widget.ImageView {
        val v = android.widget.ImageView(ctx)
        val d = ctx.getDrawable(recurso)?.mutate()
        d?.setTint(color)
        v.setImageDrawable(d)
        v.layoutParams = LinearLayout.LayoutParams(dp(ctx, ladoDp), dp(ctx, ladoDp))
        return v
    }

    /** Boton compacto con icono a la izquierda; para colocarlo en una fila (peso 1). */
    fun botonIcono(ctx: Context, recurso: Int, texto: String, color: Int, alClic: () -> Unit): Button {
        val b = boton(ctx, texto, color, alClic)
        val d = ctx.getDrawable(recurso)?.mutate()
        d?.setTint(Color.WHITE)
        b.setCompoundDrawablesRelativeWithIntrinsicBounds(d, null, null, null)
        b.compoundDrawablePadding = dp(ctx, 12)
        b.gravity = Gravity.CENTER
        b.textSize = 16f
        b.minHeight = dp(ctx, 48)
        b.layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f).also {
            it.marginStart = dp(ctx, 6)
            it.marginEnd = dp(ctx, 6)
        }
        return b
    }

    private fun aclarar(color: Int, f: Float): Int {
        val r = (Color.red(color) + (255 - Color.red(color)) * f).toInt()
        val g = (Color.green(color) + (255 - Color.green(color)) * f).toInt()
        val b = (Color.blue(color) + (255 - Color.blue(color)) * f).toInt()
        return Color.rgb(r, g, b)
    }

    private fun fondoMosaico(ctx: Context, color: Int, borde: Int): GradientDrawable {
        val d = GradientDrawable(GradientDrawable.Orientation.TL_BR, intArrayOf(aclarar(color, 0.18f), color))
        d.cornerRadius = dp(ctx, 18).toFloat()
        d.setStroke(dp(ctx, 4), borde)
        return d
    }

    /**
     * Mosaico grande del menu principal: icono, titulo y descripcion sobre un color. Se agranda un poco
     * y muestra un borde blanco cuando tiene el foco (asi se ve a que boton apunta el mando).
     * [compacto] = pantallas bajitas (celular en horizontal): icono y letras mas chicos.
     */
    fun mosaico(
        ctx: Context,
        recurso: Int,
        titulo: String,
        detalle: String,
        color: Int,
        compacto: Boolean,
        alClic: () -> Unit,
    ): LinearLayout {
        val t = LinearLayout(ctx)
        t.orientation = LinearLayout.VERTICAL
        t.gravity = Gravity.CENTER_VERTICAL or Gravity.START
        val p = dp(ctx, if (compacto) 10 else 20)
        t.setPadding(p, p, p, p)
        t.minimumHeight = dp(ctx, if (compacto) 68 else 120)

        val normal = fondoMosaico(ctx, color, color)
        val foco = fondoMosaico(ctx, color, Color.WHITE)
        val sl = StateListDrawable()
        sl.addState(intArrayOf(android.R.attr.state_focused), foco)
        sl.addState(intArrayOf(android.R.attr.state_pressed), foco)
        sl.addState(intArrayOf(), normal)
        t.background = sl

        t.addView(icono(ctx, recurso, if (compacto) 26 else 52))
        val tit = TextView(ctx)
        tit.text = titulo
        tit.setTextColor(Color.WHITE)
        tit.textSize = if (compacto) 18f else 26f
        tit.setTypeface(tit.typeface, Typeface.BOLD)
        tit.setPadding(0, dp(ctx, if (compacto) 4 else 10), 0, 0)
        t.addView(tit)
        val det = TextView(ctx)
        det.text = detalle
        det.setTextColor(0xE6FFFFFF.toInt())
        det.textSize = if (compacto) 12f else 15f
        det.setPadding(0, dp(ctx, 2), 0, 0)
        t.addView(det)

        t.isFocusable = true
        t.isFocusableInTouchMode = false
        t.isClickable = true
        t.setOnClickListener { alClic() }
        t.setOnFocusChangeListener { v, tiene ->
            v.animate().scaleX(if (tiene) 1.03f else 1f).scaleY(if (tiene) 1.03f else 1f).setDuration(120).start()
            v.elevation = if (tiene) dp(ctx, 8).toFloat() else 0f
        }
        return t
    }

    /**
     * Boton que da la vuelta por una lista de opciones cada vez que se aprieta (mucho mas comodo con
     * el mando que un desplegable). [opciones] = clave guardada -> texto que se ve.
     */
    fun opcion(
        ctx: Context,
        etiqueta: String,
        opciones: List<Pair<String, String>>,
        actual: String,
        alCambiar: (String) -> Unit,
    ): Button {
        var i = opciones.indexOfFirst { it.first == actual }.coerceAtLeast(0)
        val b = boton(ctx, "", 0xFF2A3441.toInt()) {}
        fun pintar() {
            b.text = "$etiqueta:  ${opciones[i].second}   ◂▸"
        }
        pintar()
        b.setOnClickListener {
            i = (i + 1) % opciones.size
            pintar()
            alCambiar(opciones[i].first)
        }
        return b
    }

    fun titulo(ctx: Context, texto: String): TextView {
        val t = TextView(ctx)
        t.text = texto
        t.textSize = 30f
        t.setTypeface(t.typeface, Typeface.BOLD)
        t.setTextColor(TEXTO)
        t.gravity = Gravity.CENTER_HORIZONTAL
        t.setPadding(0, dp(ctx, 8), 0, dp(ctx, 12))
        return t
    }

    fun texto(ctx: Context, texto: String, color: Int = TENUE, tam: Float = 16f): TextView {
        val t = TextView(ctx)
        t.text = texto
        t.textSize = tam
        t.setTextColor(color)
        t.setPadding(0, dp(ctx, 8), 0, dp(ctx, 4))
        return t
    }

    /** Campo de texto con etiqueta encima. [soloIp] = solo digitos y puntos; [soloNumero] = solo digitos. */
    fun campo(ctx: Context, valor: String, soloIp: Boolean = false, soloNumero: Boolean = false): EditText {
        val e = EditText(ctx)
        e.setText(valor)
        e.textSize = 18f
        e.setTextColor(TEXTO)
        e.setHintTextColor(TENUE)
        e.setSingleLine(true)
        e.imeOptions = EditorInfo.IME_ACTION_DONE or EditorInfo.IME_FLAG_NO_EXTRACT_UI
        if (soloIp) {
            e.inputType = InputType.TYPE_CLASS_NUMBER or InputType.TYPE_NUMBER_FLAG_DECIMAL
            e.keyListener = DigitsKeyListener.getInstance("0123456789.")
        } else if (soloNumero) {
            e.inputType = InputType.TYPE_CLASS_NUMBER
        }
        val normal = fondoBoton(ctx, PANEL, 0xFF3A4654.toInt(), 2)
        val foco = fondoBoton(ctx, PANEL, Color.WHITE, 3)
        val sl = StateListDrawable()
        sl.addState(intArrayOf(android.R.attr.state_focused), foco)
        sl.addState(intArrayOf(), normal)
        e.background = sl
        e.setPadding(dp(ctx, 14), dp(ctx, 10), dp(ctx, 14), dp(ctx, 10))
        e.layoutParams = LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT,
        )
        return e
    }

    fun puntoDeColor(ctx: Context, color: Int, lado: Int = 44): View {
        val v = View(ctx)
        val d = GradientDrawable()
        d.shape = GradientDrawable.OVAL
        d.setColor(color)
        d.setStroke(dp(ctx, 2), TEXTO)
        v.background = d
        v.layoutParams = LinearLayout.LayoutParams(dp(ctx, lado), dp(ctx, lado))
        return v
    }

    /** Pantalla de menu: columna centrada de ancho maximo razonable, con scroll. */
    class Pantalla(val ctx: Context) {
        val raiz = ScrollView(ctx)
        val columna = LinearLayout(ctx)

        init {
            raiz.setBackgroundColor(FONDO)
            raiz.isFillViewport = true
            columna.orientation = LinearLayout.VERTICAL
            val margen = dp(ctx, 24)
            columna.setPadding(margen, margen, margen, margen)
            val marco = LinearLayout(ctx)
            marco.gravity = Gravity.CENTER_HORIZONTAL
            columna.layoutParams = LinearLayout.LayoutParams(dp(ctx, 640), ViewGroup.LayoutParams.WRAP_CONTENT)
            marco.addView(columna)
            raiz.addView(
                marco,
                ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT),
            )
        }

        fun <T : View> agregar(v: T): T {
            columna.addView(v)
            return v
        }
    }

    /** Pantalla completa sin barras (streaming). */
    @Suppress("DEPRECATION")
    fun inmersivo(a: Activity) {
        if (Build.VERSION.SDK_INT >= 30) {
            a.window.insetsController?.let {
                it.hide(WindowInsets.Type.systemBars())
                it.systemBarsBehavior = WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
            }
        } else {
            a.window.decorView.systemUiVisibility =
                View.SYSTEM_UI_FLAG_FULLSCREEN or View.SYSTEM_UI_FLAG_HIDE_NAVIGATION or
                    View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY or View.SYSTEM_UI_FLAG_LAYOUT_STABLE or
                    View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN or View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
        }
    }
}

/** Base de las pantallas de menu: B del mando = volver. */
open class PantallaActivity : Activity() {
    open val volverConB: Boolean = true

    override fun onKeyDown(keyCode: Int, event: KeyEvent): Boolean {
        if (volverConB && keyCode == KeyEvent.KEYCODE_BUTTON_B) return true
        return super.onKeyDown(keyCode, event)
    }

    override fun onKeyUp(keyCode: Int, event: KeyEvent): Boolean {
        if (volverConB && keyCode == KeyEvent.KEYCODE_BUTTON_B) {
            finish()
            return true
        }
        return super.onKeyUp(keyCode, event)
    }
}
