package com.projectsconsoles.remoteplay

import android.app.Activity
import android.app.Dialog
import android.content.Context
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.graphics.drawable.StateListDrawable
import android.os.Build
import android.text.InputType
import android.text.TextUtils
import android.text.method.DigitsKeyListener
import android.view.Gravity
import android.view.KeyEvent
import android.view.View
import android.view.ViewGroup
import android.view.WindowInsets
import android.view.WindowInsetsController
import android.view.WindowManager
import android.view.inputmethod.EditorInfo
import android.widget.Button
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast

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
        colorTexto: Int = Color.WHITE,
        interactivo: Boolean = true,
        tamTitulo: Float? = null,
        alClic: () -> Unit = {},
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

        t.addView(icono(ctx, recurso, if (compacto) 26 else 52, colorTexto))
        val tit = TextView(ctx)
        tit.text = titulo
        tit.setTextColor(colorTexto)
        tit.textSize = tamTitulo ?: if (compacto) 18f else 26f
        tit.setTypeface(tit.typeface, Typeface.BOLD)
        tit.maxLines = 2
        tit.ellipsize = TextUtils.TruncateAt.END
        tit.setPadding(0, dp(ctx, if (compacto) 4 else 10), 0, 0)
        t.addView(tit)
        val det = TextView(ctx)
        det.text = detalle
        det.setTextColor((colorTexto and 0x00FFFFFF) or 0xE6000000.toInt())
        det.textSize = if (compacto) 12f else 15f
        det.maxLines = 2
        det.ellipsize = TextUtils.TruncateAt.END
        det.setPadding(0, dp(ctx, 2), 0, 0)
        t.addView(det)

        if (interactivo) {
            t.isFocusable = true
            t.isFocusableInTouchMode = false
            t.isClickable = true
            t.setOnClickListener { alClic() }
            t.setOnFocusChangeListener { v, tiene ->
                v.animate().scaleX(if (tiene) 1.03f else 1f).scaleY(if (tiene) 1.03f else 1f).setDuration(120).start()
                v.elevation = if (tiene) dp(ctx, 8).toFloat() else 0f
            }
        }
        return t
    }

    /** El texto grande de un mosaico (hijo 1: icono, titulo, detalle). Sirve para actualizar su valor. */
    fun textoTitulo(mosaico: LinearLayout): TextView = mosaico.getChildAt(1) as TextView

    /** Habilita o atenua un mosaico (mientras hay una operacion en curso). */
    fun habilitar(v: View, si: Boolean) {
        v.isEnabled = si
        v.isClickable = si
        v.alpha = if (si) 1f else 0.5f
    }

    /**
     * Reparte los mosaicos en una cuadricula que ocupa todo el espacio disponible: cada elemento de
     * [filas] es una fila y todas las filas y columnas miden lo mismo. Agregarla con peso 1.
     */
    fun cuadricula(ctx: Context, compacto: Boolean, filas: List<List<View>>): LinearLayout {
        val col = LinearLayout(ctx)
        col.orientation = LinearLayout.VERTICAL
        col.clipChildren = false
        col.clipToPadding = false
        val m = dp(ctx, if (compacto) 4 else 6)
        for (fila in filas) {
            val f = LinearLayout(ctx)
            f.orientation = LinearLayout.HORIZONTAL
            f.clipChildren = false
            for (v in fila) {
                f.addView(
                    v,
                    LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.MATCH_PARENT, 1f).also { it.setMargins(m, m, m, m) },
                )
            }
            col.addView(f, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))
        }
        return col
    }

    /** Titulo a la izquierda y una nota tenue a la derecha. */
    fun cabecera(ctx: Context, titulo: String, derecha: String, compacto: Boolean): LinearLayout {
        val c = LinearLayout(ctx)
        c.orientation = LinearLayout.HORIZONTAL
        c.gravity = Gravity.CENTER_VERTICAL
        val t = TextView(ctx)
        t.text = titulo
        t.setTextColor(TEXTO)
        t.textSize = if (compacto) 22f else 30f
        t.setTypeface(t.typeface, Typeface.BOLD)
        c.addView(t, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        val d = TextView(ctx)
        d.text = derecha
        d.setTextColor(TENUE)
        d.textSize = if (compacto) 11f else 13f
        d.gravity = Gravity.END
        c.addView(d, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1.4f))
        return c
    }

    /** Tira redondeada con un punto de color y un mensaje (estado del servidor, resultados). */
    class TiraEstado(ctx: Context, compacto: Boolean) {
        val vista = LinearLayout(ctx)
        private val punto = GradientDrawable()
        private val texto = TextView(ctx)

        init {
            vista.orientation = LinearLayout.HORIZONTAL
            vista.gravity = Gravity.CENTER_VERTICAL
            val fondo = GradientDrawable()
            fondo.cornerRadius = dp(ctx, 12).toFloat()
            fondo.setColor(PANEL)
            vista.background = fondo
            val v = dp(ctx, if (compacto) 6 else 10)
            vista.setPadding(dp(ctx, 14), v, dp(ctx, 14), v)
            val marca = View(ctx)
            punto.shape = GradientDrawable.OVAL
            punto.setColor(TENUE)
            marca.background = punto
            vista.addView(
                marca,
                LinearLayout.LayoutParams(dp(ctx, 12), dp(ctx, 12)).also { it.marginEnd = dp(ctx, 12) },
            )
            texto.setTextColor(TEXTO)
            texto.textSize = if (compacto) 12f else 15f
            vista.addView(texto, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        }

        fun pintar(color: Int, mensaje: String) {
            punto.setColor(color)
            texto.text = mensaje
        }
    }

    fun ipValida(s: String): Boolean =
        Regex("""\d{1,3}(\.\d{1,3}){3}""").matches(s) && s.split(".").all { it.toInt() in 0..255 }

    /** Cuadro para escribir un texto (IP o puerto), con el teclado ya abierto. */
    fun pedirTexto(
        a: Activity,
        titulo: String,
        actual: String,
        soloIp: Boolean,
        soloNumero: Boolean,
        alAceptar: (String) -> Unit,
    ) {
        // Cuadro propio y compacto (no AlertDialog): en un celular horizontal con el teclado abierto casi no
        // hay alto, asi que la etiqueta va chica arriba y campo + botones comparten una sola fila.
        val d = Dialog(a, android.R.style.Theme_DeviceDefault_Dialog_NoActionBar)
        val edit = campo(a, actual, soloIp = soloIp, soloNumero = soloNumero)
        edit.setPadding(dp(a, 12), dp(a, 6), dp(a, 12), dp(a, 6))

        fun compactar(b: Button, m: Int) {
            b.minHeight = dp(a, 44)
            b.minWidth = 0
            b.gravity = Gravity.CENTER
            b.textSize = 16f
            b.setPadding(dp(a, 16), dp(a, 6), dp(a, 16), dp(a, 6))
            b.layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT,
            ).also { it.marginStart = m }
        }

        fun aceptar() {
            alAceptar(edit.text.toString().trim())
            d.dismiss()
        }

        val cancelar = boton(a, "Cancelar", 0xFF2A3441.toInt()) { d.dismiss() }
        val ok = boton(a, "Aceptar", 0xFF3F8F4A.toInt()) { aceptar() }
        compactar(cancelar, dp(a, 10))
        compactar(ok, dp(a, 8))
        edit.setOnEditorActionListener { _, _, _ -> aceptar(); true }

        val fila = LinearLayout(a)
        fila.orientation = LinearLayout.HORIZONTAL
        fila.gravity = Gravity.CENTER_VERTICAL
        fila.addView(edit, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        fila.addView(cancelar)
        fila.addView(ok)

        val marco = LinearLayout(a)
        marco.orientation = LinearLayout.VERTICAL
        marco.setPadding(dp(a, 16), dp(a, 10), dp(a, 16), dp(a, 14))
        marco.addView(texto(a, titulo, TENUE, 13f))
        marco.addView(fila)
        d.setContentView(marco)

        d.window?.let { w ->
            val fondo = GradientDrawable()
            fondo.cornerRadius = dp(a, 16).toFloat()
            fondo.setColor(PANEL)
            w.setBackgroundDrawable(fondo)
            val ancho = minOf(dp(a, 620), a.resources.displayMetrics.widthPixels - dp(a, 32))
            w.setLayout(ancho, ViewGroup.LayoutParams.WRAP_CONTENT)
            w.setGravity(Gravity.TOP or Gravity.CENTER_HORIZONTAL)
            w.setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_STATE_VISIBLE)
        }
        d.show()
        edit.requestFocus()
        edit.selectAll()
    }

    /**
     * Mosaico con un valor de texto que se edita en un cuadro (IP, puerto). [guardar] recibe lo que se
     * escribio y devuelve si era valido; si no lo es se avisa y el valor no cambia.
     */
    fun mosaicoTexto(
        a: Activity,
        recurso: Int,
        etiqueta: String,
        mostrado: String,
        color: Int,
        compacto: Boolean,
        esIp: Boolean,
        valorDialogo: (() -> String)? = null,
        guardar: (String) -> Boolean,
    ): LinearLayout {
        lateinit var t: LinearLayout
        t = mosaico(a, recurso, mostrado, etiqueta, color, compacto, tamTitulo = if (compacto) 15f else 22f) {
            val inicial = valorDialogo?.invoke() ?: textoTitulo(t).text.toString()
            pedirTexto(a, etiqueta, inicial, soloIp = esIp, soloNumero = !esIp) { nuevo ->
                if (guardar(nuevo)) {
                    textoTitulo(t).text = nuevo
                } else {
                    Toast.makeText(a, if (esIp) "IP no valida: $nuevo" else "Valor no valido: $nuevo", Toast.LENGTH_SHORT).show()
                }
            }
        }
        return t
    }

    /**
     * Mosaico que cambia al siguiente valor de [opciones] (clave -> texto) cada vez que se aprieta.
     * [obtener] da la clave actual (asi el valor se puede cambiar tambien desde fuera).
     */
    fun mosaicoCiclo(
        ctx: Context,
        recurso: Int,
        etiqueta: String,
        opciones: List<Pair<String, String>>,
        obtener: () -> String,
        color: Int,
        compacto: Boolean,
        alCambiar: (String) -> Unit,
    ): LinearLayout {
        fun textoDe(clave: String) = opciones.firstOrNull { it.first == clave }?.second ?: clave
        val tam = if (compacto) 15f else 22f
        val t = mosaico(ctx, recurso, textoDe(obtener()), etiqueta, color, compacto, tamTitulo = tam)
        t.setOnClickListener {
            val i = opciones.indexOfFirst { it.first == obtener() }.coerceAtLeast(0)
            val siguiente = opciones[(i + 1) % opciones.size]
            alCambiar(siguiente.first)
            textoTitulo(t).text = siguiente.second
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

/**
 * Base de las pantallas de menu: pantalla completa (sin barra de estado ni de navegacion; reaparecen
 * un momento al deslizar desde el borde), respeto a la camara del celular y B del mando = volver.
 */
open class PantallaActivity : Activity() {
    open val volverConB: Boolean = true

    override fun onCreate(savedInstanceState: android.os.Bundle?) {
        super.onCreate(savedInstanceState)
        if (Build.VERSION.SDK_INT >= 28) {
            val lp = window.attributes
            lp.layoutInDisplayCutoutMode = WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES
            window.attributes = lp
        }
        if (Build.VERSION.SDK_INT >= 30) window.setDecorFitsSystemWindows(false)
    }

    /** Envuelve cada pantalla en un marco con el margen seguro de la camara (muesca o agujero). */
    override fun setContentView(view: View) {
        val marco = FrameLayout(this)
        marco.setBackgroundColor(Ui.FONDO)
        marco.addView(view, FrameLayout.LayoutParams(-1, -1))
        marco.setOnApplyWindowInsetsListener { v, insets ->
            if (Build.VERSION.SDK_INT >= 28) {
                val c = insets.displayCutout
                if (c != null) {
                    v.setPadding(c.safeInsetLeft, c.safeInsetTop, c.safeInsetRight, c.safeInsetBottom)
                } else {
                    v.setPadding(0, 0, 0, 0)
                }
            }
            insets
        }
        super.setContentView(marco)
        Ui.inmersivo(this)
    }

    override fun onResume() {
        super.onResume()
        Ui.inmersivo(this)
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus) Ui.inmersivo(this) // tras un cuadro de texto o el teclado, las barras se vuelven a esconder
    }

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
