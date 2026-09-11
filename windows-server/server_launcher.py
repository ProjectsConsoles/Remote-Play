#!/usr/bin/env python3
"""Lanzador nativo del servidor de PS3 Remote Play (reemplaza iniciar_servidor.bat).

POR QUE EXISTE: el usuario ya habia pedido una vez convertir el motor del
servidor (start_server_stream.ps1/.bat, el que de verdad maneja ffmpeg) a
.exe con ps2exe, y eso metio un desfase de audio (ps2exe re-aloja el script
completo dentro de su propio runtime, lo que cambio el timing de algo en esa
cadena). La leccion, documentada en los comentarios de start_client_stream.sh
del lado de la Deck y en start_server_gui.ps1 del lado de la PC ("POR QUE NO
REIMPLEMENTA FFMPEG"), es: nunca tocar ni re-alojar el motor.

Por eso esto NO reimplementa nada de start_server_gui.ps1 ni de
start_server_stream.bat. Hace exactamente lo mismo que hacia
iniciar_servidor.bat (un "start" con ventana oculta hacia start_server_gui.ps1)
pero como un .exe nativo de verdad, para poder pinearlo al taskbar / darle un
icono / abrirlo con doble clic sin pasar por "Abrir con -> Windows PowerShell".

El .bat, el .ps1 de la interfaz y el .bat del motor siguen intactos y
siguen siendo la unica fuente de verdad de la logica del servidor.
"""

import os
import subprocess
import sys


def app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def lanzar_oculto(ps1_path, aqui):
    """Mismo patron para cualquier .ps1: consola real pero oculta, escapa
    del Job Object del .exe, descriptores explicitos. Ver las notas largas
    mas abajo (se dejan una sola vez, valen para los dos lanzamientos)."""
    CREATE_BREAKAWAY_FROM_JOB = 0x01000000
    subprocess.Popen(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-WindowStyle", "Hidden", "-File", ps1_path],
        cwd=aqui,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=CREATE_BREAKAWAY_FROM_JOB,
        close_fds=True,
    )


def main():
    aqui = app_dir()
    gui_ps1 = os.path.join(aqui, "start_server_gui.ps1")
    listener_ps1 = os.path.join(aqui, "config_listener.ps1")

    if not os.path.isfile(gui_ps1):
        # Sin consola (windowed): un cuadro de mensaje via WinForms es la
        # unica forma de avisar que algo esta mal, en vez de fallar en
        # silencio total.
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                0,
                f"No encontre start_server_gui.ps1 junto a este .exe:\n{aqui}",
                "PS3 Remote Play - Servidor",
                0x10,  # MB_ICONERROR
            )
        except Exception:
            pass
        return

    # CREATE_BREAKAWAY_FROM_JOB (2026-09-11): imprescindible. Un .exe --onefile
    # de PyInstaller envuelve su proceso extraido en un Job Object de Windows
    # con JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE (para poder borrar sus archivos
    # temporales al salir). Los procesos hijos heredan esa membresia del job
    # por defecto - asi que sin este flag, en cuanto ESTE lanzador termina
    # (que es casi al instante, por diseno: es "fire and forget"), Windows
    # mata TAMBIEN al powershell/GUI que acaba de lanzar, y a todo lo que ese
    # GUI lance despues (el .bat, ffmpeg). El .bat viejo (iniciar_servidor.bat)
    # nunca tuvo este problema porque cmd.exe no envuelve nada en un Job Object.
    #
    # SIN CREATE_NO_WINDOW (2026-09-11, segunda vuelta): la primera version de
    # este lanzador SI lo llevaba, y el servidor fallaba siempre al arrancar
    # por la GUI (ffmpeg nunca llegaba a aparecer, sin log ni nada - fallaba
    # ANTES de la deteccion de la capturadora). CREATE_NO_WINDOW le dice a
    # Windows que no le asigne NINGUNA consola al proceso hijo. El
    # iniciar_servidor.bat viejo, en cambio, usa `start ... -WindowStyle
    # Hidden`, que SI asigna una consola real a powershell (solo que oculta).
    # La deteccion automatica de la capturadora dentro del motor (start_
    # server_stream.bat) corre otros procesos de consola y lee su salida; sin
    # ninguna consola de verdad detras (ni siquiera oculta), esa lectura
    # aparentemente no funciona igual. Quitando CREATE_NO_WINDOW, Windows le
    # asigna una consola nueva a powershell (como no la hereda de este exe,
    # que no tiene ninguna), y "-WindowStyle Hidden" la oculta exactamente
    # igual que hacia el .bat - mismo resultado visual, sin la consola
    # faltante.
    # DESCRIPTORES EXPLICITOS (2026-09-11, la causa de verdad). Un .exe
    # compilado con --windowed no tiene consola, y por lo tanto sus
    # sys.stdin/stdout/stderr son None: los descriptores estandar del proceso
    # son INVALIDOS. Si se lanza un hijo sin decir nada, Windows le pasa esos
    # descriptores invalidos, y los hereda TODA la cadena de abajo
    # (powershell -> cmd del motor -> ffmpeg). La ventana del GUI sobrevive
    # (WinForms no usa stdio), por eso se veia normal y se podia escribir la
    # IP; pero el motor, que si lee y escribe salida, se colgaba en el acto,
    # antes siquiera de crear su archivo de log. Ese era exactamente el
    # sintoma: "no arranco en 15 segundos" y ni un log de esa corrida.
    #
    # Comprobado con una sonda compilada igual (env_probe.py): con los
    # descriptores heredados el arranque se cuelga; con DEVNULL explicito,
    # arranca. El iniciar_servidor.bat viejo nunca tuvo el problema porque
    # cmd.exe siempre tiene descriptores de consola validos que heredar.
    #
    # DEVNULL no pierde nada de diagnostico: el motor escribe sus propios
    # logs a logs\ffmpeg-*.log y logs\progreso-*.log por su cuenta.
    lanzar_oculto(gui_ps1, aqui)

    # config_listener.ps1 (2026-09-11): deja configurar modo/IP del servidor
    # en remoto desde el menu de la Deck, aun con esta ventana cerrada -
    # por eso se lanza APARTE de la GUI, no dentro de ella (ver la nota
    # larga en config_listener.ps1 sobre por que). Si ya hay uno corriendo
    # de un lanzamiento anterior, el nuevo revienta solo al intentar tomar
    # el puerto UDP 9200 (ya ocupado) - autolimitado, no hace falta mas
    # logica de instancia unica para esto.
    if os.path.isfile(listener_ps1):
        lanzar_oculto(listener_ps1, aqui)

    # Fire-and-forget, igual que el "start" del .bat viejo: este proceso
    # termina enseguida, el servidor sigue vivo por su cuenta.


if __name__ == "__main__":
    main()
