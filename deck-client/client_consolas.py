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

        # Una fila por marca, en orden de generacion (2026-10-04, pedido del usuario: "lo de play con
        # lo de play y xbox con lo de xbox"). Numeros = indice en ui.LEDS (0 PS3, 1 PS2, 2 Xbox 360,
        # 3 Xbox clasico), que es tambien el modo que se le manda al ESP32. Solo control no lleva las
        # apps externas. Las filas se crean antes porque cada Mosaico nace dentro de la suya.
        if modo == "streaming":
            orden = [1, 0, "chiaki", 3, 2, "xbplay"]
            por_fila = 3
        else:
            orden = [1, 0, 3, 2]
            por_fila = 2
        marcos = [ui.fila(marco, esc) for _ in range((len(orden) + por_fila - 1) // por_fila)]
        todos = []
        self.estados = {}

        def padre():
            return marcos[len(todos) // por_fila]

        def mosaico_esp32(i):
            # Mismos colores/logos que el LED y que Info (ui.LEDS).
            color, nombre_color, consola, color_texto, icono = ui.LEDS[i]
            t = ui.Mosaico(padre(), esc, iconos, icono, consola, f"Capturadora + ESP32 (LED {nombre_color.lower()})",
                           color, color_texto=color_texto, tam_titulo=30, tam_detalle=15,
                           on_a=lambda: self.elegir_esp32(i, consola))
            self.estados[t] = (ui.TENUE, f"{consola}: el ESP32 se configura solo al elegirla "
                                         "(se reinicia ~2 s).")
            return t

        def mosaico_app(clave):
            if clave == "chiaki":
                estado, icono, titulo, detalle, color = (client_apps.estado_chiaki, "ps", "PS4 / PS5",
                                                         "chiaki-ng (Remote Play de Sony).", client_apps.AZUL_PS)
            else:
                estado, icono, titulo, detalle, color = (client_apps.estado_xbplay, "xbox", "Xbox One / Series",
                                                         "xbPlay (Remote Play de Xbox).", client_apps.VERDE_XBOX)
            ok, col, txt = estado()
            t = ui.Mosaico(padre(), esc, iconos, icono, titulo, detalle if ok else "No está instalado.",
                           color if ok else ui.mezclar(color, ui.FONDO, 0.6), tam_titulo=30, tam_detalle=15,
                           on_a=lambda: self.elegir_app(clave, estado))
            self.estados[t] = (col, txt)
            return t

        for clave in orden:
            todos.append(mosaico_esp32(clave) if isinstance(clave, int) else mosaico_app(clave))

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
