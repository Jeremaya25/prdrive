#!/usr/bin/env python3
"""
prdrive-install.py — Aprovisiona un dispositivo prdrive nuevo.

Punto de entrada y poco más: aquí se miran los argumentos y se abre el asistente.
Lo que sabe hacer está repartido:

    install/     lo que decide y lo que toca disco o red (sin Tkinter)
    ui/tk_install.py, ui/tk_crypto.py   el asistente (solo dibujan)

Lo que hace el asistente, en orden: pregunta la conexión con tu remoto (un
formulario, o importar un remote de tu rclone.conf), consigue un rclone, lee el
catálogo global de parejas, te deja elegir la unidad y cómo cifrarla (VeraCrypt o
BitLocker), **copia el programa** en su carpeta oculta `.prdrive/`, escribe el
`rclone.conf` y el `sync_config.toml` de ESE dispositivo, crea sus carpetas,
inicializa las parejas bisync y comprueba que todo está.

    python prdrive-install.py                 el asistente
    python prdrive-install.py --check         rclone + conexión + catálogo, y sale
    python prdrive-install.py --probe         qué unidades ve, y sale
    python prdrive-install.py --update RUTA   sustituye el código de un dispositivo
    python prdrive-install.py --update-components RUTA   pone al día su rclone y su Python

`--update` es el otro extremo del aviso de versión nueva de la ventana: no
aprovisiona nada, solo repite el paso 5 sobre un dispositivo que ya existe. Y no
se ejecuta desde el dispositivo, sino desde el zip que `common/update.py` acaba
de descargar y verificar: `install/` no viaja al dispositivo, así que **la
versión nueva es la que se instala a sí misma**, y no hay una segunda copia del
manifiesto de qué se despliega que se pueda quedar atrás.

El código que aterriza en el dispositivo viaja DENTRO del instalador; antes lo
bajaba del remoto con un espejo del árbol entero. El remoto guarda configuración,
no programas.

La forma en que se reparte es un ejecutable de PyInstaller (`build_installer.py`),
que además puede incrustar un perfil de conexión con su clave privada, para
repartir dispositivos llave en mano. El .py de este repositorio NO lleva ninguno:
sin perfil, el asistente abre su formulario de conexión y lo pregunta. Por eso
esto se puede publicar sin filtrar nada.

Ojo con una trampa que solo aparece compilado: `sys.executable` es este mismo
ejecutable, no Python. Todo lo que lance el `sync.py` del dispositivo pasa por
`deploy.device_python()`, que usa el Python que lleva el propio dispositivo y,
si no lleva uno para este equipo, busca uno instalado.
"""

from __future__ import annotations

import argparse
import os
import sys
import traceback
from pathlib import Path

# Ejecutado como .py hay que poner la raíz del proyecto en el path para importar
# `install`, `ui` y `common`. Compilado no hace falta: PyInstaller ya los trae.
if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from install import APP_NAME, InstallError, __version__  # noqa: E402
from install import components, deploy, device, profile, rclone_bin, remote  # noqa: E402
from common.update import CODIGO_RELEVO  # noqa: E402

DESCRIPCION = ("Aprovisiona un dispositivo prdrive nuevo a partir del catálogo "
               "de tu remoto.")


def report(lineas: list[str]) -> None:
    """Enseña un informe por donde se pueda.

    Compilado con --windowed no hay consola: `sys.stdout` es None y `print()` se
    convierte en un no-op silencioso, así que un `--check` desde el .exe no diría
    nada. En ese caso se abre una ventana con el mismo texto. Lo mismo el relevo,
    que corre con `pythonw.exe`."""
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
    """Que haya rclone, que el remoto conteste y que su catálogo se entienda.

    Sin perfil incrustado no hay nada que comprobar y se dice: es el caso de
    quien acaba de clonar el repo, y la respuesta útil ahí es «abre el
    asistente», no un error de conexión."""
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
    """Las unidades que se ven, tal y como las vería el asistente."""
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

    Es el paso 5 del asistente menos las plataformas —rclone y Python ya están
    en `bin/` y `runtime/`— y menos todo lo demás: no se pregunta la conexión, no
    se elige unidad, no se cifra nada, no se tocan las parejas. Se sobrescriben
    los ficheros del programa y se conservan `rclone.conf`, `keys/`,
    `sync_config.toml`, `state/`, `logs/`, `filters/`, `bin/`, `runtime/` y el
    fichero de control del volumen.

    Tampoco se tocan los lanzadores de la raíz: se escriben al aprovisionar y
    ya está. Actualizar cambia el programa, no la forma de arrancarlo —y el
    runtime es un componente, no código: el zip de la release no lo lleva—.

    Se imprime línea a línea con `print()` y no con `report()` al final porque
    esto solo se ejecuta desde un checkout —el zip que ha descargado
    `common/update.py`—, nunca congelado: hay stdout de verdad, y quien mira es
    la ventana de salida, que enseña lo que va llegando."""
    root = Path(raiz).expanduser()
    destino = deploy.app_dir(root)
    if not destino.is_dir():
        raise InstallError(
            f"En {root} no hay ningún {deploy.APP_SUBDIR}/, así que ahí no hay "
            f"nada que actualizar.\n"
            f"Para preparar un dispositivo nuevo, abre el asistente sin "
            f"argumentos.")

    print(f"Actualizando {destino} a la versión {__version__}")
    escrito = deploy.deploy_code(root)          # sin rclone: ya está puesto
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


def cmd_update_components(raiz: str, relevo: int | None = None) -> int:
    """Pone al día el rclone y el Python que lleva un dispositivo. Nada más.

    El hermano de `--update`: aquel cambia el CÓDIGO y deja los componentes,
    éste cambia los componentes y no toca el código, la configuración, las
    claves ni los lanzadores. Se ejecuta igual, desde el zip descargado, y por
    el mismo motivo: `install/` no viaja al dispositivo, y la maquinaria de bajar
    y comprobar rclone y Python vive aquí.

    No se instala ninguna plataforma nueva. Eso es «Añadir plataformas…» del
    asistente, que es una decisión con megas de por medio y una lista delante.

    `relevo` es el pid de la ventana que lo ha lanzado. Si uno de los pendientes
    es el Python con el que corre este proceso (el de la ventana), ése no se
    intenta: se deja preparado el relevo que lo cambiará cuando la ventana se
    cierre (`components.preparar_relevo()`) y se sale con
    `update.CODIGO_RELEVO`, que es lo que le dice a la ventana que se cierre."""
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
    res = components.aplicar(root, progreso=print,
                             pends=[p for p in pendientes if p != propio])
    for linea in res.hechos:
        print(f"  hecho      {linea}")
    for linea in res.pospuestos:
        print(f"  POSPUESTO  {linea}")
    for linea in res.fallidos:
        print(f"  FALLO      {linea}")

    if propio is not None:
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
        print("Cierra esta ventana: prdrive se cerrará, cambiará ese Python y "
              "volverá a abrirse solo en unos segundos.")
        return CODIGO_RELEVO

    if res.fallidos:
        print("No se ha podido con todo. Nada ha quedado a medias: lo que no se "
              "ha sustituido sigue exactamente como estaba.")
        return 1
    print("Hecho. Ni el código, ni la configuración, ni las claves se han tocado.")
    return 0


def cmd_relevo(raiz: str, esperar: list[int], reabrir: str | None) -> int:
    """El relevo: espera a que la ventana se cierre, pone al día y la reabre.

    Corre desde el temporal de este equipo (`components.preparar_relevo()`) con
    un intérprete sin consola, así que no hay stdout: lo que diría va a
    `relevo.log`, en su carpeta, y solo se enseña si algo ha salido mal —con la
    ventana de `report()`—. Si ha ido bien, lo que lo dice es la ventana
    reabierta sin el recuadro ámbar."""
    carpeta = Path(__file__).resolve().parent.parent
    log = carpeta / components.RELEVO_LOG
    rc, reabrir_ahora = 1, False
    with open(log, "w", encoding="utf-8", buffering=1) as salida:
        antes = sys.stdout, sys.stderr
        sys.stdout = sys.stderr = salida
        try:
            if not components.esperar_a(esperar):
                print("prdrive sigue abierto, así que no se ha cambiado nada. "
                      "Ciérralo y vuelve a pulsar «Actualizar…».")
            else:
                reabrir_ahora = True
                rc = cmd_update_components(raiz)
        except InstallError as e:
            print(e)
        except Exception:                            # noqa: BLE001
            traceback.print_exc()
        finally:
            sys.stdout, sys.stderr = antes

    if reabrir_ahora and reabrir:
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


def cmd_wizard() -> int:
    """El asistente. Sin Tkinter no hay instalador: no hay menú de consola.

    No lo hay a propósito. Todo lo que se decide aquí —elegir la unidad que se va
    a usar, escribir una passphrase dos veces, teclear la conexión al remoto— se
    hace UNA vez en la vida de un dispositivo y con la pantalla delante. Un menú
    de texto que replicara eso sería el doble de código y el doble de sitios
    donde equivocarse en la parte más delicada del proyecto."""
    try:
        from ui import tk_install
        return tk_install.run_wizard()
    except Exception as e:                           # noqa: BLE001
        # Por report() y no por stderr: si el fallo es «no hay Tkinter», tampoco
        # habrá ventana, pero compilado tampoco hay stderr, y este es justo el
        # mensaje que hace falta leer.
        report([f"No puedo abrir el asistente: {type(e).__name__}: {e}",
                "",
                "Hace falta Tkinter. En Debian/Ubuntu: sudo apt install python3-tk",
                "Para comprobar la conexión sin ventana: --check"])
        return 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
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
    # Los tres siguientes son de la ventana y del relevo, no de quien teclea.
    parser.add_argument("--relevo", metavar="PID", type=int,
                        help=argparse.SUPPRESS)
    parser.add_argument("--esperar", metavar="PID", type=int, action="append",
                        help=argparse.SUPPRESS)
    parser.add_argument("--reabrir", metavar="PYTHON", help=argparse.SUPPRESS)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(encoding="utf-8")      # la salida va con acentos
        except (AttributeError, OSError):
            pass                                     # compilado puede no haber consola

    args = parse_args(argv)
    remote.install_signal_handlers()
    try:
        if args.update_components and args.esperar:
            return cmd_relevo(args.update_components, args.esperar, args.reabrir)
        if args.update_components:
            return cmd_update_components(args.update_components, args.relevo)
        if args.update:
            return cmd_update(args.update)
        if args.check:
            return cmd_check()
        if args.probe:
            return cmd_probe()
        return cmd_wizard()
    except InstallError as e:
        # Por report() y no por stderr: compilado sin consola, stderr es None y
        # el error se perdería justo cuando más falta hace verlo.
        report([str(e)])
        return 1
    except KeyboardInterrupt:
        report(["Cancelado."])
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
