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


def _buscar_icono():
    for c in (os.path.join(CARPETA, "icon_256.png"),
              os.path.join(CARPETA, "..", "deck-client", "remote_play_steam_assets", "icon_256.png")):
        if os.path.isfile(c):
            return c
    return None


_ICONO_PROYECTO = _buscar_icono()


def _leer_progreso():
    """(fps, Mbps) del ULTIMO SEGUNDO segun -progress de ffmpeg, o (None, None). Los fps= y bitrate= que
    escribe ffmpeg son promedios desde que arranco (una caida no se notaria): se calculan con la diferencia
    de cuadros, bytes y tiempo entre los dos ultimos bloques."""
    try:
        with open(os.path.join(CARPETA, "ffmpeg_progreso.log"), "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 1500))
            texto = f.read().decode("latin-1")
    except OSError:
        return None, None
    cuadros = re.findall(r"^frame=(\d+)", texto, re.M)
    tam = re.findall(r"^total_size=(\d+)", texto, re.M)
    t = re.findall(r"^out_time_us=(\d+)", texto, re.M)
    if len(cuadros) < 2 or len(tam) < 2 or len(t) < 2:
        return None, None
    dt = (int(t[-1]) - int(t[-2])) / 1e6
    if dt <= 0:
        return None, None
    return (int(cuadros[-1]) - int(cuadros[-2])) / dt, (int(tam[-1]) - int(tam[-2])) * 8 / dt / 1e6


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
        servidor.VENTANA_COLA = self.cola   # el acceso directo del escritorio pide "mostrar" por UDP
        self._paquetes = (0, time.monotonic())
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)   # texto nitido con la escala de Windows (125 %)
            dpi = ctypes.windll.user32.GetDpiForSystem() / 96
        except Exception:
            dpi = 1.0
        self.root = tk.Tk()
        self.root.title("Remote Play - Servidor de PC")
        if _ICONO_PROYECTO:
            try:
                self._icono_ventana = tk.PhotoImage(file=_ICONO_PROYECTO)   # barra de tareas y titulo
                self.root.iconphoto(True, self._icono_ventana)
            except tk.TclError:
                pass
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
        kw = dict(marco=False, interactivo=False, tam_titulo=24, tam_detalle=14)
        self.t_video = ui.Mosaico(f, esc, iconos, "image", "Video", "", AZUL_PC, **kw)
        self.t_audio = ui.Mosaico(f, esc, iconos, "tune", "Audio", "", ui.MORADO, **kw)
        ui.disponer(f, [self.t_video, self.t_audio], esc)
        f2 = ui.fila(marco, esc)
        self.t_mando = ui.Mosaico(f2, esc, iconos, "gamepad", "Mando", "", ui.VERDE, **kw)
        self.t_tableta = ui.Mosaico(f2, esc, iconos, "wifi", "Tableta", "", ui.NARANJA, **kw)
        ui.disponer(f2, [self.t_mando, self.t_tableta], esc)

        pie = ui.fila(marco, esc, expandir=False)
        bkw = dict(marco=False, tam_titulo=18, tam_detalle=12, tam_icono=40, horizontal=True, alto=esc.px(84))
        self.b_detener = ui.Mosaico(pie, esc, iconos, "power", "Detener transmisión", "La tableta se queda sin video",
                                    ui.ROJO, on_a=self.detener, **bkw)
        b_ocultar = ui.Mosaico(pie, esc, iconos, "back", "Ocultar", "Sigue corriendo junto al reloj",
                               ui.GRIS, on_a=self.ocultar, **bkw)
        b_salir = ui.Mosaico(pie, esc, iconos, "exit", "Salir", "Apaga el servidor", ui.ROJO_OSCURO,
                             on_a=self.salir, **bkw)
        ui.disponer(pie, [self.b_detener, b_ocultar, b_salir], esc)
        for b in (self.b_detener, b_ocultar, b_salir):
            self._con_mouse(b)

        self.icono = self._crear_icono()
        self.root.withdraw()            # arranca oculta: solo el icono junto al reloj
        self.root.after(200, self._tic)

    def _con_mouse(self, b):
        """Los mosaicos se pensaron para el mando de la Deck: aca el mouse los agranda al pasar por encima
        (como la ventana del server del PS3) y cada clic queda en el log."""
        b.bind("<Enter>", lambda e: b.poner_foco(b.habilitado))
        b.bind("<Leave>", lambda e: b.poner_foco(False))
        accion = b.on_a

        def con_log():
            self.sv.log.info("ventana: clic en '%s'", b.titulo)
            accion()
        b.on_a = con_log

    # --- icono junto al reloj (pystray, en su propio hilo) ----------------------------------------
    def _crear_icono(self):
        try:
            import pystray
            from PIL import Image, ImageDraw
        except ImportError:
            self.root.deiconify()      # sin pystray no hay icono: la ventana se muestra
            return None

        # El icono del proyecto (el mismo de Steam/Android) con un punto de estado en la esquina
        base = Image.open(_ICONO_PROYECTO).convert("RGBA").resize((64, 64), Image.LANCZOS) \
            if _ICONO_PROYECTO else None

        def imagen(color):
            im = base.copy() if base else Image.new("RGBA", (64, 64), (20, 28, 40, 255))
            d = ImageDraw.Draw(im)
            d.ellipse((40, 40, 63, 63), fill=color, outline=(15, 20, 30), width=3)
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

        if self.b_detener.habilitado != transmite:   # sin transmision no hay nada que detener: se atenua
            self.b_detener.habilitar(transmite)
            if not transmite:
                self.b_detener.poner_foco(False)
        self._poner(self.t_video, titulo="Video: " + ("transmitiendo" if transmite else "en espera"))
        self._poner(self.t_video, detalle=f"Pantalla en {gpu}. Captura a {self.sv.FPS} fps, "
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
