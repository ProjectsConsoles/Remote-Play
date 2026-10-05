"""Apps externas de la Ally (2026-10-04, porteo de deck-client/client_apps.py y del bloque
correr_app_externa de start_client_stream.sh).

Programas de terceros que se eligen como una consola mas en "¿Qué consola?" (Streaming) y, al
cerrarlos, regresan al menu. Traen su propio video, audio y control: no usan el servidor ni el
ESP32-S3.

    chiaki-ng   Remote Play de Sony para PS4/PS5. Version PORTATIL de Windows (zip oficial
                chiaki-ng-win_x64-MSYS2-Release-portable), en apps\\chiaki-ng-Win\\chiaki.exe junto
                al .exe. En Windows guarda su config en el REGISTRO (HKCU\\Software\\Chiaki\\Chiaki),
                no en archivo: las consolas de la Deck se pasan con Settings -> Import settings de
                chiaki-ng, que lee el mismo .ini que el Chiaki.conf de la Deck (ver README_ALLY.md).
    xbPlay      Remote Play de Xbox (Studio08, de pago, comprado en Steam: la misma compra trae la
                version de Windows). Nunca se baja ni va en el repo: se usa el instalado.

Mientras una app esta abierta ESTE proceso solo espera: no lee el mando ni manda nada al ESP32, y
el mutex de instancia unica impide que haya otro cliente nuestro mandando (en la Deck habia que
vigilar otras instancias; aqui no hace falta).
"""

import glob
import logging
import os
import re
import subprocess
import sys

log = logging.getLogger("ps3rp")

AZUL_PS = (0, 112, 209)      # #0070d1, azul de PlayStation (logo: iconos/ps_*.png)
VERDE_XBOX = (16, 124, 16)   # #107c10, verde de Xbox (logo: iconos/xbox_*.png)
XBPLAY_APPID = "2693120"


def _app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _ejecutable(ruta):
    return bool(ruta) and os.path.isfile(ruta)


def buscar_chiaki():
    """chiaki.exe, o None. Orden: PS3RP_CHIAKI_EXE, apps\\chiaki-ng-Win (como sale del zip
    portatil), apps\\chiaki-ng, y la instalacion normal en Program Files."""
    base = os.path.join(_app_dir(), "apps")
    for c in (os.environ.get("PS3RP_CHIAKI_EXE"),
              os.path.join(base, "chiaki-ng-Win", "chiaki.exe"),
              os.path.join(base, "chiaki-ng", "chiaki.exe"),
              os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "chiaki-ng", "chiaki.exe")):
        if _ejecutable(c):
            return c
    return None


def _bibliotecas_steam():
    """Carpetas de bibliotecas de Steam: la de la instalacion (registro de Windows o la ruta de
    siempre) y las de libraryfolders.vdf (otro disco, microSD)."""
    raices = []
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
            raices.append(os.path.normpath(winreg.QueryValueEx(k, "SteamPath")[0]))
    except Exception:
        pass
    raices.append(r"C:\Program Files (x86)\Steam")
    libs = []
    for raiz in raices:
        if raiz not in libs:
            libs.append(raiz)
        try:
            with open(os.path.join(raiz, "steamapps", "libraryfolders.vdf"), encoding="utf-8", errors="replace") as f:
                for ruta in re.findall(r'^\s*"path"\s*"(.*)"', f.read(), re.M):
                    ruta = os.path.normpath(ruta.replace("\\\\", "\\"))
                    if ruta not in libs:
                        libs.append(ruta)
        except OSError:
            pass
    return libs


def buscar_xbplay():
    """Ejecutable de xbPlay, o None. Orden: PS3RP_XBPLAY, y la version de Steam en cualquier
    biblioteca (steamapps\\common\\Studio08, el .exe con "xbplay" en el nombre; se busca por patron
    porque la carpeta de Windows no se pudo ver antes de instalarlo)."""
    if _ejecutable(os.environ.get("PS3RP_XBPLAY")):
        return os.environ["PS3RP_XBPLAY"]
    for lib in _bibliotecas_steam():
        base = os.path.join(lib, "steamapps", "common", "Studio08")
        if not os.path.isdir(base):
            continue
        for patron in ("*.exe", "*/*.exe", "*/*/*.exe", "*/*/*/*.exe"):
            for exe in sorted(glob.glob(os.path.join(base, patron))):
                nombre = os.path.basename(exe).lower()
                if "xbplay" in nombre and "uninst" not in nombre and "crash" not in nombre:
                    return exe
    return None


def consolas_chiaki():
    """Consolas registradas en chiaki-ng (registro de Windows, formato de QSettings). Solo
    informativo: si no se puede leer, lista vacia."""
    nombres = []
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Chiaki\Chiaki\registered_hosts") as k:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(k, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(k, sub) as h:
                        nombres.append(str(winreg.QueryValueEx(h, "server_nickname")[0]))
                except OSError:
                    pass
    except Exception:
        pass
    return nombres


def estado_chiaki(ui):
    """(instalado, color, texto para la tira)."""
    if not buscar_chiaki():
        return False, ui.AVISO, ("chiaki-ng no está instalado: falta apps\\chiaki-ng-Win\\chiaki.exe "
                                 "junto al programa (ver README_ALLY).")
    consolas = consolas_chiaki()
    if consolas:
        return True, ui.OK, "chiaki-ng listo. Consolas registradas: " + ", ".join(consolas)
    return True, ui.TENUE, ("chiaki-ng listo. Sin consolas: regístralas con el PIN o importa las de "
                            "la Deck (Settings -> Import settings).")


def estado_xbplay(ui):
    """(instalado, color, texto para la tira)."""
    ruta = buscar_xbplay()
    if ruta:
        return True, ui.OK, "xbPlay listo (" + os.path.basename(ruta) + ")."
    return False, ui.AVISO, "xbPlay no está instalado: instálalo desde Steam (es de pago)."


def correr(clave):
    """Lanza la app ("chiaki" o "xbplay") y espera a que se cierre. Devuelve (ok, mensaje)."""
    if clave == "chiaki":
        nombre, exe, env = "chiaki-ng", buscar_chiaki(), dict(os.environ)
    else:
        nombre, exe, env = "xbPlay", buscar_xbplay(), dict(os.environ)
        # xbPlay valida la compra con steamworks y no trae steam_appid.txt; si se abriera desde un
        # acceso directo de Steam heredaria el SteamAppId de ese acceso. Con el suyo, SteamAPI_Init
        # carga bien sin que Steam lo relance (probado en la Deck, 2026-10-04).
        env["SteamAppId"] = env["SteamGameId"] = XBPLAY_APPID
    if not exe:
        return False, f"{nombre} no está instalado."
    log.info("--- app externa: %s (%s) ---", nombre, exe)
    try:
        proc = subprocess.Popen([exe], cwd=os.path.dirname(exe), env=env)
        codigo = proc.wait()
        log.info("%s termino (codigo %s).", nombre, codigo)
        return True, ""
    except Exception as e:
        log.error("No se pudo abrir %s: %s", nombre, e)
        return False, f"No se pudo abrir {nombre}: {e}"
