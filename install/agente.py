#!/usr/bin/env python3
"""El agente residente en ESTE equipo: ponerlo y quitarlo.

Es la instalación «solo agente» del diseño
(`docs/superpowers/specs/2026-09-25-instalacion-en-el-equipo-design.md`): ni
raíz, ni conexión, ni clave. Deja en la carpeta del equipo (`common/equipo.py`)
el código del agente, su propio Python y su configuración, lo registra para que
arranque al iniciar sesión y le quita el sitio a penwatch, que es a quien
sustituye.
- `preparar()`: el código en `agente/<versión>/` y el Python en
  `runtime/<id>/`.
- `candidatas()`: qué unidades se le pueden dar ya (las de penwatch, las
  enchufadas y las que ya tenga en su lista).
- `activar()`: su lista de unidades (y la raíz del equipo, si la hay), penwatch
  fuera, registro, el acceso del menú y arranque.
- `anadir()`: lo mismo con el agente ya instalado y de esta versión, solo por
  su buzón, sin pararlo ni reinstalarlo.
- `actualizar()`: la versión que trae este instalador en lugar de la puesta
  (`--update-agente`, lo que lanza «Actualizar» de la bandeja).
- `desinstalar()`: todo lo anterior al revés; nunca toca una unidad ni la raíz.

La raíz del equipo (`install/raiz_equipo.py`) la pone el asistente antes; aquí
solo entra en la lista del agente, con su ruta, y trae consigo el acceso
«prdrive» del menú del sistema, que abre su ventana (`agente.py abrir`): no
lleva lanzadores ni Python propio.

Tres reglas, las mismas que en el resto de `install/`:
- Nunca se cambia en sitio lo que está corriendo: cada versión del código y
  cada Python va en su carpeta, al lado de la anterior; se ponen con un
  `os.replace` y se recogen las viejas después. En Windows no se renombra la
  carpeta de un `pythonw.exe` vivo, y el agente corre justo desde ahí.
- `agente.json` tiene un escritor: lo crea este módulo la primera vez; si ya
  existe, lo que se elige aquí se le PIDE al agente por su buzón
  (`equipo.pedir()`) y él lo escribe.
- Nada de esto toca una unidad: solo se lee su id y su nombre para ofrecerla, y
  desinstalar no borra nada de ninguna.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, replace
from pathlib import Path

import penwatch
from common import APP_NAME, components, equipo, model, pins, store, vestibulo
from common.pins import Plataforma

from . import (InstallError, bundle_dir, pintar, platforms, rclone_bin, runtime_bin,
               veracrypt_bin, version)

IS_WIN = os.name == "nt"

CODIGO_FICHEROS = ("pregunta.py", "agente.py", "penwatch.py", "VERSION")
"""Ficheros sueltos que se copian al equipo, en este orden.

La entrada de la ventanita de la pregunta (`pregunta.py`), que va antes que el
agente que la lanza; el agente, penwatch (del que importa la detección) y la
versión.

`install/` no se copia: el agente no instala nada.
"""
CODIGO_ARBOLES = ("common", "ui")
"""Paquetes que se copian al equipo."""
NO_COPIAR = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo")
"""Patrones de ficheros que se ignoran al copiar el código."""

TAREA = APP_NAME  # Windows: la tarea programada
DESCRIPCION = (f"{APP_NAME} residente: sincroniza las unidades {APP_NAME} que se "
               f"enchufan en este equipo.")
"""Descripción con la que se registra el agente."""
PARAR_ESPERA = 12.0
"""Segundos que se espera a que el agente se vaya si no tiene pasada en marcha."""
ESPERA_PASADA = 600.0
"""Segundos que se espera a que acabe la pasada en marcha, antes de cortarla."""


def autostart_file() -> Path:
    """Devuelve el autostart XDG de Linux.

    Es función para que los tests lo lleven a un temporal.
    """
    base = os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
    return Path(base) / "autostart" / f"{APP_NAME}.desktop"


def orden(python: str | Path, codigo: Path) -> list[str]:
    """Devuelve con qué se arranca el agente: su Python y su `agente.py run`."""
    return [str(python), str(codigo / "agente.py"), "run"]


@dataclass(frozen=True)
class Preparado:
    """Datos preparados para arrancar el agente.

    Args:
        codigo: La carpeta `agente/<versión>/` con el código.
        python: El intérprete sin consola del runtime.
        sello: El sello del runtime (de qué archivo salió).
        rclone: El binario `rclone/<versión fijada>/rclone` que el agente pasa
            a sus hijos, si lo hay.
        veracrypt: La carpeta `veracrypt/<versión fijada>/` con su VeraCrypt,
            si hace falta.
    """
    codigo: Path
    python: Path
    sello: str
    rclone: Path | None = None
    veracrypt: Path | None = None


def copiar_codigo(origen: Path | None = None) -> Path:
    """Copia el código del agente a `agente/<versión>/` y devuelve la carpeta.

    Se monta al lado y se pone con un `os.replace`; si ya había una carpeta de
    esa misma versión se aparta antes y se borra después.

    Raises:
        InstallError: Si falta algo en el origen o no se puede copiar.
    """
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
    pintar(trabajo, bandeja=True)   # sin ellos, el agente repinta los de la bandeja
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
    """Devuelve el archivo de Python comprobado para esta plataforma.

    Sale de la caché del instalador o de la descarga. Es un punto de
    indirección para los tests.
    """
    return runtime_bin.ensure_runtime(plat, progreso)


def poner_runtime(progreso=None) -> tuple[Path, str]:
    """Pone el Python del agente en `runtime/<id>/` y devuelve `(intérprete, sello)`.

    El id sale del sello, como en penwatch: dos versiones nunca comparten
    carpeta y una que ya está no se vuelve a extraer.

    Raises:
        InstallError: Si este equipo no es Windows ni Linux o no se puede
            extraer.
    """
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


def conseguir_rclone(plat: Plataforma, progreso=None) -> Path:
    """Devuelve el rclone de la versión fijada para esta plataforma, comprobado.

    Sale de la caché del instalador, del zip oficial dejado a mano o de la
    descarga; nunca uno cualquiera del `PATH`: es el que el agente pasa en
    lugar del de cada unidad y tiene que ser uno del que se sabe qué es. Es un
    punto de indirección para los tests.
    """
    return rclone_bin.pinned_rclone(plat, progreso)


def poner_rclone(progreso=None) -> Path:
    """Pone el rclone del agente en `rclone/<versión fijada>/` y devuelve el binario.

    Va en una carpeta por versión, como el Python: una pasada puede estar
    usando el de ahora mientras se instala el siguiente. Se copia al lado y se
    pone con un `os.replace`; uno que ya está, del mismo tamaño, no se vuelve a
    copiar.

    Raises:
        InstallError: Si este equipo no es Windows ni Linux o no se puede
            copiar.
    """
    plat = platforms.host()
    if plat is None:
        raise InstallError("El agente residente es para Windows y Linux, y este "
                           "equipo no es ninguno de los dos.")
    origen = conseguir_rclone(plat, progreso)
    destino = equipo.dir_rclone() / pins.RCLONE_VERSION
    binario = destino / model.rclone_name()
    try:
        if binario.is_file() and binario.stat().st_size == origen.stat().st_size:
            return binario
    except OSError:
        pass
    trabajo = destino.with_name(f".{destino.name}.nuevo-{os.getpid()}")
    shutil.rmtree(trabajo, ignore_errors=True)
    try:
        trabajo.mkdir(parents=True)
        shutil.copy2(origen, trabajo / model.rclone_name())
        if not IS_WIN:
            (trabajo / model.rclone_name()).chmod(0o755)
        if destino.exists():
            shutil.rmtree(destino)
        os.replace(trabajo, destino)
    except OSError as e:
        shutil.rmtree(trabajo, ignore_errors=True)
        raise InstallError(f"No he podido poner el rclone del agente en {destino}: "
                           f"{e}") from e
    return binario


def quiere_veracrypt(cifrada: bool = False) -> bool:
    r"""Indica si el agente tiene que llevar su propio VeraCrypt.

    El agente abre y cierra la raíz cifrada del equipo. Con VeraCrypt
    instalado, con ese (su driver ya está cargado y solo pide la contraseña).
    Sin él, en Windows, con el VeraCrypt Portable oficial fijado en `pins.py`,
    el mismo que lleva una unidad cifrada en `VeraCrypt\`: sin instalar nada,
    pero con UAC cada vez que carga su driver, que es cada vez que abre o
    cierra (documentación de VeraCrypt, «Portable Mode»: «You need
    administrator privileges in order to be able to run VeraCrypt in portable
    mode»). En Linux, con el AppImage oficial, que pide la contraseña de
    administrador para montar igual que el instalado. Se copia a
    `veracrypt/<versión>/` de la carpeta del agente, fuera de toda raíz y con
    su sello: el agente lo vuelve a resumir contra él antes de cada lanzamiento
    (`agente.veracrypt_propio()`).

    Solo hace falta si atiende una raíz cifrada y en el equipo no hay uno
    instalado. El instalado va siempre primero: con el driver de otra versión
    menor cargado, el portable falla con `ERR_DRIVER_VERSION` (`DriverAttach()`
    en `Common/Dlgcode.c`), y con el suyo cargado no hay UAC que pedir.

    Args:
        cifrada: Si la raíz cifrada es la que el asistente está poniendo ahora;
            si no, se mira la de `agente.json`.
    """
    if not (cifrada or equipo.leer_ajustes().cifradas):
        return False
    return penwatch.installed_veracrypt() is None


def conseguir_veracrypt(progreso=None) -> Path:
    """Devuelve la carpeta con el VeraCrypt fijado para este equipo, comprobado.

    Es el Portable en Windows y el AppImage en Linux, de la caché del
    instalador, dejado a mano o descargado. Es un punto de indirección para los
    tests.
    """
    return veracrypt_bin.para_este_equipo(progreso)


def poner_veracrypt(progreso=None) -> Path:
    """Pone el VeraCrypt del agente en `veracrypt/<versión fijada>/`.

    Devuelve la carpeta. Va en una carpeta por versión, como el rclone: la de
    antes puede tener su driver cargado (en modo portátil, con un NTFS
    escribible montado, se queda así hasta reiniciar) y no se toca. Se copia al
    lado, se comprueba contra el sello y se pone con un `os.replace`; una que
    ya está y cuadra no se vuelve a copiar.

    Raises:
        InstallError: Si la copia no cuadra con su sello o no se puede poner.
    """
    destino = equipo.dir_veracrypt() / pins.VERACRYPT_VERSION
    if components.veracrypt_integro(destino, version=pins.VERACRYPT_VERSION):
        return destino
    origen = conseguir_veracrypt(progreso)
    nombres = [components.VERACRYPT_STAMP,
               *components.veracrypt_ficheros(
                   (origen / components.VERACRYPT_STAMP).read_text(encoding="utf-8"))]
    trabajo = destino.with_name(f".{destino.name}.nuevo-{os.getpid()}")
    viejo = destino.with_name(f".{destino.name}.viejo-{os.getpid()}")
    shutil.rmtree(trabajo, ignore_errors=True)
    if progreso:
        progreso("Copiando VeraCrypt para el agente…")
    try:
        trabajo.mkdir(parents=True)
        for nombre in nombres:
            shutil.copy2(origen / nombre, trabajo / nombre)
            if not IS_WIN and nombre != components.VERACRYPT_STAMP:
                (trabajo / nombre).chmod(0o755)
        if not components.veracrypt_integro(trabajo, version=pins.VERACRYPT_VERSION):
            raise InstallError(f"La copia de VeraCrypt en {trabajo} no cuadra con su "
                               f"sello. No se ha puesto nada.")
        if destino.exists():
            os.replace(destino, viejo)
        os.replace(trabajo, destino)
    except OSError as e:
        shutil.rmtree(trabajo, ignore_errors=True)
        raise InstallError(f"No he podido poner el VeraCrypt del agente en {destino}: "
                           f"{e}") from e
    except InstallError:
        shutil.rmtree(trabajo, ignore_errors=True)
        raise
    shutil.rmtree(viejo, ignore_errors=True)
    return destino


def preparar(progreso=None, origen: Path | None = None,
             cifrada: bool = False) -> Preparado:
    """Hace el paso «Instalación» del recorrido del equipo.

    Código, Python, rclone y, si hace falta, VeraCrypt.

    El VeraCrypt del agente solo va si atiende una raíz cifrada sin VeraCrypt
    instalado (`quiere_veracrypt()`).
    """
    codigo = copiar_codigo(origen)
    python, sello = poner_runtime(progreso)
    rclone = poner_rclone(progreso)
    vc = poner_veracrypt(progreso) if quiere_veracrypt(cifrada) else None
    return Preparado(codigo, python, sello, rclone, vc)


def asegurar_veracrypt(prep: Preparado, progreso=None) -> Preparado:
    """Devuelve el agente ya instalado y de esta versión.

    Con su VeraCrypt si ahora le hace falta.

    Pasa cuando el asistente le añade una raíz cifrada sin reinstalarlo. Lo
    apunta en `instalacion.json`, que el agente lee cada vez que lo necesita:
    no hay que pararlo.
    """
    if prep.veracrypt is not None or not quiere_veracrypt(True):
        return prep
    nuevo = replace(prep, veracrypt=poner_veracrypt(progreso))
    datos = instalado() or {}
    datos["veracrypt"] = str(nuevo.veracrypt)
    store.write_json(equipo.instalacion_json(), datos)
    return nuevo


def _instalacion(prep: Preparado) -> dict:
    """Devuelve lo que se apunta en `instalacion.json`: dónde está cada cosa."""
    return {"version": version(), "codigo": str(prep.codigo), "python": str(prep.python),
            "runtime": penwatch.stamp_id(prep.sello),
            **({"rclone": str(prep.rclone)} if prep.rclone else {}),
            **({"veracrypt": str(prep.veracrypt)} if prep.veracrypt else {}),
            "instalado": store.stamp()}


@dataclass(frozen=True)
class Candidata:
    """Una unidad que el paso «Unidades» ofrece.

    Args:
        id: El id de la unidad.
        nombre: Su nombre, o vacío.
        modo: El que se le propone.
        origen: De dónde se sabe de ella, para decirlo.
    """
    id: str
    nombre: str
    modo: str
    origen: str


def de_penwatch() -> tuple[str, str] | None:
    """Devuelve `(id, modo)` de la unidad que atiende el penwatch de este equipo.

    O `None`.
    """
    cfg = penwatch.read_json(penwatch.CONFIG_FILE)
    uid = cfg.get("device_id")
    if not isinstance(uid, str) or not uid:
        return None
    modo = cfg.get("mode") if cfg.get("mode") in equipo.MODOS else equipo.UI
    return uid, modo


def enchufadas() -> list[tuple[str, str]]:
    """Devuelve `(id, nombre)` de las unidades prdrive enchufadas y abiertas.

    Solo se leen su fichero de control y su `state/fleet.json`.
    """
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
    """Devuelve las unidades que el paso «Unidades» ofrece, sin red.

    Son las que el agente ya tiene en su lista, la de penwatch y las
    enchufadas. El resto llegará con el aviso de «unidad nueva».
    """
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
    """Aplica lo elegido en «Unidades» y la raíz del equipo del asistente.

    Sin `agente.json` se escribe de una vez. Con él, el agente ya es dueño de
    su configuración y se le pide por el buzón: una unidad nueva entra con su
    modo (`PIDE_MODO`), la raíz con `PIDE_RAIZ` (con su contenedor si va
    cifrada), y el plazo y `pedir_al_iniciar` son `PIDE_AJUSTE`.

    Args:
        elegidas: `{id: (modo, nombre)}`.
        espera: Plazo para contestar «¿Atenderla?».
        raiz: La raíz del equipo, una `Unidad` con `ruta`.
        pedir_al_iniciar: `None` es «no lo ha preguntado nadie»: se deja como
            esté.

    Returns:
        Qué se ha hecho, en una frase.

    Raises:
        InstallError: Si no se puede escribir `agente.json`.
    """
    if not equipo.ajustes_json().exists():
        aj = equipo.Ajustes(espera_unidad_nueva=espera,
                            pedir_al_iniciar=True if pedir_al_iniciar is None
                            else pedir_al_iniciar)
        for uid, (modo, nombre) in elegidas.items():
            aj = aj.con_unidad(equipo.Unidad(uid, modo, nombre))
        if raiz is not None:
            aj = aj.con_unidad(raiz)
        aj = equipo.desde_dict(equipo.a_dict(aj))  # saneado, como al leerlo
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
    """Indica si hay en el buzón del agente una petición sin leer de añadir esa raíz.

    Es lo que la verificación del asistente acepta como «ya está en camino».
    """
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


def quitar_penwatch() -> list[str]:
    """Desinstala penwatch de este equipo, que el agente sustituye, y lo dice.

    Lo que vigilaba ya ha pasado a la lista del agente (`candidatas()`).
    """
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
    """Registra el agente para que arranque al iniciar sesión.

    En Windows es la tarea por usuario de penwatch, con sus trampas resueltas.
    En Linux, autostart XDG y no una unidad systemd, porque los avisos, la
    pregunta de «unidad nueva» y la contraseña de VeraCrypt necesitan la sesión
    gráfica y `enable-linger` no la da.

    Raises:
        InstallError: Si no se puede registrar.
    """
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
    """Quita el registro de arranque del agente y dice qué había."""
    if IS_WIN:
        res = penwatch.run_quiet(["schtasks", "/Delete", "/TN", TAREA, "/F"])
        return (f"Tarea '{TAREA}' eliminada." if res.returncode == 0
                else f"No había tarea '{TAREA}'.")
    destino = autostart_file()
    if destino.exists():
        destino.unlink(missing_ok=True)
        return f"Autostart {destino} eliminado."
    return "No había autostart."


def acceso_menu() -> Path:
    """Devuelve dónde va el acceso «prdrive» del menú del sistema.

    Es función para que los tests lo lleven a un temporal, como
    `autostart_file()`.
    """
    if IS_WIN:
        base = os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming")
        return (Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
                / f"{APP_NAME}.lnk")
    base = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
    return Path(base) / "applications" / f"{APP_NAME}.desktop"


COMENTARIO_MENU = f"La ventana de {APP_NAME} de este equipo: sus parejas y su estado."
"""Comentario del acceso del menú cuando hay una raíz del equipo."""
COMENTARIO_SOLO = f"El agente de {APP_NAME}: lo arranca si no está, y dice cómo va."
"""Comentario del acceso del menú de la instalación «solo agente»."""


def menu_desktop(args: list[str], icono: Path | None = None,
                 comentario: str = COMENTARIO_MENU) -> str:
    """Devuelve la entrada del menú de aplicaciones (Desktop Entry Specification).

    Es visible, a diferencia del autostart, y lleva el `Exec=` escapado como
    aquel.
    """
    return ("[Desktop Entry]\nType=Application\n"
            f"Name={APP_NAME}\n"
            f"Comment={comentario}\n"
            f"Exec={penwatch.desktop_exec(args)}\n"
            + (f"Icon={icono}\n" if icono else "")
            + "Terminal=false\nCategories=Utility;\n")


def crear_lnk(destino: Path, objetivo: str, argumentos: str, carpeta: str,
              icono: str, descripcion: str) -> None:
    """Crea un acceso directo `.lnk` de Windows, con `IShellLinkW` e `IPersistFile`.

    Usa COM por vtabla, como `IShellItem2` en `install/crypto.py`: la
    biblioteca estándar no trae COM y el proyecto no admite dependencias. Es un
    punto de indirección (los tests lo sustituyen) y no está probado en un
    Windows real.

    Huecos de la vtabla, detrás de los 3 de `IUnknown`, en el orden de
    `ShObjIdl_core.h`: `IShellLinkW` 7 `SetDescription`, 9
    `SetWorkingDirectory`, 11 `SetArguments`, 17 `SetIconLocation`, 20
    `SetPath`; `IPersistFile` (detrás de `IPersist::GetClassID`, el 3) 6
    `Save`.

    Raises:
        OSError: Si falla alguna llamada COM.
    """
    import ctypes
    from ctypes import POINTER, byref, c_int, c_long, c_void_p, c_wchar_p
    from ctypes.wintypes import ULONG

    class GUID(ctypes.Structure):
        """Estructura `GUID` de Windows."""
        _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
                    ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]

    ole32 = ctypes.windll.ole32

    def guid(texto: str) -> GUID:
        """Convierte un texto `{...}` en un `GUID`."""
        g = GUID()
        if ole32.CLSIDFromString(c_wchar_p(texto), byref(g)) < 0:
            raise OSError(f"GUID ilegible: {texto}")
        return g

    def vtabla(objeto: c_void_p):
        """Devuelve la vtabla de un objeto COM."""
        return ctypes.cast(objeto, POINTER(POINTER(c_void_p))).contents

    def soltar(objeto: c_void_p) -> None:
        """Libera un objeto COM (`IUnknown::Release`)."""
        ctypes.WINFUNCTYPE(ULONG, c_void_p)(vtabla(objeto)[2])(objeto)

    def comprobar(hr: int, que: str) -> None:
        """Lanza `OSError` si el `HRESULT` es un error."""
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


def quiere_menu(con_raiz: bool) -> bool:
    """Indica si este equipo lleva el acceso «prdrive» del menú.

    Con una raíz del equipo, siempre: es su ventana. En Linux, además, siempre:
    donde el escritorio no tiene bandeja (GNOME sin la extensión AppIndicator)
    es lo que arranca el agente o dice cómo va. En Windows la bandeja no falta.
    """
    return con_raiz or not IS_WIN


def poner_menu(prep: Preparado, con_raiz: bool | None = None) -> str:
    """Pone el acceso «prdrive» del menú (`agente.py abrir`), con el Python del agente.

    Abre la ventana de la raíz del equipo; sin raíz, arranca el agente o dice
    cómo va. Se reescribe en cada instalación: apunta a la versión del código,
    que cambia.

    Returns:
        Qué se ha hecho, en una frase.
    """
    if con_raiz is None:
        con_raiz = bool(equipo.leer_ajustes().raices)
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
                icono if icono.is_file() else None,
                COMENTARIO_MENU if con_raiz else COMENTARIO_SOLO), encoding="utf-8")
    except (OSError, AttributeError) as e:
        return (f"No he podido crear el acceso del menú ({e}): la ventana se abre con "
                f"«{prep.python} {prep.codigo / 'agente.py'} abrir».")
    if con_raiz:
        return f"Acceso «{APP_NAME}» en el menú del sistema: abre la ventana de este equipo."
    return (f"Acceso «{APP_NAME}» en el menú de aplicaciones: arranca el agente, o dice "
            f"cómo va (donde el escritorio no tiene bandeja).")


def quitar_menu() -> str | None:
    """Quita el acceso del menú y dice qué ha hecho.

    Returns:
        La frase, o `None` si no había acceso.
    """
    destino = acceso_menu()
    if not destino.exists():
        return None
    try:
        destino.unlink()
    except OSError as e:
        return f"No he podido borrar {destino}: {e}"
    return f"Acceso del menú {destino} eliminado."


def lanzar(args: list[str], **kwargs):
    """Arranca el agente sin esperar a la sesión siguiente.

    Es un punto de indirección.
    """
    return subprocess.Popen(args, **kwargs)


def arrancar(prep: Preparado) -> str:
    """Arranca el agente ya, sin esperar a la sesión siguiente, y dice cómo ha ido."""
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


def matar_arbol(pid: int) -> None:
    """Termina un proceso Y sus hijos.

    Una pasada es `sync.py` más su rclone y matar solo el primero deja el
    segundo escribiendo. En POSIX la pasada es jefa de su propia sesión (el
    agente la lanza con `start_new_session`), así que su grupo es su pid; en
    Windows `taskkill /T` sigue el árbol. Es de módulo para que los tests lo
    sustituyan.
    """
    try:
        if IS_WIN:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           capture_output=True, creationflags=penwatch.CREATE_NO_WINDOW)
            return
        import signal
        try:
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            os.kill(pid, signal.SIGTERM)    # no era jefe de grupo: al menos él
    except (OSError, subprocess.SubprocessError):
        pass


def decirlo(progreso):
    """Devuelve el `avance` de `parar_agente()` para quien solo sabe decir líneas.

    (`progreso(texto)`, un `print`).

    Cada texto se dice una vez, no dos veces por segundo.
    """
    if progreso is None:
        return None
    dicho: list[str] = []

    def avance(_fraccion: float, texto: str) -> None:
        """Dice el texto si no es el último que se dijo."""
        if not dicho or dicho[-1] != texto:
            dicho.append(texto)
            progreso(texto)
    return avance


def parar_agente(avance=None) -> str | None:
    """Pide al agente que termine y espera a que se vaya él Y su pasada.

    El agente acaba la pareja en curso antes de irse, y lo que venga después
    (el código nuevo, un agente nuevo, borrar su Python) no puede pasarle por
    encima. Se espera `ESPERA_PASADA` con una pasada en marcha, diciéndolo por
    `avance(fracción, texto)` si se da; sin pasada, `PARAR_ESPERA`. Pasado el
    plazo se corta: primero el agente (que no vea acabar la pasada, la cuente
    como fallo y borre su registro) y luego la pasada con su rclone
    (`matar_arbol()`). Una bisync cortada deja su `.lck`, que caduca solo en
    dos minutos: se apunta el corte (`equipo.apuntar_corte()`) y el agente que
    venga deja esa pareja hasta entonces en vez de fallar contra él.

    Returns:
        Qué ha pasado, o `None` si no había nada en marcha.
    """
    vivo = equipo.agente_vivo()
    pasada = equipo.pasada_viva()
    if vivo is None and pasada is None:
        return None
    pid = int((vivo or {}).get("pid", -1))
    if vivo is not None:
        equipo.pedir({"pide": equipo.PIDE_PARAR})
    inicio = time.monotonic()
    esperado = False
    sin_pasada = None       # desde cuándo no hay pasada: `PARAR_ESPERA` cuenta desde ahí
    while True:
        vivo, pasada = equipo.agente_vivo(), equipo.pasada_viva()
        if vivo is None and pasada is None:
            break
        ahora = time.monotonic()
        pasado = ahora - inicio
        if pasada is None:
            # Desde que la pasada acabó y no desde que se empezó a esperar:
            # tras una pasada larga el agente aún necesita unos segundos para
            # apuntarla y soltar el lock, y contar el total lo cortaba en
            # cuanto ella terminaba (visto en real: una pasada de 5 min,
            # cortado a los 2 s).
            sin_pasada = ahora if sin_pasada is None else sin_pasada
            if ahora - sin_pasada >= PARAR_ESPERA:
                break
        else:
            sin_pasada = None
            if pasado >= ESPERA_PASADA:
                break
        if pasada is not None:
            esperado = True
            if avance is not None:
                minutos = max(1, round((ESPERA_PASADA - pasado) / 60))
                avance(pasado / ESPERA_PASADA,
                       f"Esperando a que acabe la pasada de «{pasada.get('pareja')}» en "
                       f"{pasada.get('unidad')}; como mucho {minutos} min más.")
        time.sleep(0.5)
    quien = f"Agente anterior (pid {pid})" if pid > 0 else "El agente anterior"
    if vivo is None and pasada is None:
        return f"{quien} detenido" + (" tras acabar su pasada." if esperado else ".")
    partes = []
    if vivo is not None:
        penwatch.kill_pid(pid)
        partes.append(f"{quien} terminado a la fuerza.")
    if pasada is not None:
        try:
            matar_arbol(int(pasada.get("pid")))
        except (TypeError, ValueError):
            pass
        equipo.apuntar_corte(pasada)
        partes.append(f"La pasada de «{pasada.get('pareja')}» en {pasada.get('unidad')} "
                      f"no acababa en {ESPERA_PASADA / 60:g} min y se ha cortado; el "
                      f"agente la retoma en unos minutos, cuando caduque su bloqueo. "
                      f"Si copiaba un fichero grande, puede quedar a medias como "
                      f"«….partial» en uno de los lados, y la próxima pasada lo "
                      f"sincroniza como uno más: bórralo en cualquiera de los dos.")
    return " ".join(partes)


def _runtime_de(interprete: Path | str) -> str | None:
    """Devuelve la carpeta de `runtime/` a la que pertenece ese intérprete, o `None`."""
    try:
        rel = Path(os.path.relpath(Path(interprete).resolve(),
                                   equipo.dir_runtimes().resolve()))
    except (OSError, ValueError):
        return None
    return None if not rel.parts or rel.parts[0] == ".." else rel.parts[0]


def podar(prep: Preparado) -> None:
    """Borra las versiones viejas de código y de Python que ya no usa nadie.

    Lo que no se pueda borrar (un Python en uso) se queda para la próxima vez.
    El Python con el que corre ESTE proceso no se toca nunca, aunque sea el
    viejo: «Actualizar» se lanza con el Python del agente, y borrarle a medias
    su biblioteca estándar a un proceso vivo es tumbarlo en su próximo import.
    Se recogerá en la siguiente instalación, como hace penwatch
    (`prune_runtimes()`).
    """
    guardar_py = {_runtime_de(prep.python), _runtime_de(sys.executable)} - {None}
    # El rclone de antes puede estar corriendo en una pasada que aún no acabó,
    # si se cortó; en Windows no se deja borrar y queda para la próxima.
    podables = [(equipo.dir_codigo(), {prep.codigo.name}),
                (equipo.dir_runtimes(), guardar_py)]
    if prep.rclone is not None:
        podables.append((equipo.dir_rclone(), {prep.rclone.parent.name}))
    # El VeraCrypt de antes puede tener su driver cargado (hasta reiniciar): lo
    # que no se deje borrar se queda para la próxima.
    podables.append((equipo.dir_veracrypt(),
                     {prep.veracrypt.name} if prep.veracrypt is not None else set()))
    for base, guardar in podables:
        try:
            hijos = list(base.iterdir())
        except OSError:
            continue
        for hijo in hijos:
            if hijo.name not in guardar:
                shutil.rmtree(hijo, ignore_errors=True)


def activar(prep: Preparado, elegidas: dict[str, tuple[str, str]], espera: float,
            arrancar_ya: bool = True, raiz: equipo.Unidad | None = None,
            pedir_al_iniciar: bool | None = None, avance=None) -> list[str]:
    """Hace los pasos «Unidades» y «Arranque» de una vez.

    Son la configuración (con la raíz del equipo, si la hay), penwatch fuera,
    el registro, el acceso del menú, `instalacion.json`, las versiones viejas
    fuera y el arranque.

    Args:
        avance: El de `parar_agente()`.
    """
    msgs = []
    parado = parar_agente(avance)
    if parado:
        msgs.append(parado)
    msgs.append(aplicar_unidades(elegidas, espera, raiz, pedir_al_iniciar))
    msgs += quitar_penwatch()
    msgs.append(registrar(prep))
    # El acceso del menú: con una raíz del equipo es su ventana; sin ella, en
    # Linux, hace las veces de la bandeja donde no la hay.
    con_raiz = raiz is not None or bool(equipo.leer_ajustes().raices)
    if quiere_menu(con_raiz):
        msgs.append(poner_menu(prep, con_raiz))
    store.write_json(equipo.instalacion_json(), _instalacion(prep))
    podar(prep)
    if arrancar_ya:
        msgs.append(arrancar(prep))
    return msgs


def instalado_prep() -> Preparado | None:
    """Devuelve el agente que ya está instalado, como si se acabara de preparar.

    Sale de `instalacion.json` (su código y su Python).

    Returns:
        Lo instalado, o `None` si no hay o falta algo.
    """
    datos = instalado()
    if not datos:
        return None
    codigo, python = datos.get("codigo"), datos.get("python")
    if not isinstance(codigo, str) or not isinstance(python, str):
        return None
    try:
        if not Path(python).is_file():
            return None
    except OSError:
        return None
    rclone = datos.get("rclone")
    try:
        if not isinstance(rclone, str) or not Path(rclone).is_file():
            return None             # de antes de que el agente llevara el suyo
    except OSError:
        return None
    vc = datos.get("veracrypt")
    return Preparado(Path(codigo), Path(python), str(datos.get("runtime") or ""),
                     Path(rclone), Path(vc) if isinstance(vc, str) and vc else None)


def misma_version() -> bool:
    """Indica si el agente instalado es de la versión que trae este instalador.

    Entonces volver a pasar el asistente no lo reinstala (sección 7 del
    diseño): se le pide lo nuevo por su buzón y ya.
    """
    datos = instalado()
    return bool(datos) and datos.get("version") == version() and \
        instalado_prep() is not None


def anadir(elegidas: dict[str, tuple[str, str]], espera: float,
           raiz: equipo.Unidad | None = None,
           pedir_al_iniciar: bool | None = None) -> list[str]:
    """Hace «Unidades» y «Arranque» con el agente ya instalado y de esta versión.

    No se para, ni se registra, ni se copia nada. Lo elegido se le PIDE por su
    buzón (`aplicar_unidades`), que es como se añade una raíz a un agente ya
    instalado. Si con esto el equipo estrena raíz se pone el acceso del menú, y
    si el agente no está en marcha se arranca para que lo lea ya.

    Raises:
        InstallError: Si no hay un agente instalado.
    """
    prep = instalado_prep()
    if prep is None:
        raise InstallError("No hay un agente instalado del que fiarse: instálalo.")
    msgs = [aplicar_unidades(elegidas, espera, raiz, pedir_al_iniciar)]
    msgs += quitar_penwatch()
    con_raiz = raiz is not None or bool(equipo.leer_ajustes().raices)
    if quiere_menu(con_raiz) and (raiz is not None or not acceso_menu().exists()):
        msgs.append(poner_menu(prep, con_raiz))
    if equipo.agente_vivo() is None:
        msgs.append(arrancar(prep))
    else:
        msgs.append("El agente sigue en marcha: lo lee de su buzón en unos segundos.")
    return msgs


def actualizar_raices(origen: Path | None = None) -> list[str]:
    """Pone el código de las raíces de este equipo a la versión del instalador.

    Es lo mismo que `--update` en una unidad (`deploy.deploy_code()`, fichero a
    fichero, sin tocar configuración, claves, estado ni rclone). Una raíz
    cifrada bloqueada no se puede tocar: se queda como está y su ventana
    ofrecerá la versión nueva al desbloquearla (sección 8 del diseño).
    """
    from . import deploy
    msgs = []
    for u in equipo.leer_ajustes().raices.values():
        raiz = Path(u.ruta)
        nombre = u.nombre or str(raiz)
        # Abierta es VERLA abierta, como en el agente: en Windows una letra con
        # Abierta es VERLA abierta, como en el agente: en Windows una letra con
        # el id al lado de un `.hc` libre es el fantasma que sirve lo que tenía
        # en caché, y escribir ahí daría la raíz por actualizada sin haberla
        # tocado.
        fantasma = u.cifrada and _presente(raiz) and \
            vestibulo.retenido(u.contenedor) is False
        if fantasma or not _presente(raiz):
            msgs.append(f"{nombre}: " + ("bloqueada; su ventana ofrecerá la versión "
                                         "nueva al desbloquearla." if u.cifrada else
                                         f"no está en {raiz}; no se actualiza."))
            continue
        try:
            deploy.deploy_code(raiz, origen=origen)
            pintar(deploy.app_dir(raiz))
        except (OSError, InstallError) as e:
            msgs.append(f"{nombre}: no he podido actualizar su código: {e}")
            continue
        msgs.append(f"{nombre}: su código, a la versión {version()}.")
    return msgs


def actualizar(progreso=None, origen: Path | None = None) -> list[str]:
    """Pone la versión que trae este instalador en lugar de la instalada.

    (`--update-agente`).

    Lo lanza «Actualizar» de la bandeja (`agente.py actualizar`) DESDE el zip
    descargado, como `--update` en una unidad: la versión nueva se instala a sí
    misma. Nunca se cambia en sitio lo que corre: el código nuevo y, si cambia,
    el Python nuevo van a su carpeta al lado; se para el agente, se vuelve a
    registrar (la tarea apunta a la versión), se cambia `instalacion.json`, se
    ponen al día las raíces del equipo abiertas, se recoge lo viejo y se
    arranca. `agente.json` no se toca: su lista y sus ajustes siguen.

    Raises:
        InstallError: Si no hay agente instalado.
    """
    if instalado() is None:
        raise InstallError("En este equipo no hay ningún agente instalado: no hay "
                           "nada que actualizar. Instálalo con el asistente.")
    prep = preparar(progreso, origen)
    msgs = [f"Código del agente en {prep.codigo}", f"Su Python: {prep.python}"]
    parado = parar_agente(decirlo(progreso))
    if parado:
        msgs.append(parado)
    msgs.append(registrar(prep))
    con_raiz = bool(equipo.leer_ajustes().raices)
    if quiere_menu(con_raiz):
        msgs.append(poner_menu(prep, con_raiz))
    store.write_json(equipo.instalacion_json(), _instalacion(prep))
    msgs += actualizar_raices(origen)
    podar(prep)
    msgs.append(arrancar(prep))
    return msgs


def instalar(elegidas: dict[str, tuple[str, str]] | None = None,
             espera: float = equipo.ESPERA_UNIDAD_NUEVA, progreso=None) -> list[str]:
    """Lo hace todo de una vez, sin asistente (`prdrive-install.py --instalar-agente`).

    Sin unidades elegidas, las que `candidatas()` propone, con su modo.
    """
    prep = preparar(progreso)
    if elegidas is None:
        elegidas = {c.id: (c.modo, c.nombre) for c in candidatas()}
    return [f"Código del agente en {prep.codigo}", f"Su Python: {prep.python}",
            *activar(prep, elegidas, espera)]


def desinstalar(progreso=None) -> list[str]:
    """Quita el registro, el acceso del menú, el agente y su Python.

    Nunca toca una unidad ni la raíz del equipo: lo que tuviera a medias el
    agente sigue en ellas, como lo dejó (y la pasada en marcha se espera,
    `parar_agente()`).
    """
    msgs = []
    parado = parar_agente(decirlo(progreso))
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
        # Nunca se borra: tiene las carpetas del usuario y la clave. Se dice
        # dónde está para que no parezca que se ha ido con el agente.
        if u.cifrada:
            # Tampoco se cierra: si está abierta es porque alguien la usa, y
            # desmontar con algo abierto dentro es decisión de la persona.
            abierta = _presente(Path(u.ruta))
            instalado_vc = penwatch.installed_veracrypt() is not None
            cerrar = ("ciérrala desde VeraCrypt cuando quieras" if instalado_vc else
                      "se cierra sola al reiniciar el equipo (el VeraCrypt que la "
                      "abría era el del agente, y se ha ido con él)")
            msgs.append(f"La raíz cifrada de este equipo sigue en {u.contenedor}"
                        + (f", y ABIERTA en {u.ruta}: {cerrar}." if abierta else ".")
                        + ("" if instalado_vc else
                           " Para volver a abrirla hace falta VeraCrypt: vuelve a "
                           "instalar el agente o instala VeraCrypt.")
                        + " Bórrala a mano si ya no la quieres.")
            continue
        msgs.append(f"La raíz de este equipo sigue en {u.ruta}, con sus carpetas y su "
                    f".prdrive/ (la clave incluida): bórrala a mano si ya no la quieres.")
    return msgs


def _presente(raiz: Path) -> bool:
    """Indica si esa raíz tiene su fichero de control a la vista."""
    try:
        return (raiz / penwatch.CONTROL_FILE).is_file()
    except OSError:
        return False


def instalado() -> dict | None:
    """Devuelve lo que dice `instalacion.json`, si hay un agente instalado."""
    return equipo.leer_instalacion() if equipo.instalado() else None
