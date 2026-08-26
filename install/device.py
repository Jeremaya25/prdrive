#!/usr/bin/env python3
"""
device.py — Qué unidades hay, cuál va a ser el pen, y si al final quedó bien.

Tres cosas, y las tres son de seguridad más que de comodidad:

  * `list_volumes()` NO filtra por «extraíble». Muchos pendrives —y casi todos
    los SSD por USB— se declaran `Fixed`, así que filtrar por ahí es justo lo que
    hace que el pen del usuario no aparezca en la lista. Se listan todos y se
    marca cuáles lo parecen; quien decide es el usuario, con los datos delante.

  * `seed_target()` mira qué hay en el destino ANTES de sembrar. La siembra es un
    espejo que borra en destino: apuntar a la carpeta equivocada la vacía, con
    `--max-delete` como único freno. Una carpeta con cosas que no son de un pen
    PEREPEN no se siembra sin que el usuario lo confirme a conciencia.

  * `ensure_control_file()` renueva el `id=` del fichero PEREPEN. El pen se
    siembra copiando el espejo maestro, y ese espejo trae el PEREPEN del pen de
    origen: sin renovar el id, dos pens distintos dirían ser el mismo y un
    vigilante configurado para uno concreto se confundiría.

`CONTROL_FILE` y `CONTROL_TEMPLATE` están copiados de `penwatch.py` a propósito y
no importados: penwatch se copia al equipo del usuario y tiene que funcionar con
el pen desconectado, así que no puede depender de este paquete, y este paquete
acaba dentro de un .exe donde importar un script hermano es un lío. Hay un test
que comprueba que las dos copias no se separan.
"""

from __future__ import annotations

import json
import os
import subprocess
import tomllib
import uuid
from dataclasses import dataclass
from pathlib import Path

from common import model

from . import CREATE_NO_WINDOW, IS_WIN, InstallError
from .rclone_bin import bin_subdir, exe_name

CONTROL_FILE = "PEREPEN"
CONTROL_TEMPLATE = """\
# PEREPEN — fichero de control del pen. NO LO BORRES.
# Es lo que permite reconocer esta unidad se monte donde se monte (F:, /media/...).
# Lo usa rclone-sync/penwatch.py para lanzar la sincronización al conectar el pen.
id={pen_id}
"""

CONTAINER_SUFFIX = ".hc"
STRUCT_MARKER = Path("rclone-sync") / "runsync.py"

# Lo que el sistema deja en cualquier volumen y no cuenta como «aquí hay cosas».
RUIDO = {
    "system volume information", "$recycle.bin", "recycler", "lost+found",
    "desktop.ini", ".ds_store", ".spotlight-v100", ".fseventsd", ".trashes",
    "autorun.inf", "perepen", "perepen.hc",
}

# Puntos de montaje donde los escritorios de Linux/macOS cuelgan los extraíbles.
POSIX_BASES = ("/media", "/run/media", "/mnt", "/Volumes")


# ---------------------------------------------------------------------------
# Volúmenes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Volume:
    """Una unidad candidata. Todo lo que se sabe de ella sin abrirla."""
    root: Path
    label: str = ""
    filesystem: str = ""
    drive_type: str = ""            # Removable | Fixed | ... ; vacío en POSIX
    size: int = 0
    free: int = 0
    is_system: bool = False

    @property
    def removable(self) -> bool:
        return self.drive_type.lower() == "removable"

    def _exists(self, rel) -> bool:
        """Un volumen bloqueado por BitLocker responde con error de permisos, no
        con «no existe»: cualquier OSError significa «ahora mismo no se sabe»."""
        try:
            return (self.root / rel).exists()
        except OSError:
            return False

    @property
    def has_control(self) -> bool:
        return self._exists(CONTROL_FILE)

    @property
    def has_container(self) -> bool:
        return self._exists("PEREPEN" + CONTAINER_SUFFIX)

    @property
    def has_structure(self) -> bool:
        return self._exists(STRUCT_MARKER)

    @property
    def nota(self) -> str:
        """Lo que hay que saber de un vistazo al elegir destino."""
        partes = []
        if self.is_system:
            partes.append("¡UNIDAD DEL SISTEMA!")
        if self.has_container:
            partes.append("contenedor VeraCrypt")
        if self.has_control:
            partes.append("ya es un PEREPEN" if self.has_structure
                          else "tiene PEREPEN pero le falta rclone-sync/")
        if not partes and not self.removable:
            partes.append("no se declara extraíble")
        return "; ".join(partes)

    @property
    def size_gb(self) -> float:
        return round(self.size / 1024 ** 3, 1)

    @property
    def free_gb(self) -> float:
        return round(self.free / 1024 ** 3, 1)


PS_VOLUMES = (
    "Get-Volume -ErrorAction SilentlyContinue | "
    "Where-Object { $_.DriveLetter } | "
    "Select-Object DriveLetter, FileSystemLabel, FileSystem, "
    "@{n='DriveType';e={[string]$_.DriveType}}, Size, SizeRemaining | "
    "ConvertTo-Json -Compress"
)


def _powershell(script: str, timeout: float = 30.0) -> str:
    kwargs: dict = {}
    if IS_WIN:
        kwargs["creationflags"] = CREATE_NO_WINDOW
    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            text=True, encoding="utf-8", errors="replace",
            capture_output=True, timeout=timeout, **kwargs)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return (res.stdout or "").strip()


def parse_volumes_json(salida: str, system_drive: str = "") -> list[Volume]:
    """El JSON de Get-Volume -> Volumes.

    ConvertTo-Json devuelve un OBJETO cuando solo hay un volumen y una LISTA
    cuando hay varios; con un solo pendrive conectado, tratarlo como lista es
    justo el caso que falla."""
    if not salida:
        return []
    try:
        data = json.loads(salida)
    except ValueError:
        return []
    filas = [data] if isinstance(data, dict) else list(data)

    system = (system_drive or os.environ.get("SystemDrive", "C:")).rstrip(":").upper()
    volumenes = []
    for fila in filas:
        letra = str(fila.get("DriveLetter") or "").strip().rstrip(":")
        if not letra:
            continue
        volumenes.append(Volume(
            root=Path(f"{letra.upper()}:\\"),
            label=str(fila.get("FileSystemLabel") or ""),
            filesystem=str(fila.get("FileSystem") or ""),
            drive_type=str(fila.get("DriveType") or ""),
            size=int(fila.get("Size") or 0),
            free=int(fila.get("SizeRemaining") or 0),
            is_system=letra.upper() == system,
        ))
    return volumenes


def _posix_volumes() -> list[Volume]:
    """Lo que haya montado bajo los sitios habituales de los extraíbles.

    Se miran DOS niveles porque los escritorios no se ponen de acuerdo:
    `/media/<etiqueta>` y `/media/<usuario>/<etiqueta>` son igual de comunes, y
    quedarse en el primero deja fuera medio Linux."""
    puntos: list[Path] = []
    for base in POSIX_BASES:
        raiz = Path(base)
        try:
            hijos = sorted(raiz.iterdir()) if raiz.is_dir() else []
        except OSError:
            continue                       # /media existe pero no se puede leer
        for hijo in hijos:
            puntos.append(hijo)
            try:
                puntos += [n for n in sorted(hijo.iterdir()) if n.is_dir()]
            except OSError:
                pass                       # no es directorio, o es un montaje ilegible

    volumenes, vistos = [], set()
    for punto in puntos:
        if punto in vistos:
            continue
        vistos.add(punto)
        try:
            st = os.statvfs(punto)
            size, free = st.f_blocks * st.f_frsize, st.f_bavail * st.f_frsize
        except (OSError, AttributeError):
            size = free = 0
        volumenes.append(Volume(root=punto, label=punto.name, size=size, free=free))
    return volumenes


def list_volumes() -> list[Volume]:
    """Todas las unidades candidatas, sin filtrar por «extraíble».

    Los pendrives que se declaran `Fixed` son la norma, no la excepción, así que
    filtrar por el tipo es la forma más rápida de que el pen del usuario no salga
    en la lista. Se ordenan poniendo delante lo que más se parece a un pen."""
    volumenes = parse_volumes_json(_powershell(PS_VOLUMES)) if IS_WIN else _posix_volumes()
    return sorted(volumenes, key=lambda v: (v.is_system, not v.has_control,
                                            not v.has_container, not v.removable,
                                            str(v.root)))


def volume_for(root: Path) -> Volume:
    """El Volume de una ruta escrita a mano, con lo que se pueda averiguar."""
    root = Path(root)
    for vol in list_volumes():
        try:
            if vol.root == root or vol.root.resolve() == root.resolve():
                return vol
        except OSError:
            continue
    try:
        import shutil as _shutil
        uso = _shutil.disk_usage(str(root))
        size, free = uso.total, uso.free
    except OSError:
        size = free = 0
    system = os.environ.get("SystemDrive", "C:").rstrip(":").upper()
    return Volume(root=root, label=root.name, size=size, free=free,
                  is_system=str(root).rstrip("\\/").upper() == f"{system}:")


# ---------------------------------------------------------------------------
# ¿Se puede sembrar aquí?
# ---------------------------------------------------------------------------

VACIO = "vacio"
PEREPEN_YA = "perepen"
AJENO = "ajeno"


def seed_target(root: Path) -> tuple[str, str]:
    """Qué hay en el destino, para decidir si se puede sembrar sin preguntar.

    Devuelve ('vacio'|'perepen'|'ajeno', explicación). La siembra es un `rclone
    sync`, o sea un espejo que BORRA en destino lo que no esté en el origen:
    'ajeno' significa que ahí hay cosas que no son de un pen PEREPEN y que se
    perderían, así que quien llama tiene que pedir una confirmación seria."""
    root = Path(root)
    try:
        if not root.exists():
            return VACIO, "La carpeta no existe todavía; se creará."
        contenido = [p for p in root.iterdir() if p.name.lower() not in RUIDO]
    except OSError as e:
        raise InstallError(
            f"No puedo leer {root}: {e}\n"
            "¿Está el volumen desbloqueado (BitLocker/VeraCrypt)?") from e

    if not contenido:
        return VACIO, "Está vacío."

    tiene_control = (root / CONTROL_FILE).exists()
    tiene_estructura = (root / STRUCT_MARKER).exists()
    if tiene_control and tiene_estructura:
        return PEREPEN_YA, "Ya es un pen PEREPEN: la siembra lo actualiza."

    nombres = ", ".join(sorted(p.name for p in contenido)[:6])
    return AJENO, (
        f"Aquí hay {len(contenido)} elemento(s) que no son de un pen PEREPEN "
        f"({nombres}{'…' if len(contenido) > 6 else ''}). La siembra es un ESPEJO: "
        f"todo eso se BORRARÍA.")


# ---------------------------------------------------------------------------
# El fichero de control
# ---------------------------------------------------------------------------

def control_id(root: Path) -> str | None:
    """El 'id=' de dentro del PEREPEN, o None si no lleva ninguno."""
    try:
        texto = (Path(root) / CONTROL_FILE).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for linea in texto.splitlines():
        linea = linea.strip()
        if linea.lower().startswith("id="):
            return linea[3:].strip() or None
    return None


def ensure_control_file(root: Path, renew: bool = False) -> str:
    """Deja un PEREPEN con id en la raíz y devuelve ese id.

    `renew=True` es lo que hay que usar DESPUÉS de sembrar: el fichero que llega
    con la siembra trae el id del pen de origen, y dos pens con el mismo id no se
    pueden distinguir."""
    path = Path(root) / CONTROL_FILE
    actual = control_id(root)
    if actual and not renew:
        return actual
    nuevo = uuid.uuid4().hex
    try:
        path.write_text(CONTROL_TEMPLATE.format(pen_id=nuevo), encoding="utf-8")
    except OSError as e:
        raise InstallError(f"No he podido escribir {path}: {e}") from e
    return nuevo


# ---------------------------------------------------------------------------
# Verificación final
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Check:
    etiqueta: str
    ok: bool
    detalle: str


def verify_pen(root: Path, esperadas: list[str] | None = None) -> list[Check]:
    """La lista de comprobación del último paso: ¿este pen va a funcionar?

    Mira lo que de verdad hace falta para que `runsync.py` arranque en cualquier
    equipo: el binario de rclone de esta arquitectura, la clave, el config, y que
    el config se pueda leer. Lo que falte aquí es lo que fallaría luego sin que
    se entienda por qué."""
    root = Path(root)
    app = root / "rclone-sync"
    checks: list[Check] = []

    def mirar(etiqueta: str, ruta: Path, pista: str = "") -> bool:
        try:
            existe = ruta.exists()
        except OSError as e:
            checks.append(Check(etiqueta, False, f"no se puede leer: {e}"))
            return False
        checks.append(Check(etiqueta, existe,
                            str(ruta) if existe else (pista or f"falta {ruta}")))
        return existe

    pen_id = control_id(root)
    checks.append(Check("Fichero de control", bool(pen_id),
                        f"id {pen_id[:8]}…" if pen_id else
                        f"falta {root / CONTROL_FILE} o no tiene id propio"))

    mirar("Lanzador (runsync.py)", app / "runsync.py")
    mirar("Motor (sync.py)", app / "sync.py")
    mirar(f"rclone ({bin_subdir()})", app / "bin" / bin_subdir() / exe_name(),
          "sin el binario de esta arquitectura el pen no sincroniza aquí")
    mirar("Clave del NAS", app / "keys" / "synology_ed25519")
    mirar("rclone.conf", app / "rclone.conf")

    config = app / "sync_config.toml"
    if mirar("sync_config.toml", config):
        checks.append(_check_config(config, esperadas or []))

    checks.append(check_python())
    return checks


def _check_config(config: Path, esperadas: list[str]) -> Check:
    try:
        with config.open("rb") as f:
            cfg = model.parse_config(tomllib.load(f))
    except (OSError, ValueError, model.ConfigError) as e:
        return Check("El config se lee", False, str(e))
    faltan = [n for n in esperadas if n not in cfg.names]
    if faltan:
        return Check("El config se lee", False,
                     f"no están las parejas elegidas: {', '.join(faltan)}")
    return Check("El config se lee", True, f"{len(cfg.pairs)} pareja(s): "
                 + ", ".join(cfg.names))


def check_python() -> Check:
    """Python y Tkinter EN ESTE EQUIPO. No es del pen, pero sin ellos el pen no
    se puede usar aquí, y es mejor enterarse ahora que al conectarlo."""
    from . import python_command
    cmd = python_command()
    if not cmd:
        return Check("Python en este equipo", False,
                     "no encuentro ningún intérprete: instala Python 3.11+")
    try:
        import tkinter  # noqa: F401
        return Check("Python en este equipo", True, f"{' '.join(cmd)} (con Tkinter)")
    except Exception:
        return Check("Python en este equipo", True,
                     f"{' '.join(cmd)}, pero SIN Tkinter: saldrá el menú de consola")
