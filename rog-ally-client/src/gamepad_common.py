#!/usr/bin/env python3
"""Tablas de mando y lectura de estado, compartidas por todo el cliente de la Ally.

PORTEO DESDE LA STEAM DECK (input_client_v3.py / deck_gamepad.py). En Windows no
existe el concepto de "lizard_mode" ni el mando NATIVO de la Deck: SDL/pygame en
Windows normaliza cualquier mando compatible con XInput (que es el caso de la
ROG Ally X) al mismo layout de 10-11 botones / 6 ejes que la Deck ve como
"gamepad virtual de Steam Input". Por eso aca solo queda UN mapeo, tomado
directo de XINPUT_BUTTON_NAMES/XINPUT_AXIS_NAMES del script de la Deck.

SIN VERIFICAR EN HARDWARE REAL (2026-09-07): estas tablas se heredan del mapeo
"xinput" ya confirmado en la Deck cuando Steam Input le presenta un pad virtual,
que sigue el orden estandar del driver xpad de Linux / XInput de Microsoft. Es
el mapeo mas probable para la Ally, pero NO fue medido contra el hardware
fisico. Si algun boton sale con el nombre equivocado, correr con
PS3RP_DEBUG=1 y mirar el log: ahi se imprime una linea por cada cambio de
botones/ejes, igual que hacia el cliente de la Deck.

Los nombres de aca son el contrato con el firmware del ESP32
(ds3_controller.ino): A/B/X/Y, L1/R1, L2_CLICK/R2_CLICK, SELECT/START,
L3_CLICK/R3_CLICK, STEAM, y los ejes LSTICK_*/RSTICK_*/L2_ANALOG/R2_ANALOG.
Cualquier otro nombre el firmware lo ignora en silencio (por ejemplo, el boton
de Armoury Crate de la Ally, que no tiene equivalente en el DS3).
"""

import os
import time

BUTTON_NAMES = {
    0: "A",
    1: "B",
    2: "X",
    3: "Y",
    4: "L1",       # LB
    5: "R1",       # RB
    6: "SELECT",   # Back / View
    7: "START",    # Start / Menu
    8: "STEAM",    # Guide / boton Xbox
    9: "L3_CLICK",
    10: "R3_CLICK",
}

AXIS_NAMES = {
    0: "LSTICK_X",
    1: "LSTICK_Y",
    2: "L2_ANALOG",
    3: "RSTICK_X",
    4: "RSTICK_Y",
    5: "R2_ANALOG",
}

# Gatillos en reposo = -1.0, a fondo = +1.0. Umbral en -0.5 = un cuarto de
# recorrido. Igual que TRIGGER_CLICK_THRESHOLD / UMBRAL_GATILLO en la Deck.
TRIGGER_CLICK_THRESHOLD = -0.5

# ---------------------------------------------------------------------------
# Boton PS por acorde de botones (copiado tal cual de input_client_v3.py)
# ---------------------------------------------------------------------------
# En la Deck esto existe porque Steam Input intercepta START y STEAM antes de
# que lleguen a pygame. En Windows, si esto se lanza por fuera de Steam Big
# Picture, es posible que START SI llegue entero y el acorde no haga falta -
# pero dejarlo activo no hace dano (el acorde solo se dispara si de verdad se
# aprietan todos los botones a la vez) y mantiene el mismo comportamiento que
# la Deck si en algun momento se lanza via Steam en la Ally tambien.
PS_CHORD_GUARD_S = 0.08
PS_CHORD_DEFAULT = "SELECT+R1"


def _parse_ps_combo(spec: str) -> list:
    spec = (spec or "").strip()
    if not spec or spec.lower() in ("none", "no", "0", "off"):
        return []
    nombres = [t.strip().upper() for t in spec.split("+") if t.strip()]
    conocidos = set(BUTTON_NAMES.values())
    for n in nombres:
        if n not in conocidos:
            print(f"AVISO: '{n}' no es un boton conocido; el acorde PS puede no formarse nunca.")
            print(f"  Validos: {', '.join(sorted(conocidos))}")
    return nombres


PS_CHORD = _parse_ps_combo(os.environ.get("PS3RP_PS_COMBO", PS_CHORD_DEFAULT))

_ps_chord = {"single_since": 0.0, "latched": False}


def apply_ps_chord(buttons: dict) -> None:
    """Convierte el acorde configurado en el boton PS (bandera STEAM)."""
    if not PS_CHORD:
        return

    ancla = PS_CHORD[0]
    presionados = [bool(buttons.get(n)) for n in PS_CHORD]
    combo = all(presionados)
    ancla_sola = bool(buttons.get(ancla)) and not combo
    now = time.monotonic()

    if combo:
        _ps_chord["latched"] = True
        _ps_chord["single_since"] = 0.0
    elif not any(presionados):
        _ps_chord["latched"] = False
        _ps_chord["single_since"] = 0.0
    elif ancla_sola and _ps_chord["single_since"] == 0.0:
        _ps_chord["single_since"] = now

    buttons["STEAM"] = int(bool(buttons.get("STEAM")) or combo)

    if _ps_chord["latched"]:
        buttons[ancla] = 0
        return

    since = _ps_chord["single_since"]
    if since != 0.0 and (now - since) < PS_CHORD_GUARD_S:
        buttons[ancla] = 0


# ---------------------------------------------------------------------------
# Gatillos con umbral auto-calibrado (2026-09-11)
# ---------------------------------------------------------------------------
# TRIGGER_CLICK_THRESHOLD = -0.5 da por hecho que un gatillo en reposo vale
# -1.0 (lo estandar de XInput, y lo que hace la Deck). En la ROG Ally real eso
# NO se cumplio: "en modo control siempre aparece el L2 presionado" - o sea
# que el eje descansa en un valor > -0.5 (tipicamente 0.0, que es como lo
# reportan algunos drivers/capas cuando el pad no pasa por XInput puro), y con
# el umbral fijo el gatillo se leia pulsado para siempre, mandandole L2
# pisado al PS3 todo el tiempo.
#
# En vez de adivinar el valor de reposo de cada mando, se aprende solo: el
# MINIMO visto en el eje es el reposo, y el maximo siempre es +1.0 (eso si lo
# garantiza SDL). El umbral queda al 30% de ese recorrido:
#     reposo -1.0  ->  umbral -0.4   (como antes)
#     reposo  0.0  ->  umbral  0.3
# Si al arrancar el usuario tuviera el gatillo pisado, el minimo empieza alto
# y el gatillo se lee SUELTO hasta que lo suelte una vez - falla hacia el lado
# seguro (nunca "pegado"), que es justo lo contrario del bug reportado.
_gatillo_reposo = {}


def _gatillo_pulsado(nombre: str, axes: dict) -> bool:
    if nombre not in axes:
        return False
    valor = axes[nombre]
    previo = _gatillo_reposo.get(nombre)
    reposo = valor if previo is None else min(previo, valor)
    _gatillo_reposo[nombre] = reposo
    return valor > (reposo + 0.3 * (1.0 - reposo))


# ---------------------------------------------------------------------------
# Mapeo por SDL_GameController (2026-09-11) - ver por que abajo
# ---------------------------------------------------------------------------
# Las tablas BUTTON_NAMES/AXIS_NAMES de arriba son indices CRUDOS de joystick,
# heredados del mapeo "xinput" de la Deck y nunca verificados contra la Ally.
# Medido en la Ally real: su mando expone DIECISEIS botones (un XInput
# estandar expone 11), asi que los indices no corresponden - de todos los
# botones solo la A caia en el lugar correcto por casualidad ("el x(a) si jalo
# los demas nada").
#
# En vez de medir a mano los indices de ESTE mando y hardcodearlos (fragil, y
# solo sirve para este modelo), se usa la API de GameController de SDL, que ya
# trae el mapeo normalizado por dispositivo: se le pide "el boton A" y SDL
# sabe cual es, sea cual sea el orden crudo. Tambien resuelve los gatillos, que
# ahi son ejes conocidos (TRIGGERLEFT/RIGHT) en vez de un indice adivinado.
#
# Si el mando no fuera reconocido como GameController, se cae al camino viejo
# de indices crudos - que al menos deja la A funcionando, como hasta ahora.
_ctrl = {"obj": None, "intentado": False, "avisado": False}


def _controlador():
    if _ctrl["obj"] is not None or _ctrl["intentado"]:
        return _ctrl["obj"]
    _ctrl["intentado"] = True
    try:
        from pygame._sdl2 import controller as sdl_controller
        sdl_controller.init()
        if sdl_controller.get_count() > 0 and sdl_controller.is_controller(0):
            _ctrl["obj"] = sdl_controller.Controller(0)
    except Exception:
        _ctrl["obj"] = None
    return _ctrl["obj"]


def modo_mapeo() -> str:
    """'gamecontroller' si SDL reconocio el mando y se usa su mapeo
    normalizado, 'crudo' si se cayo a los indices de las tablas de arriba.
    Solo para dejarlo en el log y no tener que adivinar cual se uso."""
    return "gamecontroller" if _controlador() is not None else "crudo"


def _estado_por_gamecontroller(pygame, ctrl):
    """buttons/axes/dpad con los nombres del contrato del firmware, leidos con
    el mapeo normalizado de SDL. Los ejes de SDL vienen en -32768..32767 y los
    gatillos en 0..32767; se normalizan a -1..1 (con el gatillo en reposo en
    -1.0) para que el resto del proyecto no note la diferencia."""
    def eje(const):
        return round(ctrl.get_axis(const) / 32767.0, 4)

    def gatillo(const):
        return round((ctrl.get_axis(const) / 32767.0) * 2.0 - 1.0, 4)

    axes = {
        "LSTICK_X": eje(pygame.CONTROLLER_AXIS_LEFTX),
        "LSTICK_Y": eje(pygame.CONTROLLER_AXIS_LEFTY),
        "RSTICK_X": eje(pygame.CONTROLLER_AXIS_RIGHTX),
        "RSTICK_Y": eje(pygame.CONTROLLER_AXIS_RIGHTY),
        "L2_ANALOG": gatillo(pygame.CONTROLLER_AXIS_TRIGGERLEFT),
        "R2_ANALOG": gatillo(pygame.CONTROLLER_AXIS_TRIGGERRIGHT),
    }

    buttons = {
        "A": ctrl.get_button(pygame.CONTROLLER_BUTTON_A),
        "B": ctrl.get_button(pygame.CONTROLLER_BUTTON_B),
        "X": ctrl.get_button(pygame.CONTROLLER_BUTTON_X),
        "Y": ctrl.get_button(pygame.CONTROLLER_BUTTON_Y),
        "L1": ctrl.get_button(pygame.CONTROLLER_BUTTON_LEFTSHOULDER),
        "R1": ctrl.get_button(pygame.CONTROLLER_BUTTON_RIGHTSHOULDER),
        "SELECT": ctrl.get_button(pygame.CONTROLLER_BUTTON_BACK),
        "START": ctrl.get_button(pygame.CONTROLLER_BUTTON_START),
        "STEAM": ctrl.get_button(pygame.CONTROLLER_BUTTON_GUIDE),
        "L3_CLICK": ctrl.get_button(pygame.CONTROLLER_BUTTON_LEFTSTICK),
        "R3_CLICK": ctrl.get_button(pygame.CONTROLLER_BUTTON_RIGHTSTICK),
    }

    # La cruceta aca son botones, no un hat: se traduce al mismo (x, y) que
    # espera el firmware.
    dx = (ctrl.get_button(pygame.CONTROLLER_BUTTON_DPAD_RIGHT)
          - ctrl.get_button(pygame.CONTROLLER_BUTTON_DPAD_LEFT))
    dy = (ctrl.get_button(pygame.CONTROLLER_BUTTON_DPAD_UP)
          - ctrl.get_button(pygame.CONTROLLER_BUTTON_DPAD_DOWN))
    return buttons, axes, (dx, dy)


def build_state(joystick) -> dict:
    """Estado del mando con los nombres del contrato del firmware.

    Prefiere el mapeo normalizado de SDL_GameController; si el mando no es
    reconocido, cae a los indices crudos de las tablas de arriba."""
    import pygame
    pygame.event.pump()

    ctrl = _controlador()
    if ctrl is not None:
        buttons, axes, dpad_hat = _estado_por_gamecontroller(pygame, ctrl)
        buttons["L2_CLICK"] = int(_gatillo_pulsado("L2_ANALOG", axes))
        buttons["R2_CLICK"] = int(_gatillo_pulsado("R2_ANALOG", axes))
        apply_ps_chord(buttons)
        return {
            "t": time.time(),
            "axes": axes,
            "buttons": buttons,
            "dpad": {"x": dpad_hat[0], "y": dpad_hat[1]},
        }

    axes = {}
    for i in range(joystick.get_numaxes()):
        name = AXIS_NAMES.get(i, f"axis_{i}")
        axes[name] = round(joystick.get_axis(i), 4)

    buttons = {}
    for i in range(joystick.get_numbuttons()):
        name = BUTTON_NAMES.get(i, f"button_{i}")
        buttons[name] = joystick.get_button(i)

    # El pad XInput no tiene boton digital de gatillo; sin esto el firmware
    # nunca ve L2/R2 (el analogico solo se usa para el byte de presion).
    buttons["L2_CLICK"] = int(_gatillo_pulsado("L2_ANALOG", axes))
    buttons["R2_CLICK"] = int(_gatillo_pulsado("R2_ANALOG", axes))

    apply_ps_chord(buttons)

    hats = [joystick.get_hat(i) for i in range(joystick.get_numhats())]
    dpad_hat = hats[0] if hats else (0, 0)

    return {
        "t": time.time(),
        "axes": axes,
        "buttons": buttons,
        "dpad": {"x": dpad_hat[0], "y": dpad_hat[1]},
    }


# ---------------------------------------------------------------------------
# Etiquetas para mostrar en pantalla (control_ui / menu)
# ---------------------------------------------------------------------------
ETIQUETAS = {
    "A": "A", "B": "B", "X": "X", "Y": "Y",
    "L1": "L1", "R1": "R1",
    "L2_CLICK": "L2", "R2_CLICK": "R2",
    "L3_CLICK": "L3", "R3_CLICK": "R3",
    "SELECT": "SELECT", "START": "START", "STEAM": "STEAM/XBOX",
    "DPAD_UP": "↑", "DPAD_DOWN": "↓",
    "DPAD_LEFT": "←", "DPAD_RIGHT": "→",
}

ORDEN = ["DPAD_UP", "DPAD_DOWN", "DPAD_LEFT", "DPAD_RIGHT",
         "A", "B", "X", "Y", "L1", "R1", "L2_CLICK", "R2_CLICK",
         "L3_CLICK", "R3_CLICK", "SELECT", "START", "STEAM"]


def etiquetar(nombres):
    vistos = [ETIQUETAS.get(n, n) for n in ORDEN if n in nombres]
    vistos += sorted(ETIQUETAS.get(n, n) for n in nombres if n not in ORDEN)
    return "  +  ".join(vistos)


class Mando:
    """Lee el mando sin tirar excepciones hacia afuera (mismo contrato que
    deck_gamepad.Mando: si algo falla, devuelve vacio y quien lo use sigue
    funcionando sin mando)."""

    def __init__(self):
        self.js = None
        self.previos = set()
        self.ok = False
        try:
            import pygame
            self.pygame = pygame
            pygame.init()
            pygame.joystick.init()
            self.ok = True
        except Exception:
            self.pygame = None

    def _conectar(self):
        if self.js is not None:
            return True
        try:
            if self.pygame.joystick.get_count() == 0:
                self.pygame.joystick.quit()
                self.pygame.joystick.init()
                if self.pygame.joystick.get_count() == 0:
                    return False
            self.js = self.pygame.joystick.Joystick(0)
            self.js.init()
            return True
        except Exception:
            self.js = None
            return False

    def pulsados(self):
        if not self.ok or not self._conectar():
            return set()
        try:
            self.pygame.event.pump()
            js = self.js
            fuera = set()
            for idx, nombre in BUTTON_NAMES.items():
                if idx < js.get_numbuttons() and js.get_button(idx):
                    fuera.add(nombre)

            for h in range(js.get_numhats()):
                hx, hy = js.get_hat(h)
                if hx < 0:
                    fuera.add("DPAD_LEFT")
                elif hx > 0:
                    fuera.add("DPAD_RIGHT")
                if hy > 0:
                    fuera.add("DPAD_UP")
                elif hy < 0:
                    fuera.add("DPAD_DOWN")

            for idx, nombre in AXIS_NAMES.items():
                if idx >= js.get_numaxes():
                    continue
                valor = js.get_axis(idx)
                if nombre == "L2_ANALOG" and valor > TRIGGER_CLICK_THRESHOLD:
                    fuera.add("L2_CLICK")
                elif nombre == "R2_ANALOG" and valor > TRIGGER_CLICK_THRESHOLD:
                    fuera.add("R2_CLICK")

            return fuera
        except Exception:
            self.js = None
            self.previos = set()
            return set()

    def direccion_stick(self):
        if not self.ok or self.js is None:
            return None
        try:
            if self.js.get_numaxes() == 0:
                return None
            ax = self.js.get_axis(0)
        except Exception:
            return None
        if ax < -0.5:
            return "izq"
        if ax > 0.5:
            return "der"
        return None

    def nuevos(self):
        ahora = self.pulsados()
        direccion = self.direccion_stick()
        if direccion == "izq":
            ahora = ahora | {"DPAD_LEFT"}
        elif direccion == "der":
            ahora = ahora | {"DPAD_RIGHT"}
        recien = ahora - self.previos
        self.previos = ahora
        return recien
