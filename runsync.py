#!/usr/bin/env python3
"""Lanzador del sync del dispositivo: la ventana y el servicio periódico.

Sin argumentos abre la UI (paquete `ui/`: Tkinter o, si no se puede, menú de
consola) con dos caminos: sincronizar ahora (todas las parejas o una selección)
o iniciar un SERVICIO periódico, un proceso en segundo plano y sin ventana que
sincroniza las parejas elegidas cada N minutos. Este fichero no dibuja nada: le
pregunta a `ui` qué se quiere hacer y lo hace; lo suyo es el servicio y la
coordinación con él.

El servicio solo se detiene en dos casos:
- El dispositivo deja de estar conectado (se comprueba cada pocos segundos).
- Se vuelve a ejecutar runsync: el lanzador detecta el servicio anterior, le
  pide parar, espera y muestra la UI de nuevo.

De ventana solo hay una a la vez: la segunda se niega a abrirse en vez de
apilarse, porque abrir runsync detiene el servicio anterior y dos ventanas se
lo quitarían la una a la otra. Mientras haya ventana o servicio vivos, el
vigilante de `penwatch.py` tampoco lanza nada al enchufar el dispositivo.

Coordinación servicio <-> lanzador (todo en `state/`, viaja con el
dispositivo):

    daemon.lock.json  <- quién es el servicio (pid, host, arranque, último ciclo)
    daemon.stop       <- su presencia le pide al servicio que pare
    daemon.log        <- diario del servicio (recortado automáticamente)
    ui.lock.json      <- quién tiene la ventana abierta (pid, host, arranque)
    ui_prefs.json     <- parejas e intervalo del servicio (lo gestiona `ui.prefs`)

El servicio es uno, se arranque a mano o al enchufar: `ui_prefs.json` es su
configuración, precarga la UI siguiente y es el valor por defecto de `--auto`,
por delante de `[daemon]` del TOML. Solo la escribe la UI: las parejas, al
arrancar el servicio, y el intervalo solo, en «Ajustes → Configuración». Una
pasada manual no la toca, y `--auto` y `--daemon` únicamente la leen.

Con el agente residente (`agente.py`) como servicio de esta raíz (vivo y en
modo `daemon`), la ventana no ofrece «Iniciar servicio» sino «Pausar» /
«Reanudar», que se lo piden por `state/servicio.pide` sin pasar por aquí
(`ui/watch.py`). La consola sí lo ofrece, y entonces no se arranca otro: se
guarda esa memoria y se deja un `reanudar`, y el agente vuelve en cuanto se
sale de ella.

Con argumentos se pasan tal cual a `sync.py` (así `runsync.bat --doctor` sigue
funcionando), salvo estos flags propios:

    --auto [--once] [--interval N] [parejas]
        Arranca el servicio sin UI y sin preguntar, con las parejas y el
        intervalo del servicio (o, si no hay, los de [daemon] del TOML); lo
        indicado aquí manda sobre ambos. Con --once, una sola pasada de esas
        parejas y nada más. Es lo que lanza penwatch.py al detectar el
        dispositivo (modos daemon y sync).
    --daemon
        Punto de entrada interno del servicio.
    --llavero
        «Abrir llavero» sin la ventana: abre KeePassXC con la base del
        dispositivo (`ui.abrir_llavero()`). Es lo que hacen `Llavero.bat` y `llavero.sh`.
    --cerrar-llavero
        Lo que hacen «Expulsar PRDRIVE.bat» y `expulsar-prdrive.sh` antes de desmontar: cierra
        KeePassXC (si se dice que sí), sube lo pendiente y deja el registro del
        navegador como estaba (`keepassxc.cerrar_llavero()`). Sale con 1 si
        KeePassXC sigue abierto.
    --combinar-llavero BASE COPIA [--keyfile LLAVE] [--codigo FICHERO]
        La consola de «Combinar»: `keepassxc-cli merge` pide en ella la
        contraseña de la base (`keepassxc.combinar_aqui()`).
    --vigilar-llavero
        El vigilante del llavero: atiende la base mientras viva el KeePassXC
        de la unidad, si no lo hace ya el servicio o el agente. Lo arranca
        «Abrir llavero».

Con llavero (`[keychain]`), el servicio también lo atiende: una pasada en cada
ciclo y, entre ciclos, la vigilancia de la base (`common/llavero.py`): lo que
se guarda sube a los 20 s, y lo de otro dispositivo llega cada 5 min mientras
KeePassXC está abierto.
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
from common import APP_NAME, keepassxc, llavero, model, store, update  # noqa: E402
from common.store import pid_alive  # noqa: E402
from ui import prefs  # noqa: E402

SELF = Path(__file__).resolve()
SENTINEL = model.CONFIG_FILE
"""Fichero cuya presencia dice que el dispositivo está conectado."""
LOCK = model.daemon_lock()
"""Registro del servicio: quién es."""
STOP = model.STATE_DIR / "daemon.stop"
"""Fichero que, si existe, le pide al servicio que pare."""
DLOG = model.STATE_DIR / "daemon.log"
"""Diario del servicio."""
UI_LOCK = model.ui_lock()
"""Registro de la ventana abierta: quién la tiene."""

POLL_SECONDS = 2.0
"""Cada cuántos segundos mira el servicio si debe parar o si se fue el dispositivo."""
STOP_WAIT_SECONDS = 15.0
"""Segundos que espera el lanzador a que pare el servicio anterior."""
DLOG_MAX_BYTES = 256 * 1024
"""Tamaño del diario a partir del cual `dlog` lo recorta."""
HOST = prefs.HOST

CREATE_NO_WINDOW = model.CREATE_NO_WINDOW
CREATE_NEW_PROCESS_GROUP = model.CREATE_NEW_PROCESS_GROUP
"""Flag de creación de procesos de Windows: grupo propio para el servicio."""


def pen_present() -> bool:
    """Indica si el dispositivo está conectado (se ve su fichero de config)."""
    try:
        return SENTINEL.exists()
    except OSError:
        return False


def read_lock() -> dict | None:
    """Devuelve el registro del servicio, o `None` si no hay."""
    return store.read_json(LOCK) or None


def write_lock(data: dict) -> None:
    """Escribe el registro del servicio."""
    store.write_json(LOCK, data)


def _lock_mio(info: dict | None) -> bool:
    """Indica si el registro es de este proceso."""
    return bool(info) and info.get("pid") == os.getpid() and info.get("host") == HOST


def dlog(msg: str) -> None:
    """Añade una línea con la hora al diario del servicio.

    Abre y cierra el fichero en cada línea para no mantener ningún descriptor
    abierto sobre el dispositivo: bloquearía su extracción segura. Pasado
    `DLOG_MAX_BYTES`, se queda con las últimas 300 líneas.
    """
    line = f"{store.stamp()} {msg}\n"
    try:
        if DLOG.exists() and DLOG.stat().st_size > DLOG_MAX_BYTES:
            tail = DLOG.read_text(encoding="utf-8", errors="replace").splitlines()[-300:]
            DLOG.write_text("\n".join(tail) + "\n", encoding="utf-8")
        with DLOG.open("a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass  # dispositivo ausente o de solo lectura: el diario no es vital


ESPERA_REGISTRO = 1.0
"""Segundos que se dan a quien acaba de crear el registro para llenarlo."""


def _leer_ui() -> dict | None:
    """Lee el registro de la ventana tal como está.

    Quien toma el registro lo crea y LUEGO lo llena (ver `tomar_ui`): un
    fichero vacío puede ser el de otra ventana a medio escribir y no un resto,
    así que se espera `ESPERA_REGISTRO` antes de darlo por ilegible.

    Returns:
        `None` si no hay registro, `{}` si lo hay y no se entiende.
    """
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
    """Indica si el registro es de una ventana viva EN ESTE EQUIPO.

    Mismo criterio que el registro del servicio: un pid muerto o de otro
    anfitrión es rastro de un dispositivo extraído sin cerrar nada. El fichero
    viaja con el dispositivo, así que el pid de otra máquina aquí no significa
    nada.
    """
    if not info:
        return False
    try:
        pid = int(info.get("pid", -1))
    except (TypeError, ValueError):
        pid = -1
    return info.get("host") == HOST and pid_alive(pid)


def _crear_exclusivo(ruta: Path, datos: bytes) -> bool | None:
    """Crea `ruta` con `datos` solo si no existe.

    `O_EXCL` es lo que lo hace un cerrojo: de dos que lo intentan a la vez solo
    uno lo crea. `store.write_json` no sirve: escribe a un temporal y renombra,
    y el renombrado pisa lo que haya.

    Returns:
        `True` si lo ha creado, `False` si ya estaba, `None` si no se puede
        escribir (dispositivo de solo lectura o ya extraído).
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
        pass                            # vacío también cuenta como tomado
    finally:
        os.close(fd)
    return True


def _borrar(ruta: Path) -> bool:
    """Borra `ruta` aunque otro proceso la esté leyendo.

    En Windows no se puede borrar un fichero abierto por otro (WinError 32) y,
    con varios runsync mirando el registro a la vez, el primer intento falla
    casi siempre: se reintenta hasta `ESPERA_REGISTRO`.

    Returns:
        `True` si ya no está.
    """
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


ROMPER_ABANDONADO = 5.0
"""Segundos tras los que un «romper» se da por de un proceso que murió dentro."""


def _retirar_ui(visto: dict | None) -> bool:
    """Quita el resto `visto` del registro si sigue siendo ese.

    Borrar a secas no vale: entre leer el resto y borrarlo, otra ventana puede
    haberlo retirado y haber tomado el suyo. Retirar pide antes otro cerrojo
    exclusivo, `ui.lock.json.romper`, que se tiene unos milisegundos: con él
    puesto se vuelve a leer y solo se borra si sigue el mismo resto. Nadie más
    lo borra mientras tanto (su dueño está muerto o en otro equipo) y crear el
    cerrojo exige que no esté.

    Un «romper» más viejo que `ROMPER_ABANDONADO` es de un proceso que murió
    con él puesto y se quita. Eso deja un hueco (dos que lo vean viejo a la
    vez), pero exige morir en esos milisegundos Y dos ventanas a la vez: no
    merece más maquinaria.

    Returns:
        `True` si lo ha quitado.
    """
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
    """Devuelve el registro de una ventana de runsync viva EN ESTE EQUIPO, o `None`.

    Solo mira: retira el resto de una ventana muerta o de otro equipo, pero no
    toma nada. Para abrir una ventana, `tomar_ui()`.
    """
    info = _leer_ui()
    if info is None:
        return None
    if not _viva_aqui(info):
        _retirar_ui(info)
        return None
    return info


def tomar_ui() -> dict | None:
    """Apunta que esta ventana es la de este dispositivo, si nadie la tiene.

    Mirar y escribir son UN paso: el fichero se crea con `O_EXCL`
    (`_crear_exclusivo`). Como dos pasos, el 28/09/2026 dos ventanas lanzadas
    con 6 s de diferencia miraron las dos antes de que ninguna escribiera y se
    abrieron a la vez.

    Si hay un resto (pid muerto, otro equipo, ilegible) se retira y se
    reintenta una sola vez: si otra ventana se ha adelantado, manda esa.

    Si no se puede escribir (dispositivo de solo lectura) o el resto no se deja
    quitar, la ventana se abre igual: el registro es para que la SIGUIENTE no
    se abra encima, no un permiso para abrir esta.

    Returns:
        `None` si la ha tomado; si no, el registro de la ventana que la tiene.
    """
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
    """Suelta el registro si sigue siendo el nuestro.

    Si otro lo ha tomado ya (el dispositivo se extrajo y se volvió a enchufar),
    no es nuestro para borrarlo.
    """
    info = store.read_json(UI_LOCK)
    if info.get("pid") == os.getpid() and info.get("host") == HOST:
        UI_LOCK.unlink(missing_ok=True)


def vigilante_instalado() -> bool:
    """Indica si este equipo tiene un arranque automático para este dispositivo.

    Solo sirve para decirlo en un mensaje: va bajo `except` porque penwatch es
    un script hermano que puede no importarse, y no saberlo no es motivo para
    no abrir la ventana.
    """
    try:
        from ui import watch
        return watch.resumen().vigila_este
    except Exception:                                   # noqa: BLE001
        return False


def agente_sirve() -> bool:
    """Indica si el servicio de esta raíz es el agente residente.

    Vivo y en modo `daemon` (`watch.Resumen.servicio_del_agente`); va bajo
    `except` por lo mismo que `vigilante_instalado`.
    """
    try:
        from ui import watch
        return watch.resumen().servicio_del_agente
    except Exception:                                   # noqa: BLE001
        return False


def pedir_reanudar() -> bool:
    """Deja `reanudar` en el buzón de esta raíz (`state/servicio.pide`).

    Es «Iniciar servicio» cuando el servicio es el agente: también le quita a
    la raíz el «Pausar» de su ventana. Punto de indirección: los tests la
    sustituyen.

    Returns:
        Si se pudo dejar el pedido.
    """
    from common import equipo
    from ui import watch
    return watch.pedir_a_la_raiz({"pide": equipo.PIDE_REANUDAR})


def stop_previous_daemon() -> str | None:
    """Pide parar al servicio registrado y espera a que pare.

    Con el agente residente como servicio no se dice nada: suelta la unidad
    mientras haya una ventana abierta y vuelve al cerrarla, y eso ya lo cuenta
    el botón «Cambiar…» de su línea en la ventana.

    Returns:
        El mensaje para la persona, o `None` si no había nada que decir (ni
        servicio registrado, ni el agente soltando la unidad).
    """
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
            if info.get("agente"):
                return None
            return f"Servicio anterior (pid {pid}) detenido."
        time.sleep(0.3)

    # No ha contestado a tiempo: probablemente está en mitad de una pareja. Se
    # le deja el `daemon.stop` (parará al terminarla). El lock del agente se
    # queda: lo suelta él al acabar la pareja y mientras lo tenga ningún
    # servicio nuevo lo toma (`tomar_lock()` espera), así que no hay dos
    # pasadas a la vez. El de un servicio de runsync se libera, como siempre.
    if info.get("agente"):
        return (f"El agente de este equipo está a mitad de una pareja; deja de "
                f"sincronizar {que} en cuanto la acabe.")
    LOCK.unlink(missing_ok=True)
    return (f"El servicio (pid {pid}) está ocupado (¿sincronización en curso?); "
            f"parará al terminar la pareja actual.")


def servicio_en_marcha() -> dict | None:
    """Devuelve el registro del servicio si es de un proceso vivo de ESTE equipo.

    Si no, `None`. Solo lee: limpiar lo rancio es de `stop_previous_daemon()`,
    que es quien lo va a sustituir.
    """
    info = read_lock()
    if info is None or info.get("host") != HOST:
        return None
    try:
        pid = int(info.get("pid", -1))
    except (TypeError, ValueError):
        return None
    return info if pid_alive(pid) else None


def stop_requested() -> bool:
    """Indica si hay una petición de parada (existe `daemon.stop`)."""
    try:
        return STOP.exists()
    except OSError:
        return False


def run_pair_quiet(name: str) -> tuple[int, str]:
    """Ejecuta `sync.py` para una pareja, sin terminal.

    Con stdin cerrado, las preguntas de `sync.py` toman su valor por defecto:
    una pareja que requiera `--resync` se SALTA (a propósito: un resync no se
    lanza solo).

    Returns:
        `(código_de_salida, salida)`.
    """
    proc = subprocess.run(
        [sys.executable, str(model.SYNC_PY), name],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        # `sync.py` escribe UTF-8 (ver su `main()`): sin decirlo, las tildes
        # llegarían rotas a `daemon.log`.
        encoding="utf-8",
        errors="replace",
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def notificar_fallo(nombres: list[str]) -> None:
    """Enseña que ha fallado un ciclo, con una ventanita del propio servicio.

    Es `ui.avisar_fallo`, en el mismo intérprete y sin lanzar nada. Sin
    pantalla (un servicio de systemd sin DISPLAY, por ejemplo) el aviso se
    queda en el diario. Punto de indirección: los tests la sustituyen.

    Args:
        nombres: Las parejas que fallan.
    """
    if ui.avisar_fallo(nombres):
        dlog(f"aviso de fallo en pantalla: {', '.join(nombres)}")
    else:
        dlog("no hay entorno gráfico: el aviso de fallo queda solo en este diario")


def daemon_cycle(pairs: list[str], lock_data: dict) -> None:
    """Hace un ciclo del servicio: una pasada de cada pareja.

    Apunta `last_cycle` y `last_results` en el registro y avisa solo si alguna
    EMPIEZA a fallar. Corta si se pide parada o desaparece el dispositivo.

    Args:
        pairs: Las parejas a sincronizar.
        lock_data: El registro propio, que se reescribe con el resultado.
    """
    previos = lock_data.get("last_results") or {}
    results = {}
    for name in pairs:
        if stop_requested() or not pen_present():
            return
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
        # Solo si sigue siendo nuestro: si el lanzador lo borró o lo tiene ya
        # otro servicio, reescribirlo sería quitárselo.
        write_lock(lock_data)

    # Solo cuando algo EMPIEZA a fallar: un servicio sano no dice nada, y uno
    # que lleva horas sin red no abre una ventana cada media hora (la ventana
    # principal lo sigue enseñando hasta que se arregle).
    fallidas = [n for n, r in results.items() if r.startswith("ERROR")]
    if any(not str(previos.get(n, "")).startswith("ERROR") for n in fallidas):
        notificar_fallo(fallidas)

    # De paso, refresca la caché de versiones (a lo sumo una consulta al día,
    # por `CACHE_HORAS`): es lo único que la mantiene al día para el menú de
    # consola, que nunca va a la red por su cuenta. El servicio no tiene
    # interfaz: solo lo apunta.
    try:
        update.check()                  # respeta la caché: no sale cada ciclo
        nueva = update.pending()
        if nueva is not None:
            dlog(f"hay una versión nueva disponible: {nueva.tag}")
    except Exception as e:                              # noqa: BLE001
        dlog(f"no he podido mirar si hay versión nueva: {e}")


def pareja_llavero() -> model.Pair | None:
    """Devuelve la pareja del llavero de este dispositivo, o `None` si no lo lleva.

    Un config que no se lee es «sin llavero»: el servicio sigue con las suyas.
    """
    try:
        return model.load_config().pareja_llavero
    except model.ConfigError:
        return None


def pasada_llavero(v: llavero.Vigilancia, pareja: model.Pair, por: str) -> int:
    """Hace una pasada del llavero y apunta en `v` cómo ha quedado.

    Args:
        v: Lo que se sabe de la base.
        pareja: La pareja del llavero.
        por: Por qué, para el diario.

    Returns:
        El código de `sync.py`.
    """
    v.empieza_pasada(time.monotonic())
    t0 = time.monotonic()
    rc, salida = run_pair_quiet(model.LLAVERO)
    if rc == 0:
        dlog(f"[llavero] OK ({por}, {time.monotonic() - t0:.0f}s)")
    else:
        dlog(f"[llavero] FALLÓ (rc={rc}, {por}); salida:")
        for linea in salida.splitlines()[-8:]:
            dlog(f"[llavero]   {linea}")
    v.acaba_pasada(llavero.huella(pareja.local_abs), time.monotonic(),
                   llavero.pendiente(pareja), rc == 0)
    return rc


def atender_llavero(v: llavero.Vigilancia, pareja: model.Pair) -> None:
    """Hace un paso de la vigilancia del llavero: una foto si toca y la pasada si toca.

    Lo usan la espera del servicio entre ciclos y el vigilante del llavero.
    """
    ahora = time.monotonic()
    if v.toca_mirar(ahora):
        primera = v.foto is None
        v.abierto = llavero.keepassxc_abierto()
        v.observar(llavero.huella(pareja.local_abs), ahora,
                   primera and llavero.pendiente(pareja))
    motivo = v.motivo(ahora, v.abierto)
    if motivo == "cambios":
        pasada_llavero(v, pareja, "cambios en la base")
    elif motivo == "remoto":
        pasada_llavero(v, pareja, "lo de otro dispositivo, con KeePassXC abierto")


ARRANQUE_KEEPASSXC = 30.0  # segundos
"""Lo que el vigilante espera a ver el KeePassXC de la unidad antes de darlo por cerrado."""


def vigilar_llavero() -> int:
    """Hace `--vigilar-llavero`: atiende el llavero mientras viva el KeePassXC de la unidad.

    Lo arranca «Abrir llavero» cuando no hay servicio que lo atienda. Uno a la
    vez (`llavero.registro_vigilante()`, tomado con `O_EXCL`). Para cuando el
    servicio o el agente se quedan la raíz, cuando se pide
    (`llavero.parada_vigilante()`, «Expulsar»), cuando desaparece el
    dispositivo y cuando KeePassXC se cierra; en este último caso hace antes
    la pasada que quede pendiente. Corre fuera del dispositivo (cwd en el
    temporal), así que no retiene el volumen.
    """
    os.chdir(tempfile.gettempdir())
    pareja = pareja_llavero()
    if pareja is None:
        return 0
    registro = llavero.registro_vigilante()
    datos = {"pid": os.getpid(), "host": HOST, "started": store.stamp()}
    tomado, otro = store.tomar_registro(registro, datos, _viva_aqui)
    if tomado is False:
        return 0                        # ya hay un vigilante
    llavero.parada_vigilante().unlink(missing_ok=True)
    dlog("[llavero] vigilante iniciado")
    v = llavero.Vigilancia()
    limite = time.monotonic() + ARRANQUE_KEEPASSXC
    visto = False
    fin = "desconocido"
    try:
        while True:
            if not pen_present():
                fin = "dispositivo no conectado"
                # En Linux su KeePassXC no muere con la unidad (corre extraído
                # en el equipo): se le pide que se cierre, como el agente.
                if os.name != "nt" and keepassxc.cerrar_huerfano():
                    fin += "; se le pide a KeePassXC que se cierre"
                break
            if llavero.parada_vigilante().exists():
                fin = "parada pedida"
                break
            if llavero.atiende_el_servicio():
                fin = "lo atiende el servicio de la raíz"
                break
            atender_llavero(v, pareja)
            visto = visto or v.abierto
            if not v.abierto and (visto or time.monotonic() > limite):
                if llavero.pendiente(pareja):
                    pasada_llavero(v, pareja, "al cerrar KeePassXC")
                fin = "KeePassXC cerrado"
                break
            time.sleep(POLL_SECONDS)
    finally:
        dlog(f"[llavero] vigilante detenido: {fin}")
        info = store.read_json(registro)
        if info.get("pid") == os.getpid() and info.get("host") == HOST:
            registro.unlink(missing_ok=True)
        llavero.parada_vigilante().unlink(missing_ok=True)
    return 0


def abrir_llavero() -> int:
    """Hace `--llavero`: «Abrir llavero» sin la ventana de prdrive.

    No para el servicio, a diferencia de abrir la ventana: el llavero no le
    estorba, y si está en marcha es él quien lo atiende.
    """
    try:
        config = model.load_config()
    except model.ConfigError as e:
        return ui.fatal(f"El config no se puede leer:\n\n{e}")
    return ui.abrir_llavero(config)


def cerrar_llavero(preguntar=input) -> int:
    """Hace `--cerrar-llavero`, en la consola de «Expulsar PRDRIVE.bat» o lanzado por el agente.

    Si el KeePassXC de la unidad está abierto, pregunta antes de cerrarlo; sin
    nadie que conteste (sin consola, o el agente antes de «Bloquear» una raíz
    cifrada del equipo), lo cierra, y si tiene algo sin guardar pregunta él. Lo
    demás no dice nada si va bien.

    Args:
        preguntar: Lo que pregunta (`input`).

    Returns:
        0 si se puede desmontar; 1 si KeePassXC sigue abierto.
    """
    try:
        config = model.load_config()
    except model.ConfigError:
        return 0                            # sin config no hay llavero que cerrar
    if config.pareja_llavero is None:
        return 0
    programas, _ = keepassxc.procesos_de_la_unidad()
    if programas:
        try:
            respuesta = preguntar("KeePassXC está abierto. ¿Cerrarlo? [S/n] ")
        except (EOFError, OSError, RuntimeError):
            # Sin nadie que conteste: sin consola, o lanzado por el agente al
            # «Bloquear» (con pythonw, `input()` no tiene de dónde leer).
            respuesta = ""
        if str(respuesta).strip().lower() in ("n", "no"):
            print("KeePassXC sigue abierto: no se cierra la unidad.")
            return 1
        print("Cerrando KeePassXC: si tiene algo sin guardar, te lo pregunta.")
    try:
        cierre = keepassxc.cerrar_llavero(config)
    except Exception as e:                              # noqa: BLE001
        # Un fallo aquí no puede impedir expulsar: si algo sigue abierto,
        # VeraCrypt lo dice al desmontar.
        print(f"No se ha podido cerrar el llavero del todo ({e}); se sigue expulsando.")
        return 0
    for linea in cierre.lineas:
        print(linea)
    return 0 if cierre.listo else 1


def combinar_llavero(rest: list[str]) -> int:
    """Hace `--combinar-llavero BASE COPIA [--keyfile LLAVE] [--codigo FICHERO]`.

    Es la consola que abre «Combinar»: `keepassxc.combinar_aqui()`, donde
    `keepassxc-cli merge` pide la contraseña de la base. Con `--codigo` (la
    terminal de Linux, que no devuelve el código de lo que corre) apunta su
    pid al empezar y su código al acabar, para quien espera
    (`keepassxc.esperar_codigo()`).
    """
    opciones: dict[str, Path] = {}
    while len(rest) >= 4 and rest[-2] in ("--keyfile", "--codigo") and rest[-2] not in opciones:
        opciones[rest[-2]], rest = Path(rest[-1]), rest[:-2]
    if len(rest) != 2:
        return ui.fatal("--combinar-llavero necesita la base y la copia.")
    codigo = opciones.get("--codigo")
    if codigo is not None:
        keepassxc.apuntar_codigo(codigo)
    rc = 2
    try:
        rc = keepassxc.combinar_aqui(Path(rest[0]), Path(rest[1]), opciones.get("--keyfile"))
    finally:
        if codigo is not None:
            keepassxc.apuntar_codigo(codigo, rc)
    return rc


ESPERA_AGENTE = 30 * 60
"""Segundos que el servicio espera a que el agente suelte la unidad."""


def tomar_lock(lock_data: dict) -> dict | None:
    """Apunta que este proceso es el servicio del dispositivo, si no lo es otro.

    Mirar y escribir son UN paso (`store.tomar_registro()`, O_EXCL) y el agente
    del equipo toma el mismo fichero igual: escribirlo sin mirar dejaba que el
    agente y este servicio se creyeran los dos el servicio y sincronizaran a la
    vez. Si lo tiene el agente se le pide que se aparte, como hace el lanzador
    (`daemon.stop`), y se espera a que acabe su pareja: se aparta y borra el
    stop. Si lo tiene otro servicio de runsync, manda ese.

    Returns:
        `None` si lo ha tomado (o no se puede escribir); si no, el registro del
        servicio vivo que lo tiene.
    """
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


def daemon_main(pairs: list[str], interval_min: float) -> int:
    """Es el servicio: sincroniza las parejas cada `interval_min` hasta que le paren.

    Se detiene al desaparecer el dispositivo, al pedirlo el lanzador
    (`daemon.stop`) o cuando otro servicio se queda el registro.

    Args:
        pairs: Las parejas a sincronizar.
        interval_min: Minutos entre ciclos.
    """
    # Fuera del dispositivo: un cwd en el USB impediría su extracción segura.
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
    llave = pareja_llavero()
    v = llavero.Vigilancia()
    dlog(f"servicio iniciado: pid={os.getpid()} host={HOST} "
         f"parejas={','.join(pairs)} intervalo={interval_min:g}m"
         + (" y el llavero" if llave is not None else ""))

    reason = "desconocido"
    try:
        while True:
            if not pen_present():
                reason = "dispositivo no conectado"
                break
            if stop_requested():
                reason = "parada solicitada por el lanzador"
                break
            daemon_cycle(pairs, lock_data)
            if llave is not None and not stop_requested() and pen_present():
                pasada_llavero(v, llave, "ciclo del servicio")
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
                    # arrancó otro servicio (que borra el stop que iba para
                    # nosotros): el que está ahí es el servicio, y dos a la vez
                    # no puede ser.
                    reason, stop = f"otro servicio (pid {otro.get('pid')}) tiene el registro", True
                    break
                if llave is not None:
                    atender_llavero(v, llave)
                time.sleep(POLL_SECONDS)
            if stop:
                break
    finally:
        dlog(f"servicio detenido: {reason}")
        # Solo lo propio: si el lanzador ya robó el lock y hay un servicio
        # nuevo, su registro no se toca.
        info = read_lock()
        if info and info.get("pid") == os.getpid() and info.get("host") == HOST:
            LOCK.unlink(missing_ok=True)
        STOP.unlink(missing_ok=True)
    return 0


def spawn_daemon(pairs: list[str], interval_min: float) -> str:
    """Lanza el servicio en un proceso aparte y devuelve el mensaje que lo confirma.

    En Windows con `pythonw` y sin consola; en POSIX, en sesión propia.
    """
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
    """Ejecuta `sync.py` en la consola actual, heredando stdin y stdout.

    Las preguntas de `sync.py` llegan a quien teclea.

    Returns:
        El código de salida de `sync.py`.
    """
    return subprocess.run([sys.executable, str(model.SYNC_PY), *extra_args]).returncode


def ui_flow() -> int:
    """Hace el camino sin argumentos: para el servicio anterior, pregunta y obedece."""
    # Lo PRIMERO, antes de parar nada: abrir runsync detiene el servicio
    # anterior, así que una segunda ventana mataría el que acaba de arrancar la
    # primera. Mirar y tomar el registro son un solo paso (`tomar_ui`).
    abierta = tomar_ui()
    if abierta is not None:
        return ui.fatal(
            f"Ya hay una ventana de {APP_NAME} abierta para este dispositivo "
            f"(pid {abierta.get('pid')}, desde las {abierta.get('started', '?')}).\n"
            "Usa esa; si no la encuentras, ciérrala desde el administrador de "
            "tareas y vuelve a intentarlo.")

    try:
        startup_msg = stop_previous_daemon()

        try:
            config = model.load_config()
        except model.ConfigError as e:
            return ui.fatal(str(e))

        return _atender(config, startup_msg)
    finally:
        soltar_ui()


def _atender(config: model.Config, startup_msg: str | None) -> int:
    """Pregunta qué hacer y lo hace.

    Está aparte de `ui_flow()` para que el registro de la ventana se suelte
    pase lo que pase, incluida una elección que arranca el servicio y se va.

    Args:
        config: La configuración del dispositivo.
        startup_msg: Lo que dijo la parada del servicio anterior, si dijo algo.
    """
    choice, frontend = ui.start(config, startup_msg)
    if choice is None:
        return 0

    if choice.action == "daemon":
        # Es la configuración del servicio (precarga la próxima ventana y la
        # usa `--auto`): las parejas solo se guardan aquí, una pasada manual
        # con unas pocas parejas no decide qué sincroniza el servicio. El
        # intervalo de la ventana es el ya guardado («Ajustes →
        # Configuración»); el de la consola, el que se teclea (ver `ui/prefs.py`).
        prefs.save_prefs(choice.action, list(choice.pairs), choice.minutes,
                         config.names)
        if agente_sirve() and pedir_reanudar():
            # El servicio de esta raíz ya es el agente residente: arrancar otro
            # solo lo apartaría. Lee lo que se acaba de guardar y vuelve en
            # cuanto se suelte la ventana. Desde la ventana no se llega aquí
            # (ofrece «Reanudar»), salvo que el agente arrancara con ella
            # abierta; desde la consola, sí.
            que, lo = (("esta carpeta", "la") if model.es_equipo()
                       else ("este dispositivo", "lo"))
            frontend.info(f"El agente de este equipo es el servicio de {que}: vuelve "
                          f"a sincronizar{lo} en cuanto salgas, "
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

    # `manual` solo llega desde el menú de consola: la ventana sincroniza sin
    # cerrarse.
    args = ui.manual_args(config, choice.pairs, frontend.approve_resync)
    return frontend.run_sync("Sincronización manual", args)


def auto_start(rest: list[str]) -> int:
    """Hace `--auto`: arranca el servicio sin UI, para quien lo lanza sin nadie delante.

    Lo lanzan `penwatch.py`, un acceso directo o cron. Las parejas y el
    intervalo son los del servicio (`prefs.startup_defaults`) o, si no hay, los
    de `[daemon]` del TOML; lo indicado aquí manda sobre ambos. Solo lee esa
    memoria: un arranque automático nunca reescribe lo decidido a mano. Para
    antes el servicio anterior, si lo hubiera. Con `--once` no hay servicio
    (ver `una_pasada`).

    Args:
        rest: Lo que sigue a `--auto`: `--interval N`, `--once` y parejas.
    """
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

    # También lo lanzan un acceso directo o un cron: arrancar el servicio tras
    # una ventana abierta pondría dos cosas a sincronizar las mismas parejas.
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
    """Hace `--auto --once`: las parejas del servicio, una vez, sin servicio detrás.

    Es el modo `sync` del vigilante. Con un servicio vivo en este equipo no
    hace nada: una pasada al lado del servicio chocaría con el lock de bisync.
    Y NO lo para, a diferencia de `--auto`: cambiar un servicio por una sola
    pasada dejaría el dispositivo sin servicio.

    `sync.py` hereda entrada y salida. Sin terminal (así lo lanza el
    vigilante), una pareja que pide `--resync` se salta, y la salida va a su
    diario.
    """
    servicio = servicio_en_marcha()
    if servicio is not None:
        msg = (f"El servicio periódico ya está en marcha (pid {servicio.get('pid')}): "
               "no lanzo otra pasada.")
        print(msg)
        dlog(f"--auto --once: {msg}")
        return 0
    if pareja_llavero() is not None:
        pairs = [*pairs, model.LLAVERO]
    dlog(f"--auto --once: una pasada de {', '.join(pairs)}")
    return run_interactive(pairs)


def main() -> int:
    """Despacha según los argumentos: `--auto`, `--daemon`, `sync.py` o la UI.

    Returns:
        El código de salida.
    """
    args = sys.argv[1:]

    if args and args[0] == "--auto":
        return auto_start(args[1:])

    if args == ["--vigilar-llavero"]:
        return vigilar_llavero()

    if args == ["--llavero"]:
        return abrir_llavero()

    if args == ["--cerrar-llavero"]:
        return cerrar_llavero()

    if args and args[0] == "--combinar-llavero":
        return combinar_llavero(args[1:])

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
        # Passthrough (`runsync.bat --doctor`, `obsidian --resync`…). También
        # para el servicio: va a tocar el mismo estado.
        msg = stop_previous_daemon()
        if msg:
            print(msg)
        return run_interactive(args)

    return ui_flow()


if __name__ == "__main__":
    raise SystemExit(main())
