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


ESPERA_REGISTRO = 1.0       # s que se dan a quien acaba de crear un registro para llenarlo


def leer_registro(ruta: Path, espera: float = ESPERA_REGISTRO) -> dict | None:
    """Un registro de cerrojo tal como está: None si no hay, {} si hay y no se
    entiende. Quien lo toma lo crea y LUEGO lo llena (`crear_exclusivo`), así
    que uno vacío puede ser el de otro a medio escribir, no un resto: se le da
    `espera` antes de darlo por ilegible."""
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

    (True, None) si lo ha tomado; (None, None) si no se puede escribir;
    (False, otro) si lo tiene `otro` ({} si no se entiende), según `vivo(otro)`.

    Mirar y escribir son UN paso (`crear_exclusivo`): de dos que llegan a la
    vez solo uno lo crea. Un resto (lo que `vivo` no da por vivo) se retira
    comparando antes de borrar (`retirar_si_sigue`) y se intenta crear otra vez,
    una sola: si en ese instante otro se ha adelantado, manda ese."""
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


HOLGURA_ARRANQUE = 120.0    # s: el arranque calculado en Windows baila un poco


def arranque_del_sistema() -> float | None:
    """Cuándo arrancó el sistema, en segundos de época, o None si no se sabe.

    Un pid apuntado en un fichero solo vale en el arranque en que se apuntó: tras
    reiniciar los números se reutilizan, y otro proceso cualquiera pasaría por
    el que se apuntó. Linux lo dice en `/proc/stat` (`btime`); Windows, cuánto
    lleva encendido (`GetTickCount64`), que restado de la hora da lo mismo con
    un poco de baile (`HOLGURA_ARRANQUE`)."""
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
