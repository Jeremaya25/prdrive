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
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Mapping

from common import (bisync, conflicts, fleet, historial, llavero, model, moderacion,
                    progress, results, revision, store)
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
CONFLICTS_SHOWN = 5
"""Ficheros en conflicto que se nombran en la salida."""
PROGRESS_POLL_S = 0.5
"""Cada cuántos segundos se mira si rclone ha escrito más en su log."""

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
    # bisync no dice «--max-delete»: `excessDeletes()` (cmd/bisync/deltas.go)
    # aborta con «too many deletes (>N%, X of Y)», un PORCENTAJE del listado
    # anterior (ver `MODES["bisync"]` en `common/model.py`). Va antes de la
    # entrada siguiente para que bisync lea este aviso.
    ("too many deletes",
     "Se ha superado el porcentaje de borrados permitido en esta pasada de "
     "bisync (--max-delete es un % del listado anterior, no una cuenta de "
     "ficheros). Comprueba que la ruta local NO esté vacía o desmontada antes "
     "de forzar nada."),
    ("--max-delete",
     "Se han superado los borrados permitidos (una cuenta de ficheros, en "
     "copy/mirror). Comprueba que la ruta local NO esté vacía o desmontada "
     "antes de forzar nada."),
    ("Access is denied",
     "Fichero bloqueado por otro proceso (Obsidian, KeePass, antivirus)."),
    # Lo que dice bisync al encontrar el lock de otra pasada
    # (cmd/bisync/lockfile.go, `setLockFile`). «lock file» a secas casaría
    # también con el «lock file renewed» de `--max-lock`.
    ("prior lock file found",
     "Hay un lock de otra ejecución. Si no hay ninguna corriendo, borra el .lck "
     "del workdir de la pareja."),
    ("known_hosts_file",
     "rclone no encuentra el fichero de known_hosts indicado en rclone.conf. "
     "Las rutas relativas de rclone.conf se resuelven contra rclone-sync/; "
     "comprueba que keys/known_hosts existe ahí."),
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
nunca en quien llama. Las dos entradas de flags (`--max-delete` y las de
arranque) van al final: un volcado de ayuda con esos nombres no puede explicar
un fallo ajeno.
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
    quita.
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


def explain_failure(lpath: Path | None) -> None:
    """Traduce el error de rclone a algo accionable.

    Los casos nuevos se añaden a `KNOWN_ERRORS`, nunca en quien llama.
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


def filter_args(pair: Pair, ffile: Path | None) -> list[str]:
    """Devuelve los argumentos de filtrado de la pareja.

    Con fichero de filtros no se emiten `--include` ni `--exclude`: se
    duplicarían las reglas y bisync dejaría de poder detectar cambios de
    filtrado.
    """
    if ffile is not None:
        return ["--filters-file", str(ffile)]
    args: list[str] = []
    # Las reglas del código (`Pair.reglas`) salen como `--include`/`--exclude`.
    # Aquí no pueden ir delante de las de la pareja: rclone añade siempre los
    # `--include` antes que los `--exclude` (`fs/filter/filter.go`, `NewFilter`).
    for regla in pair.reglas:
        signo, _, patron = regla.partition(" ")
        args += ["--include" if signo == "+" else "--exclude", patron]
    for pattern in pair.includes:
        args += ["--include", pattern]
    for pattern in pair.excludes:
        args += ["--exclude", pattern]
    return args


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
    keep_logs: bool = False
    sello: str = ""

    @property
    def tag(self) -> str:
        """Devuelve ` [DRY-RUN]` si es un simulacro, y nada si no."""
        return " [DRY-RUN]" if self.dry_run else ""


def build_command(ctx: RunContext, pair: Pair, ffile: Path | None,
                  need_resync: bool) -> tuple[list[str], Path]:
    """Devuelve la orden de rclone de la pareja y su log temporal.

    Los flags de la pareja llegan ya fusionados desde `model.Pair`; aquí solo
    se añaden los que dependen de ESTA ejecución y por eso no se configuran en
    el TOML. Para añadir un flag nuevo no se toca esta función: se escribe en
    el TOML.
    """
    logfile = temp_log(pair.name)

    flags = dict(pair.flags)
    flags["config"] = str(model.RCLONE_CONF)
    flags["log-file"] = str(logfile)
    if ctx.dry_run:
        flags["dry-run"] = True
    if pair.is_bisync:
        flags["workdir"] = str(pair.workdir)
        if need_resync:
            flags["resync"] = True

    if pair.versions:
        # El parseo ya garantiza que es bisync. El sello depende de la pasada,
        # por eso no va en el TOML.
        flags["backup-dir1"] = pair.versions_path1
        flags["backup-dir2"] = pair.versions_path2
        flags["suffix"] = ctx.sello
        flags["suffix-keep-extension"] = True
        # Con `delete`, el perdedor de un conflicto sale por el backup-dir
        # (`.prversions/`) en vez de quedarse como `<nombre>.conflicto-remoto1`
        # y viajar al otro lado. `setdefault`: un `[pair.flags]` sigue
        # mandando.
        flags.setdefault("conflict-loser", "delete")

    cmd = [ctx.binary, pair.mode.verb, pair.source, pair.dest]
    cmd += filter_args(pair, ffile)
    cmd += model.flags_to_args(flags)
    cmd += list(pair.extra_flags)
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


def execute(ctx: RunContext, cmd: list[str], logfile: Path | None = None) -> int:
    """Ejecuta rclone y devuelve su código de salida."""
    print(f"  ejecutando{ctx.tag}: " + " ".join(cmd))
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


def _bisync_preflight(ctx: RunContext, pair: Pair) -> tuple[bool, int | None]:
    """Hace las comprobaciones previas de una pareja bisync.

    Returns:
        `(hace_falta_resync, código_con_el_que_abortar)`. Con código `None` se
        puede seguir adelante.
    """
    bisync.migrate_legacy_state(pair)

    state = bisync.pair_state(pair)
    print(f"  estado: {state.status} — {state.detail}")

    reasons = bisync.resync_reasons(pair, state)
    need_resync = ctx.force_resync or bool(reasons)
    if need_resync and pair.llavero and reasons:
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
        return need_resync, SKIPPED

    # Con baseline y sin carpeta local (dispositivo a medio montar), crearla
    # vacía haría que bisync viese «han borrado todo».
    if state.has_baseline and not pair.local_abs.exists():
        print(f"[{pair.name}] ERROR: existe baseline pero la ruta local "
              f"'{pair.local_abs}' no existe. Se aborta (no se crea vacía a propósito).")
        return need_resync, 2

    return need_resync, None


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


def report_conflicts(ctx: RunContext, pair: Pair) -> None:
    """Apunta y avisa de los ficheros en conflicto que haya dejado bisync.

    Va tras CADA pasada, buena o mala: rclone renombra al perdedor al
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
    """Ejecuta una pareja y devuelve su código de salida."""
    print(f"\n=== {pair.name} ({pair.mode.name}){ctx.tag} ===")
    reloj = historial.Reloj()

    need_resync = ctx.force_resync
    if pair.is_bisync:
        need_resync, abort_code = _bisync_preflight(ctx, pair)
        if abort_code is not None:
            record_result(ctx, pair, abort_code, None, reloj)
            return abort_code

    if not pair.local_abs.exists():
        print(f"[{pair.name}] La ruta local '{pair.local_abs}' no existe. Creándola...")
        pair.local_abs.mkdir(parents=True, exist_ok=True)
        if pair.llavero:
            store.hide(pair.local_abs)

    if pair.llavero:
        motivo = llavero.preparar(pair)
        if motivo is not None:
            print(f"[{pair.name}] NO SE SUBE: {motivo}")
            record_result(ctx, pair, LLAVERO_ROTO, None, reloj)
            return LLAVERO_ROTO
        if need_resync:
            crear_carpeta_remota(ctx, pair)

    ffile = bisync.filters_file_for(pair)
    cmd, logfile = build_command(ctx, pair, ffile, need_resync)
    rc = execute(ctx, cmd, logfile)
    # Antes de `dispose_log()`: si la pasada fue bien, el log se tira y con él
    # lo que dice cuánto movió.
    final = progress.final_del_log(logfile)

    saved = dispose_log(pair.name, logfile, rc, ctx.keep_logs)
    if rc == 0:
        print(f"[{pair.name}] OK." + (f" Log: {saved}" if saved else ""))
    else:
        print(f"[{pair.name}] FALLÓ (código {rc}). Log: {saved}")
        print_log_tail(saved)
        explain_failure(saved)
    record_result(ctx, pair, rc, saved, reloj, final)
    report_conflicts(ctx, pair)
    return rc


def resolve_resync_approval(selected: list[Pair], assume_yes: bool) -> bool:
    """Decide UNA vez si se aprueban los `--resync` autodetectados.

    Es en lugar de ir preguntando pareja por pareja a mitad de faena.
    """
    pending = []
    for pair in selected:
        if not pair.is_bisync or pair.llavero:
            continue            # el llavero se resincroniza solo (`_bisync_preflight()`)
        bisync.migrate_legacy_state(pair)
        reasons = bisync.resync_reasons(pair)
        if reasons:
            pending.append((pair.name, reasons))
    if not pending:
        return False

    print("Parejas bisync que requieren --resync:")
    for name, reasons in pending:
        for reason in reasons:
            print(f"  - {name:<15} {reason}")
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
    parser.add_argument("--keep-logs", action="store_true",
                        help="Conserva también el log de las ejecuciones correctas "
                             "(por defecto solo se guarda el de las que fallan).")
    parser.add_argument("-y", "--yes", action="store_true",
                        help="Responde 'sí' a todo (p.ej. resincronizar parejas sin "
                             "baseline). Útil para automatizar sin interacción.")
    return parser.parse_args(argv)


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
    if not model.RCLONE_CONF.exists():
        sys.exit(f"No existe {model.RCLONE_CONF}. Crea la config de rclone con el "
                 f"remote SFTP.")

    binary = model.rclone_binary()
    approved = args.resync or resolve_resync_approval(selected, args.yes)
    ctx = RunContext(
        binary=binary,
        env=config.pen_environment(),
        dry_run=args.dry_run,
        force_resync=args.resync,
        resync_approved=approved,
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
