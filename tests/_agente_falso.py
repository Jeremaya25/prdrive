#!/usr/bin/env python3
"""Lo que comparten los tests del agente residente.

Un equipo de mentira para `agente.py`: su carpeta en un temporal, unidades
falsas (carpetas con `.prdrive/PRDRIVE`, `runsync.py`, `sync.py` y un
`sync_config.toml`) que `penwatch.candidate_roots()` «encuentra», un reloj que
avanza a mano, procesos que no se lanzan (`Proc`) y avisos y diario que se
apuntan en listas. Nada toca el sistema de verdad.
"""

from __future__ import annotations

import os
from pathlib import Path

from _harness import tmpdir

import agente
import penwatch
from common import equipo, moderacion, store


class Proc:
    """Un proceso que no se lanza: el test decide cuándo acaba y con qué."""

    def __init__(self, args, **kwargs):
        """Apunta el proceso en `LANZADOS`, sin lanzar nada."""
        self.args = [str(a) for a in args]
        self.kwargs = kwargs
        self.rc: int | None = None
        self.terminado = False
        LANZADOS.append(self)

    def poll(self):
        """Devuelve el código de salida, o `None` si sigue vivo."""
        return self.rc

    def terminate(self):
        """Lo termina (código -15) si no había acabado."""
        self.terminado = True
        if self.rc is None:
            self.rc = -15


LANZADOS: list[Proc] = []
"""Los procesos que el agente ha «lanzado»."""
AVISOS: list[tuple[str, str]] = []
"""Los avisos que ha dado, como `(título, texto)`."""
DIARIO: list[str] = []
"""Lo que ha dicho en su diario."""
ABIERTOS: list[Path] = []
"""Los contenedores que se han pedido abrir."""
RAICES: list[Path] = []
"""Lo que «encuentra» el recorrido."""
RELOJ = [1_000_000.0]
"""La hora, en una lista de un elemento para poder avanzarla (`pasar()`)."""
PANTALLA = [True]
"""Si hay pantalla donde abrir ventanas, en una lista para poder cambiarla."""
RCLONE: list = [None]
"""El rclone del agente; `[None]` es sin él."""
VERSION = (Path(__file__).resolve().parent.parent / "VERSION").read_text(
    encoding="utf-8").strip()
"""La de las unidades de mentira: la de este código."""


def preparar() -> Path:
    """Apunta el agente a un equipo de mentira. Devuelve su carpeta."""
    equipo.DIR = tmpdir("prdrive-equipo-")
    agente.lanzar = lambda args, **kw: Proc(args, **kw)
    agente.avisar = lambda t, x, u=False: AVISOS.append((t, x)) or True
    agente.diario = DIARIO.append
    agente.hay_pantalla = lambda: PANTALLA[0]
    agente.abrir_contenedor = lambda raiz: ABIERTOS.append(Path(raiz)) or True
    penwatch.candidate_roots = lambda cfg: list(RAICES)
    moderacion.energia = lambda: moderacion.Energia()
    moderacion.red_medida = lambda: False
    # Ni una pregunta a GitHub: la versión nueva la pone el test que la quiera
    # y lo que iría en un hilo corre en el sitio.
    agente.buscar_version = lambda: None
    agente.hilo = lambda funcion: funcion()
    # Ni el registro de verdad, en un Windows: las claves del navegador.
    agente.limpiar_navegador = lambda: (0, [])
    # Su rclone: el que pasa a sus hijos y con el que sondea (no hace nada).
    rclone = equipo.DIR / "rclone" / "v0" / agente.model.rclone_name()
    rclone.parent.mkdir(parents=True, exist_ok=True)
    rclone.write_text("", encoding="utf-8")
    RCLONE[:] = [rclone]
    agente.rclone_propio = lambda: RCLONE[0]
    return equipo.DIR


def reloj() -> float:
    """Devuelve la hora del reloj de mentira."""
    return RELOJ[0]


def pasar(segundos: float) -> None:
    """Avanza el reloj de mentira `segundos`."""
    RELOJ[0] += segundos


def unidad(uid: str, parejas=("docs", "fotos"), nombre: str | None = None,
           daemon: str = "", extra: dict | None = None,
           locales: dict | None = None) -> Path:
    """Una unidad prdrive de mentira, con su id y sus parejas.

    Args:
        uid: El id de la unidad.
        parejas: Los nombres de sus parejas.
        nombre: Su nombre en la flota, si lo tiene.
        daemon: Lo que va tras `[defaults]` (la tabla `[daemon]`).
        extra: Líneas de TOML que añadir a algunas parejas, por nombre
            (`{"docs": "watch = true\\n"}`).
        locales: La `local` de las parejas que no usan `sync-data/<nombre>`.
    """
    extra, locales = extra or {}, locales or {}
    raiz = tmpdir(f"prdrive-unidad-{uid[:4]}-")
    app = raiz / penwatch.APP_SUBDIR
    (app / "state").mkdir(parents=True)
    (app / "PRDRIVE").write_text(f"id={uid}\n", encoding="utf-8")
    (app / "VERSION").write_text(VERSION + "\n", encoding="utf-8")
    for nombre_py in ("runsync.py", "sync.py"):
        (app / nombre_py).write_text("# de mentira\n", encoding="utf-8")
    pares = "".join(f'[[pair]]\nname = "{p}"\nlocal = "{locales.get(p, f"sync-data/{p}")}"\n'
                    f'remote_path = "/R/{p}"\n{extra.get(p, "")}\n' for p in parejas)
    (app / "sync_config.toml").write_text(
        f'[defaults]\nremote = "nas"\n\n{daemon}\n{pares}', encoding="utf-8")
    if nombre:
        store.write_json(app / "state" / "fleet.json", {"nombre": nombre})
    return raiz


def lock(raiz: Path) -> dict:
    """Devuelve el `daemon.lock.json` de la raíz, o `{}` si no hay."""
    return store.read_json(raiz / penwatch.DAEMON_LOCK_REL)


def stop(raiz: Path) -> Path:
    """Devuelve la ruta del `daemon.stop` de la raíz."""
    return raiz / penwatch.APP_SUBDIR / "state" / "daemon.stop"


def ventana_abierta(raiz: Path) -> None:
    """Escribe lo que escribe runsync al abrir su ventana.

    Es un pid vivo de este equipo que no es el del agente (el del proceso padre
    de los tests).
    """
    store.write_json(raiz / penwatch.UI_LOCK_REL,
                     {"pid": os.getppid(), "host": penwatch.HOST, "started": "x"})


def otro_servicio(raiz: Path, host: str | None = None, pid: int | None = None) -> None:
    """Escribe en la raíz el lock de otro servicio.

    Por defecto es de este equipo y de un pid vivo.

    Args:
        raiz: La raíz de la unidad.
        host: El equipo del lock; por defecto, este.
        pid: El pid del lock; por defecto, el del padre de este proceso.
    """
    store.write_json(raiz / penwatch.DAEMON_LOCK_REL,
                     {"pid": os.getppid() if pid is None else pid,
                      "host": host or penwatch.HOST, "started": "x", "pairs": ["docs"]})


def pasadas(raiz: Path | None = None) -> list[Proc]:
    """Los `sync.py` lanzados (de esa raíz, si se dice)."""
    return [p for p in LANZADOS if len(p.args) > 1 and p.args[1].endswith("sync.py")
            and not p.args[1].endswith("runsync.py")
            and (raiz is None or p.args[1].startswith(str(raiz)))]


def acabar(proc: Proc, rc: int = 0, salida: str = "") -> None:
    """Termina una pasada falsa como lo haría sync.py: su salida en el fichero."""
    (equipo.DIR / "pasada.out").write_text(salida, encoding="utf-8")
    proc.rc = rc


def nuevo() -> "agente.Agente":
    """Devuelve un agente con el reloj de mentira."""
    return agente.Agente(reloj=reloj)


def vueltas(ag, n: int = 1, cada: float = agente.TICK, recorrer: bool = True):
    """Da `n` vueltas al agente, avanzando el reloj `cada` segundos.

    Returns:
        La decisión de la última vuelta.
    """
    decision = None
    for _ in range(n):
        decision = ag.vuelta(recorrer)
        pasar(cada)
    return decision
