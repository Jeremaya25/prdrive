#!/usr/bin/env python3
"""
pins.py — Las versiones exactas de lo que el dispositivo lleva de fuera, y las
plataformas para las que puede llevarlo.

Tres cosas del dispositivo no son código de este proyecto: el binario de rclone,
el intérprete de Python y —en uno cifrado con VeraCrypt— el VeraCrypt que viaja
fuera del contenedor. Las tres se descargan de su publicador —nunca se compilan
aquí— y las tres se fijan a una versión CONCRETA en este fichero. Moverlas es un
commit, no algo que pase solo porque alguien publicó otra cosa por la noche:

  * lo que se comprueba es lo que se ha probado, y no «lo último» que haya
    salido entre dos instalaciones;
  * los dispositivos de una misma tanda llevan lo mismo;
  * y el día que algo se rompa se sabe con qué versión, porque está escrita.

Es la fuente única que consultan el instalador (`install/rclone_bin.py`,
`install/runtime_bin.py`, `install/veracrypt_bin.py`) y el despliegue. `penwatch.py` no la importa —no puede
importar nada del proyecto— y repite solo el nombre del sello y de la carpeta del
runtime, que un test mantiene a raya.

**Por qué python-build-standalone y no el «embeddable» oficial de CPython.** El
zip embebible de python.org no trae tkinter, y sin tkinter no hay ventana. Los de
astral-sh sí, son reubicables (se descomprimen donde sea y funcionan) y publican
un `SHA256SUMS` por release con la misma forma que el de rclone.

**Por qué 3.13 y no 3.14.** Los 3.14 de python-build-standalone ya traen Tcl/Tk
9.0, y la interfaz se ha hecho y medido con Tk 8.6 (el tema de ttk, los iconos
rasterizados a mano, `tk scaling`): 3.13 sigue en Tk 8.6. Subir a 3.14 es probar
esas pantallas con Tk 9 primero, no cambiar un número.
"""

from __future__ import annotations

from dataclasses import dataclass

# --- rclone -------------------------------------------------------------------
# La que se descarga para cada plataforma elegida. El `version.txt` de rclone.org
# ya no manda: decía «la última», y la última puede ser una que nadie ha probado.
RCLONE_VERSION = "v1.75.1"

# --- Python (python-build-standalone, de astral-sh) ---------------------------
PYTHON_RELEASE = "20260924"          # el tag de la release en GitHub
PYTHON_VERSION = "3.13.15"
# No bajar de 20260924. En todas las anteriores con 3.13 para Windows ARM64
# (de 20250630 a 20260901) su `tcl86t.dll` importa `zlib1.dll` y el archivo no
# la trae: `import _tkinter` falla con «DLL load failed», y como el lanzador usa
# `pythonw.exe`, doble clic en `runsync.bat` no abría nada ni decía por qué. La
# de x64 no depende de zlib1.dll. 20260924 la lleva en `DLLs/`, que `podar()`
# no toca.
PBS_BASE_URL = ("https://github.com/astral-sh/python-build-standalone/"
                "releases/download")

# --- VeraCrypt (el paquete «VeraCrypt Portable» oficial, de IDRIX) --------------
# El que se usa para crear y montar el contenedor en un equipo que no tiene
# VeraCrypt instalado, y el que viaja en la carpeta `VeraCrypt\` de la raíz
# física de un dispositivo cifrado, con sus dos arquitecturas (x64 y ARM64).
# Lo baja y lo abre `install/veracrypt_bin.py` sin ejecutarlo.
#
# La URL lleva la versión, como la de rclone: nunca un «última» que se mueva por
# debajo. Y aquí se fija el SHA-256 del `.exe` a mano. Desde la 1.26.29 la
# release publica también `veracrypt-<versión>-sha256sum.txt` con su firma PGP,
# pero sale del mismo sitio que el paquete: lo que vale es el número de aquí,
# que alguien comprobó. Ni la firma PGP (`.sig`) ni la Authenticode del `.exe`
# se pueden comprobar en Python puro, así que QUIEN MUEVA ESTA VERSIÓN comprueba
# las dos una vez, a mano —la Authenticode de «IDRIX SARL» (propiedades del
# fichero → Firmas digitales, `Get-AuthenticodeSignature`, u `osslsigncode
# verify`) y la PGP con la clave de VeraCrypt, huella
# `5069 A233 D55A 0EEB 174A  5FC3 821A CD02 680D 16DE`
# (`gpg --verify "VeraCrypt Portable X.exe.sig"`)— y apunta aquí el SHA-256 del
# fichero que ha comprobado. A partir de ahí el asistente compara con este número
# todo lo que baje: lo que no cuadre no se escribe.
#
# 1.26.29, comprobado el 30/09/2026: PGP buena con esa huella (el `.exe` de
# Launchpad y el de GitHub son el mismo, byte a byte); Authenticode buena,
# firmante «IDRIX SARL» (EV de GlobalSign) con sello de tiempo de DigiCert del
# 08/06/2026; y el SHA-256 coincide con el de su `sha256sum.txt`, firmado también.
# Por qué 1.26.29 y no la 1.26.24 de antes: corrige un pantallazo azul del
# driver de Windows, y es la primera con AppImage de aarch64. Las dos son la
# misma versión para el driver (`VERSION_NUM` 0x0126 en `Common/Tcdefs.h`, que
# es lo que compara `DriverAttach()`), así que una unidad con la 1.26.24 y un
# equipo con la 1.26.29 instalada no chocan con ERR_DRIVER_VERSION.
VERACRYPT_VERSION = "1.26.29"
VERACRYPT_PAQUETE = f"VeraCrypt Portable {VERACRYPT_VERSION}.exe"
VERACRYPT_URL = ("https://launchpad.net/veracrypt/trunk/"
                 f"{VERACRYPT_VERSION}/+download/"
                 f"VeraCrypt%20Portable%20{VERACRYPT_VERSION}.exe")
VERACRYPT_SHA256 = "8772a127f93561d169d4b4082d9ab5e855fd928a361e020905484c388c474a4e"
# Lo que ocupa en la unidad lo que se extrae (ejecutables y drivers de las dos
# arquitecturas, catálogos, .inf y licencias: 33,7 MiB en la 1.26.29),
# redondeado hacia arriba. La descarga son ~39 MB porque trae además la
# documentación y los idiomas, que no viajan.
MB_VERACRYPT = 34

# --- VeraCrypt para Linux (el AppImage oficial, de la misma versión) -----------
# Lo que usa un Linux sin VeraCrypt instalado para CREAR el contenedor (abrirlo
# ya se puede con udisks2 o cryptsetup, #51) y lo que el agente se lleva para
# abrir y cerrar una raíz cifrada. Un solo fichero ejecutable, sin instalar
# nada; montar sigue pidiendo la contraseña de administrador (sudo), como el
# instalado. Existe desde la 1.26.24 (x86_64) y la 1.26.29 añade aarch64 y trae
# su propia biblioteca FUSE —el de la 1.26.24 no arranca sin `libfuse.so.2` en
# el equipo, que muchas distribuciones ya no traen—; sin `fusermount` en el
# equipo, su runtime extrae y ejecuta (visto: `--text --version` y crear un
# contenedor FAT, como root, en un equipo sin `fusermount`).
#
# Mismo contrato que el Portable: el SHA-256 lo apunta a mano quien mueve la
# versión, tras comprobar la firma PGP de cada uno con la clave de arriba. Los
# dos de la 1.26.29, el 30/09/2026: PGP buena, y los de Launchpad y los de GitHub
# son los mismos bytes. El de x86_64 está además en el `sha256sum.txt` firmado;
# el de aarch64 NO sale en ese fichero, solo lo cubre su `.sig`.
# Clave: la de `Plataforma.clave` (solo las de Linux).
VERACRYPT_APPIMAGE: dict[str, tuple[str, str]] = {
    "linux-x64": (f"VeraCrypt-{VERACRYPT_VERSION}-x86_64.AppImage",
                  "5a9b96f937b94de42f196c04eb9b9154f944d049ddeaeb9961851332d994c92c"),
    "linux-arm64": (f"VeraCrypt-{VERACRYPT_VERSION}-aarch64.AppImage",
                    "aaf4cf7900caa3dfd4d0e26596b7adc5d317d2a2ab5a64607cf56f39e5890d00"),
}
VERACRYPT_APPIMAGE_URL = ("https://launchpad.net/veracrypt/trunk/"
                          f"{VERACRYPT_VERSION}/+download/{{nombre}}")


@dataclass(frozen=True)
class Plataforma:
    """Un sistema y una CPU donde el dispositivo puede funcionar solo.

    `clave` es a la vez el nombre de la carpeta `runtime/<clave>/` y lo que
    comprueban los lanzadores, así que no se cambia a la ligera: un dispositivo
    ya aprovisionado la lleva escrita en disco.

    `bin_dir` es el vocabulario de `model.arch_dir()` —'x64' o 'arm'—, que es
    donde busca rclone el dispositivo. Un Windows y un Linux de la misma CPU
    comparten esa carpeta sin chocar: uno deja `rclone.exe` y el otro `rclone`.

    Los tamaños son lo que ocupa cada cosa YA en el dispositivo (descomprimida y
    podada), redondeados: sirven para decidir si cabe, no para cuadrar bytes."""
    clave: str
    nombre: str
    so: str             # 'windows' | 'linux': también el nombre de rclone en sus zips
    bin_dir: str        # 'x64' | 'arm'
    rclone_arch: str    # 'amd64' | 'arm64': el de los zips de rclone
    triple: str         # el destino de python-build-standalone
    mb_rclone: int
    mb_python: int

    @property
    def es_windows(self) -> bool:
        return self.so == "windows"

    @property
    def rclone_exe(self) -> str:
        return "rclone.exe" if self.es_windows else "rclone"

    @property
    def interprete(self) -> str:
        """El intérprete SIN consola, relativo a `runtime/<clave>/`.

        En Windows es `pythonw.exe`: con `python.exe` cada arranque abriría una
        consola negra detrás de la ventana. En Linux no hay tal distinción."""
        return "pythonw.exe" if self.es_windows else "bin/python3"

    @property
    def interprete_consola(self) -> str:
        """El que se usa cuando alguien lee la salida (inicializar parejas)."""
        return "python.exe" if self.es_windows else "bin/python3"


# Tamaños medidos con las versiones de arriba: rclone.exe 1.75.1 de amd64 son 81
# MB descomprimido; los runtimes, lo que deja `runtime_bin.extract()` ya podado.
PLATAFORMAS: tuple[Plataforma, ...] = (
    Plataforma("windows-x64", "Windows x64", "windows", "x64", "amd64",
               "x86_64-pc-windows-msvc", 82, 45),
    Plataforma("windows-arm64", "Windows ARM64", "windows", "arm", "arm64",
               "aarch64-pc-windows-msvc", 77, 47),
    Plataforma("linux-x64", "Linux x64", "linux", "x64", "amd64",
               "x86_64-unknown-linux-gnu", 82, 51),
    Plataforma("linux-arm64", "Linux ARM64", "linux", "arm", "arm64",
               "aarch64-unknown-linux-gnu", 77, 42),
)


def plataforma(clave: str) -> Plataforma:
    """La plataforma de esa clave. KeyError si no es ninguna de las conocidas."""
    for p in PLATAFORMAS:
        if p.clave == clave:
            return p
    raise KeyError(clave)


def plataforma_para(so: str, bin_dir: str) -> Plataforma | None:
    """La plataforma de un sistema ('windows'|'linux') y un `arch_dir()`.

    None si no hay ninguna: macOS, por ejemplo, ya no es una plataforma que el
    dispositivo pueda llevar (no hay equipo con el que probarla)."""
    for p in PLATAFORMAS:
        if p.so == so and p.bin_dir == bin_dir:
            return p
    return None
