#!/usr/bin/env python3
"""WiFi sin ahorro de energia en Windows (equivalente al `iw ... power_save` de la Deck).

Windows deja el adaptador WiFi dormirse entre paquetes ("Modo de ahorro de
energia" del adaptador inalambrico); eso mete jitter/delay en un stream de
video. La palanca es el ajuste de plan de energia del subgrupo "Configuracion
de adaptador inalambrico" -> "Modo de ahorro de energia":
0 = Rendimiento maximo ... 3 = Ahorro maximo. Se toca con `powercfg`, que no
pide administrador para el plan de energia del usuario. Corriente alterna (AC,
enchufada) y continua (DC, bateria) son valores separados: se ponen los dos.

SIN VERIFICAR EN LA ALLY REAL: los GUID y el formato de `powercfg /query` se
comprobaron en la PC servidor (Windows), pero ahi no hay que cambiar nada (ya
esta en 0). Todo es NO FATAL: si powercfg falla, solo queda una linea en el
log y el cliente sigue normal.

Los valores originales se guardan (wifi_power_original.json junto al exe) la
primera vez que se cambian, para poder devolverlos al poner el interruptor en
NO en vez de adivinar un default.
"""

import json
import logging
import os
import re
import subprocess

log = logging.getLogger("ps3rp.wifi_power")

SUB_INALAMBRICO = "19cbb8fa-5279-450e-9fac-8a3d5fedd0c1"
AJUSTE_AHORRO = "12bbebe6-58d6-4636-95bb-3217ef867c1a"
MAX_RENDIMIENTO = 0
TIMEOUT_S = 8

_RE_GUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
_RE_HEX = re.compile(r"0x([0-9a-fA-F]{8})\s*$")


def _powercfg(*args):
    # CREATE_NO_WINDOW: sin esto el exe --windowed abre una consola negra un
    # instante. stdin/stdout/stderr explicitos por lo mismo que ffplay (ver
    # main_client.py).
    r = subprocess.run(
        ["powercfg", *args],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        timeout=TIMEOUT_S, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    salida = r.stdout.decode("cp850", errors="replace")
    if r.returncode != 0:
        raise RuntimeError("powercfg %s -> %d: %s" % (
            " ".join(args), r.returncode, r.stderr.decode("cp850", errors="replace").strip()))
    return salida


def _plan_activo():
    m = _RE_GUID.search(_powercfg("/getactivescheme"))
    if not m:
        raise RuntimeError("no se pudo leer el plan de energia activo")
    return m.group(0).lower()


def _leer_valores(plan):
    """(ac, dc) actuales, o None si el adaptador no expone el ajuste."""
    hexes = []
    for linea in _powercfg("/query", plan, SUB_INALAMBRICO, AJUSTE_AHORRO).splitlines():
        m = _RE_HEX.search(linea)
        if m:
            hexes.append(int(m.group(1), 16))
    # Las dos ultimas lineas con 0x........ son el indice AC y el DC actuales
    # (independiente del idioma de Windows; las "posibles" salen antes).
    if len(hexes) < 2:
        return None
    return hexes[-2], hexes[-1]


def _escribir(plan, ac, dc):
    _powercfg("/setacvalueindex", plan, SUB_INALAMBRICO, AJUSTE_AHORRO, str(ac))
    _powercfg("/setdcvalueindex", plan, SUB_INALAMBRICO, AJUSTE_AHORRO, str(dc))
    _powercfg("/setactive", plan)


def _cargar_originales(archivo):
    try:
        with open(archivo, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _guardar_originales(archivo, datos):
    try:
        with open(archivo, "w", encoding="utf-8") as f:
            json.dump(datos, f, indent=2)
    except Exception as e:
        log.warning("No se pudieron guardar los valores originales de WiFi: %s", e)


def aplicar(sin_ahorro, archivo_originales):
    """sin_ahorro=True: adaptador en Rendimiento maximo. False: devuelve lo original.

    Devuelve un texto corto para el log; nunca lanza.
    """
    try:
        plan = _plan_activo()
        actual = _leer_valores(plan)
        if actual is None:
            return "el adaptador WiFi no expone 'Modo de ahorro de energia' (sin cambios)"
        originales = _cargar_originales(archivo_originales)

        if sin_ahorro:
            if actual == (MAX_RENDIMIENTO, MAX_RENDIMIENTO):
                return "ya estaba en Rendimiento maximo (AC y DC)"
            # Guardar el original solo si no hay ya uno de este plan: si se
            # aplica dos veces, el "actual" de la segunda ya es el nuestro.
            if plan not in originales:
                originales[plan] = list(actual)
                _guardar_originales(archivo_originales, originales)
            _escribir(plan, MAX_RENDIMIENTO, MAX_RENDIMIENTO)
            return "Rendimiento maximo puesto (antes AC=%d DC=%d)" % actual

        ori = originales.get(plan)
        if not ori:
            return "sin cambios (no hay valores originales guardados de este plan)"
        if tuple(ori) != actual:
            _escribir(plan, ori[0], ori[1])
        del originales[plan]
        _guardar_originales(archivo_originales, originales)
        return "restaurado AC=%d DC=%d" % (ori[0], ori[1])
    except Exception as e:
        return "AVISO: no se pudo ajustar el WiFi (%s)" % e
