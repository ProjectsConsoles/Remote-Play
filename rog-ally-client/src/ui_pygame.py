#!/usr/bin/env python3
"""Kit visual (pygame) de los menus de la Ally: el mismo estilo de "mosaicos" que el cliente Android
y la Deck (ver deck-client/ui_mosaicos.py, que hace lo mismo con tkinter).

Por que pygame y no tkinter: ver la nota al inicio de main_client.py (el Python "embeddable" con el
que se compila el .exe no trae Tcl/Tk).

Piezas:
    Escala        tamanos relativos a la pantalla (800 px de alto = escala 1.0)
    Iconos        PNG blancos con transparencia (carpeta iconos/, los mismos de la Deck y Android)
    Mosaico       tarjeta redondeada con icono, titulo y descripcion; el foco la agranda y le pone un
                  borde blanco. Bordes suavizados (se dibujan al triple y se reducen) y con cache
    Navegador     foco por fila/columna entre mosaicos (cruceta), activar con A, tocar con el dedo
    DialogoTexto  cuadro para escribir un texto (IP, numero) encima de la pantalla
    Pantalla      base de cada pantalla
    App           pila de pantallas con transicion deslizante (abrir: de derecha a izquierda; volver:
                  de izquierda a derecha) y despacho de mando/teclado/toque a la pantalla activa

TODO corre en el hilo principal (SDL en Windows no actualiza el mando fuera de el), igual que el resto
del cliente. El mando lo lee un `lector` que da main_client.py (con `nuevos()` y `evento(ev)`).
"""

import logging
import os
import sys
import time

import pygame

log = logging.getLogger("ps3rp")

FONDO = (18, 22, 28)
PANEL = (30, 37, 46)
TEXTO = (233, 238, 243)
TENUE = (147, 161, 176)
OK = (61, 220, 132)
AVISO = (255, 183, 77)
ERROR = (255, 107, 107)

AZUL = (45, 108, 223)
VERDE = (63, 143, 74)
MORADO = (142, 95, 214)
NARANJA = (192, 125, 47)
GRIS = (42, 52, 65)
ROJO = (176, 58, 58)
ROJO_OSCURO = (122, 46, 46)
NARANJA_OSCURO = (160, 74, 45)
BLANCO = (255, 255, 255)


def mezclar(c1, c2, f):
    """Mezcla dos colores RGB: f=0 -> c1, f=1 -> c2."""
    return tuple(round(a + (b - a) * f) for a, b in zip(c1[:3], c2[:3]))


def carpeta_iconos():
    """La carpeta iconos/: dentro del .exe (PyInstaller, _MEIPASS), junto al .exe, o al lado de src/."""
    aqui = os.path.dirname(os.path.abspath(__file__))
    base_exe = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else aqui
    candidatos = []
    if getattr(sys, "_MEIPASS", None):
        candidatos.append(os.path.join(sys._MEIPASS, "iconos"))
    candidatos += [os.path.join(base_exe, "iconos"), os.path.join(os.path.dirname(aqui), "iconos")]
    for c in candidatos:
        if os.path.isdir(c):
            return c
    return None


class Escala:
    def __init__(self, alto):
        self.f = max(0.7, min(1.8, alto / 800.0))
        self._fuentes = {}

    def px(self, n):
        return max(1, round(n * self.f))

    def fuente(self, tam, negrita=False):
        clave = (tam, negrita)
        if clave not in self._fuentes:
            try:
                self._fuentes[clave] = pygame.font.SysFont("segoeui", self.px(tam), bold=negrita)
            except Exception:
                self._fuentes[clave] = pygame.font.Font(None, self.px(tam))
        return self._fuentes[clave]


class Iconos:
    def __init__(self):
        self.dir = carpeta_iconos()
        self._cache = {}

    def get(self, nombre, lado):
        if not nombre or not self.dir:
            return None
        clave = (nombre, lado)
        if clave not in self._cache:
            disco = 72 if lado >= 56 else 40
            try:
                img = pygame.image.load(os.path.join(self.dir, f"{nombre}_{disco}.png")).convert_alpha()
                if img.get_width() != lado:
                    img = pygame.transform.smoothscale(img, (lado, lado))
                self._cache[clave] = img
            except Exception:
                self._cache[clave] = None  # sin icono, pero el mosaico se dibuja igual
        return self._cache[clave]


# --- formas suavizadas (cache) ----------------------------------------------------------------------
_formas = {}


def _forma(w, h, r, grosor=0):
    """Superficie blanca con alfa: rectangulo redondeado relleno (grosor=0) o solo su anillo."""
    clave = (w, h, r, grosor)
    if clave not in _formas:
        k = 3
        grande = pygame.Surface((w * k, h * k), pygame.SRCALPHA)
        pygame.draw.rect(grande, (255, 255, 255, 255), grande.get_rect(),
                         width=grosor * k if grosor else 0, border_radius=r * k)
        _formas[clave] = pygame.transform.smoothscale(grande, (w, h))
    return _formas[clave]


def _relleno(w, h, r, color, foco, grosor):
    """Mosaico: degradado vertical (un poco mas claro arriba) recortado a esquinas redondas; con foco, anillo blanco."""
    clave = ("relleno", w, h, r, color, foco, grosor)
    if clave not in _formas:
        s = pygame.Surface((w, h), pygame.SRCALPHA)
        arriba = mezclar(color, BLANCO, 0.16)
        for y in range(h):
            s.fill(mezclar(arriba, color, y / max(1, h - 1)) + (255,), (0, y, w, 1))
        s.blit(_forma(w, h, r), (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
        if foco:
            s.blit(_forma(w, h, r, grosor), (0, 0))
        _formas[clave] = s
    return _formas[clave]


def envolver(fuente, texto, ancho):
    """Parte `texto` en lineas que quepan en `ancho` pixeles."""
    lineas = []
    for parrafo in str(texto).split("\n"):
        actual = ""
        for palabra in parrafo.split():
            prueba = (actual + " " + palabra).strip()
            if fuente.size(prueba)[0] > ancho and actual:
                lineas.append(actual)
                actual = palabra
            else:
                actual = prueba
        lineas.append(actual)
    return lineas


def texto_en(surf, fuente, txt, color, x, y, anclaje="topleft"):
    img = fuente.render(txt, True, color)
    r = img.get_rect()
    setattr(r, anclaje, (x, y))
    surf.blit(img, r)
    return r


# --- Mosaico -----------------------------------------------------------------------------------------
class Mosaico:
    """Tarjeta con icono, titulo y descripcion. `horizontal=True`: icono a la izquierda y texto a la
    derecha (botones de abajo)."""

    def __init__(self, esc, iconos, icono, titulo, detalle="", color=AZUL, on_a=None, on_click=None,
                 tam_titulo=24, tam_detalle=13, tam_icono=72, color_texto=BLANCO,
                 interactivo=True, horizontal=False):
        self.esc, self.iconos = esc, iconos
        self.icono, self.titulo, self.detalle, self.color = icono, titulo, detalle, color
        self.on_a, self.on_click = on_a, on_click   # on_click: lo que hace el dedo, si difiere de on_a
        self.tam_titulo, self.tam_detalle, self.tam_icono = tam_titulo, tam_detalle, tam_icono
        self.color_texto = color_texto
        self.interactivo, self.horizontal = interactivo, horizontal
        self.habilitado = True
        self.marcado = False
        self.ayuda = ""
        self.rect = None   # donde se dibujo la ultima vez (para tocarlo)

    def activar(self):
        if self.habilitado and self.on_a:
            self.on_a()

    def tocar(self):
        if not self.habilitado:
            return
        if self.on_click is not None:
            self.on_click()
        else:
            self.activar()

    def dibujar(self, surf, rect, foco=False):
        esc = self.esc
        self.rect = rect
        inflar = esc.px(5) if foco else 0
        r = rect.inflate(2 * inflar, 2 * inflar)
        color = self.color if self.habilitado else mezclar(self.color, FONDO, 0.55)
        surf.blit(_relleno(r.w, r.h, esc.px(18), color, foco, esc.px(4)), r.topleft)

        pad = esc.px(18)
        color_txt = self.color_texto if self.habilitado else mezclar(self.color_texto, color, 0.4)
        color_det = mezclar(color_txt, color, 0.12)
        f_t = esc.fuente(self.tam_titulo, True)
        f_d = esc.fuente(self.tam_detalle)
        lado = esc.px(self.tam_icono)
        # tarjetas bajitas: icono mas chico para que todo quepa
        if r.h < esc.px(120) and not self.horizontal:
            lado = min(lado, esc.px(28))
        img = self.iconos.get(self.icono, lado) if self.icono else None

        if self.horizontal:
            x = r.x + pad
            if img:
                surf.blit(img, (x, r.centery - img.get_height() // 2))
                x += img.get_width() + esc.px(14)
            ancho = max(40, r.right - pad - x)
            lineas_t = envolver(f_t, self.titulo, ancho)
            lineas_d = envolver(f_d, self.detalle, ancho) if self.detalle else []
            alto_t, alto_d = f_t.get_linesize(), f_d.get_linesize()
            total = len(lineas_t) * alto_t + (esc.px(2) + len(lineas_d) * alto_d if lineas_d else 0)
            y = r.centery - total // 2
            for ln in lineas_t:
                texto_en(surf, f_t, ln, color_txt, x, y)
                y += alto_t
            y += esc.px(2)
            for ln in lineas_d:
                texto_en(surf, f_d, ln, color_det, x, y)
                y += alto_d
        else:
            ancho = max(40, r.w - 2 * pad)
            lineas_t = envolver(f_t, self.titulo, ancho)
            lineas_d = envolver(f_d, self.detalle, ancho) if self.detalle else []
            alto_t, alto_d = f_t.get_linesize(), f_d.get_linesize()
            disponible = r.h - esc.px(14)

            def altura(con_icono, n_det):
                a = len(lineas_t) * alto_t
                if n_det:
                    a += esc.px(3) + n_det * alto_d
                if con_icono and img:
                    a += img.get_height() + esc.px(8)
                return a

            n_det = len(lineas_d)
            while n_det > 0 and altura(True, n_det) > disponible:
                n_det -= 1      # si no cabe, se recorta la descripcion antes que el titulo
            con_icono = True
            if altura(True, n_det) > disponible:
                con_icono = False
            total = altura(con_icono, n_det)
            y = r.y + max(esc.px(6), (r.h - total) // 2)
            if con_icono and img:
                surf.blit(img, (r.x + pad, y))
                y += img.get_height() + esc.px(8)
            for ln in lineas_t:
                texto_en(surf, f_t, ln, color_txt, r.x + pad, y)
                y += alto_t
            if n_det:
                y += esc.px(3)
                for ln in lineas_d[:n_det]:
                    texto_en(surf, f_d, ln, color_det, r.x + pad, y)
                    y += alto_d

        if self.marcado:
            rad = esc.px(15)
            cx, cy = r.right - pad + esc.px(4) - rad, r.y + pad - esc.px(4) + rad
            pygame.draw.circle(surf, BLANCO, (cx, cy), rad)
            pygame.draw.lines(surf, color, False,
                              [(cx - rad // 2, cy), (cx - rad // 6, cy + rad // 3), (cx + rad // 2, cy - rad // 3)],
                              max(2, esc.px(3)))


# --- piezas sueltas -----------------------------------------------------------------------------------
def dibujar_cabecera(surf, esc, x, y, ancho, titulo, derecha=""):
    """Titulo grande a la izquierda y una nota tenue a la derecha. Devuelve el alto usado."""
    f = esc.fuente(34, True)
    r = texto_en(surf, f, titulo, TEXTO, x, y)
    if derecha:
        fd = esc.fuente(14)
        texto_en(surf, fd, derecha, TENUE, x + ancho, r.bottom - esc.px(6), "bottomright")
    return r.h


def alto_tira(esc, texto, ancho, alto_min=54):
    f = esc.fuente(15)
    lineas = envolver(f, texto, ancho - esc.px(70))
    return max(esc.px(alto_min), len(lineas) * f.get_linesize() + esc.px(22))


def dibujar_tira(surf, esc, rect, color, texto):
    """Tira redondeada con un punto de color y un mensaje (puede tener varias lineas)."""
    fondo = pygame.Surface(rect.size, pygame.SRCALPHA)
    fondo.fill(PANEL + (255,))
    fondo.blit(_forma(rect.w, rect.h, esc.px(14)), (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    surf.blit(fondo, rect.topleft)
    pygame.draw.circle(surf, color, (rect.x + esc.px(24), rect.centery), esc.px(7))
    f = esc.fuente(15)
    lineas = envolver(f, texto, rect.w - esc.px(70))
    y = rect.centery - len(lineas) * f.get_linesize() // 2
    for ln in lineas:
        texto_en(surf, f, ln, TEXTO, rect.x + esc.px(46), y)
        y += f.get_linesize()


def columnas(rect, n, hueco):
    """Parte `rect` en `n` columnas iguales."""
    ancho = (rect.w - hueco * (n - 1)) // n
    return [pygame.Rect(rect.x + i * (ancho + hueco), rect.y, ancho, rect.h) for i in range(n)]


class Navegador:
    """Foco por fila/columna. `filas` = lista de listas de Mosaico (en el orden visual)."""

    def __init__(self, filas, al_cambiar=None, recordar=False):
        self.filas = [f for f in filas if f]
        self.f = self.c = 0
        self.al_cambiar = al_cambiar
        # recordar=True: al volver a una fila por arriba/abajo se cae en la columna donde se estuvo.
        self.recordar = recordar
        self.memoria = {}
        self.marcar()

    def actual(self):
        return self.filas[self.f][self.c]

    def es_foco(self, mosaico):
        return mosaico is self.actual()

    def ir_a(self, mosaico):
        for fi, fila in enumerate(self.filas):
            if mosaico in fila:
                self.f, self.c = fi, fila.index(mosaico)
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
        if self.al_cambiar:
            self.al_cambiar(self.actual())

    def activar(self):
        self.actual().activar()

    def mosaico_en(self, pos):
        for fila in self.filas:
            for t in fila:
                if t.rect is not None and t.rect.collidepoint(pos):
                    return t
        return None


class Pantalla:
    """Base de una pantalla. Las subclases definen `dibujar(surf)` (arma su propio layout y llena
    `self.nav` con sus mosaicos), `boton(nombre)` con los nombres del mando ("DPAD_LEFT", "A", "B",
    "X", "Y", "L1", "R1"...) y, si quieren, `al_mostrar()`."""

    def __init__(self, app):
        self.app = app
        self.esc = app.esc
        self.iconos = app.iconos
        self.nav = None

    def dibujar(self, surf):
        surf.fill(FONDO)

    def boton(self, nombre):
        pass

    def click(self, pos):
        if self.nav is not None:
            t = self.nav.mosaico_en(pos)
            if t is not None and t.interactivo:
                self.nav.ir_a(t)
                t.tocar()

    def evento(self, ev):
        pass

    def al_mostrar(self):
        pass


class DialogoTexto:
    """Cuadro para escribir un texto (IP, numero) encima de la pantalla. Teclado fisico o dedo sobre
    los botones; con el mando, A acepta y B cancela. `filtro`: "ip" | "num" | "texto"."""

    def __init__(self, app, titulo, actual, filtro, al_aceptar):
        self.app, self.titulo, self.filtro, self.al_aceptar = app, titulo, filtro, al_aceptar
        self.texto = str(actual)
        self.abierto = True
        self._rects = {}
        app.modal = self   # mientras esta abierto, recibe el mando/teclado/toque en lugar de la pantalla
        pygame.key.start_text_input()

    def _permitido(self, s):
        if self.filtro == "ip":
            return all(c in "0123456789." for c in s)
        if self.filtro == "num":
            return all(c.isdigit() or (c == "-" and self.texto == "") for c in s)
        return True

    def aceptar(self):
        if not self.abierto:
            return
        valor = self.texto.strip()
        self.cerrar()
        self.al_aceptar(valor)

    def cancelar(self):
        if self.abierto:
            self.cerrar()

    def cerrar(self):
        self.abierto = False
        pygame.key.stop_text_input()
        if self.app.modal is self:
            self.app.modal = None

    def boton(self, nombre):
        if nombre == "A":
            self.aceptar()
        elif nombre == "B":
            self.cancelar()

    def evento(self, ev):
        if ev.type == pygame.TEXTINPUT:
            if self._permitido(ev.text):
                self.texto += ev.text
        elif ev.type == pygame.KEYDOWN:
            if ev.key == pygame.K_BACKSPACE:
                self.texto = self.texto[:-1]
            elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self.aceptar()
            elif ev.key == pygame.K_ESCAPE:
                self.cancelar()
        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            if self._rects.get("aceptar") and self._rects["aceptar"].collidepoint(ev.pos):
                self.aceptar()
            elif self._rects.get("cancelar") and self._rects["cancelar"].collidepoint(ev.pos):
                self.cancelar()

    def dibujar(self, surf):
        esc = self.app.esc
        w, h = surf.get_size()
        velo = pygame.Surface((w, h))
        velo.set_alpha(190)
        velo.fill((0, 0, 0))
        surf.blit(velo, (0, 0))
        ancho = min(esc.px(760), w - esc.px(60))
        alto = esc.px(250)
        panel = pygame.Rect((w - ancho) // 2, max(esc.px(30), h // 6), ancho, alto)
        surf.blit(_relleno(panel.w, panel.h, esc.px(20), PANEL, False, 0), panel.topleft)
        pad = esc.px(32)
        texto_en(surf, esc.fuente(18), self.titulo, TENUE, panel.x + pad, panel.y + esc.px(22))
        campo = pygame.Rect(panel.x + pad, panel.y + esc.px(62), panel.w - 2 * pad, esc.px(60))
        surf.blit(_relleno(campo.w, campo.h, esc.px(12), FONDO, True, esc.px(3)), campo.topleft)
        mostrar = self.texto + ("|" if int(time.monotonic() * 2) % 2 == 0 else " ")
        texto_en(surf, esc.fuente(28), mostrar, TEXTO, campo.centerx, campo.centery, "center")
        bw, bh = esc.px(210), esc.px(54)
        for clave, etiqueta, color, x in (
                ("cancelar", "Cancelar (B)", GRIS, panel.centerx - bw - esc.px(10)),
                ("aceptar", "Aceptar (A)", VERDE, panel.centerx + esc.px(10))):
            r = pygame.Rect(x, panel.bottom - bh - esc.px(26), bw, bh)
            surf.blit(_relleno(r.w, r.h, esc.px(12), color, False, 0), r.topleft)
            texto_en(surf, esc.fuente(18, True), etiqueta, BLANCO, r.centerx, r.centery, "center")
            self._rects[clave] = r


TECLAS = {
    pygame.K_LEFT: "DPAD_LEFT", pygame.K_RIGHT: "DPAD_RIGHT", pygame.K_UP: "DPAD_UP",
    pygame.K_DOWN: "DPAD_DOWN", pygame.K_RETURN: "A", pygame.K_KP_ENTER: "A", pygame.K_SPACE: "A",
    pygame.K_ESCAPE: "B", pygame.K_y: "Y", pygame.K_x: "X",
}


class App:
    """Ventana unica con una pila de pantallas. Abrir una la desliza de derecha a izquierda; volver la
    desliza de izquierda a derecha. Lee mando (via `lector`), teclado y toque en UN solo lugar."""

    DURACION = 0.32    # segundos
    PARALAJE = 0.28    # cuanto se corre la pantalla de abajo (fraccion del ancho)

    def __init__(self, screen, lector):
        self.screen = screen
        self.esc = Escala(screen.get_height())
        self.iconos = Iconos()
        self.lector = lector
        self.pila = []
        self.modal = None
        self.resultado = None
        self.cerrado = False
        self.reloj = pygame.time.Clock()

    # --- pila ------------------------------------------------------------------------------------
    def abrir_inicial(self, pantalla):
        self.pila.append(pantalla)
        pantalla.al_mostrar()

    def abrir(self, pantalla):
        if self.cerrado or not self.pila:
            return
        actual = self.pila[-1]
        self.pila.append(pantalla)
        self._animar(pantalla, actual, +1)
        pantalla.al_mostrar()

    def volver(self):
        if self.cerrado:
            return
        if len(self.pila) <= 1:
            self.terminar(None)
            return
        actual = self.pila.pop()
        anterior = self.pila[-1]
        self._animar(anterior, actual, -1)
        anterior.al_mostrar()

    def terminar(self, resultado=None):
        self.resultado = resultado
        self.cerrado = True

    def _animar(self, entrante, saliente, direccion):
        w, h = self.screen.get_size()
        a = pygame.Surface((w, h))
        b = pygame.Surface((w, h))
        saliente.dibujar(a)
        entrante.dibujar(b)
        corr = int(w * self.PARALAJE)
        velo = pygame.Surface((w, h))
        velo.fill((0, 0, 0))
        t0 = time.monotonic()
        while True:
            t = min(1.0, (time.monotonic() - t0) / self.DURACION)
            e = 1 - (1 - t) ** 3   # frena al llegar
            if direccion > 0:
                # abrir: la de abajo se corre un poco a la izquierda y se oscurece; la nueva entra por la derecha
                self.screen.blit(a, (-int(corr * e), 0))
                velo.set_alpha(int(110 * e))
                self.screen.blit(velo, (0, 0))
                self.screen.blit(b, (int(w * (1 - e)), 0))
            else:
                # volver: la actual sale hacia la derecha; la de abajo regresa desde la izquierda aclarandose
                self.screen.blit(b, (-int(corr * (1 - e)), 0))
                velo.set_alpha(int(110 * (1 - e)))
                self.screen.blit(velo, (0, 0))
                self.screen.blit(a, (int(w * e), 0))
            pygame.display.flip()
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    self.terminar(None)
            self.lector.nuevos()   # mantiene la linea base al dia: lo apretado durante la animacion no cuenta
            if t >= 1.0 or self.cerrado:
                break
            self.reloj.tick(60)

    # --- bucle ------------------------------------------------------------------------------------
    def _despachar_boton(self, nombre):
        try:
            if self.modal is not None and self.modal.abierto:
                self.modal.boton(nombre)
            elif self.pila:
                self.pila[-1].boton(nombre)
        except Exception:
            log.exception("error en la pantalla al manejar el boton %s", nombre)

    def _despachar_evento(self, ev):
        try:
            if ev.type == pygame.QUIT:
                self.terminar(None)
                return
            if self.modal is not None and self.modal.abierto:
                self.modal.evento(ev)
                return
            if ev.type == pygame.KEYDOWN:
                nombre = TECLAS.get(ev.key)
                if nombre:
                    self._despachar_boton(nombre)
            elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1 and self.pila:
                self.pila[-1].click(ev.pos)
            elif self.pila:
                self.pila[-1].evento(ev)
        except Exception:
            log.exception("error en la pantalla al manejar un evento")

    def redibujar(self):
        """Dibuja YA la pantalla actual (para mostrar un mensaje antes de una operacion lenta de red)."""
        if self.pila:
            self.pila[-1].dibujar(self.screen)
        if self.modal is not None and self.modal.abierto:
            self.modal.dibujar(self.screen)
        pygame.display.flip()

    def ejecutar(self):
        while not self.cerrado:
            for ev in pygame.event.get():
                self.lector.evento(ev)
                self._despachar_evento(ev)
                if self.cerrado:
                    break
            if self.cerrado:
                break
            for nombre in sorted(self.lector.nuevos()):
                self._despachar_boton(nombre)
                if self.cerrado:
                    break
            if self.cerrado:
                break
            self.redibujar()
            self.reloj.tick(30)
        return self.resultado
