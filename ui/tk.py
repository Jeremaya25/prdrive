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
from typing import Mapping, NamedTuple

from common import APP_NAME, model, progress, store
from common.model import Config

from . import (Choice, abrir, avisos_de_resync, cifrado, cuando_sello, icons, manual_args,
               pair_status_notes, pair_times, perf_activo, perf_al_pintar, perf_desde_inicio,
               perf_empezar, prefs, theme)

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


class TkFrontend:
    """El frontend gráfico; implementa el protocolo `ui.Frontend`."""

    def ask(self, config: Config, startup_msg: str | None) -> Choice | None:
        """Enseña la ventana principal y devuelve la elección."""
        return main_window(config, startup_msg)

    def approve_resync(self, pending: list[str],
                       carpetas: Mapping[str, str] | None = None) -> bool:
        """Pregunta en una ventana si se aprueba el `--resync` de esas parejas."""
        root = root_oculto()
        try:
            return preguntar_resync(root, pending, carpetas)
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


def preguntar_resync(parent, pending: list[str],
                     carpetas: Mapping[str, str] | None = None) -> bool:
    """Devuelve el sí/no del `--resync`, colgado de la ventana que pregunta.

    Args:
        parent: La ventana de la que cuelga.
        pending: Las parejas que lo piden.
        carpetas: Por pareja, dónde está en el remoto la copia del programa que
            subió (`ui.carpetas_del_programa()`); sale en el cuadro, que es
            cuando se puede decir.
    """
    from tkinter import messagebox
    avisos = avisos_de_resync(carpetas or {})
    aparte = "\n\n" + "\n".join(avisos) if avisos else ""
    return bool(messagebox.askyesno(
        TITLE,
        "Estas parejas requieren --resync (primera vez, baseline perdido o "
        "filtros cambiados):\n\n  " + "\n  ".join(pending) +
        "\n\nEl resync compara ambos lados y fija la referencia; no borra por "
        "diferencias." + aparte +
        "\n¿Ejecutarlo ahora? (si no, esas parejas se saltarán)",
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
    La barra horizontal, que casi ninguna pantalla necesita, se crea la primera
    vez que el contenido desborda por la derecha una mirilla que ya está a su
    tamaño (`_revisar()`); desde entonces se pone y se quita como la vertical.
    Su franja está reservada igualmente desde el principio, con el grosor de la
    vertical (en ttk son iguales), así que la ventana pide el mismo tamaño
    tenga o no la barra. No se mira antes de que el recuadro se ajuste por
    primera vez, cuando la mirilla es un tamaño de partida, ni mientras
    `encajar`/`crecer` miden el contenido, que fuerzan el reparto de las
    geometrías pendientes con la mirilla todavía a su tamaño de antes: en los
    dos casos el contenido la desborda sin que falte ninguna barra, y se
    crearía una en cada ventana cuyo contenido cambia.

    `lienzo` es un marco que hace de mirilla e `interior` va dentro colocado con
    `place`; desplazar es moverlo. No es un `Canvas` a propósito: un `Canvas`
    mapea la ventana que lleva dentro en cuanto esta pide sitio, aunque la
    ventana de arriba siga oculta, y entonces todo se coloca y se pinta una vez
    a escondidas y otra al enseñarse. Con `place` el interior tiene su tamaño
    desde el principio (lo que miden los tests y `ver()`), pero solo se mapea
    cuando la mirilla se ve, como cualquier hijo de `grid` o `pack`.

    Args:
        padre: Donde se pone el recuadro.
        ancho: El ancho de partida y el mínimo, no un tope.
        alto: El alto de partida y el mínimo, no un tope: el recuadro nunca es
            más pequeño que eso y crece con el contenido hasta donde llegue la
            pantalla.

    Attributes:
        horizontal: La barra horizontal, o `None` mientras el contenido no haya
            sido más ancho que la mirilla.
    """

    def __init__(self, padre, ancho: int | None = None, alto: int | None = None):
        """Crea el recuadro, su mirilla y la barra vertical, y engancha los eventos."""
        import tkinter as tk
        from tkinter import ttk

        self.base = (ancho, alto)
        self.marco = ttk.Frame(padre)
        self.lienzo = tk.Frame(self.marco, background=theme.PAPEL,
                               highlightthickness=0, borderwidth=0,
                               width=ancho or 200, height=alto or 150)
        self.vertical = ttk.Scrollbar(self.marco, orient="vertical",
                                      command=lambda *a: self._desplazar(1, *a))
        self.horizontal = None
        self.lienzo.grid(row=0, column=0, sticky="nsew")
        self.marco.columnconfigure(0, weight=1)
        self.marco.rowconfigure(0, weight=1)
        grosor = self.vertical.winfo_reqwidth()     # el de la horizontal es igual
        self.marco.columnconfigure(1, minsize=grosor)
        self.marco.rowconfigure(1, minsize=grosor)

        self.interior = ttk.Frame(self.lienzo)
        self.interior.place(x=0, y=0)
        self._puesto = (0, 0)          # lo último que se le dijo a `place`
        self._ajustado = False         # si `encajar`/`crecer` ya le dieron su tamaño
        self._ajustando = 0            # cuántos `encajar`/`crecer` lo están midiendo ahora
        self._capado = (False, False)  # por qué lados recortó el último ajuste (x, y)
        self._desde = [0, 0]           # cuánto está desplazado, en x y en y
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
        self._ajustado = True
        self._revisar()
        return cambia

    def _exacto(self, eje: int, natural: int, actual: int, tope: int) -> int | None:
        """Devuelve el tamaño final por un lado si se sabe sin probar, o `None`.

        Lo que sobra de la ventana por un lado solo puede menguar cuando el
        recuadro crece (un widget más ancho que el recuadro deja de mandar en
        cuanto el recuadro lo alcanza, y desde entonces el resto es constante),
        así que el tope medido con el recuadro como está nunca es mayor que el
        medido con el recuadro más grande. De ahí salen los dos casos exactos:

        - El contenido cabe y el recuadro solo crece (o se queda): cabe también
          con el tope de verdad, y el tamaño final es el natural.
        - El contenido no cabe, el último ajuste recortó ese lado (`_capado`)
          y el recuadro sigue pegado al tope: el recuadro llena la pantalla,
          manda en ese lado y el tope no se mueve al crecer. El tamaño final
          es ese tope. Pedir que siga pegado hace inofensiva una marca vieja
          (otra pantalla, un recuadro que cambió `crecer()`).

        Fuera de ahí (el primer desbordamiento por ese lado, o un recuadro que
        mengua) hay que probar con el recuadro estirado.

        Args:
            eje: 0 para el horizontal, 1 para el vertical.
            natural: Lo que pide el contenido por ese lado.
            actual: Lo que mide ahora el recuadro por ese lado.
            tope: El tope medido con el recuadro como está.
        """
        if actual <= natural <= tope:
            return natural
        if natural > tope and actual == tope and self._capado[eje]:
            return tope
        return None

    def encajar(self, ventana=None) -> bool:
        """Deja el recuadro del tamaño del contenido, o del que quepa si no cabe.

        No da al recuadro ningún tamaño que no se quede siempre que pueda
        saber el final sin probar (`_exacto()`): en Windows cada cambio de
        tamaño de la ventana repinta todos sus widgets, y estirar el recuadro
        hasta lo que pide el contenido entero (más que la pantalla, cuando
        desborda) para medir lo que sobra de la ventana es un repintado entero
        que no cambia nada. Solo cuando no se sabe (el primer desbordamiento
        por un lado, que casi siempre ocurre con la ventana sin enseñar) se
        estira ese lado, se mide y se recorta.

        Devuelve si el recuadro ha cambiado de tamaño, quepa el contenido o no:
        es cuando quien llama tiene que volver a colocar la ventana.
        """
        antes = self._medida()
        ventana = ventana or self.marco.winfo_toplevel()
        self._ajustando += 1
        try:
            natural = self._natural()
            tope = self._tope(ventana)
            final = [self._exacto(eje, natural[eje], antes[eje], tope[eje])
                     for eje in (0, 1)]
            if None in final:
                self._fijar(*(natural[eje] if final[eje] is None else final[eje]
                              for eje in (0, 1)))
                tope = self._tope(ventana)
                final = [min(natural[eje], tope[eje]) if final[eje] is None else final[eje]
                         for eje in (0, 1)]
        finally:
            self._ajustando -= 1
        self._capado = (natural[0] > final[0], natural[1] > final[1])
        self._fijar(*final)
        return self._medida() != antes

    def crecer(self, ventana=None) -> bool:
        """Agranda el recuadro si lo de ahora pide más, y no lo encoge nunca.

        Es lo que necesita un asistente: el hueco tiene que valer para el paso
        más grande y una ventana que menguara y creciera a cada paso sería un
        baile. Devuelve si ha cambiado de tamaño, que es cuando quien llama
        tiene que volver a colocarla.
        """
        ventana = ventana or self.marco.winfo_toplevel()
        self._ajustando += 1
        try:
            pide_x, pide_y = self._natural()
            hay_x, hay_y = self._medida()
            tope_x, tope_y = self._tope(ventana)
        finally:
            self._ajustando -= 1
        quiere = (max(hay_x, pide_x), max(hay_y, pide_y))
        self._capado = (quiere[0] > tope_x, quiere[1] > tope_y)
        return self._fijar(min(quiere[0], tope_x), min(quiere[1], tope_y))

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
        desde = self._desde[1]
        if abajo > desde + alto:
            desde = abajo - alto
        elif arriba < desde:
            desde = arriba
        else:
            return
        self._mover(1, desde)

    def desplazado(self) -> tuple[int, int]:
        """Devuelve cuánto está desplazado el contenido, en píxeles: `(x, y)`."""
        return (self._desde[0], self._desde[1])

    def _hueco(self) -> tuple[int, int]:
        """Devuelve lo que se ve del contenido: el tamaño pedido o el real, el mayor."""
        ancho, alto = self._medida()
        return (max(ancho, self.lienzo.winfo_width()),
                max(alto, self.lienzo.winfo_height()))

    def _mover(self, eje: int, desde: float) -> None:
        """Desplaza el contenido a `desde` píxeles en ese eje y avisa a su barra.

        Args:
            eje: 0 para el horizontal, 1 para el vertical.
            desde: Dónde empieza lo que se ve; se recorta a lo que hay.
        """
        total, hueco = self._puesto[eje], self._hueco()[eje]
        desde = int(round(max(0.0, min(desde, total - hueco))))
        if desde != self._desde[eje]:
            self._desde[eje] = desde
            self.interior.place_configure(x=-self._desde[0], y=-self._desde[1])
        barra = self.vertical if eje else self.horizontal
        if barra is not None and total > 0:
            barra.set(desde / total, min(1.0, (desde + hueco) / total))

    def _desplazar(self, eje: int, *orden) -> None:
        """Hace lo que pide una barra: `moveto <fracción>` o `scroll <n> units|pages`.

        Como en un `Canvas`: una unidad es la décima parte de lo que se ve y
        una página, nueve décimas.
        """
        if not orden:
            return
        if orden[0] == "moveto":
            self._mover(eje, float(orden[1]) * self._puesto[eje])
        elif orden[0] == "scroll":
            paso = self._hueco()[eje] * (0.9 if orden[2].startswith("page") else 0.1)
            self._mover(eje, self._desde[eje] + int(orden[1]) * max(1, int(paso)))

    def barras(self) -> tuple[bool, bool]:
        """Indica qué barras están puestas: `(vertical, horizontal)`.

        La horizontal cuenta como puesta solo si existe y está en la rejilla;
        una que se quitó porque dejó de hacer falta sigue existiendo y no cuenta.
        """
        return (bool(self.vertical.grid_info()),
                self.horizontal is not None and bool(self.horizontal.grid_info()))

    def _revisar(self) -> None:
        """Enseña cada barra solo si por ese lado sobra contenido.

        El interior se estira hasta llenar el hueco cuando no sobra, para que
        un formulario colocado con `sticky='ew'` siga ocupando todo el ancho; y
        solo se le habla cuando la medida cambia, porque redimensionarlo
        dispara otro `<Configure>` y con él se volvería aquí sin parar.

        La barra horizontal se crea aquí, la primera vez que hace falta con la
        mirilla ya a su tamaño, con la misma forma que si hubiera nacido con
        el recuadro; su estilo ya lo dejó puesto `theme.apply()`, así que
        crearla con la ventana enseñada no toca ningún estilo de ttk.
        """
        ancho, alto = self._hueco()
        pide_x = self.interior.winfo_reqwidth()
        pide_y = self.interior.winfo_reqheight()
        medida = (max(ancho, pide_x), max(alto, pide_y))
        if medida != self._puesto:
            self._puesto = medida
            self.interior.place_configure(width=medida[0], height=medida[1])
        if (pide_x > ancho and self.horizontal is None
                and self._ajustado and not self._ajustando):
            from tkinter import ttk
            self.horizontal = ttk.Scrollbar(self.marco, orient="horizontal",
                                            command=lambda *a: self._desplazar(0, *a))
        for eje in (0, 1):                  # lo que sobraba puede haber menguado
            self._mover(eje, self._desde[eje])
        # Puesta o no en la rejilla, no `winfo_ismapped()`: una ventana todavía
        # oculta —y todas nacen ocultas, ver `modal()`— no tiene nada mapeado, y
        # con eso la barra se pondría cada vez y no se quitaría nunca.
        for barra, falta, sitio in (
                (self.vertical, pide_y > alto, dict(row=0, column=1, sticky="ns")),
                (self.horizontal, pide_x > ancho, dict(row=1, column=0, sticky="ew"))):
            if barra is None:
                continue
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
        self._desplazar(1, "scroll", -1 if arriba else 1, "units")
        return "break"


def cuerpo_visible(ventana, directo: bool = False, **opciones):
    """Devuelve el marco donde se dibuja una pantalla, ya dentro de un `Visor`.

    Sustituye al `ttk.Frame(ventana, padding=…)` + `.grid(sticky='nsew')` que
    hacían todos los diálogos. La única diferencia visible es que, cuando la
    pantalla es pequeña, el contenido se desplaza en vez de quedarse fuera. El
    visor queda colgado de la ventana para que `mostrar()` lo encaje al
    enseñarla, sin que cada diálogo tenga que acordarse.

    Args:
        ventana: La ventana donde se pone el `Visor`.
        directo: Si se da, la pantalla se dibuja en el `interior` del `Visor` y
            no en un marco más: las opciones van a `interior.configure()` y no
            se le dan pesos a sus columnas ni a sus filas, que son de quien
            dibuja (el marco de siempre sí estira su celda). Es un widget
            menos para las ventanas que tienen pocos.
        **opciones: Las del marco (`padding=…`).

    Returns:
        El marco, o el `interior` del `Visor` con `directo`.
    """
    from tkinter import ttk
    visor = Visor(ventana)
    visor.marco.grid(row=0, column=0, sticky="nsew")
    ventana.columnconfigure(0, weight=1)
    ventana.rowconfigure(0, weight=1)
    ventana.visor = visor
    if directo:
        visor.interior.configure(**opciones)
        return visor.interior
    visor.interior.columnconfigure(0, weight=1)
    visor.interior.rowconfigure(0, weight=1)
    marco = ttk.Frame(visor.interior, **opciones)
    marco.grid(row=0, column=0, sticky="nsew")
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
    ventana que no está visible, y por eso `ensenar()` lleva detrás un
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
    ensenar(dlg)
    dlg.update_idletasks()
    try:
        dlg.grab_set()
    except tk.TclError:
        pass
    # Con PRDRIVE_PERF, el momento que declaró quien abrió el diálogo acaba aquí, en su pintado.
    momento = getattr(dlg, "perf_momento", None)
    if momento:
        perf_al_pintar(dlg, momento)
    dlg.wait_window()


DWMWA_CLOAK = 13
"""El atributo de DWM que encubre una ventana: existe, se mapea y se pinta, pero no se compone."""


def _atributo_dwm(hwnd: int, atributo: int, valor: int) -> bool:
    """Le pone a una ventana de nivel superior un atributo de DWM de 4 bytes.

    Es la única llamada a dwmapi y un punto de indirección: los tests la
    sustituyen, porque `ctypes.WinDLL` solo existe en Windows.

    Args:
        hwnd: El envoltorio de la ventana (`wm frame`).
        atributo: Un `DWMWA_*`.
        valor: Un BOOL o un COLORREF; los dos caben en un int.

    Returns:
        Si DWM lo aceptó (`S_OK`). Un atributo que su versión no conoce lo
        rechaza (`E_INVALIDARG`).
    """
    import ctypes
    from ctypes import wintypes
    poner = ctypes.WinDLL("dwmapi", use_last_error=True).DwmSetWindowAttribute
    # El BOOL de Win32 es un int de 4 bytes; el de wintypes es un c_long, que
    # solo mide 4 en Windows.
    poner.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.POINTER(ctypes.c_int),
                      wintypes.DWORD]
    poner.restype = ctypes.c_long                   # HRESULT
    dato = ctypes.c_int(valor)
    return poner(hwnd, atributo, ctypes.byref(dato), ctypes.sizeof(dato)) == 0


def _encubrir(hwnd: int, encubierta: bool) -> bool:
    """Encubre o descubre una ventana de nivel superior de Windows (`DWMWA_CLOAK`).

    Es un punto de indirección: los tests de `ensenar()` la sustituyen.

    Returns:
        Si DWM lo aceptó (`S_OK`; Windows 8 en adelante).
    """
    return _atributo_dwm(hwnd, DWMWA_CLOAK, 1 if encubierta else 0)


def _poner_barra(hwnd: int) -> None:
    """Pide a DWM la barra de título del tema; lo que rechace se queda como estaba."""
    for atributo, valor in theme.barra_titulo():
        try:
            _atributo_dwm(hwnd, atributo, valor)
        except Exception:                               # noqa: BLE001
            pass


def ensenar(ventana) -> None:
    """Enseña una ventana retirada (`deiconify`) cuando ya está pintada entera.

    En Windows cada widget de Tk es una ventana del sistema y se pinta cuando
    le llega su `WM_PAINT`, uno detrás de otro: con los controles dibujados
    (piezas de imagen) eso se veía como una pantalla que se iba rellenando
    widget a widget. Así que la ventana se enseña **encubierta** por DWM
    (`DWMWA_CLOAK`: el sistema la da por visible, la mapea y le manda pintar,
    pero no la compone en pantalla), se procesa todo lo pendiente
    (`update()`) y solo entonces se descubre, ya entera.

    El manejador es el de `wm frame`, como en `proteger_de_capturas()`; si Tk
    aún no ha creado su envoltorio, o DWM no acepta el atributo, se enseña
    sin más. Fuera de Windows es un `deiconify()`.

    **Aquí se pone también la barra de título del tema** (`theme.barra_titulo()`),
    antes de enseñarla, y no al crear la ventana: los atributos de DWM son del
    envoltorio, y `transient()` y `resizable()`, que llevan todas las ventanas,
    lo destruyen y crean otro (`UpdateWrapper`), con la barra clara. Por la
    misma razón no se toca el estilo de una ventana después de enseñarla. Que
    falle la barra no impide enseñar la ventana.
    """
    hwnd = None
    if IS_WIN:
        try:
            ventana.update_idletasks()
            marco = int(ventana.wm_frame(), 16)
            if marco != int(ventana.winfo_id()):
                _poner_barra(marco)
                if _encubrir(marco, True):
                    hwnd = marco
        except Exception:                               # noqa: BLE001
            hwnd = None
    ventana.deiconify()
    if hwnd is None:
        return
    try:
        ventana.update()
    except Exception:                                   # noqa: BLE001
        pass                            # cerrada mientras se pintaba: nada que enseñar
    finally:
        try:
            _encubrir(hwnd, False)
        except Exception:                               # noqa: BLE001
            pass


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



TONOS_RESULTADO = {"ok": "Verde.", "peligro": "Rojo.", "aviso": "Ambar.", "info": "Azul."}
"""El tono del aviso de cada clase de resultado (`Resultado.poner`)."""


class Resultado:
    """El hueco donde se dice cómo ha ido algo: nada, una pista o un aviso.

    Es el `Notice` del diseño debajo de un botón de acción («Instalado: …»,
    «No se ha podido…»). Con `tono` vacío es una pista gris de una línea, para
    lo que solo informa («Se sigue sin llavero»); con tono es el aviso con
    baldosa: la primera línea es el título y el resto el cuerpo. Se rehace en
    cada `poner()`, así que el marco se coloca una vez y ya está.

    Args:
        parent: Dónde va.
        ancho: Dónde se corta el texto, en medidas del diseño.

    Attributes:
        marco: El marco, para colocarlo.
        tono: El de lo último que se ha puesto (`''` sin nada).
        texto: Lo último que se ha puesto.
    """

    def __init__(self, parent, ancho: int = 720) -> None:
        from tkinter import ttk
        self.marco = ttk.Frame(parent)
        self.marco.columnconfigure(0, weight=1)
        self.ancho = ancho
        self.tono = ""
        self.texto = ""

    def grid(self, **opciones):
        """Coloca el marco, como un widget."""
        self.marco.grid(**opciones)
        return self

    def poner(self, texto: str, tono: str = "", icono: str | None = None) -> None:
        """Pone ese texto, con el aviso de ese tono (`ok`, `peligro`, `aviso`, `info`).

        `icono` cambia el glifo de la baldosa, que si no es el del tono.
        """
        from tkinter import ttk
        for hijo in self.marco.winfo_children():
            hijo.destroy()
        self.texto, self.tono = texto, tono
        if not texto:
            return
        if not tono:
            ttk.Label(self.marco, text=texto, style="Pista.TLabel", justify="left",
                      wraplength=theme.medida(self.ancho)).grid(row=0, column=0,
                                                                sticky="w")
            return
        bloque_aviso(self.marco, texto, ancho=self.ancho - 80, icono=icono,
                     tono=TONOS_RESULTADO[tono]).grid(row=0, column=0, sticky="ew")

    def quitar(self) -> None:
        """Deja el hueco vacío."""
        self.poner("")


ESTADO_CHIP = {True: "Ok.", False: "Peligro.", None: "Apagado.", "aviso": "Aviso."}
"""El tipo de chip de cada estado de una fila de `tabla_estado`."""


def tabla_estado(parent, filas, palabras=("bien", "falla", "sin comprobar", "aviso"),
                 ancho_nombre: int = 170):
    """Devuelve una tarjeta con una fila por comprobación: nombre, chip y detalle.

    Es la tabla de «Comprobaciones» y de «Verificación» del diseño: lo que se
    lee de un vistazo es el chip (verde, rojo, gris sin comprobar o ámbar); el
    detalle va al lado, en tinta suave.

    Args:
        filas: `(nombre, estado, detalle)`; el estado es `True`, `False`,
            `None` (sin comprobar) o `'aviso'`.
        palabras: Lo que dice el chip en cada estado, en ese orden.
    """
    from tkinter import ttk

    from . import icons
    tarjeta = ttk.Frame(parent, style="Card.TFrame", padding=(theme.E4, theme.E1))
    tarjeta.columnconfigure(2, weight=1)
    tarjeta.columnconfigure(0, minsize=icons.px(parent, ancho_nombre))
    dicho = dict(zip((True, False, None, "aviso"), palabras))
    for i, (nombre, estado, detalle) in enumerate(filas):
        if i:
            separador_fila(tarjeta, 2 * i - 1, 3)
        ttk.Label(tarjeta, text=nombre, style="Card.Fuerte.TLabel").grid(
            row=2 * i, column=0, sticky="w", pady=theme.E3)
        theme.chip(tarjeta, dicho[estado], ESTADO_CHIP[estado]).grid(
            row=2 * i, column=1, sticky="w", padx=(theme.E3, theme.E3))
        ttk.Label(tarjeta, text=detalle, style="Card.Pista.TLabel", justify="left",
                  wraplength=theme.medida(480)).grid(row=2 * i, column=2, sticky="w")
    return tarjeta

def separador_fila(parent, fila: int, columnas: int, superficie: str = "Card."):
    """Pone la línea fina entre dos filas de una lista dibujada a mano."""
    from tkinter import ttk
    est = "Card.TSeparator" if superficie == "Card." else "TSeparator"
    ttk.Separator(parent, orient="horizontal", style=est).grid(
        row=fila, column=0, columnspan=columnas, sticky="ew")


class CeldaChip(NamedTuple):
    """Una celda de `Tabla` que es un chip (`theme.chip`)."""
    texto: str
    tipo: str = ""
    icono: str | None = None


class CeldaIcono(NamedTuple):
    """Una celda de `Tabla` que es un icono; `texto` es lo que dice para quien no lo ve."""
    nombre: str
    texto: str = ""


class CeldaTexto(NamedTuple):
    """Una celda de `Tabla` con texto en un rol (`'Fuerte.'`, `'Mono.'`, `'MonoPista.'`…)."""
    texto: str
    rol: str = ""


class FilaTabla(NamedTuple):
    """Una fila de `Tabla`.

    Args:
        iid: Cómo se la llama al elegirla.
        celdas: Una por columna: un texto, `CeldaTexto`, `CeldaChip` o `CeldaIcono`.
        tono: `''`, `'aviso'` (fondo ámbar), `'peligro'` (fondo rojo), `'propio'`
            (fondo del acento) o `'apagado'` (todo el texto en gris).
    """
    iid: str
    celdas: tuple
    tono: str = ""


class Tabla:
    """Una tabla dibujada: cabecera en rótulos y una fila por elemento.

    Es la `Table` del diseño. No es una `ttk.Treeview` porque las celdas llevan
    chips e iconos y una lista de Tk no sabe pintar nada dentro de una celda:
    se dibuja en un solo lienzo (`tk_tabla.TablaLienzo`), con una tarjeta, los
    rótulos de la cabecera y, por fila, rectángulos, textos e imágenes. Las
    celdas no son widgets: en Windows cada widget es una ventana del sistema
    que se crea, se coloca y se pinta por su cuenta, y así la tabla es un solo
    widget, lleve las filas que lleve.

    Se ve como una rejilla de etiquetas de ttk (mismas medidas, huecos y
    colores; lo que lo asegura es `tests/test_tk_tabla.py`). Frente a la lista
    de «Parejas», que es la misma pieza, tiene dos diferencias: nada se corta
    con «…» (cada columna mide lo que su contenido más ancho; la que estira se
    queda con lo que sobra) y la fila que tiene el ratón encima no se tiñe. Si
    se le da `al_elegir`, las filas se eligen con un clic o con las flechas, y
    la elegida va en el azul suave del acento; sin él no hay nada que elegir ni
    toma el foco. La rueda no es suya: la recoge la pantalla (el `Visor`).

    Args:
        parent: Dónde va.
        columnas: `(titulo, ancho, estira)` por columna; el ancho es el mínimo,
            en medidas del diseño.
        al_elegir: Lo que se llama, sin argumentos, al elegir otra fila; sin
            él, no se elige.
        vacio: Lo que se dice cuando no hay ninguna fila.
        alto_fila: El alto mínimo de cada fila, en medidas del diseño: 36 la
            de una lista, 30 la de una tabla larga que solo se lee.

    Attributes:
        marco: Lo que se coloca (`grid()`): el lienzo, que no tiene ningún
            widget dentro.
        filas: Por `iid`, el texto de cada celda de la fila (de un icono, lo
            que dice para quien no lo ve).
        orden: Los `iid`, de arriba abajo.
        elegida: El `iid` de la fila elegida, o `None`.
        cabeceras: Los títulos de las columnas.
        n: Cuántas columnas tiene.
    """

    def __init__(self, parent, columnas, al_elegir=None, vacio: str = "",
                 alto_fila: int = 36):
        from .tk_tabla import TablaLienzo
        self.vacio, self.alto_fila = vacio, alto_fila
        self.n = len(columnas)
        self.cabeceras = [titulo for titulo, _ancho, _estira in columnas]
        self._lienzo = TablaLienzo(parent, columnas, al_elegir=al_elegir, vacio=vacio,
                                   alto_fila=alto_fila, rejilla=True, encima=False)
        self.marco = self._lienzo.marco
        self.filas: dict[str, list[str]] = {}
        self._lienzo.poner([])      # sin filas aún, ya pide lo que ocupa su cabecera

    @property
    def al_elegir(self):
        """Lo que se llama al elegir otra fila (se puede cambiar)."""
        return self._lienzo.al_elegir

    @al_elegir.setter
    def al_elegir(self, funcion) -> None:
        self._lienzo.al_elegir = funcion

    @property
    def orden(self) -> list[str]:
        """Los `iid`, de arriba abajo."""
        return self._lienzo.orden

    @property
    def elegida(self) -> str | None:
        """El `iid` de la fila elegida, o `None`."""
        return self._lienzo.elegida

    @property
    def momento_elegir(self) -> str | None:
        """Nombre del momento de `PRDRIVE_PERF` que se anota al elegir una fila; `None`, ninguno."""
        return self._lienzo.momento_elegir

    @momento_elegir.setter
    def momento_elegir(self, momento: str | None) -> None:
        self._lienzo.momento_elegir = momento

    def grid(self, **opciones):
        """Coloca la tabla como un widget; devuelve la tabla."""
        self.marco.grid(**opciones)
        return self

    def poner(self, filas) -> bool:
        """Pinta estas filas (`FilaTabla`) en lugar de las de antes, tocando solo las que cambian.

        Una fila igual a la de antes no se toca; una que cambia se dibuja de
        nuevo, y solo ella. Lo dibuja la tabla en el acto, aunque la ventana
        aún no se haya enseñado.

        Returns:
            Si lo que la tabla pide (su ancho y su alto) ha cambiado.
        """
        filas = list(filas)
        cambio = self._lienzo.poner(filas)
        self.filas = {fila.iid: [celda.texto if hasattr(celda, "texto") else str(celda)
                                 for celda in fila.celdas] for fila in filas}
        return cambio

    def elegir(self, iid: str | None, avisar: bool = True) -> bool:
        """Elige esa fila (o ninguna) y lo cuenta, si `avisar`.

        Returns:
            Si la elección se ha hecho.
        """
        return self._lienzo.elegir(iid, avisar)

    def leer(self) -> list[tuple[str, ...]]:
        """Devuelve lo que se dibuja, fila a fila: el texto de cada celda."""
        return self._lienzo.leer()


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

    Un apartado de «Ajustes» que se deja no se destruye: se esconde y se
    conserva. Lo que espera o se anima no puede seguir gastando mientras tanto,
    así que una pantalla que lo hace lo pide al panel (`sondeo()`,
    `indicador()`) en vez de crearlo ella, y quien esconde o enseña el apartado
    avisa con `ocultado()` y `mostrado()`: el panel pausa y reanuda lo que
    pidió, y llama a lo que la pantalla registró con `al_ocultar()` y
    `al_mostrar()`. Un diálogo suelto no se esconde nunca y no los llama.

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
        self._sondeos: list[Sondeo] = []
        self._indicadores: list[Indicador] = []
        self._al_mostrar: list = []
        self._al_ocultar: list = []

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

    def al_mostrar(self, funcion) -> None:
        """Registra `funcion()` para cuando se vuelva a enseñar el panel (`mostrado()`)."""
        self._al_mostrar.append(funcion)

    def al_ocultar(self, funcion) -> None:
        """Registra `funcion()` para cuando se esconda el panel (`ocultado()`)."""
        self._al_ocultar.append(funcion)

    def sondeo(self) -> Sondeo:
        """Crea un `Sondeo` colgado del marco, que el panel pausa al esconderse.

        Se cancela con el marco, como cualquier `Sondeo`, y además lo pausa
        `ocultado()` y lo reanuda `mostrado()`.
        """
        sondeo = Sondeo(self.marco)
        self._sondeos.append(sondeo)
        return sondeo

    def indicador(self, padre, ancho: int = 560) -> Indicador:
        """Crea un `Indicador` en `padre`, que el panel para al esconderse.

        Args:
            padre: Donde va la línea; quien lo pide la coloca.
            ancho: El corte de la frase, en medidas del diseño.
        """
        indicador = Indicador(padre, ancho=ancho)
        self._indicadores.append(indicador)
        return indicador

    def mostrado(self) -> None:
        """Reanuda lo que `ocultado()` paró y llama a los `al_mostrar`.

        Lo llama quien vuelve a enseñar el apartado, nunca al dibujarlo por
        primera vez.
        """
        for sondeo in self._sondeos:
            sondeo.seguir()
        for indicador in self._indicadores:
            indicador.seguir()
        for funcion in list(self._al_mostrar):
            funcion()

    def ocultado(self) -> None:
        """Pausa los sondeos e indicadores del panel y llama a los `al_ocultar`.

        Lo llama quien esconde el apartado sin destruirlo. Un sondeo pausado
        conserva su encargo y lo recoge al `mostrado()`.
        """
        for sondeo in self._sondeos:
            sondeo.pausar()
        for indicador in self._indicadores:
            indicador.pausar()
        for funcion in list(self._al_ocultar):
            funcion()

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


PASO_BARRA_MS = 32
"""Milisegundos entre dos pasos de la barra sin cifra.

Con 12 la barra gastaba el 10,6 % de un núcleo, y con 48 el 2,6 %, pero a 48
(21 pasos por segundo) se la veía ir a saltos. 32 son unos 31 por segundo:
fluida a la vista y con la tercera parte de los pasos de antes.
"""
SALTO_BARRA = PASO_BARRA_MS / 12
"""Cuánto avanza la barra sin cifra en cada paso, de un máximo de 100.

Es proporcional al intervalo, así que barre a la velocidad de siempre (un
vaivén cada 1,2 s, el de saltos de 1 cada 12 ms), con menos pasos y más grandes.
"""


def _arrancar_barra(barra) -> None:
    """Pone a ir y venir una barra sin cifra, a `PASO_BARRA_MS` y `SALTO_BARRA`.

    `ttk::progressbar start` acepta el salto como segundo argumento
    (`start ?intervalo? ?salto?`) y tkinter solo deja darle el intervalo, así que
    se llama a Tcl directamente. Un Tk que solo admitiera el intervalo la
    arranca igual, a saltos de 1: más despacio, pero va.
    """
    import tkinter as tk
    try:
        barra.tk.call(str(barra), "start", PASO_BARRA_MS, SALTO_BARRA)
    except tk.TclError:
        barra.start(PASO_BARRA_MS)


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
            _arrancar_barra(barra)
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
    _arrancar_barra(barra)
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

    Es la mitad de Tk de un `Encargo`: mira cada `cada` milisegundos si ha
    terminado y, cuando termina, llama a quien lo esperaba desde este hilo,
    nunca desde el del trabajo. Hay uno por pantalla y espera un encargo cada
    vez: uno nuevo deja sin respuesta al anterior.

    Si la pantalla se cierra antes, la espera se cancela con ella
    (`after_cancel`) y nadie pinta en widgets que ya no existen. Sin eso, el
    `after` pendiente llamaría a una orden que Tk ya ha borrado con la ventana.

    Una pantalla que se esconde sin cerrarse (un apartado de «Ajustes» que se
    conserva) lo pausa con `pausar()`: no deja ningún `after` pendiente, pero
    guarda el encargo y a quien lo esperaba, y `seguir()` los retoma. Mientras
    está pausado no programa ninguna mirada: un encargo nuevo sin terminar
    espera a `seguir()`.

    Args:
        ventana: La pantalla de la que cuelga la espera.
        cada: Milisegundos entre dos miradas al encargo.

    Attributes:
        cada: Lo mismo que el argumento.
    """

    def __init__(self, ventana, cada: int = SONDEO_MS) -> None:
        """Engancha la espera al cierre de la ventana."""
        self.ventana = ventana
        self.cada = cada
        self._id = None
        self._encargo = None
        self._al_llegar = None
        self._pausado = False
        ventana.bind("<Destroy>", self._al_destruir, add="+")

    @property
    def esperando(self) -> bool:
        """Indica si hay un encargo pendiente de recoger, esté pausado el sondeo o no."""
        return self._encargo is not None

    def esperar(self, encargo, al_llegar) -> None:
        """Llama a `al_llegar(encargo)` cuando el encargo termine.

        Si ya ha terminado, en el acto: es lo que hace que una pantalla cuyos
        tests corren el encargo en el sitio (`segundo_plano.en_el_acto`) se
        pinte entera antes de enseñarse. Con el sondeo pausado, un encargo sin
        terminar queda guardado hasta `seguir()`.
        """
        self.cancelar()
        if encargo.hecho:
            al_llegar(encargo)
            return
        self._encargo, self._al_llegar = encargo, al_llegar
        if not self._pausado:
            self._id = self.ventana.after(self.cada, self._mirar)

    def cancelar(self) -> None:
        """Deja de esperar; lo que llegue después no se recoge."""
        self._quitar_after()
        self._encargo = self._al_llegar = None

    def pausar(self) -> None:
        """Deja de mirar sin olvidar lo que espera.

        Cancela el `after` pendiente y conserva el encargo y a quien lo
        esperaba. Pausar dos veces es lo mismo que una.
        """
        self._pausado = True
        self._quitar_after()

    def seguir(self) -> None:
        """Retoma la espera: llama en el acto si el encargo ya terminó, y si no vuelve a mirar.

        Sin nada que esperar, o si ya estaba mirando, no hace nada.
        """
        self._pausado = False
        if self._encargo is None or self._id is not None:
            return
        self._mirar()

    def _quitar_after(self) -> None:
        """Cancela el `after` pendiente, si lo hay."""
        if self._id is not None:
            try:
                self.ventana.after_cancel(self._id)
            except Exception:                        # noqa: BLE001 — ya no está
                pass
            self._id = None

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
            if not self._pausado:
                self._id = self.ventana.after(self.cada, self._mirar)
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

    Una pantalla que se esconde sin cerrarse la pausa con `pausar()`: la barra
    se para, porque Tk la anima aunque nadie la vea, y la frase queda como
    está. `seguir()` la reanuda si sigue esperando.

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
        self._pausado = False

    @property
    def esperando(self) -> bool:
        """Indica si la barra está puesta."""
        return bool(self.barra.grid_info())

    def _viva(self) -> bool:
        """Indica si la barra existe todavía (su pantalla no se ha destruido)."""
        try:
            return bool(self.barra.winfo_exists())
        except Exception:                            # noqa: BLE001 — intérprete cerrado
            return False

    def pausar(self) -> None:
        """Para la barra sin tocar la frase; mientras dure, `poner()` no la arranca."""
        self._pausado = True
        if self._viva():
            self.barra.stop()

    def seguir(self) -> None:
        """Reanuda la barra si la línea sigue esperando."""
        self._pausado = False
        if self._viva() and self.esperando:
            _arrancar_barra(self.barra)

    def poner(self, texto: str, esperando: bool, tono: str = "Pista.") -> None:
        """Pone la frase y la barra; sin ninguna de las dos, quita la línea.

        Args:
            texto: Lo que dice la línea.
            esperando: Si la barra va y viene; con la línea pausada queda
                puesta pero parada, hasta `seguir()`.
            tono: El rol de la frase (`Pista.`, `Aviso.`, `Peligro.`).
        """
        if esperando:
            self.barra.grid()
            if not self._pausado:
                _arrancar_barra(self.barra)
        else:
            self.barra.stop()
            self.barra.grid_remove()
        self.texto.configure(text=texto, style=f"{tono}TLabel")
        if texto or esperando:
            self.marco.grid()
        else:
            self.marco.grid_remove()


PRECARGA = ("ui.tk_pairs", "ui.tk_doctor", "ui.tk_watch", "ui.tk_repair", "ui.tk_update",
            "ui.instantanea", "ui.watch", "common.conflicts")
"""Lo que la principal importa después de pintarse, en orden de uso probable.

Sale de los `import` de dentro de `main_window()`: las pantallas que abre cada
clic y, al final, lo que trae la lectura del dispositivo, que ya suele estar
cargado (lo importa el hilo de `instantanea.leer()`). Con `[keychain]` se añade
`PRECARGA_LLAVERO`. `tests/test_imports_perezosos.py` comprueba que no falta
ninguno.
"""
PRECARGA_LLAVERO = ("common.cifrada", "common.keepassxc", "ui.llavero_editor", "ui.tk_llavero")
"""Lo mismo, del llavero: en trozos de menos de 10 ms, porque `tk_llavero` arrastra a todos."""
PAUSA_PRECARGA_MS = 1
"""Milisegundos entre un import y el siguiente de `precargar_a_ratos()`."""


def precarga_de(config: Config) -> tuple[str, ...]:
    """Devuelve los módulos que la principal de ese dispositivo puede tener que importar después."""
    return PRECARGA + (PRECARGA_LLAVERO if config.llavero is not None else ())


def precargar(nombres: tuple[str, ...] = PRECARGA) -> None:
    """Importa ahora esos módulos, los que falten.

    Es lo que se hace antes de aplicar una actualización: `deploy_code()`
    sustituye los ficheros de uno en uno, y un módulo importado a mitad se
    leería ya nuevo junto a los viejos que están en memoria. Un fallo no se
    cuenta: si importarlo falla, fallará igual al abrir la pantalla.
    """
    from importlib import import_module

    for nombre in nombres:
        try:
            import_module(nombre)
        except Exception:                                # noqa: BLE001
            pass


def precargar_a_ratos(root, nombres: tuple[str, ...]) -> None:
    """Importa esos módulos de uno en uno, ya con la ventana enseñada.

    Un import por turno del bucle de Tk (`after`, no `after_idle`: una cadena
    de `after_idle` deja sin turno a los temporizadores mientras dura), así que
    un clic espera como mucho a un import. El primer clic en «Parejas…» ya no
    paga los 8–12 ms de los módulos de esa pantalla.

    Args:
        root: La ventana.
        nombres: Qué importar, en orden.
    """
    pendientes = list(nombres)

    def uno() -> None:
        """Importa el siguiente y deja el turno al bucle."""
        precargar((pendientes.pop(0),))
        if pendientes:
            try:
                root.after(PAUSA_PRECARGA_MS, uno)
            except Exception:                            # noqa: BLE001
                pass                                     # la ventana ya se ha cerrado

    if pendientes:
        root.after(PAUSA_PRECARGA_MS, uno)


def linea_llavero(config: Config):
    """Devuelve la línea del llavero de la principal, o `None` si el dispositivo no lo lleva.

    Solo importa `llavero_editor` (y con él KeePassXC y el llavero) cuando hay
    `[keychain]` con su pareja: la misma condición con la que `linea()` ya
    devolvía `None`.
    """
    if config.llavero is None or config.pareja_llavero is None:
        return None
    from . import llavero_editor
    return llavero_editor.linea(config)


SONDEO_INSTANTANEA_MS = 20
"""Milisegundos entre dos miradas de la principal a su lectura del dispositivo.

Menos que `SONDEO_MS`: lo que espera es el resto de su primer pintado (los
chips, «Sincronizar ahora», las líneas del pie), y mirar si ha llegado es mirar
un booleano.
"""


def main_window(config: Config, startup_msg: str | None) -> Choice | None:
    """Abre la ventana principal: qué parejas y qué hacer con ellas.

    Sincronizar y el doctor se hacen DESDE aquí, en una ventana de salida hija
    que no la cierra: al terminar se vuelve a esta con todo al día. Lo único
    que sale de la ventana es arrancar el servicio, que vive en otro proceso:
    la elección `daemon` se devuelve a `runsync`. Si el servicio de esta raíz
    es el agente del equipo, en su lugar están «Pausar» / «Reanudar», que se
    lo piden por su buzón sin cerrarla. Devuelve `None` si se cierra sin más.

    Se pinta primero con lo que se sabe sin leer el dispositivo (la config,
    `ui_prefs.json`, las horas de las pasadas, la versión pendiente de la
    caché) y lee el resto después de enseñarse, en un hilo
    (`refrescar_instantanea`): mientras, el chip es «…» y lo que necesita esa
    lectura no se puede pulsar (`principal.controles`). Lo que cambia después
    se cambia en su sitio (`tk_principal.VistaPrincipal.aplicar`), nunca se
    rehace la ventana. Para los tests y la comprobación de tiempos deja en la
    raíz `instantanea` (el encargo de la última lectura), `instantanea_lista`
    (si ya se aplicó) y `sondeo_instantanea` (el único `Sondeo` que la espera).

    Raises:
        ImportError: Si no hay tkinter.
        TclError: Si no hay entorno gráfico.
    """
    import tkinter as tk
    from functools import partial
    from tkinter import messagebox

    from common import update

    from . import principal, segundo_plano, tk_principal

    theme.nitidez()
    root = tk.Tk()  # TclError aquí si no hay display -> fallback consola
    theme.apply(root)
    icons.poner_icono(root)
    root.title(TITLE)
    root.configure(background=theme.PAPEL)
    root.resizable(False, False)
    root.withdraw()          # se enseña ya centrada, ver el final de la función
    result: dict = {"choice": None}
    # Lo que la ventana sabe. `inst` es la última lectura del dispositivo
    # (`ui.instantanea`), `None` hasta que llega; `pedido` es lo que se le ha
    # pedido al agente y la lectura aún no ve, con el número de lecturas
    # lanzadas cuando se pidió; `marcadas`, con qué nace la casilla de una
    # pareja que aparece; `ancho`, `arriba` y `abajo`, el ancho recordado de su
    # contenido y lo que ocupan lo que va encima y lo que va debajo de la lista
    # (`state/ventana.json`); `reservado`, `reservado_arriba` y `reservado_abajo`,
    # lo que se le guarda de cada uno hasta que llega la lectura, y `libera`, el
    # número de la lectura que deja libre la ventana tras una pasada.
    vista: dict = {"config": config, "aviso": startup_msg, "en_curso": False,
                   "inst": None, "pedido": None, "lecturas": 0, "compartida": None,
                   "volcado": None, "ancho": None, "reservado": 0, "arriba": None,
                   "reservado_arriba": 0, "abajo": None, "reservado_abajo": 0,
                   "libera": None}
    seleccion = prefs.SeleccionPendiente()

    def poner_nueva(nueva) -> None:
        """Apunta la release pendiente y, si la hay, la versión que lleva puesta."""
        vista["nueva"] = nueva
        vista["instalada"] = None
        if nueva is not None:
            try:
                vista["instalada"] = update.installed_version()
            except Exception:                        # noqa: BLE001
                pass

    # `nueva` es la release pendiente, si la hay. Se pregunta a la caché y no a
    # la red: es el primer pintado y tiene que ser instantáneo. Quien va a
    # GitHub es el hilo de `mirar_version()`. Bajo `except` porque `ui.start()`
    # envuelve toda la llamada a `ask()`: un estado ilegible aquí no daría un
    # error, daría un menú de consola sin explicar por qué.
    try:
        poner_nueva(update.pending())
    except Exception:                                # noqa: BLE001
        poner_nueva(None)
    vista["tiempos"] = pair_times(config)
    # Las casillas salen marcadas con lo del servicio (`prefs`): lo que se ve
    # marcado al abrir es lo que sincroniza el servicio.
    vista["marcadas"] = frozenset(prefs.startup_defaults(config)[0])

    # Dentro de un visor: la lista de parejas crece con cada pareja y la ventana
    # no puede pasar del alto de la pantalla. Con pocas parejas no se nota nada.
    frame = cuerpo_visible(root, padding=(theme.E5, theme.E5, theme.E5, theme.E4))
    frame.columnconfigure(0, weight=1)
    clave_ancho = prefs.clave_ancho(str(tk.TkVersion), float(root.tk.call("tk", "scaling")))
    vista["ancho"] = prefs.ancho_recordado(clave_ancho)
    vista["arriba"] = prefs.arriba_recordado(clave_ancho)
    vista["abajo"] = prefs.abajo_recordado(clave_ancho)
    # Uno solo para todas las lecturas: una nueva deja sin recoger la anterior.
    sondeo = Sondeo(root, cada=SONDEO_INSTANTANEA_MS)
    root.sondeo_instantanea = sondeo

    def la_compartida():
        """Devuelve la lectura que se reparte a las pantallas, creada la primera vez."""
        if vista["compartida"] is None:
            from . import instantanea
            vista["compartida"] = instantanea.Compartida()
        return vista["compartida"]

    def vigilante_actual():
        """Qué hace el arranque automático: lo pedido al agente, o lo leído; `None` sin leer."""
        if vista["pedido"] is not None:
            return vista["pedido"][1]
        return None if vista["inst"] is None else vista["inst"].vigilante

    def pedir(resumen) -> None:
        """Apunta lo que se le acaba de pedir al agente, para enseñarlo hasta que se vea."""
        vista["pedido"] = (vista["lecturas"], resumen)

    def estado_actual():
        """Devuelve lo que la ventana tiene que enseñar ahora (`principal.estado`)."""
        return principal.estado(
            vista["config"], aviso=vista["aviso"], nueva=vista["nueva"],
            instalada=vista["instalada"], tiempos=vista["tiempos"],
            marcadas=vista["marcadas"], en_curso=vista["en_curso"], inst=vista["inst"],
            vigilante=None if vista["pedido"] is None else vista["pedido"][1])

    def reajustar() -> None:
        """Cambia lo que haya cambiado y, solo si cambió de tamaño, la vuelve a encajar.

        Lo que cambia aquí (un botón que se apaga mientras sincroniza, un chip
        que pasa a ámbar) casi nunca cambia el tamaño, y recolocar una ventana
        que la persona ha movido sería arrastrársela: se centra solo si ha
        cambiado de tamaño.
        """
        if v.aplicar(estado_actual()) and root.visor.encajar(root):
            centrar(root)

    def posicion() -> tuple[int, int]:
        """Dónde está la ventana, en las coordenadas de `geometry("+x+y")`.

        Las de `wm geometry`, que son las que se le dan para moverla, y no las
        de `winfo_x`/`winfo_y`: con el marco del sistema alrededor pueden no
        coincidir, y moverla con unas leídas de las otras la desplazaría.
        """
        import re

        casa = re.fullmatch(r"\d+x\d+\+(-?\d+)\+(-?\d+)", root.geometry())
        if casa is None:                 # colocada desde la derecha o desde abajo
            return root.winfo_x(), root.winfo_y()
        return int(casa.group(1)), int(casa.group(2))

    def recolocar(ancho_antes: int, x: int, y: int) -> None:
        """Tras cambiar de tamaño con una lectura: el mismo centro y el mismo borde de arriba.

        No se vuelve a centrar entera (se acaba de ver dónde está, y la persona
        la ha podido mover): crece hacia abajo y a los dos lados por igual, y
        solo sube lo justo si su borde de abajo se saldría de la pantalla. Como
        `centrar`, el lado solo se corrige si está en la pantalla principal.

        Args:
            ancho_antes: Lo que pedía de ancho antes de la lectura.
            x: Dónde estaba (`posicion()`), antes de la lectura.
            y: Lo mismo, en vertical.
        """
        ancho, alto = root.winfo_reqwidth(), root.winfo_reqheight()
        nueva_x = x
        if ancho != ancho_antes:
            nueva_x = x - (ancho - ancho_antes) // 2
            pantalla = root.winfo_screenwidth()
            if 0 <= x < pantalla:
                nueva_x = max(0, min(nueva_x, pantalla - ancho))
        _ancho_util, alto_util = pantalla_util(root)
        nueva_y = max(0, alto_util - alto) if y + alto > alto_util else y
        if (nueva_x, nueva_y) != (x, y):
            root.geometry(f"+{nueva_x}+{nueva_y}")

    def reservar(ancho: int) -> None:
        """Guarda ese ancho al contenido, aunque pida menos (0: ninguno).

        Va en la columna del `Visor` donde `cuerpo_visible` pone el marco: lo
        que pide el marco sigue siendo lo suyo, que es lo que se recuerda.
        """
        root.visor.interior.columnconfigure(0, minsize=ancho)
        vista["reservado"] = ancho

    def asentar_ancho(recordar: bool) -> None:
        """Tras aplicar una lectura: la ventana a su ancho, y ese ancho recordado.

        Se llama recién encajada, así que lo que pide el contenido está al día.
        Si es lo reservado no se mueve nada. Si pide menos, se quita la reserva
        y se encaja otra vez: se coloca una sola vez a su ancho, como si no
        hubiera habido reserva (si pedía más, `encajar` ya lo ha hecho). Se
        escribe solo si cambia, y un dispositivo que no se deja escribir no lo
        recuerda y ya está.

        Args:
            recordar: Si se apunta. No con una lectura que falló entera: la
                ventana sin nada leído es más estrecha que la de siempre.
        """
        ancho = frame.winfo_reqwidth()
        if vista["reservado"]:
            sobra = vista["reservado"] > ancho
            reservar(0)
            if sobra:
                root.visor.encajar(root)
        if recordar and ancho != vista["ancho"]:
            vista["ancho"] = ancho
            prefs.recordar_ancho(clave_ancho, ancho)

    def reservar_arriba(alto: int) -> None:
        """Guarda ese alto a lo que va encima de la lista, aunque aún no esté (0: ninguno).

        Es lo que le falta a lo que ya hay encima (`VistaPrincipal.reservar_arriba`);
        la reserva se queda apuntada hasta que se suelta.
        """
        vista["reservado_arriba"] = v.reservar_arriba(alto)

    def asentar_arriba(recordar: bool) -> None:
        """Tras aplicar una lectura y encajar: apunta lo que ocupa lo que va encima de la lista.

        Se llama con la reserva ya suelta y la ventana recién encajada, así que
        mide lo que hay de verdad sin repintar nada. Si es lo reservado, la lista
        no se ha movido; si no, se movió una sola vez, a donde queda ahora. Se
        escribe solo si cambia (sin nada recordado, 0 es lo mismo que nada), y
        un dispositivo que no se deja escribir no lo recuerda y ya está.

        Args:
            recordar: Si se apunta. No con una lectura que falló entera: la
                ventana sin nada leído no tiene lo que la lectura pone encima.
        """
        alto = v.alto_arriba()
        if recordar and alto != (vista["arriba"] or 0):
            vista["arriba"] = alto
            prefs.recordar_arriba(clave_ancho, alto)

    def reservar_abajo(alto: int) -> None:
        """Guarda ese alto a lo que va debajo de la lista, aunque aún no esté (0: ninguno).

        Es lo que le falta a lo que ya hay (`VistaPrincipal.reservar_abajo`); la
        reserva se queda apuntada hasta que se suelta.
        """
        vista["reservado_abajo"] = v.reservar_abajo(alto)

    def asentar_abajo(recordar: bool) -> None:
        """Tras aplicar una lectura y encajar: apunta lo que ocupa lo que va debajo de la lista.

        Como `asentar_arriba`, con la reserva ya suelta y la ventana recién
        encajada: si lo medido es lo reservado, el pie no se ha movido ni la
        ventana ha cambiado de alto; si no, se movió una sola vez. Lo que se mide
        incluye «Parejas…» y «Ajustes…», que siempre están, así que sin nada
        recordado la primera lectura siempre apunta.

        Args:
            recordar: Si se apunta. No con una lectura que falló entera: la
                ventana sin nada leído no tiene las líneas que la lectura pone.
        """
        alto = v.alto_abajo()
        if recordar and alto != (vista["abajo"] or 0):
            vista["abajo"] = alto
            prefs.recordar_abajo(clave_ancho, alto)

    def llegar(numero: int, encargo) -> None:
        """Aplica la lectura que acaba de llegar y la reparte a las pantallas.

        La ventana cambia de tamaño sin centrarse otra vez (`recolocar`), y no
        se ensancha si su contenido pide el ancho reservado desde el primer
        pintado, que es el de la última vez (`asentar_ancho`); la lista
        tampoco baja si lo que la lectura pone encima ocupa lo reservado
        (`asentar_arriba`), ni el pie ni la ventana si lo que pone debajo
        ocupa lo reservado (`asentar_abajo`). Lo que se le había pedido al
        agente antes de lanzar esta lectura se olvida: ya lo cuenta ella, o lo
        contará la siguiente. La que se lanzó al cerrar una pasada (o una
        posterior) deja la ventana libre. Un hilo que falló deja una lectura
        vacía, la de una ventana sin nada que enseñar.
        """
        perf_empezar("llega-instantanea")
        from . import instantanea

        inst = encargo.resultado
        leida = encargo.error is None and inst is not None
        if not leida:
            inst = instantanea.vacia(vista["config"])
        vista["inst"] = inst
        if vista["pedido"] is not None and vista["pedido"][0] < numero:
            vista["pedido"] = None
        if vista["libera"] is not None and numero >= vista["libera"]:
            vista["en_curso"], vista["libera"] = False, None
        vista["tiempos"] = pair_times(vista["config"])
        ancho_antes, (x, y) = root.winfo_reqwidth(), posicion()
        if (v.aplicar(estado_actual()) or vista["reservado"] or vista["reservado_arriba"]
                or vista["reservado_abajo"]):
            # Las reservas de arriba y de abajo se sueltan en la misma colocación
            # que grida los bloques que llegan: con `encajar` se coloca todo de una vez.
            if vista["reservado_arriba"]:
                reservar_arriba(0)
            if vista["reservado_abajo"]:
                reservar_abajo(0)
            root.visor.encajar(root)
            asentar_ancho(leida)
            asentar_arriba(leida)
            asentar_abajo(leida)
            recolocar(ancho_antes, x, y)
        root.instantanea_lista = True
        # Lo último: un suscriptor que falla (una pantalla a medio cerrar) no
        # deja esta ventana a medias.
        la_compartida().poner(inst)
        perf_al_pintar(root, "llega-instantanea")

    def refrescar_instantanea(libera: bool = False) -> None:
        """Lee en un hilo lo que la ventana enseña del dispositivo, y lo aplica al llegar.

        Es la única lectura de averías, conflictos, componentes, contenedor,
        arranque automático y llavero de esta ventana (`instantanea.leer()`):
        la primera, tras enseñarse, y otra cada vez que algo puede haberlo
        cambiado (una pasada, «Reparación», el llavero, la config…). Una nueva
        sustituye a la que estuviera en camino, cuyo resultado se tira.

        Args:
            libera: La ventana está ocupada y deja de estarlo cuando llegue
                esta lectura, o una lanzada después (al cerrar una pasada).
        """
        from . import instantanea

        vista["lecturas"] += 1
        numero = vista["lecturas"]
        if libera:
            vista["libera"] = numero
        encargo = segundo_plano.lanzar(partial(
            instantanea.leer, vista["config"], notas=pair_status_notes,
            linea_llavero=linea_llavero))
        root.instantanea = encargo
        root.instantanea_lista = False
        sondeo.esperar(encargo, lambda hecho: llegar(numero, hecho))

    def volcar_seleccion() -> None:
        """Escribe ya la última selección de casillas, si la hay, y quita su espera."""
        if vista["volcado"] is not None:
            try:
                root.after_cancel(vista["volcado"])
            except Exception:                        # noqa: BLE001 — se está cerrando
                pass
            vista["volcado"] = None
        seleccion.volcar()

    def selected() -> list[str]:
        """Devuelve las parejas con la casilla marcada, en el orden del config."""
        return [n for n in vista["config"].names
                if n in v.casillas and v.casillas[n].get()]

    def al_marcar() -> None:
        """Pone el «N de M» y apunta la selección, sin escribirla en el clic.

        La escribe `volcar_seleccion` pasados `prefs.ESPERA_MS` sin más clics, y
        siempre antes de lanzar una pasada, de iniciar el servicio, de expulsar
        o de cerrar la ventana: el servicio y el agente leen esa elección. Sin
        ninguna marcada no se guarda nada (`prefs.guardar_parejas`) y queda la
        anterior.
        """
        perf_empezar("marcar")
        v.contar()
        seleccion.poner(vista["config"], selected())
        if vista["volcado"] is not None:
            root.after_cancel(vista["volcado"])
        vista["volcado"] = root.after(prefs.ESPERA_MS, volcar_seleccion)
        perf_al_pintar(root, "marcar")

    def marcar_todas() -> None:
        """Marca todas las casillas, o las desmarca si ya lo están."""
        valor = not all(var.get() for var in v.casillas.values())
        for var in v.casillas.values():
            var.set(valor)
        al_marcar()

    def recargar() -> None:
        """Relee el config, que ha cambiado bajo nuestros pies, y lo vuelve a leer todo.

        Si ha quedado ilegible se dice y se conserva el anterior en pantalla,
        que es mejor que quedarse con una ventana en blanco. Las parejas nuevas
        nacen marcadas; las que siguen, como estén.
        """
        try:
            nuevo = model.load_config()
        except model.ConfigError as e:
            messagebox.showerror(TITLE, f"El config no se puede leer:\n\n{e}")
            return
        conocidas = set(vista["config"].names)
        vista["marcadas"] = frozenset(selected()) | {n for n in nuevo.names
                                                     if n not in conocidas}
        vista["config"] = nuevo
        vista["aviso"] = None
        vista["tiempos"] = pair_times(nuevo)
        reajustar()
        refrescar_instantanea()

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
        from . import tk_update

        if tk_update.open_dialog(root, vista["nueva"]):
            result["choice"] = None
            root.destroy()
            return
        mirar_pendiente()

    def mirar_pendiente() -> None:
        """Vuelve a mirar en la caché la release pendiente y repinta solo si ha cambiado."""
        try:
            nueva = update.pending()
        except Exception:                            # noqa: BLE001
            return
        if nueva != vista["nueva"]:
            poner_nueva(nueva)
            reajustar()

    def abrir_componentes() -> None:
        """Abre la pantalla para poner al día el rclone y el Python del dispositivo.

        Aquí sí se vuelve, a diferencia de la actualización del programa: lo
        que se sustituye son binarios que este proceso no tiene cargados en
        memoria, así que no hay que relanzar nada. Salvo el Python con el que
        corre esta ventana: ése lo cambia el relevo cuando se cierra y la
        reabre él.
        """
        from . import tk_update

        inst = vista["inst"]
        tocado = tk_update.open_components_dialog(
            root, list(inst.componentes) if inst is not None else [])
        if tocado == tk_update.CERRAR:
            result["choice"] = None
            root.destroy()
            return
        if tocado:
            refrescar_instantanea()

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
                poner_nueva(nueva)
                reajustar()
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

        Lo que se pintó sale del último escaneo (`state/conflicts.json`); esto
        lo pone al día (conflictos que han llegado de otro dispositivo, o que se
        han resuelto a mano) y, si las cuentas no son las que se enseñan, vuelve
        a leer: los conflictos son una avería más, así que la línea de «cosas
        que revisar» y el chip de la cabecera salen de la misma lectura. Va en
        un hilo porque recorrer un árbol grande en un dispositivo USB tarda, y
        devuelve por `after` porque a Tk solo se le habla desde su hilo.
        Mientras sincroniza no se mira: `sync.py` ya lo hace al acabar.
        """
        if vista["en_curso"]:
            return
        config_ahora = vista["config"]

        def responder(cuentas) -> None:
            """Vuelve a leer si la cuenta de conflictos no es la que se enseña."""
            if vista["en_curso"]:
                return
            inst = vista["inst"]
            # Sin lectura todavía no se sabe qué se enseña: se lee otra vez.
            if inst is None or cuentas != dict(inst.conflictos):
                refrescar_instantanea()

        def trabajo() -> None:
            """Recorre las parejas, en el hilo, y le pasa la cuenta a la ventana."""
            try:
                from common import conflicts
                cuentas = conflicts.contar(conflicts.refrescar(config_ahora))
            except Exception:                        # noqa: BLE001
                return
            try:
                root.after(0, responder, cuentas)
            except Exception:                        # noqa: BLE001
                pass         # la ventana ya se ha cerrado

        threading.Thread(target=trabajo, daemon=True).start()

    def abrir_parejas() -> None:
        """Abre «Parejas…» y, si se ha guardado algo, relee el config y el estado."""
        perf_empezar("open-parejas")
        from . import tk_pairs

        if tk_pairs.open_dialog(root, vista["config"], compartida=la_compartida()):
            recargar()

    def abrir_arranque() -> None:
        """Abre la pantalla del vigilante.

        Con el agente residente se abre «Qué hace el agente», que se lo pide por
        su buzón: la línea enseña lo pedido, que el agente aplica en unos
        segundos. La del vigilante no devuelve nada y se puede haber instalado,
        cambiado de modo o quitado: al volver se lee otra vez, siempre.
        """
        from . import tk_watch

        actual = vigilante_actual()
        if actual is not None and actual.es_agente:
            modo = tk_watch.open_agente(root, actual)
            if modo is not None:
                from . import watch

                pedir(watch.pedido(actual, modo))
                reajustar()
            return
        tk_watch.open_dialog(root)
        refrescar_instantanea()

    def abrir_reparacion() -> None:
        """Abre la pantalla donde se ve lo que está mal y se arregla.

        Se le pasan las parejas marcadas porque desde allí se puede simular una
        pasada, y lo que interesa simular es lo que se iba a sincronizar.
        """
        from . import tk_repair

        if tk_repair.open_dialog(root, vista["config"], lanzar, selected(),
                                 compartida=la_compartida()):
            refrescar_instantanea()

    def abrir_llavero() -> None:
        """«Abrir llavero»: KeePassXC con la base del dispositivo (`tk_llavero`).

        Al volver se lee otra vez: puede haber hecho una pasada, y la línea del
        llavero dice si su KeePassXC está abierto.
        """
        from . import tk_llavero

        tk_llavero.abrir(root, vista["config"])
        refrescar_instantanea()

    def abrir_ajustes() -> None:
        """Abre «Ajustes» y hace lo que digan sus apartados al cerrarlo.

        Lo que pasa dentro de cada apartado lo hace él; aquí queda lo que es de
        esta ventana: cerrarse tras actualizar el programa (sus módulos ya no
        son los de disco), releer el config tras tocar el llavero y, si se ha
        activado, lanzar su primera pasada, que sube la base o trae la del
        remoto en la ventana de salida de siempre; y volver a leer el estado o
        el vigilante si se han tocado. Si no ha cambiado nada no se toca nada.
        """
        perf_empezar("open-ajustes")
        from . import tk_doctor, tk_update

        inst = vista["inst"]
        hecho = tk_doctor.open_dialog(
            root, vista["config"], lanzar, buscar_version=mirar_version,
            nueva=vista["nueva"],
            componentes=list(inst.componentes) if inst is not None else None,
            vigilante=vigilante_actual(),
            hallazgos=list(inst.hallazgos) if inst is not None else None,
            marcadas=selected(), compartida=la_compartida())
        perf_empezar("volver-ajustes")
        if (hecho.get("actualizaciones") is True
                or hecho.get("componentes") == tk_update.CERRAR):
            result["choice"] = None
            root.destroy()
            return
        releer = bool(hecho.get("reparacion") or hecho.get("componentes"))
        llavero = hecho.get("llavero")
        if llavero is not None:
            from . import tk_llavero

            recargar()                       # que ya vuelve a leer
            releer = False
            if llavero == tk_llavero.ACTIVADO:
                lanzar("Llavero: la primera pasada", [model.LLAVERO])
        modo = hecho.get("arranque")
        if isinstance(modo, str):
            actual = vigilante_actual()
            if actual is not None:
                from . import watch

                pedir(watch.pedido(actual, modo))
                reajustar()
        elif modo and llavero is None:
            releer = True
        if releer:
            refrescar_instantanea()
        mirar_pendiente()
        perf_al_pintar(root, "volver-ajustes")

    def expulsar() -> None:
        """Cierra el llavero, la ventana y el contenedor, para poder quitar la unidad.

        Con llavero, antes que nada se cierra (`tk_llavero.cerrar()`), también en
        un dispositivo sin cifrar: entonces termina diciendo que ya se puede
        quitar (`QUITAR_UNIDAD`).

        No desmonta este proceso: corre desde DENTRO del contenedor y mientras
        viva no se puede desmontar sin forzar. Lanza el script del vestíbulo,
        que espera a que esta ventana se haya ido, y se cierra. Con la ventana
        abierta no hay servicio en marcha (abrirla lo para), así que no queda
        nada nuestro con ficheros abiertos dentro. El script se busca ahora y no
        en la lectura de la ventana, que puede ser de hace rato.
        """
        try:
            script = cifrado.expulsion()
        except Exception:                            # noqa: BLE001
            script = None
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
        if con_llavero:
            from . import tk_llavero

            if not tk_llavero.cerrar(root, vista["config"]):
                return
        # Lo último que esta ventana escribe o lee en la unidad, antes de soltarla.
        volcar_seleccion()
        store.matar_hijos()
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
            # La ventana sigue abierta: lo que se leía se acaba de cortar.
            refrescar_instantanea()
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
        inst = vista["inst"]
        uid = None if inst is None else inst.bloqueo
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
        if con_llavero:
            from . import tk_llavero

            if not tk_llavero.cerrar(root, vista["config"]):
                return
        volcar_seleccion()
        store.matar_hijos()
        if not cifrado.pedir_bloqueo(uid):
            messagebox.showerror(TITLE, (
                "El agente de este equipo no está en marcha, y es quien cierra el "
                "contenedor. Ciérralo desde VeraCrypt."), parent=root)
            refrescar_instantanea()  # sigue abierta, y sus lecturas se han cortado
            return
        result["choice"] = None
        root.destroy()

    def lanzar(titulo: str, args: list[str]) -> None:
        """Ejecuta `sync.py` en la ventana de salida SIN cerrar esta.

        La ventana de salida es hija de esta y no la bloquea; mientras corre,
        lo que tocaría el mismo estado (otra pasada, el servicio, las parejas)
        queda apagado, y se enciende cuando llega la lectura que se lanza al
        cerrarla, la de lo que `sync.py` acaba de escribir en `state/`. Si la
        ventana de salida no llega a abrirse, esta vuelve a quedar libre y el
        error sigue su camino.
        Con la ventana ya enseñada (la pasada arranca en el turno siguiente) se
        escribe la última selección de casillas, si quedaba alguna sin escribir.
        """
        if not vista["en_curso"]:
            vista["en_curso"] = True
            reajustar()

        def al_cerrar(_rc) -> None:
            """Lee otra vez al cerrarse la de salida, y la ventana queda libre al llegar.

            Hasta entonces sigue ocupada, como durante la pasada: lo que se leyó
            antes (cosas que revisar, una pareja que pedía resync) puede no ser
            verdad ya, y enseñarlo otra vez para cambiarlo al llegar la lectura
            sería un parpadeo con texto viejo. Si la lectura no se puede lanzar,
            queda libre ya. Si es la principal entera la que se cierra (la de
            salida cae con ella), no hay nada que leer.
            """
            if not frame.winfo_exists():
                vista["en_curso"] = False
                return
            try:
                refrescar_instantanea(libera=True)
            except tk.TclError:
                pass         # se está cerrando la ventana principal entera
            except BaseException:
                vista["en_curso"] = False
                reajustar()
                raise
            perf_al_pintar(root, "volver-pasada")

        try:
            output_window(titulo, orden_sync(args), parent=root,
                          subtitulo=subtitulo_sync(args), modal=False, al_cerrar=al_cerrar)
            # La marca va a la principal: `output_window` no devuelve la de salida, y
            # `perf_al_pintar` solo usa la raíz de Tk, que es la misma para las dos.
            perf_al_pintar(root, "sincronizar-ventana")
        except BaseException:
            vista["en_curso"] = False
            reajustar()
            raise
        volcar_seleccion()

    def sincronizar() -> None:
        """Lanza la pasada manual, aquí mismo.

        En el clic solo se ocupa la ventana: la pregunta del resync (que lee el
        estado de las parejas en ese momento, no la lectura de la ventana) y la
        ventana de salida van en el turno siguiente, así que el botón responde
        al momento. Sin ninguna marcada no hace nada.
        """
        sel = selected()
        if not sel:
            return  # nada marcado, nada que hacer: el botón responde, y no hay pasada que medir
        # Después de la guarda: con el botón activo y nada marcado, un inicio aquí
        # quedaría abierto y la próxima pasada lo cerraría con minutos de retraso.
        perf_empezar("sincronizar-ventana")
        vista["en_curso"] = True
        reajustar()
        root.after(1, continuar, sel)

    def continuar(sel: list[str]) -> None:
        """Pregunta lo que haga falta y abre la ventana de salida de la pasada manual.

        Si algo falla antes de que la ventana de salida exista, la ventana deja
        de estar ocupada y el error sigue su camino; si la ventana se abre, sigue
        ocupada hasta que se cierre (`lanzar`).
        """
        try:
            args = manual_args(vista["config"], sel,
                               lambda pendientes, carpetas: preguntar_resync(
                                   root, pendientes, carpetas))
        except BaseException:
            vista["en_curso"] = False
            reajustar()
            raise
        lanzar("Sincronización manual", args)

    def servicio(accion: str) -> None:
        """El botón del servicio: «Iniciar servicio», o lo que se le pide al agente.

        «Iniciar servicio» cierra la ventana pidiendo arrancar el servicio: corre
        en otro proceso, sin ella, y quien lo arranca es `runsync` al volver de
        aquí. Antes se escribe la selección que quedara. El intervalo es el
        guardado («Ajustes → Configuración»), que se lee ahora y no al pintar:
        se ha podido cambiar con la ventana abierta.
        """
        if accion != principal.INICIAR:
            pausa_del_agente(accion)
            return
        sel = selected()
        if not sel:
            return
        volcar_seleccion()
        minutos = prefs.startup_defaults(vista["config"])[1]
        result["choice"] = Choice("daemon", tuple(sel), minutos)
        root.destroy()

    def pausa_del_agente(accion: str) -> None:
        """«Pausar», «Reanudar» o «Reanudar todo»: se lo pide al agente y sigue aquí.

        A diferencia de «Iniciar servicio», no cierra la ventana: no hay
        nada que arrancar, el agente ya es el servicio. La línea enseña lo
        pedido, que el agente aplica en unos segundos (`watch.tras_servicio`).
        """
        from . import watch

        if not watch.pedir_servicio(accion):
            messagebox.showerror(TITLE, "No he podido dejarle la petición al "
                                        "agente.", parent=root)
            return
        actual = vigilante_actual()
        if actual is not None:
            pedir(watch.tras_servicio(actual, accion))
            reajustar()

    def al_destruir(evento) -> None:
        """Al cerrarse la ventana: la selección que quedara, y fuera sus lecturas.

        Ningún rclone que leía para ella se queda con la unidad abierta
        (`store.matar_hijos`).
        """
        if str(evento.widget) != str(root):
            return
        volcar_seleccion()
        store.matar_hijos()

    v = tk_principal.VistaPrincipal(frame, tk_principal.Acciones(
        sincronizar=sincronizar, servicio=servicio, parejas=abrir_parejas,
        ajustes=abrir_ajustes, reparacion=abrir_reparacion, llavero=abrir_llavero,
        expulsar=expulsar, bloquear=bloquear, arranque=abrir_arranque,
        descartar=descartar_aviso, actualizar=abrir_actualizacion,
        componentes=abrir_componentes, al_marcar=al_marcar, marcar_todas=marcar_todas))
    v.aplicar(estado_actual())
    root.bind("<Destroy>", al_destruir, add="+")
    root.instantanea = None
    root.instantanea_lista = False
    # El ancho de la última vez, ya con la lectura: con él reservado, la ventana
    # se pinta ya como quedará y no se ensancha al llegar la lectura (en
    # Windows, cada fila de la lista es una ventana del sistema que se movería).
    reservar(vista["ancho"] or 0)
    # Y lo que ocupó lo que la lectura pone encima de la lista (la línea de
    # «Reparación…»): sin esto la lista, que ya está pintada, baja al llegar.
    reservar_arriba(vista["arriba"] or 0)
    # Y lo que ocupó lo que la lectura pone debajo de la lista (la línea del
    # arranque automático): sin esto el pie baja, y la ventana crece, al llegar.
    reservar_abajo(vista["abajo"] or 0)
    root.visor.encajar(root)
    centrar(root)
    ensenar(root)
    if perf_activo():
        # Desde que el proceso existe, no desde aquí: el mismo punto que el cronómetro del chequeo.
        edad = perf_desde_inicio()
        if edad is not None:
            perf_al_pintar(root, "start-main", time.perf_counter() - edad / 1000)
    # Después de enseñarla, no antes: la lectura del dispositivo, la
    # comprobación de versión y el recorrido de las carpetas no pueden retrasar
    # la apertura ni un parpadeo. La lectura va la primera, en cuanto Tk tiene
    # un momento libre.
    root.after_idle(refrescar_instantanea)
    root.after(300, mirar_version)
    root.after(300, mirar_conflictos)
    precargar_a_ratos(root, precarga_de(vista["config"]))
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
    ensenar(root)
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


LINEAS_VENTANA = 20_000
"""Líneas que conserva el texto de la ventana de la pasada.

La salida entera no se pierde: está en `_Salida.completa`, que es lo que lleva
«Guardar el log».
"""


class _Salida:
    """La salida de la ventana de la pasada: entera, y aparte del texto que se ve.

    Decide qué se inserta en el texto con cada tanda de líneas, sin Tk, para
    probarlo sin pantalla. La línea de progreso se reescribe en su sitio: varias
    seguidas son una sola, la última, también dentro de una tanda, y así lo
    mismo en el texto que en la copia entera.

    Attributes:
        completa: Las líneas tal como las guarda «Guardar el log»; las de
            progreso seguidas ya están reducidas a la última.
        viva: Si la última línea es de progreso, o sea si la siguiente de
            progreso la sustituye.
    """

    def __init__(self) -> None:
        """Empieza sin ninguna línea."""
        self.completa: list[str] = []
        self.viva = False

    def anadir(self, lineas: list[str]) -> tuple[bool, list[tuple[str, str]]]:
        """Apunta una tanda de líneas y dice qué hay que hacerle al texto.

        Returns:
            `(sustituye, trozos)`. Con `sustituye`, el texto borra antes la
            línea viva que ya tenía (de la marca `progreso-vivo` al final).
            `trozos` son `(texto, tono)` para un solo `insert`: las líneas
            contiguas del mismo tono van juntas y la de progreso va siempre
            sola.
        """
        sustituye = False
        trozos: list[tuple[str, list[str]]] = []
        for linea in lineas:
            tono = _tono(linea)
            if tono == "progreso" and self.viva:
                self.completa[-1] = linea
                if trozos:              # la viva es de esta tanda: su trozo es el último
                    trozos.pop()
                else:                   # la viva ya está en el texto
                    sustituye = True
            else:
                self.completa.append(linea)
            self.viva = tono == "progreso"
            if trozos and trozos[-1][0] == tono and tono != "progreso":
                trozos[-1][1].append(linea)
            else:
                trozos.append((tono, [linea]))
        return sustituye, [("".join(juntas), tono) for tono, juntas in trozos]


def _volcar(texto, salida: _Salida, lineas: list[str]) -> None:
    """Pasa a un `tk.Text` una tanda de líneas: un `insert` y un `see`.

    Es lo que hace `poll()` en cada vuelta con lo que haya llegado. Un `insert`
    por línea costaba 0,42 ms cada una y uno por tanda 0,01 ms. El texto se
    queda con las últimas `LINEAS_VENTANA`; `salida` guarda todas.

    Args:
        texto: El `tk.Text` de la ventana, con los tonos ya configurados.
        salida: La salida de esa ventana.
        lineas: Lo que ha llegado desde la vuelta anterior.
    """
    if not lineas:
        return
    if not salida.completa:
        perf_empezar("log-10k")          # la primera tanda: empieza el volcado de la pasada
    sustituye, trozos = salida.anadir(lineas)
    texto.configure(state="normal")
    try:
        if sustituye:
            texto.delete("progreso-vivo", "end-1c")
        texto.insert("end", *(parte for trozo in trozos for parte in trozo))
        if salida.viva:
            # Al principio de esa línea, con gravedad a la izquierda: aunque se
            # escriba en ella, la marca no se mueve. Acaba en salto de línea,
            # así que "end-1c" ya está en la siguiente; sin él, no.
            texto.mark_set("progreso-vivo", "end-2c linestart"
                           if trozos[-1][0].endswith("\n") else "end-1c linestart")
            texto.mark_gravity("progreso-vivo", "left")
        sobran = int(texto.index("end-1c").split(".")[0]) - 1 - LINEAS_VENTANA
        if sobran > 0:
            texto.delete("1.0", f"{sobran + 1}.0")
        texto.see("end")
    finally:
        texto.configure(state="disabled")


def output_window(title: str, cmd: list[str], parent=None,
                  subtitulo: str = "", modal: bool = True,
                  al_cerrar=None, veredictos: dict[int, str] | None = None) -> int | None:
    """Ejecuta una orden y muestra su salida en una ventana con desplazamiento.

    Sustituye a la consola cuando no la hay, así que la usan tanto `sync.py`
    como `penwatch.py`: recibe la orden entera y no supone a quién llama.
    Cerrar la ventana a mitad de faena corta el proceso y todo lo que cuelga de
    él (su rclone también: `store.matar_arbol()`); bisync se recupera con
    `--recover` en la siguiente pasada.

    Con `parent` se cuelga de una ventana existente en vez de crear un Tk
    nuevo: tkinter no lleva bien dos intérpretes a la vez y desde un diálogo ya
    hay uno en marcha.

    Con `modal=False` (y `parent`) no espera ni captura: vuelve enseguida con
    `None` y la ventana principal sigue viva debajo, que es lo que necesita
    para no desaparecer al sincronizar.

    La ventana se construye y se enseña antes de que exista el proceso: la
    orden se lanza en el turno siguiente (`after(1)`), cuando ya se ve. Hasta
    entonces `ventana.proceso` es `None`; después, el `Popen`. Cerrar la
    ventana antes de ese turno no lanza nada. Si la orden no se puede lanzar
    (`OSError`, o `ValueError` por argumentos no válidos), la ventana lo dice
    en su texto y acaba con el código 127, el de «orden no encontrada»: sigue
    abierta, con «Guardar el log», hasta que se cierra.

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

    q: queue.Queue = queue.Queue()
    DONE = object()

    def reader(proc) -> None:
        """Pasa a la cola, en el hilo, cada línea de la salida y marca el final."""
        assert proc.stdout is not None
        for line in proc.stdout:
            q.put(line)
        q.put(DONE)

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
    root.proceso = None      # el `Popen`, cuando `arrancar` lo lance

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

    state = {"rc": None, "arranque": time.monotonic()}
    salida = _Salida()

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
                f.write("".join(salida.completa))
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

    def terminado(rc: int, sin_lanzar: bool = False) -> None:
        """Apunta el código de salida y enseña el veredicto.

        Args:
            rc: El código de salida de la orden.
            sin_lanzar: Si la orden no llegó a lanzarse. Es un error siempre:
                `veredictos` habla de lo que la orden devuelve, no de eso.
        """
        state["rc"] = rc
        segundos = int(time.monotonic() - state["arranque"])
        especial = None if sin_lanzar else (veredictos or {}).get(rc)
        bien = rc == 0 or especial is not None
        verdict = ("OK" if rc == 0 else especial if bien
                   else f"ERROR (código {rc})")
        impresas = len(salida.completa)
        _volcar(text, salida, [f"\n=== Terminado: {verdict} ===\n"])
        root.title(f"{TITLE} — {title} — {verdict}")
        nuevo = theme.chip(barra, f"{'terminado' if bien else verdict} · {segundos} s",
                           "Ok." if bien else "Peligro.", "ok" if bien else "warn")
        estado.destroy()
        nuevo.grid(row=0, column=2, rowspan=2, sticky="e")
        if impresas >= 1000:             # solo los volcados grandes: es lo que `log-10k` mide
            perf_al_pintar(root, "log-10k", lineas=impresas)

    def poll() -> None:
        """Pasa a la ventana, de una vez, lo que haya en la cola, cada 120 ms."""
        # Sin ventana no hay a quién contárselo. Con la principal viva debajo el
        # bucle de eventos sigue, y sin esto el sondeo seguiría para siempre.
        if not root.winfo_exists():
            return
        lineas: list[str] = []
        acabo = False
        try:
            while True:
                item = q.get_nowait()
                if item is DONE:
                    acabo = True
                    break
                lineas.append(item)
        except queue.Empty:
            pass
        _volcar(text, salida, lineas)
        if acabo:
            terminado(root.proceso.wait())
            return
        root.after(120, poll)

    # Jefe de su sesión (POSIX) o de su grupo de procesos (Windows): cerrar la
    # ventana corta el árbol entero con `store.matar_arbol()`, que en POSIX
    # señala al grupo y por eso necesita que `proc` sea su jefe. Se mira el
    # sistema de verdad y no `IS_WIN`, que los tests fuerzan.
    if sys.platform == "win32":
        aparte: dict = {"creationflags": model.CREATE_NEW_PROCESS_GROUP}
    else:
        aparte = {"start_new_session": True}
    pendiente = {"id": None}

    def arrancar() -> None:
        """Lanza la orden, con la ventana ya enseñada, y empieza a leer su salida.

        Corre en el turno siguiente al de enseñarla (`ensenar()` no ha vuelto
        hasta que la ventana está pintada): lo primero que se ve es la ventana
        y no lo que tarda en lanzarse el proceso. Si no se puede lanzar, la
        ventana lo cuenta y da la pasada por acabada con el 127.
        """
        pendiente["id"] = None
        try:
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
                **aparte,
            )
        except (OSError, ValueError) as e:
            _volcar(text, salida, [f"No se ha podido lanzar: {e}\n"])
            terminado(127, sin_lanzar=True)
            return
        root.proceso = proc
        state["arranque"] = time.monotonic()
        threading.Thread(target=reader, args=(proc,), daemon=True).start()
        root.after(120, poll)

    cortado = {"ya": False}

    def cortar() -> None:
        """Corta el proceso, con su rclone, si sigue; una sola vez por ventana.

        Si aún no se ha lanzado no hay nada que cortar, y se cancela el
        arranque: un `after` que sobrevive a su ventana da un error de Tcl.

        En Windows `taskkill` vuelve antes de que el proceso haya salido: en el
        siguiente punto de corte `proc.poll()` aún lo vería vivo y se lanzaría
        otro `taskkill` (hasta tres por ventana).
        """
        if pendiente["id"] is not None:
            try:
                root.after_cancel(pendiente["id"])
            except tk.TclError:
                pass              # la ventana ya no existe
            pendiente["id"] = None
        proc = root.proceso
        if cortado["ya"] or proc is None or proc.poll() is not None:
            return
        cortado["ya"] = True
        store.matar_arbol(proc.pid)

    def on_close() -> None:
        """Corta el proceso, con su rclone, si sigue y cierra la ventana."""
        if state["rc"] is None:
            cortar()
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
        perf_empezar("volver-pasada")
        cortar()
        if al_cerrar is not None:
            rc = state["rc"] if state["rc"] is not None else 1
            try:
                parent.after_idle(al_cerrar, rc)
            except Exception:                        # noqa: BLE001
                pass         # la madre también se está cerrando

    root.protocol("WM_DELETE_WINDOW", on_close)
    centrar(root, parent)
    ensenar(root)
    root.update_idletasks()
    sin_espera = parent is not None and not modal
    if sin_espera:
        root.bind("<Destroy>", al_destruir, add="+")
    elif parent is not None:
        try:
            root.grab_set()  # después de enseñarla: Tk no captura lo que no se ve
        except tk.TclError:
            pass
    # La orden se lanza cuando la ventana ya se ve, no antes de construirla.
    pendiente["id"] = root.after(1, arrancar)
    if sin_espera:
        return None
    esperar()
    cortar()
    return state["rc"] if state["rc"] is not None else 1
