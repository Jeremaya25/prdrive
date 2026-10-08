#!/usr/bin/env python3
"""Todo lo que replica el comportamiento interno de `rclone bisync`.

Aquí vive la parte incómoda del proyecto, y junta a propósito: bisync guarda su
baseline en ficheros cuyo nombre deduce de los dos extremos y no perdona que
ese nombre cambie. Saber calcular ANTES de ejecutar el nombre que rclone va a
buscar permite decidir si el baseline que hay en disco sirve para esta pareja o
hay que apartarlo y rehacerlo (`ui/pair_editor.py`).

Los listados NO se renombran jamás: renombrar es decirle a bisync que el
listado del destino ANTERIOR describe el NUEVO, y no hay forma de distinguir el
caso benigno del maligno. El nombre no depende de la máquina porque el lado
local va como `device_remote` (un remote `combine` propio).

Cada apartado cita el fichero de rclone cuyo comportamiento imita: es contra
esas fuentes contra lo que hay que contrastar cualquier cambio.
"""

from __future__ import annotations

import hashlib
import ntpath
import os
import posixpath
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

from . import model
from .model import Pair

PATH1_SUFFIX = ".path1.lst"
PATH2_SUFFIX = ".path2.lst"
ERR_SUFFIX = ".lst-err"

MISSING_LISTINGS = "cannot find prior Path1 or Path2 listings"
"""Mensaje con el que rclone se queja de que no encuentra el baseline."""


_NON_CANONICAL = re.compile(r"[\s\\/:?*]")


def canonical_path(remote: str) -> str:
    r"""Réplica de `CanonicalPath` (cmd/bisync/bilib/canonical.go, rclone master).

    Quita `/` y `\` de los extremos y sustituye `[\s\\/:?*]` por `_`.
    """
    return _NON_CANONICAL.sub("_", remote.strip("\\/"))


def strip_hex_string(path: str) -> str:
    """Quita el sufijo `{hexstring}` que rclone añade a la ruta.

    rclone lo añade cuando la config del remote viene de flags, entorno o
    connection string.
    """
    opening, closing = path.find("{"), path.find("}")
    if opening >= 0 and closing > opening:
        return path[:opening] + path[closing + 1:]
    return path


def fs_path_local(p: str) -> str:
    r"""Réplica de `FsPath` de canonical.go para el backend local: `F:\ruta\`.

    Termina siempre en el separador del sistema; en Windows quita el prefijo
    `\\?\`.
    """
    sep = os.sep
    if os.name == "nt":
        p = p.replace("/", sep)
        if p.startswith("\\\\?\\"):
            p = p[4:]
    return p if p.endswith(sep) else p + sep


def fs_path_remote(s: str) -> str:
    """Réplica de `FsPath` de canonical.go para un remote con nombre: `remote:ruta/`.

    `FsPath` pone `nombre + ":" + f.Root()`, y casi siempre `Root()` es la ruta
    tal cual. Un remote de tipo `local` (`tipos_de_remote()`) es la excepción:
    su `Root()` es la ruta limpia (`raiz_local()`).
    """
    nombre, dos_puntos, ruta = s.partition(":")
    if dos_puntos:
        tipo, nounc = tipos_de_remote().get(nombre, (None, False))
        if tipo == "local":
            s = f"{nombre}:{raiz_local(ruta, nounc)}"
    return s if s.endswith("/") else s + "/"


IS_WIN = os.name == "nt"
"""Si `raiz_local()` hace lo de Windows; de módulo para que los tests prueben las dos."""
_UNIDAD = re.compile(r"^[a-zA-Z]:\\")


def tipos_de_remote() -> dict[str, tuple[str | None, bool]]:
    """Devuelve `{remote: (tipo, nounc)}` del `rclone.conf` del dispositivo.

    Lo lee `pairing.parse_rclone_conf()`, el único lector del proyecto. Sin
    fichero, o sin leerse, vacío: el nombre se calcula como el de cualquier
    remote.
    """
    from .pairing import parse_rclone_conf
    try:
        texto = model.RCLONE_CONF.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    return {nombre: (opciones.get("type"), opciones.get("nounc", "").lower() == "true")
            for nombre, opciones in parse_rclone_conf(texto).items()}


def raiz_local(ruta: str, nounc: bool = False) -> str:
    r"""Réplica del `Root()` del backend local de rclone (backend/local/local.go).

    Es `cleanRootPath()` con `/`, contrastado con rclone v1.75.1: en Linux la
    ruta limpia (`filepath.Clean`: `a//b` y `a/./b` son `a/b`), y un segmento
    `.` o `..` sale como `．`/`．．` por el codificador de nombres
    (`ToStandardPath`). En Windows, absoluta (`filepath.Abs`, y rclone corre
    con cwd en `model.APP_DIR`) y con `\\?\` delante (`file.UNCPath()`,
    lib/file/unc_windows.go) salvo con `nounc = true`: `D:\datos` es
    `//?/D:/datos`, y `\\nas\datos`, `//?/UNC/nas/datos`.
    """
    if IS_WIN:
        limpia = ntpath.normpath(ntpath.join(str(model.APP_DIR), ruta.replace("/", "\\")))
        if not nounc and not limpia.startswith("\\\\?\\"):
            if limpia.startswith("\\\\"):
                limpia = "\\\\?\\UNC\\" + limpia[2:]
            elif _UNIDAD.match(limpia):
                limpia = "\\\\?\\" + limpia
        return limpia.replace("\\", "/")
    limpia = posixpath.normpath(ruta or ".")
    if limpia.startswith("//"):
        limpia = limpia[1:]          # `filepath.Clean` no guarda las dos barras de POSIX
    return "/".join("\uff0e" * len(trozo) if trozo in (".", "..") else trozo
                    for trozo in limpia.split("/"))


def session_name(path1: str, path2: str) -> str:
    """Réplica de `SessionName` de canonical.go.

    Es `CanonicalPath(path1) + ".." + CanonicalPath(path2)`, sin el sufijo
    `{hexstring}`.
    """
    return strip_hex_string(canonical_path(path1)) + ".." + strip_hex_string(canonical_path(path2))


def expected_prefix(pair: Pair) -> str:
    """Devuelve el nombre base de los `.path1.lst` y `.path2.lst` que rclone buscará."""
    def render(kind: str) -> str:
        """Devuelve el extremo tal como lo escribe rclone al nombrar la sesión."""
        endpoint = pair.endpoint(kind)
        if kind == "local" and not pair.device_remote:
            return fs_path_local(endpoint)
        return fs_path_remote(endpoint)

    return session_name(render(pair.mode.source), render(pair.mode.dest))


FILTERS_HEADER = (
    "# Generado por sync.py desde sync_config.toml. No editar a mano:\n"
    "# se regenera en cada ejecución. Cambiar los patrones exige --resync."
)
"""Cabecera del fichero de filtros generado."""


class FiltersState(NamedTuple):
    """Si el fichero de filtros coincide con el que se usó en el último resync.

    Args:
        status: `ok`, `new` (sin hash previo) o `changed`.
        detail: Frase que lo explica.
    """
    status: str
    detail: str

    @property
    def needs_resync(self) -> bool:
        """Indica si hace falta un `--resync` por culpa de los filtros."""
        return self.status != "ok"


def filters_content(pair: Pair) -> str:
    """Devuelve el contenido del fichero de filtros de la pareja.

    Las reglas van en orden de prioridad: gana la primera que casa.
    """
    lines = [FILTERS_HEADER]
    if pair.versions:
        # No es filtrado: es la condición de rclone para que `.prversions/`
        # viva dentro del pair. Sin ella `--backup-dir1` solapa con Path1 y la
        # pasada muere con «destination and parameter to --backup-dir mustn't
        # overlap», error crítico que invalida el baseline. Va PRIMERA: rclone
        # aplica las reglas en orden y detrás de un `+ **/*.md` no excluiría
        # nada.
        lines.append(f"- {model.VERSIONS_DIR}/**")
    # Las del código van antes que las del TOML: las del llavero son toda su
    # lista, y `REGLA_SIN_LLAVERO` tiene que ganar a cualquier `+` de la pareja.
    lines += list(pair.reglas)
    lines += [f"+ {p}" for p in pair.includes]
    lines += [f"- {p}" for p in pair.excludes]
    if pair.includes:
        # Como `--include`: si hay reglas `+`, todo lo demás queda fuera.
        lines.append("- **")
    return "\n".join(lines) + "\n"


def filters_file_for(pair: Pair) -> Path | None:
    """Genera `filters/<pareja>.txt` si hace falta y devuelve su ruta.

    El contenido es determinista: si no cambia no se reescribe el fichero, para
    no gastar ciclos del dispositivo ni invalidar el md5 sin motivo.

    Returns:
        La ruta, o `None` si la pareja no usa fichero de filtros.
    """
    if not pair.wants_filters_file:
        return None

    content = filters_content(pair)
    model.FILTERS_DIR.mkdir(parents=True, exist_ok=True)
    path = model.FILTERS_DIR / f"{pair.name}.txt"
    if not path.exists() or path.read_text(encoding="utf-8") != content:
        path.write_text(content, encoding="utf-8", newline="\n")
    return path


def filters_state(ffile: Path | None) -> FiltersState:
    """Compara el fichero de filtros con el `.md5` que dejó el último resync.

    bisync guarda el md5 junto al propio fichero (`filtersFile + ".md5"`,
    cmd/bisync/cmd.go: `applyFilters`) y solo lo escribe durante un `--resync`;
    si el fichero cambia sin resync aborta con error crítico. Aquí se compara
    ANTES de ejecutar y se trata como «hace falta resync», que es una
    conversación y no un log rojo.

    Args:
        ffile: El fichero de filtros, o `None` si la pareja no tiene.
    """
    if ffile is None:
        return FiltersState("ok", "sin fichero de filtros")
    digest = hashlib.md5(ffile.read_bytes()).hexdigest()
    hash_file = Path(str(ffile) + ".md5")
    if not hash_file.exists():
        return FiltersState("new", f"{ffile.name} sin hash previo")
    if hash_file.read_text(encoding="utf-8").strip() != digest:
        return FiltersState("changed", f"{ffile.name} ha cambiado desde el último resync")
    return FiltersState("ok", f"{ffile.name} sin cambios")


class PairState(NamedTuple):
    """El estado real del baseline de una pareja.

    Args:
        status: `fresh` (sin listados), `ok` o `broken`.
        detail: Frase que lo explica.
        prefix: Prefijo de los listados; solo con `status == "ok"`.
    """
    status: str
    detail: str
    prefix: str | None

    @property
    def has_baseline(self) -> bool:
        """Indica si hay un baseline utilizable."""
        return self.status == "ok"


def _prefixes(paths: list[Path], suffix: str) -> set[str]:
    """Devuelve los prefijos de los listados, sin el sufijo `suffix`."""
    return {p.name[: -len(suffix)] for p in paths}


def pair_state(pair: Pair) -> PairState:
    """Devuelve el estado real del baseline, mirando los `.lst` del workdir."""
    workdir = pair.workdir
    if not workdir.exists():
        return PairState("fresh", "sin workdir (nunca sincronizada)", None)

    # Los `.lst-err` no los limpia nadie (rclone solo renombra `.lst` a
    # `.lst-err` al abortar; cmd/bisync/operations.go): si después hay un juego
    # de listados válido, el baseline es bueno y esos son residuo.
    #
    # Contra rclone v1.75.1: ante un error crítico `Bisync()` renombra los dos
    # listados a `.lst-err` («the prior listings are renamed to .lst-err to lock
    # out further runs»), y una interrupción que no se cierra bien hace lo mismo
    # con `markFailed()` (cmd/bisync/lockfile.go), que antes borra el `-err` que
    # hubiera. Con `--recover` la pasada siguiente vuelve a los `.lst-old` y
    # rehace los `.lst` (operations.go, «Reverting to prior backup»), y los
    # `-err` se quedan como estaban: ahí no se vuelven a leer, solo se
    # renombran. Se explican, nunca se borran: lo que hay en el workdir de
    # bisync no es cosa nuestra.
    path1 = sorted(workdir.glob("*" + PATH1_SUFFIX))
    path2 = sorted(workdir.glob("*" + PATH2_SUFFIX))
    errors = sorted(workdir.glob("*" + ERR_SUFFIX))
    residuo = (f" (+{len(errors)} {ERR_SUFFIX}: el baseline que rclone apartó al "
               f"abortar una pasada; ya no lo usa y se puede borrar a mano)"
               if errors else "")

    if path1 and path2:
        pre1 = _prefixes(path1, PATH1_SUFFIX)
        pre2 = _prefixes(path2, PATH2_SUFFIX)
        common = pre1 & pre2
        if len(common) != 1 or len(pre1) != 1 or len(pre2) != 1:
            return PairState("broken", f"varios juegos de listados: {sorted(pre1 | pre2)}", None)
        prefix = common.pop()
        return PairState("ok", f"baseline '{prefix}'{residuo}", prefix)

    if errors:
        return PairState(
            "broken",
            f"{len(errors)} listado(s) {ERR_SUFFIX}: rclone aparta así el baseline "
            f"cuando una pasada aborta con un error crítico, para bloquear las "
            f"siguientes",
            None)
    if path1 or path2:
        return PairState("broken", "falta uno de los dos listados (.path1/.path2)", None)
    return PairState("fresh", "sin listados previos", None)


def last_run(pair: Pair) -> float | None:
    """Devuelve cuándo fue la última pasada buena.

    No hay registro de pasadas ni hace falta inventarlo: bisync reescribe sus
    dos listados justo al terminar bien (cmd/bisync/operations.go), así que la
    fecha del más nuevo ES la de la última sincronización correcta. Fuera de
    bisync no queda rastro (un `copy` no deja estado) y esas parejas se quedan
    sin hora antes que enseñar una inventada.

    Returns:
        La marca de tiempo, o `None` si no se puede saber.
    """
    if not pair.is_bisync:
        return None
    try:
        marcas = [p.stat().st_mtime
                  for sufijo in (PATH1_SUFFIX, PATH2_SUFFIX)
                  for p in pair.workdir.glob("*" + sufijo)]
    except OSError:
        return None  # el dispositivo ya no está
    return max(marcas) if marcas else None


def programa_en_listado(pair: Pair) -> bool:
    """Indica si el último listado del remoto trae la carpeta del programa.

    Lo mira en el `path2.lst` del baseline, que describe el lado remoto tal
    como quedó en la última pasada buena. Es la señal de que una pareja de la
    raíz entera subió `.prdrive/` (con su clave y su `rclone.conf`) antes de
    que `model.REGLA_SIN_PROGRAMA` la dejara fuera: la regla no la borra del
    remoto, y tras el `--resync` el listado nuevo ya no la enseña. Solo tiene
    sentido para una pareja de la raíz entera (`Pair.es_raiz`): en otra, una
    carpeta con ese nombre sería del usuario.

    Es información de cortesía y no decide nada, así que un listado que falta
    o que no se puede leer cuenta como que no.

    Returns:
        `True` si alguna ruta del listado cuelga de la carpeta del programa.
    """
    lst = pair.workdir / (expected_prefix(pair) + PATH2_SUFFIX)
    # Cada línea es `flags tamaño hash id fecha "ruta"` (cmd/bisync/listing.go):
    # la ruta empieza en la primera comilla, y la cabecera `# …` no lleva ruta.
    carpeta = model.APP_DIR.name + "/"
    try:
        with lst.open(encoding="utf-8", errors="replace") as f:
            for linea in f:
                _, comilla, ruta = linea.partition('"')
                if comilla and not linea.startswith("#") and ruta.startswith(carpeta):
                    return True
    except OSError:
        pass
    return False


def resync_reasons(pair: Pair, state: PairState | None = None) -> list[str]:
    """Devuelve por qué esta pareja necesita `--resync`.

    Args:
        state: El estado ya calculado, para no recorrer otra vez el workdir.

    Returns:
        Los motivos; lista vacía si no lo necesita (también fuera de bisync).
    """
    if not pair.is_bisync:
        return []
    if state is None:
        state = pair_state(pair)
    reasons = []
    if not state.has_baseline:
        reasons.append(f"estado {state.status}: {state.detail}")
    filters = filters_state(filters_file_for(pair))
    if filters.needs_resync:
        reasons.append(f"filtros {filters.status}: {filters.detail}")
    return reasons


def migrate_legacy_state(pair: Pair) -> None:
    """Mueve los listados del layout antiguo al workdir de la pareja.

    El layout antiguo los tenía sueltos en `state/`. La pareja se identifica
    por el token del remoto en el nombre; si no es inequívoca no se toca nada.
    """
    workdir = pair.workdir
    if workdir.exists() and any(workdir.glob("*.lst")):
        return
    token = canonical_path(pair.remote_endpoint)
    candidates = {
        f.name[: -len(PATH1_SUFFIX)]
        for f in model.STATE_DIR.glob("*" + PATH1_SUFFIX)
        if token in f.name
    }
    if len(candidates) != 1:
        return
    prefix = candidates.pop()
    workdir.mkdir(parents=True, exist_ok=True)
    moved = 0
    for f in model.STATE_DIR.iterdir():
        if f.is_file() and f.name.startswith(prefix):
            shutil.move(str(f), str(workdir / f.name))
            moved += 1
    if moved:
        print(f"  migrados {moved} fichero(s) de estado a {workdir}")


def pair_state_paths(name: str) -> list[Path]:
    """Devuelve lo que hay en disco atado a esa pareja.

    Son su workdir y su fichero de filtros. Sirve para avisar de qué queda
    huérfano al quitar una pareja y para limpiarlo si se pide.
    """
    encontrados = [model.STATE_DIR / name]
    encontrados += [model.FILTERS_DIR / f"{name}.txt",
                    model.FILTERS_DIR / f"{name}.txt.md5"]
    return [p for p in encontrados if p.exists()]


def shelve_baseline(name: str) -> Path | None:
    """Aparta el baseline de una pareja: `state/<n>/` pasa a `state/<n>.old-<fecha>/`.

    Es lo que hay que hacer cuando cambia un EXTREMO de la pareja (`local`,
    `remote`, `remote_path` o `mode`): reaprovechar los listados con el prefijo
    nuevo diría a bisync que el listado del destino VIEJO describe el NUEVO, y
    todo lo que falte en el nuevo se leería como borrado y se propagaría.
    Apartándolo, la pareja queda `fresh` y exige un `--resync` explícito.

    Se renombra en vez de borrar por si hay que volver atrás; el directorio
    apartado queda inerte porque lo que recorre `state/` solo mira su primer
    nivel.

    Returns:
        Dónde ha quedado, o `None` si no había baseline que apartar.
    """
    workdir = model.STATE_DIR / name
    if not workdir.is_dir():
        return None
    sello = f"{datetime.now():%Y%m%d_%H%M%S}"
    destino = model.STATE_DIR / f"{name}.old-{sello}"
    n = 1
    while destino.exists():
        destino = model.STATE_DIR / f"{name}.old-{sello}_{n}"
        n += 1
    workdir.rename(destino)
    return destino


def rename_pair_state(old: str, new: str) -> list[tuple[Path, Path]]:
    """Mueve el estado de una pareja cuando solo cambia su nombre.

    El prefijo de los listados NO depende del nombre (sale de los extremos:
    `expected_prefix`), así que renombrar no invalida el baseline. Lo que
    cuelga del nombre son `state/<nombre>/` y `filters/<nombre>.txt` con su
    `.md5`, que se mueven juntos para que el hash que guarda bisync siga
    cuadrando.

    Returns:
        Los movimientos como `(origen, destino)`, para poder deshacerlos.
    """
    movimientos: list[tuple[Path, Path]] = []
    origen, destino = model.STATE_DIR / old, model.STATE_DIR / new
    if origen.is_dir() and not destino.exists():
        origen.rename(destino)
        movimientos.append((origen, destino))
    for sufijo in (".txt", ".txt.md5"):
        f_old = model.FILTERS_DIR / f"{old}{sufijo}"
        f_new = model.FILTERS_DIR / f"{new}{sufijo}"
        if f_old.exists() and not f_new.exists():
            f_old.rename(f_new)
            movimientos.append((f_old, f_new))
    return movimientos
