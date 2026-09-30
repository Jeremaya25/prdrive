#!/usr/bin/env python3
"""
runsync.py — Lanzador del sync del dispositivo.

Sin argumentos abre la UI (paquete `ui/`: Tkinter si se puede, menú de consola si
no) con dos caminos:

  * Sincronizar ahora (todas las parejas o una selección).
  * Iniciar un SERVICIO periódico: un proceso en segundo plano, sin ventana, que
    sincroniza las parejas elegidas cada N minutos.

Este fichero no dibuja nada: le pregunta a `ui` qué se quiere hacer y lo hace. Lo
suyo es el servicio y la coordinación con él.

El servicio solo se detiene en dos casos:
  1. El dispositivo deja de estar conectado (se comprueba cada pocos segundos).
  2. Se vuelve a ejecutar runsync: el lanzador detecta el servicio anterior, le
     pide parar, espera, y muestra la UI inicial de nuevo.

Y de ventana solo hay una a la vez: la segunda se niega a abrirse en vez de
apilarse, porque abrir runsync detiene el servicio anterior y dos ventanas se
lo quitarían la una a la otra. Mientras haya ventana o servicio vivos,
el vigilante de `penwatch.py` tampoco lanza nada al enchufar el dispositivo.

Coordinación servicio <-> lanzador (todo en state/, viaja con el dispositivo):
    daemon.lock.json  <- quién es el servicio (pid, host, arranque, último ciclo)
    daemon.stop       <- su presencia le pide al servicio que pare
    daemon.log        <- diario del servicio (recortado automáticamente)
    ui.lock.json      <- quién tiene la ventana abierta (pid, host, arranque)
    ui_prefs.json     <- parejas e intervalo del servicio (lo gestiona ui.prefs)

El servicio es uno, se arranque a mano o al enchufar: esa memoria es su
configuración, precarga la UI siguiente y sirve de valor por defecto a --auto,
por delante de [daemon] del TOML. Solo la escribe la UI, y solo al arrancar el
servicio: una pasada manual no la toca, y --auto y --daemon únicamente la leen,
para que un arranque automático no reescriba lo que decidiste a mano.

Con el agente residente (`agente.py`) como servicio de esta raíz —vivo, y con
ella en modo `daemon`—, «Iniciar servicio» no arranca otro: guarda esa memoria
y le deja un `reanudar` en `state/servicio.pide`, y el agente vuelve en cuanto
se cierra la ventana.

Con argumentos, se pasan tal cual a sync.py (así `runsync.bat --doctor` sigue
funcionando), salvo dos flags propios:

  --auto [--once] [--interval N] [parejas]  arranca el servicio sin UI y sin
      preguntar nada, con las parejas y el intervalo del servicio (o, si no hay,
      con los valores de [daemon] del TOML); lo que se indique aquí manda sobre
      ambos. Con --once, una sola pasada de esas parejas y nada más. Es lo que
      lanza penwatch.py al detectar el dispositivo (modos daemon y sync).
  --daemon                          punto de entrada interno del servicio.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import ui  # noqa: E402
from common import APP_NAME, model, store, update, vigilancia  # noqa: E402
from common.store import pid_alive  # noqa: E402
from ui import prefs  # noqa: E402

SELF = Path(__file__).resolve()
SENTINEL = model.CONFIG_FILE          # si esto no se ve, el dispositivo no está
LOCK = model.daemon_lock()            # quién es el servicio
STOP = model.STATE_DIR / "daemon.stop"
DLOG = model.STATE_DIR / "daemon.log"
UI_LOCK = model.ui_lock()             # quién tiene la ventana abierta

POLL_SECONDS = 2.0        # cadencia de comprobación de parada / dispositivo ausente
STOP_WAIT_SECONDS = 15.0  # cuánto espera el lanzador a que pare el servicio
DLOG_MAX_BYTES = 256 * 1024
HOST = prefs.HOST

CREATE_NO_WINDOW = model.CREATE_NO_WINDOW
CREATE_NEW_PROCESS_GROUP = 0x00000200


# ---------------------------------------------------------------------------
# Utilidades comunes
# ---------------------------------------------------------------------------

def pen_present() -> bool:
    try:
        return SENTINEL.exists()
    except OSError:
        return False


def read_lock() -> dict | None:
    return store.read_json(LOCK) or None


def write_lock(data: dict) -> None:
    store.write_json(LOCK, data)


def _lock_mio(info: dict | None) -> bool:
    return bool(info) and info.get("pid") == os.getpid() and info.get("host") == HOST


def dlog(msg: str) -> None:
    """Diario del servicio. Se abre y cierra en cada línea para no mantener
    ningún descriptor abierto sobre el dispositivo (bloquearía la extracción segura)."""
    line = f"{store.stamp()} {msg}\n"
    try:
        if DLOG.exists() and DLOG.stat().st_size > DLOG_MAX_BYTES:
            tail = DLOG.read_text(encoding="utf-8", errors="replace").splitlines()[-300:]
            DLOG.write_text("\n".join(tail) + "\n", encoding="utf-8")
        with DLOG.open("a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass  # dispositivo ausente o de solo lectura: el diario no es vital


# ---------------------------------------------------------------------------
# Una sola ventana a la vez (lado lanzador)
# ---------------------------------------------------------------------------

ESPERA_REGISTRO = 1.0     # lo que se da a quien acaba de crear el registro para llenarlo


def _leer_ui() -> dict | None:
    """El registro tal como está: None si no hay, {} si hay y no se entiende.

    Quien toma el registro lo crea y LUEGO lo llena (ver `tomar_ui`), así que un
    fichero vacío puede ser el de otra ventana a medio escribir, no un resto. Se
    le da `ESPERA_REGISTRO` antes de darlo por ilegible."""
    limite = time.monotonic() + ESPERA_REGISTRO
    while True:
        try:
            texto = UI_LOCK.read_text(encoding="utf-8")
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


def _viva_aqui(info: dict | None) -> bool:
    """¿Es el registro de una ventana viva EN ESTE EQUIPO?

    Mismo criterio que el registro del servicio: un pid muerto o un registro de
    otro anfitrión es rastro de un dispositivo que se extrajo sin cerrar nada.
    Solo cuenta este equipo porque el fichero viaja con el dispositivo: el pid
    de otra máquina aquí no quiere decir nada."""
    if not info:
        return False
    try:
        pid = int(info.get("pid", -1))
    except (TypeError, ValueError):
        pid = -1
    return info.get("host") == HOST and pid_alive(pid)


def _crear_exclusivo(ruta: Path, datos: bytes) -> bool | None:
    """Crea `ruta` con `datos` solo si no existe: True creado, False ya estaba,
    None no se puede escribir (dispositivo de solo lectura o ya extraído).

    O_EXCL es lo que hace de esto un cerrojo: de dos que lo intentan a la vez
    solo uno lo crea. `store.write_json` no sirve para esto: escribe a un
    temporal y renombra, y el renombrado pisa lo que haya."""
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


def _borrar(ruta: Path) -> bool:
    """Borra `ruta` aunque otro la esté leyendo en ese momento. True si ya no está.

    En Windows no se puede borrar ni renombrar un fichero que otro proceso
    tiene abierto (WinError 32): con varios runsync mirando el registro a la
    vez, el primer intento falla casi siempre. Se reintenta un rato."""
    limite = time.monotonic() + ESPERA_REGISTRO
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


ROMPER_ABANDONADO = 5.0   # s: un «romper» más viejo es de un proceso que murió dentro


def _retirar_ui(visto: dict | None) -> bool:
    """Quita el resto `visto` si sigue siendo ese. True si lo ha quitado.

    Borrar a secas no vale: entre leer el resto y borrarlo, otra ventana puede
    haberlo retirado ya y haber tomado el suyo, y el borrado se llevaría ese.
    Así que retirar pide antes otro cerrojo exclusivo, `ui.lock.json.romper`,
    que se tiene unos milisegundos: con él puesto se vuelve a leer, y solo si
    sigue ahí el mismo resto se borra. Nadie más borra el registro mientras
    tanto (su dueño está muerto o en otro equipo) y crearlo exige que no esté,
    así que lo que se comprueba es lo que se borra.

    Si el «romper» es de un proceso que murió con él puesto, pasado
    `ROMPER_ABANDONADO` se quita. Eso tiene su propio hueco (dos que lo vean
    viejo a la vez), pero exige morir en esos milisegundos Y dos ventanas en el
    mismo instante: no merece más maquinaria."""
    romper = UI_LOCK.with_name(f"{UI_LOCK.name}.romper")
    marca = str(os.getpid()).encode("ascii")
    limite = time.monotonic() + ROMPER_ABANDONADO + 1.0
    while True:
        creado = _crear_exclusivo(romper, marca)
        if creado:
            break
        if creado is None or time.monotonic() >= limite:
            return False
        try:
            if time.time() - romper.stat().st_mtime > ROMPER_ABANDONADO:
                _borrar(romper)
                continue
        except OSError:
            continue                    # se acaba de soltar: otra vez
        time.sleep(0.02)
    try:
        actual = _leer_ui()
        if actual is None or actual != (visto or {}):
            return False                # ya lo retiró otro, o es otro registro
        return _borrar(UI_LOCK)
    finally:
        _borrar(romper)


def ui_en_marcha() -> dict | None:
    """El registro de una ventana de runsync viva EN ESTE EQUIPO, o None.

    Solo mira: el resto de una ventana muerta o de otro equipo se limpia, pero
    esto no toma nada. Para abrir una ventana, `tomar_ui()`."""
    info = _leer_ui()
    if info is None:
        return None
    if not _viva_aqui(info):
        _retirar_ui(info)
        return None
    return info


def tomar_ui() -> dict | None:
    """Apunta que esta ventana es la de este dispositivo, si nadie la tiene.

    None si la ha tomado; si no, el registro de la ventana que la tiene.

    Mirar y escribir son UN paso: el fichero se crea con O_EXCL
    (`_crear_exclusivo`), así que de dos runsync que llegan a la vez solo uno
    lo crea. Eran dos pasos, y el 28/09/2026 dos ventanas lanzadas con 6 s de
    diferencia miraron las dos antes de que ninguna escribiera y se abrieron a
    la vez.

    Si lo que hay es un resto (pid muerto, otro equipo, ilegible) se retira y se
    vuelve a intentar crearlo, una sola vez: si en ese instante otra ventana se
    ha adelantado, manda esa.

    Si no se puede escribir (dispositivo de solo lectura), o el resto no se deja
    quitar, la ventana se abre igual, como antes: el registro es para que la
    SIGUIENTE no se abra encima, no un permiso para abrir esta."""
    datos = json.dumps({"pid": os.getpid(), "host": HOST, "started": store.stamp()},
                       ensure_ascii=False, indent=1).encode("utf-8")
    for intento in range(2):
        creado = _crear_exclusivo(UI_LOCK, datos)
        if creado is not False:
            return None                 # tomado, o no se puede escribir
        otra = _leer_ui()
        if otra is None:
            continue                    # se soltó entre medias: otra vez
        if _viva_aqui(otra):
            return otra
        if not intento:
            _retirar_ui(otra)
    return None


def soltar_ui() -> None:
    """Suelta el registro si sigue siendo el nuestro. Lo de «si sigue siendo»
    es por el mismo motivo que en el servicio: si otro lo ha tomado ya —el
    dispositivo se extrajo y se volvió a enchufar—, no es nuestro para borrarlo."""
    info = store.read_json(UI_LOCK)
    if info.get("pid") == os.getpid() and info.get("host") == HOST:
        UI_LOCK.unlink(missing_ok=True)


def vigilante_instalado() -> bool:
    """¿Hay en este equipo un arranque automático que atienda a este dispositivo?

    Solo para decirlo en un mensaje. Bajo `except` porque penwatch es un script
    hermano que puede no poder importarse, y porque no saberlo no es motivo para
    no abrir la ventana."""
    try:
        from ui import watch
        return watch.resumen().vigila_este
    except Exception:                                   # noqa: BLE001
        return False


def agente_sirve() -> bool:
    """¿El servicio de esta raíz es el agente residente, vivo, en modo daemon?
    (`watch.Resumen.servicio_del_agente`). Bajo `except`, como el de arriba."""
    try:
        from ui import watch
        return watch.resumen().servicio_del_agente
    except Exception:                                   # noqa: BLE001
        return False


def pedir_reanudar() -> bool:
    """«Iniciar servicio» con el agente: `reanudar` en el buzón de esta raíz
    (`state/servicio.pide`). De módulo para que los tests la sustituyan."""
    from common import equipo
    return equipo.pedir({"pide": equipo.PIDE_REANUDAR},
                        model.STATE_DIR / equipo.BUZON_SERVICIO)


# ---------------------------------------------------------------------------
# Parada del servicio anterior (lado lanzador)
# ---------------------------------------------------------------------------

def stop_previous_daemon() -> str | None:
    """Si hay un servicio registrado, le pide parar y espera. Devuelve un mensaje
    para el usuario, o None si no había nada."""
    info = read_lock()
    if info is None:
        return None

    pid = int(info.get("pid", -1))
    if info.get("host") != HOST or not pid_alive(pid):
        # Rastro de otro equipo (dispositivo extraído sin más) o proceso ya muerto.
        LOCK.unlink(missing_ok=True)
        STOP.unlink(missing_ok=True)
        return (f"Había un registro de un servicio ya inexistente "
                f"(pid {pid}, host {info.get('host')}); limpiado.")

    STOP.touch()
    que = "esta carpeta" if model.es_equipo() else "este dispositivo"
    deadline = time.monotonic() + STOP_WAIT_SECONDS
    while time.monotonic() < deadline:
        if read_lock() is None:
            # El agente residente (`agente.py`) no se va: suelta el dispositivo
            # mientras haya una ventana abierta y vuelve cuando se cierra.
            if info.get("agente"):
                return (f"El agente de este equipo deja de sincronizar {que} "
                        f"mientras la ventana esté abierta.")
            return f"Servicio anterior (pid {pid}) detenido."
        time.sleep(0.3)

    # No ha contestado a tiempo: probablemente está en mitad de una pareja.
    # Se le deja el daemon.stop puesto (parará al terminarla). El lock del
    # agente se queda: lo suelta él al acabar la pareja, y mientras lo tenga
    # ningún servicio nuevo lo toma (`tomar_lock()` espera), así que no hay dos
    # pasadas a la vez. El de un servicio de runsync se libera, como siempre.
    if info.get("agente"):
        return (f"El agente de este equipo está a mitad de una pareja; deja de "
                f"sincronizar {que} en cuanto la acabe.")
    LOCK.unlink(missing_ok=True)
    return (f"El servicio (pid {pid}) está ocupado (¿sincronización en curso?); "
            f"parará al terminar la pareja actual.")


# ---------------------------------------------------------------------------
# El servicio (lado daemon)
# ---------------------------------------------------------------------------

def servicio_en_marcha() -> dict | None:
    """El registro del servicio si es de un proceso vivo de ESTE equipo, o None.

    Solo lee: limpiar lo rancio es de `stop_previous_daemon()`, que es quien va
    a sustituirlo. Quien pregunta esto no lo sustituye."""
    info = read_lock()
    if info is None or info.get("host") != HOST:
        return None
    try:
        pid = int(info.get("pid", -1))
    except (TypeError, ValueError):
        return None
    return info if pid_alive(pid) else None


def stop_requested() -> bool:
    try:
        return STOP.exists()
    except OSError:
        return False


def run_pair_quiet(name: str) -> tuple[int, str]:
    """Ejecuta sync.py para una pareja, sin terminal. Con stdin cerrado, las
    preguntas interactivas de sync.py toman el valor por defecto: una pareja que
    requiera --resync se SALTA (a propósito: un resync no se lanza solo)."""
    proc = subprocess.run(
        [sys.executable, str(model.SYNC_PY), name],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        # sync.py escribe UTF-8 (ver su main()); sin decirlo aquí se decodifica
        # con la del sistema y las tildes acaban descompuestas en daemon.log.
        encoding="utf-8",
        errors="replace",
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def notificar_fallo(nombres: list[str]) -> None:
    """Enseña que ha fallado un ciclo: una ventanita del propio servicio, en su
    mismo intérprete y sin lanzar nada (ver `ui.avisar_fallo`). Sin pantalla
    —un servicio de systemd sin DISPLAY, por ejemplo— el aviso se queda en el
    diario, que es donde estaba antes. De módulo para que un test la sustituya."""
    if ui.avisar_fallo(nombres):
        dlog(f"aviso de fallo en pantalla: {', '.join(nombres)}")
    else:
        dlog("no hay entorno gráfico: el aviso de fallo queda solo en este diario")


def daemon_cycle(pairs: list[str], lock_data: dict, vigia=None,
                 parcial: bool = False) -> None:
    """Una pasada de `pairs`. `vigia` (la de `watch = true`) toma su instantánea
    de cada pareja justo antes de lanzarla. Con `parcial` —una pasada disparada
    por cambios, no el ciclo— los resultados de las demás parejas se conservan."""
    previos = lock_data.get("last_results") or {}
    results = dict(previos) if parcial else {}
    for name in pairs:
        if stop_requested() or not pen_present():
            return
        if vigia is not None:
            vigia.iniciar(name, time.monotonic())
        t0 = time.monotonic()
        rc, output = run_pair_quiet(name)
        secs = time.monotonic() - t0
        if rc != 0:
            results[name] = f"ERROR rc={rc}"
            dlog(f"[{name}] FALLÓ (rc={rc}, {secs:.0f}s); salida:")
            for line in output.splitlines()[-12:]:
                dlog(f"[{name}]   {line}")
        elif "saltada" in output.lower():
            results[name] = "saltada (requiere --resync manual)"
            dlog(f"[{name}] saltada: requiere --resync; ejecútalo a mano desde la UI")
        else:
            results[name] = f"OK ({secs:.0f}s)"
            dlog(f"[{name}] OK ({secs:.0f}s)")
    lock_data["last_cycle"] = store.stamp()
    lock_data["last_results"] = results
    if _lock_mio(read_lock()):
        # Solo si sigue siendo nuestro: si el lanzador se cansó de esperar y lo
        # borró, o lo tiene ya otro servicio, reescribirlo sería quitárselo.
        write_lock(lock_data)

    # Solo cuando algo EMPIEZA a fallar. Un servicio sano no dice nada, y uno
    # que lleva horas sin red no abre una ventana cada media hora: ya lo ha
    # dicho, y la ventana principal lo sigue enseñando hasta que se arregle.
    fallidas = [n for n in pairs if results.get(n, "").startswith("ERROR")]
    if any(not str(previos.get(n, "")).startswith("ERROR") for n in fallidas):
        notificar_fallo(fallidas)

    # De paso, refrescar la caché de versiones. Con las 24 h de `CACHE_HORAS`
    # esto es como mucho una consulta al día, y es lo único que la mantiene al
    # día para el menú de consola, que nunca va a la red por su cuenta. El
    # servicio no tiene interfaz, así que aquí no se enseña nada: solo se apunta.
    try:
        update.check()                  # respeta la caché: no sale cada ciclo
        nueva = update.pending()
        if nueva is not None:
            dlog(f"hay una versión nueva disponible: {nueva.tag}")
    except Exception as e:                              # noqa: BLE001
        dlog(f"no he podido mirar si hay versión nueva: {e}")


ESPERA_AGENTE = 30 * 60   # s que el servicio espera a que el agente suelte la unidad


def tomar_lock(lock_data: dict) -> dict | None:
    """Apunta que este proceso es el servicio del dispositivo, si no lo es otro.
    None si lo ha tomado (o si no se puede escribir: así era antes); si no, el
    registro del servicio vivo que lo tiene.

    Mirar y escribir son UN paso (`store.tomar_registro()`, O_EXCL), y el agente
    del equipo toma el mismo fichero igual: escribirlo sin mirar dejaba que el
    agente y este servicio se creyeran los dos el servicio y sincronizaran a la
    vez. Si lo tiene el agente, se le pide que se aparte como lo pide el
    lanzador (`daemon.stop`), y se espera a que acabe su pareja: se aparta y
    borra el stop. Si lo tiene otro servicio de runsync, manda ese."""
    limite = time.monotonic() + ESPERA_AGENTE
    pedido = False
    while True:
        tomado, otro = store.tomar_registro(LOCK, lock_data, _viva_aqui)
        if tomado is not False:
            if pedido:
                STOP.unlink(missing_ok=True)    # el agente se apartó por su cuenta
            return None
        if not (otro or {}).get("agente") or time.monotonic() >= limite \
                or not pen_present():
            return otro or {}
        if not stop_requested():
            try:
                STOP.touch()
                pedido = True
            except OSError:
                return otro
        time.sleep(0.3)


def crear_vigia(pairs: list[str]):
    """La `Vigia` de las parejas del servicio con `watch = true`, o None si no
    hay ninguna (o el config no se puede leer: entonces manda el intervalo)."""
    try:
        config = model.load_config()
    except (model.ConfigError, OSError) as e:
        dlog(f"no vigilo cambios: no puedo leer el config ({e})")
        return None
    vigiladas = {p.name: p.local_abs for p in config.pairs
                 if p.watch and p.name in pairs}
    if not vigiladas:
        return None
    dlog(f"vigilando cambios en: {', '.join(vigiladas)}")
    return vigilancia.Vigia(vigiladas, ignorar=(model.VERSIONS_DIR,), avisar=dlog)


def daemon_main(pairs: list[str], interval_min: float) -> int:
    # Fuera del dispositivo: mantener el cwd en el USB impediría su extracción segura.
    os.chdir(tempfile.gettempdir())

    STOP.unlink(missing_ok=True)
    lock_data = {
        "pid": os.getpid(),
        "host": HOST,
        "started": store.stamp(),
        "pairs": pairs,
        "interval_min": interval_min,
    }
    otro = tomar_lock(lock_data)
    if otro is not None:
        quien = "el agente de este equipo" if otro.get("agente") else "otro servicio"
        dlog(f"servicio no iniciado: ya atiende {quien} (pid {otro.get('pid')})")
        return 0
    dlog(f"servicio iniciado: pid={os.getpid()} host={HOST} "
         f"parejas={','.join(pairs)} intervalo={interval_min:g}m")

    reason = "desconocido"
    vigia = crear_vigia(pairs)
    try:
        while True:
            if not pen_present():
                reason = "dispositivo no conectado"
                break
            if stop_requested():
                reason = "parada solicitada por el lanzador"
                break
            daemon_cycle(pairs, lock_data, vigia)
            wake = time.monotonic() + interval_min * 60
            stop = False
            while time.monotonic() < wake:
                if not pen_present():
                    reason, stop = "dispositivo no conectado", True
                    break
                if stop_requested():
                    reason, stop = "parada solicitada por el lanzador", True
                    break
                otro = read_lock()
                if otro is not None and not _lock_mio(otro) and _viva_aqui(otro):
                    # El lanzador se cansó de esperar, borró nuestro registro y
                    # arrancó otro servicio, que al empezar borra el stop que
                    # iba para nosotros: el que está ahí es el servicio, y dos
                    # a la vez es lo que no puede ser.
                    reason, stop = f"otro servicio (pid {otro.get('pid')}) tiene el registro", True
                    break
                if vigia is not None:
                    tocan = vigia.mirar(time.monotonic())
                    if tocan:
                        dlog(f"cambios en: {', '.join(tocan)}")
                        daemon_cycle(tocan, lock_data, vigia, parcial=True)
                        continue        # el tiempo de la pasada ya ha corrido
                time.sleep(POLL_SECONDS)
            if stop:
                break
    finally:
        dlog(f"servicio detenido: {reason}")
        # Limpiar solo lo propio: si el lanzador ya "robó" el lock y hay un
        # servicio nuevo, su registro no se toca.
        info = read_lock()
        if info and info.get("pid") == os.getpid() and info.get("host") == HOST:
            LOCK.unlink(missing_ok=True)
        STOP.unlink(missing_ok=True)
    return 0


def spawn_daemon(pairs: list[str], interval_min: float) -> str:
    cmd = [str(SELF), "--daemon", "--interval", str(interval_min), *pairs]
    kwargs: dict = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
        "cwd": tempfile.gettempdir(),
    }
    if os.name == "nt":
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        exe = str(pythonw) if pythonw.exists() else sys.executable
        kwargs["creationflags"] = CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
    else:
        exe = sys.executable
        kwargs["start_new_session"] = True

    proc = subprocess.Popen([exe, *cmd], **kwargs)
    return (f"Servicio iniciado (pid {proc.pid}): {', '.join(pairs)} "
            f"cada {interval_min:g} min.\n"
            f"Se detendrá solo si se extrae el dispositivo o si vuelves a ejecutar runsync.\n"
            f"Diario: {DLOG}")


def run_interactive(extra_args: list[str]) -> int:
    """sync.py en la consola actual, heredando stdin/stdout (preguntas incluidas)."""
    return subprocess.run([sys.executable, str(model.SYNC_PY), *extra_args]).returncode


# ---------------------------------------------------------------------------
# Caminos de entrada
# ---------------------------------------------------------------------------

def ui_flow() -> int:
    """Sin argumentos: parar el servicio anterior, preguntar, y hacer lo pedido."""
    # Lo PRIMERO, antes de parar nada: si ya hay una ventana abierta, esta sobra
    # y además haría daño. Abrir runsync detiene el servicio anterior, así que
    # una segunda ventana mataría el que acaba de arrancar la primera. Mirar y
    # tomar el registro son un solo paso (`tomar_ui`): mirar primero y tomarlo
    # después dejaba pasar a dos ventanas que llegaran casi a la vez.
    abierta = tomar_ui()
    if abierta is not None:
        return ui.fatal(
            f"Ya hay una ventana de {APP_NAME} abierta para este dispositivo "
            f"(pid {abierta.get('pid')}, desde las {abierta.get('started', '?')}).\n"
            "Usa esa; si no la encuentras, ciérrala desde el administrador de "
            "tareas y vuelve a intentarlo.")

    try:
        # Que el vigilante no lanza nada mientras esta ventana esté abierta ya
        # no se dice aquí: lo dice la línea del arranque automático, que está
        # siempre a la vista y no desaparece con el siguiente repintado.
        startup_msg = stop_previous_daemon()

        try:
            config = model.load_config()
        except model.ConfigError as e:
            return ui.fatal(str(e))

        return _atender(config, startup_msg)
    finally:
        soltar_ui()


def _atender(config: model.Config, startup_msg: str | None) -> int:
    """Preguntar y hacer lo pedido. Aparte de `ui_flow()` para que el registro
    de la ventana se suelte pase lo que pase, incluida una elección que arranca
    el servicio y se va."""
    choice, frontend = ui.start(config, startup_msg)
    if choice is None:
        return 0

    if choice.action == "daemon":
        # Es la configuración del servicio: la precarga de la próxima ventana y
        # lo que usa --auto. Solo se guarda aquí; una pasada manual con unas
        # pocas parejas no decide qué sincroniza el servicio (ver ui/prefs.py).
        prefs.save_prefs(choice.action, list(choice.pairs), choice.minutes,
                         config.names)
        if agente_sirve() and pedir_reanudar():
            # El servicio de esta raíz ya es el agente residente: arrancar otro
            # solo lo apartaría. Lee lo que se acaba de guardar y vuelve en
            # cuanto se cierre esta ventana.
            que = "esta carpeta" if model.es_equipo() else "este dispositivo"
            frontend.info(f"El agente de este equipo vuelve a sincronizar {que} en "
                          f"cuanto se cierre esta ventana: "
                          f"{', '.join(choice.pairs)} cada {choice.minutes:g} min.")
            return 0
        msg = spawn_daemon(list(choice.pairs), choice.minutes)
        if vigilante_instalado():
            msg += ("\nMientras el servicio esté en marcha, el arranque "
                    "automático tampoco abrirá nada al enchufar el dispositivo.")
        frontend.info(msg)
        return 0

    if choice.action == "doctor":
        return frontend.run_sync("Comprobación", ["--doctor"])

    # 'manual' solo llega aquí desde el menú de consola: la ventana sincroniza
    # sin cerrarse y no devuelve esta elección.
    args = ui.manual_args(config, choice.pairs, frontend.approve_resync)
    return frontend.run_sync("Sincronización manual", args)


def auto_start(rest: list[str]) -> int:
    """--auto: arranca el servicio sin UI, para quien lo lanza sin nadie delante
    (penwatch.py al conectar el dispositivo, un acceso directo, cron). Las parejas y el
    intervalo son los del servicio (`prefs.startup_defaults`), y si no hay, los de
    [daemon] del TOML; lo que se indique aquí manda sobre ambos. Solo lee esa
    memoria: un arranque automático nunca reescribe lo decidido a mano.
    Se para antes el servicio anterior, si lo hubiera.

    Con --once no hay servicio: una pasada de esas mismas parejas y se acaba
    (ver `una_pasada`)."""
    interval: float | None = None
    once = False
    while rest and rest[0] in ("--interval", "--once"):
        if rest[0] == "--once":
            once, rest = True, rest[1:]
            continue
        try:
            interval = float(rest[1])
        except (IndexError, ValueError):
            return ui.fatal("--interval necesita un número de minutos.")
        rest = rest[2:]

    try:
        config = model.load_config()
    except model.ConfigError as e:
        return ui.fatal(str(e))

    # El vigilante ya no llama aquí con la ventana abierta, pero esto también lo
    # lanzan un acceso directo o un cron: arrancar el servicio por detrás de una
    # ventana abierta pondría dos cosas a sincronizar las mismas parejas.
    abierta = ui_en_marcha()
    if abierta is not None:
        msg = (f"Hay una ventana de {APP_NAME} abierta (pid {abierta.get('pid')}): "
               + ("no lanzo la pasada." if once else "no arranco el servicio."))
        print(msg)
        dlog(f"--auto: {msg}")
        return 0

    names = config.names
    d_pairs, d_interval, memo = prefs.startup_defaults(config)
    unknown = [n for n in rest if n not in names]
    if unknown:
        dlog(f"--auto: parejas desconocidas, ignoradas: {', '.join(unknown)}")
    pairs = [n for n in rest if n in names] or d_pairs
    if memo and not rest:
        dlog(f"--auto: parejas del servicio: {', '.join(pairs)}")

    if once:
        return una_pasada(pairs)

    msg = stop_previous_daemon()
    if msg:
        print(msg)
        dlog(f"--auto: {msg}")
    msg = spawn_daemon(pairs, interval if interval is not None else d_interval)
    print(msg)
    dlog("--auto: " + msg.splitlines()[0])
    return 0


def una_pasada(pairs: list[str]) -> int:
    """--auto --once: las parejas del servicio, una vez, sin servicio detrás.

    Es el modo `sync` del vigilante. Con un servicio vivo en este equipo no hace
    nada: el vigilante ya no lanzaría en ese caso, pero un cron sí, y una pasada
    al lado del servicio chocaría con el lock de bisync. Y NO lo para, a
    diferencia de --auto: cambiar un servicio por una sola pasada dejaría el
    dispositivo sin servicio, que no es lo que se ha pedido.

    `sync.py` hereda la entrada y la salida. Sin terminal —así lo lanza el
    vigilante—, una pareja que pide --resync se salta, y la salida va a su
    diario."""
    servicio = servicio_en_marcha()
    if servicio is not None:
        msg = (f"El servicio periódico ya está en marcha (pid {servicio.get('pid')}): "
               "no lanzo otra pasada.")
        print(msg)
        dlog(f"--auto --once: {msg}")
        return 0
    dlog(f"--auto --once: una pasada de {', '.join(pairs)}")
    return run_interactive(pairs)


def main() -> int:
    args = sys.argv[1:]

    if args and args[0] == "--auto":
        return auto_start(args[1:])

    if args and args[0] == "--daemon":
        rest = args[1:]
        interval = model.DEFAULT_INTERVAL_MIN
        if rest and rest[0] == "--interval":
            interval = float(rest[1])
            rest = rest[2:]
        if not rest:
            return ui.fatal("--daemon necesita al menos una pareja.")
        return daemon_main(rest, interval)

    if args:
        # Passthrough: runsync.bat --doctor, runsync.bat obsidian --resync, etc.
        # También se para el servicio: va a tocar el mismo estado.
        msg = stop_previous_daemon()
        if msg:
            print(msg)
        return run_interactive(args)

    return ui_flow()


if __name__ == "__main__":
    raise SystemExit(main())
