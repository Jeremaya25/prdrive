#!/usr/bin/env python3
r"""Lo que el agente deja en este equipo fuera de su carpeta, y cómo se quita todo.

Dentro de `equipo.DIR` va todo lo suyo: código, Python, configuración y diario.
Fuera deja lo justo para arrancar y para poder quitarlo, siempre de la persona
(`HKEY_CURRENT_USER`, su carpeta personal) y sin pedir administrador:

- **El arranque al iniciar sesión.** En Windows, el valor `prdrive` de
  `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`: Windows lo enseña en
  «Aplicaciones de arranque» (Configuración y Administrador de tareas) y deja
  apagarlo; lo apagado lo apunta Windows en `...\Explorer\StartupApproved\Run`
  y se respeta al actualizar, porque eso no se toca al registrar. No es una
  tarea programada: la de las versiones que arrancaban así se borra al
  registrar (`quitar_tarea_vieja()`). En Linux, un autostart XDG y no una
  unidad systemd: los avisos, la pregunta de unidad nueva y la contraseña de
  VeraCrypt necesitan la sesión gráfica.
- **Su ficha en «Aplicaciones instaladas»** (Windows): la clave
  `HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\prdrive`, cuyo
  «Desinstalar» abre `agente.py desinstalar`.
- **El acceso «prdrive» del menú** (`acceso_menu()`), cuando lo lleva.

Desinstalar (`plan_desinstalar()`, que se enseña antes de hacer nada) quita
eso, lo que el agente dejó en el registro por las unidades (el nombre y el
icono de la letra de un volumen VeraCrypt, las claves del navegador que
apuntan a un llavero que ya no está), la caché del usuario (Linux) y la
carpeta entera. Nunca toca una unidad ni la raíz del equipo, que tiene las
carpetas de la persona: dice dónde se queda.

La carpeta no se puede borrar desde el Python que vive en ella, que es justo
el que lanza el «Desinstalar» de Windows: se borra al salir (`rematar()`), con
un `cmd` suelto que espera a que este proceso termine. Si aun así queda algo
en uso (el driver de VeraCrypt sigue cargado hasta reiniciar), una entrada de
`RunOnce` lo borra al siguiente inicio de sesión, y Windows quita esa entrada
al usarla.

Las llamadas al sistema son puntos de indirección que los tests sustituyen:
`ejecutar()`, `lanzar()`, `lanzar_suelto()`, `limpiar_letras()` y
`limpiar_navegador()`, además de las de `common/registro.py`.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import APP_NAME, equipo, model, registro, store

IS_WIN = os.name == "nt"

APP_SUBDIR = f".{APP_NAME}"
"""La carpeta del programa en una raíz (la misma que `penwatch.APP_SUBDIR`)."""
NOMBRE = APP_NAME
"""El nombre del valor de arranque, de la ficha de «Aplicaciones instaladas» y de la tarea vieja."""
CLAVE_RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
"""Lo que Windows arranca al iniciar la sesión de la persona."""
CLAVE_APAGADO = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"
"""Donde Windows apunta que la persona ha apagado una aplicación de arranque."""
CLAVE_RUNONCE = r"Software\Microsoft\Windows\CurrentVersion\RunOnce"
"""Lo que Windows ejecuta una sola vez en el siguiente inicio de sesión, y luego olvida."""
CLAVE_FICHA = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_NAME}"
"""La ficha del agente en «Aplicaciones instaladas»."""
DESCRIPCION = (f"{APP_NAME} residente: sincroniza las unidades {APP_NAME} que se "
               f"enchufan en este equipo.")
"""Descripción con la que se registra el agente."""

PARAR_ESPERA = 12.0  # segundos
"""Lo que se espera a que el agente se vaya si no tiene pasada en marcha."""
ESPERA_PASADA = 600.0  # segundos
"""Lo que se espera a que acabe la pasada en marcha, antes de cortarla."""
ESPERA_AJENOS = 5.0  # segundos
"""Lo que se espera, con el agente ya parado, a que salgan los procesos que lanzó."""
REINTENTOS_BORRADO = 60
"""Vueltas de un segundo del `cmd` que borra la carpeta cuando este proceso sale."""

VARIABLES_DEL_CONGELADO = ("TCL_LIBRARY", "TK_LIBRARY", "TCLLIBPATH", "PYTHONHOME",
                           "PYTHONPATH")
"""Variables que deja el instalador compilado y que el Python del agente no debe heredar.

PyInstaller apunta Tcl y Tk a su carpeta temporal, que desaparece al cerrar el
asistente; con ellas, la primera ventana del agente buscaría allí su Tcl.
También las que empiezan por `_PYI_` o `_MEI` (`entorno_limpio()`).
"""
VARIABLES_DE_HIJO = (model.RCLONE_DEL_AGENTE, "PYTHONPYCACHEPREFIX")
"""Variables que el agente pone a sus hijos (`agente._opciones_hijo()`).

«Actualizar» arranca el agente nuevo desde un hijo del viejo, y el nuevo no
debe heredar el rclone ni la caché de `.pyc` del anterior: arranca como al
iniciar sesión.
"""

_PENDIENTE: Path | None = None
"""La carpeta del agente que `rematar()` tiene que terminar de borrar, si la hay."""


class DesinstalacionError(Exception):
    """No se ha podido desinstalar: el texto dice por qué y qué hacer."""


# --- dónde está cada cosa

def autostart_file() -> Path:
    """Devuelve el autostart XDG de Linux.

    Es función para que los tests lo lleven a un temporal.
    """
    base = os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
    return Path(base) / "autostart" / f"{APP_NAME}.desktop"


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


def cache_usuario() -> Path:
    """Devuelve la caché de prdrive en este usuario de Linux (`~/.cache/prdrive/`).

    Ahí van la copia ejecutable de rclone de una unidad exFAT y el KeePassXC
    extraído del llavero. Es función para que los tests la lleven a un temporal.
    """
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / APP_NAME


# --- las órdenes

def orden(python: str | Path, codigo: Path) -> list[str]:
    """Devuelve con qué se arranca el agente: su Python y su `agente.py run`."""
    return [str(python), str(codigo / "agente.py"), "run"]


def orden_desinstalar(python: str | Path, codigo: Path,
                      sin_preguntar: bool = False) -> list[str]:
    """Devuelve la orden del «Desinstalar» de «Aplicaciones instaladas».

    Args:
        sin_preguntar: Para la desinstalación silenciosa: no enseña nada antes.
    """
    return [str(python), str(codigo / "agente.py"), "desinstalar",
            *(["--si"] if sin_preguntar else [])]


def linea(args: list[str]) -> str:
    """Devuelve una orden como la línea que guardan `Run` y la ficha, citada para Windows."""
    return subprocess.list2cmdline([str(a) for a in args])


def ejecutar(orden_: list[str]) -> subprocess.CompletedProcess:
    """Ejecuta una orden del sistema sin consola y devuelve cómo ha ido.

    Si no se puede lanzar, el código es 127. Es un punto de indirección.
    """
    import penwatch
    return penwatch.run_quiet(orden_)


def entorno_limpio() -> dict[str, str]:
    """Devuelve el entorno de este proceso tal como lo tendría el agente al iniciar sesión.

    Sin `VARIABLES_DE_HIJO` y, desde un `.exe` de PyInstaller, sin
    `VARIABLES_DEL_CONGELADO`.
    """
    congelado = bool(getattr(sys, "frozen", False))
    return {k: v for k, v in os.environ.items()
            if k.upper() not in VARIABLES_DE_HIJO
            and not (congelado and (k.upper() in VARIABLES_DEL_CONGELADO
                                    or k.upper().startswith(("_PYI_", "_MEI"))))}


def lanzar(args: list[str], **kwargs):
    """Arranca el agente sin esperar a la sesión siguiente.

    Es un punto de indirección.
    """
    return subprocess.Popen(args, **kwargs)


# --- el arranque y la ficha

def registrar_arranque(python: Path, codigo: Path) -> list[str]:
    """Hace que el agente arranque al iniciar sesión y dice qué ha hecho.

    En Windows, el valor `NOMBRE` de `CLAVE_RUN`, y fuera la tarea programada
    de las versiones anteriores; si la persona lo apagó en «Aplicaciones de
    arranque», sigue apagado. En Linux, el autostart XDG.

    Raises:
        OSError: Si no se puede registrar.
    """
    if IS_WIN:
        registro.escribir(CLAVE_RUN, linea(orden(python, codigo)), NOMBRE)
        msgs = ["Arranca al iniciar sesión: está en «Aplicaciones de arranque» de "
                "Windows, que deja apagarlo."]
        vieja = quitar_tarea_vieja()
        return msgs + ([vieja] if vieja else [])
    import penwatch
    destino = autostart_file()
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(penwatch.autostart_desktop(APP_NAME, orden(python, codigo),
                                                  DESCRIPCION), encoding="utf-8")
    return [f"Autostart instalado en {destino}: arranca al iniciar el escritorio."]


def quitar_tarea_vieja() -> str | None:
    """Borra la tarea programada con la que arrancaba el agente antes, si la hay (Windows).

    Returns:
        La frase que lo dice, o `None` si no había ninguna.
    """
    if not IS_WIN:
        return None
    res = ejecutar(["schtasks", "/Delete", "/TN", NOMBRE, "/F"])
    return ("Quitada la tarea programada con la que arrancaba antes."
            if res.returncode == 0 else None)


def tamano_kb(carpeta: Path) -> int:
    """Devuelve lo que ocupa una carpeta, en KiB; lo que no se deja leer no cuenta."""
    total = 0
    for base, _dirs, ficheros in os.walk(carpeta):
        for nombre in ficheros:
            try:
                total += os.lstat(os.path.join(base, nombre)).st_size
            except OSError:
                pass
    return total // 1024


def registrar_ficha(python: Path, codigo: Path, version: str) -> str | None:
    """Pone o pone al día la ficha del agente en «Aplicaciones instaladas» (Windows).

    Su «Desinstalar» es `orden_desinstalar()` con el Python sin consola del
    agente, y el silencioso, lo mismo con `--si`. Se reescribe en cada
    instalación y actualización: el código cambia de carpeta con la versión.
    La fecha de instalación es la primera.

    Returns:
        La frase que lo dice, o `None` fuera de Windows.

    Raises:
        OSError: Si no se puede escribir.
    """
    if not IS_WIN:
        return None
    textos = {"DisplayName": APP_NAME,
              "DisplayVersion": version,
              "Comments": DESCRIPCION,
              "InstallLocation": str(equipo.DIR),
              "InstallDate": registro.leer(CLAVE_FICHA, "InstallDate")
              or time.strftime("%Y%m%d"),
              "UninstallString": linea(orden_desinstalar(python, codigo)),
              "QuietUninstallString": linea(orden_desinstalar(python, codigo,
                                                              sin_preguntar=True))}
    icono = codigo / "runsync.ico"
    if icono.is_file():
        textos["DisplayIcon"] = str(icono)
    else:
        registro.borrar_valor(CLAVE_FICHA, "DisplayIcon")
    for nombre, valor in textos.items():
        registro.escribir(CLAVE_FICHA, valor, nombre)
    for nombre, numero in (("NoModify", 1), ("NoRepair", 1),
                           ("EstimatedSize", tamano_kb(equipo.DIR))):
        registro.escribir_numero(CLAVE_FICHA, numero, nombre)
    return "En «Aplicaciones instaladas» de Windows: desde ahí se desinstala."


def arranque_registrado() -> bool:
    """Indica si el agente arrancará al iniciar sesión (el valor de `Run` o el autostart)."""
    if IS_WIN:
        return registro.leer(CLAVE_RUN, NOMBRE) is not None
    return autostart_file().is_file()


def ficha_registrada() -> bool:
    """Indica si el agente está en «Aplicaciones instaladas» con su «Desinstalar» (Windows)."""
    return registro.leer(CLAVE_FICHA, "UninstallString") is not None


def arrancar(python: Path, codigo: Path) -> str:
    """Arranca el agente ya, sin esperar a la sesión siguiente, y dice cómo ha ido.

    Suelto, sin consola, fuera de toda unidad (`equipo.DIR`) y con
    `entorno_limpio()`.
    """
    kwargs: dict = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
                    "stderr": subprocess.DEVNULL, "cwd": str(equipo.DIR),
                    "close_fds": True, "env": entorno_limpio()}
    if IS_WIN:
        import penwatch
        kwargs["creationflags"] = (penwatch.CREATE_NO_WINDOW
                                   | penwatch.CREATE_NEW_PROCESS_GROUP)
    else:
        kwargs["start_new_session"] = True
    try:
        lanzar(orden(python, codigo), **kwargs)
    except OSError as e:
        return f"No he podido arrancarlo ahora ({e}); arrancará al iniciar sesión."
    return "Agente arrancado."


# --- quitarlo

def quitar_registros() -> list[str]:
    """Quita el arranque al iniciar sesión, lo apagado, la tarea vieja y la ficha.

    Returns:
        Lo que se ha quitado, una frase por cosa; lo que no estaba no se dice.
    """
    msgs: list[str] = []
    if not IS_WIN:
        destino = autostart_file()
        if destino.exists():
            destino.unlink(missing_ok=True)
            msgs.append(f"Autostart {destino} eliminado.")
        return msgs
    for clave, frase in ((CLAVE_RUN, "Ya no arranca al iniciar sesión."),
                         (CLAVE_APAGADO, None)):
        try:
            if registro.borrar_valor(clave, NOMBRE) and frase:
                msgs.append(frase)
        except OSError as e:
            msgs.append(f"No he podido borrar {clave}\\{NOMBRE}: {e}")
    vieja = quitar_tarea_vieja()
    if vieja:
        msgs.append(vieja)
    try:
        if registro.borrar(CLAVE_FICHA):
            msgs.append("Fuera de «Aplicaciones instaladas».")
    except OSError as e:
        msgs.append(f"No he podido quitarlo de «Aplicaciones instaladas»: {e}")
    return msgs


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


def limpiar_letras() -> list[str]:
    """Quita el nombre y el icono que prdrive puso a letras de VeraCrypt, también abiertas (Windows).

    Es punto de indirección: los tests no tocan el registro.

    Returns:
        Las letras limpiadas.
    """
    from . import explorador
    return explorador.limpiar(APP_SUBDIR, todas=True)


def limpiar_navegador() -> tuple[int, list[str]]:
    """Quita lo del navegador que apunta a un KeePassXC de prdrive que ya no está.

    En Windows, las claves del registro: el navegador seguiría buscando
    KeePassXC en una letra muerta; si hay uno instalado, la clave vuelve a él
    (`keepassxc.cerrar_navegador(muertas=True)`). En Linux, los manifiestos de
    prdrive, si ya no queda abierto ningún KeePassXC extraído
    (`keepassxc.cerrar_navegador_linux(muertas=True)`). Lo de otros programas,
    y lo de un llavero que sigue abierto, no se toca. Punto de indirección: los
    tests no tocan el registro ni los navegadores.

    Returns:
        Cuántas claves o manifiestos ha tocado y lo que no ha podido hacer.
    """
    from . import keepassxc
    if not IS_WIN:
        manifiestos = keepassxc.plan_cerrar_navegador_linux(muertas=True)
        if not manifiestos:
            return 0, []
        return len(manifiestos), keepassxc.cerrar_navegador_linux(muertas=True)
    plan = keepassxc.plan_cerrar_navegador(carpeta_app=APP_SUBDIR, muertas=True)
    if not plan:
        return 0, []
    return len(plan), keepassxc.cerrar_navegador(carpeta_app=APP_SUBDIR, muertas=True)


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
            import penwatch
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


def parar_agente(avance=None, quien: str = "Agente anterior") -> str | None:
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

    Un «parar» que no se ha podido dejar en el buzón se vuelve a pedir en cada
    vuelta de la espera: sin él el agente no sabe que tiene que irse, lanza la
    pareja siguiente y acaba cortado a la fuerza con ella.

    Args:
        avance: `avance(fracción, texto)` mientras espera a la pasada.
        quien: Cómo se le nombra en lo que se dice: el anterior, al instalar
            uno nuevo; el agente, al desinstalar.

    Returns:
        Qué ha pasado, o `None` si no había nada en marcha.
    """
    import penwatch
    vivo = equipo.agente_vivo()
    pasada = equipo.pasada_viva()
    if vivo is None and pasada is None:
        return None
    pid = int((vivo or {}).get("pid", -1))
    pedido = vivo is None or equipo.pedir({"pide": equipo.PIDE_PARAR})
    inicio = time.monotonic()
    esperado = False
    sin_pasada = None       # desde cuándo no hay pasada: `PARAR_ESPERA` cuenta desde ahí
    while True:
        vivo, pasada = equipo.agente_vivo(), equipo.pasada_viva()
        if vivo is None and pasada is None:
            break
        if not pedido and vivo is not None:
            pedido = equipo.pedir({"pide": equipo.PIDE_PARAR})
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
    quien = f"{quien} (pid {pid})" if pid > 0 else quien
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


def procesos_ajenos() -> dict[int, str]:
    """Devuelve `{pid: ejecutable}` de lo que corre desde la carpeta del agente, menos este proceso.

    Con el agente parado suele ser la ventana de la raíz de este equipo, que
    corre con su Python.
    """
    yo = os.getpid()
    return {pid: exe for pid, exe in store.procesos_desde(equipo.DIR).items()
            if pid != yo}


def esperar_ajenos(espera: float | None = None) -> dict[int, str]:
    """Espera a que salga lo que corre desde la carpeta del agente y devuelve lo que queda.

    Al parar el agente, lo que lanzó (la pregunta de una unidad nueva, la
    ventana de los atajos) tarda un momento en irse.

    Args:
        espera: Segundos como mucho; sin ella, `ESPERA_AJENOS`.
    """
    limite = time.monotonic() + (ESPERA_AJENOS if espera is None else espera)
    while True:
        ajenos = procesos_ajenos()
        if not ajenos or time.monotonic() >= limite:
            return ajenos
        time.sleep(0.3)


def texto_ajenos(ajenos: dict[int, str]) -> str:
    """Devuelve por qué no se puede desinstalar con esos procesos abiertos, y qué hacer."""
    lista = ", ".join(f"{Path(exe).name} (pid {pid})" for pid, exe in sorted(ajenos.items()))
    return (f"El agente está parado, pero hay programas de {APP_NAME} abiertos que usan "
            f"su carpeta: {lista}. Suele ser la ventana de {APP_NAME} de este equipo. "
            f"Ciérralos y vuelve a desinstalar; mientras, no se ha quitado nada.")


def presente(raiz: Path) -> bool:
    """Indica si esa raíz tiene su fichero de control a la vista."""
    import penwatch
    try:
        return (raiz / penwatch.CONTROL_FILE).is_file()
    except OSError:
        return False


def raices_que_quedan() -> list[str]:
    """Dice dónde se quedan las raíces de este equipo, que desinstalar nunca borra.

    Tienen las carpetas de la persona y su clave. Una cifrada tampoco se
    cierra: si está abierta es porque alguien la usa, y desmontar con algo
    abierto dentro es decisión de la persona.
    """
    import penwatch
    msgs = []
    for u in equipo.leer_ajustes().raices.values():
        if u.cifrada:
            abierta = presente(Path(u.ruta))
            instalado_vc = penwatch.installed_veracrypt() is not None
            cerrar = ("ciérrala desde VeraCrypt cuando quieras" if instalado_vc else
                      "se cierra sola al reiniciar el equipo (el VeraCrypt que la "
                      "abría era el del agente, y se va con él)")
            msgs.append(f"La raíz cifrada de este equipo se queda en {u.contenedor}"
                        + (f", y ABIERTA en {u.ruta}: {cerrar}." if abierta else ".")
                        + ("" if instalado_vc else
                           " Para volver a abrirla hace falta VeraCrypt: vuelve a "
                           "instalar el agente o instala VeraCrypt.")
                        + " Bórrala a mano si ya no la quieres.")
            continue
        msgs.append(f"La raíz de este equipo se queda en {u.ruta}, con sus carpetas y su "
                    f"{APP_SUBDIR}/ (la clave incluida): bórrala a mano si ya no la quieres.")
    return msgs


def borrar_cache() -> list[str]:
    """Borra la caché de prdrive del usuario (Linux), si nada corre desde ella.

    Returns:
        Lo que ha pasado, o nada si no había caché.
    """
    if IS_WIN:
        return []
    carpeta = cache_usuario()
    if not carpeta.exists():
        return []
    if store.procesos_desde(carpeta):
        return [f"La caché {carpeta} sigue en uso (un KeePassXC abierto del llavero): "
                f"bórrala a mano cuando lo cierres."]
    shutil.rmtree(carpeta, ignore_errors=True)
    return [f"Eliminada la caché {carpeta}." if not carpeta.exists() else
            f"Queda algo en {carpeta}; se puede borrar a mano."]


def comspec() -> str:
    """Devuelve el intérprete de órdenes de Windows (`%ComSpec%`)."""
    return os.environ.get("COMSPEC") or os.environ.get("ComSpec") or "cmd.exe"


def orden_borrado(carpeta: Path) -> str:
    """Devuelve la línea de `cmd` que borra la carpeta del agente cuando quede libre (Windows).

    Mientras la carpeta exista, espera un segundo (`ping`) y lo intenta, hasta
    `REINTENTOS_BORRADO` veces: el primer intento ya llega con este proceso
    fuera, sin borrarle nada mientras sale. Al conseguirlo quita la entrada de
    `RunOnce` que la habría borrado al siguiente inicio de sesión. Con `/s`,
    `cmd` quita la primera y la última comilla tras `/c` y ejecuta el resto tal
    cual.
    """
    d = str(carpeta)
    return (f'"{comspec()}" /d /s /c "(for /l %i in (1,1,{REINTENTOS_BORRADO}) do '
            f'@(if exist "{d}" (ping -n 2 127.0.0.1 >nul & rmdir /s /q "{d}" 2>nul))) '
            f'& if not exist "{d}" '
            f'reg delete "HKCU\\{CLAVE_RUNONCE}" /v {NOMBRE} /f >nul 2>&1"')


def apuntar_borrado(carpeta: Path) -> bool:
    """Deja en `RunOnce` el borrado de la carpeta para el siguiente inicio de sesión (Windows).

    Windows quita la entrada al ejecutarla. Una ruta con `%` no se apunta:
    `cmd` la expandiría.

    Returns:
        Si ha quedado apuntado.
    """
    if not IS_WIN or "%" in str(carpeta):
        return False
    try:
        registro.escribir(CLAVE_RUNONCE,
                          f'"{comspec()}" /d /c rmdir /s /q "{carpeta}"', NOMBRE)
    except OSError:
        return False
    return True


def lanzar_suelto(linea_orden: str) -> None:
    """Lanza una línea de órdenes de Windows desligada de este proceso y sin ventana.

    Fuera del trabajo (job) de quien lanzó la desinstalación si se puede, para
    que no se la lleve al salir. Es un punto de indirección: los tests no
    lanzan nada.

    Raises:
        OSError: Si no se puede lanzar.
    """
    import penwatch
    banderas = penwatch.CREATE_NO_WINDOW | penwatch.CREATE_NEW_PROCESS_GROUP
    kwargs: dict = {"cwd": tempfile.gettempdir(), "stdin": subprocess.DEVNULL,
                    "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
                    "close_fds": True}
    try:
        subprocess.Popen(linea_orden, creationflags=banderas | 0x01000000, **kwargs)
    except OSError:                       # CREATE_BREAKAWAY_FROM_JOB no permitido
        subprocess.Popen(linea_orden, creationflags=banderas, **kwargs)


def borrar_carpeta() -> str:
    """Borra la carpeta del agente, o lo deja para `rematar()` si este proceso corre desde ella.

    Lo que siga en uso en Windows (el driver de VeraCrypt, cargado hasta
    reiniciar) se apunta en `RunOnce` (`apuntar_borrado()`).

    Returns:
        Lo que ha pasado, en una frase.
    """
    global _PENDIENTE
    carpeta = equipo.DIR
    if not carpeta.exists():
        return f"No había carpeta del agente en {carpeta}."
    from . import components
    if components.corre_desde(carpeta):
        _PENDIENTE = carpeta
        apuntar_borrado(carpeta)
        return f"Su carpeta, {carpeta}, se borra al cerrar esto."
    shutil.rmtree(carpeta, ignore_errors=True)
    if not carpeta.exists():
        return f"Eliminado {carpeta}."
    if apuntar_borrado(carpeta):
        return (f"Queda algo en uso en {carpeta}: se borra solo la próxima vez que "
                f"inicies sesión.")
    return f"Queda algo en {carpeta} (en uso); se puede borrar a mano."


def rematar() -> None:
    """Termina de borrar la carpeta del agente, si se dejó para el final.

    Es lo último que hace `agente.py desinstalar`, ya sin nada que importar:
    en Linux la borra; en Windows lanza `orden_borrado()`, que espera a que
    este proceso suelte su Python. Si no se puede lanzar, queda `RunOnce`.
    Nunca lanza.
    """
    global _PENDIENTE
    carpeta, _PENDIENTE = _PENDIENTE, None
    if carpeta is None:
        return
    if not IS_WIN:
        shutil.rmtree(carpeta, ignore_errors=True)
        return
    if "%" in str(carpeta):
        return
    try:
        lanzar_suelto(orden_borrado(carpeta))
    except OSError:
        pass


@dataclass
class Desinstalacion:
    """Lo que hará desinstalar el agente, para enseñarlo antes de hacerlo.

    Args:
        consequences: Una línea por cosa que se quita.
        warnings: Lo que se queda y conviene saber: las raíces de este equipo.
    """
    consequences: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def execute(self, avance=None) -> list[str]:
        """Desinstala (`desinstalar()`) y devuelve lo hecho.

        Raises:
            DesinstalacionError: Si algo de prdrive sigue usando su carpeta.
        """
        return desinstalar(avance)


def plan_desinstalar() -> Desinstalacion:
    """Devuelve lo que hará desinstalar el agente; todavía no se toca nada."""
    cons = []
    if equipo.agente_vivo() is not None:
        cons.append("Se para el agente. Si está sincronizando, antes acaba la pareja "
                    "en curso.")
    cons.append("Deja de arrancar al iniciar sesión"
                + (" y sale de «Aplicaciones instaladas»." if IS_WIN else "."))
    if acceso_menu().exists():
        cons.append(f"Se quita el acceso «{APP_NAME}» del menú.")
    cons.append(f"Se borra su carpeta, {equipo.DIR}: su código, su Python, su lista "
                f"de unidades y su diario.")
    if not IS_WIN and cache_usuario().exists():
        cons.append(f"Se borra su caché, {cache_usuario()}.")
    cons.append("Las unidades no se tocan. Al enchufarlas ya no se sincronizan solas "
                f"en este equipo: se abren desde la propia unidad.")
    return Desinstalacion(cons, raices_que_quedan())


def desinstalar(avance=None) -> list[str]:
    """Quita el agente de este equipo sin dejar rastro, y dice qué ha hecho.

    Para el agente (`parar_agente()`); si algo de prdrive sigue usando su
    carpeta, se detiene ahí sin quitar nada más. Si no, quita lo que dejó en el
    registro por las unidades, su arranque, su ficha, su acceso del menú, la
    caché y la carpeta (o la deja para `rematar()`). Nunca toca una unidad ni
    la raíz del equipo.

    Args:
        avance: El de `parar_agente()`.

    Raises:
        DesinstalacionError: Si algo de prdrive sigue usando su carpeta.
    """
    msgs = []
    parado = parar_agente(avance, quien="El agente")
    if parado:
        msgs.append(parado)
    ajenos = esperar_ajenos()
    if ajenos:
        raise DesinstalacionError(texto_ajenos(ajenos))
    quedan = raices_que_quedan()
    if IS_WIN:
        letras = limpiar_letras()
        if letras:
            msgs.append("Quitados el nombre y el icono que había puesto en "
                        + ", ".join(f"{letra}:" for letra in letras) + ".")
    try:
        tocadas, fallos = limpiar_navegador()
    except Exception as e:                              # noqa: BLE001 — no para lo demás
        tocadas, fallos = 0, [f"{type(e).__name__}: {e}"]
    if tocadas:
        msgs.append("El navegador ya no busca el KeePassXC de un llavero que no está.")
    if fallos:
        msgs.append(f"No he podido dejar como estaban las claves del navegador: {fallos[0]}")
    msgs += quitar_registros()
    menu = quitar_menu()
    if menu:
        msgs.append(menu)
    msgs += borrar_cache()
    msgs.append(borrar_carpeta())
    msgs.append("Las unidades no se han tocado.")
    return msgs + quedan
