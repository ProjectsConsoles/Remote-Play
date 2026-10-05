#!/usr/bin/env python3
"""Ventana del servidor de PC (2026-10-05): el mismo estilo de mosaicos de la Deck (usa ui_mosaicos.py de
deck-client, que es tkinter puro y el Python de python.org ya trae tkinter) y un icono junto al reloj.

    - Tira de estado: esperando a la tableta / transmitiendo (fps y Mbps reales, del -progress de ffmpeg).
    - Tarjetas: Video (GPU de la pantalla, camino de captura), Audio (donde suena), Mando (control de Xbox
      virtual y paquetes por segundo), Tableta (a quien se transmite).
    - Botones: Detener transmision, Ocultar (queda el icono junto al reloj) y Salir (detiene todo y cierra).

Al iniciar sesion arranca OCULTA (solo el icono, gris esperando / verde transmitiendo): asi no sale una ventana
cada vez que se prende la laptop. Clic en el icono -> Mostrar.

pc_server.py la arranca en el hilo principal; el servidor corre en hilos aparte. Lo que llega del icono (otro
hilo) pasa por una cola que la ventana revisa, porque tkinter no se debe tocar desde otros hilos.
"""

import ctypes
import os
import queue
import re
import sys
import threading
import time
import tkinter as tk

CARPETA = os.path.dirname(os.path.abspath(__file__))
# En el repo, ui_mosaicos.py vive en deck-client; en la laptop se copia junto a este archivo.
for _p in (CARPETA, os.path.join(CARPETA, "..", "deck-client")):
    if os.path.isfile(os.path.join(_p, "ui_mosaicos.py")):
        sys.path.insert(0, os.path.abspath(_p))
        break
import ui_mosaicos as ui  # noqa: E402

ui.FAMILIA = "Segoe UI"   # en Windows no esta DejaVu Sans

VERDE = "#2fa84f"
AZUL_PC = "#2d6cdf"


def _leer_progreso():
    """(fps, Mbps) del ultimo bloque de -progress de ffmpeg, o (None, None)."""
    try:
        with open(os.path.join(CARPETA, "ffmpeg_progreso.log"), "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 1500))
            texto = f.read().decode("latin-1")
    except OSError:
        return None, None
    fps = re.findall(r"^fps=([\d.]+)", texto, re.M)
    br = re.findall(r"^bitrate=\s*([\d.]+)kbits/s", texto, re.M)
    return (float(fps[-1]) if fps else None), (float(br[-1]) / 1000 if br else None)


def _ip_local():
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("192.168.0.1", 9))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "?"


class Ventana:
    def __init__(self, servidor):
        """`servidor`: el modulo pc_server (transmision, mando, gpu_de_la_pantalla, SALIDA_VIRTUAL...)."""
        self.sv = servidor
        self.cola = queue.Queue()
        self._paquetes = (0, time.monotonic())
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)   # texto nitido con la escala de Windows (125 %)
            dpi = ctypes.windll.user32.GetDpiForSystem() / 96
        except Exception:
            dpi = 1.0
        self.root = tk.Tk()
        self.root.title("Remote Play - Servidor de PC")
        self.root.configure(bg=ui.FONDO)
        ancho, alto = round(1000 * dpi), round(640 * dpi)
        self.root.geometry(f"{ancho}x{alto}")
        self.root.minsize(round(760 * dpi), round(520 * dpi))
        self.root.protocol("WM_DELETE_WINDOW", self.ocultar)
        esc = ui.Escala(alto * 1.25)   # la escala de ui_mosaicos piensa en la pantalla de la Deck
        iconos = ui.Iconos()

        marco = tk.Frame(self.root, bg=ui.FONDO, padx=esc.px(24), pady=esc.px(16))
        marco.pack(fill="both", expand=True)
        cab, self.lbl_der = ui.cabecera(marco, esc, "Servidor de PC", f"IP: {_ip_local()}")
        cab.pack(fill="x")
        self.tira = ui.TiraEstado(marco, esc)
        self.tira.pack(fill="x", pady=(esc.px(6), esc.px(4)))

        f = ui.fila(marco, esc)
        kw = dict(interactivo=False, tam_titulo=24, tam_detalle=14)
        self.t_video = ui.Mosaico(f, esc, iconos, "image", "Video", "", AZUL_PC, **kw)
        self.t_audio = ui.Mosaico(f, esc, iconos, "tune", "Audio", "", ui.MORADO, **kw)
        ui.disponer(f, [self.t_video, self.t_audio], esc)
        f2 = ui.fila(marco, esc)
        self.t_mando = ui.Mosaico(f2, esc, iconos, "gamepad", "Mando", "", ui.VERDE, **kw)
        self.t_tableta = ui.Mosaico(f2, esc, iconos, "wifi", "Tableta", "", ui.NARANJA, **kw)
        ui.disponer(f2, [self.t_mando, self.t_tableta], esc)

        pie = ui.fila(marco, esc, expandir=False)
        bkw = dict(tam_titulo=18, tam_detalle=12, tam_icono=40, horizontal=True, alto=esc.px(84))
        self.b_detener = ui.Mosaico(pie, esc, iconos, "power", "Detener transmisión", "La tableta se queda sin video",
                                    ui.ROJO, on_a=self.detener, **bkw)
        b_ocultar = ui.Mosaico(pie, esc, iconos, "back", "Ocultar", "Sigue corriendo junto al reloj",
                               ui.GRIS, on_a=self.ocultar, **bkw)
        b_salir = ui.Mosaico(pie, esc, iconos, "exit", "Salir", "Apaga el servidor", ui.ROJO_OSCURO,
                             on_a=self.salir, **bkw)
        ui.disponer(pie, [self.b_detener, b_ocultar, b_salir], esc)

        self.icono = self._crear_icono()
        self.root.withdraw()            # arranca oculta: solo el icono junto al reloj
        self.root.after(200, self._tic)

    # --- icono junto al reloj (pystray, en su propio hilo) ----------------------------------------
    def _crear_icono(self):
        try:
            import pystray
            from PIL import Image, ImageDraw
        except ImportError:
            self.root.deiconify()      # sin pystray no hay icono: la ventana se muestra
            return None

        def imagen(color):
            im = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
            d = ImageDraw.Draw(im)
            d.rounded_rectangle((2, 8, 62, 46), radius=8, fill=color)
            d.rectangle((24, 46, 40, 54), fill=color)
            d.rounded_rectangle((14, 54, 50, 60), radius=3, fill=color)
            return im

        self._img = {"espera": imagen((147, 161, 176)), "transmite": imagen((61, 220, 132))}
        menu = pystray.Menu(
            pystray.MenuItem("Mostrar", lambda: self.cola.put("mostrar"), default=True),
            pystray.MenuItem("Detener transmisión", lambda: self.cola.put("detener")),
            pystray.MenuItem("Salir", lambda: self.cola.put("salir")),
        )
        icono = pystray.Icon("ps3rp_pc", self._img["espera"], "Remote Play - Servidor de PC", menu)
        icono.run_detached()
        return icono

    # --- acciones ----------------------------------------------------------------------------------
    def mostrar(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def ocultar(self):
        if self.icono is None:
            self.root.iconify()
        else:
            self.root.withdraw()

    def detener(self):
        threading.Thread(target=self.sv.TRANSMISION.detener, daemon=True).start()

    def salir(self):
        self.tira.pintar(ui.AVISO, "Cerrando: deteniendo la transmisión y regresando el audio...")
        self.root.update_idletasks()
        try:
            self.sv.TRANSMISION.detener()
        finally:
            if self.icono is not None:
                self.icono.stop()
            os._exit(0)

    # --- refresco cada segundo -------------------------------------------------------------------
    def _tic(self):
        while not self.cola.empty():
            orden = self.cola.get_nowait()
            {"mostrar": self.mostrar, "detener": self.detener, "salir": self.salir}[orden]()
        try:
            self._pintar()
        except Exception:
            pass
        self.root.after(1000, self._tic)

    @staticmethod
    def _poner(tarjeta, titulo=None, detalle=None):
        """Solo repinta la tarjeta si el texto cambio (repintar cada segundo se ve como parpadeo)."""
        if titulo is not None and titulo != tarjeta.titulo:
            tarjeta.poner_titulo(titulo)
        if detalle is not None and detalle != tarjeta.detalle:
            tarjeta.poner_detalle(detalle)

    def _pintar(self):
        t, m = self.sv.TRANSMISION, self.sv.MANDO
        transmite = t.corriendo()
        gpu = self.sv.gpu_de_la_pantalla() or "?"
        ahora = time.monotonic()
        n0, t0 = self._paquetes
        por_s = (m.paquetes - n0) / max(0.5, ahora - t0)
        self._paquetes = (m.paquetes, ahora)

        if transmite:
            fps, mbps = _leer_progreso()
            extra = " · ".join(x for x in (f"{fps:.0f} fps" if fps else "", f"{mbps:.1f} Mbps" if mbps else "") if x)
            self.tira.pintar(ui.OK, f"Transmitiendo a {t.destino}" + (f" · {extra}" if extra else ""))
        else:
            self.tira.pintar(ui.TENUE, "Esperando a la tableta: en la app, Streaming → PC (juegos de Windows).")

        self._poner(self.t_video, titulo="Video: " + ("transmitiendo" if transmite else "en espera"))
        self._poner(self.t_video, detalle=f"Pantalla en {gpu}. Captura de cuadros nuevos hasta {self.sv.FPS} fps, "
                                   f"{'directo a NVENC' if t.directo else 'copiada a NVENC'}.")
        if transmite and t.salida_previa is not None:
            self._poner(self.t_audio, detalle=f"Suena solo en la tableta (salida: {self.sv.SALIDA_VIRTUAL}).")
        elif transmite:
            self._poner(self.t_audio, detalle="Se transmite el audio de la salida actual de Windows.")
        else:
            self._poner(self.t_audio, detalle="Suena en la laptop. Al transmitir pasa a la tableta.")
        self._poner(self.t_audio, titulo="Audio")
        if m.pad is not None:
            self._poner(self.t_mando, titulo="Mando: " + ("conectado" if por_s > 1 else "listo"))
            self._poner(self.t_mando, detalle=f"Control de Xbox 360 virtual. {por_s:.0f} paquetes/s de la tableta.")
        else:
            self._poner(self.t_mando, titulo="Mando")
            self._poner(self.t_mando, detalle="El control virtual se crea con el primer paquete de la tableta.")
        self._poner(self.t_tableta, titulo=t.destino or "Tableta")
        self._poner(self.t_tableta, detalle="Recibe el video y manda el mando y el tacto." if t.destino
                                     else "Ninguna conectada todavía.")
        if self.icono is not None:
            self.icono.icon = self._img["transmite" if transmite else "espera"]

    def correr(self):
        self.root.mainloop()


def correr(servidor):
    Ventana(servidor).correr()
