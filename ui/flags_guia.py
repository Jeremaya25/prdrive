#!/usr/bin/env python3
"""La guía de flags de rclone: las fichas, la búsqueda y la página de `docs/guia`, sin Tkinter ni red.

Es la parte 3 de #95. Une dos fuentes y no escribe nada que ya esté en una de ellas:

- **Lo que prdrive hace con cada flag** se lee del modelo: quién lo pone (`model.BASE_FLAGS`,
  los flags de cada `Mode`, `FLAGS_RESERVADOS`, `problema_flag()`), con qué valor y con qué
  motivo. Un valor que cambia en `model.py` cambia aquí sin tocar nada.
- **Lo que significa** sale de `ui/flags_catalogo.py` (escrito a mano, solo para los flags
  que prdrive usa y los de borrado, comparación, filtrado, tiempos y concurrencia) y, para
  el resto de los de la rclone fijada, de `common/flags_rclone.json` (su ayuda corta, en
  inglés y marcada como tal).

La ventana (`ui/tk_flags_guia.py`) solo dibuja lo que da `buscar()` y `detalle()`, y
`docs/guia/flags-de-rclone.md` es exactamente `a_markdown()`: un test comprueba que no
divergen. Nada de esto usa la red ni restringe qué se puede escribir: la guía ayuda, un
flag que no aparece aquí se admite igual (`ui/flags_ayuda.py`).
"""

from __future__ import annotations

import re
import unicodedata
from typing import NamedTuple

from common import model

from . import flags_ayuda, flags_editor
from .flags_catalogo import (  # noqa: F401 — los riesgos y los temas se piden desde aquí
    ENTRADAS, RIESGO_BORRA, RIESGO_LEE, RIESGO_NOMBRES, RIESGOS, TEMA_BORRADO, TEMA_COMPARAR,
    TEMA_CONCURRENCIA, TEMA_FILTRADO, TEMA_OTROS, TEMA_PRDRIVE, TEMA_TIEMPOS, TEMAS)

ESTADO_LIBRE = "libre"
"""Estado: prdrive no lo toca; lo que se escriba va tal cual a rclone."""
ESTADO_VALOR = "valor"
"""Estado: prdrive lo pone con un valor de partida que se puede cambiar."""
ESTADO_FIJO = "fijo"
"""Estado: lo pone `sync.py` en cada pasada y no se puede escribir (`FLAGS_RESERVADOS`)."""
ESTADO_NO_ADMITIDO = "no_admitido"
"""Estado: el config lo rechaza (lanza un programa o escribe un fichero del equipo)."""
ESTADOS = (ESTADO_LIBRE, ESTADO_VALOR, ESTADO_FIJO, ESTADO_NO_ADMITIDO)

ETIQUETA_ESTADO = {
    ESTADO_LIBRE: "No lo toca prdrive",
    ESTADO_VALOR: "prdrive le da un valor, que puedes cambiar",
    ESTADO_FIJO: "Lo pone prdrive, no se puede cambiar",
    ESTADO_NO_ADMITIDO: "No se admite en el config",
}
"""Cómo se marca cada estado para la persona."""

ETIQUETAS_RIESGO = {
    RIESGO_LEE: "Solo lectura",
    RIESGO_NOMBRES: "Cambia nombres",
    RIESGO_BORRA: "Borra o reescribe",
}
"""Cómo se llama cada riesgo para la persona."""

DESCRIPCION_RIESGO = {
    RIESGO_LEE: "no cambia ningún fichero por sí solo: ajusta cómo se mira, cuánto va a la "
                "vez o qué se cuenta.",
    RIESGO_NOMBRES: "cambia el nombre de ficheros, o los aparta con otro nombre.",
    RIESGO_BORRA: "borra o reescribe ficheros, o es el freno que los protege. Pruébalo "
                  "antes con «Simular».",
}
"""Qué quiere decir cada riesgo."""

ETIQUETAS_TEMA = {
    TEMA_PRDRIVE: "Los que pone prdrive",
    TEMA_BORRADO: "Borrados y sobrescrituras",
    TEMA_COMPARAR: "Cómo decide qué ha cambiado",
    TEMA_FILTRADO: "Qué ficheros entran",
    TEMA_TIEMPOS: "Esperas, reintentos y duración",
    TEMA_CONCURRENCIA: "Cuánto va a la vez y a qué velocidad",
    TEMA_OTROS: "Sin explicación propia",
}
"""Cómo se llama cada tema para la persona."""

DESCRIPCION_TEMA = {
    TEMA_PRDRIVE: "prdrive pone estos flags en cada pasada o les da un valor de partida. Los "
                  "marcados «Lo pone prdrive, no se puede cambiar» no se pueden escribir en "
                  "una pareja; los que solo traen un valor se pueden cambiar. Aquí están "
                  "también los que el config no admite, porque lanzarían un programa o "
                  "escribirían un fichero de tu equipo.",
    TEMA_BORRADO: "Qué se borra del otro lado, cuándo, y lo que lo frena. Pruébalo todo "
                  "antes con «Simular», sobre todo en una pareja *-mirror, que borra.",
    TEMA_COMPARAR: "Cómo decide rclone que un fichero ya está al día o que hay que copiarlo.",
    TEMA_FILTRADO: "Qué ficheros se dejan fuera o se eligen. Para ignorar ficheros por su "
                   "nombre, lo normal es el cuadro «Excluir» de la pareja.",
    TEMA_TIEMPOS: "Cuánto espera rclone, cuántas veces reintenta y cuánto puede durar una "
                  "pasada.",
    TEMA_CONCURRENCIA: "Cuántos ficheros van a la vez, con cuánta memoria y a qué velocidad.",
    TEMA_OTROS: "Los demás flags de la rclone fijada. Solo se sabe lo que dice su ayuda "
                "corta, que viene en inglés.",
}
"""Qué agrupa cada tema."""

R_ESTADO = "Quién lo pone"
R_PARA_QUE = "Para qué sirve"
R_EFECTO = "Qué hace en la práctica"
R_RIESGO = "Riesgo"
R_MODOS = "Modos donde sirve"
R_TU_PAREJA = "En tu pareja"
R_PRDRIVE = "Lo que pone prdrive"
R_EJEMPLO = "Ejemplo"
R_EN_SU_LUGAR = "En su lugar"
R_RCLONE = "Ayuda de rclone (en inglés)"
"""Los rótulos de `detalle()`, que la ventana y la página comparten."""

SIN_EXPLICACION = ("Sin explicación propia: de este flag solo está la ayuda corta de rclone, "
                   "que viene en inglés.")
"""Lo que se dice de un flag que no está en el catálogo explicado."""


class Ficha(NamedTuple):
    """Todo lo que la guía sabe de un flag.

    Args:
        nombre: Sin guiones y con `-`, como lo ve rclone.
        tema: Uno de `TEMAS`; `TEMA_PRDRIVE` para todo lo que prdrive pone o rechaza y
            `TEMA_OTROS` para lo que no tiene explicación propia.
        estado: Uno de `ESTADOS`, leído del modelo.
        riesgo: Uno de `RIESGOS`, o `None` si el flag no está explicado.
        modos: Los modos donde sirve (en uno explicado) o donde rclone lo acepta.
        titulo: Una línea que dice de qué va; vacío si no está explicado.
        para_que: Para qué sirve; vacío si no está explicado.
        efecto: Qué hace en la práctica; vacío si no está explicado.
        ejemplo: Cómo se escribe (TOML) o, en uno que no se escribe, qué usar en su lugar.
        prdrive: El valor que pone prdrive, leído del modelo; vacío si no lo toca.
        motivo: Por qué no se puede escribir (de `model`), en `ESTADO_FIJO` y
            `ESTADO_NO_ADMITIDO`.
        ayuda: La ayuda corta de rclone, en inglés.
        defecto: El valor de fábrica de rclone.
        tipo: El tipo según rclone.
        explicada: Si tiene explicación propia (está en `flags_catalogo.ENTRADAS`).
        buscar: Las palabras con las que se pregunta por él (solo para buscar).
    """
    nombre: str
    tema: str
    estado: str
    riesgo: str | None
    modos: tuple[str, ...]
    titulo: str
    para_que: str
    efecto: str
    ejemplo: str
    prdrive: str
    motivo: str
    ayuda: str
    defecto: str
    tipo: str
    explicada: bool
    buscar: str


def _unir(nombres: list[str]) -> str:
    """Devuelve `a`, `a y b` o `a, b y c`."""
    return nombres[0] if len(nombres) == 1 else ", ".join(nombres[:-1]) + " y " + nombres[-1]


def _valor_de_prdrive(nombre: str, a_mano: str) -> str:
    """Devuelve qué valor pone prdrive para este flag, leído del modelo; vacío si no lo toca.

    Args:
        nombre: El flag, normalizado.
        a_mano: El texto del catálogo para lo que el modelo no tiene (un flag que prdrive
            pone solo en ciertos casos); va detrás de lo que diga el modelo.
    """
    partes: list[str] = []
    for clave, valor in model.BASE_FLAGS.items():
        if flags_ayuda.normalizar(clave) == nombre:
            partes.append(f"{flags_editor.valor_texto(valor)} en todos los modos")
    por_valor: dict[str, list[str]] = {}
    for modo in model.MODES.values():
        for clave, valor in modo.flags.items():
            if flags_ayuda.normalizar(clave) == nombre:
                por_valor.setdefault(flags_editor.valor_texto(valor), []).append(modo.name)
    partes += [f"{valor} en {_unir(modos)}" for valor, modos in por_valor.items()]
    if a_mano:
        partes.append(a_mano)
    return " · ".join(partes)


def _estado(nombre: str, con_valor: bool) -> tuple[str, str]:
    """Devuelve el estado de un flag y, si no se puede escribir, el motivo del modelo.

    Args:
        nombre: El flag, normalizado.
        con_valor: Si prdrive le pone un valor (que se puede cambiar).
    """
    if nombre in model.FLAGS_RESERVADOS:
        return ESTADO_FIJO, model.FLAGS_RESERVADOS[nombre]
    motivo = model.problema_flag(nombre)
    if motivo:
        return ESTADO_NO_ADMITIDO, motivo
    return (ESTADO_VALOR if con_valor else ESTADO_LIBRE), ""


def _modos_de(comandos: tuple[str, ...]) -> tuple[str, ...]:
    """Devuelve los modos cuya orden de rclone es una de `comandos`."""
    return tuple(m.name for m in model.MODES.values() if m.verb in comandos)


def _construir() -> tuple[Ficha, ...]:
    """Hace las fichas: una por cada flag de la rclone fijada y por cada explicación escrita."""
    datos = flags_ayuda.datos().flags
    entradas = {flags_ayuda.normalizar(e.nombre): e for e in ENTRADAS}
    posicion = {flags_ayuda.normalizar(e.nombre): i for i, e in enumerate(ENTRADAS)}
    fichas: list[tuple[tuple, Ficha]] = []
    for nombre in sorted(set(datos) | set(entradas)):
        e = entradas.get(nombre)
        f = datos.get(nombre)
        valor = _valor_de_prdrive(nombre, e.prdrive if e else "")
        estado, motivo = _estado(nombre, bool(valor))
        comandos = f.comandos if f else flags_ayuda.VERBOS
        if e is not None:
            modos = tuple(e.modos)
            tema, riesgo = e.tema, e.riesgo
            textos = (e.titulo, e.para_que, e.efecto, e.ejemplo)
            buscar = e.buscar
            orden = (TEMAS.index(tema), posicion[nombre])
        else:
            modos = _modos_de(comandos)
            if nombre in flags_ayuda.SOLO_SINCRONIZA:
                modos = tuple(m for m in modos if model.MODES[m].verb != "copy")
            tema = TEMA_PRDRIVE if estado != ESTADO_LIBRE else TEMA_OTROS
            riesgo, textos, buscar = None, ("", "", "", ""), ""
            orden = (len(TEMAS), 0)
        fichas.append(((*orden, nombre), Ficha(
            nombre=nombre, tema=tema, estado=estado, riesgo=riesgo, modos=modos,
            titulo=textos[0], para_que=textos[1], efecto=textos[2], ejemplo=textos[3],
            prdrive=valor, motivo=motivo, ayuda=f.ayuda if f else "",
            defecto=f.defecto if f else "", tipo=f.tipo if f else "",
            explicada=e is not None, buscar=buscar)))
    return tuple(f for _clave, f in sorted(fichas, key=lambda par: par[0]))


_FICHAS: tuple[Ficha, ...] | None = None
_POR_NOMBRE: dict[str, Ficha] = {}


def fichas() -> tuple[Ficha, ...]:
    """Devuelve todas las fichas: las explicadas primero, por tema y en el orden del catálogo.

    Después van las que solo tienen la ayuda de rclone, por nombre. Se hacen una vez.
    """
    global _FICHAS
    if _FICHAS is None:
        _FICHAS = _construir()
        _POR_NOMBRE.clear()
        _POR_NOMBRE.update({f.nombre: f for f in _FICHAS})
    return _FICHAS


def ficha(nombre: str) -> Ficha | None:
    """Devuelve la ficha de un flag (como lo escriba la persona), o `None` si no se conoce."""
    fichas()
    return _POR_NOMBRE.get(flags_ayuda.normalizar(nombre))


# ----------------------------------------------------------------------------
# Buscar
# ----------------------------------------------------------------------------

_RELLENO = frozenset(
    "a al algo ante aqui como con cual cuales cuando cuanto cuantos cuanta cuantas de del desde "
    "donde el ella ellos en entre es esta estan este esto hace hacen hacer hago haga hay la las "
    "le les lo los me mi mis muy ni no o otra otro para pasa pero por porque que quiero se si "
    "sin sobre su sus te tu tus un una unas uno unos y ya".split())
"""Las palabras de una pregunta que no dicen nada del flag («qué hace con los…»)."""

_PALABRA = re.compile(r"[a-z0-9]+")


def _plano(texto: str) -> str:
    """Devuelve el texto en minúsculas y sin tildes: `Cómo` y `como` son lo mismo."""
    descompuesto = unicodedata.normalize("NFKD", str(texto).lower())
    return "".join(c for c in descompuesto if not unicodedata.combining(c))


def _raiz(palabra: str) -> str:
    """Devuelve la raíz con la que se comparan dos palabras: `borrados` y `borrar` son `borra`."""
    return palabra[:5]


def _raices(texto: str) -> frozenset[str]:
    """Devuelve las raíces de las palabras de un texto."""
    return frozenset(_raiz(p) for p in _PALABRA.findall(_plano(texto)))


class _Indice(NamedTuple):
    """Las palabras de una ficha, por campo, para buscar sin recorrer sus textos cada vez."""
    nombre: tuple[str, ...]
    buscar: frozenset[str]
    titulo: frozenset[str]
    texto: frozenset[str]
    etiquetas: frozenset[str]
    ayuda: frozenset[str]


_INDICES: dict[str, _Indice] = {}

PESO_NOMBRE = 10
PESO_PREFIJO = 8
PESO_BUSCAR = 7
PESO_TITULO = 5
PESO_TEXTO = 3
PESO_ETIQUETA = 2
PESO_AYUDA = 2
"""Cuánto cuenta que una palabra de la pregunta aparezca en cada campo de una ficha."""


def _indice(f: Ficha) -> _Indice:
    """Devuelve el índice de palabras de una ficha, hecho una sola vez."""
    if f.nombre not in _INDICES:
        etiquetas = " ".join(filter(None, (
            ETIQUETAS_RIESGO.get(f.riesgo or "", ""), ETIQUETA_ESTADO[f.estado]
            if f.estado != ESTADO_LIBRE else "", ETIQUETAS_TEMA[f.tema], " ".join(f.modos))))
        _INDICES[f.nombre] = _Indice(
            nombre=tuple(_PALABRA.findall(_plano(f.nombre))), buscar=_raices(f.buscar),
            titulo=_raices(f.titulo), texto=_raices(f"{f.para_que} {f.efecto}"),
            etiquetas=_raices(etiquetas), ayuda=_raices(f.ayuda))
    return _INDICES[f.nombre]


def _puntos(f: Ficha, palabras: list[str]) -> tuple[int, int]:
    """Devuelve `(palabras de la pregunta que aparecen, puntos)` de una ficha.

    De cada palabra cuenta cada campo donde sale, así que lo que está en el nombre, en las
    palabras con las que se pregunta y en el texto pesa más que lo que solo se menciona.
    """
    indice = _indice(f)
    encontradas = puntos = 0
    for palabra in palabras:
        raiz = _raiz(palabra)
        de_esta = 0
        if palabra in indice.nombre:
            de_esta += PESO_NOMBRE
        elif len(palabra) >= 3 and any(n.startswith(palabra) for n in indice.nombre):
            de_esta += PESO_PREFIJO
        for campo, peso in ((indice.buscar, PESO_BUSCAR), (indice.titulo, PESO_TITULO),
                            (indice.texto, PESO_TEXTO), (indice.etiquetas, PESO_ETIQUETA),
                            (indice.ayuda, PESO_AYUDA)):
            if raiz in campo:
                de_esta += peso
        if de_esta:
            encontradas += 1
            puntos += de_esta
    return encontradas, puntos


def _nombre_buscado(consulta: str, f: Ficha) -> int:
    """Devuelve cuánto se parece el nombre del flag a lo escrito, si es una sola palabra.

    Una pregunta con espacios no es un nombre y no puntúa aquí. El flag exacto va por
    delante del que empieza igual, y ese del que solo lo contiene.
    """
    nombre = flags_ayuda.normalizar(consulta)
    if not nombre or " " in nombre:
        return 0
    if f.nombre == nombre:
        return 3000
    if f.nombre.startswith(nombre):
        return 2000 - len(f.nombre)
    if nombre in f.nombre:
        return 1000 - f.nombre.index(nombre)
    return 0


def buscar(consulta: str = "", *, riesgo: str | None = None, modo: str | None = None,
           tema: str | None = None, solo_explicadas: bool = False) -> list[Ficha]:
    """Busca flags por su nombre, por lo que hacen o por la ayuda de rclone.

    La pregunta se lee como la escribiría una persona («qué hace con los borrados», «cómo
    ignoro ficheros temporales»): sin tildes ni mayúsculas, sin las palabras de relleno y
    comparando las raíces, de modo que `borrados` encuentra lo que dice `borrar`. Un nombre
    de flag (`--max_delete`, `Max-Delete`) sale primero el exacto, luego los que empiezan
    igual y luego los que lo contienen. Sin nada que buscar, salen todas.

    Los filtros se juntan con la búsqueda. Un valor que no existe no encuentra nada, y uno
    de riesgo o de tema deja fuera los flags sin explicación propia, que no los tienen.
    Nunca lanza.

    Args:
        consulta: Lo que se escribe en el cuadro de búsqueda.
        riesgo: Solo los de ese riesgo (`RIESGOS`).
        modo: Solo los que sirven en ese modo de una pareja (`model.MODES`).
        tema: Solo los de ese tema (`TEMAS`).
        solo_explicadas: Si se da, deja fuera los que solo tienen la ayuda de rclone.

    Returns:
        Las fichas, la más parecida primero y, a igualdad, en el orden de `fichas()`.
    """
    candidatas = [f for f in fichas()
                  if (riesgo is None or f.riesgo == riesgo)
                  and (modo is None or modo in f.modos)
                  and (tema is None or f.tema == tema)
                  and (not solo_explicadas or f.explicada)]
    palabras = [p for p in _PALABRA.findall(_plano(consulta)) if p not in _RELLENO]
    if not palabras:
        return candidatas
    puntuadas = []
    for posicion, f in enumerate(candidatas):
        encontradas, puntos = _puntos(f, palabras)
        parecido = _nombre_buscado(consulta, f)
        if encontradas or parecido:
            puntuadas.append(((-parecido, -encontradas, -puntos, posicion), f))
    return [f for _clave, f in sorted(puntuadas, key=lambda par: par[0])]


# ----------------------------------------------------------------------------
# Lo que se enseña de cada flag
# ----------------------------------------------------------------------------

def _marca(f: Ficha) -> str:
    """Devuelve cómo se marca el estado de un flag, con el motivo del modelo si lo hay."""
    if f.estado in (ESTADO_FIJO, ESTADO_NO_ADMITIDO):
        return f"{ETIQUETA_ESTADO[f.estado]} ({f.motivo})."
    return f"{ETIQUETA_ESTADO[f.estado]}."


def _modos_texto(modos: tuple[str, ...]) -> str:
    """Devuelve los modos para leerlos: «todos» si son los cinco."""
    return "todos" if set(modos) == set(model.MODES) else ", ".join(modos)


def _valor_texto(f: Ficha) -> str:
    """Devuelve lo que se dice de lo que pone prdrive para este flag."""
    if f.prdrive:
        return f.prdrive
    if f.estado == ESTADO_FIJO:
        return "Lo pone en cada pasada; no se escribe."
    if f.estado == ESTADO_NO_ADMITIDO:
        return "No lo pone: el config lo rechaza."
    por_defecto = f" (rclone usa {f.defecto})" if f.defecto else ""
    return f"Ninguno: prdrive no lo toca{por_defecto}."


def _ayuda_texto(f: Ficha) -> str:
    """Devuelve el tipo, el valor de fábrica y la ayuda corta de rclone, en una línea."""
    partes = [f.tipo] if f.tipo else []
    partes.append(f"valor de fábrica: {f.defecto}" if f.defecto else "sin valor de fábrica")
    if f.ayuda:
        partes.append(f.ayuda)
    return " · ".join(partes)


def sirve_en(f: Ficha, modo: str | None) -> bool:
    """Indica si el flag sirve en ese modo de pareja; sin modo (los comunes), sirve en todos."""
    return modo is None or modo in f.modos


def _tu_pareja(f: Ficha, modo: str | None) -> list[tuple[str, str]]:
    """Devuelve la fila que dice si el flag sirve en la pareja que se edita, si hay pareja."""
    if modo is None:
        return []
    return [(R_TU_PAREJA, f"Sí, sirve en tu pareja ({modo})." if sirve_en(f, modo)
             else f"No sirve en tu pareja ({modo}).")]


def detalle(f: Ficha, modo: str | None = None) -> list[tuple[str, str]]:
    """Devuelve lo que se enseña de un flag, como pares `(rótulo, texto)` en orden.

    Es lo único que lee la ventana y la página de `docs/guia` (con otro formato): un flag
    explicado trae para qué sirve, su efecto, el riesgo, los modos, lo que pone prdrive,
    un ejemplo y la ayuda de rclone; uno que no lo está lo dice y trae solo la ayuda de
    rclone, que viene en inglés. Ningún texto sale vacío.

    Args:
        f: El flag.
        modo: El modo de la pareja que se edita, para decir si el flag le sirve; `None`
            en los flags comunes de `[defaults]`, que no tienen pareja.
    """
    filas: list[tuple[str, str]] = []
    if not f.explicada:
        filas.append((R_ESTADO, SIN_EXPLICACION if f.estado == ESTADO_LIBRE
                      else f"{SIN_EXPLICACION} {_marca(f)}"))
        filas.append((R_MODOS, f"Según la orden de rclone de cada modo: "
                               f"{_modos_texto(f.modos)}."))
        filas += _tu_pareja(f, modo)
        filas.append((R_RCLONE, _ayuda_texto(f)))
        return filas
    if f.estado != ESTADO_LIBRE:
        filas.append((R_ESTADO, _marca(f)))
    filas += [(R_PARA_QUE, f.para_que), (R_EFECTO, f.efecto),
              (R_RIESGO, ETIQUETAS_RIESGO[f.riesgo or RIESGO_LEE]),
              (R_MODOS, _modos_texto(f.modos)), *_tu_pareja(f, modo),
              (R_PRDRIVE, _valor_texto(f)),
              (R_EJEMPLO if f.estado in (ESTADO_LIBRE, ESTADO_VALOR) else R_EN_SU_LUGAR,
               f.ejemplo), (R_RCLONE, _ayuda_texto(f))]
    return filas


_CLAVE = re.compile(r"\s*([A-Za-z][A-Za-z0-9_-]*)\s*=")


def flag_de_la_linea(texto: str, indice: int) -> str:
    """Devuelve el flag de la línea del cuadro donde está el cursor, o `""` si no hay.

    Es con lo que se abre la guía desde el editor de flags: en la línea de un flag, en ese
    flag. Sirve el cursor en cualquier punto de la línea; en una en blanco, un comentario o
    sin `=`, ninguno. Un índice fuera del texto se queda en su principio o su final.

    Args:
        texto: Lo que hay en el cuadro de flags.
        indice: Dónde está el cursor, en caracteres desde el principio.
    """
    if not texto:
        return ""
    indice = max(0, min(indice, len(texto)))
    inicio = texto.rfind("\n", 0, indice) + 1
    fin = texto.find("\n", indice)
    coincide = _CLAVE.match(texto[inicio:len(texto) if fin < 0 else fin])
    return flags_ayuda.normalizar(coincide.group(1)) if coincide else ""


# ----------------------------------------------------------------------------
# docs/guia/flags-de-rclone.md
# ----------------------------------------------------------------------------

def _celda(texto: str) -> str:
    """Devuelve el texto listo para una celda de tabla de Markdown (el `|` parte la fila)."""
    return str(texto).replace("|", "\\|").replace("\n", " ")


def _bloque(f: Ficha) -> list[str]:
    """Devuelve las líneas del apartado de un flag explicado en la página de la guía."""
    lineas = [f"### `--{f.nombre}`", "", f"**{f.titulo}**", ""]
    if f.estado != ESTADO_LIBRE:
        lineas += [f"> **{ETIQUETA_ESTADO[f.estado]}**" + (f" ({f.motivo})" if f.motivo else ""),
                   ""]
    escribible = f.estado in (ESTADO_LIBRE, ESTADO_VALOR)
    ejemplo = f"`{f.ejemplo}`" if escribible else f.ejemplo
    lineas += [f"- **{R_PARA_QUE}:** {f.para_que}", f"- **{R_EFECTO}:** {f.efecto}",
               f"- **{R_RIESGO}:** {ETIQUETAS_RIESGO[f.riesgo or RIESGO_LEE]}",
               f"- **{R_MODOS}:** {_modos_texto(f.modos)}",
               f"- **{R_PRDRIVE}:** {_valor_texto(f)}",
               f"- **{R_EJEMPLO if escribible else R_EN_SU_LUGAR}:** {ejemplo}", ""]
    return lineas


def a_markdown() -> str:
    """Devuelve la página `docs/guia/flags-de-rclone.md`, entera y siempre igual.

    La página es esta función y nada más: `generar_guia_flags.py` la escribe y
    `tests/test_flags_guia.py` falla si el fichero no es exactamente esto, así que lo que
    lee quien no abre el programa no puede divergir de lo que enseña la ventana.
    """
    version = flags_ayuda.datos().rclone or "la fijada"
    lineas = [
        "[← Guías](README.md)", "",
        "# Flags de rclone", "",
        "<!-- Esta página la genera `python generar_guia_flags.py` a partir del catálogo de "
        "la guía (`ui/flags_catalogo.py`). No la edites a mano: `tests/test_flags_guia.py` "
        "falla si no coincide. -->", "",
        "Qué hace cada flag de rclone que puedes poner en una pareja, explicado para quien usa "
        "el dispositivo. Es la misma guía que trae el programa, con búsqueda por texto y por "
        "efecto («qué hace con los borrados», «cómo ignoro ficheros temporales»): **Parejas → "
        "Modificar… → Avanzado → Editar flags… → «Guía de flags…»**.", "",
        "Un flag se escribe en el TOML de la pareja, sin los guiones de delante (`transfers = "
        "8`); cómo se funden las capas y qué no admite el config está en "
        "[Configuración](configuracion.md). Esta guía ayuda y no restringe: un flag que no "
        "aparece aquí se puede escribir igual, y rclone tiene la última palabra.", "",
        "## Cómo leer cada ficha", "",
        "**Riesgo**, de menos a más:", ""]
    lineas += [f"- **{ETIQUETAS_RIESGO[r]}:** {DESCRIPCION_RIESGO[r]}" for r in RIESGOS]
    lineas += ["", "**Quién lo pone:**", ""]
    lineas += [f"- **{ETIQUETA_ESTADO[e]}.**" + {
        ESTADO_LIBRE: " Lo que escribas va tal cual a rclone.",
        ESTADO_VALOR: " Lo pone prdrive con un valor de partida; puedes poner otro en la "
                      "pareja.",
        ESTADO_FIJO: " Lo pone el script en cada pasada; escribirlo en una pareja se rechaza.",
        ESTADO_NO_ADMITIDO: " Lanzaría un programa o escribiría un fichero de tu equipo, y el "
                            "config viaja con el dispositivo: se rechaza.",
    }[e] for e in ESTADOS]
    lineas += ["", "**Modos donde sirve** son los de la pareja: `bisync`, `up`, `down`, "
               "`up-mirror` y `down-mirror`. Un flag que rclone acepta en una orden pero no hace "
               "nada ahí, o que solo vale en otra, no los incluye.", ""]
    todas = fichas()
    for tema in TEMAS:
        if tema == TEMA_OTROS:
            continue
        del_tema = [f for f in todas if f.tema == tema and f.explicada]
        if not del_tema:
            continue
        lineas += [f"## {ETIQUETAS_TEMA[tema]}", "", DESCRIPCION_TEMA[tema], ""]
        for f in del_tema:
            lineas += _bloque(f)
    resto = [f for f in todas if not f.explicada]
    lineas += [f"## {ETIQUETAS_TEMA[TEMA_OTROS]}", "",
               f"Son los flags de rclone {version}, la que lleva prdrive, que esta guía todavía "
               f"no explica. Salen con la ayuda corta de rclone, que está **en inglés**, para "
               f"saber que existen y de qué tipo son. Escribirlos vale igual que cualquier otro; "
               f"si el tipo del valor no es el que rclone espera, el editor lo dice al guardar.",
               "",
               "| Flag | Tipo | Valor de fábrica | Ayuda de rclone (en inglés) | Modos |",
               "|---|---|---|---|---|"]
    for f in resto:
        conocido = flags_ayuda.conocido(f.nombre)
        tipo = flags_ayuda.etiqueta_tipo(conocido) if conocido else f.tipo
        lineas.append(f"| `--{f.nombre}` | {_celda(tipo)} | {_celda(f.defecto or '—')} | "
                      f"{_celda(f.ayuda)} | {_modos_texto(f.modos)} |")
    return "\n".join(lineas) + "\n"
