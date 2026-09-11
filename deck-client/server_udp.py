#!/usr/bin/env python3
"""Cliente UDP para hablar con config_listener.ps1 del lado del servidor
Windows (protocolo: un JSON por datagrama, puerto 9200 - ver ese script
para el detalle completo del protocolo).

Se guarda la IP del servidor en un archivo local para no tener que volver
a escribirla cada vez (independiente de la IP de la Deck, que ya se
detecta sola en client_menu.py - esta es la de la OTRA maquina)."""

import json
import os
import socket
import subprocess

PUERTO_CONFIG = 9200
TIMEOUT_S = 3.0
ARCHIVO_IP_SERVIDOR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "server_ip.txt")


def leer_ip_servidor_guardada():
    try:
        with open(ARCHIVO_IP_SERVIDOR) as f:
            ip = f.read().strip()
            return ip or None
    except Exception:
        return None


def guardar_ip_servidor(ip):
    try:
        with open(ARCHIVO_IP_SERVIDOR, "w") as f:
            f.write(ip.strip() + "\n")
    except Exception:
        pass


def _pedir(ip_servidor, comando: dict):
    """Manda `comando` como JSON por UDP a ip_servidor:PUERTO_CONFIG y
    espera una respuesta (tambien JSON). Devuelve (True, dict) si hubo
    respuesta valida, o (False, mensaje_de_error) si no."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(TIMEOUT_S)
    try:
        payload = json.dumps(comando).encode("utf-8")
        sock.sendto(payload, (ip_servidor, PUERTO_CONFIG))
        data, _ = sock.recvfrom(4096)
        respuesta = json.loads(data.decode("utf-8"))
        return True, respuesta
    except socket.timeout:
        return False, "Sin respuesta del servidor (timeout). ¿Esta prendido y en la misma red?"
    except OSError as e:
        return False, f"Error de red: {e}"
    except (json.JSONDecodeError, UnicodeDecodeError):
        return False, "El servidor respondio algo que no se pudo leer."
    finally:
        sock.close()


def obtener_config(ip_servidor):
    """-> (True, {"ip":..., "modo":..., "corriendo": bool, "modos": [...]})
    o (False, mensaje_de_error)."""
    return _pedir(ip_servidor, {"cmd": "get_config"})


def aplicar_config(ip_servidor, deck_ip, modo):
    """-> (True, {"aplicado": "reiniciado"|"guardado_para_proxima_vez", ...})
    o (False, mensaje_de_error)."""
    return _pedir(ip_servidor, {"cmd": "set_config", "ip": deck_ip, "modo": modo})


# ---------------------------------------------------------------------------
# Utilidades de red generales (movidas de client_menu.py, 2026-09-11: las
# necesita tambien la pantalla de "Configurar servidor" para mostrar/mandar
# la IP de esta Deck).
# ---------------------------------------------------------------------------

def obtener_ip_local():
    """IP de esta Deck en la red local. El truco del socket UDP "conectado"
    a 8.8.8.8 no manda ningun paquete: solo hace que el sistema operativo
    elija que interfaz de salida usaria, y de ahi se lee la IP local de esa
    interfaz. Funciona sin internet real."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def obtener_red_wifi():
    """Nombre (SSID) de la red Wi-Fi conectada ahora, o None si no hay
    conexion inalambrica activa (por ejemplo, si esta por cable)."""
    try:
        salida = subprocess.check_output(
            ["nmcli", "-t", "-f", "active,ssid", "dev", "wifi"],
            text=True, timeout=2)
        for linea in salida.splitlines():
            if linea.startswith("yes:"):
                return linea.split(":", 1)[1]
    except Exception:
        pass
    return None
