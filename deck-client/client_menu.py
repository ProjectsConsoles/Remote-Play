#!/usr/bin/env python3
"""Menu de arranque del cliente de PS3 Remote Play.

Pregunta que se quiere hacer y lo imprime por stdout, que es lo que lee
start_client_stream.sh:

    streaming -> video + audio + control (lo de siempre)
    control   -> SOLO el control, con la pantalla de la Deck apagada

Se usa tkinter y no zenity/kdialog a proposito: tkinter ya viene con el Python
del sistema y con el del venv, y deja hacer botones del tamano que uno quiera.

SE NAVEGA CON EL MANDO, y eso hay que hacerlo a mano (2026-09-06). En Modo
Juego, Steam Input le entrega a la aplicacion un GAMEPAD, no un raton: el
trackpad NO mueve ningun cursor, asi que una ventana normal solo se puede tocar
con la pantalla tactil. Por eso aca se lee el mando directo con pygame y se
traduce a mover el foco / confirmar. El tactil y el raton siguen funcionando.

Codigos de salida:
    0 = eligio algo, esta impreso en stdout
    1 = cancelo (B, Escape, o cerro la ventana)
    2 = no se pudo abrir ninguna ventana (sin DISPLAY, por ejemplo)

El 2 importa: el .sh lo trata como "sigue en streaming, como siempre", para que
un problema con el menu nunca deje al usuario sin nada.
"""

import os
import socket
import subprocess
import sys

# La lectura del mando vive en deck_gamepad.py, compartida con
# client_control_ui.py. Ese modulo tambien fija SDL_VIDEODRIVER=dummy y
# PYGAME_HIDE_SUPPORT_PROMPT al importarse, que son criticos aca: sin el
# primero SDL pelea con la ventana de tkinter, y sin el segundo pygame saluda
# por stdout, que es justo por donde este script devuelve la eleccion.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from deck_gamepad import Mando            # noqa: E402

FONDO = "#101014"
TEXTO = "#e8e8ea"
TENUE = "#8a8a95"



def obtener_ip_local():
    """IP de esta Deck en la red local. Se muestra en el menu para no tener
    que ir a buscarla en Configuracion cuando hace falta ponerla en el
    servidor de Windows (el campo de IP de start_server_gui.ps1).

    El truco del socket UDP "conectado" a 8.8.8.8 no manda ningun paquete:
    solo hace que el sistema operativo elija que interfaz de salida usaria,
    y de ahi se lee la IP local de esa interfaz. Funciona sin internet real.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def obtener_red_wifi():
    """Nombre (SSID) de la red Wi-Fi conectada ahora, o None si no hay
    conexion inalambrica activa (por ejemplo, si esta por cable)."""
    try:
        salida = subprocess.check_output(
            ["nmcli", "-t", "-f", "active,ssid", "dev", "wifi"],
            text=True, timeout=2)
        for linea in salida.splitlines():
            if linea.startswith("yes:"):
                return linea.split(":", 1)[1]
    except Exception:
        pass
    return None

def main():
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
    f_boton = tkfont.Font(family="DejaVu Sans", size=20, weight="bold")
    f_ayuda = tkfont.Font(family="DejaVu Sans", size=12)
    f_pie = tkfont.Font(family="DejaVu Sans", size=11)

    tk.Label(root, text="Remote Play", font=f_titulo,
             bg=FONDO, fg=TEXTO).pack(pady=(60, 6))

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
             bg=FONDO, fg=TENUE).pack(pady=(0, 40))

    fila = tk.Frame(root, bg=FONDO)
    fila.pack(expand=True)

    def elegir(modo):
        eleccion["modo"] = modo
        root.destroy()

    def tarjeta(titulo, detalle, color, modo):
        marco = tk.Frame(fila, bg=FONDO)
        marco.pack(side="left", padx=26)
        b = tk.Button(marco, text=titulo, font=f_boton,
                      bg=color, fg="#ffffff",
                      activebackground=color, activeforeground="#ffffff",
                      width=14, height=3, relief="flat", bd=0,
                      highlightthickness=5, highlightbackground=FONDO,
                      highlightcolor="#ffffff",
                      command=lambda: elegir(modo))
        b.pack()
        tk.Label(marco, text=detalle, font=f_ayuda, bg=FONDO, fg=TENUE,
                 wraplength=290, justify="center").pack(pady=(14, 0))
        return b

    b_stream = tarjeta(
        "Streaming",
        "Video y audio de la consola en la pantalla de la Deck, mas el control.\n"
        "Es lo de siempre.",
        "#2d6cdf", "streaming")

    b_control = tarjeta(
        "Solo control",
        "La Deck funciona nada mas como mando, con la pantalla apagada.\n"
        "Para jugar mirando la tele.",
        "#3f8f4a", "control")

    opciones = [b_stream, b_control]
    foco = {"i": 0}

    def marcar():
        for i, b in enumerate(opciones):
            # El recuadro blanco es la unica pista visual de donde estas
            # parado cuando navegas con el mando.
            b.configure(highlightbackground="#ffffff" if i == foco["i"] else FONDO)
        opciones[foco["i"]].focus_set()

    def mover(paso):
        foco["i"] = (foco["i"] + paso) % len(opciones)
        marcar()

    def confirmar():
        opciones[foco["i"]].invoke()

    pie = tk.Label(root, font=f_pie, bg=FONDO, fg=TENUE)
    pie.pack(side="bottom", pady=30)

    # Teclado (Modo Escritorio) y tactil (los dos modos) siguen andando.
    root.bind("<Left>", lambda e: mover(-1))
    root.bind("<Right>", lambda e: mover(1))
    root.bind("<Up>", lambda e: mover(-1))
    root.bind("<Down>", lambda e: mover(1))
    root.bind("<Tab>", lambda e: mover(1))
    root.bind("<Return>", lambda e: confirmar())
    root.bind("<space>", lambda e: confirmar())
    root.bind("<Escape>", lambda e: root.destroy())

    mando = Mando()
    pie.configure(
        text=("Muevete con la cruceta o el stick, confirma con A, cancela con B."
              if mando.ok else
              "Toca la pantalla para elegir.")
        + "   (el tactil siempre funciona)")

    def revisar_mando():
        for nombre in mando.nuevos():
            if nombre == "DPAD_LEFT":
                mover(-1)
            elif nombre == "DPAD_RIGHT":
                mover(1)
            elif nombre == "A":
                confirmar()
                return          # la ventana ya se destruyo
            elif nombre == "B":
                root.destroy()
                return
        # 40 ms: bastante fino para que no se sienta pegajoso y lo bastante
        # espaciado para no gastar CPU en un menu.
        root.after(40, revisar_mando)

    marcar()
    root.after(40, revisar_mando)
    root.mainloop()

    if eleccion["modo"] is None:
        return 1
    print(eleccion["modo"])
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        # Sin DISPLAY, sin Xwayland, tkinter roto... da igual el motivo: el .sh
        # tiene que poder seguir adelante en vez de dejar al usuario sin nada.
        print(f"menu no disponible: {e}", file=sys.stderr)
        sys.exit(2)
