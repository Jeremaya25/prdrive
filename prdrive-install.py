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

    python prdrive-install.py            el asistente
    python prdrive-install.py --check    rclone + conexión + catálogo, y sale
    python prdrive-install.py --probe    qué unidades ve, y sale

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
`install.python_command()`, que busca un intérprete de verdad.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ejecutado como .py hay que poner la raíz del proyecto en el path para importar
# `install`, `ui` y `common`. Compilado no hace falta: PyInstaller ya los trae.
if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from install import APP_NAME, InstallError, __version__  # noqa: E402
from install import device, profile, rclone_bin, remote  # noqa: E402

DESCRIPCION = ("Aprovisiona un dispositivo prdrive nuevo a partir del catálogo "
               "de tu remoto.")


def report(lineas: list[str]) -> None:
    """Enseña un informe por donde se pueda.

    Compilado con --windowed no hay consola: `sys.stdout` es None y `print()` se
    convierte en un no-op silencioso, así que un `--check` desde el .exe no diría
    nada. En ese caso se abre una ventana con el mismo texto."""
    texto = "\n".join(lineas)
    if sys.stdout is not None:
        print(texto)
        return
    try:
        import tkinter as tk
        from tkinter import scrolledtext
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
