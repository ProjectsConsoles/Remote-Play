#!/usr/bin/env python3
"""Ventana del modo "solo control".

POR QUE EXISTE (2026-09-06). El modo control no abria ninguna ventana: solo
lanzaba el cliente de input y se quedaba esperando. En Modo Juego eso se ve como
que NO ARRANCO NADA - Steam se queda mostrando el boton "Cancelar" de la
pantalla de lanzamiento, porque espera que la aplicacion muestre una ventana que
nunca llega. Con esta ventana, Steam da el juego por arrancado.

EL MANDO SE LEE, PERO NO SE LE LIGA NINGUNA ACCION. La distincion es la clave
de esta ventana: aca el mando lo esta usando el usuario para JUGAR, asi que si
el boton A estuviera ligado a algo, cada salto en el juego pulsaria "Salir" o
movería el brillo. Por eso lo unico que se hace con el mando es MOSTRAR que se
esta pulsando, abajo de todo. Salir y el brillo son tactiles (o teclado, que no
se puede pulsar sin querer con el mando).

"Salir" NO cierra la aplicacion: devuelve al selector de modo. Quien se encarga
de eso es start_client_stream.sh, que corre en un bucle; aca solo se cierra la
ventana y el .sh decide. Antes de volver al menu, el .sh mata el cliente de
input y devuelve el brillo.

Codigos de salida:
    0 = el usuario cerro la ventana, o el cliente de input termino
    2 = no se pudo abrir ninguna ventana (el .sh entonces espera sin ventana)
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from deck_gamepad import Mando, etiquetar
except Exception:      # sin pygame o sin el modulo: la ventana anda igual,
    Mando = None       # solo se queda sin el indicador de botones.
    etiquetar = None

FONDO = "#000000"
TEXTO = "#e8e8ea"
TENUE = "#6f6f78"
VERDE = "#3f8f4a"

# No se deja bajar a 0: a oscuras total no se ve la propia barra para volver a
# subirla, y esta ventana no escucha el mando (ver arriba), asi que el usuario
# se quedaria sin forma de recuperarla salvo saliendo.
PCT_MIN = 1


def vivo(pid):
    """True si el proceso sigue existiendo."""
    if not pid:
        return True          # sin PID que vigilar, no cerrar nunca por esto
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


class Brillo:
    """Lee y escribe el backlight por sysfs.

    En la Steam Deck /sys/class/backlight/amdgpu_bl0/brightness es rw para el
    grupo "deck", asi que no hace falta sudo ni polkit (verificado 2026-09-06).
    """

    def __init__(self, carpeta):
        self.archivo = os.path.join(carpeta, "brightness")
        self.maximo = 65535
        try:
            with open(os.path.join(carpeta, "max_brightness")) as f:
                self.maximo = int(f.read().strip()) or 65535
        except Exception:
            pass
        self.ok = os.access(self.archivo, os.W_OK)

    def leer_pct(self):
        try:
            with open(self.archivo) as f:
                return round(int(f.read().strip()) * 100 / self.maximo)
        except Exception:
            return None

    def escribir_pct(self, pct):
        if not self.ok:
            return
        # No escribir si ya estamos en ese porcentaje. Parece de mas, pero
        # evita un efecto real: la barra trabaja en enteros de 1%, asi que
        # sincronizarla contra el sistema y devolver ese valor redondeado
        # CAMBIA el brillo unas decenas de unidades (medido: 37339 volvia
        # como 37354, que es exactamente 65535*57/100). Con esto, sincronizar
        # nunca escribe: solo escribe un movimiento real del usuario.
        if self.leer_pct() == pct:
            return
        crudo = max(1, int(self.maximo * pct / 100))
        try:
            with open(self.archivo, "w") as f:
                f.write(str(crudo))
        except Exception:
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid", type=int, default=0,
                    help="PID del cliente de input, para cerrarse si se muere")
    ap.add_argument("--host", default="")
    ap.add_argument("--port", default="")
    ap.add_argument("--backlight", default="/sys/class/backlight/amdgpu_bl0")
    args = ap.parse_args()

    import tkinter as tk
    from tkinter import font as tkfont

    brillo = Brillo(args.backlight)

    root = tk.Tk()
    root.title("Remote Play - Control")
    root.configure(bg=FONDO)
    try:
        root.attributes("-fullscreen", True)
    except Exception:
        root.geometry("900x600")

    f_titulo = tkfont.Font(family="DejaVu Sans", size=28, weight="bold")
    f_sub = tkfont.Font(family="DejaVu Sans", size=13)
    f_chico = tkfont.Font(family="DejaVu Sans", size=11)
    f_boton = tkfont.Font(family="DejaVu Sans", size=16, weight="bold")

    tk.Frame(root, bg=FONDO, height=60).pack()
    tk.Label(root, text="MODO CONTROL ACTIVO", font=f_titulo,
             bg=FONDO, fg=VERDE).pack(pady=(0, 14))
    tk.Label(root,
             text="La Steam Deck esta funcionando solo como mando.\n"
                  "Mira la consola en la tele.",
             font=f_sub, bg=FONDO, fg=TEXTO, justify="center").pack(pady=(0, 8))

    destino = ""
    if args.host:
        destino = f"Mandando al ESP32 en {args.host}"
        if args.port:
            destino += f":{args.port}"
    tk.Label(root, text=destino, font=f_chico, bg=FONDO, fg=TENUE).pack()

    # ------------------------------------------------------------
    #  Barra de brillo
    # ------------------------------------------------------------
    caja = tk.Frame(root, bg=FONDO)
    caja.pack(pady=(34, 0))

    etiqueta = tk.Label(caja, text="Brillo de la pantalla", font=f_chico,
                        bg=FONDO, fg=TENUE)
    etiqueta.pack(pady=(0, 6))

    # Bandera para que sincronizar() no se cuente como toque del usuario: sin
    # esto, cada sincronizacion reiniciaria el temporizador y la barra nunca
    # volveria a seguir al sistema.
    sincronizando = [False]
    ultimo_toque = [0.0]

    def al_mover(valor):
        if sincronizando[0]:
            return
        ultimo_toque[0] = time.time()
        brillo.escribir_pct(int(float(valor)))

    escala = tk.Scale(caja, from_=PCT_MIN, to=100, orient="horizontal",
                      command=al_mover,
                      length=560, width=34, sliderlength=70,
                      showvalue=True, resolution=1,
                      font=f_chico,
                      bg=FONDO, fg=TEXTO, troughcolor="#2a2a30",
                      activebackground="#5a5a66", highlightthickness=0,
                      bd=0, relief="flat")
    escala.pack()

    if not brillo.ok:
        etiqueta.configure(text="Brillo (no se puede escribir el backlight)")
        escala.configure(state="disabled")
    else:
        actual = brillo.leer_pct()
        if actual is not None:
            sincronizando[0] = True
            escala.set(max(PCT_MIN, actual))
            sincronizando[0] = False

    tk.Label(root,
             text="La pantalla se atenua sola a los pocos segundos; es a proposito,\n"
                  "para ahorrar bateria. Subela aqui si la necesitas.",
             font=f_chico, bg=FONDO, fg=TENUE, justify="center").pack(pady=(18, 0))

    estado = tk.Label(root, text="", font=f_chico, bg=FONDO, fg=TENUE)
    estado.pack(pady=(14, 0))

    tk.Button(root, text="Salir", font=f_boton,
              bg="#3a3a42", fg="#ffffff",
              activebackground="#4a4a55", activeforeground="#ffffff",
              width=12, height=2, relief="flat", bd=0,
              command=root.destroy).pack(pady=(26, 0))

    # ------------------------------------------------------------
    #  Indicador de boton pulsado (abajo de todo, centrado)
    # ------------------------------------------------------------
    # Sirve para ver de un vistazo que esta llegando del mando: si el PS3 no
    # responde, esto dice enseguida si el problema esta antes (la Deck no lee
    # el boton) o despues (lo lee y no llega al PS3).
    #
    # Se pulsa el mismo umbral de gatillo que usa input_client_v3.py, asi que
    # lo que se ve aca es lo que se le manda al ESP32.
    f_pulsado = tkfont.Font(family="DejaVu Sans", size=22, weight="bold")

    # El texto va SIEMPRE en el mismo lugar y la etiqueta no cambia de tamano
    # al vaciarse, para que la pantalla no salte cada vez que se suelta un
    # boton. Por eso height fijo y no un pack/forget.
    pulsado = tk.Label(root, text="", font=f_pulsado, bg=FONDO, fg=TEXTO,
                       height=2)
    pulsado.pack(side="bottom", pady=(0, 14))

    tk.Label(root,
             text="\"Salir\" te devuelve al selector de modo, no cierra la aplicacion.",
             font=f_chico, bg=FONDO, fg=TENUE).pack(side="bottom")

    mando = Mando() if Mando is not None else None
    ultimo = [""]

    def mirar_botones():
        if mando is not None and mando.ok:
            texto = etiquetar(mando.pulsados())
            # Solo tocar el widget cuando de verdad cambio: a 20 veces por
            # segundo, reescribirlo siempre es trabajo de dibujo regalado.
            if texto != ultimo[0]:
                pulsado.configure(text=texto)
                ultimo[0] = texto
        root.after(50, mirar_botones)

    root.after(50, mirar_botones)

    root.bind("<Escape>", lambda e: root.destroy())

    def vigilar():
        if not vivo(args.pid):
            # Si el cliente de input se murio, esta ventana ya no representa
            # nada: cerrarla devuelve al selector y restaura el brillo, que es
            # la señal visible de que algo paso.
            estado.configure(text="El cliente de input se detuvo. Volviendo al menu...",
                             fg="#c86464")
            root.after(1200, root.destroy)
            return

        # Seguir al sistema mientras el usuario no este tocando la barra. Esto
        # es lo que hace que la barra se mueva sola cuando el .sh atenua la
        # pantalla a los 2 segundos, en vez de quedar desfasada.
        if brillo.ok and (time.time() - ultimo_toque[0]) > 3:
            actual = brillo.leer_pct()
            if actual is not None and abs(actual - escala.get()) >= 1:
                sincronizando[0] = True
                escala.set(max(PCT_MIN, actual))
                sincronizando[0] = False

        root.after(1000, vigilar)

    root.after(1000, vigilar)
    root.mainloop()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"ventana de control no disponible: {e}", file=sys.stderr)
        sys.exit(2)
