#!/usr/bin/env python3
"""Brillo de pantalla en Windows, equivalente al Brillo por sysfs de la Deck.

PORTEO: la Deck escribe directo a /sys/class/backlight/.../brightness (rw sin
sudo para el grupo "deck"). Windows no tiene ese archivo; el equivalente es la
clase WMI WmiMonitorBrightnessMethods (namespace root\\WMI), que es EXACTAMENTE
lo que usa el control deslizante de brillo del propio Windows para pantallas
integradas (laptops, y de esperar, handhelds como la Ally).

SIN VERIFICAR EN HARDWARE REAL: esto depende de que el driver de pantalla de la
Ally exponga esa clase WMI (normal en paneles de laptop con soporte ACPI de
brillo). Si no esta disponible, `ok` queda en False y la barra se deshabilita
sola, mismo comportamiento de fallback que en la Deck cuando el backlight no es
escribible.

Se hace por subprocess a powershell en vez de pywin32/wmi para no meter
dependencias COM pesadas en el build de PyInstaller (que ya de por si tiene que
empaquetar pygame). El costo es un proceso de powershell por lectura/escritura;
irrelevante aca porque el brillo se toca poco (al mover la barra, o una vez por
segundo al sincronizar).
"""

import subprocess
import time

# No baja de 1: igual que en la Deck, a oscuras total no se ve la propia barra
# para volver a subirla y esta ventana no escucha el mando.
PCT_MIN = 1

_PS_LEER = (
    "(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness "
    "-ErrorAction Stop).CurrentBrightness"
)

_PS_ESCRIBIR = (
    "$m = Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods "
    "-ErrorAction Stop; "
    "Invoke-CimMethod -InputObject $m -MethodName WmiSetBrightness "
    "-Arguments @{{Timeout=0; Brightness={pct}}} | Out-Null"
)

_CREATIONFLAGS = 0x08000000  # CREATE_NO_WINDOW: que no parpadee una consola


def _run_ps(script: str, timeout: float = 3.0):
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=timeout,
            creationflags=_CREATIONFLAGS,
        )
        if r.returncode != 0:
            return None
        return r.stdout.strip()
    except Exception:
        return None


class Brillo:
    def __init__(self):
        # Probar una lectura real para decidir si esta disponible. Igual que
        # Brillo.ok en la Deck (ahi era os.access; aca es "did WMI answer").
        self.ok = self.leer_pct() is not None
        self._ultimo_escrito = None

    def leer_pct(self):
        salida = _run_ps(_PS_LEER)
        if not salida:
            return None
        try:
            return int(float(salida))
        except ValueError:
            return None

    def escribir_pct(self, pct: int):
        if not self.ok:
            return
        pct = max(PCT_MIN, min(100, int(pct)))
        # Mismo motivo que en la Deck: no reescribir si ya estamos ahi, para
        # no generar trafico/parpadeo por nada cuando sincronizar() se llama
        # seguido desde el poll de 1s.
        if self._ultimo_escrito == pct:
            return
        _run_ps(_PS_ESCRIBIR.format(pct=pct))
        self._ultimo_escrito = pct
