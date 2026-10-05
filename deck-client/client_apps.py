#!/usr/bin/env python3
"""Apps externas (2026-10-04): programas de terceros que se lanzan desde nuestro menu y, al
cerrarlos, regresan a el. No son parte del streaming propio del proyecto (capturadora + ESP32):
cada app trae su propio video, audio y control. Desde 2026-10-04 se eligen como una consola mas
en la pantalla de Streaming (client_consolas.py); aqui solo vive como encontrarlas y su estado.

    chiaki-ng   (antes "chiaki4deck") Remote Play oficial de Sony para PS4 y PS5. Se usa el
                AppImage, no el Flatpak, para que viva junto al proyecto y no dependa de Flathub.
                Ruta: PS3RP_CHIAKI_APPIMAGE, o apps/chiaki-ng.AppImage junto a este archivo.
    xbPlay      Remote Play de Xbox (Studio08, de pago, comprado en Steam). Nunca se baja ni va
                en el repo: se usa el instalado (ver buscar_xbplay).

Lanzarlas NO pasa por aqui: el menu termina imprimiendo "chiaki" o "xbplay" y start_client_stream.sh la
corre y espera a que se cierre, igual que el modo control (asi el tkinter del menu no queda
vivo debajo peleandose el mando con la app).
"""

import os
import re
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


def estado_chiaki():
    """(instalado, color, texto para la tira de estado)."""
    if not os.access(CHIAKI_APPIMAGE, os.X_OK):
        return False, ui.AVISO, ("chiaki-ng no está instalado: falta el AppImage en "
                                 + CHIAKI_APPIMAGE + " (ver README).")
    consolas = consolas_chiaki()
    if consolas:
        return True, ui.OK, "chiaki-ng listo. Consolas registradas: " + ", ".join(consolas)
    return True, ui.TENUE, "chiaki-ng listo. Sin consolas registradas: se registran con el PIN."


def estado_xbplay():
    """(instalado, color, texto para la tira de estado)."""
    ruta = buscar_xbplay()
    if ruta:
        return True, ui.OK, "xbPlay listo (" + os.path.basename(ruta) + ")."
    return False, ui.AVISO, "xbPlay no está instalado: instálalo desde Steam (es de pago)."
