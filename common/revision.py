#!/usr/bin/env python3
"""
revision.py — Qué está mal en este dispositivo, como datos.

Esto era texto dentro de `sync.py --doctor`: una lista de averías impresa, que
acababa mandando al usuario a arreglarlo a mano («apártalo y haz --resync»,
«bórralos si no hay ninguna ejecución en curso»). Para que la interfaz pueda
poner un botón al lado de cada avería hace falta que la avería sea un dato, no
una línea.

Vive en `common/` y no en `ui/` por una razón concreta: **`sync.py` no importa
`ui/`**. Si el diagnóstico viviera del lado de la ventana habría dos: el que
enseña la pantalla y el que imprime el subcomando, y se separarían a la primera.
Aquí solo hay uno; `--doctor` imprime `informe()` y la pantalla dibuja
`revisar()`.

Este módulo **no toca nada y no decide nada**: mira el estado y cuenta lo que
ve. Qué se puede hacer con cada avería —y cómo— es de `ui/repair.py`, que es
quien sabe pedir confirmación antes de mover un baseline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import bisync, conflicts, historial, model, results, store, vestibulo
from .model import Config, Pair

# Cuánto pesa una avería. No son tres colores: son tres respuestas distintas a
# «¿puedo seguir usando esto?».
GRAVE = "grave"     # no se puede sincronizar, o hacerlo arriesga datos
AVISO = "aviso"     # hay algo que hacer, pero nada está en peligro
NOTA = "nota"       # informativo; normalmente se arregla solo


@dataclass(frozen=True)
class Hallazgo:
    """Una avería concreta.

    `clave` es lo que mira quien repara para saber de qué habla; el texto es
    para quien lo lee. `dato` lleva lo que la reparación necesita y el diagnóstico
    ya ha averiguado —las rutas de los locks, por ejemplo—, para no recorrer el
    disco dos veces."""
    clave: str                  # 'local' | 'prefijo' | 'resync' | 'lock' | 'espacio' | …
    titulo: str
    detalle: str
    pareja: str | None = None   # None: es del dispositivo, no de una pareja
    gravedad: str = AVISO
    dato: tuple = field(default_factory=tuple)


def _local(pair: Pair, estado: bisync.PairState) -> Hallazgo | None:
    """La carpeta local que no está.

    Es la única avería de la lista que NO se repara desde aquí, y a propósito:
    crearla es exactamente lo que `sync._bisync_preflight()` se niega a hacer
    cuando hay baseline, porque un lado local vacío se lee como «se ha borrado
    todo» y eso se propaga al remoto. Lo que hay que arreglar está fuera del
    programa —el volumen no está montado donde se cree, o la carpeta se movió—,
    así que aquí solo se dice."""
    if pair.local_abs.exists():
        return None
    if pair.is_bisync and estado.has_baseline:
        return Hallazgo(
            "local", f"«{pair.name}»: la carpeta local no está",
            f"{pair.local_endpoint} no existe, y esta pareja ya tiene baseline. "
            "La sincronización se parará en vez de crearla: un lado vacío se lee "
            "como «se ha borrado todo». Comprueba que el volumen esté montado "
            "donde toca y que la carpeta no se haya movido; no lo arregles "
            "creándola vacía.",
            pair.name, GRAVE)
    return Hallazgo(
        "local", f"«{pair.name}»: la carpeta local aún no está",
        f"{pair.local_endpoint} no existe. Como esta pareja no tiene baseline "
        "que proteger, la próxima pasada la crea.",
        pair.name, NOTA)


def _prefijo(pair: Pair, estado: bisync.PairState) -> Hallazgo | None:
    """Un baseline guardado con el prefijo de OTRO destino."""
    esperado = bisync.expected_prefix(pair)
    if not estado.prefix or estado.prefix == esperado:
        return None
    return Hallazgo(
        "prefijo", f"«{pair.name}»: el baseline no es de esta pareja",
        f"Está guardado como «{estado.prefix}» y esta pareja espera "
        f"«{esperado}», así que rclone no lo va a encontrar. Pasa cuando cambia "
        "un extremo (la carpeta local, el remoto o su ruta). Se aparta y se "
        "rehace con un --resync.",
        pair.name, GRAVE, (estado.prefix, esperado))


def _resync(pair: Pair, estado: bisync.PairState) -> Hallazgo | None:
    """La pareja pide un --resync y nadie lo ha hecho."""
    razones = bisync.resync_reasons(pair, estado)
    if not razones:
        return None
    return Hallazgo(
        "resync", f"«{pair.name}» necesita un --resync",
        "; ".join(razones) + ". Hasta que se haga, esta pareja se salta en cada "
        "pasada: el servicio no resincroniza solo, nunca.",
        pair.name, AVISO)


def _locks(pair: Pair) -> Hallazgo | None:
    """Locks de bisync que han quedado sueltos."""
    try:
        sueltos = sorted(pair.workdir.glob("*.lck"))
    except OSError:
        return None
    if not sueltos:
        return None
    return Hallazgo(
        "lock", f"«{pair.name}»: hay {len(sueltos)} bloqueo(s) sin dueño",
        "Los deja una pasada que se cortó a medias, y mientras estén ahí bisync "
        "se niega a empezar. Solo se pueden borrar si no hay ninguna "
        "sincronización en curso.",
        pair.name, AVISO, tuple(sueltos))


def _conflictos(config: Config) -> list[Hallazgo]:
    """Ficheros que cambiaron en los dos lados. Se lee lo apuntado, no se
    recorre el disco: esto lo llama la ventana al pintarse."""
    try:
        cuentas = conflicts.contar(conflicts.cargar(config))
    except Exception:                                   # noqa: BLE001
        return []
    return [Hallazgo(
        "conflicto",
        f"«{nombre}»: {n} fichero(s) en conflicto" if n > 1
        else f"«{nombre}»: 1 fichero en conflicto",
        "Cambiaron en los dos lados entre dos pasadas, así que hay dos versiones "
        "y se van separando. Hay que elegir con cuál te quedas.",
        nombre, AVISO, (n,)) for nombre, n in cuentas.items() if n]


def _dia(sello: str) -> str:
    """«12/09», o «12/09/2025» si no es de este año."""
    cuando = datetime.strptime(sello, store.FORMATO)
    return f"{cuando:%d/%m}" if cuando.year == datetime.now().year else f"{cuando:%d/%m/%Y}"


def _frase_racha(racha: historial.Racha) -> str:
    """Desde cuándo falla y cuántas de sus últimas pasadas fueron bien, en una
    frase: «Falla desde el 12/09 · 0 de las últimas 14 bien.»

    «Al menos» cuando el diario no ve dónde empezó la racha —todas las que
    constan fallaron—: puede que lleve fallando desde antes de que el diario
    existiera, y una fecha que parece exacta y no lo es haría buscar la causa
    en el día equivocado."""
    desde = ("Falla desde el " if racha.exacta else "Falla al menos desde el ")
    cuenta = ("es la única pasada que consta" if racha.pasadas == 1
              else f"{racha.buenas} de las últimas {racha.pasadas} bien")
    return f"{desde}{_dia(racha.desde)} · {cuenta}."


def _fallos(config: Config) -> list[Hallazgo]:
    """La última pasada de esa pareja falló. No tiene reparación: es un informe,
    y lo que se ofrece es el log que lo explica.

    Del diario de pasadas sale desde cuándo falla, que es lo que distingue un
    tropiezo de una avería. Sin diario (un dispositivo recién actualizado, o
    uno que no se deja leer) la avería se cuenta igual, sin esa frase."""
    try:
        fallos = results.fallos(config)
    except Exception:                                   # noqa: BLE001
        return []
    try:
        rachas = historial.rachas(f.pareja for f in fallos)
    except Exception:                                   # noqa: BLE001
        rachas = {}
    hallazgos = []
    for f in fallos:
        racha = rachas.get(f.pareja)
        hallazgos.append(Hallazgo(
            "fallo", f"«{f.pareja}»: la última pasada falló",
            f"Acabó con código {f.codigo}" + (f" el {f.cuando}" if f.cuando else "") +
            (". El log lo explica." if f.log else ". No queda log de aquella pasada.") +
            (f" {_frase_racha(racha)}" if racha is not None else "") +
            " Mientras no se arregle, eso no está sincronizado.",
            f.pareja, AVISO, (f.log,)))
    return hallazgos


def _listados_sueltos() -> Hallazgo | None:
    """Listados en la raíz de state/, del layout de una sola carpeta."""
    try:
        sueltos = sorted(model.STATE_DIR.glob("*.lst")) if model.STATE_DIR.exists() else []
    except OSError:
        return None
    if not sueltos:
        return None
    return Hallazgo(
        "listados", f"{len(sueltos)} listado(s) sueltos en state/",
        "Son del reparto antiguo, cuando todas las parejas compartían carpeta. "
        "Se reparten solos en la próxima pasada de cada pareja.",
        None, NOTA, tuple(sueltos))


def _espacio() -> Hallazgo | None:
    """Un contenedor VeraCrypt dinámico al que se le acaba el sitio de fuera.

    Uno dinámico (disperso) crece a medida que se escribe dentro, así que su
    sitio libre de verdad es el de la unidad física. Cuando se acaba, el volumen
    de dentro da errores de E/S en mitad de lo que esté escribiendo —un bisync,
    por ejemplo—, y rclone no puede explicar por qué: desde dentro, el disco no
    está lleno. No tiene botón: la salida es liberar sitio fuera del contenedor.

    `fleet` se importa aquí dentro: es el que sabe leer el id del fichero de
    control, y arrastra el catálogo, que el resto de este módulo no necesita."""
    try:
        from . import fleet
        falta = vestibulo.sin_sitio_fuera(fleet.device_id())
    except Exception:                                # noqa: BLE001
        return None
    if falta is None:
        return None
    fisica, libre = falta
    return Hallazgo(
        "espacio", "El contenedor se queda sin sitio fuera",
        f"{vestibulo.CONTENEDOR} es dinámico: crece a medida que se escribe "
        f"dentro, y en {fisica} quedan {libre / 1024 ** 2:.0f} MB libres. Si se "
        "llena, lo de dentro empieza a dar errores de escritura en mitad de una "
        "sincronización. Libera sitio en la unidad, fuera del contenedor.",
        None, AVISO, (str(fisica), libre))


def revisar(config: Config) -> list[Hallazgo]:
    """Todo lo que está mal ahora mismo, lo más grave primero.

    No habla con el remoto ni lanza rclone: lee el dispositivo. Es lo que
    permite llamarlo mientras se pinta una ventana.

    Lo único que puede escribir es `filters/<pareja>.txt`, y no es cosa suya:
    lo regenera `bisync.resync_reasons()` cuando el contenido ha cambiado, que
    es justo lo que hace falta saber para decir si la pareja pide un resync. La
    ventana principal ya lo hacía al pintarse, por el mismo camino."""
    hallazgos: list[Hallazgo] = []
    for pair in config.pairs:
        estado = (bisync.pair_state(pair) if pair.is_bisync
                  else bisync.PairState("fresh", "no es bisync", None))
        for hallazgo in (_local(pair, estado), _prefijo(pair, estado),
                         _resync(pair, estado), _locks(pair)):
            if hallazgo is not None:
                hallazgos.append(hallazgo)
    hallazgos += _conflictos(config)
    hallazgos += _fallos(config)
    for hallazgo in (_listados_sueltos(), _espacio()):
        if hallazgo is not None:
            hallazgos.append(hallazgo)

    orden = {GRAVE: 0, AVISO: 1, NOTA: 2}
    return sorted(hallazgos, key=lambda h: orden.get(h.gravedad, 9))


def cuenta(hallazgos: list[Hallazgo]) -> int:
    """Cuántas cosas hay que mirar. Las notas no cuentan: se arreglan solas, y
    un aviso que no pide nada de nadie es ruido en la ventana principal."""
    return sum(1 for h in hallazgos if h.gravedad in (GRAVE, AVISO))


# ---------------------------------------------------------------------------
# El mismo diagnóstico, en texto: lo que imprime `sync.py --doctor`
# ---------------------------------------------------------------------------

def _informe_pareja(pair: Pair) -> list[str]:
    lineas = [f"[{pair.name}] {pair.mode.name}",
              f"  local : {pair.local_endpoint} "
              f"{'(OK)' if pair.local_abs.exists() else '(NO EXISTE)'}",
              f"  remoto: {pair.remote_endpoint}"]
    if not pair.is_bisync:
        return lineas + [""]

    estado = bisync.pair_state(pair)
    lineas += [f"  estado: {estado.status} — {estado.detail}",
               f"  prefijo esperado: {bisync.expected_prefix(pair)}"]
    filtros = bisync.filters_state(bisync.filters_file_for(pair))
    lineas.append(f"  filtros: {filtros.status} — {filtros.detail}")

    if pair.workdir.exists():
        for f in sorted(pair.workdir.iterdir()):
            if f.is_file():
                cuando = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
                lineas.append(f"    {f.name:<62} {cuando}")
    return lineas + [""]


def informe(config: Config) -> list[str]:
    """El informe completo, línea a línea, para quien no tiene pantalla.

    Lleva más que `revisar()` —las rutas resueltas, el entorno del combine, los
    ficheros del workdir con su fecha— porque eso es lo que se pega en un
    mensaje cuando algo no cuadra. Las averías son las mismas: salen de
    `revisar()`, así que el subcomando y la pantalla no pueden discrepar."""
    lineas = [f"Dispositivo detectado en: {model.DEVICE_ROOT}",
              f"Workdir de estado: {model.STATE_DIR}"]
    lineas += [f"  {clave}={valor}" for clave, valor in config.pen_environment().items()]
    lineas.append("")
    for pair in config.pairs:
        lineas += _informe_pareja(pair)

    hallazgos = revisar(config)
    if not hallazgos:
        lineas.append("Sin incidencias.")
        return lineas
    lineas.append(f"{len(hallazgos)} cosa(s) que revisar:")
    for h in hallazgos:
        lineas.append(f"  {h.gravedad.upper():<6} {h.titulo}")
        lineas.append(f"         {h.detalle}")
    return lineas
