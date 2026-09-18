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
# set_config, cuando el servidor YA esta corriendo, no responde hasta que
# Iniciar-Servidor termina de reiniciar el motor completo (detener + esperar
# hasta 15s a que vuelva a levantar - ver server_engine_lib.ps1). Con solo
# 3s de timeout el cliente se rendia ANTES de que el servidor terminara,
# mostrando "sin respuesta del servidor" aunque el cambio si se aplicaba de
# verdad (confirmado en vivo: 2026-09-11, "el server no respondio... pero
# cuando abro y cierro el server si se ve el dato" - el timeout, no un bug
# del listener, era la causa real de fondo de ese reporte).
TIMEOUT_APLICAR_S = 20.0
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


def _pedir(ip_servidor, comando: dict, timeout=TIMEOUT_S):
    """Manda `comando` como JSON por UDP a ip_servidor:PUERTO_CONFIG y
    espera una respuesta (tambien JSON). Devuelve (True, dict) si hubo
    respuesta valida, o (False, mensaje_de_error) si no."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
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
    o (False, mensaje_de_error). Timeout largo (ver TIMEOUT_APLICAR_S): si el
    servidor esta corriendo, esto lo reinicia de verdad y puede tardar."""
    return _pedir(ip_servidor, {"cmd": "set_config", "ip": deck_ip, "modo": modo},
                  timeout=TIMEOUT_APLICAR_S)


def detener_servidor(ip_servidor):
    """-> (True, {"aplicado": "detenido"|"ya_estaba_detenido"}) o
    (False, mensaje_de_error). A diferencia de aplicar_config, esto SOLO
    apaga - no vuelve a arrancar con ninguna config (2026-09-17, pedido
    aparte de "Reiniciar servidor")."""
    return _pedir(ip_servidor, {"cmd": "stop_server"}, timeout=TIMEOUT_APLICAR_S)


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
