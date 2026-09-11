#!/usr/bin/env python3
"""Lector del mando de la Steam Deck, compartido por las ventanas del cliente.

Existe para que `client_menu.py` (que navega con el mando) y
`client_control_ui.py` (que solo muestra que boton se esta pulsando) no tengan
dos copias del mismo codigo.

LAS TABLAS DE BOTONES NO VIVEN AQUI: se importan de `input_client_v3.py`, que es
donde estan verificadas contra hardware real. Copiarlas seria garantizar que un
dia queden desincronizadas. Hay un fallback minimo por si el import falla.

Se puede abrir el mando aunque `input_client_v3.py` ya lo tenga abierto:
verificado el 2026-09-06 con dos procesos leyendo a la vez, ninguno se estorba
(SDL no toma el dispositivo en exclusiva).
"""

import os

# pygame se usa SOLO como lector de mando, nunca para dibujar. Sin estos tres,
# SDL abre su propio video/audio y pelea con la ventana de tkinter (bajo
# gamescope eso puede terminar en una ventana negra encima de todo), y ademas
# saluda por stdout, que ya rompio el paso de la eleccion del menu una vez.
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

# Los gatillos descansan en -1.0 y llegan a +1.0. Mismo umbral que usa
# input_client_v3.py para sintetizar el click, o sea que lo que se muestra
# coincide con lo que se le manda al ESP32.
UMBRAL_GATILLO = -0.5

# Como se escribe cada boton en pantalla. Solo caracteres que DejaVu Sans
# dibuja seguro; nada de simbolos raros que salgan como cuadrito.
ETIQUETAS = {
    "A": "A", "B": "B", "X": "X", "Y": "Y",
    "L1": "L1", "R1": "R1",
    "L2_CLICK": "L2", "R2_CLICK": "R2",
    "L3_CLICK": "L3", "R3_CLICK": "R3",
    "SELECT": "SELECT", "START": "START",
    "STEAM": "STEAM", "QUICK_ACCESS": "ACCESO RAPIDO",
    "DPAD_UP": "↑", "DPAD_DOWN": "↓",
    "DPAD_LEFT": "←", "DPAD_RIGHT": "→",
    "L4": "L4", "R4": "R4", "L5": "L5", "R5": "R5",
}

# Orden fijo para que la linea no baile cuando se pulsan varios a la vez.
ORDEN = ["DPAD_UP", "DPAD_DOWN", "DPAD_LEFT", "DPAD_RIGHT",
         "A", "B", "X", "Y", "L1", "R1", "L2_CLICK", "R2_CLICK",
         "L3_CLICK", "R3_CLICK", "SELECT", "START", "STEAM",
         "QUICK_ACCESS", "L4", "R4", "L5", "R5"]

_FALLBACK_NATIVO = {3: "A", 4: "B", 5: "X", 6: "Y", 7: "L1", 8: "R1",
                    11: "SELECT", 12: "START",
                    16: "DPAD_UP", 17: "DPAD_DOWN",
                    18: "DPAD_LEFT", 19: "DPAD_RIGHT"}
_FALLBACK_VIRTUAL = {0: "A", 1: "B", 2: "X", 3: "Y", 4: "L1", 5: "R1",
                     6: "SELECT", 7: "START"}


def _tablas():
    try:
        from input_client_v3 import (NATIVE_BUTTON_NAMES, XINPUT_BUTTON_NAMES,
                                     NATIVE_AXIS_NAMES, XINPUT_AXIS_NAMES)
        return (NATIVE_BUTTON_NAMES, XINPUT_BUTTON_NAMES,
                NATIVE_AXIS_NAMES, XINPUT_AXIS_NAMES)
    except Exception:
        return (_FALLBACK_NATIVO, _FALLBACK_VIRTUAL, {}, {})


def etiquetar(nombres):
    """Conjunto de nombres internos -> texto listo para mostrar."""
    vistos = [ETIQUETAS.get(n, n) for n in ORDEN if n in nombres]
    # Cualquiera que no este en ORDEN (button_7 y demas) va al final.
    vistos += sorted(ETIQUETAS.get(n, n) for n in nombres if n not in ORDEN)
    return "  +  ".join(vistos)


class Mando:
    """Lee el mando sin tirar excepciones hacia afuera.

    Aguanta que no haya mando, que aparezca despues o que se desconecte a mitad:
    reintenta en cada vuelta. Si algo falla, `pulsados()` devuelve un conjunto
    vacio y quien lo use sigue funcionando sin mando.
    """

    def __init__(self):
        self.js = None
        self.previos = set()
        self.ok = False
        (self.bot_nativos, self.bot_virtuales,
         self.ejes_nativos, self.ejes_virtuales) = _tablas()
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
        """Nombres de todos los botones pulsados en este instante."""
        if not self.ok or not self._conectar():
            return set()
        try:
            self.pygame.event.pump()
            js = self.js
            # Misma regla que layout_for() de input_client_v3.py: el mando
            # nativo reporta ~24 botones, el pad virtual de Steam 11. Se
            # recalcula cada vuelta, asi que si Steam arranca o se cierra con
            # la ventana ya abierta, el mapeo se acomoda solo.
            nativo = js.get_numbuttons() >= 16
            botones = self.bot_nativos if nativo else self.bot_virtuales
            ejes = self.ejes_nativos if nativo else self.ejes_virtuales

            fuera = set()
            for idx, nombre in botones.items():
                if idx < js.get_numbuttons() and js.get_button(idx):
                    fuera.add(nombre)

            # El pad virtual entrega la cruceta como hat; el nativo como
            # botones sueltos (ya cubiertos arriba).
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

            # Gatillos: el pad de Xbox no tiene boton digital, hay que
            # sintetizarlo del eje analogico igual que hace el cliente de input.
            for idx, nombre in ejes.items():
                if idx >= js.get_numaxes():
                    continue
                valor = js.get_axis(idx)
                if nombre == "L2_ANALOG" and valor > UMBRAL_GATILLO:
                    fuera.add("L2_CLICK")
                elif nombre == "R2_ANALOG" and valor > UMBRAL_GATILLO:
                    fuera.add("R2_CLICK")

            return fuera
        except Exception:
            # Se desconecto en medio; que lo reintente la proxima vuelta.
            self.js = None
            self.previos = set()
            return set()

    def direccion_stick(self):
        """'izq', 'der' o None, para navegar menus con el stick izquierdo."""
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
        """Nombres que pasaron de sueltos a pulsados desde la ultima llamada."""
        ahora = self.pulsados()
        direccion = self.direccion_stick()
        if direccion == "izq":
            ahora = ahora | {"DPAD_LEFT"}
        elif direccion == "der":
            ahora = ahora | {"DPAD_RIGHT"}
        recien = ahora - self.previos
        self.previos = ahora
        return recien
