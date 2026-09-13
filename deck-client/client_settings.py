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

No hay suficiente pantalla para 18 variables sin scroll: se arma con un
Canvas + Frame desplazable. La edicion de texto es con teclado/tactil (no
hay teclado en pantalla para el mando); el mando solo mueve el scroll.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from deck_gamepad import Mando  # noqa: E402

FONDO = "#101014"
PANEL = "#181c28"
TEXTO = "#e8e8ea"
TENUE = "#8a8a95"
VERDE = "#3f8f4a"
AZUL = "#2d6cdf"

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


def main():
    import tkinter as tk
    from tkinter import font as tkfont

    root = tk.Tk()
    root.title("Configurar cliente")
    root.configure(bg=FONDO)
    try:
        root.attributes("-fullscreen", True)
    except Exception:
        root.geometry("900x600")

    f_titulo = tkfont.Font(family="DejaVu Sans", size=22, weight="bold")
    f_seccion = tkfont.Font(family="DejaVu Sans", size=14, weight="bold")
    f_label = tkfont.Font(family="DejaVu Sans", size=12)
    f_ayuda = tkfont.Font(family="DejaVu Sans", size=10)
    f_entry = tkfont.Font(family="DejaVu Sans", size=12)
    f_boton = tkfont.Font(family="DejaVu Sans", size=14, weight="bold")
    f_pie = tkfont.Font(family="DejaVu Sans", size=11)

    tk.Label(root, text="Configurar cliente", font=f_titulo,
             bg=FONDO, fg=TEXTO).pack(pady=(18, 2))
    tk.Label(root, text="Variables de latencia del cliente (Deck). Vacio = usar el default.",
             font=f_ayuda, bg=FONDO, fg=TENUE).pack(pady=(0, 10))

    # --- area con scroll ---
    contenedor = tk.Frame(root, bg=FONDO)
    contenedor.pack(fill="both", expand=True, padx=20)

    canvas = tk.Canvas(contenedor, bg=FONDO, highlightthickness=0)
    scrollbar = tk.Scrollbar(contenedor, orient="vertical", command=canvas.yview)
    interior = tk.Frame(canvas, bg=FONDO)

    interior.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    ventana_interior = canvas.create_window((0, 0), window=interior, anchor="nw")
    # Sin esto, "interior" solo mide lo que su contenido pide y las filas
    # (fill="x") quedan angostas y pegadas a la izquierda dentro del canvas,
    # con hueco vacio a la derecha - "no esta centrado, se ve a la
    # izquierda" (reportado 2026-09-11). Igualando el ancho de la ventana
    # interna al del canvas en cada resize, las filas ocupan todo el ancho
    # real de la pantalla.
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
    widgets = {}   # variable -> (tipo, getter_callable)
    filas_nav = []  # [{"frame":.., "on_left":fn, "on_right":fn, "on_a":fn}, ...] en orden visual

    def _cambiar_numero(entry, delta):
        actual = entry.get().strip()
        try:
            base = int(actual) if actual else 0
        except ValueError:
            return
        entry.delete(0, "end")
        entry.insert(0, str(base + delta))

    for campo in CAMPOS:
        var, etiqueta, tipo, default, opciones, ayuda = campo

        if var == "__SECCION__":
            tk.Label(interior, text=etiqueta, font=f_seccion, bg=FONDO, fg=AZUL,
                     anchor="w").pack(fill="x", pady=(16, 4))
            continue

        fila = tk.Frame(interior, bg=PANEL, padx=12, pady=8,
                         highlightthickness=2, highlightbackground=PANEL)
        fila.pack(fill="x", pady=3)

        izq = tk.Frame(fila, bg=PANEL)
        izq.pack(side="left", fill="x", expand=True)
        tk.Label(izq, text=etiqueta, font=f_label, bg=PANEL, fg=TEXTO,
                 anchor="w").pack(anchor="w")
        if ayuda:
            tk.Label(izq, text=ayuda, font=f_ayuda, bg=PANEL, fg=TENUE,
                     anchor="w", wraplength=560, justify="left").pack(anchor="w")

        valor_actual = guardado.get(var, default)

        if tipo in ("texto", "numero"):
            entry = tk.Entry(fila, font=f_entry, width=14, justify="center")
            entry.insert(0, valor_actual)
            entry.pack(side="right", padx=(10, 0))
            widgets[var] = ("texto", lambda e=entry: e.get().strip())

            nav = {"frame": fila, "on_a": lambda e=entry: e.focus_set()}
            if tipo == "numero":
                nav["on_left"] = lambda e=entry: _cambiar_numero(e, -1)
                nav["on_right"] = lambda e=entry: _cambiar_numero(e, 1)
            filas_nav.append(nav)

        elif tipo == "bool":
            estado = {"v": valor_actual == "1"}
            btn = tk.Button(fila, font=f_boton, width=6, relief="flat", bd=0)

            def refrescar(b=btn, e=estado):
                b.configure(text="SI" if e["v"] else "NO",
                            bg=VERDE if e["v"] else "#3a3a42",
                            fg="#ffffff", activebackground=VERDE if e["v"] else "#3a3a42",
                            activeforeground="#ffffff")

            def alternar(e=estado, r=refrescar):
                e["v"] = not e["v"]
                r()

            btn.configure(command=alternar)
            refrescar()
            btn.pack(side="right", padx=(10, 0))
            widgets[var] = ("bool", lambda e=estado: ("1" if e["v"] else "0"))
            filas_nav.append({"frame": fila, "on_a": alternar,
                               "on_left": alternar, "on_right": alternar})

        elif tipo == "enum":
            estado = {"i": opciones.index(valor_actual) if valor_actual in opciones else 0}
            btn = tk.Button(fila, font=f_boton, width=12, relief="flat", bd=0,
                             bg="#3a3a42", fg="#ffffff", activebackground="#4a4a55",
                             activeforeground="#ffffff")

            def refrescar(b=btn, e=estado, ops=opciones):
                b.configure(text=ops[e["i"]])

            def ciclar(paso, e=estado, ops=opciones, r=refrescar):
                e["i"] = (e["i"] + paso) % len(ops)
                r()

            btn.configure(command=lambda c=ciclar: c(1))
            refrescar()
            btn.pack(side="right", padx=(10, 0))
            widgets[var] = ("enum", lambda e=estado, ops=opciones: ops[e["i"]])
            filas_nav.append({"frame": fila, "on_a": lambda c=ciclar: c(1),
                               "on_left": lambda c=ciclar: c(-1),
                               "on_right": lambda c=ciclar: c(1)})

    # --- botones de accion, fijos abajo (fuera del scroll) ---
    filaBotones = tk.Frame(root, bg=FONDO)
    filaBotones.pack(pady=14)

    lblEstado = tk.Label(root, text="", font=f_pie, bg=FONDO, fg=TENUE)
    lblEstado.pack(pady=(0, 6))

    def guardar_todo():
        valores = {var: getter() for var, (tipo, getter) in widgets.items()}
        guardar(valores)
        lblEstado.configure(text="Guardado. Se aplica la proxima vez que arranques streaming/control.",
                             fg=VERDE)

    def restaurar_defaults():
        for campo in CAMPOS:
            var = campo[0]
            if var == "__SECCION__" or var not in widgets:
                continue
        try:
            os.remove(ARCHIVO_CONFIG)
        except FileNotFoundError:
            pass
        root.destroy()
        main()  # reabre la pantalla limpia, releyendo (ya no hay archivo) los defaults

    # highlightthickness/highlightbackground (2026-09-13, "quiero que TODOS
    # los botones sean ejecutables [y focuseables]"): antes estos 3 botones
    # solo se alcanzaban con mouse/tactil, fuera del sistema de foco de
    # filas_nav. Se agregan al MISMO filas_nav (mas abajo) para que la
    # cruceta siga bajando hacia ellos despues de la ultima opcion - el
    # highlight funciona igual que en las filas de arriba porque es el mismo
    # truco (highlightbackground blanco = foco).
    btnGuardar = tk.Button(filaBotones, text="Guardar", font=f_boton, width=14, height=2,
                            bg=AZUL, fg="#ffffff", activebackground=AZUL, activeforeground="#ffffff",
                            relief="flat", bd=0, highlightthickness=3, highlightbackground=FONDO,
                            command=guardar_todo)
    btnGuardar.pack(side="left", padx=10)
    btnRestaurar = tk.Button(filaBotones, text="Restaurar defaults", font=f_boton, width=18, height=2,
                              bg="#3a3a42", fg="#ffffff", activebackground="#4a4a55", activeforeground="#ffffff",
                              relief="flat", bd=0, highlightthickness=3, highlightbackground=FONDO,
                              command=restaurar_defaults)
    btnRestaurar.pack(side="left", padx=10)
    btnVolver = tk.Button(filaBotones, text="Volver", font=f_boton, width=10, height=2,
                           bg="#3a3a42", fg="#ffffff", activebackground="#4a4a55", activeforeground="#ffffff",
                           relief="flat", bd=0, highlightthickness=3, highlightbackground=FONDO,
                           command=root.destroy)
    btnVolver.pack(side="left", padx=10)

    # Cuantas filas de OPCIONES hay (antes de agregar los botones) - marcar()
    # solo intenta desplazar el scroll del canvas para las primeras
    # "total_opciones" entradas; los botones viven fuera del scroll (fijos
    # abajo), asi que desplazar el canvas por ellos no tendria sentido (sus
    # coordenadas ni siquiera son relativas al mismo canvas).
    total_opciones = len(filas_nav)
    filas_nav.append({"frame": btnGuardar, "on_a": guardar_todo})
    filas_nav.append({"frame": btnRestaurar, "on_a": restaurar_defaults})
    filas_nav.append({"frame": btnVolver, "on_a": root.destroy})

    tk.Label(root, text="Cruceta arriba/abajo mueve el foco, izq/der cambia el valor, A activa, B vuelve.",
             font=f_pie, bg=FONDO, fg=TENUE).pack(side="bottom", pady=10)

    # --- navegacion por fila (2026-09-11) -----------------------------------
    # Antes el mando solo movia el scroll y todo lo demas era tactil/teclado -
    # "por cada opcion deberia responder a la botonera de la Deck" (reportado
    # el mismo dia). Con filas_nav ya armado arriba, cada fila sabe reaccionar
    # a izquierda/derecha/A segun su tipo (bool alterna, enum cicla, numero
    # suma/resta 1, texto solo enfoca el Entry para teclear).
    foco = {"i": 0}

    def marcar():
        for i, nav in enumerate(filas_nav):
            color_apagado = PANEL if i < total_opciones else FONDO
            nav["frame"].configure(highlightbackground="#ffffff" if i == foco["i"] else color_apagado)
        if filas_nav and foco["i"] < total_opciones:
            fila_actual = filas_nav[foco["i"]]["frame"]
            root.update_idletasks()
            y = fila_actual.winfo_y()
            alto_total = interior.winfo_height() or 1
            canvas.yview_moveto(max(0.0, (y - 40) / alto_total))

    def mover_foco(delta):
        if not filas_nav:
            return
        foco["i"] = (foco["i"] + delta) % len(filas_nav)
        marcar()

    def accionar(lado):
        if not filas_nav:
            return
        nav = filas_nav[foco["i"]]
        fn = nav.get(lado)
        if fn:
            fn()

    root.bind("<Escape>", lambda e: root.destroy())

    if filas_nav:
        marcar()

    mando = Mando()

    def revisar_mando():
        for nombre in mando.nuevos():
            if nombre == "DPAD_UP":
                mover_foco(-1)
            elif nombre == "DPAD_DOWN":
                mover_foco(1)
            elif nombre == "DPAD_LEFT":
                accionar("on_left")
            elif nombre == "DPAD_RIGHT":
                accionar("on_right")
            elif nombre == "A":
                accionar("on_a")
            elif nombre == "B":
                root.destroy()
                return
        root.after(40, revisar_mando)

    root.after(40, revisar_mando)
    root.mainloop()


if __name__ == "__main__":
    main()
