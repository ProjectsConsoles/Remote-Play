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
    canvas.create_window((0, 0), window=interior, anchor="nw")
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

    for campo in CAMPOS:
        var, etiqueta, tipo, default, opciones, ayuda = campo

        if var == "__SECCION__":
            tk.Label(interior, text=etiqueta, font=f_seccion, bg=FONDO, fg=AZUL,
                     anchor="w").pack(fill="x", pady=(16, 4))
            continue

        fila = tk.Frame(interior, bg=PANEL, padx=12, pady=8)
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

        elif tipo == "enum":
            estado = {"i": opciones.index(valor_actual) if valor_actual in opciones else 0}
            btn = tk.Button(fila, font=f_boton, width=12, relief="flat", bd=0,
                             bg="#3a3a42", fg="#ffffff", activebackground="#4a4a55",
                             activeforeground="#ffffff")

            def refrescar(b=btn, e=estado, ops=opciones):
                b.configure(text=ops[e["i"]])

            def ciclar(e=estado, ops=opciones, r=refrescar):
                e["i"] = (e["i"] + 1) % len(ops)
                r()

            btn.configure(command=ciclar)
            refrescar()
            btn.pack(side="right", padx=(10, 0))
            widgets[var] = ("enum", lambda e=estado, ops=opciones: ops[e["i"]])

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

    tk.Button(filaBotones, text="Guardar", font=f_boton, width=14, height=2,
              bg=AZUL, fg="#ffffff", activebackground=AZUL, activeforeground="#ffffff",
              relief="flat", bd=0, command=guardar_todo).pack(side="left", padx=10)
    tk.Button(filaBotones, text="Restaurar defaults", font=f_boton, width=18, height=2,
              bg="#3a3a42", fg="#ffffff", activebackground="#4a4a55", activeforeground="#ffffff",
              relief="flat", bd=0, command=restaurar_defaults).pack(side="left", padx=10)
    tk.Button(filaBotones, text="Volver", font=f_boton, width=10, height=2,
              bg="#3a3a42", fg="#ffffff", activebackground="#4a4a55", activeforeground="#ffffff",
              relief="flat", bd=0, command=root.destroy).pack(side="left", padx=10)

    tk.Label(root, text="Toca/usa teclado para editar. El mando solo mueve el scroll (arriba/abajo) y B vuelve.",
             font=f_pie, bg=FONDO, fg=TENUE).pack(side="bottom", pady=10)

    root.bind("<Escape>", lambda e: root.destroy())

    mando = Mando()

    def revisar_mando():
        for nombre in mando.nuevos():
            if nombre == "DPAD_UP":
                _scroll(-2)
            elif nombre == "DPAD_DOWN":
                _scroll(2)
            elif nombre == "B":
                root.destroy()
                return
        root.after(40, revisar_mando)

    root.after(40, revisar_mando)
    root.mainloop()


if __name__ == "__main__":
    main()
