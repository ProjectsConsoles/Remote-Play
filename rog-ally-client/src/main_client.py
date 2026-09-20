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
DE UN SOLO HILO (nada de tkinter.after() cooperando con un Mando aparte).

TODO EL PROYECTO LEE EL MANDO EN EL HILO PRINCIPAL (2026-09-11). Hubo un
hilo de fondo (InputSender) para el envio de input durante el streaming;
se elimino porque en Windows SDL no actualiza el estado del joystick fuera
del hilo principal - mandaba sus 105 paquetes por segundo con todos los
botones en cero. Ver _bombear_input_hasta_que_muera().

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

# SDL_JOYSTICK_RAWINPUT=0 (2026-09-12, tiene que ir ANTES de cualquier
# pygame.joystick.init() - el menu ya inicializa el joystick antes que
# streaming, y el hint solo se lee la primera vez). Sin ventana real (driver
# dummy) durante streaming, solo los gatillos (ejes) llegaban - ni un boton
# digital, confirmado con captura real. Sospecha: el backend RawInput de SDL
# para botones en Windows necesita que la ventana tenga foco/sea foreground
# para recibir WM_INPUT, cosa que una ventana dummy invisible nunca tiene;
# los ejes se leen via XInputGetState, que no le importa el foco. Forzando
# XInput puro (sin RawInput) los botones deberian leerse igual que los ejes.
os.environ.setdefault("SDL_JOYSTICK_RAWINPUT", "0")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gamepad_common as gp        # noqa: E402
from brightness_win import Brillo, PCT_MIN   # noqa: E402
import server_udp                  # noqa: E402
import wifi_power                  # noqa: E402
import ui_pygame as ui            # noqa: E402

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


def find_gst():
    """gst-launch-1.0.exe de la carpeta "gstreamer" junto al .exe (2026-09-18).
    Es el runtime MSVC 1.26.11 recortado a los plugins que se usan (ver
    ejecutar_modo_streaming); no se instala nada en Windows."""
    exe = os.path.join(app_dir(), "gstreamer", "bin", "gst-launch-1.0.exe")
    return exe if os.path.isfile(exe) else None


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
    # Enum y no numero porque en la Ally no hay teclado para escribir decimales:
    # asi se ajusta con izquierda/derecha del mando.
    ("PS3RP_ZONA_MUERTA", "Zona muerta de los sticks", "enum", "nada",
     ["nada", "medio", "alta"]),
    ("PS3RP_STREAM_PORT", "Puerto UDP del video", "numero", "5000", None),
    ("PS3RP_FULLSCREEN", "Video en pantalla completa", "bool", "1", None),
    ("PS3RP_PLAYER", "Reproductor de video", "enum", "gstreamer", ["gstreamer", "ffplay"]),
    ("PS3RP_BRILLO", "Brillo en modo control (0-100, vacio = no tocar)", "numero", "", None),
    ("PS3RP_WIFI_SIN_AHORRO", "WiFi sin ahorro de energia (menos delay)", "bool", "1", None),
    ("PS3RP_MODO", "Modo fijo al abrir (vacio = preguntar cada vez)", "enum", "",
     ["", "streaming", "control"]),
]


def cargar_config_guardada():
    # utf-8-sig y no utf-8 (2026-09-11, error real): cualquier editor de
    # Windows que guarde este archivo - el Bloc de notas, o un
    # Set-Content -Encoding UTF8 de PowerShell - le mete un BOM al principio.
    # json.load() con encoding="utf-8" revienta con ese BOM, el except de
    # abajo se lo tragaba en silencio y la app se quedaba usando TODOS los
    # valores por default sin avisar: paso de verdad, y costo un buen rato
    # porque los sintomas no apuntaban al archivo (la IP del ESP32 volvia
    # sola a la de fabrica). utf-8-sig lee bien con BOM y sin BOM.
    if not os.path.isfile(ARCHIVO_CONFIG_CLIENTE):
        return
    try:
        with open(ARCHIVO_CONFIG_CLIENTE, "r", encoding="utf-8-sig") as f:
            datos = json.load(f)
        for k, v in datos.items():
            if v not in (None, ""):
                os.environ.setdefault(k, str(v))
    except Exception as e:
        log.error("No se pudo leer %s (%s): se usan los valores por default.",
                  ARCHIVO_CONFIG_CLIENTE, e)


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


def _botones_pulsados(gp, joystick):
    """Nombres de todos los botones/cruceta/stick pulsados AHORA MISMO (sin
    comparar contra nada). Separado de _botones_nuevos() (2026-09-11) para
    poder arrancar cada pantalla nueva con el estado REAL del mando como
    linea de base - ver la nota larga en _botones_nuevos() sobre por que.

    Se apoya en gp.build_state() a proposito, y no en los indices crudos del
    joystick: asi el menu usa EXACTAMENTE el mismo mapeo normalizado de
    SDL_GameController que el envio de input al ESP32 (ver la nota en
    gamepad_common.py sobre por que los indices crudos no sirven en la Ally,
    donde el mando expone 16 botones y solo la A caia en su lugar)."""
    if joystick is None:
        return set()
    try:
        estado = gp.build_state(joystick)
    except Exception:
        return set()

    botones = {nombre for nombre, v in estado["buttons"].items() if v}

    dx, dy = estado["dpad"]["x"], estado["dpad"]["y"]
    if dx < 0:
        botones.add("DPAD_LEFT")
    elif dx > 0:
        botones.add("DPAD_RIGHT")
    if dy > 0:
        botones.add("DPAD_UP")
    elif dy < 0:
        botones.add("DPAD_DOWN")

    # El stick izquierdo tambien mueve el foco, como en la Deck.
    ax = estado["axes"].get("LSTICK_X", 0.0)
    ay = estado["axes"].get("LSTICK_Y", 0.0)
    if ax < -0.5:
        botones.add("DPAD_LEFT")
    elif ax > 0.5:
        botones.add("DPAD_RIGHT")
    if ay < -0.5:
        botones.add("DPAD_UP")
    elif ay > 0.5:
        botones.add("DPAD_DOWN")

    return botones


def _botones_nuevos(gp, joystick, prev):
    """Botones/cruceta/stick que pasaron de sueltos a pulsados desde la
    ultima vez. Factorizado (2026-09-11) de la logica que ya traia
    mostrar_menu() para que las pantallas nuevas de configuracion no la
    reescriban cada una - mismo patron que deck_gamepad.Mando.nuevos() de la
    Deck, adaptado a pygame directo (aca no hay un lector de mando con
    estado propio, gamepad_common.py solo define el mapeo).

    IMPORTANTE al arrancar una pantalla nueva: inicializar `prev` en `set()`
    hace que CUALQUIER boton que siga fisicamente apretado en el primer
    cuadro (tipico: el mismo B con el que se acaba de salir de la pantalla
    anterior, el dedo no lo suelta tan rapido) se lea como "recien apretado"
    y dispare esa accion de nuevo de inmediato - sintoma real reportado
    2026-09-11: "si presiono B despues de configurar el server ya no me
    regresa al menu, se cierra todo" (el menu se abria y el mismo B, todavia
    apretado, lo cerraba en el primer cuadro). La correccion es usar
    _botones_pulsados() como linea de base de `prev` al ENTRAR a cada
    pantalla, no `set()` - ver donde se llama mas abajo."""
    if joystick is None:
        return set(), prev
    botones = _botones_pulsados(gp, joystick)
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


# Ventana compartida entre pantallas (2026-09-11): antes cada pantalla
# (menu/config servidor/config cliente/modo control) hacia su propio
# pygame.display.quit() al salir y _abrir_ventana() volvia a crear una
# ventana nueva desde cero - eso deja un instante SIN ninguna ventana SDL
# entre pantalla y pantalla, y en ese instante se ve el escritorio de
# Windows de fondo ("parpadeo" reportado 2026-09-11 con la Ally real). Ahora
# la ventana se crea UNA sola vez y se reutiliza mientras se navega entre
# pantallas; solo se cierra de verdad antes de lanzar streaming (ffplay
# maneja su propia ventana) o al salir del programa - ver cerrar_ventana().
_VENTANA = {"screen": None}


def _abrir_ventana(pygame, titulo):
    if _VENTANA["screen"] is not None:
        pygame.display.set_caption(titulo)
        return _VENTANA["screen"]
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
    _VENTANA["screen"] = screen
    return screen


def cerrar_ventana(pygame):
    if _VENTANA["screen"] is not None:
        pygame.display.quit()
        _VENTANA["screen"] = None


# ---------------------------------------------------------------------------
# Menu de arranque y pantallas de configuracion (2026-09-20): mosaicos con icono, igual que el
# cliente Android y la Deck, y una PILA de pantallas con transicion deslizante (abrir: de derecha
# a izquierda; volver: de izquierda a derecha). Las piezas visuales estan en ui_pygame.py.
#
# Todo vive en UNA App con UN lector de mando (2026-09-20): antes cada pantalla era un bucle propio
# que arrancaba con su propia linea base del mando; ahora Configurar servidor / cliente / Info se
# abren dentro del menu y, al volver, nada se re-inicia (ni se cuela un boton que aun se estaba
# soltando). Streaming y solo control siguen siendo cosa de main(): el menu solo devuelve la eleccion.
# ---------------------------------------------------------------------------

class _LectorMando:
    """Lee el mando en el hilo principal (SDL en Windows no actualiza el joystick fuera de el) y da
    solo lo NUEVO desde la ultima vuelta. Arranca con el estado REAL del mando como linea base: un
    boton que aun este apretado al abrir (el B con el que se salio de otra pantalla) no cuenta."""

    def __init__(self):
        import pygame
        self.pygame = pygame
        self.joystick = _joystick_activo(pygame, None)
        self.prev = _botones_pulsados(gp, self.joystick)

    def evento(self, ev):
        if ev.type == self.pygame.JOYDEVICEADDED:
            self.joystick = self.pygame.joystick.Joystick(ev.device_index)
            self.joystick.init()

    def nuevos(self):
        self.joystick = _joystick_activo(self.pygame, self.joystick)
        nuevos, self.prev = _botones_nuevos(gp, self.joystick, self.prev)
        return nuevos


def _texto_estado_servidor(ip_servidor, resp, ip_local):
    """(color, texto) para la tira de estado del menu. `resp` es lo que devuelve obtener_config."""
    if not ip_servidor:
        return ui.TENUE, "Servidor sin configurar: entra a \"Configurar servidor\" para poner su IP."
    ok, datos = resp if resp else (False, "sin respuesta")
    if not ok:
        return ui.ERROR, f"Servidor {ip_servidor}: sin respuesta. ¿Prendido y en la misma red?"
    modo = datos.get("modo") or "?"
    if not datos.get("corriendo"):
        return ui.AVISO, (f"Servidor {ip_servidor}: detenido (modo {modo}). "
                          "Prendelo en la PC o aplica la configuracion.")
    if datos.get("transmitiendo") is False:
        return ui.AVISO, f"Servidor {ip_servidor}: corriendo pero SIN transmitir. Revisa la capturadora."
    destino = datos.get("ip") or ""
    if ip_local and destino and destino != ip_local:
        return ui.AVISO, (f"Servidor {ip_servidor}: transmite a {destino}, no a esta Ally ({ip_local}). "
                          "Entra a \"Configurar servidor\" y manda tu IP.")
    return ui.OK, f"Servidor {ip_servidor}: transmitiendo a {destino} ({modo})"


class PantallaMenu(ui.Pantalla):
    """2x2 de mosaicos (jugar arriba, configurar abajo) y una fila con Info y Salir."""

    def __init__(self, app):
        super().__init__(app)
        esc, ic = self.esc, self.iconos
        self.ip_local = server_udp.obtener_ip_local()
        self.estado = (ui.TENUE, "Servidor: consultando...")
        self._fondo = None
        self._consulta = 0

        self.t_stream = ui.Mosaico(esc, ic, "play", "Streaming", "Video y audio del PS3, mas el control.",
                                   ui.AZUL, on_a=lambda: app.terminar("streaming"),
                                   tam_titulo=32, tam_detalle=16)
        self.t_control = ui.Mosaico(esc, ic, "gamepad", "Solo control", "La Ally funciona solo como mando.",
                                    ui.VERDE, on_a=lambda: app.terminar("control"),
                                    tam_titulo=32, tam_detalle=16)
        self.t_servidor = ui.Mosaico(esc, ic, "server", "Configurar servidor",
                                     "Elige el modo de captura de la PC sin ir a tocarla.", ui.MORADO,
                                     on_a=lambda: app.abrir(PantallaServidor(app)),
                                     tam_titulo=32, tam_detalle=16)
        self.t_cliente = ui.Mosaico(esc, ic, "settings", "Configurar cliente",
                                    "Variables PS3RP_* de este lado (ESP32, input, video).", ui.NARANJA,
                                    on_a=lambda: app.abrir(PantallaCliente(app)),
                                    tam_titulo=32, tam_detalle=16)
        self.t_info = ui.Mosaico(esc, ic, "info", "Info: colores del ESP32-S3", "Y", ui.GRIS,
                                 on_a=lambda: app.abrir(PantallaInfo(app)), tam_titulo=20,
                                 tam_detalle=13, tam_icono=40, horizontal=True)
        self.t_salir = ui.Mosaico(esc, ic, "exit", "Salir", "B o Escape", ui.ROJO_OSCURO,
                                  on_a=lambda: app.terminar(None), tam_titulo=20, tam_detalle=13,
                                  tam_icono=40, horizontal=True)
        self.nav = ui.Navegador([[self.t_stream, self.t_control], [self.t_servidor, self.t_cliente],
                                 [self.t_info, self.t_salir]])

    # --- estado del servidor, en un hilo aparte (la consulta UDP tarda hasta 3 s si no responde) ---
    def al_mostrar(self):
        import threading
        self._consulta += 1
        mia = self._consulta
        self.estado = (ui.TENUE, "Servidor: consultando...")
        fondo = {"listo": False, "ip": None, "resp": None, "id": mia}
        self._fondo = fondo

        def trabajo():
            try:
                fondo["ip"] = server_udp.leer_ip_servidor_guardada()
                if fondo["ip"]:
                    fondo["resp"] = server_udp.obtener_config(fondo["ip"])
            except Exception as e:
                fondo["resp"] = (False, str(e))
            fondo["listo"] = True

        threading.Thread(target=trabajo, daemon=True).start()

    def dibujar(self, surf):
        f = self._fondo
        if f is not None and f["listo"] and f["id"] == self._consulta:
            self.estado = _texto_estado_servidor(f["ip"], f["resp"], self.ip_local)
            self._fondo = None
        esc = self.esc
        surf.fill(ui.FONDO)
        w, h = surf.get_size()
        m = esc.px(24)
        x, ancho = m, w - 2 * m
        y = esc.px(16)
        y += ui.dibujar_cabecera(surf, esc, x, y, ancho, "PS3 Remote Play",
                                 f"IP: {self.ip_local}" if self.ip_local else "") + esc.px(6)
        color, texto = self.estado
        alto_t = ui.alto_tira(esc, texto, ancho)
        ui.dibujar_tira(surf, esc, pygame_rect(x, y, ancho, alto_t), color, texto)
        y += alto_t + esc.px(10)

        alto_pie = esc.px(84)
        ui.texto_en(surf, esc.fuente(13), "Flechas/stick + Enter/A, Escape/B cancela, Y colores del ESP32.   "
                    "(mouse/touch siempre funciona)", ui.TENUE, w // 2, h - esc.px(10), "midbottom")
        y_pie = h - esc.px(34) - alto_pie
        hueco = esc.px(14)
        alto_fila = (y_pie - y - hueco * 2) // 2
        for i, fila in enumerate(([self.t_stream, self.t_control], [self.t_servidor, self.t_cliente])):
            celdas = ui.columnas(pygame_rect(x, y + i * (alto_fila + hueco), ancho, alto_fila), 2, hueco)
            for t, r in zip(fila, celdas):
                t.dibujar(surf, r, self.nav.es_foco(t))
        celdas = ui.columnas(pygame_rect(x, y_pie, ancho, alto_pie), 2, hueco)
        for t, r in zip((self.t_info, self.t_salir), celdas):
            t.dibujar(surf, r, self.nav.es_foco(t))

    def boton(self, nombre):
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
        elif nombre == "Y":
            self.app.abrir(PantallaInfo(self.app))
        elif nombre == "B":
            self.app.terminar(None)


def pygame_rect(x, y, w, h):
    import pygame
    return pygame.Rect(x, y, w, h)


LEDS = [
    ((212, 177, 6), "Amarillo", "PS3", (27, 27, 27)),
    (ui.AZUL, "Azul", "PS2 / OPL", ui.BLANCO),
    (ui.MORADO, "Morado", "Xbox 360", ui.BLANCO),
    ((47, 168, 79), "Verde", "Xbox clasico", ui.BLANCO),
]


class PantallaInfo(ui.Pantalla):
    """Colores del LED del ESP32-S3 (selector de modo). 2026-09-13: "se me olvidan los colores"."""

    def __init__(self, app):
        super().__init__(app)
        esc, ic = self.esc, self.iconos
        self.leds = [ui.Mosaico(esc, ic, "gamepad", nombre, consola, color, color_texto=ct,
                                tam_titulo=32, tam_detalle=18, interactivo=False)
                     for color, nombre, consola, ct in LEDS]
        self.t_volver = ui.Mosaico(esc, ic, "back", "Volver", "A o B", ui.GRIS, on_a=app.volver,
                                   tam_titulo=22, tam_detalle=13, tam_icono=40, horizontal=True)
        self.nav = ui.Navegador([[self.t_volver]])

    def dibujar(self, surf):
        esc = self.esc
        surf.fill(ui.FONDO)
        w, h = surf.get_size()
        m = esc.px(24)
        x, ancho = m, w - 2 * m
        y = esc.px(16) + ui.dibujar_cabecera(surf, esc, x, esc.px(16), ancho, "Selector de modo del ESP32-S3") + esc.px(8)
        f = esc.fuente(15)
        for ln in ui.envolver(f, "Con la placa ya encendida (nunca al conectarla o resetearla), mantén BOOT ~1.5 s. "
                                 "El LED cicla de color cada ~0.7 s; suelta el botón en el color que corresponda.",
                              ancho):
            ui.texto_en(surf, f, ln, ui.TENUE, x, y)
            y += f.get_linesize()
        y += esc.px(10)
        alto_pie = esc.px(84)
        y_pie = h - m - alto_pie
        ui.texto_en(surf, esc.fuente(14), "El modo elegido queda guardado en la placa hasta que se cambie a mano.",
                    ui.TENUE, x, y_pie - esc.px(10), "bottomleft")
        hueco = esc.px(14)
        alto_leds = y_pie - esc.px(40) - y
        for t, r in zip(self.leds, ui.columnas(pygame_rect(x, y, ancho, alto_leds), len(self.leds), hueco)):
            t.dibujar(surf, r, False)
        self.t_volver.dibujar(surf, pygame_rect(x, y_pie, ancho, alto_pie), True)

    def boton(self, nombre):
        if nombre in ("A", "B"):
            self.app.volver()


# --- Configurar servidor: mismo protocolo UDP (puerto 9200) que la Deck contra config_listener.ps1 ---
MODOS_SERVIDOR = [
    ("mjpeg720", "1280x720 - MJPEG (recomendado)", "60 fps estables, ~6 Mbps de wifi."),
    ("mjpeg1080", "1920x1080 - MJPEG (mas nitido)", "Mas definido, pero sube a 8 Mbps."),
    ("crudo480", "720x480 - SIN COMPRIMIR (prueba)", "Salta el MJPEG, 5x mas datos por USB."),
    ("crudo640", "640x480 - SIN COMPRIMIR (prueba)", "Igual pero pide menos por el USB."),
    ("crudo720", "1280x720 - SIN COMPRIMIR (Hagibis)",
     "Salta el MJPEG a 720p - solo si tu capturadora lo sostiene a 60fps (la 'Hagibis' si)."),
]

IP_SERVIDOR_DEFAULT = "192.168.0.90"


class PantallaServidor(ui.Pantalla):
    """Modo de captura del servidor Windows en remoto. Atajos del mando (los de siempre de la Ally):
    A aplica (sobre un modo) o ejecuta el mosaico enfocado, X consulta, Y manda la IP, L1 reinicia,
    R1 apaga, B vuelve. La fila de modos sigue al foco; tocar un modo solo lo elige."""

    def __init__(self, app):
        super().__init__(app)
        esc, ic = self.esc, self.iconos
        self.ip_ally = server_udp.obtener_ip_local() or "?"
        self.ip = server_udp.leer_ip_servidor_guardada() or IP_SERVIDOR_DEFAULT
        self.sel = 0
        self.msg = (ui.TENUE, "Sin consultar todavia.")
        self._consultado = False

        self.t_ip = ui.Mosaico(esc, ic, "server", self.ip, "IP del servidor Windows  (A o tocar para cambiarla)",
                               ui.MORADO, on_a=self.editar_ip, tam_titulo=26, tam_detalle=14,
                               tam_icono=40, horizontal=True)
        self.t_ally = ui.Mosaico(esc, ic, "wifi", self.ip_ally, "IP de esta Ally (a donde llega el video)",
                                 ui.GRIS, tam_titulo=26, tam_detalle=14, tam_icono=40, horizontal=True,
                                 interactivo=False)
        self.t_modos = [ui.Mosaico(esc, ic, "image", nombre, detalle, ui.MORADO, tam_titulo=18,
                                   tam_detalle=13, tam_icono=40, on_a=self.aplicar, on_click=lambda: None)
                        for _c, nombre, detalle in MODOS_SERVIDOR]

        def accion(icono, titulo, detalle, color, fn):
            return ui.Mosaico(esc, ic, icono, titulo, detalle, color, on_a=fn, tam_titulo=20,
                              tam_detalle=13, tam_icono=40)

        self.t_acciones = [
            accion("refresh", "Consultar (X)", "Estado del servidor", ui.AZUL, self.consultar),
            accion("wifi", "Enviar IP (Y)", "Manda la IP de esta Ally", ui.AZUL, self.enviar_ip),
            accion("check", "Aplicar (A)", "Pone el modo marcado", ui.VERDE, self.aplicar),
            accion("refresh", "Reiniciar (L1)", "Reinicia el servidor", ui.NARANJA_OSCURO, self.reiniciar_servidor),
            accion("power", "Apagar (R1)", "Detiene la transmision", ui.ROJO, self.apagar_servidor),
        ]
        self.t_volver = ui.Mosaico(esc, ic, "back", "Volver (B)", "", ui.GRIS, on_a=app.volver,
                                   tam_titulo=20, tam_icono=40, horizontal=True)
        self.nav = ui.Navegador([[self.t_ip], self.t_modos, self.t_acciones, [self.t_volver]],
                                al_cambiar=self._al_cambiar, recordar=True)

    # --- estado --------------------------------------------------------------------------------------
    def _al_cambiar(self, t):
        if t in self.t_modos:      # el foco sobre un modo LO ELIGE: el marcado es el que Aplicar usa
            self.sel = self.t_modos.index(t)

    def _elegir_modo(self, clave):
        for i, (c, _n, _d) in enumerate(MODOS_SERVIDOR):
            if c == clave:
                self.sel = i
                self.nav.memoria[1] = i

    def _msg(self, color, texto):
        self.msg = (color, texto)
        self.app.redibujar()

    def al_mostrar(self):
        # La primera vez (ya terminada la animacion, para no congelarla) consulta al servidor.
        if not self._consultado:
            self._consultado = True
            self.consultar()

    def editar_ip(self):
        def aceptar(valor):
            self.ip = valor
            self.t_ip.titulo = valor or "(sin IP)"
        ui.DialogoTexto(self.app, "IP del servidor Windows", self.ip, "ip", aceptar)

    # --- acciones de red (mismos mensajes y flujo que antes) ---------------------------------------
    def consultar(self):
        self._msg(ui.TENUE, "Consultando...")
        ok, resp = server_udp.obtener_config(self.ip)
        if not ok:
            self._msg(ui.ERROR, str(resp))
            return
        server_udp.guardar_ip_servidor(self.ip)
        corriendo = "SI" if resp.get("corriendo") else "no"
        texto = f"Corriendo: {corriendo}  ·  Modo actual: {resp.get('modo') or '(ninguno guardado)'}"
        # IP sincronizada (2026-09-13): solo tiene sentido si el servidor esta corriendo - apagado,
        # "ip" es la ultima que quedo guardada de una corrida vieja.
        if resp.get("corriendo"):
            tiene = resp.get("ip")
            if tiene == self.ip_ally:
                texto += f"\nIP sincronizada: SI (le manda el video a {self.ip_ally})"
            else:
                texto += f"\nIP sincronizada: NO (le manda el video a {tiene or '?'}, no a esta Ally)"
        self._msg(ui.OK if resp.get("corriendo") else ui.TENUE, texto)
        self._elegir_modo(resp.get("modo"))

    def aplicar(self):
        clave = MODOS_SERVIDOR[self.sel][0]
        self._msg(ui.TENUE, "Aplicando... si el servidor ya esta corriendo, puede tardar unos segundos.")
        ok, resp = server_udp.aplicar_config(self.ip, self.ip_ally, clave)
        if not ok:
            self._msg(ui.ERROR, str(resp))
            return
        server_udp.guardar_ip_servidor(self.ip)
        aplicado = resp.get("aplicado")
        if aplicado == "reiniciado":
            self._msg(ui.OK, "Listo: servidor reiniciado con la config nueva.")
        elif aplicado == "guardado_para_proxima_vez":
            self._msg(ui.OK, "Guardado. Se aplicara la proxima vez que le den Iniciar.")
        else:
            self._msg(ui.ERROR, str(resp))

    def enviar_ip(self):
        # Manda la IP de ESTA Ally sin tocar el modo: consulta el modo actual del servidor y se lo
        # vuelve a mandar junto con la IP nueva (mismo pedido que en la Deck, 2026-09-11).
        self._msg(ui.TENUE, "Consultando modo actual del servidor...")
        ok, resp = server_udp.obtener_config(self.ip)
        if not ok:
            self._msg(ui.ERROR, str(resp))
            return
        modo_actual = resp.get("modo") or MODOS_SERVIDOR[self.sel][0]
        self._msg(ui.TENUE, f"Enviando IP de esta Ally ({self.ip_ally})...")
        ok, resp = server_udp.aplicar_config(self.ip, self.ip_ally, modo_actual)
        if not ok:
            self._msg(ui.ERROR, str(resp))
            return
        server_udp.guardar_ip_servidor(self.ip)
        if resp.get("aplicado") == "reiniciado":
            self._msg(ui.OK, f"IP enviada ({self.ip_ally}). Servidor reiniciado con el mismo modo.")
        else:
            self._msg(ui.OK, f"IP enviada ({self.ip_ally}). Se aplicara la proxima vez que arranque.")
        self._elegir_modo(modo_actual)

    def reiniciar_servidor(self):
        # Mismo mecanismo que "Enviar IP" (set_config con el modo actual sin cambiarlo).
        self._msg(ui.TENUE, "Consultando servidor antes de reiniciar...")
        ok, resp = server_udp.obtener_config(self.ip)
        if not ok:
            self._msg(ui.ERROR, str(resp))
            return
        if not resp.get("corriendo"):
            self._msg(ui.TENUE, "El servidor no esta corriendo; no hay nada que reiniciar.")
            return
        modo_actual = resp.get("modo") or MODOS_SERVIDOR[self.sel][0]
        self._msg(ui.TENUE, "Reiniciando servidor... puede tardar unos segundos.")
        ok, resp2 = server_udp.aplicar_config(self.ip, self.ip_ally, modo_actual)
        if not ok:
            self._msg(ui.ERROR, str(resp2))
            return
        server_udp.guardar_ip_servidor(self.ip)
        if resp2.get("aplicado") == "reiniciado":
            self._msg(ui.OK, "Listo: servidor reiniciado.")
        else:
            self._msg(ui.ERROR, str(resp2))

    def apagar_servidor(self):
        # stop_server (2026-09-17): a diferencia de reiniciar, esto SOLO apaga.
        if not self.ip:
            self._msg(ui.ERROR, "Pon una IP primero.")
            return
        self._msg(ui.TENUE, "Apagando servidor...")
        ok, resp = server_udp.detener_servidor(self.ip)
        if not ok:
            self._msg(ui.ERROR, str(resp))
            return
        if resp.get("aplicado") == "detenido":
            self._msg(ui.OK, "Listo: servidor apagado.")
        else:
            self._msg(ui.TENUE, "El servidor ya estaba apagado.")

    # --- dibujo y mando ---------------------------------------------------------------------------------
    def dibujar(self, surf):
        esc = self.esc
        surf.fill(ui.FONDO)
        w, h = surf.get_size()
        m = esc.px(24)
        x, ancho = m, w - 2 * m
        y = esc.px(16)
        y += ui.dibujar_cabecera(surf, esc, x, y, ancho, "Configurar servidor",
                                 f"Esta Ally: {self.ip_ally}") + esc.px(6)
        color, texto = self.msg
        alto_t = ui.alto_tira(esc, texto, ancho)
        ui.dibujar_tira(surf, esc, pygame_rect(x, y, ancho, alto_t), color, texto)
        y += alto_t + esc.px(8)

        for i, t in enumerate(self.t_modos):
            t.marcado = i == self.sel
        hueco = esc.px(12)
        alto_ip, alto_acc, alto_pie = esc.px(92), esc.px(124), esc.px(72)
        ui.texto_en(surf, esc.fuente(13), "Cruceta: mueve el foco. A ejecuta (sobre un modo, lo aplica). "
                    "X consulta, Y manda la IP, L1 reinicia, R1 apaga, B vuelve.",
                    ui.TENUE, w // 2, h - esc.px(8), "midbottom")
        y_pie = h - esc.px(30) - alto_pie
        y_acc = y_pie - hueco - alto_acc
        alto_modos = max(esc.px(120), y_acc - hueco - (y + alto_ip + hueco))
        for t, r in zip((self.t_ip, self.t_ally), ui.columnas(pygame_rect(x, y, ancho, alto_ip), 2, hueco)):
            t.dibujar(surf, r, self.nav.es_foco(t))
        y_modos = y + alto_ip + hueco
        for t, r in zip(self.t_modos, ui.columnas(pygame_rect(x, y_modos, ancho, alto_modos), 5, hueco)):
            t.dibujar(surf, r, self.nav.es_foco(t))
        for t, r in zip(self.t_acciones, ui.columnas(pygame_rect(x, y_acc, ancho, alto_acc), 5, hueco)):
            t.dibujar(surf, r, self.nav.es_foco(t))
        self.t_volver.dibujar(surf, pygame_rect(x, y_pie, ancho, alto_pie), self.nav.es_foco(self.t_volver))

    def boton(self, nombre):
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
        elif nombre == "X":
            self.consultar()
        elif nombre == "Y":
            self.enviar_ip()
        elif nombre == "L1":
            self.reiniciar_servidor()
        elif nombre == "R1":
            self.apagar_servidor()
        elif nombre == "B":
            self.app.volver()


# --- Configurar cliente: las variables PS3RP_* de la Ally (ally_config.json) --------------------------
# (icono, color) de cada variable; los booleanos se pintan verde/gris segun su valor.
ESTILO_CAMPOS = {
    "PS3RP_ESP32_IP": ("wifi", ui.AZUL), "PS3RP_ESP32_PORT": ("port", ui.AZUL),
    "PS3RP_STREAM_PORT": ("port", ui.AZUL),
    "PS3RP_INPUT": ("gamepad", ui.VERDE), "PS3RP_INPUT_RATE": ("speed", ui.VERDE),
    "PS3RP_PS_COMBO": ("gamepad", ui.VERDE), "PS3RP_ZONA_MUERTA": ("tune", ui.VERDE),
    "PS3RP_FULLSCREEN": ("image", ui.NARANJA), "PS3RP_PLAYER": ("play", ui.NARANJA),
    "PS3RP_BRILLO": ("tune", ui.NARANJA),
    "PS3RP_WIFI_SIN_AHORRO": ("wifi", ui.MORADO), "PS3RP_MODO": ("info", ui.MORADO),
}
COLUMNAS_CLIENTE = 3


class PantallaCliente(ui.Pantalla):
    """Cada variable es un mosaico que muestra su VALOR. A cambia (en textos y numeros abre un cuadro
    para escribirlo); L1 / R1 = valor anterior / siguiente (en los numeros, -1 / +1); X restaura los
    defaults (sin guardar todavia), Y guarda, B vuelve."""

    def __init__(self, app):
        super().__init__(app)
        esc, ic = self.esc, self.iconos
        guardado = {}
        if os.path.isfile(ARCHIVO_CONFIG_CLIENTE):
            try:
                with open(ARCHIVO_CONFIG_CLIENTE, "r", encoding="utf-8-sig") as f:
                    guardado = json.load(f)
            except Exception:
                guardado = {}
        self.valores = {var: str(guardado.get(var, default)) for var, _e, _t, default, _o in CAMPOS_CLIENTE}
        self.msg = (ui.TENUE, "Cruceta: mover · A: cambiar · L1/R1: anterior / siguiente · X restaurar · Y guardar · B volver")
        self.tiles = []
        for i, (var, etiqueta, _tipo, _d, _o) in enumerate(CAMPOS_CLIENTE):
            icono, color = ESTILO_CAMPOS.get(var, ("settings", ui.AZUL))
            t = ui.Mosaico(esc, ic, icono, "", etiqueta, color, on_a=lambda i=i: self._a(i),
                           tam_titulo=24, tam_detalle=13, tam_icono=40)
            t.color_base = color
            self.tiles.append(t)
        self.t_guardar = ui.Mosaico(esc, ic, "check", "Guardar (Y)", "", ui.AZUL, on_a=self.guardar,
                                    tam_titulo=20, tam_icono=40, horizontal=True)
        self.t_restaurar = ui.Mosaico(esc, ic, "refresh", "Restaurar (X)", "", ui.GRIS,
                                      on_a=self.restaurar_defaults, tam_titulo=20, tam_icono=40,
                                      horizontal=True)
        self.t_volver = ui.Mosaico(esc, ic, "back", "Volver (B)", "", ui.GRIS, on_a=app.volver,
                                   tam_titulo=20, tam_icono=40, horizontal=True)
        filas = [self.tiles[i:i + COLUMNAS_CLIENTE] for i in range(0, len(self.tiles), COLUMNAS_CLIENTE)]
        self.filas_tiles = filas
        self.nav = ui.Navegador(filas + [[self.t_guardar, self.t_restaurar, self.t_volver]])

    def _visible(self, i):
        var, _e, tipo, _d, _o = CAMPOS_CLIENTE[i]
        if tipo == "bool":
            return "SI" if self.valores[var] == "1" else "NO"
        if tipo == "enum":
            return self.valores[var] if self.valores[var] else "(preguntar)"
        return self.valores[var] if self.valores[var] != "" else "(vacio)"

    def _ajustar(self, i, delta):
        var, _e, tipo, _d, opciones = CAMPOS_CLIENTE[i]
        if tipo == "numero":
            try:
                base = int(self.valores[var]) if self.valores[var].strip() else 0
            except ValueError:
                base = 0
            self.valores[var] = str(base + delta)
        elif tipo == "bool":
            self.valores[var] = "0" if self.valores[var] == "1" else "1"
        elif tipo == "enum":
            actual = opciones.index(self.valores[var]) if self.valores[var] in opciones else 0
            self.valores[var] = opciones[(actual + delta) % len(opciones)]

    def _a(self, i):
        var, etiqueta, tipo, _d, _o = CAMPOS_CLIENTE[i]
        if tipo in ("texto", "numero"):
            filtro = "num" if tipo == "numero" else ("ip" if var == "PS3RP_ESP32_IP" else "texto")

            def aceptar(valor):
                self.valores[var] = valor
            ui.DialogoTexto(self.app, etiqueta, self.valores[var], filtro, aceptar)
        else:
            self._ajustar(i, 1)

    def guardar(self):
        if guardar_config_cliente(self.valores):
            self.msg = (ui.OK, "Guardado. Se aplica la proxima vez que arranques streaming/control.")
        else:
            self.msg = (ui.ERROR, "No se pudo guardar (revisa permisos de la carpeta).")

    def restaurar_defaults(self):
        self.valores = {var: default for var, _e, _t, default, _o in CAMPOS_CLIENTE}
        try:
            if os.path.isfile(ARCHIVO_CONFIG_CLIENTE):
                os.remove(ARCHIVO_CONFIG_CLIENTE)
        except Exception:
            pass
        self.msg = (ui.TENUE, "Restaurado a los defaults (sin guardar todavia).")

    def dibujar(self, surf):
        esc = self.esc
        surf.fill(ui.FONDO)
        w, h = surf.get_size()
        m = esc.px(24)
        x, ancho = m, w - 2 * m
        y = esc.px(16)
        y += ui.dibujar_cabecera(surf, esc, x, y, ancho, "Configurar cliente", "Vacío = usar el default") + esc.px(6)
        color, texto = self.msg
        alto_t = ui.alto_tira(esc, texto, ancho, 46)
        ui.dibujar_tira(surf, esc, pygame_rect(x, y, ancho, alto_t), color, texto)
        y += alto_t + esc.px(8)

        hueco = esc.px(12)
        alto_pie = esc.px(72)
        y_pie = h - esc.px(14) - alto_pie
        n_filas = len(self.filas_tiles)
        alto_fila = max(esc.px(96), min(esc.px(150), (y_pie - hueco - y - hueco * (n_filas - 1)) // n_filas))
        for i, t in enumerate(self.tiles):
            var, _e, tipo, _d, _o = CAMPOS_CLIENTE[i]
            t.titulo = self._visible(i)
            if tipo == "bool":
                t.color = ui.VERDE if self.valores[var] == "1" else ui.GRIS
        for fi, fila in enumerate(self.filas_tiles):
            celdas = ui.columnas(pygame_rect(x, y + fi * (alto_fila + hueco), ancho, alto_fila),
                                 COLUMNAS_CLIENTE, hueco)
            for t, r in zip(fila, celdas):
                t.dibujar(surf, r, self.nav.es_foco(t))
        celdas = ui.columnas(pygame_rect(x, y_pie, ancho, alto_pie), 3, hueco)
        for t, r in zip((self.t_guardar, self.t_restaurar, self.t_volver), celdas):
            t.dibujar(surf, r, self.nav.es_foco(t))

    def boton(self, nombre):
        if nombre == "DPAD_UP":
            self.nav.mover(0, -1)
        elif nombre == "DPAD_DOWN":
            self.nav.mover(0, 1)
        elif nombre == "DPAD_LEFT":
            self.nav.mover(-1, 0)
        elif nombre == "DPAD_RIGHT":
            self.nav.mover(1, 0)
        elif nombre == "A":
            self.nav.activar()
        elif nombre in ("L1", "R1"):
            t = self.nav.actual()
            if t in self.tiles:
                self._ajustar(self.tiles.index(t), -1 if nombre == "L1" else 1)
        elif nombre == "X":
            self.restaurar_defaults()
        elif nombre == "Y":
            self.guardar()
        elif nombre == "B":
            self.app.volver()


def mostrar_menu():
    """Devuelve 'streaming', 'control' o None si cancelo. Configurar servidor, Configurar cliente e
    Info se abren dentro del menu (con transicion deslizante); al volver se esta otra vez en el menu."""
    import pygame
    if "SDL_VIDEODRIVER" in os.environ and os.environ["SDL_VIDEODRIVER"] == "dummy":
        del os.environ["SDL_VIDEODRIVER"]
    pygame.init()
    screen = _abrir_ventana(pygame, "PS3 Remote Play")
    app = ui.App(screen, _LectorMando())
    app.abrir_inicial(PantallaMenu(app))
    return app.ejecutar()


# ---------------------------------------------------------------------------
# Modo "solo control" - un solo hilo: lee mando, manda UDP Y dibuja, todo en
# la misma vuelta de loop.
#
# POR QUE NO SE USA UN HILO DE FONDO ACA (2026-09-07): SDL/pygame espera que
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

    # EL BRILLO SE LEE EN UN HILO APARTE (2026-09-11, LA causa de "se siente
    # trabado"). brillo.leer_pct() lanza un proceso de PowerShell - en Windows
    # eso cuesta entre 300 y 600 ms - y se llamaba UNA VEZ POR SEGUNDO dentro
    # de este mismo bucle. O sea que el bucle de input se congelaba medio
    # segundo, cada segundo: por eso al ESP32 le llegaban ~50 estados/s en vez
    # de 120, los botones respondian tarde, se perdian pulsaciones, y una
    # direccion de la cruceta se quedaba "sonando" mas tiempo del que se
    # tocaba (el ESP32 sigue reenviando el ultimo estado recibido), que es lo
    # que se sentia como que el cursor se movia solo.
    #
    # La Deck no lo sufre porque ahi el brillo sale de un archivo de sysfs, que
    # se lee al instante. Aca se hace en un hilo: no toca SDL ni pygame (solo
    # subprocess y un numero), asi que no aplica la regla de "el mando solo se
    # lee en el hilo principal".
    _parar_brillo = threading.Event()
    _brillo_visto = {"pct": None}

    def _leer_brillo_en_segundo_plano():
        while not _parar_brillo.is_set():
            try:
                v = brillo.leer_pct()
                if v is not None:
                    _brillo_visto["pct"] = v
            except Exception:
                pass
            _parar_brillo.wait(1.0)

    if brillo.ok:
        threading.Thread(target=_leer_brillo_en_segundo_plano, daemon=True).start()

    arrastrando_barra = False
    ultimo_toque_barra = 0.0
    texto_pulsado = ""

    salir = False
    ultima_firma = None
    ultimo_dibujo = 0.0
    # Instrumentacion del ritmo (2026-09-11): el input llegaba al ESP32 a ~50/s
    # en vez de 120 y no estaba claro donde se iba el tiempo. Se mide y se deja
    # en el log cada 5s.
    m_vueltas = 0
    m_envios = 0
    m_t_leer = 0.0
    m_t_dibujar = 0.0
    m_desde = time.time()

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
        if brillo.ok and not arrastrando_barra and (ahora - ultimo_toque_barra) > 3:
            real = _brillo_visto["pct"]
            if real is not None and abs(real - pct_actual) >= 1:
                pct_actual = real

        # Un solo pump/lectura del mando por vuelta: se usa para mandar UDP y
        # para el indicador. Reconecta solo si hace falta.
        estado = None
        if joystick is None and pygame.joystick.get_count() > 0:
            joystick = pygame.joystick.Joystick(0)
            joystick.init()
        if joystick is not None:
            try:
                _t0 = time.perf_counter()
                estado = gp.build_state(joystick)
                m_t_leer += time.perf_counter() - _t0
            except Exception:
                joystick = None

        if estado is not None:
            texto_pulsado = gp.etiquetar([k for k, v in estado["buttons"].items() if v])
            if sock is not None and ahora >= proximo_envio:
                try:
                    sock.sendto(json.dumps(estado).encode("utf-8"), (ESP32_IP, ESP32_PORT))
                except OSError:
                    pass
                m_envios += 1
                proximo_envio = ahora + interval
        else:
            texto_pulsado = ""

        # SOLO SE REDIBUJA SI CAMBIO ALGO (2026-09-11, medido). Redibujar
        # la pantalla completa cuesta ~50 ms en la Ally, y durante ese rato
        # el bucle no manda input: por eso al ESP32 le llegaban ~45
        # paquetes/s aunque entre cuadro y cuadro se mandara a 120. Esta
        # pantalla es casi toda texto fijo, asi que se redibuja solo cuando
        # cambia lo que muestra (botones pulsados o brillo), o una vez cada
        # medio segundo para que no se vea congelada.
        firma = (texto_pulsado, pct_actual, arrastrando_barra)
        if firma != ultima_firma or (ahora - ultimo_dibujo) > 0.5:
            ultima_firma = firma
            ultimo_dibujo = ahora
            _td = time.perf_counter()
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
            m_t_dibujar += time.perf_counter() - _td

        m_vueltas += 1
        if ahora - m_desde >= 5.0:
            _span = ahora - m_desde
            log.debug("[ritmo] %.0f vueltas/s  %.0f envios/s  leer_mando=%.1fms/vuelta  dibujar=%.0fms total",
                     m_vueltas / _span, m_envios / _span,
                     (m_t_leer / max(1, m_vueltas)) * 1000.0, m_t_dibujar * 1000.0)
            m_vueltas = m_envios = 0
            m_t_leer = m_t_dibujar = 0.0
            m_desde = ahora

        # Con el dibujo salteado, la vuelta es barata y el envio de arriba
        # corre a su ritmo real. El respiro es para no quemar CPU (y bateria)
        # girando en vacio.
        time.sleep(0.001)

    _parar_brillo.set()
    if sock is not None:
        sock.close()


# ---------------------------------------------------------------------------
# Modo streaming: lanza ffplay y espera a que se cierre.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Ventana "de foco" durante el streaming (2026-09-18).
# ---------------------------------------------------------------------------
# En Modo Juego de la Ally (Armoury Crate) el mando SOLO le llega al proceso
# que tiene la ventana en primer plano: con ffplay (proceso aparte) al frente
# y este proceso con SDL en driver "dummy" (sin ventana), SDL y XInput leian
# todo en cero - medido en el log ([botones] sin cambios aunque se apretaran).
# En Modo Escritorio no pasa, y el menu (ventana propia al frente) tampoco.
# Solucion: mientras dura el streaming este proceso tiene su propia ventana,
# del tamano de la pantalla, casi invisible (alpha 1/255), transparente al
# raton/toque (WS_EX_TRANSPARENT), sin boton en la barra (TOOLWINDOW) - y la
# mantiene en primer plano. ffplay se ve igual. SOLO se la quita a ffplay: si
# el usuario abre el overlay de Armoury Crate o el boton Xbox, no se pelea.
# PS3RP_FOCO_INPUT=0 desactiva todo esto (comportamiento anterior).

FOCO_INPUT = os.environ.get("PS3RP_FOCO_INPUT", "1") == "1"
_FOCO = {"hwnd": None}


def _crear_ventana_foco(pygame):
    if not FOCO_INPUT:
        return
    try:
        pygame.display.init()
        info = pygame.display.Info()
        pygame.display.set_mode((info.current_w, info.current_h), pygame.NOFRAME)
        pygame.display.set_caption("PS3RP input")
        hwnd = pygame.display.get_wm_info()["window"]
        u = ctypes.windll.user32
        GWL_EXSTYLE, LWA_ALPHA = -20, 2
        WS_EX_LAYERED, WS_EX_TRANSPARENT, WS_EX_TOOLWINDOW = 0x80000, 0x20, 0x80
        estilo = u.GetWindowLongW(hwnd, GWL_EXSTYLE)
        u.SetWindowLongW(hwnd, GWL_EXSTYLE,
                         estilo | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW)
        u.SetLayeredWindowAttributes(hwnd, 0, 1, LWA_ALPHA)
        _FOCO["hwnd"] = hwnd
        _tomar_foco(hwnd)
        log.info("Ventana de foco creada (hwnd=%s) para recibir el mando en Modo Juego", hwnd)
    except Exception as e:
        _FOCO["hwnd"] = None
        log.warning("No se pudo crear la ventana de foco (%s); sigue sin ella", e)


def _tomar_foco(hwnd):
    try:
        u = ctypes.windll.user32
        k = ctypes.windll.kernel32
        fg = u.GetForegroundWindow()
        if fg == hwnd:
            return
        tid_fg = u.GetWindowThreadProcessId(fg, None) if fg else 0
        tid_yo = k.GetCurrentThreadId()
        # AttachThreadInput: Windows solo deja robar el primer plano a quien
        # ya comparte la cola de entrada con la ventana actual.
        enlazado = bool(tid_fg and tid_fg != tid_yo
                        and u.AttachThreadInput(tid_yo, tid_fg, True))
        u.SetForegroundWindow(hwnd)
        u.BringWindowToTop(hwnd)
        if enlazado:
            u.AttachThreadInput(tid_yo, tid_fg, False)
    except Exception as e:
        log.debug("No se pudo tomar el foco: %s", e)


def _mantener_foco(pid_ffplay):
    """Si ffplay tiene el primer plano, se lo quita; con cualquier otra
    ventana (overlays de Armoury Crate/Xbox) no hace nada."""
    hwnd = _FOCO["hwnd"]
    if hwnd is None:
        return
    try:
        u = ctypes.windll.user32
        fg = u.GetForegroundWindow()
        if fg == hwnd:
            return
        pid = ctypes.c_ulong(0)
        u.GetWindowThreadProcessId(fg, ctypes.byref(pid))
        if pid.value == pid_ffplay:
            _tomar_foco(hwnd)
    except Exception:
        pass


def _iniciar_input_streaming():
    """Abre SDL/el mando ANTES de lanzar ffplay - devuelve (sock, socket UDP)
    o None si ENABLE_INPUT esta apagado.

    ORDEN CRITICO (2026-09-12, LA causa de "solo jala el gatillo en
    streaming"). Capturando el JSON real que sale durante streaming de
    verdad (con ffplay corriendo, no en loopback): los EJES (L2_ANALOG/
    R2_ANALOG, via SDL_GameController) llegaban perfectos, pero NINGUN
    boton digital (A/B/X/Y/L1/R1, ni la cruceta por el hat) aparecia
    pulsado nunca, por mas que se apretaran. La diferencia con modo control
    (donde todo funciona) es que ahi no hay ningun otro proceso tocando el
    mando; en streaming, ffplay (tambien SDL2) se lanzaba ANTES de que este
    proceso abriera el joystick - y en Windows, el primero en abrir un HID
    gamepad puede quedarse con acceso exclusivo a los REPORTES DE BOTONES
    (los ejes, que muchos drivers exponen por un canal XInput mas simple,
    no se ven afectados igual). O sea: ffplay se quedaba con los botones.
    Se invierte el orden: este proceso abre el mando PRIMERO, ffplay se
    lanza despues y ya no tiene con que competir."""
    if not ENABLE_INPUT:
        return None

    import pygame
    if FOCO_INPUT:
        # Driver de video REAL para poder tener la ventana de foco (ver
        # _crear_ventana_foco); si no se puede crear, cae al dummy de antes.
        os.environ.pop("SDL_VIDEODRIVER", None)
    else:
        os.environ["SDL_VIDEODRIVER"] = "dummy"
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    pygame.init()
    pygame.display.init()
    pygame.joystick.init()
    _crear_ventana_foco(pygame)
    if FOCO_INPUT and _FOCO["hwnd"] is None:
        pygame.display.quit()
        os.environ["SDL_VIDEODRIVER"] = "dummy"
        pygame.display.init()
    # SDL se acaba de rehacer (se cerro la ventana del menu y se reinicio con
    # el driver dummy): el mando abierto en el contexto anterior quedo
    # invalido y devolvia valores pegados - ver reiniciar_mapeo().
    gp.reiniciar_mapeo()
    return socket.socket(socket.AF_INET, socket.SOCK_DGRAM)


# ---------------------------------------------------------------------------
# Diagnostico de entrada (2026-09-18): "en Modo Juego de la Ally (Armoury
# Crate) el streaming no manda los controles, en Escritorio si". Antes el log
# solo decia "mando=True" y no habia forma de saber SI LLEGABAN botones. Ahora
# se registra, cada vez que cambia, que ve SDL y que ve XInput directo (sin
# SDL de por medio), mas que ventana tiene el foco. Comparar los dos separa
# "SDL no ve el mando" de "el mando no manda nada a nadie".
# ---------------------------------------------------------------------------

class _XInputGamepad(ctypes.Structure):
    _fields_ = [("wButtons", ctypes.c_ushort), ("bLeftTrigger", ctypes.c_ubyte),
                ("bRightTrigger", ctypes.c_ubyte), ("sThumbLX", ctypes.c_short),
                ("sThumbLY", ctypes.c_short), ("sThumbRX", ctypes.c_short),
                ("sThumbRY", ctypes.c_short)]


class _XInputState(ctypes.Structure):
    _fields_ = [("dwPacketNumber", ctypes.c_uint), ("Gamepad", _XInputGamepad)]


_XINPUT_DLL = []


def _xinput_leer(idx):
    """(botones, gatillo_izq, gatillo_der) del slot XInput idx, o None."""
    try:
        if not _XINPUT_DLL:
            _XINPUT_DLL.append(None)
            for nombre in ("xinput1_4", "xinput1_3", "xinput9_1_0"):
                try:
                    _XINPUT_DLL[0] = ctypes.WinDLL(nombre)
                    break
                except OSError:
                    continue
        dll = _XINPUT_DLL[0]
        if dll is None:
            return None
        st = _XInputState()
        if dll.XInputGetState(idx, ctypes.byref(st)) != 0:
            return None
        g = st.Gamepad
        return (g.wButtons, g.bLeftTrigger, g.bRightTrigger)
    except Exception:
        return None


def _xinput_conectados():
    return [i for i in range(4) if _xinput_leer(i) is not None]


def _ventana_en_primer_plano():
    try:
        u = ctypes.windll.user32
        hwnd = u.GetForegroundWindow()
        buf = ctypes.create_unicode_buffer(120)
        u.GetWindowTextW(hwnd, buf, 120)
        pid = ctypes.c_ulong(0)
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return "'%s' pid=%d" % (buf.value, pid.value)
    except Exception:
        return "?"


def _bombear_input_hasta_que_muera(proc, sock):
    """Lee el mando y manda su estado al ESP32 EN EL HILO PRINCIPAL, hasta
    que ffplay (proc) se cierre. El mando ya viene abierto por
    _iniciar_input_streaming() - ver ahi el por que del orden."""
    if sock is None:
        proc.wait()
        return

    import pygame
    interval = 1.0 / INPUT_RATE
    log.info("Enviando input a %s:%s a %s Hz (hilo principal)",
             ESP32_IP, ESP32_PORT, INPUT_RATE)

    joystick = None
    ultimo_aviso = 0.0
    stats_last = time.time()
    stats_ticks = 0
    xi_activos = _xinput_conectados()
    ultima_firma = None
    ultimo_foco = 0.0

    try:
        while proc.poll() is None:
            inicio = time.time()

            if joystick is None:
                if pygame.joystick.get_count() > 0:
                    joystick = pygame.joystick.Joystick(0)
                    joystick.init()
                    log.info("Mando conectado: %s (ejes=%d, botones=%d, hats=%d) mapeo=%s",
                             joystick.get_name(), joystick.get_numaxes(),
                             joystick.get_numbuttons(), joystick.get_numhats(),
                             gp.modo_mapeo())
                elif inicio - ultimo_aviso > 5:
                    ultimo_aviso = inicio
                    log.warning("Sin mando conectado; reintentando...")

            if joystick is not None:
                try:
                    estado = gp.build_state(joystick)
                    sock.sendto(json.dumps(estado).encode("utf-8"), (ESP32_IP, ESP32_PORT))
                    stats_ticks += 1
                    sdl_pulsados = sorted(k for k, v in estado["buttons"].items() if v)
                    xi = [(i, _xinput_leer(i)) for i in xi_activos]
                    firma = (tuple(sdl_pulsados),
                             tuple((i, v and (v[0], v[1] > 30, v[2] > 30)) for i, v in xi))
                    if firma != ultima_firma:
                        ultima_firma = firma
                        log.info("[botones] SDL=%s XInput=%s primer_plano=%s",
                                 sdl_pulsados,
                                 [(i, v and "0x%04x LT=%d RT=%d" % v) for i, v in xi],
                                 _ventana_en_primer_plano())
                except OSError as e:
                    log.warning("Error de red mandando input: %s", e)
                except Exception as e:
                    log.warning("Error leyendo el mando (%s); reconectando...", e)
                    joystick = None
                    pygame.joystick.quit()
                    pygame.joystick.init()

            ahora = time.time()
            if ahora - ultimo_foco >= 0.5:
                ultimo_foco = ahora
                _mantener_foco(proc.pid)
            if ahora - stats_last >= 5.0:
                span = ahora - stats_last
                log.info("[stats] %d envios en %.1fs = %.1f Hz (objetivo %d) mando=%s ffplay_vivo=%s",
                         stats_ticks, span, stats_ticks / span, INPUT_RATE,
                         joystick is not None, proc.poll() is None)
                xi_activos = _xinput_conectados()
                log.info("[diag] xinput_conectados=%s primer_plano=%s mi_pid=%d",
                         xi_activos, _ventana_en_primer_plano(), os.getpid())
                stats_last, stats_ticks = ahora, 0

            restante = interval - (time.time() - inicio)
            if restante > 0:
                time.sleep(restante)
    finally:
        sock.close()
        if _FOCO["hwnd"] is not None:
            # La ventana de foco no debe sobrevivir al streaming: el menu abre
            # la suya con _abrir_ventana().
            _FOCO["hwnd"] = None
            try:
                pygame.display.quit()
            except Exception:
                pass


# Si no llega NADA de video en este tiempo, se corta y se vuelve al menu
# (2026-09-18). Antes, cuando la capturadora del servidor fallaba ("I/O
# error"), gst-launch se quedaba esperando para siempre: pantalla congelada y
# la app "ya abierta" al querer reabrirla. Si el servidor se relanza solo (ver
# config_listener.ps1, ~10 s), GStreamer retoma el video sin hacer nada
# (medido: sigue decodificando tras un corte de 6 s), por eso el margen es 25 s.
SIN_VIDEO_S = 25


def _vigilar_salida_gst(proc, estado):
    """Lee la salida de gst-launch (hay que drenarla igual, o se llena el
    pipe y gst se traba) y lo mata si udpsrc avisa que no llega video."""
    try:
        for linea in iter(proc.stdout.readline, b""):
            if b"GstUDPSrcTimeout" in linea:
                estado["sin_video"] = True
                log.warning("No llega video hace %d s: cerrando gstreamer.", SIN_VIDEO_S)
                try:
                    proc.terminate()
                except Exception:
                    pass
                return
    except Exception as e:
        log.debug("vigilar_salida_gst: %s", e)


def _streaming_gstreamer(gst):
    """Mismo contrato que ejecutar_modo_streaming: (ok, mensaje)."""
    fs = "true" if FULLSCREEN_VIDEO else "false"
    args = [
        # -m: imprime los mensajes del bus, de ahi se lee el aviso de udpsrc
        # cuando pasan SIN_VIDEO_S segundos sin recibir nada (ver abajo). SIN
        # -q: medido, -q calla tambien esos mensajes.
        gst, "-m",
        "udpsrc", f"port={STREAM_PORT}", "caps=video/mpegts",
        f"timeout={SIN_VIDEO_S * 1_000_000_000}",
        "!", "tsdemux", "latency=0", "name=d",
        # Video: GPU (Direct3D 11), colas chicas que TIRAN lo atrasado, sin reloj.
        "d.", "!", "queue", "max-size-buffers=3", "max-size-time=0", "max-size-bytes=0",
        "leaky=downstream",
        "!", "h264parse", "!", "d3d11h264dec",
        "!", "queue", "max-size-buffers=1", "max-size-time=0", "max-size-bytes=0",
        "leaky=downstream",
        "!", "d3d11videosink", "sync=false", "force-aspect-ratio=true",
        # fullscreen se ignora si fullscreen-toggle-mode no incluye "property"
        # (dicho por gst-inspect de este mismo runtime).
        "fullscreen-toggle-mode=property", f"fullscreen={fs}",
        # Audio: Opus a WASAPI en modo de baja latencia, tambien sin reloj.
        "d.", "!", "queue", "max-size-buffers=8", "max-size-time=0", "max-size-bytes=0",
        "leaky=downstream",
        "!", "opusdec", "!", "audioconvert", "!", "audioresample",
        "!", "wasapi2sink", "sync=false", "low-latency=true",
    ]
    log.info("Lanzando gstreamer: %s", " ".join(args))

    carpeta = os.path.dirname(gst)
    # Mismo entorno limpio de SDL que ffplay (ver la nota larga en
    # ejecutar_modo_streaming), mas el bin de gstreamer primero en el PATH
    # para que cargue SUS DLL, y el registro de plugins en una carpeta con
    # permiso de escritura (la de este .exe).
    entorno = {k: v for k, v in os.environ.items()
               if k not in ("SDL_VIDEODRIVER", "SDL_AUDIODRIVER")}
    entorno["PATH"] = carpeta + os.pathsep + entorno.get("PATH", "")
    entorno["GST_REGISTRY"] = os.path.join(app_dir(), "gst_registry.bin")

    try:
        sock_input = _iniciar_input_streaming()
        t0 = time.time()
        proc = subprocess.Popen(args,
                                stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT,
                                env=entorno,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        estado = {"sin_video": False}
        threading.Thread(target=_vigilar_salida_gst, args=(proc, estado), daemon=True).start()
        _bombear_input_hasta_que_muera(proc, sock_input)
        dur = time.time() - t0
        if estado["sin_video"]:
            return False, (f"Dejo de llegar video del servidor ({SIN_VIDEO_S} s sin imagen).\n\n"
                            "Lo mas comun: la capturadora de la PC se desconecto un momento. "
                            "El servidor intenta relanzarse solo; espera unos segundos y "
                            "vuelve a entrar a Streaming.")
        # Cerrar la ventana de video hace que gst-launch termine con error (1):
        # eso es una salida normal. Solo se trata como falla si murio enseguida.
        if proc.returncode != 0 and dur < 10:
            log.warning("gstreamer termino con codigo %s a los %.1fs", proc.returncode, dur)
            return False, ("El video no arranco (gstreamer se cerro a los pocos segundos).\n\n"
                            "Revisa que el servidor este transmitiendo, o cambia el reproductor "
                            "a ffplay en \"Configurar cliente\".")
        log.info("gstreamer termino (codigo %s) tras %.0fs", proc.returncode, dur)
        return True, ""
    except Exception as e:
        log.error("No se pudo lanzar gstreamer: %s", e)
        return False, f"No se pudo lanzar gstreamer: {e}"


def ejecutar_modo_streaming():
    """Devuelve (True, "") si parece haber recibido stream de verdad, o
    (False, mensaje) si fallo (ffplay no encontrado, o se cerro solo sin
    recibir nada) - para que main() decida si volver al menu o cerrar todo.
    Antes esto no devolvia nada y el programa se cerraba entero pasara lo
    que pasara con ffplay: si el servidor no tenia la IP de esta Ally
    puesta, ffplay se quedaba COLGADO para siempre esperando el primer
    paquete UDP (sin timeout, avformat_open_input bloquea ahi mismo, antes
    de crear ninguna ventana) - "ni la pantalla de ffplay me salio", y la
    unica salida era matar el proceso a mano. Ahora la URL UDP lleva un
    timeout (ver mas abajo) para que ffplay se rinda solo en vez de colgarse
    para siempre."""
    # GStreamer (2026-09-18, porteo del arreglo de la Deck: "igualito a la
    # tele"). ffplay forma el video detras del reloj de audio y lo que se junta
    # al arrancar no se descarta nunca, asi que cada arranque caia en un
    # retraso distinto. GStreamer con sync=false y colas que tiran lo viejo
    # muestra cada cuadro apenas llega. Si falta la carpeta, sigue con ffplay.
    if os.environ.get("PS3RP_PLAYER", "gstreamer").strip().lower() != "ffplay":
        gst = find_gst()
        if gst:
            return _streaming_gstreamer(gst)
        log.warning("PS3RP_PLAYER=gstreamer pero no esta la carpeta gstreamer junto al .exe; uso ffplay.")

    ffplay = find_ffplay()
    if not ffplay:
        log.error("No se encontro ffplay.exe (ver PS3RP_FFPLAY, o ponerlo junto al .exe).")
        return False, "No se encontro ffplay.exe junto al programa."

    # timeout=8000000 (2026-09-11): microsegundos que el protocolo udp de
    # ffmpeg espera el primer paquete antes de rendirse con ETIMEDOUT, en vez
    # de bloquear para siempre si el servidor le manda el video a otra IP.
    url = f"udp://0.0.0.0:{STREAM_PORT}?fifo_size=1500&overrun_nonfatal=1&timeout=8000000"
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

    try:
        # stdin tambien en DEVNULL, no solo stdout/stderr (2026-09-11): este
        # .exe se compila con --windowed, o sea sin consola, asi que sus
        # descriptores estandar son INVALIDOS (sys.stdin/stdout/stderr son
        # None). Todo hijo que no reciba descriptores explicitos hereda esos
        # invalidos y se cuelga. Costo un buen rato descubrirlo del lado del
        # servidor, donde el motor no arrancaba nunca y no dejaba ni un log;
        # aca ffplay habria hecho lo mismo.
        # CREATE_NO_WINDOW (2026-09-11): ffplay.exe es una app de consola; sin
        # esto Windows le crea una consola nueva propia (este .exe no tiene
        # ninguna que heredar, al ser --windowed) - un cuadro negro vacio al
        # lado del video real, que es lo que se reporto viendo. La ventana de
        # video de ffplay la abre SDL por su cuenta, no depende de la
        # consola, asi que ocultarla no le quita nada.
        # ENTORNO LIMPIO DE SDL (2026-09-11, LA causa de "le doy streaming y
        # no abre nada"). ffplay dibuja con SDL2, igual que pygame. Y este
        # mismo proceso pone SDL_VIDEODRIVER=dummy para leer el mando sin
        # abrir ventana propia (antes en el hilo de InputSender, hoy en
        # _bombear_input_hasta_que_muera). Como el hijo hereda el entorno del
        # padre, ffplay se encontraba con el
        # driver de video "dummy" y hacia exactamente lo que se le pidio:
        # decodificar todo perfecto y no dibujar NADA. Por eso el proceso
        # quedaba vivo, sano, consumiendo el stream (medido: recibia sus
        # 3400 paquetes/6s sin problema) pero sin ventana ni titulo.
        #
        # Las pantallas de pygame de este archivo ya borraban la variable
        # antes de crear su ventana; el streaming era el unico camino que no
        # lo hacia. Aca no alcanza con borrarla del os.environ propio (el
        # hilo la puede volver a poner en cualquier momento): se le pasa a
        # ffplay una copia del entorno SIN las variables de SDL.
        entorno = {k: v for k, v in os.environ.items()
                    if k not in ("SDL_VIDEODRIVER", "SDL_AUDIODRIVER")}
        sock_input = _iniciar_input_streaming()
        proc = subprocess.Popen(args,
                                stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                                env=entorno,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        _bombear_input_hasta_que_muera(proc, sock_input)
        if proc.returncode != 0:
            log.warning("ffplay termino con codigo %s (probable timeout: no llego video de la PC)",
                        proc.returncode)
            return False, ("No llego video del servidor en 8 segundos.\n\n"
                            "Revisa que el servidor este transmitiendo y que tenga puesta "
                            "la IP de esta Ally (usa \"Configurar servidor\" para mandarsela).")
        return True, ""
    except Exception as e:
        log.error("No se pudo lanzar ffplay: %s", e)
        return False, f"No se pudo lanzar ffplay: {e}"


# ---------------------------------------------------------------------------
# Verificacion previa al streaming - porteo del mismo chequeo de
# client_menu.py de la Deck (2026-09-11).
# ---------------------------------------------------------------------------
# El timeout de 8s en la URL UDP de ffplay (ver ejecutar_modo_streaming) NO
# alcanzo solo: probado en vivo contra la Ally real, ffplay se quedo colgado
# de todos modos mas alla de los 8s (el proceso nunca volvio de proc.wait())
# - mande la IP al servidor, le di Streaming, y se quedo igual de trabado
# que antes del fix, con el mismo mutex atascado bloqueando reabrir. En vez
# de perseguir por que el timeout del protocolo udp de ffmpeg no se dispara
# como se esperaba, se copia la solucion que SI funciono en la Deck: antes
# de intentar streaming, preguntarle al servidor (mismo protocolo UDP,
# puerto 9200) si esta transmitiendo Y a la IP correcta - si no, avisar y
# quedarse en el menu, sin llegar a lanzar ffplay para nada. El timeout de
# la URL se deja de todos modos como red de seguridad extra, no hace dano
# aunque no dispare.
def verificar_servidor_listo():
    """Devuelve (True, "") si el servidor esta corriendo y mandandole a esta
    Ally, o (False, mensaje) si no. Si nunca se uso "Configurar servidor"
    desde aca (no hay IP de servidor guardada), no se puede chequear nada:
    devuelve (True, "") y sigue como siempre, sin bloquear a nadie."""
    ip_servidor = server_udp.leer_ip_servidor_guardada()
    log.info("verificar_servidor_listo: ip_servidor guardada = %r", ip_servidor)
    if not ip_servidor:
        return True, ""
    ip_local = server_udp.obtener_ip_local()
    ok, resp = server_udp.obtener_config(ip_servidor)
    log.info("verificar_servidor_listo: ip_local=%r ok=%r resp=%r", ip_local, ok, resp)
    if not ok:
        return False, f"No se pudo consultar el servidor ({ip_servidor}):\n{resp}"
    if not resp.get("corriendo"):
        return False, (f"El servidor ({ip_servidor}) no esta transmitiendo ahora mismo.\n\n"
                        "Prendelo desde la PC, o revisa \"Configurar servidor\".")
    # "transmitiendo" (2026-09-11): el servidor lo agrego para no mentir
    # cuando su ffmpeg quedo colgado (proceso vivo pero sin sacar un solo
    # cuadro, ver server_engine_lib.ps1) - fue exactamente lo que dejo a
    # esta Ally esperando video que nunca llego. Solo se exige si el campo
    # viene: con un listener viejo no esta y no se bloquea nada.
    if resp.get("transmitiendo") is False:
        return False, (f"El servidor ({ip_servidor}) dice estar prendido pero no esta "
                        "sacando video (se le colgo la captura).\n\n"
                        "Detenlo y vuelvelo a iniciar desde la PC.")
    if ip_local and resp.get("ip") != ip_local:
        return False, (f"El servidor esta mandando el video a {resp.get('ip')}, "
                        f"no a esta Ally ({ip_local}).\n\n"
                        "Entra a \"Configurar servidor\" y manda tu IP con el boton "
                        "de enviar IP.")
    return True, ""


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def _timer_fino(activar: bool):
    """Sube (o baja) la resolucion del temporizador de Windows a 1 ms.

    POR QUE (2026-09-11, medido): por default Windows programa los timers
    cada ~15.6 ms, asi que un time.sleep(0.001) duerme de verdad ~15 ms y
    ningun bucle de envio puede pasar de ~64 vueltas por segundo. Medido
    contra el ESP32: en modo control llegaban 50-63 paquetes/s en vez de los
    120 pedidos, y ademas irregulares - se siente trabado. En streaming
    llegaban ~110/s SOLO porque ffplay ya estaba corriendo y el (via SDL)
    sube esa resolucion para todo el sistema; apenas se cierra, vuelve a
    caer. Pidiendola nosotros, el ritmo de input deja de depender de que otro
    programa la haya subido.

    Se libera al salir: es un ajuste global del sistema y dejarlo puesto
    gasta bateria de mas en un portatil."""
    try:
        if activar:
            ctypes.windll.winmm.timeBeginPeriod(1)
        else:
            ctypes.windll.winmm.timeEndPeriod(1)
    except Exception as e:
        log.debug("No se pudo ajustar la resolucion del temporizador: %s", e)


def main():
    ya, _mutex = ya_hay_instancia()
    if ya:
        log.warning("Ya hay una instancia corriendo; saliendo.")
        return

    log.info("=== PS3 Remote Play (Ally) iniciando ===")
    _timer_fino(True)

    # WiFi sin ahorro de energia (o devolverlo, segun el interruptor). En hilo
    # aparte: son 3-4 llamadas a powercfg y el menu no debe esperarlas.
    def _wifi():
        sin_ahorro = os.environ.get("PS3RP_WIFI_SIN_AHORRO", "1") == "1"
        log.info("WiFi power save: %s", wifi_power.aplicar(
            sin_ahorro, os.path.join(app_dir(), "wifi_power_original.json")))
    threading.Thread(target=_wifi, daemon=True).start()

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

        if modo == "streaming" and not MODO_FIJO:
            try:
                ok, mensaje = verificar_servidor_listo()
            except Exception as e:
                # Que un error de red al chequear no tire abajo TODO el
                # programa (2026-09-11): mejor seguir a streaming como antes
                # que cerrarse sin avisar nada - "se cerro y me mostro el
                # escritorio" es peor que simplemente no chequear esta vez.
                log.error("verificar_servidor_listo fallo, sigo sin chequear: %s", e)
                ok, mensaje = True, ""
            if not ok:
                log.warning("Servidor no listo para streaming: %s", mensaje)
                try:
                    ctypes.windll.user32.MessageBoxW(0, mensaje, "PS3 Remote Play", 0x30)
                except Exception:
                    pass
                continue

        log.info("--- modo STREAMING ---")
        # Cerrar la ventana propia antes: ffplay abre y maneja la suya, y
        # dejar la nuestra abierta de fondo no sirve de nada mientras dura
        # el streaming.
        import pygame
        cerrar_ventana(pygame)
        ok, mensaje = ejecutar_modo_streaming()
        if ok or MODO_FIJO:
            # Si vino de PS3RP_MODO=streaming (sin menu), respeta esa
            # intencion y cierra igual aunque haya fallado - no hay a que
            # menu volver.
            break
        # "deberia decirme que no se pudo conectar y mandarme al inicio, no
        # solo cerrarse y no hacer nada" (reportado 2026-09-11): antes esto
        # siempre hacia break sin importar el resultado.
        try:
            ctypes.windll.user32.MessageBoxW(0, mensaje, "PS3 Remote Play", 0x30)
        except Exception:
            pass
        continue

    import pygame
    cerrar_ventana(pygame)
    _timer_fino(False)
    log.info("=== Cerrando ===")


if __name__ == "__main__":
    main()
