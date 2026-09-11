#!/usr/bin/env python3
"""
Cliente de input para PS3 Remote Play - Steam Deck (v2)
----------------------------------------------------------
Lee el mando (detectado en SteamOS Desktop como "Xbox 360 pad")
y lo envía por UDP al servidor con nombres de botones claros.

Requisitos:
    pip install pygame

Uso:
    python3 input_client_v2.py --host 192.168.1.50 --port 9000
    python3 input_client_v2.py --list        # solo lista mandos
    python3 input_client_v2.py --host X --port Y --debug  # imprime cada envío
"""

import argparse
import json
import socket
import time

import pygame

# Mapeo estándar Xbox 360 (confirmado en Steam Deck modo Desktop vía SDL)
BUTTON_NAMES = {
    0: "A",
    1: "B",
    2: "X",
    3: "Y",
    4: "LB",
    5: "RB",
    6: "BACK",
    7: "START",
    8: "GUIDE",
    9: "L3",
    10: "R3",
}

AXIS_NAMES = {
    0: "LSTICK_X",
    1: "LSTICK_Y",
    2: "RSTICK_X",
    3: "RSTICK_Y",
    4: "LT",
    5: "RT",
}


def build_state(joystick: "pygame.joystick.Joystick") -> dict:
    """Lee el estado actual del mando y lo empaqueta con nombres legibles."""
    pygame.event.pump()

    axes = {}
    for i in range(joystick.get_numaxes()):
        name = AXIS_NAMES.get(i, f"axis_{i}")
        axes[name] = round(joystick.get_axis(i), 4)

    buttons = {}
    for i in range(joystick.get_numbuttons()):
        name = BUTTON_NAMES.get(i, f"button_{i}")
        buttons[name] = joystick.get_button(i)

    hats = [joystick.get_hat(i) for i in range(joystick.get_numhats())]
    dpad = hats[0] if hats else (0, 0)

    return {
        "t": time.time(),
        "axes": axes,
        "buttons": buttons,
        "dpad": {"x": dpad[0], "y": dpad[1]},
    }


def connect_joystick():
    """Espera a que haya un mando disponible y lo inicializa. Reintenta si se desconecta."""
    while True:
        pygame.joystick.quit()
        pygame.joystick.init()
        count = pygame.joystick.get_count()
        if count > 0:
            joystick = pygame.joystick.Joystick(0)
            joystick.init()
            print(f"Mando conectado: {joystick.get_name()} "
                  f"(ejes={joystick.get_numaxes()}, botones={joystick.get_numbuttons()}, "
                  f"hats={joystick.get_numhats()})")
            return joystick
        print("No hay mando conectado. Reintentando en 2s...")
        time.sleep(2)


def main():
    parser = argparse.ArgumentParser(description="Cliente de input UDP para PS3 Remote Play")
    parser.add_argument("--host", help="IP del servidor (PC con el Arduino/PS3)")
    parser.add_argument("--port", type=int, default=9000, help="Puerto UDP del servidor")
    parser.add_argument("--rate", type=int, default=60, help="Envíos por segundo (Hz)")
    parser.add_argument("--list", action="store_true", help="Solo lista mandos detectados y sale")
    parser.add_argument("--debug", action="store_true", help="Imprime cada paquete enviado")
    args = parser.parse_args()

    if not args.list and not args.host:
        parser.error("--host es requerido salvo que uses --list")

    pygame.init()
    pygame.joystick.init()

    if args.list:
        count = pygame.joystick.get_count()
        if count == 0:
            print("No se detectó ningún mando.")
            return
        print(f"Mandos detectados ({count}):")
        for i in range(count):
            j = pygame.joystick.Joystick(i)
            j.init()
            print(f"  [{i}] {j.get_name()}  (ejes={j.get_numaxes()}, "
                  f"botones={j.get_numbuttons()}, hats={j.get_numhats()})")
        return

    joystick = connect_joystick()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    interval = 1.0 / args.rate

    print(f"\nEnviando input a {args.host}:{args.port} a {args.rate} Hz. Ctrl+C para salir.\n")

    consecutive_errors = 0
    try:
        while True:
            start = time.time()

            # Si el mando se desconectó, pygame lanza error al leer -> reconectar
            try:
                if pygame.joystick.get_count() == 0:
                    print("Mando desconectado. Esperando reconexión...")
                    joystick = connect_joystick()

                state = build_state(joystick)
            except pygame.error as e:
                print(f"Error leyendo el mando ({e}), reintentando...")
                joystick = connect_joystick()
                continue

            payload = json.dumps(state).encode("utf-8")

            try:
                sock.sendto(payload, (args.host, args.port))
                consecutive_errors = 0
            except OSError as e:
                consecutive_errors += 1
                print(f"Error de red ({e}). Fallos consecutivos: {consecutive_errors}")
                if consecutive_errors > 20:
                    print("Demasiados errores de red seguidos. Verifica la conexión al servidor.")
                time.sleep(0.5)
                continue

            if args.debug:
                pressed = [k for k, v in state["buttons"].items() if v]
                print(f"botones={pressed} dpad={state['dpad']} "
                      f"LSTICK=({state['axes'].get('LSTICK_X', 0):+.2f},"
                      f"{state['axes'].get('LSTICK_Y', 0):+.2f})")

            elapsed = time.time() - start
            sleep_time = interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)
    except KeyboardInterrupt:
        print("\nCerrando cliente de input.")
    finally:
        sock.close()
        pygame.quit()


if __name__ == "__main__":
    main()
