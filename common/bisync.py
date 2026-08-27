#!/usr/bin/env python3
"""
bisync.py — Todo lo que replica el comportamiento interno de rclone bisync.

Aquí vive la parte incómoda del proyecto, y vive junta a propósito: bisync guarda
su baseline en ficheros cuyo nombre deduce de los dos extremos, y no perdona que
ese nombre cambie. Saber calcular ANTES de ejecutar el nombre que rclone va a
buscar es lo que permite renombrar el juego de listados en vez de comerse un
error crítico.

Cada apartado cita el fichero de rclone cuyo comportamiento imita. Si se toca
algo de aquí, es contra esas fuentes contra lo que hay que contrastarlo.
"""

from __future__ import annotations

import hashlib
import os
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

# El mensaje con el que rclone se queja de que no encuentra el baseline.
MISSING_LISTINGS = "cannot find prior Path1 or Path2 listings"


# ---------------------------------------------------------------------------
# Nombre de sesión
#
# Réplica exacta de cmd/bisync/bilib/canonical.go (rclone master):
#
#   FsPath(f)        -> "F:\ruta\" para el backend local, "remote:ruta/" para el resto
#   CanonicalPath(s) -> quita / y \ de los extremos y sustituye [\s\\/:?*] por _
#   SessionName      -> CanonicalPath(path1) + ".." + CanonicalPath(path2), sin el
#                       sufijo {hexstring} que rclone añade cuando la config del
#                       remote viene de flags/env/connection string.
# ---------------------------------------------------------------------------

_NON_CANONICAL = re.compile(r"[\s\\/:?*]")


def canonical_path(remote: str) -> str:
    return _NON_CANONICAL.sub("_", remote.strip("\\/"))


def strip_hex_string(path: str) -> str:
    opening, closing = path.find("{"), path.find("}")
    if opening >= 0 and closing > opening:
        return path[:opening] + path[closing + 1:]
    return path


def fs_path_local(p: str) -> str:
    sep = os.sep
    if os.name == "nt":
        p = p.replace("/", sep)
        if p.startswith("\\\\?\\"):
            p = p[4:]
    return p if p.endswith(sep) else p + sep


def fs_path_remote(s: str) -> str:
    return s if s.endswith("/") else s + "/"


def session_name(path1: str, path2: str) -> str:
    return strip_hex_string(canonical_path(path1)) + ".." + strip_hex_string(canonical_path(path2))


def expected_prefix(pair: Pair) -> str:
    """Nombre base (.path1.lst / .path2.lst) que rclone buscará para esta pareja."""
    def render(kind: str) -> str:
        endpoint = pair.endpoint(kind)
        if kind == "local" and not pair.device_remote:
            return fs_path_local(endpoint)
        return fs_path_remote(endpoint)

    return session_name(render(pair.mode.source), render(pair.mode.dest))


# ---------------------------------------------------------------------------
# Filtros
#
# bisync guarda el md5 del fichero de filtros JUNTO AL PROPIO FICHERO
# (filtersFile + ".md5", ver cmd/bisync/cmd.go: applyFilters) y solo lo escribe
# durante un --resync. Si el fichero cambia sin resync, aborta con error crítico.
# Aquí se compara el md5 ANTES de ejecutar y se trata como "hace falta resync",
# que es una conversación y no un log rojo.
# ---------------------------------------------------------------------------

FILTERS_HEADER = (
    "# Generado por sync.py desde sync_config.toml. No editar a mano:\n"
    "# se regenera en cada ejecución. Cambiar los patrones exige --resync."
)


class FiltersState(NamedTuple):
    status: str          # 'ok' | 'new' | 'changed'
    detail: str

    @property
    def needs_resync(self) -> bool:
        return self.status != "ok"


def filters_content(pair: Pair) -> str:
    lines = [FILTERS_HEADER]
    lines += [f"+ {p}" for p in pair.includes]
    lines += [f"- {p}" for p in pair.excludes]
    if pair.includes:
        # Igual que --include: si hay reglas '+', todo lo demás queda fuera.
        lines.append("- **")
    return "\n".join(lines) + "\n"


def filters_file_for(pair: Pair) -> Path | None:
    """Genera (si hace falta) filters/<pareja>.txt y devuelve su ruta.

    El contenido es determinista: si no cambia, no se reescribe el fichero, para
    no gastar ciclos del dispositivo ni invalidar el md5 sin motivo."""
    if not pair.wants_filters_file:
        return None

    content = filters_content(pair)
    model.FILTERS_DIR.mkdir(parents=True, exist_ok=True)
    path = model.FILTERS_DIR / f"{pair.name}.txt"
    if not path.exists() or path.read_text(encoding="utf-8") != content:
        path.write_text(content, encoding="utf-8", newline="\n")
    return path


def filters_state(ffile: Path | None) -> FiltersState:
    """Compara el fichero de filtros con el .md5 que dejó el último resync."""
    if ffile is None:
        return FiltersState("ok", "sin fichero de filtros")
    digest = hashlib.md5(ffile.read_bytes()).hexdigest()
    hash_file = Path(str(ffile) + ".md5")
    if not hash_file.exists():
        return FiltersState("new", f"{ffile.name} sin hash previo")
    if hash_file.read_text(encoding="utf-8").strip() != digest:
        return FiltersState("changed", f"{ffile.name} ha cambiado desde el último resync")
    return FiltersState("ok", f"{ffile.name} sin cambios")


# ---------------------------------------------------------------------------
# Estado del baseline
# ---------------------------------------------------------------------------

class PairState(NamedTuple):
    status: str          # 'fresh' | 'ok' | 'broken'
    detail: str
    prefix: str | None   # solo cuando status == 'ok'

    @property
    def has_baseline(self) -> bool:
        return self.status == "ok"


def _prefixes(paths: list[Path], suffix: str) -> set[str]:
    return {p.name[: -len(suffix)] for p in paths}


def pair_state(pair: Pair) -> PairState:
    """El estado real del baseline, mirando los .lst que hay en el workdir."""
    workdir = pair.workdir
    if not workdir.exists():
        return PairState("fresh", "sin workdir (nunca sincronizada)", None)

    # OJO al orden: los .lst-err NO los limpia nadie (rclone solo renombra
    # .lst -> .lst-err al abortar; ver cmd/bisync/operations.go). Si después hay
    # un juego de listados válido, el baseline es bueno y esos son residuo.
    path1 = sorted(workdir.glob("*" + PATH1_SUFFIX))
    path2 = sorted(workdir.glob("*" + PATH2_SUFFIX))
    errors = sorted(workdir.glob("*" + ERR_SUFFIX))
    residuo = f" (+{len(errors)} {ERR_SUFFIX} residuales)" if errors else ""

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
            f"{len(errors)} listado(s) marcados {ERR_SUFFIX} por un fallo crítico previo",
            None)
    if path1 or path2:
        return PairState("broken", "falta uno de los dos listados (.path1/.path2)", None)
    return PairState("fresh", "sin listados previos", None)


def last_run(pair: Pair) -> float | None:
    """Cuándo fue la última pasada buena, o None si no hay forma de saberlo.

    No existe un registro de pasadas y no hace falta inventarlo: bisync reescribe
    sus dos listados justo al terminar bien (ver cmd/bisync/operations.go), así
    que la fecha del más nuevo ES la de la última sincronización correcta. Fuera
    de bisync no queda rastro —un `copy` no deja estado—, y esas parejas se
    quedan sin hora antes que enseñar una inventada."""
    if not pair.is_bisync:
        return None
    try:
        marcas = [p.stat().st_mtime
                  for sufijo in (PATH1_SUFFIX, PATH2_SUFFIX)
                  for p in pair.workdir.glob("*" + sufijo)]
    except OSError:
        return None                      # el dispositivo ya no está: no es asunto de aquí
    return max(marcas) if marcas else None


def resync_reasons(pair: Pair, state: PairState | None = None) -> list[str]:
    """Por qué esta pareja necesita --resync. Lista vacía = no lo necesita.

    `state` se puede pasar ya calculado: quien acaba de mirarlo no tiene por qué
    volver a recorrer el workdir."""
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


# ---------------------------------------------------------------------------
# Reparaciones del baseline
# ---------------------------------------------------------------------------

def migrate_legacy_state(pair: Pair) -> None:
    """Mueve los listados del layout antiguo (todo suelto en state/) al workdir
    por pareja, identificando la pareja por el token del remoto en el nombre."""
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


def rename_prefix(pair: Pair, old_prefix: str, new_prefix: str) -> None:
    for f in sorted(pair.workdir.iterdir()):
        if f.is_file() and f.name.startswith(old_prefix):
            f.rename(pair.workdir / (new_prefix + f.name[len(old_prefix):]))
    print(f"  listados renombrados: '{old_prefix}' -> '{new_prefix}'")


def normalize_prefix(pair: Pair) -> None:
    """Si el baseline está guardado con otro prefijo (el dispositivo se montaba en G: y
    ahora en F:), lo renombra ANTES de ejecutar. El contenido de los .lst es
    relativo a la raíz sincronizada, así que renombrarlos es seguro."""
    state = pair_state(pair)
    if not state.has_baseline or state.prefix is None:
        return
    want = expected_prefix(pair)
    if state.prefix != want:
        rename_prefix(pair, state.prefix, want)


def pair_state_paths(name: str) -> list[Path]:
    """Lo que hay en disco atado a esa pareja: su workdir y su fichero de filtros.

    Sirve para avisar de qué queda huérfano al quitar una pareja, y para
    limpiarlo si se pide."""
    encontrados = [model.STATE_DIR / name]
    encontrados += [model.FILTERS_DIR / f"{name}.txt",
                    model.FILTERS_DIR / f"{name}.txt.md5"]
    return [p for p in encontrados if p.exists()]


def shelve_baseline(name: str) -> Path | None:
    """Aparta el baseline de una pareja: state/<n>/ -> state/<n>.old-<fecha>/.

    Es lo que hay que hacer cuando cambia un EXTREMO de la pareja (local, remote,
    remote_path o mode). No basta con dejar que normalize_prefix() renombre los
    listados al prefijo nuevo: eso le estaría diciendo a bisync que el listado del
    destino VIEJO describe el destino NUEVO, y todo lo que no esté en el nuevo se
    leería como borrado y se propagaría al otro lado. Apartándolo, la pareja queda
    'fresh' y exige un --resync explícito, que es una conversación.

    Se renombra en vez de borrar por si hay que volver atrás; el directorio
    apartado queda inerte, porque lo que recorre state/ solo mira su primer nivel.

    Devuelve dónde ha quedado, o None si no había baseline que apartar."""
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
    """Mueve el estado de una pareja cuando solo le cambia el nombre.

    El prefijo de los listados NO depende del nombre (ver expected_prefix: sale de
    los extremos), así que renombrar no invalida el baseline. Lo que sí cuelga del
    nombre son las rutas: state/<nombre>/ y filters/<nombre>.txt, con su .md5 al
    lado. Se mueven juntos para que el hash que guarda bisync siga cuadrando.

    Devuelve los movimientos como (origen, destino) para poder deshacerlos."""
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


_TIP_RE = re.compile(r"^\s*(Path1|Path2):\s*(.+?)\s*$", re.MULTILINE)


def heal_listings(pair: Pair, logfile: Path) -> bool:
    """Red de seguridad por si el prefijo calculado no coincidiera con el de
    rclone: se lee el nombre que rclone dice esperar en su propio log ('Tip: here
    are the filenames...') y se renombra el juego de listados."""
    if not logfile.exists():
        return False
    text = logfile.read_text(encoding="utf-8", errors="replace")
    if MISSING_LISTINGS not in text:
        return False

    tips = dict(_TIP_RE.findall(text))
    if "Path1" not in tips:
        return False
    expected = Path(tips["Path1"])
    if not expected.name.endswith(PATH1_SUFFIX):
        return False
    if expected.parent.name != pair.workdir.name:  # paranoia
        return False

    new_prefix = expected.name[: -len(PATH1_SUFFIX)]
    state = pair_state(pair)
    if not state.has_baseline or state.prefix in (None, new_prefix):
        return False
    rename_prefix(pair, state.prefix, new_prefix)
    return True
