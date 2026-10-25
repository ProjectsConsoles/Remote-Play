#!/usr/bin/env python3
"""Motor de video con calidad ajustable en caliente (2026-10-22): hace lo mismo que la linea de ffmpeg de
pc_server.py (ddagrab -> NVENC -> MPEG-TS por UDP al relevo, audio Opus desde stdin), pero con PyAV, para poder
cambiar el bitrate de NVENC SIN reiniciar nada. ffmpeg por linea de comandos no lo permite: reiniciarlo para
bajar la calidad seria justo el corton que se quiere evitar.

Como YouTube, pero sin colchon: cuando la red se atora (lo detectan la tableta y el relevo, ver
pc_server.ControlCalidad) se baja la calidad un rato en vez de congelarse, y luego se sube poco a poco.

Medido en la laptop (RTX 4060, prueba_bitrate.py): cambiar codec_context.bit_rate con el codificador abierto
funciona al instante (15 -> 5 -> 2 -> 15 Mbps). Cada cambio fuerza UN cuadro clave (ffmpeg reinicia NVENC con
forceIDR): ~1.5 veces un cuadro normal, y los 2-3 siguientes salen chicos (un instante borroso). Por eso
pc_server no cambia la calidad mas de una vez por segundo.

Lo lanza pc_server.py como proceso aparte (como a ffmpeg): si PyAV se cae no tumba el servidor, terminate()
lo detiene aunque ddagrab este esperando un cuadro con la pantalla quieta, y el audio llega por stdin igual.

Uso (todo lo pone pc_server):
  pythonw motor_video.py --destino 127.0.0.1:5099 --control 5098 --fps 240 --bitrate 60000000 ...
Ordenes por UDP a 127.0.0.1:<control>: {"bitrate": bps} (bps ya escalado por FPS/60, como -b:v).
"""

import argparse
import json
import os
import socket
import sys
import threading
import time
import traceback
from fractions import Fraction

import av
import av.filter
import numpy as np


def leer_args():
    p = argparse.ArgumentParser()
    p.add_argument("--destino", required=True)          # host:puerto del relevo
    p.add_argument("--control", type=int, required=True)
    p.add_argument("--fps", type=int, default=240)
    p.add_argument("--dup", type=int, default=0)
    p.add_argument("--bitrate", type=int, required=True)
    p.add_argument("--bufsize", type=int, default=500_000)
    p.add_argument("--intra", type=int, default=1)
    p.add_argument("--ciclo", type=int, default=30)
    p.add_argument("--max_interleave", type=int, default=50000)
    p.add_argument("--audio", default="")                # "tasa,canales" (s16le por stdin) o vacio
    p.add_argument("--progreso", required=True)
    p.add_argument("--log", required=True)
    # prueba por SSH (ddagrab solo captura en la sesion del usuario): imagen sintetica en vez de la pantalla
    p.add_argument("--prueba", action="store_true")
    return p.parse_args()


class Motor:
    def __init__(self, a):
        self.a = a
        self.log = open(a.log, "a", buffering=1, encoding="utf-8")
        self.cerrojo = threading.Lock()      # mux desde dos hilos (video y audio)
        self.t0 = time.perf_counter()
        self.bitrate_pedido = a.bitrate
        self.bitrate_actual = a.bitrate
        self.cuadros = 0
        self.bytes = 0
        self.cambios = 0
        self.vivo = True

    def escribir(self, texto):
        self.log.write(time.strftime("%Y-%m-%d %H:%M:%S ") + texto + "\n")

    # ---- salida -------------------------------------------------------------------------------------------
    def abrir_salida(self, ancho, alto):
        a = self.a
        host, puerto = a.destino.rsplit(":", 1)
        # mismas opciones que la linea de ffmpeg: -muxdelay 0 (max_delay), -flush_packets 1,
        # -max_interleave_delta, -pes_payload_size 0 (cada cuadro en cuanto sale, sin juntar)
        self.cont = av.open(f"udp://{host}:{puerto}?pkt_size=1316&buffer_size=4194304", "w", format="mpegts",
                            container_options={"max_delay": "0", "flush_packets": "1",
                                               "max_interleave_delta": str(a.max_interleave),
                                               "pes_payload_size": "0"})
        v = self.cont.add_stream("h264_nvenc", rate=a.fps)
        c = v.codec_context
        c.width, c.height = ancho, alto
        c.pix_fmt = "bgra"                       # NVENC toma BGRA directo: sin convertir en la CPU
        c.time_base = Fraction(1, 1_000_000)     # pts en microsegundos (la hora de captura)
        c.framerate = Fraction(a.fps, 1)         # NVENC reparte el bitrate segun esto (como -b:v escalado)
        c.max_b_frames = 0
        self._poner_bitrate(c, a.bitrate)
        opciones = {"preset": "p1", "tune": "ull", "zerolatency": "1", "rc": "cbr", "rc-lookahead": "0",
                    "delay": "0"}
        if a.intra:
            # intra-refresh + la configuracion (SPS/PPS) en cada cuadro, ver pc_server.Transmision.iniciar
            c.gop_size = a.ciclo
            opciones.update({"intra-refresh": "1", "flags": "+global_header"})
        else:
            c.gop_size = 30
        c.options = opciones
        self.video = v
        self.audio = None
        if a.audio:
            s = self.cont.add_stream("libopus", rate=48000)
            ca = s.codec_context
            ca.layout = "stereo"
            ca.format = "s16"
            ca.bit_rate = 96000
            ca.options = {"application": "lowdelay", "frame_duration": "5"}
            self.audio = s
        # los dos abiertos (y la cabecera del TS escrita) ANTES de arrancar los hilos: si no, el primer mux
        # de cualquiera de los dos abriria el otro codificador mientras ese hilo lo usa
        c.open()
        if self.audio is not None:
            self.audio.codec_context.open()
        self.cont.start_encoding()
        self.cabecera = bytes(c.extradata or b"") if a.intra else b""

    def _poner_bitrate(self, c, bps):
        c.bit_rate = bps
        c.max_bit_rate = bps
        # el buffer se escala con el bitrate: igual de chico en tiempo (latencia), no en bytes
        c.rc_buffer_size = max(50_000, int(self.a.bufsize * bps / self.a.bitrate))

    def mux(self, paquetes, es_video):
        for p in paquetes:
            if es_video:
                self.bytes += p.size
                if self.cabecera:
                    # dump_extra=freq=all: un cliente que se une tarde (o tras perder datos) puede arrancar
                    # con cualquier cuadro
                    n = av.Packet(self.cabecera + bytes(p))
                    n.pts, n.dts, n.time_base = p.pts, p.dts, p.time_base
                    n.is_keyframe = p.is_keyframe
                    n.stream = self.video
                    p = n
            with self.cerrojo:
                self.cont.mux(p)

    # ---- video --------------------------------------------------------------------------------------------
    def grafo(self):
        a = self.a
        g = av.filter.Graph()
        if a.prueba:
            src = g.add("testsrc2", "size=1920x1080:rate=60")
            dl = g.add("realtime")
        else:
            src = g.add("ddagrab", f"output_idx=0:framerate={a.fps}:dup_frames={a.dup}:draw_mouse=1")
            # La pantalla de esta laptop (Optimus) la maneja la Intel: los cuadros se bajan a memoria y NVENC
            # los sube a la RTX (el camino directo D3D11 -> NVENC no se puede desde PyAV).
            dl = g.add("hwdownload")
        fm = g.add("format", "bgra")
        sk = g.add("buffersink")
        src.link_to(dl)
        dl.link_to(fm)
        fm.link_to(sk)
        g.configure()
        return g

    def bucle_video(self, g, primero):
        c = self.video.codec_context
        base = primero.time        # segundos segun ddagrab
        desfase = time.perf_counter() - self.t0
        cuadro = primero
        while self.vivo:
            if self.bitrate_pedido != self.bitrate_actual:
                antes = self.bitrate_actual
                self.bitrate_actual = self.bitrate_pedido
                self._poner_bitrate(c, self.bitrate_actual)
                self.cambios += 1
                self.escribir(f"bitrate {antes / 1e6:.1f} -> {self.bitrate_actual / 1e6:.1f} M (codificador)")
            # pts = hora de captura de ddagrab (lo que usa el ritmo parejo de la tableta), en el mismo reloj
            # que el audio
            cuadro.pts = int(((cuadro.time - base) + desfase) * 1_000_000)
            cuadro.time_base = c.time_base
            self.mux(self.video.encode(cuadro), True)
            self.cuadros += 1
            cuadro = g.pull()

    # ---- audio --------------------------------------------------------------------------------------------
    def bucle_audio(self, tasa, canales):
        """s16le por stdin en bloques de 5 ms a ritmo de reloj (pc_server._abrir_loopback.copiar)."""
        bloque = tasa // 200
        bytes_bloque = bloque * canales * 2
        entrada = sys.stdin.buffer
        disposicion = "stereo" if canales == 2 else "mono"
        remuestreo = av.AudioResampler(format="s16", layout="stereo", rate=48000)
        fifo = av.AudioFifo()
        enc = self.audio.codec_context
        n = 0
        inicio = None
        salida = 0         # muestras a 48 kHz ya codificadas
        while self.vivo:
            datos = entrada.read(bytes_bloque)
            if not datos or len(datos) < bytes_bloque:
                break
            if inicio is None:
                inicio = time.perf_counter() - self.t0
            f = av.AudioFrame.from_ndarray(np.frombuffer(datos, np.int16).reshape(1, -1), format="s16",
                                           layout=disposicion)
            f.sample_rate = tasa
            f.time_base = Fraction(1, tasa)
            f.pts = int(inicio * tasa) + n * bloque
            n += 1
            for r in remuestreo.resample(f):
                r.pts = None       # la fifo exige pts seguidos desde 0; la hora se pone abajo
                fifo.write(r)
            while True:
                trozo = fifo.read(enc.frame_size or 240)
                if trozo is None:
                    break
                trozo.pts = int(inicio * 48000) + salida
                trozo.time_base = Fraction(1, 48000)
                salida += trozo.samples
                self.mux(self.audio.encode(trozo), False)

    # ---- ordenes y progreso -------------------------------------------------------------------------------
    def bucle_control(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.bind(("127.0.0.1", self.a.control))
        while self.vivo:
            datos, _ = s.recvfrom(4096)
            try:
                bps = int(json.loads(datos)["bitrate"])
            except (ValueError, KeyError, TypeError):
                continue
            if bps > 0:
                self.bitrate_pedido = bps     # lo aplica el hilo de video antes del siguiente cuadro

    def bucle_progreso(self):
        """Mismo formato que -progress de ffmpeg: lo lee la ventana (pc_gui._leer_progreso)."""
        while self.vivo:
            time.sleep(1)
            with open(self.a.progreso, "a") as f:
                f.write(f"frame={self.cuadros}\ntotal_size={self.bytes}\n"
                        f"out_time_us={int((time.perf_counter() - self.t0) * 1e6)}\n"
                        f"bitrate_objetivo={self.bitrate_actual}\nprogress=continue\n")

    def correr(self):
        a = self.a
        g = self.grafo()
        primero = g.pull()
        self.abrir_salida(primero.width, primero.height)
        self.escribir(f"motor PyAV {av.__version__}: {primero.width}x{primero.height}, {a.fps} fps, "
                      f"{a.bitrate / 1e6:.1f} M, audio={a.audio or 'no'} -> {a.destino}")
        for objetivo, args in ((self.bucle_control, ()), (self.bucle_progreso, ())):
            threading.Thread(target=objetivo, args=args, daemon=True).start()
        if self.audio is not None:
            tasa, canales = (int(x) for x in a.audio.split(","))
            threading.Thread(target=self._audio_seguro, args=(tasa, canales), daemon=True).start()
        self.bucle_video(g, primero)

    def _audio_seguro(self, tasa, canales):
        try:
            self.bucle_audio(tasa, canales)
        except Exception:
            self.escribir("audio se cayo (sigue solo el video):\n" + traceback.format_exc())
            # seguir leyendo stdin y tirarlo: si nadie lo lee, el hilo de audio de pc_server se traba escribiendo
            while sys.stdin.buffer.read(65536):
                pass


def main():
    a = leer_args()
    m = Motor(a)
    try:
        m.correr()
    except av.error.PermissionError:
        # ddagrab sin permiso: Windows muestra la ventana de permisos de administrador (escritorio protegido)
        # o la pantalla esta bloqueada. No es falla del motor: pc_server reintenta con este mismo motor.
        m.escribir("Windows no deja capturar la pantalla (Desktop duplication access denied)")
        m.log.flush()
        os._exit(3)
    except Exception:
        m.escribir("motor se cayo:\n" + traceback.format_exc())
        m.log.flush()
        os._exit(1)      # sin esperar a los hilos: pc_server ve que murio y decide (ver bucle_vigia)


if __name__ == "__main__":
    main()
