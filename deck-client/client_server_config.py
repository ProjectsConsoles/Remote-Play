#!/usr/bin/env python3
"""Pantalla "Configurar servidor" del menu de la Deck (2026-09-11).

Deja elegir el modo de captura del servidor Windows (y confirma la IP de
esta Deck) SIN tener que ir a tocar la PC - manda el cambio por red al
config_listener.ps1 que corre alli (ver ese script para el protocolo).

Si el servidor ya esta transmitiendo, el cambio lo REINICIA con la config
nueva (unos segundos de corte). Si esta apagado, solo queda guardado para
la proxima vez que le den Iniciar en la PC - eso lo decide el listener, no
esta pantalla.

Estilo (2026-09-20): mosaicos con icono, igual que el cliente Android, y es una
pantalla de la ventana unica de ui_mosaicos.App (se desliza al abrir y al volver). El
comportamiento no cambio: mismos mensajes, mismo protocolo, mismos atajos (Y manda la
IP, X reinicia, L1 apaga, B vuelve).

Como se maneja: la fila de modos sigue al foco (el modo marcado con el visto es el que
se aplica), A sobre un modo lo APLICA (como antes), tocar un modo solo lo elige. La IP
del servidor se edita con A / tocando su mosaico (cuadro de texto, con teclado).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server_udp  # noqa: E402
import ui_mosaicos as ui  # noqa: E402

# Mismo texto que $Modos en server_engine_lib.ps1 (Windows) - duplicado a
# proposito: son 4 lineas fijas, y mantenerlas identicas en las dos
# pantallas (Deck y Windows) es mas simple que inventar un protocolo para
# sincronizar descripciones que casi nunca cambian.
MODOS = [
    ("mjpeg720", "1280x720 - MJPEG (recomendado)",
     "El modo de siempre y el unico probado a fondo: 60 fps estables, ~6 Mbps de wifi."),
    ("mjpeg1080", "1920x1080 - MJPEG (mas nitido)",
     "Imagen mas definida, pero sube a 8 Mbps. Sin probar a fondo."),
    ("crudo480", "720x480 - SIN COMPRIMIR (prueba)",
     "Prueba de latencia: salta el MJPEG. Manda 5x mas datos por USB."),
    ("crudo640", "640x480 - SIN COMPRIMIR (prueba)",
     "Igual que el anterior pero pide menos por el USB."),
    ("crudo720", "1280x720 - SIN COMPRIMIR (Hagibis)",
     "Salta el MJPEG a 720p - solo si tu capturadora lo sostiene a 60fps (la 'Hagibis' si)."),
]

IP_SERVIDOR_DEFAULT = "192.168.0.90"


class PantallaServidor(ui.Pantalla):
    def __init__(self, app):
        super().__init__(app)
        import tkinter as tk
        root = app.root
        esc, iconos = app.esc, app.iconos

        ip_deck = server_udp.obtener_ip_local() or "?"
        estado = {"ip": server_udp.leer_ip_servidor_guardada() or IP_SERVIDOR_DEFAULT,
                  "sel": 0, "consultado": False}

        marco = tk.Frame(self.frame, bg=ui.FONDO, padx=esc.px(24), pady=esc.px(16))
        marco.pack(fill="both", expand=True)
        cab, _ = ui.cabecera(marco, esc, "Configurar servidor", f"Esta Deck: {ip_deck}")
        cab.pack(fill="x")
        tira = ui.TiraEstado(marco, esc)
        tira.pack(fill="x", pady=esc.px(6))
        tira.pintar(ui.TENUE, "Sin consultar todavia.")

        def msg(color, texto):
            tira.pintar(color, texto)
            root.update_idletasks()

        # --- IP del servidor (editable) + IP de esta Deck (informativa) ---
        f_ip = ui.fila(marco, esc, expandir=False)
        t_ip = ui.Mosaico(f_ip, esc, iconos, "server", estado["ip"],
                          "IP del servidor Windows  (A o tocar para cambiarla)", ui.MORADO,
                          tam_titulo=26, tam_detalle=14, tam_icono=40, horizontal=True,
                          alto=esc.px(96))
        t_deck = ui.Mosaico(f_ip, esc, iconos, "wifi", ip_deck,
                            "IP de esta Deck (a donde llega el video)", ui.GRIS,
                            tam_titulo=26, tam_detalle=14, tam_icono=40, horizontal=True,
                            alto=esc.px(96), interactivo=False)
        ui.disponer(f_ip, [t_ip, t_deck], esc)

        def editar_ip():
            def aceptar(valor):
                estado["ip"] = valor
                t_ip.poner_titulo(valor or "(sin IP)")
            ui.DialogoTexto(app, "IP del servidor Windows", estado["ip"], aceptar)

        t_ip.on_a = editar_ip

        # --- modos de captura ---
        f_modos = ui.fila(marco, esc)
        t_modos = []
        for clave, nombre, detalle in MODOS:
            t = ui.Mosaico(f_modos, esc, iconos, "image", nombre, detalle, ui.MORADO,
                           tam_titulo=18, tam_detalle=13, tam_icono=40,
                           on_a=lambda: aplicar(), on_click=lambda: None)
            t_modos.append(t)
        ui.disponer(f_modos, t_modos, esc)

        def refrescar_marcas():
            for i, t in enumerate(t_modos):
                t.poner_marca(i == estado["sel"])

        # --- acciones ---
        f_acc = ui.fila(marco, esc, expandir=False)
        t_consultar = ui.Mosaico(f_acc, esc, iconos, "refresh", "Consultar", "Estado del servidor",
                                 ui.AZUL, tam_titulo=20, tam_detalle=13, tam_icono=40,
                                 alto=esc.px(140), on_a=lambda: consultar())
        t_enviar = ui.Mosaico(f_acc, esc, iconos, "wifi", "Enviar IP (Y)", "Manda la IP de esta Deck",
                              ui.AZUL, tam_titulo=20, tam_detalle=13, tam_icono=40,
                              alto=esc.px(140), on_a=lambda: enviar_ip())
        t_aplicar = ui.Mosaico(f_acc, esc, iconos, "check", "Aplicar", "Pone el modo marcado",
                               ui.VERDE, tam_titulo=20, tam_detalle=13, tam_icono=40,
                               alto=esc.px(140), on_a=lambda: aplicar())
        t_reiniciar = ui.Mosaico(f_acc, esc, iconos, "refresh", "Reiniciar (X)", "Reinicia el servidor",
                                 "#a04a2d", tam_titulo=20, tam_detalle=13, tam_icono=40,
                                 alto=esc.px(140), on_a=lambda: reiniciar_servidor())
        t_apagar = ui.Mosaico(f_acc, esc, iconos, "power", "Apagar (L1)", "Detiene la transmision",
                              ui.ROJO, tam_titulo=20, tam_detalle=13, tam_icono=40,
                              alto=esc.px(140), on_a=lambda: apagar_servidor())
        ui.disponer(f_acc, [t_consultar, t_enviar, t_aplicar, t_reiniciar, t_apagar], esc)

        f_pie = ui.fila(marco, esc, expandir=False)
        t_volver = ui.Mosaico(f_pie, esc, iconos, "back", "Volver", "B o Escape", ui.GRIS,
                              tam_titulo=20, tam_detalle=13, tam_icono=40, horizontal=True,
                              alto=esc.px(84), on_a=app.volver)
        ui.disponer(f_pie, [t_volver], esc)

        def al_cambiar(t):
            # el foco sobre un modo LO ELIGE (asi el marcado siempre es el que Aplicar va a usar)
            if t in t_modos:
                estado["sel"] = t_modos.index(t)
                refrescar_marcas()

        nav = ui.Navegador([[t_ip], t_modos, [t_consultar, t_enviar, t_aplicar, t_reiniciar, t_apagar],
                            [t_volver]], al_cambiar=al_cambiar, recordar=True)
        refrescar_marcas()

        def elegir_modo_por_clave(clave):
            for i, (c, _, _) in enumerate(MODOS):
                if c == clave:
                    estado["sel"] = i
                    nav.memoria[1] = i
            refrescar_marcas()

        # --- acciones de red (mismos mensajes y mismo flujo que antes) ---
        def consultar():
            ip = estado["ip"].strip()
            if not ip:
                msg(ui.ERROR, "Pon una IP primero.")
                return
            msg(ui.TENUE, "Consultando...")
            ok, resp = server_udp.obtener_config(ip)
            if not ok:
                msg(ui.ERROR, str(resp))
                return
            server_udp.guardar_ip_servidor(ip)
            corriendo = "SI" if resp.get("corriendo") else "no"
            modo_actual = resp.get("modo") or "(ninguno guardado)"
            texto = f"Corriendo: {corriendo}  ·  Modo actual: {modo_actual}"
            # IP sincronizada (2026-09-13): solo tiene sentido mostrarla si el
            # servidor esta corriendo - apagado, "ip" es la ultima que quedo
            # guardada de una corrida vieja, no algo que este mandando video
            # ahorita, y compararla confundiria mas de lo que ayuda.
            if resp.get("corriendo"):
                ip_servidor_tiene = resp.get("ip")
                if ip_servidor_tiene == ip_deck:
                    texto += f"\nIP sincronizada: SI (le manda el video a {ip_deck})"
                else:
                    texto += (f"\nIP sincronizada: NO (le manda el video a "
                              f"{ip_servidor_tiene or '?'}, no a esta Deck)")
            msg(ui.OK if resp.get("corriendo") else ui.TENUE, texto)
            elegir_modo_por_clave(resp.get("modo"))

        def aplicar():
            ip = estado["ip"].strip()
            if not ip:
                msg(ui.ERROR, "Pon una IP primero.")
                return
            clave = MODOS[estado["sel"]][0]
            msg(ui.TENUE, "Aplicando... si el servidor ya esta corriendo, puede tardar unos "
                          "segundos en reiniciar (no se congelo).")
            ok, resp = server_udp.aplicar_config(ip, ip_deck, clave)
            if not ok:
                msg(ui.ERROR, str(resp))
                return
            server_udp.guardar_ip_servidor(ip)
            aplicado = resp.get("aplicado")
            if aplicado == "reiniciado":
                msg(ui.OK, "Listo: servidor reiniciado con la config nueva.")
            elif aplicado == "guardado_para_proxima_vez":
                msg(ui.OK, "Guardado. El servidor no estaba corriendo; se aplicara la proxima vez que le den Iniciar.")
            else:
                msg(ui.ERROR, str(resp))

        def enviar_ip():
            # "que no sea necesario escribirla en el servidor por si cambia"
            # (pedido 2026-09-11): manda la IP de ESTA Deck al servidor sin
            # tocar el modo de captura - consulta el modo que ya tiene puesto
            # el servidor y se lo vuelve a mandar junto con la IP nueva, asi
            # Aplicar-config actualiza Guardar-Ip en la PC sin que el usuario
            # tenga que ir a escribirla a mano ahi ni elegir un modo aca.
            ip = estado["ip"].strip()
            if not ip:
                msg(ui.ERROR, "Pon una IP primero.")
                return
            msg(ui.TENUE, "Consultando modo actual del servidor...")
            ok, resp = server_udp.obtener_config(ip)
            if not ok:
                msg(ui.ERROR, str(resp))
                return
            modo_actual = resp.get("modo") or MODOS[estado["sel"]][0]
            msg(ui.TENUE, f"Enviando IP de esta Deck ({ip_deck})... si el servidor esta "
                          "corriendo, puede tardar unos segundos en reiniciar.")
            ok, resp = server_udp.aplicar_config(ip, ip_deck, modo_actual)
            if not ok:
                msg(ui.ERROR, str(resp))
                return
            server_udp.guardar_ip_servidor(ip)
            aplicado = resp.get("aplicado")
            if aplicado == "reiniciado":
                msg(ui.OK, f"IP enviada ({ip_deck}). Servidor reiniciado con el mismo modo.")
            elif aplicado == "guardado_para_proxima_vez":
                msg(ui.OK, f"IP enviada ({ip_deck}). Se aplicara la proxima vez que arranque.")
            else:
                msg(ui.ERROR, str(resp))
            elegir_modo_por_clave(modo_actual)

        def reiniciar_servidor():
            # Reusa el mismo camino que "Enviar IP" (set_config con el modo
            # actual sin cambiarlo) - config_listener.ps1 ya reinicia el motor
            # cuando esto llega con el servidor corriendo (ver
            # server_engine_lib.ps1 / Iniciar-Servidor). No hace falta un
            # comando nuevo del lado de Windows para esto.
            ip = estado["ip"].strip()
            if not ip:
                msg(ui.ERROR, "Pon una IP primero.")
                return
            msg(ui.TENUE, "Consultando servidor antes de reiniciar...")
            ok, resp = server_udp.obtener_config(ip)
            if not ok:
                msg(ui.ERROR, str(resp))
                return
            if not resp.get("corriendo"):
                msg(ui.TENUE, "El servidor no esta corriendo; no hay nada que reiniciar.")
                return
            modo_actual = resp.get("modo") or MODOS[estado["sel"]][0]
            msg(ui.TENUE, "Reiniciando servidor... puede tardar unos segundos.")
            ok, resp2 = server_udp.aplicar_config(ip, ip_deck, modo_actual)
            if not ok:
                msg(ui.ERROR, str(resp2))
                return
            server_udp.guardar_ip_servidor(ip)
            if resp2.get("aplicado") == "reiniciado":
                msg(ui.OK, "Listo: servidor reiniciado.")
            else:
                msg(ui.ERROR, str(resp2))

        def apagar_servidor():
            # A diferencia de reiniciar_servidor, esto usa el comando nuevo
            # stop_server (2026-09-17) - set_config SIEMPRE vuelve a arrancar,
            # no sirve para apagar de verdad.
            ip = estado["ip"].strip()
            if not ip:
                msg(ui.ERROR, "Pon una IP primero.")
                return
            msg(ui.TENUE, "Apagando servidor...")
            ok, resp = server_udp.detener_servidor(ip)
            if not ok:
                msg(ui.ERROR, str(resp))
                return
            if resp.get("aplicado") == "detenido":
                msg(ui.OK, "Listo: servidor apagado.")
            else:
                msg(ui.TENUE, "El servidor ya estaba apagado.")

        tk.Label(marco, font=esc.fuente(13), bg=ui.FONDO, fg=ui.TENUE,
                 text="Cruceta: mueve el foco. A ejecuta (sobre un modo, lo aplica). "
                      "Y manda la IP, X reinicia el servidor, L1 lo apaga, B vuelve."
                 ).pack(pady=(esc.px(4), 0))

        def tecla(nombre):
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
                enviar_ip()
            elif nombre == "X":
                reiniciar_servidor()
            elif nombre == "L1":
                apagar_servidor()
            elif nombre == "B":
                app.volver()

        def al_mostrar():
            # La primera vez que se ve (ya terminada la animacion, para no congelarla) consulta al servidor.
            if not estado["consultado"]:
                estado["consultado"] = True
                consultar()

        self.tecla = tecla
        self.al_mostrar = al_mostrar


def main():
    """Solo para probar esta pantalla suelta: python3 client_server_config.py"""
    from deck_gamepad import Mando
    app = ui.App("Configurar servidor", Mando())
    app.abrir_inicial(PantallaServidor(app))
    app.ejecutar()


if __name__ == "__main__":
    main()
