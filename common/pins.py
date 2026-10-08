#!/usr/bin/env python3
"""Versiones fijadas de lo que el dispositivo lleva de fuera.

También lista las plataformas donde puede llevarlo. Hay cosas del dispositivo
que no son código de este proyecto: el binario de rclone, el intérprete de
Python, en uno cifrado con VeraCrypt el VeraCrypt que viaja fuera del
contenedor y, con el llavero, KeePassXC. Se descargan de su publicador (nunca
se compilan aquí) y todas se fijan a una versión CONCRETA en este fichero.
Moverlas es un commit, no algo que pase solo porque alguien publicó otra cosa
por la noche:
- lo que se comprueba es lo que se ha probado, y no «lo último» que haya salido
  entre dos instalaciones;
- los dispositivos de una misma tanda llevan lo mismo;
- el día que algo se rompa se sabe con qué versión, porque está escrita.

Es la fuente única que consultan el instalador (`install/rclone_bin.py`,
`install/runtime_bin.py`, `install/veracrypt_bin.py`) y el despliegue.
`penwatch.py` no la importa (no puede importar nada del proyecto) y repite solo
el nombre del sello y de la carpeta del runtime, que un test mantiene a raya.

Por qué python-build-standalone y no el «embeddable» oficial de CPython: el zip
de python.org no trae tkinter, y sin tkinter no hay ventana. Los de astral-sh
sí, son reubicables (se descomprimen donde sea y funcionan) y publican un
`SHA256SUMS` por release con la misma forma que el de rclone.

Por qué 3.14 (desde el 08/10/2026; antes era 3.13): los 3.14 de
python-build-standalone traen Tcl/Tk 9.0.4 en TODAS las plataformas, y los 3.13
traían Tk 8.6.15 en Windows y Tk 9.0.4 en Linux. Con 3.14 la ventana corre con
el mismo Tk en los dos sistemas y lo que se mide en uno vale para el otro.

Qué trae cada plataforma de la 20261001 con 3.14.8, comprobado el 08/10/2026
sobre los cuatro archivos (SHA-256 iguales a los de su `SHA256SUMS`):

- Windows x64 y ARM64: `DLLs/tcl90.dll` y `DLLs/tcl9tk90.dll` (Tk 9.0.4).
  `tcl90.dll` importa `zlib1.dll` y `libtommath.dll`, y `_tkinter.pyd` también
  `libtommath.dll`: las tres están en `DLLs/`, que `podar()` no toca (el fallo
  de las 3.13 de ARM64 de antes de la 20260924, abajo, era justo una
  `zlib1.dll` que faltaba). `icu.dll` aparece entre sus cadenas, pero no es una
  importación: se carga si está.
- Linux x64 y ARM64: el mismo Tcl/Tk 9.0.4 que traían los 3.13
  (`lib/libtcl9tk9.0.so`), **compilado sin Xft** (su versión lo dice:
  `…no-xft.x11`). Sin Xft, Tk solo ve las fuentes de mapa de bits de X11: la
  letra sale sin suavizar y no puede usar la de `ui/fuentes/`. Por eso viaja
  al lado uno compilado con Xft (`TK_XFT_VERSION`, abajo).

Qué NO trae Tk 9.0.4, aunque se espere: el redibujado al pasar a una pantalla
con otro zoom. Su DLL no usa ninguna función de densidad por monitor
(`GetDpiForWindow`…) y su manifiesto declara la del sistema, la misma que pide
`theme.nitidez()`. Sí trae `-placeholder` en `ttk::entry` y lectura de SVG.

Cómo se mide: la suite normal corre con el Python del sistema (Tk 8.6), así que
las pantallas se miden también con el intérprete del propio runtime:
`xvfb-run -a <runtime>/bin/python3 tests/test_tk_medidas.py` (y
`test_tk_servicio.py`, `test_tk_densidad.py`, `test_daemon_aviso.py`). Con Tk
9.0.4 en Linux, el 03/10/2026: medidas y servicio pasan enteros; densidad falla
un píxel de redondeo en Xvfb igual que con Tk 8.6; y la ventanita de fallo
abortaba el proceso (`Tcl_Panic: epoll_ctl`) al abrir la segunda, porque Tk
9.0.4 no admite crear un intérprete en un hilo nuevo después de que otro
hilo hubiera creado el suyo y acabado: `ui.avisar_fallo()` usa ahora un único
hilo que no acaba. **Windows con Tk 9 no está probado en una máquina de verdad**
(entre otras cosas, la protección de capturas de #59, que dependía de cómo
envuelve Tk 8.6.15 sus ventanas con `wm frame`): es lo primero que hay que
mirar en Windows antes de publicar.
"""

from __future__ import annotations

from dataclasses import dataclass

RCLONE_VERSION = "v1.75.1"
"""Versión de rclone que se descarga para cada plataforma elegida.

Es fija: «la última» puede ser una que nadie ha probado.
"""

PYTHON_RELEASE = "20261001"          # el tag de la release en GitHub
"""Tag de la release de python-build-standalone en GitHub.

No bajar de 20260924: en todas las anteriores con 3.13 para Windows ARM64 (de
20250630 a 20260901) su `tcl86t.dll` importa `zlib1.dll` y el archivo no la
trae. `import _tkinter` falla con «DLL load failed» y, como el lanzador usa
`pythonw.exe`, el doble clic en `runsync.bat` no abría nada ni decía por qué.
La de x64 no depende de `zlib1.dll`. La 20260924 la lleva en `DLLs/`, que
`podar()` no toca.

La 20261001 lleva Python 3.14.8 (y 3.13.16, que es el que se usó hasta el
08/10/2026) para las cuatro plataformas de `PLATAFORMAS`, con `DLLs/zlib1.dll` y
`DLLs/libtommath.dll` en los dos Windows (comprobado el 08/10/2026).
"""
PYTHON_VERSION = "3.14.8"
PBS_BASE_URL = ("https://github.com/astral-sh/python-build-standalone/"
                "releases/download")
"""URL base de las releases de python-build-standalone."""

TK_XFT_VERSION = "9.0.4"
"""El Tk con Xft que acompaña al runtime de Linux: el MISMO que trae su Python.

Tiene que ser la versión del `lib/libtcl9tk9.0.so` del runtime fijado (la de
sus scripts, `lib/tk9.0/`, que usa también este): quien mueva `PYTHON_VERSION`
o `PYTHON_RELEASE` comprueba que sigue siéndolo, o recompila
(`.github/workflows/tk-xft.yml`).

Por qué hace falta: el de python-build-standalone para Linux está compilado sin
Xft y solo ve las fuentes de mapa de bits de X11. Este se compila igual pero
con Xft, lo publica ese workflow como prerelease de este repositorio, y
`install/runtime_bin.py` lo deja en `lib/tk-xft/` del runtime, al lado del de
serie; `ui` lo precarga antes de tkinter si el equipo tiene `libXft`.
"""
TK_XFT_REVISION = "1"
"""La compilación de esa versión: sube si se recompila (otra opción, otra base)."""
TK_XFT_TAG = f"tk-xft-{TK_XFT_VERSION}-{TK_XFT_REVISION}"
"""El tag de su release en este repositorio, que es también lo que anota el sello."""
TK_XFT_BASE_URL = "https://github.com/Jeremaya25/prdrive/releases/download"
"""URL base de las releases de este repositorio."""
TK_XFT_SHA256 = {
    "x86_64": "6a9db4afc3e87757c719f984d78a421e2c3701a1cd166df9d468bafc6211bb3c",
    "aarch64": "0f92f19cc9d4c9757af7d9310db8a52e8d88a06b014e3eb4821281f0685fc8dc",
}
"""El SHA-256 de cada paquete, por arquitectura (la primera parte del triple).

Se fija aquí, como el de VeraCrypt, y no se lee de un SHA256SUMS de la misma
release: así lo publicado no se puede cambiar sin un commit que se vea. Salen
de la release `tk-xft-9.0.4-1` (compilada en manylinux_2_28 el 08/10/2026),
comprobados ese día: coinciden con su `SHA256SUMS`; cada biblioteca es de su
arquitectura, lleva el SONAME `libtcl9tk9.0.so`, pide `libXft.so.2` y ninguna
ruta de búsqueda, y la glibc 2.14 (x86_64) o 2.17 (aarch64) o más nueva. La de
x86_64 se ha probado en el runtime 3.14.8: carga ella sola, ve las fuentes del
sistema y las de `ui/fuentes/`, y sin `libXft` queda la de serie.
"""

VERACRYPT_VERSION = "1.26.29"
r"""Versión del paquete «VeraCrypt Portable» oficial (IDRIX) que se usa y se lleva.

Sirve para crear y montar el contenedor en un equipo sin VeraCrypt instalado, y
viaja en la carpeta `VeraCrypt\` de la raíz física de un dispositivo cifrado,
con sus dos arquitecturas (x64 y ARM64). Lo baja y lo abre
`install/veracrypt_bin.py` sin ejecutarlo.

La URL lleva la versión, como la de rclone: nunca un «última» que se mueva por
debajo. El SHA-256 del `.exe` se fija a mano: desde la 1.26.29 la release
publica también `veracrypt-<versión>-sha256sum.txt` con su firma PGP, pero sale
del mismo sitio que el paquete, así que lo que vale es el número de aquí, que
alguien comprobó. Ni la firma PGP (`.sig`) ni la Authenticode del `.exe` se
pueden comprobar en Python puro, así que QUIEN MUEVA ESTA VERSIÓN comprueba las
dos una vez, a mano (la Authenticode de «IDRIX SARL»: propiedades del fichero →
Firmas digitales, `Get-AuthenticodeSignature` u `osslsigncode verify`; la PGP
con la clave de VeraCrypt, huella `5069 A233 D55A 0EEB 174A  5FC3 821A CD02
680D 16DE`, con `gpg --verify "VeraCrypt Portable X.exe.sig"`) y apunta aquí el
SHA-256 del fichero comprobado. Desde ahí el asistente compara con este número
todo lo que baje: lo que no cuadre no se escribe.

1.26.29, comprobada el 30/09/2026: PGP buena con esa huella (el `.exe` de
Launchpad y el de GitHub son byte a byte el mismo); Authenticode buena,
firmante «IDRIX SARL» (EV de GlobalSign) con sello de tiempo de DigiCert del
08/06/2026; y el SHA-256 coincide con el de su `sha256sum.txt`, firmado
también.

Se eligió la 1.26.29 porque corrige un pantallazo azul del driver de Windows y
es la primera con AppImage de aarch64. Para el driver es la misma versión que
la 1.26.24 (`VERSION_NUM` 0x0126 en `Common/Tcdefs.h`, lo que compara
`DriverAttach()`), así que una unidad con la 1.26.24 y un equipo con la 1.26.29
instalada no chocan con `ERR_DRIVER_VERSION`.
"""
VERACRYPT_PAQUETE = f"VeraCrypt Portable {VERACRYPT_VERSION}.exe"
"""Nombre del `.exe` del Portable."""
VERACRYPT_URL = ("https://launchpad.net/veracrypt/trunk/"
                 f"{VERACRYPT_VERSION}/+download/"
                 f"VeraCrypt%20Portable%20{VERACRYPT_VERSION}.exe")
"""URL versionada del Portable en Launchpad."""
VERACRYPT_SHA256 = "8772a127f93561d169d4b4082d9ab5e855fd928a361e020905484c388c474a4e"
"""SHA-256 del `.exe` del Portable, apuntado a mano (ver `VERACRYPT_VERSION`)."""
MB_VERACRYPT = 34
"""Megabytes que ocupa en la unidad lo que se extrae del Portable.

Son ejecutables y drivers de las dos arquitecturas, catálogos, `.inf` y
licencias: 33,7 MiB en la 1.26.29, redondeado hacia arriba. La descarga son ~39
MB porque trae además documentación e idiomas, que no viajan.
"""

VERACRYPT_APPIMAGE: dict[str, tuple[str, str]] = {
    "linux-x64": (f"VeraCrypt-{VERACRYPT_VERSION}-x86_64.AppImage",
                  "5a9b96f937b94de42f196c04eb9b9154f944d049ddeaeb9961851332d994c92c"),
    "linux-arm64": (f"VeraCrypt-{VERACRYPT_VERSION}-aarch64.AppImage",
                    "aaf4cf7900caa3dfd4d0e26596b7adc5d317d2a2ab5a64607cf56f39e5890d00"),
}
"""AppImage oficial de VeraCrypt por plataforma Linux: `{clave: (nombre, sha256)}`.

Es lo que usa un Linux sin VeraCrypt instalado para CREAR el contenedor
(abrirlo ya se puede con udisks2 o cryptsetup) y lo que el agente se lleva para
abrir y cerrar una raíz cifrada. Es un solo fichero ejecutable, sin instalar
nada; montar sigue pidiendo la contraseña de administrador (sudo), como el
instalado. Existe desde la 1.26.24 (x86_64); la 1.26.29 añade aarch64 y trae su
propia biblioteca FUSE (el de la 1.26.24 no arranca sin `libfuse.so.2`, que
muchas distribuciones ya no traen). Sin `fusermount` su runtime extrae y
ejecuta (visto: `--text --version` y crear un contenedor FAT, como root, en un
equipo sin `fusermount`).

Mismo contrato que el Portable: quien mueve la versión apunta a mano el SHA-256
tras comprobar la firma PGP de cada uno con la clave de `VERACRYPT_VERSION`.
Los dos de la 1.26.29, el 30/09/2026: PGP buena, y los de Launchpad y GitHub
son los mismos bytes. El de x86_64 está además en el `sha256sum.txt` firmado;
el de aarch64 NO sale en ese fichero y solo lo cubre su `.sig`. La clave es la
de `Plataforma.clave` (solo las de Linux).
"""
VERACRYPT_APPIMAGE_URL = ("https://launchpad.net/veracrypt/trunk/"
                          f"{VERACRYPT_VERSION}/+download/{{nombre}}")
"""Plantilla de la URL de un AppImage; `{nombre}` es el de `VERACRYPT_APPIMAGE`."""

KEEPASSXC_VERSION = "2.7.12"
"""Versión de KeePassXC que viaja con el llavero (`.prdrive/keepassxc/`).

Es la primera con passkeys que pone los indicadores BE/BS que piden los sitios
(`docs/superpowers/pruebas/2026-10-04-keepassxc-portatil.md`, sección 5): una
sola versión en todos los equipos evita la mezcla, que es lo que V1 y V2 no
llegaron a ver rechazado pero que nadie garantiza.

Mismo contrato que VeraCrypt: el SHA-256 se apunta a mano tras comprobar la
firma PGP con la clave de KeePassXC, huella `BF5A 669F 2272 CF43 24C1  FDA8
CFB4 C216 6397 D0D2` (`gpg --verify KeePassXC-<versión>-Win64.zip.sig`). En
ejecución no se lee ningún `.DIGEST`: vienen en tres formatos distintos según
la versión (H-2) y salen del mismo sitio que el paquete.

2.7.12, comprobada el 05/10/2026: firma buena de esa clave (subclave `C1E4 CBA3
AD78 D3AF D894  F9E0 B7A6 6F03 B590 76A8`, la misma que vio K0), y el SHA-256
coincide con su `.DIGEST`. El AppImage de Linux, el mismo día y con la misma
subclave.
"""
KEEPASSXC: dict[str, tuple[str, str]] = {
    "windows-x64": ("KeePassXC-2.7.12-Win64.zip",
                    "958234b0669d757b53eacf42bdd5de0fa1cc1ab7527709ddf4f7e29c06a8305f"),
    "linux-x64": ("KeePassXC-2.7.12-x86_64.AppImage",
                  "564fe8b751b9ef7aa057e4d3d0b2878db24eaa0f6b1c855c82e699ab0913ae49"),
}
"""El paquete oficial de KeePassXC por paquete: `{paquete: (nombre, sha256)}`.

La clave es también la carpeta `.prdrive/keepassxc/<paquete>/`. En Windows es
el ZIP tal cual: ya trae `.portable` (H-3) y no trae el runtime de Visual C++
(K3), que se detecta al lanzarlo. En Linux es el AppImage, entero y con un
nombre fijo (`components.KEEPASSXC_APPIMAGE`); no se ejecuta desde la unidad,
sino extraído una vez en cada equipo (`common/keepassxc.py`, §11 de la
especificación).
"""
KEEPASSXC_URL = ("https://github.com/keepassxreboot/keepassxc/releases/download/"
                 "{version}/{nombre}")
"""Plantilla de la URL versionada de un paquete de KeePassXC."""
KEEPASSXC_PARA: dict[str, str] = {"windows-x64": "windows-x64",
                                  "windows-arm64": "windows-x64",
                                  "linux-x64": "linux-x64"}
"""Qué paquete de `KEEPASSXC` usa cada plataforma.

Windows ARM64 usa el de x64, emulado: en las pruebas, el ZIP x64 funcionó
entero en Windows ARM (A1), y el único ZIP ARM64 publicado, el de la
2.8.0-beta1, no conectaba con el navegador (A2, H-7). Linux ARM64 no tiene
ninguno, porque no hay AppImage aarch64: usa el KeePassXC del equipo, si lo
hay (§11 de la especificación).
"""
MB_KEEPASSXC: dict[str, int] = {"windows-x64": 78, "linux-x64": 47}
"""Megabytes que ocupa en la unidad cada paquete de la 2.7.12.

El ZIP descomprimido son 78,0 MiB; el AppImage, que viaja entero, 47,0.
"""


@dataclass(frozen=True)
class Plataforma:
    """Un sistema y una CPU donde el dispositivo puede funcionar solo.

    `clave` es a la vez el nombre de la carpeta `runtime/<clave>/` y lo que
    comprueban los lanzadores, así que no se cambia a la ligera: un dispositivo
    ya aprovisionado la lleva escrita en disco. `bin_dir` es el vocabulario de
    `model.arch_dir()` y es donde busca rclone el dispositivo: un Windows y un
    Linux de la misma CPU comparten esa carpeta sin chocar, porque uno deja
    `rclone.exe` y el otro `rclone`.

    Args:
        clave: Identificador de la plataforma, p. ej. `windows-x64`.
        nombre: Nombre para mostrar.
        so: `windows` o `linux`; es también el nombre del sistema en los zips
            de rclone.
        bin_dir: `x64` o `arm`.
        rclone_arch: `amd64` o `arm64`, como en los zips de rclone.
        triple: Destino de python-build-standalone.
        mb_rclone: Lo que ocupa rclone ya en el dispositivo.
        mb_python: Lo que ocupa el runtime ya descomprimido y podado. Los
            tamaños son redondeados: sirven para decidir si cabe, no para
            cuadrar bytes.
    """
    clave: str
    nombre: str
    so: str
    bin_dir: str
    rclone_arch: str
    triple: str
    mb_rclone: int
    mb_python: int

    @property
    def es_windows(self) -> bool:
        """Indica si la plataforma es Windows."""
        return self.so == "windows"

    @property
    def rclone_exe(self) -> str:
        """Devuelve el nombre del ejecutable de rclone de la plataforma."""
        return "rclone.exe" if self.es_windows else "rclone"

    @property
    def interprete(self) -> str:
        """Devuelve el intérprete SIN consola, relativo a `runtime/<clave>/`.

        En Windows es `pythonw.exe`: con `python.exe` cada arranque abriría una
        consola negra detrás de la ventana. En Linux no hay tal distinción.
        """
        return "pythonw.exe" if self.es_windows else "bin/python3"

    @property
    def interprete_consola(self) -> str:
        """Devuelve el intérprete con consola, el que se usa para leer su salida.

        Por ejemplo, al inicializar las parejas.
        """
        return "python.exe" if self.es_windows else "bin/python3"


PLATAFORMAS: tuple[Plataforma, ...] = (
    Plataforma("windows-x64", "Windows x64", "windows", "x64", "amd64",
               "x86_64-pc-windows-msvc", 82, 43),
    Plataforma("windows-arm64", "Windows ARM64", "windows", "arm", "arm64",
               "aarch64-pc-windows-msvc", 77, 44),
    Plataforma("linux-x64", "Linux x64", "linux", "x64", "amd64",
               "x86_64-unknown-linux-gnu", 82, 55),
    Plataforma("linux-arm64", "Linux ARM64", "linux", "arm", "arm64",
               "aarch64-unknown-linux-gnu", 77, 45),
)
"""Las plataformas que el dispositivo puede llevar.

Los tamaños están medidos con las versiones de arriba: el `rclone.exe` 1.75.1
de amd64 son 81 MB descomprimido y los runtimes son lo que deja
`runtime_bin.extract()` ya podado, en MiB redondeados hacia arriba. Con la
20261001 y Python 3.14.8, el 08/10/2026: Windows x64 42,47 MiB, Windows ARM64
43,27, Linux x64 54,08 y Linux ARM64 44,73 (los de Linux, con el Tk con Xft de
`TK_XFT_TAG`, que son 1,6 MiB).
"""


def plataforma(clave: str) -> Plataforma:
    """Devuelve la plataforma de esa clave.

    Raises:
        KeyError: Si no es ninguna de las conocidas.
    """
    for p in PLATAFORMAS:
        if p.clave == clave:
            return p
    raise KeyError(clave)


def plataforma_para(so: str, bin_dir: str) -> Plataforma | None:
    """Devuelve la plataforma de un sistema (`windows` o `linux`) y un `arch_dir()`.

    Returns:
        La plataforma, o `None` si no hay ninguna: macOS, por ejemplo, ya no es
        una plataforma que el dispositivo pueda llevar (no hay equipo con el
        que probarla).
    """
    for p in PLATAFORMAS:
        if p.so == so and p.bin_dir == bin_dir:
            return p
    return None
