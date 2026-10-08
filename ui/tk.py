#!/usr/bin/env python3
"""La interfaz gráfica (Tkinter).

Es la que se usa cuando se llega por doble clic en `runsync.bat` (o en el
`runsync.pyw` de una instalación ligera), es decir con `pythonw` y sin consola
detrás: por eso aquí no basta con elegir, hace falta además poder enseñar la
salida de la sincronización y preguntar sí/no, cosas que en el modo consola
hace la propia terminal.

El aspecto entero sale de `ui/theme.py` y los iconos de `ui/icons.py`: aquí no
se escribe ningún color a mano. Cada ventana llama a `theme.apply()` nada más
nacer, porque los estilos de ttk son globales dentro de un intérprete de Tk y a
lo largo de una sesión se abre más de uno.

`import tkinter` va dentro de cada función a propósito y no arriba: importar
este módulo no puede fallar en un equipo sin tkinter, porque el fallo tiene que
saltar cuando se intenta abrir la ventana, que es cuando `ui.start()` puede
recogerlo y caer al menú de consola.
"""

from __future__ import annotations

import queue
import subprocess
import sys
import threading
import time

from common import (APP_NAME, components, conflicts, model, progress, revision,
                    update)
from common.model import Config

from . import (Choice, abrir, cifrado, cuando, cuando_sello, icons, manual_args,
               pair_status_notes, pair_times, prefs, theme)

TITLE = APP_NAME
"""El nombre de la ventana, que sale de `common/`."""

IS_WIN = sys.platform == "win32"
QUITAR_UNIDAD = ("con «Quitar hardware de forma segura»" if IS_WIN else
                 "con «Expulsar» en el gestor de archivos")
"""Cómo se quita una unidad sin VeraCrypt después de «Expulsar», en cada sistema."""
"""Si esto corre en Windows; los tests lo fuerzan para pasar por la otra rama."""

CAPTURA_NINGUNA = 0
"""`WDA_NONE`: la ventana no ha quedado protegida de las capturas."""
CAPTURA_EN_NEGRO = 0x1
"""`WDA_MONITOR`: en una captura la ventana sale, pero como un rectángulo negro."""
CAPTURA_EXCLUIDA = 0x11
"""`WDA_EXCLUDEFROMCAPTURE`: en una captura la ventana no sale (Windows 10 2004)."""


def corto(texto: str, maximo: int = 30) -> str:
    r"""Devuelve una ruta recortada por delante, que es por donde sobra.

    En el dispositivo esto no hace nada (`DEVICE_ROOT` es `F:\`), pero montado
    en un punto con nombre largo (`/media/quien/PRDRIVE`) o corriendo desde el
    repositorio, una ruta entera estira la ventana hasta salirse de la
    pantalla.
    """
    return texto if len(texto) <= maximo else "…" + texto[-(maximo - 1):]


class TkFrontend:
    """El frontend gráfico; implementa el protocolo `ui.Frontend`."""

    def ask(self, config: Config, startup_msg: str | None) -> Choice | None:
        """Enseña la ventana principal y devuelve la elección."""
        return main_window(config, startup_msg)

    def approve_resync(self, pending: list[str]) -> bool:
        """Pregunta en una ventana si se aprueba el `--resync` de esas parejas."""
        root = root_oculto()
        try:
            return preguntar_resync(root, pending)
        finally:
            root.destroy()

    def info(self, msg: str) -> None:
        """Enseña un mensaje en una ventana."""
        from tkinter import messagebox
        root = root_oculto()
        messagebox.showinfo(TITLE, msg)
        root.destroy()

    def run_sync(self, title: str, args: list[str]) -> int:
        """Lanza `sync.py` en la ventana de salida y devuelve su código."""
        rc = output_window(title, orden_sync(args), subtitulo=subtitulo_sync(args))
        return rc if rc is not None else 1


def orden_sync(args: list[str]) -> list[str]:
    """Devuelve la orden que lanza `sync.py` con esos argumentos."""
    return [sys.executable, str(model.SYNC_PY), *args]


def subtitulo_sync(args: list[str]) -> str:
    """Devuelve el subtítulo de la ventana: las parejas que se van a tocar.

    Lo que se pasa son sus nombres y, detrás, las opciones que empiezan por
    `-`.
    """
    return ", ".join(a for a in args if not a.startswith("-"))


def preguntar_resync(parent, pending: list[str]) -> bool:
    """Devuelve el sí/no del `--resync`, colgado de la ventana que pregunta."""
    from tkinter import messagebox
    return bool(messagebox.askyesno(
        TITLE,
        "Estas parejas requieren --resync (primera vez, baseline perdido o "
        "filtros cambiados):\n\n  " + "\n  ".join(pending) +
        "\n\nEl resync compara ambos lados y fija la referencia; no borra por "
        "diferencias.\n¿Ejecutarlo ahora? (si no, esas parejas se saltarán)",
        parent=parent))


def root_oculto():
    """Devuelve un Tk invisible en mitad de la pantalla.

    Es para colgarle un messagebox suelto. Los messagebox se colocan respecto a
    su ventana padre y un Tk recién creado está en la esquina superior
    izquierda: sin mover el padre, el aviso sale arrinconado aunque no se vea
    la ventana de la que cuelga.
    """
    import tkinter as tk
    theme.nitidez()
    root = tk.Tk()
    root.withdraw()
    theme.apply(root)
    icons.poner_icono(root)
    root.geometry(f"+{root.winfo_screenwidth() // 2}+{root.winfo_screenheight() // 2}")
    return root


def centrar(win, parent=None) -> None:
    """Coloca una ventana en el centro de su padre o, sin él, de la pantalla.

    El `update_idletasks()` no es opcional: hasta que Tk no ha resuelto la
    disposición, `winfo_width()` vale 1 y el centro saldría a ojo.
    """
    win.update_idletasks()
    ancho = max(win.winfo_width(), win.winfo_reqwidth())
    alto = max(win.winfo_height(), win.winfo_reqheight())
    pantalla_x, pantalla_y = win.winfo_screenwidth(), win.winfo_screenheight()

    if parent is not None and parent.winfo_ismapped():
        x = parent.winfo_rootx() + (parent.winfo_width() - ancho) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - alto) // 2
        # Un diálogo puede ser bastante mayor que su padre (la pantalla de
        # parejas lo es), así que centrado sobre un padre pegado a un borde se
        # saldría. Solo se recoloca si el padre está en la pantalla principal:
        # con dos monitores las coordenadas pueden ser negativas y ahí
        # «corregir» sería arrastrar el diálogo a la otra pantalla.
        if 0 <= parent.winfo_rootx() < pantalla_x:
            x = max(0, min(x, pantalla_x - ancho))
            y = max(0, min(y, pantalla_y - alto))
    else:
        x = max(0, (pantalla_x - ancho) // 2)
        # Un pelín por encima del centro geométrico, que es donde el ojo lo
        # espera y deja sitio por abajo para los diálogos hijos.
        y = max(0, (pantalla_y - alto) // 2 - alto // 8)
    win.geometry(f"+{x}+{y}")


def pantalla_util(win) -> tuple[int, int]:
    """Devuelve lo que de verdad le queda a una ventana.

    Es la pantalla menos su marco y la barra de tareas. Los márgenes van en
    medidas del diseño escaladas (`icons.px`) porque el adorno del sistema
    crece con la densidad igual que el texto: una barra de tareas ocupa más
    píxeles en una pantalla al 150 % que en una al 100 %.
    """
    return (max(480, win.winfo_screenwidth() - icons.px(win, 60)),
            max(360, win.winfo_screenheight() - icons.px(win, 110)))


class Visor:
    """Un recuadro con el contenido dentro, que se desplaza cuando no cabe.

    Existe porque una ventana no puede ser más alta que la pantalla y el
    contenido de estas sí: los tamaños de letra van en puntos, así que en una
    pantalla densa (o con el zoom del sistema al 150 %) todo crece, mientras
    que los recuadros de tamaño fijo no. Eso se veía como un asistente al que
    le faltaba el último campo, sin nada que lo avisara: el paso 1 pide 486 px
    de alto en una pantalla normal y el hueco medía 430.

    `interior` es donde se dibuja. El recuadro se ajusta cuando la ventana ya
    está montada (`encajar`/`crecer`) y no antes, porque hasta entonces no se
    sabe cuánto ocupa el resto (cabecera, pie, márgenes) y descontar una cifra
    fija sería volver a suponer el tamaño de las letras.

    Las barras tienen su hueco reservado siempre, aparezcan o no: si lo ganaran
    y lo perdieran, la ventana cambiaría de ancho al pasar de un paso a otro.

    Args:
        padre: Donde se pone el recuadro.
        ancho: El ancho de partida y el mínimo, no un tope.
        alto: El alto de partida y el mínimo, no un tope: el recuadro nunca es
            más pequeño que eso y crece con el contenido hasta donde llegue la
            pantalla.
    """

    def __init__(self, padre, ancho: int | None = None, alto: int | None = None):
        """Crea el recuadro, su lienzo y sus barras, y engancha los eventos."""
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

    def _medida(self) -> tuple[int, int]:
        """Devuelve lo que mide el recuadro ahora mismo."""
        return (int(self.lienzo.cget("width")), int(self.lienzo.cget("height")))

    def _natural(self) -> tuple[int, int]:
        """Devuelve lo que pediría el contenido si nadie lo recortara.

        Nunca es menos que el tamaño de partida: `base` es un mínimo, no un
        tope.
        """
        self.interior.update_idletasks()
        base_x, base_y = self.base
        return (max(base_x or 0, self.interior.winfo_reqwidth()),
                max(base_y or 0, self.interior.winfo_reqheight()))

    def _tope(self, ventana) -> tuple[int, int]:
        """Devuelve lo más grande que puede ser el recuadro sin que la ventana se salga.

        Se mide el resto de la ventana en vez de descontar una cifra fija: la
        cabecera y el pie ocupan lo que ocupen sus fuentes.
        """
        ventana.update_idletasks()
        resto_x = max(0, ventana.winfo_reqwidth() - self.lienzo.winfo_reqwidth())
        resto_y = max(0, ventana.winfo_reqheight() - self.lienzo.winfo_reqheight())
        util_x, util_y = pantalla_util(ventana)
        return (max(320, util_x - resto_x), max(240, util_y - resto_y))

    def _fijar(self, ancho: int, alto: int) -> bool:
        """Pone el tamaño del recuadro y devuelve si ha cambiado.

        `_revisar()` se llama aunque no cambie: cambiar de paso cambia el
        contenido sin cambiar el hueco y entonces la barra que hace falta (o la
        que sobra) es distinta. Dejarlo colgando del `<Configure>` significaba
        que hasta el siguiente reposo del bucle de eventos la barra no estaba y
        el hueco parecía completo cuando no lo era.
        """
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
        más grande y una ventana que menguara y creciera a cada paso sería un
        baile. Devuelve si ha cambiado de tamaño, que es cuando quien llama
        tiene que volver a colocarla.
        """
        ventana = ventana or self.marco.winfo_toplevel()
        pide_x, pide_y = self._natural()
        hay_x, hay_y = self._medida()
        tope_x, tope_y = self._tope(ventana)
        return self._fijar(min(max(hay_x, pide_x), tope_x),
                           min(max(hay_y, pide_y), tope_y))

    def ver(self, widget) -> None:
        """Desplaza lo justo para que `widget` quede entero a la vista.

        Es para lo que crece con la pantalla ya pintada, cuando ni creciendo
        cabe: un error de una docena de líneas encima del botón que hay que
        volver a pulsar dejaba ese botón a medias por debajo del borde, con la
        barra puesta pero sin que nada invitara a usarla (#49). Se mide por la
        cadena de `winfo_y` hasta `interior` y no con coordenadas de pantalla,
        que en una ventana todavía oculta no existen.
        """
        self.interior.update_idletasks()
        arriba, w = 0, widget
        while w is not None and w is not self.interior:
            arriba += w.winfo_y()
            w = w.master
        if w is None:
            return                          # no está dentro de este visor
        abajo = arriba + widget.winfo_reqheight()
        alto = self._medida()[1]
        desde = self.lienzo.canvasy(0)
        if abajo > desde + alto:
            desde = abajo - alto
        elif arriba < desde:
            desde = arriba
        else:
            return
        self.lienzo.yview_moveto(max(0.0, desde) / max(1, self._puesto[1]))

    def _revisar(self) -> None:
        """Enseña cada barra solo si por ese lado sobra contenido.

        El interior se estira hasta llenar el hueco cuando no sobra, para que
        un formulario colocado con `sticky='ew'` siga ocupando todo el ancho; y
        solo se le habla cuando la medida cambia, porque redimensionarlo
        dispara otro `<Configure>` y con él se volvería aquí sin parar.
        """
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
        """Activa o desactiva la rueda del ratón sobre el recuadro."""
        eventos = ("<MouseWheel>", "<Button-4>", "<Button-5>")   # Windows / X11
        for evento in eventos:
            if activar:
                self.lienzo.bind_all(evento, self._girar)
            else:
                self.lienzo.unbind_all(evento)

    def _girar(self, evento):
        """Desplaza el recuadro con la rueda, salvo sobre algo que ya se desplaza solo.

        Dentro de la caja de opciones o de una lista, la rueda es suya.
        """
        if not self.vertical.winfo_ismapped():
            return None
        if evento.widget is not self.lienzo and hasattr(evento.widget, "yview_scroll"):
            return None
        arriba = getattr(evento, "num", 0) == 4 or getattr(evento, "delta", 0) > 0
        self.lienzo.yview_scroll(-1 if arriba else 1, "units")
        return "break"


def cuerpo_visible(ventana, **opciones):
    """Devuelve el marco donde se dibuja una pantalla, ya dentro de un `Visor`.

    Sustituye al `ttk.Frame(ventana, padding=…)` + `.grid(sticky='nsew')` que
    hacían todos los diálogos. La única diferencia visible es que, cuando la
    pantalla es pequeña, el contenido se desplaza en vez de quedarse fuera. El
    visor queda colgado de la ventana para que `mostrar()` lo encaje al
    enseñarla, sin que cada diálogo tenga que acordarse.
    """
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


def modal(parent, title: str, suelto: bool = False):
    """Devuelve un diálogo hijo, todavía OCULTO; se enseña con `mostrar()`.

    Nace oculto porque hasta que no están puestos todos los widgets no se sabe
    cuánto ocupa y sin saberlo no se puede centrar. Enseñarlo antes sería verlo
    aparecer en una esquina y pegar el salto al centro.

    `suelto` es para un padre que no se enseña nunca (`root_oculto()`): un
    `transient` hereda el estado de su padre y, colgado de uno oculto, no llega
    a verse aunque se le haga `deiconify()` (medido en Windows con la ventanita
    del relevo).
    """
    import tkinter as tk
    dlg = tk.Toplevel(parent)
    theme.apply(dlg)
    theme.barra_titulo(dlg)
    dlg.title(f"{TITLE} — {title}")
    dlg.configure(background=theme.PAPEL)
    if not suelto:
        dlg.transient(parent)
    dlg.resizable(False, False)
    dlg.withdraw()
    return dlg


def mostrar(dlg, parent=None) -> None:
    """Centra el diálogo sobre su padre, lo enseña y espera a que se cierre.

    El `grab_set()` va aquí y no en `modal()` porque Tk no deja capturar una
    ventana que no está visible, y por eso `deiconify()` lleva detrás un
    `update_idletasks()`: sin él el mapeo puede seguir pendiente. Si aun así
    fallara, se sigue: un diálogo sin captura es un incordio, pero uno que no
    se abre es un cuelgue.
    """
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


def _afinidad_de_pantalla(hwnd: int, afinidad: int) -> bool:
    """Pone la afinidad de pantalla de una ventana de Windows.

    Es la única llamada a user32 de `proteger_de_capturas()` y un punto de
    indirección: los tests la sustituyen, porque `ctypes.WinDLL` solo existe en
    Windows.

    Args:
        hwnd: El manejador de la ventana de nivel superior.
        afinidad: Uno de `CAPTURA_EN_NEGRO` o `CAPTURA_EXCLUIDA`.

    Returns:
        Si Windows la aceptó. Windows la rechaza (`ERROR_INVALID_PARAMETER`)
        con un valor que su versión no conoce.
    """
    import ctypes
    from ctypes import wintypes
    poner = ctypes.WinDLL("user32", use_last_error=True).SetWindowDisplayAffinity
    poner.argtypes = [wintypes.HWND, wintypes.DWORD]
    poner.restype = wintypes.BOOL
    return bool(poner(hwnd, afinidad))


def proteger_de_capturas(ventana) -> int:
    """Hace que la ventana no salga en capturas ni al compartir pantalla (Windows).

    Pide a Windows que la ventana solo se vea en el monitor, con
    `SetWindowDisplayAffinity` (user32, vía `ctypes`: sin dependencias ni
    shell). Prueba primero `WDA_EXCLUDEFROMCAPTURE` (Windows 10 2004 en
    adelante: en la captura la ventana no está) y, si Windows no lo conoce,
    `WDA_MONITOR` (en la captura sale un rectángulo negro). En el monitor la
    ventana se ve igual en los dos casos. Si no queda ninguna, la ventana sigue
    sin protección y se abre igual: esto nunca lanza.

    Se llama entre `modal()` y `mostrar()`, con la ventana todavía retirada:
    así no se enseña ni un fotograma sin proteger.

    **El manejador es `wm frame`, y antes hay un `update_idletasks()`.** Tk en
    Windows mete cada ventana de nivel superior en una ventana envoltorio
    (`UpdateWrapper`, `win/tkWinWm.c`) que solo crea al mapearla por primera vez,
    en reposo (`MapFrame` → `TkWmMapWindow`); un `withdraw()` no la crea, pero el
    mapeo la crea oculta (`SW_HIDE`: `initial_state` es `WithdrawnState`). Hasta
    entonces `wm frame` devuelve la ventana propia de Tk, la misma que
    `winfo_id()` (`WmFrameCmd`; `TkpMakeWindow` en `win/tkWinWindow.c`, un
    `WS_POPUP` sin padre): aceptaría la afinidad y la perdería cuando Tk la
    mete dentro del envoltorio, con la ventana creyéndose protegida. Por eso,
    si `wm frame` sigue igual a `winfo_id()` no se protege nada.

    **Después de llamarla no se toca el estilo de la ventana** (`resizable`,
    `transient`, `overrideredirect`, `attributes` de estilo): `UpdateWrapper`
    destruye el envoltorio y crea otro, y la afinidad es de la ventana, no de
    Tk. `modal()` hace las suyas antes; `mostrar()` solo usa `geometry` y
    `deiconify`, que no lo recrean.

    **Lo que no cubre:** una foto con otro móvil, un programa con privilegios
    que lea la pantalla, la Lupa y las herramientas de accesibilidad, y el
    Escritorio remoto, donde quien se conecta la ve en negro. En Linux no hay
    equivalente (X11 no tiene esa API y en Wayland lo decide el portal): ahí no
    hace nada.

    Args:
        ventana: Un `Toplevel` (o la raíz) todavía sin enseñar.

    Returns:
        La protección que ha quedado: `CAPTURA_EXCLUIDA`, `CAPTURA_EN_NEGRO` o
        `CAPTURA_NINGUNA`. Es el valor que daría `GetWindowDisplayAffinity`, y
        sirve de booleano (solo la última es falsa). Dice cuál y no solo si
        porque la frase que cabe decir es otra: con la segunda la ventana
        sí aparece en la captura, en negro. Fuera de Windows devuelve
        `CAPTURA_NINGUNA` sin tocar la ventana.
    """
    if not IS_WIN:
        return CAPTURA_NINGUNA
    try:
        ventana.update_idletasks()
        hwnd = int(ventana.wm_frame(), 16)
        if hwnd == int(ventana.winfo_id()):
            return CAPTURA_NINGUNA
    except Exception:
        return CAPTURA_NINGUNA
    for afinidad in (CAPTURA_EXCLUIDA, CAPTURA_EN_NEGRO):
        try:
            if _afinidad_de_pantalla(hwnd, afinidad):
                return afinidad
        except Exception:
            pass        # cualquier fallo es no haberla puesto: se prueba la otra
    return CAPTURA_NINGUNA


def cabecera(parent, titulo: str, pista: str = "", ancho: int = 620,
             estilo: str = "Titulo.TLabel"):
    """Devuelve el título de una pantalla con su frase debajo.

    Es el marco, para poder colgarle a la derecha un chip de estado.
    """
    from tkinter import ttk
    marco = ttk.Frame(parent)
    marco.columnconfigure(0, weight=1)
    ttk.Label(marco, text=titulo, style=estilo).grid(row=0, column=0, sticky="w")
    if pista:
        ttk.Label(marco, text=pista, style="Pista.TLabel", wraplength=theme.medida(ancho),
                  justify="left").grid(row=1, column=0, sticky="w", pady=(theme.E1, 0))
    return marco


def bloque_aviso(parent, texto: str, ancho: int = 560, tipo: str = "Ambar",
                 icono: str | None = None, boton: tuple[str, object] | None = None,
                 tono: str | None = None):
    """Devuelve el aviso con baldosa (`theme.aviso`) para un texto ya escrito.

    Es lo que hay que leer dos veces. Si el texto trae varias líneas, la
    primera es el título y el resto el cuerpo; si es una sola, va entera como
    texto, sin negrita. `icono` y `boton` son opcionales porque el mismo
    recuadro sirve para dos cosas distintas: un aviso que solo se lee (el
    servicio que se ha parado) y uno sobre el que se actúa (hay versión nueva
    y el botón la instala); el botón va debajo del texto, con el borde que
    toca sobre el fondo del aviso.

    Args:
        tipo: `'Ambar'` o `'Rojo'`; `tono` (`'Azul.'`, `'Verde.'`…) manda si
            se da.
    """
    from tkinter import ttk
    tono = tono or f"{tipo}."
    titulo, _, cuerpo = texto.partition("\n")
    if not cuerpo:
        titulo, cuerpo = "", titulo
    caja = theme.aviso(parent, titulo, cuerpo, tono=tono, icono=icono,
                       ancho=ancho)
    if boton is not None:
        rotulo, accion = boton
        ttk.Button(caja.acciones, text=rotulo, command=accion,
                   style="Ambar.TButton" if tono == "Ambar." else "TButton").grid(
            row=0, column=0, sticky="w", pady=(theme.E3, 0))
    return caja


def separador_fila(parent, fila: int, columnas: int, superficie: str = "Card."):
    """Pone la línea fina entre dos filas de una lista dibujada a mano."""
    from tkinter import ttk
    est = "Card.TSeparator" if superficie == "Card." else "TSeparator"
    ttk.Separator(parent, orient="horizontal", style=est).grid(
        row=fila, column=0, columnspan=columnas, sticky="ew")


class Panel:
    """Dónde se dibuja una pantalla: su propio diálogo o un apartado de «Ajustes».

    Las pantallas que cuelgan de «Ajustes» (la configuración, el llavero, las
    versiones…) se abren de dos maneras: sueltas, en su diálogo, desde la
    ventana principal; y dentro de «Ajustes», a la derecha de su barra
    lateral. Cada una se dibuja una sola vez, en `construir(panel, …)`, y el
    panel es lo que cambia entre las dos: dónde se dibuja, de qué ventana
    cuelgan sus mensajes y qué pasa al terminar.

    Hay tres maneras de terminar y no son la misma:
    - `terminar()`: lo de esta pantalla está hecho («Guardar», «Cancelar»).
      Suelta, se cierra; dentro de «Ajustes», se vuelve a dibujar con lo que
      hay ahora y la ventana sigue abierta.
    - `cerrar(despues)`: se cierra la ventana entera, sea el diálogo o
      «Ajustes», y luego se llama a `despues()`. Es lo que hace falta para
      ceder el paso a la ventana principal (lanzar una pasada, que abre su
      ventana de salida), porque dos modales no pueden tener la captura a la
      vez.
    - `devolver(valor)`: no cierra nada; apunta lo que la pantalla le dice a
      quien la abrió. Suelta lo devuelve `dialogo()`; en «Ajustes» se guarda
      por apartado y se le da a la ventana principal al cerrarla.

    Attributes:
        ventana: La ventana de nivel superior: padre de los mensajes, de
            `working()` y de los modales que se abran desde aquí.
        marco: Donde se dibuja, ya con su relleno.
        incrustado: Si es un apartado de «Ajustes».
    """

    def __init__(self, ventana, marco, incrustado: bool = False, al_terminar=None,
                 al_cerrar=None, resultados: dict | None = None,
                 clave: str = "") -> None:
        """Lo prepara; `al_terminar` y `al_cerrar` los pone quien lo crea."""
        self.ventana = ventana
        self.marco = marco
        self.incrustado = incrustado
        self._al_terminar = al_terminar
        self._al_cerrar = al_cerrar
        self._resultados = {} if resultados is None else resultados
        self._clave = clave

    def devolver(self, valor) -> None:
        """Apunta lo que la pantalla devuelve; lo último que se apunta manda."""
        self._resultados[self._clave] = valor

    def resultado(self, defecto=None):
        """Devuelve lo apuntado con `devolver()`, o `defecto` si no hay nada."""
        return self._resultados.get(self._clave, defecto)

    def terminar(self, nota: str = "") -> None:
        """Da por hecha esta pantalla: suelta se cierra; en «Ajustes», se rehace.

        Args:
            nota: Lo que se ha hecho («Guardado.»), para decirlo en el
                apartado rehecho; suelta, la ventana se cierra y no hace falta.
        """
        if self._al_terminar is not None:
            self._al_terminar(nota)

    def cerrar(self, despues=None) -> None:
        """Cierra la ventana entera y luego llama a `despues()`, si se da."""
        if self._al_cerrar is not None:
            self._al_cerrar()
        if despues is not None:
            despues()

    def ajustar(self) -> None:
        """Hace sitio a lo que ha crecido después de enseñarse.

        Es para lo que se repinta con la pantalla ya a la vista (lo que llega
        de la red, una lista que se relee): el recuadro crece hasta donde
        quepa y la ventana se vuelve a centrar, que es lo que hacía cada
        diálogo a mano.
        """
        visor = getattr(self.ventana, "visor", None)
        if visor is None or not self.ventana.winfo_ismapped():
            return
        if visor.crecer(self.ventana):
            centrar(self.ventana, self.ventana.master)


def dialogo(parent, titulo: str, construir, defecto=None, padding=(theme.E5, theme.E5, theme.E5, theme.E4),
            ensenar=None):
    """Abre una pantalla en su propio diálogo y devuelve lo que haya devuelto.

    Args:
        parent: La ventana de la que cuelga.
        titulo: El de la barra de la ventana.
        construir: `construir(panel)`, que la dibuja (`Panel`).
        defecto: Lo que se devuelve si la pantalla no ha devuelto nada.
        padding: El relleno del marco.
        ensenar: El `mostrar()` con que se enseña. Cada módulo pasa el suyo,
            el nombre que importó, porque es ése el que los tests sustituyen.
    """
    dlg = modal(parent, titulo)
    marco = cuerpo_visible(dlg, padding=padding)
    marco.columnconfigure(0, weight=1)
    panel = Panel(dlg, marco, al_terminar=lambda _nota="": dlg.destroy(),
                  al_cerrar=dlg.destroy)
    construir(panel)
    try:
        vivo = bool(dlg.winfo_exists())
    except Exception:                                # noqa: BLE001
        vivo = False
    if vivo:
        (ensenar or mostrar)(dlg, parent)
    return panel.resultado(defecto)


def pie(marco, fila: int, columnas: int = 1):
    """Pone el pie de una pantalla y devuelve el marco donde van sus botones.

    Encima del pie va una fila vacía que se estira: dentro de «Ajustes» el
    apartado ocupa todo el alto y el pie tiene que quedar abajo, como en el
    diseño; en un diálogo, que mide lo que su contenido, no se nota. Luego el
    filete y el marco de los botones, a todo el ancho.

    Args:
        fila: La primera fila libre; el pie ocupa esa y las dos siguientes.
        columnas: Cuántas columnas abarca.
    """
    from tkinter import ttk
    marco.rowconfigure(fila, weight=1)
    ttk.Separator(marco, orient="horizontal").grid(
        row=fila + 1, column=0, columnspan=columnas, sticky="ew", pady=(theme.E4, 0))
    botones = ttk.Frame(marco)
    botones.grid(row=fila + 2, column=0, columnspan=columnas, sticky="ew",
                 pady=(theme.E4, 0))
    return botones


def soltar_capturas(ventana) -> None:
    """Le quita a una ventana la protección de `proteger_de_capturas()`.

    Es para «Ajustes»: el código QR se protege mientras está a la vista, pero
    la ventana sigue abierta con otros apartados que sí pueden salir en una
    captura. Nunca lanza.
    """
    if not IS_WIN:
        return
    try:
        _afinidad_de_pantalla(int(ventana.wm_frame(), 16), CAPTURA_NINGUNA)
    except Exception:                                # noqa: BLE001 — ya no está
        pass


PASO_BARRA_MS = 12
"""Milisegundos que tarda en avanzar la barra sin cifra."""


def _medir_avance(progreso) -> tuple[float, str] | None:
    """Devuelve lo que dice `progreso()`, o `None` si no dice nada que se pueda pintar.

    Se captura `Exception` a propósito: el avance es un adorno y esto corre en
    el sondeo de `working()`, que es lo único que cierra la ventanita. Un error
    aquí que cortara ese sondeo dejaría la ventana abierta para siempre y no se
    puede cerrar a mano.
    """
    try:
        medida = progreso()
        if medida is None:
            return None
        fraccion, texto = medida
        return max(0.0, min(1.0, float(fraccion))), str(texto)
    except Exception:                                # noqa: BLE001 — ver docstring
        return None


def _pintar_avance(barra, etiqueta, medida: tuple[float, str] | None) -> None:
    """Pinta el avance en la barra y la etiqueta.

    Con cifra, la barra determinada y el texto debajo; sin ella, la barra que
    va y viene y el texto vacío: «mejor sin número que con uno falso».
    """
    determinada = str(barra.cget("mode")) == "determinate"
    if medida is None:
        if determinada:
            barra.configure(mode="indeterminate", value=0)
            barra.start(PASO_BARRA_MS)
        if str(etiqueta.cget("text")):
            etiqueta.configure(text="")
        return
    fraccion, texto = medida
    if not determinada:
        barra.stop()
        barra.configure(mode="determinate")
    barra.configure(value=100 * fraccion)
    if str(etiqueta.cget("text")) != texto:
        etiqueta.configure(text=texto)


def working(parent, title: str, funcion, mensaje: str = "",
            progreso=None, suelto: bool = False) -> tuple[bool, object]:
    """Ejecuta `funcion()` en un hilo aparte y enseña una ventanita mientras.

    Devuelve `(True, resultado)` o `(False, excepción)`.

    Existe porque `output_window` no sirve para todo: hay órdenes que tardan
    minutos y no dicen nada por su salida (crear un contenedor VeraCrypt) y
    otras cuya línea de órdenes NO se puede enseñar porque lleva la contraseña
    dentro. Lanzarlas en el hilo de Tk congelaría la ventana, así que van a un
    hilo y aquí solo se espera.

    No hay botón de cancelar a propósito: lo que se lanza así no se puede
    cortar a medias sin dejar las cosas peor (un contenedor a medio formatear).

    Al cerrarse devuelve la captura a quien la tuviera antes: Tk no guarda
    una pila de capturas y, sin esto, un diálogo modal que espera aquí dejaría
    de serlo (el explorador del remoto espera en cada carpeta).

    Args:
        parent: De quién cuelga la ventanita.
        title: Su título.
        funcion: El trabajo, que corre en el hilo.
        mensaje: Lo que dice la ventanita.
        progreso: Si se da, es una función sin argumentos que devuelve
            `(fracción, texto)` o `None` y se pregunta en cada vuelta del
            sondeo. Mientras diga algo, la barra se llena y el texto va debajo
            («43 % · quedan unos 25 min»); cuando vuelva a `None`, la barra
            vuelve a ir y venir. La llama el hilo de Tk, así que no puede tocar
            el disco ni esperar a nada: tiene que devolver lo último que otro
            hilo haya medido (`crypto.Seguimiento.progreso`). El hueco de ese
            texto se reserva desde el principio, para que la ventanita no
            cambie de alto cuando llega la primera cifra.
        suelto: Como en `modal()`: para colgarla de una raíz que no se enseña.
    """
    from tkinter import ttk

    dlg = modal(parent, title, suelto=suelto)
    dlg.protocol("WM_DELETE_WINDOW", lambda: None)   # no se cierra a medias

    marco = ttk.Frame(dlg, padding=(theme.E5, theme.E4))
    marco.grid(sticky="nsew")
    ttk.Label(marco, text=mensaje or f"{title}…", wraplength=theme.medida(380),
              justify="left").grid(row=0, column=0, sticky="w")
    barra = ttk.Progressbar(marco, mode="indeterminate",
                            length=theme.medida(380))
    barra.grid(row=1, column=0, pady=(theme.E4, 0), sticky="ew")
    barra.start(PASO_BARRA_MS)
    cifra = None
    if progreso is not None:
        cifra = ttk.Label(marco, text="", wraplength=theme.medida(380),
                          justify="left")
        cifra.grid(row=2, column=0, sticky="w", pady=(theme.E2, 0))
    dlg.barra, dlg.cifra = barra, cifra     # colgadas como `visor`: los tests las miran

    resultado: dict = {"ok": False, "valor": None, "hecho": False}

    def trabajar() -> None:
        """Corre la función y apunta su resultado o su excepción."""
        try:
            resultado["valor"] = funcion()
            resultado["ok"] = True
        except Exception as e:                       # se le enseña a quien llama
            resultado["valor"] = e
        finally:
            resultado["hecho"] = True

    threading.Thread(target=trabajar, daemon=True).start()

    def mirar() -> None:
        """Sondea cada 120 ms si ha acabado el trabajo.

        Cuando acaba, cierra la ventanita.
        """
        if resultado["hecho"]:
            barra.stop()
            dlg.destroy()
            return
        # La siguiente vuelta se pide ANTES de pintar: si pintar fallara, el
        # sondeo seguiría y la ventanita se cerraría igual al terminar.
        dlg.after(120, mirar)
        if cifra is not None:
            _pintar_avance(barra, cifra, _medir_avance(progreso))

    try:
        previa = dlg.grab_current()
    except Exception:                                # noqa: BLE001 — una que Tkinter no conoce
        previa = None
    dlg.after(120, mirar)
    mostrar(dlg, parent)
    _devolver_captura(previa)
    return bool(resultado["ok"]), resultado["valor"]


def _devolver_captura(ventana) -> None:
    """Le devuelve la captura a una ventana que sigue viva y a la vista."""
    if ventana is None:
        return
    try:
        if ventana.winfo_exists() and ventana.winfo_viewable():
            ventana.grab_set()
    except Exception:                                # noqa: BLE001 — sin captura, se sigue
        pass


SONDEO_MS = 120
"""Milisegundos entre dos miradas de `Sondeo` a su encargo, como en `working()`."""


class Sondeo:
    """Recoge en el hilo de Tk lo que una pantalla encargó a `ui.segundo_plano`.

    Es la mitad de Tk de un `Encargo`: mira cada `SONDEO_MS` si ha terminado
    y, cuando termina, llama a quien lo esperaba desde este hilo, nunca desde
    el del trabajo. Hay uno por pantalla y espera un encargo cada vez: uno
    nuevo deja sin respuesta al anterior.

    Si la pantalla se cierra antes, la espera se cancela con ella
    (`after_cancel`) y nadie pinta en widgets que ya no existen. Sin eso, el
    `after` pendiente llamaría a una orden que Tk ya ha borrado con la ventana.

    Args:
        ventana: La pantalla de la que cuelga la espera.
    """

    def __init__(self, ventana) -> None:
        """Engancha la espera al cierre de la ventana."""
        self.ventana = ventana
        self._id = None
        self._encargo = None
        self._al_llegar = None
        ventana.bind("<Destroy>", self._al_destruir, add="+")

    @property
    def esperando(self) -> bool:
        """Indica si hay un encargo pendiente de recoger."""
        return self._id is not None

    def esperar(self, encargo, al_llegar) -> None:
        """Llama a `al_llegar(encargo)` cuando el encargo termine.

        Si ya ha terminado, en el acto: es lo que hace que una pantalla cuyos
        tests corren el encargo en el sitio (`segundo_plano.en_el_acto`) se
        pinte entera antes de enseñarse.
        """
        self.cancelar()
        if encargo.hecho:
            al_llegar(encargo)
            return
        self._encargo, self._al_llegar = encargo, al_llegar
        self._id = self.ventana.after(SONDEO_MS, self._mirar)

    def cancelar(self) -> None:
        """Deja de esperar; lo que llegue después no se recoge."""
        if self._id is not None:
            try:
                self.ventana.after_cancel(self._id)
            except Exception:                        # noqa: BLE001 — ya no está
                pass
        self._id = self._encargo = self._al_llegar = None

    def _mirar(self) -> None:
        """Mira si el encargo ha terminado y, si no, vuelve a mirar luego."""
        self._id = None
        try:
            viva = bool(self.ventana.winfo_exists())
        except Exception:                            # noqa: BLE001 — intérprete cerrado
            viva = False
        if not viva or self._encargo is None:
            self.cancelar()
            return
        if not self._encargo.hecho:
            self._id = self.ventana.after(SONDEO_MS, self._mirar)
            return
        encargo, al_llegar = self._encargo, self._al_llegar
        self._encargo = self._al_llegar = None
        al_llegar(encargo)

    def _al_destruir(self, evento) -> None:
        """Cancela la espera si lo que se destruye es la ventana, no un hijo suyo."""
        if str(evento.widget) == str(self.ventana):
            self.cancelar()


LARGO_INDICADOR = 90
"""El largo de la barra del `Indicador`, en medidas del diseño."""


class Indicador:
    """La línea que dice que una pantalla espera a la red, o por qué ya no.

    Una barra que va y viene, como la de `working()`, y al lado su frase. La
    barra solo está mientras se espera; la frase puede quedarse después (la
    pantalla se quedó con la copia local y explica por qué) y, sin nada que
    decir, la línea desaparece entera. Quien la crea la coloca con
    `indicador.marco.grid(...)` y luego solo la `poner()`.

    Args:
        padre: Donde va la línea.
        ancho: El corte de la frase, en medidas del diseño.

    Attributes:
        marco: La línea entera.
        barra: La barra que va y viene.
        texto: La frase.
    """

    def __init__(self, padre, ancho: int = 560) -> None:
        """Dibuja la línea, todavía sin colocar."""
        from tkinter import ttk
        self.marco = ttk.Frame(padre)
        self.marco.columnconfigure(1, weight=1)
        self.barra = ttk.Progressbar(self.marco, mode="indeterminate",
                                     length=theme.medida(LARGO_INDICADOR))
        self.barra.grid(row=0, column=0, sticky="w", padx=(0, theme.E3))
        self.texto = ttk.Label(self.marco, style="Pista.TLabel", justify="left",
                               wraplength=theme.medida(ancho))
        self.texto.grid(row=0, column=1, sticky="w")

    @property
    def esperando(self) -> bool:
        """Indica si la barra está puesta."""
        return bool(self.barra.grid_info())

    def poner(self, texto: str, esperando: bool, tono: str = "Pista.") -> None:
        """Pone la frase y la barra; sin ninguna de las dos, quita la línea.

        Args:
            texto: Lo que dice la línea.
            esperando: Si la barra va y viene.
            tono: El rol de la frase (`Pista.`, `Aviso.`, `Peligro.`).
        """
        if esperando:
            self.barra.grid()
            self.barra.start(PASO_BARRA_MS)
        else:
            self.barra.stop()
            self.barra.grid_remove()
        self.texto.configure(text=texto, style=f"{tono}TLabel")
        if texto or esperando:
            self.marco.grid()
        else:
            self.marco.grid_remove()


def main_window(config: Config, startup_msg: str | None) -> Choice | None:
    """Abre la ventana principal: qué parejas y qué hacer con ellas.

    Sincronizar y el doctor se hacen DESDE aquí, en una ventana de salida hija
    que no la cierra: al terminar se vuelve a esta con todo al día. Lo único
    que sale de la ventana es arrancar el servicio, que vive en otro proceso:
    la elección `daemon` se devuelve a `runsync`. Si el servicio de esta raíz
    es el agente del equipo, en su lugar están «Pausar» / «Reanudar», que se
    lo piden por su buzón sin cerrarla. Devuelve `None` si se cierra sin más.

    Raises:
        ImportError: Si no hay tkinter.
        TclError: Si no hay entorno gráfico.
    """
    import tkinter as tk
    from tkinter import messagebox, ttk

    from . import llavero_editor, tk_doctor, tk_llavero, tk_pairs, tk_update, tk_watch, watch

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
    # la red: es el primer pintado y tiene que ser instantáneo. Quien va a
    # GitHub es el hilo de `mirar_version()`. Bajo `except` porque `ui.start()`
    # envuelve toda la llamada a `ask()`: un estado ilegible aquí no daría un
    # error, daría un menú de consola sin explicar por qué.
    try:
        pendiente = update.pending()
    except Exception:                                # noqa: BLE001
        pendiente = None
    vista: dict = {"config": config, "aviso": startup_msg, "nueva": pendiente,
                   "en_curso": False}

    # Dentro de un visor: la lista de parejas crece con cada pareja y la ventana
    # no puede pasar del alto de la pantalla. Con pocas parejas no se nota nada.
    frame = cuerpo_visible(root, padding=(theme.E5, theme.E5, theme.E5, theme.E4))
    frame.columnconfigure(0, weight=1)

    def leer_estado() -> None:
        """Lee lo que hay que revisar: averías apuntadas, conflictos y componentes.

        Se lee de `state/` y no se recorre nada: es lo que pinta la ventana
        nada más abrirse y al volver de una sincronización (`sync.py` lo acaba
        de escribir). El recorrido de verdad lo hace `mirar_conflictos()` en un
        hilo. Va bajo `except` por lo mismo que `update.pending()` arriba.
        """
        try:
            vista["hallazgos"] = revision.revisar(vista["config"])
        except Exception:                            # noqa: BLE001
            vista["hallazgos"] = []
        try:
            vista["conflictos"] = conflicts.contar(conflicts.cargar(vista["config"]))
        except Exception:                            # noqa: BLE001
            vista["conflictos"] = {}
        # Los componentes se leen de sus sellos: es un puñado de ficheros de dos
        # líneas del propio dispositivo, así que no hace falta hilo ni red —a
        # diferencia de la release, que vive en GitHub—.
        try:
            vista["componentes"] = components.pendientes()
        except Exception:                            # noqa: BLE001
            vista["componentes"] = []
        # ¿Vive en un contenedor VeraCrypt? Entonces cerrar la ventana no basta
        # para quitar la unidad, y el pie ofrece «Expulsar». Mira las unidades,
        # no la red: es un stat por letra.
        try:
            vista["expulsion"] = cifrado.expulsion()
        except Exception:                            # noqa: BLE001
            vista["expulsion"] = None
        # La raíz cifrada de un equipo no se expulsa: se bloquea, y lo hace el
        # agente residente (`cifrado.bloqueo`).
        try:
            vista["bloqueo"] = cifrado.bloqueo()
        except Exception:                            # noqa: BLE001
            vista["bloqueo"] = None
        # Una carpeta de este equipo no se quita: con llavero no hay «Expulsar».
        try:
            vista["del_equipo"] = model.es_equipo()
        except Exception:                            # noqa: BLE001
            vista["del_equipo"] = False
        # Qué hace este equipo al enchufar el dispositivo. Solo lee ficheros del
        # equipo (ver `watch.resumen`), así que también cabe en el primer pintado.
        try:
            vista["vigilante"] = watch.resumen()
        except Exception:                            # noqa: BLE001
            vista["vigilante"] = watch.Resumen("no_disponible")
        # Cómo está el llavero, si lo lleva: ficheros del dispositivo y una foto
        # de los procesos del equipo (si su KeePassXC está abierto), sin red.
        try:
            vista["llavero"] = llavero_editor.linea(vista["config"])
        except Exception:                            # noqa: BLE001
            vista["llavero"] = None

    leer_estado()

    def reajustar() -> None:
        """Repinta sin mover la ventana si no ha cambiado de tamaño.

        Lo que cambia aquí (un botón que se apaga mientras sincroniza, un chip
        que pasa a ámbar) casi nunca cambia el tamaño, y recolocar una ventana
        que la persona ha movido sería arrastrársela.
        """
        render()
        if root.visor.encajar(root):
            centrar(root)

    def recargar() -> None:
        """Relee el config, que ha cambiado bajo nuestros pies, y repinta.

        Si ha quedado ilegible se dice y se conserva el anterior en pantalla,
        que es mejor que quedarse con una ventana en blanco.
        """
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
        """Repinta y recoloca la ventana.

        La ventana no es redimensionable y va dentro de un visor, así que
        quitar o poner un bloque obliga a rehacer las dos medidas; sin esto el
        aviso nuevo aparece recortado.
        """
        render()
        root.visor.encajar(root)
        centrar(root)

    def descartar_aviso() -> None:
        """Quita el aviso de arranque, que es lo único de la ventana que se lee una vez.

        Los otros recuadros ámbar no se descartan y no deben poder hacerlo: una
        pareja que falló, un fichero en conflicto o un componente viejo son
        ESTADO del dispositivo y se van cuando se arreglan. Este cuenta un
        suceso («se ha parado el servicio que había») y una vez leído no tiene
        por qué seguir ocupando sitio.
        """
        vista["aviso"] = None
        reajustar()

    def abrir_actualizacion() -> None:
        """Abre la pantalla de actualización.

        Si se ha actualizado, aquí no se vuelve: `tk_update` relanza el
        programa y cierra esta ventana, porque este proceso tiene cargados en
        memoria los módulos que se acaban de sustituir.
        """
        if tk_update.open_dialog(root, vista["nueva"]):
            result["choice"] = None
            root.destroy()
            return
        vista["nueva"] = update.pending()
        repintar()

    def abrir_componentes() -> None:
        """Abre la pantalla para poner al día el rclone y el Python del dispositivo.

        Aquí sí se vuelve, a diferencia de la actualización del programa: lo
        que se sustituye son binarios que este proceso no tiene cargados en
        memoria, así que no hay que relanzar nada. Salvo el Python con el que
        corre esta ventana: ése lo cambia el relevo cuando se cierra y la
        reabre él.
        """
        tocado = tk_update.open_components_dialog(root, vista["componentes"])
        if tocado == tk_update.CERRAR:
            result["choice"] = None
            root.destroy()
            return
        if tocado:
            leer_estado()
        repintar()

    def mirar_version(respuesta=None) -> None:
        """Le pregunta a GitHub si hay algo nuevo.

        Va en un hilo porque la ventana ya está abierta y no puede quedarse
        quieta esperando a la red, y devuelve por `after` porque a Tk solo se
        le habla desde su propio hilo. Todo va bajo `except`: `ui.start()`
        envuelve la llamada entera a `ask()`, así que una excepción suelta aquí
        no daría un error sino un menú de consola sin explicación.

        Args:
            respuesta: Con él es un «Buscar actualizaciones» pedido a mano: se
                salta la caché de 24 h y `respuesta(texto)` recibe, desde el
                hilo de Tk, lo que hay que decirle al usuario (`update.veredicto()`),
                también si falla. Sin él es la mirada de fondo del arranque,
                que callada se queda.
        """
        def responder(nueva, texto) -> None:
            """Repinta si la versión pendiente ha cambiado y dice la respuesta."""
            # También cuando pasa a None: si la caché estaba adelantada, el
            # aviso tiene que irse, no quedarse puesto hasta la próxima vez.
            if nueva != vista["nueva"]:
                vista["nueva"] = nueva
                repintar()
            if respuesta is not None:
                respuesta(texto)

        def trabajo() -> None:
            """Pregunta a la red, en el hilo, y le pasa la respuesta a la ventana."""
            try:
                rel, motivo = update.check(force=respuesta is not None)
                nueva = update.pending()
                texto = update.veredicto(rel, motivo, update.installed_version())
            except Exception:                        # noqa: BLE001
                if respuesta is None:
                    return   # sin red no hay aviso, y no pasa nada
                nueva, texto = vista["nueva"], "No he podido mirar si hay versión nueva."
            try:
                root.after(0, responder, nueva, texto)
            except Exception:                        # noqa: BLE001
                pass         # la ventana ya se ha cerrado

        threading.Thread(target=trabajo, daemon=True).start()

    def mirar_conflictos() -> None:
        """Recorre las carpetas de verdad, sin que se note.

        Lo que se pintó al abrir sale del último escaneo; esto lo pone al día
        (conflictos que han llegado de otro dispositivo, o que se han resuelto
        a mano). Va en un hilo porque recorrer un árbol grande en un
        dispositivo USB tarda, y devuelve por `after` porque a Tk solo se le
        habla desde su hilo. Mientras sincroniza no se mira: `sync.py` ya lo
        hace al acabar.
        """
        if vista["en_curso"]:
            return
        config_ahora = vista["config"]

        def responder(cuentas) -> None:
            """Repinta si la cuenta de conflictos ha cambiado."""
            if cuentas != vista["conflictos"] and not vista["en_curso"]:
                # `leer_estado()` y no solo la cuenta nueva: los conflictos son
                # una avería más, así que la línea de «cosas que revisar» y el
                # chip de la cabecera salen de la misma revisión y hay que
                # rehacerla, o dirían uno menos de los que se acaban de ver.
                leer_estado()
                vista["conflictos"] = cuentas
                reajustar()

        def trabajo() -> None:
            """Recorre las parejas, en el hilo, y le pasa la cuenta a la ventana."""
            try:
                cuentas = conflicts.contar(conflicts.refrescar(config_ahora))
            except Exception:                        # noqa: BLE001
                return
            try:
                root.after(0, responder, cuentas)
            except Exception:                        # noqa: BLE001
                pass         # la ventana ya se ha cerrado

        threading.Thread(target=trabajo, daemon=True).start()

    def abrir_arranque() -> None:
        """Abre la pantalla del vigilante.

        Al volver relee qué hace este equipo al enchufar. Se puede haber
        instalado, cambiado de modo o quitado. Con el agente residente se abre
        «Qué hace el agente», que se lo pide por su buzón: la línea enseña lo
        pedido, que el agente aplica en unos segundos.
        """
        actual = vista["vigilante"]
        if actual.es_agente:
            modo = tk_watch.open_agente(root, actual)
            if modo is not None:
                vista["vigilante"] = watch.pedido(actual, modo)
                reajustar()
            return
        tk_watch.open_dialog(root)
        try:
            vista["vigilante"] = watch.resumen()
        except Exception:                            # noqa: BLE001
            vista["vigilante"] = watch.Resumen("no_disponible")
        reajustar()

    def abrir_reparacion() -> None:
        """Abre la pantalla donde se ve lo que está mal y se arregla.

        Se le pasan las parejas marcadas porque desde allí se puede simular una
        pasada, y lo que interesa simular es lo que se iba a sincronizar.
        """
        from . import tk_repair
        marcadas = [n for n in vista["config"].names
                    if n in vista.get("casillas", {})
                    and vista["casillas"][n].get()]
        if tk_repair.open_dialog(root, vista["config"], lanzar, marcadas):
            leer_estado()
        reajustar()

    def abrir_llavero() -> None:
        """«Abrir llavero»: KeePassXC con la base del dispositivo (`tk_llavero`).

        Al volver relee el estado: puede haber hecho una pasada, y la línea del
        llavero dice si su KeePassXC está abierto.
        """
        tk_llavero.abrir(root, vista["config"])
        leer_estado()
        reajustar()

    def abrir_ajustes() -> None:
        """Abre «Ajustes» y hace lo que digan sus apartados al cerrarlo.

        Lo que pasa dentro de cada apartado lo hace él; aquí queda lo que es de
        esta ventana: cerrarse tras actualizar el programa (sus módulos ya no
        son los de disco), releer el config tras tocar el llavero y, si se ha
        activado, lanzar su primera pasada, que sube la base o trae la del
        remoto en la ventana de salida de siempre; y releer el estado o el
        vigilante si se han tocado.
        """
        marcadas = [n for n in vista["config"].names
                    if n in vista.get("casillas", {}) and vista["casillas"][n].get()]
        hecho = tk_doctor.open_dialog(
            root, vista["config"], lanzar, buscar_version=mirar_version,
            nueva=vista["nueva"], componentes=vista["componentes"],
            vigilante=vista["vigilante"], hallazgos=vista["hallazgos"],
            marcadas=marcadas)
        if (hecho.get("actualizaciones") is True
                or hecho.get("componentes") == tk_update.CERRAR):
            result["choice"] = None
            root.destroy()
            return
        llavero = hecho.get("llavero")
        if llavero is not None:
            recargar()
            if llavero == tk_llavero.ACTIVADO:
                lanzar("Llavero: la primera pasada", [model.LLAVERO])
        elif hecho.get("reparacion") or hecho.get("componentes"):
            leer_estado()
        modo = hecho.get("arranque")
        if isinstance(modo, str):
            vista["vigilante"] = watch.pedido(vista["vigilante"], modo)
        elif modo:
            try:
                vista["vigilante"] = watch.resumen()
            except Exception:                        # noqa: BLE001
                vista["vigilante"] = watch.Resumen("no_disponible")
        vista["nueva"] = update.pending()
        reajustar()

    def expulsar() -> None:
        """Cierra el llavero, la ventana y el contenedor, para poder quitar la unidad.

        Con llavero, antes que nada se cierra (`tk_llavero.cerrar()`), también en
        un dispositivo sin cifrar: entonces termina diciendo que ya se puede
        quitar (`QUITAR_UNIDAD`).

        No desmonta este proceso: corre desde DENTRO del contenedor y mientras
        viva no se puede desmontar sin forzar. Lanza el script del vestíbulo,
        que espera a que esta ventana se haya ido, y se cierra. Con la ventana
        abierta no hay servicio en marcha (abrirla lo para), así que no queda
        nada nuestro con ficheros abiertos dentro.
        """
        script = vista.get("expulsion")
        con_llavero = vista["config"].pareja_llavero is not None
        if script is None and not con_llavero:
            return
        if script is not None:
            pregunta = ("Se cierra esta ventana y, unos segundos después, el contenedor "
                        "cifrado. Cuando VeraCrypt termine, ya puedes quitar la unidad.\n\n"
                        "Si algún otro programa tiene abierto algo de dentro, VeraCrypt "
                        "te preguntará si forzar el cierre.")
        else:
            pregunta = ("Se cierra el llavero (KeePassXC, si está abierto) y esta ventana. "
                        f"Después, quita la unidad {QUITAR_UNIDAD}.")
        if not messagebox.askokcancel(TITLE, pregunta, parent=root):
            return
        # El llavero antes que nada: KeePassXC y su proxy retienen la unidad,
        # y lo que quede sin subir se sube ahora (`keepassxc.cerrar_llavero()`).
        if con_llavero and not tk_llavero.cerrar(root, vista["config"]):
            return
        if script is None:
            messagebox.showinfo(TITLE, f"Ya puedes quitarla {QUITAR_UNIDAD}.", parent=root)
            result["choice"] = None
            root.destroy()
            return
        try:
            cifrado.lanzar_expulsion(script)
        except OSError as e:
            messagebox.showerror(TITLE, f"No he podido lanzar {script.name}: {e}",
                                 parent=root)
            return
        result["choice"] = None
        root.destroy()

    def bloquear() -> None:
        """«Bloquear» la raíz cifrada de este equipo: se lo pide al agente y se cierra.

        Con llavero, antes se cierra (`tk_llavero.cerrar()`), como al expulsar:
        KeePassXC corre desde dentro del contenedor y lo retiene. El agente
        espera a que esta ventana se haya ido (y a la pareja en curso) y
        desmonta sin `/silent`.
        """
        uid = vista.get("bloqueo")
        con_llavero = vista["config"].pareja_llavero is not None
        if uid is None or not messagebox.askokcancel(TITLE, (
                ("Se cierra el llavero (KeePassXC, si está abierto), esta ventana y "
                 if con_llavero else "Se cierra esta ventana y ")
                + "el agente cierra el contenedor cifrado. "
                "Hasta que lo desbloquees, nada de dentro se puede leer ni se "
                "sincroniza.\n\n"
                "Si algún otro programa tiene abierto algo de dentro, VeraCrypt "
                "te preguntará si forzar el cierre."), parent=root):
            return
        if con_llavero and not tk_llavero.cerrar(root, vista["config"]):
            return
        if not cifrado.pedir_bloqueo(uid):
            messagebox.showerror(TITLE, (
                "El agente de este equipo no está en marcha, y es quien cierra el "
                "contenedor. Ciérralo desde VeraCrypt."), parent=root)
            return
        result["choice"] = None
        root.destroy()

    def abrir_log(ruta) -> None:
        """Abre un log con el programa del sistema."""
        try:
            abrir(ruta)
        except OSError as e:
            messagebox.showerror(TITLE, f"No se ha podido abrir:\n\n{ruta}\n\n{e}",
                                 parent=root)

    def lanzar(titulo: str, args: list[str]) -> None:
        """Ejecuta `sync.py` en la ventana de salida SIN cerrar esta.

        La ventana de salida es hija de esta y no la bloquea; mientras corre,
        lo que tocaría el mismo estado (otra pasada, el servicio, las parejas)
        queda apagado. Al cerrarla se vuelve aquí con las horas, los chips y
        los avisos ya al día: `sync.py` acaba de escribirlos en `state/`.
        """
        vista["en_curso"] = True
        reajustar()

        def al_cerrar(_rc) -> None:
            """Relee el estado y repinta al cerrarse la ventana de salida."""
            vista["en_curso"] = False
            try:
                leer_estado()
                reajustar()
            except tk.TclError:
                pass         # se está cerrando la ventana principal entera

        output_window(titulo, orden_sync(args), parent=root,
                      subtitulo=subtitulo_sync(args), modal=False, al_cerrar=al_cerrar)

    def render() -> None:
        """Pinta la ventana entera, conservando lo marcado a mano."""
        # Lo marcado a mano se conserva al repintar: esta ventana se repinta
        # sola (vuelve una sincronización, llega el escaneo de conflictos) y
        # perder las casillas que se acaban de tocar sería un castigo por
        # esperar.
        if vista.get("casillas"):
            vista["marcadas"] = [n for n, v in vista["casillas"].items() if v.get()]
            vista["conocidas"] = list(vista["casillas"])
        for hijo in frame.winfo_children():
            hijo.destroy()

        config = vista["config"]
        names = config.names
        notes = pair_status_notes(config)
        marcas = pair_times(config)
        cuentas = {n: k for n, k in vista["conflictos"].items() if n in names}
        d_pairs, _, _ = prefs.startup_defaults(config)
        if "marcadas" in vista:
            d_pairs = [n for n in names
                       if n in vista["marcadas"] or n not in vista["conocidas"]]
        en_curso = vista["en_curso"]
        apagado = "disabled" if en_curso else "normal"
        fila = 0

        # Quién es este dispositivo y cómo está.
        arriba = ttk.Frame(frame)
        arriba.grid(row=fila, column=0, sticky="ew")
        arriba.columnconfigure(0, weight=1)
        fila += 1

        titulo = ttk.Frame(arriba)
        titulo.grid(row=0, column=0, sticky="w")
        ttk.Label(titulo, text="Sincronizar", style="Titulo.TLabel").grid(
            row=0, column=0, sticky="w")
        extremos = ttk.Frame(titulo)
        extremos.grid(row=1, column=0, sticky="w", pady=(theme.E2, 0))
        remotos = sorted({p.remote_name for p in config.pairs}) or [model.DEFAULT_REMOTE]
        for col, (icono, texto) in enumerate((("dispositivo", corto(str(model.DEVICE_ROOT))),
                                              ("nas", corto(", ".join(remotos))))):
            if col:
                ttk.Label(extremos, text="·", style="Apagado.TLabel").grid(
                    row=0, column=2, padx=theme.E2)
            marca = theme.etiqueta_icono(extremos, icono, theme.TINTA3,
                                         "mono_pequena", 14)
            marca.grid(row=0, column=col * 3, sticky="w")
            ttk.Label(extremos, text=texto, style="MonoPista.TLabel").grid(
                row=0, column=col * 3 + 1, sticky="w", padx=(theme.E1, 0))

        # El chip dice lo que se sabe sin hablar con nadie: lo que hay apuntado
        # en state/. La conexión con el remoto NO se comprueba aquí — se
        # tardaría segundos en abrir la ventana y la respuesta caducaría enseguida.
        # Es una sola cuenta, la misma que la línea de abajo y la que enseña
        # «Reparación»: tres maneras de contar lo mismo se contradicen solas.
        pendientes_chip = revision.cuenta(vista["hallazgos"])
        if en_curso:
            chip = theme.chip(arriba, "sincronizando…", "Acento.", "sync")
        elif pendientes_chip:
            chip = theme.chip(arriba, f"{pendientes_chip} que revisar"
                              if pendientes_chip > 1 else "1 que revisar",
                              "Aviso.", "warn")
        else:
            chip = theme.chip(arriba, "al día", "Ok.", "ok")
        chip.grid(row=0, column=1, sticky="ne", pady=(theme.E1, 0))

        if vista["aviso"]:
            # Con botón para descartarlo: es el único aviso que no describe un
            # estado del dispositivo sino algo que acaba de pasar. El hueco del
            # botón ya lo tiene `bloque_aviso`, que lo estrenó la actualización.
            bloque_aviso(frame, vista["aviso"], ancho=400,
                         boton=("Descartar", descartar_aviso)).grid(
                row=fila, column=0, sticky="ew", pady=(theme.E4, 0))
            fila += 1

        # Una línea y no un recuadro por cada cosa: apilados, del mismo ámbar y
        # con el mismo peso, dejaban de ser jerarquía para ser ruido. Lo que
        # dicen y lo que se hace con ello está en «Reparación»; aquí queda
        # cuántas cosas son y por dónde se va. Mientras sincroniza no se
        # enseña: no se repara bajo los pies de rclone.
        pendientes = revision.cuenta(vista["hallazgos"])
        if pendientes and not en_curso:
            aviso_linea = ttk.Frame(frame)
            aviso_linea.grid(row=fila, column=0, sticky="ew", pady=(theme.E4, 0))
            aviso_linea.columnconfigure(1, weight=1)
            fila += 1
            marca = theme.etiqueta_icono(aviso_linea, "warn", theme.AVISO)
            marca.grid(row=0, column=0, sticky="w", padx=(0, theme.E2))
            ttk.Label(aviso_linea,
                      text=("Hay 1 cosa que revisar." if pendientes == 1
                            else f"Hay {pendientes} cosas que revisar."),
                      ).grid(row=0, column=1, sticky="w")
            revisar = ttk.Button(aviso_linea, text="Reparación…",
                                 style="Quiet.TButton", command=abrir_reparacion)
            theme.boton_icono(revisar, "doctor", theme.ACENTO, theme.PAPEL)
            revisar.grid(row=0, column=2, sticky="e")

        # Hay versión nueva. Va debajo del aviso de arranque y no encima: ese
        # cuenta lo que acaba de pasar (el servicio que se ha parado) y esto
        # puede esperar.
        nueva = vista["nueva"]
        if nueva is not None:
            actual = update.installed_version() or "desconocida"
            bloque_aviso(
                frame,
                f"Hay una actualización: {nueva.tag}\nTienes la {actual}. "
                "«Actualizar…» baja la versión nueva y reabre la ventana.",
                ancho=420, icono="down", tono="Azul.",
                boton=("Actualizar…", abrir_actualizacion),
            ).grid(row=fila, column=0, sticky="ew", pady=(theme.E4, 0))
            fila += 1
        # Los componentes están anticuados. Es un `elif` y no un bloque suyo:
        # los pines viajan CON el programa, así que actualizarlo primero puede
        # mover lo que toca; ofrecer las dos cosas a la vez sería pedir el
        # mismo trabajo dos veces y en el orden malo.
        elif vista["componentes"]:
            # Sin botón si lo único pendiente es el VeraCrypt sin sello de un
            # dispositivo de antes: eso no lo arregla «Actualizar…» sino
            # «Añadir plataformas…» del instalador, y el texto ya lo dice.
            caja = bloque_aviso(
                frame,
                "Lo que lleva el dispositivo de fuera (rclone, Python, VeraCrypt) "
                "no es lo que fija esta versión:\n"
                + components.resumen(vista["componentes"]),
                ancho=420, icono="down", tono="Azul.",
                boton=(("Actualizar…", abrir_componentes)
                       if components.actualizables(vista["componentes"]) else None))
            caja.grid(row=fila, column=0, sticky="ew", pady=(theme.E4, 0))
            # Sustituir el rclone mientras sincroniza sería cambiárselo bajo los
            # pies; el módulo lo pospondría, pero es mejor no ofrecerlo siquiera.
            for hijo in caja.acciones.winfo_children():
                if isinstance(hijo, ttk.Button):
                    hijo.configure(state=apagado)
            fila += 1

        # La lista de parejas. Las casillas son las mismas para «Sincronizar
        # ahora» y «Iniciar servicio» y salen marcadas con lo del servicio
        # (`prefs`): lo que se ve marcado al abrir es lo que sincroniza el
        # servicio.
        rotulo = ttk.Frame(frame)
        rotulo.grid(row=fila, column=0, sticky="ew", pady=(theme.E5, theme.E2))
        rotulo.columnconfigure(2, weight=1)
        fila += 1
        ttk.Label(rotulo, text=theme.rotulo("Parejas"),
                  style="Rotulo.TLabel").grid(row=0, column=0, sticky="w")
        ultima = cuando(max((m for m in marcas.values() if m), default=None))
        resumen = ttk.Label(rotulo, style="Pista.TLabel")
        resumen.grid(row=0, column=3, sticky="e")
        todas = None
        if len(names) > 1:
            # El texto dice lo que hará, y cambia: se mide el más largo y se le
            # reserva el sitio, o el resumen de la derecha bailaría con cada clic.
            todas = ttk.Button(rotulo, text="Desmarcar todas", style="Quiet.TButton")
            todas.grid(row=0, column=1, sticky="w", padx=(theme.E3, 0))
            todas.update_idletasks()
            rotulo.columnconfigure(1, minsize=todas.winfo_reqwidth() + 10)

        tarjeta = ttk.Frame(frame, style="Card.TFrame", padding=(theme.E3, theme.E1))
        tarjeta.grid(row=fila, column=0, sticky="ew")
        tarjeta.columnconfigure(2, weight=1)
        fila += 1

        vars_by_name: dict[str, tk.BooleanVar] = {}

        def contar() -> None:
            """Pone el «N de M» y el texto del botón según las casillas.

            Lo llama cada casilla con su `command` y no un `trace` de la
            variable: la orden de un widget se borra con él y la de un trace
            no, así que desde Tcl seguiría sujetando esta función (y con ella
            la ventana entera y sus imágenes) hasta cerrar el intérprete.
            """
            marcadas = sum(1 for v in vars_by_name.values() if v.get())
            texto = f"{marcadas} de {len(names)}"
            if ultima:
                texto += f" · última pasada {ultima}"
            resumen.configure(text=texto)
            if todas is not None:
                todas.configure(text="Desmarcar todas" if marcadas == len(names)
                                else "Marcar todas")

        def al_marcar() -> None:
            """Actualiza el «N de M» y recuerda las parejas marcadas.

            Es lo que hace una casilla al tocarla. Se guarda en el momento, no al
            sincronizar: el servicio y el agente leen esa elección. Sin ninguna
            marcada no se guarda nada (`prefs.guardar_parejas`) y queda la
            anterior; si el dispositivo no se deja escribir, recordar no es vital.
            """
            contar()
            prefs.guardar_parejas(vista["config"],
                                  [n for n, v in vars_by_name.items() if v.get()])

        def marcar_todas() -> None:
            """Marca todas las casillas, o las desmarca si ya lo están."""
            valor = not all(v.get() for v in vars_by_name.values())
            for v in vars_by_name.values():
                v.set(valor)
            al_marcar()

        linea = 0
        for name in names:
            if linea:
                separador_fila(tarjeta, linea, 5)
                linea += 1
            var = tk.BooleanVar(value=(name in d_pairs))
            vars_by_name[name] = var
            ttk.Checkbutton(tarjeta, text=name, variable=var, command=al_marcar,
                            style="Card.Fuerte.TCheckbutton").grid(
                row=linea, column=0, sticky="w", pady=theme.E2)
            pareja = next(p for p in config.pairs if p.name == name)
            ttk.Label(tarjeta, text=pareja.mode.name, style="Card.Pista.TLabel").grid(
                row=linea, column=1, sticky="w", padx=(theme.E3, 0))
            ttk.Label(tarjeta, text=cuando(marcas.get(name)) or "—",
                      style="Card.MonoPista.TLabel").grid(row=linea, column=3,
                                                          sticky="e", padx=(theme.E3, theme.E2))
            if name in notes:
                theme.chip(tarjeta, notes[name], "Aviso.").grid(
                    row=linea, column=4, sticky="e")
            elif name in cuentas:
                # Se queda hasta que no quede ninguna copia en disco: no es un
                # suceso que se lee y se olvida, es un estado de la carpeta.
                texto = "1 conflicto" if cuentas[name] == 1 else f"{cuentas[name]} conflictos"
                theme.chip(tarjeta, texto, "Aviso.").grid(row=linea, column=4, sticky="e")
            linea += 1
        if not names:
            ttk.Label(tarjeta, text="No hay ninguna pareja configurada.",
                      style="Card.Pista.TLabel").grid(row=0, column=0, pady=theme.E3)

        if todas is not None:
            todas.configure(command=marcar_todas)
        contar()

        # El llavero, si lo lleva: cómo está la base y el botón que la abre. Es
        # de cada día, así que va aquí y no detrás del engranaje. Apagado
        # mientras sincroniza, como lo demás que toca `state/`.
        del_llavero = vista.get("llavero")
        if del_llavero is not None:
            llave = theme.linea_estado(
                frame, "llave", del_llavero.texto, llavero_editor.ABRIR,
                abrir_llavero, tono="Ambar." if del_llavero.aviso else "",
                ancho=420)
            llave.boton.configure(state=apagado if del_llavero.abrir else "disabled")
            llave.grid(row=fila, column=0, sticky="ew", pady=(theme.E4, 0))
            fila += 1

        # Las pantallas de las que se vuelve aquí.
        pantallas = ttk.Frame(frame)
        pantallas.grid(row=fila, column=0, sticky="ew", pady=(theme.E3, 0))
        pantallas.columnconfigure(1, weight=1)
        fila += 1
        # Mientras sincroniza se apaga lo que toca el mismo estado: la pantalla
        # de parejas puede apartar un baseline que rclone está usando.
        boton = ttk.Button(pantallas, text="Parejas…", style="Quiet.TButton",
                           command=lambda: (tk_pairs.open_dialog(root, vista["config"])
                                            and recargar()),
                           state=apagado)
        theme.boton_icono(boton, "parejas", theme.ACENTO, theme.PAPEL)
        boton.grid(row=0, column=0, sticky="w")
        # El engranaje, apartado a la derecha: detrás está lo que se hace de
        # tarde en tarde —la comprobación del doctor, el intervalo del
        # servicio, emparejar un móvil, las versiones—, para que esta ventana
        # no crezca con cada cosa nueva.
        ajustes = ttk.Button(pantallas, text="Ajustes…", style="Quiet.TButton",
                             command=abrir_ajustes,
                             state=apagado)
        theme.boton_icono(ajustes, "gear", theme.ACENTO, theme.PAPEL)
        ajustes.grid(row=0, column=2, sticky="e")

        vista["casillas"] = vars_by_name

        # La línea del arranque automático. Sigue encendida mientras
        # sincroniza, como el botón al que sustituye: el vigilante no toca nada
        # del dispositivo.
        vigilante = vista["vigilante"]
        dicho = watch.linea(vigilante)
        if dicho is not None:
            arranque = theme.linea_estado(
                frame, "arranque", dicho.texto, dicho.boton, abrir_arranque,
                tono="Ambar." if dicho.aviso else "", ancho=420)
            arranque.grid(row=fila, column=0, sticky="ew", pady=(theme.E4, 0))
            fila += 1
            pausa = watch.pausa(vigilante)
            if pausa is not None:
                # El vigilante no lanza nada mientras esta ventana esté abierta;
                # sin decirlo, enchufar con la ventana abierta parecería que el
                # arranque automático se ha roto. Con el agente como servicio,
                # dice además qué cambia «Pausar».
                ttk.Label(frame, text=pausa, style="Pista.TLabel",
                          wraplength=theme.medida(560), justify="left").grid(
                    row=fila, column=0, sticky="w", pady=(theme.E1, 0))
                fila += 1

        def selected() -> list[str]:
            """Devuelve las parejas con la casilla marcada, en el orden del config."""
            return [n for n in names if vars_by_name[n].get()]

        def sincronizar() -> None:
            """Lanza la pasada manual, aquí mismo.

            No escribe nada por su cuenta: las parejas ya quedaron guardadas al
            marcarlas (`al_marcar`).
            """
            sel = selected()
            if not sel:
                return  # nada marcado, nada que hacer
            args = manual_args(vista["config"], sel,
                               lambda pendientes: preguntar_resync(root, pendientes))
            lanzar("Sincronización manual", args)

        def servicio() -> None:
            """Cierra la ventana pidiendo arrancar el servicio.

            El servicio sí cierra la ventana: corre en otro proceso, sin ella,
            y quien lo arranca (y guarda las parejas marcadas) es `runsync` al
            volver de aquí. El intervalo es el guardado («Ajustes →
            Configuración»), que se lee ahora y no al pintar: se ha podido
            cambiar con la ventana abierta.
            """
            sel = selected()
            if not sel:
                return
            minutos = prefs.startup_defaults(vista["config"])[1]
            result["choice"] = Choice("daemon", tuple(sel), minutos)
            root.destroy()

        def pausa_del_agente(accion: str) -> None:
            """«Pausar», «Reanudar» o «Reanudar todo»: se lo pide al agente y sigue aquí.

            A diferencia de «Iniciar servicio», no cierra la ventana: no hay
            nada que arrancar, el agente ya es el servicio. La línea enseña lo
            pedido, que el agente aplica en unos segundos (`watch.tras_servicio`).
            """
            if not watch.pedir_servicio(accion):
                messagebox.showerror(TITLE, "No he podido dejarle la petición al "
                                            "agente.", parent=root)
                return
            vista["vigilante"] = watch.tras_servicio(vista["vigilante"], accion)
            reajustar()

        # La acción principal, en grande; sin filete encima: la separa el aire.
        pie = ttk.Frame(frame)
        pie.grid(row=fila, column=0, sticky="ew", pady=(theme.E5, 0))
        pie.columnconfigure(0, weight=1)
        ahora = ttk.Button(pie, text="Sincronizar ahora",
                           style="Grande.Primary.TButton", command=sincronizar,
                           state=apagado)
        theme.boton_icono(ahora, "sync", theme.SOBRE_ACENTO, theme.ACENTO, 16)
        ahora.grid(row=0, column=0, sticky="ew", padx=(0, theme.E2))
        # «Iniciar servicio», o, si el agente de este equipo es el servicio de
        # esta raíz, «Pausar» / «Reanudar» (`watch.boton_servicio`). Estos no
        # cierran la ventana ni tocan nada de la raíz, así que no se apagan
        # mientras sincroniza.
        del_servicio = watch.boton_servicio(vigilante)
        if del_servicio.accion == watch.INICIAR:
            ttk.Button(pie, text=del_servicio.texto, style="Grande.TButton",
                       command=servicio, state=apagado).grid(row=0, column=1)
        else:
            accion = del_servicio.accion
            al_agente = ttk.Button(pie, text=del_servicio.texto,
                                   style="Grande.TButton",
                                   command=lambda: pausa_del_agente(accion))
            theme.boton_icono(al_agente, "pausa" if accion == watch.PAUSAR else "play",
                              theme.TINTA, theme.SUPERFICIE)
            al_agente.grid(row=0, column=1)
        # Solo en un dispositivo que vive en un contenedor VeraCrypt, y apagado
        # mientras sincroniza: cerrar el contenedor en mitad de una pasada es
        # arrancarle los ficheros a rclone.
        if vista.get("bloqueo") is not None:
            boton_bloquear = ttk.Button(pie, text="Bloquear", style="Grande.TButton",
                                        command=bloquear, state=apagado)
            theme.boton_icono(boton_bloquear, "expulsar", theme.TINTA,
                              theme.SUPERFICIE)
            boton_bloquear.grid(row=0, column=2, padx=(theme.E2, 0))
        elif vista.get("expulsion") is not None or (
                vista.get("llavero") is not None and not vista.get("del_equipo")):
            # También sin VeraCrypt si lleva el llavero: hay que cerrar KeePassXC
            # y subir lo pendiente antes de quitar la unidad. Una carpeta de
            # este equipo no se quita.
            boton_expulsar = ttk.Button(pie, text="Expulsar", style="Grande.TButton",
                                        command=expulsar, state=apagado)
            theme.boton_icono(boton_expulsar, "expulsar", theme.TINTA,
                              theme.SUPERFICIE)
            boton_expulsar.grid(row=0, column=2, padx=(theme.E2, 0))

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


def aviso_fallo(fallos, al_abrir=None) -> None:
    """Enseña la ventanita que abre el servicio cuando falla un ciclo.

    Bloquea hasta que se cierra: quien la llama (`ui.avisar_fallo`) la tiene en
    su propio hilo. Es lo mínimo: qué parejas, cuándo y el log. Explicar el
    fallo es cosa de la ventana principal, que ya tiene su bloque ámbar para
    esto; aquí solo hay que conseguir que alguien se entere.

    Al cerrarse se suelta AQUÍ todo lo de Tk: lo que recuerdan `theme` e
    `icons` de este intérprete y los `PhotoImage` colgados de los widgets en
    ciclos de referencias. Si los soltara más tarde el hilo del servicio,
    borrarlos sería hablarle a Tk desde un hilo que no es el suyo.

    Args:
        fallos: Las parejas que han fallado.
        al_abrir: Se llama cuando la ventana ya se ve.
    """
    import gc
    try:
        _aviso_fallo(fallos, al_abrir)
    finally:
        gc.collect()


def _aviso_fallo(fallos, al_abrir) -> None:
    """Pinta la ventanita del fallo y espera a que se cierre."""
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

    marco = cuerpo_visible(root, padding=(theme.E5, theme.E5, theme.E5, theme.E4))
    marco.columnconfigure(0, weight=1)

    # La marca con la pastilla de aviso, la misma de la bandeja: dice de quién
    # es la ventana aunque nadie la haya abierto.
    arriba = ttk.Frame(marco)
    arriba.grid(row=0, column=0, sticky="ew")
    arriba.columnconfigure(1, weight=1)
    img = icons.marca_estado(arriba, 40, icons.AVISO, fondo=theme.PAPEL)
    if img is not None:
        marca = ttk.Label(arriba, image=img)
        marca.image = img
        marca.grid(row=0, column=0, sticky="nw", padx=(0, theme.E3))
    cabecera(arriba, "El servicio no ha podido sincronizar",
             "Sigue en marcha y lo reintentará en el próximo ciclo.",
             ancho=400, estilo="Dialogo.TLabel").grid(row=0, column=1, sticky="w")

    rotulo = ttk.Frame(marco)
    rotulo.grid(row=1, column=0, sticky="ew", pady=(theme.E4, theme.E2))
    rotulo.columnconfigure(0, weight=1)
    ttk.Label(rotulo, text=theme.rotulo("Ha fallado" if len(fallos) == 1
                                        else "Han fallado"),
              style="Rotulo.TLabel").grid(row=0, column=0, sticky="w")
    ttk.Label(rotulo, text="1 pareja" if len(fallos) == 1 else f"{len(fallos)} parejas",
              style="Pista.TLabel").grid(row=0, column=1, sticky="e")

    tarjeta = ttk.Frame(marco, style="Card.TFrame", padding=(theme.E4, theme.E1))
    tarjeta.grid(row=2, column=0, sticky="ew")
    tarjeta.columnconfigure(0, weight=1)
    for i, fallo in enumerate(fallos):
        if i:
            separador_fila(tarjeta, i * 2 - 1, 3)
        ttk.Label(tarjeta, text=fallo.pareja, style="Card.Fuerte.TLabel").grid(
            row=i * 2, column=0, sticky="w", pady=theme.E2)
        ttk.Label(tarjeta, text=cuando_sello(fallo.cuando) or "—",
                  style="Card.MonoPista.TLabel").grid(row=i * 2, column=1, sticky="e",
                                                      padx=(theme.E3, theme.E3))
        theme.chip(tarjeta, "falló", "Peligro.", "alert", solido=True).grid(
            row=i * 2, column=2, sticky="e")

    def ver(ruta) -> None:
        """Abre un log; sin visor, no pasa nada."""
        try:
            abrir(ruta)
        except OSError:
            pass         # sin visor no hay log que enseñar; la principal lo tiene

    ttk.Separator(marco).grid(row=3, column=0, sticky="ew", pady=(theme.E5, 0))
    pie = ttk.Frame(marco)
    pie.grid(row=4, column=0, sticky="ew", pady=(theme.E4, 0))
    pie.columnconfigure(1, weight=1)
    logs = [f.log for f in fallos if f.log is not None]
    if logs:
        ver_log = ttk.Button(pie, text="Ver el log" if len(logs) == 1
                             else "Abrir los logs", style="Quiet.TButton",
                             command=lambda: ver(logs[0] if len(logs) == 1
                                                 else model.LOG_DIR))
        theme.boton_icono(ver_log, "file", theme.ACENTO, theme.PAPEL)
        ver_log.grid(row=0, column=0, sticky="w")
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


def _tono(linea: str) -> str:
    """Devuelve cómo se colorea una línea de la salida.

    Es el vocabulario que ya usa `sync.py` por su salida (`=== pareja ===`, `
    ejecutando:`, `[pareja] OK.`, `[pareja] FALLÓ`), así que esta tabla se lee
    junto a los `print()` de `sync.py`: si allí cambia una fórmula, aquí deja
    de pintarse, no se rompe nada. La excepción es la de progreso, que no está
    escrita aquí sino importada (`progress.ETIQUETA`).
    """
    limpia = linea.strip()
    if not limpia:
        return "normal"
    if limpia.startswith(progress.ETIQUETA):
        return "progreso"
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
                  al_cerrar=None, veredictos: dict[int, str] | None = None) -> int | None:
    """Ejecuta una orden y muestra su salida en una ventana con desplazamiento.

    Sustituye a la consola cuando no la hay, así que la usan tanto `sync.py`
    como `penwatch.py`: recibe la orden entera y no supone a quién llama.
    Cerrar la ventana a mitad de faena corta el proceso (bisync se recupera con
    `--recover` en la siguiente pasada).

    Con `parent` se cuelga de una ventana existente en vez de crear un Tk
    nuevo: tkinter no lleva bien dos intérpretes a la vez y desde un diálogo ya
    hay uno en marcha.

    Con `modal=False` (y `parent`) no espera ni captura: vuelve enseguida con
    `None` y la ventana principal sigue viva debajo, que es lo que necesita
    para no desaparecer al sincronizar.

    Args:
        title: Qué se está haciendo.
        cmd: La orden entera.
        parent: De quién cuelga la ventana.
        subtitulo: Lo que se enseña bajo el título.
        modal: Si espera y captura hasta que se cierra.
        al_cerrar: `al_cerrar(rc)` se llama una vez, cuando la ventana se
            cierra, sea como sea.
        veredictos: Los códigos distintos de 0 que para quien llama NO son un
            error, con lo que hay que decir en su lugar: el aplicador de
            componentes sale con `update.CODIGO_RELEVO` cuando todo ha ido bien
            y falta cerrar la ventana, y leer ahí «ERROR (código 3)» hacía
            pensar lo contrario.

    Returns:
        El código de salida, o `None` si no espera.
    """
    import tkinter as tk
    from tkinter import filedialog, font as tkfont, messagebox, ttk

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        # Lo que se lee aquí es castellano (sync.py) o UTF-8 de rclone; con la
        # codificación del sistema las tildes se rompían en la propia ventana.
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    q: queue.Queue = queue.Queue()
    DONE = object()

    def reader() -> None:
        """Pasa a la cola, en el hilo, cada línea de la salida y marca el final."""
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

    # La barra de arriba: qué se está haciendo y cómo va.
    barra = ttk.Frame(root, style="Card.TFrame", padding=(theme.E4, theme.E3))
    barra.grid(row=0, column=0, columnspan=2, sticky="ew")
    barra.columnconfigure(1, weight=1)
    img = icons.get(barra, "sync", 20, theme.ACENTO, theme.SUPERFICIE)
    marca = ttk.Label(barra, style="Card.TLabel")
    if img is not None:
        marca.configure(image=img)
        marca.image = img
    marca.grid(row=0, column=0, rowspan=2, sticky="w", padx=(0, theme.E3))
    ttk.Label(barra, text=title.capitalize(), style="Card.Fuerte.TLabel").grid(
        row=0, column=1, sticky="w")
    ttk.Label(barra, text=subtitulo or " ", style="Card.MonoPista.TLabel").grid(
        row=1, column=1, sticky="w")
    estado = theme.chip(barra, "en marcha…", "Acento.", "sync")
    estado.grid(row=0, column=2, rowspan=2, sticky="e")

    # El cuerpo. `wrap="char"` y no el `none` que trae `caja_texto`: aquí no
    # hay barra horizontal, así que no ajustar sería perder el final de las
    # líneas largas (y las órdenes de rclone lo son).
    # Va en una caja con su borde, apartada del filo de la ventana: es lo que
    # se lee, y se lee como un documento, no como el fondo de la ventana.
    text = theme.caja_texto(root, width=104, height=28, state="disabled",
                            padx=theme.E3, pady=theme.E2, wrap="char")
    text.grid(row=1, column=0, sticky="nsew", padx=(theme.E4, 0), pady=(theme.E4, theme.E4))
    scroll = ttk.Scrollbar(root, command=text.yview)
    text.configure(yscrollcommand=scroll.set)
    scroll.grid(row=1, column=1, sticky="ns", padx=(0, theme.E4), pady=(theme.E4, theme.E4))

    # 104x28 son filas y columnas de texto, no píxeles: con el zoom del sistema
    # al 150 % esas 28 líneas miden más que la pantalla y la ventana nace con
    # el final fuera. No hace falta un `Visor` (el texto ya se desplaza solo):
    # basta con pedir las que caben. Se mide el resto de la ventana en vez de
    # descontar una cifra fija, igual que `Visor._tope`.
    root.update_idletasks()
    resto_x = max(0, root.winfo_reqwidth() - text.winfo_reqwidth())
    resto_y = max(0, root.winfo_reqheight() - text.winfo_reqheight())
    util_x, util_y = pantalla_util(root)
    letra = tkfont.Font(root=root, font=text.cget("font"))
    columna, linea = max(1, letra.measure("0")), max(1, letra.metrics("linespace"))
    text.configure(width=max(40, min(104, (util_x - resto_x) // columna)),
                   height=max(8, min(28, (util_y - resto_y) // linea)))

    for nombre, opciones in (
            ("normal", dict(foreground=theme.TINTA)),
            ("cabecera", dict(foreground=theme.TINTA, font=(
                theme.familia("mono"), 9, "bold"))),
            ("orden", dict(foreground=theme.TINTA3)),
            ("ok", dict(foreground=theme.OK)),
            ("aviso", dict(foreground=theme.AVISO)),
            ("fallo", dict(foreground=theme.PELIGRO, font=(
                theme.familia("mono"), 9, "bold"))),
            ("progreso", dict(foreground=theme.ACENTO))):
        text.tag_configure(nombre, **opciones)

    state = {"rc": None, "progreso": False}

    def append(line: str) -> None:
        """Añade una línea al texto, con su color.

        El progreso llega cada pocos segundos mientras dura la pareja: se
        reescribe en su sitio y no se apila. Es una línea viva por pareja, que
        al terminar se queda con la última lectura. La marca, con gravedad a la
        izquierda, se queda al principio de esa línea aunque se escriba en
        ella.
        """
        tono = _tono(line)
        text.configure(state="normal")
        if tono == "progreso" and state["progreso"]:
            text.delete("progreso-vivo", "end-1c")
        elif tono == "progreso":
            text.mark_set("progreso-vivo", "end-1c")
            text.mark_gravity("progreso-vivo", "left")
        state["progreso"] = tono == "progreso"
        text.insert("end", line, tono)
        text.see("end")
        text.configure(state="disabled")

    def guardar() -> None:
        """Se lleva la salida tal cual a un fichero.

        Los logs de rclone solo se guardan cuando algo falla, así que esta es
        la única copia de una pasada buena.
        """
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

    # El pie.
    ttk.Separator(root, orient="horizontal").grid(row=2, column=0, columnspan=2,
                                                  sticky="ew")
    pie = ttk.Frame(root, padding=(theme.E4, theme.E3))
    pie.grid(row=3, column=0, columnspan=2, sticky="ew")
    pie.columnconfigure(1, weight=1)
    guardar_btn = ttk.Button(pie, text="Guardar el log", style="Quiet.TButton",
                             command=guardar)
    theme.boton_icono(guardar_btn, "file", theme.ACENTO, theme.PAPEL)
    guardar_btn.grid(row=0, column=0, sticky="w")
    ttk.Button(pie, text="Cerrar", style="Primary.TButton",
               command=lambda: root.destroy()).grid(row=0, column=2)

    def terminado() -> None:
        """Apunta el código de salida y enseña el veredicto."""
        state["rc"] = proc.wait()
        segundos = int(time.monotonic() - arranque)
        especial = (veredictos or {}).get(state["rc"])
        bien = state["rc"] == 0 or especial is not None
        verdict = ("OK" if state["rc"] == 0 else especial if bien
                   else f"ERROR (código {state['rc']})")
        append(f"\n=== Terminado: {verdict} ===\n")
        root.title(f"{TITLE} — {title} — {verdict}")
        nuevo = theme.chip(barra, f"{'terminado' if bien else verdict} · {segundos} s",
                           "Ok." if bien else "Peligro.", "ok" if bien else "warn")
        estado.destroy()
        nuevo.grid(row=0, column=2, rowspan=2, sticky="e")

    def poll() -> None:
        """Pasa a la ventana lo que haya en la cola, cada 120 ms."""
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
        """Corta el proceso si sigue y cierra la ventana."""
        if state["rc"] is None and proc.poll() is None:
            proc.terminate()
        root.destroy()

    avisado = {"ya": False}

    def al_destruir(evento) -> None:
        """Corta el proceso y avisa a quien espera, una sola vez.

        Se llama al destruirse la ventana. Se cierra por el botón, por la X o
        porque se cierra la ventana madre: cualquiera de las tres acaba aquí y
        en las tres hay que cortar el proceso si sigue y avisar a quien espera.
        """
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
