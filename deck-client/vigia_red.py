#!/usr/bin/env python3
"""Vigia de red del modo PC (2026-10-24): la parte de la calidad adaptativa que le tocaba al cliente.

El servidor de PC baja la calidad cuando la red se atora (pc_server.ControlCalidad). Por su lado solo ve los
atascos grandes (tiene que tirar paquetes o un envio tarda >50 ms); los avisos tempranos los da el cliente:
paquetes perdidos y cuadros que llegan desparejos (jitter). La tableta ya los manda (ReporteRed.kt); la Deck
no, porque el video lo recibe GStreamer y de ahi no se puede sacar eso.

Por eso este programa se mete en medio: recibe el video en el puerto de siempre (5000), lo reenvia al instante
a GStreamer en 127.0.0.1:<--hacia> y, mientras, mide lo mismo que la tableta. Cada 0.5 s manda a la PC el mismo
comando "red" (puerto 9200, sin respuesta), asi que la PC no cambia nada:

  - perdidos: paquetes TS que faltan, por el contador de continuidad de 4 bits de cada PID (TsDemuxer.kt).
  - jitter_ms: (llegada - pts) mas grande menos el mas chico de la ventana, en los inicios de cuadro del
    video (StreamActivity.kt). La captura sale pareja, asi que lo que varie es la red / el envio.
  - entrada_ms: hueco mas grande entre dos cuadros que llegaron. kbps: lo recibido.

Reenviar primero y medir despues: el cuadro no espera a las cuentas (<1 ms en total).
"""

import argparse
import json
import socket
import select
import time

TS = 188
PERIODO_S = 0.5


def leer_args():
    p = argparse.ArgumentParser()
    p.add_argument("--pc", required=True)                    # IP de la PC (a donde va el reporte)
    p.add_argument("--puerto-pc", type=int, default=9200)
    p.add_argument("--escucha", type=int, default=5000)      # donde llega el video de la PC
    p.add_argument("--hacia", type=int, default=5002)        # donde lo espera GStreamer
    return p.parse_args()


class Medidor:
    def __init__(self):
        self.cc = {}                # pid -> ultimo contador de continuidad
        self.pmt_pid = -1
        self.video_pid = -1
        self.perdidos = 0
        self.bytes = 0
        self.des_min = None         # (llegada - pts) en us, ventana actual
        self.des_max = None
        self.hueco_max = 0.0
        self.ult_cuadro = None

    def datagrama(self, d, llegada):
        self.bytes += len(d)
        for o in range(0, len(d) - TS + 1, TS):
            if d[o] == 0x47:
                self.paquete(d, o, llegada)

    def paquete(self, d, o, llegada):
        b1 = d[o + 1]
        if b1 & 0x80:
            return                                   # transport_error_indicator
        pusi = bool(b1 & 0x40)
        pid = ((b1 & 0x1F) << 8) | d[o + 2]
        if pid == 0x1FFF:
            return                                   # relleno (el relevo de la PC manda uno con la pantalla quieta)
        afc = (d[o + 3] >> 4) & 3
        if not afc & 1:
            return                                   # sin datos: el contador no avanza
        cc = d[o + 3] & 0x0F
        ant = self.cc.get(pid)
        # igual al anterior = paquete repetido (lo permite la norma), no es perdida
        if ant is not None and cc != ant:
            self.perdidos += (cc - ant - 1) & 0x0F
        self.cc[pid] = cc
        off = o + 4
        if afc & 2:
            off += 1 + d[off]
        fin = o + TS
        if off >= fin or not pusi:
            return
        if pid == 0:
            self.pat(d, off, fin)
        elif pid == self.pmt_pid:
            self.pmt(d, off, fin)
        elif pid == self.video_pid:
            self.inicio_cuadro(d, off, fin, llegada)

    def pat(self, d, off, fin):
        off += 1 + d[off]                            # pointer_field
        if off + 12 > fin:
            return
        largo = ((d[off + 1] & 0x0F) << 8) | d[off + 2]
        p = off + 8
        while p + 4 <= min(fin, off + 3 + largo - 4):
            programa = (d[p] << 8) | d[p + 1]
            if programa != 0:
                self.pmt_pid = ((d[p + 2] & 0x1F) << 8) | d[p + 3]
                return
            p += 4

    def pmt(self, d, off, fin):
        off += 1 + d[off]
        if off + 12 > fin:
            return
        largo = ((d[off + 1] & 0x0F) << 8) | d[off + 2]
        info = ((d[off + 10] & 0x0F) << 8) | d[off + 11]
        p = off + 12 + info
        tope = min(fin, off + 3 + largo - 4)
        while p + 5 <= tope:
            tipo = d[p]
            pid = ((d[p + 1] & 0x1F) << 8) | d[p + 2]
            if tipo == 0x1B:                         # H.264
                self.video_pid = pid
                return
            p += 5 + (((d[p + 3] & 0x0F) << 8) | d[p + 4])

    def inicio_cuadro(self, d, off, fin, llegada):
        if self.ult_cuadro is not None:
            self.hueco_max = max(self.hueco_max, llegada - self.ult_cuadro)
        self.ult_cuadro = llegada
        # cabecera PES: 00 00 01, stream_id, largo(2), banderas(2), largo de cabecera, PTS(5)
        if off + 14 > fin or d[off] != 0 or d[off + 1] != 0 or d[off + 2] != 1 or not d[off + 7] & 0x80:
            return
        p = d[off + 9:off + 14]
        pts = (((p[0] >> 1) & 0x07) << 30) | (p[1] << 22) | ((p[2] >> 1) << 15) | (p[3] << 7) | (p[4] >> 1)
        desfase = int(llegada * 1e6) - pts * 100 // 9
        if self.des_min is None or desfase < self.des_min:
            self.des_min = desfase
        if self.des_max is None or desfase > self.des_max:
            self.des_max = desfase

    def ventana(self, dt):
        """Reporte de la ventana que termina y arranca otra."""
        jitter = -1.0
        if self.des_min is not None and 0 <= self.des_max - self.des_min < 1_000_000:
            # si el pts salto (reinicio del servidor) el desfase cambia de golpe: no es jitter
            jitter = (self.des_max - self.des_min) / 1000.0
        r = {"cmd": "red", "perdidos": self.perdidos, "jitter_ms": round(jitter, 1),
             "entrada_ms": round(self.hueco_max * 1000, 1), "kbps": round(self.bytes * 8 / 1000 / dt, 1),
             "cliente": "deck"}
        self.perdidos = self.bytes = 0
        self.des_min = self.des_max = None
        self.hueco_max = 0.0
        return r


def main():
    a = leer_args()
    entrada = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    entrada.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
    entrada.bind(("0.0.0.0", a.escucha))
    salida = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    salida.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4 * 1024 * 1024)
    destino = ("127.0.0.1", a.hacia)
    reporte = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    m = Medidor()
    print(f"[vigia_red] {a.escucha} -> 127.0.0.1:{a.hacia}, reporte a {a.pc}:{a.puerto_pc} cada {PERIODO_S} s",
          flush=True)
    inicio_ventana = time.monotonic()
    hubo_video = False
    while True:
        listo, _, _ = select.select([entrada], [], [], PERIODO_S)
        if listo:
            d = entrada.recv(65536)
            try:
                salida.sendto(d, destino)
            except OSError:
                pass                                 # GStreamer todavia no abre o ya cerro: igual se mide
            m.datagrama(d, time.monotonic())
            hubo_video = True
        ahora = time.monotonic()
        if ahora - inicio_ventana >= PERIODO_S:
            r = m.ventana(ahora - inicio_ventana)
            inicio_ventana = ahora
            # sin nada en la ventana no se reporta: la PC no transmite o la red se corto del todo (ese caso lo
            # ve el relevo de la PC)
            if hubo_video:
                try:
                    reporte.sendto(json.dumps(r).encode(), (a.pc, a.puerto_pc))
                except OSError:
                    pass
            hubo_video = False


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
