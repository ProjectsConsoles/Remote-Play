#!/usr/bin/env python3
"""
Cliente de input para PS3 Remote Play - Steam Deck (v3)
----------------------------------------------------------
Mapeo confirmado empíricamente en hardware real (Steam Deck, con
lizard_mode desactivado vía /sys/module/hid_steam/parameters/lizard_mode).

NOTA: con lizard_mode=0, SDL detecta el mando NATIVO de la Deck
(no la emulación Xbox 360), por eso el D-pad llega como botones
sueltos (16-19) en vez de como hat, y hay botones extra (Steam,
acceso rápido, etc.)

Requisitos:
    pip install pygame

Uso:
    python3 input_client_v3.py --host 192.168.1.50 --port 9000 --debug
"""

import argparse
import json
import os
import signal
import socket
import subprocess
import time

import pygame

# ---------------------------------------------------------------------------
# Dos mapeos, elegidos en tiempo real segun que mando expone SDL
# ---------------------------------------------------------------------------
# Cual de los dos toca NO depende solo de lizard_mode: mientras el cliente de
# Steam este corriendo (o sea, SIEMPRE en Modo Juego) Steam se queda con el
# mando nativo y publica en su lugar un gamepad virtual "Microsoft X-Box 360
# pad" de 11 botones / 6 ejes / 1 hat. Con lizard_mode=0 y Steam cerrado, en
# cambio, aparece el mando NATIVO de la Deck (24 botones, sin hat).
#
# Esto fue exactamente el bug del 2026-08-28 ("en Modo Juego la Deck no mueve
# el PS3"): el script asumia siempre el mapeo nativo, asi que contra el pad
# virtual los nombres salian corridos (el boton fisico Start se mandaba como
# "L1", Select como "Y") y sobre todo SELECT/START -indices 11 y 12, que en
# un pad de 11 botones no existen- no se mandaban NUNCA. Como el firmware
# hace el boton PS con START+SELECT, el PS quedaba inalcanzable y el menu del
# PS3 no se podia cerrar.
#
# Los nombres que salen de aca son el contrato con el firmware del ESP32
# (ds3_controller.ino, funcion de parseo del JSON): A/B/X/Y, L1/R1,
# L2_CLICK/R2_CLICK, SELECT/START, L3_CLICK/R3_CLICK, STEAM, y los ejes
# LSTICK_*/RSTICK_*/L2_ANALOG/R2_ANALOG. Cualquier otro nombre el firmware
# lo ignora en silencio.

# --- Mando NATIVO de la Deck (lizard_mode=0 y sin Steam por delante) ---
# Confirmado empiricamente en hardware real. Los indices 0,1,14,15 y los
# grips traseros (L4/L5/R4/R5) todavia no estan confirmados - quedan como
# button_N generico hasta probarlos.
NATIVE_BUTTON_NAMES = {
    2: "QUICK_ACCESS",
    3: "A",
    4: "B",
    5: "X",
    6: "Y",
    7: "L1",
    8: "R1",
    9: "L2_CLICK",
    10: "R2_CLICK",
    11: "SELECT",
    12: "START",
    13: "STEAM",
    14: "L3_CLICK",
    15: "R3_CLICK",
    16: "DPAD_UP",
    17: "DPAD_DOWN",
    18: "DPAD_LEFT",
    19: "DPAD_RIGHT",
    20: "L4",
    21: "R4",
    22: "L5",
    23: "R5",
}

# Mapeo 100% confirmado en hardware real. Los gatillos analogicos NO
# estan en 4/5 (esos se quedan siempre en 0, no se usan) sino en 8/9.
# Convencion: -1.00 = gatillo suelto, +1.00 = gatillo a fondo.
NATIVE_AXIS_NAMES = {
    0: "LSTICK_X",
    1: "LSTICK_Y",
    2: "RSTICK_X",
    3: "RSTICK_Y",
    8: "R2_ANALOG",
    9: "L2_ANALOG",
}

# --- Gamepad virtual de Steam Input ("Microsoft X-Box 360 pad") ---
# Orden estandar del driver xpad de Linux, que es lo que Steam emula.
XINPUT_BUTTON_NAMES = {
    0: "A",
    1: "B",
    2: "X",
    3: "Y",
    4: "L1",       # LB
    5: "R1",       # RB
    6: "SELECT",   # Back / boton "vista" de la Deck
    7: "START",    # Start / boton "menu" de la Deck
    8: "STEAM",    # Guide (Steam normalmente lo intercepta antes)
    9: "L3_CLICK",
    10: "R3_CLICK",
}

# OJO: este NO es el mapeo de ejes de input_client_v2.py. Ese decia
# 2=RSTICK_X y 4=LT, y quedo desmentido midiendo el mando en reposo
# (2026-08-28): en reposo los ejes 2 y 5 marcan -1.00 y el resto 0.00, o sea
# que 2 y 5 son los gatillos (suelto = -1), no un stick. Coincide con el
# orden de xpad: X, Y, LT, RX, RY, RT.
XINPUT_AXIS_NAMES = {
    0: "LSTICK_X",
    1: "LSTICK_Y",
    2: "L2_ANALOG",
    3: "RSTICK_X",
    4: "RSTICK_Y",
    5: "R2_ANALOG",
}

# El pad de Xbox no tiene boton digital de gatillo, pero el firmware prende el
# bit L2/R2 del DS3 SOLO con L2_CLICK/R2_CLICK (el analogico se usa nada mas
# para el byte de presion). Sin sintetizar el click, L2/R2 no existirian para
# el PS3. Umbral en -0.5 = un cuarto de recorrido.
TRIGGER_CLICK_THRESHOLD = -0.5


def layout_for(joystick: "pygame.joystick.Joystick") -> str:
    """"native" o "xinput" segun el mando que SDL este exponiendo ahora.

    Se decide por cantidad de botones (el nativo tiene ~24, el virtual 11) y
    se recalcula en cada lectura, asi que si Steam arranca o se cierra con el
    cliente ya corriendo, el mapeo se acomoda solo.
    """
    return "native" if joystick.get_numbuttons() >= 16 else "xinput"


# ---------------------------------------------------------------------------
# Boton PS por acorde de botones
# ---------------------------------------------------------------------------
# QUE BOTONES SE PUEDEN USAR. Con el pad virtual de Steam Input (lo que ve SDL
# en Modo Juego, ver la nota de layout_for) hay dos que NO sirven:
#   - STEAM: Steam lo intercepta y nunca llega a pygame.
#   - START (☰): llega, pero no se queda sostenido. Medido el 2026-08-28: se
#     suelta a los ~2 cuadros (33 ms) por mas que lo mantengas apretado, porque
#     Steam se lo queda. Por eso el combo START+SELECT que ya trae el firmware
#     nunca se forma con el pad virtual, y hubo que armar el acorde aca.
# Quedan utilizables: A, B, X, Y, L1, R1, SELECT, L3_CLICK, R3_CLICK.
#
# POR QUE YA NO ES L3+R3 (2026-08-29). Era el acorde original, y el usuario se
# encontro con lo obvio en cuanto jugo de verdad: **hay juegos que usan L3+R3**
# (los dos clicks de stick juntos son un gesto real en varios titulos). Un falso
# positivo ahi no es menor: te saca del juego al XMB en medio de la partida.
#
# EL ANCLA ES LO QUE HACE QUE ESTO SEA SEGURO. El acorde se define como una
# lista de botones donde el PRIMERO es el ancla, y es el unico que se retiene:
#
#   - El ancla (SELECT por default, o sea ⧉) se guarda PS_CHORD_GUARD_S antes de
#     mandarse, por si los demas del acorde vienen en camino. Es un boton de
#     menu, retenerlo 80 ms no se siente.
#   - Los demas del acorde pasan SIN retencion, en el instante. Esto es
#     deliberado: si el acorde lleva R1 y se retuvieran todos, cada disparo del
#     juego llegaria 80 ms tarde. Inaceptable. El precio es que al hacer el
#     acorde se le cuela al PS3 un R1 suelto durante unos ms - inofensivo,
#     porque justo despues se abre el XMB.
#
# O sea que el ancla tiene que ser un boton de menu (SELECT), y el resto pueden
# ser botones de juego sin costo de latencia.
#
# COMO CAMBIARLO SIN TOCAR CODIGO:
#   PS3RP_PS_COMBO="SELECT+R1"        -> el default: comodo, dos botones
#   PS3RP_PS_COMBO="SELECT+L1+R1"     -> mas seguro todavia, practicamente
#                                        imposible de apretar sin querer
#   PS3RP_PS_COMBO="none"             -> desactivar el acorde del cliente
# El firmware sigue aceptando START+SELECT por su cuenta (applyPsCombo en
# ds3_controller.ino); eso solo se forma con el mando nativo, no con el virtual.
PS_CHORD_GUARD_S = 0.08

PS_CHORD_DEFAULT = "SELECT+R1"


def _parse_ps_combo(spec: str) -> list:
    """'SELECT+L1+R1' -> ['SELECT', 'L1', 'R1']. 'none'/'' -> []."""
    spec = (spec or "").strip()
    if not spec or spec.lower() in ("none", "no", "0", "off"):
        return []
    nombres = [t.strip().upper() for t in spec.split("+") if t.strip()]
    conocidos = set(NATIVE_BUTTON_NAMES.values()) | set(XINPUT_BUTTON_NAMES.values())
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
        # Mientras dure el acorde (y hasta soltar todo), no dejar pasar el ancla
        # por separado, ni siquiera de cola al soltar.
        buttons[ancla] = 0
        return

    since = _ps_chord["single_since"]
    if since != 0.0 and (now - since) < PS_CHORD_GUARD_S:
        buttons[ancla] = 0


def build_state(joystick: "pygame.joystick.Joystick") -> dict:
    pygame.event.pump()

    layout = layout_for(joystick)
    axis_names = NATIVE_AXIS_NAMES if layout == "native" else XINPUT_AXIS_NAMES
    button_names = (NATIVE_BUTTON_NAMES if layout == "native"
                    else XINPUT_BUTTON_NAMES)

    axes = {}
    for i in range(joystick.get_numaxes()):
        name = axis_names.get(i, f"axis_{i}")
        axes[name] = round(joystick.get_axis(i), 4)

    buttons = {}
    for i in range(joystick.get_numbuttons()):
        name = button_names.get(i, f"button_{i}")
        buttons[name] = joystick.get_button(i)

    if layout == "xinput":
        # Ver TRIGGER_CLICK_THRESHOLD: sin esto el PS3 no ve L2/R2.
        buttons["L2_CLICK"] = int(
            axes.get("L2_ANALOG", -1.0) > TRIGGER_CLICK_THRESHOLD)
        buttons["R2_CLICK"] = int(
            axes.get("R2_ANALOG", -1.0) > TRIGGER_CLICK_THRESHOLD)

    apply_ps_chord(buttons)

    hats = [joystick.get_hat(i) for i in range(joystick.get_numhats())]
    dpad_hat = hats[0] if hats else (0, 0)

    # Fallback: si el hat no se usa, arma el dpad desde los botones 16-19
    dpad_x = dpad_hat[0]
    dpad_y = dpad_hat[1]
    if dpad_x == 0 and dpad_y == 0:
        if buttons.get("DPAD_LEFT"):
            dpad_x = -1
        elif buttons.get("DPAD_RIGHT"):
            dpad_x = 1
        if buttons.get("DPAD_DOWN"):
            dpad_y = -1
        elif buttons.get("DPAD_UP"):
            dpad_y = 1

    return {
        "t": time.time(),
        "axes": axes,
        "buttons": buttons,
        "dpad": {"x": dpad_x, "y": dpad_y},
    }


def kill_stale_instances():
    """Mata otras instancias de este script que hayan quedado colgadas de
    pruebas anteriores (ej. de un `timeout ... &` en subshell que no las mato
    como se esperaba) - evita que manden UDP con estados contradictorios."""
    script_name = os.path.basename(__file__)
    my_pid = os.getpid()
    try:
        output = subprocess.check_output(["pgrep", "-f", script_name], text=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return
    for line in output.split():
        pid = int(line)
        if pid == my_pid:
            continue
        try:
            os.kill(pid, signal.SIGKILL)
            print(f"Instancia colgada matada: PID {pid}")
        except ProcessLookupError:
            pass


def connect_joystick():
    while True:
        pygame.joystick.quit()
        pygame.joystick.init()
        count = pygame.joystick.get_count()
        if count > 0:
            joystick = pygame.joystick.Joystick(0)
            joystick.init()
            layout = layout_for(joystick)
            print(f"Mando conectado: {joystick.get_name()} "
                  f"(ejes={joystick.get_numaxes()}, botones={joystick.get_numbuttons()}, "
                  f"hats={joystick.get_numhats()})")
            if layout == "native":
                print("Mapeo: NATIVO de la Deck (lizard_mode=0, sin Steam por delante).")
            else:
                print("Mapeo: gamepad virtual de Steam Input (Xbox 360). Normal en "
                      "Modo Juego o con Steam abierto.")
            return joystick
        print("No hay mando conectado. Reintentando en 2s...")
        time.sleep(2)


def main():
    parser = argparse.ArgumentParser(description="Cliente de input UDP para PS3 Remote Play")
    parser.add_argument("--host", help="IP del servidor")
    parser.add_argument("--port", type=int, default=9000)
    parser.add_argument("--rate", type=int, default=60)
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    if not args.list and not args.host:
        parser.error("--host es requerido salvo que uses --list")

    kill_stale_instances()

    pygame.init()
    pygame.joystick.init()

    if args.list:
        count = pygame.joystick.get_count()
        if count == 0:
            print("No se detectó ningún mando.")
            return
        for i in range(count):
            j = pygame.joystick.Joystick(i)
            j.init()
            print(f"  [{i}] {j.get_name()}  (ejes={j.get_numaxes()}, "
                  f"botones={j.get_numbuttons()}, hats={j.get_numhats()}) "
                  f"-> mapeo {layout_for(j)}")
        return

    joystick = connect_joystick()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    interval = 1.0 / args.rate

    print(f"\nEnviando input a {args.host}:{args.port} a {args.rate} Hz. Ctrl+C para salir.\n")

    consecutive_errors = 0
    # Contador de ritmo real. En Modo Juego no hay terminal donde mirar, y una
    # queja de "input lag" puede ser del video o de ESTE lazo: si el proceso no
    # alcanza a mandar sus 60 paquetes por segundo (Steam/gamescope compitiendo
    # por CPU, el mando virtual tardando en responder), cada tick perdido son
    # ~16 ms mas de retraso entre el boton y el PS3. Una linea cada 5 s al log
    # contesta eso sin instrumentar nada mas.
    stats_last = time.time()
    stats_ticks = 0
    last_snapshot = None
    try:
        while True:
            start = time.time()

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
                time.sleep(0.5)
                continue

            if args.debug:
                pressed = [k for k, v in state["buttons"].items() if v]
                axes_str = " ".join(f"{k}={v:+.2f}" for k, v in state["axes"].items())
                print(f"botones={pressed} dpad={state['dpad']} {axes_str}")

            # Traza por CAMBIO (siempre activa, no solo con --debug). En Modo
            # Juego no hay terminal a la vista, asi que cuando el usuario dice
            # "los botones salen chuecos" no hay forma de saber si el nombre
            # que sale de aca es el correcto o no. Imprimir cada paquete a
            # 120 Hz ahogaria el log; imprimir solo las transiciones deja una
            # linea por pulsacion, que es exactamente lo que hace falta para
            # comparar "aprete la cruz" contra "se mando A".
            snapshot = (tuple(k for k, v in state["buttons"].items() if v),
                        state["dpad"]["x"], state["dpad"]["y"])
            if snapshot != last_snapshot:
                last_snapshot = snapshot
                print(f"[botones] {list(snapshot[0])} dpad=({snapshot[1]},{snapshot[2]})")

            now = time.time()
            stats_ticks += 1
            if now - stats_last >= 5.0:
                span = now - stats_last
                print(f"[stats] {stats_ticks} paquetes en {span:.1f}s = "
                      f"{stats_ticks / span:.1f} Hz efectivos (objetivo {args.rate})")
                stats_last, stats_ticks = now, 0

            elapsed = now - start
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
