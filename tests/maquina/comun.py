#!/usr/bin/env python3
"""Lo que comparten las pruebas en máquina real (`tests/maquina/f*.py`).

Cada prueba es una fila de `docs/superpowers/pruebas/2026-09-25-equipo-pendiente-en-real.md`
hecha en una máquina de usar y tirar de GitHub Actions (`.github/workflows/maquina-real.yml`),
con permisos de administrador: discos virtuales de verdad (VHD en Windows, loop en
Linux) con su sistema de ficheros de verdad, VeraCrypt instalado, carpetas
compartidas por red. No es un test de `run_all.py`: toca el sistema.

Una prueba es un módulo con `CODIGO` (`"F14"`), `SISTEMA` (`"W"` o `"L"`),
`QUE` (una línea) y `probar(p: Prueba)`. Lo que no se puede hacer en esta
máquina lanza `Saltada` con el motivo; lo demás son comprobaciones (`p.ver()`)
y notas (`p.nota()`). `correr.py` las lanza y resume.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

IS_WIN = os.name == "nt"
SISTEMA = "W" if IS_WIN else "L"
TMP = Path(tempfile.gettempdir()) / "prdrive-maquina"


class Saltada(Exception):
    """La prueba no se puede hacer en esta máquina; el mensaje dice por qué."""


class Prueba:
    """Las comprobaciones y notas de una prueba.

    Args:
        codigo: El código de la fila (`F14`).

    Attributes:
        bien: Cuántas comprobaciones han salido bien.
        mal: Las que han fallado, por su texto.
        notas: Lo que la prueba ha averiguado y hay que apuntar.
    """

    def __init__(self, codigo: str) -> None:
        """Empieza sin comprobaciones."""
        self.codigo = codigo
        self.bien = 0
        self.mal: list[str] = []
        self.notas: list[str] = []

    def ver(self, que: str, obtenido, esperado) -> bool:
        """Comprueba que `obtenido` sea `esperado`, lo cuenta y lo dice."""
        if obtenido == esperado:
            self.bien += 1
            print(f"  OK     {que}", flush=True)
            return True
        self.mal.append(que)
        print(f"  FALLO  {que}\n           obtenido: {obtenido!r}\n"
              f"           esperado: {esperado!r}", flush=True)
        return False

    def nota(self, texto: str) -> None:
        """Apunta algo averiguado (va al resumen)."""
        self.notas.append(texto)
        print(f"  NOTA   {texto}", flush=True)


def ejecutar(cmd: list[str] | str, timeout: float = 180, entrada: str | None = None,
             shell: bool = False, callado: bool = False) -> subprocess.CompletedProcess:
    """Ejecuta una orden, enseña su salida sangrada y la devuelve; no lanza si falla.

    Con `callado`, no enseña nada (una comprobación que se repite).
    """
    try:
        r = subprocess.run(cmd, input=entrada, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout, shell=shell)
    except subprocess.TimeoutExpired as e:
        r = subprocess.CompletedProcess(cmd, 124, e.stdout or "", f"timeout: {e}")
    except OSError as e:
        r = subprocess.CompletedProcess(cmd, 127, "", str(e))
    if callado:
        return r
    salida = ((r.stdout or "") + (r.stderr or "")).strip().splitlines()
    print(f"    $ {cmd if isinstance(cmd, str) else ' '.join(map(str, cmd))} -> {r.returncode}",
          flush=True)
    for linea in salida[-15:]:
        print(f"    | {linea}", flush=True)
    return r


def esperar(condicion, segundos: float, cada: float = 0.1) -> bool:
    """Espera a que se cumpla algo; devuelve si se cumplió."""
    fin = time.monotonic() + segundos
    while time.monotonic() < fin:
        if condicion():
            return True
        time.sleep(cada)
    return bool(condicion())


def carpeta(nombre: str) -> Path:
    """Una carpeta de trabajo vacía de esta prueba."""
    ruta = TMP / nombre
    shutil.rmtree(ruta, ignore_errors=True)
    ruta.mkdir(parents=True)
    return ruta


def arbol(raiz: Path, carpetas: int, ficheros: int = 0) -> Path:
    """Crea un árbol de `carpetas` subcarpetas (y `ficheros` en la primera) bajo `raiz`."""
    raiz.mkdir(parents=True, exist_ok=True)
    for i in range(carpetas):
        (raiz / f"c{i // 100}" / f"d{i}").mkdir(parents=True, exist_ok=True)
    for i in range(ficheros):
        (raiz / f"f{i}.txt").write_text("x", encoding="utf-8")
    return raiz


# ---------------------------------------------------------------------------
# Linux
# ---------------------------------------------------------------------------
_apt_al_dia = False


def apt(*paquetes: str) -> None:
    """Instala paquetes de Ubuntu si faltan.

    Raises:
        Saltada: Si no se pueden instalar.
    """
    global _apt_al_dia
    faltan = [p for p in paquetes
              if ejecutar(["dpkg", "-s", p], timeout=30, callado=True).returncode != 0]
    if not faltan:
        return
    if not _apt_al_dia:
        ejecutar(["apt-get", "update", "-qq"], timeout=300)
        _apt_al_dia = True
    r = ejecutar(["apt-get", "install", "-y", "-qq", "--no-install-recommends", *faltan],
                 timeout=600)
    if r.returncode != 0:
        raise Saltada(f"no se han podido instalar {', '.join(faltan)}")


MKFS = {"vfat": ["mkfs.vfat", "-F", "32"], "exfat": ["mkfs.exfat"], "ext4": ["mkfs.ext4", "-q"]}
"""Cómo se formatea cada sistema de ficheros de prueba en Linux."""


@contextlib.contextmanager
def volumen_linux(tipo: str, mb: int = 64):
    """Monta un volumen de ese sistema de ficheros en un dispositivo loop y lo da.

    Se desmonta al salir aunque la prueba ya lo haya desmontado.

    Yields:
        El punto de montaje.

    Raises:
        Saltada: Si no se puede formatear o montar (falta el módulo del núcleo).
    """
    apt("dosfstools", "exfatprogs")
    base = carpeta(f"vol-{tipo}")
    imagen, punto = base / "disco.img", base / "punto"
    punto.mkdir()
    with imagen.open("wb") as f:
        f.truncate(mb * 1024 * 1024)
    if ejecutar([*MKFS[tipo], str(imagen)], timeout=120).returncode != 0:
        raise Saltada(f"no se puede formatear en {tipo}")
    if ejecutar(["mount", "-o", "loop", "-t", tipo, str(imagen), str(punto)],
                timeout=60).returncode != 0:
        raise Saltada(f"este núcleo no monta {tipo}")
    try:
        yield punto
    finally:
        ejecutar(["umount", "-l", str(punto)], timeout=60)


# ---------------------------------------------------------------------------
# Windows
# ---------------------------------------------------------------------------
def diskpart(lineas: list[str]) -> int:
    """Ejecuta un guion de diskpart y devuelve su código de salida."""
    guion = TMP / "diskpart.txt"
    TMP.mkdir(parents=True, exist_ok=True)
    guion.write_text("\n".join(lineas) + "\n", encoding="ascii")
    return ejecutar(["diskpart", "/s", str(guion)], timeout=300).returncode


def soltar_vhd(fichero: Path) -> None:
    """Desconecta un disco virtual, si sigue conectado."""
    diskpart([f'select vdisk file="{fichero}"', "detach vdisk noerr"])


@contextlib.contextmanager
def volumen_windows(tipo: str, letra: str, mb: int = 128):
    """Conecta un disco virtual (VHD) con un volumen de ese sistema de ficheros en esa letra.

    Es un disco de verdad para Windows: su controlador de NTFS, exFAT o FAT32,
    sus avisos de extracción. Se desconecta al salir.

    Yields:
        La raíz del volumen (`R:\\`).

    Raises:
        Saltada: Si diskpart no lo crea.
    """
    fichero = carpeta(f"vhd-{tipo}") / f"{tipo}.vhdx"
    rc = diskpart([f'create vdisk file="{fichero}" maximum={mb} type=expandable',
                   f'select vdisk file="{fichero}"', "attach vdisk",
                   "attributes disk clear readonly noerr", "online disk noerr",
                   "convert mbr noerr", "create partition primary",
                   f"format quick fs={tipo} label=PRUEBA", f"assign letter={letra}"])
    raiz = Path(f"{letra}:\\")
    if rc != 0 or not esperar(raiz.exists, 30):
        soltar_vhd(fichero)
        raise Saltada(f"diskpart no ha creado el volumen {tipo} (rc={rc})")
    try:
        yield raiz
    finally:
        soltar_vhd(fichero)


GUID_IO_VOLUME_LOCK = "50708874-c9af-11d1-8fef-00a0c9a06d32"
"""El aviso de que alguien bloquea un volumen (`FSCTL_LOCK_VOLUME`), ioevent.h."""


def describir_aviso(lparam: int) -> tuple[int, int | None, str]:
    """Lee el `DEV_BROADCAST_*` de un `WM_DEVICECHANGE`: tipo, handle y GUID del evento."""
    import ctypes

    class Handle(ctypes.Structure):
        """`DEV_BROADCAST_HANDLE` de dbt.h."""
        _fields_ = [("size", ctypes.c_uint32), ("tipo", ctypes.c_uint32),
                    ("reservado", ctypes.c_uint32), ("handle", ctypes.c_void_p),
                    ("aviso", ctypes.c_void_p), ("guid", ctypes.c_ubyte * 16)]

    if not lparam:
        return 0, None, ""
    tipo = ctypes.cast(lparam, ctypes.POINTER(ctypes.c_uint32 * 2)).contents[1]
    if tipo != 6:                           # DBT_DEVTYP_HANDLE
        return tipo, None, ""
    h = ctypes.cast(lparam, ctypes.POINTER(Handle)).contents
    g = bytes(h.guid)
    guid = (f"{int.from_bytes(g[0:4], 'little'):08x}-{int.from_bytes(g[4:6], 'little'):04x}-"
            f"{int.from_bytes(g[6:8], 'little'):04x}-{g[8:10].hex()}-{g[10:16].hex()}")
    return tipo, h.handle, guid


@contextlib.contextmanager
def bandeja_windows():
    """Pone la bandeja de verdad del agente (su ventana y su bucle) y apunta lo que le llega.

    Yields:
        `(bandeja, avisos)`: la `Bandeja` arrancada y la lista de cada
        `WM_DEVICECHANGE` que recibe, como `(wparam, tipo, handle, guid)`.

    Raises:
        Saltada: Si no hay ventana.
    """
    from ui import bandeja_windows as bw
    from ui import icons
    iconos = carpeta("iconos")
    icons.write_bandeja(iconos)
    b = bw.Bandeja(iconos, lambda p: None, lambda: None)
    avisos: list[tuple] = []
    original = b._mensaje

    def apuntar(hwnd, msg, wparam, lparam):
        """Apunta el aviso de dispositivo y deja que la bandeja haga lo suyo."""
        if msg == bw.WM_DEVICECHANGE:
            try:
                avisos.append((wparam, *describir_aviso(lparam)))
            except Exception as e:                      # noqa: BLE001
                avisos.append((wparam, -1, None, str(e)))
        return original(hwnd, msg, wparam, lparam)

    b._mensaje = apuntar
    if not b.arrancar():
        raise Saltada("no hay ventana para la bandeja")
    try:
        yield b, avisos
    finally:
        b.cerrar()


# ---------------------------------------------------------------------------
# Los avisos de un motor de `common/avisos_carpeta.py`
# ---------------------------------------------------------------------------
def avisos(motor, segundos: float = 5.0) -> dict:
    """Espera a que el motor avise de algo y devuelve los tipos, por pareja.

    En Windows los avisos llegan por un hilo, un poco después: se espera al
    primero y medio segundo más para juntar la ráfaga. Si llegan varios de una
    pareja, se queda el más grave.
    """
    from common import avisos_carpeta as ac
    juntos: dict = {}
    fin, hasta = time.monotonic() + segundos, None
    while time.monotonic() < (hasta or fin):
        for k, a in motor.recoger().items():
            antes = juntos.get(k)
            if antes is None or ac.GRAVEDAD[a.tipo] > ac.GRAVEDAD[antes]:
                juntos[k] = a.tipo
        if juntos and hasta is None:
            hasta = time.monotonic() + 0.5
        time.sleep(0.05)
    return juntos


def asentar(motor, segundos: float = 30.0) -> None:
    """Tira avisos hasta que pasa un segundo entero sin ninguno (tras una copia grande)."""
    fin = time.monotonic() + segundos
    while time.monotonic() < fin:
        time.sleep(1.0)
        if not motor.recoger():
            return


def quieto(motor, segundos: float = 1.5) -> dict:
    """Espera sin tocar nada y devuelve lo que haya avisado (debería ser nada)."""
    time.sleep(segundos)
    return {k: a.tipo for k, a in motor.recoger().items()}
