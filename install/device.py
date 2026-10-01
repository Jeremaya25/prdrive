#!/usr/bin/env python3
"""Qué unidades hay, cuál va a ser el dispositivo y si al final quedó bien.

Tres cosas, las tres de seguridad más que de comodidad:
- `list_volumes()` NO filtra por «extraíble». Muchos pendrives (y casi todos
  los SSD por USB) se declaran `Fixed`, así que filtrar por ahí hace que el
  dispositivo del usuario no aparezca. Se listan todos y se marca cuáles lo
  parecen; decide el usuario con los datos delante. Solo se descartan las
  unidades de red (`TIPOS_OCULTOS`): ninguna puede ser un dispositivo y
  `GetLogicalDrives` sí las devuelve.
- `install_target()` mira qué hay en el destino ANTES de escribir. Instalar no
  borra nada (es una copia local), pero seguir adelante sobre la carpeta
  equivocada deja el programa desperdigado entre los datos de otro, así que se
  pide confirmación antes de tocarla.
- `ensure_control_file()` pone el `id=` del fichero PRDRIVE, que distingue este
  dispositivo de cualquier otro: sin id propio, un vigilante configurado para
  uno concreto se confundiría con el de al lado.

`CONTROL_FILE` y `CONTROL_TEMPLATE` están copiados de `penwatch.py` a propósito
y no importados: penwatch se copia al equipo del usuario y tiene que funcionar
con el dispositivo desconectado, así que no puede depender de este paquete, y
este paquete acaba dentro de un `.exe` donde importar un script hermano es un
lío. Un test comprueba que las dos copias no se separan.
"""

from __future__ import annotations

import os
import shutil
import tomllib
import uuid
from dataclasses import dataclass, replace
from pathlib import Path

from common import autorun, model, vestibulo

from . import DEVICE_LABEL, IS_WIN, InstallError
from .rclone_bin import bin_subdir, exe_name

CONTAINER_SUFFIX = ".hc"
"""Extensión del contenedor VeraCrypt."""
APP_SUBDIR = ".prdrive"
"""Carpeta del programa en la raíz del dispositivo."""
STRUCT_MARKER = Path(APP_SUBDIR) / "runsync.py"
"""Fichero cuya presencia dice que el programa está instalado."""

CONTROL_FILE = Path(APP_SUBDIR) / DEVICE_LABEL
"""Fichero de control, DENTRO de la carpeta del programa y no en la raíz del volumen.

Identifica la unidad se monte donde se monte, y para eso da igual dónde esté
mientras la ruta sea relativa a la raíz: en `.prdrive/` cumple lo mismo sin
dejar un fichero suelto entre los datos del usuario y no se puede borrar sin
borrar también el programa.
"""
CONTROL_TEMPLATE = """\
# PRDRIVE — fichero de control del dispositivo. NO LO BORRES.
# Es lo que permite reconocer esta unidad se monte donde se monte (F:, /media/...).
# Lo usa .prdrive/penwatch.py para lanzar la sincronización al conectarla.
id={device_id}
"""
"""Contenido del fichero de control; `{device_id}` es el id del dispositivo."""

RUIDO = {
    "system volume information", "$recycle.bin", "recycler", "lost+found",
    ".ds_store", ".spotlight-v100", ".fseventsd", ".trashes", "desktop.ini",
    "autorun.inf", "prdrive.hc", ".prdrive", "veracrypt",
    "runsync.pyw", "runsync.bat", "runsync.sh", "runsync.ico",
    *(nombre.lower() for nombre in vestibulo.TODOS),
}
"""Lo que el sistema deja en cualquier volumen, o lo que ponemos nosotros.

Y no cuenta como «aquí hay cosas de otro».

Se compara con `p.name.lower()`, así que va todo en minúsculas. Olvidar aquí
algo que escribe el instalador hace que un dispositivo recién hecho se
clasifique como AJENO la siguiente vez. El vestíbulo de un dispositivo
VeraCrypt (`common/vestibulo.py`) sale de sus constantes y no se teclea: son
seis nombres y crecerán.
"""


def es_ruido(nombre: str) -> bool:
    """Indica si ese nombre no cuenta como «aquí hay cosas de otro».

    Además de `RUIDO` cuenta el icono de la unidad (`common/autorun.py`), cuyo
    nombre cambia con el dibujo y no cabe en un conjunto, y lo que deja a
    medias un intercambio del VeraCrypt de viaje (`.VeraCrypt.viejo-<pid>`,
    `vestibulo.es_resto_traveler()`), que lleva el pid en el nombre.
    """
    return (nombre.lower() in RUIDO or autorun.es_icono(nombre)
            or vestibulo.es_resto_traveler(nombre))


# Puntos de montaje donde los escritorios de Linux y macOS cuelgan los
# extraíbles.
POSIX_BASES = ("/media", "/run/media", "/mnt", "/Volumes")


@dataclass(frozen=True)
class Volume:
    """Una unidad candidata, con todo lo que se sabe de ella sin abrirla.

    Args:
        root: Su raíz.
        label: Su etiqueta.
        filesystem: Su sistema de ficheros.
        drive_type: `Removable`, `Fixed`…; vacío en POSIX.
        size: Tamaño total en bytes.
        free: Bytes libres.
        is_system: Si es la unidad del sistema.
    """
    root: Path
    label: str = ""
    filesystem: str = ""
    drive_type: str = ""
    size: int = 0
    free: int = 0
    is_system: bool = False

    @property
    def removable(self) -> bool:
        """Indica si el sistema la declara extraíble."""
        return self.drive_type.lower() == "removable"

    def _exists(self, rel) -> bool:
        """Indica si existe esa ruta dentro del volumen.

        Un `OSError` cuenta como que no.

        Un volumen bloqueado por BitLocker responde con error de permisos y no
        con «no existe»: cualquier `OSError` significa «ahora mismo no se
        sabe».
        """
        try:
            return (self.root / rel).exists()
        except OSError:
            return False

    @property
    def has_control(self) -> bool:
        """Indica si tiene el fichero de control."""
        return self._exists(CONTROL_FILE)

    @property
    def has_container(self) -> bool:
        """Indica si tiene un contenedor VeraCrypt."""
        return self._exists(DEVICE_LABEL + CONTAINER_SUFFIX)

    @property
    def has_structure(self) -> bool:
        """Indica si tiene el programa instalado."""
        return self._exists(STRUCT_MARKER)

    @property
    def nota(self) -> str:
        """Devuelve lo que hay que saber de un vistazo al elegir destino."""
        partes = []
        if self.is_system:
            partes.append("¡UNIDAD DEL SISTEMA!")
        if self.has_container:
            partes.append("contenedor VeraCrypt")
        if self.has_control:
            # Con el control dentro de `.prdrive/`, que falte la estructura ya
            # no es «no hay carpeta»: la carpeta está y lo que falta es el
            # programa (una instalación a medias).
            partes.append("ya es un prdrive" if self.has_structure
                          else f"tiene {CONTROL_FILE} pero le falta el programa")
        if not partes and not self.removable:
            partes.append("no se declara extraíble")
        return "; ".join(partes)

    @property
    def size_gb(self) -> float:
        """Devuelve el tamaño en GiB, con un decimal."""
        return round(self.size / 1024 ** 3, 1)

    @property
    def free_gb(self) -> float:
        """Devuelve el espacio libre en GiB, con un decimal."""
        return round(self.free / 1024 ** 3, 1)


DRIVE_TYPES = {
    2: "Removable",
    3: "Fixed",
    4: "Network",
    5: "CD-ROM",
    6: "RAM disk",
}
"""Tipos de `GetDriveTypeW` con los mismos nombres que daba `Get-Volume`.

Son los que enseña la tabla del asistente y los que mira `Volume.removable`:
traducirlos a otra cosa sería cambiar la pantalla y la lógica a la vez sin
necesidad.
"""

TIPOS_OCULTOS = ("Network",)
"""Tipos que se enumeran pero NO se ofrecen.

Una unidad de red no puede ser el dispositivo; sin este filtro el selector se
llena de unidades mapeadas que nadie puede elegir.
"""


def make_volume(letra: str, drive_type: str = "", label: str = "",
                filesystem: str = "", size: int = 0, free: int = 0,
                system_drive: str = "") -> Volume:
    """Construye un `Volume` a partir de lo que haya contestado el sistema.

    Es la mitad pura de la enumeración y por eso la que se prueba:
    `_win_volumes()` solo traduce llamadas de kernel32 a estos argumentos,
    igual que `_leer_estado_bitlocker` en `crypto.py` es la parte que los tests
    sustituyen en vez de simular.
    """
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
    """Devuelve las unidades con letra, preguntando a kernel32 en vez de a PowerShell.

    Son cuatro llamadas y ninguna eleva. Se evita PowerShell por dos razones:
    tardaba 3,5 s constantes (contra unos 35 ms de esto) y
    `ui.tk_install._paso_destino` lo llama en el hilo de Tk al dibujar la
    primera pantalla y en cada «Actualizar lista», que es lo que se pulsa tras
    enchufar el pendrive; y un `.exe` sin firmar que corre desde `%TEMP%` y
    lanza PowerShell es la forma que puntúa en un antivirus (ver la nota de
    BitLocker en `crypto.py`).

    Hace dos cosas que `Get-Volume` hacía por su cuenta:
    - Callar el diálogo «No hay ningún disco en la unidad»: un lector de
      tarjetas o un CD vacíos lo sacan en cuanto se les pregunta, ENCIMA del
      asistente. `SetThreadErrorMode` es la versión por hilo de `SetErrorMode`,
      global al proceso, y se restaura al salir para no cambiarle el modo a
      nadie más.
    - Quitar las unidades de red, que `GetLogicalDrives` sí devuelve.
    """
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
                # lista, sin etiqueta: que la letra exista ya es un dato, y
                # esconderla dejaba al usuario sin ver su dispositivo.
                etiqueta.value = sistema.value = ""

            total, libre = c_ulonglong(0), c_ulonglong(0)
            # El segundo hueco es el libre PARA QUIEN PREGUNTA (cuotas); aquí
            # se quiere el total libre.
            if not k32.GetDiskFreeSpaceExW(raiz, None, byref(total), byref(libre)):
                total.value = libre.value = 0

            volumenes.append(make_volume(letra, tipo, etiqueta.value,
                                         sistema.value, total.value, libre.value))
    finally:
        k32.SetThreadErrorMode(anterior, byref(DWORD()))
    return volumenes


def _posix_volumes() -> list[Volume]:
    """Devuelve lo que haya montado bajo los sitios habituales de los extraíbles.

    Se miran DOS niveles porque los escritorios no se ponen de acuerdo:
    `/media/<etiqueta>` y `/media/<usuario>/<etiqueta>` son igual de comunes, y
    quedarse en el primero deja fuera medio Linux.
    """
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

    Un cero aquí merece una segunda opinión antes de enseñárselo a nadie: se
    vio una vez `Get-Volume` devolver `Size` y `SizeRemaining` a cero con el
    volumen montado y legible (un `disk_usage` sobre esa misma ruta contestaba
    bien) y quien ve «0 GB» descarta esa unidad. No ha vuelto a reproducirse,
    así que no se finge saber la causa. Se hace aquí y no en `make_volume` para
    que este siga siendo una traducción pura de lo que conteste el sistema.
    """
    if vol.size:
        return vol
    try:
        uso = shutil.disk_usage(str(vol.root))
    except OSError:
        return vol                     # bloqueado, sin medio dentro, o desaparecido
    return replace(vol, size=uso.total, free=uso.free)


def list_volumes() -> list[Volume]:
    """Devuelve todas las unidades candidatas, sin filtrar por «extraíble».

    Los pendrives que se declaran `Fixed` son la norma y no la excepción. Salen
    ordenadas poniendo delante lo que más se parece a un dispositivo.
    """
    volumenes = [_con_tamano(v) for v in
                 (_win_volumes() if IS_WIN else _posix_volumes())]
    return sorted(volumenes, key=lambda v: (v.is_system, not v.has_control,
                                            not v.has_container, not v.removable,
                                            str(v.root)))


def raiz_del_volumen(ruta: Path | str) -> Path:
    r"""Devuelve la raíz del volumen que guarda `ruta`, exista ya o no.

    Por ejemplo, `C:\` para `C:\Users\x\PRDRIVE-cifrado`, o el punto de montaje
    en POSIX. Lo que se pregunta al sistema de ficheros (cuál es, si admite
    dispersos) se pregunta ahí: `GetVolumeInformationW` solo acepta la raíz de
    un volumen y con una carpeta falla, y la raíz cifrada de un equipo vive en
    una carpeta. Se usa `GetVolumePathNameW` y no la letra de la ruta porque un
    volumen puede estar montado en una carpeta de otro.
    """
    ruta = Path(os.path.abspath(str(ruta)))
    if IS_WIN:
        import ctypes
        buf = ctypes.create_unicode_buffer(261)         # MAX_PATH + 1
        try:
            if ctypes.windll.kernel32.GetVolumePathNameW(ctypes.c_wchar_p(str(ruta)),
                                                         buf, 261):
                return Path(buf.value)
        except OSError:
            pass
        return Path(ruta.anchor or str(ruta))
    while not os.path.ismount(ruta) and ruta != ruta.parent:
        ruta = ruta.parent
    return ruta


def volume_for(root: Path) -> Volume:
    """Devuelve el `Volume` de una ruta escrita a mano.

    Con lo que se pueda averiguar.
    """
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


VACIO = "vacio"
"""Resultado de `install_target`: no hay nada."""
YA_INSTALADO = "instalado"
"""Resultado de `install_target`: ya es un dispositivo prdrive."""
AJENO = "ajeno"
"""Resultado de `install_target`: hay contenido que no es de un prdrive."""


def install_target(root: Path) -> tuple[str, str]:
    """Dice qué hay en el destino, para decidir si se puede instalar sin preguntar.

    Instalar es copiar, así que `ajeno` no significa «esto se borraría» sino
    que el volumen es de otra cosa y dejar ahí el programa y sus lanzadores
    probablemente no es lo que se quería. Quien llama pide confirmación, pero
    no es la destructiva que hacía falta con la siembra.

    Returns:
        `(vacio | instalado | ajeno, explicación)`.

    Raises:
        InstallError: Si no se puede leer el volumen (¿bloqueado?).
    """
    root = Path(root)
    try:
        if not root.exists():
            return VACIO, "La carpeta no existe todavía; se creará."
        contenido = [p for p in root.iterdir() if not es_ruido(p.name)]
    except OSError as e:
        raise InstallError(
            f"No puedo leer {root}: {e}\n"
            "¿Está el volumen desbloqueado (BitLocker/VeraCrypt)?") from e

    # Reconocer el dispositivo va ANTES de mirar si hay algo dentro, y el orden
    # no es cosmético: `.prdrive` está en `RUIDO` (tiene que estarlo, o el
    # dispositivo recién hecho se leería como ajeno la vez siguiente), así que
    # un volumen recién provisionado, con el programa y aún sin datos del
    # usuario, no deja NINGÚN contenido a la vista y se leería como vacío, y el
    # asistente no ofrecería el recorrido corto en el dispositivo más nuevo.
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


def control_id(root: Path) -> str | None:
    """Devuelve el `id=` del PRDRIVE, o `None` si no lleva ninguno."""
    try:
        texto = (Path(root) / CONTROL_FILE).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for linea in texto.splitlines():
        linea = linea.strip()
        if linea.lower().startswith("id="):
            return linea[3:].strip() or None
    return None


def ensure_control_file(root: Path, renew: bool = False,
                        tipo: str = model.TIPO_UNIDAD) -> str:
    """Deja un PRDRIVE con id dentro de `.prdrive/` y devuelve ese id.

    `renew=True` fuerza un id nuevo aunque ya hubiera uno. Hace falta al
    reutilizar un volumen que ya fue de otro dispositivo: dos con el mismo id
    no se pueden distinguir y un vigilante atado a ese id lanzaría con el
    equivocado. Actualizar es el caso contrario y va con `renew=False`: es el
    MISMO dispositivo, y cambiarle el id dejaría colgado al vigilante que ya le
    apuntara.

    Args:
        renew: Si se fuerza un id nuevo.
        tipo: Qué raíz es (`model.TIPO_EQUIPO` para la carpeta de un equipo).
            Va en su propia línea, que un penwatch viejo no lee; cambiarlo
            conserva el id.

    Raises:
        InstallError: Si no se puede escribir el fichero.
    """
    path = Path(root) / CONTROL_FILE
    actual = control_id(root)
    if actual and not renew and control_tipo(root) == tipo:
        return actual
    nuevo = actual if actual and not renew else uuid.uuid4().hex
    texto = CONTROL_TEMPLATE.format(device_id=nuevo)
    if tipo != model.TIPO_UNIDAD:
        texto += f"tipo={tipo}\n"
    try:
        # En la instalación el directorio ya está (lo crea `deploy_code`), pero
        # penwatch también adopta unidades y ahí puede no estarlo.
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(texto, encoding="utf-8")
    except OSError as e:
        raise InstallError(f"No he podido escribir {path}: {e}") from e
    return nuevo


def control_tipo(root: Path) -> str:
    """Devuelve el `tipo=` del PRDRIVE.

    Es `model.TIPO_EQUIPO` en la raíz de un equipo y una unidad si no lo dice,
    que es como están todas las de antes.
    """
    return model.tipo_raiz(Path(root) / APP_SUBDIR)


@dataclass(frozen=True)
class Check:
    """Una comprobación de la verificación final.

    Args:
        etiqueta: Qué se comprueba.
        ok: Si está bien.
        detalle: Lo que se ha visto.
    """
    etiqueta: str
    ok: bool
    detalle: str


def verify_device(root: Path, esperadas: list[str] | None = None,
                  key_name: str | None = None) -> list[Check]:
    """Devuelve la lista de comprobación del último paso.

    ¿va a funcionar este dispositivo?

    Mira lo que de verdad hace falta para que `runsync.py` arranque en
    cualquier equipo: el lanzador, el binario de rclone de esta arquitectura,
    la conexión, el config y que el config se pueda leer. Lo que falte aquí es
    lo que fallaría luego sin que se entienda por qué.

    Args:
        esperadas: Parejas que tienen que estar en el config.
        key_name: Nombre del fichero de clave, que lo elige el usuario; sin
            clave (un backend con contraseña o con agente) no se comprueba
            ninguna.
    """
    root = Path(root)
    app = root / APP_SUBDIR
    checks: list[Check] = []

    def mirar(etiqueta: str, ruta: Path, pista: str = "") -> bool:
        """Anota una comprobación de existencia y devuelve si existe."""
        try:
            existe = ruta.exists()
        except OSError as e:
            checks.append(Check(etiqueta, False, f"no se puede leer: {e}"))
            return False
        checks.append(Check(etiqueta, existe,
                            str(ruta) if existe else (pista or f"falta {ruta}")))
        return existe

    device_id = control_id(root)
    # La raíz de un equipo no lleva lanzadores ni Python propio: la abre y
    # sincroniza el agente del equipo con el suyo (`install/raiz_equipo.py`).
    equipo = control_tipo(root) == model.TIPO_EQUIPO
    checks.append(Check("Fichero de control", bool(device_id),
                        (f"id {device_id[:8]}…" + (", raíz del equipo" if equipo else ""))
                        if device_id else
                        f"falta {root / CONTROL_FILE} o no tiene id propio"))

    # El lanzador de ESTE sistema; el `.pyw` ya no: la instalación completa no
    # lo lleva.
    lanzador = "runsync.bat" if IS_WIN else "runsync.sh"
    if not equipo:
        mirar(f"Lanzador ({lanzador})", root / lanzador)
    mirar("Interfaz (runsync.py)", app / "runsync.py")
    mirar("Motor (sync.py)", app / "sync.py")
    mirar(f"rclone ({bin_subdir()})", app / "bin" / bin_subdir() / exe_name(),
          "sin el binario de esta arquitectura no sincroniza en este equipo")
    if key_name:
        mirar("Clave del remoto", app / "keys" / key_name)
    mirar("rclone.conf", app / "rclone.conf")

    config = app / "sync_config.toml"
    if mirar("sync_config.toml", config):
        checks.append(_check_config(config, esperadas or [], equipo))

    if not equipo:
        checks.append(check_python(root))
    return checks


def _check_config(config: Path, esperadas: list[str], equipo: bool = False) -> Check:
    """Comprueba que el config se lee y trae las parejas esperadas."""
    try:
        with config.open("rb") as f:
            cfg = model.parse_config(tomllib.load(f), equipo=equipo)
    except (OSError, ValueError, model.ConfigError) as e:
        return Check("El config se lee", False, str(e))
    faltan = [n for n in esperadas if n not in cfg.names]
    if faltan:
        return Check("El config se lee", False,
                     f"no están las parejas elegidas: {', '.join(faltan)}")
    return Check("El config se lee", True, f"{len(cfg.pairs)} pareja(s): "
                 + ", ".join(cfg.names))


def check_python(root: Path | None = None) -> Check:
    """Devuelve con qué Python arrancará el dispositivo EN ESTE EQUIPO.

    Con `root`, lo primero es el del propio dispositivo (el que usará
    `runsync.bat`) y entonces no hace falta ninguno instalado; si no lleva uno
    que sirva aquí cuenta el del equipo, con Tkinter o sin él. Sin `root` (el
    paso de comprobaciones, antes de que exista el dispositivo) solo se mira el
    del equipo, y que falte no es grave: la instalación completa lleva el suyo.
    """
    from . import platforms, python_command
    if root is not None:
        anfitrion = platforms.host()
        propio = platforms.device_interpreter(root, anfitrion)
        if propio is not None:
            return Check("Python para este equipo", True,
                         f"el del dispositivo: {propio}")
        cmd = python_command()
        if not cmd:
            nombre = anfitrion.nombre if anfitrion else "este sistema"
            return Check("Python para este equipo", False,
                         f"el dispositivo no lleva Python para {nombre} y aquí no "
                         f"hay ninguno instalado: vuelve a ejecutar el instalador y "
                         f"pulsa «Añadir plataformas…», o instala Python 3.11+")
        return Check("Python para este equipo", True,
                     f"el del equipo: {' '.join(cmd)} (el dispositivo no lleva "
                     f"uno propio para aquí)")

    cmd = python_command()
    if not cmd:
        return Check("Python en este equipo", False,
                     "no hay ninguno: hará falta la instalación completa, que "
                     "lleva el suyo")
    try:
        import tkinter  # noqa: F401
        return Check("Python en este equipo", True, f"{' '.join(cmd)} (con Tkinter)")
    except Exception:
        return Check("Python en este equipo", True,
                     f"{' '.join(cmd)}, pero SIN Tkinter: saldrá el menú de consola")
