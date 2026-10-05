#!/usr/bin/env python3
"""Servidor de PC (2026-10-05): jugar los juegos de ESTA PC en la tableta Android, con el mismo cliente
que ya se usa para el PS3 (en vez de Moonlight/Sunshine, que al usuario le daban mucho lag).

Tres partes, todas en este proceso:

  1. Puerto UDP 9200: el mismo protocolo que config_listener.ps1 del servidor de la capturadora, para
     que la app Android (ConsolaActivity -> "PC") lo use igual:
        {"cmd": "get_config"}                    -> estado
        {"cmd": "set_config", "ip": ..., ...}    -> transmitir a esa IP (reinicia si ya transmitia)
        {"cmd": "stop_server"}                   -> dejar de transmitir
  2. Transmision: ffmpeg captura la pantalla con ddagrab (Desktop Duplication) y la codifica con NVENC
     con los MISMOS ajustes de baja latencia del servidor del PS3 (start_server_stream.bat): H.264 p1 ull,
     sin B-frames, intra-refresh, Opus lowdelay de 5 ms, MPEG-TS con -pes_payload_size 0 por UDP al puerto
     5000 (a traves del relevo local, ver bucle_relevo). Detalles y ajustes en README.md.
     El audio es lo que suena en la PC (loopback de WASAPI con PyAudioWPatch), metido a ffmpeg por stdin:
     la laptop no tiene "Mezcla estereo".
  3. Puerto UDP 9000: el JSON del mando que la tableta le manda al ESP32 (GamepadState.toJson) se
     convierte en un control de Xbox 360 virtual (ViGEmBus + vgamepad). Los juegos lo ven como un
     control real.

Si la tableta deja de mandar el mando por SIN_MANDO_S, se deja de transmitir (la app no avisa al salir).

TIENE QUE CORRER EN LA SESION DEL USUARIO, no por SSH: ddagrab no puede capturar desde la sesion 0
(sin escritorio). Lo arranca la tarea programada "PS3RP PC Server" (instalar_tarea.ps1) al iniciar sesion.

Log: pc_server.log junto a este archivo.
"""

import glob
import json
import logging
import os
import shutil
import socket
import subprocess
import threading
import time

CARPETA = os.path.dirname(os.path.abspath(__file__))
logging.basicConfig(filename=os.path.join(CARPETA, "pc_server.log"), level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("pc")

PUERTO_CONFIG = 9200
PUERTO_MANDO = int(os.environ.get("PS3RP_PC_PUERTO_MANDO", "9000"))
PUERTO_VIDEO = int(os.environ.get("PS3RP_PC_PUERTO_VIDEO", "5000"))
# ffmpeg no manda directo a la tableta sino a este puerto local, y bucle_relevo reenvia (ver alli por que)
PUERTO_RELEVO = int(os.environ.get("PS3RP_PC_PUERTO_RELEVO", "5099"))
# Captura a FPS cuadros por segundo. Con muestreo fijo a 60 contra una pantalla de 144 Hz se repetian/saltaban
# cuadros: 51 distintos por segundo de un juego a 60 (medido 2026-10-05, "se ve con pocos fps"); a 90 cada
# cuadro de un juego a 60 dura mas que el intervalo de muestreo y ninguno se pierde.
# DUP_FRAMES=0 (default, "solo cuadros nuevos"): sale un cuadro solo cuando la pantalla cambia. Con 1 se repiten
# cuadros hasta FPS: medido 2026-10-05 con el juego a 60, la tableta recibia ~70/s con repetidos a destiempo y su
# pantalla de 60 Hz tiraba algunos de los buenos (tirones, "no veo 60"); con 0 salen ~59 distintos.
# Con la pantalla quieta no sale video: para que el AUDIO siga, el muxer espera al video a lo mucho
# MAX_INTERLEAVE_US (con 0 esperaba para siempre y se callaba todo), y la tableta conserva la ultima imagen y
# retoma sola con el siguiente cuadro (VideoPlayer.puedeArrancar).
# NVENC reparte el bitrate segun FPS, asi que se escala para que a 60 fps reales salgan ~BITRATE_MBPS.
# 240 (2026-10-05): con "solo cuadros nuevos" FPS es cuantas veces se REVISA la pantalla, y cada cuadro sale con
# la hora de la revision. A 90 los cuadros de un juego a 60 salian con horas de 11/22 ms (0 % a 16.7 +-3 ms) y el
# ritmo parejo de la tableta los mostraba disparejos; a 240: 98 % parejos, mismos fps (59.6) y mismos Mbps reales.
FPS = int(os.environ.get("PS3RP_PC_FPS", "240"))
DUP_FRAMES = os.environ.get("PS3RP_PC_DUP_FRAMES", "0") == "1"
MAX_INTERLEAVE_US = os.environ.get("PS3RP_PC_MAX_INTERLEAVE_US", "50000")
BITRATE_MBPS = float(os.environ.get("PS3RP_PC_BITRATE_MBPS", "15"))
BITRATE = f"{BITRATE_MBPS * FPS / 60:.1f}M"
SIN_MANDO_S = 60
INTRA_REFRESH = os.environ.get("PS3RP_PC_INTRA_REFRESH", "1") == "1"
# Mientras se transmite, la salida predeterminada pasa a esta "bocina" virtual (la instala Steam) para que
# el juego no suene en la laptop y se capture de ahi; al terminar se regresa la que estaba. Vacio = no tocar.
SALIDA_VIRTUAL = os.environ.get("PS3RP_PC_SALIDA_VIRTUAL", "Steam Streaming Speakers")
ARCHIVO_SALIDA_PREVIA = os.path.join(CARPETA, "salida_previa.txt")
# Mientras se transmite la pantalla de la laptop se pone NEGRA (brillo 0) y al detener vuelve el brillo que tenia
# (pedido 2026-10-05). Apagarla de verdad no sirve: con el monitor apagado Windows deja de entregar cuadros a la
# captura (Desktop Duplication) y la tableta se quedaria sin video.
APAGAR_PANTALLA = os.environ.get("PS3RP_PC_APAGAR_PANTALLA", "1") == "1"
ARCHIVO_BRILLO_PREVIO = os.path.join(CARPETA, "brillo_previo.txt")


def buscar_ffmpeg():
    if os.environ.get("PS3RP_FFMPEG") and os.path.isfile(os.environ["PS3RP_FFMPEG"]):
        return os.environ["PS3RP_FFMPEG"]
    # winget (Gyan.FFmpeg) lo deja aqui y su alias no siempre esta en el PATH de una tarea programada
    for f in glob.glob(os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg*\*\bin\ffmpeg.exe")):
        return f
    # el del servidor de consolas, si esta en el mismo paquete (lanzador unico, 2026-10-05): en la carpeta de
    # arriba del servidor de PC o en consolas\
    arriba = os.path.dirname(CARPETA)
    for d in (CARPETA, arriba, os.path.join(arriba, "consolas")):
        for f in glob.glob(os.path.join(d, "ffmpeg-*", "bin", "ffmpeg.exe")):
            return f
    return shutil.which("ffmpeg")


# ------------------------------------------------------------------------------------------------
# Salida de audio: que el juego suene en la tableta y NO en la laptop (reportado 2026-10-05)
# ------------------------------------------------------------------------------------------------
def _dispositivos_salida():
    """{nombre: id} de las salidas de audio activas (pycaw). COM se inicializa en el hilo que llama."""
    import warnings
    try:
        import comtypes
        comtypes.CoInitialize()
    except Exception:
        pass
    from pycaw.utils import AudioUtilities
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        todos = AudioUtilities.GetAllDevices()
        bocinas = AudioUtilities.GetSpeakers()
    salidas = {d.FriendlyName: d.id for d in todos
               if d.id and d.id.startswith("{0.0.0.") and "Active" in str(d.state)}
    actual = getattr(bocinas, "id", None) or bocinas.GetId()
    return salidas, actual


def _poner_salida(dev_id):
    from pycaw.utils import AudioUtilities
    AudioUtilities.SetDefaultDevice(dev_id)


def silenciar_laptop():
    """Pone SALIDA_VIRTUAL como predeterminada. Devuelve el id de la que estaba (o None si no se cambio)."""
    if not SALIDA_VIRTUAL:
        return None
    try:
        salidas, actual = _dispositivos_salida()
        virtual = next((i for n, i in salidas.items() if SALIDA_VIRTUAL.lower() in n.lower()), None)
        if not virtual:
            log.warning("no hay '%s': el audio tambien sonara en la PC", SALIDA_VIRTUAL)
            return None
        if virtual == actual:
            return None
        with open(ARCHIVO_SALIDA_PREVIA, "w") as f:
            f.write(actual)     # por si el servidor se cae: al volver a arrancar se restaura
        _poner_salida(virtual)
        log.info("salida de audio -> %s (estaba %s)", SALIDA_VIRTUAL, actual)
        return actual
    except Exception as e:
        log.error("no se pudo cambiar la salida de audio: %s", e)
        return None


def restaurar_salida(previa=None):
    if previa is None:
        try:
            with open(ARCHIVO_SALIDA_PREVIA) as f:
                previa = f.read().strip()
        except OSError:
            return
    try:
        _dispositivos_salida()   # inicializa COM en este hilo
        _poner_salida(previa)
        log.info("salida de audio restaurada (%s)", previa)
    except Exception as e:
        log.error("no se pudo restaurar la salida de audio: %s", e)
    try:
        os.remove(ARCHIVO_SALIDA_PREVIA)
    except OSError:
        pass


# ------------------------------------------------------------------------------------------------
# Brillo de la pantalla de la laptop (WMI): negra mientras se transmite
# ------------------------------------------------------------------------------------------------
_cerrojo_brillo = threading.Lock()


def _powershell(cmd):
    r = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True,
                       timeout=20, creationflags=subprocess.CREATE_NO_WINDOW)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[-300:])
    return r.stdout.strip()


def _leer_brillo():
    return int(_powershell("(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness | "
                           "Select-Object -First 1).CurrentBrightness"))


def _poner_brillo(valor):
    _powershell("Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods | "
                f"Invoke-CimMethod -MethodName WmiSetBrightness -Arguments @{{Timeout=0; Brightness={int(valor)}}} | "
                "Out-Null")


def _oscurecer():
    with _cerrojo_brillo:
        if os.path.exists(ARCHIVO_BRILLO_PREVIO):
            return      # ya esta oscura (reinicio de la captura): no pisar el brillo guardado con el 0
        try:
            previo = _leer_brillo()
            with open(ARCHIVO_BRILLO_PREVIO, "w") as f:
                f.write(str(previo))    # por si el servidor se cae: al volver a arrancar se restaura
            _poner_brillo(0)
            log.info("pantalla de la laptop a negro (brillo estaba en %s)", previo)
        except Exception as e:
            log.error("no se pudo bajar el brillo: %s", e)


def _restaurar_brillo():
    with _cerrojo_brillo:
        try:
            with open(ARCHIVO_BRILLO_PREVIO) as f:
                previo = int(f.read().strip())
        except (OSError, ValueError):
            return
        try:
            _poner_brillo(previo)
            log.info("brillo de la laptop restaurado (%s)", previo)
        except Exception as e:
            log.error("no se pudo restaurar el brillo: %s", e)
            return      # se deja el archivo para reintentar la proxima vez
        try:
            os.remove(ARCHIVO_BRILLO_PREVIO)
        except OSError:
            pass


def oscurecer_pantalla():
    """En otro hilo: powershell tarda ~1 s y no debe retrasar el arranque del video."""
    if APAGAR_PANTALLA:
        threading.Thread(target=_oscurecer, daemon=True).start()


def restaurar_brillo():
    threading.Thread(target=_restaurar_brillo, daemon=True).start()


# ------------------------------------------------------------------------------------------------
# Transmision: ffmpeg (pantalla + NVENC) y el audio del sistema por stdin
# ------------------------------------------------------------------------------------------------
class Transmision:
    def __init__(self):
        self.proc = None
        self.destino = None
        self.hilo_audio = None
        self.cerrojo = threading.Lock()
        self.inicio = 0.0
        self.salida_previa = None
        self.directo_falla = False   # el camino directo a NVENC fallo una vez: ya no se intenta
        self.directo = False

    def corriendo(self):
        return self.proc is not None and self.proc.poll() is None

    def murio(self):
        """ffmpeg se cerro solo (no lo detuvimos nosotros)."""
        return self.proc is not None and self.proc.poll() is not None

    def iniciar(self, ip):
        with self.cerrojo:
            # (antes de _detener, que borra el proceso) si el camino directo a NVENC murio en sus primeros
            # segundos, no volver a intentarlo
            if self.directo and self.murio() and time.monotonic() - self.inicio < 5:
                log.warning("el camino directo a NVENC fallo: se usa hwdownload desde ahora")
                self.directo_falla = True
            self._detener(restaurar_audio=False)   # reinicio: la salida virtual se queda puesta
            ffmpeg = buscar_ffmpeg()
            if not ffmpeg:
                raise RuntimeError("no encuentro ffmpeg")
            if self.salida_previa is None:
                self.salida_previa = silenciar_laptop()
            oscurecer_pantalla()
            tasa, canales, abrir_audio = _abrir_loopback()
            # Pantalla en la NVIDIA (con un juego abierto, ver bucle_vigia): ddagrab y NVENC estan en la
            # misma GPU y NVENC toma los cuadros de D3D11 directo -> 60 fps. En la Intel (escritorio) hay
            # que bajarlos a memoria (hwdownload) y eso lo deja en ~40 fps.
            self.directo = "NVIDIA" in gpu_de_la_pantalla().upper() and not self.directo_falla
            captura = f"ddagrab=output_idx=0:framerate={FPS}:dup_frames={int(DUP_FRAMES)}:draw_mouse=1"
            if not self.directo:
                captura += ",hwdownload,format=bgra"
            cmd = [
                ffmpeg, "-hide_banner", "-loglevel", "warning",
                # progreso cada 1 s (cuadros, bytes, tiempo) para la ventana y para ubicar caidas de fps
                "-stats_period", "1", "-progress", os.path.join(CARPETA, "ffmpeg_progreso.log"),
                # video: Desktop Duplication. En esta laptop (Optimus) la pantalla la maneja la GPU Intel,
                # asi que los frames de ddagrab viven en la Intel y NVENC no los puede tomar directo
                # ("OpenEncodeSessionEx failed: no encode device"): se bajan a memoria (hwdownload) y
                # NVENC los sube a la RTX. Cuesta unos ms por cuadro; los juegos siguen en la NVIDIA.
                "-f", "lavfi", "-i", captura,
            ]
            if abrir_audio:
                # SIN -use_wallclock_as_timestamps: con esa opcion ffmpeg deja de leer el audio del pipe a
                # los ~48 bloques y el .ts sale SIN un solo paquete de audio (medido 2026-10-05 con
                # prueba_pipe.py: 0 paquetes con wallclock, 801 sin el; video 60 fps en los dos casos).
                cmd += ["-f", "s16le", "-ar", str(tasa), "-ac", str(canales), "-thread_queue_size", "64",
                        "-i", "pipe:0"]
            cmd += [
                "-map", "0:v",
                "-c:v", "h264_nvenc", "-preset", "p1", "-tune", "ull", "-zerolatency", "1",
                "-rc", "cbr", "-b:v", BITRATE, "-maxrate", BITRATE, "-bufsize", "500k",
                "-bf", "0", "-rc-lookahead", "0", "-delay", "0",
                # cada cuadro sale apenas el juego lo dibuja (sin rellenar a un ritmo fijo)
                "-fps_mode", "passthrough",
            ]
            if INTRA_REFRESH:
                # En vez de un cuadro clave entero cada 30 cuadros (con un buffer tan chico cada uno sale
                # con otra calidad/color y se ve un "parpadeo" 2 veces por segundo, reportado 2026-10-05),
                # NVENC refresca la imagen por franjas a lo largo de 60 cuadros: sin pulso y se sigue
                # recuperando de paquetes perdidos.
                # OJO: con intra-refresh solo el PRIMER cuadro es clave y trae la configuracion del video
                # (SPS/PPS): un cliente que empieza a escuchar un instante tarde no decodifica NADA (medido:
                # 0 cuadros; la tableta se quedaba en "esperando la primera imagen" con audio). Por eso la
                # configuracion se repite en cada cuadro (global_header + dump_extra, unos bytes por cuadro).
                cmd += ["-g", "60", "-intra-refresh", "1", "-flags", "+global_header",
                        "-bsf:v", "dump_extra=freq=all"]
            else:
                cmd += ["-g", "30"]
            if abrir_audio:
                cmd += ["-map", "1:a", "-af", "aresample=async=1000",
                        "-c:a", "libopus", "-application", "lowdelay", "-frame_duration", "5",
                        "-b:a", "96k", "-ar", "48000", "-ac", "2"]
            cmd += [
                "-f", "mpegts", "-muxdelay", "0", "-muxpreload", "0", "-flush_packets", "1",
                "-max_interleave_delta", MAX_INTERLEAVE_US, "-pes_payload_size", "0",
                # A la PC misma: bucle_relevo lo reenvia a la tableta. Directo a la tableta, cuando la red se
                # atoraba ffmpeg se CERRABA con "Error number -10055" (WSAENOBUFS) aun con buffer de 4 MB.
                f"udp://127.0.0.1:{PUERTO_RELEVO}?pkt_size=1316&buffer_size=4194304",
            ]
            log.info("ffmpeg -> %s:%s (%s fps, %s, audio=%s, %s): %s", ip, PUERTO_VIDEO, FPS, BITRATE,
                     bool(abrir_audio), "directo NVIDIA" if self.directo else "hwdownload", " ".join(cmd))
            err = open(os.path.join(CARPETA, "ffmpeg.log"), "ab")
            self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE if abrir_audio else subprocess.DEVNULL,
                                         stdout=subprocess.DEVNULL, stderr=err,
                                         creationflags=subprocess.CREATE_NO_WINDOW)
            self.destino = ip
            self.inicio = time.monotonic()
            if abrir_audio:
                self.hilo_audio = threading.Thread(target=abrir_audio, args=(self.proc,), daemon=True)
                self.hilo_audio.start()

    def detener(self):
        with self.cerrojo:
            self._detener()

    def _detener(self, restaurar_audio=True):
        if self.proc is not None:
            log.info("deteniendo ffmpeg")
            # PRIMERO matar ffmpeg y DESPUES cerrar su stdin: cerrar el pipe mientras el hilo de audio
            # esta escribiendo en el se trababa en Windows (stop_server no contestaba y ffmpeg seguia).
            try:
                self.proc.terminate()
                self.proc.wait(3)
            except Exception:
                self.proc.kill()
            try:
                if self.proc.stdin:
                    self.proc.stdin.close()
            except Exception:
                pass
        self.proc = None
        if restaurar_audio and self.salida_previa is not None:
            restaurar_salida(self.salida_previa)
            self.salida_previa = None
        if restaurar_audio:     # (False = reinicio de la captura: la pantalla se queda negra)
            restaurar_brillo()


def _abrir_loopback():
    """(tasa, canales, funcion_que_copia_el_audio_a_ffmpeg). Siempre hay audio para ffmpeg: si no se
    puede capturar el del sistema, se le manda silencio (sin eso ffmpeg espera el audio y tampoco saca
    video: paso en las primeras pruebas)."""
    tasa, canales, indice, nombre = 48000, 2, None, None
    try:
        import pyaudiowpatch as pyaudio
        pa = pyaudio.PyAudio()
        try:
            disp = pa.get_default_wasapi_loopback()
            tasa, canales = int(disp["defaultSampleRate"]), min(2, int(disp["maxInputChannels"]))
            indice, nombre = disp["index"], disp["name"]
        finally:
            pa.terminate()
    except Exception as e:
        pyaudio = None
        log.warning("sin loopback de audio (%s): va silencio", e)
    log.info("audio: %s a %s Hz, %s canales", nombre or "silencio", tasa, canales)

    def copiar(proc):
        log.info("hilo de audio arrancando")
        # El loopback de WASAPI NO entrega nada mientras la PC esta en silencio, asi que el audio llega
        # por callback a un buffer y aqui se le da a ffmpeg a ritmo de reloj, cada 5 ms: lo que haya
        # llegado, o silencio si no llego nada. PyAudio se crea EN ESTE HILO: creado en otro, WASAPI
        # fallaba al abrir ("[Errno -9999] Unanticipated host error").
        import collections
        bloque = tasa // 200                      # 5 ms, como el frame de Opus
        bytes_bloque = bloque * canales * 2
        pendiente = collections.deque()
        silencio = bytes(bytes_bloque)
        pa = flujo = None

        def llega(datos, _n, _info, _estado):
            pendiente.append(datos)
            if len(pendiente) > 40:               # muy atrasado: tirar lo viejo, no acumular delay
                pendiente.popleft()
            return (None, pyaudio.paContinue)

        if pyaudio is not None and indice is not None:
            try:
                pa = pyaudio.PyAudio()
                flujo = pa.open(format=pyaudio.paInt16, channels=canales, rate=tasa, input=True,
                                input_device_index=indice, stream_callback=llega)
            except Exception as e:
                log.error("no se pudo abrir el loopback (%s): va silencio", e)
                flujo = None
        buf = bytearray()
        t0 = time.perf_counter()
        enviados = 0
        try:
            while proc.poll() is None:
                debidos = int((time.perf_counter() - t0) * 200)   # bloques que ya deberian haber salido
                while enviados < debidos:
                    while len(buf) < bytes_bloque and pendiente:
                        buf += pendiente.popleft()
                    if len(buf) >= bytes_bloque:
                        trozo, buf = bytes(buf[:bytes_bloque]), buf[bytes_bloque:]
                    else:
                        trozo = silencio
                    proc.stdin.write(trozo)
                    enviados += 1
                proc.stdin.flush()
                time.sleep(0.002)
        except Exception as e:
            if proc.poll() is None:   # si ffmpeg sigue vivo no es un cierre normal: que quede en el log
                log.exception("el hilo de audio se cayo: %s", e)
        finally:
            if flujo is not None:
                flujo.close()
            if pa is not None:
                pa.terminate()

    return tasa, canales, copiar


# ------------------------------------------------------------------------------------------------
# Mando: JSON de la tableta -> control de Xbox 360 virtual
# ------------------------------------------------------------------------------------------------
class Mando:
    BOTONES = {
        "A": "XUSB_GAMEPAD_A", "B": "XUSB_GAMEPAD_B", "X": "XUSB_GAMEPAD_X", "Y": "XUSB_GAMEPAD_Y",
        "L1": "XUSB_GAMEPAD_LEFT_SHOULDER", "R1": "XUSB_GAMEPAD_RIGHT_SHOULDER",
        "SELECT": "XUSB_GAMEPAD_BACK", "START": "XUSB_GAMEPAD_START", "STEAM": "XUSB_GAMEPAD_GUIDE",
        "L3_CLICK": "XUSB_GAMEPAD_LEFT_THUMB", "R3_CLICK": "XUSB_GAMEPAD_RIGHT_THUMB",
    }

    def __init__(self):
        self.pad = None
        self.ultimo = 0.0
        self.paquetes = 0
        self._intento = 0.0

    def _crear(self):
        """Un solo control para toda la vida del servidor. Si ViGEmBus no lo acepta (XInput solo tiene 4
        lugares: con otros controles conectados -o duplicados por Steam Input- no hay lugar), se
        reintenta cada 5 s en vez de en cada paquete (antes fallaba 120 veces por segundo)."""
        if time.monotonic() - self._intento < 5:
            return False
        self._intento = time.monotonic()
        try:
            import vgamepad as vg
            self.vg = vg
            self.pad = _pad_paciente(vg)
            log.info("control de Xbox 360 virtual creado")
            return True
        except Exception as e:
            log.error("no se pudo crear el control virtual (%s); se reintenta en 5 s. "
                      "¿Hay 4 controles de Xbox conectados? (XInput solo admite 4)", e)
            return False

    def aplicar(self, d):
        if self.pad is None and not self._crear():
            return
        vg = self.vg
        b = d.get("buttons", {})
        ejes = d.get("axes", {})
        dpad = d.get("dpad", {})
        p = self.pad
        p.reset()
        for nombre, boton in self.BOTONES.items():
            if b.get(nombre):
                p.press_button(button=getattr(vg.XUSB_BUTTON, boton))
        x, y = dpad.get("x", 0), dpad.get("y", 0)
        if x > 0:
            p.press_button(button=vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_RIGHT)
        elif x < 0:
            p.press_button(button=vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_LEFT)
        if y > 0:
            p.press_button(button=vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_UP)
        elif y < 0:
            p.press_button(button=vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_DOWN)

        def lim(v):
            return max(-1.0, min(1.0, float(v)))

        # La tableta manda el eje Y de Android (abajo = +1); XInput es arriba = +1.
        p.left_joystick_float(x_value_float=lim(ejes.get("LSTICK_X", 0)), y_value_float=-lim(ejes.get("LSTICK_Y", 0)))
        p.right_joystick_float(x_value_float=lim(ejes.get("RSTICK_X", 0)), y_value_float=-lim(ejes.get("RSTICK_Y", 0)))
        # Gatillos: -1 suelto .. +1 a fondo; el click digital cuenta como a fondo.
        lt = 1.0 if b.get("L2_CLICK") else (lim(ejes.get("L2_ANALOG", -1)) + 1) / 2
        rt = 1.0 if b.get("R2_CLICK") else (lim(ejes.get("R2_ANALOG", -1)) + 1) / 2
        p.left_trigger_float(value_float=lt)
        p.right_trigger_float(value_float=rt)
        p.update()

    def soltar(self):
        if self.pad is not None:
            self.pad.reset()
            self.pad.update()


def _pad_paciente(vg):
    """VX360Gamepad que ESPERA a que el driver lo conecte. El de vgamepad revisa vigem_target_is_attached
    una sola vez, al instante, e ignora el error de vigem_target_add: si ViGEmBus tardaba, fallaba con
    "could not connect" pero el control SI terminaba de conectarse y quedaba huerfano ocupando un lugar de
    XInput (solo hay 4). Con los reintentos se llenaron los 4 y ya no habia lugar (2026-10-05). Aqui se
    espera hasta 5 s y, si no conecta, se quita del driver explicitamente."""
    from ctypes import CFUNCTYPE, c_ubyte, c_void_p
    from vgamepad.win.virtual_gamepad import VBUS, vcli

    class Pad(vg.VX360Gamepad):
        def __init__(self):
            self._vivo = False
            self.vbus = VBUS
            self._busp = VBUS.get_busp()
            self._devicep = self.target_alloc()
            self.CMPFUNC = CFUNCTYPE(None, c_void_p, c_void_p, c_ubyte, c_ubyte, c_ubyte, c_void_p)
            self.cmp_func = None
            err = vcli.vigem_target_add(self._busp, self._devicep)
            limite = time.monotonic() + 5
            while not vcli.vigem_target_is_attached(self._devicep) and time.monotonic() < limite:
                time.sleep(0.1)
            if not vcli.vigem_target_is_attached(self._devicep):
                vcli.vigem_target_remove(self._busp, self._devicep)
                vcli.vigem_target_free(self._devicep)
                raise RuntimeError(f"ViGEmBus no conecto el control (vigem_target_add = 0x{err & 0xffffffff:08x})")
            self._vivo = True
            self.report = self.get_default_report()
            self.update()

        def __del__(self):
            if getattr(self, "_vivo", False):
                self._vivo = False
                super().__del__()

    return Pad()


# ------------------------------------------------------------------------------------------------
# Mouse: tocar la imagen en la tableta (TactilPc.kt) -> mouse real de Windows
# ------------------------------------------------------------------------------------------------
_MOVE, _ABS = 0x0001, 0x8000
_LDOWN, _LUP, _RDOWN, _RUP, _WHEEL = 0x0002, 0x0004, 0x0008, 0x0010, 0x0800


def _send_input(flags, x=None, y=None, datos=0):
    """SendInput de un evento de mouse. x/y en 0..1 de la pantalla principal (la que captura ddagrab con
    output_idx=0): en coordenadas absolutas de Windows eso es 0..65535 sin MOUSEEVENTF_VIRTUALDESK."""
    import ctypes
    from ctypes import wintypes

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

    class INPUT(ctypes.Structure):
        class _U(ctypes.Union):
            _fields_ = [("mi", MOUSEINPUT), ("relleno", ctypes.c_byte * 32)]
        _anonymous_ = ("u",)
        _fields_ = [("type", wintypes.DWORD), ("u", _U)]

    i = INPUT(type=0)
    if x is not None:
        i.mi.dx, i.mi.dy = round(x * 65535), round(y * 65535)
        flags |= _MOVE | _ABS
    i.mi.dwFlags = flags
    i.mi.mouseData = datos & 0xFFFFFFFF
    ctypes.windll.user32.SendInput(1, ctypes.byref(i), ctypes.sizeof(INPUT))


def aplicar_mouse(m):
    ev = m.get("ev")
    x, y = m.get("x"), m.get("y")
    pos = (float(x), float(y)) if x is not None and y is not None else (None, None)
    if ev == "mover":
        _send_input(0, *pos)
    elif ev == "clic":
        _send_input(0, *pos)
        _send_input(_LDOWN)
        _send_input(_LUP)
    elif ev == "clic_der":
        _send_input(0, *pos)
        _send_input(_RDOWN)
        _send_input(_RUP)
    elif ev == "izq_abajo":
        _send_input(_LDOWN, *pos)
    elif ev == "izq_arriba":
        _send_input(_LUP, *pos)
    elif ev == "scroll":
        _send_input(_WHEEL, datos=120 * int(m.get("d", 0)))


def bucle_mando(mando, transmision):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("0.0.0.0", PUERTO_MANDO))
    s.settimeout(0.5)
    log.info("mando: escuchando UDP %s", PUERTO_MANDO)
    suelto = True
    while True:
        try:
            datos, _ = s.recvfrom(4096)
        except socket.timeout:
            ahora = time.monotonic()
            # sin paquetes medio segundo: soltar todo (que no se quede un boton apretado)
            if not suelto and ahora - mando.ultimo > 0.5:
                mando.soltar()
                suelto = True
            # la tableta se fue (la app no avisa al salir): dejar de transmitir
            if transmision.corriendo() and ahora - max(mando.ultimo, transmision.inicio) > SIN_MANDO_S:
                log.info("sin mando %s s: se deja de transmitir", SIN_MANDO_S)
                transmision.detener()
            continue
        try:
            d = json.loads(datos)
        except ValueError:
            continue
        if "set_modo" in d:
            continue  # comando del ESP32, aqui no aplica
        if "mouse" in d:
            try:
                aplicar_mouse(d["mouse"])
            except Exception as e:
                log.error("error con el mouse: %s", e)
            continue
        try:
            mando.aplicar(d)
            mando.ultimo = time.monotonic()
            mando.paquetes += 1
            suelto = False
        except Exception as e:
            log.exception("error aplicando el mando: %s", e)
            time.sleep(1)


# ------------------------------------------------------------------------------------------------
# Puerto 9200: mismo protocolo que config_listener.ps1
# ------------------------------------------------------------------------------------------------
def bucle_config(transmision, mando):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("0.0.0.0", PUERTO_CONFIG))
    log.info("config: escuchando UDP %s", PUERTO_CONFIG)
    while True:
        datos, origen = s.recvfrom(4096)
        try:
            cmd = json.loads(datos)
        except ValueError:
            continue
        c = cmd.get("cmd")
        resp = {"ok": True}
        try:
            if c == "set_config":
                ip = cmd.get("ip") or origen[0]
                transmision.iniciar(ip)
                resp["aplicado"] = "reiniciado"
            elif c == "stop_server":
                transmision.detener()
                resp["aplicado"] = "detenido"
            elif c == "mostrar_ventana" and origen[0] == "127.0.0.1":
                # el acceso directo del escritorio (abrir_servidor.pyw), solo desde esta misma PC
                if VENTANA_COLA is not None:
                    VENTANA_COLA.put("mostrar")
            elif c != "get_config":
                resp = {"ok": False, "error": f"comando desconocido: {c}"}
        except Exception as e:
            log.exception("fallo %s", c)
            resp = {"ok": False, "error": str(e)}
        corriendo = transmision.corriendo()
        resp.update({"corriendo": corriendo, "transmitiendo": corriendo, "ip": transmision.destino or "",
                     "modo": "pc", "modos": ["pc"], "mando_paquetes": mando.paquetes})
        s.sendto(json.dumps(resp).encode(), origen)


# ------------------------------------------------------------------------------------------------
# Relevo: ffmpeg -> 127.0.0.1 -> tableta, tirando paquetes en vez de caerse
# ------------------------------------------------------------------------------------------------
def bucle_relevo(transmision):
    """Reenvia a la tableta lo que ffmpeg manda a PUERTO_RELEVO. Si Windows contesta que el buffer de envio
    esta lleno (WSAENOBUFS, la red se atoro un momento) el paquete se TIRA y se sigue: en la tableta se ve un
    detalle borroso un instante (intra-refresh lo limpia) en vez de 1-2 s sin imagen mientras ffmpeg se
    reiniciaba (medido 2026-10-05 10:20: ffmpeg se cerro con -10055 jugando)."""
    entrada = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    entrada.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8 << 20)
    entrada.bind(("127.0.0.1", PUERTO_RELEVO))
    salida = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    salida.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 8 << 20)
    log.info("relevo de video: escuchando 127.0.0.1:%s", PUERTO_RELEVO)
    tirados = 0
    ultimo_aviso = 0.0
    while True:
        datos = entrada.recv(65536)
        destino = transmision.destino
        if not destino:
            continue
        try:
            salida.sendto(datos, (destino, PUERTO_VIDEO))
        except OSError:
            tirados += 1
            ahora = time.monotonic()
            if ahora - ultimo_aviso > 5:
                log.warning("relevo: red atorada, %s paquetes tirados hasta ahora", tirados)
                ultimo_aviso = ahora


# ------------------------------------------------------------------------------------------------
# Vigia: la laptop cambia la pantalla de GPU (Intel <-> NVIDIA) al abrir/cerrar un juego
# ------------------------------------------------------------------------------------------------
def gpu_de_la_pantalla():
    """Nombre del adaptador que maneja la pantalla principal (EnumDisplayDevices, muy barato)."""
    import ctypes
    from ctypes import wintypes

    class DISPLAY_DEVICEW(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("DeviceName", wintypes.WCHAR * 32),
                    ("DeviceString", wintypes.WCHAR * 128), ("StateFlags", wintypes.DWORD),
                    ("DeviceID", wintypes.WCHAR * 128), ("DeviceKey", wintypes.WCHAR * 128)]

    i = 0
    while True:
        d = DISPLAY_DEVICEW(cb=ctypes.sizeof(DISPLAY_DEVICEW))
        if not ctypes.windll.user32.EnumDisplayDevicesW(None, i, ctypes.byref(d), 0):
            return ""
        if d.StateFlags & 0x4:   # DISPLAY_DEVICE_PRIMARY_DEVICE
            return d.DeviceString
        i += 1


def bucle_vigia(transmision):
    """Esta laptop (MSI, Advanced Optimus) pasa la pantalla a la NVIDIA al abrir un juego y de vuelta a la
    Intel al cerrarlo. ddagrab se queda enganchado a la GPU que tenia la pantalla al arrancar y la imagen
    se CONGELA (reportado 2026-10-05: "prendi el juego y se congelo"). Si la GPU cambia mientras se
    transmite, se reinicia ffmpeg (corte de 1-2 s); tambien si ffmpeg se murio solo."""
    gpu = gpu_de_la_pantalla()
    log.info("pantalla en: %s", gpu)
    while True:
        time.sleep(1)
        try:
            ahora = gpu_de_la_pantalla()
            cambio = ahora and ahora != gpu
            if cambio:
                log.info("la pantalla cambio de GPU: %s -> %s", gpu, ahora)
                gpu = ahora
            destino = transmision.destino
            if destino and (cambio and transmision.corriendo() or transmision.murio()):
                log.info("reiniciando la captura hacia %s", destino)
                time.sleep(0.5)   # dejar que Windows termine de mover la pantalla
                transmision.iniciar(destino)
        except Exception as e:
            log.error("vigia: %s", e)


TRANSMISION = None
MANDO = None
VENTANA_COLA = None   # la pone pc_gui: ordenes para la ventana desde otros hilos ("mostrar")


def matar_ffmpeg_huerfanos():
    """Si la instancia anterior murio a la fuerza (Stop-Process, reinicio de la tarea) su ffmpeg SIGUE VIVO
    mandando video a la tableta. Con el nuevo encima, la tableta recibe dos transmisiones revueltas en el mismo
    puerto (paso el 2026-10-05: tirones y fps raros por ~10 min). Se reconocen por el archivo de progreso."""
    marca = os.path.join(CARPETA, "ffmpeg_progreso.log").replace("'", "''")
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='ffmpeg.exe'\" | "
          f"Where-Object {{ $_.CommandLine -like '*{marca}*' }} | "
          "ForEach-Object { Stop-Process -Id $_.ProcessId -Force; $_.ProcessId }")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True,
                           timeout=20, creationflags=subprocess.CREATE_NO_WINDOW)
        pids = r.stdout.split()
        if pids:
            log.warning("ffmpeg huerfanos de una instancia anterior detenidos: %s", ", ".join(pids))
    except Exception:
        log.exception("no se pudieron revisar ffmpeg huerfanos")


def main():
    global TRANSMISION, MANDO
    log.info("=== servidor de PC iniciando ===")
    matar_ffmpeg_huerfanos()
    restaurar_salida()   # si la vez anterior se cayo transmitiendo, la laptop se quedo sin sonido
    restaurar_brillo()   # ... y con la pantalla negra
    TRANSMISION = transmision = Transmision()
    MANDO = mando = Mando()
    threading.Thread(target=bucle_mando, args=(mando, transmision), daemon=True).start()
    threading.Thread(target=bucle_vigia, args=(transmision,), daemon=True).start()
    threading.Thread(target=bucle_relevo, args=(transmision,), daemon=True).start()
    threading.Thread(target=bucle_config, args=(transmision, mando), daemon=True).start()
    # La ventana (pc_gui.py) va en el hilo principal (tkinter lo exige). Sin ella (PS3RP_PC_SIN_VENTANA=1 o si
    # falla), el servidor sigue igual de invisible que antes.
    if os.environ.get("PS3RP_PC_SIN_VENTANA") != "1":
        try:
            import sys
            import pc_gui
            pc_gui.correr(sys.modules[__name__])
            return
        except Exception:
            log.exception("no se pudo abrir la ventana; sigue sin ella")
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
