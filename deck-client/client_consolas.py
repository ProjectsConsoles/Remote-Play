#!/usr/bin/env python3
"""Pantalla "¿Qué consola?" (2026-10-04): la abren Streaming y Solo control del menu principal.

Antes Streaming/Solo control arrancaban directo y el modo del ESP32-S3 se cambiaba aparte (Info,
o sosteniendo BOOT). Pedido del usuario: elegir la consola al entrar y que el ESP32 quede
configurado solo. Al elegir una consola del ESP32 se le manda {"set_modo": n} (el mismo comando de
Info) en ese momento y se sigue al modo pedido. El firmware SIEMPRE se reinicia al recibirlo
(~2-4 s sin control en la consola), aunque ya estuviera en ese modo: decision del usuario, sin
cambiar el firmware. Info sigue existiendo como respaldo por si el comando no llega.

Streaming ademas ofrece las apps externas (PS4/PS5 con chiaki-ng, Xbox One/Series con xbPlay,
ver client_apps.py), que no usan el servidor ni el ESP32. Solo control muestra unicamente las 4
consolas del ESP32 (las apps traen su propio control).
"""

import tkinter as tk

import client_apps
import ui_mosaicos as ui

ESPERA_SALIDA_MS = 900   # lo justo para leer "Modo X enviado" antes de que se cierre el menu


class PantallaConsola(ui.Pantalla):
    """`modo` = "streaming" o "control" (lo que se imprime al final para start_client_stream.sh).
    `verificar_servidor` = client_menu.verificar_servidor_listo (se pasa para no importar
    client_menu de vuelta); solo se usa en streaming con una consola del ESP32."""

    def __init__(self, app, modo, verificar_servidor=None):
        super().__init__(app)
        self.modo = modo
        self.verificar_servidor = verificar_servidor
        self.saliendo = False
        esc, iconos = app.esc, app.iconos
        marco = tk.Frame(self.frame, bg=ui.FONDO, padx=esc.px(24), pady=esc.px(16))
        marco.pack(fill="both", expand=True)
        titulo = "Streaming: ¿qué consola?" if modo == "streaming" else "Solo control: ¿qué consola?"
        cab, _ = ui.cabecera(marco, esc, titulo)
        cab.pack(fill="x")
        self.tira = ui.TiraEstado(marco, esc)
        self.tira.pack(fill="x", pady=(esc.px(6), esc.px(4)))

        # Streaming: 3 + 3 (PS3 PS2 360 / Xbox PS4-5 XboxOne). Solo control: 2 + 2. Las filas se
        # crean antes porque cada Mosaico nace dentro de la suya.
        total = len(ui.LEDS) + (2 if modo == "streaming" else 0)
        por_fila = 3 if modo == "streaming" else 2
        marcos = [ui.fila(marco, esc) for _ in range((total + por_fila - 1) // por_fila)]
        todos = []

        def padre():
            return marcos[len(todos) // por_fila]

        # Las 4 consolas del ESP32: mismos colores/logos que el LED y que Info (ui.LEDS).
        self.estados = {}
        for i, (color, nombre_color, consola, color_texto, icono) in enumerate(ui.LEDS):
            t = ui.Mosaico(padre(), esc, iconos, icono, consola, f"Capturadora + ESP32 (LED {nombre_color.lower()})",
                           color, color_texto=color_texto, tam_titulo=30, tam_detalle=15,
                           on_a=lambda i=i, c=consola: self.elegir_esp32(i, c))
            self.estados[t] = (ui.TENUE, f"{consola}: el ESP32 se configura solo al elegirla "
                                         "(se reinicia ~2 s).")
            todos.append(t)

        if modo == "streaming":
            ok_c, col_c, txt_c = client_apps.estado_chiaki()
            ok_x, col_x, txt_x = client_apps.estado_xbplay()
            t_chiaki = ui.Mosaico(padre(), esc, iconos, "ps", "PS4 / PS5",
                                  "chiaki-ng (Remote Play de Sony)." if ok_c else "No está instalado.",
                                  client_apps.AZUL_PS if ok_c else ui.mezclar(client_apps.AZUL_PS, ui.FONDO, 0.6),
                                  tam_titulo=30, tam_detalle=15,
                                  on_a=lambda: self.elegir_app("chiaki", client_apps.estado_chiaki))
            todos.append(t_chiaki)
            t_xbplay = ui.Mosaico(padre(), esc, iconos, "xbox", "Xbox One / Series",
                                  "xbPlay (Remote Play de Xbox)." if ok_x else "No está instalado.",
                                  client_apps.VERDE_XBOX if ok_x else ui.mezclar(client_apps.VERDE_XBOX, ui.FONDO, 0.6),
                                  tam_titulo=30, tam_detalle=15,
                                  on_a=lambda: self.elegir_app("xbplay", client_apps.estado_xbplay))
            self.estados[t_chiaki] = (col_c, txt_c)
            self.estados[t_xbplay] = (col_x, txt_x)
            todos.append(t_xbplay)

        filas = [todos[k:k + por_fila] for k in range(0, len(todos), por_fila)]
        for f, fila_ in zip(marcos, filas):
            ui.disponer(f, fila_, esc, columnas=por_fila)

        pie = ui.fila(marco, esc, expandir=False)
        volver = ui.Mosaico(pie, esc, iconos, "back", "Volver", "B o Escape", ui.GRIS, on_a=app.volver,
                            tam_titulo=22, tam_detalle=13, tam_icono=40, horizontal=True, alto=esc.px(84))
        ui.disponer(pie, [volver], esc)
        self.estados[volver] = (ui.TENUE, "Volver al menú.")
        self.nav = ui.Navegador(filas + [[volver]], al_cambiar=self._foco)

    def _foco(self, mosaico):
        if not self.saliendo:
            self.tira.pintar(*self.estados.get(mosaico, (ui.TENUE, "")))

    def _salir(self, resultado):
        self.saliendo = True
        self.app.root.after(ESPERA_SALIDA_MS, lambda: self.app.terminar(resultado))

    def elegir_esp32(self, indice, consola):
        if self.saliendo:
            return
        if self.modo == "streaming" and self.verificar_servidor:
            # Primero el servidor: si no esta listo no tiene caso reiniciar el ESP32.
            self.tira.pintar(ui.TENUE, "Verificando el servidor...")
            self.app.root.update_idletasks()
            ok, mensaje = self.verificar_servidor()
            if not ok:
                self.tira.pintar(ui.AVISO, "No se puede iniciar streaming: " + mensaje.replace("\n\n", "  "))
                return
        if ui.enviar_modo_esp32(indice):
            self.tira.pintar("#d4b106", f"ESP32 en modo {consola}: se reinicia (~2 s) y arranca "
                                        f"{'el streaming' if self.modo == 'streaming' else 'solo control'}...")
        else:
            # Sin red no hay forma de mandarlo; se sigue igual (puede que ya este en ese modo).
            self.tira.pintar(ui.AVISO, f"No pude mandar el modo {consola} al ESP32; sigo igual "
                                       "(revisa Info si el control no responde).")
        self._salir(self.modo)

    def elegir_app(self, resultado, estado):
        if self.saliendo:
            return
        instalado, _, texto = estado()   # se revisa otra vez: pudo instalarse con el menu abierto
        if not instalado:
            self.tira.pintar(ui.ERROR, "No se puede abrir: " + texto)
            return
        self.tira.pintar(ui.OK, "Abriendo " + ("chiaki-ng" if resultado == "chiaki" else "xbPlay") + "...")
        self._salir(resultado)

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
