#!/usr/bin/env python3
"""Pantalla "Configurar servidor" del menu de la Deck (2026-09-11).

Deja elegir el modo de captura del servidor Windows (y confirma la IP de
esta Deck) SIN tener que ir a tocar la PC - manda el cambio por red al
config_listener.ps1 que corre alli (ver ese script para el protocolo).

Si el servidor ya esta transmitiendo, el cambio lo REINICIA con la config
nueva (unos segundos de corte). Si esta apagado, solo queda guardado para
la proxima vez que le den Iniciar en la PC - eso lo decide el listener, no
esta pantalla.

Mismo estilo visual que client_menu.py (mismos colores, misma fuente,
mismo patron de navegacion con el mando via deck_gamepad.Mando).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from deck_gamepad import Mando  # noqa: E402
import server_udp  # noqa: E402

FONDO = "#101014"
TEXTO = "#e8e8ea"
TENUE = "#8a8a95"
VERDE = "#3f8f4a"
ROJO = "#c0392b"

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
]

IP_SERVIDOR_DEFAULT = "192.168.0.90"


def main():
    import tkinter as tk
    from tkinter import font as tkfont

    root = tk.Tk()
    root.title("Configurar servidor")
    root.configure(bg=FONDO)
    try:
        root.attributes("-fullscreen", True)
    except Exception:
        root.geometry("900x600")

    f_titulo = tkfont.Font(family="DejaVu Sans", size=26, weight="bold")
    f_label = tkfont.Font(family="DejaVu Sans", size=13)
    f_entry = tkfont.Font(family="DejaVu Sans", size=14)
    f_boton = tkfont.Font(family="DejaVu Sans", size=15, weight="bold")
    f_modo_titulo = tkfont.Font(family="DejaVu Sans", size=13, weight="bold")
    f_modo_detalle = tkfont.Font(family="DejaVu Sans", size=10)
    f_estado = tkfont.Font(family="DejaVu Sans", size=12)
    f_pie = tkfont.Font(family="DejaVu Sans", size=11)

    tk.Label(root, text="Configurar servidor", font=f_titulo,
             bg=FONDO, fg=TEXTO).pack(pady=(30, 4))

    ip_deck = server_udp.obtener_ip_local() or "?"
    tk.Label(root, text=f"Esta Deck: {ip_deck}", font=f_pie,
             bg=FONDO, fg=TENUE).pack(pady=(0, 14))

    # --- IP del servidor ---
    filaIp = tk.Frame(root, bg=FONDO)
    filaIp.pack(pady=(0, 8))
    tk.Label(filaIp, text="IP del servidor Windows:", font=f_label,
             bg=FONDO, fg=TEXTO).pack(side="left", padx=(0, 10))
    ip_guardada = server_udp.leer_ip_servidor_guardada() or IP_SERVIDOR_DEFAULT
    entryIp = tk.Entry(filaIp, font=f_entry, width=16, justify="center")
    entryIp.insert(0, ip_guardada)
    entryIp.pack(side="left")

    lblEstado = tk.Label(root, text="Sin consultar todavia.", font=f_estado,
                          bg=FONDO, fg=TENUE)
    lblEstado.pack(pady=(6, 18))

    # --- Tarjetas de modo ---
    fila = tk.Frame(root, bg=FONDO)
    fila.pack(expand=True)

    estado = {"seleccionado": 0}
    tarjetas = []

    def elegir_modo(i):
        estado["seleccionado"] = i
        marcar()

    for i, (clave, nombre, detalle) in enumerate(MODOS):
        marco = tk.Frame(fila, bg="#181c28", padx=14, pady=12,
                          highlightthickness=3, highlightbackground=FONDO)
        marco.grid(row=i // 2, column=i % 2, padx=10, pady=10, sticky="nsew")
        marco.bind("<Button-1>", lambda e, i=i: elegir_modo(i))
        t = tk.Label(marco, text=nombre, font=f_modo_titulo, bg="#181c28", fg=TEXTO)
        t.pack(anchor="w")
        t.bind("<Button-1>", lambda e, i=i: elegir_modo(i))
        d = tk.Label(marco, text=detalle, font=f_modo_detalle, bg="#181c28",
                     fg=TENUE, wraplength=280, justify="left")
        d.pack(anchor="w", pady=(4, 0))
        d.bind("<Button-1>", lambda e, i=i: elegir_modo(i))
        tarjetas.append(marco)

    def marcar():
        for i, m in enumerate(tarjetas):
            m.configure(highlightbackground="#ffffff" if i == estado["seleccionado"] else FONDO)

    # --- Botones de accion ---
    filaBotones = tk.Frame(root, bg=FONDO)
    filaBotones.pack(pady=(18, 10))

    def consultar():
        ip = entryIp.get().strip()
        if not ip:
            lblEstado.configure(text="Pon una IP primero.", fg=ROJO)
            return
        lblEstado.configure(text="Consultando...", fg=TENUE)
        root.update_idletasks()
        ok, resp = server_udp.obtener_config(ip)
        if not ok:
            lblEstado.configure(text=str(resp), fg=ROJO)
            return
        server_udp.guardar_ip_servidor(ip)
        corriendo = "SI" if resp.get("corriendo") else "no"
        modo_actual = resp.get("modo") or "(ninguno guardado)"
        lblEstado.configure(
            text=f"Corriendo: {corriendo}  ·  Modo actual: {modo_actual}",
            fg=VERDE if resp.get("corriendo") else TENUE)
        for i, (clave, _, _) in enumerate(MODOS):
            if clave == resp.get("modo"):
                estado["seleccionado"] = i
        marcar()

    def aplicar():
        ip = entryIp.get().strip()
        if not ip:
            lblEstado.configure(text="Pon una IP primero.", fg=ROJO)
            return
        clave = MODOS[estado["seleccionado"]][0]
        lblEstado.configure(text="Aplicando...", fg=TENUE)
        root.update_idletasks()
        ok, resp = server_udp.aplicar_config(ip, ip_deck, clave)
        if not ok:
            lblEstado.configure(text=str(resp), fg=ROJO)
            return
        server_udp.guardar_ip_servidor(ip)
        aplicado = resp.get("aplicado")
        if aplicado == "reiniciado":
            lblEstado.configure(text="Listo: servidor reiniciado con la config nueva.", fg=VERDE)
        elif aplicado == "guardado_para_proxima_vez":
            lblEstado.configure(
                text="Guardado. El servidor no estaba corriendo; se aplicara la proxima vez que le den Iniciar.",
                fg=VERDE)
        else:
            lblEstado.configure(text=str(resp), fg=ROJO)

    btnConsultar = tk.Button(filaBotones, text="Consultar estado", font=f_boton,
                              bg="#3a3a42", fg="#ffffff", activebackground="#4a4a55",
                              activeforeground="#ffffff", relief="flat", bd=0,
                              width=16, height=2, command=consultar)
    btnConsultar.pack(side="left", padx=10)

    btnAplicar = tk.Button(filaBotones, text="Aplicar", font=f_boton,
                            bg="#2d6cdf", fg="#ffffff", activebackground="#2d6cdf",
                            activeforeground="#ffffff", relief="flat", bd=0,
                            width=16, height=2, command=aplicar)
    btnAplicar.pack(side="left", padx=10)

    btnVolver = tk.Button(filaBotones, text="Volver", font=f_boton,
                           bg="#3a3a42", fg="#ffffff", activebackground="#4a4a55",
                           activeforeground="#ffffff", relief="flat", bd=0,
                           width=12, height=2, command=root.destroy)
    btnVolver.pack(side="left", padx=10)

    tk.Label(root, text="Flechas para elegir modo, Enter aplica, Escape vuelve.",
             font=f_pie, bg=FONDO, fg=TENUE).pack(side="bottom", pady=16)

    root.bind("<Left>", lambda e: elegir_modo((estado["seleccionado"] - 1) % len(MODOS)))
    root.bind("<Right>", lambda e: elegir_modo((estado["seleccionado"] + 1) % len(MODOS)))
    root.bind("<Up>", lambda e: elegir_modo((estado["seleccionado"] - 2) % len(MODOS)))
    root.bind("<Down>", lambda e: elegir_modo((estado["seleccionado"] + 2) % len(MODOS)))
    root.bind("<Return>", lambda e: aplicar())
    root.bind("<Escape>", lambda e: root.destroy())

    mando = Mando()

    def revisar_mando():
        for nombre in mando.nuevos():
            if nombre == "DPAD_LEFT":
                elegir_modo((estado["seleccionado"] - 1) % len(MODOS))
            elif nombre == "DPAD_RIGHT":
                elegir_modo((estado["seleccionado"] + 1) % len(MODOS))
            elif nombre == "DPAD_UP":
                elegir_modo((estado["seleccionado"] - 2) % len(MODOS))
            elif nombre == "DPAD_DOWN":
                elegir_modo((estado["seleccionado"] + 2) % len(MODOS))
            elif nombre == "A":
                aplicar()
            elif nombre == "B":
                root.destroy()
                return
        root.after(40, revisar_mando)

    marcar()
    consultar()
    root.after(40, revisar_mando)
    root.mainloop()


if __name__ == "__main__":
    main()
