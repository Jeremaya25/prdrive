#!/usr/bin/env python3
"""La ventana de la flota: qué otros dispositivos llevan este catálogo.

Solo dibuja. Quién es cada uno, cuándo se le vio por última vez y a partir de
cuándo eso es demasiado tiempo lo sabe `common/fleet.py`, que no importa Tk y
se prueba sin pantalla.

Cuelga de la pantalla de parejas y no de la principal a propósito: es
información para cuando uno se pregunta «¿dónde estaba el otro pendrive?», no
algo que haya que ver cada vez que se sincroniza. La ventana principal ya tiene
sus avisos, y son los urgentes.

De la nota de otro dispositivo, desde aquí solo se puede hacer una cosa:
**quitarla de la lista**. Ningún dispositivo escribe la nota de otro (por eso
son ficheros separados) y quitarla no es escribirla: es borrar un rastro que el
dueño vuelve a dejar en cuanto se enchufa. El contenido de una nota lo sigue
decidiendo solo quien la firma, y el nombre de ESTE dispositivo no se cambia
aquí sino en «Nombre e icono de la unidad…» (`ui/tk_volumen.py`): esta ventana
solo lo enseña.

Debajo de la lista va la **ficha** del elegido: versión, plataformas, desde
cuándo falla y en qué equipos ha estado. Va en la misma ventana y no en otra:
sería el tercer modal en fila (principal → Parejas → Dispositivos → Ficha). Lo
que dice la ficha lo decide `ficha()`, que no toca Tk; aquí solo se dibuja, y
con un juego fijo de etiquetas (`Ficha`) que se rellena en su sitio al elegir.

Las notas están en el remoto y no hay copia local: la ventana se abre en el
acto y las lee en segundo plano (`ui.segundo_plano`), con el indicador puesto y
los botones apagados hasta que llegan. Quitar una nota, lo único que escribe en
el remoto, va por `working()`.
"""

from __future__ import annotations

from functools import partial
from typing import NamedTuple

from common import fleet
from common.model import Config

from . import cuando_sello, icons, segundo_plano, theme
from .tk import (TITLE, CeldaChip, CeldaIcono, CeldaTexto, FilaTabla, Indicador, Sondeo,
                 Tabla, cabecera, centrar, cuerpo_visible, modal, mostrar, working)

COLUMNAS = [
    ("aqui", "Este", 44),
    ("nombre", "Dispositivo", 200),
    ("visto", "Visto", 110),
    ("equipo", "Último equipo", 130),
    ("estado", "Última pasada", 180),
]
"""Las columnas de la tabla: clave, título y ancho mínimo en medidas del diseño.

La versión y las plataformas se fueron a la ficha: en la tabla queda lo que se
compara de un vistazo entre dispositivos. «Último equipo» es solo el más
reciente (`Dispositivo.ultimo_equipo`); la lista entera, con sus fechas, está en
el apartado «Equipos» de la ficha.
"""

SIN_DATO = "—"
"""Lo que se enseña en una celda de la tabla de la que la nota no dice nada."""

SIN_NOTA = ("Todavía no hay ningún dispositivo apuntado. Cada uno deja su nota al "
            "sincronizar, así que aparecerán aquí en cuanto se usen.")
"""Lo que se dice cuando todavía no hay ningún dispositivo apuntado."""
LEYENDO = "Leyendo en el remoto las notas de los dispositivos…"
"""Lo que dice el indicador mientras se lee la flota."""

ROTULOS_FICHA = ("Versión", "Para", "Estado", "Equipos")
"""Los rótulos de los apartados de la ficha."""
ESTE_EQUIPO = " · este equipo"
"""Lo que se añade al nombre del equipo desde el que se mira."""
SIN_EQUIPOS = "No consta: las versiones anteriores no lo apuntaban."
"""Lo que se dice de un dispositivo que no apuntó dónde ha estado."""
SIN_BUENA = "No consta ninguna pasada buena."
"""Lo que se dice cuando no consta ninguna pasada buena."""
EN_UN_EQUIPO = "Una carpeta de un equipo, no una unidad"
"""Lo que dice el apartado «Para» de la raíz de un equipo."""
MARCA_EQUIPO = " (equipo)"
"""Lo que se añade al nombre en la tabla para la raíz de un equipo."""
MARCA_EQUIPO_CIFRADO = " (equipo, cifrado)"
"""Lo mismo para la raíz de un equipo cifrada."""
EN_UN_EQUIPO_CIFRADO = "Una carpeta de un equipo, cifrada con VeraCrypt"
"""Lo que dice el apartado «Para» de la raíz de un equipo cifrada."""


class Linea(NamedTuple):
    """Una línea de la ficha.

    Args:
        texto: Lo que dice.
        fecha: Cuándo, a la derecha y en monoespaciada.
        pista: Si acompaña al dato en vez de ser el dato.
    """
    texto: str
    fecha: str = ""
    pista: bool = False


class Fila(NamedTuple):
    """Un apartado de la ficha: su rótulo y sus líneas.

    Args:
        rotulo: El título del apartado.
        lineas: Lo que dice.
        reserva: Las líneas que se reservan aunque no haya tantas, que es lo
            que hace que la ficha mida lo mismo con un equipo que con cinco.
    """
    rotulo: str
    lineas: tuple[Linea, ...]
    reserva: int = 0


def fecha(sello: str) -> str:
    """Devuelve una fecha de la nota como se enseña en la tabla.

    Las recientes llevan el formato de la ventana («ayer», «08:20»); las de
    hace una semana o más, la fecha entera. Aquí sí hace falta el año, a
    diferencia del resto de la aplicación: entre un dispositivo visto hace tres
    semanas y otro visto hace dos años, un «12/09» a secas no distingue nada, y
    distinguirlos es justo para lo que se abre esta lista.
    """
    if not sello:
        return "—"
    if fleet.sello_obsoleto(sello):
        return sello[:10]
    return cuando_sello(sello) or sello[:10]


def ultimo_equipo(disp: fleet.Dispositivo) -> str:
    """Devuelve lo que dice la columna «Último equipo» de un dispositivo.

    El equipo desde el que publicó por última vez, o `SIN_DATO` si su nota no
    lo apunta (una de una versión que aún no llevaba la lista de equipos).
    """
    return disp.ultimo_equipo or SIN_DATO


def ficha(disp: fleet.Dispositivo, equipo_aqui: str) -> list[Fila]:
    """Devuelve lo que dice la ficha de un dispositivo, apartado por apartado.

    Args:
        disp: El dispositivo.
        equipo_aqui: El nombre de red de este equipo: la entrada que coincide
            se marca, y eso contesta sin más si el otro pendrive ha estado en
            este ordenador.
    """
    estado = [Linea(BIEN if disp.bien else disp.last_result)]
    if disp.ultima_buena == fleet.SIN_BUENA:
        estado.append(Linea(SIN_BUENA, pista=True))
    elif disp.ultima_buena:
        estado.append(Linea(f"Última pasada buena: {fecha(disp.ultima_buena)}",
                            pista=True))
    equipos = []
    for equipo in disp.equipos:
        marca = ESTE_EQUIPO if equipo_aqui and equipo.nombre == equipo_aqui else ""
        equipos.append(Linea(equipo.nombre + marca, fecha(equipo.visto)))
    if not equipos:
        equipos.append(Linea(SIN_EQUIPOS, pista=True))
    version, para, est, eqs = ROTULOS_FICHA
    # La raíz de un equipo no se enchufa en ningún sitio: su «para» es el equipo
    # donde vive, y lo que lleva es rclone para él (el Python es el del agente).
    para_que = ((EN_UN_EQUIPO_CIFRADO if disp.cifrado else EN_UN_EQUIPO)
                if disp.es_equipo else ", ".join(disp.plataformas) or "—")
    return [Fila(version, (Linea(disp.version),)),
            Fila(para, (Linea(para_que),)),
            Fila(est, tuple(estado)),
            Fila(eqs, tuple(equipos), reserva=fleet.MAX_EQUIPOS)]


def marca(disp: fleet.Dispositivo) -> str:
    """Devuelve lo que se le añade al nombre en la tabla: nada en una unidad."""
    if not disp.es_equipo:
        return ""
    return MARCA_EQUIPO_CIFRADO if disp.cifrado else MARCA_EQUIPO


def _tono(disp: fleet.Dispositivo) -> str:
    """Devuelve el color de una fila: apagado, ok o aviso.

    Sale apagado el que lleva una semana sin aparecer y en aviso el que acabó
    mal. El olvido va antes que el fallo a propósito: de uno que no se enchufa
    desde hace un mes, lo que falló hace un mes ya no es la noticia.
    """
    if disp.obsoleto():
        return "apagado"
    return "ok" if disp.bien else "aviso"


BIEN = "bien"
"""Lo que dice el chip de un dispositivo cuya última pasada fue bien."""

ESTE = "✓"
"""Lo que dice la columna «Este» en la fila de este dispositivo (va con su icono)."""


def ultima_pasada(disp: fleet.Dispositivo) -> tuple[str, str]:
    """Devuelve lo que dice la columna «Última pasada» y su tono.

    El tono es el de la fila (`_tono`): `ok`, `aviso` o `apagado`. Un `ok` de
    la nota se dice «bien», como en el resto de la ventana.
    """
    texto = BIEN if disp.bien else disp.last_result
    return texto, _tono(disp)


def fila(disp: fleet.Dispositivo, yo: str) -> FilaTabla:
    """Devuelve la fila de la tabla de un dispositivo."""
    texto, tono = ultima_pasada(disp)
    if tono == "ok":
        estado = CeldaChip(texto, "Ok.", "ok")
    elif tono == "aviso":
        estado = CeldaChip(texto, "Aviso.", "warn")
    else:
        estado = CeldaTexto(texto, "Pista.")
    return FilaTabla(disp.id, (
        CeldaIcono("ok", ESTE) if disp.id == yo else "",
        CeldaTexto(disp.nombre + marca(disp), "Fuerte."),
        CeldaTexto(fecha(disp.last_seen), "Mono."),
        CeldaTexto(ultimo_equipo(disp), "Mono."),
        estado), "" if tono == "ok" else tono)


LINEAS_FICHA = (1, 1, 2, fleet.MAX_EQUIPOS)
"""Cuántas etiquetas de línea tiene la ficha por apartado al hacerse.

Son las líneas que `ficha()` da en el caso común: una para «Versión» y para
«Para», dos para «Estado» (el resultado y su pista) y las `MAX_EQUIPOS` que
«Equipos» reserva siempre. Si una nota pidiera más se hacen al llegar.
"""


class Ficha:
    """La ficha del elegido: un juego fijo de etiquetas que se rellena en su sitio.

    Las etiquetas se hacen la primera vez que la ficha se necesita (`_construir()`,
    desde `poner()` o `reservar()`): con una flota vacía no se hace ninguna. Son el
    nombre y el id, el rótulo de cada apartado y sus líneas (`LINEAS_FICHA`). Las
    fechas de los equipos se hacen cuando una flota las pide, y no se destruyen.
    `poner()` solo cambia el texto y el estilo de cada una y la fila de la rejilla
    donde está, y esconde con `grid_remove()` las que no tienen nada que decir:
    elegir otro dispositivo no crea ni destruye ningún widget. Las filas fluyen:
    un «Estado» de una línea deja subir a «Equipos», y uno de dos lo baja.

    El sitio de la ficha se reserva para el dispositivo que más pida
    (`reservar()`), y se mide con las propias etiquetas: sus tamaños pedidos
    son los correctos nada más cambiar su texto, sin esperar a ningún reposo
    del bucle de eventos, y la altura y el ancho de la tarjeta salen de sumar
    lo que pide cada fila y cada columna de la rejilla. No se pinta una tarjeta
    por dispositivo para medirla.

    Args:
        padre: El marco donde va la ficha: su rótulo en la fila `fila` y la
            tarjeta en la siguiente, en la columna `columna`.
        fila: La fila del rótulo «Ficha».
        columna: La columna de la rejilla de `padre` en que va.

    Attributes:
        marco: La tarjeta, donde están las etiquetas; `None` hasta que se hace.
        rotulo: El rótulo «Ficha», encima de la tarjeta; `None` hasta que se hace.
        reserva: El `(ancho, alto)` que reservó `reservar()`, en píxeles.
    """

    def __init__(self, padre, fila: int, columna: int = 0) -> None:
        """Deja la ficha lista para hacerse, sin widgets: nace escondida y sin hacer."""
        self.padre, self.fila, self.columna = padre, fila, columna
        self.rotulo = self.marco = None
        self.nombre = self.ident = None
        self.rotulos: list = []
        self.lineas: list = []
        self.fechas: list = []
        self.reserva = (0, 0)
        # Las medidas de la rejilla se toman del padre: no hace falta ninguna
        # etiqueta para tenerlas.
        self._canalon = theme.ancho_rotulo(padre, *ROTULOS_FICHA) + icons.px(padre, 14)
        # Los espacios de la rejilla, en píxeles: lo que `_pide()` suma es lo
        # mismo que `grid` reparte.
        self._px = {d: int(padre.winfo_pixels(d))
                    for d in (theme.E2, theme.E3, theme.E4)}
        self._aire = icons.px(padre, 2)

    def _construir(self) -> None:
        """Hace las etiquetas fijas de la ficha, sin colocarlas.

        Lo llama `_colocar()` la primera vez, así que la ficha existe desde que
        hay un dispositivo que enseñar. Las fechas no se hacen aquí: las pide cada
        flota.
        """
        from tkinter import ttk
        padre = self.padre
        self.rotulo = ttk.Label(padre, text=theme.rotulo("Ficha"), style="Rotulo.TLabel")
        self.marco = ttk.Frame(padre, style="Card.TFrame",
                               padding=(theme.E4, theme.E3, theme.E4, theme.E3))
        self.marco.columnconfigure(0, minsize=self._canalon)
        self.marco.columnconfigure(1, weight=1)
        self.nombre = ttk.Label(self.marco, style="Card.Fuerte.TLabel",
                                wraplength=theme.medida(460), justify="left")
        self.ident = ttk.Label(self.marco, style="Card.MonoPista.TLabel")
        self.rotulos = [ttk.Label(self.marco, style="Card.Rotulo.TLabel")
                        for _ in ROTULOS_FICHA]
        self.lineas = [[self._nueva_linea() for _ in range(n)] for n in LINEAS_FICHA]

    def _nueva_linea(self):
        """Hace una etiqueta de línea, sin colocar."""
        from tkinter import ttk
        return ttk.Label(self.marco, justify="left", style="Card.TLabel",
                         wraplength=theme.medida(440))

    def _nueva_fecha(self):
        """Hace una etiqueta de fecha, sin colocar."""
        from tkinter import ttk
        return ttk.Label(self.marco, style="Card.MonoPista.TLabel")

    def mostrar(self) -> None:
        """Coloca la ficha, con su rótulo, en su sitio."""
        self.rotulo.grid(row=self.fila, column=self.columna, sticky="w",
                         pady=(theme.E4, theme.E2))
        self.marco.grid(row=self.fila + 1, column=self.columna, sticky="nsew")

    def ocultar(self) -> None:
        """Quita la ficha entera de la rejilla; recuerda el hueco que se le reservó.

        No hace nada mientras la ficha no se ha hecho.
        """
        if self.marco is None:
            return
        self.rotulo.grid_remove()
        self.marco.grid_remove()

    def poner(self, disp: fleet.Dispositivo, equipo_aqui: str) -> None:
        """Rellena la ficha con ese dispositivo y la enseña.

        Args:
            disp: El dispositivo elegido.
            equipo_aqui: El nombre de red de este equipo, para marcarlo.
        """
        self._colocar(disp, equipo_aqui)
        self.mostrar()

    def _colocar(self, disp: fleet.Dispositivo, equipo_aqui: str) -> list[tuple]:
        """Pone el texto, el estilo y la fila de cada etiqueta para ese dispositivo.

        Si la ficha todavía no se ha hecho, la hace antes (`_construir()`). Lo que
        `ficha()` no usa se esconde y se deja sin texto. Es lo que comparten
        `poner()` y `reservar()`: la ficha que se mide es la que se pinta.

        Returns:
            Lo colocado, `(etiqueta, fila, columna, columnas, hueco_x, hueco_y)`
            por etiqueta, con los huecos en píxeles: lo que `_pide()` suma.
        """
        if self.marco is None:
            self._construir()
        e2, e3 = self._px[theme.E2], self._px[theme.E3]
        self.nombre.configure(text=disp.nombre)
        self.nombre.grid(row=0, column=0, columnspan=2, sticky="w")
        # El id corto: dos dispositivos aprovisionados en el mismo equipo
        # empiezan con el mismo nombre, y el id es lo único que los distingue
        # (y el nombre de su fichero en `devices/`).
        self.ident.configure(text=f"id {disp.id[:8]}")
        self.ident.grid(row=0, column=2, sticky="ne", padx=(theme.E3, 0))
        colocadas = [(self.nombre, 0, 0, 2, 0, 0), (self.ident, 0, 2, 1, e3, 0)]
        fila, fecha_n = 1, 0
        for apartado, rotulo, etiquetas in zip(ficha(disp, equipo_aqui), self.rotulos,
                                               self.lineas):
            rotulo.configure(text=theme.rotulo(apartado.rotulo))
            rotulo.grid(row=fila, column=0, sticky="nw", pady=(theme.E2, 0))
            colocadas.append((rotulo, fila, 0, 1, 0, e2))
            lineas = list(apartado.lineas)
            lineas += [Linea(" ")] * (apartado.reserva - len(lineas))
            while len(etiquetas) < len(lineas):
                etiquetas.append(self._nueva_linea())
            for i, etiqueta in enumerate(etiquetas):
                if i >= len(lineas):
                    etiqueta.configure(text="")
                    etiqueta.grid_remove()
                    continue
                linea = lineas[i]
                # Ocho de aire entre apartados y dos entre las líneas de uno.
                aire, aire_px = (theme.E2, e2) if i == 0 else (self._aire, self._aire)
                etiqueta.configure(
                    text=linea.texto,
                    style="Card.Pista.TLabel" if linea.pista else "Card.TLabel")
                etiqueta.grid(row=fila, column=1, sticky="w", pady=(aire, 0))
                colocadas.append((etiqueta, fila, 1, 1, 0, aire_px))
                if linea.fecha:
                    if fecha_n == len(self.fechas):
                        self.fechas.append(self._nueva_fecha())
                    fecha = self.fechas[fecha_n]
                    fecha_n += 1
                    fecha.configure(text=linea.fecha)
                    fecha.grid(row=fila, column=2, sticky="e", padx=(theme.E3, 0),
                               pady=(aire, 0))
                    colocadas.append((fecha, fila, 2, 1, e3, aire_px))
                fila += 1
        for sobrante in self.fechas[fecha_n:]:
            sobrante.configure(text="")
            sobrante.grid_remove()
        return colocadas

    def _pide(self, colocadas: list[tuple]) -> tuple[int, int]:
        """Devuelve lo que pediría la tarjeta con esas etiquetas colocadas: `(ancho, alto)`.

        Es lo que hace `grid`: cada fila mide lo que pide la mayor de sus
        etiquetas con su hueco, cada columna lo mismo (con el mínimo del
        canalón en la primera) y una etiqueta que ocupa dos columnas añade a
        la última lo que no les cabe. A eso, el relleno de la tarjeta.
        """
        alto: dict[int, int] = {}
        ancho: dict[int, int] = {0: self._canalon}
        for etiqueta, fila, columna, columnas, hueco_x, hueco_y in colocadas:
            alto[fila] = max(alto.get(fila, 0), etiqueta.winfo_reqheight() + hueco_y)
            if columnas == 1:
                ancho[columna] = max(ancho.get(columna, 0),
                                     etiqueta.winfo_reqwidth() + hueco_x)
        # El nombre es la única etiqueta que ocupa dos columnas, y `_colocar()` la
        # pone sin hueco: por eso no se suma ninguno aquí.
        for etiqueta, _fila, columna, columnas, _hueco_x, _hueco_y in colocadas:
            if columnas > 1:
                ultima = columna + columnas - 1
                falta = (etiqueta.winfo_reqwidth()
                         - sum(ancho.get(c, 0) for c in range(columna, ultima + 1)))
                if falta > 0:
                    ancho[ultima] = ancho.get(ultima, 0) + falta
        return (2 * self._px[theme.E4] + sum(ancho.values()),
                2 * self._px[theme.E3] + sum(alto.values()))

    def reservar(self, flota: list[fleet.Dispositivo], equipo_aqui: str) -> tuple[int, int]:
        """Reserva el sitio de la ficha: el que pide la más grande de esta flota.

        Los equipos ya reservan siempre sus `MAX_EQUIPOS` líneas, pero hay
        texto que sí cambia de alto (un «fallo en a, b, c…» que parte en dos
        líneas, un nombre largo) y medirlo es la única forma de no suponerlo.
        Se rellenan las etiquetas con cada dispositivo y se lee lo que piden:
        no se crea ningún widget (salvo la ficha la primera vez, y las fechas que
        falten) ni se espera a un reposo del bucle de eventos. La ficha queda con el
        último dispositivo: quien llama la repinta con el elegido.

        Args:
            flota: Los dispositivos de la lista.
            equipo_aqui: El nombre de red de este equipo.

        Returns:
            El `(ancho, alto)` reservado, en píxeles; `(0, 0)` sin dispositivos.
        """
        ancho = alto = 0
        for disp in flota:
            pide = self._pide(self._colocar(disp, equipo_aqui))
            ancho, alto = max(ancho, pide[0]), max(alto, pide[1])
        self.padre.columnconfigure(self.columna, minsize=ancho)
        self.padre.rowconfigure(self.fila + 1, minsize=alto)
        self.reserva = (ancho, alto)
        return self.reserva


def open_dialog(parent, config: Config, raw: dict | None = None) -> None:
    """Abre la ventana; no devuelve nada.

    Lo único que escribe es quitar la nota de otro dispositivo del remoto, y no
    hay nada local que repintar después.

    Args:
        parent: La ventana de la que cuelga.
        config: El config de este dispositivo. Esta ventana no lo usa: la flota
            sale del remoto y el dispositivo no se publica desde aquí.
        raw: El config en bruto, para saber dónde está el catálogo y, junto a
            él, la flota.
    """
    from tkinter import messagebox, ttk

    dlg = modal(parent, "Dispositivos")
    estado: dict = {"flota": []}
    yo = fleet.device_id()
    sondeo = Sondeo(dlg)

    marco = cuerpo_visible(dlg, padding=(theme.E5, theme.E4, theme.E5, theme.E4))
    marco.columnconfigure(0, weight=1)

    arriba = ttk.Frame(marco)
    arriba.grid(row=0, column=0, sticky="ew")
    arriba.columnconfigure(0, weight=1)
    # Lo de los equipos se dice aquí, a la vista, y no en una ayuda: es el nombre
    # de red de los ordenadores de cada uno, y se publica siempre.
    cabecera(arriba, "Dispositivos",
             "Cada uno deja una nota al sincronizar, con el nombre de red de los "
             "equipos donde se enchufa. El de este se cambia en «Ajustes» → "
             "«Nombre e icono».",
             ancho=470, estilo="Dialogo.TLabel").grid(row=0, column=0, sticky="w")

    donde = ttk.Frame(arriba)
    donde.grid(row=0, column=1, sticky="ne")
    donde.columnconfigure(0, weight=1)
    chip = {"widget": None}
    endpoint = ttk.Label(donde, style="MonoPista.TLabel", text=fleet.carpeta(raw))
    endpoint.grid(row=1, column=0, sticky="e", pady=(theme.E2, 0))
    indicador = Indicador(arriba, ancho=520)
    indicador.marco.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(theme.E3, 0))
    dlg.indicador, dlg.sondeo = indicador, sondeo   # como `visor`: los tests los miran

    tabla = Tabla(marco, [(titulo, ancho, clave in ("nombre", "estado"))
                          for clave, titulo, ancho in COLUMNAS],
                  al_elegir=lambda: repasar())
    tabla.grid(row=1, column=0, sticky="ew", pady=(theme.E4, 0))
    dlg.tabla = tabla                                  # los tests la miran

    # El aviso de que aún no hay nadie apuntado se hace la primera vez que hace
    # falta: con notas no se llega a necesitar.
    vacio = {"etiqueta": None}

    # La ficha del elegido, en las filas 2 y 3. Su sitio se reserva para la ficha
    # más grande de la flota (`Ficha.reservar()`): el `Visor` encaja una sola
    # vez, al abrir, y sin la reserva elegir una ficha más larga que la primera
    # hacía crecer el contenido y sacaba una barra de desplazamiento que al
    # abrir no estaba.
    ficha_elegida = Ficha(marco, fila=2)
    dlg.ficha = ficha_elegida                          # los tests la miran
    aqui = fleet.equipo_actual()

    def pintar_chip(texto: str, tipo: str, icono: str) -> None:
        """Cambia el chip de arriba a la derecha por otro que dice lo que toca."""
        if chip["widget"] is not None:
            chip["widget"].destroy()
        chip["widget"] = theme.chip(donde, texto, tipo, icono)
        chip["widget"].grid(row=0, column=0, sticky="e")

    def refrescar(nota: str = "") -> None:
        """Relee la flota en segundo plano y repinta la tabla y la ficha al llegar.

        Mientras tanto se queda lo que había (nada, al abrir) con el indicador
        puesto y los botones apagados: los dos hablan con el remoto.
        """
        pintar_chip("leyendo la flota…", "Apagado.", "clock")
        indicador.poner(LEYENDO, True)
        repasar()
        for boton in (quitar, releer):
            boton.configure(state="disabled")

        def llegada(encargo) -> None:
            """Pinta lo que ha llegado; `fleet.leer()` no lanza, pero el hilo sí podría."""
            if encargo.error is not None:
                pintar([], f"No se ha podido leer la flota: {encargo.error}", nota)
            else:
                pintar(*encargo.resultado, nota)

        sondeo.esperar(segundo_plano.lanzar_sin_repetir(
            "flota", raw, partial(fleet.leer, raw)), llegada)

    def pintar(flota: list, aviso: str | None, nota: str = "") -> None:
        """Repinta la tabla, el chip y la ficha con la flota leída."""
        estado["flota"] = flota
        indicador.poner("", False)
        releer.configure(state="normal")
        if aviso:
            pintar_chip("sin conexión", "Aviso.", "warn")
        else:
            pintar_chip(f"{len(flota)} dispositivo(s)", "Acento.", "ok")

        tabla.poner([fila(disp, yo) for disp in flota])
        ficha_elegida.reservar(flota, aqui)
        if flota:
            if vacio["etiqueta"] is not None:
                vacio["etiqueta"].grid_remove()
            tabla.elegir(tabla.elegida or flota[0].id, avisar=False)
        else:
            if vacio["etiqueta"] is None:
                vacio["etiqueta"] = ttk.Label(marco, text=SIN_NOTA, style="Pista.TLabel",
                                              wraplength=theme.medida(620), justify="left")
            vacio["etiqueta"].grid(row=2, column=0, sticky="w", pady=(theme.E3, 0))
        repasar()
        pie_nota.configure(text=nota or (aviso or ""))
        # Releer puede traer una ficha más grande que las que había al abrir:
        # entonces el recuadro crece, en vez de meter la ventana tras una barra,
        # y la ventana se recoloca (como el asistente) para que lo que ha
        # crecido no quede por debajo del borde de la pantalla.
        if dlg.winfo_ismapped() and dlg.visor.crecer(dlg):
            centrar(dlg, parent)

    def elegido() -> fleet.Dispositivo | None:
        """Devuelve el dispositivo de la fila elegida, o `None`."""
        return next((d for d in estado["flota"] if d.id == tabla.elegida), None)

    def repasar(_evento=None) -> None:
        """Repinta lo que cuelga de la fila elegida: su ficha y el botón de quitar.

        Sin nada elegido (flota vacía, o recién quitado uno) la ficha se
        esconde entera. «Quitar de la lista» se apaga sobre este mismo
        dispositivo: `fleet` lo rechaza igualmente (la regla es suya), pero un
        botón encendido que siempre contesta que no es peor que uno apagado.
        Y mientras se relee la flota, sobre cualquiera.
        """
        disp = elegido()
        if disp is None:
            ficha_elegida.ocultar()
        else:
            ficha_elegida.poner(disp, aqui)
        quitar.configure(state="normal" if disp is not None and disp.id != yo
                         and not sondeo.esperando else "disabled")

    def quitar_de_la_lista() -> None:
        """Quita la nota de un dispositivo que ya no existe.

        Es un `askokcancel` y no `confirmar_plan()`: esa ventana gobierna los
        borrados que pierden datos y esto no pierde ninguno (si el dispositivo
        vuelve a enchufarse, publica otra vez y reaparece). Lo que sí hace
        falta es decirlo, porque «quitar» suena a más de lo que es.
        """
        disp = elegido()
        if disp is None or disp.id == yo:
            return
        if not messagebox.askokcancel(
                TITLE,
                f"¿Quitar «{disp.nombre}» de la lista?\n\n"
                f"Se borra su nota del remoto, no el dispositivo. Si vuelve a "
                f"enchufarse en algún sitio, se apuntará solo y reaparecerá aquí.",
                parent=dlg):
            return
        ok, fallo = working(dlg, "Dispositivos", partial(fleet.olvidar, disp.id, raw),
                            f"Quitando la nota de «{disp.nombre}» del remoto…")
        if not ok or fallo:
            refrescar(str(fallo))
            return
        refrescar(f"«{disp.nombre}» ya no está en la lista.")

    acciones = ttk.Frame(marco)
    acciones.grid(row=4, column=0, sticky="ew", pady=(theme.E4, 0))
    acciones.columnconfigure(1, weight=1)
    quitar = ttk.Button(acciones, text="Quitar de la lista…", style="Danger.TButton",
                        command=quitar_de_la_lista, state="disabled")
    theme.boton_icono(quitar, "trash", theme.PELIGRO, theme.SUPERFICIE)
    quitar.grid(row=0, column=0, sticky="w")
    releer = ttk.Button(acciones, text="Releer", style="Quiet.TButton",
                        command=lambda: refrescar("Flota releída."))
    theme.boton_icono(releer, "reload", theme.ACENTO, theme.PAPEL)
    releer.grid(row=0, column=2, sticky="e")

    cierre = ttk.Frame(marco)
    cierre.grid(row=5, column=0, sticky="ew", pady=(theme.E3, 0))
    cierre.columnconfigure(0, weight=1)
    pie_nota = ttk.Label(cierre, text="", style="MonoPista.TLabel",
                         wraplength=theme.medida(620), justify="left")
    pie_nota.grid(row=0, column=0, sticky="w")
    ttk.Button(cierre, text="Cerrar", command=dlg.destroy).grid(row=0, column=1)

    refrescar()
    mostrar(dlg, parent)
