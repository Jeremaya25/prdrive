#!/usr/bin/env python3
"""
install/agente.py — El agente residente en ESTE equipo: ponerlo y quitarlo.

La instalación «solo agente» del diseño (`docs/superpowers/specs/2026-09-25-
instalacion-en-el-equipo-design.md`): ni raíz, ni conexión, ni clave. Deja en la
carpeta del equipo (`common/equipo.py`) el código del agente, su propio Python y
su configuración, lo registra para que arranque al iniciar sesión, y le quita el
sitio a penwatch, que es a quien sustituye.

    preparar()     el código en `agente/<versión>/` y el Python en `runtime/<id>/`
    candidatas()   qué unidades se le pueden dar ya: las de penwatch, las
                   enchufadas y las que ya tenga en su lista
    activar()      su lista de unidades (y la raíz del equipo, si la hay),
                   penwatch fuera, registro, el acceso del menú, arranque
    desinstalar()  todo lo anterior al revés; nunca toca una unidad ni la raíz

La raíz del equipo (fase 2, `install/raiz_equipo.py`) la pone el asistente
antes; aquí solo entra en la lista del agente, con su ruta, y trae consigo el
acceso «prdrive» del menú del sistema, que abre su ventana (`agente.py abrir`):
no lleva lanzadores ni Python propio.

Tres reglas, las mismas que en el resto de `install/`:

  * **Nunca se cambia en sitio lo que está corriendo.** Cada versión del código y
    cada Python en su carpeta, al lado de la anterior; se ponen con un
    `os.replace` y se recogen las viejas después. En Windows no se renombra la
    carpeta de un `pythonw.exe` vivo, y el agente corre justo desde ahí.
  * **`agente.json` tiene un escritor.** Lo crea este módulo la primera vez; si
    ya existe, lo que se elige aquí se le PIDE al agente por su buzón
    (`equipo.pedir()`), y él lo escribe.
  * **Nada de esto toca una unidad.** Leer su id y su nombre para ofrecerla, y
    punto: desinstalar no borra nada de ninguna.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import penwatch
from common import APP_NAME, equipo, store
from common.pins import Plataforma

from . import InstallError, bundle_dir, platforms, runtime_bin, version

IS_WIN = os.name == "nt"

# Lo que se copia al equipo: el agente, penwatch (del que importa la detección)
# y los dos paquetes. `install/` no: el agente no instala nada.
CODIGO_FICHEROS = ("agente.py", "penwatch.py", "VERSION")
CODIGO_ARBOLES = ("common", "ui")
NO_COPIAR = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo")

TAREA = APP_NAME                            # Windows: la tarea programada
DESCRIPCION = (f"{APP_NAME} residente: sincroniza las unidades {APP_NAME} que se "
               f"enchufan en este equipo.")
PARAR_ESPERA = 12.0


def autostart_file() -> Path:
    """Linux: el autostart XDG. Función para que los tests lo lleven a un temporal."""
    base = os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
    return Path(base) / "autostart" / f"{APP_NAME}.desktop"


def orden(python: str | Path, codigo: Path) -> list[str]:
    """Con qué se arranca el agente: su Python y su `agente.py run`."""
    return [str(python), str(codigo / "agente.py"), "run"]


# ---------------------------------------------------------------------------
# El código y el Python
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Preparado:
    codigo: Path            # agente/<versión>/
    python: Path            # el intérprete sin consola del runtime
    sello: str              # el sello del runtime (de qué archivo salió)


def copiar_codigo(origen: Path | None = None) -> Path:
    """Copia el código del agente a `agente/<versión>/`. Devuelve la carpeta.

    Se monta al lado y se pone con un `os.replace`; si ya había una carpeta de
    esa misma versión, se aparta antes y se borra después."""
    base = Path(origen) if origen else bundle_dir()
    destino = equipo.dir_codigo() / version()
    trabajo = destino.with_name(f".{destino.name}.nuevo-{os.getpid()}")
    shutil.rmtree(trabajo, ignore_errors=True)
    try:
        trabajo.mkdir(parents=True)
        for nombre in CODIGO_FICHEROS:
            src = base / nombre
            if not src.is_file():
                raise InstallError(f"El instalador no lleva {nombre} dentro "
                                   f"(buscado en {base}).")
            shutil.copy2(src, trabajo / nombre)
        for nombre in CODIGO_ARBOLES:
            src = base / nombre
            if not src.is_dir():
                raise InstallError(f"El instalador no lleva el paquete {nombre}/.")
            shutil.copytree(src, trabajo / nombre, ignore=NO_COPIAR)
    except OSError as e:
        shutil.rmtree(trabajo, ignore_errors=True)
        raise InstallError(f"No he podido copiar el agente a {trabajo}: {e}") from e
    try:
        from ui import icons                    # sin Tk: rasteriza él solo
        icons.write_ico(trabajo / "runsync.ico")
        icons.write_bandeja(trabajo)            # los cinco estados de la bandeja
    except Exception:                           # noqa: BLE001
        pass            # sin iconos: el agente repinta los de la bandeja al arrancar
    viejo = destino.with_name(f".{destino.name}.viejo-{os.getpid()}")
    try:
        if destino.exists():
            os.replace(destino, viejo)
        os.replace(trabajo, destino)
    except OSError as e:
        if viejo.exists() and not destino.exists():
            os.replace(viejo, destino)
        shutil.rmtree(trabajo, ignore_errors=True)
        raise InstallError(f"No he podido poner el agente en {destino}: {e}") from e
    shutil.rmtree(viejo, ignore_errors=True)
    return destino


def conseguir_runtime(plat: Plataforma, progreso=None) -> Path:
    """El archivo de Python comprobado para esta plataforma (de la caché del
    instalador o descargado). Punto de indirección para los tests."""
    return runtime_bin.ensure_runtime(plat, progreso)


def poner_runtime(progreso=None) -> tuple[Path, str]:
    """El Python del agente en `runtime/<id>/`. Devuelve (intérprete, sello).

    El id sale del sello, como en penwatch: dos versiones nunca comparten
    carpeta, y una que ya está no se vuelve a extraer."""
    plat = platforms.host()
    if plat is None:
        raise InstallError("El agente residente es para Windows y Linux, y este "
                           "equipo no es ninguno de los dos.")
    archivo = conseguir_runtime(plat, progreso)
    sha = runtime_bin.recorded_sha256(archivo) or runtime_bin.file_sha256(archivo)
    sello = runtime_bin.stamp_text(plat, sha)
    destino = equipo.dir_runtimes() / penwatch.stamp_id(sello)
    interprete = destino / plat.interprete
    try:
        if (destino / runtime_bin.STAMP).read_text(encoding="utf-8") == sello \
                and interprete.is_file():
            return interprete, sello
    except OSError:
        pass
    trabajo = destino.with_name(f".{destino.name}.nuevo-{os.getpid()}")
    shutil.rmtree(trabajo, ignore_errors=True)
    if progreso:
        progreso(f"Extrayendo Python {plat.nombre} para el agente…")
    try:
        runtime_bin.extract(archivo, trabajo, plat, sha)
        if destino.exists():
            shutil.rmtree(destino)          # uno sin sello bueno: a medias
        os.replace(trabajo, destino)
    except OSError as e:
        shutil.rmtree(trabajo, ignore_errors=True)
        raise InstallError(f"No he podido poner el Python del agente en {destino}: "
                           f"{e}") from e
    except InstallError:
        shutil.rmtree(trabajo, ignore_errors=True)
        raise
    return interprete, sello


def preparar(progreso=None, origen: Path | None = None) -> Preparado:
    """El paso «Instalación» del recorrido del equipo: código y Python."""
    codigo = copiar_codigo(origen)
    python, sello = poner_runtime(progreso)
    return Preparado(codigo, python, sello)


# ---------------------------------------------------------------------------
# Las unidades que se le pueden dar
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Candidata:
    id: str
    nombre: str
    modo: str               # el que se le propone
    origen: str             # de dónde se sabe de ella, para decirlo


def de_penwatch() -> tuple[str, str] | None:
    """(id, modo) de la unidad que atiende el penwatch de este equipo, o None."""
    cfg = penwatch.read_json(penwatch.CONFIG_FILE)
    uid = cfg.get("device_id")
    if not isinstance(uid, str) or not uid:
        return None
    modo = cfg.get("mode") if cfg.get("mode") in equipo.MODOS else equipo.UI
    return uid, modo


def enchufadas() -> list[tuple[str, str]]:
    """(id, nombre) de las unidades prdrive enchufadas y abiertas ahora mismo.
    Solo se leen su fichero de control y su `state/fleet.json`."""
    vistas: dict[str, str] = {}
    for raiz in penwatch.candidate_roots({}):
        try:
            if not ((raiz / penwatch.CONTROL_FILE).is_file()
                    and (raiz / penwatch.STRUCT_MARKER).is_file()):
                continue
            uid = penwatch.control_id(raiz)
        except OSError:
            continue
        if uid and uid not in vistas:
            nombre = store.read_json(raiz / penwatch.APP_SUBDIR / "state" / "fleet.json"
                                     ).get("nombre")
            vistas[uid] = nombre.strip() if isinstance(nombre, str) and nombre.strip() \
                else ""
    return list(vistas.items())


def candidatas() -> list[Candidata]:
    """Las unidades que el paso «Unidades» ofrece, sin red: las que el agente
    ya tiene en su lista, la de penwatch y las enchufadas. El resto llegará con
    el aviso de «unidad nueva»."""
    salida: dict[str, Candidata] = {}
    for u in equipo.leer_ajustes().unidades.values():
        if u.es_raiz:
            continue            # la raíz del equipo no se enchufa: no es una unidad
        salida[u.id] = Candidata(u.id, u.nombre, u.modo, "ya en la lista del agente")
    pw = de_penwatch()
    if pw and pw[0] not in salida:
        salida[pw[0]] = Candidata(pw[0], "", pw[1], "la vigilaba penwatch")
    for uid, nombre in enchufadas():
        if uid in salida:
            if nombre and not salida[uid].nombre:
                c = salida[uid]
                salida[uid] = Candidata(uid, nombre, c.modo, c.origen)
            continue
        salida[uid] = Candidata(uid, nombre, equipo.MODO_AL_ATENDER, "enchufada ahora")
    return list(salida.values())


def aplicar_unidades(elegidas: dict[str, tuple[str, str]], espera: float,
                     raiz: equipo.Unidad | None = None,
                     pedir_al_iniciar: bool | None = None) -> str:
    """Lo que se ha elegido en «Unidades»: {id: (modo, nombre)} y el plazo, y
    la raíz del equipo que haya puesto el asistente (una `Unidad` con `ruta`).

    Sin `agente.json` se escribe de una vez. Con él, el agente ya tiene dueño de
    su configuración y se le pide por el buzón: una unidad nueva entra con su
    modo (`PIDE_MODO`), la raíz con `PIDE_RAIZ` (con su contenedor si va
    cifrada), y el plazo y `pedir_al_iniciar` son `PIDE_AJUSTE`. None en
    `pedir_al_iniciar` es «no lo ha preguntado nadie»: se deja como esté."""
    if not equipo.ajustes_json().exists():
        aj = equipo.Ajustes(espera_unidad_nueva=espera,
                            pedir_al_iniciar=True if pedir_al_iniciar is None
                            else pedir_al_iniciar)
        for uid, (modo, nombre) in elegidas.items():
            aj = aj.con_unidad(equipo.Unidad(uid, modo, nombre))
        if raiz is not None:
            aj = aj.con_unidad(raiz)
        aj = equipo.desde_dict(equipo.a_dict(aj))          # saneado, como al leerlo
        if not equipo.guardar_ajustes(aj):
            raise InstallError(f"No he podido escribir {equipo.ajustes_json()}.")
        return f"Configuración del agente escrita en {equipo.ajustes_json()}."
    actuales = equipo.leer_ajustes()
    pedidas = 0
    if raiz is not None:
        ya = actuales.unidades.get(raiz.id)
        if (ya is None or ya.ruta != raiz.ruta or ya.modo != raiz.modo
                or ya.contenedor != raiz.contenedor):
            equipo.pedir({"pide": equipo.PIDE_RAIZ, "id": raiz.id, "ruta": raiz.ruta,
                          "nombre": raiz.nombre, "modo": raiz.modo,
                          **({"contenedor": raiz.contenedor} if raiz.contenedor
                             else {})})
            pedidas += 1
    for uid, (modo, nombre) in elegidas.items():
        ya = actuales.unidades.get(uid)
        if ya is None or ya.modo != modo:
            equipo.pedir({"pide": equipo.PIDE_MODO, "id": uid, "modo": modo,
                          "nombre": nombre})
            pedidas += 1
    if actuales.espera_unidad_nueva != espera:
        equipo.pedir({"pide": equipo.PIDE_AJUSTE, "clave": "espera_unidad_nueva",
                      "valor": espera})
        pedidas += 1
    if pedir_al_iniciar is not None and actuales.pedir_al_iniciar != pedir_al_iniciar:
        equipo.pedir({"pide": equipo.PIDE_AJUSTE, "clave": "pedir_al_iniciar",
                      "valor": pedir_al_iniciar})
        pedidas += 1
    return (f"El agente ya tenía su configuración: se le han pedido {pedidas} cambios."
            if pedidas else "El agente ya tenía esta configuración.")


def raiz_pedida(uid: str | None) -> bool:
    """¿Hay en el buzón del agente una petición sin leer de añadir esa raíz? Es
    lo que la verificación del asistente acepta como «ya está en camino»."""
    if not uid:
        return False
    try:
        lineas = equipo.buzon().read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    for linea in lineas:
        try:
            p = json.loads(linea)
        except ValueError:
            continue
        if isinstance(p, dict) and p.get("pide") == equipo.PIDE_RAIZ \
                and p.get("id") == uid:
            return True
    return False


# ---------------------------------------------------------------------------
# penwatch fuera, registro, arranque
# ---------------------------------------------------------------------------

def quitar_penwatch() -> list[str]:
    """El agente lo sustituye en este equipo: se desinstala, y se dice.

    Lo que vigilaba ya ha pasado a la lista del agente (`candidatas()`)."""
    if not (penwatch.CONFIG_FILE.exists() or penwatch.HOST_DIR.exists()):
        return []
    msgs = [f"penwatch: {m}" for m in penwatch.unregister()]
    parado = penwatch.stop_running_watcher()
    if parado:
        msgs.append(f"penwatch: {parado}")
    try:
        shutil.rmtree(penwatch.HOST_DIR)
        msgs.append(f"penwatch: eliminado {penwatch.HOST_DIR}")
    except OSError as e:
        msgs.append(f"penwatch: no he podido borrar {penwatch.HOST_DIR}: {e}")
    msgs.append("El agente sustituye a penwatch en este equipo: lo que vigilaba "
                "está en su lista.")
    return msgs


def registrar(prep: Preparado) -> str:
    """Que arranque al iniciar sesión. Windows: la tarea por usuario de penwatch,
    con sus trampas resueltas. Linux: autostart XDG y no una unidad systemd,
    porque los avisos, la pregunta de «unidad nueva» y la contraseña de
    VeraCrypt necesitan la sesión gráfica, y `enable-linger` no la da."""
    if IS_WIN:
        try:
            return penwatch.register_task(
                TAREA, str(prep.python), f'"{prep.codigo / "agente.py"}" run',
                equipo.DIR, DESCRIPCION)
        except (OSError, RuntimeError) as e:
            raise InstallError(f"No he podido registrar el agente: {e}") from e
    destino = autostart_file()
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(penwatch.autostart_desktop(
            APP_NAME, orden(prep.python, prep.codigo), DESCRIPCION), encoding="utf-8")
    except OSError as e:
        raise InstallError(f"No he podido escribir {destino}: {e}") from e
    return f"Autostart instalado en {destino}: arranca al iniciar el escritorio."


def desregistrar() -> str:
    if IS_WIN:
        res = penwatch.run_quiet(["schtasks", "/Delete", "/TN", TAREA, "/F"])
        return (f"Tarea '{TAREA}' eliminada." if res.returncode == 0
                else f"No había tarea '{TAREA}'.")
    destino = autostart_file()
    if destino.exists():
        destino.unlink(missing_ok=True)
        return f"Autostart {destino} eliminado."
    return "No había autostart."


# ---------------------------------------------------------------------------
# El acceso del menú: abrir la ventana de la raíz del equipo
# ---------------------------------------------------------------------------

def acceso_menu() -> Path:
    """Dónde va el acceso «prdrive» del menú del sistema. Función para que los
    tests lo lleven a un temporal, como `autostart_file()`."""
    if IS_WIN:
        base = os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming")
        return (Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
                / f"{APP_NAME}.lnk")
    base = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
    return Path(base) / "applications" / f"{APP_NAME}.desktop"


COMENTARIO_MENU = f"La ventana de {APP_NAME} de este equipo: sus parejas y su estado."


def menu_desktop(args: list[str], icono: Path | None = None) -> str:
    """La entrada del menú de aplicaciones (Desktop Entry Specification): visible,
    a diferencia del autostart, con el `Exec=` escapado como aquel."""
    return ("[Desktop Entry]\nType=Application\n"
            f"Name={APP_NAME}\n"
            f"Comment={COMENTARIO_MENU}\n"
            f"Exec={penwatch.desktop_exec(args)}\n"
            + (f"Icon={icono}\n" if icono else "")
            + "Terminal=false\nCategories=Utility;\n")


def crear_lnk(destino: Path, objetivo: str, argumentos: str, carpeta: str,
              icono: str, descripcion: str) -> None:
    """Un acceso directo `.lnk` de Windows, con `IShellLinkW` + `IPersistFile`.

    COM por vtable, como `IShellItem2` en `install/crypto.py`: la biblioteca
    estándar no trae COM y el proyecto no admite dependencias. Punto de
    indirección: los tests lo sustituyen, y no está probado en un Windows real.

    Huecos de la vtabla (detrás de los 3 de IUnknown), en el orden de
    `ShObjIdl_core.h`: IShellLinkW 7 SetDescription, 9 SetWorkingDirectory,
    11 SetArguments, 17 SetIconLocation, 20 SetPath; IPersistFile (detrás de
    IPersist::GetClassID, el 3) 6 Save."""
    import ctypes
    from ctypes import POINTER, byref, c_int, c_long, c_void_p, c_wchar_p
    from ctypes.wintypes import ULONG

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
                    ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]

    ole32 = ctypes.windll.ole32

    def guid(texto: str) -> GUID:
        g = GUID()
        if ole32.CLSIDFromString(c_wchar_p(texto), byref(g)) < 0:
            raise OSError(f"GUID ilegible: {texto}")
        return g

    def vtabla(objeto: c_void_p):
        return ctypes.cast(objeto, POINTER(POINTER(c_void_p))).contents

    def soltar(objeto: c_void_p) -> None:
        ctypes.WINFUNCTYPE(ULONG, c_void_p)(vtabla(objeto)[2])(objeto)

    def comprobar(hr: int, que: str) -> None:
        if hr < 0:
            raise OSError(f"{que}: 0x{hr & 0xFFFFFFFF:08X}")

    clsid = guid("{00021401-0000-0000-C000-000000000046}")      # CLSID_ShellLink
    iid_enlace = guid("{000214F9-0000-0000-C000-000000000046}")  # IID_IShellLinkW
    iid_fichero = guid("{0000010B-0000-0000-C000-000000000046}") # IID_IPersistFile
    hr_init = ole32.CoInitializeEx(None, 2)             # COINIT_APARTMENTTHREADED
    try:
        enlace = c_void_p()
        comprobar(ole32.CoCreateInstance(byref(clsid), None, 1, byref(iid_enlace),
                                         byref(enlace)), "CoCreateInstance(ShellLink)")
        tabla = vtabla(enlace)
        try:
            texto = ctypes.WINFUNCTYPE(c_long, c_void_p, c_wchar_p)
            for hueco, valor, que in ((20, objetivo, "SetPath"),
                                      (11, argumentos, "SetArguments"),
                                      (9, carpeta, "SetWorkingDirectory"),
                                      (7, descripcion, "SetDescription")):
                comprobar(texto(tabla[hueco])(enlace, valor), que)
            comprobar(ctypes.WINFUNCTYPE(c_long, c_void_p, c_wchar_p, c_int)(
                tabla[17])(enlace, icono, 0), "SetIconLocation")
            fichero = c_void_p()
            comprobar(ctypes.WINFUNCTYPE(c_long, c_void_p, POINTER(GUID),
                                         POINTER(c_void_p))(tabla[0])(
                enlace, byref(iid_fichero), byref(fichero)), "QueryInterface")
            try:
                comprobar(ctypes.WINFUNCTYPE(c_long, c_void_p, c_wchar_p, c_int)(
                    vtabla(fichero)[6])(fichero, str(destino), 1), "IPersistFile::Save")
            finally:
                soltar(fichero)
        finally:
            soltar(enlace)
    finally:
        if hr_init >= 0:
            ole32.CoUninitialize()


def poner_menu(prep: Preparado) -> str:
    """El acceso «prdrive» del menú, que abre la ventana de la raíz del equipo
    con el Python del agente (`agente.py abrir`). Se reescribe en cada
    instalación: apunta a la versión del código, que cambia."""
    destino = acceso_menu()
    icono = prep.codigo / "runsync.ico"
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
        if IS_WIN:
            crear_lnk(destino, str(prep.python), f'"{prep.codigo / "agente.py"}" abrir',
                      str(equipo.DIR), str(icono), COMENTARIO_MENU)
        else:
            destino.write_text(menu_desktop(
                [str(prep.python), str(prep.codigo / "agente.py"), "abrir"],
                icono if icono.is_file() else None), encoding="utf-8")
    except (OSError, AttributeError) as e:
        return (f"No he podido crear el acceso del menú ({e}): la ventana se abre con "
                f"«{prep.python} {prep.codigo / 'agente.py'} abrir».")
    return f"Acceso «{APP_NAME}» en el menú del sistema: abre la ventana de este equipo."


def quitar_menu() -> str | None:
    destino = acceso_menu()
    if not destino.exists():
        return None
    try:
        destino.unlink()
    except OSError as e:
        return f"No he podido borrar {destino}: {e}"
    return f"Acceso del menú {destino} eliminado."


def lanzar(args: list[str], **kwargs):
    """Punto de indirección: arrancar el agente sin esperar a la sesión siguiente."""
    return subprocess.Popen(args, **kwargs)


def arrancar(prep: Preparado) -> str:
    if IS_WIN:
        res = penwatch.run_quiet(["schtasks", "/Run", "/TN", TAREA])
        if res.returncode == 0:
            return "Agente arrancado."
        return (f"No he podido arrancarlo ahora ({res.stderr.strip()}); arrancará "
                f"al iniciar sesión.")
    try:
        lanzar(orden(prep.python, prep.codigo), stdin=subprocess.DEVNULL,
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
               cwd=str(equipo.DIR), start_new_session=True, close_fds=True)
        return "Agente arrancado."
    except OSError as e:
        return f"No he podido arrancarlo ahora ({e}); arrancará al iniciar sesión."


def parar_agente() -> str | None:
    """Pide al agente en marcha que termine, y si no lo hace a tiempo (está en
    mitad de una pasada), lo termina: la pasada sigue sola hasta acabar."""
    vivo = equipo.agente_vivo()
    if vivo is None:
        return None
    pid = int(vivo.get("pid", -1))
    equipo.pedir({"pide": equipo.PIDE_PARAR})
    limite = time.monotonic() + PARAR_ESPERA
    while time.monotonic() < limite and equipo.agente_vivo() is not None:
        time.sleep(0.3)
    if equipo.agente_vivo() is None:
        return f"Agente anterior (pid {pid}) detenido."
    penwatch.kill_pid(pid)
    return f"Agente anterior (pid {pid}) terminado a la fuerza."


def podar(prep: Preparado) -> None:
    """Las versiones viejas de código y de Python que ya no usa nadie. Lo que no
    se pueda borrar (un Python en uso) se queda para la próxima vez."""
    python = Path(os.path.relpath(prep.python, equipo.dir_runtimes())).parts[0]
    for base, guardar in ((equipo.dir_codigo(), prep.codigo.name),
                          (equipo.dir_runtimes(), python)):
        try:
            hijos = list(base.iterdir())
        except OSError:
            continue
        for hijo in hijos:
            if hijo.name != guardar:
                shutil.rmtree(hijo, ignore_errors=True)


def activar(prep: Preparado, elegidas: dict[str, tuple[str, str]], espera: float,
            arrancar_ya: bool = True, raiz: equipo.Unidad | None = None,
            pedir_al_iniciar: bool | None = None) -> list[str]:
    """Los pasos «Unidades» y «Arranque» de una vez: configuración (con la raíz
    del equipo, si la hay), penwatch fuera, registro, el acceso del menú,
    `instalacion.json`, versiones viejas fuera y arranque."""
    msgs = []
    parado = parar_agente()
    if parado:
        msgs.append(parado)
    msgs.append(aplicar_unidades(elegidas, espera, raiz, pedir_al_iniciar))
    msgs += quitar_penwatch()
    msgs.append(registrar(prep))
    # El acceso del menú solo tiene sentido con una raíz del equipo: es su
    # ventana. Sin ella, cada unidad se abre desde sí misma.
    if raiz is not None or equipo.leer_ajustes().raices:
        msgs.append(poner_menu(prep))
    store.write_json(equipo.instalacion_json(), {
        "version": version(), "codigo": str(prep.codigo), "python": str(prep.python),
        "runtime": penwatch.stamp_id(prep.sello), "instalado": store.stamp()})
    podar(prep)
    if arrancar_ya:
        msgs.append(arrancar(prep))
    return msgs


def instalar(elegidas: dict[str, tuple[str, str]] | None = None,
             espera: float = equipo.ESPERA_UNIDAD_NUEVA, progreso=None) -> list[str]:
    """Todo de una vez, sin asistente (`prdrive-install.py --instalar-agente`).
    Sin unidades elegidas, las que `candidatas()` propone, con su modo."""
    prep = preparar(progreso)
    if elegidas is None:
        elegidas = {c.id: (c.modo, c.nombre) for c in candidatas()}
    return [f"Código del agente en {prep.codigo}", f"Su Python: {prep.python}",
            *activar(prep, elegidas, espera)]


def desinstalar() -> list[str]:
    """Quita el registro, el acceso del menú, el agente y su Python. Nunca toca
    una unidad ni la raíz del equipo: lo que tuviera a medias el agente sigue en
    ellas, como las dejó."""
    msgs = []
    parado = parar_agente()
    if parado:
        msgs.append(parado)
    msgs.append(desregistrar())
    menu = quitar_menu()
    if menu:
        msgs.append(menu)
    raices = list(equipo.leer_ajustes().raices.values())
    if equipo.DIR.exists():
        shutil.rmtree(equipo.DIR, ignore_errors=True)
        msgs.append(f"Eliminado {equipo.DIR}" if not equipo.DIR.exists()
                    else f"Queda algo en {equipo.DIR} (en uso); se puede borrar a mano.")
    msgs.append("Las unidades no se han tocado.")
    for u in raices:
        # Nunca se borra: tiene las carpetas del usuario, y la clave. Se dice
        # dónde está para que no parezca que se ha ido con el agente.
        if u.cifrada:
            # Tampoco se cierra: si está abierta es porque alguien la usa, y
            # desmontar con algo abierto dentro es decisión de la persona.
            abierta = _presente(Path(u.ruta))
            msgs.append(f"La raíz cifrada de este equipo sigue en {u.contenedor}"
                        + (f", y ABIERTA en {u.ruta}: ciérrala desde VeraCrypt cuando "
                           f"quieras." if abierta else ".")
                        + " Bórrala a mano si ya no la quieres.")
            continue
        msgs.append(f"La raíz de este equipo sigue en {u.ruta}, con sus carpetas y su "
                    f".prdrive/ (la clave incluida): bórrala a mano si ya no la quieres.")
    return msgs


def _presente(raiz: Path) -> bool:
    try:
        return (raiz / penwatch.CONTROL_FILE).is_file()
    except OSError:
        return False


def instalado() -> dict | None:
    """Lo que dice `instalacion.json`, si hay un agente instalado."""
    return equipo.leer_instalacion() if equipo.instalado() else None
