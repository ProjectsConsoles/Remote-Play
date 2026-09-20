#!/usr/bin/env python3
"""Menu de arranque del cliente de PS3 Remote Play.

Pregunta que se quiere hacer y lo imprime por stdout, que es lo que lee
start_client_stream.sh:

    streaming -> video + audio + control (lo de siempre)
    control   -> SOLO el control, con la pantalla de la Deck apagada

Ademas hay dos pantallas de configuracion (2026-09-11) que NO salen del
menu: se abren, y al cerrarse vuelven a mostrar este mismo menu.
    - "Configurar servidor": modo de captura del PC Windows, en remoto
      (client_server_config.py, habla con config_listener.ps1 por UDP).
    - "Configurar cliente": las variables de latencia de este mismo lado
      (client_settings.py, escribe client_config.env).

Estilo (2026-09-20): mosaicos con icono, igual que el cliente Android. Las piezas
visuales viven en ui_mosaicos.py (compartidas con las otras pantallas y, despues,
con la Ally); aqui solo se arma el menu y se lee el mando. Arriba hay una tira con
el estado del servidor, consultado en un hilo aparte para que el menu abra al
instante.

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


def mostrar_menu():
    """Una vuelta del menu. Devuelve la eleccion (string) o None si cancelo."""
    import tkinter as tk

    eleccion = {"modo": None}
    cerrado = {"v": False}
    root = tk.Tk()
    root.title("Remote Play")
    root.configure(bg=ui.FONDO)
    esc = ui.Escala(ui.configurar_ventana(root))
    iconos = ui.Iconos()

    def cerrar_ventana():
        cerrado["v"] = True
        root.destroy()

    def elegir(modo):
        eleccion["modo"] = modo
        cerrar_ventana()

    marco = tk.Frame(root, bg=ui.FONDO, padx=esc.px(24), pady=esc.px(16))
    marco.pack(fill="both", expand=True)

    ip_local = obtener_ip_local()
    cab, lbl_red = ui.cabecera(marco, esc, "Remote Play", f"IP: {ip_local}" if ip_local else "")
    cab.pack(fill="x")

    tira = ui.TiraEstado(marco, esc)
    tira.pack(fill="x", pady=esc.px(6))
    tira.pintar(ui.TENUE, "Servidor: consultando...")

    # 2x2 (las de jugar arriba, configuracion abajo) y una fila de abajo con Info y Salir.
    f1 = ui.fila(marco, esc)
    t_stream = ui.Mosaico(f1, esc, iconos, "play", "Streaming",
                          "Video y audio de la consola, mas el control.", ui.AZUL,
                          on_a=lambda: elegir("streaming"), tam_titulo=32, tam_detalle=16)
    t_control = ui.Mosaico(f1, esc, iconos, "gamepad", "Solo control",
                           "La Deck es nada mas el mando, con la pantalla apagada.", ui.VERDE,
                           on_a=lambda: elegir("control"), tam_titulo=32, tam_detalle=16)
    ui.disponer(f1, [t_stream, t_control], esc)

    f2 = ui.fila(marco, esc)
    t_servidor = ui.Mosaico(f2, esc, iconos, "server", "Configurar servidor",
                            "Modo de captura y estado de la PC Windows, en remoto.", ui.MORADO,
                            on_a=lambda: elegir("config_servidor"), tam_titulo=32, tam_detalle=16)
    t_cliente = ui.Mosaico(f2, esc, iconos, "settings", "Configurar cliente",
                           "Variables de latencia de esta Deck (VSYNC, watchdog, etc.).", ui.NARANJA,
                           on_a=lambda: elegir("config_cliente"), tam_titulo=32, tam_detalle=16)
    ui.disponer(f2, [t_servidor, t_cliente], esc)

    info = {"v": None}

    def mostrar_info():
        if info["v"] is None or not info["v"].abierta:
            info["v"] = ui.VentanaInfo(root, esc, iconos)

    f3 = ui.fila(marco, esc, expandir=False)
    t_info = ui.Mosaico(f3, esc, iconos, "info", "Info: colores del ESP32-S3", "Y", ui.GRIS,
                        on_a=mostrar_info, tam_titulo=20, tam_detalle=13, tam_icono=40,
                        horizontal=True, alto=esc.px(84))
    t_salir = ui.Mosaico(f3, esc, iconos, "exit", "Salir", "B o Escape", ui.ROJO_OSCURO,
                         on_a=cerrar_ventana, tam_titulo=20, tam_detalle=13, tam_icono=40,
                         horizontal=True, alto=esc.px(84))
    ui.disponer(f3, [t_info, t_salir], esc)

    nav = ui.Navegador([[t_stream, t_control], [t_servidor, t_cliente], [t_info, t_salir]])

    mando = Mando()
    tk.Label(marco, font=esc.fuente(13), bg=ui.FONDO, fg=ui.TENUE,
             text=("Cruceta/stick para moverte, confirma con A, cancela con B, info con Y."
                   if mando.ok else "Toca la pantalla para elegir.")
                  + "   (el tactil siempre funciona)").pack(pady=(esc.px(4), 0))

    root.bind("<Left>", lambda e: nav.mover(-1, 0))
    root.bind("<Right>", lambda e: nav.mover(1, 0))
    root.bind("<Up>", lambda e: nav.mover(0, -1))
    root.bind("<Down>", lambda e: nav.mover(0, 1))
    root.bind("<Tab>", lambda e: nav.mover(1, 0))
    root.bind("<Return>", lambda e: nav.activar())
    root.bind("<space>", lambda e: nav.activar())
    root.bind("<y>", lambda e: mostrar_info())
    root.bind("<Y>", lambda e: mostrar_info())
    root.bind("<Escape>", lambda e: cerrar_ventana())

    # --- estado del servidor, en un hilo aparte (la consulta UDP tarda hasta 3 s si no responde) ---
    fondo = {"listo": False, "wifi": None, "ip": None, "resp": None}

    def consultar_en_fondo():
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

    threading.Thread(target=consultar_en_fondo, daemon=True).start()

    def revisar_fondo():
        if cerrado["v"]:
            return
        if not fondo["listo"]:
            root.after(150, revisar_fondo)
            return
        partes = []
        if ip_local:
            partes.append(f"IP: {ip_local}")
        if fondo["wifi"]:
            partes.append(f"Red: {fondo['wifi']}")
        lbl_red.configure(text="   ·   ".join(partes))
        color, texto = _texto_estado_servidor(fondo["ip"], fondo["resp"], ip_local)
        tira.pintar(color, texto)

    root.after(150, revisar_fondo)

    def revisar_mando():
        for nombre in mando.nuevos():
            # Mientras la ventana de info esta abierta, el mando solo la cierra (B o A) - todo lo
            # demas (mover el foco) es del menu de atras y no deberia colar mientras se lee.
            if info["v"] is not None and info["v"].abierta:
                info["v"].tecla(nombre)
                continue
            if nombre == "DPAD_LEFT":
                nav.mover(-1, 0)
            elif nombre == "DPAD_RIGHT":
                nav.mover(1, 0)
            elif nombre == "DPAD_UP":
                nav.mover(0, -1)
            elif nombre == "DPAD_DOWN":
                nav.mover(0, 1)
            elif nombre == "A":
                nav.activar()
            elif nombre == "Y":
                mostrar_info()
            elif nombre == "B":
                cerrar_ventana()
            # OJO (2026-09-13): si activar() destruyo la ventana (elegir una tarjeta real) hay que
            # dejar de re-programar el bucle; si solo abrio la info, el bucle DEBE seguir vivo o el
            # mando se queda mudo ("no funciona la navegacion, solo el touch").
            if cerrado["v"]:
                return
        # 40 ms: bastante fino para que no se sienta pegajoso y lo bastante
        # espaciado para no gastar CPU en un menu.
        root.after(40, revisar_mando)

    root.after(40, revisar_mando)
    root.mainloop()

    return eleccion["modo"]


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
    # Bucle (2026-09-11): "Configurar servidor"/"Configurar cliente" abren su
    # propia pantalla y, al cerrarse, vuelven aca en vez de salir - por eso
    # esto ya no es un tiro unico como streaming/control (que SI terminan el
    # programa, imprimiendo la eleccion para que la lea start_client_stream.sh).
    while True:
        modo = mostrar_menu()

        if modo is None:
            return 1

        if modo == "config_servidor":
            import client_server_config
            try:
                client_server_config.main()
            except Exception as e:
                print(f"pantalla de config del servidor fallo: {e}", file=sys.stderr)
            continue

        if modo == "config_cliente":
            import client_settings
            try:
                client_settings.main()
            except Exception as e:
                print(f"pantalla de config del cliente fallo: {e}", file=sys.stderr)
            continue

        if modo == "streaming":
            ok, mensaje = verificar_servidor_listo()
            if not ok:
                try:
                    from tkinter import messagebox
                    messagebox.showwarning("Remote Play", mensaje)
                except Exception as e:
                    print(f"aviso de servidor no listo: {mensaje} ({e})", file=sys.stderr)
                continue

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
