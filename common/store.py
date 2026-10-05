#!/usr/bin/env python3
"""Los ficheros de estado en JSON que viajan dentro del dispositivo.

Dos reglas, y las dos vienen del medio: el dispositivo puede desaparecer a
media frase y puede estar leyéndolo otra máquina.
- Leer nunca es un error: un fichero que no está, que está a medias o que trae
  basura significa «aquí no hay nada escrito», no una excepción que propagar.
- Escribir es atómico (fichero temporal + `os.replace`) y, si falla, se dice
  que ha fallado en vez de reventar: ninguno de estos ficheros es
  imprescindible.

Los comparten el registro del servicio (`daemon.lock.json`) y la memoria de la
UI (`ui_prefs.json`). Con ellos viaja `pid_alive`, que da sentido a un registro
con un pid dentro: un fichero de bloqueo solo vale si se puede saber si quien
lo escribió sigue vivo.

Al final están `hide()` y `unhide()`, el atributo de oculto de Windows: el
dispositivo también esconde algo suyo (el icono de la unidad, `ui/volumen.py`)
e `install/` no viaja a él.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path


FORMATO = "%Y-%m-%d %H:%M:%S"
"""Formato de las fechas de todos estos ficheros y del diario de pasadas."""


def stamp() -> str:
    """Devuelve la fecha de ahora, como se escribe en todos estos ficheros."""
    return f"{datetime.now():{FORMATO}}"


def desde_sello(texto: str) -> float | None:
    """Devuelve la marca de tiempo de un sello de `stamp()`.

    La escribe quien apunta y la lee quien compara: una marca de tiempo se
    puede medir contra la mtime de un fichero y una cadena no. Va junto a
    `stamp()` para que las dos mitades del formato no puedan separarse.

    Returns:
        Segundos de época, o `None` si eso no es una fecha suya.
    """
    try:
        return datetime.strptime(texto, FORMATO).timestamp()
    except (TypeError, ValueError):
        return None


def read_json(path: Path) -> dict:
    """Lee un JSON que es un objeto.

    Si falta, está a medias o no lo es, devuelve `{}`.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_json(path: Path, data: dict) -> bool:
    """Escribe un JSON de forma atómica.

    Returns:
        True si se ha escrito; False si el dispositivo es de solo lectura o ya
        se extrajo.
    """
    return write_text(path, json.dumps(data, ensure_ascii=False, indent=1))


def write_text(path: Path, text: str) -> bool:
    """Escribe un texto cualquiera con la misma regla que `write_json`.

    El diario de pasadas no es un JSON sino una línea por pasada
    (`common/historial.py`), y cuando se recorta se reescribe entero con la
    misma regla que el resto.
    """
    try:
        tmp = path.with_suffix(".tmp")
        # El temporal se crea de nuevo y en exclusiva: el `.tmp` que hubiera
        # (el de un corte, o un enlace que alguien dejó ahí) se quita antes, y
        # `O_EXCL` no sigue enlaces. Abrirlo sin más seguiría uno y el
        # contenido iría a parar, fuera del dispositivo, al fichero al que
        # apunte. El renombrado final tampoco sigue enlaces: sustituye el
        # nombre.
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
        return True
    except OSError:
        return False


def crear_exclusivo(ruta: Path, datos: bytes) -> bool | None:
    """Crea `ruta` con `datos` solo si no existe.

    `O_EXCL` es lo que hace de esto un cerrojo: de dos que lo intentan a la vez
    solo uno lo crea (`write_json` no sirve: su renombrado pisa lo que haya).
    Es lo mismo que el registro de la ventana (`runsync.tomar_ui()`), para
    quien no es runsync.

    Returns:
        True si lo ha creado, False si ya estaba, `None` si no se puede
        escribir.
    """
    try:
        fd = os.open(ruta, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                     | getattr(os, "O_BINARY", 0))
    except FileExistsError:
        return False
    except OSError:
        return None
    try:
        os.write(fd, datos)
    except OSError:
        pass  # vacío también cuenta como tomado
    finally:
        os.close(fd)
    return True


def borrar(ruta: Path, espera: float = 1.0) -> bool:
    """Borra `ruta` aunque otro la esté leyendo.

    En Windows no se borra un fichero que otro proceso tiene abierto (WinError
    32), así que se reintenta durante `espera` segundos.

    Returns:
        True si ya no está.
    """
    import time
    limite = time.monotonic() + espera
    while True:
        try:
            ruta.unlink()
            return True
        except FileNotFoundError:
            return True
        except PermissionError:
            if time.monotonic() >= limite:
                return False
            time.sleep(0.02)
        except OSError:
            return False


ROMPER_ABANDONADO = 5.0
"""Segundos tras los cuales un cerrojo «romper» se da por abandonado.

Es de un proceso que murió dentro.
"""


def retirar_si_sigue(ruta: Path, visto: dict, leer) -> bool:
    """Borra el resto `visto` de `ruta` si sigue siendo ese.

    Borrar a secas no vale: entre leer el resto y borrarlo otro puede haberlo
    retirado y haber tomado el suyo, y el borrado se llevaría ese. Antes se
    toma otro cerrojo, `<ruta>.romper`; con él puesto se vuelve a leer
    (`leer()`) y solo si sigue el mismo resto se borra. Es la regla de
    `runsync._retirar_ui()`.

    Returns:
        True si lo ha quitado.
    """
    import time
    romper = ruta.with_name(f"{ruta.name}.romper")
    marca = str(os.getpid()).encode("ascii")
    limite = time.monotonic() + ROMPER_ABANDONADO + 1.0
    while True:
        creado = crear_exclusivo(romper, marca)
        if creado:
            break
        if creado is None or time.monotonic() >= limite:
            return False
        try:
            if time.time() - romper.stat().st_mtime > ROMPER_ABANDONADO:
                borrar(romper)
                continue
        except OSError:
            continue                    # se acaba de soltar: otra vez
        time.sleep(0.02)
    try:
        actual = leer()
        if actual is None or actual != (visto or {}):
            return False                # ya lo retiró otro, o es otro registro
        return borrar(ruta)
    finally:
        borrar(romper)


ESPERA_REGISTRO = 1.0
"""Segundos que se dan a quien acaba de crear un registro para llenarlo."""


def leer_registro(ruta: Path, espera: float = ESPERA_REGISTRO) -> dict | None:
    """Devuelve un registro de cerrojo tal como está.

    Quien lo toma lo crea y LUEGO lo llena (`crear_exclusivo`), así que uno
    vacío puede ser el de otro a medio escribir y no un resto: se le da
    `espera` antes de darlo por ilegible.

    Returns:
        `None` si no hay registro, `{}` si lo hay y no se entiende.
    """
    import time
    limite = time.monotonic() + espera
    while True:
        try:
            texto = ruta.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except OSError:
            texto = ""
        try:
            info = json.loads(texto)
            if isinstance(info, dict):
                return info
        except ValueError:
            pass
        if time.monotonic() >= limite:
            return {}
        time.sleep(0.05)


def tomar_registro(ruta: Path, datos: dict, vivo) -> tuple[bool | None, dict | None]:
    """Toma el cerrojo `ruta` con `datos` si nadie vivo lo tiene.

    Mirar y escribir son UN paso (`crear_exclusivo`): de dos que llegan a la
    vez solo uno lo crea. Un resto (lo que `vivo` no da por vivo) se retira
    comparando antes de borrar (`retirar_si_sigue`) y se intenta crear otra
    vez, una sola: si en ese instante otro se ha adelantado, manda ese.

    Args:
        ruta: El fichero de cerrojo.
        datos: Lo que se apunta en él.
        vivo: `vivo(otro)` dice si el registro de otro es de alguien vivo.

    Returns:
        `(True, None)` si lo ha tomado; `(None, None)` si no se puede escribir;
        `(False, otro)` si lo tiene `otro` (`{}` si no se entiende).
    """
    texto = json.dumps(datos, ensure_ascii=False, indent=1).encode("utf-8")
    otro: dict | None = None
    for intento in range(2):
        creado = crear_exclusivo(ruta, texto)
        if creado is not False:
            return creado, None
        otro = leer_registro(ruta)
        if otro is None:
            continue                    # se soltó entre medias: otra vez
        if vivo(otro):
            return False, otro
        if not intento:
            retirar_si_sigue(ruta, otro, lambda: leer_registro(ruta))
    return False, otro or {}


HOLGURA_ARRANQUE = 120.0
"""Segundos de tolerancia al comparar arranques del sistema.

El arranque calculado en Windows baila un poco.
"""


def arranque_del_sistema() -> float | None:
    """Devuelve cuándo arrancó el sistema, en segundos de época.

    Un pid apuntado en un fichero solo vale en el arranque en que se apuntó:
    tras reiniciar los números se reutilizan y otro proceso cualquiera pasaría
    por el que se apuntó. Linux lo dice en `/proc/stat` (`btime`); Windows,
    cuánto lleva encendido (`GetTickCount64`), que restado de la hora da lo
    mismo con un poco de baile (`HOLGURA_ARRANQUE`).

    Returns:
        Los segundos de época, o `None` si no se sabe.
    """
    import time
    try:
        if os.name == "nt":
            import ctypes
            k32 = ctypes.windll.kernel32                    # type: ignore[attr-defined]
            k32.GetTickCount64.restype = ctypes.c_uint64
            return time.time() - k32.GetTickCount64() / 1000.0
        with open("/proc/stat", encoding="ascii", errors="replace") as f:
            for linea in f:
                if linea.startswith("btime "):
                    return float(linea.split()[1])
    except (OSError, ValueError, AttributeError):
        pass
    return None


def pid_alive(pid: int) -> bool:
    """Indica si ese proceso sigue vivo.

    En Windows NO vale `os.kill(pid, 0)`: con cualquier señal que no sea
    CTRL_C/CTRL_BREAK, `os.kill` llama a `TerminateProcess`, es decir, MATA el
    proceso en vez de comprobarlo. Hay que preguntar por el handle.
    """
    if os.name == "nt":
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        k32 = ctypes.windll.kernel32
        handle = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        code = ctypes.c_ulong()
        ok = k32.GetExitCodeProcess(handle, ctypes.byref(code))
        k32.CloseHandle(handle)
        return bool(ok) and code.value == STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True     # existe, pero es de otro usuario
    return not _zombi(pid)


def _zombi(pid: int) -> bool:
    """Indica si ese proceso ya ha salido y solo espera a que su padre lo recoja.

    `os.kill(pid, 0)` lo da por vivo, y no lo está: el KeePassXC que lanza la
    ventana es hijo suyo, y al cerrarlo se queda así hasta que ella lo recoge,
    así que «Expulsar» lo esperaba hasta el tope. Es el estado `Z` de
    `/proc/<pid>/stat` (el tercer campo, detrás del nombre entre paréntesis);
    sin `/proc`, no se sabe y no lo es.
    """
    try:
        datos = (Path("/proc") / str(pid) / "stat").read_bytes()
    except OSError:
        return False
    return datos[datos.rfind(b")") + 2:][:1] == b"Z"


def procesos_llamados(nombre: str) -> set[int]:
    """Devuelve los pid de los procesos vivos cuyo ejecutable se llama `nombre`.

    Solo en Windows (en POSIX, vacío). Es como se ve la copia elevada que
    VeraCrypt sin su driver instalado lanza de sí mismo (`/q UAC`): la lanzada
    sale y la otra sigue. Va por la instantánea de Toolhelp, que da el nombre
    sin abrir ningún proceso ni pedir permisos sobre uno elevado, y no por WMI:
    en las pruebas en G:, la consulta a WMI no enseñaba la copia elevada de
    VeraCrypt y `Get-Process` sí. Si no se puede sacar la instantánea devuelve
    un conjunto vacío: no poder mirar no puede dejar a nadie esperando.
    """
    if os.name != "nt":
        return set()
    import ctypes
    from ctypes import wintypes

    class PROCESSENTRY32W(ctypes.Structure):
        """Estructura `PROCESSENTRY32W` de Toolhelp."""
        _fields_ = [("dwSize", wintypes.DWORD),
                    ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_size_t),
                    ("th32ModuleID", wintypes.DWORD),
                    ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", ctypes.c_long),
                    ("dwFlags", wintypes.DWORD),
                    ("szExeFile", wintypes.WCHAR * 260)]

    TH32CS_SNAPPROCESS = 0x00000002
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    k32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]

    foto = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not foto or foto == wintypes.HANDLE(-1).value:
        return set()
    vivos = set()
    try:
        entrada = PROCESSENTRY32W()
        entrada.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        seguir = k32.Process32FirstW(foto, ctypes.byref(entrada))
        while seguir:
            if entrada.szExeFile.lower() == nombre.lower():
                vivos.add(entrada.th32ProcessID)
            seguir = k32.Process32NextW(foto, ctypes.byref(entrada))
    finally:
        k32.CloseHandle(foto)
    return vivos


def procesos_desde(carpeta: Path) -> dict[int, str]:
    """Devuelve `{pid: ejecutable}` de los procesos que corren desde `carpeta`.

    Esperar a la ventana y al aplicador no basta: un `runsync` lanzado con la
    ventana ya abierta llevaba una hora enseñando «Ya hay una ventana de
    prdrive abierta…» desde ese mismo `pythonw.exe`, y el cambio le borró la
    biblioteca estándar debajo y dejó la carpeta vieja a medio borrar. Esto es
    lo que lo ve, para esperarlo y decir cuál es. En Windows va por la
    instantánea de Toolhelp (como `crypto._procesos()`) y
    `QueryFullProcessImageNameW`, que con `PROCESS_QUERY_LIMITED_INFORMATION`
    contesta sin elevación; en Linux por `/proc/<pid>/exe`. Lo que no se deja
    mirar no cuenta. Es función de módulo para que los tests la sustituyan.

    Vive aquí y no en `install/` porque también lo pregunta el dispositivo: el
    llavero mira si KeePassXC corre desde la unidad. `install/components.py` la
    reexporta, y sus tests la sustituyen allí.
    """
    try:
        base = Path(carpeta).resolve()
    except OSError:
        return {}
    salida: dict[int, str] = {}
    for pid, exe in procesos().items():
        try:
            Path(exe).resolve().relative_to(base)
        except (ValueError, OSError):
            continue
        salida[pid] = exe
    return salida


def procesos() -> dict[int, str]:
    """Devuelve `{pid: ejecutable}` de todos los procesos del equipo que se dejan mirar.

    Es lo que recorre `procesos_desde()`; el llavero lo pregunta además para
    saber si hay otro KeePassXC abierto, que no corre desde la unidad. Es
    función de módulo para que los tests la sustituyan.
    """
    return dict(_ejecutables())


def orden_de(pid: int) -> list[str]:
    """Devuelve la línea de órdenes de un proceso, o `[]` si no se deja mirar.

    En Linux es `/proc/<pid>/cmdline`. En Windows no hace falta: lo que se
    pregunta allí se sabe por el ejecutable (`procesos_desde()`). El llavero
    la mira en Linux para saber de qué unidad es un KeePassXC, que corre
    extraído fuera de ella (`llavero.pids_keepassxc()`). Es función de módulo
    para que los tests la sustituyan.
    """
    if os.name == "nt":
        return []
    try:
        datos = (Path("/proc") / str(pid) / "cmdline").read_bytes()
    except OSError:
        return []
    return [p.decode("utf-8", "surrogateescape") for p in datos.split(b"\0") if p]


def _ejecutables() -> list[tuple[int, str]]:
    """Devuelve `(pid, ruta del ejecutable)` de los procesos que se dejan mirar."""
    if os.name != "nt":
        salida = []
        for d in Path("/proc").glob("[0-9]*"):
            try:
                salida.append((int(d.name), os.readlink(d / "exe")))
            except (OSError, ValueError):
                continue
        return salida

    import ctypes
    from ctypes import wintypes

    class PROCESSENTRY32W(ctypes.Structure):
        """Estructura `PROCESSENTRY32W` de Toolhelp."""
        _fields_ = [("dwSize", wintypes.DWORD),
                    ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_size_t),
                    ("th32ModuleID", wintypes.DWORD),
                    ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", ctypes.c_long),
                    ("dwFlags", wintypes.DWORD),
                    ("szExeFile", wintypes.WCHAR * 260)]

    TH32CS_SNAPPROCESS = 0x00000002
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    k32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]

    foto = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not foto or foto == wintypes.HANDLE(-1).value:
        return []
    pids = []
    try:
        entrada = PROCESSENTRY32W()
        entrada.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        seguir = k32.Process32FirstW(foto, ctypes.byref(entrada))
        while seguir:
            pids.append(entrada.th32ProcessID)
            seguir = k32.Process32NextW(foto, ctypes.byref(entrada))
    finally:
        k32.CloseHandle(foto)

    salida = []
    for pid in pids:
        h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            continue
        try:
            buf = ctypes.create_unicode_buffer(32768)
            n = wintypes.DWORD(len(buf))
            if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
                salida.append((pid, buf.value))
        finally:
            k32.CloseHandle(h)
    return salida


FILE_ATTRIBUTE_HIDDEN = 0x02
"""Atributo de Windows: oculto."""
FILE_ATTRIBUTE_NORMAL = 0x80
"""Atributo de Windows: normal, sin ocultar."""


def hide(path: Path | str) -> bool:
    """Marca el fichero o la carpeta como oculto en Windows.

    No lanza nunca: es un adorno, y un adorno no puede abortar una instalación
    que por lo demás ha ido bien (el mismo criterio que `icons.get()`). En
    POSIX devuelve True sin hacer nada porque el punto del nombre ya lo oculta.

    Returns:
        True si lo ha conseguido.
    """
    if os.name != "nt":
        return True
    try:
        import ctypes
        return bool(ctypes.windll.kernel32.SetFileAttributesW(  # type: ignore[attr-defined]
            str(path), FILE_ATTRIBUTE_HIDDEN))
    except Exception:
        return False


def unhide(path: Path | str) -> bool:
    """Hace lo contrario de `hide()`, para poder reescribir un fichero oculto.

    Windows niega abrir con `CREATE_ALWAYS` (lo que hace `open(…, "w")`) un
    fichero oculto o de sistema si no se le piden esos mismos atributos
    (`CreateFileW`): el «acceso denegado» sale aunque se tenga permiso. No
    lanza nunca, y sin el fichero no hay nada que destapar.
    """
    if os.name != "nt":
        return True
    try:
        import ctypes
        return bool(ctypes.windll.kernel32.SetFileAttributesW(  # type: ignore[attr-defined]
            str(path), FILE_ATTRIBUTE_NORMAL))
    except Exception:
        return False
