#!/usr/bin/env python3
"""
build_installer.py — Genera el ejecutable del instalador e incrusta la clave.

    python build_installer.py                 dist/perepen-install(.exe)
    python build_installer.py --console       con consola detrás (para depurar)
    python build_installer.py --only-secret   solo genera install/secret.py

Esto es lo que hace que `perepen-install.py` se pueda versionar en git sin llevar
dentro la clave privada del NAS. El reparto:

  * El **fuente** no tiene ninguna clave. Ejecutado como .py, la coge de `keys/`
    del pen desde el que se ejecuta (ver `install/remote.py`).
  * El **binario** sí la lleva: este script lee `keys/` y genera
    `install/secret.py`, PyInstaller lo empaqueta, y al terminar se borra.
    El secreto vive solo dentro del .exe, que es lo que se comparte en privado.

`install/secret.py` se borra siempre, también si la compilación falla: dejarlo
por ahí sería justo el escape que queremos evitar, y encima la pareja `perepen`
lo subiría al NAS en la siguiente sincronización. Está además en .gitignore, como
segunda red.

PyInstaller es dependencia SOLO de compilación (`pip install pyinstaller`). No
rompe la regla de «sin dependencias» del proyecto, que es sobre lo que se ejecuta
en el pen: ni el pen ni el instalador necesitan nada instalado para funcionar.

Si esta clave se filtra alguna vez, lo que hay que hacer es revocarla en el
Synology y generar otra: el instalador antiguo deja de servir, que es lo suyo.
"""

from __future__ import annotations

import argparse
import base64
import shutil
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
KEYS = RAIZ / "keys"
KEY_FILE = KEYS / "synology_ed25519"
KNOWN_FILE = KEYS / "known_hosts"
SECRET = RAIZ / "install" / "secret.py"
ENTRADA = RAIZ / "perepen-install.py"
NOMBRE = "perepen-install"

PLANTILLA = '''"""
secret.py — GENERADO por build_installer.py. NO SE VERSIONA.

Lleva dentro la clave privada del usuario SFTP del NAS. Existe solo mientras dura
la compilación: build_installer.py lo crea, PyInstaller lo empaqueta y se borra
después. Si te lo encuentras en el árbol de fuentes, es que una compilación se
quedó a medias: bórralo.
"""

PRIVATE_KEY_B64 = "{clave}"

KNOWN_HOSTS = """\\
{known}"""
'''


def escribir_secreto() -> Path:
    """Genera install/secret.py a partir de las llaves de este pen."""
    if not KEY_FILE.is_file():
        raise SystemExit(
            f"No encuentro {KEY_FILE}.\n"
            "Este script hay que ejecutarlo desde un pen ya provisionado: es de "
            "ahí de donde saca la clave que incrusta en el ejecutable.")
    clave = base64.b64encode(KEY_FILE.read_bytes()).decode("ascii")
    known = KNOWN_FILE.read_text(encoding="utf-8") if KNOWN_FILE.is_file() else ""
    if not known.strip():
        print("Aviso: no hay keys/known_hosts. El instalador aceptará la clave de "
              "host del NAS a la primera (TOFU) en vez de tenerla fijada.")
    if known and not known.endswith("\n"):
        known += "\n"
    SECRET.write_text(PLANTILLA.format(clave=clave, known=known), encoding="utf-8")
    print(f"Generado {SECRET} ({len(clave)} caracteres de clave en base64).")
    return SECRET


def comprobar_pyinstaller() -> None:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        raise SystemExit(
            "Falta PyInstaller: pip install pyinstaller\n"
            "Es dependencia solo de compilación; el pen no la necesita.")


def escribir_icono() -> Path | None:
    """Pinta `runsync.ico` en build/, para que el .exe salga con la marca.

    Se genera en vez de guardarse compilado porque el icono ES código: sale de
    `ui/icons.py`, que es el mismo sitio del que salen los de la ventana, así que
    no hay dos versiones que puedan separarse. No necesita Tkinter ni pantalla."""
    from ui import icons
    destino = RAIZ / "build" / "runsync.ico"
    destino.parent.mkdir(parents=True, exist_ok=True)
    return icons.write_ico(destino)


def compilar(consola: bool) -> Path:
    """Llama a PyInstaller y devuelve la ruta del ejecutable."""
    cmd = [
        sys.executable, "-m", "PyInstaller", "--onefile", "--noconfirm", "--clean",
        "--name", NOMBRE,
        "--distpath", str(RAIZ / "dist"),
        "--workpath", str(RAIZ / "build"),
        "--specpath", str(RAIZ / "build"),
        # Se importan dentro de funciones o por nombre, así que el analizador de
        # PyInstaller no siempre los ve venir.
        "--hidden-import", "install.secret",
        "--hidden-import", "ui.tk_install",
        "--hidden-import", "ui.tk_crypto",
        "--console" if consola else "--windowed",
    ]
    # El icono solo lo entiende el PyInstaller de Windows; en Linux se compila
    # igual, sin él, en vez de abortar por un adorno.
    if sys.platform == "win32":
        cmd += ["--icon", str(escribir_icono())]
    cmd.append(str(ENTRADA))
    print("$ " + " ".join(cmd))
    if subprocess.run(cmd, cwd=str(RAIZ)).returncode != 0:
        raise SystemExit("PyInstaller ha fallado.")

    # PyInstaller deja además el árbol sin empaquetar en dist/<nombre>/, que es
    # una SEGUNDA copia de la aplicación con la clave dentro. El entregable es el
    # fichero único, así que la otra sobra: es 33 MB de superficie de fuga
    # viviendo dentro del pen, que encima la pareja 'perepen' subiría al NAS.
    shutil.rmtree(RAIZ / "dist" / NOMBRE, ignore_errors=True)

    sufijo = ".exe" if sys.platform == "win32" else ""
    return RAIZ / "dist" / (NOMBRE + sufijo)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--console", action="store_true",
                        help="Deja la consola detrás del asistente. Útil para "
                             "depurar: sin ella, un fallo al arrancar es mudo.")
    parser.add_argument("--only-secret", action="store_true",
                        help="Genera install/secret.py y no compila. Para probar "
                             "el camino de la clave incrustada sin PyInstaller.")
    args = parser.parse_args(argv)

    if args.only_secret:
        escribir_secreto()
        print("Recuerda borrarlo cuando acabes: contiene la clave privada.")
        return 0

    comprobar_pyinstaller()
    try:
        escribir_secreto()
        binario = compilar(args.console)
    finally:
        # Pase lo que pase. Un secret.py olvidado en el árbol es la fuga que este
        # script existe para evitar, y la pareja 'perepen' lo subiría al NAS.
        if SECRET.exists():
            SECRET.unlink()
            print(f"Borrado {SECRET}.")
        # El intermedio de PyInstaller son otros 20 MB dentro del pen que no le
        # hacen falta a nadie una vez está el ejecutable.
        shutil.rmtree(RAIZ / "build", ignore_errors=True)

    print(f"\nListo: {binario}")
    print("Compruébalo con:  "
          + str(binario) + " --check")
    print("\nEse fichero LLEVA DENTRO la clave privada del NAS. Compártelo solo en "
          "privado; si se filtra, revoca la clave en el Synology.")
    return 0


def limpiar() -> None:
    """Se lleva por delante lo que deja PyInstaller."""
    for carpeta in (RAIZ / "build", RAIZ / "dist"):
        shutil.rmtree(carpeta, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
