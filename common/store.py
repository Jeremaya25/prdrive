#!/usr/bin/env python3
"""
store.py — Los ficheros de estado en JSON que viajan dentro del dispositivo.

Dos reglas, y las dos vienen del medio: el dispositivo puede desaparecer a media frase y
puede estar leyéndolo otra máquina.

  * Leer nunca es un error. Un fichero que no está, que está a medias o que trae
    basura significa "aquí no hay nada escrito", no una excepción que propagar.
  * Escribir es atómico (fichero temporal + os.replace), y si falla, se dice que
    ha fallado en vez de reventar: ninguno de estos ficheros es imprescindible.

Los comparten el registro del servicio (daemon.lock.json) y la memoria de la UI
(ui_prefs.json). Y con ellos viaja `pid_alive`, que es lo que le da sentido a un
registro con un pid dentro: un fichero de bloqueo solo vale si se puede saber si
quien lo escribió sigue vivo.

Al final, `hide()` y `unhide()`: el atributo de oculto de Windows. Los usaba solo
el instalador, y vivían en `install/deploy.py`; el dispositivo también esconde
algo suyo (el icono de la unidad, `ui/volumen.py`) e `install/` no viaja a él.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path


FORMATO = "%Y-%m-%d %H:%M:%S"    # el de todos estos ficheros y el del diario


def stamp() -> str:
    """La fecha de ahora, como se escribe en todos estos ficheros."""
    return f"{datetime.now():{FORMATO}}"


def desde_sello(texto: str) -> float | None:
    """La vuelta de `stamp()`, o None si eso no es una fecha suya.

    La escribe quien apunta y la lee quien compara: una marca de tiempo se puede
    medir contra la mtime de un fichero, y una cadena no. Va aquí, al lado de
    `stamp()`, para que las dos mitades del formato no puedan separarse."""
    try:
        return datetime.strptime(texto, FORMATO).timestamp()
    except (TypeError, ValueError):
        return None


def read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_json(path: Path, data: dict) -> bool:
    """True si se ha escrito. False = dispositivo de solo lectura o ya extraído."""
    return write_text(path, json.dumps(data, ensure_ascii=False, indent=1))


def write_text(path: Path, text: str) -> bool:
    """Lo mismo para un texto cualquiera: el diario de pasadas no es un JSON
    sino una línea por pasada (`common/historial.py`), y cuando se recorta se
    reescribe entero con la misma regla que el resto."""
    try:
        tmp = path.with_suffix(".tmp")
        # El temporal se crea de nuevo y en exclusiva: el `.tmp` que ya hubiera
        # (el de un corte, o un enlace que alguien dejó ahí) se quita antes, y
        # O_EXCL no sigue enlaces. Abrirlo sin más seguiría uno, y el contenido
        # iría a parar al fichero al que apunte, fuera del dispositivo. El
        # renombrado final tampoco sigue enlaces: sustituye el nombre.
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


# ---------------------------------------------------------------------------
# Cerrojos: un fichero que solo uno puede crear
# ---------------------------------------------------------------------------

def crear_exclusivo(ruta: Path, datos: bytes) -> bool | None:
    """Crea `ruta` con `datos` solo si no existe: True creado, False ya estaba,
    None no se puede escribir. O_EXCL es lo que hace de esto un cerrojo: de dos
    que lo intentan a la vez solo uno lo crea (`write_json` no sirve: su
    renombrado pisa lo que haya). Es lo mismo que el registro de la ventana
    (`runsync.tomar_ui()`), para quien no es runsync."""
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
        pass                            # vacío también cuenta como tomado
    finally:
        os.close(fd)
    return True


def borrar(ruta: Path, espera: float = 1.0) -> bool:
    """Borra `ruta` aunque otro la esté leyendo. True si ya no está. En Windows
    no se borra un fichero que otro proceso tiene abierto (WinError 32): se
    reintenta un rato."""
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


ROMPER_ABANDONADO = 5.0     # s: un «romper» más viejo es de un proceso que murió dentro


def retirar_si_sigue(ruta: Path, visto: dict, leer) -> bool:
    """Borra el resto `visto` de `ruta` si sigue siendo ese. True si lo ha quitado.

    Borrar a secas no vale: entre leer el resto y borrarlo, otro puede haberlo
    retirado y haber tomado el suyo, y el borrado se llevaría ese. Así que antes
    se toma otro cerrojo, `<ruta>.romper`; con él puesto se vuelve a leer
    (`leer()`), y solo si sigue el mismo resto se borra. Es la regla de
    `runsync._retirar_ui()`."""
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


def pid_alive(pid: int) -> bool:
    """¿Sigue vivo ese proceso?

    OJO: en Windows NO vale os.kill(pid, 0). Con cualquier señal que no sea
    CTRL_C/CTRL_BREAK, os.kill llama a TerminateProcess, es decir, MATA el
    proceso en vez de comprobarlo. Hay que preguntar por el handle."""
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
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True     # existe, pero es de otro usuario


FILE_ATTRIBUTE_HIDDEN = 0x02
FILE_ATTRIBUTE_NORMAL = 0x80


def hide(path: Path | str) -> bool:
    """Marca el fichero o la carpeta como oculto en Windows. Devuelve si lo ha
    conseguido.

    No lanza nunca: es un adorno, y un adorno no puede abortar una instalación
    que por lo demás ha ido bien —el mismo criterio que `icons.get()`—. En POSIX
    devuelve True sin hacer nada porque el punto del nombre ya lo oculta."""
    if os.name != "nt":
        return True
    try:
        import ctypes
        return bool(ctypes.windll.kernel32.SetFileAttributesW(  # type: ignore[attr-defined]
            str(path), FILE_ATTRIBUTE_HIDDEN))
    except Exception:
        return False


def unhide(path: Path | str) -> bool:
    """Lo contrario de `hide()`, para poder reescribir un fichero oculto.

    Windows niega abrir con `CREATE_ALWAYS` —lo que hace `open(…, "w")`— un
    fichero oculto o de sistema si no se le piden esos mismos atributos
    (`CreateFileW`): el «acceso denegado» sale aunque se tenga permiso. No lanza
    nunca, y sin el fichero no hay nada que destapar."""
    if os.name != "nt":
        return True
    try:
        import ctypes
        return bool(ctypes.windll.kernel32.SetFileAttributesW(  # type: ignore[attr-defined]
            str(path), FILE_ATTRIBUTE_NORMAL))
    except Exception:
        return False
