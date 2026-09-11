#!/usr/bin/env python3
"""PS3 Remote Play - Cliente para ROG Ally X (Windows)

PORTEO del cliente de la Steam Deck (start_client_stream.sh + client_menu.py +
client_control_ui.py + input_client_v3.py + deck_gamepad.py), fusionado en UN
solo proceso porque se compila como un unico .exe con PyInstaller.

POR QUE LA UI ES PYGAME Y NO TKINTER (2026-09-07): el build con el Python
"embeddable" de python.org (el paquete zip, sin instalador MSI) NO trae Tcl/Tk
- PyInstaller lo detecto solo ("tkinter installation is broken. It will be
excluded") y lo dejaba afuera del .exe, lo que habria dejado el menu y la
ventana de control sin nada que mostrar. Arreglar eso implicaba conseguir e
inyectar a mano las DLLs de Tcl/Tk de otra instalacion de Python. Como pygame
YA es una dependencia dura de este proyecto (lee el mando) y trae su propio
render de texto (SDL_ttf) sin depender de Tcl/Tk, se uso pygame tambien para
dibujar el menu y la ventana de control. Efecto secundario bueno: como ahora
todo vive en una sola libreria, el menu y el modo control quedaron
DE UN SOLO HILO (nada de tkinter.after() cooperando con un Mando aparte) - ver
la nota en ejecutar_modo_control() sobre por que el hilo de fondo de
InputSender NO se usa ahi.

QUE NO SE PORTEO (y por que):
  - lizard_mode: es un parametro del driver hid_steam de Valve, no existe en
    Windows. La Ally siempre expone el mando via XInput; ver gamepad_common.py.
  - Los ajustes de Mesa/Vulkan (vblank_mode, MESA_VK_WSI_PRESENT_MODE) y los
    umbrales de PS3RP_FIFO/PS3RP_VQ_*: son resultado de medir en la GPU y el
    compositor (gamescope) de la Deck. En la Ally la ventana la maneja
    DWM/Windows, no gamescope, asi que esos numeros no significan lo mismo
    aca. Se dejan las perillas de ffplay que SI son genericas (fifo_size,
    low_delay, sync=audio) con el mismo punto de partida, pero HAY QUE
    REMEDIR en la Ally real - ver README_ALLY.md.
  - El watchdog de "video atascado" (reinicio automatico de ffplay de la
    Deck): se deja afuera de entrada, para no adivinar umbrales que no se
    pueden medir sin el hardware.

CONFIGURACION: variables de entorno, mismo esquema que la Deck (ver
README_ALLY.md). Como esto se lanza como .exe de escritorio, la forma normal
de fijarlas es un acceso directo de Windows con variables puestas antes, o un
.bat que las exporte y despues llame al .exe.

No hay consola visible (build --windowed): todo lo que en la Deck iba a
stdout/stderr aca va al archivo de log, junto al .exe.
"""

import ctypes
import json
import logging
import os
import shutil
import socket
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gamepad_common as gp        # noqa: E402
from brightness_win import Brillo, PCT_MIN   # noqa: E402

# ---------------------------------------------------------------------------
# Rutas y logging
# ---------------------------------------------------------------------------

def app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


LOG_PATH = os.path.join(app_dir(), "ps3rp_ally_client.log")
logging.basicConfig(
    filename=LOG_PATH,
    level=logging.DEBUG if os.environ.get("PS3RP_DEBUG") == "1" else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("ps3rp")


def find_ffplay():
    override = os.environ.get("PS3RP_FFPLAY")
    if override and os.path.isfile(override):
        return override
    junto = os.path.join(app_dir(), "ffplay.exe")
    if os.path.isfile(junto):
        return junto
    return shutil.which("ffplay")


# ---------------------------------------------------------------------------
# Instancia unica: un mutex nombrado de Windows alcanza porque todo (menu +
# input + control) vive en un solo .exe ahora, a diferencia de la Deck donde
# kill_stale_instances() tenia que barrer procesos sueltos de un script viejo.
# ---------------------------------------------------------------------------

def ya_hay_instancia():
    mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "PS3RP_Ally_Client_Mutex")
    ERROR_ALREADY_EXISTS = 183
    return ctypes.windll.kernel32.GetLastError() == ERROR_ALREADY_EXISTS, mutex


# ---------------------------------------------------------------------------
# Configuracion (env vars, mismos nombres que la Deck cuando aplica)
# ---------------------------------------------------------------------------

ESP32_IP = os.environ.get("PS3RP_ESP32_IP", "192.168.0.40")
ESP32_PORT = int(os.environ.get("PS3RP_ESP32_PORT", "9000"))
ENABLE_INPUT = os.environ.get("PS3RP_INPUT", "1") == "1"
INPUT_RATE = int(os.environ.get("PS3RP_INPUT_RATE", "120"))
STREAM_PORT = int(os.environ.get("PS3RP_STREAM_PORT", "5000"))
FULLSCREEN_VIDEO = os.environ.get("PS3RP_FULLSCREEN", "1") == "1"
BRILLO_DESTINO = os.environ.get("PS3RP_BRILLO", "")  # vacio = 1%
MODO_FIJO = os.environ.get("PS3RP_MODO", "").strip().lower() or None

FONDO = (16, 16, 20)
FONDO_CONTROL = (0, 0, 0)
TEXTO = (232, 232, 234)
TENUE = (138, 138, 149)
VERDE = (63, 143, 74)
AZUL = (45, 108, 223)
GRIS_BOTON = (58, 58, 66)


# ---------------------------------------------------------------------------
# Cliente de input en hilo de fondo. SOLO se usa en modo streaming: ahi no hay
# ninguna ventana de pygame propia (ffplay es otro proceso con su propia
# ventana), asi que este hilo es el UNICO lugar del proceso que toca SDL/
# pygame y no compite con nada. En modo control NO se usa (ver mas abajo).
# ---------------------------------------------------------------------------

class InputSender(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self._detener = threading.Event()

    def _conectar(self):
        import pygame
        while not self._detener.is_set():
            pygame.joystick.quit()
            pygame.joystick.init()
            if pygame.joystick.get_count() > 0:
                js = pygame.joystick.Joystick(0)
                js.init()
                log.info("Mando conectado: %s (ejes=%d, botones=%d, hats=%d)",
                         js.get_name(), js.get_numaxes(), js.get_numbuttons(),
                         js.get_numhats())
                return js
            time.sleep(2)
        return None

    def run(self):
        import pygame
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        pygame.init()
        pygame.joystick.init()

        joystick = self._conectar()
        if joystick is None:
            return

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        interval = 1.0 / INPUT_RATE
        log.info("Enviando input a %s:%s a %s Hz", ESP32_IP, ESP32_PORT, INPUT_RATE)

        stats_last = time.time()
        stats_ticks = 0
        last_snapshot = None

        while not self._detener.is_set():
            start = time.time()
            try:
                if pygame.joystick.get_count() == 0:
                    log.warning("Mando desconectado. Esperando reconexion...")
                    joystick = self._conectar()
                    if joystick is None:
                        break
                state = gp.build_state(joystick)
            except Exception as e:
                log.warning("Error leyendo el mando (%s), reintentando...", e)
                joystick = self._conectar()
                if joystick is None:
                    break
                continue

            payload = json.dumps(state).encode("utf-8")
            try:
                sock.sendto(payload, (ESP32_IP, ESP32_PORT))
            except OSError as e:
                log.warning("Error de red (%s)", e)
                time.sleep(0.5)
                continue

            snapshot = (tuple(k for k, v in state["buttons"].items() if v),
                        state["dpad"]["x"], state["dpad"]["y"])
            if snapshot != last_snapshot:
                last_snapshot = snapshot
                log.debug("[botones] %s dpad=(%s,%s)", list(snapshot[0]), snapshot[1], snapshot[2])

            now = time.time()
            stats_ticks += 1
            if now - stats_last >= 5.0:
                span = now - stats_last
                log.debug("[stats] %d paquetes en %.1fs = %.1f Hz efectivos (objetivo %d)",
                          stats_ticks, span, stats_ticks / span, INPUT_RATE)
                stats_last, stats_ticks = now, 0

            elapsed = time.time() - start
            sleep_time = interval - elapsed
            if sleep_time > 0:
                self._detener.wait(sleep_time)

        sock.close()

    def detener(self):
        self._detener.set()
        self.join(timeout=2)


# ---------------------------------------------------------------------------
# Helpers de dibujo (pygame)
# ---------------------------------------------------------------------------

def _fuente(pygame, tam, negrita=False):
    try:
        return pygame.font.SysFont("segoeui", tam, bold=negrita)
    except Exception:
        return pygame.font.Font(None, tam)


def _texto(pygame, screen, fuente, txt, color, center=None, topleft=None):
    surf = fuente.render(txt, True, color)
    rect = surf.get_rect()
    if center:
        rect.center = center
    elif topleft:
        rect.topleft = topleft
    screen.blit(surf, rect)
    return rect


def _abrir_ventana(pygame, titulo):
    pygame.display.init()
    pygame.font.init()
    pygame.joystick.init()
    info = pygame.display.Info()
    try:
        screen = pygame.display.set_mode((info.current_w, info.current_h), pygame.FULLSCREEN)
    except Exception:
        screen = pygame.display.set_mode((1000, 650))
    pygame.display.set_caption(titulo)
    pygame.mouse.set_visible(True)
    return screen


# ---------------------------------------------------------------------------
# Menu de arranque (streaming / solo control) - un solo hilo, pygame puro.
# ---------------------------------------------------------------------------

def mostrar_menu():
    """Devuelve 'streaming', 'control', o None si cancelo."""
    import pygame
    if "SDL_VIDEODRIVER" in os.environ and os.environ["SDL_VIDEODRIVER"] == "dummy":
        del os.environ["SDL_VIDEODRIVER"]
    pygame.init()
    screen = _abrir_ventana(pygame, "PS3 Remote Play")
    w, h = screen.get_size()

    f_titulo = _fuente(pygame, 44, True)
    f_boton = _fuente(pygame, 30, True)
    f_ayuda = _fuente(pygame, 18)
    f_pie = _fuente(pygame, 16)

    opciones = [
        ("Streaming", "Video y audio del PS3 en la pantalla de la Ally, mas el control.",
         AZUL, "streaming"),
        ("Solo control", "La Ally funciona nada mas como mando, con la pantalla atenuada.",
         VERDE, "control"),
    ]
    foco = 0
    reloj = pygame.time.Clock()
    resultado = None

    ancho_tarjeta, alto_tarjeta = 320, 170
    espacio = 60
    total_ancho = ancho_tarjeta * 2 + espacio
    x0 = (w - total_ancho) // 2
    y0 = h // 2 - alto_tarjeta // 2
    rects = [pygame.Rect(x0 + i * (ancho_tarjeta + espacio), y0, ancho_tarjeta, alto_tarjeta)
             for i in range(len(opciones))]

    joy_ok = pygame.joystick.get_count() > 0 or True  # se reintenta solo mas abajo
    prev_botones = set()

    corriendo = True
    while corriendo:
        for evento in pygame.event.get():
            if evento.type == pygame.QUIT:
                resultado = None
                corriendo = False
            elif evento.type == pygame.KEYDOWN:
                if evento.key in (pygame.K_LEFT, pygame.K_UP):
                    foco = (foco - 1) % len(opciones)
                elif evento.key in (pygame.K_RIGHT, pygame.K_DOWN, pygame.K_TAB):
                    foco = (foco + 1) % len(opciones)
                elif evento.key in (pygame.K_RETURN, pygame.K_SPACE):
                    resultado = opciones[foco][3]
                    corriendo = False
                elif evento.key == pygame.K_ESCAPE:
                    resultado = None
                    corriendo = False
            elif evento.type == pygame.MOUSEBUTTONDOWN:
                for i, r in enumerate(rects):
                    if r.collidepoint(evento.pos):
                        resultado = opciones[i][3]
                        corriendo = False
            elif evento.type == pygame.JOYDEVICEADDED:
                pygame.joystick.Joystick(evento.device_index).init()

        # Navegacion con mando: boton A confirma, B cancela, dpad/stick mueve.
        if pygame.joystick.get_count() > 0:
            js = pygame.joystick.Joystick(0)
            botones = set()
            for idx, nombre in gp.BUTTON_NAMES.items():
                if idx < js.get_numbuttons() and js.get_button(idx):
                    botones.add(nombre)
            for hnum in range(js.get_numhats()):
                hx, hy = js.get_hat(hnum)
                if hx < 0:
                    botones.add("DPAD_LEFT")
                elif hx > 0:
                    botones.add("DPAD_RIGHT")
            if js.get_numaxes() > 0:
                ax = js.get_axis(0)
                if ax < -0.5:
                    botones.add("DPAD_LEFT")
                elif ax > 0.5:
                    botones.add("DPAD_RIGHT")
            nuevos = botones - prev_botones
            prev_botones = botones
            if "DPAD_LEFT" in nuevos:
                foco = (foco - 1) % len(opciones)
            if "DPAD_RIGHT" in nuevos:
                foco = (foco + 1) % len(opciones)
            if "A" in nuevos:
                resultado = opciones[foco][3]
                corriendo = False
            if "B" in nuevos:
                resultado = None
                corriendo = False

        screen.fill(FONDO)
        _texto(pygame, screen, f_titulo, "PS3 Remote Play", TEXTO, center=(w // 2, h // 2 - 220))
        _texto(pygame, screen, f_ayuda, "Que quieres hacer?", TENUE, center=(w // 2, h // 2 - 160))

        for i, (titulo, detalle, color, _modo) in enumerate(opciones):
            r = rects[i]
            pygame.draw.rect(screen, color, r, border_radius=14)
            if i == foco:
                pygame.draw.rect(screen, (255, 255, 255), r, width=4, border_radius=14)
            _texto(pygame, screen, f_boton, titulo, (255, 255, 255), center=r.center)
            # Texto de detalle envuelto a mano (lineas cortas, sin libreria de wrap)
            palabras = detalle.split()
            lineas, linea = [], ""
            for p in palabras:
                prueba = (linea + " " + p).strip()
                if f_ayuda.size(prueba)[0] > ancho_tarjeta + 40:
                    lineas.append(linea)
                    linea = p
                else:
                    linea = prueba
            if linea:
                lineas.append(linea)
            for j, ln in enumerate(lineas):
                _texto(pygame, screen, f_ayuda, ln, TENUE, center=(r.centerx, r.bottom + 26 + j * 22))

        pie = "Flechas/stick + Enter/A, Escape/B cancela.   (mouse/touch siempre funciona)"
        _texto(pygame, screen, f_pie, pie, TENUE, center=(w // 2, h - 40))

        pygame.display.flip()
        reloj.tick(30)

    pygame.display.quit()
    return resultado


# ---------------------------------------------------------------------------
# Modo "solo control" - un solo hilo: lee mando, manda UDP Y dibuja, todo en
# la misma vuelta de loop.
#
# POR QUE NO SE USA InputSender (hilo) ACA (2026-09-07): SDL/pygame espera que
# el pump de eventos y el manejo de ventana pasen por el mismo hilo que la creo
# (particularmente cierto en Windows, donde la ventana tiene su propio message
# pump de Win32). Tener esta ventana en el hilo principal Y un hilo aparte
# leyendo el mismo joystick para mandar UDP es exactamente el tipo de uso
# concurrente de SDL que puede colgar o perder eventos. En la Deck esto se
# evitaba porque cada pieza era un PROCESO distinto (limites de SO, no de
# hilos). Aca, al ser un solo proceso, la solucion es un solo bucle: cada
# vuelta lee el mando UNA vez y usa esa misma lectura para mandar el UDP y
# para actualizar el indicador en pantalla - no hay lectura concurrente.
# ---------------------------------------------------------------------------

def ejecutar_modo_control():
    import pygame
    if "SDL_VIDEODRIVER" in os.environ and os.environ["SDL_VIDEODRIVER"] == "dummy":
        del os.environ["SDL_VIDEODRIVER"]
    pygame.init()
    screen = _abrir_ventana(pygame, "PS3 Remote Play - Control")
    w, h = screen.get_size()

    f_titulo = _fuente(pygame, 46, True)
    f_sub = _fuente(pygame, 20)
    f_chico = _fuente(pygame, 16)
    f_boton = _fuente(pygame, 24, True)
    f_pulsado = _fuente(pygame, 30, True)

    brillo = Brillo()
    pct_actual = int(BRILLO_DESTINO) if BRILLO_DESTINO else (brillo.leer_pct() or 50)
    pct_actual = max(PCT_MIN, min(100, pct_actual))
    if BRILLO_DESTINO and brillo.ok:
        brillo.escribir_pct(pct_actual)

    barra_rect = pygame.Rect(w // 2 - 280, h // 2 + 40, 560, 34)
    boton_salir = pygame.Rect(w // 2 - 90, h - 160, 180, 56)

    joystick = None
    if pygame.joystick.get_count() > 0:
        joystick = pygame.joystick.Joystick(0)
        joystick.init()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) if ENABLE_INPUT else None
    interval = 1.0 / INPUT_RATE
    proximo_envio = time.time()

    arrastrando_barra = False
    ultimo_toque_barra = 0.0
    texto_pulsado = ""

    reloj = pygame.time.Clock()
    salir = False
    ultima_sync_brillo = 0.0

    while not salir:
        ahora = time.time()

        for evento in pygame.event.get():
            if evento.type == pygame.QUIT:
                salir = True
            elif evento.type == pygame.KEYDOWN and evento.key == pygame.K_ESCAPE:
                salir = True
            elif evento.type == pygame.JOYDEVICEADDED:
                joystick = pygame.joystick.Joystick(evento.device_index)
                joystick.init()
            elif evento.type == pygame.JOYDEVICEREMOVED:
                joystick = None
            elif evento.type == pygame.MOUSEBUTTONDOWN:
                if boton_salir.collidepoint(evento.pos):
                    salir = True
                elif barra_rect.inflate(0, 20).collidepoint(evento.pos):
                    arrastrando_barra = True
            elif evento.type == pygame.MOUSEBUTTONUP:
                arrastrando_barra = False

        if arrastrando_barra:
            mx, _ = pygame.mouse.get_pos()
            frac = (mx - barra_rect.left) / barra_rect.width
            pct_actual = max(PCT_MIN, min(100, round(frac * 100)))
            if brillo.ok:
                brillo.escribir_pct(pct_actual)
            ultimo_toque_barra = ahora

        # Sincronizar con el brillo real del sistema si el usuario no la esta
        # tocando (por si algo mas en Windows lo cambio), igual que en la Deck.
        if brillo.ok and not arrastrando_barra and (ahora - ultimo_toque_barra) > 3 \
                and (ahora - ultima_sync_brillo) > 1:
            real = brillo.leer_pct()
            if real is not None and abs(real - pct_actual) >= 1:
                pct_actual = real
            ultima_sync_brillo = ahora

        # Un solo pump/lectura del mando por vuelta: se usa para mandar UDP y
        # para el indicador. Reconecta solo si hace falta.
        estado = None
        if joystick is None and pygame.joystick.get_count() > 0:
            joystick = pygame.joystick.Joystick(0)
            joystick.init()
        if joystick is not None:
            try:
                estado = gp.build_state(joystick)
            except Exception:
                joystick = None

        if estado is not None:
            texto_pulsado = gp.etiquetar([k for k, v in estado["buttons"].items() if v])
            if sock is not None and ahora >= proximo_envio:
                try:
                    sock.sendto(json.dumps(estado).encode("utf-8"), (ESP32_IP, ESP32_PORT))
                except OSError:
                    pass
                proximo_envio = ahora + interval
        else:
            texto_pulsado = ""

        # --- dibujo ---
        screen.fill(FONDO_CONTROL)
        _texto(pygame, screen, f_titulo, "MODO CONTROL ACTIVO", VERDE, center=(w // 2, h // 2 - 200))
        _texto(pygame, screen, f_sub, "La Ally esta funcionando solo como mando.",
               TEXTO, center=(w // 2, h // 2 - 140))
        _texto(pygame, screen, f_sub, "Mira el PS3 en la tele.", TEXTO, center=(w // 2, h // 2 - 112))
        _texto(pygame, screen, f_chico, f"Mandando al ESP32 en {ESP32_IP}:{ESP32_PORT}",
               TENUE, center=(w // 2, h // 2 - 70))

        _texto(pygame, screen, f_chico, "Brillo de la pantalla", TENUE,
               center=(barra_rect.centerx, barra_rect.top - 20))
        if brillo.ok:
            pygame.draw.rect(screen, (42, 42, 48), barra_rect, border_radius=8)
            relleno = barra_rect.copy()
            relleno.width = max(4, int(barra_rect.width * pct_actual / 100))
            pygame.draw.rect(screen, AZUL, relleno, border_radius=8)
            pygame.draw.rect(screen, (255, 255, 255), barra_rect, width=2, border_radius=8)
            _texto(pygame, screen, f_chico, f"{pct_actual}%", TEXTO,
                   center=(barra_rect.centerx, barra_rect.bottom + 20))
        else:
            _texto(pygame, screen, f_chico, "Brillo no disponible via WMI en este equipo",
                   TENUE, center=(barra_rect.centerx, barra_rect.centery))

        pygame.draw.rect(screen, GRIS_BOTON, boton_salir, border_radius=10)
        _texto(pygame, screen, f_boton, "Salir", (255, 255, 255), center=boton_salir.center)
        _texto(pygame, screen, f_chico, "\"Salir\" te devuelve al selector de modo.",
               TENUE, center=(w // 2, h - 90))

        _texto(pygame, screen, f_pulsado, texto_pulsado, TEXTO, center=(w // 2, h - 40))

        pygame.display.flip()
        reloj.tick(60)

    if sock is not None:
        sock.close()
    pygame.display.quit()


# ---------------------------------------------------------------------------
# Modo streaming: lanza ffplay y espera a que se cierre.
# ---------------------------------------------------------------------------

def ejecutar_modo_streaming():
    ffplay = find_ffplay()
    if not ffplay:
        log.error("No se encontro ffplay.exe (ver PS3RP_FFPLAY, o ponerlo junto al .exe).")
        return

    url = f"udp://0.0.0.0:{STREAM_PORT}?fifo_size=1500&overrun_nonfatal=1"
    args = [
        ffplay,
        "-fflags", "nobuffer",
        "-flags", "low_delay",
        "-framedrop",
        "-probesize", "32",
        "-analyzeduration", "0",
        "-f", "mpegts",
        "-sync", "audio",
        "-loglevel", "warning",
        "-nostats",
        "-window_title", "PS3 Remote Play",
    ]
    if FULLSCREEN_VIDEO:
        args.append("-fs")
    args.append(url)

    log.info("Lanzando ffplay: %s", " ".join(args))

    sender = None
    if ENABLE_INPUT:
        sender = InputSender()
        sender.start()

    try:
        # stdin tambien en DEVNULL, no solo stdout/stderr (2026-09-11): este
        # .exe se compila con --windowed, o sea sin consola, asi que sus
        # descriptores estandar son INVALIDOS (sys.stdin/stdout/stderr son
        # None). Todo hijo que no reciba descriptores explicitos hereda esos
        # invalidos y se cuelga. Costo un buen rato descubrirlo del lado del
        # servidor, donde el motor no arrancaba nunca y no dejaba ni un log;
        # aca ffplay habria hecho lo mismo.
        proc = subprocess.Popen(args,
                                stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
        proc.wait()
    except Exception as e:
        log.error("No se pudo lanzar ffplay: %s", e)
    finally:
        if sender is not None:
            sender.detener()


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    ya, _mutex = ya_hay_instancia()
    if ya:
        log.warning("Ya hay una instancia corriendo; saliendo.")
        return

    log.info("=== PS3 Remote Play (Ally) iniciando ===")

    while True:
        modo = MODO_FIJO
        if modo not in ("streaming", "control"):
            modo = mostrar_menu()
            if modo is None:
                log.info("Menu cancelado; cerrando.")
                break

        if modo == "control":
            log.info("--- modo SOLO CONTROL ---")
            ejecutar_modo_control()
            if MODO_FIJO:
                break
            continue

        log.info("--- modo STREAMING ---")
        ejecutar_modo_streaming()
        break

    log.info("=== Cerrando ===")


if __name__ == "__main__":
    main()
