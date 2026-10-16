#!/usr/bin/env python3
"""Los atajos de teclado globales del agente: qué se graba, qué hace cada uno y sobre qué unidad.

Es la mitad que DECIDE, como `ui/bandeja.py`: sin Tk y sin el sistema. Las
mitades que tocan el sistema son las que registran las combinaciones y oyen
cuándo se pulsan: `ui/bandeja_windows.py` (`RegisterHotKey` en el hilo de la
bandeja) y `ui/atajos_linux.py` (`XGrabKey` en X11, el portal
`org.freedesktop.portal.GlobalShortcuts` en Wayland). La ventana que graba la
combinación es `ui/tk_atajos.py`, que solo dibuja.

Lo que se decide aquí:
- **Las cinco acciones** (`ACCIONES`): sincronizar ahora, abrir la carpeta de
  la unidad, pausar o reanudarla, abrir su ventana y abrir su llavero. Un atajo
  pulsado no es una lógica nueva: se convierte en las mismas peticiones del
  buzón que el menú de la bandeja (`pulsado()`), y el agente las atiende por el
  camino de siempre.
- **Sobre qué unidad** (`objetivo()`): la última usada (la última cuya ventana
  se abrió o sobre la que se usó una acción de la bandeja) y, si no se ha usado
  ninguna, la última que se conectó. Con una sola, esa. La del llavero elige
  solo entre las que lo llevan.
- **Cómo se escribe una combinación.** Por dentro, en minúsculas y en un orden
  fijo (`ctrl+alt+s`), que es lo que guarda `agente.json`; de cara al usuario,
  con los nombres de su teclado (`texto()`: «Ctrl+Alt+S», «Mayús», «Win» o
  «Súper»). Lo que necesita cada sistema sale de ahí: los modificadores y la
  tecla virtual de `RegisterHotKey` (`windows()`), la máscara y el keysym de
  `XGrabKey` (`x11()`) y el disparador preferido del portal (`portal()`, la
  especificación «shortcuts» de freedesktop).
- **Qué combinación vale** (`problema()`): una tecla que se sepa nombrar en los
  tres sistemas, con Ctrl, Alt o la tecla del logotipo. Sin ninguno de los
  tres, la tecla dejaría de escribirse en los demás programas; por lo mismo,
  en Windows no vale Ctrl+Alt con una tecla que escribe, porque es AltGr.
  `validar()` lo aplica también a lo que hay en `agente.json`.
- **Grabar** (`Teclas`, `Edicion`): las teclas que llegan a la ventana mientras
  se graba, y lo que dice cada fila antes y después de guardar.
- **Guardar** (`guardar()`, `respuesta()`, `tras_guardar()`): la petición que
  deja la ventana en el buzón del agente y su respuesta en `estado.json`
  (`leer_estado()` y `pedir()`, sustituibles). La ventana solo los llama.
- **Con qué se ponen en este equipo** (`mecanismo()`), y qué se dice si no se
  puede.

No hay ningún atajo de fábrica: un equipo sin ellos en `agente.json` no
registra nada.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from typing import Any, Mapping

from common import APP_NAME, equipo

ACCIONES = equipo.ACCIONES_DE_ATAJO
"""Las acciones que pueden llevar atajo, en el orden en que se enseñan."""
SINCRONIZAR, CARPETA, PAUSAR, VENTANA, LLAVERO = ACCIONES

NOMBRES = {SINCRONIZAR: "Sincronizar ahora", CARPETA: "Abrir su carpeta",
           PAUSAR: "Pausar o reanudar", VENTANA: "Abrir su ventana",
           LLAVERO: "Abrir el llavero"}
"""Cómo se nombra cada acción de cara al usuario."""

CTRL, ALT, MAYUS, LOGO = "ctrl", "alt", "shift", "super"
MODIFICADORES = (CTRL, ALT, MAYUS, LOGO)
"""Los modificadores, en el orden en que se escriben."""

# Las teclas que se pueden usar, con lo que necesita cada sistema:
# su tecla virtual de Windows (winuser.h, «Virtual-Key Codes»), su keysym de X
# (keysymdef.h, que es también el nombre de tecla del portal) y cómo se llama
# en un teclado español.
_NOMBRADAS = {
    "space": (0x20, "space", "Espacio"),
    "insert": (0x2D, "Insert", "Insert"),
    "delete": (0x2E, "Delete", "Supr"),
    "home": (0x24, "Home", "Inicio"),
    "end": (0x23, "End", "Fin"),
    "pageup": (0x21, "Prior", "RePág"),
    "pagedown": (0x22, "Next", "AvPág"),
    "left": (0x25, "Left", "←"),
    "up": (0x26, "Up", "↑"),
    "right": (0x27, "Right", "→"),
    "down": (0x28, "Down", "↓"),
}


def _tabla() -> dict[str, tuple[int, str, str]]:
    """Devuelve todas las teclas: letras, cifras, F1–F24 y las de `_NOMBRADAS`."""
    teclas = {chr(c): (c - 32, chr(c), chr(c - 32)) for c in range(ord("a"), ord("z") + 1)}
    teclas.update({str(d): (0x30 + d, str(d), str(d)) for d in range(10)})
    teclas.update({f"f{n}": (0x6F + n, f"F{n}", f"F{n}") for n in range(1, 25)})
    teclas.update(_NOMBRADAS)
    return teclas


TECLAS = _tabla()
"""Cada tecla que vale para un atajo: `(tecla virtual, keysym, texto)`, por su nombre de dentro."""

_ALIAS_MODIFICADOR = {"ctrl": CTRL, "control": CTRL, "ctl": CTRL, "alt": ALT, "shift": MAYUS,
                      "mayús": MAYUS, "mayus": MAYUS, "super": LOGO, "súper": LOGO,
                      "win": LOGO, "windows": LOGO, "logo": LOGO, "meta": LOGO}
_ALIAS_TECLA = {"espacio": "space", "supr": "delete", "suprimir": "delete", "del": "delete",
                "ins": "insert", "inicio": "home", "fin": "end", "prior": "pageup",
                "repág": "pageup", "repag": "pageup", "next": "pagedown",
                "avpág": "pagedown", "avpag": "pagedown", "izquierda": "left",
                "derecha": "right", "arriba": "up", "abajo": "down"}


@dataclass(frozen=True)
class Combinacion:
    """Una combinación de teclas.

    Args:
        modificadores: Los que lleva, de `MODIFICADORES`.
        tecla: La tecla, por su nombre de dentro (una clave de `TECLAS`), o
            vacía si todavía no se ha pulsado ninguna.
    """
    modificadores: frozenset[str] = frozenset()
    tecla: str = ""

    def __str__(self) -> str:
        """Devuelve la forma de dentro: `ctrl+alt+s`."""
        return "+".join([m for m in MODIFICADORES if m in self.modificadores]
                        + ([self.tecla] if self.tecla else []))


def leer(texto: Any) -> Combinacion | None:
    """Lee una combinación escrita a mano o guardada («Ctrl+Alt+S», `ctrl+alt+s`).

    Admite los nombres de los modificadores en inglés y en español, en
    cualquier orden y con mayúsculas o sin ellas.

    Returns:
        La combinación, o `None` si no se entiende o le falta la tecla.
    """
    if not isinstance(texto, str) or not texto.strip():
        return None
    partes = [p.strip().lower() for p in texto.split("+")]
    if any(not p for p in partes):
        return None
    *mods, tecla = partes
    modificadores = set()
    for m in mods:
        if m not in _ALIAS_MODIFICADOR:
            return None
        modificadores.add(_ALIAS_MODIFICADOR[m])
    tecla = _ALIAS_TECLA.get(tecla, tecla)
    if tecla not in TECLAS:
        return None
    return Combinacion(frozenset(modificadores), tecla)


def normal(texto: Any) -> str:
    """Devuelve la forma de dentro de una combinación, o `""` si no se entiende."""
    c = leer(texto)
    return str(c) if c is not None else ""


def texto(combo: Any, windows: bool) -> str:
    """Devuelve cómo se enseña una combinación: «Ctrl+Alt+S».

    Args:
        combo: La combinación, en su forma de dentro.
        windows: Si se enseña en Windows: la tecla del logotipo es «Win»; si
            no, «Súper».

    Returns:
        El texto, o `""` si no hay combinación o no se entiende.
    """
    c = leer(combo)
    if c is None:
        return ""
    nombres = {CTRL: "Ctrl", ALT: "Alt", MAYUS: "Mayús", LOGO: "Win" if windows else "Súper"}
    return "+".join([nombres[m] for m in MODIFICADORES if m in c.modificadores]
                    + [TECLAS[c.tecla][2]])


_ESCRIBEN = frozenset([chr(c) for c in range(ord("a"), ord("z") + 1)]
                      + [str(d) for d in range(10)] + ["space"])
"""Las teclas que escriben algo con AltGr en algún teclado."""

ALTGR = ("En Windows, Ctrl+Alt es AltGr: con una letra, un número o el espacio, el atajo le "
         "quitaría a los demás programas caracteres como «@», «#» o «€». Añade la tecla Win, "
         "quita Ctrl o Alt, o usa una tecla F.")


def problema(c: Combinacion, windows: bool) -> str | None:
    """Dice por qué una combinación no vale para un atajo de todo el sistema.

    En Windows, además, no vale Ctrl+Alt con una tecla que escribe: Windows
    da AltGr como Ctrl+Alt, así que `RegisterHotKey` se quedaría AltGr+2 («@»
    en un teclado español) y ese carácter no llegaría a ningún programa. Con
    Mayús tampoco (AltGr+Mayús escribe en algunos teclados: «Ą» en el polaco);
    con la tecla Win, sí, porque nadie la pulsa para escribir. En X11 AltGr es
    otra tecla (`ISO_Level3_Shift`) y en Wayland decide el escritorio.

    Args:
        c: La combinación.
        windows: Si es para Windows.

    Returns:
        El motivo, o `None` si vale.
    """
    if not c.tecla:
        return "Falta la tecla: pulsa los modificadores y, sin soltarlos, una letra."
    if c.tecla not in TECLAS:
        return "Esa tecla no vale para un atajo: usa una letra, un número o una tecla F."
    if not c.modificadores & {CTRL, ALT, LOGO}:
        return ("Un atajo de todo el sistema necesita Ctrl, Alt o la tecla del logotipo: "
                "sin ellos, esa tecla dejaría de escribirse en los demás programas.")
    if windows and {CTRL, ALT} <= c.modificadores and LOGO not in c.modificadores \
            and c.tecla in _ESCRIBEN:
        return ALTGR
    return None


# --- Lo que necesita cada sistema

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
"""Los modificadores de `RegisterHotKey` (winuser.h)."""


def windows(combo: str) -> tuple[int, int]:
    """Devuelve `(fsModifiers, vk)` de `RegisterHotKey` para una combinación.

    Lleva `MOD_NOREPEAT`: dejar la tecla pulsada no repite la acción.

    Raises:
        ValueError: Si la combinación no se entiende.
    """
    c = leer(combo)
    if c is None:
        raise ValueError(f"combinación ilegible: {combo!r}")
    mods = MOD_NOREPEAT
    for m, bit in ((CTRL, MOD_CONTROL), (ALT, MOD_ALT), (MAYUS, MOD_SHIFT), (LOGO, MOD_WIN)):
        if m in c.modificadores:
            mods |= bit
    return mods, TECLAS[c.tecla][0]


SHIFT_MASK, LOCK_MASK, CONTROL_MASK = 0x1, 0x2, 0x4
MOD1_MASK, MOD2_MASK, MOD4_MASK = 0x8, 0x10, 0x40
"""Las máscaras de X (X.h): Mod1 es Alt, Mod2 el bloqueo numérico y Mod4 la tecla del logotipo."""

BLOQUEOS_X11 = (0, LOCK_MASK, MOD2_MASK, LOCK_MASK | MOD2_MASK)
"""Lo que se añade a cada máscara al agarrar la tecla.

X compara el estado entero de los modificadores, y el bloqueo de mayúsculas y
el numérico cuentan: sin agarrarla también con ellos, el atajo dejaría de
funcionar con cualquiera de los dos encendido.
"""


def x11(combo: str) -> tuple[int, str]:
    """Devuelve `(máscara, keysym)` de `XGrabKey` para una combinación.

    Raises:
        ValueError: Si la combinación no se entiende.
    """
    c = leer(combo)
    if c is None:
        raise ValueError(f"combinación ilegible: {combo!r}")
    mascara = 0
    for m, bit in ((CTRL, CONTROL_MASK), (ALT, MOD1_MASK), (MAYUS, SHIFT_MASK),
                   (LOGO, MOD4_MASK)):
        if m in c.modificadores:
            mascara |= bit
    return mascara, TECLAS[c.tecla][1]


def de_x11(estado: int) -> int:
    """Devuelve el estado de una tecla de X sin los bloqueos ni lo que no es un modificador.

    Es lo que se compara con la máscara de `x11()` al llegar un `KeyPress`.
    """
    return estado & (SHIFT_MASK | CONTROL_MASK | MOD1_MASK | MOD4_MASK)


def portal(combo: str) -> str:
    """Devuelve el disparador preferido de la combinación para el portal.

    Es el formato de la especificación «shortcuts» de freedesktop: los
    modificadores `CTRL`, `ALT`, `SHIFT` y `LOGO` y el nombre XKB de la tecla,
    unidos por `+` (`CTRL+ALT+s`).

    Raises:
        ValueError: Si la combinación no se entiende.
    """
    c = leer(combo)
    if c is None:
        raise ValueError(f"combinación ilegible: {combo!r}")
    nombres = {CTRL: "CTRL", ALT: "ALT", MAYUS: "SHIFT", LOGO: "LOGO"}
    return "+".join([nombres[m] for m in MODIFICADORES if m in c.modificadores]
                    + [TECLAS[c.tecla][1]])


# --- Lo que dice el sistema al ponerlas

ERROR_HOTKEY_ALREADY_REGISTERED = 1409
"""El error de `RegisterHotKey` cuando otro ya tiene esa combinación (winerror.h)."""

YA_LA_USA = "otro programa (o el propio sistema) ya la usa"
SIN_ESA_TECLA = "este teclado no tiene esa tecla"
RECHAZADA_PORTAL = "el escritorio no la ha aceptado"
CANCELADA_PORTAL = "se ha cancelado en la ventana del escritorio"
SIN_RESPUESTA = "el sistema no ha contestado"
SIN_DECIDIR = (CANCELADA_PORTAL, SIN_RESPUESTA)
"""Los motivos que no son un no del sistema, sino que nadie ha decidido.

Un «Guardar» que acaba así no ha pasado: siguen los atajos de antes, en
`agente.json` y puestos (el agente los vuelve a poner). Llegan siempre para
todas las combinaciones a la vez: el portal cancela la petición entera y el
plazo del agente vence para todas.
"""


def sin_decidir(rechazados: Mapping[str, str]) -> str:
    """Devuelve el motivo si nadie ha decidido sobre lo pedido (`SIN_DECIDIR`), o `""`."""
    return next((m for m in rechazados.values() if m in SIN_DECIDIR), "")


def motivo_windows(error: int) -> str:
    """Devuelve por qué `RegisterHotKey` no ha puesto una combinación, dicho para el usuario.

    Args:
        error: Lo que devolvió `GetLastError()`.
    """
    if error == ERROR_HOTKEY_ALREADY_REGISTERED:
        return YA_LA_USA
    return f"Windows no la deja poner (error {error})"


def aviso_de_rechazo(accion: str, combo: str, motivo: str, en_windows: bool) -> tuple[str, str]:
    """Devuelve el aviso de un atajo que el sistema no ha dejado poner.

    Returns:
        `(título, texto)`.
    """
    return (f"No he podido poner el atajo {texto(combo, en_windows) or combo}",
            f"Para «{NOMBRES.get(accion, accion)}»: {motivo}. Se queda sin atajo; elige otra "
            f"combinación en «Atajos de teclado…» del icono de {APP_NAME}.")


def aviso_sin_guardar(motivo: str) -> tuple[str, str]:
    """Devuelve el aviso de un «Guardar» que no ha pasado (`SIN_DECIDIR`).

    Returns:
        `(título, texto)`.
    """
    return ("No he cambiado los atajos de teclado",
            f"{motivo[:1].upper()}{motivo[1:]}: siguen los de antes. Para cambiarlos, vuelve "
            f"a «Atajos de teclado…» del icono de {APP_NAME}.")


# --- Con qué se ponen en este equipo

WINDOWS, X11, PORTAL = "windows", "x11", "portal"

NOMBRE_MECANISMO = {WINDOWS: "RegisterHotKey", X11: "XGrabKey",
                    PORTAL: "el portal GlobalShortcuts"}
"""Cómo se llama en el diario cada forma de poner los atajos."""

SIN_ESCRITORIO = "no hay escritorio gráfico"
SIN_PORTAL = ("este escritorio (Wayland) no ofrece atajos de todo el sistema a los "
              "programas: le falta el portal GlobalShortcuts")
SIN_BANDEJA = "sin el icono de la bandeja no hay dónde recibirlos"
OTRO_SISTEMA = "este sistema no los tiene"


def mecanismo(es_windows: bool, entorno: Mapping[str, str]) -> tuple[str | None, str]:
    """Decide con qué se ponen los atajos en este equipo.

    En Windows, `RegisterHotKey` en el hilo de la bandeja. En Linux, el portal
    si la sesión es Wayland (agarrar una tecla con X solo funciona ahí con una
    ventana de XWayland delante, así que no sería global) y `XGrabKey` si es
    X11.

    Args:
        es_windows: Si es Windows.
        entorno: Las variables de entorno.

    Returns:
        `(mecanismo, motivo)`: uno de `WINDOWS`, `X11`, `PORTAL` y `""`, o
        `None` y por qué no se puede.
    """
    if es_windows:
        return WINDOWS, ""
    if entorno.get("XDG_SESSION_TYPE", "").lower() == "wayland" or entorno.get("WAYLAND_DISPLAY"):
        return PORTAL, ""
    if entorno.get("DISPLAY"):
        return X11, ""
    return None, SIN_ESCRITORIO


# --- Sobre qué unidad

def candidatas(resumen: Mapping[str, Any], llavero: bool = False) -> list[Mapping[str, Any]]:
    """Devuelve los dispositivos conectados sobre los que puede actuar un atajo.

    Son los de la lista con su código aceptado y de una versión que se atiende
    (`en_lista`): a los demás la bandeja tampoco les ofrece nada.

    Args:
        resumen: El resumen del agente.
        llavero: Solo los que llevan llavero.
    """
    return [u for u in resumen.get("unidades") or []
            if u.get("en_lista") and (u.get("llavero") or not llavero)]


def objetivo(resumen: Mapping[str, Any], usadas: Mapping[str, float],
             conectadas: Mapping[str, float], llavero: bool = False) -> Mapping[str, Any] | None:
    """Devuelve la fila del dispositivo sobre el que actúa un atajo.

    Es la última unidad usada: la última cuya ventana se abrió o sobre la que
    se usó una acción de la bandeja. Si no se ha usado ninguna de las que están
    conectadas, la última que se conectó. Con una sola, esa.

    Args:
        resumen: El resumen del agente (`Agente.resumen()`).
        usadas: Cuándo se usó por última vez cada dispositivo, por id.
        conectadas: Cuándo se conectó cada uno, por id.
        llavero: Elegir solo entre las que llevan llavero: que la última usada
            no lo lleve no deja sin abrir el de otra enchufada al lado.

    Returns:
        Su fila del resumen, o `None` si no hay ninguno.
    """
    filas = candidatas(resumen, llavero)
    if len(filas) <= 1:
        return filas[0] if filas else None
    usada = [f for f in filas if f.get("id") in usadas]
    if usada:
        return max(usada, key=lambda f: usadas[f.get("id")])
    return max(enumerate(filas), key=lambda par: (conectadas.get(par[1].get("id"), 0.0),
                                                  par[0]))[1]


@dataclass(frozen=True)
class Respuesta:
    """Lo que hace un atajo pulsado.

    Args:
        peticiones: Las peticiones del buzón que se atienden, las mismas que
            las de la entrada de la bandeja que hace lo mismo.
        aviso: `(título, texto)` del aviso que lo cuenta, o `None` si no hace
            falta (abrir algo se ve solo).
        unidad: El id del dispositivo sobre el que actúa, o `""`.
    """
    peticiones: tuple[dict, ...] = ()
    aviso: tuple[str, str] | None = None
    unidad: str = ""


def pulsado(accion: str, resumen: Mapping[str, Any], usadas: Mapping[str, float],
            conectadas: Mapping[str, float]) -> Respuesta:
    """Decide qué hace un atajo pulsado.

    Sincronizar y pausar no se ven, así que lo dice un aviso corto con el
    nombre de la unidad. Abrir su carpeta o su ventana no avisa: se ve. Sin
    ninguna unidad sobre la que actuar, o si la acción no se puede hacer, el
    aviso dice por qué y no se pide nada.

    La pausa es la de esa unidad (la del «Pausar» de su ventana, que se
    guarda): con ella puesta, el atajo la quita; con la pausa de todo el agente
    puesta (la de la bandeja), el atajo la quita, como el «Reanudar todo» de
    su ventana.

    Args:
        accion: Una de `ACCIONES`.
        resumen: El resumen del agente.
        usadas: Cuándo se usó por última vez cada dispositivo, por id.
        conectadas: Cuándo se conectó cada uno, por id.
    """
    if accion not in ACCIONES:
        return Respuesta()
    if accion == LLAVERO:
        return _llavero(resumen, usadas, conectadas)
    fila = objetivo(resumen, usadas, conectadas)
    if fila is None:
        return Respuesta(aviso=(f"{APP_NAME}: no hay ninguna unidad a mano",
                                f"El atajo de «{NOMBRES[accion]}» actúa sobre la última "
                                f"unidad que has usado, y no hay ninguna conectada que "
                                f"atienda este equipo."))
    uid, nombre = str(fila.get("id", "")), str(fila.get("nombre") or APP_NAME)
    if accion == CARPETA:
        return Respuesta(({"pide": equipo.PIDE_EXPLORAR, "id": uid},), unidad=uid)
    if accion == VENTANA:
        return Respuesta(({"pide": equipo.PIDE_ABRIR, "id": uid},), unidad=uid)
    if accion == PAUSAR:
        if fila.get("pausada"):
            return Respuesta(({"pide": equipo.PIDE_REANUDAR, "id": uid},),
                             (f"{nombre}: reanudada", "Vuelve a sincronizarse."), uid)
        if resumen.get("pausado"):
            return Respuesta(({"pide": equipo.PIDE_SIGUE},),
                             (f"{nombre}: reanudado todo",
                              f"{APP_NAME} vuelve a sincronizar todas las unidades."), uid)
        return Respuesta(({"pide": equipo.PIDE_PAUSAR_RAIZ, "id": uid},),
                         (f"{nombre}: en pausa",
                          "No se sincroniza hasta que vuelvas a pulsar el atajo."), uid)
    if fila.get("atendida"):
        return Respuesta(({"pide": equipo.PIDE_PASADA, "id": uid, "parejas": []},),
                         (f"{nombre}: sincronizando", "Empieza en cuanto le toque."), uid)
    if fila.get("pausada"):
        porque = "Está en pausa: el atajo de pausar la reanuda."
    else:
        motivo = str(fila.get("motivo") or "").strip()
        porque = (f"El agente no la sincroniza ahora ({motivo})." if motivo else
                  "El agente no la sincroniza en segundo plano en este equipo.")
    return Respuesta(aviso=(f"{nombre}: no la sincronizo", porque), unidad=uid)


def _llavero(resumen: Mapping[str, Any], usadas: Mapping[str, float],
             conectadas: Mapping[str, float]) -> Respuesta:
    """Decide qué hace el atajo de «Abrir el llavero».

    Es la petición de «Abrir llavero» de la bandeja (`PIDE_LLAVERO`) sobre la
    última usada de las que llevan llavero, sin aviso: se ve abrirse, y con las
    pasadas retenidas el agente trae lo último igual (`Agente._traer_al_abrir()`).
    Lo que no se ve sí avisa: no hay ninguna con llavero, o se está
    actualizando o expulsando (el agente no la abre, y sin aviso el atajo
    parecería roto).
    """
    if not resumen.get("abre_llavero"):
        return Respuesta(aviso=(f"{APP_NAME}: aquí no se abre el llavero",
                                "Este equipo no abre el llavero de una unidad: solo se abre "
                                "en Windows y en Linux."))
    fila = objetivo(resumen, usadas, conectadas, llavero=True)
    if fila is None:
        return Respuesta(aviso=(f"{APP_NAME}: no hay ningún llavero a mano",
                                f"El atajo de «{NOMBRES[LLAVERO]}» abre el de la última unidad "
                                f"con llavero que has usado, y no hay ninguna conectada que "
                                f"atienda este equipo."))
    uid, nombre = str(fila.get("id", "")), str(fila.get("nombre") or APP_NAME)
    if fila.get("actualizando") or fila.get("expulsando"):
        porque = ("Se está actualizando: vuelve a pulsar el atajo cuando acabe."
                  if fila.get("actualizando") else "Se está expulsando.")
        return Respuesta(aviso=(f"{nombre}: ahora no abro su llavero", porque), unidad=uid)
    return Respuesta(({"pide": equipo.PIDE_LLAVERO, "id": uid},), unidad=uid)


# --- Grabar

_TECLAS_MODIFICADOR = {"Control_L": CTRL, "Control_R": CTRL, "Alt_L": ALT, "Alt_R": ALT,
                       "Meta_L": ALT, "Meta_R": ALT, "Shift_L": MAYUS, "Shift_R": MAYUS,
                       "Super_L": LOGO, "Super_R": LOGO, "Win_L": LOGO, "Win_R": LOGO,
                       "Hyper_L": LOGO, "Hyper_R": LOGO}
"""Los keysym de Tk de las teclas modificadoras, en Windows y en X11."""

_VK_A_TECLA = {vk: nombre for nombre, (vk, _x, _t) in TECLAS.items()}
_KEYSYM_A_TECLA = {x.lower(): nombre for nombre, (_vk, x, _t) in TECLAS.items()}

ESTADO_TK = {False: {CTRL: 0x4, MAYUS: 0x1, ALT: 0x8, LOGO: 0x40},
             True: {CTRL: 0x4, MAYUS: 0x1, ALT: 0x20000}}
"""Qué bit del `state` de un evento de teclado de Tk es cada modificador.

En X11 es el de X (Mod1 Alt, Mod4 la tecla del logotipo). En Windows Alt es
`0x20000` (el `ALT_MASK` de Tk, `tkWinInt.h`) y la tecla del logotipo no sale
en el estado: se sabe por su propio `KeyPress`.
"""


@dataclass
class Teclas:
    """Lo que la ventana va viendo del teclado mientras graba una combinación.

    Los modificadores se siguen por sus propios `KeyPress`/`KeyRelease` y por
    el `state` de cada evento: la tecla del logotipo en Windows solo se ve así,
    y el `state` cubre un modificador que ya estaba pulsado al empezar.

    Args:
        windows: Si la ventana es de Windows (cambian el `state` de Tk y la
            tecla, que allí se lee de su tecla virtual).
    """
    windows: bool
    pulsados: set[str] = field(default_factory=set)

    def soltar_todo(self) -> None:
        """Olvida los modificadores: la ventana ha perdido el foco y no verá sus `KeyRelease`."""
        self.pulsados.clear()

    def suelta(self, keysym: str) -> None:
        """Apunta que se ha soltado una tecla."""
        m = _TECLAS_MODIFICADOR.get(keysym)
        if m is not None:
            self.pulsados.discard(m)

    def pulsa(self, keysym: str, keycode: int, estado: int) -> Combinacion | None:
        """Apunta una tecla pulsada y devuelve la combinación si ya hay una.

        Args:
            keysym: El `keysym` del evento de Tk.
            keycode: Su `keycode` (en Windows, la tecla virtual).
            estado: Su `state`.

        Returns:
            `None` si es un modificador (la combinación sigue a medias); si no,
            la combinación con los modificadores pulsados. Si esa tecla no vale
            para un atajo, su `tecla` no está en `TECLAS` (`problema()` lo dice).
        """
        m = _TECLAS_MODIFICADOR.get(keysym)
        if m is not None:
            self.pulsados.add(m)
            return None
        mods = set(self.pulsados)
        for nombre, bit in ESTADO_TK[self.windows].items():
            if estado & bit:
                mods.add(nombre)
        tecla = (_VK_A_TECLA.get(keycode) if self.windows else None) \
            or _KEYSYM_A_TECLA.get(keysym.lower()) or f"?{keysym}"
        return Combinacion(frozenset(mods), tecla)


GRABANDO = "Pulsa la combinación…"
SIN_ATAJO = "Sin atajo"
ESC = "Esc para dejarlo como estaba."
MAS_LARGA = "Ctrl+Alt+Mayús+Súper+AvPág"
"""La combinación más larga que se puede enseñar: la ventana le guarda sitio."""


@dataclass(frozen=True)
class Fila:
    """Lo que enseña la fila de una acción en la ventana que graba.

    Args:
        accion: La acción.
        nombre: Cómo se llama.
        combinacion: Lo que dice su casilla: la combinación, «Sin atajo» o
            «Pulsa la combinación…».
        nota: Lo que va debajo: por qué no vale lo que se ha pulsado, o por qué
            el sistema no la ha dejado poner. Vacía si no hay nada que decir.
        grabando: Si es la que está grabando.
        borrable: Si tiene un atajo que se pueda quitar.
    """
    accion: str
    nombre: str
    combinacion: str
    nota: str = ""
    grabando: bool = False
    borrable: bool = False


@dataclass(frozen=True)
class Edicion:
    """Los atajos mientras se cambian en la ventana, antes de guardarlos.

    Args:
        windows: Si se enseñan con los nombres de Windows.
        guardados: Los que tiene el agente, por acción.
        atajos: Los de la ventana, por acción.
        notas: Lo que dice cada fila debajo, por acción.
        grabando: La acción cuya combinación se está grabando, o `""`.
    """
    windows: bool
    guardados: Mapping[str, str] = field(default_factory=dict)
    atajos: Mapping[str, str] = field(default_factory=dict)
    notas: Mapping[str, str] = field(default_factory=dict)
    grabando: str = ""

    @classmethod
    def desde(cls, estado: Mapping[str, Any], windows: bool) -> "Edicion":
        """Empieza con lo que dice el agente en `estado.json` (`resumen()["atajos"]`).

        Una acción cuyo atajo no se pudo poner sale con su motivo.
        """
        guardados: dict[str, str] = {}
        notas: dict[str, str] = {}
        acciones = estado.get("acciones") if isinstance(estado.get("acciones"), Mapping) else {}
        for accion in ACCIONES:
            dato = acciones.get(accion) if isinstance(acciones.get(accion), Mapping) else {}
            combo = normal(dato.get("combo"))
            if combo:
                guardados[accion] = combo
            if isinstance(dato.get("error"), str) and dato["error"]:
                notas[accion] = f"No se ha podido poner: {dato['error']}."
        return cls(windows, guardados, dict(guardados), notas)

    def filas(self) -> list[Fila]:
        """Devuelve lo que enseña cada fila, en el orden de `ACCIONES`.

        La que graba dice que se pulse y, si no tiene otra cosa que decir, cómo
        dejarlo.
        """
        filas = []
        for accion in ACCIONES:
            combo = self.atajos.get(accion, "")
            nota = self.notas.get(accion, "")
            if accion == self.grabando:
                dice, nota = GRABANDO, nota or ESC
            else:
                dice = texto(combo, self.windows) or SIN_ATAJO
            filas.append(Fila(accion, NOMBRES[accion], dice, nota, accion == self.grabando,
                              bool(combo)))
        return filas

    @property
    def cambiada(self) -> bool:
        """Indica si hay algo que guardar."""
        return {a: c for a, c in self.atajos.items() if c} != \
            {a: c for a, c in self.guardados.items() if c}

    def grabar(self, accion: str) -> "Edicion":
        """Empieza a grabar la combinación de una acción (o deja de grabar con `""`)."""
        notas = {a: n for a, n in self.notas.items() if a != accion}
        return replace(self, grabando=accion if accion in ACCIONES else "", notas=notas)

    def borrar(self, accion: str) -> "Edicion":
        """Quita el atajo de una acción."""
        atajos = {a: c for a, c in self.atajos.items() if a != accion}
        notas = {a: n for a, n in self.notas.items() if a != accion}
        return replace(self, atajos=atajos, notas=notas,
                       grabando="" if self.grabando == accion else self.grabando)

    def pulsada(self, c: Combinacion) -> "Edicion":
        """Pone a la acción que graba lo que se acaba de pulsar, si vale.

        Si no vale (le falta Ctrl, Alt o el logotipo, o la tecla no se puede
        usar) se dice en su fila y sigue grabando. Si es la de otra acción, se
        la quita a esa: una combinación hace una sola cosa.
        """
        if not self.grabando:
            return self
        porque = problema(c, self.windows)
        if porque is not None:
            return replace(self, notas={**self.notas, self.grabando: porque})
        combo = str(c)
        notas = {a: n for a, n in self.notas.items() if a != self.grabando}
        atajos = dict(self.atajos)
        for otra, suya in list(atajos.items()):
            if suya == combo and otra != self.grabando:
                del atajos[otra]
                notas[otra] = (f"{texto(combo, self.windows)} ahora es de "
                               f"«{NOMBRES[self.grabando]}».")
        atajos[self.grabando] = combo
        return replace(self, atajos=atajos, notas=notas, grabando="")

    def pedido(self) -> dict[str, str]:
        """Devuelve los atajos que se piden al guardar, por acción (sin las vacías)."""
        return {a: c for a, c in self.atajos.items() if c and a in ACCIONES}

    def veredicto(self, respuesta_: Mapping[str, Any]) -> "Edicion":
        """Pone lo que ha contestado el agente a un «Guardar» (`rechazados`, `guardados`).

        Los que el sistema no ha dejado poner se quedan sin atajo y su fila dice
        por qué. Si nadie ha decidido (`SIN_DECIDIR`: se canceló en la ventana
        del escritorio, el sistema no contestó), no se ha guardado nada: la
        ventana se queda con lo que tenía, para volver a guardarlo. Lo guardado
        es lo que dice el agente (`guardados`).
        """
        rechazados = _rechazados(respuesta_)
        notas = dict(self.notas)
        atajos = dict(self.atajos)
        for accion, motivo in rechazados.items():
            if accion in ACCIONES and motivo not in SIN_DECIDIR:
                combo = atajos.pop(accion, "")
                notas[accion] = (f"{texto(combo, self.windows) or 'Esa combinación'} no se ha "
                                 f"podido poner: {motivo}.")
        guardados = respuesta_.get("guardados")
        if isinstance(guardados, Mapping):
            guardados = {a: normal(c) for a, c in guardados.items()
                         if a in ACCIONES and normal(c)}
        else:
            guardados = dict(self.guardados) if sin_decidir(rechazados) else dict(atajos)
        return replace(self, atajos=atajos, guardados=guardados, notas=notas, grabando="")


def _rechazados(respuesta_: Mapping[str, Any]) -> dict[str, str]:
    """Devuelve los rechazados de una respuesta del agente, por acción."""
    rechazados = respuesta_.get("rechazados")
    if not isinstance(rechazados, Mapping):
        return {}
    return {str(a): str(m) for a, m in rechazados.items()}


# --- La ventana que graba y el agente

ESPERA = 15.0
"""Segundos tras un «Guardar» a partir de los que la ventana dice que el agente tarda."""
ESPERA_PORTAL = 200.0
"""Lo mismo con el portal: contesta cuando se confirma en la ventana del escritorio."""

COMPROBANDO = "Comprobando con el sistema…"
CONFIRMA = "Confirma los atajos en la ventana del escritorio…"
TARDA = ("El agente todavía no ha contestado\nPuede estar ocupado con una unidad, o no estar en "
         "marcha. Ya tiene el encargo y lo hará en cuanto pueda; si alguno no se puede poner, "
         "te avisará. Puedes esperar aquí o cerrar la ventana.")
SIN_ENCARGO = "No he podido dejarle el encargo al agente\nVuelve a intentarlo."
NO_TODOS = ("No se han podido poner todos\nLos que el sistema no deja se quedan sin atajo: "
            "elige otra combinación y vuelve a guardar.")


def leer_estado() -> dict:
    """Devuelve lo que cuenta el agente de los atajos (`resumen()["atajos"]`, en `estado.json`).

    Punto de indirección: los tests lo sustituyen.
    """
    datos = equipo.leer_estado().get("atajos")
    return datos if isinstance(datos, dict) else {}


def pedir(peticion: dict) -> bool:
    """Deja una petición en el buzón del agente (`equipo.pedir()`).

    Punto de indirección: los tests lo sustituyen.
    """
    return equipo.pedir(peticion)


@dataclass(frozen=True)
class Guardado:
    """Un «Guardar» de la ventana, que espera la respuesta del agente.

    No caduca: la petición se queda en el buzón del agente (que la atiende
    aunque se reinicie), así que lo que pide puede pasar en cualquier momento.

    Args:
        vez: Lo que lo identifica en la respuesta.
        tarda: Cuándo (`time.monotonic()`) se dice que el agente tarda.
    """
    vez: str
    tarda: float


def guardar(edicion: Edicion, portal: bool, ahora: float) -> Guardado | None:
    """Deja en el buzón del agente lo que pide `edicion` (`PIDE_ATAJOS`, con una `vez` propia).

    Args:
        edicion: Los atajos de la ventana.
        portal: Si se ponen con el portal, que contesta cuando se confirman.
        ahora: La hora de `time.monotonic()`.

    Returns:
        Lo que hay que esperar, o `None` si no se ha podido dejar.
    """
    vez = uuid.uuid4().hex
    if not pedir({"pide": equipo.PIDE_ATAJOS, "vez": vez, "atajos": edicion.pedido()}):
        return None
    return Guardado(vez, ahora + (ESPERA_PORTAL if portal else ESPERA))


def respuesta(guardado: Guardado) -> dict | None:
    """Devuelve lo que ha contestado el agente a ese «Guardar», o `None` si todavía nada."""
    r = leer_estado().get("respuesta")
    return r if isinstance(r, dict) and r.get("vez") == guardado.vez else None


def tras_guardar(respuesta_: Mapping[str, Any]) -> tuple[str, str] | None:
    """Dice qué contar con la respuesta del agente a un «Guardar».

    Returns:
        `None` si se ha guardado todo (la ventana se cierra); si no, el texto
        para el resultado y su tono.
    """
    rechazados = _rechazados(respuesta_)
    if not rechazados:
        return None
    motivo = sin_decidir(rechazados)
    if motivo:
        return (f"No se ha guardado nada\n{motivo[:1].upper()}{motivo[1:]}: siguen los atajos "
                f"de antes. Vuelve a guardar para intentarlo otra vez.", "aviso")
    return NO_TODOS, "aviso"


# --- Lo que el agente cuenta de los atajos

def resumen_de(mecanismo_: str | None, motivo: str, puestos: Mapping[str, str],
               errores: Mapping[str, str], grabando: bool,
               respuesta: Mapping[str, Any] | None) -> dict:
    """Devuelve lo que va en `resumen()["atajos"]`, para la bandeja y la ventana.

    Args:
        mecanismo_: Con qué se ponen (`mecanismo()`), o `None` si no se puede.
        motivo: Por qué no se puede; vacío si se puede.
        puestos: Los atajos guardados, por acción.
        errores: Por qué el sistema no ha dejado poner los que no, por acción.
        grabando: Si la ventana de grabarlos está abierta.
        respuesta: Lo último contestado a un «Guardar» (`vez`, `rechazados`,
            `guardados`).
    """
    return {"mecanismo": mecanismo_ or "", "motivo": motivo,
            "acciones": {a: {"combo": puestos.get(a, ""), "error": errores.get(a, "")}
                         for a in ACCIONES if puestos.get(a) or errores.get(a)},
            "grabando": grabando, "respuesta": dict(respuesta) if respuesta else None}


def validar(pedidos: Any, windows: bool) -> tuple[dict[str, str], dict[str, str]]:
    """Separa unos atajos en los que valen y los que no.

    Es para lo que pide un «Guardar» y para lo que hay en `agente.json`, que se
    puede haber escrito a mano o con otra versión. Una acción desconocida se
    ignora; una combinación ilegible o que no vale (`problema()`), o repetida
    en otra acción, se rechaza con su motivo.

    Args:
        pedidos: Los atajos, por acción.
        windows: Si es para Windows (`problema()`).

    Returns:
        `(validos, rechazados)`, los dos por acción.
    """
    validos: dict[str, str] = {}
    rechazados: dict[str, str] = {}
    if not isinstance(pedidos, Mapping):
        return validos, rechazados
    vistos: dict[str, str] = {}
    for accion in ACCIONES:
        crudo = pedidos.get(accion)
        if crudo in (None, ""):
            continue
        c = leer(crudo)
        porque = "no se entiende" if c is None else problema(c, windows)
        if porque is not None:
            rechazados[accion] = porque.rstrip(".")
            continue
        combo = str(c)
        if combo in vistos:
            rechazados[accion] = f"ya es la de «{NOMBRES[vistos[combo]]}»"
            continue
        vistos[combo] = accion
        validos[accion] = combo
    return validos, rechazados
