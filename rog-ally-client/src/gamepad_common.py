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


def build_state(joystick) -> dict:
    """Igual que build_state() de la Deck, pero con un solo mapeo (xinput)."""
    import pygame
    pygame.event.pump()

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
    buttons["L2_CLICK"] = int(axes.get("L2_ANALOG", -1.0) > TRIGGER_CLICK_THRESHOLD)
    buttons["R2_CLICK"] = int(axes.get("R2_ANALOG", -1.0) > TRIGGER_CLICK_THRESHOLD)

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
