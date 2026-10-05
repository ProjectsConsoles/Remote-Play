#!/usr/bin/env python3
"""Lanzador del servidor de Remote Play: "Iniciar Servidor Remote Play.exe".

UN SOLO PAQUETE PARA LOS DOS SERVIDORES (2026-10-05, pedido del usuario):
  - Consolas (capturadora HDMI): start_server_gui.ps1 + config_listener.ps1 (windows-server/).
  - Juegos de esta PC: pc_server.py (windows-pc-server/), para la tableta.
La primera vez pregunta en una ventana cual es esta PC y lo guarda en tipo_servidor.txt (junto al
.exe). Despues arranca ese directo, sin preguntar, en cada arranque de Windows. Para cambiarlo:
el boton "Cambiar tipo de servidor" de la ventana de cada servidor (lanza este .exe con --elegir).

Argumentos:  --elegir  mostrar la ventana de eleccion aunque ya haya uno guardado (o elegir.flag, ver main)
             --inicio  arranque de Windows: el servidor de PC se queda oculto junto al reloj

Donde busca cada servidor (para que sirva con la carpeta vieja de cada PC y con la nueva):
  consolas: junto al .exe o en consolas\\ ;  PC: en pc\\ o junto al .exe.

POR QUE ESTE LANZADOR NO TOCA EL MOTOR (de antes, sigue valiendo): el usuario ya habia pedido una
vez convertir el motor (start_server_stream.ps1/.bat, el que maneja ffmpeg) a .exe con ps2exe, y eso
metio un desfase de audio. Aqui no se reimplementa nada: solo se lanza lo de siempre.
"""

import glob
import json
import os
import shutil
import socket
import subprocess
import sys
import time

TITULO = "Remote Play - Servidor"
CONSOLAS, PC = "consolas", "pc"
CREATE_BREAKAWAY_FROM_JOB = 0x01000000
CREATE_NO_WINDOW = 0x08000000


def app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def mensaje(texto, icono=0x40):
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, texto, TITULO, icono)
    except Exception:
        pass


# --- donde esta cada servidor y que le falta ---------------------------------------------------------
def carpeta_consolas(aqui):
    for d in (aqui, os.path.join(aqui, "consolas")):
        if os.path.isfile(os.path.join(d, "start_server_gui.ps1")):
            return d
    return None


def carpeta_pc(aqui):
    for d in (os.path.join(aqui, "pc"), aqui):
        if os.path.isfile(os.path.join(d, "pc_server.py")):
            return d
    return None


def buscar_pythonw():
    candidatos = [r"C:\Program Files\Python312\pythonw.exe"]
    candidatos += sorted(glob.glob(r"C:\Program Files\Python3*\pythonw.exe"), reverse=True)
    candidatos += sorted(glob.glob(os.path.expandvars(r"%LOCALAPPDATA%\Programs\Python\Python3*\pythonw.exe")),
                         reverse=True)
    for c in candidatos:
        if os.path.isfile(c):
            return c
    return shutil.which("pythonw")


def faltantes_consolas(d):
    if not d:
        return ["los archivos del servidor de consolas"]
    falta = []
    if not glob.glob(os.path.join(d, "ffmpeg-*", "bin", "ffmpeg.exe")):
        falta.append("ffmpeg (carpeta ffmpeg-*-full_build)")
    return falta


def faltantes_pc(d):
    if not d:
        return ["los archivos del servidor de PC"]
    falta = []
    if not buscar_pythonw():
        falta.append("Python 3.12")
    sistema = os.path.expandvars(r"%SystemRoot%\System32")
    if not os.path.isfile(os.path.join(sistema, "drivers", "ViGEmBus.sys")):
        falta.append("ViGEmBus (control virtual)")
    if not os.path.isfile(os.path.join(sistema, "nvEncodeAPI64.dll")):
        falta.append("una tarjeta NVIDIA")
    return falta


# --- tipo guardado ------------------------------------------------------------------------------------
def archivo_tipo(aqui):
    return os.path.join(aqui, "tipo_servidor.txt")


def leer_tipo(aqui):
    try:
        with open(archivo_tipo(aqui)) as f:
            t = f.read().strip().lower()
        return t if t in (CONSOLAS, PC) else None
    except OSError:
        return None


def guardar_tipo(aqui, tipo):
    with open(archivo_tipo(aqui), "w") as f:
        f.write(tipo + "\n")


# --- ventana para elegir --------------------------------------------------------------------------------
CODIGOS = {CONSOLAS: 10, PC: 11}


def elegir(aqui, actual=None):
    """Devuelve CONSOLAS, PC o None (se cerro sin elegir).
    En el .exe la ventana se abre SIEMPRE en un proceso nuevo (este mismo .exe con --solo-elegir, la
    eleccion vuelve como codigo de salida): una segunda ventana de tkinter en el mismo proceso (despues de
    "Cambiar tipo", el lanzador sigue vivo esperando al servidor) reusaba imagenes de la ventana anterior,
    ya destruida, y los mosaicos salian VACIOS ("image pyimage2 doesn't exist", 2026-10-05)."""
    if getattr(sys, "frozen", False):
        args = [sys.executable, "--solo-elegir"] + (["--actual=" + actual] if actual else [])
        try:
            r = subprocess.run(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL).returncode
        except OSError as e:
            log(f"no se pudo abrir la ventana de eleccion en otro proceso ({e}): la abro aqui")
            return elegir_aqui(aqui, actual)
        return {v: k for k, v in CODIGOS.items()}.get(r)
    return elegir_aqui(aqui, actual)


def elegir_aqui(aqui, actual=None):
    """La ventana en este proceso. Usa los mosaicos de la ventana del servidor de PC (ui_mosaicos.py, en la
    carpeta del servidor de PC); si no se puede, un cuadro de Si/No."""
    d_cons, d_pc = carpeta_consolas(aqui), carpeta_pc(aqui)
    f_cons, f_pc = faltantes_consolas(d_cons), faltantes_pc(d_pc)
    try:
        return _elegir_mosaicos(d_pc, f_cons, f_pc, actual, d_cons is not None)
    except Exception:
        import traceback
        log("la ventana de mosaicos fallo, uso el cuadro de Si/No:\n" + traceback.format_exc())
    r = _messagebox_si_no(
        "Que tipo de servidor es esta PC?\n\n"
        f"Si = Consolas (capturadora HDMI){'  - falta: ' + ', '.join(f_cons) if f_cons else ''}\n"
        f"No = Juegos de esta PC (tableta){'  - falta: ' + ', '.join(f_pc) if f_pc else ''}\n\n"
        "Se recuerda para los proximos arranques.")
    return {6: CONSOLAS, 7: PC}.get(r)


def _messagebox_si_no(texto):
    try:
        import ctypes
        return ctypes.windll.user32.MessageBoxW(0, texto, TITULO, 0x3 | 0x20)   # Si/No/Cancelar, pregunta
    except Exception:
        return 2


def _elegir_mosaicos(d_pc, f_cons, f_pc, actual, hay_consolas):
    import ctypes
    import tkinter as tk
    if not d_pc:
        raise RuntimeError("sin ui_mosaicos")
    sys.path.insert(0, d_pc)
    import ui_mosaicos as ui
    # por si acaso: las imagenes guardadas son de la ventana de tkinter que las creo
    for cache in ("_tarjetas_suaves", "_degradados"):
        if isinstance(getattr(ui, cache, None), dict):
            getattr(ui, cache).clear()

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
        dpi = ctypes.windll.user32.GetDpiForSystem() / 96
    except Exception:
        dpi = 1.0
    eleccion = {"tipo": None}
    root = tk.Tk()

    def error_de_tk(tipo, valor, tb):
        # dentro del .exe (sin consola) tkinter se tragaba los errores al pintar: mosaicos vacios sin pista
        import traceback
        log("error en la ventana de eleccion:\n" + "".join(traceback.format_exception(tipo, valor, tb)))
    root.report_callback_exception = error_de_tk
    root.title(TITULO)
    root.configure(bg=ui.FONDO)
    ancho, alto = round(860 * dpi), round(470 * dpi)
    # centrada en la pantalla (pedido 2026-10-05)
    x = max(0, (root.winfo_screenwidth() - ancho) // 2)
    y = max(0, (root.winfo_screenheight() - alto) // 2 - round(30 * dpi))
    root.geometry(f"{ancho}x{alto}+{x}+{y}")
    root.minsize(round(700 * dpi), round(420 * dpi))
    icono = os.path.join(d_pc, "icon_256.png")
    if os.path.isfile(icono):
        try:
            root._icono = tk.PhotoImage(file=icono)
            root.iconphoto(True, root._icono)
        except tk.TclError:
            pass
    esc = ui.Escala(alto * 1.6)
    iconos = ui.Iconos()
    marco = tk.Frame(root, bg=ui.FONDO, padx=esc.px(24), pady=esc.px(16))
    marco.pack(fill="both", expand=True)
    cab, _ = ui.cabecera(marco, esc, "Servidor de Remote Play", "")
    cab.pack(fill="x")
    tira = ui.TiraEstado(marco, esc)
    tira.pack(fill="x", pady=(esc.px(6), esc.px(8)))
    tira.pintar(ui.TENUE, "¿Qué es esta PC? Se recuerda para los próximos arranques; se cambia desde la "
                          "ventana del servidor.")

    def detalle(base, falta):
        return base + ("  ·  Falta: " + ", ".join(falta) if falta else "  ·  Listo")

    def elegir_y_cerrar(tipo):
        eleccion["tipo"] = tipo
        root.destroy()

    f = ui.fila(marco, esc)
    kw = dict(marco=False, tam_titulo=24, tam_detalle=13)
    t_cons = ui.Mosaico(f, esc, iconos, "gamepad", "Consolas",
                        detalle("Capturadora HDMI: PS3, PS2, Xbox... a la Deck, la Ally o la tableta", f_cons),
                        ui.AZUL, on_a=lambda: elegir_y_cerrar(CONSOLAS), **kw)
    t_pc = ui.Mosaico(f, esc, iconos, "server", "Juegos de esta PC",
                      detalle("Su pantalla y su sonido a la tableta, con el mando como control de Xbox", f_pc),
                      ui.VERDE, on_a=lambda: elegir_y_cerrar(PC), **kw)
    ui.disponer(f, [t_cons, t_pc], esc)
    if not hay_consolas:
        t_cons.habilitar(False)
    if f_pc and "los archivos del servidor de PC" in f_pc:
        t_pc.habilitar(False)
    for t in (t_cons, t_pc):
        t.bind("<Enter>", lambda e, t=t: t.poner_foco(t.habilitado))
        t.bind("<Leave>", lambda e, t=t: t.poner_foco(False))
    if actual:
        (t_cons if actual == CONSOLAS else t_pc).poner_marca(True)
    root.protocol("WM_DELETE_WINDOW", root.destroy)
    root.lift()
    root.focus_force()
    root.mainloop()
    return eleccion["tipo"]


# --- arrancar cada servidor --------------------------------------------------------------------------
HIJOS_A_ESPERAR = []


def lanzar(cmd, carpeta, flags=0):
    """Popen soltando al hijo del Job Object de este .exe (CREATE_BREAKAWAY_FROM_JOB, ver lanzar_oculto).
    Desde la tarea programada de inicio de sesion Windows NO deja soltarlo (el Job de la tarea no lo
    permite: medido 2026-10-05, el .exe se quedaba atorado mostrando un error que nadie veia y el
    servidor no arrancaba). En ese caso se lanza sin soltarlo y este proceso se queda esperando a que
    el hijo termine (ver main): si saliera, el Job del .exe se llevaria al servidor con el."""
    base = dict(cwd=carpeta, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                close_fds=True)
    try:
        return subprocess.Popen(cmd, creationflags=flags | CREATE_BREAKAWAY_FROM_JOB, **base)
    except OSError as e:
        log(f"sin breakaway ({e}): se lanza dentro del Job y se espera al hijo")
        p = subprocess.Popen(cmd, creationflags=flags, **base)
        HIJOS_A_ESPERAR.append(p)
        return p


def log(texto):
    try:
        with open(os.path.join(app_dir(), "lanzador.log"), "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + texto + "\n")
    except OSError:
        pass


def lanzar_oculto(ps1_path, carpeta):
    """Igual que siempre para los .ps1 del servidor de consolas: consola real pero oculta, escapa del
    Job Object del .exe y con descriptores explicitos. Por que cada cosa (medido 2026-09-11):
      - CREATE_BREAKAWAY_FROM_JOB: un .exe --onefile de PyInstaller mete su proceso en un Job Object que
        mata a los hijos al salir; sin esto el servidor moria en cuanto este lanzador terminaba.
      - SIN CREATE_NO_WINDOW: el motor detecta la capturadora corriendo otros procesos de consola y sin
        ninguna consola detras (ni oculta) eso fallaba. -WindowStyle Hidden la oculta.
      - DEVNULL explicito: un .exe --windowed no tiene stdio valido y el motor se colgaba al heredarlo.
    """
    lanzar(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", ps1_path],
           carpeta)


def arrancar_consolas(d):
    lanzar_oculto(os.path.join(d, "start_server_gui.ps1"), d)
    # config_listener.ps1 aparte de la GUI: se puede configurar desde los clientes aun con la ventana
    # cerrada. Si ya habia uno, el script nuevo mata al viejo (logs\config_listener.pid).
    listener = os.path.join(d, "config_listener.ps1")
    if os.path.isfile(listener):
        lanzar_oculto(listener, d)


def _pedir_local(cmd, espera=1.5):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(espera)
    try:
        s.sendto(json.dumps({"cmd": cmd}).encode(), ("127.0.0.1", 9200))
        return json.loads(s.recvfrom(4096)[0])
    except (OSError, ValueError):
        return None
    finally:
        s.close()


def arrancar_pc(d, mostrar):
    """Si ya corre, solo muestra su ventana. Si no, lo arranca (pythonw, sin consola) y, si mostrar, abre la
    ventana en cuanto conteste (arranca oculta junto al reloj)."""
    estado = _pedir_local("get_config")
    if estado is not None and estado.get("modo") == "pc":
        if mostrar:
            _pedir_local("mostrar_ventana")
        return True
    pythonw = buscar_pythonw()
    if not pythonw:
        mensaje("No encontre Python 3.12 (python.org, para todos los usuarios): el servidor de PC lo necesita.",
                0x10)
        return False
    lanzar([pythonw, os.path.join(d, "pc_server.py")], d, CREATE_NO_WINDOW)
    if mostrar:
        fin = time.monotonic() + 20
        while time.monotonic() < fin:
            time.sleep(1)
            if _pedir_local("get_config", 1) is not None:
                time.sleep(2)   # la ventana se arma un momento despues de abrir el puerto
                _pedir_local("mostrar_ventana")
                break
    return True


def main():
    """Si el servidor se quedo como hijo de este proceso (tarea programada, ver lanzar), al terminar puede
    haber dejado elegir.flag: lo pidio "Cambiar tipo de servidor" en su ventana. Entonces se muestra la
    eleccion aqui mismo y se arranca el elegido (un .exe nuevo moriria junto con el Job de este)."""
    args = [a.lower() for a in sys.argv[1:]]
    flag = os.path.join(app_dir(), "elegir.flag")
    while True:
        try:
            _main(args)
        except Exception as e:
            import traceback
            log("ERROR: " + traceback.format_exc())
            mensaje(f"El lanzador del servidor fallo: {e}\n(detalles en lanzador.log)", 0x10)
        if not HIJOS_A_ESPERAR:
            return
        for p in HIJOS_A_ESPERAR:
            p.wait()
        del HIJOS_A_ESPERAR[:]
        if not os.path.exists(flag):
            return
        try:
            os.remove(flag)
        except OSError:
            pass
        log("el servidor pidio cambiar de tipo")
        args = ["--elegir"]


def _main(args):
    aqui = app_dir()
    if "--solo-elegir" in args:
        actual = next((a.split("=", 1)[1] for a in args if a.startswith("--actual=")), None)
        r = elegir_aqui(aqui, actual if actual in CODIGOS else None)
        sys.exit(CODIGOS.get(r, 0))
    tipo = leer_tipo(aqui)
    log(f"arranque {sys.argv[1:]} tipo guardado={tipo}")
    if tipo is None or "--elegir" in args:
        nuevo = elegir(aqui, actual=tipo)
        if nuevo is None:
            if tipo is None:
                return          # se cerro sin elegir y no habia nada guardado
        else:
            tipo = nuevo
            guardar_tipo(aqui, tipo)
    if tipo == CONSOLAS:
        d = carpeta_consolas(aqui)
        if not d:
            mensaje(f"No encontre start_server_gui.ps1 junto a este .exe ni en consolas\\:\n{aqui}", 0x10)
            return
        arrancar_consolas(d)
    else:
        d = carpeta_pc(aqui)
        if not d:
            mensaje(f"No encontre pc_server.py junto a este .exe ni en pc\\:\n{aqui}", 0x10)
            return
        arrancar_pc(d, mostrar="--inicio" not in args)


if __name__ == "__main__":
    main()
