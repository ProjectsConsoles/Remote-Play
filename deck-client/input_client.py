#!/usr/bin/env python3
"""
Cliente de input para PS3 Remote Play - Steam Deck
----------------------------------------------------
Lee el estado del mando integrado (o cualquier gamepad conectado)
y lo envía por UDP al servidor como paquetes JSON pequeños.

Requisitos:
    pip install pygame

Uso:
    python3 input_client.py --host 192.168.1.50 --port 9000
"""

import argparse
import json
import socket
import time

import pygame


def build_state(joystick: "pygame.joystick.Joystick") -> dict:
    """Lee el estado actual del mando y lo empaqueta en un dict simple."""
    pygame.event.pump()

    axes = [round(joystick.get_axis(i), 4) for i in range(joystick.get_numaxes())]
    buttons = [joystick.get_button(i) for i in range(joystick.get_numbuttons())]
    hats = [joystick.get_hat(i) for i in range(joystick.get_numhats())]

    return {
        "t": time.time(),
        "axes": axes,
        "buttons": buttons,
        "hats": hats,
    }


def test_mode(joystick: "pygame.joystick.Joystick"):
    """Imprime solo los cambios de estado, para mapear botones/ejes a mano."""
    print("\nModo de prueba: presiona botones y mueve los sticks/gatillos.")
    print("Presiona Ctrl+C para salir.\n")

    prev = build_state(joystick)
    try:
        while True:
            time.sleep(0.02)
            curr = build_state(joystick)

            for i, (a, b) in enumerate(zip(prev["axes"], curr["axes"])):
                if abs(a - b) > 0.05:
                    print(f"  eje[{i}] = {b:+.3f}")

            for i, (a, b) in enumerate(zip(prev["buttons"], curr["buttons"])):
                if a != b:
                    estado = "presionado" if b else "soltado"
                    print(f"  boton[{i}] {estado}")

            for i, (a, b) in enumerate(zip(prev["hats"], curr["hats"])):
                if a != b:
                    print(f"  hat[{i}] = {b}")

            prev = curr
    except KeyboardInterrupt:
        print("\nSaliendo del modo de prueba.")


def main():
    parser = argparse.ArgumentParser(description="Cliente de input UDP para PS3 Remote Play")
    parser.add_argument("--host", required=False, help="IP del servidor (PC con el Arduino/PS3)")
    parser.add_argument("--port", type=int, default=9000, help="Puerto UDP del servidor")
    parser.add_argument("--rate", type=int, default=60, help="Envíos por segundo (Hz)")
    parser.add_argument("--list", action="store_true", help="Solo lista mandos detectados y sale")
    parser.add_argument("--test", action="store_true", help="Modo de prueba: muestra qué cambia al mover el mando")
    args = parser.parse_args()

    pygame.init()
    pygame.joystick.init()

    count = pygame.joystick.get_count()
    if count == 0:
        print("No se detectó ningún mando. Conecta uno o revisa los controles de la Steam Deck.")
        return

    print(f"Mandos detectados ({count}):")
    for i in range(count):
        j = pygame.joystick.Joystick(i)
        j.init()
        print(f"  [{i}] {j.get_name()}  (ejes={j.get_numaxes()}, botones={j.get_numbuttons()}, hats={j.get_numhats()})")

    if args.list:
        return

    if not args.host and not args.test:
        parser.error("--host es obligatorio salvo que uses --list o --test")

    joystick = pygame.joystick.Joystick(0)
    joystick.init()
    print(f"\nUsando mando: {joystick.get_name()}")

    if args.test:
        test_mode(joystick)
        return

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    interval = 1.0 / args.rate

    print(f"Enviando input a {args.host}:{args.port} a {args.rate} Hz. Ctrl+C para salir.\n")

    try:
        while True:
            start = time.time()

            # Si el mando se desconecta, pygame lo saca de la lista de joysticks.
            # Reintentamos reconectar en vez de crashear.
            if pygame.joystick.get_count() == 0:
                print("Mando desconectado. Esperando reconexión...")
                while pygame.joystick.get_count() == 0:
                    time.sleep(0.5)
                    pygame.joystick.quit()
                    pygame.joystick.init()
                joystick = pygame.joystick.Joystick(0)
                joystick.init()
                print(f"Mando reconectado: {joystick.get_name()}")

            try:
                state = build_state(joystick)
            except pygame.error:
                # El objeto joystick quedó inválido tras una desconexión momentánea
                pygame.joystick.quit()
                pygame.joystick.init()
                continue

            payload = json.dumps(state).encode("utf-8")
            sock.sendto(payload, (args.host, args.port))

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
