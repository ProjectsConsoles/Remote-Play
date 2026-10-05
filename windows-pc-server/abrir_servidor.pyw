"""Acceso directo del escritorio (2026-10-05): si el servidor de PC ya corre, muestra su ventana; si no, lo
arranca con su tarea programada (asi corre igual que al iniciar sesion, sin duplicarse) y luego la muestra."""
import json
import socket
import subprocess
import time

PUERTO_CONFIG = 9200


def pedir(cmd, espera=1.5):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(espera)
    try:
        s.sendto(json.dumps({"cmd": cmd}).encode(), ("127.0.0.1", PUERTO_CONFIG))
        return json.loads(s.recvfrom(4096)[0])
    except (OSError, ValueError):
        return None
    finally:
        s.close()


if pedir("mostrar_ventana") is None:
    subprocess.run(["schtasks", "/run", "/tn", "PS3RP PC Server"], capture_output=True,
                   creationflags=subprocess.CREATE_NO_WINDOW)
    fin = time.monotonic() + 20
    while time.monotonic() < fin:
        time.sleep(1)
        if pedir("get_config", 1) is not None:
            time.sleep(2)   # la ventana se arma despues de abrir el puerto
            pedir("mostrar_ventana")
            break
