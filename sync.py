#!/usr/bin/env python3
"""
sync.py — Sincronización portable Synology <-> pen mediante rclone.

Todo vive en el pen y no depende de nada instalado en la máquina salvo
Python 3.11+ (para tomllib). El binario de rclone es portable (carpeta bin/).

    common/model.py   el TOML convertido en objetos ya resueltos
    common/bisync.py  lo que replica el comportamiento interno de rclone bisync
    ui/               la ventana y el menu de consola (los usa runsync.py)
    sync.py           este fichero: construir el comando, ejecutarlo y contarlo

Estructura esperada en el pen:

    PEN/
    ├── rclone-sync/
    │   ├── sync.py            <- este script
    │   ├── common/            <- config, bisync y ficheros de estado
    │   ├── ui/                <- la interfaz (la usa runsync.py)
    │   ├── sync_config.toml   <- qué carpetas sincronizar y en qué dirección
    │   ├── rclone.conf        <- config de rclone (remote SFTP + ruta a la clave)
    │   ├── bin/<arch>/        <- binario portable de rclone (Windows y Linux)
    │   ├── keys/              <- clave privada SSH (el pen ya va cifrado)
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
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Mapping

from common import bisync, model
from common.model import Config, Pair

LOG_TAIL_LINES = 15  # líneas de log que se vuelcan a consola cuando algo falla
SKIPPED = -1         # código interno: pareja no ejecutada (ni OK ni fallo)

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
    ("--max-delete",
     "Se han superado los borrados permitidos. Comprueba que la ruta local NO "
     "esté vacía o desmontada antes de forzar nada."),
    ("Access is denied",
     "Fichero bloqueado por otro proceso (Obsidian, KeePass, antivirus)."),
    ("lock file",
     "Hay un lock de otra ejecución. Si no hay ninguna corriendo, borra el .lck "
     "del workdir de la pareja."),
    ("known_hosts_file",
     "rclone no encuentra el fichero de known_hosts indicado en rclone.conf. "
     "Las rutas relativas de rclone.conf se resuelven contra rclone-sync/; "
     "comprueba que keys/known_hosts existe ahí."),
    ("Failed to create file system",
     "rclone no ha podido montar uno de los dos extremos. Suele ser una ruta o "
     "credencial mal resuelta en rclone.conf (revisa key_file y "
     "known_hosts_file), o el NAS inalcanzable."),
]


# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------

def temp_log(name: str) -> Path:
    """rclone escribe siempre a un log, pero en un temporal del sistema.

    Solo se conserva (moviéndolo a logs/) si la ejecución ha fallado. Si todo va
    bien no queda rastro y no se escribe en el pen: menos ciclos de escritura y
    una carpeta logs/ que solo contiene lo que hay que mirar."""
    fd, path = tempfile.mkstemp(prefix=f"rclone-sync-{name}-", suffix=".log")
    os.close(fd)
    return Path(path)


def keep_log(name: str, tmp: Path) -> Path:
    """Mueve un log temporal a logs/ y devuelve su ruta definitiva."""
    model.LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    final = model.LOG_DIR / f"{name}_{stamp}.log"
    n = 1
    while final.exists():  # ejecución + reintento dentro del mismo segundo
        final = model.LOG_DIR / f"{name}_{stamp}_{n}.log"
        n += 1
    shutil.move(str(tmp), str(final))
    return final


def dispose_log(name: str, tmp: Path, rc: int, keep_always: bool) -> Path | None:
    """Descarta el log si la ejecución fue bien; si no, lo guarda en logs/."""
    if rc == 0 and not keep_always:
        tmp.unlink(missing_ok=True)
        return None
    return keep_log(name, tmp)


def print_log_tail(lpath: Path | None, lines: int = LOG_TAIL_LINES) -> None:
    if lpath is None or not lpath.exists():
        return
    tail = lpath.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]
    print(f"--- últimas {len(tail)} líneas de {lpath.name} ---")
    for line in tail:
        print("  " + line)
    print("---")


def explain_failure(lpath: Path | None) -> None:
    """Traduce el error de rclone a algo accionable. Los casos nuevos se añaden a
    KNOWN_ERRORS, nunca en quien llama."""
    if lpath is None or not lpath.exists():
        return
    text = lpath.read_text(encoding="utf-8", errors="replace")
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

def flags_to_args(flags: Mapping) -> list[str]:
    """{nombre: valor} -> argumentos de rclone.

        clave = true          -> --clave
        clave = false / None  -> (se omite)
        clave = 4 / "texto"   -> --clave 4 / --clave texto
        clave = ["a", "b"]    -> --clave a --clave b
    """
    args: list[str] = []
    for key, value in flags.items():
        flag = "--" + str(key).replace("_", "-")
        if value is True:
            args.append(flag)
        elif value is False or value is None:
            continue
        elif isinstance(value, (list, tuple)):
            args += [item for v in value for item in (flag, str(v))]
        else:
            args += [flag, str(value)]
    return args


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

    cmd = [ctx.binary, pair.mode.verb, pair.source, pair.dest]
    cmd += filter_args(pair, ffile)
    cmd += flags_to_args(flags)
    cmd += list(pair.extra_flags)
    return cmd, logfile


def execute(ctx: RunContext, cmd: list[str]) -> int:
    print(f"  ejecutando{ctx.tag}: " + " ".join(cmd))
    # cwd FIJO en rclone-sync/: rclone.conf usa rutas relativas (key_file,
    # known_hosts_file) para que el pen siga siendo portable, y esas rutas se
    # resuelven contra el directorio de trabajo. No se puede depender de quién
    # nos haya lanzado ni desde dónde.
    kwargs: dict = {"cwd": str(model.APP_DIR)}
    if os.name == "nt":
        # Sin esto, cada invocación abre una ventana de consola cuando quien
        # llama no tiene una (pythonw, el servicio). La salida va al --log-file.
        kwargs["creationflags"] = model.CREATE_NO_WINDOW
    return subprocess.run(cmd, env={**os.environ, **ctx.env}, **kwargs).returncode


# ---------------------------------------------------------------------------
# Ejecución de una pareja
# ---------------------------------------------------------------------------

def _bisync_preflight(ctx: RunContext, pair: Pair) -> tuple[bool, int | None]:
    """Comprobaciones previas de una pareja bisync.

    Devuelve (hace_falta_resync, código_con_el_que_abortar). Con código None se
    puede seguir adelante."""
    bisync.migrate_legacy_state(pair)
    bisync.normalize_prefix(pair)

    state = bisync.pair_state(pair)
    print(f"  estado: {state.status} — {state.detail}")

    reasons = bisync.resync_reasons(pair, state)
    need_resync = ctx.force_resync or bool(reasons)
    if need_resync and not ctx.resync_approved:
        for reason in reasons:
            print(f"  requiere --resync -> {reason}")
        print(f"[{pair.name}] Saltada: requiere --resync y no está aprobado.")
        return need_resync, SKIPPED

    # Si YA había baseline y la carpeta local no está, algo va mal (pen a medio
    # montar). Crearla vacía haría que bisync viese "han borrado todo".
    if state.has_baseline and not pair.local_abs.exists():
        print(f"[{pair.name}] ERROR: existe baseline pero la ruta local "
              f"'{pair.local_abs}' no existe. Se aborta (no se crea vacía a propósito).")
        return need_resync, 2

    return need_resync, None


def run_pair(ctx: RunContext, pair: Pair) -> int:
    print(f"\n=== {pair.name} ({pair.mode.name}){ctx.tag} ===")

    need_resync = ctx.force_resync
    if pair.is_bisync:
        need_resync, abort_code = _bisync_preflight(ctx, pair)
        if abort_code is not None:
            return abort_code

    if not pair.local_abs.exists():
        print(f"[{pair.name}] La ruta local '{pair.local_abs}' no existe. Creándola...")
        pair.local_abs.mkdir(parents=True, exist_ok=True)

    ffile = bisync.filters_file_for(pair)
    cmd, logfile = build_command(ctx, pair, ffile, need_resync)
    rc = execute(ctx, cmd)

    # Un solo reintento, y solo si podemos reparar el estado con certeza. El log
    # del intento fallido se conserva aunque el reintento salga bien: documenta
    # por qué hubo que reparar nada.
    if rc != 0 and pair.is_bisync and not ctx.dry_run and bisync.heal_listings(pair, logfile):
        dispose_log(pair.name, logfile, rc, keep_always=False)
        print(f"[{pair.name}] Reintentando tras reparar los listados...")
        cmd, logfile = build_command(ctx, pair, ffile, need_resync=False)
        rc = execute(ctx, cmd)

    saved = dispose_log(pair.name, logfile, rc, ctx.keep_logs)
    if rc == 0:
        print(f"[{pair.name}] OK." + (f" Log: {saved}" if saved else ""))
    else:
        print(f"[{pair.name}] FALLÓ (código {rc}). Log: {saved}")
        print_log_tail(saved)
        explain_failure(saved)
    return rc


def resolve_resync_approval(selected: list[Pair], assume_yes: bool) -> bool:
    """Decide UNA vez si se aprueban los --resync auto-detectados, en lugar de ir
    preguntando pareja por pareja a mitad de faena."""
    pending = []
    for pair in selected:
        if not pair.is_bisync:
            continue
        bisync.migrate_legacy_state(pair)
        bisync.normalize_prefix(pair)
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
        rc = run_pair(ctx, pair)
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


def _doctor_pair(pair: Pair) -> bool:
    """Diagnostica una pareja e informa. Devuelve True si requiere atención."""
    print(f"[{pair.name}] {pair.mode.name}")
    local_ok = pair.local_abs.exists()
    print(f"  local : {pair.local_endpoint} {'(OK)' if local_ok else '(NO EXISTE)'}")
    print(f"  remoto: {pair.remote_endpoint}")
    if not pair.is_bisync:
        print()
        return False

    state = bisync.pair_state(pair)
    want = bisync.expected_prefix(pair)
    print(f"  estado: {state.status} — {state.detail}")
    print(f"  prefijo esperado: {want}")
    if state.prefix and state.prefix != want:
        print("  AVISO: el baseline está guardado con otro prefijo; se renombrará "
              "en la próxima ejecución.")
    filters = bisync.filters_state(bisync.filters_file_for(pair))
    print(f"  filtros: {filters.status} — {filters.detail}")

    if pair.workdir.exists():
        for f in sorted(pair.workdir.iterdir()):
            if f.is_file():
                ts = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
                print(f"    {f.name:<62} {ts}")
        if list(pair.workdir.glob("*.lck")):
            print("  AVISO: hay lock(s). Si no hay ninguna ejecución en curso, "
                  "bórralos o espera a que caduquen (--max-lock).")
    print()
    return not state.has_baseline or filters.needs_resync or not local_ok


def doctor(config: Config) -> int:
    print(f"Pen detectado en: {model.PEN_ROOT}")
    print(f"Workdir de estado: {model.STATE_DIR}")
    if config.pen_remote:
        for key, value in config.pen_environment().items():
            print(f"  {key}={value}")
    else:
        print("  (sin pen_remote: el lado local va como ruta absoluta, el nombre "
              "de los listados depende de la letra de unidad)")
    print()

    stray = sorted(model.STATE_DIR.glob("*.lst")) if model.STATE_DIR.exists() else []
    if stray:
        print(f"Aviso: {len(stray)} listado(s) sueltos en la raíz de state/ "
              f"(layout antiguo). Se migrarán al ejecutar.\n")

    problems = sum(_doctor_pair(pair) for pair in config.pairs)
    print("Sin incidencias." if not problems else f"{problems} pareja(s) requieren atención.")
    return 0


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sincronización portable Synology <-> pen (rclone)."
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


def main() -> int:
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
    )
    return run_all(ctx, selected)


if __name__ == "__main__":
    raise SystemExit(main())
