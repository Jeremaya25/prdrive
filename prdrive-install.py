#!/usr/bin/env python3
"""Aprovisiona un dispositivo prdrive nuevo: argumentos y asistente.

Punto de entrada y poco más: aquí se miran los argumentos y se abre el
asistente. Lo que sabe hacer está repartido:

    install/              lo que decide y lo que toca disco o red (sin Tkinter)
    ui/tk_install.py      el asistente (solo dibujan él y ui/tk_crypto.py)

Lo que hace el asistente, en orden: pregunta la conexión con tu remoto (un
formulario, o importar un remote de tu `rclone.conf`), consigue un rclone, lee
el catálogo global de parejas, te deja elegir la unidad y cómo cifrarla
(VeraCrypt o BitLocker), **copia el programa** en su carpeta oculta
`.prdrive/`, escribe el `rclone.conf` y el `sync_config.toml` de ESE
dispositivo, crea sus carpetas, inicializa las parejas bisync y comprueba que
todo está.

Sin argumentos abre el asistente. Los demás modos hacen una cosa y salen:
- `--check`: rclone + conexión + catálogo.
- `--probe`: qué unidades ve.
- `--update RUTA`: sustituye el código de un dispositivo.
- `--update-components RUTA`: pone al día su rclone y su Python.
- `--instalar-agente`: instala el agente residente en ESTE equipo.
- `--desinstalar-agente`: lo quita (no toca ninguna unidad).
- `--update-agente`: pone el agente instalado a esta versión.
- `--autoprueba RUTA`: la prueba del `.exe` recién compilado, sin ventana, que
  la CI lee antes de publicarlo (no sale en `--help`).

`--update` es el otro extremo del aviso de versión nueva de la ventana: no
aprovisiona nada, solo repite el paso 5 sobre un dispositivo que ya existe. Y
no se ejecuta desde el dispositivo sino desde el zip que `common/update.py`
acaba de descargar y verificar: `install/` no viaja al dispositivo, así que
**la versión nueva es la que se instala a sí misma** y no hay una segunda copia
del manifiesto de qué se despliega que se pueda quedar atrás.

El código que aterriza en el dispositivo viaja DENTRO del instalador. El remoto
guarda configuración, no programas.

Se reparte como un ejecutable de PyInstaller (`build_installer.py`), que además
puede incrustar un perfil de conexión con su clave privada, para repartir
dispositivos llave en mano. El .py de este repositorio NO lleva ninguno: sin
perfil, el asistente abre su formulario de conexión y lo pregunta. Por eso esto
se puede publicar sin filtrar nada.

Una trampa que solo aparece compilado: `sys.executable` es este mismo
ejecutable, no Python. Todo lo que lance el `sync.py` del dispositivo pasa por
`deploy.device_python()`, que usa el Python que lleva el propio dispositivo y,
si no lleva uno para este equipo, busca uno instalado.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Callable

# Como .py, la raíz del proyecto va al path para importar `install`, `ui` y
# `common`; compilado, PyInstaller ya los trae.
if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from install import APP_NAME, InstallError, __version__  # noqa: E402
from install import components, deploy, device, platforms, profile, rclone_bin, remote  # noqa: E402
from common.update import CODIGO_RELEVO  # noqa: E402

DESCRIPCION = ("Aprovisiona un dispositivo prdrive nuevo a partir del catálogo "
               "de tu remoto.")
"""Descripción que enseña `--help`."""


def report(lineas: list[str]) -> None:
    """Enseña un informe por donde se pueda.

    Compilado con `--windowed` no hay consola: `sys.stdout` es None y `print()`
    no hace nada, así que un `--check` desde el .exe no diría nada. En ese caso
    se abre una ventana con el mismo texto. Igual el relevo, que corre con
    `pythonw.exe`.

    Args:
        lineas: Las líneas del informe.
    """
    texto = "\n".join(lineas)
    if sys.stdout is not None:
        print(texto)
        return
    try:
        import tkinter as tk
        from tkinter import scrolledtext

        from ui import theme
        theme.nitidez()
        raiz = tk.Tk()
        raiz.title(f"{APP_NAME} — Instalador")
        caja = scrolledtext.ScrolledText(raiz, width=96, height=20,
                                         font=("Consolas", 9))
        caja.grid(padx=8, pady=8)
        caja.insert("end", texto)
        caja.configure(state="disabled")
        raiz.mainloop()
    except Exception:                                # noqa: BLE001
        pass                                         # ni consola ni ventana: nada que hacer


def cmd_check() -> int:
    """Comprueba que haya rclone, que el remoto conteste y que su catálogo se entienda.

    Sin perfil incrustado no hay nada que comprobar y se dice: es el caso de
    quien acaba de clonar el repo, y la respuesta útil ahí es «abre el
    asistente», no un error de conexión.

    Returns:
        0 si todo está bien; 1 si no hay conexión configurada.
    """
    perfil = profile.load()
    if not perfil.configured:
        report(["Este instalador no lleva ninguna conexión configurada.",
                "",
                "Es lo normal si lo has clonado del repositorio: la conexión con",
                "tu remoto se configura en el primer paso del asistente, y desde",
                "ahí se puede guardar en el catálogo para los demás dispositivos.",
                "",
                "Ábrelo sin argumentos:  python prdrive-install.py"])
        return 1

    lineas: list[str] = []
    binario = rclone_bin.ensure_rclone(progreso=lineas.append)
    lineas.append(f"rclone:      {binario}")
    lineas.append(f"conexión:    {perfil.describe()}")
    lineas.append(f"origen:      {perfil.origen}")

    remote.sweep_stale()
    with remote.EphemeralConf(perfil) as conf:
        rclone = remote.Rclone(str(binario), conf.path,
                               remote_name=perfil.remote_name)
        rclone.check_connection()
        lineas.append("estado:      el remoto contesta")
        catalogo = remote.pull_catalog(rclone, perfil.catalog_path)
        lineas.append(f"catálogo:    {len(catalogo.names)} parejas: "
                      + ", ".join(catalogo.names))

    lineas.append(f"python:      {device.check_python().detalle}")
    report(lineas)
    return 0


def cmd_probe() -> int:
    """Enseña las unidades que se ven, tal y como las vería el asistente."""
    volumenes = device.list_volumes()
    if not volumenes:
        report(["No veo ninguna unidad. En Linux/macOS se buscan los puntos de "
                "montaje habituales de los extraíbles."])
        return 1
    lineas = [f"{'Unidad':<10}{'Etiqueta':<14}{'Formato':<9}{'Tipo':<11}"
              f"{'Tamaño':>10}{'Libre':>10}  Nota"]
    for vol in volumenes:
        lineas.append(f"{str(vol.root):<10}{vol.label:<14}{vol.filesystem:<9}"
                      f"{vol.drive_type:<11}{vol.size_gb:>9.1f}G{vol.free_gb:>9.1f}G  "
                      f"{vol.nota}")
    report(lineas)
    return 0


def cmd_update(raiz: str) -> int:
    """Sustituye el código de un dispositivo que ya existe. Nada más.

    Es el paso 5 del asistente menos las plataformas (rclone y Python ya están
    en `bin/` y `runtime/`) y menos todo lo demás: no se pregunta la conexión,
    no se elige unidad, no se cifra nada, no se tocan las parejas. Se
    sobrescriben los ficheros del programa y se conservan `rclone.conf`,
    `keys/`, `sync_config.toml`, `state/`, `logs/`, `filters/`, `bin/`,
    `runtime/` y el fichero de control del volumen.

    Tampoco se tocan los lanzadores de la raíz: se escriben al aprovisionar.
    Actualizar cambia el programa, no la forma de arrancarlo; y el runtime es
    un componente, no código: el zip de la release no lo lleva.

    Se imprime línea a línea con `print()` y no con `report()` al final porque
    solo se ejecuta desde un checkout (el zip descargado por
    `common/update.py`), nunca congelado: hay stdout de verdad, y quien mira es
    la ventana de salida, que enseña lo que va llegando.

    Args:
        raiz: La raíz del volumen.

    Raises:
        InstallError: Si ahí no hay un dispositivo.
    """
    root = Path(raiz).expanduser()
    destino = deploy.app_dir(root)
    if not destino.is_dir():
        raise InstallError(
            f"En {root} no hay ningún {deploy.APP_SUBDIR}/, así que ahí no hay "
            f"nada que actualizar.\n"
            f"Para preparar un dispositivo nuevo, abre el asistente sin "
            f"argumentos.")

    print(f"Actualizando {destino} a la versión {__version__}")
    escrito = deploy.deploy_code(root, progreso=print)   # sin rclone: ya está puesto
    guia = deploy.write_guide(root)
    if guia is not None:
        escrito.append(guia)
    try:
        from ui import icons                    # sin Tk: rasteriza él solo
        escrito.append(icons.write_ico(destino / "runsync.ico"))
    except Exception:                           # noqa: BLE001
        pass        # un icono no puede tumbar una actualización que va bien

    for ruta in escrito:
        print(f"  {ruta}")
    print("Hecho. Se conservan la configuración, las claves y el estado.")
    return 0


def cmd_update_components(raiz: str, relevo: int | None = None,
                          fase: Callable[[], None] | None = None) -> int:
    """Pone al día el rclone y el Python que lleva un dispositivo. Nada más.

    Es el hermano de `--update`: aquel cambia el CÓDIGO y deja los componentes;
    este cambia los componentes y no toca el código, la configuración, las
    claves ni los lanzadores. Se ejecuta igual, desde el zip descargado, y por
    el mismo motivo: `install/` no viaja al dispositivo y la maquinaria de
    bajar y comprobar rclone y Python vive aquí.

    No instala ninguna plataforma nueva: eso es «Añadir plataformas…» del
    asistente, que es una decisión con megas de por medio y una lista delante.

    Si uno de los pendientes es el Python con el que corre este proceso (el de
    la ventana), no se intenta: se deja preparado el relevo que lo cambiará
    cuando la ventana se cierre (`components.preparar_relevo()`) y se sale con
    `update.CODIGO_RELEVO`, que le dice a la ventana que se cierre.

    Si cambia el Python que usará este equipo, deja precompilado el programa con
    el nuevo (`deploy.precompilar_dispositivo()`) antes de volver: el cambio
    borra sus `.pyc`, y la ventana que se reabre no debe pagarlos.

    Args:
        raiz: La raíz del volumen.
        relevo: Pid de la ventana que lo ha lanzado, si la hay.
        fase: Se llama justo antes de precompilar, para que quien enseña un
            avance (la ventanita del relevo) lo diga.

    Returns:
        0 si ha ido bien, 1 si algo no se ha podido, `CODIGO_RELEVO` si el
        Python de la ventana queda para el relevo.
    """
    root = Path(raiz).expanduser()
    destino = deploy.app_dir(root)
    if not destino.is_dir():
        raise InstallError(
            f"En {root} no hay ningún {deploy.APP_SUBDIR}/, así que ahí no hay "
            f"componentes que poner al día.\n"
            f"Para preparar un dispositivo nuevo, abre el asistente sin "
            f"argumentos.")

    for resto in deploy.barrer_restos_runtime(root):
        print(f"Borrado un resto de un intento anterior: {resto}")

    pendientes = components.pendientes(root)
    if not pendientes:
        print(f"Los componentes de {destino} ya son los que fija la versión "
              f"{__version__}. No hay nada que hacer.")
        return 0

    propio = components.runtime_propio(root, pendientes) if relevo else None
    print(f"Componentes por poner al día en {destino}:")
    for p in pendientes:
        print(f"  {p.describe()}")
    sello_antes = platforms.sello_del_equipo(root)
    res = components.aplicar(root, progreso=print,
                             pends=[p for p in pendientes if p != propio])
    for linea in res.hechos:
        print(f"  hecho      {linea}")
    for linea in res.pospuestos:
        print(f"  POSPUESTO  {linea}")
    for linea in res.fallidos:
        print(f"  FALLO      {linea}")
    if platforms.sello_del_equipo(root) != sello_antes:
        if fase is not None:
            fase()
        deploy.precompilar_dispositivo(root, progreso=print)

    if propio is not None:
        # Antes de cerrar nada: si algo más corre desde ese Python, cambiarlo
        # le borraría la biblioteca estándar debajo (ver «El relevo» en
        # `install/components.py`). Se dice ahora, con la ventana abierta, y no
        # después, con el relevo esperando a algo que nadie ve.
        otros = components.quien_retiene(root, propio, [relevo, os.getpid()])
        if otros:
            print(f"  FALLO      {propio.titulo}: además de esta ventana, hay más "
                  f"procesos corriendo desde él:")
            print(components.describir_retenedores(otros))
            print("Ciérralos —suele ser otra ventana de prdrive, o un aviso suyo que "
                  "se ha quedado abierto detrás— y vuelve a pulsar «Actualizar…».")
            return 1
        try:
            orden, carpeta = components.preparar_relevo(
                root, propio, esperar=[relevo, os.getpid()],
                reabrir=sys.executable, decir=print)
            components.lanzar_relevo(orden, carpeta)
        except (InstallError, OSError) as e:
            print(f"  FALLO      {propio.titulo}: no he podido preparar su cambio "
                  f"con la ventana cerrada: {e}")
            print("No se ha podido con todo. Nada ha quedado a medias: lo que no "
                  "se ha sustituido sigue exactamente como estaba.")
            return 1
        print(f"  DESPUÉS    {propio.titulo}: es con el que está abierto prdrive, "
              f"así que se cambiará con la ventana cerrada.")
        print("Cierra esta ventana: prdrive se cerrará y una ventanita irá "
              "diciendo cómo va. En un USB tarda un par de minutos; no abras "
              "prdrive mientras tanto, se volverá a abrir solo.")
        return CODIGO_RELEVO

    if res.fallidos:
        print("No se ha podido con todo. Nada ha quedado a medias: lo que no se "
              "ha sustituido sigue exactamente como estaba.")
        return 1
    print("Hecho. Ni el código, ni la configuración, ni las claves se han tocado.")
    return 0


def cmd_instalar_agente() -> int:
    """Instala el agente residente sin asistente.

    Hace el mismo recorrido «En este equipo», con las unidades que se sepan sin
    red (la de penwatch, las enchufadas) en el modo que se les propone. Las
    demás llegarán con el aviso de «unidad nueva».
    """
    from install import agente
    for linea in agente.instalar(progreso=print):
        print(f"  {linea}")
    print("Hecho. Estado:  python agente.py status   (en la carpeta del agente)")
    return 0


def cmd_update_agente() -> int:
    """Pone el agente residente de este equipo a la versión de ESTE instalador.

    Su código y su Python van al lado de los que hay; después se registra de
    nuevo, se actualizan las raíces del equipo que estén abiertas y se arranca.
    Lo lanza «Actualizar» de la bandeja desde el zip que acaba de descargar
    (`agente.py actualizar`), por lo mismo que `--update`: la versión nueva se
    instala a sí misma. Se imprime línea a línea porque quien lo lanza lo copia
    en el diario del agente.
    """
    from install import agente
    print(f"Actualizando el agente de este equipo a la versión {__version__}")
    for linea in agente.actualizar(progreso=print):
        print(f"  {linea}")
    print("Hecho. Su lista de unidades y sus ajustes se conservan.")
    return 0


def cmd_desinstalar_agente() -> int:
    """Quita el agente residente de este equipo; no toca ninguna unidad."""
    from install import agente
    for linea in agente.desinstalar(progreso=print):
        print(f"  {linea}")
    return 0


def cmd_relevo(raiz: str, esperar: list[int], reabrir: str | None) -> int:
    """Hace el relevo: espera a que la ventana se cierre, pone al día y la reabre.

    Corre desde el temporal de este equipo (`components.preparar_relevo()`) con
    un intérprete sin consola, así que no hay stdout: lo que diría va a
    `relevo.log`, en su carpeta, y solo se enseña entero si algo ha salido mal,
    con la ventana de `report()`. Mientras trabaja, una ventanita dice cómo va
    (`ui.tk_relevo`); si ha ido bien, lo que lo dice es la ventana reabierta
    sin el recuadro ámbar.

    Espera a los pids de la ventana y del aplicador y, además, a que nada corra
    desde `runtime/`: a un prdrive abierto a mano mientras tanto, o a un aviso
    suyo olvidado detrás, el cambio le borraría la biblioteca estándar debajo.
    La ventanita dice cuál es, para cerrarlo.

    Args:
        raiz: La raíz del volumen.
        esperar: Pids de los procesos que tienen que acabar antes.
        reabrir: Python con el que reabrir la ventana al terminar, si hay que
            hacerlo.
    """
    root = Path(raiz).expanduser()
    carpeta = Path(__file__).resolve().parent.parent
    log = carpeta / components.RELEVO_LOG
    runtimes = deploy.app_dir(root) / "runtime"
    avance = components.AvanceRelevo(root, carpeta / "python")
    estado = {"rc": 1, "reabrir": False, "empezado": False, "terminado": False}

    def trabajar() -> None:
        """Hace el cambio de componentes con la salida en `relevo.log`.

        Deja en `estado` cómo ha ido, para quien lo espera.
        """
        estado["empezado"] = True
        with open(log, "w", encoding="utf-8", buffering=1) as salida:
            antes = sys.stdout, sys.stderr
            sys.stdout = sys.stderr = salida
            try:
                if not components.esperar_a(esperar, libre=runtimes,
                                            avisar=avance.esperando):
                    print("prdrive sigue abierto, así que no se ha cambiado nada. "
                          "Ciérralo y vuelve a pulsar «Actualizar…».")
                    otros = components.procesos_desde(runtimes)
                    if otros:
                        print(components.describir_retenedores(otros))
                    return
                estado["reabrir"] = True
                avance.medir()
                estado["rc"] = cmd_update_components(str(root), fase=avance.precompilando)
            except InstallError as e:
                print(e)
            except Exception:                        # noqa: BLE001
                traceback.print_exc()
            finally:
                avance.fin()
                sys.stdout, sys.stderr = antes
                estado["terminado"] = True

    try:
        from ui import tk_relevo
        tk_relevo.mientras(f"Cambiando el Python de prdrive en {root}.\n\nEn un USB "
                           f"tarda un par de minutos. No abras prdrive mientras "
                           f"tanto: se volverá a abrir solo al terminar.",
                           trabajar, avance.progreso)
    except Exception:                                # noqa: BLE001
        # Sin Tk o sin pantalla el trabajo es el mismo, solo no se ve. Si la
        # ventanita cayó con el trabajo ya en marcha, se espera a que acabe:
        # empezarlo otra vez serían dos intercambios a la vez.
        if not estado["empezado"]:
            trabajar()
        while not estado["terminado"]:
            time.sleep(0.5)

    rc = estado["rc"]
    if estado["reabrir"] and reabrir:
        try:
            components.lanzar_suelto(
                [reabrir, str(deploy.app_dir(Path(raiz).expanduser()) / "runsync.py")])
        except OSError:
            pass            # sin ventana reabierta, el informe de abajo lo cuenta
    if rc != 0:
        try:
            texto = log.read_text(encoding="utf-8")
        except OSError:
            texto = ""
        report(["No se han podido poner al día todos los componentes.", ""]
               + texto.splitlines())
    return rc


MODULOS_ASISTENTE = (
    "common.avisos", "common.cifrada", "common.dbus", "common.equipo", "common.pins",
    "common.vestibulo", "install", "install.agente", "install.crypto", "install.deploy",
    "install.device", "install.llavero", "install.raiz_equipo", "install.traveler",
    "install.veracrypt_bin", "penwatch", "shutil", "tkinter", "tkinter.filedialog",
    "tkinter.messagebox", "tkinter.ttk", "ui.bandeja_linux", "ui.lecturas_asistente",
    "ui.segundo_plano", "ui.tk", "ui.tk_crypto", "ui.tk_equipo", "ui.tk_install",
    "ui.tk_pairs", "unicodedata")
"""Lo que el asistente y sus pasos importan dentro de funciones.

Es lo que el `.exe` tiene que llevar dentro aunque no se use al abrirlo: un
módulo que PyInstaller no recogiera fallaría en un paso del asistente, lejos
de la compilación. `--autoprueba` los importa uno a uno. Sale de los imports de
dentro de funciones de `ui/tk_install.py`, `ui/tk_crypto.py` y
`ui/tk_equipo.py`, y `tests/test_autoprueba.py` falla si alguno no está.
"""


def _probar(informe: dict, clave: str, prueba: Callable[[], object]) -> object:
    """Apunta en `informe[clave]` lo que da `prueba()`, o su error si falla.

    Returns:
        Lo que dio la prueba, o `None` si falló.
    """
    try:
        valor = prueba()
    except Exception as e:                           # noqa: BLE001
        informe[clave] = f"error: {type(e).__name__}: {e}"
        return None
    informe[clave] = valor
    return valor


def _autoprueba(informe: dict) -> None:
    """Hace la autoprueba y la apunta en `informe`, clave a clave, según avanza.

    Las ventanas se crean escondidas y se destruyen sin enseñarse. El tema se
    aplica en una raíz y el asistente se monta en otra (`tk_install.build()`
    aplica el tema él mismo): así un fallo dice cuál de los dos ha sido.
    """
    import importlib
    import platform

    import install
    from install import agente

    informe["python"] = platform.python_version()
    informe["congelado"] = install.is_frozen()
    informe["prdrive"] = __version__

    from ui import icons, theme
    theme.nitidez()                     # como el asistente: antes del primer Tk()

    def raiz():
        import tkinter
        r = tkinter.Tk()
        r.withdraw()
        return r

    try:
        primera = raiz()
    except Exception as e:                           # noqa: BLE001
        sin_tk = f"error: {type(e).__name__}: {e}"
        for clave in ("tk", "tk9", "svg", "tema", "letra", "pintadas_python"):
            informe[clave] = sin_tk
    else:
        import tkinter
        try:
            _probar(informe, "tk", lambda: str(primera.getvar("tk_patchLevel")))
            _probar(informe, "tk9", lambda: tkinter.TkVersion >= 9)
            _probar(informe, "svg", lambda: icons.svg_disponible(primera))
            _probar(informe, "tema", lambda: theme.apply(primera) or True)
            _probar(informe, "letra", lambda: theme.familia("texto"))
            informe["pintadas_python"] = icons.PINTADAS["python"]
        finally:
            primera.destroy()

    def asistente() -> bool:
        from ui import tk_install
        otra = raiz()
        try:
            wiz = tk_install.build(otra)
            if wiz.conf is not None:
                wiz.conf.close()
        finally:
            otra.destroy()
        return True

    _probar(informe, "asistente", asistente)

    modulos: dict[str, str] = {}
    for nombre in MODULOS_ASISTENTE:
        _probar(modulos, nombre, lambda n=nombre: importlib.import_module(n) and "ok")
    informe["modulos"] = modulos

    base = install.bundle_dir()
    datos: dict[str, str] = {}
    for nombre in dict.fromkeys((*deploy.DEPLOY_FILES, *agente.CODIGO_FICHEROS,
                                 deploy.GUIDE_SOURCE)):
        datos[nombre] = "ok" if (base / nombre).is_file() else f"falta en {base}"
    for nombre in deploy.DEPLOY_TREES:
        datos[nombre] = "ok" if (base / nombre).is_dir() else f"falta en {base}"
    informe["datos"] = datos

    _probar(informe, "python_equipo", lambda: device.check_python().detalle)
    _probar(informe, "unidades", lambda: len(device.list_volumes()))


def _autoprueba_superada(informe: dict) -> bool:
    """Indica si el `.exe` se puede publicar.

    Hace falta Tk 9 con SVG, el tema, el asistente, cada módulo y cada fichero;
    `python_equipo` y `unidades` solo se leen.
    """
    return (all(informe.get(clave) is True for clave in ("tk9", "svg", "tema", "asistente"))
            and bool(informe.get("modulos")) and bool(informe.get("datos"))
            and all(v == "ok" for v in informe["modulos"].values())
            and all(v == "ok" for v in informe["datos"].values()))


def cmd_autoprueba(ruta: str) -> int:
    """Prueba, sin enseñar nada, que el `.exe` puede abrir el asistente, y lo apunta en `ruta`.

    Es la puerta de la CI antes de publicar un instalador
    (`.github/actions/compilar-instalador`). No usa `report()`: compilado con
    `--windowed` no hay consola, y una ventana con `mainloop()` no acabaría
    nunca. Lo que dice va a `ruta`, en JSON UTF-8: la versión de Python, si
    está congelado, el Tk (`tk`, `tk9`), si pinta con SVG (`svg`), el tema
    (`tema`, `letra`, `pintadas_python`), el asistente montado en una raíz
    escondida (`asistente`), cada módulo de `MODULOS_ASISTENTE` (`modulos`),
    cada fichero que despliega (`datos`) y, solo para leerlo, el Python del
    equipo (`python_equipo`) y cuántas unidades ve (`unidades`). Un fallo
    inesperado se apunta en `error`, con lo que se llegara a ver.

    Args:
        ruta: El fichero donde se escribe el informe; se crea su carpeta.

    Returns:
        0 si se puede publicar (`_autoprueba_superada()`); 1 si no, o si no se
        ha podido escribir el informe.
    """
    import json

    informe: dict = {}
    try:
        _autoprueba(informe)
        rc = 0 if _autoprueba_superada(informe) else 1
    except Exception as e:                           # noqa: BLE001
        informe["error"] = f"{type(e).__name__}: {e}"
        rc = 1
    try:
        destino = Path(ruta)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(json.dumps(informe, ensure_ascii=False, indent=2, default=str)
                           + "\n", encoding="utf-8")
    except OSError:
        return 1
    return rc


def cmd_wizard() -> int:
    """Abre el asistente. Sin Tkinter no hay instalador: no hay menú de consola.

    Es a propósito. Todo lo que se decide aquí (elegir la unidad, escribir una
    passphrase dos veces, teclear la conexión al remoto) se hace UNA vez en la
    vida de un dispositivo y con la pantalla delante. Un menú de texto que
    replicara eso sería el doble de código y el doble de sitios donde
    equivocarse en la parte más delicada del proyecto.
    """
    try:
        from ui import tk_install
        return tk_install.run_wizard()
    except Exception as e:                           # noqa: BLE001
        # Por `report()` y no por stderr: compilado tampoco hay stderr, y este
        # es justo el mensaje que hace falta leer.
        report([f"No puedo abrir el asistente: {type(e).__name__}: {e}",
                "",
                "Hace falta Tkinter. En Debian/Ubuntu: sudo apt install python3-tk",
                "Para comprobar la conexión sin ventana: --check"])
        return 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Devuelve los argumentos de la línea de comandos."""
    parser = argparse.ArgumentParser(prog=f"{APP_NAME}-install",
                                     description=DESCRIPCION)
    parser.add_argument("--check", action="store_true",
                        help="Comprueba rclone, la conexión al remoto y el "
                             "catálogo, y sale.")
    parser.add_argument("--probe", action="store_true",
                        help="Lista las unidades detectadas y sale.")
    parser.add_argument("--update", metavar="RUTA",
                        help="Sustituye el código de un dispositivo ya "
                             "instalado (la raíz del volumen) y sale. No toca "
                             "ni la configuración ni las claves.")
    parser.add_argument("--update-components", metavar="RUTA",
                        help="Pone al día el rclone y el Python que ya lleva un "
                             "dispositivo instalado (la raíz del volumen) y "
                             "sale. No toca el código ni la configuración.")
    parser.add_argument("--instalar-agente", action="store_true",
                        help="Instala el agente residente en este equipo (atiende "
                             "las unidades que se enchufan) y sale.")
    parser.add_argument("--desinstalar-agente", action="store_true",
                        help="Quita el agente residente de este equipo y sale. No "
                             "toca ninguna unidad.")
    parser.add_argument("--update-agente", action="store_true",
                        help="Pone el agente residente de este equipo (y el código de "
                             "sus raíces abiertas) a la versión de este instalador, y "
                             "sale. No toca su configuración.")
    # Los tres siguientes son de la ventana y del relevo, no de quien teclea.
    parser.add_argument("--relevo", metavar="PID", type=int,
                        help=argparse.SUPPRESS)
    parser.add_argument("--esperar", metavar="PID", type=int, action="append",
                        help=argparse.SUPPRESS)
    parser.add_argument("--reabrir", metavar="PYTHON", help=argparse.SUPPRESS)
    # El de la CI, sobre el .exe recién compilado.
    parser.add_argument("--autoprueba", metavar="RUTA", help=argparse.SUPPRESS)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser.parse_args(argv)


def _con_quien_pintar() -> None:
    """Le dice a `install/` quién pinta los iconos que instala.

    Los pinta `ui/icons.py`, que `install/` no importa: se lo dice este
    lanzador, que sí conoce `ui/` (`install.pintar_iconos`). Sin él, sin
    iconos; nada más.
    """
    try:
        import install
        from ui import icons                    # sin Tk: rasteriza él solo
        install.pintar_iconos = icons.pintar
    except Exception:                           # noqa: BLE001
        pass


def main(argv: list[str] | None = None) -> int:
    """Atiende la línea de comandos: el asistente o uno de sus subcomandos.

    Returns:
        El código de salida: 1 si hay un error, 130 si se cancela.
    """
    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(encoding="utf-8")      # la salida va con acentos
        except (AttributeError, OSError):
            pass                                     # compilado puede no haber consola

    args = parse_args(argv)
    remote.install_signal_handlers()
    _con_quien_pintar()
    try:
        if args.autoprueba:
            return cmd_autoprueba(args.autoprueba)
        if args.update_components and args.esperar:
            return cmd_relevo(args.update_components, args.esperar, args.reabrir)
        if args.update_components:
            return cmd_update_components(args.update_components, args.relevo)
        if args.update:
            return cmd_update(args.update)
        if args.update_agente:
            return cmd_update_agente()
        if args.instalar_agente:
            return cmd_instalar_agente()
        if args.desinstalar_agente:
            return cmd_desinstalar_agente()
        if args.check:
            return cmd_check()
        if args.probe:
            return cmd_probe()
        return cmd_wizard()
    except InstallError as e:
        # Por `report()`: compilado sin consola, stderr es None y el error se
        # perdería.
        report([str(e)])
        return 1
    except KeyboardInterrupt:
        report(["Cancelado."])
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
