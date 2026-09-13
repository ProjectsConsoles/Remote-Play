#!/usr/bin/env python3
"""Menu de arranque del cliente de PS3 Remote Play.

Pregunta que se quiere hacer y lo imprime por stdout, que es lo que lee
start_client_stream.sh:

    streaming -> video + audio + control (lo de siempre)
    control   -> SOLO el control, con la pantalla de la Deck apagada

Ademas hay dos pantallas de configuracion (2026-09-11) que NO salen del
menu: se abren, y al cerrarse vuelven a mostrar este mismo menu.
    - "Configurar servidor": modo de captura del PC Windows, en remoto
      (client_server_config.py, habla con config_listener.ps1 por UDP).
    - "Configurar cliente": las variables de latencia de este mismo lado
      (client_settings.py, escribe client_config.env).

Se usa tkinter y no zenity/kdialog a proposito: tkinter ya viene con el Python
del sistema y con el del venv, y deja hacer botones del tamano que uno quiera.

SE NAVEGA CON EL MANDO, y eso hay que hacerlo a mano (2026-09-06). En Modo
Juego, Steam Input le entrega a la aplicacion un GAMEPAD, no un raton: el
trackpad NO mueve ningun cursor, asi que una ventana normal solo se puede tocar
con la pantalla tactil. Por eso aca se lee el mando directo con pygame y se
traduce a mover el foco / confirmar. El tactil y el raton siguen funcionando.

Codigos de salida:
    0 = eligio streaming o control, esta impreso en stdout
    1 = cancelo (B, Escape, o cerro la ventana)
    2 = no se pudo abrir ninguna ventana (sin DISPLAY, por ejemplo)

El 2 importa: el .sh lo trata como "sigue en streaming, como siempre", para que
un problema con el menu nunca deje al usuario sin nada.
"""

import os
import sys

# La lectura del mando vive en deck_gamepad.py, compartida con
# client_control_ui.py. Ese modulo tambien fija SDL_VIDEODRIVER=dummy y
# PYGAME_HIDE_SUPPORT_PROMPT al importarse, que son criticos aca: sin el
# primero SDL pelea con la ventana de tkinter, y sin el segundo pygame saluda
# por stdout, que es justo por donde este script devuelve la eleccion.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from deck_gamepad import Mando            # noqa: E402
from server_udp import (obtener_ip_local, obtener_red_wifi,  # noqa: E402
                         obtener_config, leer_ip_servidor_guardada)

FONDO = "#101014"
TEXTO = "#e8e8ea"
TENUE = "#8a8a95"


def mostrar_menu():
    """Una vuelta del menu. Devuelve la eleccion (string) o None si cancelo."""
    import tkinter as tk
    from tkinter import font as tkfont

    eleccion = {"modo": None}
    root = tk.Tk()
    root.title("Remote Play")
    root.configure(bg=FONDO)

    try:
        root.attributes("-fullscreen", True)
    except Exception:
        root.geometry("900x600")

    f_titulo = tkfont.Font(family="DejaVu Sans", size=26, weight="bold")
    f_boton = tkfont.Font(family="DejaVu Sans", size=16, weight="bold")
    f_ayuda = tkfont.Font(family="DejaVu Sans", size=12)
    f_detalle = tkfont.Font(family="DejaVu Sans", size=10)
    f_pie = tkfont.Font(family="DejaVu Sans", size=11)

    tk.Label(root, text="Remote Play", font=f_titulo,
             bg=FONDO, fg=TEXTO).pack(pady=(40, 6))

    ip_local = obtener_ip_local()
    red_wifi = obtener_red_wifi()
    partes_red = []
    if ip_local:
        partes_red.append(f"IP: {ip_local}")
    if red_wifi:
        partes_red.append(f"Red: {red_wifi}")
    if partes_red:
        tk.Label(root, text="   ·   ".join(partes_red), font=f_pie,
                 bg=FONDO, fg=TENUE).pack(pady=(0, 4))

    tk.Label(root, text="¿Que quieres hacer?", font=f_ayuda,
             bg=FONDO, fg=TENUE).pack(pady=(0, 26))

    grilla = tk.Frame(root, bg=FONDO)
    grilla.pack(expand=True)

    def elegir(modo):
        eleccion["modo"] = modo
        root.destroy()

    def tarjeta(fila, columna, titulo, detalle, color, modo):
        marco = tk.Frame(grilla, bg=FONDO)
        marco.grid(row=fila, column=columna, padx=18, pady=14)
        b = tk.Button(marco, text=titulo, font=f_boton,
                      bg=color, fg="#ffffff",
                      activebackground=color, activeforeground="#ffffff",
                      width=15, height=3, relief="flat", bd=0,
                      highlightthickness=5, highlightbackground=FONDO,
                      highlightcolor="#ffffff",
                      command=lambda: elegir(modo))
        b.pack()
        tk.Label(marco, text=detalle, font=f_detalle, bg=FONDO, fg=TENUE,
                 wraplength=240, justify="center").pack(pady=(10, 0))
        return b

    # 2x2: streaming/control arriba (las de jugar), configuracion abajo.
    b_stream = tarjeta(0, 0, "Streaming",
        "Video y audio de la consola en la Deck, mas el control.",
        "#2d6cdf", "streaming")
    b_control = tarjeta(0, 1, "Solo control",
        "La Deck es nada mas el mando, con la pantalla apagada.",
        "#3f8f4a", "control")
    b_config_srv = tarjeta(1, 0, "Configurar servidor",
        "Modo de captura y estado de la PC Windows, en remoto.",
        "#8e5fd6", "config_servidor")
    b_config_cli = tarjeta(1, 1, "Configurar cliente",
        "Variables de latencia de esta Deck (VSYNC, watchdog, etc.).",
        "#c07d2f", "config_cliente")

    # Info del selector de modo del ESP32-S3 (2026-09-13, "se me olvidan los
    # colores"): boton aparte, NO metido en la grilla 2x2 de arriba (esa
    # tiene su propia matematica de foco por fila/columna, meterle un 5to
    # elemento la complicaria sin necesidad) - mismo patron que Y/X en las
    # otras pantallas (atajo fijo, no parte de la navegacion principal).
    # "abierta"/"cerrar" (no solo un bool): revisar_mando esta fuera del
    # scope de mostrar_info y necesita poder cerrar la ventana de info al
    # apretar B sin destruir TAMBIEN el menu de atras (los dos escuchan al
    # mismo mando via el mainloop de tkinter, sin importar cual ventana
    # tiene el foco - sin esto, B cerraba las dos de un jalon).
    info_estado = {"abierta": False, "cerrar": None}

    def mostrar_info():
        info_estado["abierta"] = True
        ventana = tk.Toplevel(root)
        ventana.title("Selector de modo del ESP32-S3")
        ventana.configure(bg=FONDO)
        try:
            ventana.attributes("-fullscreen", True)
        except Exception:
            ventana.geometry("700x500")

        tk.Label(ventana, text="Selector de modo del ESP32-S3", font=f_titulo,
                 bg=FONDO, fg=TEXTO).pack(pady=(40, 10))
        tk.Label(ventana,
                 text="Con la placa ya encendida (nunca al conectarla/resetear),\n"
                      "mantén BOOT ~1.5s. El LED cicla de color cada ~0.7s;\n"
                      "suelta el botón en el color que corresponda.",
                 font=f_ayuda, bg=FONDO, fg=TENUE, justify="center").pack(pady=(0, 30))

        colores = [
            ("#d4b106", "Amarillo", "PS3"),
            ("#2d6cdf", "Azul", "PS2 / OPL"),
            ("#8e5fd6", "Morado", "Xbox 360"),
        ]
        filaColores = tk.Frame(ventana, bg=FONDO)
        filaColores.pack(pady=10)
        for color, nombre, consola in colores:
            marco = tk.Frame(filaColores, bg=FONDO)
            marco.pack(side="left", padx=24)
            tk.Frame(marco, bg=color, width=48, height=48,
                     highlightthickness=2, highlightbackground=TEXTO).pack()
            tk.Label(marco, text=nombre, font=f_boton, bg=FONDO, fg=TEXTO).pack(pady=(10, 0))
            tk.Label(marco, text=consola, font=f_detalle, bg=FONDO, fg=TENUE).pack()

        tk.Label(ventana, text="El modo elegido queda guardado en la placa hasta que se cambie a mano.",
                 font=f_pie, bg=FONDO, fg=TENUE).pack(pady=(30, 0))

        def cerrar_info():
            info_estado["abierta"] = False
            ventana.destroy()

        info_estado["cerrar"] = cerrar_info

        btnCerrar = tk.Button(ventana, text="Volver", font=f_boton,
                               bg="#3a3a42", fg="#ffffff", activebackground="#4a4a55",
                               activeforeground="#ffffff", relief="flat", bd=0,
                               width=12, height=2, command=cerrar_info)
        btnCerrar.pack(pady=30)
        btnCerrar.focus_set()

        tk.Label(ventana, text="B o Escape para volver.", font=f_pie,
                 bg=FONDO, fg=TENUE).pack(side="bottom", pady=16)

        ventana.bind("<Escape>", lambda e: cerrar_info())
        ventana.bind("<Return>", lambda e: cerrar_info())
        ventana.protocol("WM_DELETE_WINDOW", cerrar_info)
        ventana.grab_set()

    opciones = [b_stream, b_control, b_config_srv, b_config_cli]

    btnInfo = tk.Button(root, text="Info: colores del ESP32-S3", font=f_pie,
                         bg=FONDO, fg=TENUE, activebackground=FONDO, activeforeground=TEXTO,
                         relief="flat", bd=0, highlightthickness=3, highlightbackground=FONDO,
                         command=mostrar_info)
    btnInfo.pack(side="bottom", pady=(0, 4))

    # zona="grid"/"info" (2026-09-13, "otra vez el boton solo es tactil, no
    # puedo focusearlo" - mismo patron ya usado en client_server_config.py y
    # client_settings.py): bajar desde la fila de abajo de la grilla 2x2
    # entra al boton de Info; arriba desde ahi regresa a la grilla.
    foco = {"zona": "grid", "i": 0}

    def marcar():
        for i, b in enumerate(opciones):
            en_foco = foco["zona"] == "grid" and i == foco["i"]
            b.configure(highlightbackground="#ffffff" if en_foco else FONDO)
        btnInfo.configure(highlightbackground="#ffffff" if foco["zona"] == "info" else FONDO)
        if foco["zona"] == "grid":
            opciones[foco["i"]].focus_set()
        else:
            btnInfo.focus_set()

    def mover(dx, dy):
        if foco["zona"] == "info":
            if dy < 0:
                foco["zona"] = "grid"
                marcar()
            return
        fila, col = divmod(foco["i"], 2)
        if dy > 0 and fila == 1:
            foco["zona"] = "info"
            marcar()
            return
        fila = (fila + dy) % 2
        col = (col + dx) % 2
        foco["i"] = fila * 2 + col
        marcar()

    def confirmar():
        if foco["zona"] == "info":
            mostrar_info()
            return
        opciones[foco["i"]].invoke()

    pie = tk.Label(root, font=f_pie, bg=FONDO, fg=TENUE)
    pie.pack(side="bottom", pady=24)

    root.bind("<Left>", lambda e: mover(-1, 0))
    root.bind("<Right>", lambda e: mover(1, 0))
    root.bind("<Up>", lambda e: mover(0, -1))
    root.bind("<Down>", lambda e: mover(0, 1))
    root.bind("<Tab>", lambda e: mover(1, 0))
    root.bind("<Return>", lambda e: confirmar())
    root.bind("<space>", lambda e: confirmar())
    root.bind("<y>", lambda e: mostrar_info())
    root.bind("<Y>", lambda e: mostrar_info())
    root.bind("<Escape>", lambda e: root.destroy())

    mando = Mando()
    pie.configure(
        text=("Cruceta/stick para moverte, confirma con A, cancela con B, info con Y."
              if mando.ok else
              "Toca la pantalla para elegir.")
        + "   (el tactil siempre funciona)")

    def revisar_mando():
        for nombre in mando.nuevos():
            # Mientras la ventana de info esta abierta, el mando solo la
            # cierra (B) - todo lo demas (mover el foco, A) es del menu de
            # atras y no deberia colar mientras se esta leyendo la info.
            if info_estado["abierta"]:
                if nombre == "B" and info_estado["cerrar"]:
                    info_estado["cerrar"]()
                continue
            if nombre == "DPAD_LEFT":
                mover(-1, 0)
            elif nombre == "DPAD_RIGHT":
                mover(1, 0)
            elif nombre == "DPAD_UP":
                mover(0, -1)
            elif nombre == "DPAD_DOWN":
                mover(0, 1)
            elif nombre == "A":
                confirmar()
                return          # la ventana ya se destruyo
            elif nombre == "Y":
                mostrar_info()
            elif nombre == "B":
                root.destroy()
                return
        # 40 ms: bastante fino para que no se sienta pegajoso y lo bastante
        # espaciado para no gastar CPU en un menu.
        root.after(40, revisar_mando)

    marcar()
    root.after(40, revisar_mando)
    root.mainloop()

    return eleccion["modo"]


def verificar_servidor_listo():
    """Antes de streaming (2026-09-11): confirma con el servidor (mismo
    protocolo UDP de "Configurar servidor", puerto 9200) que tiene puesta la
    IP de ESTA Deck y que esta transmitiendo - en vez de lanzar ffplay a
    esperar un video que puede no llegar nunca si el servidor le manda los
    paquetes a otra maquina. Alternativa mas segura que ponerle un timeout a
    la propia conexion UDP de ffplay (eso arriesgaria cortar una partida real
    si la wifi tiene un corte de mas de unos segundos, ver la nota en
    OPCIONES.md/discusion del 2026-09-11) - esto solo mira el ESTADO
    declarado del servidor, nunca toca el pipeline de video en si.

    Devuelve (True, "") si esta todo bien (o si nunca se configuro el
    servidor desde aca y no hay como chequear - se sigue como siempre, sin
    bloquear a nadie que no use la pantalla nueva), o (False, mensaje) si
    hay algo que el usuario deberia arreglar antes de intentar streaming."""
    ip_servidor = leer_ip_servidor_guardada()
    if not ip_servidor:
        return True, ""
    ip_local = obtener_ip_local()
    ok, resp = obtener_config(ip_servidor)
    if not ok:
        return False, f"No se pudo consultar el servidor ({ip_servidor}):\n{resp}"
    if not resp.get("corriendo"):
        return False, (f"El servidor ({ip_servidor}) no esta transmitiendo ahora mismo.\n\n"
                        "Prendelo desde la PC, o revisa \"Configurar servidor\".")
    # "transmitiendo" (2026-09-11): el servidor lo agrego para no mentir
    # cuando su ffmpeg quedo colgado (proceso vivo pero sin sacar un solo
    # cuadro, ver server_engine_lib.ps1). Solo se exige si el servidor
    # mando el campo: si es una version vieja del listener, no esta y no se
    # bloquea nada.
    if resp.get("transmitiendo") is False:
        return False, (f"El servidor ({ip_servidor}) dice estar prendido pero no esta "
                        "sacando video (se le colgo la captura).\n\n"
                        "Detenlo y vuelvelo a iniciar desde la PC.")
    if ip_local and resp.get("ip") != ip_local:
        return False, (f"El servidor esta mandando el video a {resp.get('ip')}, "
                        f"no a esta Deck ({ip_local}).\n\n"
                        "Entra a \"Configurar servidor\" y manda tu IP con el boton "
                        "de enviar IP.")
    return True, ""


def main():
    # Bucle (2026-09-11): "Configurar servidor"/"Configurar cliente" abren su
    # propia pantalla y, al cerrarse, vuelven aca en vez de salir - por eso
    # esto ya no es un tiro unico como streaming/control (que SI terminan el
    # programa, imprimiendo la eleccion para que la lea start_client_stream.sh).
    while True:
        modo = mostrar_menu()

        if modo is None:
            return 1

        if modo == "config_servidor":
            import client_server_config
            try:
                client_server_config.main()
            except Exception as e:
                print(f"pantalla de config del servidor fallo: {e}", file=sys.stderr)
            continue

        if modo == "config_cliente":
            import client_settings
            try:
                client_settings.main()
            except Exception as e:
                print(f"pantalla de config del cliente fallo: {e}", file=sys.stderr)
            continue

        if modo == "streaming":
            ok, mensaje = verificar_servidor_listo()
            if not ok:
                try:
                    from tkinter import messagebox
                    messagebox.showwarning("Remote Play", mensaje)
                except Exception as e:
                    print(f"aviso de servidor no listo: {mensaje} ({e})", file=sys.stderr)
                continue

        print(modo)
        return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        # Sin DISPLAY, sin Xwayland, tkinter roto... da igual el motivo: el .sh
        # tiene que poder seguir adelante en vez de dejar al usuario sin nada.
        print(f"menu no disponible: {e}", file=sys.stderr)
        sys.exit(2)
