#!/usr/bin/env python3
"""Menu de arranque del cliente de PS3 Remote Play.

Pregunta que se quiere hacer y lo imprime por stdout, que es lo que lee
start_client_stream.sh:

    streaming -> video + audio + control (lo de siempre)
    control   -> SOLO el control, con la pantalla de la Deck apagada

Ademas hay tres pantallas que NO salen del menu: "Configurar servidor" (modo de captura
del PC Windows, en remoto: client_server_config.py, habla con config_listener.ps1 por UDP),
"Configurar cliente" (las variables de latencia de este mismo lado: client_settings.py,
escribe client_config.env) e "Info" (colores del LED del ESP32-S3).

Estilo (2026-09-20): mosaicos con icono, igual que el cliente Android, y TODO dentro de UNA
sola ventana: abrir una pantalla la desliza de derecha a izquierda y volver la desliza de
izquierda a derecha (ver ui_mosaicos.App). Arriba del menu hay una tira con el estado del
servidor, consultado en un hilo aparte para que el menu abra al instante.

Por que una sola ventana y un solo Mando (2026-09-20, bug reportado: "le doy Volver y me saca
de la app"): antes cada pantalla abria su propia ventana y creaba su propio deck_gamepad.Mando.
Un Mando nuevo arranca sin memoria de lo que ya esta apretado y lo cuenta como "recien
pulsado": al soltar B (o A sobre Volver) la pantalla anterior se cerraba y el menu nuevo leia
ese mismo boton como suyo - B cancelaba el menu y A activaba el primer mosaico (Streaming).
Con un solo Mando que vive toda la sesion, el boton se cuenta una vez.

Se usa tkinter y no zenity/kdialog a proposito: tkinter ya viene con el Python
del sistema y con el del venv, y deja hacer botones del tamano que uno quiera.

SE NAVEGA CON EL MANDO, y eso hay que hacerlo a mano (2026-09-06). En Modo
Juego, Steam Input le entrega a la aplicacion un GAMEPAD, no un raton: el
trackpad NO mueve ningun cursor, asi que una ventana normal solo se puede tocar
con la pantalla tactil. Por eso aca se lee el mando directo con pygame y se
traduce a mover el foco / confirmar. El tactil y el raton siguen funcionando.

Codigos de salida:
    0 = eligio streaming o control, esta impreso en stdout
    1 = cancelo (B, Escape, "Salir", o cerro la ventana)
    2 = no se pudo abrir ninguna ventana (sin DISPLAY, por ejemplo)

El 2 importa: el .sh lo trata como "sigue en streaming, como siempre", para que
un problema con el menu nunca deje al usuario sin nada.
"""

import os
import sys
import threading

# La lectura del mando vive en deck_gamepad.py, compartida con
# client_control_ui.py. Ese modulo tambien fija SDL_VIDEODRIVER=dummy y
# PYGAME_HIDE_SUPPORT_PROMPT al importarse, que son criticos aca: sin el
# primero SDL pelea con la ventana de tkinter, y sin el segundo pygame saluda
# por stdout, que es justo por donde este script devuelve la eleccion.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from deck_gamepad import Mando            # noqa: E402
from server_udp import (obtener_ip_local, obtener_red_wifi,  # noqa: E402
                         obtener_config, leer_ip_servidor_guardada)
import ui_mosaicos as ui                  # noqa: E402


def _texto_estado_servidor(ip_servidor, resp, ip_local):
    """(color, texto) para la tira de estado del menu. `resp` es lo que devuelve obtener_config."""
    if not ip_servidor:
        return ui.TENUE, "Servidor sin configurar: entra a \"Configurar servidor\" para poner su IP."
    ok, datos = resp if resp else (False, "sin respuesta")
    if not ok:
        return ui.ERROR, f"Servidor {ip_servidor}: sin respuesta. ¿Prendido y en la misma red?"
    modo = datos.get("modo") or "?"
    if not datos.get("corriendo"):
        return ui.AVISO, (f"Servidor {ip_servidor}: detenido (modo {modo}). "
                          "Prendelo en la PC o aplica la configuracion.")
    if datos.get("transmitiendo") is False:
        return ui.AVISO, f"Servidor {ip_servidor}: corriendo pero SIN transmitir. Revisa la capturadora."
    destino = datos.get("ip") or ""
    if ip_local and destino and destino != ip_local:
        return ui.AVISO, (f"Servidor {ip_servidor}: transmite a {destino}, no a esta Deck ({ip_local}). "
                          "Entra a \"Configurar servidor\" y manda tu IP.")
    return ui.OK, f"Servidor {ip_servidor}: transmitiendo a {destino} ({modo})"


class PantallaMenu(ui.Pantalla):
    """El menu principal: 2x2 de mosaicos (jugar arriba, configurar abajo) y Info / Salir."""

    def __init__(self, app):
        super().__init__(app)
        import tkinter as tk
        import client_server_config
        import client_settings
        esc, iconos = app.esc, app.iconos
        self.ip_local = obtener_ip_local()
        self._consulta = 0

        marco = tk.Frame(self.frame, bg=ui.FONDO, padx=esc.px(24), pady=esc.px(16))
        marco.pack(fill="both", expand=True)
        cab, self.lbl_red = ui.cabecera(marco, esc, "Remote Play",
                                        f"IP: {self.ip_local}" if self.ip_local else "")
        cab.pack(fill="x")
        self.tira = ui.TiraEstado(marco, esc)
        self.tira.pack(fill="x", pady=esc.px(6))
        self.tira.pintar(ui.TENUE, "Servidor: consultando...")

        f1 = ui.fila(marco, esc)
        t_stream = ui.Mosaico(f1, esc, iconos, "play", "Streaming",
                              "Video y audio de la consola, mas el control.", ui.AZUL,
                              on_a=self.elegir_streaming, tam_titulo=32, tam_detalle=16)
        t_control = ui.Mosaico(f1, esc, iconos, "gamepad", "Solo control",
                               "La Deck es nada mas el mando, con la pantalla apagada.", ui.VERDE,
                               on_a=lambda: app.terminar("control"), tam_titulo=32, tam_detalle=16)
        ui.disponer(f1, [t_stream, t_control], esc)

        f2 = ui.fila(marco, esc)
        t_servidor = ui.Mosaico(
            f2, esc, iconos, "server", "Configurar servidor",
            "Modo de captura y estado de la PC Windows, en remoto.", ui.MORADO,
            on_a=lambda: app.abrir(client_server_config.PantallaServidor(app)),
            tam_titulo=32, tam_detalle=16)
        t_cliente = ui.Mosaico(
            f2, esc, iconos, "settings", "Configurar cliente",
            "Variables de latencia de esta Deck (VSYNC, watchdog, etc.).", ui.NARANJA,
            on_a=lambda: app.abrir(client_settings.PantallaCliente(app)),
            tam_titulo=32, tam_detalle=16)
        ui.disponer(f2, [t_servidor, t_cliente], esc)

        f3 = ui.fila(marco, esc, expandir=False)
        t_info = ui.Mosaico(f3, esc, iconos, "info", "Info: colores del ESP32-S3", "Y", ui.GRIS,
                            on_a=self.abrir_info, tam_titulo=20, tam_detalle=13, tam_icono=40,
                            horizontal=True, alto=esc.px(84))
        t_salir = ui.Mosaico(f3, esc, iconos, "exit", "Salir", "B o Escape", ui.ROJO_OSCURO,
                             on_a=lambda: app.terminar(None), tam_titulo=20, tam_detalle=13,
                             tam_icono=40, horizontal=True, alto=esc.px(84))
        ui.disponer(f3, [t_info, t_salir], esc)

        self.nav = ui.Navegador([[t_stream, t_control], [t_servidor, t_cliente], [t_info, t_salir]])

        tk.Label(marco, font=esc.fuente(13), bg=ui.FONDO, fg=ui.TENUE,
                 text=("Cruceta/stick para moverte, confirma con A, cancela con B, info con Y."
                       if app.mando.ok else "Toca la pantalla para elegir.")
                      + "   (el tactil siempre funciona)").pack(pady=(esc.px(4), 0))

    def abrir_info(self):
        self.app.abrir(ui.PantallaInfo(self.app))

    def elegir_streaming(self):
        # Antes de streaming (2026-09-11): confirma con el servidor que esta listo. Si no, el mensaje
        # sale en la tira de arriba (ya no en una ventana emergente) y se queda en el menu.
        self.tira.pintar(ui.TENUE, "Verificando el servidor...")
        self.app.root.update_idletasks()
        ok, mensaje = verificar_servidor_listo()
        if not ok:
            self.tira.pintar(ui.AVISO, "No se puede iniciar streaming: " + mensaje.replace("\n\n", "  "))
            return
        self.app.terminar("streaming")

    def al_mostrar(self):
        self.consultar_estado()

    def consultar_estado(self):
        """Estado del servidor en un hilo aparte (la consulta UDP tarda hasta 3 s si no responde)."""
        self._consulta += 1
        mia = self._consulta
        self.tira.pintar(ui.TENUE, "Servidor: consultando...")
        fondo = {"listo": False, "wifi": None, "ip": None, "resp": None}

        def trabajo():
            try:
                fondo["wifi"] = obtener_red_wifi()
            except Exception:
                pass
            fondo["ip"] = leer_ip_servidor_guardada()
            if fondo["ip"]:
                try:
                    fondo["resp"] = obtener_config(fondo["ip"])
                except Exception as e:
                    fondo["resp"] = (False, str(e))
            fondo["listo"] = True

        threading.Thread(target=trabajo, daemon=True).start()

        def revisar():
            if self.app.cerrado or mia != self._consulta:
                return
            if not fondo["listo"]:
                self.app.root.after(150, revisar)
                return
            try:
                partes = []
                if self.ip_local:
                    partes.append(f"IP: {self.ip_local}")
                if fondo["wifi"]:
                    partes.append(f"Red: {fondo['wifi']}")
                self.lbl_red.configure(text="   ·   ".join(partes))
                color, texto = _texto_estado_servidor(fondo["ip"], fondo["resp"], self.ip_local)
                self.tira.pintar(color, texto)
            except Exception:
                pass  # la pantalla ya se cerro

        self.app.root.after(150, revisar)

    def tecla(self, nombre):
        if nombre == "DPAD_LEFT":
            self.nav.mover(-1, 0)
        elif nombre == "DPAD_RIGHT":
            self.nav.mover(1, 0)
        elif nombre == "DPAD_UP":
            self.nav.mover(0, -1)
        elif nombre == "DPAD_DOWN":
            self.nav.mover(0, 1)
        elif nombre == "A":
            self.nav.activar()
        elif nombre == "Y":
            self.abrir_info()
        elif nombre == "B":
            self.app.terminar(None)


def verificar_servidor_listo():
    """Antes de streaming (2026-09-11): confirma con el servidor (mismo
    protocolo UDP de "Configurar servidor", puerto 9200) que tiene puesta la
    IP de ESTA Deck y que esta transmitiendo - en vez de lanzar ffplay a
    esperar un video que puede no llegar nunca si el servidor le manda los
    paquetes a otra maquina. Alternativa mas segura que ponerle un timeout a
    la propia conexion UDP de ffplay (eso arriesgaria cortar una partida real
    si la wifi tiene un corte de mas de unos segundos, ver la nota en
    OPCIONES.md/discusion del 2026-09-11) - esto solo mira el ESTADO
    declarado del servidor, nunca toca el pipeline de video en si.

    Devuelve (True, "") si esta todo bien (o si nunca se configuro el
    servidor desde aca y no hay como chequear - se sigue como siempre, sin
    bloquear a nadie que no use la pantalla nueva), o (False, mensaje) si
    hay algo que el usuario deberia arreglar antes de intentar streaming."""
    ip_servidor = leer_ip_servidor_guardada()
    if not ip_servidor:
        return True, ""
    ip_local = obtener_ip_local()
    ok, resp = obtener_config(ip_servidor)
    if not ok:
        return False, f"No se pudo consultar el servidor ({ip_servidor}):\n{resp}"
    if not resp.get("corriendo"):
        return False, (f"El servidor ({ip_servidor}) no esta transmitiendo ahora mismo.\n\n"
                        "Prendelo desde la PC, o revisa \"Configurar servidor\".")
    # "transmitiendo" (2026-09-11): el servidor lo agrego para no mentir
    # cuando su ffmpeg quedo colgado (proceso vivo pero sin sacar un solo
    # cuadro, ver server_engine_lib.ps1). Solo se exige si el servidor
    # mando el campo: si es una version vieja del listener, no esta y no se
    # bloquea nada.
    if resp.get("transmitiendo") is False:
        return False, (f"El servidor ({ip_servidor}) dice estar prendido pero no esta "
                        "sacando video (se le colgo la captura).\n\n"
                        "Detenlo y vuelvelo a iniciar desde la PC.")
    if ip_local and resp.get("ip") != ip_local:
        return False, (f"El servidor esta mandando el video a {resp.get('ip')}, "
                        f"no a esta Deck ({ip_local}).\n\n"
                        "Entra a \"Configurar servidor\" y manda tu IP con el boton "
                        "de enviar IP.")
    return True, ""


def main():
    # Una sola ventana y un solo Mando para toda la sesion (ver la nota arriba). Streaming/control
    # terminan el programa imprimiendo la eleccion para que la lea start_client_stream.sh.
    app = ui.App("Remote Play", Mando())
    app.abrir_inicial(PantallaMenu(app))
    modo = app.ejecutar()
    if modo is None:
        return 1
    print(modo)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        # Sin DISPLAY, sin Xwayland, tkinter roto... da igual el motivo: el .sh
        # tiene que poder seguir adelante en vez de dejar al usuario sin nada.
        print(f"menu no disponible: {e}", file=sys.stderr)
        sys.exit(2)
