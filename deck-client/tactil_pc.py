#!/usr/bin/env python3
"""Modo PC (2026-10-05): tocar la pantalla de la Deck = usar el mouse de la PC, como TactilPc.kt en la
tableta Android. Lo arranca start_client_stream.sh junto con el cliente de input y lo mata al salir.

Lee la pantalla tactil DIRECTO de /dev/input (protocolo multitouch B del kernel) en vez de los eventos
de la ventana: la ventana del video es del reproductor (gst-launch/ffplay) y no hay forma de
engancharse a ella. Leer no "agarra" el dispositivo: gamescope y Steam lo siguen recibiendo igual
(los toques le llegan tambien a la ventana del video, que no hace nada con ellos).

PERMISO: /dev/input/eventN es root:input 0660 y deck no esta en el grupo input. La regla
70-ps3rp-tactil.rules (en esta carpeta) le da lectura al usuario de la sesion; se instala una vez con
sudo (ver la regla). Sin ella esto avisa en el log y termina: el streaming sigue sin tactil.

Gestos (iguales a Android):
    un dedo, tocar y soltar           -> clic izquierdo ahi
    un dedo, arrastrar                -> arrastrar (boton izquierdo apretado)
    dos dedos, tocar y soltar         -> clic derecho donde puso el primer dedo
    dos dedos, deslizar arriba/abajo  -> scroll

Manda {"mouse": {"ev": ..., "x": .., "y": ..}} por UDP al puerto del mando de la PC (pc_server.py), con
x/y de 0 a 1 sobre la imagen de la PC (se descuentan las barras negras o el recorte segun --ajuste).

TRACKPAD (2026-10-24, pedido del usuario: trackpad como mouse, R2 clic izquierdo, L2 derecho, sin estorbar
al control): Steam ya lo trae de fabrica en Modo Juego. Manteniendo el boton Steam, el trackpad derecho
mueve el puntero, Steam+R2 es clic izquierdo y Steam+L2 clic derecho; sin Steam, R2/L2 siguen siendo
gatillos. Nuestra app no ve el boton Steam (Steam se lo queda), pero ese puntero llega a la ventana del
juego: el display X de gamescope (:1). Medido: query_pointer ahi da la posicion (1280x800) y los botones
(Button1 = izquierdo, Button3 = derecho). bucle_puntero lo sigue a 120 Hz y lo manda a la PC con los mismos
eventos que el tactil. Tocar la pantalla tambien mueve ese puntero: mientras se toca (y 0.5 s despues) se
ignora, para no dar dos clics.

Ese puntero ademas lo dibuja gamescope encima del video y se veia junto al de la PC (que ya viene dentro
de la imagen). Se esconde poniendole un cursor transparente a las ventanas de ese display (probado en la
Deck: desaparece); al salir se regresa el de siempre.
"""

import argparse
import fcntl
import json
import os
import signal
import socket
import struct
import sys
import threading
import time

NOMBRE_TACTIL = "FTS3528:00 2808:1015"   # pantalla tactil de la Steam Deck (LCD y OLED)

# Pantalla de la Deck acostada y video de la PC (16:9).
PANTALLA_W, PANTALLA_H = 1280, 800
VIDEO_ASPECTO = 16 / 9

UMBRAL_PX = 20          # pixeles de pantalla antes de que un toque cuente como arrastre (~2 mm)

EV_SYN, EV_KEY, EV_ABS = 0, 1, 3
SYN_REPORT = 0
ABS_MT_SLOT, ABS_MT_POSITION_X, ABS_MT_POSITION_Y, ABS_MT_TRACKING_ID = 0x2F, 0x35, 0x36, 0x39
FORMATO_EVENTO = "llHHi"   # struct input_event en x86_64: timeval (2 long), type, code, value
TAM_EVENTO = struct.calcsize(FORMATO_EVENTO)


def log(msg):
    print(f"[tactil {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def buscar_dispositivo():
    """/dev/input/eventN de la pantalla tactil, por nombre (el numero cambia entre arranques)."""
    try:
        bloques = open("/proc/bus/input/devices").read().split("\n\n")
    except OSError:
        return None
    for b in bloques:
        if f'N: Name="{NOMBRE_TACTIL}"' in b:
            for linea in b.splitlines():
                if linea.startswith("H: Handlers="):
                    for h in linea.split("=", 1)[1].split():
                        if h.startswith("event"):
                            return "/dev/input/" + h
    return None


def rango_eje(fd, codigo):
    """(minimo, maximo) del eje con EVIOCGABS."""
    buf = bytearray(24)
    fcntl.ioctl(fd, 0x80184540 + codigo, buf)
    _, minimo, maximo, _, _, _ = struct.unpack("6i", buf)
    return minimo, maximo


class AVideo:
    """Del toque (coordenadas crudas del panel) a la posicion 0..1 en la pantalla acostada y en la imagen
    de la PC. El panel de la Deck es vertical (X 0..800 por el lado corto, Y 0..1280 por el largo) y se ve
    acostado. Medido en la Deck tocando las esquinas (2026-10-05): arriba-izquierda = x 771, y 35;
    abajo-derecha = x 50, y 1279. O sea: Y del panel = horizontal, X del panel = vertical al reves."""

    def __init__(self, rx, ry, ajuste):
        self.rx, self.ry, self.ajuste = rx, ry, ajuste

    def pantalla(self, tx, ty):
        """-> (sx, sy) de 0 a 1 en la pantalla tal como se ve (acostada)."""
        nx = (tx - self.rx[0]) / max(1, self.rx[1] - self.rx[0])
        ny = (ty - self.ry[0]) / max(1, self.ry[1] - self.ry[0])
        return ny, 1.0 - nx

    def video(self, sx, sy):
        """-> (vx, vy) de 0 a 1 en la imagen de la PC (puede salir de 0..1 en las barras; pc_server recorta)."""
        aspecto_pantalla = PANTALLA_W / PANTALLA_H
        if self.ajuste == "estirar":
            return sx, sy
        if self.ajuste == "zoom":
            # llena el alto y recorta los lados
            visible = aspecto_pantalla / VIDEO_ASPECTO       # fraccion del ancho del video que se ve
            return (1 - visible) / 2 + sx * visible, sy
        # barras: llena el ancho, franjas arriba y abajo
        alto = aspecto_pantalla / VIDEO_ASPECTO              # fraccion del alto de la pantalla con video
        return sx, (sy - (1 - alto) / 2) / alto


class Gestos:
    """La misma maquina de estados que TactilPc.kt, alimentada con un cuadro (SYN_REPORT) a la vez."""

    def __init__(self, mandar):
        self.mandar = mandar
        self.dedos_antes = 0
        self.x0 = self.y0 = 0.0
        self.arrastrando = False
        self.dos_dedos = False
        self.movio_dos = False
        self.y_dos = 0.0
        self.scroll = 0.0
        self.ultimo = (0.0, 0.0)

    def cuadro(self, puntos):
        """`puntos` = lista de (x, y) en pixeles de pantalla, en orden de slot (el primero es el primer dedo)."""
        n = len(puntos)
        if n and self.dedos_antes == 0:
            self.x0, self.y0 = puntos[0]
            self.arrastrando = self.dos_dedos = self.movio_dos = False
            self.mandar("mover", self.x0, self.y0)
        if n >= 2 and not self.arrastrando and not self.dos_dedos:
            self.dos_dedos = True
            self.y_dos = (puntos[0][1] + puntos[1][1]) / 2
            self.scroll = 0.0
        if n >= 2 and self.dos_dedos:
            y = (puntos[0][1] + puntos[1][1]) / 2
            self.scroll += y - self.y_dos
            self.y_dos = y
            paso = UMBRAL_PX * 2
            # dedos hacia abajo = contenido baja = rueda hacia arriba (como en el celular)
            while abs(self.scroll) >= paso:
                self.movio_dos = True
                arriba = self.scroll > 0
                self.mandar("scroll", d=1 if arriba else -1)
                self.scroll += -paso if arriba else paso
        elif n == 1 and not self.dos_dedos:
            x, y = puntos[0]
            if not self.arrastrando and ((x - self.x0) ** 2 + (y - self.y0) ** 2) ** 0.5 > UMBRAL_PX:
                self.arrastrando = True
                self.mandar("izq_abajo", self.x0, self.y0)
            if self.arrastrando:
                self.mandar("mover", x, y)
        if n:
            self.ultimo = puntos[0]
        if n == 0 and self.dedos_antes:
            if self.arrastrando:
                self.mandar("izq_arriba", *self.ultimo)
            elif self.dos_dedos:
                if not self.movio_dos:
                    self.mandar("clic_der", self.x0, self.y0)
            else:
                self.mandar("clic", self.x0, self.y0)
            self.arrastrando = self.dos_dedos = False
        self.dedos_antes = n


# hora del ultimo cuadro del tactil (para que bucle_puntero no repita lo que ya mando el tactil)
ULTIMO_TOQUE = [0.0]
PAUSA_TRAS_TOQUE_S = 0.5


def _ventanas(w):
    yield w
    try:
        hijas = w.query_tree().children
    except Exception:
        return
    for h in hijas:
        yield from _ventanas(h)


def cursor_vacio(d):
    """Cursor de 1x1 transparente (mascara en cero)."""
    pm = d.screen().root.create_pixmap(1, 1, 1)
    gc = pm.create_gc(foreground=0, background=0)
    pm.fill_rectangle(gc, 0, 0, 1, 1)
    return pm.create_cursor(pm, (0, 0, 0), (0, 0, 0), 0, 0)


def esconder_cursor(d, cursor, ya):
    """Pone `cursor` a las ventanas del display que todavia no lo tienen (`ya` = ids ya hechas)."""
    for w in _ventanas(d.screen().root):
        if w.id not in ya:
            try:
                w.change_attributes(cursor=cursor)
                ya.add(w.id)
            except Exception:
                pass      # la ventana ya no existe
    d.flush()


def restaurar_cursor():
    """Regresa el cursor normal (conexion aparte: la del hilo del trackpad puede estar ocupada)."""
    try:
        from Xlib import X, display
        d = display.Display(os.environ.get("DISPLAY") or ":1")
        for w in _ventanas(d.screen().root):
            try:
                w.change_attributes(cursor=X.NONE)
            except Exception:
                pass
        d.sync()
    except Exception:
        pass


def bucle_puntero(mandar):
    """El puntero de Steam (boton Steam + trackpad derecho; Steam+R2 / Steam+L2 = clics) -> mouse de la PC."""
    try:
        from Xlib import X, display
        d = display.Display(os.environ.get("DISPLAY") or ":1")
    except Exception as e:
        log(f"sin trackpad como mouse (no pude abrir el display X: {e})")
        return
    raiz = d.screen().root
    ancho, alto = d.screen().width_in_pixels, d.screen().height_in_pixels
    log(f"trackpad: puntero de Steam en {d.get_display_name()} ({ancho}x{alto}) -> mouse de la PC")
    # donde este el puntero al arrancar no cuenta: solo lo que se mueva despues (si no, el mouse de la PC
    # brincaria a la orilla donde quedo el puntero la ultima vez)
    p = raiz.query_pointer()
    antes = (p.root_x * PANTALLA_W / ancho, p.root_y * PANTALLA_H / alto)
    izq, der = bool(p.mask & X.Button1Mask), bool(p.mask & X.Button3Mask)
    vacio = cursor_vacio(d)
    escondidas = set()
    proxima_revision = 0.0
    while True:
        time.sleep(1 / 120)
        if time.monotonic() >= proxima_revision:
            # cada segundo: la ventana del video aparece despues de que arranca esto
            esconder_cursor(d, vacio, escondidas)
            proxima_revision = time.monotonic() + 1
        try:
            p = raiz.query_pointer()
        except Exception as e:
            log(f"trackpad: se perdio el display X ({e}); sin trackpad")
            return
        x, y = p.root_x * PANTALLA_W / ancho, p.root_y * PANTALLA_H / alto
        ahora_izq, ahora_der = bool(p.mask & X.Button1Mask), bool(p.mask & X.Button3Mask)
        if time.monotonic() - ULTIMO_TOQUE[0] < PAUSA_TRAS_TOQUE_S:
            # lo esta moviendo el tactil: solo se anota, sin mandar nada
            antes, izq, der = (x, y), ahora_izq, ahora_der
            continue
        if (x, y) != antes:
            mandar("mover", x, y)
            antes = (x, y)
        if ahora_izq != izq:
            mandar("izq_abajo" if ahora_izq else "izq_arriba", x, y)
            izq = ahora_izq
        if ahora_der and not der:
            mandar("clic_der", x, y)     # la PC no tiene "derecho abajo/arriba": el clic va al apretar
        der = ahora_der


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", required=True, help="IP de la PC")
    ap.add_argument("--port", type=int, default=9000)
    ap.add_argument("--ajuste", default="barras", choices=["barras", "estirar", "zoom"])
    args = ap.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    destino = (args.host, args.port)
    a = AVideo((0, 1), (0, 1), args.ajuste)     # el rango del panel se pone abajo, si hay tactil
    envio = threading.Lock()                    # tactil y trackpad mandan desde dos hilos

    def mandar(ev, x=None, y=None, d=0):
        j = {"ev": ev}
        if x is not None:
            vx, vy = a.video(x / PANTALLA_W, y / PANTALLA_H)
            j["x"] = round(min(1.0, max(0.0, vx)), 4)
            j["y"] = round(min(1.0, max(0.0, vy)), 4)
        if d:
            j["d"] = d
        try:
            with envio:
                sock.sendto(json.dumps({"mouse": j}).encode("ascii"), destino)
        except OSError:
            pass

    hilo_puntero = threading.Thread(target=bucle_puntero, args=(mandar,), daemon=True)
    hilo_puntero.start()

    ruta = buscar_dispositivo()
    if not ruta:
        log(f"no encontre la pantalla tactil ({NOMBRE_TACTIL}); sigo sin tactil.")
        hilo_puntero.join()
        return
    try:
        fd = os.open(ruta, os.O_RDONLY)
    except PermissionError:
        log(f"sin permiso para leer {ruta}: falta instalar 70-ps3rp-tactil.rules (ver el archivo). "
            "Sigo sin tactil.")
        hilo_puntero.join()
        return
    a.rx, a.ry = rango_eje(fd, ABS_MT_POSITION_X), rango_eje(fd, ABS_MT_POSITION_Y)
    log(f"{ruta} -> mouse de {args.host}:{args.port} (ajuste {args.ajuste})")

    gestos = Gestos(mandar)
    slots = {}      # slot -> [tracking_id, x crudo, y crudo]
    slot = 0
    while True:
        datos = os.read(fd, TAM_EVENTO * 64)
        for i in range(0, len(datos) - TAM_EVENTO + 1, TAM_EVENTO):
            _, _, tipo, codigo, valor = struct.unpack_from(FORMATO_EVENTO, datos, i)
            if tipo == EV_ABS:
                if codigo == ABS_MT_SLOT:
                    slot = valor
                elif codigo == ABS_MT_TRACKING_ID:
                    if valor < 0:
                        slots.pop(slot, None)
                    else:
                        slots[slot] = [valor, 0, 0]
                elif codigo == ABS_MT_POSITION_X and slot in slots:
                    slots[slot][1] = valor
                elif codigo == ABS_MT_POSITION_Y and slot in slots:
                    slots[slot][2] = valor
            elif tipo == EV_SYN and codigo == SYN_REPORT:
                ULTIMO_TOQUE[0] = time.monotonic()
                puntos = []
                for _, tx, ty in (slots[k] for k in sorted(slots, key=lambda k: slots[k][0])):
                    sx, sy = a.pantalla(tx, ty)
                    puntos.append((sx * PANTALLA_W, sy * PANTALLA_H))
                gestos.cuadro(puntos)


def _terminar(*_):
    raise KeyboardInterrupt      # start_client_stream.sh nos cierra con SIGTERM: salir por el finally


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _terminar)
    try:
        main()
    except KeyboardInterrupt:
        pass
    finally:
        restaurar_cursor()
    sys.exit(0)
