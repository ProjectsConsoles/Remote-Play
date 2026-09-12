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
import server_udp                  # noqa: E402

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
# Config guardada - porteo de client_config.env de la Deck (2026-09-11)
# ---------------------------------------------------------------------------
# Mismas variables PS3RP_*, mismo patron "solo si no esta puesta": si una
# variable ya viene fijada desde afuera (un acceso directo de Windows con
# variables de entorno explicitas), esta carga no la pisa - equivalente a
# `: "${VAR:=valor}"` en start_client_stream.sh, pero con
# os.environ.setdefault() porque aca no hay shell de por medio.
# ---------------------------------------------------------------------------

ARCHIVO_CONFIG_CLIENTE = os.path.join(app_dir(), "ally_config.json")

# (variable, etiqueta, tipo, default, opciones-si-es-enum)
# tipo: "texto" | "numero" | "bool" | "enum"
CAMPOS_CLIENTE = [
    ("PS3RP_ESP32_IP", "IP del ESP32-S3", "texto", "192.168.0.40", None),
    ("PS3RP_ESP32_PORT", "Puerto UDP del ESP32", "numero", "9000", None),
    ("PS3RP_INPUT", "Mandar control (no solo video)", "bool", "1", None),
    ("PS3RP_INPUT_RATE", "Frecuencia de envio (Hz)", "numero", "120", None),
    ("PS3RP_PS_COMBO", "Acorde para el boton PS", "texto", "SELECT+R1", None),
    ("PS3RP_STREAM_PORT", "Puerto UDP del video", "numero", "5000", None),
    ("PS3RP_FULLSCREEN", "Video en pantalla completa", "bool", "1", None),
    ("PS3RP_BRILLO", "Brillo en modo control (0-100, vacio = no tocar)", "numero", "", None),
    ("PS3RP_MODO", "Modo fijo al abrir (vacio = preguntar cada vez)", "enum", "",
     ["", "streaming", "control"]),
]


def cargar_config_guardada():
    if not os.path.isfile(ARCHIVO_CONFIG_CLIENTE):
        return
    try:
        with open(ARCHIVO_CONFIG_CLIENTE, "r", encoding="utf-8") as f:
            datos = json.load(f)
        for k, v in datos.items():
            if v not in (None, ""):
                os.environ.setdefault(k, str(v))
    except Exception:
        pass


def guardar_config_cliente(valores: dict):
    limpio = {k: v for k, v in valores.items() if v != ""}
    try:
        with open(ARCHIVO_CONFIG_CLIENTE, "w", encoding="utf-8") as f:
            json.dump(limpio, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False


cargar_config_guardada()

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


def _botones_nuevos(gp, joystick, prev):
    """Botones/cruceta/stick que pasaron de sueltos a pulsados desde la
    ultima vez. Factorizado (2026-09-11) de la logica que ya traia
    mostrar_menu() para que las pantallas nuevas de configuracion no la
    reescriban cada una - mismo patron que deck_gamepad.Mando.nuevos() de la
    Deck, adaptado a pygame directo (aca no hay un lector de mando con
    estado propio, gamepad_common.py solo define el mapeo)."""
    if joystick is None:
        return set(), prev
    try:
        botones = set()
        for idx, nombre in gp.BUTTON_NAMES.items():
            if idx < joystick.get_numbuttons() and joystick.get_button(idx):
                botones.add(nombre)
        for hnum in range(joystick.get_numhats()):
            hx, hy = joystick.get_hat(hnum)
            if hx < 0:
                botones.add("DPAD_LEFT")
            elif hx > 0:
                botones.add("DPAD_RIGHT")
            if hy > 0:
                botones.add("DPAD_UP")
            elif hy < 0:
                botones.add("DPAD_DOWN")
        if joystick.get_numaxes() > 1:
            ax, ay = joystick.get_axis(0), joystick.get_axis(1)
            if ax < -0.5:
                botones.add("DPAD_LEFT")
            elif ax > 0.5:
                botones.add("DPAD_RIGHT")
            if ay < -0.5:
                botones.add("DPAD_UP")
            elif ay > 0.5:
                botones.add("DPAD_DOWN")
    except Exception:
        return set(), prev
    return botones - prev, botones


def _joystick_activo(pygame, joystick):
    """Reconecta solo si hace falta; devuelve el joystick actual o None."""
    if joystick is not None:
        return joystick
    if pygame.joystick.get_count() > 0:
        js = pygame.joystick.Joystick(0)
        js.init()
        return js
    return None


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
    """Devuelve 'streaming', 'control', 'config_servidor', 'config_cliente',
    o None si cancelo."""
    import pygame
    if "SDL_VIDEODRIVER" in os.environ and os.environ["SDL_VIDEODRIVER"] == "dummy":
        del os.environ["SDL_VIDEODRIVER"]
    pygame.init()
    screen = _abrir_ventana(pygame, "PS3 Remote Play")
    w, h = screen.get_size()

    f_titulo = _fuente(pygame, 44, True)
    f_boton = _fuente(pygame, 26, True)
    f_ayuda = _fuente(pygame, 16)
    f_pie = _fuente(pygame, 16)

    # 2x2 (2026-09-11, porteo de client_menu.py de la Deck): los dos botones
    # nuevos de configuracion remota - mismo protocolo/UDP que la Deck contra
    # el mismo config_listener.ps1, asi que no hace falta nada nuevo del lado
    # del servidor de Windows.
    opciones = [
        ("Streaming", "Video y audio del PS3, mas el control.", AZUL, "streaming"),
        ("Solo control", "La Ally funciona solo como mando.", VERDE, "control"),
        ("Configurar servidor", "Elige el modo de captura de la PC sin ir a tocarla.",
         (58, 58, 66), "config_servidor"),
        ("Configurar cliente", "Variables PS3RP_* de este lado (ESP32, input, video).",
         (58, 58, 66), "config_cliente"),
    ]
    foco = 0
    reloj = pygame.time.Clock()
    resultado = None

    ancho_tarjeta, alto_tarjeta = 300, 160
    espacio_x, espacio_y = 50, 40
    columnas = 2
    filas = 2
    total_ancho = ancho_tarjeta * columnas + espacio_x * (columnas - 1)
    total_alto = alto_tarjeta * filas + espacio_y * (filas - 1)
    x0 = (w - total_ancho) // 2
    y0 = (h - total_alto) // 2
    rects = []
    for i in range(len(opciones)):
        fila, col = divmod(i, columnas)
        rects.append(pygame.Rect(x0 + col * (ancho_tarjeta + espacio_x),
                                  y0 + fila * (alto_tarjeta + espacio_y),
                                  ancho_tarjeta, alto_tarjeta))

    joystick = _joystick_activo(pygame, None)
    prev_botones = set()

    corriendo = True
    while corriendo:
        for evento in pygame.event.get():
            if evento.type == pygame.QUIT:
                resultado = None
                corriendo = False
            elif evento.type == pygame.KEYDOWN:
                fila, col = divmod(foco, columnas)
                if evento.key == pygame.K_LEFT:
                    foco = fila * columnas + (col - 1) % columnas
                elif evento.key == pygame.K_RIGHT:
                    foco = fila * columnas + (col + 1) % columnas
                elif evento.key == pygame.K_UP:
                    foco = ((fila - 1) % filas) * columnas + col
                elif evento.key == pygame.K_DOWN:
                    foco = ((fila + 1) % filas) * columnas + col
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
                joystick = pygame.joystick.Joystick(evento.device_index)
                joystick.init()

        joystick = _joystick_activo(pygame, joystick)
        nuevos, prev_botones = _botones_nuevos(gp, joystick, prev_botones)
        fila, col = divmod(foco, columnas)
        if "DPAD_LEFT" in nuevos:
            foco = fila * columnas + (col - 1) % columnas
        if "DPAD_RIGHT" in nuevos:
            foco = fila * columnas + (col + 1) % columnas
        if "DPAD_UP" in nuevos:
            foco = ((fila - 1) % filas) * columnas + col
        if "DPAD_DOWN" in nuevos:
            foco = ((fila + 1) % filas) * columnas + col
        if "A" in nuevos:
            resultado = opciones[foco][3]
            corriendo = False
        if "B" in nuevos:
            resultado = None
            corriendo = False

        screen.fill(FONDO)
        _texto(pygame, screen, f_titulo, "PS3 Remote Play", TEXTO, center=(w // 2, y0 - 90))
        _texto(pygame, screen, f_ayuda, "Que quieres hacer?", TENUE, center=(w // 2, y0 - 40))

        for i, (titulo, detalle, color, _modo) in enumerate(opciones):
            r = rects[i]
            pygame.draw.rect(screen, color, r, border_radius=14)
            if i == foco:
                pygame.draw.rect(screen, (255, 255, 255), r, width=4, border_radius=14)
            _texto(pygame, screen, f_boton, titulo, (255, 255, 255), center=(r.centerx, r.centery - 20))
            palabras = detalle.split()
            lineas, linea = [], ""
            for p in palabras:
                prueba = (linea + " " + p).strip()
                if f_ayuda.size(prueba)[0] > ancho_tarjeta - 30:
                    lineas.append(linea)
                    linea = p
                else:
                    linea = prueba
            if linea:
                lineas.append(linea)
            for j, ln in enumerate(lineas):
                _texto(pygame, screen, f_ayuda, ln, TENUE, center=(r.centerx, r.centery + 20 + j * 20))

        pie = "Flechas/stick + Enter/A, Escape/B cancela.   (mouse/touch siempre funciona)"
        _texto(pygame, screen, f_pie, pie, TENUE, center=(w // 2, h - 30))

        pygame.display.flip()
        reloj.tick(30)

    pygame.display.quit()
    return resultado


# ---------------------------------------------------------------------------
# Configurar servidor - porteo de client_server_config.py de la Deck
# (2026-09-11). Mismo protocolo UDP (puerto 9200) contra config_listener.ps1
# del lado del servidor - no hace falta nada nuevo ahi, ya sirve a las dos
# maquinas por igual. La lista de modos se duplica a proposito (misma razon
# que en la Deck: 4 lineas fijas, mas simple que sincronizar descripciones
# entre 3 maquinas que mantener un protocolo aparte para eso).
# ---------------------------------------------------------------------------

MODOS_SERVIDOR = [
    ("mjpeg720", "1280x720 - MJPEG (recomendado)", "60 fps estables, ~6 Mbps de wifi."),
    ("mjpeg1080", "1920x1080 - MJPEG (mas nitido)", "Mas definido, pero sube a 8 Mbps."),
    ("crudo480", "720x480 - SIN COMPRIMIR (prueba)", "Salta el MJPEG, 5x mas datos por USB."),
    ("crudo640", "640x480 - SIN COMPRIMIR (prueba)", "Igual pero pide menos por el USB."),
]

IP_SERVIDOR_DEFAULT = "192.168.0.90"


def mostrar_config_servidor():
    import pygame
    if "SDL_VIDEODRIVER" in os.environ and os.environ["SDL_VIDEODRIVER"] == "dummy":
        del os.environ["SDL_VIDEODRIVER"]
    pygame.init()
    pygame.key.start_text_input()
    screen = _abrir_ventana(pygame, "Configurar servidor")
    w, h = screen.get_size()

    f_titulo = _fuente(pygame, 34, True)
    f_label = _fuente(pygame, 18)
    f_modo_t = _fuente(pygame, 18, True)
    f_modo_d = _fuente(pygame, 14)
    f_pie = _fuente(pygame, 14)

    ip_ally = server_udp.obtener_ip_local() or "?"
    estado = {"ip_servidor": server_udp.leer_ip_servidor_guardada() or IP_SERVIDOR_DEFAULT,
              "editando_ip": False, "seleccionado": 0,
              "txt": "Sin consultar todavia.", "color": TENUE}

    ancho_t, alto_t = 260, 120
    esp_x, esp_y = 30, 24
    columnas = 2
    total_ancho = ancho_t * columnas + esp_x
    x0 = (w - total_ancho) // 2
    y0 = h // 2 - 110
    rects = []
    for i in range(len(MODOS_SERVIDOR)):
        fila, col = divmod(i, columnas)
        rects.append(pygame.Rect(x0 + col * (ancho_t + esp_x), y0 + fila * (alto_t + esp_y),
                                  ancho_t, alto_t))

    campo_ip_rect = pygame.Rect(w // 2 - 140, 150, 280, 40)

    def dibujar():
        screen.fill(FONDO)
        _texto(pygame, screen, f_titulo, "Configurar servidor", TEXTO, center=(w // 2, 50))
        _texto(pygame, screen, f_label, f"Esta Ally: {ip_ally}", TENUE, center=(w // 2, 90))
        _texto(pygame, screen, f_label, "IP del servidor Windows:", TEXTO,
               center=(w // 2, campo_ip_rect.top - 16))
        color_borde = (255, 255, 255) if estado["editando_ip"] else (90, 90, 100)
        pygame.draw.rect(screen, (30, 30, 36), campo_ip_rect, border_radius=6)
        pygame.draw.rect(screen, color_borde, campo_ip_rect, width=2, border_radius=6)
        _texto(pygame, screen, f_label, estado["ip_servidor"], TEXTO, center=campo_ip_rect.center)
        _texto(pygame, screen, f_label, estado["txt"], estado["color"],
               center=(w // 2, campo_ip_rect.bottom + 26))

        for i, (_clave, nombre, detalle) in enumerate(MODOS_SERVIDOR):
            r = rects[i]
            pygame.draw.rect(screen, (40, 44, 56), r, border_radius=10)
            if i == estado["seleccionado"]:
                pygame.draw.rect(screen, (255, 255, 255), r, width=3, border_radius=10)
            _texto(pygame, screen, f_modo_t, nombre, TEXTO, center=(r.centerx, r.top + 26))
            palabras = detalle.split()
            lineas, linea = [], ""
            for p in palabras:
                prueba = (linea + " " + p).strip()
                if f_modo_d.size(prueba)[0] > r.width - 20:
                    lineas.append(linea)
                    linea = p
                else:
                    linea = prueba
            if linea:
                lineas.append(linea)
            for j, ln in enumerate(lineas):
                _texto(pygame, screen, f_modo_d, ln, TENUE, center=(r.centerx, r.top + 55 + j * 18))

        pie = "Flechas elige modo, A aplica, X consulta, Y manda IP, toca el cuadro edita la IP, B vuelve."
        _texto(pygame, screen, f_pie, pie, TENUE, center=(w // 2, h - 30))
        pygame.display.flip()

    def consultar():
        estado["txt"], estado["color"] = "Consultando...", TENUE
        dibujar()
        ok, resp = server_udp.obtener_config(estado["ip_servidor"])
        if not ok:
            estado["txt"], estado["color"] = str(resp), (200, 80, 60)
            return
        server_udp.guardar_ip_servidor(estado["ip_servidor"])
        corriendo_txt = "SI" if resp.get("corriendo") else "no"
        modo_actual = resp.get("modo") or "(ninguno guardado)"
        estado["txt"] = f"Corriendo: {corriendo_txt}  ·  Modo actual: {modo_actual}"
        estado["color"] = VERDE if resp.get("corriendo") else TENUE
        for i, (clave, _, _) in enumerate(MODOS_SERVIDOR):
            if clave == resp.get("modo"):
                estado["seleccionado"] = i

    def aplicar():
        clave = MODOS_SERVIDOR[estado["seleccionado"]][0]
        estado["txt"] = "Aplicando... si el servidor ya esta corriendo, puede tardar unos segundos."
        estado["color"] = TENUE
        dibujar()
        ok, resp = server_udp.aplicar_config(estado["ip_servidor"], ip_ally, clave)
        if not ok:
            estado["txt"], estado["color"] = str(resp), (200, 80, 60)
            return
        server_udp.guardar_ip_servidor(estado["ip_servidor"])
        aplicado = resp.get("aplicado")
        if aplicado == "reiniciado":
            estado["txt"] = "Listo: servidor reiniciado con la config nueva."
            estado["color"] = VERDE
        elif aplicado == "guardado_para_proxima_vez":
            estado["txt"] = "Guardado. Se aplicara la proxima vez que le den Iniciar."
            estado["color"] = VERDE
        else:
            estado["txt"], estado["color"] = str(resp), (200, 80, 60)

    def enviar_ip():
        # "que no sea necesario escribirla en el servidor por si cambia"
        # (mismo pedido que en la Deck, 2026-09-11): manda la IP de ESTA
        # Ally sin tocar el modo - consulta el modo actual del servidor y se
        # lo vuelve a mandar junto con la IP nueva.
        estado["txt"], estado["color"] = "Consultando modo actual del servidor...", TENUE
        dibujar()
        ok, resp = server_udp.obtener_config(estado["ip_servidor"])
        if not ok:
            estado["txt"], estado["color"] = str(resp), (200, 80, 60)
            return
        modo_actual = resp.get("modo") or MODOS_SERVIDOR[estado["seleccionado"]][0]
        estado["txt"] = f"Enviando IP de esta Ally ({ip_ally})..."
        estado["color"] = TENUE
        dibujar()
        ok, resp = server_udp.aplicar_config(estado["ip_servidor"], ip_ally, modo_actual)
        if not ok:
            estado["txt"], estado["color"] = str(resp), (200, 80, 60)
            return
        server_udp.guardar_ip_servidor(estado["ip_servidor"])
        aplicado = resp.get("aplicado")
        if aplicado == "reiniciado":
            estado["txt"] = f"IP enviada ({ip_ally}). Servidor reiniciado con el mismo modo."
        else:
            estado["txt"] = f"IP enviada ({ip_ally}). Se aplicara la proxima vez que arranque."
        estado["color"] = VERDE
        for i, (clave, _, _) in enumerate(MODOS_SERVIDOR):
            if clave == modo_actual:
                estado["seleccionado"] = i

    joystick = _joystick_activo(pygame, None)
    prev_botones = set()
    reloj = pygame.time.Clock()
    consultar()

    corriendo = True
    while corriendo:
        for evento in pygame.event.get():
            if evento.type == pygame.QUIT:
                corriendo = False
            elif evento.type == pygame.TEXTINPUT and estado["editando_ip"]:
                if evento.text in "0123456789.":
                    estado["ip_servidor"] += evento.text
            elif evento.type == pygame.KEYDOWN:
                if estado["editando_ip"]:
                    if evento.key == pygame.K_BACKSPACE:
                        estado["ip_servidor"] = estado["ip_servidor"][:-1]
                    elif evento.key in (pygame.K_RETURN, pygame.K_ESCAPE):
                        estado["editando_ip"] = False
                    continue
                if evento.key == pygame.K_LEFT:
                    estado["seleccionado"] = (estado["seleccionado"] - 1) % len(MODOS_SERVIDOR)
                elif evento.key == pygame.K_RIGHT:
                    estado["seleccionado"] = (estado["seleccionado"] + 1) % len(MODOS_SERVIDOR)
                elif evento.key == pygame.K_UP:
                    estado["seleccionado"] = (estado["seleccionado"] - 2) % len(MODOS_SERVIDOR)
                elif evento.key == pygame.K_DOWN:
                    estado["seleccionado"] = (estado["seleccionado"] + 2) % len(MODOS_SERVIDOR)
                elif evento.key == pygame.K_RETURN:
                    aplicar()
                elif evento.key == pygame.K_ESCAPE:
                    corriendo = False
            elif evento.type == pygame.MOUSEBUTTONDOWN:
                if campo_ip_rect.collidepoint(evento.pos):
                    estado["editando_ip"] = True
                else:
                    estado["editando_ip"] = False
                    for i, r in enumerate(rects):
                        if r.collidepoint(evento.pos):
                            estado["seleccionado"] = i
            elif evento.type == pygame.JOYDEVICEADDED:
                joystick = pygame.joystick.Joystick(evento.device_index)
                joystick.init()

        if not estado["editando_ip"]:
            joystick = _joystick_activo(pygame, joystick)
            nuevos, prev_botones = _botones_nuevos(gp, joystick, prev_botones)
            n = len(MODOS_SERVIDOR)
            if "DPAD_LEFT" in nuevos:
                estado["seleccionado"] = (estado["seleccionado"] - 1) % n
            if "DPAD_RIGHT" in nuevos:
                estado["seleccionado"] = (estado["seleccionado"] + 1) % n
            if "DPAD_UP" in nuevos:
                estado["seleccionado"] = (estado["seleccionado"] - 2) % n
            if "DPAD_DOWN" in nuevos:
                estado["seleccionado"] = (estado["seleccionado"] + 2) % n
            if "A" in nuevos:
                aplicar()
            if "X" in nuevos:
                consultar()
            if "Y" in nuevos:
                enviar_ip()
            if "B" in nuevos:
                corriendo = False

        dibujar()
        reloj.tick(30)

    pygame.key.stop_text_input()
    pygame.display.quit()


# ---------------------------------------------------------------------------
# Configurar cliente - porteo de client_settings.py de la Deck (2026-09-11).
# Muchas menos variables que la Deck (9 contra 18): todo lo que dependia de
# Mesa/gamescope/lizard_mode no aplica aca (ver la nota grande al inicio del
# archivo, "QUE NO SE PORTEO"). Se guarda en ally_config.json en vez del
# formato `: "${VAR:=valor}"` de bash porque aca no hay shell de por medio -
# ver cargar_config_guardada()/guardar_config_cliente() mas arriba.
# ---------------------------------------------------------------------------

def mostrar_config_cliente():
    import pygame
    if "SDL_VIDEODRIVER" in os.environ and os.environ["SDL_VIDEODRIVER"] == "dummy":
        del os.environ["SDL_VIDEODRIVER"]
    pygame.init()
    pygame.key.start_text_input()
    screen = _abrir_ventana(pygame, "Configurar cliente")
    w, h = screen.get_size()

    f_titulo = _fuente(pygame, 32, True)
    f_label = _fuente(pygame, 17)
    f_valor = _fuente(pygame, 17, True)
    f_pie = _fuente(pygame, 14)

    guardado = {}
    if os.path.isfile(ARCHIVO_CONFIG_CLIENTE):
        try:
            with open(ARCHIVO_CONFIG_CLIENTE, "r", encoding="utf-8") as f:
                guardado = json.load(f)
        except Exception:
            guardado = {}

    valores = {var: str(guardado.get(var, default)) for var, _e, _t, default, _o in CAMPOS_CLIENTE}
    n = len(CAMPOS_CLIENTE)

    est = {"foco": 0, "editando": False, "buffer": "", "txt": "", "color": TENUE}

    fila_alto = 52
    y0 = 110
    ancho_fila = min(760, w - 80)
    x0 = (w - ancho_fila) // 2

    def rect_fila(i):
        return pygame.Rect(x0, y0 + i * fila_alto, ancho_fila, fila_alto - 8)

    def valor_mostrado(i):
        var, _e, tipo, _d, opciones = CAMPOS_CLIENTE[i]
        if est["editando"] and i == est["foco"] and tipo in ("texto", "numero"):
            return est["buffer"] + "_"
        if tipo == "bool":
            return "SI" if valores[var] == "1" else "NO"
        if tipo == "enum":
            return valores[var] if valores[var] else "(preguntar)"
        return valores[var] if valores[var] != "" else "(vacio)"

    def ajustar(i, delta):
        var, _e, tipo, _d, opciones = CAMPOS_CLIENTE[i]
        if tipo == "numero":
            try:
                base = int(valores[var]) if valores[var].strip() else 0
            except ValueError:
                base = 0
            valores[var] = str(base + delta)
        elif tipo == "bool":
            valores[var] = "0" if valores[var] == "1" else "1"
        elif tipo == "enum":
            i_actual = opciones.index(valores[var]) if valores[var] in opciones else 0
            valores[var] = opciones[(i_actual + delta) % len(opciones)]

    def iniciar_edicion(i):
        var, _e, tipo, _d, _o = CAMPOS_CLIENTE[i]
        if tipo in ("texto", "numero"):
            est["editando"] = True
            est["buffer"] = valores[var]

    def confirmar_edicion(i):
        var = CAMPOS_CLIENTE[i][0]
        valores[var] = est["buffer"].strip()
        est["editando"] = False

    def accionar_a(i):
        tipo = CAMPOS_CLIENTE[i][2]
        if tipo in ("texto", "numero"):
            iniciar_edicion(i)
        else:
            ajustar(i, 1)

    def guardar():
        if guardar_config_cliente(valores):
            est["txt"] = "Guardado. Se aplica la proxima vez que arranques streaming/control."
            est["color"] = VERDE
        else:
            est["txt"] = "No se pudo guardar (revisa permisos de la carpeta)."
            est["color"] = (200, 80, 60)

    def restaurar_defaults():
        nonlocal valores
        valores = {var: default for var, _e, _t, default, _o in CAMPOS_CLIENTE}
        try:
            if os.path.isfile(ARCHIVO_CONFIG_CLIENTE):
                os.remove(ARCHIVO_CONFIG_CLIENTE)
        except Exception:
            pass
        est["txt"], est["color"] = "Restaurado a los defaults (sin guardar todavia).", TENUE

    def dibujar():
        screen.fill(FONDO)
        _texto(pygame, screen, f_titulo, "Configurar cliente", TEXTO, center=(w // 2, 45))
        _texto(pygame, screen, f_pie, "Variables de este lado (Ally). Vacio = usar el default.",
               TENUE, center=(w // 2, 78))
        for i, (_var, etiqueta, _t, _d, _o) in enumerate(CAMPOS_CLIENTE):
            r = rect_fila(i)
            pygame.draw.rect(screen, (40, 44, 56), r, border_radius=8)
            if i == est["foco"]:
                pygame.draw.rect(screen, (255, 255, 255), r, width=2, border_radius=8)
            _texto(pygame, screen, f_label, etiqueta, TEXTO, topleft=(r.left + 14, r.top + 8))
            _texto(pygame, screen, f_valor, valor_mostrado(i), TEXTO, topleft=(r.right - 160, r.top + 8))
        _texto(pygame, screen, f_label, est["txt"], est["color"], center=(w // 2, y0 + n * fila_alto + 18))
        pie = ("Arriba/abajo mueve, izq/der cambia, A edita texto/numero (Enter confirma), "
               "X restaura, Y guarda, B vuelve.")
        _texto(pygame, screen, f_pie, pie, TENUE, center=(w // 2, h - 30))
        pygame.display.flip()

    joystick = _joystick_activo(pygame, None)
    prev_botones = set()
    reloj = pygame.time.Clock()

    corriendo = True
    while corriendo:
        for evento in pygame.event.get():
            if evento.type == pygame.QUIT:
                corriendo = False
            elif evento.type == pygame.TEXTINPUT and est["editando"]:
                tipo_actual = CAMPOS_CLIENTE[est["foco"]][2]
                if tipo_actual == "numero":
                    if evento.text.isdigit() or (evento.text == "-" and est["buffer"] == ""):
                        est["buffer"] += evento.text
                else:
                    est["buffer"] += evento.text
            elif evento.type == pygame.KEYDOWN:
                if est["editando"]:
                    if evento.key == pygame.K_BACKSPACE:
                        est["buffer"] = est["buffer"][:-1]
                    elif evento.key == pygame.K_RETURN:
                        confirmar_edicion(est["foco"])
                    elif evento.key == pygame.K_ESCAPE:
                        est["editando"] = False
                    continue
                if evento.key == pygame.K_UP:
                    est["foco"] = (est["foco"] - 1) % n
                elif evento.key == pygame.K_DOWN:
                    est["foco"] = (est["foco"] + 1) % n
                elif evento.key == pygame.K_LEFT:
                    ajustar(est["foco"], -1)
                elif evento.key == pygame.K_RIGHT:
                    ajustar(est["foco"], 1)
                elif evento.key == pygame.K_RETURN:
                    accionar_a(est["foco"])
                elif evento.key == pygame.K_ESCAPE:
                    corriendo = False
            elif evento.type == pygame.MOUSEBUTTONDOWN:
                for i in range(n):
                    if rect_fila(i).collidepoint(evento.pos):
                        est["foco"] = i
                        accionar_a(i)
            elif evento.type == pygame.JOYDEVICEADDED:
                joystick = pygame.joystick.Joystick(evento.device_index)
                joystick.init()

        joystick = _joystick_activo(pygame, joystick)
        nuevos, prev_botones = _botones_nuevos(gp, joystick, prev_botones)
        if est["editando"]:
            if "A" in nuevos:
                confirmar_edicion(est["foco"])
            if "B" in nuevos:
                est["editando"] = False
        else:
            if "DPAD_UP" in nuevos:
                est["foco"] = (est["foco"] - 1) % n
            if "DPAD_DOWN" in nuevos:
                est["foco"] = (est["foco"] + 1) % n
            if "DPAD_LEFT" in nuevos:
                ajustar(est["foco"], -1)
            if "DPAD_RIGHT" in nuevos:
                ajustar(est["foco"], 1)
            if "A" in nuevos:
                accionar_a(est["foco"])
            if "X" in nuevos:
                restaurar_defaults()
            if "Y" in nuevos:
                guardar()
            if "B" in nuevos:
                corriendo = False

        dibujar()
        reloj.tick(30)

    pygame.key.stop_text_input()
    pygame.display.quit()


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

        if modo == "config_servidor":
            log.info("--- configurar servidor ---")
            try:
                mostrar_config_servidor()
            except Exception as e:
                log.error("Error en configurar servidor: %s", e)
            continue

        if modo == "config_cliente":
            log.info("--- configurar cliente ---")
            try:
                mostrar_config_cliente()
            except Exception as e:
                log.error("Error en configurar cliente: %s", e)
            continue

        log.info("--- modo STREAMING ---")
        ejecutar_modo_streaming()
        break

    log.info("=== Cerrando ===")


if __name__ == "__main__":
    main()
