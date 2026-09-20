#!/usr/bin/env python3
"""Pantalla "Configurar cliente" del menu de la Deck (2026-09-11).

Deja editar TODAS las variables PS3RP_* del cliente (las de OPCIONES.md,
"Cliente - Steam Deck") sin tener que escribirlas a mano en las opciones de
lanzamiento de Steam cada vez. Escribe `client_config.env`, que
start_client_stream.sh carga solo (ver la nota en ese archivo) ANTES de leer
las PS3RP_* - y con el patron "solo si no esta puesta" (`: "${VAR:=valor}"`),
asi que una variable puesta a mano en Steam SIEMPRE gana sobre lo guardado
aca.

Los nombres, defaults y el "por que" de cada perilla son los mismos que
documenta OPCIONES.md - esta pantalla no inventa comportamiento nuevo, solo
le da una forma mas comoda de tocarlas que editar texto.

Estilo (2026-09-20): mosaicos con icono, igual que el cliente Android (las piezas
visuales viven en ui_mosaicos.py). Las 18 variables no caben sin scroll: los mosaicos
van de 3 en 3, agrupados por seccion, y la lista se desplaza sola al bajar con la
cruceta. Cada mosaico muestra el VALOR; la descripcion larga de la variable sale en la
linea de ayuda de abajo cuando el mosaico tiene el foco.

Manejo:  cruceta = mover el foco;  A = cambiar (sobre un texto o numero abre un cuadro
para escribirlo, con teclado/tactil);  L1 / R1 = valor anterior / siguiente (en los
numeros, -1 / +1);  B = volver.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from deck_gamepad import Mando  # noqa: E402
import ui_mosaicos as ui  # noqa: E402

ARCHIVO_CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "client_config.env")

# (variable, etiqueta, tipo, default, opciones-si-es-enum, ayuda)
# tipo: "texto" | "numero" | "bool" | "enum"
CAMPOS = [
    ("__SECCION__", "Pantalla", None, None, None, None),
    ("PS3RP_BRILLO", "Brillo al entrar en modo control", "numero", "",
     None, "Vacio = 1% del maximo. 0-65535 crudo."),

    ("__SECCION__", "Control remoto (ESP32 -> PS3)", None, None, None, None),
    ("PS3RP_ESP32_IP", "IP del ESP32-S3", "texto", "192.168.0.40",
     None, "A donde se manda el estado del mando por UDP."),
    ("PS3RP_ESP32_PORT", "Puerto UDP del ESP32", "numero", "9000", None, ""),
    ("PS3RP_INPUT", "Mandar control (no solo video)", "bool", "1", None, ""),
    ("PS3RP_INPUT_RATE", "Frecuencia de envio (Hz)", "numero", "120",
     None, "El firmware reporta cada 8ms (125Hz); 120 mide sin errores."),
    ("PS3RP_PS_COMBO", "Acorde para el boton PS", "texto", "SELECT+R1",
     None, "Ej. SELECT+L1+R1, o 'none' para apagarlo."),

    ("__SECCION__", "Video y latencia", None, None, None, None),
    ("PS3RP_LSFG", "Lossless Scaling (generacion de cuadros, ~/lsfg)", "bool", "0",
     None, "Envuelve el lanzamiento con ~/lsfg. Necesita lsfg-vk instalado y ese script en el home."),
    ("PS3RP_WIFI_SIN_AHORRO", "WiFi sin ahorro de energia (menos delay)", "bool", "1",
     None, "SI apaga el power save del WiFi al arrancar (menos jitter, algo mas de bateria). NO lo regresa a prendido."),
    ("PS3RP_PLAYER", "Reproductor de video", "enum", "gstreamer",
     ["gstreamer", "ffplay", "gstreamer_lsfg", "mpv"], "gstreamer = sin cola de retraso (recomendado, sin Lossless Scaling). ffplay = el de antes, con Lossless Scaling. gstreamer_lsfg = EXPERIMENTAL: gstreamer con Vulkan + Lossless Scaling. mpv = descartado."),
    ("PS3RP_AJUSTE", "Ajuste de imagen (gstreamer)", "enum", "barras",
     ["barras", "estirar", "zoom"], "barras = exacta con franjas negras; estirar = llena, ~11% mas alta; zoom = llena, recorta ~5% de cada lado."),
    ("PS3RP_VSYNC", "VSync (0 = apagado, mide mejor)", "bool", "0", None, ""),
    ("PS3RP_PRESENT", "Modo de presentacion Vulkan", "enum", "mailbox",
     ["mailbox", "fifo", "immediate"], "fifo = con cola, mas lag."),
    ("PS3RP_SYNC", "Reloj maestro de ffplay", "enum", "audio",
     ["audio", "video", "ext"], "video y ext miden peor (ver OPCIONES.md)."),
    ("PS3RP_FIFO", "Buffer UDP (paquetes de 188 bytes)", "numero", "1500", None, ""),
    ("PS3RP_NOAUDIO", "Sin audio (solo para medir)", "bool", "0", None, ""),
    ("PS3RP_AUDIO_MS", "Buffer de audio de salida (ms)", "numero", "",
     None, "Vacio = no tocar. Baja el lag pero puede desincronizar."),

    ("__SECCION__", "Watchdog de atasco de video", None, None, None, None),
    ("PS3RP_WATCHDOG", "Reiniciar ffplay solo si se atasca", "bool", "1", None, ""),
    ("PS3RP_VQ_MAX", "KB de video encolado que sospecha", "numero", "100", None, ""),
    ("PS3RP_VQ_SECS", "Segundos seguidos antes de actuar", "numero", "10", None, ""),
    ("PS3RP_VQ_ESPERA", "Veda tras un reinicio (segundos)", "numero", "90", None, ""),

    ("__SECCION__", "Diagnostico", None, None, None, None),
    ("PS3RP_STATS", "Volcar stats de ffplay al log", "bool", "0", None, ""),
    ("PS3RP_STATS_EVERY", "Segundos entre lineas de stats", "numero", "30", None, ""),
]


def leer_guardado():
    """Devuelve {variable: valor} de lo que ya este en client_config.env."""
    guardado = {}
    if not os.path.isfile(ARCHIVO_CONFIG):
        return guardado
    try:
        with open(ARCHIVO_CONFIG) as f:
            for linea in f:
                linea = linea.strip()
                if not linea.startswith(': "${'):
                    continue
                # formato: : "${PS3RP_X:=valor}"
                try:
                    resto = linea.split(':"${', 1)[-1] if ':"${' in linea else linea.split(': "${', 1)[1]
                    nombre, valor = resto.split(":=", 1)
                    valor = valor.rstrip('}"')
                    guardado[nombre] = valor
                except Exception:
                    continue
    except Exception:
        pass
    return guardado


def guardar(valores: dict):
    lineas = [
        "# Generado por client_settings.py (menu de la Deck) - no se edita a mano.",
        "# Formato 'solo si no esta puesta' para que las opciones de lanzamiento de",
        "# Steam sigan ganando si alguna vez se ponen ahi tambien.",
    ]
    for var, valor in valores.items():
        if valor == "":
            continue  # vacio = usar el default del propio .sh, no forzar nada
        valor_escapado = valor.replace('"', '\\"')
        lineas.append(f': "${{{var}:={valor_escapado}}}"')
    with open(ARCHIVO_CONFIG, "w") as f:
        f.write("\n".join(lineas) + "\n")



# Icono y color de los mosaicos de cada seccion (los mismos colores que el resto de menus).
ESTILO_SECCION = {
    "Pantalla": ("image", ui.NARANJA),
    "Control remoto (ESP32 -> PS3)": ("gamepad", ui.VERDE),
    "Video y latencia": ("play", ui.AZUL),
    "Watchdog de atasco de video": ("timer", ui.MORADO),
    "Diagnostico": ("info", ui.GRIS),
}
COLUMNAS = 3


def main():
    import tkinter as tk

    root = tk.Tk()
    root.title("Configurar cliente")
    root.configure(bg=ui.FONDO)
    esc = ui.Escala(ui.configurar_ventana(root))
    iconos = ui.Iconos()
    cerrado = {"v": False}
    estado = {"dialogo": None}

    def salir():
        cerrado["v"] = True
        root.destroy()

    marco = tk.Frame(root, bg=ui.FONDO, padx=esc.px(24), pady=esc.px(16))
    marco.pack(fill="both", expand=True)
    cab, _ = ui.cabecera(marco, esc, "Configurar cliente", "Vacío = usar el default")
    cab.pack(fill="x")
    tira = ui.TiraEstado(marco, esc, alto=46)
    tira.pack(fill="x", pady=esc.px(6))
    AYUDA_GENERAL = "Cruceta: mover · A: cambiar · L1/R1: anterior / siguiente · B: volver"
    tira.pintar(ui.TENUE, AYUDA_GENERAL)

    # --- area con scroll ---
    contenedor = tk.Frame(marco, bg=ui.FONDO)
    contenedor.pack(fill="both", expand=True)
    canvas = tk.Canvas(contenedor, bg=ui.FONDO, highlightthickness=0)
    scrollbar = tk.Scrollbar(contenedor, orient="vertical", command=canvas.yview, width=esc.px(16),
                             bg=ui.GRIS, troughcolor=ui.FONDO, relief="flat", bd=0)
    interior = tk.Frame(canvas, bg=ui.FONDO)
    interior.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    ventana_interior = canvas.create_window((0, 0), window=interior, anchor="nw")
    # Sin esto, "interior" solo mide lo que su contenido pide y las filas quedan angostas y pegadas
    # a la izquierda dentro del canvas (reportado 2026-09-11): se iguala el ancho al del canvas.
    canvas.bind("<Configure>", lambda e: canvas.itemconfig(ventana_interior, width=e.width))
    canvas.configure(yscrollcommand=scrollbar.set)
    canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")

    def _scroll(delta):
        canvas.yview_scroll(delta, "units")

    canvas.bind_all("<MouseWheel>", lambda e: _scroll(-1 if e.delta > 0 else 1))
    canvas.bind_all("<Button-4>", lambda e: _scroll(-1))
    canvas.bind_all("<Button-5>", lambda e: _scroll(1))

    guardado = leer_guardado()
    valores = {}        # variable -> texto guardable ("1"/"0", opcion del enum, o el texto/numero)
    orden = []          # variables en el orden de CAMPOS (asi sale igual en client_config.env)
    filas = []          # [(frame_de_la_fila, [mosaicos])] en orden visual
    ayuda_de = {}       # mosaico -> texto largo para la linea de ayuda

    def abrir_cuadro(titulo, actual, al_aceptar):
        estado["dialogo"] = ui.DialogoTexto(root, esc, titulo, actual, al_aceptar)

    def crear_mosaico(padre, var, etiqueta, tipo, default, opciones, ayuda, icono, color):
        valor = guardado.get(var, default)
        if tipo == "bool":
            valores[var] = "1" if valor == "1" else "0"
        elif tipo == "enum":
            valores[var] = valor if valor in opciones else opciones[0]
        else:
            valores[var] = valor
        orden.append(var)

        def visible():
            v = valores[var]
            if tipo == "bool":
                return "SI" if v == "1" else "NO"
            return v if v != "" else "(vacío)"

        def color_actual():
            if tipo == "bool":
                return ui.VERDE if valores[var] == "1" else ui.GRIS
            return color

        t = ui.Mosaico(padre, esc, iconos, icono, visible(), etiqueta, color_actual(),
                       tam_titulo=26, tam_detalle=14, tam_icono=40, alto=esc.px(150))

        def refrescar():
            t.titulo = visible()
            t.poner_color(color_actual())

        def cambiar_numero(delta):
            actual = valores[var].strip()
            try:
                base = int(actual) if actual else 0
            except ValueError:
                return
            valores[var] = str(base + delta)
            refrescar()

        def ciclar(paso):
            i = opciones.index(valores[var]) if valores[var] in opciones else 0
            valores[var] = opciones[(i + paso) % len(opciones)]
            refrescar()

        def alternar(_paso=1):
            valores[var] = "0" if valores[var] == "1" else "1"
            refrescar()

        def editar():
            def aceptar(texto):
                valores[var] = texto
                refrescar()
            abrir_cuadro(etiqueta, valores[var], aceptar)

        if tipo == "bool":
            t.on_a = alternar
            t.delta = alternar
        elif tipo == "enum":
            t.on_a = lambda: ciclar(1)
            t.delta = ciclar
        elif tipo == "numero":
            t.on_a = editar
            t.delta = cambiar_numero
        else:
            t.on_a = editar
            t.delta = None
        ayuda_de[t] = f"{etiqueta}: {ayuda}" if ayuda else etiqueta
        return t

    seccion_actual = None
    fila_actual = None
    for campo in CAMPOS:
        var, etiqueta, tipo, default, opciones, ayuda = campo
        if var == "__SECCION__":
            icono, color = ESTILO_SECCION.get(etiqueta, ("settings", ui.AZUL))
            rotulo = tk.Label(interior, text=etiqueta, font=esc.fuente(20, True), bg=ui.FONDO,
                              fg=ui.TENUE if color == ui.GRIS else color, anchor="w")
            rotulo.pack(fill="x", pady=(esc.px(14), esc.px(2)))
            seccion_actual = {"icono": icono, "color": color, "rotulo": rotulo, "primera": True}
            fila_actual = None
            continue
        if fila_actual is None or len(filas[-1][1]) >= COLUMNAS:
            f = tk.Frame(interior, bg=ui.FONDO)
            f.pack(fill="x")
            filas.append((f, []))
            fila_actual = f
            primera_fila = seccion_actual["primera"]
            seccion_actual["primera"] = False
        t = crear_mosaico(filas[-1][0], var, etiqueta, tipo, default, opciones, ayuda,
                          seccion_actual["icono"], seccion_actual["color"])
        # al enfocarlo, la lista debe dejar visible tambien el titulo de su seccion si es la 1a fila
        t.arriba = seccion_actual["rotulo"] if primera_fila and not filas[-1][1] else filas[-1][0]
        filas[-1][1].append(t)
    for f, tiles in filas:
        ui.disponer(f, tiles, esc, columnas=COLUMNAS)

    # --- botones de accion, fijos abajo (fuera del scroll) ---
    def guardar_todo():
        guardar({var: valores[var] for var in orden})
        tira.pintar(ui.OK, "Guardado. Se aplica la proxima vez que arranques streaming/control.")

    def restaurar_defaults():
        try:
            os.remove(ARCHIVO_CONFIG)
        except FileNotFoundError:
            pass
        salir()
        main()  # reabre la pantalla limpia, releyendo (ya no hay archivo) los defaults

    f_pie = ui.fila(marco, esc, expandir=False)
    t_guardar = ui.Mosaico(f_pie, esc, iconos, "check", "Guardar", "", ui.AZUL, on_a=guardar_todo,
                           tam_titulo=22, tam_icono=40, horizontal=True, alto=esc.px(84))
    t_restaurar = ui.Mosaico(f_pie, esc, iconos, "refresh", "Restaurar defaults", "", ui.GRIS,
                             on_a=restaurar_defaults, tam_titulo=22, tam_icono=40,
                             horizontal=True, alto=esc.px(84))
    t_volver = ui.Mosaico(f_pie, esc, iconos, "back", "Volver", "", ui.GRIS, on_a=salir,
                          tam_titulo=22, tam_icono=40, horizontal=True, alto=esc.px(84))
    ui.disponer(f_pie, [t_guardar, t_restaurar, t_volver], esc)
    ayuda_de[t_guardar] = "Guardar: escribe client_config.env; se aplica en el proximo arranque."
    ayuda_de[t_restaurar] = "Restaurar defaults: borra client_config.env y reabre esta pantalla."
    ayuda_de[t_volver] = "Volver al menu (lo no guardado se pierde)."

    # --- linea de ayuda de la variable enfocada ---
    lbl_ayuda = tk.Label(marco, text="", font=esc.fuente(14), bg=ui.FONDO, fg=ui.TENUE,
                         justify="left", anchor="w", wraplength=esc.px(1200))
    lbl_ayuda.pack(fill="x", pady=(esc.px(2), 0), before=f_pie)

    def asegurar_visible(t):
        """Desplaza la lista para que el mosaico enfocado (y su titulo de seccion) queden a la vista."""
        if not str(t).startswith(str(interior)) or t.arriba is None:
            return
        root.update_idletasks()
        total = interior.winfo_height() or 1
        vista = canvas.winfo_height()
        y1 = t.arriba.winfo_y()
        y2 = t.master.winfo_y() + t.master.winfo_height()
        arriba_actual = canvas.canvasy(0)
        margen = esc.px(8)
        if y1 - margen < arriba_actual:
            canvas.yview_moveto(max(0.0, (y1 - margen) / total))
        elif y2 + margen > arriba_actual + vista:
            canvas.yview_moveto(min(1.0, (y2 + margen - vista) / total))

    def al_cambiar(t):
        lbl_ayuda.configure(text=ayuda_de.get(t, ""))
        asegurar_visible(t)

    nav = ui.Navegador([tiles for _, tiles in filas] + [[t_guardar, t_restaurar, t_volver]],
                       al_cambiar=al_cambiar)

    def delta(paso):
        d = getattr(nav.actual(), "delta", None)
        if d:
            d(paso)

    root.bind("<Left>", lambda e: nav.mover(-1, 0))
    root.bind("<Right>", lambda e: nav.mover(1, 0))
    root.bind("<Up>", lambda e: nav.mover(0, -1))
    root.bind("<Down>", lambda e: nav.mover(0, 1))
    root.bind("<Return>", lambda e: nav.activar())
    root.bind("<Prior>", lambda e: delta(-1))
    root.bind("<Next>", lambda e: delta(1))
    root.bind("<Escape>", lambda e: salir())

    mando = Mando()

    def revisar_mando():
        for nombre in mando.nuevos():
            dlg = estado["dialogo"]
            if dlg is not None and dlg.abierto:
                dlg.tecla(nombre)   # con el cuadro de texto abierto, el mando solo maneja el cuadro
                continue
            if nombre == "DPAD_UP":
                nav.mover(0, -1)
            elif nombre == "DPAD_DOWN":
                nav.mover(0, 1)
            elif nombre == "DPAD_LEFT":
                nav.mover(-1, 0)
            elif nombre == "DPAD_RIGHT":
                nav.mover(1, 0)
            elif nombre == "A":
                nav.activar()
            elif nombre == "L1":
                delta(-1)
            elif nombre == "R1":
                delta(1)
            elif nombre == "B":
                salir()
            if cerrado["v"]:
                return
        root.after(40, revisar_mando)

    root.after(40, revisar_mando)
    root.mainloop()


if __name__ == "__main__":
    main()
