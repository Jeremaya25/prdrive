"""Lee lo que enseña una pantalla de Tk, para comparar dos pantallas.

Las pantallas que se actualizan en su sitio (`aplicar(estado)`) se prueban
contra la misma pantalla dibujada de nuevo con ese estado: si las dos enseñan
lo mismo, el cambio en el sitio no se dejó nada. Este lector es lo que
«enseñar lo mismo» quiere decir. No afirma nada: devuelve datos para que el
test compare.

Cuenta lo que ve la persona: qué widgets hay a la vista, en qué celda, con qué
texto, estilo, estado, imagen y valor, en el orden en que se leen. No cuenta lo
que no se ve ni lo que cambia sin que la pantalla haya cambiado: el nombre de
los widgets, el orden en que se crearon, la prioridad entre dos que comparten
celda, el relleno, ni el estado que ponen el ratón, el foco o el tema
(`ESTADOS_IGNORADOS`).

Una ventana hija (un `Toplevel`, un menú) es otra pantalla: no se lee dentro de
la que la abrió.
"""

from __future__ import annotations

import re

ESTADOS_IGNORADOS = {"active", "focus", "hover", "pressed", "alternate", "background",
                     "user1", "user2", "user3"}
"""Los estados de ttk que no cuentan como «la pantalla cambió».

Son los que ponen el ratón, el foco, la ventana inactiva y los bits `user1`–`user3`
con que el tema reparte las superficies de los controles redondeados.
"""

_SOBRE = re.compile(r"^Sobre[0-9A-Fa-f]{6}\.")
"""El prefijo `Sobre<RRGGBB>.` de los estilos de un control sobre una cara de color."""


def _viva(widget) -> bool:
    """Indica si el widget existe todavía (su ventana no se ha destruido)."""
    try:
        return bool(widget.winfo_exists())
    except Exception:                                    # noqa: BLE001 — intérprete cerrado
        return False


def a_la_vista(widget) -> bool:
    """Indica si el widget y todo lo que lo contiene hasta su ventana están colocados.

    Cuenta la geometría, no el mapa: una ventana oculta (`withdraw`) con sus
    widgets colocados sigue «a la vista», que es lo que se lee mientras una
    pantalla se construye. Un widget quitado con `grid_remove` no está, y
    tampoco lo que cuelga de él aunque siga colocado en su marco.

    Args:
        widget: El widget a mirar.

    Returns:
        `True` si el widget y cada uno de sus ancestros por debajo de su
        ventana tienen gestor de geometría (`winfo_manager() != ""`).
    """
    if not _viva(widget):
        return False
    ventana = str(widget.winfo_toplevel())
    actual = widget
    while str(actual) != ventana:
        if actual.winfo_manager() == "":
            return False
        actual = actual.master
        if actual is None:
            return False
    return True


def _opcion(widget, nombre: str, defecto=None):
    """Devuelve `cget(nombre)` normalizado, o `defecto` si el widget no tiene la opción.

    Se mira antes en `keys()` porque ttk acepta abreviaturas: en un `ttk.Entry`,
    `cget("text")` contesta con `textvariable`, el nombre de la variable, que
    cambia de una pantalla a otra sin que se vea nada distinto.
    """
    try:
        if nombre not in widget.keys():
            return defecto
        return _plano(widget.cget(nombre))
    except Exception:                                    # noqa: BLE001 — opción desconocida
        return defecto


def _plano(valor):
    """Pasa lo que devuelve Tcl a cadenas y tuplas comparables."""
    if isinstance(valor, (tuple, list)):
        return tuple(_plano(v) for v in valor)
    return str(valor)


def _texto(widget) -> str:
    """El texto del widget, o vacío si no tiene."""
    return _opcion(widget, "text", "")


def _estilo(widget) -> str:
    """El estilo del widget sin el prefijo `Sobre<RRGGBB>.`."""
    return _SOBRE.sub("", _opcion(widget, "style", ""))


def _estados(widget) -> tuple:
    """Los estados que cuentan del widget, ordenados."""
    from tkinter import ttk
    if isinstance(widget, ttk.Widget):
        puestos = {str(s) for s in widget.state()}
    else:
        estado = _opcion(widget, "state", "normal")
        puestos = set() if estado == "normal" else {estado}
    return tuple(sorted(puestos - ESTADOS_IGNORADOS))


def _valor(widget):
    """El valor de la variable ligada al widget, o `None` si no tiene o no está puesta."""
    for opcion in ("textvariable", "variable"):
        nombre = _opcion(widget, opcion, "")
        if nombre:
            try:
                return str(widget.getvar(nombre))
            except Exception:                            # noqa: BLE001 — variable sin crear
                return None
    return None


def _celda(widget) -> tuple:
    """Dónde está el widget en su marco, solo lo que se ve de ello.

    Returns:
        Para `grid`, `(fila, columna, filas, columnas, sticky)`; para otro
        gestor, cinco `None`.
    """
    if widget.winfo_manager() != "grid":
        return (None, None, None, None, None)
    info = widget.grid_info()
    return (int(info["row"]), int(info["column"]), int(info["rowspan"]),
            int(info["columnspan"]), "".join(sorted(set(str(info["sticky"])))))


def _posicion(widget) -> tuple[float, float, float, float]:
    """La posición de un widget de `place`, como números: `(rely, y, relx, x)`."""
    info = widget.place_info()

    def numero(clave: str) -> float:
        """El valor de la clave, `0.0` si no está o no es un número."""
        try:
            return float(info.get(clave, 0) or 0)
        except (TypeError, ValueError):
            return 0.0

    return numero("rely"), numero("y"), numero("relx"), numero("x")


def _otra_geometria(widget):
    """Lo que se ve de la colocación con `pack` o `place`, o `None` con `grid`."""
    gestor = widget.winfo_manager()
    if gestor == "pack":
        info = widget.pack_info()
        return ("pack", str(info["side"]), str(info["fill"]), str(info["expand"]))
    if gestor == "place":
        info = widget.place_info()
        return ("place", str(info.get("x", "")), str(info.get("y", "")),
                str(info.get("relx", "")), str(info.get("rely", "")))
    return None


def _fila(profundidad: int, widget) -> tuple:
    """Lo que se lee de un widget: ver `leer_vista`.

    La raíz de la lectura (profundidad 0) no dice dónde está: su celda es la de
    su marco, no algo que ella enseñe, y dos copias de una misma pantalla no
    tienen por qué estar en la misma.
    """
    celda = _celda(widget) if profundidad else (None,) * 5
    return (profundidad, widget.winfo_class(), _texto(widget), _estilo(widget),
            _estados(widget), _opcion(widget, "image", ""), *celda,
            _opcion(widget, "wraplength"), _valor(widget),
            _otra_geometria(widget) if profundidad else None)


def _hijos(widget) -> list:
    """Los hijos a la vista del widget, en el orden en que se leen.

    Primero los de `grid` por (fila, columna), desempatando por clase, texto,
    estilo e imagen para que no cuente cuál se creó antes; luego los de `pack`
    en el orden en que se empaquetaron, los de `place` por posición y, por
    último, los de cualquier otro gestor (un `Canvas`, un `Text`) por clase y
    texto. Las ventanas hijas (`wm`: un `Toplevel`, un menú) son otra pantalla
    y no están.
    """
    colocados = [h for h in widget.winfo_children() if h.winfo_manager() not in ("", "wm")]

    def con(gestor: str) -> list:
        """Los hijos colocados con ese gestor."""
        return [h for h in colocados if h.winfo_manager() == gestor]

    def clave(h) -> tuple:
        """Cómo se desempata entre widgets que no se distinguen por su sitio."""
        return h.winfo_class(), _texto(h), _estilo(h), _opcion(h, "image", "")

    en_rejilla = sorted(con("grid"), key=lambda h: (*_celda(h)[:2], *clave(h)))
    empaquetados = {str(h) for h in con("pack")}
    en_pack = [h for h in widget.pack_slaves() if str(h) in empaquetados]
    en_place = sorted(con("place"), key=lambda h: (*_posicion(h), *clave(h)))
    otros = sorted((h for h in colocados if h.winfo_manager() not in ("grid", "pack", "place")),
                   key=clave)
    return [*en_rejilla, *en_pack, *en_place, *otros]


def _recorrer(widget, profundidad: int = 0):
    """Recorre el widget y lo que cuelga de él a la vista, en profundidad."""
    yield profundidad, widget
    for hijo in _hijos(widget):
        yield from _recorrer(hijo, profundidad + 1)


def visibles(raiz, clase: str | None = None, texto: str | None = None) -> list:
    """Devuelve los widgets a la vista bajo `raiz`, en profundidad y en orden de lectura.

    Args:
        raiz: Donde buscar; no se incluye a sí misma.
        clase: Si se da, solo los de esa clase de Tk (`winfo_class()`: `TButton`).
        texto: Si se da, solo los que tengan ese `text`.

    Returns:
        Los widgets, vacío si `raiz` no está a la vista.
    """
    if not a_la_vista(raiz):
        return []
    return [w for _, w in _recorrer(raiz)
            if w is not raiz and (clase is None or w.winfo_class() == clase)
            and (texto is None or _texto(w) == texto)]


def leer_vista(raiz) -> list[tuple]:
    """Lee lo que enseña `raiz`: una tupla por widget a la vista, en profundidad.

    Los hijos salen por (fila, columna) si están con `grid`, en el orden de
    empaquetado si están con `pack` y por posición si están con `place`; los
    nombres de los widgets no entran.

    Args:
        raiz: La ventana, o el marco, a leer; es la primera tupla, sin la
            celda en que está colocada.

    Returns:
        Por widget, `(profundidad, clase, texto, estilo, estados, imagen, fila,
        columna, filas, columnas, sticky, wraplength, valor, otra_geometria)`:
        el estilo sin `Sobre<RRGGBB>.`; los estados ordenados y sin
        `ESTADOS_IGNORADOS`; `imagen` el nombre de la imagen de Tk (estable en
        un intérprete); las cinco de la celda `None` fuera de `grid`; `valor`
        el de la variable ligada (`textvariable` o `variable`); y
        `otra_geometria` lo que se ve de `pack`/`place`, `None` con `grid`.
        Vacío si `raiz` no está a la vista.
    """
    if not a_la_vista(raiz):
        return []
    return [_fila(profundidad, w) for profundidad, w in _recorrer(raiz)]


def estilos(interprete) -> list:
    """Devuelve lo que se sabe de los estilos de ttk, para ver si cambian.

    `ttk::style theme styles` solo existe en Tk 9. En Tk 8.6 se compara lo que el
    tema dice de los estilos de las barras, que es lo que se podría tocar, así
    que un test de «no crea ni toca un estilo» corre en los dos Tk, aunque en
    8.6 su comprobación es más estrecha.

    Args:
        interprete: El intérprete de Tcl, `raiz.tk`.

    Returns:
        Una lista de cadenas; dos llamadas que dan lo mismo quieren decir que
        el tema no cambió entre ellas.
    """
    import tkinter as tk

    try:
        return sorted(interprete.splitlist(interprete.call("ttk::style", "theme", "styles")))
    except tk.TclError:
        return [str(interprete.call("ttk::style", orden, estilo))
                for estilo in ("Horizontal.TScrollbar", "Vertical.TScrollbar")
                for orden in ("layout", "configure")]
