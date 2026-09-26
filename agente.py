#!/usr/bin/env python3
"""
agente.py — prdrive residente: un proceso por usuario que atiende las unidades.

Es el sucesor de `penwatch.py` en los equipos donde se instala: vive en el
equipo, FUERA de toda raíz (`common/equipo.py` dice dónde), arranca al iniciar
sesión con su propio Python y hace de servicio de cada unidad prdrive que se
enchufa y que tiene en su lista. Sin Tk: la ventana de una unidad y la pregunta
por una unidad nueva son procesos hijos.

    python agente.py run                  el bucle (lo lanza el registro al iniciar sesión)
    python agente.py status               qué atiende y cómo
    python agente.py atender ID           atender la unidad conectada a la que se dijo «Ahora no»
    python agente.py modo ID MODO         ui | daemon | sync | nada
    python agente.py pasada ID [PAREJA…]  «Sincronizar ahora», sin moderación
    python agente.py pausa | sigue        dejar de lanzar pasadas, y volver
    python agente.py parar                que termine (lo usa el instalador)
    python agente.py abrir [ID]           la ventana de la raíz de este equipo (o de esa)
    python agente.py desbloquear [ID]     abrir el contenedor de la raíz cifrada
    python agente.py bloquear [ID]        y cerrarlo
    python agente.py ajuste CLAVE VALOR   pedir_al_iniciar sí|no · espera_unidad_nueva SEG
    python agente.py actualizar           bajar la versión nueva y ponerla (lo que hace la bandeja)

Las órdenes que no son `run` no hacen nada por sí mismas: dejan la petición en
el buzón del agente (`equipo.pedir()`), que es quien escribe su configuración.

Cómo trabaja, vuelta a vuelta (`Agente.vuelta()`):

  1. **Detecta** las unidades con el mismo recorrido de siempre,
     `penwatch.candidate_roots()`, pero no cada 5 s: en Linux se despierta
     cuando cambia `/proc/self/mountinfo` (`POLLPRI`), y de ahí una racha de
     sondeos, porque un volumen cifrado se lee bastante después de montarse. En
     Windows, con el `WM_DEVICECHANGE` que recibe la ventana de la bandeja; sin
     bandeja, sondea como penwatch. Una unidad cuenta cuando se ha visto dos
     veces seguidas.
  2. **Pregunta** por las unidades que no conoce (sección «Una unidad nueva» del
     diseño): un aviso y una ventanita con cuenta atrás; sin respuesta es «Ahora
     no», solo para esta conexión. Antes del sí no se ejecuta NADA de la unidad:
     solo se leen su id y su nombre.
  3. **Hace de su servicio** con los ficheros que ya existen en su `state/`, así
     que funciona con unidades de código viejo: escribe `daemon.lock.json`,
     obedece `daemon.stop` (acaba la pareja en curso y suelta), se queda en pausa
     mientras haya una ventana de runsync abierta en este equipo, y se aparta si
     otro servicio vivo tiene el lock. Un servicio por raíz: el que tenga el lock.
  4. **Planifica** con `common/planificador.py`, que es puro: una sola pasada a la
     vez en todo el equipo, espera creciente tras un fallo, batería, red de uso
     medido, remotos sin conexión, «Sincronizar ahora».
  5. **Cada pasada es el `sync.py` de esa raíz**, hijo, con el Python del agente y
     el directorio de trabajo fuera de la raíz: cada raíz ejecuta su propio
     código, un rclone colgado no tumba al agente, y entre pasadas no queda nada
     abierto dentro de ninguna unidad, así que se puede expulsar.

La raíz de ESTE equipo (una carpeta del ordenador con `.prdrive/` dentro, que
pone el asistente «En este equipo») es una raíz más de la lista, con su `ruta`:
se busca ahí en vez de recorriendo volúmenes, y todo lo demás es igual. Si falta
—se ha movido o renombrado la carpeta—, se avisa una vez y no se lanza nada: una
línea base sin su carpeta local es justo lo que `_bisync_preflight()` frena.

La raíz del equipo puede vivir en un contenedor VeraCrypt (fase 3). Entonces el
agente es quien lo abre y quien lo cierra, con el VeraCrypt INSTALADO y sin que
la contraseña pase nunca por él:

  * **Desbloquear** lanza VeraCrypt con `/letter` fija (Windows) o el punto de
    montaje fijo (Linux) y sin `/password`: la pide su ventana. Abierta no es
    que VeraCrypt salga con 0, sino VER el id en la letra con el `.hc`
    retenido. Una letra con el id al lado de un `.hc` libre es el fantasma de
    las unidades (H-10): no se atiende, y se dice «Bloquear y volver a
    desbloquear». Con la letra de otro, o un punto de montaje con cosas, no se
    lanza nada: se dice.
  * **Al iniciar sesión**, con `pedir_al_iniciar`, se pide UNA vez; si se
    cancela, hasta que se pida «Desbloquear».
  * **Bloquear** deja de encolar la raíz, espera a la pareja en curso y a que
    se cierre su ventana, suelta el lock y lanza el desmontaje SIN `/silent`:
    si un programa tiene algo abierto dentro, VeraCrypt pregunta si forzar, y
    eso lo decide la persona. Bloqueada es el `.hc` libre, no la letra ida.
  * **Cerrada, simplemente no está**: no es un fallo, ni un aviso, ni una
    espera más larga. Una raíz cerrada no tiene carpeta ni línea base.

Avisa con los avisos del sistema (`common/avisos.py`), no con Tk, y solo cuando
una pareja EMPIEZA a fallar. Sin avisos, queda en su diario.

En Windows tiene un icono en la bandeja (fase 4): `ui/bandeja.py` decide qué
enseña a partir de `resumen()`, `ui/bandeja_windows.py` lo dibuja en su propio
hilo, y lo que se elige en su menú llega como las peticiones del buzón
(`Agente.pedir()`), por el mismo camino.

La ventana de una raíz le habla por dos buzones (fase 5): lo del equipo por
`agente.pide`, y lo de esa raíz —«Iniciar servicio» (`reanudar`), «Bloquear»—
por el `state/servicio.pide` de la propia raíz, que solo se lee en las raíces
de la lista. Y cuando hay una versión nueva, lo dice una vez; «Actualizar»
(`agente.py actualizar`) baja el código de la release y ejecuta SU instalador,
que pone el agente nuevo al lado de este, lo para y arranca el nuevo.

Depende de `penwatch.py` para detectar, leer los registros de runsync y abrir
VeraCrypt: el agente importa de penwatch, nunca al revés, y penwatch sigue sin
importar nada del proyecto.
"""

from __future__ import annotations

import argparse
import math
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import penwatch  # noqa: E402
from common import (APP_NAME, avisos, catalog, equipo, model, moderacion,  # noqa: E402
                    store, update, vestibulo)
from common import planificador as pl  # noqa: E402
from common.store import pid_alive  # noqa: E402
from ui import bandeja, prefs  # noqa: E402

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore

IS_WIN = os.name == "nt"
HOST = equipo.HOST
APP_SUBDIR = penwatch.APP_SUBDIR

TICK = 2.0                      # cada cuánto se mira lo barato: stop, ventana, hijos
RECORRIDO_WINDOWS = penwatch.POLL_SECONDS   # Windows sin bandeja: sin WM_DEVICECHANGE, como penwatch
RECORRIDO_RESPALDO = 30.0       # aunque mountinfo o WM_DEVICECHANGE no digan nada
RAFAGA = 60.0                   # tras un cambio de montajes, recorrer en cada vuelta
ESTABLE = penwatch.STABLE_CHECKS
GRACIA = 15.0                   # tras ver la ventana o un stop, antes de volver
MIRAR_ENTORNO = 60.0            # batería y red, cada minuto
PARAR_ESPERA = 10.0             # lo que espera `parar` a que el agente se vaya
ESPERA_VENTANA = 60.0           # «Bloquear» con su ventana abierta: lo que se espera
ESPERA_DESMONTAJE = 300.0       # a que VeraCrypt cierre (puede estar preguntando)
GRACIA_DESMONTAJE = 5.0         # tras salir VeraCrypt, a que el `.hc` quede libre
ESPERA_ABRIR = 180.0            # `abrir` con la raíz cerrada: a que se desbloquee
GRACIA_ABRIR = 20.0             # tras salir VeraCrypt, a ver la raíz abierta; si no, cancelada
COLA_SALIDA = 64 * 1024         # lo que se lee de la salida de una pasada
MIRAR_VERSION = 6 * 3600.0      # si hay versión nueva (`update.check` guarda 24 h)

OK, FALLO, RED, SALTADA = pl.OK, pl.FALLO, pl.RED, pl.SALTADA
TEXTO_RESULTADO = {OK: "bien", FALLO: "FALLÓ", RED: "FALLÓ por la red",
                   SALTADA: "saltada: pide --resync"}


# ---------------------------------------------------------------------------
# Puntos de indirección: lo que toca procesos, pantalla y avisos
# ---------------------------------------------------------------------------

def lanzar(args: list[str], **kwargs) -> Any:
    """Lanza un proceso hijo. De módulo para que los tests lo sustituyan."""
    return subprocess.Popen(args, **kwargs)


def hay_pantalla() -> bool:
    """¿Hay dónde abrir una ventana? En Windows, la sesión del usuario."""
    return IS_WIN or bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def avisar(titulo: str, texto: str, urgente: bool = False) -> bool:
    ok = avisos.enviar(titulo, texto, urgente)
    diario(f"aviso{'' if ok else ' (sin avisos del sistema: solo aquí)'}: "
           f"{titulo} — {texto}")
    return ok


def abrir_contenedor(raiz: Path) -> bool:
    return penwatch.open_container(raiz, cwd=equipo.DIR)


def diario(msg: str) -> None:
    penwatch.log(msg)


def hilo(funcion) -> None:
    """Corre `funcion` en un hilo aparte, para lo que puede tardar (la red).
    De módulo para que los tests la corran en el sitio."""
    threading.Thread(target=funcion, daemon=True).start()


def cache_version() -> Path:
    """Lo último que dijo GitHub, en la carpeta del agente: no vive en ninguna
    raíz, y el `state/` de su código se va con cada versión."""
    return equipo.DIR / "update.json"


def buscar_version() -> "update.Release | None":
    """La release más nueva que la versión de este agente, o None. Respeta la
    caché de `update.check()` (24 h), así que casi nunca sale a la red."""
    update.check(cache=cache_version())
    return update.pending(SCRIPT_DIR, cache=cache_version())


def ejecutar(args: list[str], **kwargs) -> Any:
    """Corre un proceso hasta que acaba. De módulo para los tests."""
    return subprocess.run(args, **kwargs)


def python(ventana: bool = False) -> str:
    """El Python del agente, para sus hijos: sin consola en Windows."""
    exe = sys.executable
    if IS_WIN:
        w = Path(exe).with_name("pythonw.exe")
        if w.is_file():
            return str(w)
    return exe


def _opciones_hijo(cwd: Path, separado: bool = False) -> dict:
    kwargs: dict = {"stdin": subprocess.DEVNULL, "cwd": str(cwd), "close_fds": True}
    if IS_WIN:
        kwargs["creationflags"] = penwatch.CREATE_NO_WINDOW | (
            penwatch.CREATE_NEW_PROCESS_GROUP if separado else 0)
    elif separado:
        kwargs["start_new_session"] = True
    return kwargs


# ---------------------------------------------------------------------------
# Lo que se lee de una raíz (sin ejecutar nada suyo)
# ---------------------------------------------------------------------------

def app(raiz: Path) -> Path:
    return raiz / APP_SUBDIR


def estado_de(raiz: Path) -> Path:
    return app(raiz) / "state"


def nombre_de(raiz: Path, uid: str, recordado: str = "") -> str:
    """El nombre de la unidad en la flota, de su `state/fleet.json` (solo se lee);
    si no tiene, el que el agente recuerda de ella, y si no, el principio del id."""
    guardado = store.read_json(estado_de(raiz) / "fleet.json").get("nombre")
    if isinstance(guardado, str) and guardado.strip():
        return guardado.strip()
    return recordado or f"{APP_NAME.upper()} {uid[:8]}"


@dataclass(frozen=True)
class Servicio:
    """Lo que el servicio de una raíz sincroniza: sus parejas y cada cuánto."""
    parejas: tuple[pl.Pareja, ...]
    minutos: float


def leer_servicio(raiz: Path) -> Servicio:
    """Las parejas y el intervalo del servicio de esa raíz, como los elegiría su
    propio runsync: `ui_prefs.json` > `[daemon]` > todas (`prefs.elegir()`).

    Se lee el TOML a pelo y no con `model.parse_config()` porque la raíz puede
    ir en otra versión que el agente: lo que valida es su `sync.py`, y un modo
    que este agente no conozca no puede dejarla sin servicio. ValueError con la
    frase que decir si no hay nada que atender."""
    try:
        crudo = tomllib.loads((app(raiz) / "sync_config.toml").read_text(encoding="utf-8"))
    except OSError as e:
        raise ValueError(f"no se puede leer sync_config.toml ({e})") from e
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"sync_config.toml no es TOML válido ({e})") from e
    defaults = crudo.get("defaults") if isinstance(crudo.get("defaults"), dict) else {}
    remotos: dict[str, str] = {}
    for p in crudo.get("pair") if isinstance(crudo.get("pair"), list) else []:
        if isinstance(p, dict) and isinstance(p.get("name"), str):
            remotos[p["name"]] = str(p.get("remote", defaults.get("remote",
                                                                  model.DEFAULT_REMOTE)))
    if not remotos:
        raise ValueError("sync_config.toml no tiene ninguna pareja")
    daemon = crudo.get("daemon") if isinstance(crudo.get("daemon"), dict) else {}
    elegidas, minutos, _ = prefs.elegir(list(remotos), daemon,
                                        store.read_json(estado_de(raiz) / "ui_prefs.json"))
    return Servicio(tuple(pl.Pareja(n, remotos[n]) for n in elegidas), minutos)


def orden_sonda(raiz: Path, remoto: str) -> list[str] | None:
    """rclone de esa raíz preguntando por el remoto, o None si no lleva rclone.

    `lsd` del remoto con `catalog.NET_FLAGS`: lo mínimo que exige conectar y
    entrar, y con los plazos cortos para que un remoto caído no tenga la cola
    parada."""
    carpeta = app(raiz)
    for bin_dir in model.carpetas_bin(carpeta):
        binario = bin_dir / model.rclone_name()
        try:
            if binario.is_file():
                return [model.ejecutable(binario), "--config", str(carpeta / "rclone.conf"),
                        *catalog.NET_FLAGS, "lsd", f"{remoto}:", "--max-depth", "1"]
        except OSError:
            continue
    return None


def dlog(raiz: Path, msg: str) -> None:
    """El diario del servicio de la raíz (`state/daemon.log`), como el de runsync.
    Se abre y se cierra en cada línea: nada se queda abierto en la unidad."""
    ruta = estado_de(raiz) / "daemon.log"
    try:
        with ruta.open("a", encoding="utf-8") as f:
            f.write(f"{store.stamp()} {msg}\n")
    except OSError:
        pass


def presente(raiz: Path) -> bool:
    try:
        return (raiz / penwatch.CONTROL_FILE).is_file()
    except OSError:
        return False


def punto_ocupado(unidad: equipo.Unidad) -> str | None:
    """Por qué no se puede montar ahí la raíz cifrada, o None si se puede.

    El agente no se inventa otra letra ni otro sitio: los programas apuntan a la
    raíz, y un almacén de Obsidian en `P:\\obsidian` se rompería si mañana
    fuera `Q:`. En Linux, el punto de montaje vacío es una carpeta normal, y lo
    que se guarde ahí con el contenedor cerrado quedaría tapado al montarlo."""
    if unidad.letra:
        raiz = Path(f"{unidad.letra}:\\")
        try:
            existe = raiz.exists()
        except OSError:
            existe = True
        if not existe:
            return None
        try:
            suya = penwatch.control_id(raiz) == unidad.id
        except OSError:
            suya = False
        if suya:
            return (f"La letra {unidad.letra}: tiene su raíz, pero el contenedor está "
                    f"cerrado: es un volumen fantasma (se desconectó sin bloquear). "
                    f"Bloquéala y vuelve a desbloquearla.")
        return (f"La letra {unidad.letra}: está ocupada por otra unidad, y no se "
                f"cambia: los programas apuntan a {unidad.letra}:\\. Libérala y "
                f"vuelve a desbloquear.")
    punto = Path(unidad.ruta)
    try:
        if os.path.ismount(punto):
            return f"Ya hay algo montado en {punto}."
        if punto.is_dir() and any(punto.iterdir()):
            return (f"{punto} tiene cosas con el contenedor cerrado: no se monta "
                    f"encima, porque quedarían tapadas. Muévelas a otro sitio y "
                    f"vuelve a desbloquear.")
    except OSError as e:
        return f"No puedo mirar {punto}: {e}"
    return None


def bloqueada(unidad: equipo.Unidad) -> bool:
    """¿Está cerrado ya el contenedor de esa raíz?

    En Windows, que la letra se vaya no basta: forzando el desmontaje con un
    fichero abierto dentro, la letra desaparece y el driver sigue reteniendo el
    `.hc`. Bloqueada es el `.hc` libre y la letra ida (la de un fantasma también
    tiene que irse). En Linux no hay esa prueba (`vestibulo.retenido()` no
    contesta): es el punto de montaje sin montar."""
    raiz = Path(unidad.ruta)
    if unidad.letra:
        return vestibulo.retenido(unidad.contenedor) is not True and not presente(raiz)
    try:
        return not os.path.ismount(raiz) and not presente(raiz)
    except OSError:
        return False


def orden_bloquear(unidad: equipo.Unidad) -> list[str] | None:
    """El desmontaje de la raíz cifrada, SIN `/silent`, como `Expulsar
    PRDRIVE.bat`: con un fichero abierto dentro VeraCrypt pregunta si forzar, y
    esa decisión es de la persona. None sin VeraCrypt instalado."""
    exe = penwatch.installed_veracrypt()
    if exe is None:
        return None
    if IS_WIN:
        return [exe, "/dismount", unidad.letra or unidad.ruta[:1], "/quit"]
    if hay_pantalla():
        return [exe, "-d", unidad.contenedor]
    return [exe, "--text", "--non-interactive", "-d", unidad.contenedor]


def resultado(rc: int, texto: str) -> str:
    """Cómo acabó una pasada, con el mismo criterio que `runsync.daemon_cycle()`."""
    if rc != 0:
        return RED if moderacion.es_de_red(texto) else FALLO
    if "saltada" in texto.lower():
        return SALTADA
    return OK


# ---------------------------------------------------------------------------
# Lo que el agente recuerda de cada unidad conectada
# ---------------------------------------------------------------------------

@dataclass
class Conexion:
    id: str
    raiz: Path
    nombre: str
    desde: float
    # Una unidad que no está en la lista.
    pregunta: pl.Pregunta | None = None
    hijo: Any = None                    # la ventanita de la pregunta
    respuesta: str | None = None        # AHORA_NO, para esta conexión
    # Una que sí.
    lanzada: bool = False               # modo ui: su ventana ya se ha abierto
    pausa: float | None = None          # la última vez que se vio ventana o stop
    lock: dict | None = None            # el daemon.lock.json que tenemos escrito
    servicio: Servicio | None = None
    error: str | None = None            # por qué no hay servicio que atender
    avisado_error: bool = False
    firma: tuple = ()                   # mtimes de lo que decide el servicio
    motivo: str = ""                    # qué le pasa, para `status`
    # «Iniciar servicio» en su ventana (`reanudar` en su buzón): al irse la
    # ventana se vuelve enseguida, sin la `GRACIA` que se da a un servicio que
    # la ventana arrancara por su cuenta.
    reanudar: bool = False


@dataclass
class Desbloqueo:
    """«Desbloquear», lanzado: VeraCrypt está pidiendo la contraseña."""
    desde: float
    proc: Any = None                    # el VeraCrypt que monta
    salio: float | None = None          # cuándo se vio que había salido
    abrir: bool = False                 # abrir su ventana en cuanto se vea abierta


@dataclass
class Bloqueo:
    """«Bloquear», pedido y todavía no hecho."""
    desde: float
    proc: Any = None                    # el VeraCrypt que desmonta, ya lanzado
    lanzado: float = 0.0


@dataclass
class Pasada:
    proc: Any
    tarea: pl.Tarea
    desde: float
    salida: Path
    nombre: str


@dataclass
class Agente:
    reloj: Any = time.time
    ajustes: equipo.Ajustes = field(default_factory=equipo.leer_ajustes)
    conexiones: dict[str, Conexion] = field(default_factory=dict)
    vistas: dict[str, int] = field(default_factory=dict)
    cerradas: dict[str, int] = field(default_factory=dict)
    vestibulos: dict[str, str] = field(default_factory=dict)
    marcas: dict[tuple[str, str], pl.Marca] = field(default_factory=dict)
    entorno: pl.Entorno = field(default_factory=pl.Entorno)
    entorno_leido: float = -math.inf
    pasada: Pasada | None = None
    urgentes: list[tuple[str, str]] = field(default_factory=list)
    pausado: bool = False
    terminar: bool = False
    sospechas: dict[tuple[str, str], tuple[str, pl.Marca]] = field(default_factory=dict)
    sin_red_avisado: set[tuple[str, str]] = field(default_factory=set)
    retenido: str | None = None
    rafaga_hasta: float = -math.inf
    ultimo_estado: dict | None = None
    # Las raíces del equipo que no están donde dice su `ruta`, ya avisadas.
    ausentes: set[str] = field(default_factory=set)
    # La raíz cifrada: cuándo se lanzó VeraCrypt para abrirla, las que ya se
    # pidieron al iniciar sesión (una vez), los «Bloquear» en marcha, y los
    # volúmenes fantasma ya dichos.
    desbloqueos: dict[str, Desbloqueo] = field(default_factory=dict)
    pedidas: set[str] = field(default_factory=set)
    bloqueos: dict[str, Bloqueo] = field(default_factory=dict)
    fantasmas: set[str] = field(default_factory=set)
    recorridos: int = 0
    # Lo que pide la bandeja, que corre en otro hilo: los mismos diccionarios
    # que el buzón, sin pasar por disco. Y la bandeja misma, si la hay
    # (`poner(vista)`), para enseñarle el estado.
    peticiones: Any = field(default_factory=queue.SimpleQueue)
    bandeja: Any = None
    # Cuándo arrancó, en hora de verdad (`equipo.pedir()` sella con ella): un
    # «parar» de antes iba para el agente anterior.
    inicio: float = field(default_factory=time.time)
    # Su versión, la más nueva que se sabe (su tag, o None), cuándo se miró,
    # la que ya se avisó, y el `agente.py actualizar` en marcha.
    version: str = field(default_factory=lambda: update.installed_version(SCRIPT_DIR))
    nueva: str | None = None
    version_mirada: float = -math.inf
    nueva_avisada: str | None = None
    actualizando: Any = None

    # --- la vuelta ---------------------------------------------------------------

    def vuelta(self, recorrer: bool = True) -> pl.Decision | None:
        ahora = self.reloj()
        self._buzon(ahora)
        if recorrer:
            self._recorrer(ahora)
            self._al_iniciar(ahora)
        self._seguir_desbloqueos(ahora)
        for con in list(self.conexiones.values()):
            if not presente(con.raiz):
                self._desconectar(con.id, ahora, {})
        self._preguntas(ahora)
        self._fin_de_pasada(ahora)
        self._buzones_de_raices(ahora)
        self._bloqueos(ahora)
        for con in self.conexiones.values():
            self._contrato(con, ahora)
        self._leer_entorno(ahora)
        self._mirar_version(ahora)
        decision = None
        if self.pasada is None and not self.terminar:
            decision = self._decidir(ahora)
        self._escribir_estado()
        return decision

    # --- detectar ------------------------------------------------------------------

    def _recorrer(self, ahora: float) -> None:
        abiertas: dict[str, Path] = {}
        cerradas: dict[str, Path] = {}
        # Las raíces del equipo, primero y por su ruta: son carpetas, no
        # volúmenes, y el recorrido no las vería. Van como las raíces extra de
        # penwatch, así que el recorrido sigue siendo uno.
        propias = [u.ruta for u in self.ajustes.raices.values()]
        for raiz in penwatch.candidate_roots(
                {"extra_roots": propias + list(self.ajustes.extra_roots)}):
            try:
                if (raiz / penwatch.CONTROL_FILE).is_file():
                    if not (raiz / penwatch.STRUCT_MARKER).is_file():
                        continue
                    uid = penwatch.control_id(raiz)
                    if uid:
                        abiertas.setdefault(uid, raiz)
                elif ((raiz / penwatch.VESTIBULE_MARKER).is_file()
                      and (raiz / penwatch.CONTAINER_FILE).is_file()):
                    uid = penwatch.vestibule_id(raiz)
                    if uid:
                        cerradas.setdefault(uid, raiz)
            except OSError:
                continue            # un volumen bloqueado contesta con error: ahora no
        self._fantasmas(abiertas)

        for uid in list(self.vistas):
            if uid not in abiertas:
                del self.vistas[uid]
        for uid, raiz in abiertas.items():
            con = self.conexiones.get(uid)
            if con is not None:
                con.raiz = raiz                 # remontada en otra letra
                continue
            self.vistas[uid] = self.vistas.get(uid, 0) + 1
            if self.vistas[uid] >= ESTABLE:
                del self.vistas[uid]
                self._conectar(uid, raiz, ahora)
            else:
                self.rafaga_hasta = max(self.rafaga_hasta, ahora + 3 * TICK)
        for uid in list(self.conexiones):
            if uid not in abiertas:
                self._desconectar(uid, ahora, cerradas)
        self._vestibulos(cerradas, ahora)
        self._raices_ausentes(abiertas)
        self.recorridos += 1

    def _fantasmas(self, abiertas: dict[str, Path]) -> None:
        """Una raíz cifrada vista en su letra con el `.hc` LIBRE no está abierta:
        es lo que deja un volumen que se fue sin desmontar (suspender con el
        cierre automático de VeraCrypt, H-10), que sirve el fichero de control
        de la caché. No se atiende, y se dice una vez cómo salir."""
        for uid, unidad in self.ajustes.cifradas.items():
            if uid not in abiertas:
                self.fantasmas.discard(uid)
                continue
            if vestibulo.retenido(unidad.contenedor) is not False:
                self.fantasmas.discard(uid)
                continue
            del abiertas[uid]
            if uid not in self.fantasmas:
                self.fantasmas.add(uid)
                avisar(f"{unidad.nombre or APP_NAME}: el volumen no responde",
                       f"{unidad.ruta} sigue ahí, pero su contenedor está cerrado. "
                       f"Bloquéala y vuelve a desbloquearla.", True)

    def _raices_ausentes(self, abiertas: dict[str, Path]) -> None:
        """Una raíz del equipo que no está en su ruta se dice UNA vez. No se
        busca en otro sitio ni se recrea: mover la carpeta deja las líneas base
        apuntando a lo que ya no está, y eso se arregla reinstalando."""
        for uid, unidad in self.ajustes.raices.items():
            if uid in abiertas:
                if uid in self.ausentes:
                    self.ausentes.discard(uid)
                    diario(f"{unidad.nombre or uid[:8]}: la raíz vuelve a estar en "
                           f"{unidad.ruta}")
                continue
            if unidad.cifrada:
                # Cerrada no es ausente: es lo normal con el contenedor bloqueado.
                # Lo que falta es el contenedor mismo.
                try:
                    hay = Path(unidad.contenedor).is_file()
                except OSError:
                    hay = True
                if hay:
                    if uid in self.ausentes:
                        self.ausentes.discard(uid)
                        diario(f"{unidad.nombre or uid[:8]}: su contenedor vuelve a "
                               f"estar en {unidad.contenedor}")
                elif uid not in self.ausentes:
                    self.ausentes.add(uid)
                    avisar(f"{unidad.nombre or APP_NAME}: no encuentro su contenedor",
                           f"La raíz cifrada de este equipo tenía que estar en "
                           f"{unidad.contenedor}. Si lo has movido, vuelve a ponerlo "
                           f"ahí o reinstala.", True)
                continue
            if uid not in self.ausentes:
                self.ausentes.add(uid)
                avisar(f"{unidad.nombre or APP_NAME}: no encuentro su carpeta",
                       f"La raíz de este equipo tenía que estar en {unidad.ruta}. "
                       f"Si la has movido, vuelve a ponerla ahí o reinstala.", True)

    def _conectar(self, uid: str, raiz: Path, ahora: float) -> None:
        unidad = self.ajustes.unidades.get(uid)
        nombre = nombre_de(raiz, uid, unidad.nombre if unidad else "")
        con = Conexion(uid, raiz, nombre, ahora)
        self.conexiones[uid] = con
        desbloqueo = self.desbloqueos.pop(uid, None)
        # Cada conexión empieza de cero, como el servicio que se arrancaba al
        # enchufar: se sincroniza enseguida, y el modo `sync` vuelve a tocar.
        for clave in [k for k in self.marcas if k[0] == uid]:
            del self.marcas[clave]
        if unidad is None:
            self._preguntar(con, ahora)
            return
        if unidad.nombre != nombre:
            self._guardar(self.ajustes.con_unidad(replace(unidad, nombre=nombre)))
        diario(f"{nombre}: " + ("raíz de este equipo" if unidad.es_raiz else "conectada")
               + f" en {raiz} (modo {unidad.modo})")
        if unidad.modo == equipo.UI:
            self._abrir_ventana(con)
        elif desbloqueo is not None and desbloqueo.abrir:
            self._lanzar_ventana(con)       # «Abrir» con ella bloqueada

    def _desconectar(self, uid: str, ahora: float, cerradas: dict[str, Path]) -> None:
        con = self.conexiones.pop(uid, None)
        if con is None:
            return
        if con.hijo is not None and con.hijo.poll() is None:
            try:
                con.hijo.terminate()
            except OSError:
                pass
        # No se escribe en una unidad que ya no está. Y si sigue ahí la entrada del
        # contenedor, se ha cerrado con la unidad puesta: es «Expulsar», no una
        # conexión nueva, y no se vuelve a pedir la contraseña. Se apunta como ya
        # pedida aunque no se sepa todavía (se ha notado entre dos recorridos):
        # si en el siguiente no hay entrada, `_vestibulos()` la rearma.
        self.vestibulos[uid] = str(cerradas.get(uid, ""))
        self.urgentes = [u for u in self.urgentes if u[0] != uid]
        self.entorno = replace(self.entorno, sin_conexion={
            k: v for k, v in self.entorno.sin_conexion.items() if k[0] != uid})
        self.sospechas = {k: v for k, v in self.sospechas.items() if k[0] != uid}
        self.sin_red_avisado = {k for k in self.sin_red_avisado if k[0] != uid}
        unidad = self.ajustes.unidades.get(uid)
        diario(f"{con.nombre} " + ("bloqueada: su contenedor se ha cerrado"
                                   if unidad is not None and unidad.cifrada else
                                   "ya no está en su carpeta"
                                   if unidad is not None and unidad.es_raiz
                                   else "desconectada"))

    def _vestibulos(self, cerradas: dict[str, Path], ahora: float) -> None:
        """Una unidad VeraCrypt de la lista, cerrada: se le pide a VeraCrypt que
        la abra, una vez por conexión, como penwatch. Una que no está en la
        lista, nunca: no se ejecuta nada de una unidad que no se ha aceptado."""
        for uid in list(self.vestibulos):
            if uid not in cerradas:
                if self.vestibulos.pop(uid):
                    diario("entrada de una unidad cifrada retirada; apertura rearmada")
        for uid in list(self.cerradas):
            if uid not in cerradas:
                del self.cerradas[uid]
        for uid, raiz in cerradas.items():
            if uid in self.conexiones or uid in self.vestibulos:
                continue
            unidad = self.ajustes.unidades.get(uid)
            if unidad is None or unidad.modo == equipo.NADA:
                continue
            self.cerradas[uid] = self.cerradas.get(uid, 0) + 1
            if self.cerradas[uid] < ESTABLE:
                self.rafaga_hasta = max(self.rafaga_hasta, ahora + 3 * TICK)
                continue
            del self.cerradas[uid]
            self.vestibulos[uid] = str(raiz)
            diario(f"{unidad.nombre or uid[:8]}: cifrada y cerrada en {raiz}")
            abrir_contenedor(raiz)

    # --- una unidad nueva -----------------------------------------------------------

    def _preguntar(self, con: Conexion, ahora: float) -> None:
        espera = self.ajustes.espera_unidad_nueva
        avisar(f"Se ha conectado {con.nombre}", "¿Atenderla en este equipo?")
        if not hay_pantalla():
            con.respuesta = pl.AHORA_NO
            diario(f"{con.nombre} ({con.id[:8]}) no está en la lista y no hay entorno "
                   f"gráfico donde preguntar: cuenta como «Ahora no». Para atenderla: "
                   f"agente.py atender {con.id}")
            return
        con.pregunta = pl.Pregunta(con.id, ahora, espera)
        try:
            con.hijo = lanzar([python(ventana=True), str(SCRIPT_DIR / "agente.py"),
                               "pregunta", "--nombre", con.nombre,
                               "--segundos", str(int(espera))],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              **_opciones_hijo(equipo.DIR))
        except OSError as e:
            diario(f"no he podido abrir la pregunta por {con.nombre}: {e}")
            con.hijo = None

    def _preguntas(self, ahora: float) -> None:
        for con in self.conexiones.values():
            if con.pregunta is None:
                continue
            rc = con.hijo.poll() if con.hijo is not None else 2
            respuesta = None if rc is None else (pl.ATENDER if rc == 0 else pl.AHORA_NO)
            final = pl.resolver(con.pregunta, respuesta, ahora)
            if final is None:
                continue
            if con.hijo is not None and con.hijo.poll() is None:
                try:
                    con.hijo.terminate()   # se cierra sola a cero; por si no
                except OSError:
                    pass
            con.pregunta, con.hijo = None, None
            if final == pl.ATENDER:
                self._atender(con)
            else:
                con.respuesta = pl.AHORA_NO
                diario(f"{con.nombre}: «Ahora no»; no se atiende mientras siga "
                       f"conectada. Para atenderla: agente.py atender {con.id}")

    def _atender(self, con: Conexion) -> None:
        con.respuesta = None
        self._guardar(self.ajustes.con_unidad(
            equipo.Unidad(con.id, equipo.MODO_AL_ATENDER, con.nombre)))
        diario(f"{con.nombre} añadida a la lista (modo {equipo.MODO_AL_ATENDER})")

    def _guardar(self, ajustes: equipo.Ajustes) -> None:
        self.ajustes = ajustes
        if not equipo.guardar_ajustes(ajustes):
            diario("no he podido escribir agente.json; el cambio vale hasta que "
                   "me reinicie")

    # --- el modo ui ------------------------------------------------------------------

    def _abrir_ventana(self, con: Conexion) -> None:
        """El modo `ui`: la ventana al conectarla, si no hay ya un servicio."""
        con.lanzada = True
        ocupado = penwatch.aplicacion_en_marcha(con.raiz)
        if ocupado:
            diario(f"{con.nombre}: no abro la ventana: {ocupado}")
            return
        self._lanzar_ventana(con)

    def _lanzar_ventana(self, con: Conexion) -> None:
        """La ventana de runsync de esa raíz, con el Python del agente y fuera de
        ella. Nuestro servicio no estorba: la ventana lo pausa al abrirse
        (`daemon.stop`). Otra ventana sí, y runsync ya se negaría."""
        ventana = penwatch._vivo_aqui(con.raiz, penwatch.UI_LOCK_REL)
        if ventana is not None:
            diario(f"{con.nombre}: su ventana ya está abierta (pid {ventana.get('pid')})")
            return
        if not hay_pantalla():
            diario(f"{con.nombre}: sin entorno gráfico; no hay dónde abrir "
                   f"la ventana")
            return
        try:
            lanzar([python(ventana=True), str(app(con.raiz) / "runsync.py")],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   **_opciones_hijo(equipo.DIR, separado=True))
            diario(f"{con.nombre}: ventana abierta")
        except OSError as e:
            diario(f"{con.nombre}: no he podido abrir la ventana: {e}")

    # --- el contrato del servicio ------------------------------------------------------

    def _sirve(self, con: Conexion) -> bool:
        unidad = self.ajustes.unidades.get(con.id)
        return unidad is not None and unidad.modo in (equipo.DAEMON, equipo.SYNC)

    def _cargar_servicio(self, con: Conexion) -> None:
        """Relee las parejas y el intervalo si cambió el TOML o la memoria del
        servicio: la ventana los edita mientras el agente sigue vivo."""
        firma = []
        for ruta in (app(con.raiz) / "sync_config.toml",
                     estado_de(con.raiz) / "ui_prefs.json"):
            try:
                firma.append(ruta.stat().st_mtime_ns)
            except OSError:
                firma.append(None)
        if tuple(firma) == con.firma and (con.servicio or con.error):
            return
        con.firma = tuple(firma)
        try:
            con.servicio, con.error = leer_servicio(con.raiz), None
        except ValueError as e:
            con.servicio, con.error = None, str(e)
            if not con.avisado_error:
                con.avisado_error = True
                avisar(f"{con.nombre}: nada que sincronizar", con.error)

    def _otro_servicio(self, con: Conexion) -> dict | None:
        info = store.read_json(con.raiz / penwatch.DAEMON_LOCK_REL)
        if info.get("host") != HOST:
            return None
        try:
            pid = int(info.get("pid", -1))
        except (TypeError, ValueError):
            return None
        if pid == os.getpid() or not pid_alive(pid):
            return None
        return info

    def _contrato(self, con: Conexion, ahora: float) -> None:
        ocupada = self.pasada is not None and self.pasada.tarea.raiz == con.id
        if con.id in self.bloqueos:
            # Se está bloqueando: ni se encola ni se vuelve a tomar el lock.
            if not ocupada:
                self._soltar(con)
            con.motivo = "bloqueándose"
            return
        if not self._sirve(con):
            if not ocupada:                 # el lock se suelta al acabar la pareja
                self._soltar(con)
            con.motivo = self._motivo_sin_servicio(con)
            return
        stop = estado_de(con.raiz) / "daemon.stop"
        try:
            parar = stop.exists()
        except OSError:
            parar = False
        if parar and not ocupada:
            # Lo que hace runsync al abrir su ventana (o con --auto, o con
            # cualquier orden pasada a sync.py): acabada la pareja en curso, se
            # suelta el lock y se borra el stop. Ya no se sale: se hace pausa.
            self._soltar(con)
            stop.unlink(missing_ok=True)
            con.pausa = ahora
            diario(f"{con.nombre}: runsync ha pedido parar el servicio; en pausa")
            dlog(con.raiz, "servicio (agente del equipo) en pausa: lo ha pedido runsync")
        ventana = penwatch._vivo_aqui(con.raiz, penwatch.UI_LOCK_REL) is not None
        if ventana:
            con.pausa = ahora
        otro = self._otro_servicio(con)
        if otro is not None and con.lock is not None:
            con.lock = None                 # el lock ya es de otro
        self._cargar_servicio(con)

        if con.pausa is not None and (ventana or (ahora - con.pausa < GRACIA
                                                  and not con.reanudar)):
            con.motivo = "en pausa: hay una ventana de runsync abierta"
        elif otro is not None:
            con.motivo = f"la atiende otro servicio (pid {otro.get('pid')})"
        elif con.servicio is None:
            con.motivo = f"sin servicio: {con.error}"
        else:
            con.pausa = None
            con.reanudar = False
            con.motivo = ""
            if con.lock is None:
                self._tomar(con)
            elif not self._lock_es_nuestro(con):
                con.lock = None             # lo borró runsync al cansarse de esperar
            return
        if not ocupada:
            self._soltar(con)

    def _motivo_sin_servicio(self, con: Conexion) -> str:
        if con.pregunta is not None:
            return "preguntando si atenderla"
        if con.respuesta == pl.AHORA_NO:
            return "«Ahora no» en esta conexión"
        unidad = self.ajustes.unidades.get(con.id)
        if unidad is None:
            return "sin atender"
        return f"modo {unidad.modo}: {equipo.TEXTO_MODO[unidad.modo]}"

    def _lock_es_nuestro(self, con: Conexion) -> bool:
        info = store.read_json(con.raiz / penwatch.DAEMON_LOCK_REL)
        return info.get("pid") == os.getpid() and info.get("host") == HOST

    def _tomar(self, con: Conexion) -> None:
        unidad = self.ajustes.unidades[con.id]
        datos = {"pid": os.getpid(), "host": HOST, "started": store.stamp(),
                 "pairs": [p.nombre for p in con.servicio.parejas],
                 "interval_min": con.servicio.minutos, "agente": True,
                 "modo": unidad.modo}
        if store.write_json(con.raiz / penwatch.DAEMON_LOCK_REL, datos):
            con.lock = datos
            dlog(con.raiz, f"servicio (agente del equipo, pid {os.getpid()}) atendiendo: "
                           f"{', '.join(datos['pairs'])}"
                           + ("" if unidad.modo == equipo.SYNC
                              else f" cada {con.servicio.minutos:g} min"))

    def _soltar(self, con: Conexion) -> None:
        if con.lock is None:
            return
        con.lock = None
        if self._lock_es_nuestro(con):
            (con.raiz / penwatch.DAEMON_LOCK_REL).unlink(missing_ok=True)

    # --- planificar y lanzar ------------------------------------------------------------

    def _raices(self) -> list[pl.Raiz]:
        raices = []
        for con in self.conexiones.values():
            if con.lock is None or con.servicio is None or con.id in self.bloqueos:
                continue
            modo = self.ajustes.unidades[con.id].modo
            intervalo = math.inf if modo == equipo.SYNC else con.servicio.minutos * 60
            raices.append(pl.Raiz(con.id, con.servicio.parejas, intervalo))
        return raices

    def _decidir(self, ahora: float) -> pl.Decision:
        entorno = replace(self.entorno, pausado=self.pausado)
        decision = pl.decidir(self._raices(), self.marcas, entorno, ahora,
                              self.ajustes.politica, urgentes=self.urgentes)
        if decision.retenido != self.retenido:
            diario(f"no se lanza nada: {decision.retenido}" if decision.retenido
                   else "se vuelve a sincronizar")
            self.retenido = decision.retenido
        if decision.tarea is not None:
            self._lanzar(decision.tarea, ahora)
        return decision

    def _lanzar(self, tarea: pl.Tarea, ahora: float) -> None:
        con = self.conexiones[tarea.raiz]
        if tarea.urgente:
            self.urgentes = [u for u in self.urgentes if u != (tarea.raiz, tarea.pareja)]
        if tarea.tipo == pl.SONDA:
            args = orden_sonda(con.raiz, tarea.remoto)
            if args is None:
                # Sin rclone para este equipo no hay con qué preguntar: se hace
                # como si el remoto contestara. Así el fallo que se sospechaba de
                # red cuenta como fallo de la pareja y espera lo suyo; tomarlo por
                # red otra vez la relanzaría en cada vuelta.
                self._fin_de_sonda(con, tarea.remoto, 0, "", ahora)
                return
            cwd = app(con.raiz)             # rclone.conf resuelve contra aquí
            que = f"¿contesta {tarea.remoto}?"
        else:
            args = [python(), str(app(con.raiz) / "sync.py"), tarea.pareja]
            cwd = equipo.DIR
            que = tarea.pareja
        salida = equipo.DIR / "pasada.out"
        try:
            equipo.DIR.mkdir(parents=True, exist_ok=True)
            with salida.open("wb") as f:
                proc = lanzar(args, stdout=f, stderr=subprocess.STDOUT,
                              **_opciones_hijo(cwd))
        except OSError as e:
            diario(f"[{con.nombre}] no he podido lanzar {que}: {e}")
            if tarea.tipo == pl.PASADA:
                self.marcas[(tarea.raiz, tarea.pareja)] = pl.registrar(
                    self.marcas.get((tarea.raiz, tarea.pareja), pl.Marca()), FALLO, ahora)
            return
        self.pasada = Pasada(proc, tarea, ahora, salida, con.nombre)
        diario(f"[{con.nombre}] {que}" + (" (a petición)" if tarea.urgente else ""))

    def _fin_de_pasada(self, ahora: float) -> None:
        pasada = self.pasada
        if pasada is None:
            return
        rc = pasada.proc.poll()
        if rc is None:
            return
        self.pasada = None
        texto = ""
        try:
            with pasada.salida.open("rb") as f:
                f.seek(0, os.SEEK_END)
                f.seek(max(0, f.tell() - COLA_SALIDA))
                texto = f.read().decode("utf-8", errors="replace")
        except OSError:
            pass
        pasada.salida.unlink(missing_ok=True)
        tarea = pasada.tarea
        con = self.conexiones.get(tarea.raiz)
        if con is None or not presente(con.raiz):
            # Una unidad desenchufada a mitad de pasada: no es un fallo de la
            # pareja, y no se avisa de nada.
            diario(f"[{pasada.nombre}] la unidad se ha ido a mitad de "
                   f"{tarea.pareja or 'la comprobación'}; no cuenta")
            return
        segundos = ahora - pasada.desde
        if tarea.tipo == pl.SONDA:
            self._fin_de_sonda(con, tarea.remoto, rc, texto, ahora)
            return

        clave = (tarea.raiz, tarea.pareja)
        como = resultado(rc, texto)
        antes = self.marcas.get(clave, pl.Marca())
        despues = pl.registrar(antes, como, ahora)
        self.marcas[clave] = despues
        if como == FALLO or como == RED:
            dlog(con.raiz, f"[{tarea.pareja}] FALLÓ (rc={rc}, {segundos:.0f}s); salida:")
            for linea in texto.splitlines()[-12:]:
                dlog(con.raiz, f"[{tarea.pareja}]   {linea}")
        elif como == SALTADA:
            dlog(con.raiz, f"[{tarea.pareja}] saltada: requiere --resync; ejecútalo a "
                           f"mano desde la ventana")
        else:
            dlog(con.raiz, f"[{tarea.pareja}] OK ({segundos:.0f}s)")
        diario(f"[{con.nombre}] {tarea.pareja}: {TEXTO_RESULTADO[como]} "
               f"(rc={rc}, {segundos:.0f}s)")
        self._apuntar_en_lock(con, tarea.pareja, como, rc, segundos)

        if como == RED:
            # ¿De verdad es la red? La sonda va ya: si el remoto contesta, aquel
            # fallo era de la pareja y se apunta como tal (`_fin_de_sonda`).
            self.sospechas[(tarea.raiz, tarea.remoto)] = (tarea.pareja, antes)
            self.entorno = pl.sin_conexion(self.entorno, tarea.raiz, tarea.remoto, ahora)
        elif pl.empieza_a_fallar(antes, despues):
            avisar(f"{con.nombre}: falla {tarea.pareja}", self._donde_mirar(con), True)

    def _fin_de_sonda(self, con: Conexion, remoto: str, rc: int, texto: str,
                      ahora: float) -> None:
        clave = (con.id, remoto)
        sospecha = self.sospechas.pop(clave, None)
        # Un error que no es de red —credenciales, una ruta— es un remoto que
        # contesta: no hay nada que esperar.
        if rc == 0 or not moderacion.es_de_red(texto):
            self.entorno = pl.con_conexion(self.entorno, con.id, remoto)
            if sospecha is not None:
                pareja, antes = sospecha
                despues = pl.registrar(antes, FALLO, ahora)
                self.marcas[(con.id, pareja)] = despues
                diario(f"[{con.nombre}] {remoto} contesta: el fallo de {pareja} no era "
                       f"de la red")
                if pl.empieza_a_fallar(antes, despues):
                    avisar(f"{con.nombre}: falla {pareja}", self._donde_mirar(con), True)
            elif clave in self.sin_red_avisado:
                self.sin_red_avisado.discard(clave)
                diario(f"[{con.nombre}] vuelve la conexión con {remoto}")
            return
        self.entorno = pl.sin_conexion(self.entorno, con.id, remoto,
                                       ahora + self.ajustes.politica.sondeo_sin_conexion)
        if clave not in self.sin_red_avisado:
            self.sin_red_avisado.add(clave)
            avisar(f"{con.nombre}: sin conexión con {remoto}",
                   "Sus parejas esperan a que vuelva la red; no hace falta hacer nada.")

    def _donde_mirar(self, con: Conexion) -> str:
        unidad = self.ajustes.unidades.get(con.id)
        if unidad is not None and unidad.es_raiz:
            return f"Abre la ventana de {APP_NAME} en este equipo para ver qué ha pasado."
        return f"Abre {APP_NAME} desde la unidad para ver qué ha pasado."

    def _apuntar_en_lock(self, con: Conexion, pareja: str, como: str, rc: int,
                         segundos: float) -> None:
        """Lo mismo que el servicio de runsync deja en su lock tras cada ciclo."""
        if con.lock is None or not self._lock_es_nuestro(con):
            return
        texto = {OK: f"OK ({segundos:.0f}s)", SALTADA: "saltada (requiere --resync manual)"
                 }.get(como, f"ERROR rc={rc}")
        con.lock.setdefault("last_results", {})[pareja] = texto
        con.lock["last_cycle"] = store.stamp()
        store.write_json(con.raiz / penwatch.DAEMON_LOCK_REL, con.lock)

    # --- la raíz cifrada ----------------------------------------------------------------

    def _cifrada(self, uid: str) -> equipo.Unidad | None:
        """La raíz cifrada de ese id, o la única que haya si no se dice."""
        cifradas = self.ajustes.cifradas
        if uid:
            return cifradas.get(uid)
        return next(iter(cifradas.values())) if len(cifradas) == 1 else None

    def _al_iniciar(self, ahora: float) -> None:
        """`pedir_al_iniciar`: la contraseña, UNA vez por arranque del agente.

        Se espera a haber recorrido lo bastante para saber que no está ya
        abierta (una raíz cuenta al verla `ESTABLE` veces). Si se cancela, no se
        vuelve a pedir hasta «Desbloquear»: es la misma regla de «una vez por
        conexión» que tienen las unidades cifradas."""
        if self.recorridos < ESTABLE:
            return
        for uid, unidad in self.ajustes.cifradas.items():
            if uid in self.pedidas:
                continue
            self.pedidas.add(uid)
            if (self.ajustes.pedir_al_iniciar and unidad.modo != equipo.NADA
                    and uid not in self.conexiones and uid not in self.vistas):
                self._desbloquear(unidad, ahora, "al iniciar sesión")

    def _desbloquear(self, unidad: equipo.Unidad, ahora: float, por: str = "",
                     abrir: bool = False) -> bool:
        """Le pide a VeraCrypt que abra la raíz cifrada. No espera: abierta es
        cuando el recorrido VE su id con el `.hc` retenido. Con `abrir`, su
        ventana se abre en cuanto se vea abierta (el «Abrir» de la bandeja)."""
        nombre = unidad.nombre or APP_NAME
        if unidad.id in self.conexiones or unidad.id in self.vistas:
            diario(f"{nombre}: ya está abierta")
            return False
        if unidad.id in self.bloqueos:
            diario(f"{nombre}: se está bloqueando; desbloquear después")
            return False
        if unidad.id in self.desbloqueos:
            # VeraCrypt ya está pidiendo la contraseña: una segunda ventana
            # suya no ayuda.
            self.desbloqueos[unidad.id].abrir |= abrir
            diario(f"{nombre}: ya se está desbloqueando")
            return False
        try:
            hay = Path(unidad.contenedor).is_file()
        except OSError:
            hay = False
        if not hay:
            avisar(f"{nombre}: no encuentro su contenedor",
                   f"Tenía que estar en {unidad.contenedor}.", True)
            return False
        ocupado = punto_ocupado(unidad)
        if ocupado:
            avisar(f"{nombre}: no la desbloqueo", ocupado, True)
            return False
        cmd = penwatch.veracrypt_command(None, Path(unidad.contenedor),
                                         unidad.letra or unidad.ruta)
        if cmd is None:
            avisar(f"{nombre}: no la puedo desbloquear",
                   "No hay VeraCrypt instalado en este equipo" if IS_WIN or
                   penwatch.installed_veracrypt() is None else
                   "No hay escritorio donde VeraCrypt pida la contraseña", True)
            return False
        if not unidad.letra:
            try:
                Path(unidad.ruta).mkdir(parents=True, exist_ok=True)
            except OSError:
                pass                # que lo diga VeraCrypt
        try:
            proc = lanzar(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                          **_opciones_hijo(equipo.DIR, separado=True))
        except OSError as e:
            avisar(f"{nombre}: no he podido lanzar VeraCrypt", str(e), True)
            return False
        self.desbloqueos[unidad.id] = Desbloqueo(ahora, proc, abrir=abrir)
        diario(f"{nombre}: desbloqueando" + (f" ({por})" if por else "")
               + f" en {unidad.ruta}; la contraseña la pide VeraCrypt")
        return True

    def _seguir_desbloqueos(self, ahora: float) -> None:
        """Un «Desbloquear» que no acaba en la raíz abierta se ha cancelado (o
        la contraseña no era): VeraCrypt ha salido y, pasado un rato, no se ve.
        Se olvida, para que la bandeja vuelva a ofrecerlo. Con un VeraCrypt que
        no sale (el de escritorio de Linux se queda abierto), al acabarse
        `ESPERA_ABRIR`."""
        for uid, d in list(self.desbloqueos.items()):
            if uid in self.conexiones or uid in self.vistas:
                continue
            if d.salio is None and (d.proc is None or d.proc.poll() is not None):
                d.salio = ahora
            if ((d.salio is not None and ahora - d.salio >= GRACIA_ABRIR)
                    or ahora - d.desde >= ESPERA_ABRIR):
                del self.desbloqueos[uid]
                unidad = self.ajustes.unidades.get(uid)
                diario(f"{(unidad.nombre if unidad else '') or uid[:8]}: no se ha "
                       f"desbloqueado (¿contraseña cancelada?); sigue bloqueada")

    def _bloqueos(self, ahora: float) -> None:
        """Los «Bloquear» pedidos: primero se espera a que nada lo impida, luego
        VeraCrypt desmonta y se espera a verlo cerrado de verdad."""
        for uid, b in list(self.bloqueos.items()):
            unidad = self.ajustes.unidades.get(uid)
            if unidad is None or not unidad.cifrada:
                del self.bloqueos[uid]
                continue
            nombre = unidad.nombre or APP_NAME
            con = self.conexiones.get(uid)
            if b.proc is None:
                if con is None and uid not in self.fantasmas:
                    del self.bloqueos[uid]
                    diario(f"{nombre}: ya estaba bloqueada")
                    continue
                if self.pasada is not None and self.pasada.tarea.raiz == uid:
                    continue                # acaba la pareja en curso
                if con is not None and penwatch._vivo_aqui(
                        con.raiz, penwatch.UI_LOCK_REL) is not None:
                    # Su ventana pide bloquear y se cierra; se le da un rato.
                    if ahora - b.desde >= ESPERA_VENTANA:
                        del self.bloqueos[uid]
                        avisar(f"{nombre}: no la bloqueo",
                               "Su ventana sigue abierta. Ciérrala y vuelve a pedirlo.",
                               True)
                    continue
                cmd = orden_bloquear(unidad)
                if cmd is None:
                    del self.bloqueos[uid]
                    avisar(f"{nombre}: no la puedo bloquear",
                           "No hay VeraCrypt instalado en este equipo.", True)
                    continue
                if con is not None:
                    self._soltar(con)
                try:
                    b.proc = lanzar(cmd, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL,
                                    **_opciones_hijo(equipo.DIR, separado=True))
                except OSError as e:
                    del self.bloqueos[uid]
                    avisar(f"{nombre}: no he podido lanzar VeraCrypt", str(e), True)
                    continue
                b.lanzado = ahora
                diario(f"{nombre}: bloqueando; si algo tiene un fichero abierto "
                       f"dentro, VeraCrypt pregunta si forzar")
                continue
            if bloqueada(unidad):
                del self.bloqueos[uid]
                self.desbloqueos.pop(uid, None)
                self.fantasmas.discard(uid)
                if con is not None:
                    self._desconectar(uid, ahora, {})
                diario(f"{nombre}: bloqueada")
                continue
            salio = b.proc.poll() is not None
            if (salio and ahora - b.lanzado >= GRACIA_DESMONTAJE) \
                    or ahora - b.lanzado >= ESPERA_DESMONTAJE:
                del self.bloqueos[uid]
                avisar(f"{nombre}: sigue abierta",
                       "VeraCrypt no la ha cerrado: si un programa tiene un fichero "
                       "abierto dentro, ciérralo y vuelve a bloquear.", True)

    # --- el entorno ------------------------------------------------------------------

    def _leer_entorno(self, ahora: float) -> None:
        if ahora - self.entorno_leido < MIRAR_ENTORNO:
            return
        self.entorno_leido = ahora
        energia = moderacion.energia()
        self.entorno = replace(self.entorno, con_bateria=energia.con_bateria,
                               bateria=energia.porcentaje,
                               red_medida=moderacion.red_medida())

    # --- la versión nueva ---------------------------------------------------------------

    def _mirar_version(self, ahora: float) -> None:
        """¿Hay una versión más nueva que la de este agente? En un hilo, porque
        es la red, y de tarde en tarde. Cuando la hay se dice una vez, y la
        bandeja ofrece «Actualizar» (sección 8 del diseño)."""
        if self.actualizando is not None and self.actualizando.poll() is not None:
            # Si el agente sigue siendo este, la actualización no ha llegado a
            # sustituirlo: lo cuenta su diario, y se puede volver a pedir.
            self.actualizando = None
        if self.nueva and self.nueva != self.nueva_avisada:
            self.nueva_avisada = self.nueva
            avisar(f"Hay una versión nueva de {APP_NAME}: {self.nueva}",
                   f"Tienes la {self.version or 'desconocida'}. "
                   + ("Actualízala desde su icono de la bandeja." if self.bandeja
                      else "Para ponerla: python agente.py actualizar"))
        if ahora - self.version_mirada < MIRAR_VERSION:
            return
        self.version_mirada = ahora

        def trabajo() -> None:
            try:
                rel = buscar_version()
            except Exception as e:                  # noqa: BLE001
                diario(f"no he podido mirar si hay versión nueva: {e}")
                return
            self.nueva = rel.tag if rel is not None else None

        hilo(trabajo)

    def _actualizar(self) -> None:
        """«Actualizar»: un hijo suelto (`agente.py actualizar`) que baja la
        versión nueva y la pone con su propio instalador, que para a este
        agente y arranca el nuevo. Aquí no se espera nada: la red y la copia
        no pueden tener parada la cola."""
        if self.actualizando is not None and self.actualizando.poll() is None:
            diario("ya se está actualizando")
            return
        try:
            self.actualizando = lanzar([python(), str(SCRIPT_DIR / "agente.py"),
                                        "actualizar"],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       **_opciones_hijo(equipo.DIR, separado=True))
        except OSError as e:
            avisar(f"{APP_NAME}: no he podido actualizar", str(e), True)
            return
        diario(f"actualizando a la {self.nueva or 'última versión'}; lo que pase, "
               f"aquí mismo")

    # --- el buzón ---------------------------------------------------------------------

    def pedir(self, peticion: dict) -> None:
        """Una petición de la bandeja (otro hilo): se atiende en la próxima
        vuelta, en el hilo del agente, igual que una del buzón."""
        self.peticiones.put(dict(peticion))

    def _buzon(self, ahora: float) -> None:
        pendientes = equipo.recoger()
        while True:
            try:
                pendientes.append(self.peticiones.get_nowait())
            except queue.Empty:
                break
        for p in pendientes:
            try:
                self._atender_peticion(p, ahora)
            except Exception as e:                      # noqa: BLE001
                diario(f"petición ilegible {p!r}: {e}")

    def _buzones_de_raices(self, ahora: float) -> None:
        """El buzón de cada raíz conectada y en la lista (`state/servicio.pide`):
        lo que su ventana le pide a su servicio. Lo que llega por ahí es de ESA
        raíz, sea cual sea el id que traiga, y solo lo que es de una raíz
        (`equipo.PIDE_SERVICIO`). El de una unidad que no está en la lista ni se
        mira: de ella solo se lee su id y su nombre."""
        for con in list(self.conexiones.values()):
            if con.id not in self.ajustes.unidades:
                continue
            for p in equipo.recoger(estado_de(con.raiz) / equipo.BUZON_SERVICIO):
                if p.get("pide") not in equipo.PIDE_SERVICIO:
                    diario(f"{con.nombre}: su buzón pide {p.get('pide')!r}, que no es "
                           f"cosa de una raíz; ignorado")
                    continue
                try:
                    self._atender_peticion({**p, "id": con.id}, ahora)
                except Exception as e:                  # noqa: BLE001
                    diario(f"petición ilegible {p!r}: {e}")

    def _atender_peticion(self, p: dict, ahora: float) -> None:
        que = p.get("pide")
        uid = p.get("id") if isinstance(p.get("id"), str) else ""
        if que == equipo.PIDE_REANUDAR:
            # «Iniciar servicio» en la ventana de esa raíz: ya no arranca un
            # servicio suyo, le dice al agente que vuelva en cuanto se cierre.
            # Como el servicio que se arrancaba, empieza con una pasada: las
            # parejas o el intervalo acaban de elegirse.
            con = self.conexiones.get(uid)
            if con is None:
                diario(f"reanudar {uid[:8]}: no está conectada")
                return
            con.reanudar = True
            for clave in [k for k in self.marcas if k[0] == uid]:
                del self.marcas[clave]
            diario(f"{con.nombre}: su ventana pide volver a sincronizarla")
        elif que == equipo.PIDE_ATENDER:
            con = self.conexiones.get(uid)
            if con is None:
                diario(f"atender {uid[:8]}: no está conectada; se atiende enchufada")
            elif uid in self.ajustes.unidades:
                diario(f"atender {con.nombre}: ya estaba en la lista")
            else:
                if con.hijo is not None and con.hijo.poll() is None:
                    con.hijo.terminate()
                con.pregunta, con.hijo = None, None
                self._atender(con)
        elif que == equipo.PIDE_MODO:
            # Una que no está en la lista entra con ese modo: es como el
            # asistente, vuelto a pasar con el agente ya instalado, añade las
            # unidades que se eligen en su paso «Unidades».
            modo = p.get("modo")
            if not uid.strip() or modo not in equipo.MODOS:
                diario(f"modo {modo!r} para {uid[:8]!r}: no es un id o no es un modo")
                return
            nombre = p.get("nombre") if isinstance(p.get("nombre"), str) else ""
            unidad = self.ajustes.unidades.get(uid) or equipo.Unidad(uid, modo, nombre)
            self._guardar(self.ajustes.con_unidad(
                replace(unidad, modo=modo, nombre=unidad.nombre or nombre)))
            diario(f"{unidad.nombre or nombre or uid[:8]}: modo {modo}")
        elif que == equipo.PIDE_RAIZ:
            # Lo que pide el asistente vuelto a pasar con el agente instalado:
            # la raíz que acaba de poner en este equipo.
            ruta = p.get("ruta") if isinstance(p.get("ruta"), str) else ""
            if not uid.strip() or not ruta.strip():
                diario(f"añadir raíz {uid[:8]!r} en {ruta!r}: falta el id o la ruta")
                return
            nombre = p.get("nombre") if isinstance(p.get("nombre"), str) else ""
            modo = p.get("modo") if p.get("modo") in equipo.MODOS else equipo.DAEMON
            hc = p.get("contenedor") if isinstance(p.get("contenedor"), str) else ""
            self._guardar(self.ajustes.con_unidad(
                equipo.Unidad(uid, modo, nombre, ruta.strip(), hc.strip())))
            self.ausentes.discard(uid)
            self.pedidas.add(uid)           # la acaba de dejar abierta el asistente
            diario(f"raíz de este equipo añadida: {nombre or uid[:8]} en {ruta}"
                   + (f" (cifrada, contenedor {hc})" if hc else ""))
        elif que in (equipo.PIDE_DESBLOQUEAR, equipo.PIDE_BLOQUEAR):
            unidad = self._cifrada(uid)
            if unidad is None:
                diario(f"{que} {uid[:8]!r}: no hay esa raíz cifrada en este equipo")
            elif que == equipo.PIDE_DESBLOQUEAR:
                self._desbloquear(unidad, ahora, "pedido")
            elif unidad.id not in self.bloqueos:
                self.bloqueos[unidad.id] = Bloqueo(ahora)
                self.urgentes = [u for u in self.urgentes if u[0] != unidad.id]
        elif que == equipo.PIDE_ABRIR:
            self._abrir(uid, ahora)
        elif que == equipo.PIDE_DESPERTAR:
            # Vuelta de la suspensión: la batería y la red pueden ser otras, y
            # un remoto «sin conexión» quizá ya contesta. Se mira todo ya.
            self.entorno_leido = -math.inf
            self.entorno = replace(self.entorno, sin_conexion={
                k: min(v, ahora) for k, v in self.entorno.sin_conexion.items()})
            self.rafaga_hasta = max(self.rafaga_hasta, ahora + RAFAGA)
            diario("el equipo vuelve de la suspensión")
        elif que == equipo.PIDE_AJUSTE:
            clave, valor = p.get("clave"), p.get("valor")
            if clave not in equipo.AJUSTES_PEDIBLES:
                diario(f"ajuste desconocido: {clave!r}")
                return
            crudo = equipo.a_dict(self.ajustes)
            crudo[clave] = valor
            self._guardar(equipo.desde_dict(crudo))
            diario(f"ajuste {clave} = {getattr(self.ajustes, clave)}")
        elif que == equipo.PIDE_PASADA:
            con = self.conexiones.get(uid)
            if con is None or con.servicio is None:
                diario(f"pasada de {uid[:8]}: no está conectada o no tiene servicio")
                return
            pedidas = p.get("parejas") if isinstance(p.get("parejas"), list) else []
            nombres = [x.nombre for x in con.servicio.parejas
                       if not pedidas or x.nombre in pedidas]
            self.urgentes += [(uid, n) for n in nombres if (uid, n) not in self.urgentes]
        elif que == equipo.PIDE_ACTUALIZAR:
            self._actualizar()
        elif que == equipo.PIDE_PAUSA:
            self.pausado = True
        elif que == equipo.PIDE_SIGUE:
            self.pausado = False
        elif que == equipo.PIDE_PARAR:
            cuando = p.get("cuando")
            if isinstance(cuando, (int, float)) and cuando < self.inicio:
                # Se lo pidieron al agente anterior, que se fue sin leerlo (el
                # instalador lo terminó a la fuerza): no va con este.
                diario("un «parar» de antes de arrancar: no es para este agente")
                return
            self.terminar = True
            diario("parada pedida: termina en cuanto acabe lo que esté en marcha")

    def _abrir(self, uid: str, ahora: float) -> None:
        """«Abrir» de la bandeja: la ventana de una raíz. Una unidad que no está
        en la lista no: sería ejecutar su código sin el sí. Una raíz cifrada
        bloqueada se desbloquea antes, y su ventana sale al verla abierta."""
        unidad = self.ajustes.unidades.get(uid)
        con = self.conexiones.get(uid)
        if unidad is None:
            diario(f"abrir {uid[:8]!r}: no está en la lista; no se ejecuta nada suyo")
        elif con is not None:
            self._lanzar_ventana(con)
        elif unidad.cifrada and uid not in self.ausentes:
            self._desbloquear(unidad, ahora, "para abrirla", abrir=True)
        else:
            diario(f"abrir {unidad.nombre or uid[:8]}: no está aquí ahora")

    # --- estado ----------------------------------------------------------------------

    def _estado_raiz(self, uid: str, unidad: equipo.Unidad) -> str:
        """En qué está una raíz de este equipo, para la bandeja."""
        if uid in self.ausentes:
            return bandeja.AUSENTE
        if uid in self.fantasmas:
            return bandeja.FANTASMA
        if uid in self.bloqueos:
            return bandeja.BLOQUEANDO
        if uid in self.conexiones:
            return bandeja.ABIERTA
        if uid in self.desbloqueos:
            return bandeja.DESBLOQUEANDO
        return bandeja.BLOQUEADA if unidad.cifrada else bandeja.BUSCANDO


    def resumen(self) -> dict:
        unidades = []
        for con in self.conexiones.values():
            unidad = self.ajustes.unidades.get(con.id)
            unidades.append({"id": con.id, "nombre": con.nombre, "raiz": str(con.raiz),
                             "del_equipo": bool(unidad and unidad.es_raiz),
                             "cifrada": bool(unidad and unidad.cifrada),
                             "modo": unidad.modo if unidad else None,
                             "atendida": con.lock is not None,
                             "motivo": con.motivo,
                             "en_lista": unidad is not None,
                             "ahora_no": con.respuesta == pl.AHORA_NO,
                             "preguntando": con.pregunta is not None,
                             "error": con.error,
                             "fallando": sorted(p for (r, p), m in self.marcas.items()
                                                if r == con.id and m.fallos > 0)})
        cerradas = [u.nombre or u.id[:8] for u in self.ajustes.cifradas.values()
                    if u.id not in self.conexiones and u.id not in self.ausentes]
        return {"pid": os.getpid(), "pausado": self.pausado, "retenido": self.retenido,
                "pasada": None if self.pasada is None else {
                    "unidad": self.pasada.nombre, "pareja": self.pasada.tarea.pareja,
                    "tipo": self.pasada.tarea.tipo},
                "sin_conexion": sorted(f"{self.conexiones[r].nombre}: {m}"
                                       for r, m in self.entorno.sin_conexion
                                       if r in self.conexiones),
                "unidades": unidades,
                "ausentes": sorted((self.ajustes.unidades[u].contenedor
                                    or self.ajustes.unidades[u].ruta)
                                   for u in self.ausentes if u in self.ajustes.unidades),
                "bloqueadas": sorted(cerradas),
                "desbloqueando": sorted(self.ajustes.unidades[u].nombre or u[:8]
                                        for u in self.desbloqueos
                                        if u in self.ajustes.unidades),
                "bloqueando": sorted(self.ajustes.unidades[u].nombre or u[:8]
                                     for u in self.bloqueos if u in self.ajustes.unidades),
                "fantasmas": sorted(self.ajustes.unidades[u].ruta for u in self.fantasmas
                                    if u in self.ajustes.unidades),
                # Las raíces de este equipo, con su estado: lo que pinta la bandeja.
                "equipo": [{"id": uid, "nombre": u.nombre or APP_NAME, "ruta": u.ruta,
                            "cifrada": u.cifrada, "estado": self._estado_raiz(uid, u)}
                           for uid, u in self.ajustes.raices.items()],
                "pedir_al_iniciar": self.ajustes.pedir_al_iniciar,
                "version": self.version, "nueva": self.nueva,
                "actualizando": self.actualizando is not None
                and self.actualizando.poll() is None}

    def _escribir_estado(self) -> None:
        resumen = self.resumen()
        if resumen != self.ultimo_estado:
            self.ultimo_estado = resumen
            store.write_json(equipo.estado_json(), {**resumen, "actualizado": store.stamp()})
            if self.bandeja is not None:
                try:
                    self.bandeja.poner(bandeja.vista(resumen))
                except Exception as e:                  # noqa: BLE001
                    diario(f"la bandeja no se ha podido poner al día: {e}")

    def cerrar(self) -> None:
        """Al terminar: se sueltan los locks que sean nuestros. Una pasada en
        marcha sigue sola hasta acabar; nadie la mata desde aquí."""
        for con in self.conexiones.values():
            if presente(con.raiz):
                self._soltar(con)
        store.write_json(equipo.estado_json(), {"pid": None, "actualizado": store.stamp()})


# ---------------------------------------------------------------------------
# Despertarse cuando cambian los montajes
# ---------------------------------------------------------------------------

MOUNTINFO = Path("/proc/self/mountinfo")


class Vigia:
    """Espera el tic, o menos si cambian los montajes o alguien lo despierta.

    En Linux, `/proc/self/mountinfo` avisa con `POLLPRI` (y `POLLERR`) cuando
    cambia la tabla de montajes; hay que releerlo entero para rearmar el aviso.
    En Windows los montajes los dice la bandeja (`WM_DEVICECHANGE`), desde su
    hilo, con `despertar(montajes=True)`; y lo que se elige en su menú,
    con `despertar()`, para no esperar al tic. En Linux ese despertar va por
    un pipe que se vigila junto a mountinfo."""

    def __init__(self) -> None:
        self._f = None
        self._poll = None
        self._evento = threading.Event()
        self._montajes = False
        self._pipe: tuple[int, int] | None = None
        if IS_WIN:
            return
        try:
            import select
            self._poll = select.poll()
            self._pipe = os.pipe()
            os.set_blocking(self._pipe[1], False)
            self._poll.register(self._pipe[0], select.POLLIN)
            self._f = MOUNTINFO.open("rb")
            self._f.read()
            self._poll.register(self._f.fileno(), select.POLLPRI | select.POLLERR)
        except (OSError, AttributeError, ImportError):
            if self._f is not None:
                self._f.close()
            self._f = None
            if self._pipe is None:
                self._poll = None

    def despertar(self, montajes: bool = False) -> None:
        """Que la espera acabe ya. Se puede llamar desde cualquier hilo."""
        if montajes:
            self._montajes = True
        self._evento.set()
        if self._pipe is not None:
            try:
                os.write(self._pipe[1], b"!")
            except OSError:
                pass                # lleno: ya hay un despertar pendiente

    def _tomar_montajes(self) -> bool:
        montajes, self._montajes = self._montajes, False
        self._evento.clear()
        return montajes

    def esperar(self, segundos: float) -> bool:
        """True si han cambiado los montajes (hay que recorrer en racha)."""
        if self._poll is None:
            self._evento.wait(segundos)
            return self._tomar_montajes()
        montajes = False
        try:
            for fd, _ in self._poll.poll(int(segundos * 1000)):
                if self._pipe is not None and fd == self._pipe[0]:
                    os.read(fd, 4096)
                elif self._f is not None:
                    self._f.seek(0)
                    self._f.read()
                    montajes = True
        except OSError:
            time.sleep(segundos)
        return self._tomar_montajes() or montajes


# ---------------------------------------------------------------------------
# Órdenes
# ---------------------------------------------------------------------------

def poner_bandeja(agente: Agente, vigia: Vigia) -> Any:
    """La bandeja del agente, o None si en este sistema no la hay todavía o no
    se ha podido poner. Punto de indirección: los tests no ponen ninguna.

    Windows (fase 4). En Linux la bandeja es la fase 6: mientras tanto, el menú
    del sistema, la línea de órdenes y los avisos."""
    if not IS_WIN:
        return None
    from ui import bandeja_windows, icons
    try:
        icons.write_bandeja(SCRIPT_DIR, solo_si_faltan=True)
    except Exception as e:                              # noqa: BLE001
        diario(f"no he podido pintar los iconos de la bandeja: {e}")

    def pedir(peticion: dict) -> None:
        agente.pedir(peticion)
        vigia.despertar()

    b = bandeja_windows.Bandeja(SCRIPT_DIR, pedir, lambda: vigia.despertar(montajes=True))
    if not b.arrancar():
        diario("no he podido poner la bandeja: sigo sin ella")
        return None
    return b


def _enganchar_penwatch() -> None:
    """Lo que penwatch escribe en su diario va al del agente: el agente lo
    sustituye en este equipo y su carpeta ya no existe."""
    penwatch.HOST_DIR = equipo.DIR
    penwatch.LOG_FILE = equipo.diario_log()


def _terminar_con_finally(*_args) -> None:
    """SIGTERM (cerrar sesión, `systemctl stop`, `timeout`) como salida normal:
    sin esto Python muere sin pasar por los `finally` y el lock de la unidad
    se queda escrito con un pid muerto."""
    raise SystemExit(0)


def cmd_run(_args: argparse.Namespace) -> int:
    _enganchar_penwatch()
    if not IS_WIN:
        import signal
        signal.signal(signal.SIGTERM, _terminar_con_finally)
        signal.signal(signal.SIGHUP, _terminar_con_finally)
    try:
        equipo.DIR.mkdir(parents=True, exist_ok=True)
        os.chdir(equipo.DIR)            # nunca dentro de una unidad
    except OSError as e:
        print(f"No puedo usar {equipo.DIR}: {e}", file=sys.stderr)
        return 1
    vivo = equipo.agente_vivo()
    if vivo is not None and vivo.get("pid") != os.getpid():
        print(f"Ya hay un agente en marcha (pid {vivo.get('pid')}).")
        return 0
    store.write_json(equipo.lock_json(), {"pid": os.getpid(), "host": HOST,
                                          "started": store.stamp(),
                                          "codigo": str(SCRIPT_DIR)})
    icono = SCRIPT_DIR / "runsync.ico"
    if icono.is_file():
        avisos.ICONO = icono
    agente = Agente()
    diario(f"agente iniciado (pid {os.getpid()}, {len(agente.ajustes.unidades)} "
           f"unidades en la lista)")
    vigia = Vigia()
    agente.bandeja = poner_bandeja(agente, vigia)
    # Sin quien avise de los montajes (Windows sin bandeja), se recorre como
    # penwatch; con él, el recorrido de respaldo y las rachas tras cada aviso.
    cada = RECORRIDO_WINDOWS if IS_WIN and agente.bandeja is None else RECORRIDO_RESPALDO
    proximo = -math.inf
    try:
        while not (agente.terminar and agente.pasada is None):
            ahora = time.time()
            recorrer = ahora >= proximo or ahora < agente.rafaga_hasta
            if recorrer:
                proximo = ahora + cada
            try:
                agente.vuelta(recorrer)
            except Exception as e:                      # noqa: BLE001
                # Un fallo de una vuelta no puede tumbar al agente de todas las
                # unidades: se apunta y se sigue en la siguiente.
                diario(f"error en una vuelta: {type(e).__name__}: {e}")
            if vigia.esperar(TICK):
                agente.rafaga_hasta = time.time() + RAFAGA
    except KeyboardInterrupt:
        diario("interrumpido por teclado")
    finally:
        agente.cerrar()
        if agente.bandeja is not None:
            agente.bandeja.cerrar()
        info = store.read_json(equipo.lock_json())
        if info.get("pid") == os.getpid() and info.get("host") == HOST:
            equipo.lock_json().unlink(missing_ok=True)
        diario("agente detenido")
    return 0


def cmd_status(_args: argparse.Namespace) -> int:
    aj = equipo.leer_ajustes()
    vivo = equipo.agente_vivo()
    print(f"Agente:         {'vivo (pid ' + str(vivo.get('pid')) + ')' if vivo else 'parado'}")
    print(f"En el equipo:   {equipo.DIR}")
    nueva = update.pending(SCRIPT_DIR, cache=cache_version())
    print(f"Versión:        {update.installed_version(SCRIPT_DIR) or 'desconocida'}"
          + (f" (hay una nueva, {nueva.tag}: agente.py actualizar)" if nueva else ""))
    print(f"Unidad nueva:   se pregunta y se espera {aj.espera_unidad_nueva:g} s")
    for u in aj.raices.values():
        print(f"Raíz del equipo: {u.nombre or '(sin nombre)'} en {u.ruta} ({u.modo}: "
              f"{equipo.TEXTO_MODO[u.modo]})")
        if u.cifrada:
            print(f"  cifrada: {u.contenedor}; al iniciar sesión "
                  + ("se pide la contraseña" if aj.pedir_al_iniciar
                     else "no se pide nada (agente.py desbloquear)"))
    unidades = [u for u in aj.unidades.values() if not u.es_raiz]
    print("Unidades en la lista:" if unidades else "Unidades en la lista: ninguna")
    for u in unidades:
        print(f"  {u.nombre or '(sin nombre)':<20} {u.id[:12]}…  {u.modo}: "
              f"{equipo.TEXTO_MODO[u.modo]}")
    estado = equipo.leer_estado() if vivo else {}
    if estado.get("retenido"):
        print(f"No se lanza nada: {estado['retenido']}")
    if estado.get("pausado"):
        print("En pausa (agente.py sigue para volver).")
    if estado.get("pasada"):
        p = estado["pasada"]
        print(f"Ahora: {p.get('unidad')} · {p.get('pareja') or 'comprobando la conexión'}")
    for u in estado.get("unidades") or []:
        print(f"{'Raíz' if u.get('del_equipo') else 'Conectada'}: {u.get('nombre')} "
              f"en {u.get('raiz')}"
              + (f" — {u['motivo']}" if u.get("motivo") else " — atendida"))
    for ruta in estado.get("ausentes") or []:
        print(f"Falta la raíz del equipo: no está en {ruta}")
    for nombre in estado.get("bloqueadas") or []:
        print(f"Bloqueada: {nombre} (agente.py desbloquear)")
    for nombre in estado.get("desbloqueando") or []:
        print(f"Desbloqueando: {nombre}; la contraseña la pide VeraCrypt")
    for nombre in estado.get("bloqueando") or []:
        print(f"Bloqueando: {nombre}")
    for ruta in estado.get("fantasmas") or []:
        print(f"Volumen fantasma en {ruta}: bloquéala y vuelve a desbloquearla")
    for linea in estado.get("sin_conexion") or []:
        print(f"Sin conexión: {linea}")
    return 0


def _pedir(peticion: dict) -> int:
    if not equipo.pedir(peticion):
        print(f"No he podido dejar la petición en {equipo.buzon()}.", file=sys.stderr)
        return 1
    if equipo.agente_vivo() is None:
        print("Petición apuntada, pero el agente no está en marcha: la atenderá al "
              "arrancar.")
    else:
        print("Petición apuntada; el agente la atiende en unos segundos.")
    return 0


def cmd_parar(_args: argparse.Namespace) -> int:
    vivo = equipo.agente_vivo()
    if vivo is None:
        print("El agente no está en marcha.")
        return 0
    equipo.pedir({"pide": equipo.PIDE_PARAR})
    limite = time.monotonic() + PARAR_ESPERA
    while time.monotonic() < limite and equipo.agente_vivo() is not None:
        time.sleep(0.3)
    print("Agente detenido." if equipo.agente_vivo() is None else
          "El agente sigue terminando una pasada; parará al acabarla.")
    return 0


def raiz_para_abrir(uid: str | None) -> tuple[Path | None, str]:
    """Qué raíz abre `agente.py abrir`: la de ese id (del equipo, o una unidad
    conectada según el estado del agente), o la única raíz del equipo. (raíz,
    por qué no) — la frase va vacía cuando hay raíz."""
    aj = equipo.leer_ajustes()
    if uid:
        unidad = aj.unidades.get(uid)
        if unidad is not None and unidad.es_raiz:
            return Path(unidad.ruta), ""
        for u in equipo.leer_estado().get("unidades") or []:
            if u.get("id") == uid and u.get("raiz"):
                return Path(u["raiz"]), ""
        return None, f"No conozco ninguna raíz conectada con el id {uid}."
    raices = list(aj.raices.values())
    if not raices:
        return None, ("Este equipo no tiene raíz propia: las unidades se abren desde "
                      "ellas.")
    if len(raices) > 1:
        return None, ("Hay más de una raíz en este equipo; di cuál: "
                      + ", ".join(f"{u.id} ({u.ruta})" for u in raices))
    return Path(raices[0].ruta), ""


def cmd_abrir(args: argparse.Namespace) -> int:
    """La ventana de runsync de la raíz, con el Python del agente y el directorio
    de trabajo fuera de ella: la raíz del equipo no lleva Python propio. Es lo
    que lanza el acceso «prdrive» del menú del sistema."""
    raiz, porque = raiz_para_abrir(args.id)
    if raiz is None:
        print(porque, file=sys.stderr)
        return 1
    if not presente(raiz):
        unidad = equipo.leer_ajustes().unidades.get(args.id or "") \
            or next((u for u in equipo.leer_ajustes().raices.values()
                     if Path(u.ruta) == raiz), None)
        if unidad is None or not unidad.cifrada:
            print(f"No encuentro {APP_NAME} en {raiz}.", file=sys.stderr)
            return 1
        # Cerrada: se le pide al agente que la desbloquee (la contraseña la
        # pide VeraCrypt) y se abre la ventana en cuanto aparezca. Es lo que
        # hace el acceso «prdrive» del menú con la raíz bloqueada.
        if equipo.agente_vivo() is None:
            print(f"{raiz} está bloqueada y el agente no está en marcha: no hay quien "
                  f"la desbloquee.", file=sys.stderr)
            return 1
        equipo.pedir({"pide": equipo.PIDE_DESBLOQUEAR, "id": unidad.id})
        print(f"{raiz} está bloqueada: VeraCrypt pedirá la contraseña.")
        limite = time.monotonic() + ESPERA_ABRIR
        while not presente(raiz):
            if time.monotonic() >= limite:
                print("No se ha desbloqueado a tiempo; vuelve a intentarlo.",
                      file=sys.stderr)
                return 1
            time.sleep(1.0)
    # El servicio no estorba (lo pausa la propia ventana al abrirse); otra
    # ventana sí, y runsync ya se negaría: se dice aquí, sin lanzar nada.
    ventana = penwatch._vivo_aqui(raiz, penwatch.UI_LOCK_REL)
    if ventana is not None:
        print(f"La ventana de {raiz} ya está abierta (pid {ventana.get('pid')}).")
        return 0
    try:
        lanzar([python(ventana=True), str(app(raiz) / "runsync.py")],
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
               **_opciones_hijo(equipo.DIR, separado=True))
    except OSError as e:
        print(f"No he podido abrir la ventana: {e}", file=sys.stderr)
        return 1
    return 0


VERDAD = {"si": True, "sí": True, "s": True, "true": True, "1": True, "yes": True,
          "no": False, "n": False, "false": False, "0": False}


def valor_ajuste(clave: str, texto: str) -> Any:
    """El valor de un ajuste escrito en la línea de órdenes, con su tipo. Un
    texto donde va un sí o un no volvería al valor de fábrica al leerlo, sin
    decir nada: por eso se rechaza aquí (ValueError)."""
    if clave == "pedir_al_iniciar":
        valor = VERDAD.get(texto.strip().lower())
        if valor is None:
            raise ValueError(f"{clave} es sí o no, no {texto!r}")
        return valor
    return float(texto)


def cmd_ajuste(args: argparse.Namespace) -> int:
    try:
        valor = valor_ajuste(args.clave, args.valor)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    return _pedir({"pide": equipo.PIDE_AJUSTE, "clave": args.clave, "valor": valor})


def cmd_actualizar(_args: argparse.Namespace) -> int:
    """«Actualizar» de la bandeja (o a mano): baja el código de la última
    release, lo comprueba (`update.download()`) y ejecuta SU instalador con
    `--update-agente`, que pone el agente nuevo al lado, para a este, vuelve a
    registrarlo, pone al día las raíces abiertas y arranca el nuevo. Lo que
    dice va al diario del agente. Nunca se descarga dentro de ninguna raíz."""
    _enganchar_penwatch()

    def decir(msg: str) -> None:
        print(msg)
        diario(f"actualizar: {msg}")

    rel, motivo = update.check(force=True, cache=cache_version())
    actual = update.installed_version(SCRIPT_DIR)
    if rel is None:
        decir(motivo or "no sé qué versión es la última")
        return 1
    if not update.is_newer(rel.version, actual):
        decir(f"ya está en la última versión ({actual or rel.version})")
        return 0
    trabajo = Path(tempfile.mkdtemp(prefix=f"{APP_NAME}-agente-"))
    try:
        try:
            update.download(rel.tag, trabajo / "codigo", progreso=decir)
        except update.UpdateError as e:
            decir(str(e))
            avisar(f"{APP_NAME}: no he podido actualizar", str(e).splitlines()[0], True)
            return 1
        kwargs = _opciones_hijo(equipo.DIR)
        proc = ejecutar(update.agent_command(trabajo / "codigo", sys.executable),
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", **kwargs)
        for linea in ((proc.stdout or "") + (proc.stderr or "")).splitlines():
            if linea.strip():
                decir(linea.rstrip())
        if proc.returncode != 0:
            avisar(f"{APP_NAME}: no he podido actualizar",
                   f"Lo que ha pasado está en {equipo.diario_log()}.", True)
            return proc.returncode
        avisar(f"{APP_NAME} actualizado a la {rel.tag}",
               "El agente se ha reiniciado con la versión nueva.")
        return 0
    finally:
        shutil.rmtree(trabajo, ignore_errors=True)


def cmd_pregunta(args: argparse.Namespace) -> int:
    from ui import tk_agente
    return tk_agente.main(args.nombre, args.segundos)


def main(argv: list[str] | None = None) -> int:
    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass
    ap = argparse.ArgumentParser(prog="agente.py",
                                 description=f"{APP_NAME} residente: atiende las "
                                             f"unidades que se enchufan en este equipo.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run", help="El bucle del agente.").set_defaults(func=cmd_run)
    sub.add_parser("status", help="Qué atiende y cómo.").set_defaults(func=cmd_status)
    p = sub.add_parser("atender", help="Atender una unidad conectada.")
    p.add_argument("id")
    p.set_defaults(func=lambda a: _pedir({"pide": equipo.PIDE_ATENDER, "id": a.id}))
    p = sub.add_parser("modo", help="Qué hacer con una unidad al enchufarla.")
    p.add_argument("id")
    p.add_argument("modo", choices=equipo.MODOS)
    p.set_defaults(func=lambda a: _pedir({"pide": equipo.PIDE_MODO, "id": a.id,
                                          "modo": a.modo}))
    p = sub.add_parser("pasada", help="Sincronizar ahora, sin moderación.")
    p.add_argument("id")
    p.add_argument("parejas", nargs="*")
    p.set_defaults(func=lambda a: _pedir({"pide": equipo.PIDE_PASADA, "id": a.id,
                                          "parejas": a.parejas}))
    sub.add_parser("pausa", help="Dejar de lanzar pasadas.").set_defaults(
        func=lambda a: _pedir({"pide": equipo.PIDE_PAUSA}))
    sub.add_parser("sigue", help="Volver a lanzarlas.").set_defaults(
        func=lambda a: _pedir({"pide": equipo.PIDE_SIGUE}))
    sub.add_parser("parar", help="Que el agente termine.").set_defaults(func=cmd_parar)
    p = sub.add_parser("abrir", help="La ventana de la raíz de este equipo.")
    p.add_argument("id", nargs="?")
    p.set_defaults(func=cmd_abrir)
    p = sub.add_parser("desbloquear", help="Abrir el contenedor de la raíz cifrada.")
    p.add_argument("id", nargs="?", default="")
    p.set_defaults(func=lambda a: _pedir({"pide": equipo.PIDE_DESBLOQUEAR, "id": a.id}))
    p = sub.add_parser("bloquear", help="Cerrarlo.")
    p.add_argument("id", nargs="?", default="")
    p.set_defaults(func=lambda a: _pedir({"pide": equipo.PIDE_BLOQUEAR, "id": a.id}))
    sub.add_parser("actualizar", help="Bajar la versión nueva y ponerla.").set_defaults(
        func=cmd_actualizar)
    p = sub.add_parser("ajuste", help="Cambiar un ajuste del agente.")
    p.add_argument("clave", choices=equipo.AJUSTES_PEDIBLES)
    p.add_argument("valor")
    p.set_defaults(func=cmd_ajuste)
    p = sub.add_parser("pregunta", help=argparse.SUPPRESS)
    p.add_argument("--nombre", required=True)
    p.add_argument("--segundos", type=int, default=int(equipo.ESPERA_UNIDAD_NUEVA))
    p.set_defaults(func=cmd_pregunta)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
