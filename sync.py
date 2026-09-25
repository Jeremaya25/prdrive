#!/usr/bin/env python3
"""
sync.py — Sincronización portable entre un remoto de rclone y un dispositivo local.

Todo vive en el dispositivo y no depende de nada instalado en la máquina salvo
Python 3.11+ (para tomllib). El binario de rclone es portable (carpeta bin/).

    common/model.py   el TOML convertido en objetos ya resueltos
    common/bisync.py  lo que replica el comportamiento interno de rclone bisync
    ui/               la ventana y el menu de consola (los usa runsync.py)
    sync.py           este fichero: construir el comando, ejecutarlo y contarlo

Estructura esperada en el dispositivo:

    PEN/
    ├── rclone-sync/
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

from common import bisync, conflicts, fleet, model, progress, results, revision
from common.model import Config, Pair

LOG_TAIL_LINES = 15  # líneas de log que se vuelcan a consola cuando algo falla
SKIPPED = -1         # código interno: pareja no ejecutada (ni OK ni fallo)
CONFLICTS_SHOWN = 5  # ficheros en conflicto que se nombran en la salida
PROGRESS_POLL_S = 0.5  # cada cuánto se mira si rclone ha escrito más en su log

# La cabecera con la que se marca, dentro del log, lo que rclone sacó por
# consola en vez de por --log-file. Ver append_output().
DIRECT_OUTPUT_HEADER = "--- salida directa de rclone (no pasó por --log-file) ---"

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
    # bisync no dice "--max-delete": excessDeletes() (cmd/bisync/deltas.go)
    # aborta con "too many deletes (>N%, X of Y)", porque ahí el freno es un
    # PORCENTAJE del listado anterior, no una cuenta de ficheros (ver el
    # comentario de MODES["bisync"] en common/model.py). Esta entrada va antes
    # que la de más abajo para que una pareja bisync lea el aviso correcto.
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
    # Lo que dice bisync al encontrar el lock de otra (cmd/bisync/lockfile.go,
    # setLockFile). "lock file" a secas no vale: con --max-lock, cada pasada que
    # coge el lock apunta "lock file renewed", y todo fallo de bisync salía
    # explicado como un lock que no existía.
    ("prior lock file found",
     "Hay un lock de otra ejecución. Si no hay ninguna corriendo, borra el .lck "
     "del workdir de la pareja."),
    ("known_hosts_file",
     "rclone no encuentra el fichero de known_hosts indicado en rclone.conf. "
     "Las rutas relativas de rclone.conf se resuelven contra rclone-sync/; "
     "comprueba que keys/known_hosts existe ahí."),
    ("Failed to create file system",
     "rclone no ha podido montar uno de los dos extremos. Suele ser una ruta o "
     "credencial mal resuelta en rclone.conf (revisa key_file y "
     "known_hosts_file), o el remoto inalcanzable."),
    # Los dos últimos son errores de ARRANQUE: rclone rechaza la orden antes de
    # instalar el --log-file, así que solo se ven desde que execute() captura su
    # consola. Van al final a propósito: si un log trae además uno de los de
    # arriba, ese es el que hay que explicar, porque el de arriba es el que
    # ocurrió de verdad durante la sincronización.
    ("unknown flag",
     "rclone no conoce uno de los flags. Está escrito en sync_config.toml (o en "
     "el editor de flags de la ventana de parejas): rclone lo rechaza antes de "
     "empezar, por eso no hay más log que este."),
    ("invalid argument",
     "rclone rechaza el VALOR de un flag: no es de los que admite (por ejemplo "
     "conflict-resolve = \"new\" cuando lo válido es \"newer\"). El mensaje de "
     "arriba enumera los buenos. Se corrige en sync_config.toml."),
]


# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------

def temp_log(name: str) -> Path:
    """rclone escribe siempre a un log, pero en un temporal del sistema.

    Solo se conserva (moviéndolo a logs/) si la ejecución ha fallado. Si todo va
    bien no queda rastro y no se escribe en el dispositivo: menos ciclos de escritura y
    una carpeta logs/ que solo contiene lo que hay que mirar."""
    fd, path = tempfile.mkstemp(prefix=f"rclone-sync-{name}-", suffix=".log")
    os.close(fd)
    return Path(path)


def keep_log(name: str, tmp: Path) -> Path:
    """Mueve un log temporal a logs/ y devuelve dónde ha quedado.

    Normalmente en logs/, pero esto va justo detrás de un fallo, y el fallo
    puede ser que el dispositivo haya desaparecido a mitad de pasada (#36): ni
    logs/ se deja crear ni el log mover, y el traceback que salía tapaba en la
    ventana la cola del log y su explicación, que es lo que hay que leer en ese
    momento. Ahora se dice en una línea y el log se queda en el temporal del
    sistema, que está en el equipo: esa es la ruta que se devuelve, y de ahí
    leen `print_log_tail` y `explain_failure`.

    `OSError` y no `PermissionError`, que es como llega en Windows
    ([WinError 21]): en otro sistema, o con el dispositivo lleno o de solo
    lectura, llega otro. Y el movimiento dentro: entre dos unidades
    `shutil.move` copia y borra el origen al final, así que puede fallar con la
    copia a medias y el temporal entero. Esa copia se quita, para que en logs/
    no quede un log cortado con nombre de completo."""
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

    Ante un flag malo, rclone escribe el error y detrás la ayuda entera del
    subcomando: 12 KB documentando todos los flags que existen. Meter eso en el
    log tiene dos efectos y los dos son malos. El primero es que las 15 líneas de
    `print_log_tail` se van en documentación y el mensaje queda enterrado. El
    segundo es peor: `explain_failure` busca agujas de `KNOWN_ERRORS` dentro del
    texto, y esa ayuda menciona `--max-delete`, `lock file` y compañía, así que
    un error de flags salía explicado como «se han superado los borrados
    permitidos» — un diagnóstico falso, que es peor que ninguno.

    El bloque va desde la línea `Usage:` hasta la última que empieza por
    `Use "rclone`, que es como lo cierra siempre. Lo de fuera —el `Error:` de
    arriba y el `Fatal error:` de abajo— es justo lo que hay que leer."""
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

    Con `--log-file`, rclone manda al fichero todo lo que registra... pero solo
    desde que lo instala. Lo que falla ANTES —un flag que no existe, o un valor
    que no admite, como `--conflict-resolve new` cuando lo válido es `newer`—
    sale por stderr y no llega nunca al fichero: el log quedaba de 0 bytes,
    `print_log_tail` no tenía nada que enseñar y `explain_failure` nada que
    reconocer, justo en el caso en el que ese es el único mensaje que hay.

    Va marcado y no mezclado a secas porque no son líneas de log de rclone: no
    llevan su fecha ni su nivel, y sin el aviso no se sabría quién las escribió."""
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
    """Descarta el log si la ejecución fue bien; si no, lo guarda en logs/."""
    if rc == 0 and not keep_always:
        tmp.unlink(missing_ok=True)
        return None
    return keep_log(name, tmp)


def print_log_tail(lpath: Path | None, lines: int = LOG_TAIL_LINES) -> None:
    if lpath is None:
        return
    try:
        if not lpath.exists():
            return
        todas = lpath.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as e:
        # Guardado en el dispositivo, que se ha ido justo después (#36): un
        # volumen de VeraCrypt desenchufado sin expulsar sigue aceptando
        # escrituras en caché y luego no deja leer. Una línea, no un traceback.
        print(f"  (no he podido leer {lpath}: {e.strerror or e})")
        return
    # Sin las estadísticas. Con una cada pocos segundos, una pasada que se queda
    # pensando antes de fallar llenaba estas líneas de números y el error se
    # quedaba fuera; lo que llegó a transferir ya lo ha contado el progreso.
    tail = [linea for linea in todas if progress.leer(linea) is None][-lines:]
    print(f"--- últimas {len(tail)} líneas de {lpath.name} ---")
    for line in tail:
        print("  " + line)
    print("---")


def explain_failure(lpath: Path | None) -> None:
    """Traduce el error de rclone a algo accionable. Los casos nuevos se añaden a
    KNOWN_ERRORS, nunca en quien llama."""
    if lpath is None:
        return
    try:
        if not lpath.exists():
            return
        text = lpath.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return          # ya lo ha dicho print_log_tail, que va antes
    for needle, explanation in KNOWN_ERRORS:
        if needle in text:
            print(f"  >> {explanation}")
            return


def ask_yes_no(question: str, default: bool = False) -> bool:
    """Sí/no por consola. Sin terminal interactiva no bloquea: devuelve 'default'."""
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


# ---------------------------------------------------------------------------
# Construcción del comando
# ---------------------------------------------------------------------------

def filter_args(pair: Pair, ffile: Path | None) -> list[str]:
    """Con fichero de filtros no se emiten --include/--exclude: se duplicarían
    las reglas y bisync dejaría de poder detectar cambios de filtrado."""
    if ffile is not None:
        return ["--filters-file", str(ffile)]
    args: list[str] = []
    for pattern in pair.includes:
        args += ["--include", pattern]
    for pattern in pair.excludes:
        args += ["--exclude", pattern]
    return args


@dataclass(frozen=True)
class RunContext:
    """Lo que no cambia de una pareja a otra dentro de una misma ejecución."""
    binary: str
    env: Mapping[str, str]
    dry_run: bool = False
    force_resync: bool = False
    resync_approved: bool = False
    keep_logs: bool = False
    # El sufijo que llevan las versiones guardadas (`--suffix`), en hora local
    # como el resto de fechas que ve el usuario. Se calcula UNA vez por
    # invocación y no por pareja: así todo lo que aparta una misma pasada
    # comparte marca, que es lo que luego permite leer «esto se perdió junto».
    sello: str = ""

    @property
    def tag(self) -> str:
        return " [DRY-RUN]" if self.dry_run else ""


def build_command(ctx: RunContext, pair: Pair, ffile: Path | None,
                  need_resync: bool) -> tuple[list[str], Path]:
    """Los flags de la pareja llegan ya fusionados desde model.Pair; aquí solo se
    añaden los que dependen de ESTA ejecución y por eso no se configuran en el
    TOML. Para añadir un flag nuevo no se toca esta función: se escribe en el TOML."""
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
        # que es justo por lo que esto no se puede escribir en el TOML.
        flags["backup-dir1"] = pair.versions_path1
        flags["backup-dir2"] = pair.versions_path2
        flags["suffix"] = ctx.sello
        flags["suffix-keep-extension"] = True
        # Con `delete`, el perdedor de un conflicto no se borra: sale por el
        # backup-dir y acaba en `.prversions/` con su marca de tiempo, en vez de
        # quedarse dentro del pair como `<nombre>.conflicto-remoto1` y viajar al
        # otro lado. Va con setdefault para que un `[pair.flags]` siga mandando.
        flags.setdefault("conflict-loser", "delete")

    cmd = [ctx.binary, pair.mode.verb, pair.source, pair.dest]
    cmd += filter_args(pair, ffile)
    cmd += model.flags_to_args(flags)
    cmd += list(pair.extra_flags)
    return cmd, logfile


def _seguir(logfile: Path, parar: threading.Event) -> None:
    """El hilo de `seguir_progreso`: lee lo nuevo del log hasta que le avisan,
    y una vez más después, que es cuando rclone ya ha escrito su última
    estadística."""
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
        # Cualquier fallo aquí es del progreso, no de la pasada: un log que no
        # se deja abrir o un error del lector no pueden cortar la sincronización
        # ni llenar la ventana con un traceback. Sin progreso, y ya está.
        return


@contextmanager
def seguir_progreso(logfile: Path | None):
    """Mientras dura el bloque, cuenta por la salida cómo va rclone.

    Lee el log temporal de la pareja desde otro hilo, porque quien lanza rclone
    se queda esperando a que termine. El fichero se cierra antes de salir del
    bloque: en Windows no se puede borrar ni mover un fichero abierto, y justo
    después `dispose_log` hace una de las dos cosas."""
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


def execute(ctx: RunContext, cmd: list[str], logfile: Path | None = None) -> int:
    print(f"  ejecutando{ctx.tag}: " + " ".join(cmd))
    # cwd FIJO en rclone-sync/: rclone.conf usa rutas relativas (key_file,
    # known_hosts_file) para que el dispositivo siga siendo portable, y esas rutas se
    # resuelven contra el directorio de trabajo. No se puede depender de quién
    # nos haya lanzado ni desde dónde.
    kwargs: dict = {"cwd": str(model.APP_DIR)}
    if os.name == "nt":
        # Sin esto, cada invocación abre una ventana de consola cuando quien
        # llama no tiene una (pythonw, el servicio).
        kwargs["creationflags"] = model.CREATE_NO_WINDOW
    # La consola de rclone se CAPTURA, no se hereda. Con --log-file puesto, por
    # aquí solo sale lo que rclone no ha llegado a registrar —lo que falla antes
    # de instalar el log—, y heredarlo significaba perderlo: sin consola detrás
    # (pythonw, el servicio) no va a ninguna parte, y aun con ella se quedaba
    # fuera del fichero que luego se guarda, se enseña y se explica. Es poco
    # texto por definición: todo lo demás está en el log. Y el log se lee
    # mientras tanto: de ahí sale el progreso (common/progress.py).
    with seguir_progreso(logfile):
        # encoding explícito: rclone escribe UTF-8 en todas las plataformas, y
        # sin decirlo Python decodifica con la del sistema (cp1252 en Windows).
        # Un nombre de fichero con tilde llegaba roto al log que luego se guarda.
        proc = subprocess.run(cmd, env={**os.environ, **ctx.env},
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, encoding="utf-8", errors="replace",
                              **kwargs)
    if proc.stdout and logfile is not None:
        append_output(logfile, proc.stdout)
    return proc.returncode


# ---------------------------------------------------------------------------
# Ejecución de una pareja
# ---------------------------------------------------------------------------

def _bisync_preflight(ctx: RunContext, pair: Pair) -> tuple[bool, int | None]:
    """Comprobaciones previas de una pareja bisync.

    Devuelve (hace_falta_resync, código_con_el_que_abortar). Con código None se
    puede seguir adelante."""
    bisync.migrate_legacy_state(pair)

    state = bisync.pair_state(pair)
    print(f"  estado: {state.status} — {state.detail}")

    reasons = bisync.resync_reasons(pair, state)
    need_resync = ctx.force_resync or bool(reasons)
    if need_resync and not ctx.resync_approved:
        for reason in reasons:
            print(f"  requiere --resync -> {reason}")
        print(f"[{pair.name}] Saltada: requiere --resync y no está aprobado.")
        return need_resync, SKIPPED

    # Si YA había baseline y la carpeta local no está, algo va mal (dispositivo a medio
    # montar). Crearla vacía haría que bisync viese "han borrado todo".
    if state.has_baseline and not pair.local_abs.exists():
        print(f"[{pair.name}] ERROR: existe baseline pero la ruta local "
              f"'{pair.local_abs}' no existe. Se aborta (no se crea vacía a propósito).")
        return need_resync, 2

    return need_resync, None


def record_result(ctx: RunContext, pair: Pair, rc: int, log: Path | None) -> None:
    """Deja apuntado cómo acabó la pareja, para que la ventana y el servicio lo
    enseñen (ver common/results.py). Un dry-run no apunta nada: no dice cómo
    está la pareja de verdad, y un simulacro bueno no puede tapar un fallo real."""
    if ctx.dry_run or rc == SKIPPED:
        return
    # `results` apunta el log por su nombre y lo busca en logs/. Uno que se ha
    # quedado en el temporal del sistema porque el dispositivo ya no estaba
    # (`keep_log`, #36) no se encontraría ahí: apuntarlo sería dar un nombre
    # que no lleva a ninguna parte.
    if log is not None and log.parent != model.LOG_DIR:
        log = None
    results.apuntar(pair.name, rc, log)


def report_conflicts(ctx: RunContext, pair: Pair) -> None:
    """Busca los ficheros en conflicto que haya dejado bisync y los apunta.

    Va después de CADA pasada, buena o mala: rclone renombra al perdedor en
    cuanto lo detecta, así que un fallo más adelante no quita el conflicto. Si
    el recorrido falla (el dispositivo ha desaparecido a medias), se calla: es
    un aviso, no puede tumbar la sincronización."""
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
    print(f"\n=== {pair.name} ({pair.mode.name}){ctx.tag} ===")

    need_resync = ctx.force_resync
    if pair.is_bisync:
        need_resync, abort_code = _bisync_preflight(ctx, pair)
        if abort_code is not None:
            record_result(ctx, pair, abort_code, None)
            return abort_code

    if not pair.local_abs.exists():
        print(f"[{pair.name}] La ruta local '{pair.local_abs}' no existe. Creándola...")
        pair.local_abs.mkdir(parents=True, exist_ok=True)

    ffile = bisync.filters_file_for(pair)
    cmd, logfile = build_command(ctx, pair, ffile, need_resync)
    rc = execute(ctx, cmd, logfile)

    saved = dispose_log(pair.name, logfile, rc, ctx.keep_logs)
    if rc == 0:
        print(f"[{pair.name}] OK." + (f" Log: {saved}" if saved else ""))
    else:
        print(f"[{pair.name}] FALLÓ (código {rc}). Log: {saved}")
        print_log_tail(saved)
        explain_failure(saved)
    record_result(ctx, pair, rc, saved)
    report_conflicts(ctx, pair)
    return rc


def resolve_resync_approval(selected: list[Pair], assume_yes: bool) -> bool:
    """Decide UNA vez si se aprueban los --resync auto-detectados, en lugar de ir
    preguntando pareja por pareja a mitad de faena."""
    pending = []
    for pair in selected:
        if not pair.is_bisync:
            continue
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
    ok = failures = skipped = 0
    for pair in selected:
        try:
            rc = run_pair(ctx, pair)
        except OSError as e:
            # Si el dispositivo desaparece a mitad de pasada (#36), la pareja que
            # estaba en marcha falla con su log y su explicación, pero las de
            # detrás ni llegan a rclone: crear su carpeta local, escribir sus
            # filtros o arrancar el rclone, que vive en el dispositivo, fallan
            # antes. Cada una con su línea y contada como fallo, no con un
            # traceback que se lleva por delante el resumen y la nota de la flota.
            # Nada de esto se salta una comprobación: la pareja se corta ahí.
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


# ---------------------------------------------------------------------------
# Informes (no tocan nada)
# ---------------------------------------------------------------------------

def list_pairs(config: Config) -> int:
    print("Parejas configuradas:")
    for pair in config.pairs:
        print(f"  - {pair.name:<15} {pair.mode.name:<12} "
              f"{pair.local_endpoint}  <->  {pair.remote_endpoint}")
    return 0


def doctor(config: Config) -> int:
    """El estado del dispositivo, en texto. No toca nada.

    El diagnóstico no está aquí: lo hace `common/revision.py`, que es también de
    donde saca sus averías la pantalla de «Reparación». Aquí solo se imprime, y
    por eso esta función es tan corta como debe: dos sitios que decidan qué está
    roto acaban discrepando, y el que se equivoque será el que no se mire."""
    for linea in revision.informe(config):
        print(linea)
    return 0


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
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

    Línea a línea aunque la salida sea una tubería, que es lo que es cuando
    lanza sync.py la ventana: Python llena las tuberías por bloques, y lo
    escrito llegaba todo junto al final, progreso incluido.

    Y en UTF-8, que no se coge solo: hacia una tubería Python codifica con la
    del sistema, que en Windows es cp1252. Todo lo que escribe este script está
    en castellano, así que las tildes llegaban descompuestas a la ventana y al
    diario del servicio, que leen UTF-8. En una consola de verdad ya era UTF-8,
    así que ahí no cambia nada.

    stderr también: por ahí salen los ConfigError («No existe el fichero de
    configuración…»), que es justo el texto que lee quien tiene un problema."""
    for flujo in (sys.stdout, sys.stderr):
        reconfigurar = getattr(flujo, "reconfigure", None)
        if reconfigurar is not None:
            reconfigurar(line_buffering=True, encoding="utf-8", errors="replace")


def main() -> int:
    preparar_salida()
    args = parse_args()

    # logs/ se crea solo cuando hay algo que guardar (ver dispose_log).
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

    # Deja constancia en la flota de que este dispositivo se ha usado, y de cómo
    # le ha ido. Va detrás de la pasada y nunca lanza (ver common/fleet.py): es
    # una nota para la ventana de parejas, no parte de la sincronización. Un
    # simulacro no cuenta, por lo mismo que no apunta resultados.
    if not ctx.dry_run:
        fleet.publicar(config)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
