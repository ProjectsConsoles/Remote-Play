#!/usr/bin/env python3
"""Pantalla "Apps externas" del menu (2026-10-04): programas de terceros que se lanzan desde
nuestro menu y, al cerrarlos, regresan a el. No son parte del streaming propio del proyecto
(PS3 por capturadora + ESP32): cada app trae su propio video, audio y control.

Por ahora una sola:

    chiaki-ng   (antes "chiaki4deck") Remote Play oficial de Sony para PS4 y PS5. Se usa el
                AppImage, no el Flatpak, para que viva junto al proyecto y no dependa de Flathub.
                Ruta: PS3RP_CHIAKI_APPIMAGE, o apps/chiaki-ng.AppImage junto a este archivo.

Lanzarla NO pasa por aqui: el menu termina imprimiendo "chiaki" y start_client_stream.sh la
corre y espera a que se cierre, igual que el modo control (asi el tkinter del menu no queda
vivo debajo peleandose el mando con la app). Esta pantalla solo la ofrece y dice si esta lista.
"""

import os
import re
import tkinter as tk

import ui_mosaicos as ui

CARPETA = os.path.dirname(os.path.abspath(__file__))
AZUL_PS = "#0070d1"   # azul de PlayStation, para el mosaico de chiaki-ng (con el logo PS: iconos/ps_*.png)
CHIAKI_APPIMAGE = os.environ.get("PS3RP_CHIAKI_APPIMAGE") or os.path.join(CARPETA, "apps", "chiaki-ng.AppImage")
# El AppImage guarda su config en ~/.config/Chiaki; el Flatpak, dentro de su sandbox. Si solo
# existe la del Flatpak, start_client_stream.sh la copia antes de lanzar (consolas ya registradas).
CHIAKI_CONF = os.path.expanduser("~/.config/Chiaki/Chiaki.conf")
CHIAKI_CONF_FLATPAK = os.path.expanduser(
    "~/.var/app/io.github.streetpea.Chiaki4deck/config/Chiaki/Chiaki.conf")


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
    """Apps externas: un mosaico por app y Volver."""

    def __init__(self, app):
        super().__init__(app)
        esc, iconos = app.esc, app.iconos
        marco = tk.Frame(self.frame, bg=ui.FONDO, padx=esc.px(24), pady=esc.px(16))
        marco.pack(fill="both", expand=True)
        cab, _ = ui.cabecera(marco, esc, "Apps externas")
        cab.pack(fill="x")
        self.tira = ui.TiraEstado(marco, esc)
        self.tira.pack(fill="x", pady=(esc.px(6), esc.px(4)))

        self.chiaki_ok = os.access(CHIAKI_APPIMAGE, os.X_OK)
        consolas = consolas_chiaki()
        if not self.chiaki_ok:
            self.tira.pintar(ui.AVISO, f"No encuentro chiaki-ng en {CHIAKI_APPIMAGE} (o no es ejecutable).")
        elif consolas:
            self.tira.pintar(ui.OK, "chiaki-ng listo. Consolas registradas: " + ", ".join(consolas))
        else:
            self.tira.pintar(ui.TENUE, "chiaki-ng listo. Sin consolas registradas: se registran con el PIN.")

        f = ui.fila(marco, esc)
        t_chiaki = ui.Mosaico(f, esc, iconos, "ps", "PS4 / PS5",
                              "chiaki-ng: Remote Play de Sony. Al cerrarlo regresas a este menu.",
                              AZUL_PS, on_a=self.abrir_chiaki, tam_titulo=32, tam_detalle=16)
        ui.disponer(f, [t_chiaki], esc)
        tk.Label(marco, text="Estas apps traen su propio video, audio y control: no usan el servidor "
                             "Windows ni el ESP32-S3.",
                 font=esc.fuente(14), bg=ui.FONDO, fg=ui.TENUE, justify="left",
                 wraplength=esc.px(1180)).pack(anchor="w", pady=(esc.px(6), esc.px(4)))
        pie = ui.fila(marco, esc, expandir=False)
        volver = ui.Mosaico(pie, esc, iconos, "back", "Volver", "B o Escape", ui.GRIS, on_a=app.volver,
                            tam_titulo=22, tam_detalle=13, tam_icono=40, horizontal=True, alto=esc.px(84))
        ui.disponer(pie, [volver], esc)
        self.nav = ui.Navegador([[t_chiaki], [volver]])

    def abrir_chiaki(self):
        if not self.chiaki_ok:
            self.tira.pintar(ui.ERROR, "No se puede abrir: falta el AppImage de chiaki-ng (ver README).")
            return
        self.app.terminar("chiaki")

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
