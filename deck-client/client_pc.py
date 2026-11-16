#!/usr/bin/env python3
"""Menu "PC" (2026-11-16, como Android): todo lo del servidor de PC (windows-pc-server) en una pantalla propia,
en vez de una fila dentro de "¿Qué consola?". Jugar en la PC, Reiniciar Steam (nuevo), Reiniciar servidor y la
IP de la PC.

Reiniciar Steam: a veces, tras un rato sin tocar nada, Big Picture se ve en la laptop pero al cliente solo le llega
negro con el puntero en medio; cerrar y abrir Steam lo compone. El servidor lo hace con el comando
reiniciar_steam y el avance se sigue con get_config -> "steam" (cerrando / abriendo / listo / error: ...).
"""

import time
import tkinter as tk

import client_settings
import server_udp
import ui_mosaicos as ui

ESPERA_SALIDA_MS = 900
IP_PC_DEFAULT = "192.168.0.171"   # la laptop; mismo default que PS3RP_PC_IP en client_settings y el .sh
AZUL_STEAM = "#2a6f97"
ESPERA_STEAM_S = 90


def leer_ip_pc():
    return client_settings.leer_guardado().get("PS3RP_PC_IP") or IP_PC_DEFAULT


def guardar_ip_pc(ip):
    valores = client_settings.leer_guardado()
    valores["PS3RP_PC_IP"] = ip
    client_settings.guardar(valores)


def ip_valida(texto):
    partes = texto.strip().split(".")
    return len(partes) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in partes)


class PantallaPc(ui.Pantalla):
    def __init__(self, app):
        super().__init__(app)
        self.saliendo = False
        self.ocupado = False
        self._consulta = 0
        esc, iconos = app.esc, app.iconos
        marco = tk.Frame(self.frame, bg=ui.FONDO, padx=esc.px(24), pady=esc.px(16))
        marco.pack(fill="both", expand=True)
        cab, _ = ui.cabecera(marco, esc, "PC", "Juegos de Windows en la Deck")
        cab.pack(fill="x")
        self.tira = ui.TiraEstado(marco, esc)
        self.tira.pack(fill="x", pady=(esc.px(6), esc.px(4)))

        f1 = ui.fila(marco, esc)
        jugar = ui.Mosaico(f1, esc, iconos, "play", "Jugar en la PC",
                           "Transmite la pantalla; el mando llega como control de Xbox.", ui.AZUL,
                           on_a=self.jugar, tam_titulo=30, tam_detalle=15)
        steam = ui.Mosaico(f1, esc, iconos, "refresh", "Reiniciar Steam",
                           "Si aquí se ve negro y en la PC sí.", AZUL_STEAM,
                           on_a=self.reiniciar_steam, tam_titulo=30, tam_detalle=15)
        servidor = ui.Mosaico(f1, esc, iconos, "server", "Reiniciar servidor",
                              "Si se trabó la imagen o el control.", "#8a4b14",
                              on_a=self.reiniciar_servidor, tam_titulo=30, tam_detalle=15)
        ui.disponer(f1, [jugar, steam, servidor], esc, columnas=3)

        f2 = ui.fila(marco, esc)
        self.t_ip = ui.Mosaico(f2, esc, iconos, "computer", leer_ip_pc(), "IP de la PC (se guarda sola)",
                               ui.VERDE, on_a=self.editar_ip, tam_titulo=26, tam_detalle=15)
        volver = ui.Mosaico(f2, esc, iconos, "back", "Volver", "B o Escape", ui.GRIS, on_a=app.volver,
                            tam_titulo=26, tam_detalle=15)
        ui.disponer(f2, [self.t_ip, volver], esc, columnas=2)

        self.estados = {
            jugar: (ui.TENUE, "Le pide a la PC que transmita a esta Deck. La pantalla táctil y el trackpad "
                              "(con Steam) son el mouse."),
            steam: (ui.TENUE, "Cierra Steam en la PC y lo abre en Big Picture (~30 s), sin levantarse a la laptop."),
            servidor: (ui.TENUE, "Deja el servidor de la PC como recién abierto. Luego elige Jugar otra vez."),
            self.t_ip: (ui.TENUE, "La laptop con el servidor de PC. A para cambiarla."),
            volver: (ui.TENUE, "Volver al menú."),
        }
        self.nav = ui.Navegador([[jugar, steam, servidor], [self.t_ip, volver]], al_cambiar=self._foco)

    # --- estado ---------------------------------------------------------------------------------
    def _foco(self, mosaico):
        if not self.saliendo and not self.ocupado:
            self.tira.pintar(*self.estados.get(mosaico, (ui.TENUE, "")))

    def _sigo_aqui(self):
        return not self.app.cerrado and bool(self.app.pila) and self.app.pila[-1] is self

    def al_mostrar(self):
        self.consultar_estado()

    def consultar_estado(self):
        if self.ocupado:
            return
        self._consulta += 1
        mia = self._consulta
        ip_pc = leer_ip_pc()
        self.tira.pintar(ui.TENUE, f"PC {ip_pc}: consultando...")

        def listo(r):
            if mia != self._consulta or self.ocupado or self.saliendo or not self._sigo_aqui():
                return
            ok, resp = r
            if not ok:
                self.tira.pintar(ui.AVISO, f"PC {ip_pc}: sin respuesta. ¿Prendida y con el servidor de PC corriendo?")
            elif resp.get("corriendo"):
                self.tira.pintar(ui.OK, f"PC {ip_pc}: lista, transmitiendo a {resp.get('ip') or '?'}.")
            else:
                self.tira.pintar(ui.OK, f"PC {ip_pc}: lista.")

        self.app.en_fondo(lambda: server_udp.obtener_config(ip_pc), listo)

    # --- acciones -------------------------------------------------------------------------------
    def jugar(self):
        """Le pide a la PC (UDP 9200) que transmita a esta Deck y sale con "pc": start_client_stream.sh abre el
        streaming con el mando y el tactil apuntando a la PC. get_config primero (3 s) para avisar rapido si la
        PC no responde, en vez de esperar los 20 s de set_config."""
        if self.saliendo or self.ocupado:
            return
        self.saliendo = True
        ip_pc = leer_ip_pc()
        self.tira.pintar(ui.TENUE, f"Pidiéndole a la PC ({ip_pc}) que transmita a esta Deck...")

        def trabajo():
            mi_ip = server_udp.obtener_ip_local()
            if not mi_ip:
                return False, (ui.ERROR, "Esta Deck no tiene red.")
            if not server_udp.obtener_config(ip_pc)[0] or not server_udp.aplicar_config(ip_pc, mi_ip, "pc")[0]:
                return False, (ui.AVISO, f"La PC {ip_pc} no responde. ¿Está prendida y con el servidor de PC "
                                         "corriendo?")
            return True, None

        def listo(r):
            ok, error = r
            if not ok:
                self.saliendo = False
                self.tira.pintar(*(error if isinstance(error, tuple) else (ui.ERROR, str(error))))
                return
            self.tira.pintar(ui.OK, "PC lista: arrancando el streaming...")
            self.app.root.after(ESPERA_SALIDA_MS, lambda: self.app.terminar("pc"))

        self.app.en_fondo(trabajo, listo)

    def reiniciar_servidor(self):
        if self.saliendo or self.ocupado:
            return
        self.ocupado = True
        ip_pc = leer_ip_pc()
        self.tira.pintar(ui.TENUE, f"Reiniciando el servidor de la PC ({ip_pc})...")

        def listo(r):
            self.ocupado = False
            ok, resp = r
            if not ok:
                self.tira.pintar(ui.AVISO, f"La PC {ip_pc} no responde. ¿Está prendida y con el servidor de PC "
                                           "corriendo?")
            elif not resp.get("ok", False):
                self.tira.pintar(ui.ERROR, "La PC no pudo reiniciar: " + str(resp.get("error", "servidor viejo, "
                                                                                       "sin este comando")))
            else:
                self.tira.pintar(ui.OK, "Servidor de PC reiniciado. Elige Jugar para volver a jugar.")

        self.app.en_fondo(lambda: server_udp.reiniciar_servidor_pc(ip_pc), listo)

    def reiniciar_steam(self):
        if self.saliendo or self.ocupado:
            return
        self.ocupado = True
        ip_pc = leer_ip_pc()
        self.tira.pintar(ui.TENUE, f"Pidiéndole a la PC ({ip_pc}) que reinicie Steam...")

        def listo(r):
            ok, resp = r
            if not ok:
                self.ocupado = False
                self.tira.pintar(ui.AVISO, f"La PC {ip_pc} no responde. ¿Está prendida y con el servidor de PC "
                                           "corriendo?")
            elif not resp.get("ok", False):
                self.ocupado = False
                self.tira.pintar(ui.ERROR, "La PC no reconoce el comando: actualiza el servidor de PC.")
            else:
                self._seguir_steam(ip_pc, time.time())

        self.app.en_fondo(lambda: server_udp.reiniciar_steam_pc(ip_pc), listo)

    def _seguir_steam(self, ip_pc, inicio):
        """Pregunta cada 2 s como va (get_config -> "steam"), hasta ESPERA_STEAM_S."""
        def listo(r):
            ok, resp = r
            estado = (resp.get("steam") or "") if ok else ""
            seg = int(time.time() - inicio)
            if estado == "listo":
                self.ocupado = False
                self.tira.pintar(ui.OK, "Steam reiniciado. Big Picture tarda unos segundos más en salir; "
                                        "luego elige Jugar.")
            elif estado.startswith("error"):
                self.ocupado = False
                self.tira.pintar(ui.ERROR, "No se pudo reiniciar Steam: " + estado.split(":", 1)[-1].strip())
            elif seg > ESPERA_STEAM_S:
                self.ocupado = False
                self.tira.pintar(ui.AVISO, f"Steam sigue sin terminar de reiniciar tras {ESPERA_STEAM_S} s. "
                                           "Revisa la laptop.")
            else:
                paso = {"cerrando": "cerrando Steam", "abriendo": "abriendo Steam en Big Picture"}.get(
                    estado, "esperando a la PC")
                self.tira.pintar("#d4b106", f"Reiniciando Steam: {paso}... ({seg} s)")
                self.app.root.after(2000, lambda: None if self.app.cerrado else self._seguir_steam(ip_pc, inicio))

        self.app.en_fondo(lambda: server_udp.obtener_config(ip_pc), listo)

    def editar_ip(self):
        if self.saliendo or self.ocupado:
            return

        def aceptar(texto):
            texto = texto.strip()
            if not ip_valida(texto):
                self.tira.pintar(ui.ERROR, f"IP no válida: {texto}")
                return
            guardar_ip_pc(texto)
            self.t_ip.titulo = texto
            self.t_ip._pintar()
            self.consultar_estado()

        ui.DialogoTexto(self.app, "IP de la PC", leer_ip_pc(), aceptar)

    def tecla(self, nombre):
        if self.saliendo:
            return
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
        elif nombre == "B":
            self.app.volver()
