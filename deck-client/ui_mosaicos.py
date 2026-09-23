#!/usr/bin/env python3
"""Piezas visuales compartidas de los menus (Deck, y despues la Ally): el mismo estilo de
"mosaicos" que el cliente Android.

Nada de aqui habla con la red: solo dibuja, lleva el foco y reparte el mando/teclado. Cada
pantalla (client_menu.py, client_server_config.py, client_settings.py) es una `Pantalla` que arma
sus mosaicos, se los da a un `Navegador` y recibe los botones ya traducidos en `tecla(nombre)`.
`App` es dueña de UN solo deck_gamepad.Mando para toda la sesion (ver la nota en client_menu.py).

Piezas:
    Escala        tamanos relativos a la pantalla (la Deck, 1280x800, es escala 1.0)
    Iconos        PNG blancos con transparencia (carpeta iconos/, sacados de los vectores de Android)
    Mosaico       tarjeta redondeada con icono, titulo y descripcion; el foco la "agranda" y le pone
                  borde blanco (tkinter no tiene escalado, asi que se logra achicando el margen)
    TiraEstado    tira redondeada con un punto de color y un mensaje
    Navegador     foco por fila/columna entre mosaicos (cruceta), activar con A, tocar con el dedo
    App           ventana unica con una PILA de pantallas que se deslizan (abrir: de derecha a
                  izquierda; volver: de izquierda a derecha), y que lee mando y teclado en un solo lugar
    Pantalla      base de cada pantalla (un Frame dentro de App)
    DialogoTexto  cuadro para escribir un texto (IP, numero), como panel dentro de la ventana
    PantallaInfo  los colores del LED del ESP32-S3

PS3RP_VENTANA=1280x800 (solo para probar en una PC): abre una ventana de ese tamano en vez de
pantalla completa.
"""

import os
import time
import tkinter as tk
from tkinter import font as tkfont

FONDO = "#12161c"
PANEL = "#1e252e"
TEXTO = "#e9eef3"
TENUE = "#93a1b0"
OK = "#3ddc84"
AVISO = "#ffb74d"
ERROR = "#ff6b6b"

AZUL = "#2d6cdf"
VERDE = "#3f8f4a"
MORADO = "#8e5fd6"
NARANJA = "#c07d2f"
GRIS = "#2a3441"
ROJO = "#b03a3a"
ROJO_OSCURO = "#7a2e2e"
BLANCO = "#ffffff"

FAMILIA = "DejaVu Sans"
DURACION_FOCO = 0.14   # segundos: lo que tarda una tarjeta en ganar/perder el foco (Android: 120 ms)
CARPETA_ICONOS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "iconos")


def configurar_ventana(root):
    """Pantalla completa (o el tamano de PS3RP_VENTANA para pruebas). Devuelve el alto en pixeles."""
    prueba = os.environ.get("PS3RP_VENTANA", "")
    if prueba and "x" in prueba:
        try:
            ancho, alto = (int(v) for v in prueba.lower().split("x", 1))
            root.geometry(f"{ancho}x{alto}+0+40")
            return alto
        except ValueError:
            pass
    try:
        root.attributes("-fullscreen", True)
    except Exception:
        root.geometry("1280x800")
        return 800
    return root.winfo_screenheight()


def mezclar(color, con, f):
    """Mezcla dos colores '#rrggbb': f=0 -> color, f=1 -> con."""
    a = [int(color[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(con[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * f):02x}" for x, y in zip(a, b))


class Escala:
    def __init__(self, alto):
        self.f = max(0.7, min(1.8, alto / 800.0))
        self._fuentes = {}

    def px(self, n):
        return max(1, round(n * self.f))

    def fuente(self, tam, negrita=False):
        clave = (tam, negrita)
        if clave not in self._fuentes:
            self._fuentes[clave] = tkfont.Font(
                family=FAMILIA, size=-self.px(tam), weight="bold" if negrita else "normal")
        return self._fuentes[clave]


class Iconos:
    """Carga perezosa de los PNG. Hay que crear uno por ventana (las imagenes pertenecen a su Tk)."""

    def __init__(self):
        self._cache = {}

    def get(self, nombre, lado):
        if not nombre:
            return None
        disco = 72 if lado >= 56 else 40
        clave = (nombre, disco)
        if clave not in self._cache:
            try:
                self._cache[clave] = tk.PhotoImage(file=os.path.join(CARPETA_ICONOS, f"{nombre}_{disco}.png"))
            except Exception:
                self._cache[clave] = None  # sin icono, pero el mosaico se dibuja igual
        return self._cache[clave]


def _rect_redondeado(x1, y1, x2, y2, r):
    # Poligono con esquinas repetidas + smooth=True = rectangulo con esquinas redondas.
    return [x1 + r, y1, x1 + r, y1, x2 - r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y1 + r,
            x2, y2 - r, x2, y2 - r, x2, y2, x2 - r, y2, x2 - r, y2, x1 + r, y2, x1 + r, y2,
            x1, y2, x1, y2 - r, x1, y2 - r, x1, y1 + r, x1, y1 + r, x1, y1]


class Mosaico(tk.Canvas):
    """Tarjeta con icono, titulo y descripcion. `horizontal=True` = icono a la izquierda y texto a
    la derecha (botones de abajo: Volver, Guardar...)."""

    def __init__(self, parent, esc, iconos, icono, titulo, detalle="", color=AZUL, on_a=None,
                 tam_titulo=24, tam_detalle=13, tam_icono=72, color_texto=BLANCO,
                 interactivo=True, horizontal=False, alto=None, on_click=None):
        super().__init__(parent, bg=FONDO, highlightthickness=0, bd=0, takefocus=0,
                         height=alto if alto else esc.px(150), width=esc.px(200))
        self.esc = esc
        self.iconos = iconos
        self.icono = icono
        self.titulo = titulo
        self.detalle = detalle
        self.color = color
        self.color_texto = color_texto
        self.tam_titulo = tam_titulo
        self.tam_detalle = tam_detalle
        self.tam_icono = tam_icono
        self.on_a = on_a
        self.on_click = on_click  # si se da, el dedo hace esto en vez de on_a (solo enfoca/elige)
        self.interactivo = interactivo
        self.horizontal = horizontal
        self.habilitado = True
        self.foco = False
        self.marcado = False
        self.al_tocar = None      # lo pone el Navegador
        self.arriba = None        # widget que debe quedar visible al enfocar (listas con scroll)
        # Foco suave (2026-09-20, como Android): _t va de 0 (sin foco) a 1 (con foco) con frenado.
        self._t = self._desde = self._objetivo = 0.0
        self._t0 = 0.0
        self._dur = DURACION_FOCO
        self._job = None
        self.bind("<Configure>", lambda e: self._pintar())
        if interactivo:
            self.bind("<Button-1>", self._tocado)

    # --- estado -------------------------------------------------------------------------------
    def poner_foco(self, si, animar=True):
        if si == self.foco:
            return
        self.foco = si
        self._objetivo = 1.0 if si else 0.0
        if self._job is not None:
            self.after_cancel(self._job)
            self._job = None
        if not animar:
            self._t = self._desde = self._objetivo
            self._actualizar_forma()
            return
        self._desde = self._t
        self._dur = max(0.05, DURACION_FOCO * abs(self._objetivo - self._desde))
        self._t0 = time.monotonic()
        self._paso_foco()

    def _paso_foco(self):
        self._job = None
        p = min(1.0, (time.monotonic() - self._t0) / self._dur)
        e = 1 - (1 - p) ** 3   # frena al llegar
        self._t = self._desde + (self._objetivo - self._desde) * e
        self._actualizar_forma()
        if p < 1.0:
            self._job = self.after(10, self._paso_foco)
        else:
            self._t = self._objetivo

    def destroy(self):
        if self._job is not None:
            try:
                self.after_cancel(self._job)
            except Exception:
                pass
            self._job = None
        super().destroy()

    def _puntos_forma(self, w, h):
        esc = self.esc
        inset = round(esc.px(7) + (esc.px(1) - esc.px(7)) * self._t)   # crece al enfocar
        return _rect_redondeado(inset, inset, w - inset, h - inset, esc.px(20))

    def _actualizar_forma(self):
        """Durante la animacion solo se mueve el fondo y se aclara el borde: el texto no se redibuja."""
        w, h = self.winfo_width(), self.winfo_height()
        if w < 30 or h < 30:
            return
        if not self.find_withtag("forma"):
            self._pintar()
            return
        color = self.color if self.habilitado else mezclar(self.color, FONDO, 0.55)
        self.coords("forma", *self._puntos_forma(w, h))
        self.itemconfigure("forma", outline=mezclar(color, BLANCO, self._t))

    def poner_titulo(self, texto):
        self.titulo = texto
        self._pintar()

    def poner_detalle(self, texto):
        self.detalle = texto
        self._pintar()

    def poner_color(self, color):
        self.color = color
        self._pintar()

    def poner_marca(self, si):
        if si != self.marcado:
            self.marcado = si
            self._pintar()

    def habilitar(self, si):
        self.habilitado = si
        self._pintar()

    def activar(self):
        if self.habilitado and self.on_a:
            self.on_a()

    def _tocado(self, _e):
        if self.al_tocar:
            self.al_tocar(self)
        if self.on_click is not None:
            if self.habilitado:
                self.on_click()
        else:
            self.activar()

    # --- dibujo -------------------------------------------------------------------------------
    def _pintar(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 30 or h < 30:
            return
        esc = self.esc
        color = self.color if self.habilitado else mezclar(self.color, FONDO, 0.55)
        grosor = esc.px(4)
        self.create_polygon(
            self._puntos_forma(w, h), smooth=True, fill=color,
            outline=mezclar(color, BLANCO, self._t), width=grosor, tags="forma")

        pad = esc.px(24)   # fijo: el texto ya no se corre al enfocar (solo crece la forma)
        ancho_txt = max(40, w - 2 * pad)
        lado_icono = esc.px(self.tam_icono)
        img = self.iconos.get(self.icono, lado_icono) if self.icono else None
        color_txt = self.color_texto if self.habilitado else mezclar(self.color_texto, color, 0.4)
        color_det = mezclar(color_txt, color, 0.12)
        f_tit = esc.fuente(self.tam_titulo, True)
        f_det = esc.fuente(self.tam_detalle)

        # Todo lo de adentro se arma apilado desde y=0 y al final se baja la mitad del espacio libre,
        # asi queda centrado en vertical y alineado a la izquierda (como en Android).
        partes = []
        if self.horizontal:
            x = pad
            if img:
                partes.append(self.create_image(x, 0, image=img, anchor="nw"))
                x += img.width() + esc.px(14)
            ancho_txt = max(40, w - x - pad)
            t = self.create_text(x, 0, text=self.titulo, fill=color_txt, font=f_tit,
                                 anchor="nw", width=ancho_txt)
            partes.append(t)
            fin = self.bbox(t)[3]
            if self.detalle:
                d = self.create_text(x, fin + esc.px(2), text=self.detalle, fill=color_det,
                                     font=f_det, anchor="nw", width=ancho_txt)
                partes.append(d)
                fin = self.bbox(d)[3]
            if img:
                # el icono se centra respecto del bloque de texto
                self.move(partes[0], 0, max(0, (fin - img.height()) // 2))
        else:
            y = 0
            if img:
                partes.append(self.create_image(pad, y, image=img, anchor="nw"))
                y += img.height() + esc.px(8)
            t = self.create_text(pad, y, text=self.titulo, fill=color_txt, font=f_tit,
                                 anchor="nw", width=ancho_txt)
            partes.append(t)
            fin = self.bbox(t)[3]
            if self.detalle:
                d = self.create_text(pad, fin + esc.px(3), text=self.detalle, fill=color_det,
                                     font=f_det, anchor="nw", width=ancho_txt)
                partes.append(d)
                fin = self.bbox(d)[3]
        libre = max(0, (h - fin) // 2)
        for p in partes:
            self.move(p, 0, libre)

        if self.marcado:
            r = esc.px(15)
            cx, cy = w - pad + esc.px(6) - r, pad - esc.px(6) + r
            self.create_oval(cx - r, cy - r, cx + r, cy + r, fill=BLANCO, outline=BLANCO)
            self.create_text(cx, cy, text="✓", fill=self.color, font=esc.fuente(17, True))


class TiraEstado(tk.Canvas):
    """Tira redondeada con un punto de color y un mensaje (puede tener varias lineas)."""

    def __init__(self, parent, esc, alto=54):
        super().__init__(parent, bg=FONDO, highlightthickness=0, bd=0, height=esc.px(alto))
        self.esc = esc
        self.alto_min = esc.px(alto)
        self._color = TENUE
        self._texto = ""
        self._ajustes = 0
        self.bind("<Configure>", lambda e: self._pintar())

    def pintar(self, color, texto):
        self._color, self._texto = color, texto
        self._ajustes = 0
        self._pintar()

    def _pintar(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 60:
            return
        esc = self.esc
        x_txt = esc.px(46)
        t = self.create_text(x_txt, 0, text=self._texto, fill=TEXTO, font=esc.fuente(15),
                             anchor="nw", width=w - x_txt - esc.px(20))
        bb = self.bbox(t)
        alto_txt = bb[3] - bb[1]
        necesario = max(self.alto_min, alto_txt + esc.px(24))
        if abs(necesario - h) > 1 and self._ajustes < 4:
            # el mensaje tiene mas (o menos) lineas: la tira cambia de alto y se repinta sola
            self._ajustes += 1
            self.configure(height=necesario)
            return
        self.create_polygon(_rect_redondeado(1, 1, w - 1, h - 1, esc.px(14)), smooth=True,
                            fill=PANEL, outline=PANEL, tags="fondo")
        self.tag_lower("fondo")
        self.coords(t, x_txt, max(0, (h - alto_txt) // 2))
        r = esc.px(7)
        self.create_oval(esc.px(24) - r, h // 2 - r, esc.px(24) + r, h // 2 + r,
                         fill=self._color, outline=self._color)


def cabecera(parent, esc, titulo, derecha=""):
    """Titulo grande a la izquierda y una nota tenue a la derecha. Devuelve (frame, label_derecha)."""
    f = tk.Frame(parent, bg=FONDO)
    tk.Label(f, text=titulo, font=esc.fuente(34, True), bg=FONDO, fg=TEXTO).pack(side="left")
    der = tk.Label(f, text=derecha, font=esc.fuente(14), bg=FONDO, fg=TENUE, justify="right")
    der.pack(side="right", anchor="s", pady=(0, esc.px(4)))
    return f, der


def fila(parent, esc, expandir=True, alto=None):
    """Una fila donde los mosaicos se reparten el ancho por igual. Crea los mosaicos con esta fila de
    padre y luego llama a disponer(fila, [mosaicos])."""
    f = tk.Frame(parent, bg=FONDO)
    if alto:
        f.configure(height=alto)
    f.pack(fill="both" if expandir else "x", expand=expandir)
    return f


def disponer(f, mosaicos, esc, columnas=None):
    """Coloca los mosaicos en columnas iguales. `columnas` fija cuantas columnas tiene la fila (para que
    una fila incompleta deje el hueco vacio en vez de estirar sus mosaicos)."""
    n = columnas or len(mosaicos)
    m = esc.px(6)
    for i in range(n):
        f.columnconfigure(i, weight=1, uniform="col")
    f.rowconfigure(0, weight=1)
    for i, t in enumerate(mosaicos):
        t.grid(row=0, column=i, sticky="nsew", padx=m, pady=m)


class Navegador:
    """Foco por fila/columna. `filas` = lista de listas de Mosaico (en el orden visual)."""

    def __init__(self, filas, al_cambiar=None, recordar=False):
        self.filas = [f for f in filas if f]
        self.f = 0
        self.c = 0
        self.al_cambiar = al_cambiar
        # recordar=True: al volver a una fila por arriba/abajo se cae en la columna donde se estuvo
        # (la fila de modos de "Configurar servidor" lo necesita: ahi la columna ES la eleccion).
        self.recordar = recordar
        self.memoria = {}
        for fila_ in self.filas:
            for t in fila_:
                t.al_tocar = self.ir_a
        self._inicial = True    # el foco inicial se pone sin animar (la pantalla ya viene deslizandose)
        self.marcar()
        self._inicial = False

    def actual(self):
        return self.filas[self.f][self.c]

    def ir_a(self, mosaico):
        for fi, fila_ in enumerate(self.filas):
            if mosaico in fila_:
                self.f, self.c = fi, fila_.index(mosaico)
                self.marcar()
                return

    def mover(self, dx, dy):
        if dy:
            self.f = (self.f + dy) % len(self.filas)
            if self.recordar and self.f in self.memoria:
                self.c = self.memoria[self.f]
            self.c = min(self.c, len(self.filas[self.f]) - 1)
        if dx:
            self.c = (self.c + dx) % len(self.filas[self.f])
        self.marcar()

    def marcar(self):
        self.memoria[self.f] = self.c
        act = self.actual()
        for fila_ in self.filas:
            for t in fila_:
                t.poner_foco(t is act, animar=not self._inicial)
        if self.al_cambiar:
            self.al_cambiar(act)

    def activar(self):
        self.actual().activar()


class Pantalla:
    """Base de una pantalla del menu: un Frame dentro de la ventana unica de `App`.

    Las subclases arman sus widgets en `self.frame` y definen `tecla(nombre)`, que recibe los nombres
    de botones de deck_gamepad ("DPAD_LEFT", "A", "B", "X", "Y", "L1", "R1"...), tanto del mando como
    del teclado (ver TECLAS). `al_mostrar()` se llama cuando la pantalla queda a la vista (al abrirse,
    ya terminada la animacion, y al volver a ella)."""

    def __init__(self, app):
        self.app = app
        self.frame = tk.Frame(app.contenedor, bg=FONDO)

    def tecla(self, nombre):
        pass

    def al_mostrar(self):
        pass


# Teclado -> nombres de boton del mando (asi cada pantalla solo entiende un vocabulario).
TECLAS = {
    "Left": "DPAD_LEFT", "Right": "DPAD_RIGHT", "Up": "DPAD_UP", "Down": "DPAD_DOWN",
    "Tab": "DPAD_RIGHT", "Return": "A", "KP_Enter": "A", "space": "A", "Escape": "B",
    "y": "Y", "Y": "Y", "x": "X", "X": "X",
}


class App:
    """Ventana unica (pantalla completa) con una pila de pantallas. Abrir una desliza la nueva de
    derecha a izquierda; volver la desliza de izquierda a derecha, como en Android. Tambien lee el
    mando y el teclado en un solo lugar y se lo pasa a la pantalla activa (o al cuadro de texto)."""

    DURACION = 0.32    # segundos (0.22 le parecio muy rapida al usuario, 2026-09-20)
    PARALAJE = 0.28    # cuanto se corre la pantalla de abajo (fraccion del ancho)
    # 2026-09-22: el usuario vio la transicion con "pocos fps" en la Deck real. Medido con
    # un arnes que parchea _animar en memoria (no toca lo desplegado): el paso corre firme
    # a ~8.2 ms incluso con las pantallas reales (Menu/Configurar servidor), asi que el
    # calculo en Python no es el cuello de botella. Pedir un paso cada 8 ms (~120 fps) es
    # mas rapido que cualquier pantalla real (60-90 Hz) y solo le compite trabajo de mas
    # al compositor de gamescope en Modo Juego (headless no lo reproduce). Bajado a 16 ms
    # (~60 fps, lo que cualquier pantalla puede mostrar) para no pelear con el compositor.
    PASO_MS = 16

    def __init__(self, titulo, mando):
        self.root = tk.Tk()
        self.root.title(titulo)
        self.root.configure(bg=FONDO)
        self.esc = Escala(configurar_ventana(self.root))
        self.iconos = Iconos()
        # UN solo mando para toda la sesion. Un Mando() nuevo arranca sin memoria de lo que ya estaba
        # apretado y lo cuenta como "recien pulsado": si cada pantalla creaba el suyo, soltar B/A al
        # cerrar una pantalla se colaba en la siguiente (B cancelaba el menu, A activaba Streaming).
        self.mando = mando
        try:
            self.mando.nuevos()   # lo que ya este apretado al abrir no cuenta
        except Exception:
            pass
        self.contenedor = tk.Frame(self.root, bg=FONDO)
        self.contenedor.pack(fill="both", expand=True)
        self.pila = []
        self.modal = None        # DialogoTexto abierto (tiene prioridad sobre la pantalla)
        self.animando = False
        self.resultado = None
        self.cerrado = False
        self.root.bind("<Key>", self._tecla_teclado)
        self.root.protocol("WM_DELETE_WINDOW", lambda: self.terminar(None))
        self.root.after(40, self._bucle_mando)

    # --- entrada -----------------------------------------------------------------------------
    def _despachar(self, nombre):
        if self.animando or self.cerrado:
            return
        try:
            if self.modal is not None and self.modal.abierto:
                self.modal.tecla(nombre)
            elif self.pila:
                self.pila[-1].tecla(nombre)
        except Exception:
            # un error en una pantalla no debe dejar el mando muerto: se registra y se sigue
            import traceback
            traceback.print_exc()

    def _tecla_teclado(self, e):
        if self.modal is not None and self.modal.abierto:
            return  # el cuadro de texto maneja su propio teclado (Enter / Escape)
        nombre = TECLAS.get(e.keysym)
        if nombre:
            self._despachar(nombre)

    def _bucle_mando(self):
        if self.cerrado:
            return
        try:
            for nombre in self.mando.nuevos():
                self._despachar(nombre)
                if self.cerrado:
                    return
        except Exception:
            import traceback
            traceback.print_exc()
        self.root.after(40, self._bucle_mando)

    # --- pila de pantallas ---------------------------------------------------------------------
    def abrir_inicial(self, pantalla):
        self.pila.append(pantalla)
        pantalla.frame.place(x=0, y=0, relwidth=1, relheight=1)
        self.root.after(30, pantalla.al_mostrar)

    def abrir(self, pantalla):
        if self.animando or not self.pila:
            pantalla.frame.destroy()
            return
        actual = self.pila[-1]
        self.pila.append(pantalla)

        def fin():
            actual.frame.place_forget()   # la de abajo deja de dibujarse mientras no se ve
            pantalla.al_mostrar()

        self._animar(pantalla, actual, +1, fin)

    def volver(self):
        if self.animando:
            return
        if len(self.pila) <= 1:
            self.terminar(None)
            return
        actual = self.pila.pop()
        anterior = self.pila[-1]

        def fin():
            actual.frame.destroy()
            anterior.al_mostrar()

        self._animar(anterior, actual, -1, fin)

    def reemplazar(self, nueva):
        """Cambia la pantalla de arriba por otra, sin animacion (p. ej. tras restaurar defaults)."""
        if self.animando or not self.pila:
            nueva.frame.destroy()
            return
        vieja = self.pila[-1]
        self.pila[-1] = nueva
        nueva.frame.place(x=0, y=0, relwidth=1, relheight=1)
        nueva.frame.lift()
        self.root.update_idletasks()
        vieja.frame.destroy()
        self.root.after(30, nueva.al_mostrar)

    def _animar(self, entrante, saliente, direccion, fin):
        self.root.update_idletasks()
        ancho = max(1, self.contenedor.winfo_width())
        corrimiento = int(ancho * self.PARALAJE)
        self.animando = True
        if direccion > 0:
            # abrir: la nueva llega desde la derecha encima; la de abajo se corre un poco a la izquierda
            entrante.frame.place(x=ancho, y=0, relwidth=1, relheight=1)
            entrante.frame.lift()

            def x_ent(e):
                return int(ancho * (1 - e))

            def x_sal(e):
                return -int(corrimiento * e)
        else:
            # volver: la actual sale hacia la derecha; la de abajo regresa desde la izquierda
            entrante.frame.place(x=-corrimiento, y=0, relwidth=1, relheight=1)
            entrante.frame.lower()
            saliente.frame.lift()

            def x_ent(e):
                return -int(corrimiento * (1 - e))

            def x_sal(e):
                return int(ancho * e)

        self.root.update_idletasks()
        t0 = time.monotonic()

        def paso():
            if self.cerrado:
                return
            t = min(1.0, (time.monotonic() - t0) / self.DURACION)
            e = 1 - (1 - t) ** 3   # frena al llegar
            entrante.frame.place_configure(x=x_ent(e))
            saliente.frame.place_configure(x=x_sal(e))
            if t < 1.0:
                self.root.after(self.PASO_MS, paso)
            else:
                entrante.frame.place_configure(x=0)
                self.animando = False
                fin()

        paso()

    def terminar(self, resultado=None):
        if self.cerrado:
            return
        self.resultado = resultado
        self.cerrado = True
        try:
            self.root.destroy()
        except Exception:
            pass

    def ejecutar(self):
        self.root.mainloop()
        return self.resultado


class DialogoTexto:
    """Cuadro para escribir un texto (IP, numero): un panel encima de toda la ventana (no una ventana
    aparte, que en Modo Juego puede quedar oculta). Teclado/tactil como el Entry de antes; con el
    mando, A acepta y B cancela (lo enruta App mientras esta abierto)."""

    def __init__(self, app, titulo, actual, al_aceptar):
        self.app = app
        self.abierto = True
        self.al_aceptar = al_aceptar
        esc = app.esc
        self.frame = tk.Frame(app.root, bg=FONDO)
        self.frame.place(x=0, y=0, relwidth=1, relheight=1)
        self.frame.lift()
        panel = tk.Frame(self.frame, bg=PANEL, padx=esc.px(40), pady=esc.px(30))
        panel.place(relx=0.5, rely=0.32, anchor="center")
        tk.Label(panel, text=titulo, font=esc.fuente(18), bg=PANEL, fg=TENUE).pack(anchor="w")
        self.entry = tk.Entry(panel, font=esc.fuente(28), width=20, justify="center",
                              bg=FONDO, fg=TEXTO, insertbackground=TEXTO, relief="flat",
                              highlightthickness=3, highlightbackground=TENUE, highlightcolor=BLANCO)
        self.entry.insert(0, actual)
        self.entry.pack(pady=esc.px(16), ipady=esc.px(8))
        botones = tk.Frame(panel, bg=PANEL)
        botones.pack()
        for texto, color, cmd in (("Cancelar (B)", GRIS, self.cancelar), ("Aceptar (A)", VERDE, self.aceptar)):
            tk.Button(botones, text=texto, font=esc.fuente(18, True), bg=color, fg=BLANCO,
                      activebackground=color, activeforeground=BLANCO, relief="flat", bd=0,
                      padx=esc.px(26), pady=esc.px(10), command=cmd).pack(side="left", padx=esc.px(10))
        self.entry.bind("<Return>", lambda e: (self.aceptar(), "break")[1])
        self.entry.bind("<Escape>", lambda e: (self.cancelar(), "break")[1])
        app.modal = self
        self.entry.focus_force()
        self.entry.select_range(0, "end")

    def aceptar(self):
        if not self.abierto:
            return
        valor = self.entry.get().strip()
        self.cerrar()
        self.al_aceptar(valor)

    def cancelar(self):
        if self.abierto:
            self.cerrar()

    def cerrar(self):
        self.abierto = False
        if self.app.modal is self:
            self.app.modal = None
        try:
            self.frame.destroy()
        except Exception:
            pass

    def tecla(self, nombre):
        """Botones del mando mientras el cuadro esta abierto."""
        if nombre == "A":
            self.aceptar()
        elif nombre == "B":
            self.cancelar()


LEDS = [
    ("#d4b106", "Amarillo", "PS3", "#1b1b1b", "ps3"),
    ("#2d6cdf", "Azul", "PS2 / OPL", BLANCO, "ps2"),
    ("#8e5fd6", "Morado", "Xbox 360", BLANCO, "xbox360"),
    ("#2fa84f", "Verde", "Xbox clásico", BLANCO, "xboxclasico"),
]


class PantallaInfo(Pantalla):
    """Colores del LED del ESP32-S3 (selector de modo)."""

    def __init__(self, app):
        super().__init__(app)
        esc, iconos = app.esc, app.iconos
        marco = tk.Frame(self.frame, bg=FONDO, padx=esc.px(24), pady=esc.px(16))
        marco.pack(fill="both", expand=True)
        cab, _ = cabecera(marco, esc, "Selector de modo del ESP32-S3")
        cab.pack(fill="x")
        tk.Label(marco, text="Con la placa ya encendida (nunca al conectarla o resetearla), mantén BOOT ~1.5 s. "
                             "El LED cicla de color cada ~0.7 s; suelta el botón en el color que corresponda.",
                 font=esc.fuente(15), bg=FONDO, fg=TENUE, justify="left",
                 wraplength=esc.px(1180)).pack(anchor="w", pady=(esc.px(6), esc.px(10)))
        f = fila(marco, esc)
        tiles = [Mosaico(f, esc, iconos, icono, nombre, consola, color, color_texto=ct,
                         tam_titulo=32, tam_detalle=18, interactivo=False)
                 for color, nombre, consola, ct, icono in LEDS]
        disponer(f, tiles, esc)
        tk.Label(marco, text="El modo elegido queda guardado en la placa hasta que se cambie a mano.",
                 font=esc.fuente(14), bg=FONDO, fg=TENUE).pack(anchor="w", pady=(esc.px(6), esc.px(4)))
        pie = fila(marco, esc, expandir=False)
        volver = Mosaico(pie, esc, iconos, "back", "Volver", "B o Escape", GRIS, on_a=app.volver,
                         tam_titulo=22, tam_detalle=13, tam_icono=40, horizontal=True, alto=esc.px(84))
        disponer(pie, [volver], esc)
        self.nav = Navegador([[volver]])

    def tecla(self, nombre):
        if nombre in ("B", "A"):
            self.app.volver()
