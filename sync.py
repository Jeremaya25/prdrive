#!/usr/bin/env python3
"""Sincronización portable entre un remoto de rclone y un dispositivo local.

Todo vive en el dispositivo y no depende de nada instalado en la máquina salvo
Python 3.11+ (para `tomllib`). El binario de rclone es portable (carpeta
`bin/`).

    common/model.py   el TOML convertido en objetos ya resueltos
    common/bisync.py  lo que replica el comportamiento interno de rclone bisync
    ui/               la ventana y el menú de consola (los usa runsync.py)
    sync.py           este fichero: construir el comando, ejecutarlo y contarlo

Estructura en el dispositivo:

    PEN/
    ├── .prdrive/
    │   ├── sync.py            <- este script
    │   ├── common/            <- config, bisync y ficheros de estado
    │   ├── ui/                <- la interfaz (la usa runsync.py)
    │   ├── sync_config.toml   <- qué carpetas sincronizar y en qué dirección
    │   ├── rclone.conf        <- config de rclone (remote SFTP + ruta a la clave)
    │   ├── bin/<arch>/        <- binario portable de rclone (Windows y Linux)
    │   ├── keys/              <- clave privada SSH (el dispositivo ya va cifrado)
    │   ├── filters/<pareja>.txt     <- filtros generados desde el TOML (+ su .md5)
    │   ├── state/<pareja>/    <- workdir de bisync, UNO POR PAREJA
    │   └── logs/              <- solo logs de ejecuciones fallidas
    └── sync-data/             <- aquí viven las carpetas locales que se sincronizan

Uso:

    python sync.py                 # ejecuta todas las parejas del config
    python sync.py obsidian fotos  # solo esas parejas
    python sync.py --list          # lista las parejas configuradas
    python sync.py --doctor        # diagnostica el estado de bisync y sale
    python sync.py --dry-run       # simula, no toca nada (úsalo SIEMPRE la 1a vez)
    python sync.py --resync        # rehace el baseline de bisync (1a vez o si se rompe)
    python sync.py notas --force   # salta el freno de borrados SOLO en esta pasada de «notas»
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Mapping

from common import (bisync, cifrada, conflicts, fleet, frenos, historial, llavero, model,
                    moderacion, orden, parte, progress, results, revision, store)
from common.model import Config, Pair

LOG_TAIL_LINES = 15
"""Líneas de log que se vuelcan a consola cuando algo falla."""
SKIPPED = -1
"""Código interno: pareja no ejecutada (ni OK ni fallo)."""
LLAVERO_ROTO = 2
"""Código del llavero cuando una base no está entera y la pasada no corre.

Es el «error sin clasificar» de rclone: cuenta como fallo, y la próxima pasada
lo vuelve a intentar.
"""
LLAVERO_SIN_CIFRAR = 3
"""Código del llavero sin contraseña en un dispositivo que no está cifrado: la pasada no corre.

Sin cifrar, la llave estaría junto a la base: no se baja ni se sube nada.
Cuenta como fallo, y la próxima pasada lo vuelve a comprobar.
"""
CONFLICTS_SHOWN = 5
"""Ficheros en conflicto que se nombran en la salida."""
SIMULADOS_SHOWN = 20
"""Ficheros que una simulación forzada nombra; del resto solo se dice cuántos son."""
PROGRESS_POLL_S = 0.5
"""Cada cuántos segundos se mira si rclone ha escrito más en su log."""
LOGS_POR_PAREJA = 20
"""Logs de pasadas fallidas que se conservan en `logs/` por pareja.

Una pareja que falla cada media hora deja 48 al día: sin tope, `logs/` crecería
sin fin en el dispositivo. Los veinte más nuevos bastan para ver cómo falla.
"""

DIRECT_OUTPUT_HEADER = "--- salida directa de rclone (no pasó por --log-file) ---"
"""Cabecera que marca, en el log, lo que rclone sacó por consola.

Es lo que no llegó a `--log-file` (ver `append_output()`).
"""

KNOWN_ERRORS = [
    (bisync.MISSING_LISTINGS,
     "No hay baseline: primera vez, listados en otro sitio (¿cambió la ruta?) o "
     "un fallo crítico previo los invalidó. Solución: --resync."),
    ("filters file has changed",
     "Han cambiado los filtros. Solución: --resync (bisync no puede saber qué "
     "ficheros excluidos existían antes)."),
    ("filters file md5 hash not found",
     "Primer uso de este fichero de filtros. Solución: --resync."),
    ("must run --resync",
     "bisync ha invalidado el baseline y exige rehacerlo. Solución: --resync."),
    # Los frenos de borrado, que reconoce `common/frenos.py` (lo comparte con el
    # diagnóstico de «Reparación»). Son dos y no se miden igual: el de bisync es un
    # PORCENTAJE del listado anterior (`excessDeletes()`, cmd/bisync/deltas.go) y el
    # de un espejo una CUENTA de ficheros (ver `MODES` en `common/model.py`). Sus
    # agujas son exactas: la `--max-delete` a secas casaba también con
    # `--max-delete-size`, que es otro freno.
    *frenos.ENTRADAS,
    ("Access is denied",
     "Fichero bloqueado por otro proceso (Obsidian, KeePass, antivirus)."),
    # Lo que dice bisync al encontrar el lock de otra pasada
    # (cmd/bisync/lockfile.go, `setLockFile`). «lock file» a secas casaría
    # también con el «lock file renewed» de `--max-lock`.
    ("prior lock file found",
     "Hay un lock de otra ejecución. Si no hay ninguna corriendo, borra el .lck "
     "del workdir de la pareja."),
    # Lo que dice sftp cuando `knownhosts.New()` no puede abrir o leer el
    # fichero (`NewFs`, backend/sftp/sftp.go). «known_hosts_file» a secas
    # casaría también con el NOTICE «No host key validation is being
    # performed» de cada pasada a un remoto sin ese fichero.
    ("couldn't parse known_hosts_file",
     "rclone no puede leer el fichero de known_hosts indicado en rclone.conf "
     "(no existe o está mal formado). Las rutas relativas de rclone.conf se "
     "resuelven contra .prdrive/; comprueba que keys/known_hosts existe ahí."),
    # Sin conexión. Es una función y no una aguja porque el agente residente la
    # comparte y no lleva este fichero: la lista vive en
    # `common/moderacion.py`. Va antes de la siguiente, que suele acompañarla y
    # explica menos.
    (moderacion.es_de_red, moderacion.EXPLICACION_RED),
    ("Failed to create file system",
     "rclone no ha podido montar uno de los dos extremos. Suele ser una ruta o "
     "credencial mal resuelta en rclone.conf (revisa key_file y "
     "known_hosts_file), o el remoto inalcanzable."),
    # Errores de ARRANQUE: rclone rechaza la orden antes de instalar
    # `--log-file`. Van al final para que gane cualquier error ocurrido durante
    # la sincronización.
    ("unknown flag",
     "rclone no conoce uno de los flags. Está escrito en sync_config.toml (o en "
     "el editor de flags de la ventana de parejas): rclone lo rechaza antes de "
     "empezar, por eso no hay más log que este."),
    ("invalid argument",
     "rclone rechaza el VALOR de un flag: no es de los que admite (por ejemplo "
     "conflict-resolve = \"new\" cuando lo válido es \"newer\"). El mensaje de "
     "arriba enumera los buenos. Se corrige en sync_config.toml."),
]
"""Agujas de lo que dice rclone al fallar y su explicación; gana la primera que casa.

Una aguja es un texto o una función del log. Los casos nuevos se añaden aquí,
nunca en quien llama. Las entradas de flags (las de arranque) van al final: un
volcado de ayuda con esos nombres no puede explicar un fallo ajeno.
"""


def temp_log(name: str) -> Path:
    """Devuelve un log temporal del sistema donde escribe rclone.

    Solo se conserva (en `logs/`) si la ejecución falla: así una pasada buena
    no escribe en el dispositivo (menos ciclos de escritura) y `logs/` solo
    contiene lo que hay que mirar.
    """
    fd, path = tempfile.mkstemp(prefix=f"rclone-sync-{name}-", suffix=".log")
    os.close(fd)
    return Path(path)


def podar_logs(nombre: str, conservar: Path | None = None) -> None:
    """Deja en `logs/` solo los `LOGS_POR_PAREJA` logs más nuevos de una pareja.

    Los más nuevos son los del sello más alto del nombre
    (`<pareja>_AAAAMMDD_HHMMSS[_N].log`, con `N` como número), no los de mtime
    más reciente: copiar o tocar el dispositivo cambia la mtime de todos. Solo
    se mira lo que casa con ese nombre exacto, así que los logs de `a_b` no
    cuentan para `a`. Lo más viejo se borra; no lanza nunca, porque una poda
    que falla no puede estropear el guardado de un log (ni la pasada).

    Args:
        nombre: La pareja cuyos logs se podan.
        conservar: Un log que no se borra nunca y queda fuera del ranking (el
            que `keep_log()` acaba de guardar: con el reloj atrasado su sello
            sería más viejo que los de antes y se podaría a sí mismo). Cuenta
            en el tope: de los demás se quedan `LOGS_POR_PAREJA - 1`.
    """
    patron = re.compile(rf"^{re.escape(nombre)}_(\d{{8}})_(\d{{6}})(?:_(\d+))?\.log$")
    sellados = []
    try:
        for ruta in model.LOG_DIR.iterdir():
            m = patron.match(ruta.name)
            if m and ruta != conservar:
                sellados.append(((m[1], m[2], int(m[3] or 0)), ruta))
    except OSError:
        return
    sellados.sort(key=lambda s: s[0], reverse=True)
    quedan = LOGS_POR_PAREJA - (1 if conservar is not None else 0)
    for _, ruta in sellados[quedan:]:
        try:
            ruta.unlink(missing_ok=True)
        except OSError:
            pass            # con el dispositivo fuera tampoco se puede borrar


def keep_log(name: str, tmp: Path) -> Path:
    """Mueve un log temporal a `logs/` y devuelve dónde ha quedado.

    Va justo detrás de un fallo, que puede ser el dispositivo desaparecido a
    mitad de pasada (#36): si `logs/` no se deja crear o el log mover, se avisa
    en una línea y el log se queda en el temporal del sistema, que es la ruta
    devuelta (de ahí leen `print_log_tail` y `explain_failure`).

    Se captura `OSError` y no `PermissionError` (Windows: `[WinError 21]`): en
    otro sistema, o con el dispositivo lleno o de solo lectura, llega otro. El
    movimiento va dentro del `try` porque entre dos unidades `shutil.move`
    copia y borra al final: puede fallar con la copia a medias, y esa copia se
    quita. Una vez guardado el log, se podan los más viejos de la pareja
    (`podar_logs()`), sin tocar el que acaba de guardarse aunque su sello
    (hora local) sea más viejo que los de antes.
    """
    destino = None
    try:
        model.LOG_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        final = model.LOG_DIR / f"{name}_{stamp}.log"
        n = 1
        while final.exists():  # ejecución + reintento dentro del mismo segundo
            final = model.LOG_DIR / f"{name}_{stamp}_{n}.log"
            n += 1
        destino = final
        shutil.move(str(tmp), str(final))
        podar_logs(name, final)
        return final
    except OSError as e:
        motivo = e.strerror or str(e)
    # Solo con el temporal todavía ahí: si no, lo de logs/ sería la única copia.
    if destino is not None and tmp.exists():
        try:
            destino.unlink(missing_ok=True)
        except OSError:
            pass            # con el dispositivo fuera tampoco se puede borrar
    print(f"[{name}] AVISO: no he podido guardar el log en el dispositivo "
          f"({motivo}); está en {tmp}")
    return tmp


def strip_usage(text: str) -> str:
    """Quita el volcado de ayuda con el que rclone acompaña un error de flags.

    Ante un flag malo rclone escribe el error y la ayuda entera del subcomando
    (12 KB). Enterraría el mensaje en `print_log_tail` y, peor,
    `explain_failure` casaría agujas de `KNOWN_ERRORS` (`--max-delete`, `lock
    file`) dentro de la documentación: un diagnóstico falso, peor que ninguno.

    El bloque va de la línea `Usage:` a la última que empieza por `Use
    "rclone`; lo de fuera (`Error:` y `Fatal error:`) es lo que hay que leer.
    """
    lineas = text.splitlines()
    inicio = next((i for i, l in enumerate(lineas) if l.strip() == "Usage:"), None)
    if inicio is None:
        return text
    fin = max((i for i, l in enumerate(lineas) if l.strip().startswith('Use "rclone')),
              default=len(lineas) - 1)
    quedan = lineas[:inicio] + lineas[fin + 1:]
    return "\n".join(l for l in quedan if l.strip())


def append_output(logfile: Path, text: str) -> None:
    """Añade al log lo que rclone haya escrito por consola.

    Con `--log-file`, rclone solo registra desde que lo instala: lo que falla
    ANTES (un flag que no existe, un valor que no admite) sale por stderr y
    dejaba el log vacío, sin nada que enseñar ni reconocer. Va marcado con
    `DIRECT_OUTPUT_HEADER` porque no son líneas de log de rclone (sin fecha ni
    nivel).
    """
    limpio = strip_usage(text)
    if not limpio.strip():
        return
    tenia = logfile.exists() and logfile.stat().st_size > 0
    with logfile.open("a", encoding="utf-8", errors="replace") as f:
        if tenia:
            f.write("\n")
        f.write(DIRECT_OUTPUT_HEADER + "\n")
        f.write(limpio if limpio.endswith("\n") else limpio + "\n")


def dispose_log(name: str, tmp: Path, rc: int, keep_always: bool) -> Path | None:
    """Descarta el log si la ejecución fue bien; si no, lo guarda en `logs/`."""
    if rc == 0 and not keep_always:
        tmp.unlink(missing_ok=True)
        return None
    return keep_log(name, tmp)


def print_log_tail(lpath: Path | None, lines: int = LOG_TAIL_LINES) -> None:
    """Imprime las últimas líneas del log, sin las estadísticas de progreso."""
    if lpath is None:
        return
    try:
        if not lpath.exists():
            return
        todas = lpath.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as e:
        # Dispositivo ido justo después de guardar el log (#36): un VeraCrypt
        # desenchufado sin expulsar acepta escrituras en caché y luego no deja
        # leer. Una línea, no un traceback.
        print(f"  (no he podido leer {lpath}: {e.strerror or e})")
        return
    # Sin las estadísticas: llenarían las líneas de números y dejarían el error
    # fuera.
    tail = [linea for linea in todas if progress.leer(linea) is None][-lines:]
    print(f"--- últimas {len(tail)} líneas de {lpath.name} ---")
    for line in tail:
        print("  " + line)
    print("---")


def explain_failure(lpath: Path | None, pair: Pair | None = None) -> None:
    """Traduce el error de rclone a algo accionable.

    Los casos nuevos se añaden a `KNOWN_ERRORS`, nunca en quien llama.

    Args:
        lpath: El log de la pasada.
        pair: La pareja que falló, si se sabe. Las explicaciones de un freno de
            borrados dicen cómo forzar la pasada, y al llavero no se le fuerza:
            para él se dice lo suyo (`frenos.EXPLICACION_LLAVERO`).
    """
    if lpath is None:
        return
    try:
        if not lpath.exists():
            return
        text = lpath.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return          # ya lo ha dicho print_log_tail, que va antes
    for needle, explanation in KNOWN_ERRORS:
        if needle(text) if callable(needle) else needle in text:
            if pair is not None and pair.llavero and explanation in frenos.EXPLICACIONES:
                explanation = frenos.explicacion_llavero(explanation)
            print(f"  >> {explanation}")
            return


def ask_yes_no(question: str, default: bool = False) -> bool:
    """Pregunta sí o no por consola.

    Sin terminal interactiva no bloquea: devuelve `default`.
    """
    if not sys.stdin or not sys.stdin.isatty():
        return default
    suffix = " [S/n] " if default else " [s/N] "
    try:
        answer = input(question + suffix).strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    if not answer:
        return default
    return answer in {"s", "si", "sí", "y", "yes"}


@dataclass(frozen=True)
class RunContext:
    """Lo que no cambia de una pareja a otra dentro de una misma ejecución.

    Args:
        binary: El rclone.
        env: Las variables de entorno que se le añaden (el remote `combine` del
            dispositivo).
        dry_run: Si es un simulacro.
        force_resync: Si se pidió `--resync`.
        resync_approved: Si se aprueban los `--resync` que hagan falta.
        force: Si se pidió `--force`: las parejas de esta ejecución saltan su freno
            de borrados (`orden.flags_de_la_pasada()`). Solo viene de la línea de
            órdenes y de una persona: ni el servicio, ni `--auto`, ni el agente
            lo pasan, y no es un flag del TOML.
        keep_logs: Si se guarda también el log de las pasadas buenas.
        sello: El sufijo de las versiones guardadas (`--suffix`), en hora local
            como el resto de fechas que ve la persona. Se calcula UNA vez por
            invocación y no por pareja: así todo lo que aparta una misma pasada
            comparte marca, que es lo que luego permite leer «esto se perdió
            junto».
    """
    binary: str
    env: Mapping[str, str]
    dry_run: bool = False
    force_resync: bool = False
    resync_approved: bool = False
    force: bool = False
    keep_logs: bool = False
    sello: str = ""

    @property
    def tag(self) -> str:
        """Devuelve ` [DRY-RUN]` si es un simulacro, y nada si no."""
        return " [DRY-RUN]" if self.dry_run else ""


def build_command(ctx: RunContext, pair: Pair, ffile: Path | None,
                  need_resync: bool) -> tuple[list[str], Path]:
    """Devuelve la orden de rclone de la pareja y su log temporal.

    La orden la monta `orden.orden_rclone()`, la misma pieza con la que el
    editor de flags enseña la vista previa: los flags de la pareja llegan ya
    fundidos desde `model.Pair` y solo se añaden los que dependen de ESTA
    ejecución y por eso no se configuran en el TOML. Para añadir un flag nuevo
    no se toca esta función: se escribe en el TOML.
    """
    logfile = temp_log(pair.name)
    cmd = orden.orden_rclone(pair, binario=ctx.binary, filtros=ffile,
                             config=model.RCLONE_CONF, logfile=logfile,
                             simulacro=ctx.dry_run, resync=need_resync, sello=ctx.sello,
                             forzar=ctx.force)
    return cmd, logfile


def _seguir(logfile: Path, parar: threading.Event) -> None:
    """Lee lo nuevo del log hasta que le avisan, y una vez más después.

    Es el hilo de `seguir_progreso`. La última vez es cuando rclone ya ha
    escrito su última estadística.
    """
    try:
        seguidor = progress.Seguidor()
        with logfile.open("rb") as f:
            while True:
                acabado = parar.wait(PROGRESS_POLL_S)
                linea = seguidor.alimentar(f.read())
                if linea is not None:
                    print(linea)
                if acabado:
                    return
    except Exception:                                    # noqa: BLE001
        # Un fallo aquí es del progreso, no de la pasada: sin progreso, y ya
        # está.
        return


@contextmanager
def seguir_progreso(logfile: Path | None):
    """Cuenta por la salida cómo va rclone mientras dura el bloque.

    Lee el log temporal de la pareja desde otro hilo, porque quien lanza rclone
    se queda esperando a que termine. El fichero se cierra antes de salir del
    bloque: en Windows no se puede borrar ni mover un fichero abierto, y justo
    después `dispose_log` hace una de las dos cosas.
    """
    if logfile is None:
        yield
        return
    parar = threading.Event()
    hilo = threading.Thread(target=_seguir, args=(logfile, parar), daemon=True)
    hilo.start()
    try:
        yield
    finally:
        parar.set()
        hilo.join()


def crear_carpeta_remota(ctx: RunContext, pair: Pair) -> int:
    """Crea en el remoto la carpeta de una pareja antes de su `--resync` (`rclone mkdir`).

    Es para el llavero: su carpeta (`keychain/`, junto al catálogo) la pone el
    código y nadie más la crea, y `bisync --resync` aborta si la del remoto no
    existe («error reading source root directory: directory not found»). Sin
    esto, en un remoto recién activado la primera pasada fallaba siempre. Si ya
    está, `mkdir` no hace nada; con `--dry-run`, tampoco crea nada. Un fallo
    solo se dice: la pasada lo volverá a decir con su log.
    """
    cmd = [ctx.binary, "mkdir", pair.dest, "--config", str(model.RCLONE_CONF)]
    if ctx.dry_run:
        cmd.append("--dry-run")
    rc = execute(ctx, cmd)
    if rc != 0:
        print(f"[{pair.name}] No se ha podido crear {pair.dest} (código {rc}).")
    return rc


ORDENES = [0]
"""Cuántas veces ha lanzado rclone este proceso (`execute()`); va en el parte de cada pareja."""


def execute(ctx: RunContext, cmd: list[str], logfile: Path | None = None) -> int:
    """Ejecuta rclone y devuelve su código de salida."""
    print(f"  ejecutando{ctx.tag}: " + " ".join(cmd))
    ORDENES[0] += 1
    # cwd fijo: `rclone.conf` usa rutas relativas (`key_file`,
    # `known_hosts_file`) que se resuelven contra él.
    kwargs: dict = {"cwd": str(model.APP_DIR)}
    if os.name == "nt":
        # Sin consola propia (`pythonw`, el servicio), evita una ventana por
        # invocación.
        kwargs["creationflags"] = model.CREATE_NO_WINDOW
    # Consola capturada, no heredada: con `--log-file` solo sale lo que falla
    # antes de instalarlo, y heredado se perdería (sin consola) o quedaría
    # fuera del log que se guarda. El log se lee mientras tanto: de ahí sale el
    # progreso (`common/progress.py`).
    with seguir_progreso(logfile):
        # `encoding` explícito: rclone escribe UTF-8 y el del sistema (cp1252
        # en Windows) rompería las tildes del log.
        proc = subprocess.run(cmd, env={**os.environ, **ctx.env},
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, encoding="utf-8", errors="replace",
                              **kwargs)
    if proc.stdout and logfile is not None:
        append_output(logfile, proc.stdout)
    return proc.returncode


def _bisync_preflight(ctx: RunContext, pair: Pair) -> tuple[bool, bool, int | None]:
    """Hace las comprobaciones previas de una pareja bisync.

    Returns:
        `(hace_falta_resync, referencia_vacía, código_con_el_que_abortar)`.
        `referencia_vacía` es que el resync parte de un baseline vacío
        (`bisync.referencia_vacia()`), para que quien mide la pasada no lo
        cuente como que movió algo. Con código `None` se puede seguir adelante.
    """
    bisync.migrate_legacy_state(pair)

    state = bisync.pair_state(pair)
    print(f"  estado: {state.status} — {state.detail}")

    reasons = bisync.resync_reasons(pair, state)
    # Con los dos listados vacíos no queda nada que proteger, y rclone se niega
    # a pasar con ellos (`checkListing()`): se rehacen, sin pedirlo. Sin carpeta
    # local no entra (lo comprueba `referencia_vacia()`): ahí manda el aborto de
    # más abajo.
    vacia = bisync.referencia_vacia(pair, state)
    need_resync = ctx.force_resync or bool(reasons) or vacia
    if vacia:
        for reason in reasons:
            print(f"  requiere --resync -> {reason}")
        print("  la referencia está vacía: se rehace con --resync, sin pedirlo (no hay "
              "nada que proteger, y un --resync no borra nada).")
    elif need_resync and pair.llavero and reasons:
        # El llavero no espera a que nadie lo apruebe: con `resync-mode =
        # newer` gana la versión más nueva y la otra queda en `.prversions/`
        # (el backup-dir también vale en un --resync). Saltarlo lo dejaría sin
        # sincronizar sin que nadie se enterase: una pasada saltada sale con 0.
        for reason in reasons:
            print(f"  requiere --resync -> {reason}")
        print(f"[{pair.name}] El llavero se resincroniza solo: gana lo más nuevo y lo "
              f"otro queda en {model.VERSIONS_DIR}.")
    elif need_resync and not ctx.resync_approved:
        for reason in reasons:
            print(f"  requiere --resync -> {reason}")
        print(f"[{pair.name}] Saltada: requiere --resync y no está aprobado.")
        return need_resync, vacia, SKIPPED

    # Con baseline y sin carpeta local (dispositivo a medio montar), crearla
    # vacía haría que bisync viese «han borrado todo».
    if state.has_baseline and not pair.local_abs.exists():
        print(f"[{pair.name}] ERROR: existe baseline pero la ruta local "
              f"'{pair.local_abs}' no existe. Se aborta (no se crea vacía a propósito).")
        return need_resync, vacia, 2

    return need_resync, vacia, None


def record_result(ctx: RunContext, pair: Pair, rc: int, log: Path | None,
                  reloj: historial.Reloj | None = None,
                  final: progress.Progreso | None = None) -> None:
    """Apunta cómo acabó la pareja, para que la ventana y el servicio lo enseñen.

    Un dry-run no apunta nada: un simulacro bueno no puede tapar un fallo real.
    Con el mismo criterio va al diario de pasadas (`common/historial.py`), que
    dice desde cuándo falla. Sin `reloj`, la pasada consta igual, con la hora
    de ahora y sin duración.

    Args:
        reloj: Cuándo empezó la pareja.
        final: Última estadística de rclone, si la hubo.
    """
    if ctx.dry_run or rc == SKIPPED:
        return
    # `results` busca el log en `logs/`: uno que se quedó en el temporal
    # (`keep_log`, #36) no se encontraría.
    if log is not None and log.parent != model.LOG_DIR:
        log = None
    results.apuntar(pair.name, rc, log)
    historial.apuntar(historial.pasada(pair.name, rc, reloj,
                                       final.hecho if final is not None else None))


def sin_conflictos_nuevos(pair: Pair, dicho: parte.Parte | None) -> bool:
    """Indica si se puede dar por sabido que la pasada no ha dejado conflictos.

    Solo cuando se sabe que no movió nada (`Parte.vacia`) y el último recorrido
    de la pareja no apuntó ninguna copia: rclone renombra al perdedor al
    detectar el conflicto, y eso cambia los listados. Con alguna copia apuntada
    se sigue recorriendo, para que la lista se vacíe cuando la persona las
    resuelva. Ahorra recorrer con `os.walk` toda la carpeta local tras cada
    pasada sin cambios.
    """
    if dicho is None or not dicho.vacia or not pair.is_bisync:
        return False
    try:
        return conflicts.sin_apuntar(pair.name)
    except OSError:
        return False


def report_conflicts(ctx: RunContext, pair: Pair) -> None:
    """Apunta y avisa de los ficheros en conflicto que haya dejado bisync.

    Va tras cada pasada, buena o mala, que haya podido dejarlos
    (`sin_conflictos_nuevos()`): rclone renombra al perdedor al
    detectarlo y un fallo posterior no quita el conflicto. Si el recorrido
    falla (dispositivo desaparecido a medias) se calla: es un aviso y no puede
    tumbar la sincronización.
    """
    if not pair.is_bisync or ctx.dry_run:
        return
    try:
        encontrados = conflicts.actualizar_pareja(pair)
    except OSError:
        return
    if not encontrados:
        return
    print(f"[{pair.name}] AVISO: {len(encontrados)} fichero(s) en conflicto: cambiaron "
          f"en los dos lados y hay dos versiones. Resuélvelos desde la ventana.")
    for conflicto in encontrados[:CONFLICTS_SHOWN]:
        print(f"  conflicto: {conflicto.relativa}")
    if len(encontrados) > CONFLICTS_SHOWN:
        print(f"  … y {len(encontrados) - CONFLICTS_SHOWN} más")


def run_pair(ctx: RunContext, pair: Pair) -> int:
    """Ejecuta una pareja y devuelve su código de salida.

    Antes de nada aborta con 2 si su carpeta local, ya resuelta, es la del
    programa o cae dentro (`model.problema_contencion()`). Al acabar escribe su
    parte (`common/parte.py`): la línea que lee el agente residente, con si la
    pasada movió algo. Un simulacro no lo escribe.
    """
    medida = parte.Medida(pair, ORDENES[0], medir=not ctx.dry_run)
    rc = _pasar_pareja(ctx, pair, medida)
    if not ctx.dry_run:
        print(parte.linea(medida.parte or medida.acabar(rc, ORDENES[0])))
    return rc


def decir_lo_que_borraria(pair: Pair, logfile: Path) -> None:
    """Dice, tras una simulación forzada, qué ficheros habría borrado la pasada.

    Es lo que enseña la ventana antes de que nadie fuerce de verdad: la salida de
    una simulación buena es solo «OK» y su log se tira, así que sin esto no hay
    forma de ver qué se borraría. Lee el log ENTERO, no solo el final: la cifra
    es la que la persona mira antes de forzar, y con cien mil ficheros el final
    no la da. Se calla si no se puede leer el log (el dispositivo ha desaparecido):
    la pasada ya lo dirá por su cuenta.

    Args:
        pair: La pareja simulada.
        logfile: El log temporal de la pasada, que `dispose_log()` va a tirar.
    """
    try:
        nombres = frenos.borrarian(frenos.leer(logfile, completo=True))
    except OSError:
        return
    if not nombres:
        print("  Simulación forzada: el log de la simulación no ha apuntado ningún borrado. "
              "No se ha tocado nada.")
        return
    donde = "" if pair.is_bisync else f" en {frenos.nombre_lado(pair.mode.dest)}"
    print(f"  Simulación forzada: se borrarían {len(nombres)} "
          f"{'fichero' if len(nombres) == 1 else 'ficheros'}{donde}; no se ha tocado nada:")
    for nombre in nombres[:SIMULADOS_SHOWN]:
        print(f"    - {nombre}")
    if len(nombres) > SIMULADOS_SHOWN:
        print(f"    … y {len(nombres) - SIMULADOS_SHOWN} más")


def avisar_forzada(pair: Pair) -> str:
    """Devuelve la línea que dice cómo salta el freno una pasada forzada, o que no hay freno."""
    if pair.llavero:
        return ("--force no se aplica al llavero: sus bases son tus contraseñas y su freno no "
                "se salta. Sigue la pasada normal.")
    if not frenos.se_puede_forzar(pair):
        return (f"--force no hace nada aquí: el modo {pair.mode.name} no tiene freno de "
                "borrados. Sigue la pasada normal.")
    como = "--force" if pair.is_bisync else "--max-delete -1"
    return (f"PASADA FORZADA ({como}): esta pasada no frena los borrados; la siguiente "
            "vuelve a llevar el freno.")


def _pasar_pareja(ctx: RunContext, pair: Pair, medida: parte.Medida) -> int:
    """Hace la pasada de una pareja (`run_pair()`) y deja en `medida` lo que solo se sabe aquí."""
    print(f"\n=== {pair.name} ({pair.mode.name}){ctx.tag} ===")
    if ctx.force:
        print(f"[{pair.name}] " + avisar_forzada(pair))
    reloj = historial.Reloj()

    # Dónde cae de verdad su carpeta, resuelta: lo que el texto del config no
    # delata (un enlace, un nombre corto de Windows) a `.prdrive/`, con la clave.
    contencion = model.problema_contencion(pair)
    if contencion is not None:
        print(f"[{pair.name}] ERROR: {contencion} Se aborta.")
        record_result(ctx, pair, 2, None, reloj)
        return 2

    need_resync = ctx.force_resync
    vacia = False
    if pair.is_bisync:
        need_resync, vacia, abort_code = _bisync_preflight(ctx, pair)
        if abort_code is not None:
            record_result(ctx, pair, abort_code, None, reloj)
            return abort_code

    if not pair.local_abs.exists():
        if pair.mode.borra_en_remoto:
            # Un espejo de subida vacía el remoto si su origen está vacío: sin la
            # carpeta, rclone se niega («directory not found»); creada vacía, borra.
            print(f"[{pair.name}] ERROR: la ruta local '{pair.local_abs}' no existe y es el "
                  "origen de un espejo de subida. Se aborta (no se crea vacía a propósito: "
                  "un origen vacío vaciaría el remoto).")
            record_result(ctx, pair, 2, None, reloj)
            return 2
        print(f"[{pair.name}] La ruta local '{pair.local_abs}' no existe. Creándola...")
        pair.local_abs.mkdir(parents=True, exist_ok=True)
        if pair.llavero:
            store.hide(pair.local_abs)

    if pair.llavero and pair.llave_interna:
        estado = cifrada.estado()
        if not estado.cifrada:
            print(f"[{pair.name}] NO SE SINCRONIZA: el llavero va sin contraseña y "
                  f"{estado.motivo[:1].lower()}{estado.motivo[1:]} Cifra el dispositivo, "
                  "o quita el llavero de aquí.")
            record_result(ctx, pair, LLAVERO_SIN_CIFRAR, None, reloj)
            return LLAVERO_SIN_CIFRAR
    if pair.llavero:
        motivo = llavero.preparar(pair, simulacro=ctx.dry_run)
        if motivo is not None:
            print(f"[{pair.name}] NO SE SUBE: {motivo}")
            record_result(ctx, pair, LLAVERO_ROTO, None, reloj)
            return LLAVERO_ROTO
        if need_resync:
            crear_carpeta_remota(ctx, pair)

    ffile = bisync.filters_file_for(pair)
    cmd, logfile = build_command(ctx, pair, ffile, need_resync)
    # Un resync que parte de una referencia vacía solo mueve algo si trae
    # ficheros: lo dirá la comparación de los listados (`parte.Medida.acabar()`),
    # no el simple hecho de ser un resync.
    medida.resync = bool(need_resync) and not vacia
    rc = execute(ctx, cmd, logfile)
    if ctx.dry_run and ctx.force and rc == 0 and frenos.se_puede_forzar(pair):
        decir_lo_que_borraria(pair, logfile)
    if rc != 0 and pair.llavero and not need_resync:
        rc, logfile = repetir_sin_freno(ctx, pair, ffile, logfile, rc)
    # Antes de `dispose_log()`: si la pasada fue bien, el log se tira y con él
    # lo que dice cuánto movió.
    final = progress.final_del_log(logfile)
    if not pair.is_bisync:
        medida.quieta = parte.sin_actividad(logfile)

    saved = dispose_log(pair.name, logfile, rc, ctx.keep_logs)
    if rc == 0:
        print(f"[{pair.name}] OK." + (f" Log: {saved}" if saved else ""))
    else:
        print(f"[{pair.name}] FALLÓ (código {rc}). Log: {saved}")
        print_log_tail(saved)
        explain_failure(saved, pair)
    record_result(ctx, pair, rc, saved, reloj, final)
    if not pair.llavero and not ctx.dry_run:
        # El llavero puede dar otra pasada aquí debajo: su parte se cierra al final.
        medida.cerrar(rc, ORDENES[0])
    if not sin_conflictos_nuevos(pair, medida.parte):
        report_conflicts(ctx, pair)
    if rc == 0 and pair.llavero and not ctx.dry_run:
        reapuntar_llavero(ctx, pair, ffile)
    return rc


def lo_que_borraria_forzando(ctx: RunContext, pair: Pair, ffile: Path | None) -> list[str] | None:
    """Simula la pasada del llavero con `--force` y dice qué ficheros borraría.

    Es la comprobación de antes de repetir una pasada parada por «han cambiado todos»
    (`repetir_sin_freno()`): la misma orden que se repetiría, con `--dry-run` (que no apunta
    nada en el listado). Cuenta lo que rclone dice que saltaría al simular
    (`frenos.borrarian()`: `Skipped delete` y `Skipped move into backup dir`), no lo que
    sobrescribiría, que el backup-dir guarda.

    Returns:
        Los nombres que borraría (vacío si ninguno), o `None` si no se ha podido saber: la
        simulación falló o su log no se deja leer.
    """
    simulada = replace(ctx, dry_run=True)
    cmd, logfile = build_command(simulada, replace(pair, flags={**pair.flags, "force": True}),
                                 ffile, False)
    try:
        if execute(simulada, cmd, logfile) != 0:
            return None
        return frenos.borrarian(frenos.leer(logfile, completo=True))
    except OSError:
        return None
    finally:
        logfile.unlink(missing_ok=True)


def repetir_sin_freno(ctx: RunContext, pair: Pair, ffile: Path | None, logfile: Path,
                      rc: int) -> tuple[int, Path]:
    """Repite UNA vez la pasada del llavero sin el freno que la ha parado, si ese freno se puede quitar.

    Son tres frenos de rclone, y quitarlos es seguro en el llavero porque lo que pisa cada lado
    se queda en `.prversions/` (backup-dir, también en un conflicto y en un `--resync`). Los
    dos primeros los salta `--force` (`frenos.py`):

    - **Borrados** (`--max-delete`, 25 % del listado anterior): el llavero tiene tan pocos
      ficheros que quitar una copia de conflicto ya lo pisa, al combinar aquí o al ver en otro
      dispositivo que se fue del remoto. Si todo lo borrado son copias
      (`llavero.solo_copias_borradas()`), se repite con `llavero.FRENO_SIN_COPIAS`; si hay una
      base entre lo borrado, no.
    - **Han cambiado todos los ficheros de un lado** (#115): con dos ficheros, una base y
      `LEEME.txt`, basta con que cambie la hora de los dos, y pasaba al traer el llavero a un
      segundo dispositivo. Se repite con `--force`, que también salta el freno de borrados:
      por eso antes se simula (`lo_que_borraria_forzando()`) y solo se fuerza si la
      simulación sale bien y no borra nada.

    El tercero solo lo salta `--resync`:

    - **El remoto está vacío** (`llavero.remoto_vacio()`): alguien ha borrado a mano la carpeta
      del llavero en el remoto. Con baseline nadie la vuelve a crear, rclone no sincroniza
      contra un lado vacío y, con `--resilient`, falla así en cada pasada. Se crea la carpeta
      (`crear_carpeta_remota()`) y se repite con `--resync`, que no borra nada y se queda con
      la base más nueva (`resync-mode = newer`): la del dispositivo vuelve a subir.

    Una sola repetición por pasada, sea cual sea el freno: si la repetida vuelve a pararse
    (por ese u otro), se queda el fallo, que `explain_failure()` y «Reparación» explican. Esto
    es de la pasada del llavero y de ninguna otra, y no pasa por `RunContext.force`: a una
    persona no se le deja forzar el llavero (`frenos.se_puede_forzar()`).

    Returns:
        `(código, log)`: los de la pasada repetida, o los mismos si no se repite.
    """
    try:
        texto = logfile.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return rc, logfile
    copias = llavero.solo_copias_borradas(texto, pair) if "too many deletes" in texto else None
    cambio: dict = {}
    resync = False
    if copias is not None:
        print(f"[{pair.name}] Lo borrado son copias de conflicto ({', '.join(copias)}), y cada "
              f"una queda en {model.VERSIONS_DIR}: se repite la pasada sin el freno de borrados.")
        dispose_log(pair.name, logfile, 0, ctx.keep_logs)
        cambio = {"max-delete": llavero.FRENO_SIN_COPIAS}
    elif frenos.es_cambiados_bisync(texto):
        # `--force` salta también el freno de borrados, y la repetición es otra ejecución de rclone
        # que vuelve a listar los dos lados: lo que se hubiera borrado entre una y otra no
        # frenaría. Se simula antes, y si borrara algo (o no se pudiera saber) no se fuerza.
        borraria = lo_que_borraria_forzando(ctx, pair, ffile)
        if borraria is None or borraria:
            que = ("no se ha podido simular" if borraria is None
                   else f"borraría {', '.join(borraria)}")
            print(f"[{pair.name}] Han cambiado todos los ficheros de un lado y bisync se ha parado, "
                  f"pero forzar la pasada {que}: no se fuerza, el freno manda.")
            return rc, logfile
        # El log de la pasada parada se guarda aunque la repetida vaya bien: es lo que dice por
        # qué se forzó, y de la repetida no queda nada (su log se tira si sale bien).
        parada = dispose_log(pair.name, logfile, rc, True)
        print(f"[{pair.name}] Han cambiado todos los ficheros de un lado y bisync se ha parado"
              + (f" (Log: {parada})" if parada else "")
              + f". El llavero deja lo que pisa cada lado en {model.VERSIONS_DIR}: "
              "se repite la pasada una vez con --force.")
        cambio = {"force": True}
    elif llavero.remoto_vacio(texto):
        # Su log se guarda como el del forzado: dice por qué se ha vuelto a subir el llavero.
        parada = dispose_log(pair.name, logfile, rc, True)
        print(f"[{pair.name}] La carpeta del llavero en el remoto está vacía o ya no está, y "
              "bisync no sincroniza contra un lado vacío"
              + (f" (Log: {parada})" if parada else "")
              + f". Un --resync no borra nada y lo que pise queda en {model.VERSIONS_DIR}: "
              "se crea la carpeta y se repite la pasada una vez con --resync.")
        crear_carpeta_remota(ctx, pair)
        resync = True
    else:
        return rc, logfile
    repetida = replace(pair, flags={**pair.flags, **cambio})
    cmd, logfile = build_command(ctx, repetida, ffile, resync)
    return execute(ctx, cmd, logfile), logfile


def reapuntar_llavero(ctx: RunContext, pair: Pair, ffile: Path | None) -> None:
    """Repite en seguida la pasada del llavero si rclone ha dejado una base fuera de su listado.

    Pasa tras un conflicto que gana el remoto, por un fallo de rclone
    (`llavero.sin_listar()`). Tiene que ser ya, con las dos bases iguales: así
    bisync solo la vuelve a apuntar. Si falla, solo se dice: lo peor es que un
    cambio antes de la próxima pasada buena salga como otro conflicto.
    """
    faltan = llavero.sin_listar(pair)
    if not faltan:
        return
    print(f"[{pair.name}] rclone no ha apuntado {', '.join(faltan)} tras el conflicto: "
          "otra pasada, ahora que están iguales, para que lo haga.")
    cmd, logfile = build_command(ctx, pair, ffile, False)
    rc = execute(ctx, cmd, logfile)
    saved = dispose_log(pair.name, logfile, rc, ctx.keep_logs)
    if rc != 0:
        print(f"[{pair.name}] Esa pasada ha fallado (código {rc}). Log: {saved}")


def resolve_resync_approval(selected: list[Pair], assume_yes: bool) -> bool:
    """Decide UNA vez si se aprueban los `--resync` autodetectados.

    Es en lugar de ir preguntando pareja por pareja a mitad de faena. Antes de
    preguntar dice, de cada pareja de la raíz que subió la carpeta del programa,
    dónde está esa copia en el remoto (`revision.carpeta_programa_en_remoto()`):
    el resync no la borra, y después el listado ya no la enseña.
    """
    pending = []
    programas = []
    for pair in selected:
        if not pair.is_bisync or pair.llavero:
            continue            # el llavero se resincroniza solo (`_bisync_preflight()`)
        bisync.migrate_legacy_state(pair)
        reasons = bisync.resync_reasons(pair)
        if reasons:
            pending.append((pair.name, reasons))
            # Se dice ahora y no después: tras el resync el listado ya no lo enseña.
            carpeta = revision.carpeta_programa_en_remoto(pair)
            if carpeta is not None:
                programas.append((pair.name, carpeta))
    if not pending:
        return False

    print("Parejas bisync que requieren --resync:")
    for name, reasons in pending:
        for reason in reasons:
            print(f"  - {name:<15} {reason}")
    for name, carpeta in programas:
        print(f"  - {name:<15} {revision.aviso_carpeta_programa(carpeta)}")
    print("El --resync compara ambos lados y fija la referencia; no borra por diferencias.")

    if assume_yes:
        print("--yes: se ejecutará --resync en todas.")
        return True
    approved = ask_yes_no("¿Ejecutar --resync en TODAS ahora?")
    if not approved:
        print("De acuerdo, esas parejas se saltarán. (Usa --yes para automatizar.)")
    return approved


def run_all(ctx: RunContext, selected: list[Pair]) -> int:
    """Ejecuta las parejas elegidas y devuelve 1 si alguna ha fallado."""
    ok = failures = skipped = 0
    for pair in selected:
        try:
            rc = run_pair(ctx, pair)
        except OSError as e:
            # Dispositivo desaparecido a mitad de pasada (#36): las de detrás
            # fallan antes de llegar a rclone (carpeta local, filtros, el
            # propio rclone). Cada una con su línea y contada como fallo, sin
            # traceback que se lleve el resumen y la nota de la flota.
            print(f"[{pair.name}] FALLÓ: {e}")
            rc = 1                  # el «error sin clasificar» de rclone
            record_result(ctx, pair, rc, None)
        if rc == SKIPPED:
            skipped += 1
        elif rc == 0:
            ok += 1
        else:
            failures += 1

    summary = f"\nHecho. {ok}/{len(selected)} parejas OK"
    if skipped:
        summary += f", {skipped} saltada(s)"
    if failures:
        summary += f", {failures} con errores"
    print(summary + ".")
    return 1 if failures else 0


def list_pairs(config: Config) -> int:
    """Imprime las parejas configuradas."""
    print("Parejas configuradas:")
    for pair in config.pairs:
        marca = "  (el llavero, lo pone prdrive)" if pair.llavero else ""
        print(f"  - {pair.name:<15} {pair.mode.name:<12} "
              f"{pair.local_endpoint}  <->  {pair.remote_endpoint}{marca}")
    return 0


def doctor(config: Config) -> int:
    """Imprime el estado del dispositivo, en texto, sin tocar nada.

    El diagnóstico lo hace `common/revision.py`, que también alimenta
    «Reparación»: dos sitios que decidan qué está roto acaban discrepando.
    """
    for linea in revision.informe(config):
        print(linea)
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Devuelve los argumentos de la línea de comandos."""
    parser = argparse.ArgumentParser(
        description="Sincronización portable entre un remoto de rclone y un dispositivo local."
    )
    parser.add_argument("pairs", nargs="*",
                        help="Nombres de parejas a sincronizar (por defecto: todas).")
    parser.add_argument("--list", action="store_true",
                        help="Lista las parejas configuradas y sale.")
    parser.add_argument("--doctor", action="store_true",
                        help="Diagnostica el estado de bisync y sale.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Simula sin modificar nada.")
    parser.add_argument("--resync", action="store_true",
                        help="Rehace el baseline de bisync.")
    parser.add_argument("--force", action="store_true",
                        help="Salta el freno de borrados SOLO en esta pasada de las parejas "
                             "nombradas (bisync: --force; un espejo: --max-delete -1). "
                             "Simula antes con --dry-run.")
    parser.add_argument("--keep-logs", action="store_true",
                        help="Conserva también el log de las ejecuciones correctas "
                             "(por defecto solo se guarda el de las que fallan).")
    parser.add_argument("-y", "--yes", action="store_true",
                        help="Responde 'sí' a todo (p.ej. resincronizar parejas sin "
                             "baseline). Útil para automatizar sin interacción.")
    args = parser.parse_args(argv)
    if args.force and not args.pairs:
        parser.error("--force necesita que nombres la pareja (o las parejas) a la que se "
                     "aplica: sin nombres saltaría el freno de todas.")
    if args.force and args.resync:
        parser.error("--force y --resync no van juntos: uno salta el freno de borrados y el "
                     "otro rehace el baseline.")
    return args


def preparar_salida() -> None:
    """Deja stdout y stderr línea a línea y en UTF-8.

    Línea a línea aunque sea una tubería (lo es cuando la ventana lanza
    `sync.py`): por bloques, el progreso llegaba todo junto al final. En UTF-8
    porque hacia una tubería Python usa la codificación del sistema (cp1252 en
    Windows) y las tildes llegarían rotas a quien lee UTF-8. stderr también:
    por ahí salen los `ConfigError`.
    """
    for flujo in (sys.stdout, sys.stderr):
        reconfigurar = getattr(flujo, "reconfigure", None)
        if reconfigurar is not None:
            reconfigurar(line_buffering=True, encoding="utf-8", errors="replace")


def main() -> int:
    """Hace la ejecución completa y devuelve el código de salida."""
    preparar_salida()
    args = parse_args()

    # `logs/` se crea solo si hay algo que guardar (`dispose_log`).
    for d in (model.STATE_DIR, model.FILTERS_DIR):
        d.mkdir(parents=True, exist_ok=True)

    try:
        config = model.load_config()
        if args.list:
            return list_pairs(config)
        if args.doctor:
            return doctor(config)
        selected = config.select(args.pairs) if args.pairs else list(config.pairs)
    except model.ConfigError as e:
        sys.exit(str(e))
    if args.force and any(p.llavero for p in selected):
        sys.exit("--force no vale para el llavero: sus bases son tus contraseñas y su freno no "
                 "se salta. Si hay copias de conflicto, usa «Combinar» al abrir el llavero.")
    if not model.RCLONE_CONF.exists():
        sys.exit(f"No existe {model.RCLONE_CONF}. Crea la config de rclone con el "
                 f"remote SFTP.")

    try:
        binary = model.rclone_binary()
    except OSError as e:
        sys.exit(f"No puedo preparar el rclone de este equipo para ejecutarlo: {e}")
    approved = args.resync or resolve_resync_approval(selected, args.yes)
    ctx = RunContext(
        binary=binary,
        env=config.pen_environment(),
        dry_run=args.dry_run,
        force_resync=args.resync,
        resync_approved=approved,
        force=args.force,
        keep_logs=args.keep_logs or config.keep_logs,
        sello=datetime.now().strftime("~%Y%m%d-%H%M%S"),
    )
    rc = run_all(ctx, selected)

    # Constancia en la flota de cómo le ha ido; nunca lanza
    # (`common/fleet.py`). Un simulacro no cuenta, como no apunta resultados.
    if not ctx.dry_run:
        fleet.publicar(config)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
