#!/usr/bin/env python3
"""
build_installer.py — Genera el ejecutable del instalador.

    python build_installer.py                 dist/prdrive-install(.exe)
    python build_installer.py --console       con consola detrás (para depurar)
    python build_installer.py --only-secret   solo genera install/secret.py
    python build_installer.py --onedir        carpeta en vez de fichero único

Hace dos cosas distintas, y conviene no confundirlas:

**1. Meter el programa dentro del instalador.** El dispositivo ya no baja el
código del remoto: se lo copia el instalador (`install/deploy.py`). Así que el
`.exe` lleva `sync.py`, `runsync.py`, `penwatch.py`, `common/` y `ui/` como datos
además de como módulos importables. Sí, dos veces: PyInstaller no deja recuperar
el `.py` fuente de un módulo que ha importado, y lo que hay que dejar en el
dispositivo es fuente.

**2. Incrustar un perfil de conexión, si lo hay.** Es opcional y es lo que separa
el binario público del privado:

  * **Sin perfil** —lo normal al clonar el repo— sale un instalador genérico. Al
    abrirlo, el primer paso pregunta la conexión. No lleva ningún secreto y se
    puede repartir a cualquiera.
  * **Con perfil** (`prdrive-profile.toml` + `keys/` en el checkout) sale un
    instalador llave en mano: quien lo ejecute no tiene que configurar nada. Ese
    binario LLEVA DENTRO tu clave privada y solo se comparte en privado.

`install/secret.py` es el vehículo del perfil y se borra siempre, también si la
compilación falla: dejarlo por ahí sería justo el escape que se quiere evitar.
Está además en .gitignore, como segunda red, igual que `prdrive-profile.toml` y
`keys/`.

PyInstaller es dependencia SOLO de compilación (`pip install pyinstaller`). No
rompe la regla de «sin dependencias» del proyecto, que es sobre lo que se ejecuta
en el dispositivo: ni él ni el instalador necesitan nada instalado.

Si esa clave se filtra alguna vez, revócala en el servidor y genera otra: el
instalador antiguo deja de servir, que es lo suyo.
"""

from __future__ import annotations

import argparse
import base64
import os
import shutil
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
KEYS = RAIZ / "keys"
SECRET = RAIZ / "install" / "secret.py"
ENTRADA = RAIZ / "prdrive-install.py"
NOMBRE = "prdrive-install"

# Lo que el instalador va a dejar en el dispositivo. Tiene que coincidir con
# `install/deploy.py`: si aquí falta algo, el fallo aparece a mitad de una
# instalación de verdad y no al compilar.
DATOS_FICHEROS = ("sync.py", "runsync.py", "penwatch.py", "VERSION",
                  "device-readme.md")
DATOS_ARBOLES = ("common", "ui")

# Los datos del recurso de versión del .exe. La línea de copyright es la misma
# que el apéndice de LICENSE: si cambia una, cambia la otra.
AUTOR = "Jeremaya"
COPYRIGHT = "Copyright 2026 Jeremaya - Apache License 2.0"
DESCRIPCION = "Instalador de prdrive: sincronizacion portable con rclone"

PLANTILLA = '''"""
secret.py — GENERADO por build_installer.py. NO SE VERSIONA.

Lleva dentro el perfil de conexión con el remoto y, si el backend usa una, la
clave privada. Existe solo mientras dura la compilación: build_installer.py lo
crea, PyInstaller lo empaqueta y se borra después. Si te lo encuentras en el
árbol de fuentes, es que una compilación se quedó a medias: bórralo.
"""

PROFILE_TOML = """\\
{perfil}"""

PRIVATE_KEY_B64 = "{clave}"

KNOWN_HOSTS = """\\
{known}"""
'''


def leer_perfil() -> tuple[str, bytes | None, str] | None:
    """El perfil del checkout, si lo hay. None si este es un build genérico.

    No es un error no tenerlo: es el caso de quien se ha bajado el repositorio y
    solo quiere el instalador. La diferencia se dice en voz alta al terminar,
    porque de ella depende si el binario se puede repartir o no."""
    from install import profile

    perfil = profile.from_bundle()
    if perfil is None or not perfil.configured:
        return None
    conocidos = perfil.known_hosts
    if conocidos and not conocidos.endswith("\n"):
        conocidos += "\n"
    return profile.dumps(perfil), perfil.private_key, conocidos


def escribir_secreto() -> Path | None:
    """Genera install/secret.py. Devuelve None si no hay perfil que incrustar."""
    datos = leer_perfil()
    if datos is None:
        print(f"Sin {RAIZ / 'prdrive-profile.toml'}: el ejecutable saldrá genérico "
              f"(pedirá la conexión al abrirlo).")
        return None

    perfil_toml, clave, conocidos = datos
    b64 = base64.b64encode(clave).decode("ascii") if clave else ""
    if not b64:
        print("Aviso: el perfil no lleva clave privada. El instalador la pedirá, "
              "o usará lo que diga el backend (contraseña, token…).")
    if clave and not conocidos.strip():
        print("Aviso: no hay keys/known_hosts. El instalador aceptará la clave de "
              "host del servidor a la primera (TOFU) en vez de tenerla fijada.")
    SECRET.write_text(
        PLANTILLA.format(perfil=perfil_toml, clave=b64, known=conocidos),
        encoding="utf-8")
    print(f"Generado {SECRET} ({len(b64)} caracteres de clave en base64).")
    return SECRET


def comprobar_pyinstaller() -> None:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        raise SystemExit(
            "Falta PyInstaller: pip install pyinstaller\n"
            "Es dependencia solo de compilación; el dispositivo no la necesita.")


def escribir_icono() -> Path | None:
    """Pinta el .ico en build/, para que el .exe salga con la marca.

    Se genera en vez de guardarse compilado porque el icono ES código: sale de
    `ui/icons.py`, que es el mismo sitio del que salen los de la ventana, así que
    no hay dos versiones que puedan separarse. No necesita Tkinter ni pantalla."""
    from ui import icons
    destino = RAIZ / "build" / "runsync.ico"
    destino.parent.mkdir(parents=True, exist_ok=True)
    return icons.write_ico(destino)


# Se genera en ASCII a proposito, sin acentos: lo lee PyInstaller, no una
# persona, y no merece la pena depender de con que codificacion lo abra.
VERSION_INFO = """# GENERADO por build_installer.py. El recurso de version del .exe.
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={tupla}, prodvers={tupla},
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040a04b0', [
      StringStruct('CompanyName', {autor!r}),
      StringStruct('FileDescription', {descripcion!r}),
      StringStruct('FileVersion', {version!r}),
      StringStruct('InternalName', {nombre!r}),
      StringStruct('LegalCopyright', {copyright!r}),
      StringStruct('OriginalFilename', {fichero!r}),
      StringStruct('ProductName', {producto!r}),
      StringStruct('ProductVersion', {version!r}),
    ])]),
    VarFileInfo([VarStruct('Translation', [0x040a, 1200])]),
  ]
)
"""


def escribir_version_info() -> Path:
    """Pinta build/version_info.txt: quién firma el .exe, qué es y qué versión."""
    from common import APP_NAME
    from common.update import installed_version

    version = installed_version(RAIZ) or "0.0.0"
    # filevers exige cuatro enteros. 'v1.2' o un sufijo raro no pueden tumbar la
    # compilación por un campo informativo: lo que no sea número cuenta como 0.
    partes = [int(x) if x.isdigit() else 0 for x in version.split(".")[:4]]
    tupla = tuple(partes + [0] * (4 - len(partes)))

    destino = RAIZ / "build" / "version_info.txt"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(VERSION_INFO.format(
        tupla=tupla, autor=AUTOR, descripcion=DESCRIPCION, version=version,
        nombre=NOMBRE, copyright=COPYRIGHT, fichero=NOMBRE + ".exe",
        producto=APP_NAME), encoding="utf-8")
    return destino


def datos() -> list[str]:
    """Los `--add-data` del árbol que se despliega en el dispositivo."""
    args: list[str] = []
    for nombre in DATOS_FICHEROS:
        origen = RAIZ / nombre
        if not origen.is_file():
            raise SystemExit(f"Falta {origen}: sin él el instalador no puede "
                             f"desplegar nada.")
        args += ["--add-data", f"{origen}{os.pathsep}."]
    for nombre in DATOS_ARBOLES:
        origen = RAIZ / nombre
        if not origen.is_dir():
            raise SystemExit(f"Falta el paquete {origen}.")
        args += ["--add-data", f"{origen}{os.pathsep}{nombre}"]
    return args


def compilar(consola: bool, carpeta: bool) -> Path:
    """Llama a PyInstaller y devuelve la ruta del entregable."""
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onedir" if carpeta else "--onefile",
        "--noconfirm", "--clean",
        # UPX comprime el ejecutable y es, a ojos de un antivirus, exactamente
        # lo que hace un empaquetador de malware. PyInstaller lo usa solo si lo
        # encuentra en el PATH, así que sin esto el binario saldría distinto
        # según la máquina que compile.
        "--noupx",
        "--name", NOMBRE,
        "--distpath", str(RAIZ / "dist"),
        "--workpath", str(RAIZ / "build"),
        "--specpath", str(RAIZ / "build"),
        # Se importan dentro de funciones o por nombre, así que el analizador de
        # PyInstaller no siempre los ve venir.
        "--hidden-import", "install.secret",
        "--hidden-import", "ui.tk_install",
        "--hidden-import", "ui.tk_crypto",
        *datos(),
        "--console" if consola else "--windowed",
    ]
    # El icono solo lo entiende el PyInstaller de Windows; en Linux se compila
    # igual, sin él, en vez de abortar por un adorno.
    if sys.platform == "win32":
        cmd += ["--icon", str(escribir_icono())]
        cmd += ["--version-file", str(escribir_version_info())]
    cmd.append(str(ENTRADA))
    print("$ " + " ".join(cmd))
    if subprocess.run(cmd, cwd=str(RAIZ)).returncode != 0:
        raise SystemExit("PyInstaller ha fallado.")

    if carpeta:
        # En modo carpeta el entregable ES dist/<nombre>/: el .exe de dentro no
        # arranca sin el _internal/ que tiene al lado.
        return RAIZ / "dist" / NOMBRE

    # PyInstaller deja además el árbol sin empaquetar en dist/<nombre>/, que es
    # una SEGUNDA copia de la aplicación —con el perfil dentro si lo hay—. El
    # entregable es el fichero único, así que la otra sobra.
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
                             "el camino del perfil incrustado sin PyInstaller.")
    parser.add_argument("--onedir", action="store_true",
                        help="Entrega dist/prdrive-install/ en vez de un fichero "
                             "único. Menos cómodo de repartir (hay que llevarse "
                             "la carpeta entera, o un zip), pero no se autoextrae "
                             "en el temporal al arrancar, que es la forma que más "
                             "puntúa en los antivirus.")
    args = parser.parse_args(argv)

    if args.only_secret:
        if escribir_secreto() is not None:
            print("Recuerda borrarlo cuando acabes: contiene la clave privada.")
        return 0

    comprobar_pyinstaller()
    con_secreto = False
    try:
        con_secreto = escribir_secreto() is not None
        binario = compilar(args.console, args.onedir)
    finally:
        # Pase lo que pase. Un secret.py olvidado en el árbol es la fuga que este
        # script existe para evitar.
        if SECRET.exists():
            SECRET.unlink()
            print(f"Borrado {SECRET}.")
        # El intermedio de PyInstaller son otros 20 MB que no le hacen falta a
        # nadie una vez está el ejecutable.
        shutil.rmtree(RAIZ / "build", ignore_errors=True)

    print(f"\nListo: {binario}")
    comprobar = binario / (NOMBRE + ".exe") if args.onedir else binario
    print(f"Compruébalo con:  {comprobar} --check")
    if con_secreto:
        print("\nEse fichero LLEVA DENTRO tu clave privada. Compártelo solo en "
              "privado; si se filtra, revoca la clave en el servidor.")
    else:
        print("\nEs un instalador genérico: no lleva ningún secreto y pregunta la "
              "conexión al abrirlo. Se puede repartir sin más.")
    return 0


def limpiar() -> None:
    """Se lleva por delante lo que deja PyInstaller."""
    for carpeta in (RAIZ / "build", RAIZ / "dist"):
        shutil.rmtree(carpeta, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
