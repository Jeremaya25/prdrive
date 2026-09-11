#!/usr/bin/env python3
"""
tk.py — La interfaz gráfica (Tkinter).

Es la que se usa cuando se llega por doble clic en `runsync.pyw`, es decir sin
consola detrás: por eso aquí no basta con elegir, hace falta además poder
enseñar la salida de la sincronización y preguntar sí/no, cosas que en el modo
consola hace la propia terminal.

El aspecto entero sale de `ui/theme.py` y los iconos de `ui/icons.py`: aquí no
se escribe ningún color a mano. Cada ventana llama a `theme.apply()` nada más
nacer, porque los estilos de ttk son globales dentro de un intérprete de Tk y a
lo largo de una sesión se abre más de uno.

`import tkinter` va dentro de cada función a propósito, no arriba: importar este
módulo no puede fallar en un equipo sin tkinter, porque el fallo tiene que
saltar cuando se intenta abrir la ventana, que es cuando `ui.start()` puede
recogerlo y caer al menú de consola.
"""

from __future__ import annotations

import queue
import subprocess
import sys
import threading
import time

from common import APP_NAME, conflicts, model, results, update
from common.model import Config

from . import (Choice, abrir, cuando, cuando_sello, icons, manual_args,
               pair_status_notes, pair_times, prefs, theme)

TITLE = APP_NAME          # el nombre de la ventana sale de common/


def corto(texto: str, maximo: int = 30) -> str:
    """Una ruta recortada por delante, que es por donde sobra.

    En el dispositivo esto no hace nada —`DEVICE_ROOT` es `F:\\`—, pero montado en un punto
    con nombre largo (`/media/quien/PRDRIVE`) o corriendo desde el repositorio,
    una ruta entera estira la ventana hasta salirse de la pantalla."""
    return texto if len(texto) <= maximo else "…" + texto[-(maximo - 1):]


class TkFrontend:
    """El frontend gráfico. Ver el protocolo `ui.Frontend`."""

    def ask(self, config: Config, startup_msg: str | None) -> Choice | None:
        return main_window(config, startup_msg)

    def approve_resync(self, pending: list[str]) -> bool:
        root = root_oculto()
        try:
            return preguntar_resync(root, pending)
        finally:
            root.destroy()

    def info(self, msg: str) -> None:
        from tkinter import messagebox
        root = root_oculto()
        messagebox.showinfo(TITLE, msg)
        root.destroy()

    def run_sync(self, title: str, args: list[str]) -> int:
        rc = output_window(title, orden_sync(args), subtitulo=subtitulo_sync(args))
        return rc if rc is not None else 1


def orden_sync(args: list[str]) -> list[str]:
    return [sys.executable, str(model.SYNC_PY), *args]


def subtitulo_sync(args: list[str]) -> str:
    """El subtítulo de la ventana son las parejas que se van a tocar: lo que se
    pasa son sus nombres y, detrás, las opciones que empiezan por '-'."""
    return ", ".join(a for a in args if not a.startswith("-"))


def preguntar_resync(parent, pending: list[str]) -> bool:
    """El sí/no del --resync, colgado de la ventana que pregunta."""
    from tkinter import messagebox
    return bool(messagebox.askyesno(
        TITLE,
        "Estas parejas requieren --resync (primera vez, baseline perdido o "
        "filtros cambiados):\n\n  " + "\n  ".join(pending) +
        "\n\nEl resync compara ambos lados y fija la referencia; no borra por "
        "diferencias.\n¿Ejecutarlo ahora? (si no, esas parejas se saltarán)",
        parent=parent))


def root_oculto():
    """Un Tk invisible en mitad de la pantalla, del que colgar un messagebox suelto.

    Los messagebox se colocan respecto a su ventana padre, y un Tk recién creado
    está en la esquina superior izquierda: sin mover el padre, el aviso sale
    arrinconado aunque no se vea la ventana de la que cuelga."""
    import tkinter as tk
    theme.nitidez()
    root = tk.Tk()
    root.withdraw()
    theme.apply(root)
    icons.poner_icono(root)
    root.geometry(f"+{root.winfo_screenwidth() // 2}+{root.winfo_screenheight() // 2}")
    return root


def centrar(win, parent=None) -> None:
    """Coloca una ventana en el centro: de su padre si lo hay, si no de la pantalla.

    El `update_idletasks()` no es opcional: hasta que Tk no ha resuelto la
    disposición, `winfo_width()` vale 1 y el centro saldría a ojo."""
    win.update_idletasks()
    ancho = max(win.winfo_width(), win.winfo_reqwidth())
    alto = max(win.winfo_height(), win.winfo_reqheight())
    pantalla_x, pantalla_y = win.winfo_screenwidth(), win.winfo_screenheight()

    if parent is not None and parent.winfo_ismapped():
        x = parent.winfo_rootx() + (parent.winfo_width() - ancho) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - alto) // 2
        # Un diálogo puede ser bastante mayor que su padre —la pantalla de
        # parejas lo es—, así que centrado sobre un padre pegado a un borde se
        # saldría. Solo se recoloca si el padre está en la pantalla principal:
        # con dos monitores las coordenadas pueden ser negativas, y ahí
        # "corregir" sería arrastrar el diálogo a la otra pantalla.
        if 0 <= parent.winfo_rootx() < pantalla_x:
            x = max(0, min(x, pantalla_x - ancho))
            y = max(0, min(y, pantalla_y - alto))
    else:
        x = max(0, (pantalla_x - ancho) // 2)
        # Un pelín por encima del centro geométrico, que es donde el ojo lo
        # espera y deja sitio por abajo para los diálogos hijos.
        y = max(0, (pantalla_y - alto) // 2 - alto // 8)
    win.geometry(f"+{x}+{y}")


# ---------------------------------------------------------------------------
# Que quepa en la pantalla
# ---------------------------------------------------------------------------

def pantalla_util(win) -> tuple[int, int]:
    """Lo que de verdad le queda a una ventana: la pantalla menos su marco y la
    barra de tareas.

    Los márgenes van en medidas del diseño escaladas (`icons.px`) porque el
    adorno del sistema crece con la densidad igual que el texto: una barra de
    tareas ocupa más píxeles en una pantalla al 150 % que en una al 100 %."""
    return (max(480, win.winfo_screenwidth() - icons.px(win, 60)),
            max(360, win.winfo_screenheight() - icons.px(win, 110)))


class Visor:
    """Un recuadro con el contenido dentro, que se desplaza cuando no cabe.

    Existe porque una ventana no puede ser más alta que la pantalla y el
    contenido de estas sí: los tamaños de letra van en puntos, así que en una
    pantalla densa —o con el zoom del sistema al 150 %— todo crece, mientras que
    los recuadros de tamaño fijo no. Eso se veía como un asistente al que le
    faltaba el último campo, sin nada que lo avisara: el paso 1 pide 486 px de
    alto en una pantalla normal y el hueco medía 430.

    `interior` es donde se dibuja. El recuadro se ajusta cuando la ventana ya
    está montada (`encajar`/`crecer`) y no antes, porque hasta entonces no se
    sabe cuánto ocupa el resto —cabecera, pie, márgenes—, y descontar una cifra
    fija sería volver a suponer el tamaño de las letras.

    Las barras tienen su hueco reservado siempre, aparezcan o no: si lo ganaran
    y lo perdieran, la ventana cambiaría de ancho al pasar de un paso a otro."""

    def __init__(self, padre, ancho: int | None = None, alto: int | None = None):
        """`ancho`/`alto` son el tamaño de partida y el mínimo, no un tope: el
        recuadro nunca es más pequeño que eso, y crece con el contenido hasta
        donde llegue la pantalla."""
        import tkinter as tk
        from tkinter import ttk

        self.base = (ancho, alto)
        self.marco = ttk.Frame(padre)
        self.lienzo = tk.Canvas(self.marco, background=theme.PAPEL,
                                highlightthickness=0, borderwidth=0,
                                width=ancho or 200, height=alto or 150)
        self.vertical = ttk.Scrollbar(self.marco, orient="vertical",
                                      command=self.lienzo.yview)
        self.horizontal = ttk.Scrollbar(self.marco, orient="horizontal",
                                        command=self.lienzo.xview)
        self.lienzo.configure(yscrollcommand=self.vertical.set,
                              xscrollcommand=self.horizontal.set)
        self.lienzo.grid(row=0, column=0, sticky="nsew")
        self.marco.columnconfigure(0, weight=1)
        self.marco.rowconfigure(0, weight=1)
        self.marco.columnconfigure(1, minsize=self.vertical.winfo_reqwidth())
        self.marco.rowconfigure(1, minsize=self.horizontal.winfo_reqheight())

        self.interior = ttk.Frame(self.lienzo)
        self._dentro = self.lienzo.create_window((0, 0), window=self.interior,
                                                 anchor="nw")
        self._puesto = (0, 0)          # lo último que se le dijo al item
        self.interior.bind("<Configure>", lambda _e: self._revisar())
        self.lienzo.bind("<Configure>", lambda _e: self._revisar())
        self.lienzo.bind("<Enter>", lambda _e: self._rueda(True))
        self.lienzo.bind("<Leave>", lambda _e: self._rueda(False))
        self.lienzo.bind("<Destroy>", lambda _e: self._rueda(False))

    # --- tamaño -------------------------------------------------------------

    def _medida(self) -> tuple[int, int]:
        """Lo que mide el recuadro ahora mismo."""
        return (int(self.lienzo.cget("width")), int(self.lienzo.cget("height")))

    def _natural(self) -> tuple[int, int]:
        """Lo que pediría el contenido si nadie lo recortara, nunca por debajo
        del tamaño de partida: `base` es un mínimo, no un tope."""
        self.interior.update_idletasks()
        base_x, base_y = self.base
        return (max(base_x or 0, self.interior.winfo_reqwidth()),
                max(base_y or 0, self.interior.winfo_reqheight()))

    def _tope(self, ventana) -> tuple[int, int]:
        """Lo más grande que puede ser el recuadro sin que la ventana se salga.

        Se mide el resto de la ventana en vez de descontar una cifra fija: la
        cabecera y el pie ocupan lo que ocupen sus fuentes."""
        ventana.update_idletasks()
        resto_x = max(0, ventana.winfo_reqwidth() - self.lienzo.winfo_reqwidth())
        resto_y = max(0, ventana.winfo_reqheight() - self.lienzo.winfo_reqheight())
        util_x, util_y = pantalla_util(ventana)
        return (max(320, util_x - resto_x), max(240, util_y - resto_y))

    def _fijar(self, ancho: int, alto: int) -> bool:
        """Devuelve si ha cambiado de tamaño.

        `_revisar()` se llama aunque no cambie: cambiar de paso cambia el
        contenido sin cambiar el hueco, y entonces la barra que hace falta (o la
        que sobra) es distinta. Dejarlo colgando del `<Configure>` significaba
        que hasta el siguiente reposo del bucle de eventos la barra no estaba, y
        el hueco parecía completo cuando no lo era."""
        cambia = (ancho, alto) != self._medida()
        if cambia:
            self.lienzo.configure(width=ancho, height=alto)
        self._revisar()
        return cambia

    def encajar(self, ventana=None) -> bool:
        """Deja el recuadro del tamaño del contenido, o del que quepa si no cabe."""
        ventana = ventana or self.marco.winfo_toplevel()
        ancho, alto = self._natural()
        self._fijar(ancho, alto)
        tope_x, tope_y = self._tope(ventana)
        return self._fijar(min(ancho, tope_x), min(alto, tope_y))

    def crecer(self, ventana=None) -> bool:
        """Agranda el recuadro si lo de ahora pide más, y no lo encoge nunca.

        Es lo que necesita un asistente: el hueco tiene que valer para el paso
        más grande, y una ventana que menguara y creciera a cada paso sería un
        baile. Devuelve si ha cambiado de tamaño, que es cuando quien llama
        tiene que volver a colocarla."""
        ventana = ventana or self.marco.winfo_toplevel()
        pide_x, pide_y = self._natural()
        hay_x, hay_y = self._medida()
        tope_x, tope_y = self._tope(ventana)
        return self._fijar(min(max(hay_x, pide_x), tope_x),
                           min(max(hay_y, pide_y), tope_y))

    # --- barras --------------------------------------------------------------

    def _revisar(self) -> None:
        """Enseña cada barra solo si por ese lado sobra contenido.

        El interior se estira hasta llenar el hueco cuando no sobra, para que un
        formulario colocado con `sticky='ew'` siga ocupando todo el ancho; y solo
        se le habla cuando la medida cambia, porque redimensionarlo dispara otro
        `<Configure>` y con él se volvería aquí sin parar."""
        ancho, alto = self._medida()
        ancho = max(ancho, self.lienzo.winfo_width())
        alto = max(alto, self.lienzo.winfo_height())
        pide_x = self.interior.winfo_reqwidth()
        pide_y = self.interior.winfo_reqheight()
        medida = (max(ancho, pide_x), max(alto, pide_y))
        if medida != self._puesto:
            self._puesto = medida
            self.lienzo.itemconfigure(self._dentro, width=medida[0], height=medida[1])
            self.lienzo.configure(scrollregion=(0, 0, medida[0], medida[1]))
        # Puesta o no en la rejilla, no `winfo_ismapped()`: una ventana todavía
        # oculta —y todas nacen ocultas, ver `modal()`— no tiene nada mapeado, y
        # con eso la barra se pondría cada vez y no se quitaría nunca.
        for barra, falta, sitio in (
                (self.vertical, pide_y > alto, dict(row=0, column=1, sticky="ns")),
                (self.horizontal, pide_x > ancho, dict(row=1, column=0, sticky="ew"))):
            puesta = bool(barra.grid_info())
            if falta and not puesta:
                barra.grid(**sitio)
            elif not falta and puesta:
                barra.grid_remove()

    def _rueda(self, activar: bool) -> None:
        eventos = ("<MouseWheel>", "<Button-4>", "<Button-5>")   # Windows / X11
        for evento in eventos:
            if activar:
                self.lienzo.bind_all(evento, self._girar)
            else:
                self.lienzo.unbind_all(evento)

    def _girar(self, evento):
        """La rueda desplaza el recuadro, salvo sobre algo que ya se desplaza
        solo: dentro de la caja de opciones o de una lista, la rueda es suya."""
        if not self.vertical.winfo_ismapped():
            return None
        if evento.widget is not self.lienzo and hasattr(evento.widget, "yview_scroll"):
            return None
        arriba = getattr(evento, "num", 0) == 4 or getattr(evento, "delta", 0) > 0
        self.lienzo.yview_scroll(-1 if arriba else 1, "units")
        return "break"


def cuerpo_visible(ventana, **opciones):
    """El marco donde se dibuja una pantalla, ya dentro de un `Visor`.

    Sustituye al `ttk.Frame(ventana, padding=…)` + `.grid(sticky='nsew')` que
    hacían todos los diálogos. La única diferencia visible es que, cuando la
    pantalla es pequeña, el contenido se desplaza en vez de quedarse fuera. El
    visor queda colgado de la ventana para que `mostrar()` lo encaje al
    enseñarla, sin que cada diálogo tenga que acordarse."""
    from tkinter import ttk
    visor = Visor(ventana)
    visor.marco.grid(row=0, column=0, sticky="nsew")
    ventana.columnconfigure(0, weight=1)
    ventana.rowconfigure(0, weight=1)
    visor.interior.columnconfigure(0, weight=1)
    visor.interior.rowconfigure(0, weight=1)
    marco = ttk.Frame(visor.interior, **opciones)
    marco.grid(row=0, column=0, sticky="nsew")
    ventana.visor = visor
    return marco


def modal(parent, title: str):
    """Un diálogo hijo, todavía OCULTO. Se enseña con `mostrar()`.

    Nace oculto porque hasta que no están puestos todos los widgets no se sabe
    cuánto ocupa, y sin saberlo no se puede centrar. Enseñarlo antes sería verlo
    aparecer en una esquina y pegar el salto al centro."""
    import tkinter as tk
    dlg = tk.Toplevel(parent)
    theme.apply(dlg)
    dlg.title(f"{TITLE} — {title}")
    dlg.configure(background=theme.PAPEL)
    dlg.transient(parent)
    dlg.resizable(False, False)
    dlg.withdraw()
    return dlg


def mostrar(dlg, parent=None) -> None:
    """Centra el diálogo sobre su padre, lo enseña y espera a que se cierre.

    El `grab_set()` va aquí y no en `modal()` porque Tk no deja capturar una
    ventana que no está visible, y por eso `deiconify()` lleva detrás un
    `update_idletasks()`: sin él el mapeo puede seguir pendiente. Si aun así
    fallara, se sigue: un diálogo sin captura es un incordio, pero uno que no se
    abre es un cuelgue."""
    import tkinter as tk
    # Primero encoger el contenido a lo que quepa y solo después centrar: al
    # revés se centraría un tamaño que aún va a cambiar.
    visor = getattr(dlg, "visor", None)
    if visor is not None:
        visor.encajar(dlg)
    centrar(dlg, parent)
    dlg.deiconify()
    dlg.update_idletasks()
    try:
        dlg.grab_set()
    except tk.TclError:
        pass
    dlg.wait_window()


# ---------------------------------------------------------------------------
# Piezas del diseño que aparecen en más de una pantalla
# ---------------------------------------------------------------------------

def cabecera(parent, titulo: str, pista: str = "", ancho: int = 620,
             estilo: str = "Titulo.TLabel"):
    """El título de una pantalla con su frase debajo. Devuelve el marco, para
    poder colgarle a la derecha un chip de estado."""
    from tkinter import ttk
    marco = ttk.Frame(parent)
    marco.columnconfigure(0, weight=1)
    ttk.Label(marco, text=titulo, style=estilo).grid(row=0, column=0, sticky="w")
    if pista:
        ttk.Label(marco, text=pista, style="Pista.TLabel", wraplength=theme.medida(ancho),
                  justify="left").grid(row=1, column=0, sticky="w", pady=(5, 0))
    return marco


def bloque_aviso(parent, texto: str, ancho: int = 560, tipo: str = "Ambar",
                 icono: str = "warn", boton: tuple[str, object] | None = None):
    """El recuadro ámbar (o rojo) con su triángulo: lo que hay que leer dos veces.

    `icono` y `boton` son opcionales porque el mismo recuadro sirve para dos
    cosas distintas: un aviso que solo se lee (el servicio que se ha parado) y
    uno sobre el que se actúa (hay versión nueva, y el botón la instala). Dos
    funciones casi iguales serían dos sitios donde arreglar el mismo color.
    El botón va en `AmbarQuiet.TButton`, que es el único cuyo fondo es el del
    bloque: cualquier otro se recortaría contra el ámbar."""
    from tkinter import ttk
    fondo = theme.AVISO_FONDO if tipo == "Ambar" else theme.PELIGRO_FONDO
    color = theme.AVISO if tipo == "Ambar" else theme.PELIGRO
    caja = ttk.Frame(parent, style=f"{tipo}.TFrame", padding=(11, 9))
    img = icons.get(caja, icono, 16, color, fondo)
    marca = ttk.Label(caja, style=f"{tipo}.TLabel")
    if img is not None:
        marca.configure(image=img)
        marca.image = img
    marca.grid(row=0, column=0, sticky="nw")
    ttk.Label(caja, text=texto, style=f"{tipo}.TLabel", wraplength=theme.medida(ancho),
              justify="left").grid(row=0, column=1, sticky="w", padx=(9, 0))
    caja.columnconfigure(1, weight=1)
    if boton is not None:
        rotulo, accion = boton
        # Solo hay botón hecho para el ámbar; el día que haga falta uno rojo se
        # añade `RojoQuiet.TButton` al tema, no se inventa aquí un color.
        estilo = "AmbarQuiet.TButton" if tipo == "Ambar" else "Quiet.TButton"
        ttk.Button(caja, text=rotulo, style=estilo,
                   command=accion).grid(row=0, column=2, sticky="e", padx=(12, 0))
    return caja


def separador_fila(parent, fila: int, columnas: int, superficie: str = "Card."):
    """La línea fina entre dos filas de una lista dibujada a mano."""
    from tkinter import ttk
    est = "Card.TSeparator" if superficie == "Card." else "TSeparator"
    ttk.Separator(parent, orient="horizontal", style=est).grid(
        row=fila, column=0, columnspan=columnas, sticky="ew")


def working(parent, title: str, funcion, mensaje: str = "") -> tuple[bool, object]:
    """Ejecuta `funcion()` en un hilo aparte y enseña una ventanita mientras.

    Devuelve `(True, resultado)` o `(False, excepción)`.

    Existe porque `output_window` no sirve para todo: hay órdenes que tardan
    minutos y no dicen nada por su salida —crear un contenedor VeraCrypt—, y
    otras cuya línea de órdenes NO se puede enseñar porque lleva la contraseña
    dentro. Lanzarlas en el hilo de Tk congelaría la ventana, así que van a un
    hilo y aquí solo se espera.

    No hay botón de cancelar a propósito: lo que se lanza así no se puede cortar
    a medias sin dejar las cosas peor (un contenedor a medio formatear)."""
    from tkinter import ttk

    dlg = modal(parent, title)
    dlg.protocol("WM_DELETE_WINDOW", lambda: None)   # no se cierra a medias

    marco = ttk.Frame(dlg, padding=(20, 18))
    marco.grid(sticky="nsew")
    ttk.Label(marco, text=mensaje or f"{title}…", wraplength=theme.medida(380),
              justify="left").grid(row=0, column=0, sticky="w")
    barra = ttk.Progressbar(marco, mode="indeterminate",
                            length=theme.medida(380))
    barra.grid(row=1, column=0, pady=(14, 0), sticky="ew")
    barra.start(12)

    resultado: dict = {"ok": False, "valor": None, "hecho": False}

    def trabajar() -> None:
        try:
            resultado["valor"] = funcion()
            resultado["ok"] = True
        except Exception as e:                       # se le enseña a quien llama
            resultado["valor"] = e
        finally:
            resultado["hecho"] = True

    threading.Thread(target=trabajar, daemon=True).start()

    def mirar() -> None:
        if resultado["hecho"]:
            barra.stop()
            dlg.destroy()
            return
        dlg.after(120, mirar)

    dlg.after(120, mirar)
    mostrar(dlg, parent)
    return bool(resultado["ok"]), resultado["valor"]


# ---------------------------------------------------------------------------
# La ventana principal
# ---------------------------------------------------------------------------

def main_window(config: Config, startup_msg: str | None) -> Choice | None:
    """La ventana principal: qué parejas, cada cuánto, y qué hacer con ellas.

    Sincronizar y el doctor se hacen DESDE aquí, en una ventana de salida hija
    que no la cierra: al terminar se vuelve a esta con todo al día. Lo único que
    sale de la ventana es arrancar el servicio, que vive en otro proceso: la
    elección 'daemon' se devuelve a runsync. None si se cierra sin más.
    Lanza ImportError/TclError si no hay entorno gráfico."""
    import tkinter as tk
    from tkinter import messagebox, ttk

    from . import tk_pairs, tk_update, tk_watch

    theme.nitidez()
    root = tk.Tk()  # TclError aquí si no hay display -> fallback consola
    theme.apply(root)
    icons.poner_icono(root)
    root.title(TITLE)
    root.configure(background=theme.PAPEL)
    root.resizable(False, False)
    root.withdraw()          # se enseña ya centrada, ver el final de la función
    result: dict = {"choice": None}
    # `nueva` es la release pendiente, si la hay. Se pregunta a la caché y no a
    # la red: esto es el primer pintado y tiene que ser instantáneo. Quien va a
    # GitHub es el hilo de `mirar_version()`, más abajo. Bajo `except` porque
    # `ui.start()` envuelve toda la llamada a `ask()`: un estado ilegible aquí no
    # daría un error, daría un menú de consola sin explicar por qué.
    try:
        pendiente = update.pending()
    except Exception:                                # noqa: BLE001
        pendiente = None
    vista: dict = {"config": config, "aviso": startup_msg, "nueva": pendiente,
                   "en_curso": False}

    # Dentro de un visor: la lista de parejas crece con cada pareja y la ventana
    # no puede pasar del alto de la pantalla. Con pocas parejas no se nota nada.
    frame = cuerpo_visible(root, padding=(22, 20, 22, 18))
    frame.columnconfigure(0, weight=1)

    def leer_estado() -> None:
        """Lo que dejó apuntado la última pasada: qué falló y qué conflictos hay.

        Se lee de state/ y no se recorre nada: es lo que pinta la ventana nada
        más abrirse y al volver de una sincronización (sync.py lo acaba de
        escribir). El recorrido de verdad lo hace `mirar_conflictos()` en un
        hilo. Bajo `except` por lo mismo que `update.pending()` arriba."""
        try:
            vista["fallos"] = results.fallos(vista["config"])
        except Exception:                            # noqa: BLE001
            vista["fallos"] = []
        try:
            vista["conflictos"] = conflicts.contar(conflicts.cargar(vista["config"]))
        except Exception:                            # noqa: BLE001
            vista["conflictos"] = {}

    leer_estado()

    def reajustar() -> None:
        """Repintar sin mover la ventana si no ha cambiado de tamaño.

        Lo que cambia aquí —un botón que se apaga mientras sincroniza, un chip
        que pasa a ámbar— casi nunca cambia el tamaño, y recolocar una ventana
        que el usuario ha movido sería arrastrársela."""
        render()
        if root.visor.encajar(root):
            centrar(root)

    def recargar() -> None:
        """El config ha cambiado bajo nuestros pies: releerlo y repintar.

        Si ha quedado ilegible se dice y se conserva el anterior en pantalla, que
        es mejor que quedarse con una ventana en blanco."""
        try:
            vista["config"] = model.load_config()
        except model.ConfigError as e:
            messagebox.showerror(TITLE, f"El config no se puede leer:\n\n{e}")
            return
        vista["aviso"] = None
        leer_estado()
        render()
        root.visor.encajar(root)
        centrar(root)   # quitar o añadir parejas le cambia el alto

    def repintar() -> None:
        """Repintar y recolocar. La ventana no es redimensionable y va dentro de
        un visor, así que quitar o poner un bloque obliga a rehacer las dos
        medidas; sin esto el aviso nuevo aparece recortado."""
        render()
        root.visor.encajar(root)
        centrar(root)

    def abrir_actualizacion() -> None:
        """La pantalla de actualización. Si se ha actualizado, aquí no se vuelve:
        `tk_update` relanza el programa y cierra esta ventana, porque este
        proceso tiene cargados en memoria los módulos que se acaban de
        sustituir."""
        if tk_update.open_dialog(root, vista["nueva"]):
            result["choice"] = None
            root.destroy()
            return
        vista["nueva"] = update.pending()
        repintar()

    def mirar_version() -> None:
        """Preguntarle a GitHub si hay algo nuevo, sin que se note.

        En un hilo porque la ventana ya está abierta y no puede quedarse quieta
        esperando a la red, y devolviendo por `after` porque a Tk solo se le
        habla desde su propio hilo. Todo bajo `except`: `ui.start()` envuelve la
        llamada entera a `ask()`, así que una excepción suelta aquí no daría un
        error, daría un menú de consola sin explicación."""
        def responder(nueva) -> None:
            # También cuando pasa a None: si la caché estaba adelantada, el
            # aviso tiene que irse, no quedarse puesto hasta la próxima vez.
            if nueva != vista["nueva"]:
                vista["nueva"] = nueva
                repintar()

        def trabajo() -> None:
            try:
                update.check()
                nueva = update.pending()
            except Exception:                        # noqa: BLE001
                return       # sin red no hay aviso, y no pasa nada
            try:
                root.after(0, responder, nueva)
            except Exception:                        # noqa: BLE001
                pass         # la ventana ya se ha cerrado

        threading.Thread(target=trabajo, daemon=True).start()

    def mirar_conflictos() -> None:
        """Recorrer las carpetas de verdad, sin que se note.

        Lo que se pintó al abrir sale del último escaneo; esto lo pone al día
        —conflictos que han llegado de otro dispositivo, o que se han resuelto a
        mano—. En un hilo porque recorrer un árbol grande en un dispositivo USB
        tarda, y devolviendo por `after` porque a Tk solo se le habla desde su
        hilo. Mientras sincroniza no se mira: sync.py ya lo hace al acabar."""
        if vista["en_curso"]:
            return
        config_ahora = vista["config"]

        def responder(cuentas) -> None:
            if cuentas != vista["conflictos"] and not vista["en_curso"]:
                vista["conflictos"] = cuentas
                reajustar()

        def trabajo() -> None:
            try:
                cuentas = conflicts.contar(conflicts.refrescar(config_ahora))
            except Exception:                        # noqa: BLE001
                return
            try:
                root.after(0, responder, cuentas)
            except Exception:                        # noqa: BLE001
                pass         # la ventana ya se ha cerrado

        threading.Thread(target=trabajo, daemon=True).start()

    def abrir_conflictos() -> None:
        from . import tk_conflicts
        tk_conflicts.open_dialog(root, vista["config"])
        leer_estado()
        reajustar()

    def abrir_log(ruta) -> None:
        try:
            abrir(ruta)
        except OSError as e:
            messagebox.showerror(TITLE, f"No se ha podido abrir:\n\n{ruta}\n\n{e}",
                                 parent=root)

    def lanzar(titulo: str, args: list[str]) -> None:
        """Ejecuta sync.py en la ventana de salida SIN cerrar esta.

        La ventana de salida es hija de esta y no la bloquea; mientras corre, lo
        que tocaría el mismo estado (otra pasada, el servicio, las parejas) queda
        apagado. Al cerrarla se vuelve aquí con las horas, los chips y los avisos
        ya al día: sync.py acaba de escribirlos en state/."""
        vista["en_curso"] = True
        reajustar()

        def al_cerrar(_rc) -> None:
            vista["en_curso"] = False
            try:
                leer_estado()
                reajustar()
            except tk.TclError:
                pass         # se está cerrando la ventana principal entera

        output_window(titulo, orden_sync(args), parent=root,
                      subtitulo=subtitulo_sync(args), modal=False, al_cerrar=al_cerrar)

    def render() -> None:
        # Lo marcado a mano se conserva al repintar: esta ventana se repinta sola
        # (vuelve una sincronización, llega el escaneo de conflictos) y perder
        # las casillas que se acaban de tocar sería un castigo por esperar.
        if vista.get("casillas"):
            vista["marcadas"] = [n for n, v in vista["casillas"].items() if v.get()]
            vista["conocidas"] = list(vista["casillas"])
            vista["intervalo"] = vista["intervalo_var"].get()
        for hijo in frame.winfo_children():
            hijo.destroy()

        config = vista["config"]
        names = config.names
        notes = pair_status_notes(config)
        marcas = pair_times(config)
        cuentas = {n: k for n, k in vista["conflictos"].items() if n in names}
        d_pairs, d_interval, _ = prefs.startup_defaults(config)
        if "marcadas" in vista:
            d_pairs = [n for n in names
                       if n in vista["marcadas"] or n not in vista["conocidas"]]
        en_curso = vista["en_curso"]
        apagado = "disabled" if en_curso else "normal"
        fila = 0

        # --- quién es este dispositivo y cómo está -----------------------------------
        arriba = ttk.Frame(frame)
        arriba.grid(row=fila, column=0, sticky="ew")
        arriba.columnconfigure(0, weight=1)
        fila += 1

        titulo = ttk.Frame(arriba)
        titulo.grid(row=0, column=0, sticky="w")
        ttk.Label(titulo, text="Sincronizar", style="Titulo.TLabel").grid(
            row=0, column=0, sticky="w")
        extremos = ttk.Frame(titulo)
        extremos.grid(row=1, column=0, sticky="w", pady=(6, 0))
        remotos = sorted({p.remote_name for p in config.pairs}) or [model.DEFAULT_REMOTE]
        for col, (icono, texto) in enumerate((("dispositivo", corto(str(model.DEVICE_ROOT))),
                                              ("nas", corto(", ".join(remotos))))):
            if col:
                ttk.Label(extremos, text="·", style="Apagado.TLabel").grid(
                    row=0, column=2, padx=6)
            img = icons.get(extremos, icono, 14, theme.TINTA3, theme.PAPEL)
            marca = ttk.Label(extremos, style="Pista.TLabel")
            if img is not None:
                marca.configure(image=img)
                marca.image = img
            marca.grid(row=0, column=col * 3, sticky="w")
            ttk.Label(extremos, text=texto, style="MonoPista.TLabel").grid(
                row=0, column=col * 3 + 1, sticky="w", padx=(5, 0))

        # El chip dice lo que se sabe sin hablar con nadie: si alguna pareja
        # necesita un --resync. La conexión con el remoto NO se comprueba aquí — se
        # tardaría segundos en abrir la ventana y la respuesta caducaría enseguida.
        if en_curso:
            chip = theme.chip(arriba, "sincronizando…", "Acento.", "sync")
        elif notes:
            chip = theme.chip(arriba, f"{len(notes)} requieren resync" if len(notes) > 1
                              else "1 requiere resync", "Aviso.", "warn")
        elif cuentas:
            total = sum(cuentas.values())
            chip = theme.chip(arriba, f"{total} en conflicto", "Aviso.", "warn")
        else:
            chip = theme.chip(arriba, "al día", "Ok.", "ok")
        chip.grid(row=0, column=1, sticky="ne", pady=(4, 0))

        if vista["aviso"]:
            bloque_aviso(frame, vista["aviso"], ancho=400).grid(
                row=fila, column=0, sticky="ew", pady=(14, 0))
            fila += 1

        # --- lo que falló la última vez ---------------------------------------
        # Justo debajo del aviso de arranque: es lo más urgente de la ventana, y
        # sin esto un fallo del servicio solo existía en logs/, donde nadie mira.
        # Se queda mientras la última pasada de esa pareja siga siendo un fallo.
        fallos = [f for f in vista["fallos"] if f.pareja in names]
        if fallos and not en_curso:
            lineas = [f"{f.pareja}" + (f" · {cuando_sello(f.cuando)}"
                                       if cuando_sello(f.cuando) else "")
                      for f in fallos]
            logs = [f.log for f in fallos if f.log is not None]
            boton = None
            if len(logs) == 1:
                boton = ("Ver el log", lambda ruta=logs[0]: abrir_log(ruta))
            elif logs:
                boton = ("Abrir los logs", lambda: abrir_log(model.LOG_DIR))
            bloque_aviso(
                frame,
                "La última pasada falló en:\n" + "\n".join(lineas) +
                "\nMientras no se arregle, eso no está sincronizado.",
                ancho=330, boton=boton,
            ).grid(row=fila, column=0, sticky="ew", pady=(14, 0))
            fila += 1

        # --- ficheros con dos versiones ----------------------------------------
        if cuentas:
            total = sum(cuentas.values())
            caja = bloque_aviso(
                frame,
                f"{total} fichero(s) en conflicto en {', '.join(cuentas)}: cambiaron "
                f"en los dos lados y ahora hay dos versiones.",
                ancho=330, boton=("Revisar…", abrir_conflictos))
            caja.grid(row=fila, column=0, sticky="ew", pady=(14, 0))
            # Resolver mientras sincroniza sería mover ficheros bajo los pies de
            # rclone.
            for hijo in caja.winfo_children():
                if isinstance(hijo, ttk.Button):
                    hijo.configure(state=apagado)
            fila += 1

        # --- hay versión nueva -----------------------------------------------
        # Debajo del aviso de arranque y no encima: ese cuenta lo que acaba de
        # pasar (el servicio que se ha parado), y esto puede esperar.
        nueva = vista["nueva"]
        if nueva is not None:
            actual = update.installed_version() or "desconocida"
            bloque_aviso(
                frame,
                f"Hay una actualización: {nueva.tag}\nTienes la {actual}",
                ancho=330, icono="down",
                boton=("Actualizar…", abrir_actualizacion),
            ).grid(row=fila, column=0, sticky="ew", pady=(14, 0))
            fila += 1

        # --- la lista de parejas ---------------------------------------------
        rotulo = ttk.Frame(frame)
        rotulo.grid(row=fila, column=0, sticky="ew", pady=(20, 8))
        rotulo.columnconfigure(1, weight=1)
        fila += 1
        ttk.Label(rotulo, text=theme.rotulo("Parejas"),
                  style="Rotulo.TLabel").grid(row=0, column=0, sticky="w")
        ultima = cuando(max((m for m in marcas.values() if m), default=None))
        resumen = f"{len(d_pairs)} de {len(names)}"
        if ultima:
            resumen += f" · última pasada {ultima}"
        ttk.Label(rotulo, text=resumen, style="Pista.TLabel").grid(
            row=0, column=2, sticky="e")

        tarjeta = ttk.Frame(frame, style="Card.TFrame", padding=(12, 2))
        tarjeta.grid(row=fila, column=0, sticky="ew")
        tarjeta.columnconfigure(2, weight=1)
        fila += 1

        vars_by_name: dict[str, tk.BooleanVar] = {}
        linea = 0
        for name in names:
            if linea:
                separador_fila(tarjeta, linea, 5)
                linea += 1
            var = tk.BooleanVar(value=(name in d_pairs))
            vars_by_name[name] = var
            ttk.Checkbutton(tarjeta, text=name, variable=var,
                            style="Card.Fuerte.TCheckbutton").grid(
                row=linea, column=0, sticky="w", pady=6)
            pareja = next(p for p in config.pairs if p.name == name)
            ttk.Label(tarjeta, text=pareja.mode.name, style="Card.Pista.TLabel").grid(
                row=linea, column=1, sticky="w", padx=(10, 0))
            ttk.Label(tarjeta, text=cuando(marcas.get(name)) or "—",
                      style="Card.MonoPista.TLabel").grid(row=linea, column=3,
                                                          sticky="e", padx=(10, 8))
            if name in notes:
                theme.chip(tarjeta, notes[name], "Aviso.").grid(
                    row=linea, column=4, sticky="e")
            elif name in cuentas:
                # Se queda hasta que no quede ninguna copia en disco: no es un
                # suceso que se lee y se olvida, es un estado de la carpeta.
                texto = "1 conflicto" if cuentas[name] == 1 else f"{cuentas[name]} conflictos"
                theme.chip(tarjeta, texto, "Aviso.").grid(row=linea, column=4, sticky="e")
            else:
                theme.chip(tarjeta, "al día", "Ok.").grid(row=linea, column=4,
                                                          sticky="e")
            linea += 1
        if not names:
            ttk.Label(tarjeta, text="No hay ninguna pareja configurada.",
                      style="Card.Pista.TLabel").grid(row=0, column=0, pady=10)

        # --- cada cuánto ------------------------------------------------------
        repetir = ttk.Frame(frame)
        repetir.grid(row=fila, column=0, sticky="w", pady=(16, 0))
        fila += 1
        img = icons.get(repetir, "clock", 15, theme.TINTA3, theme.PAPEL)
        reloj = ttk.Label(repetir)
        if img is not None:
            reloj.configure(image=img)
            reloj.image = img
        reloj.grid(row=0, column=0, sticky="w")
        ttk.Label(repetir, text="Repetir cada", style="Campo.TLabel").grid(
            row=0, column=1, sticky="w", padx=(8, 10))
        interval_var = tk.StringVar(value=vista.get("intervalo") or f"{d_interval:g}")
        ttk.Spinbox(repetir, from_=1, to=1440, textvariable=interval_var,
                    width=5, font=theme.fuente("mono")).grid(row=0, column=2)
        ttk.Label(repetir, text="minutos, mientras el dispositivo siga puesto",
                  style="Pista.TLabel").grid(row=0, column=3, sticky="w", padx=(10, 0))
        vista["casillas"], vista["intervalo_var"] = vars_by_name, interval_var

        def selected() -> list[str]:
            return [n for n in names if vars_by_name[n].get()]

        def minutos() -> float:
            try:
                return max(1.0, float(interval_var.get().replace(",", ".")))
            except ValueError:
                return d_interval

        def sincronizar() -> None:
            """La pasada manual, aquí mismo. Se recuerda lo elegido —el
            intervalo también: aquí no se usa, pero forma parte de lo que se
            recuerda para la próxima vez— antes de preguntar por los resync."""
            sel = selected()
            if not sel:
                return  # nada marcado, nada que hacer
            prefs.save_prefs("manual", sel, minutos(), names)
            args = manual_args(vista["config"], sel,
                               lambda pendientes: preguntar_resync(root, pendientes))
            lanzar("Sincronización manual", args)

        def servicio() -> None:
            """El servicio sí cierra la ventana: corre en otro proceso, sin
            ella, y quien lo arranca es runsync al volver de aquí."""
            sel = selected()
            if not sel:
                return
            result["choice"] = Choice("daemon", tuple(sel), minutos())
            root.destroy()

        # --- las pantallas de las que se vuelve aquí --------------------------
        ajustes = ttk.Frame(frame)
        ajustes.grid(row=fila, column=0, sticky="ew", pady=(18, 0))
        ajustes.columnconfigure(2, weight=1)
        fila += 1
        # Mientras sincroniza se apaga todo lo que toca el mismo estado: otra
        # pasada chocaría con el lock de bisync, y la pantalla de parejas puede
        # apartar un baseline que rclone está usando. «Arranque automático» no
        # toca nada del dispositivo, así que sigue a mano.
        for col, (texto, icono, accion, estado_boton) in enumerate((
                ("Parejas…", "grid",
                 lambda: tk_pairs.open_dialog(root, vista["config"]) and recargar(),
                 apagado),
                ("Arranque automático…", "plug",
                 lambda: tk_watch.open_dialog(root, vista["config"]), "normal"))):
            boton = ttk.Button(ajustes, text=texto, style="Quiet.TButton",
                               command=accion, state=estado_boton)
            theme.boton_icono(boton, icono, theme.ACENTO, theme.PAPEL)
            boton.grid(row=0, column=col, sticky="w", padx=(0, 4))
        doctor = ttk.Button(ajustes, text="Doctor", style="Quiet.TButton",
                            command=lambda: lanzar("Doctor", ["--doctor"]),
                            state=apagado)
        theme.boton_icono(doctor, "doctor", theme.ACENTO, theme.PAPEL)
        doctor.grid(row=0, column=3, sticky="e")

        ttk.Separator(frame, orient="horizontal").grid(
            row=fila, column=0, sticky="ew", pady=(14, 0))
        fila += 1

        # --- la acción principal ---------------------------------------------
        pie = ttk.Frame(frame)
        pie.grid(row=fila, column=0, sticky="ew", pady=(14, 0))
        pie.columnconfigure(0, weight=1)
        ahora = ttk.Button(pie, text="Sincronizar ahora", style="Primary.TButton",
                           padding=(14, 8), command=sincronizar, state=apagado)
        theme.boton_icono(ahora, "sync", theme.SUPERFICIE, theme.ACENTO, 16)
        ahora.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ttk.Button(pie, text="Iniciar servicio", padding=(12, 8),
                   command=servicio, state=apagado).grid(row=0, column=1)

    render()
    root.visor.encajar(root)
    centrar(root)
    root.deiconify()
    # Después de enseñarla, no antes: la comprobación de versión y el recorrido
    # de las carpetas no pueden retrasar la apertura ni un parpadeo.
    root.after(300, mirar_version)
    root.after(300, mirar_conflictos)
    root.mainloop()
    return result["choice"]


# ---------------------------------------------------------------------------
# El aviso del servicio
# ---------------------------------------------------------------------------

def aviso_fallo(fallos, al_abrir=None) -> None:
    """La ventanita que abre el servicio cuando falla un ciclo. Bloquea hasta
    que se cierra: quien la llama (`ui.avisar_fallo`) la tiene en su propio
    hilo. `al_abrir()` se llama cuando ya se ve.

    Es lo mínimo: qué parejas, cuándo, y el log. Explicar el fallo es cosa de la
    ventana principal, que ya tiene su bloque ámbar para esto; aquí solo hay
    que conseguir que alguien se entere.

    Al cerrarse se suelta AQUÍ todo lo de Tk: lo que recuerdan `theme` e
    `icons` de este intérprete, y los `PhotoImage` colgados de los widgets en
    ciclos de referencias. Si los soltara más tarde el hilo del servicio,
    borrarlos sería hablarle a Tk desde un hilo que no es el suyo."""
    import gc
    try:
        _aviso_fallo(fallos, al_abrir)
    finally:
        gc.collect()


def _aviso_fallo(fallos, al_abrir) -> None:
    import tkinter as tk
    from tkinter import ttk

    theme.nitidez()
    root = tk.Tk()               # TclError aquí si no hay display: lo recoge quien llama
    theme.apply(root)
    icons.poner_icono(root)
    root.title(f"{TITLE} — el servicio ha fallado")
    root.configure(background=theme.PAPEL)
    root.resizable(False, False)
    root.withdraw()

    marco = cuerpo_visible(root, padding=(22, 20, 22, 18))
    marco.columnconfigure(0, weight=1)
    cabecera(marco, "El servicio no ha podido sincronizar",
             "Sigue en marcha y lo volverá a intentar en el próximo ciclo. Abre "
             f"{TITLE} para ver qué ha pasado.",
             ancho=420, estilo="Dialogo.TLabel").grid(row=0, column=0, sticky="w")

    tarjeta = ttk.Frame(marco, style="Card.TFrame", padding=(14, 4))
    tarjeta.grid(row=1, column=0, sticky="ew", pady=(14, 0))
    tarjeta.columnconfigure(0, weight=1)
    for i, fallo in enumerate(fallos):
        if i:
            separador_fila(tarjeta, i * 2 - 1, 2)
        ttk.Label(tarjeta, text=fallo.pareja, style="Card.Fuerte.TLabel").grid(
            row=i * 2, column=0, sticky="w", pady=6)
        ttk.Label(tarjeta, text=cuando_sello(fallo.cuando) or "—",
                  style="Card.MonoPista.TLabel").grid(row=i * 2, column=1, sticky="e")

    def ver(ruta) -> None:
        try:
            abrir(ruta)
        except OSError:
            pass         # sin visor no hay log que enseñar; la principal lo tiene

    pie = ttk.Frame(marco)
    pie.grid(row=2, column=0, sticky="ew", pady=(16, 0))
    pie.columnconfigure(0, weight=1)
    logs = [f.log for f in fallos if f.log is not None]
    if logs:
        ttk.Button(pie, text="Ver el log" if len(logs) == 1 else "Abrir los logs",
                   style="Quiet.TButton",
                   command=lambda: ver(logs[0] if len(logs) == 1 else model.LOG_DIR)).grid(
            row=0, column=1, padx=(0, 8))
    ttk.Button(pie, text="Cerrar", style="Primary.TButton",
               command=root.destroy).grid(row=0, column=2)

    root.visor.encajar(root)
    centrar(root)
    root.deiconify()
    # Un proceso sin ventana no puede quitarle el foco a nadie, así que Windows
    # la dejaría debajo de todo: encima un momento, lo justo para verla.
    try:
        root.attributes("-topmost", True)
        root.after(1500, lambda: root.attributes("-topmost", False))
    except tk.TclError:
        pass
    if al_abrir is not None:
        al_abrir()
    root.mainloop()
    interp = root.tk
    theme.olvidar(interp)
    icons.olvidar(interp)


# ---------------------------------------------------------------------------
# La ventana de salida
# ---------------------------------------------------------------------------

# Cómo se colorea cada línea. Es el vocabulario que ya usa sync.py por su salida
# —'=== pareja ===', '  ejecutando:', '[pareja] OK.', '[pareja] FALLÓ'—, así que
# esta tabla se lee junto a los print() de sync.py: si allí cambia una fórmula,
# aquí deja de pintarse, no se rompe nada.
def _tono(linea: str) -> str:
    limpia = linea.strip()
    if not limpia:
        return "normal"
    # El resumen final lleva las tres cosas en la misma línea ("2/4 parejas OK,
    # 1 saltada(s), 1 con errores"), así que se mira entero y de peor a mejor;
    # buscar 'OK' suelto lo pintaría de verde con un fallo dentro.
    if limpia.startswith("Hecho."):
        return ("fallo" if "con errores" in limpia
                else "aviso" if "saltada" in limpia else "ok")
    if limpia.startswith("===") or limpia.startswith("---"):
        return "fallo" if "ERROR" in limpia else (
            "ok" if "OK" in limpia else "cabecera")
    if limpia.startswith("ejecutando"):
        return "orden"
    if "FALLÓ" in limpia or "ERROR" in limpia or "NO EXISTE" in limpia:
        return "fallo"
    if limpia.startswith(">>") or "AVISO" in limpia or "Saltada" in limpia \
            or "requiere --resync" in limpia:
        return "aviso"
    if limpia.endswith("OK.") or limpia.endswith("(OK)") or limpia.startswith("OK"):
        return "ok"
    return "normal"


def output_window(title: str, cmd: list[str], parent=None,
                  subtitulo: str = "", modal: bool = True,
                  al_cerrar=None) -> int | None:
    """Ejecuta una orden y muestra su salida en una ventana con desplazamiento.

    Sustituye a la consola cuando no la hay, así que la usan tanto sync.py como
    penwatch.py: recibe la orden entera y no supone a quién llama. Cerrar la
    ventana a mitad de faena corta el proceso (bisync se recupera con --recover
    en la siguiente pasada).

    Con `parent` se cuelga de una ventana existente en vez de crear un Tk nuevo:
    tkinter no lleva bien dos intérpretes a la vez, y desde un diálogo ya hay uno
    en marcha.

    Con `modal=False` (y `parent`) no espera ni captura: vuelve enseguida con
    None y la ventana principal sigue viva debajo —es lo que la ventana
    principal necesita para no desaparecer al sincronizar—. `al_cerrar(rc)` se
    llama una vez, cuando la ventana se cierra, sea como sea."""
    import tkinter as tk
    from tkinter import filedialog, font as tkfont, messagebox, ttk

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
        bufsize=1,
    )
    q: queue.Queue = queue.Queue()
    DONE = object()

    def reader() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            q.put(line)
        q.put(DONE)

    threading.Thread(target=reader, daemon=True).start()

    if parent is None:
        theme.nitidez()
        root = tk.Tk()
        esperar = root.mainloop
    else:
        root = tk.Toplevel(parent)
        root.transient(parent)
        esperar = root.wait_window
    theme.apply(root)
    icons.poner_icono(root)
    root.withdraw()          # igual que los diálogos: se enseña ya colocada
    root.title(f"{TITLE} — {title}")
    root.configure(background=theme.PAPEL)
    root.columnconfigure(0, weight=1)
    root.rowconfigure(1, weight=1)
    arranque = time.monotonic()

    # --- la barra de arriba: qué se está haciendo y cómo va ------------------
    barra = ttk.Frame(root, style="Card.TFrame", padding=(18, 13))
    barra.grid(row=0, column=0, columnspan=2, sticky="ew")
    barra.columnconfigure(1, weight=1)
    img = icons.get(barra, "sync", 20, theme.ACENTO, theme.SUPERFICIE)
    marca = ttk.Label(barra, style="Card.TLabel")
    if img is not None:
        marca.configure(image=img)
        marca.image = img
    marca.grid(row=0, column=0, rowspan=2, sticky="w", padx=(0, 12))
    ttk.Label(barra, text=title.capitalize(), style="Card.Fuerte.TLabel").grid(
        row=0, column=1, sticky="w")
    ttk.Label(barra, text=subtitulo or " ", style="Card.MonoPista.TLabel").grid(
        row=1, column=1, sticky="w")
    estado = theme.chip(barra, "en marcha…", "Acento.")
    estado.grid(row=0, column=2, rowspan=2, sticky="e")

    # --- el cuerpo ------------------------------------------------------------
    # `wrap="char"` y no el "none" que trae `caja_texto`: aquí no hay barra
    # horizontal, así que no ajustar sería perder el final de las líneas largas
    # —y las órdenes de rclone lo son—.
    text = theme.caja_texto(root, width=104, height=28, state="disabled",
                            highlightthickness=0, padx=18, pady=12, wrap="char")
    text.grid(row=1, column=0, sticky="nsew")
    scroll = ttk.Scrollbar(root, command=text.yview)
    text.configure(yscrollcommand=scroll.set)
    scroll.grid(row=1, column=1, sticky="ns")

    # 104x28 son filas y columnas de texto, no píxeles: con el zoom del sistema
    # al 150 % esas 28 líneas miden más que la pantalla y la ventana nace con el
    # final fuera. Aquí no hace falta un `Visor` —el texto ya se desplaza solo—,
    # basta con pedir las que caben. Se mide el resto de la ventana en vez de
    # descontar una cifra fija, igual que hace `Visor._tope`.
    root.update_idletasks()
    resto_x = max(0, root.winfo_reqwidth() - text.winfo_reqwidth())
    resto_y = max(0, root.winfo_reqheight() - text.winfo_reqheight())
    util_x, util_y = pantalla_util(root)
    letra = tkfont.Font(root=root, font=text.cget("font"))
    columna, linea = max(1, letra.measure("0")), max(1, letra.metrics("linespace"))
    text.configure(width=max(40, min(104, (util_x - resto_x) // columna)),
                   height=max(8, min(28, (util_y - resto_y) // linea)))

    for nombre, opciones in (
            ("normal", dict(foreground=theme.TINTA2)),
            ("cabecera", dict(foreground=theme.TINTA, font=(
                theme.familia("mono"), 9, "bold"))),
            ("orden", dict(foreground=theme.TINTA3)),
            ("ok", dict(foreground=theme.OK)),
            ("aviso", dict(foreground=theme.AVISO)),
            ("fallo", dict(foreground=theme.PELIGRO))):
        text.tag_configure(nombre, **opciones)

    state = {"rc": None}

    def append(line: str) -> None:
        text.configure(state="normal")
        text.insert("end", line, _tono(line))
        text.see("end")
        text.configure(state="disabled")

    def guardar() -> None:
        """Llevarse la salida tal cual. Los logs de rclone solo se guardan
        cuando algo falla, así que esta es la única copia de una pasada buena."""
        destino = filedialog.asksaveasfilename(
            parent=root, title="Guardar el log", defaultextension=".txt",
            initialfile=f"{TITLE}-{time.strftime('%Y%m%d-%H%M%S')}.txt",
            filetypes=[("Texto", "*.txt"), ("Todos", "*.*")])
        if not destino:
            return
        try:
            with open(destino, "w", encoding="utf-8") as f:
                f.write(text.get("1.0", "end"))
        except OSError as e:
            messagebox.showerror(TITLE, f"No se ha podido guardar:\n\n{e}",
                                 parent=root)

    # --- el pie ---------------------------------------------------------------
    ttk.Separator(root, orient="horizontal").grid(row=2, column=0, columnspan=2,
                                                  sticky="ew")
    pie = ttk.Frame(root, padding=(18, 11))
    pie.grid(row=3, column=0, columnspan=2, sticky="ew")
    pie.columnconfigure(0, weight=1)
    guardar_btn = ttk.Button(pie, text="Guardar el log", style="Quiet.TButton",
                             command=guardar)
    theme.boton_icono(guardar_btn, "file", theme.ACENTO, theme.PAPEL)
    guardar_btn.grid(row=0, column=1, padx=(10, 6))
    ttk.Button(pie, text="Cerrar", style="Primary.TButton",
               command=lambda: root.destroy()).grid(row=0, column=2)

    def terminado() -> None:
        state["rc"] = proc.wait()
        segundos = int(time.monotonic() - arranque)
        bien = state["rc"] == 0
        verdict = "OK" if bien else f"ERROR (código {state['rc']})"
        append(f"\n=== Terminado: {verdict} ===\n")
        root.title(f"{TITLE} — {title} — {verdict}")
        nuevo = theme.chip(barra, f"{'terminado' if bien else verdict} · {segundos} s",
                           "Ok." if bien else "Peligro.", "ok" if bien else "warn")
        estado.destroy()
        nuevo.grid(row=0, column=2, rowspan=2, sticky="e")

    def poll() -> None:
        # Sin ventana no hay a quién contárselo. Con la principal viva debajo el
        # bucle de eventos sigue, y sin esto el sondeo seguiría para siempre.
        if not root.winfo_exists():
            return
        try:
            while True:
                item = q.get_nowait()
                if item is DONE:
                    terminado()
                    return
                append(item)
        except queue.Empty:
            pass
        root.after(120, poll)

    def on_close() -> None:
        if state["rc"] is None and proc.poll() is None:
            proc.terminate()
        root.destroy()

    avisado = {"ya": False}

    def al_destruir(evento) -> None:
        """Cerrar por el botón, por la X o porque se cierra la ventana madre:
        cualquiera de las tres acaba aquí, y en las tres hay que cortar el
        proceso si sigue y avisar a quien espera, una sola vez."""
        if evento.widget is not root or avisado["ya"]:
            return
        avisado["ya"] = True
        if proc.poll() is None:
            proc.terminate()
        if al_cerrar is not None:
            rc = state["rc"] if state["rc"] is not None else 1
            try:
                parent.after_idle(al_cerrar, rc)
            except Exception:                        # noqa: BLE001
                pass         # la madre también se está cerrando

    root.protocol("WM_DELETE_WINDOW", on_close)
    centrar(root, parent)
    root.deiconify()
    root.update_idletasks()
    sin_espera = parent is not None and not modal
    if sin_espera:
        root.bind("<Destroy>", al_destruir, add="+")
        root.after(120, poll)
        return None
    if parent is not None:
        try:
            root.grab_set()  # después de enseñarla: Tk no captura lo que no se ve
        except tk.TclError:
            pass
    root.after(120, poll)
    esperar()
    if proc.poll() is None:
        proc.terminate()
    return state["rc"] if state["rc"] is not None else 1
