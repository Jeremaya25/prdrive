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

Las órdenes que no son `run` no hacen nada por sí mismas: dejan la petición en
el buzón del agente (`equipo.pedir()`), que es quien escribe su configuración.

Cómo trabaja, vuelta a vuelta (`Agente.vuelta()`):

  1. **Detecta** las unidades con el mismo recorrido de siempre,
     `penwatch.candidate_roots()`, pero no cada 5 s: en Linux se despierta
     cuando cambia `/proc/self/mountinfo` (`POLLPRI`), y de ahí una racha de
     sondeos, porque un volumen cifrado se lee bastante después de montarse. En
     Windows, hasta que la bandeja traiga su ventana para `WM_DEVICECHANGE`,
     sondea como penwatch. Una unidad cuenta cuando se ha visto dos veces seguidas.
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

Avisa con los avisos del sistema (`common/avisos.py`), no con Tk, y solo cuando
una pareja EMPIEZA a fallar. Sin avisos, queda en su diario.

Depende de `penwatch.py` para detectar, leer los registros de runsync y abrir
VeraCrypt: el agente importa de penwatch, nunca al revés, y penwatch sigue sin
importar nada del proyecto.
"""

from __future__ import annotations

import argparse
import math
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import penwatch  # noqa: E402
from common import (APP_NAME, avisos, catalog, equipo, model, moderacion,  # noqa: E402
                    store)
from common import planificador as pl  # noqa: E402
from common.store import pid_alive  # noqa: E402
from ui import prefs  # noqa: E402

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore

IS_WIN = os.name == "nt"
HOST = equipo.HOST
APP_SUBDIR = penwatch.APP_SUBDIR

TICK = 2.0                      # cada cuánto se mira lo barato: stop, ventana, hijos
RECORRIDO_WINDOWS = penwatch.POLL_SECONDS   # sin WM_DEVICECHANGE todavía: como penwatch
RECORRIDO_RESPALDO = 30.0       # Linux: aunque mountinfo no diga nada
RAFAGA = 60.0                   # tras un cambio de montajes, recorrer en cada vuelta
ESTABLE = penwatch.STABLE_CHECKS
GRACIA = 15.0                   # tras ver la ventana o un stop, antes de volver
MIRAR_ENTORNO = 60.0            # batería y red, cada minuto
PARAR_ESPERA = 10.0             # lo que espera `parar` a que el agente se vaya
COLA_SALIDA = 64 * 1024         # lo que se lee de la salida de una pasada

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
    # Cuándo arrancó, en hora de verdad (`equipo.pedir()` sella con ella): un
    # «parar» de antes iba para el agente anterior.
    inicio: float = field(default_factory=time.time)

    # --- la vuelta ---------------------------------------------------------------

    def vuelta(self, recorrer: bool = True) -> pl.Decision | None:
        ahora = self.reloj()
        self._buzon(ahora)
        if recorrer:
            self._recorrer(ahora)
        for con in list(self.conexiones.values()):
            if not presente(con.raiz):
                self._desconectar(con.id, ahora, {})
        self._preguntas(ahora)
        self._fin_de_pasada(ahora)
        for con in self.conexiones.values():
            self._contrato(con, ahora)
        self._leer_entorno(ahora)
        decision = None
        if self.pasada is None and not self.terminar:
            decision = self._decidir(ahora)
        self._escribir_estado()
        return decision

    # --- detectar ------------------------------------------------------------------

    def _recorrer(self, ahora: float) -> None:
        abiertas: dict[str, Path] = {}
        cerradas: dict[str, Path] = {}
        for raiz in penwatch.candidate_roots({"extra_roots": list(self.ajustes.extra_roots)}):
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

    def _conectar(self, uid: str, raiz: Path, ahora: float) -> None:
        unidad = self.ajustes.unidades.get(uid)
        nombre = nombre_de(raiz, uid, unidad.nombre if unidad else "")
        con = Conexion(uid, raiz, nombre, ahora)
        self.conexiones[uid] = con
        # Cada conexión empieza de cero, como el servicio que se arrancaba al
        # enchufar: se sincroniza enseguida, y el modo `sync` vuelve a tocar.
        for clave in [k for k in self.marcas if k[0] == uid]:
            del self.marcas[clave]
        if unidad is None:
            self._preguntar(con, ahora)
            return
        if unidad.nombre != nombre:
            self._guardar(self.ajustes.con_unidad(replace(unidad, nombre=nombre)))
        diario(f"{nombre} conectada en {raiz} (modo {unidad.modo})")
        if unidad.modo == equipo.UI:
            self._abrir_ventana(con)

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
        diario(f"{con.nombre} desconectada")

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
        con.lanzada = True
        ocupado = penwatch.aplicacion_en_marcha(con.raiz)
        if ocupado:
            diario(f"{con.nombre}: no abro la ventana: {ocupado}")
            return
        if not hay_pantalla():
            diario(f"{con.nombre}: modo ui sin entorno gráfico; no hay dónde abrir "
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
        if penwatch._vivo_aqui(con.raiz, penwatch.UI_LOCK_REL) is not None:
            con.pausa = ahora
        otro = self._otro_servicio(con)
        if otro is not None and con.lock is not None:
            con.lock = None                 # el lock ya es de otro
        self._cargar_servicio(con)

        if con.pausa is not None and ahora - con.pausa < GRACIA:
            con.motivo = "en pausa: hay una ventana de runsync abierta"
        elif otro is not None:
            con.motivo = f"la atiende otro servicio (pid {otro.get('pid')})"
        elif con.servicio is None:
            con.motivo = f"sin servicio: {con.error}"
        else:
            con.pausa = None
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
            if con.lock is None or con.servicio is None:
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
            avisar(f"{con.nombre}: falla {tarea.pareja}",
                   f"Abre {APP_NAME} desde la unidad para ver qué ha pasado.", True)

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
                    avisar(f"{con.nombre}: falla {pareja}",
                           f"Abre {APP_NAME} desde la unidad para ver qué ha pasado.", True)
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

    # --- el entorno ------------------------------------------------------------------

    def _leer_entorno(self, ahora: float) -> None:
        if ahora - self.entorno_leido < MIRAR_ENTORNO:
            return
        self.entorno_leido = ahora
        energia = moderacion.energia()
        self.entorno = replace(self.entorno, con_bateria=energia.con_bateria,
                               bateria=energia.porcentaje,
                               red_medida=moderacion.red_medida())

    # --- el buzón ---------------------------------------------------------------------

    def _buzon(self, ahora: float) -> None:
        for p in equipo.recoger():
            try:
                self._atender_peticion(p, ahora)
            except Exception as e:                      # noqa: BLE001
                diario(f"petición ilegible {p!r}: {e}")

    def _atender_peticion(self, p: dict, ahora: float) -> None:
        que = p.get("pide")
        uid = p.get("id") if isinstance(p.get("id"), str) else ""
        if que == equipo.PIDE_ATENDER:
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

    # --- estado ----------------------------------------------------------------------

    def resumen(self) -> dict:
        unidades = []
        for con in self.conexiones.values():
            unidad = self.ajustes.unidades.get(con.id)
            unidades.append({"id": con.id, "nombre": con.nombre, "raiz": str(con.raiz),
                             "modo": unidad.modo if unidad else None,
                             "atendida": con.lock is not None,
                             "motivo": con.motivo})
        return {"pid": os.getpid(), "pausado": self.pausado, "retenido": self.retenido,
                "pasada": None if self.pasada is None else {
                    "unidad": self.pasada.nombre, "pareja": self.pasada.tarea.pareja,
                    "tipo": self.pasada.tarea.tipo},
                "sin_conexion": sorted(f"{self.conexiones[r].nombre}: {m}"
                                       for r, m in self.entorno.sin_conexion
                                       if r in self.conexiones),
                "unidades": unidades}

    def _escribir_estado(self) -> None:
        resumen = self.resumen()
        if resumen != self.ultimo_estado:
            self.ultimo_estado = resumen
            store.write_json(equipo.estado_json(), {**resumen, "actualizado": store.stamp()})

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
    """Espera el tic, o menos si cambian los montajes (Linux).

    `/proc/self/mountinfo` avisa con `POLLPRI` (y `POLLERR`) cuando cambia la
    tabla de montajes; hay que releerlo entero para rearmar el aviso. En Windows
    todavía no hay nada que esperar: la ventana oculta de la bandeja traerá
    `WM_DEVICECHANGE`."""

    def __init__(self) -> None:
        self._f = None
        self._poll = None
        if IS_WIN:
            return
        try:
            import select
            self._f = MOUNTINFO.open("rb")
            self._f.read()
            self._poll = select.poll()
            self._poll.register(self._f.fileno(), select.POLLPRI | select.POLLERR)
        except (OSError, AttributeError, ImportError):
            self._f, self._poll = None, None

    def esperar(self, segundos: float) -> bool:
        if self._poll is None:
            time.sleep(segundos)
            return False
        try:
            hay = self._poll.poll(int(segundos * 1000))
            if hay:
                self._f.seek(0)
                self._f.read()
                return True
        except OSError:
            time.sleep(segundos)
        return False


# ---------------------------------------------------------------------------
# Órdenes
# ---------------------------------------------------------------------------

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
    proximo = -math.inf
    try:
        while not (agente.terminar and agente.pasada is None):
            ahora = time.time()
            recorrer = ahora >= proximo or ahora < agente.rafaga_hasta
            if recorrer:
                proximo = ahora + (RECORRIDO_WINDOWS if IS_WIN else RECORRIDO_RESPALDO)
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
    print(f"Unidad nueva:   se pregunta y se espera {aj.espera_unidad_nueva:g} s")
    print("Unidades en la lista:" if aj.unidades else "Unidades en la lista: ninguna")
    for u in aj.unidades.values():
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
        print(f"Conectada: {u.get('nombre')} en {u.get('raiz')}"
              + (f" — {u['motivo']}" if u.get("motivo") else " — atendida"))
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
    p = sub.add_parser("pregunta", help=argparse.SUPPRESS)
    p.add_argument("--nombre", required=True)
    p.add_argument("--segundos", type=int, default=int(equipo.ESPERA_UNIDAD_NUEVA))
    p.set_defaults(func=cmd_pregunta)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
