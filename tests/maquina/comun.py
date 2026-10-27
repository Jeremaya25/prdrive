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
import itertools
import os
import re
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
TMP = Path(tempfile.gettempdir()).resolve() / "prdrive-maquina"
"""La carpeta de trabajo, con su nombre largo.

Con el corto de Windows (`C:\\Users\\NOMBRE~1\\…`) diskpart conecta un disco
virtual pero al soltarlo dice que «ya está oculto» y lo deja conectado.
"""


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
        saltados: Los casos que no se han podido hacer en esta máquina
            (`por_cada()`): con alguno, el resultado es parcial.
    """

    def __init__(self, codigo: str) -> None:
        """Empieza sin comprobaciones."""
        self.codigo = codigo
        self.bien = 0
        self.mal: list[str] = []
        self.notas: list[str] = []
        self.saltados: list[str] = []

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


_carpetas = itertools.count(1)


def carpeta(nombre: str) -> Path:
    """Una carpeta de trabajo nueva y vacía; cada llamada, otra.

    Nunca la de una llamada anterior: en Windows el fichero de un disco virtual
    recién desconectado puede seguir ocupado un rato.
    """
    ruta = TMP / f"{nombre}-{os.getpid()}-{next(_carpetas)}"
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


def modulo_linux(tipo: str) -> None:
    """Carga el módulo del núcleo de un sistema de ficheros; si no está, lo instala.

    El núcleo de las máquinas de GitHub deja algunos (exFAT) en
    `linux-modules-extra-<versión>`.

    Raises:
        Saltada: Si no se puede cargar.
    """
    def cargado() -> bool:
        """Si el núcleo ya lo conoce (`/proc/filesystems`)."""
        lineas = Path("/proc/filesystems").read_text(encoding="ascii").split()
        return tipo in lineas

    if cargado() or ejecutar(["modprobe", tipo], callado=True).returncode == 0:
        return
    apt(f"linux-modules-extra-{os.uname().release}")
    if ejecutar(["modprobe", tipo], callado=True).returncode != 0:
        raise Saltada(f"este núcleo no tiene {tipo}")


def por_cada(p: Prueba, casos, probar_uno) -> None:
    """Prueba cada caso (un sistema de ficheros…); el que no se puede hacer se apunta y se sigue.

    Raises:
        Saltada: Si no se ha podido hacer ninguno.
    """
    saltados = []
    for caso in casos:
        try:
            probar_uno(caso)
        except Saltada as e:
            saltados.append(f"{caso}: {e}")
            print(f"  SALTADO {caso}: {e}", flush=True)
    p.saltados.extend(saltados)
    if len(saltados) == len(casos):
        raise Saltada("; ".join(saltados))


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
    modulo_linux(tipo)
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


_letras_usadas: set[str] = set()
vhd_de: dict[str, Path] = {}
"""El fichero `.vhdx` de cada letra que dio `volumen_windows()`, para desconectarlo y volver a conectarlo."""


def es_administrador() -> bool:
    """Indica si este proceso corre elevado (lo que piden diskpart y el VeraCrypt Portable)."""
    import ctypes
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def _de_red(letra: str) -> bool:
    """Indica si la persona tiene esa letra para una unidad de red (`HKCU\\Network`).

    Una sesión elevada no la ve montada, pero la letra no está libre: VeraCrypt
    la rechaza.
    """
    import winreg
    try:
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CURRENT_USER, f"Network\\{letra}"))
    except OSError:
        return False
    return True


def letra_libre() -> str:
    """Una letra de unidad libre que esta ejecución no ha usado todavía.

    Windows tarda en soltar la letra de un disco virtual recién desconectado:
    nunca se repite una.
    """
    for letra in "RSTUVWXYZQPON":
        if letra not in _letras_usadas and not Path(f"{letra}:\\").exists() \
                and not _de_red(letra):
            _letras_usadas.add(letra)
            return letra
    raise Saltada("no quedan letras de unidad libres")


@contextlib.contextmanager
def volumen_windows(tipo: str, letra: str | None = None, mb: int = 128):
    """Conecta un disco virtual (VHD) con un volumen de ese sistema de ficheros.

    Es un disco de verdad para Windows: su controlador de NTFS, exFAT o FAT32,
    sus avisos de extracción. Se desconecta al salir. Sin `letra`, una libre
    (`letra_libre()`).

    Yields:
        La raíz del volumen (`R:\\`).

    Raises:
        Saltada: Si diskpart no lo crea.
    """
    letra = letra or letra_libre()
    _letras_usadas.add(letra)
    fichero = carpeta(f"vhd-{tipo}") / f"{tipo}.vhdx"
    rc = diskpart([f'create vdisk file="{fichero}" maximum={mb} type=expandable',
                   f'select vdisk file="{fichero}"', "attach vdisk",
                   "attributes disk clear readonly noerr", "online disk noerr",
                   "convert mbr noerr", "create partition primary",
                   f"format quick fs={tipo} label=PRUEBA", f"assign letter={letra}"])
    raiz = Path(f"{letra}:\\")
    vhd_de[letra] = fichero
    if rc != 0 or not esperar(raiz.exists, 30):
        soltar_vhd(fichero)
        raise Saltada(f"diskpart no ha creado el volumen {tipo} (rc={rc})")
    try:
        yield raiz
    finally:
        soltar_vhd(fichero)


def conectar_vhd(fichero: Path, letra: str) -> bool:
    """Vuelve a conectar un disco virtual que se desconectó y devuelve si su letra reaparece.

    Si Windows no le devuelve la letra, se la pone.
    """
    raiz = Path(f"{letra}:\\")
    diskpart([f'select vdisk file="{fichero}"', "attach vdisk"])
    if esperar(raiz.exists, 15):
        return True
    diskpart([f'select vdisk file="{fichero}"', "select partition 1",
              f"assign letter={letra} noerr"])
    return esperar(raiz.exists, 15)


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
        # La clase de su ventana queda registrada con el procedimiento de ESTA
        # bandeja, y la siguiente del mismo proceso recibiría sus mensajes en la
        # vieja: no le llegaría ningún aviso de dispositivo.
        import ctypes
        from ctypes import wintypes
        k32, u32 = ctypes.WinDLL("kernel32"), ctypes.WinDLL("user32")
        k32.GetModuleHandleW.restype = wintypes.HMODULE
        u32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
        u32.UnregisterClassW(b.api.CLASE, k32.GetModuleHandleW(None))


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


# ---------------------------------------------------------------------------
# La hora de lo que baja a una unidad, con el rclone fijado (F3)
# ---------------------------------------------------------------------------
HORA_PEDIDA = 1_700_000_000_543_210_000
"""Una hora con fracción (ns desde 1970): cada sistema de ficheros la guarda distinto."""
_COLORES = re.compile(r"\x1b\[[0-9;]*m")
_SUCESOS = ("File changed", "File is new", "No changes found", "Updated modification",
            "Must run", "ERROR", "CRITICAL", "Bisync successful")
"""Lo que se enseña del log de una pasada de bisync."""


def rclone_fijado() -> Path:
    """El rclone de `common/pins.py`, el que deja `tests/_runtime_ci.py rclone`.

    Raises:
        Saltada: Si no está (`PRDRIVE_RCLONE_CI` sin poner o sin fichero).
    """
    ruta = Path(os.environ.get("PRDRIVE_RCLONE_CI", ""))
    if not ruta.is_file():
        raise Saltada("no hay rclone: `python tests/_runtime_ci.py rclone PLATAFORMA CACHE` "
                      "lo baja y apunta PRDRIVE_RCLONE_CI")
    return ruta


def medir_hora(raiz: Path) -> int:
    """Devuelve cuánto se aparta (ns) la hora que guarda esa unidad de la que se le pidió.

    Positivo es que la redondea hacia arriba, como exFAT y FAT32 en Windows.
    """
    fichero = raiz / "hora.txt"
    fichero.write_text("x", encoding="utf-8")
    os.utime(fichero, ns=(HORA_PEDIDA, HORA_PEDIDA))
    leida = fichero.stat().st_mtime_ns
    fichero.unlink()
    return leida - HORA_PEDIDA


def flags_bisync(con_ventana: bool = True) -> list[str]:
    """Los flags de rclone que prdrive pasa a una pareja bisync sin nada propio.

    Salen de la misma cascada que lee `sync.py` (`model.flags_efectivos()`), no
    de una lista escrita aquí; sin `con_ventana`, los de antes de `modify-window`.
    """
    from common import model
    flags = {f.nombre: f.valor for f in model.flags_efectivos(model.MODES["bisync"], None, None)}
    if not con_ventana:
        flags.pop("modify-window", None)
    return model.flags_to_args(flags)


def pasada_bisync(rclone: Path, local: Path, remoto: Path, trabajo: Path, flags: list[str],
                  resync: bool = False) -> tuple[int, str]:
    """Lanza una pasada de `rclone bisync` y devuelve su código y su log sin colores."""
    orden = [str(rclone), "bisync", str(local), str(remoto), "--workdir", str(trabajo),
             "--config", str(trabajo / "rclone.conf"), *flags] + (["--resync"] if resync else [])
    r = ejecutar(orden, timeout=300, callado=True)
    salida = _COLORES.sub("", (r.stdout or "") + (r.stderr or ""))
    print(f"    $ bisync{' --resync' if resync else ''} -> {r.returncode}", flush=True)
    for linea in salida.splitlines():
        if any(k in linea for k in _SUCESOS):
            print(f"    | {linea.split(': ', 1)[-1].strip()}", flush=True)
    return r.returncode, salida


def repasar_bajada(p: Prueba, etiqueta: str, local: Path, rclone: Path,
                   con_ventana: bool) -> int:
    """Baja por bisync un fichero con hora con fracción, dos veces, y repasa las pasadas siguientes.

    El baseline se hace SIEMPRE sin `modify-window`, como el de un dispositivo
    de antes; las pasadas llevan los flags de ahora (o los de antes, sin
    `con_ventana`). Cada vez: una pasada que baja el fichero, la siguiente y otra
    más. Con `con_ventana` esas dos tienen que decir «No changes found», sin
    ningún «File changed», y la hora del fichero en el remoto no se toca.

    Args:
        local: La carpeta de la unidad que se sincroniza; se crea.

    Returns:
        Cuántas pasadas siguientes a una bajada dieron por cambiado el fichero
        por su hora («File changed: … time …»).
    """
    trabajo, remoto = carpeta("bisync-trabajo"), carpeta("bisync-remoto")
    (trabajo / "rclone.conf").write_text("", encoding="utf-8")
    local.mkdir(parents=True)
    (local / "ancla.txt").write_text("ancla", encoding="utf-8")      # bisync no admite un baseline vacío
    flags = flags_bisync(con_ventana)
    rc, _ = pasada_bisync(rclone, local, remoto, trabajo, flags_bisync(False), resync=True)
    p.ver(f"{etiqueta}: el baseline, sin la ventana (el de una versión de antes)", rc, 0)
    fichero, cambiadas = remoto / "del-remoto.txt", 0
    for vez, texto in enumerate(("uno", "dos!")):
        hora = HORA_PEDIDA + vez * 60_000_000_000
        fichero.write_text(texto, encoding="utf-8")
        os.utime(fichero, ns=(hora, hora))
        rc, _ = pasada_bisync(rclone, local, remoto, trabajo, flags)
        bajado = (local / "del-remoto.txt").read_text(encoding="utf-8") \
            if (local / "del-remoto.txt").exists() else None
        if con_ventana:
            p.ver(f"{etiqueta}: la pasada {vez + 1}.ª baja el fichero", (rc, bajado), (0, texto))
        for sigue in ("siguiente", "otra más"):
            rc, salida = pasada_bisync(rclone, local, remoto, trabajo, flags)
            movio = any("File changed" in lin and "time" in lin for lin in salida.splitlines())
            cambiadas += movio
            if con_ventana:
                p.ver(f"{etiqueta}: la {sigue} a la bajada {vez + 1}.ª no ve cambios",
                      (rc, "No changes found" in salida, "File changed" in salida),
                      (0, True, False))
        remota = fichero.stat().st_mtime_ns
        if con_ventana:
            p.ver(f"{etiqueta}: la hora del fichero en el remoto no se toca", remota, hora)
        elif remota != hora:
            p.nota(f"{etiqueta}: la hora del remoto acabó {(remota - hora) / 1e9:+.3f} s "
                   f"de la que tenía")
    return cambiadas


def probar_hora(p: Prueba, tipo: str, raiz: Path) -> None:
    """Prueba en el volumen `raiz` (de ese `tipo`) que lo que baja del remoto no vuelve a dar cambios.

    Mide cuánto redondea la unidad y repasa la bajada dos veces: sin la ventana
    (el fallo, si la unidad redondea) y con ella (el arreglo).

    Raises:
        Saltada: Si no hay rclone (`rclone_fijado()`).
    """
    rclone = rclone_fijado()
    desvio = medir_hora(raiz)
    p.nota(f"{tipo}: una hora con fracción queda {desvio / 1e9:+.6f} s respecto a la pedida")
    sin = repasar_bajada(p, f"{tipo} sin la ventana", raiz / "sin-ventana", rclone, False)
    if abs(desvio) >= 1_000_000:                                  # 1 ms
        p.ver(f"{tipo}: sin la ventana, lo que baja se da por cambiado (el fallo)", sin > 0, True)
    else:
        p.ver(f"{tipo}: no la redondea, y sin la ventana nada sale cambiado", sin, 0)
    repasar_bajada(p, f"{tipo} con la ventana", raiz / "con-ventana", rclone, True)


# ---------------------------------------------------------------------------
# VeraCrypt en Windows
# ---------------------------------------------------------------------------
VERACRYPT_INSTALADO = Path(r"C:\Program Files\VeraCrypt")
CLAVE_VERACRYPT = "prueba-prdrive-2026"
DBT_DEVICEARRIVAL = 0x8000


def veracrypt() -> tuple[Path, Path]:
    """Devuelve el `VeraCrypt.exe` y el `VeraCrypt Format.exe` que hay en esta máquina.

    El instalado, si lo hay (en la nube, con choco); si no, el Portable que el
    instalador de prdrive ya bajó a este equipo, copiado a la carpeta de
    pruebas para no escribirle nada al lado.

    Raises:
        Saltada: Si no hay ninguno.
    """
    if os.environ.get("GITHUB_ACTIONS") and not (VERACRYPT_INSTALADO / "VeraCrypt.exe").exists():
        ejecutar(["choco", "install", "veracrypt", "-y", "--no-progress"], timeout=900)
    if (VERACRYPT_INSTALADO / "VeraCrypt.exe").exists():
        return VERACRYPT_INSTALADO / "VeraCrypt.exe", VERACRYPT_INSTALADO / "VeraCrypt Format.exe"
    bajados = Path(os.environ.get("LOCALAPPDATA", "")) / "prdrive-install" / "veracrypt"
    versiones = sorted((d for d in bajados.glob("*") if (d / "VeraCrypt-x64.exe").exists()),
                       key=lambda d: [int(x) for x in d.name.split(".") if x.isdigit()])
    if not versiones:
        raise Saltada("no hay VeraCrypt en esta máquina (ni instalado ni el Portable de prdrive)")
    if not es_administrador():
        # Sin elevar, el Portable pide permiso (UAC) para cargar su controlador
        # y la orden se queda esperando a que alguien conteste.
        raise Saltada("el VeraCrypt Portable necesita una sesión elevada")
    copia = TMP / f"veracrypt-{versiones[-1].name}"
    if not (copia / "VeraCrypt-x64.exe").exists():
        shutil.copytree(versiones[-1], copia, dirs_exist_ok=True)
    return copia / "VeraCrypt-x64.exe", copia / "VeraCrypt Format-x64.exe"


class Contenedor:
    """Un contenedor de VeraCrypt de prueba (60 MB, NTFS) y la letra donde se monta.

    Nunca desmonta forzando fuera de una máquina de usar y tirar: con el
    Portable deja el controlador sin descargar hasta reiniciar.

    Attributes:
        vc: El `VeraCrypt.exe`.
        portable: Si es el Portable de prdrive y no uno instalado.
        letra: La letra, sin dos puntos.
        raiz: La raíz del volumen montado.

    Raises:
        Saltada: Si no hay VeraCrypt o no crea el contenedor.
    """

    def __init__(self, carpeta_hc: Path | None = None) -> None:
        """Crea el contenedor; no lo monta.

        Args:
            carpeta_hc: Dónde va el `.hc` (por ejemplo un VHD aparte); sin ella,
                una carpeta de trabajo nueva.
        """
        self.vc, formato = veracrypt()
        self.portable = self.vc.parent != VERACRYPT_INSTALADO
        self.letra = letra_libre()
        self.raiz = Path(f"{self.letra}:\\")
        if carpeta_hc is not None:
            carpeta_hc.mkdir(parents=True, exist_ok=True)
        self.hc = (carpeta_hc or carpeta("vc")) / "prueba.hc"
        ejecutar([str(formato), "/create", str(self.hc), "/size", "60M", "/password",
                  CLAVE_VERACRYPT, "/encryption", "AES", "/hash", "sha512", "/filesystem",
                  "NTFS", "/pim", "0", "/silent", "/force"], timeout=600)
        if not self.hc.exists():
            raise Saltada("VeraCrypt no ha creado el contenedor")

    def montar(self) -> bool:
        """Monta el contenedor como lo monta prdrive (extraíble) y espera a verlo."""
        ejecutar([str(self.vc), "/volume", str(self.hc), "/letter", self.letra, "/password",
                  CLAVE_VERACRYPT, "/pim", "0", "/mountoption", "rm", "/quit", "/silent"],
                 timeout=120)
        return esperar(self.raiz.exists, 60)

    def desmontar(self, forzar: bool = False, callado: bool = True) -> tuple[bool, float]:
        """Desmonta la letra y devuelve si se ha ido y lo que tardó la orden.

        Args:
            forzar: Con `/force`.
            callado: Con `/silent`; sin él, VeraCrypt enseña sus ventanas si
                algo falla (así lo llama `Expulsar PRDRIVE.bat`).
        """
        t = time.monotonic()
        r = ejecutar([str(self.vc), "/dismount", self.letra, "/quit"]
                     + (["/silent"] if callado else []) + (["/force"] if forzar else []),
                     timeout=120)
        tardo = time.monotonic() - t
        if r.returncode != 0:
            return False, tardo
        return esperar(lambda: not self.raiz.exists(), 5), tardo

    def soltar(self) -> None:
        """Lo desmonta si sigue montado; forzando solo en una máquina de usar y tirar."""
        if self.raiz.exists() and not self.desmontar()[0] and os.environ.get("GITHUB_ACTIONS"):
            self.desmontar(forzar=True)


def ocupar(fichero: Path) -> subprocess.Popen:
    """Lanza otro programa que deja ese fichero abierto hasta que se le cierra la entrada."""
    otro = subprocess.Popen(
        [sys.executable, "-c", "import sys; f = open(sys.argv[1], 'w'); print('ya', flush=True); "
         "sys.stdin.read()", str(fichero)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    otro.stdout.readline()
    return otro


def desocupar(otro: subprocess.Popen) -> None:
    """Acaba el programa de `ocupar()`, que suelta su fichero."""
    otro.stdin.close()
    otro.wait(10)


def ventanas_de(pid: int) -> list[tuple[int, str, list[tuple[int, str]]]]:
    """Devuelve las ventanas visibles de un proceso: su handle, su título y sus controles con texto.

    El texto de un control de otro proceso se pide con `WM_GETTEXT`
    (`GetWindowTextW` solo lo da de las ventanas de arriba).
    """
    import ctypes
    from ctypes import wintypes
    u = ctypes.WinDLL("user32", use_last_error=True)
    tipo = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    u.SendMessageTimeoutW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                      ctypes.c_void_p, wintypes.UINT, wintypes.UINT,
                                      ctypes.c_void_p]

    def texto(h: int) -> str:
        """El texto de una ventana o de un control, sin el `&` de su atajo."""
        b = ctypes.create_unicode_buffer(512)
        u.SendMessageTimeoutW(h, 0x000D, 512, b, 0x0002, 1000, None)   # WM_GETTEXT
        return b.value.replace("&", "")

    salida: list[tuple[int, str, list[tuple[int, str]]]] = []

    def una(h: int, _l: int) -> bool:
        """Apunta una ventana de arriba si es de ese proceso y se ve."""
        de = wintypes.DWORD()
        u.GetWindowThreadProcessId(h, ctypes.byref(de))
        if de.value == pid and u.IsWindowVisible(h):
            hijos: list[tuple[int, str]] = []
            u.EnumChildWindows(h, tipo(lambda hh, _: hijos.append((hh, texto(hh))) or True), 0)
            salida.append((h, texto(h), [x for x in hijos if x[1]]))
        return True

    u.EnumWindows(tipo(una), 0)
    return salida


def mandar(hwnd: int, mensaje: int) -> None:
    """Deja un mensaje en la cola de una ventana (`BM_CLICK` 0xF5 pulsa un botón, `WM_CLOSE` 0x10 la cierra)."""
    import ctypes
    ctypes.WinDLL("user32").PostMessageW(ctypes.c_void_p(hwnd), mensaje, 0, 0)


BM_CLICK, WM_CLOSE = 0x00F5, 0x0010
BOTONES_DESMONTAR = ("unmount all", "dismount all")
"""El botón de desmontar todo de VeraCrypt: «Unmount All» desde la 1.26.2x, antes «Dismount All»."""


def configuracion_veracrypt(minutos: int, forzar: bool) -> str:
    """Devuelve un `Configuration.xml` de VeraCrypt que desmonta a esos minutos de inactividad.

    Args:
        minutos: `MaxVolumeIdleTime`.
        forzar: `ForceAutoDismount`: si desmonta aunque haya algo abierto dentro
            (lo de fábrica de VeraCrypt).
    """
    return ('<?xml version="1.0" encoding="utf-8"?>\n<VeraCrypt>\n\t<configuration>\n'
            f'\t\t<config key="MaxVolumeIdleTime">{minutos}</config>\n'
            f'\t\t<config key="ForceAutoDismount">{int(forzar)}</config>\n'
            '\t</configuration>\n</VeraCrypt>\n')


class VentanaVeraCrypt:
    """La ventana de VeraCrypt Portable abierta, con una configuración propia.

    Args:
        c: El contenedor de la prueba; tiene que ser del Portable.
        configuracion: El `Configuration.xml` con el que arranca
            (`configuracion_veracrypt()`).

    Raises:
        Saltada: Si VeraCrypt es uno instalado (no se toca su configuración) o
            la ventana no se abre, o no en inglés.
    """

    def __init__(self, c: Contenedor, configuracion: str) -> None:
        """Escribe la configuración, abre la ventana y busca su botón de desmontar todo."""
        if not c.portable:
            raise Saltada("solo con el Portable: no se toca la configuración de un VeraCrypt "
                          "instalado")
        (c.vc.parent / "Configuration.xml").write_text(configuracion, encoding="utf-8")
        self.proceso = subprocess.Popen([str(c.vc)])
        self.principal = self.boton = 0
        if not esperar(self._buscar, 30, 0.5):
            self.proceso.kill()
            raise Saltada("la ventana de VeraCrypt no se ha abierto, o no en inglés")

    def _buscar(self) -> bool:
        """Busca la ventana principal por su botón de desmontar todo."""
        for h, _titulo, hijos in ventanas_de(self.proceso.pid):
            for hh, texto in hijos:
                if texto.lower() in BOTONES_DESMONTAR:
                    self.principal, self.boton = h, hh
                    return True
        return False

    def desmontar_todo(self) -> None:
        """Pulsa su botón de desmontar todo."""
        mandar(self.boton, BM_CLICK)

    def preguntas(self) -> list[str]:
        """Los títulos de sus ventanas que no son la principal: una pregunta, un error."""
        return [t or "(sin título)" for h, t, _hijos in ventanas_de(self.proceso.pid)
                if h != self.principal]

    def cerrar(self) -> bool:
        """La cierra por las buenas; devuelve `False` si ha habido que matarla."""
        mandar(self.principal, WM_CLOSE)
        try:
            self.proceso.wait(20)
        except subprocess.TimeoutExpired:
            self.proceso.kill()
            return False
        return True


def al_final(motor, segundos: float = 4.0) -> dict:
    """Devuelve lo último que el motor ha dicho de cada pareja en esos segundos.

    No lo más grave, como `avisos()`: un `CAMBIO` que después se retira
    (`RETIRADO`) queda como retirado.
    """
    visto: dict = {}
    fin = time.monotonic() + segundos
    while time.monotonic() < fin:
        visto.update({k: a.tipo for k, a in motor.recoger().items()})
        time.sleep(0.1)
    return visto
