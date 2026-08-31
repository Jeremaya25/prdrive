#!/usr/bin/env python3
"""
device.py — Qué unidades hay, cuál va a ser el dispositivo, y si al final quedó bien.

Tres cosas, y las tres son de seguridad más que de comodidad:

  * `list_volumes()` NO filtra por «extraíble». Muchos pendrives —y casi todos
    los SSD por USB— se declaran `Fixed`, así que filtrar por ahí es justo lo que
    hace que el dispositivo del usuario no aparezca en la lista. Se listan todos y se
    marca cuáles lo parecen; quien decide es el usuario, con los datos delante.
    Lo único que se descarta son las unidades de red (`TIPOS_OCULTOS`): ninguna
    puede ser un dispositivo, y `GetLogicalDrives` sí las devuelve.

  * `install_target()` mira qué hay en el destino ANTES de escribir. Instalar ya
    no borra nada —era un espejo del remoto y ahora es una copia local—, pero
    seguir adelante sobre la carpeta equivocada deja el programa desperdigado
    entre los datos de otro, así que se pide confirmación antes de tocarla.

  * `ensure_control_file()` pone el `id=` del fichero PRDRIVE. Es lo que
    distingue este dispositivo de cualquier otro: sin id propio, un vigilante
    configurado para uno concreto se confundiría con el de al lado.

`CONTROL_FILE` y `CONTROL_TEMPLATE` están copiados de `penwatch.py` a propósito y
no importados: penwatch se copia al equipo del usuario y tiene que funcionar con
el dispositivo desconectado, así que no puede depender de este paquete, y este
paquete acaba dentro de un .exe donde importar un script hermano es un lío. Hay
un test que comprueba que las dos copias no se separan.
"""

from __future__ import annotations

import os
import shutil
import tomllib
import uuid
from dataclasses import dataclass, replace
from pathlib import Path

from common import model

from . import DEVICE_LABEL, IS_WIN, InstallError
from .rclone_bin import bin_subdir, exe_name

CONTAINER_SUFFIX = ".hc"
APP_SUBDIR = ".prdrive"
STRUCT_MARKER = Path(APP_SUBDIR) / "runsync.py"

# El fichero de control, DENTRO de la carpeta del programa y no en la raíz del
# volumen. Lo que hace es identificar la unidad se monte donde se monte, y para
# eso da igual dónde esté mientras la ruta sea relativa a la raíz: en `.prdrive/`
# cumple lo mismo sin dejar un fichero suelto entre los datos del usuario, y de
# paso no se puede borrar sin borrar también el programa.
CONTROL_FILE = Path(APP_SUBDIR) / DEVICE_LABEL
CONTROL_TEMPLATE = """\
# PRDRIVE — fichero de control del dispositivo. NO LO BORRES.
# Es lo que permite reconocer esta unidad se monte donde se monte (F:, /media/...).
# Lo usa .prdrive/penwatch.py para lanzar la sincronización al conectarla.
id={device_id}
"""

# Lo que el sistema deja en cualquier volumen —o lo que ponemos nosotros— y no
# cuenta como «aquí hay cosas de otro». Se compara con `p.name.lower()`, así que
# va todo en minúsculas. Olvidar aquí algo que escribe el instalador hace que un
# dispositivo recién hecho se clasifique como AJENO la siguiente vez.
RUIDO = {
    "system volume information", "$recycle.bin", "recycler", "lost+found",
    ".ds_store", ".spotlight-v100", ".fseventsd", ".trashes", "desktop.ini",
    "autorun.inf", "prdrive.hc", ".prdrive",
    "runsync.pyw", "runsync.sh", "runsync.ico",
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
        return self._exists(DEVICE_LABEL + CONTAINER_SUFFIX)

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
            # Con el control dentro de `.prdrive/`, que falte la estructura ya no
            # es «no hay carpeta»: la carpeta está y lo que falta es el programa,
            # o sea una instalación a medias.
            partes.append("ya es un prdrive" if self.has_structure
                          else f"tiene {CONTROL_FILE} pero le falta el programa")
        if not partes and not self.removable:
            partes.append("no se declara extraíble")
        return "; ".join(partes)

    @property
    def size_gb(self) -> float:
        return round(self.size / 1024 ** 3, 1)

    @property
    def free_gb(self) -> float:
        return round(self.free / 1024 ** 3, 1)


# Los tipos que devuelve `GetDriveTypeW`, con los mismos nombres que daba
# `Get-Volume`: son los que enseña la tabla del asistente y los que mira
# `Volume.removable`, así que traducirlos a otra cosa sería cambiar la pantalla y
# la lógica a la vez sin ninguna necesidad.
DRIVE_TYPES = {
    2: "Removable",
    3: "Fixed",
    4: "Network",
    5: "CD-ROM",
    6: "RAM disk",
}

# Se enumeran pero NO se ofrecen. Una unidad de red no puede ser el dispositivo,
# y `Get-Volume` tampoco las devolvía: sin este filtro el selector de destino se
# llena de unidades mapeadas que nadie puede elegir.
TIPOS_OCULTOS = ("Network",)


def make_volume(letra: str, drive_type: str = "", label: str = "",
                filesystem: str = "", size: int = 0, free: int = 0,
                system_drive: str = "") -> Volume:
    """Un `Volume` a partir de lo que haya contestado el sistema.

    Es la mitad pura de la enumeración, y por eso es la que se prueba:
    `_win_volumes()` no hace más que traducir llamadas de kernel32 a estos
    argumentos, igual que `_leer_estado_bitlocker` en `crypto.py` es la parte que
    los tests sustituyen en vez de simular."""
    system = (system_drive or os.environ.get("SystemDrive", "C:")).rstrip(":").upper()
    letra = letra.strip().rstrip(":").upper()
    return Volume(
        root=Path(f"{letra}:\\"),
        label=label or "",
        filesystem=filesystem or "",
        drive_type=drive_type or "",
        size=int(size or 0),
        free=int(free or 0),
        is_system=letra == system,
    )


def _win_volumes() -> list[Volume]:
    """Las unidades con letra, preguntándole a kernel32 en vez de a PowerShell.

    Cuatro llamadas, ninguna eleva. Antes esto era un `Get-Volume` lanzado con
    `powershell -Command`, y se cambió por dos razones:

      * **Tardaba 3,5 segundos**, medidos y constantes —no era arranque en frío—,
        contra unos 35 ms de esto. Y `ui.tk_install._paso_destino` lo llama en el
        hilo de Tk al dibujar la PRIMERA pantalla del asistente, y otra vez en
        cada «Actualizar lista», que es justo lo que se pulsa tras enchufar el
        pendrive: la ventana se quedaba muerta esos 3,5 s cada vez.
      * Era el último proceso hijo que lanzaba el instalador en el camino normal.
        Un .exe sin firmar que corre desde %TEMP% y lanza PowerShell es la forma
        que puntúa en un antivirus; ver la nota larga de BitLocker en `crypto.py`.

    Dos cosas hay que hacer aquí que `Get-Volume` hacía por su cuenta:

      * **Callar el diálogo de «No hay ningún disco en la unidad».** Un lector de
        tarjetas o un CD vacíos lo sacan en cuanto se les pregunta, y sale ENCIMA
        del asistente a esperar a que alguien lo cierre. `SetThreadErrorMode` es
        la versión por hilo de `SetErrorMode`, que es global al proceso: se
        restaura al salir para no cambiarle el modo a nadie más.
      * **Quitar las unidades de red**, que `GetLogicalDrives` sí devuelve."""
    import ctypes
    from ctypes import byref, c_ulonglong, c_wchar_p, create_unicode_buffer
    from ctypes.wintypes import DWORD

    k32 = ctypes.windll.kernel32
    SEM_FAILCRITICALERRORS = 0x0001
    LARGO = 261                    # MAX_PATH + 1, lo que pide GetVolumeInformationW

    volumenes: list[Volume] = []
    anterior = DWORD()
    k32.SetThreadErrorMode(SEM_FAILCRITICALERRORS, byref(anterior))
    try:
        mascara = k32.GetLogicalDrives()
        for i in range(26):
            if not (mascara >> i) & 1:
                continue
            letra = chr(ord("A") + i)
            raiz = c_wchar_p(f"{letra}:\\")

            tipo = DRIVE_TYPES.get(k32.GetDriveTypeW(raiz), "Unknown")
            if tipo in TIPOS_OCULTOS:
                continue

            etiqueta = create_unicode_buffer(LARGO)
            sistema = create_unicode_buffer(LARGO)
            if not k32.GetVolumeInformationW(raiz, etiqueta, LARGO,
                                             None, None, None, sistema, LARGO):
                # Sin medio dentro, o bloqueada. La unidad sigue saliendo en la
                # lista y sin etiqueta: que la letra exista ya es un dato, y
                # esconderla es lo que dejaba al usuario sin ver su dispositivo.
                etiqueta.value = sistema.value = ""

            total, libre = c_ulonglong(0), c_ulonglong(0)
            # El segundo hueco es el libre PARA QUIEN PREGUNTA (cuotas); el que
            # se quiere aquí es el total libre, que es lo que decía SizeRemaining.
            if not k32.GetDiskFreeSpaceExW(raiz, None, byref(total), byref(libre)):
                total.value = libre.value = 0

            volumenes.append(make_volume(letra, tipo, etiqueta.value,
                                         sistema.value, total.value, libre.value))
    finally:
        k32.SetThreadErrorMode(anterior, byref(DWORD()))
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


def _con_tamano(vol: Volume) -> Volume:
    """Rellena tamaño y hueco cuando la enumeración los ha dejado a cero.

    Visto una vez: `Get-Volume` devolvió el pendrive con `Size` y `SizeRemaining`
    a cero mientras el volumen estaba montado y se leía sin problemas —un
    `disk_usage` sobre esa misma ruta contestaba bien—, y el asistente lo
    enseñaba como «0 GB». No ha vuelto a reproducirse, así que la causa no se
    sabe y no se finge saberla. Lo que sí se sabe es que un cero aquí merece una
    segunda opinión antes de enseñárselo a nadie: quien ve «0 GB» descarta esa
    unidad.

    Se hace aquí y no en `make_volume` para que ese siga siendo una traducción
    pura de lo que conteste el sistema, que es como está probado."""
    if vol.size:
        return vol
    try:
        uso = shutil.disk_usage(str(vol.root))
    except OSError:
        return vol                     # bloqueado, sin medio dentro, o desaparecido
    return replace(vol, size=uso.total, free=uso.free)


def list_volumes() -> list[Volume]:
    """Todas las unidades candidatas, sin filtrar por «extraíble».

    Los pendrives que se declaran `Fixed` son la norma, no la excepción, así que
    filtrar por el tipo es la forma más rápida de que el dispositivo del usuario no salga
    en la lista. Se ordenan poniendo delante lo que más se parece a un dispositivo."""
    volumenes = [_con_tamano(v) for v in
                 (_win_volumes() if IS_WIN else _posix_volumes())]
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
        uso = shutil.disk_usage(str(root))
        size, free = uso.total, uso.free
    except OSError:
        size = free = 0
    system = os.environ.get("SystemDrive", "C:").rstrip(":").upper()
    return Volume(root=root, label=root.name, size=size, free=free,
                  is_system=str(root).rstrip("\\/").upper() == f"{system}:")


# ---------------------------------------------------------------------------
# ¿Se puede instalar aquí?
# ---------------------------------------------------------------------------

VACIO = "vacio"
YA_INSTALADO = "instalado"
AJENO = "ajeno"


def install_target(root: Path) -> tuple[str, str]:
    """Qué hay en el destino, para decidir si se puede instalar sin preguntar.

    Devuelve ('vacio'|'instalado'|'ajeno', explicación). Instalar es copiar, así
    que 'ajeno' ya no significa «esto se borraría»: significa que el volumen es
    de otra cosa y que dejar ahí el programa y sus lanzadores probablemente no es
    lo que se quería. Quien llama pide confirmación, pero no es la confirmación
    destructiva que hacía falta con la siembra."""
    root = Path(root)
    try:
        if not root.exists():
            return VACIO, "La carpeta no existe todavía; se creará."
        contenido = [p for p in root.iterdir() if p.name.lower() not in RUIDO]
    except OSError as e:
        raise InstallError(
            f"No puedo leer {root}: {e}\n"
            "¿Está el volumen desbloqueado (BitLocker/VeraCrypt)?") from e

    # Reconocer el dispositivo va ANTES de mirar si hay algo dentro, y el orden
    # no es cosmético: `.prdrive` está en RUIDO —tiene que estarlo, o el
    # dispositivo que el instalador acaba de hacer se leería como ajeno la vez
    # siguiente—, así que un volumen recién provisionado, con el programa dentro
    # y todavía sin datos del usuario, no deja NINGÚN contenido a la vista y se
    # leía como vacío. El asistente entonces no ofrecía el recorrido corto justo
    # en el dispositivo más nuevo que existe.
    tiene_control = (root / CONTROL_FILE).exists()
    tiene_estructura = (root / STRUCT_MARKER).exists()
    if tiene_control and tiene_estructura:
        return YA_INSTALADO, ("Ya es un dispositivo prdrive: se reinstala el "
                              "código encima y se conserva lo demás.")

    if not contenido:
        return VACIO, "Está vacío."

    nombres = ", ".join(sorted(p.name for p in contenido)[:6])
    return AJENO, (
        f"Aquí hay {len(contenido)} elemento(s) que no son de un prdrive "
        f"({nombres}{'…' if len(contenido) > 6 else ''}). No se borrará nada, "
        f"pero el programa quedaría instalado dentro de este volumen.")


# ---------------------------------------------------------------------------
# El fichero de control
# ---------------------------------------------------------------------------

def control_id(root: Path) -> str | None:
    """El 'id=' de dentro del PRDRIVE, o None si no lleva ninguno."""
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
    """Deja un PRDRIVE con id dentro de `.prdrive/` y devuelve ese id.

    `renew=True` fuerza un id nuevo aunque ya hubiera uno. Hace falta al reutilizar
    un volumen que ya fue de otro dispositivo: dos dispositivos con el mismo id no
    se pueden distinguir, y un vigilante atado a ese id lanzaría con el
    equivocado. Actualizar es justo el caso contrario y va con `renew=False`:
    es el MISMO dispositivo, y cambiarle el id dejaría colgado al vigilante que
    ya estuviera apuntándole."""
    path = Path(root) / CONTROL_FILE
    actual = control_id(root)
    if actual and not renew:
        return actual
    nuevo = uuid.uuid4().hex
    try:
        # En la instalación el directorio ya está (lo crea `deploy_code`), pero
        # penwatch también adopta unidades, y ahí puede no estarlo.
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(CONTROL_TEMPLATE.format(device_id=nuevo), encoding="utf-8")
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


def verify_device(root: Path, esperadas: list[str] | None = None,
                  key_name: str | None = None) -> list[Check]:
    """La lista de comprobación del último paso: ¿este dispositivo va a funcionar?

    Mira lo que de verdad hace falta para que `runsync.py` arranque en cualquier
    equipo: el lanzador, el binario de rclone de esta arquitectura, la conexión,
    el config, y que el config se pueda leer. Lo que falte aquí es lo que
    fallaría luego sin que se entienda por qué.

    `key_name` llega del perfil porque el nombre del fichero de clave lo elige el
    usuario. Sin clave —un backend con contraseña o con agente— no se comprueba
    ninguna: no falta nada."""
    root = Path(root)
    app = root / APP_SUBDIR
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

    device_id = control_id(root)
    checks.append(Check("Fichero de control", bool(device_id),
                        f"id {device_id[:8]}…" if device_id else
                        f"falta {root / CONTROL_FILE} o no tiene id propio"))

    mirar("Lanzador (runsync.pyw)", root / "runsync.pyw")
    mirar("Interfaz (runsync.py)", app / "runsync.py")
    mirar("Motor (sync.py)", app / "sync.py")
    mirar(f"rclone ({bin_subdir()})", app / "bin" / bin_subdir() / exe_name(),
          "sin el binario de esta arquitectura no sincroniza en este equipo")
    if key_name:
        mirar("Clave del remoto", app / "keys" / key_name)
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
    """Python y Tkinter EN ESTE EQUIPO. No es del dispositivo, pero sin ellos el dispositivo no
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
