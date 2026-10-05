#!/usr/bin/env python3
"""Pantalla "Apps externas" del menu (2026-10-04): programas de terceros que se lanzan desde
nuestro menu y, al cerrarlos, regresan a el. No son parte del streaming propio del proyecto
(PS3 por capturadora + ESP32): cada app trae su propio video, audio y control.

    chiaki-ng   (antes "chiaki4deck") Remote Play oficial de Sony para PS4 y PS5. Se usa el
                AppImage, no el Flatpak, para que viva junto al proyecto y no dependa de Flathub.
                Ruta: PS3RP_CHIAKI_APPIMAGE, o apps/chiaki-ng.AppImage junto a este archivo.
    xbPlay      Remote Play de Xbox (Studio08, de pago, comprado en Steam). Nunca se baja ni va
                en el repo: se usa el instalado (ver buscar_xbplay).

Lanzarlas NO pasa por aqui: el menu termina imprimiendo "chiaki" o "xbplay" y start_client_stream.sh la
corre y espera a que se cierre, igual que el modo control (asi el tkinter del menu no queda
vivo debajo peleandose el mando con la app). Esta pantalla solo la ofrece y dice si esta lista.
"""

import os
import re
import tkinter as tk

import ui_mosaicos as ui

CARPETA = os.path.dirname(os.path.abspath(__file__))
AZUL_PS = "#0070d1"   # azul de PlayStation, para el mosaico de chiaki-ng (con el logo PS: iconos/ps_*.png)
VERDE_XBOX = "#107c10"   # verde de Xbox, para el mosaico de xbPlay (logo: iconos/xbox_*.png)
CHIAKI_APPIMAGE = os.environ.get("PS3RP_CHIAKI_APPIMAGE") or os.path.join(CARPETA, "apps", "chiaki-ng.AppImage")
# El AppImage guarda su config en ~/.config/Chiaki; el Flatpak, dentro de su sandbox. Si solo
# existe la del Flatpak, start_client_stream.sh la copia antes de lanzar (consolas ya registradas).
CHIAKI_CONF = os.path.expanduser("~/.config/Chiaki/Chiaki.conf")
CHIAKI_CONF_FLATPAK = os.path.expanduser(
    "~/.var/app/io.github.streetpea.Chiaki4deck/config/Chiaki/Chiaki.conf")


def buscar_xbplay():
    """Ruta del ejecutable de xbPlay, o None. Mismo orden que buscar_xbplay() de
    start_client_stream.sh (mantener las dos iguales): PS3RP_XBPLAY, apps/xbplay.AppImage,
    Studio08/linux/xbplay/net.studio08.xbplay en cada biblioteca de Steam, y un AppImage con
    "xbplay" en el nombre en Descargas / Applications / Escritorio."""
    candidatos = [os.environ.get("PS3RP_XBPLAY"), os.path.join(CARPETA, "apps", "xbplay.AppImage")]
    steam = os.path.expanduser("~/.local/share/Steam")
    libs = [steam]
    try:
        with open(os.path.join(steam, "steamapps", "libraryfolders.vdf"), encoding="utf-8", errors="replace") as f:
            libs += re.findall(r'^\s*"path"\s*"(.*)"', f.read(), re.M)
    except OSError:
        pass
    candidatos += [os.path.join(lib, "steamapps", "common", "Studio08", "linux", "xbplay",
                                "net.studio08.xbplay") for lib in libs]
    for c in candidatos:
        if c and os.access(c, os.X_OK):
            return c
    encontrados = []
    for carpeta in ("~/Downloads", "~/Applications", "~/Desktop"):
        base = os.path.expanduser(carpeta)
        for raiz, dirs, archivos in os.walk(base):
            if raiz.count(os.sep) - base.count(os.sep) >= 1:
                dirs[:] = []   # como find -maxdepth 2
            for a in archivos:
                ruta = os.path.join(raiz, a)
                if "xbplay" in a.lower() and a.lower().endswith(".appimage") and os.access(ruta, os.X_OK):
                    encontrados.append(ruta)
    return sorted(encontrados)[0] if encontrados else None


def consolas_chiaki():
    """Nombres de las consolas ya registradas (PS4-xxx, PS5-xxx), leidos del .conf de Qt.
    Solo informativo: si no se puede leer, lista vacia."""
    for ruta in (CHIAKI_CONF, CHIAKI_CONF_FLATPAK):
        try:
            with open(ruta, encoding="utf-8", errors="replace") as f:
                texto = f.read()
        except OSError:
            continue
        nombres = re.findall(r"^\d+\\server_nickname=(.+)$", texto, re.M)
        return [n.strip() for n in nombres]
    return []


class PantallaApps(ui.Pantalla):
    """Apps externas: un mosaico por app y Volver. La tira de arriba dice el estado de la app con
    el foco."""

    def __init__(self, app):
        super().__init__(app)
        esc, iconos = app.esc, app.iconos
        marco = tk.Frame(self.frame, bg=ui.FONDO, padx=esc.px(24), pady=esc.px(16))
        marco.pack(fill="both", expand=True)
        cab, _ = ui.cabecera(marco, esc, "Apps externas")
        cab.pack(fill="x")
        self.tira = ui.TiraEstado(marco, esc)
        self.tira.pack(fill="x", pady=(esc.px(6), esc.px(4)))

        # Falta alguna app (2026-10-04, pedido del usuario): que lo diga clarito. El mosaico se ve
        # apagado con "No está instalado" (pero sigue respondiendo a A, que lo repite en la tira en vez
        # de no hacer nada), y la tira de arriba lo dice al poner el foco.
        self.chiaki_ok = os.access(CHIAKI_APPIMAGE, os.X_OK)
        consolas = consolas_chiaki()
        if not self.chiaki_ok:
            self.estado_chiaki = (ui.AVISO, "chiaki-ng no está instalado: falta el AppImage en "
                                            + CHIAKI_APPIMAGE + " (ver README).")
        elif consolas:
            self.estado_chiaki = (ui.OK, "chiaki-ng listo. Consolas registradas: " + ", ".join(consolas))
        else:
            self.estado_chiaki = (ui.TENUE, "chiaki-ng listo. Sin consolas registradas: se registran con el PIN.")
        self.xbplay = buscar_xbplay()
        if self.xbplay:
            self.estado_xbplay = (ui.OK, "xbPlay listo (" + os.path.basename(self.xbplay) + ").")
        else:
            self.estado_xbplay = (ui.AVISO, "xbPlay no está instalado: instalalo desde Steam (es de pago).")

        f = ui.fila(marco, esc)
        t_chiaki = ui.Mosaico(f, esc, iconos, "ps", "PS4 / PS5",
                              "chiaki-ng: Remote Play de Sony. Al cerrarlo regresas a este menu."
                              if self.chiaki_ok else "No está instalado (falta el AppImage de chiaki-ng).",
                              AZUL_PS if self.chiaki_ok else ui.mezclar(AZUL_PS, ui.FONDO, 0.6),
                              on_a=self.abrir_chiaki, tam_titulo=32, tam_detalle=16)
        t_xbplay = ui.Mosaico(f, esc, iconos, "xbox", "Xbox One / Series",
                              "xbPlay: Remote Play de Xbox. Al cerrarlo regresas a este menu."
                              if self.xbplay else "No está instalado (xbPlay se instala desde Steam).",
                              VERDE_XBOX if self.xbplay else ui.mezclar(VERDE_XBOX, ui.FONDO, 0.6),
                              on_a=self.abrir_xbplay, tam_titulo=32, tam_detalle=16)
        self.t_chiaki, self.t_xbplay = t_chiaki, t_xbplay
        ui.disponer(f, [t_chiaki, t_xbplay], esc)
        tk.Label(marco, text="Estas apps traen su propio video, audio y control: no usan el servidor "
                             "Windows ni el ESP32-S3.",
                 font=esc.fuente(14), bg=ui.FONDO, fg=ui.TENUE, justify="left",
                 wraplength=esc.px(1180)).pack(anchor="w", pady=(esc.px(6), esc.px(4)))
        pie = ui.fila(marco, esc, expandir=False)
        volver = ui.Mosaico(pie, esc, iconos, "back", "Volver", "B o Escape", ui.GRIS, on_a=app.volver,
                            tam_titulo=22, tam_detalle=13, tam_icono=40, horizontal=True, alto=esc.px(84))
        ui.disponer(pie, [volver], esc)
        self.nav = ui.Navegador([[t_chiaki, t_xbplay], [volver]], al_cambiar=self._foco)

    def _foco(self, mosaico):
        if mosaico is self.t_xbplay:
            self.tira.pintar(*self.estado_xbplay)
        else:
            self.tira.pintar(*self.estado_chiaki)

    def abrir_chiaki(self):
        if not self.chiaki_ok:
            self.tira.pintar(ui.ERROR, "No se puede abrir: chiaki-ng no está instalado (falta el AppImage, ver README).")
            return
        self.app.terminar("chiaki")

    def abrir_xbplay(self):
        if not buscar_xbplay():   # se busca otra vez: pudo instalarse con el menu abierto
            self.tira.pintar(ui.ERROR, "No se puede abrir: xbPlay no está instalado (Steam).")
            return
        self.app.terminar("xbplay")

    def tecla(self, nombre):
        if nombre == "DPAD_LEFT":
            self.nav.mover(-1, 0)
        elif nombre == "DPAD_RIGHT":
            self.nav.mover(1, 0)
        elif nombre == "DPAD_UP":
            self.nav.mover(0, -1)
        elif nombre == "DPAD_DOWN":
            self.nav.mover(0, 1)
        elif nombre == "A":
            self.nav.activar()
        elif nombre == "B":
            self.app.volver()
