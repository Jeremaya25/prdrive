#!/usr/bin/env python3
"""
crypto.py — VeraCrypt y BitLocker. Sin Tkinter.

Dos formas de cifrar el dispositivo, con repartos de trabajo muy distintos:

  * **VeraCrypt** hace un contenedor `PRDRIVE.hc` en la raíz del volumen físico. Lo
    crea y lo monta este módulo, y la estructura del dispositivo vive DENTRO. Es lo que
    hace portable el cifrado: no depende de la edición de Windows ni de nada
    instalado en el equipo salvo el propio VeraCrypt.

  * **BitLocker** cifra el volumen entero, y aquí solo se guía y se comprueba:
    cifrar de verdad lo hace el diálogo de Windows. Comprobarlo no pasa por
    `manage-bde` ni por `Get-BitLockerVolume` —los dos exigen elevar— sino por
    la propiedad del shell que usa el Explorador, que se lee sin permisos y sin
    lanzar nada; la nota larga está en la sección de BitLocker. Aun así «no he
    podido comprobarlo» sigue siendo una respuesta de primera clase y no se
    disfraza de «está todo bien».

Tres reglas que no se pueden relajar:

  1. **La passphrase nunca se enseña ni se registra.** En Windows la CLI de
     VeraCrypt solo admite la contraseña como argumento, así que ya es visible en
     la lista de procesos mientras dura la orden —eso no lo podemos evitar—, pero
     sí podemos no repetirlo: nada de lo que sale de aquí para pintar o para un
     log lleva la contraseña. Para eso está `redact()`, y en Linux se usa
     `--stdin`, que evita el problema del todo.
  2. **El montaje no se da por bueno por el código de retorno.** VeraCrypt eleva
     a un ayudante por UAC y lo que devuelve el proceso que lanzamos no dice si
     el volumen quedó montado. Se comprueba mirando si el punto de montaje se
     puede leer.
  3. **`/dynamic` se pregunta antes, nunca se prueba a ver.** VeraCrypt aborta
     con ERR_DYNAMIC_NOT_SUPPORTED si el anfitrión no admite ficheros dispersos,
     y esa comprobación es nuestra: `soporta_dispersos()`. Ver la sección
     «Cuánto tarda».

Sobre el XML: se usa `xml.etree` de la biblioteca estándar y no `defusedxml`
porque el proyecto no admite dependencias, y aquí no hacen falta. Lo que se
parsea es la configuración local de VeraCrypt, que escribe VeraCrypt en el perfil
del propio usuario; no es entrada de red ni de un tercero. Y `xml.etree` no
resuelve entidades externas: las declaraciones de entidad las rechaza en vez de
expandirlas, que es justo lo que hace peligrosos a otros parseadores.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET  # ver la nota sobre XML al final del docstring
from dataclasses import dataclass
from pathlib import Path

from . import CREATE_NO_WINDOW, DEVICE_LABEL, IS_WIN, InstallError

MOUNT_TIMEOUT = 90.0        # VeraCrypt puede pedir UAC y tardar lo suyo
MOUNT_POLL = 0.5
PASSWORD_MARK = "***"

FILE_SUPPORTS_SPARSE_FILES = 0x00000040     # winnt.h
SONDA_BYTES = 8 * 1024 ** 2                 # lo que se escribe para medir
SONDA_NOMBRE = ".prdrive-sonda.tmp"

WIN_CANDIDATES = {
    "mount": ["VeraCrypt.exe", r"C:\Program Files\VeraCrypt\VeraCrypt.exe",
              r"C:\Program Files (x86)\VeraCrypt\VeraCrypt.exe"],
    "format": ["VeraCrypt Format.exe",
               r"C:\Program Files\VeraCrypt\VeraCrypt Format.exe",
               r"C:\Program Files (x86)\VeraCrypt\VeraCrypt Format.exe"],
}
POSIX_CANDIDATES = [
    "veracrypt", "/usr/bin/veracrypt", "/usr/local/bin/veracrypt",
    "/Applications/VeraCrypt.app/Contents/MacOS/VeraCrypt",
]

FILESYSTEMS = ("exFAT", "NTFS", "FAT") if IS_WIN else ("exFAT", "NTFS", "ext4")


# ---------------------------------------------------------------------------
# Localizar VeraCrypt
# ---------------------------------------------------------------------------

def _first_exe(candidatos: list[str]) -> str | None:
    for c in candidatos:
        if os.sep in c or (os.altsep and os.altsep in c):
            if Path(c).is_file():
                return c
        else:
            found = shutil.which(c)
            if found:
                return found
    return None


def find_veracrypt(extra_dir: str | Path | None = None) -> dict | None:
    """Los ejecutables de VeraCrypt, o None.

    En Windows son dos binarios distintos (montar y formatear); en Linux y macOS
    los dos papeles los hace el mismo `veracrypt --text`. `extra_dir` es la
    carpeta que indique el usuario cuando no está donde se espera."""
    if IS_WIN:
        candidatos = dict(WIN_CANDIDATES)
        if extra_dir:
            d = Path(extra_dir)
            candidatos = {
                "mount": [str(d / "VeraCrypt.exe")] + candidatos["mount"],
                "format": [str(d / "VeraCrypt Format.exe")] + candidatos["format"],
            }
        mount, fmt = _first_exe(candidatos["mount"]), _first_exe(candidatos["format"])
        return {"mount": mount, "format": fmt} if mount and fmt else None

    candidatos = list(POSIX_CANDIDATES)
    if extra_dir:
        candidatos.insert(0, str(Path(extra_dir) / "veracrypt"))
        candidatos.insert(0, str(extra_dir))
    vc = _first_exe(candidatos)
    return {"mount": vc, "format": vc} if vc else None


# ---------------------------------------------------------------------------
# Tamaños y letras
# ---------------------------------------------------------------------------

UNIDADES = {"k": 1024, "m": 1024 ** 2, "g": 1024 ** 3, "t": 1024 ** 4}
MARGEN = 50 * 1024 ** 2         # lo que se deja libre al pedir 'max'


def size_to_bytes(raw: str, free: int) -> int:
    """'20G' / '500M' / 'max' -> bytes."""
    texto = str(raw).strip().lower()
    if texto in {"max", ""}:
        return max(0, free - MARGEN)
    try:
        if texto[-1] in UNIDADES:
            return int(float(texto[:-1].replace(",", ".")) * UNIDADES[texto[-1]])
        return int(float(texto.replace(",", ".")))
    except (ValueError, IndexError) as e:
        raise InstallError(
            f"No entiendo el tamaño '{raw}'. Usa 20G, 500M o 'max'.") from e


# Sin dispersos, cada giga propuesto es un giga que hay que ESCRIBIR en la
# unidad antes de poder seguir instalando. Proponer casi el disco entero —lo que
# se hacía— convierte un disco de 1 TB en una espera de horas, y encima de un
# contenedor que casi nadie va a llenar. Con dispersos no cuesta nada y el
# tamaño deja de ser una decisión.
TOPE_SIN_DISPERSOS = 64 * 1024 ** 3     # a partir de aquí no se propone más


def suggested_size(free: int, dinamico: bool = False) -> str:
    """Lo que se propone por defecto.

    Con contenedor dinámico, `max`: solo ocupa lo que se guarde dentro. Sin él,
    el hueco menos un giga de respiro pero con tope, porque ese número es
    minutos de escritura (ver la sección «Cuánto tarda»)."""
    if dinamico:
        return "max"
    gib = min(max(0, free - 1024 ** 3), TOPE_SIN_DISPERSOS) / 1024 ** 3
    return f"{max(1, int(gib))}G"


def free_drive_letter(preferida: str = "P") -> str:
    """Una letra libre. Sin PowerShell: preguntarle al kernel es instantáneo y no
    abre ninguna ventana."""
    if not IS_WIN:
        return ""
    import ctypes
    mask = ctypes.windll.kernel32.GetLogicalDrives()
    usadas = {chr(65 + i) for i in range(26) if mask & (1 << i)}
    for letra in [preferida.upper(), *"PQRSTUVWXYZNMLKJIHGFED"]:
        if letra and letra not in usadas:
            return letra
    raise InstallError("No queda ninguna letra de unidad libre.")


# ---------------------------------------------------------------------------
# Cuánto tarda, y cómo dejar de tardar
# ---------------------------------------------------------------------------
#
# Crear el contenedor en un disco externo tarda muchísimo más que en el interno,
# y la culpa NO es del cifrado. Con `/quick` sobre un contenedor-fichero,
# `FormatVolume()` preasigna el fichero con `SetEndOfFile()` y después
# `FormatNoFs()` entra en la rama `else if (!bDevice && !hiddenVol)`, que escribe
# un sector a cero cada 128 MiB *a propósito* —su propio comentario lo dice:
# «forcing Windows to allocate the disk space of each 128 MiB chunk
# immediately»—. Cada una de esas escrituras cae más allá del valid data length,
# así que NTFS rellena de ceros todo el hueco anterior: se acaba escribiendo el
# contenedor entero. En un SSD interno a 500 MB/s no se nota; en un USB a
# 30 MB/s son media hora por cada 50 GiB. (src/Common/Format.c, tag
# VeraCrypt_1.26.24.)
#
# La salida es `/dynamic`: el fichero se marca como disperso con FSCTL_SET_SPARSE
# (Format.c:407, que además exige quickFormat, ya se pasa) y entonces esa
# caminata solo asigna un clúster por tramo, porque NTFS no materializa el hueco.
# La creación pasa a segundos sea cual sea el tamaño. Lo que se paga: el
# contenedor deja de tener negación plausible —se ve cuánto ocupa de verdad— y
# si la unidad se llena, el volumen de dentro da errores de E/S.

def soporta_dispersos(root: str | Path) -> bool:
    """¿Admite ficheros dispersos el sistema de ficheros de `root`?

    Es LA pregunta de la que depende que crear el contenedor tarde segundos o
    media hora, y hay que contestarla ANTES: al recibir `/dynamic`, VeraCrypt
    hace esta misma consulta y **aborta** con ERR_DYNAMIC_NOT_SUPPORTED si sale
    que no (Tcformat.c:6338). Por eso se pregunta por la bandera y no por el
    nombre del sistema de ficheros: es la misma prueba que hace él, y así no hay
    que mantener aquí una lista de qué sistemas la cumplen.

    En POSIX devuelve False porque `--dynamic` no existe en su CLI (ver
    `create_command`), no porque ext4 no sepa de dispersos.

    Función de módulo para que los tests la sustituyan, como
    `_leer_estado_bitlocker()`."""
    if not IS_WIN:
        return False
    import ctypes
    from ctypes import byref, c_wchar_p, create_unicode_buffer
    from ctypes.wintypes import DWORD

    ruta = str(root)
    if not ruta.endswith(("\\", "/")):
        ruta += "\\"
    flags = DWORD(0)
    try:
        nombre = create_unicode_buffer(261)         # MAX_PATH + 1
        ok = ctypes.windll.kernel32.GetVolumeInformationW(
            c_wchar_p(ruta), None, 0, None, None, byref(flags), nombre, 261)
    except OSError:
        return False
    return bool(ok) and bool(flags.value & FILE_SUPPORTS_SPARSE_FILES)


def medir_escritura(root: str | Path, muestra: int = SONDA_BYTES) -> float | None:
    """Bytes por segundo que admite esa unidad, medidos. None si no se puede.

    Sirve para poder decir «≈ 14 min» en vez de «esto puede tardar bastante»,
    que es lo único honesto cuando no hay dispersos y hay que escribir el
    contenedor entero. El `fsync` no es opcional: sin él se mediría la caché del
    sistema, que en un USB miente por un orden de magnitud. La sonda se borra
    siempre, también si falla a medias.

    Función de módulo: los tests la sustituyen, y así ninguno escribe nada."""
    sonda = Path(root) / SONDA_NOMBRE
    bloque = b"\0" * (1024 ** 2)
    vueltas = max(1, muestra // len(bloque))
    try:
        inicio = time.monotonic()
        with open(sonda, "wb") as f:
            for _ in range(vueltas):
                f.write(bloque)
            f.flush()
            os.fsync(f.fileno())
        transcurrido = time.monotonic() - inicio
    except OSError:
        return None
    finally:
        try:
            sonda.unlink()
        except OSError:
            pass
    if transcurrido <= 0:
        return None
    return (vueltas * len(bloque)) / transcurrido


def estimar_creacion(root: str | Path, size_bytes: int) -> float | None:
    """Segundos que va a costar escribir un contenedor de ese tamaño, o None.

    Solo describe el caso lento —el que hay que escribir entero—. Con contenedor
    dinámico no se escribe el volumen y esto no se pregunta: quien llama lo sabe
    por `soporta_dispersos()`."""
    velocidad = medir_escritura(root)
    if not velocidad:
        return None
    return size_bytes / velocidad


def describir_espera(segundos: float | None) -> str:
    """La estimación, en algo que se pueda leer de un vistazo."""
    if segundos is None:
        return "no he podido medir la velocidad de la unidad"
    if segundos < 90:
        return "menos de dos minutos"
    if segundos < 3600:
        return f"unos {round(segundos / 60)} min"
    return f"unas {segundos / 3600:.1f} h"


# ---------------------------------------------------------------------------
# Las órdenes de VeraCrypt
# ---------------------------------------------------------------------------

def redact(cmd: list[str], password: str) -> list[str]:
    """La misma orden, con la contraseña tapada. Para enseñar o registrar.

    Se compara por valor y no por posición porque la contraseña aparece pegada al
    flag en unas formas (`--password=X`) y suelta en otras (`/password X`)."""
    limpio = []
    for arg in cmd:
        if password and arg == password:
            limpio.append(PASSWORD_MARK)
        elif password and password in arg:
            limpio.append(arg.replace(password, PASSWORD_MARK))
        else:
            limpio.append(arg)
    return limpio


def create_command(vc: dict, container: Path, size_bytes: int, password: str,
                   filesystem: str, dinamico: bool = False) -> list[str]:
    """La orden de crear el contenedor.

    `/quick` (Windows) evita rellenar el fichero entero de datos ALEATORIOS, que
    en un contenedor de varios gigas sobre USB son horas. A cambio, el espacio
    libre de dentro no queda indistinguible del contenido: no es un problema
    para un dispositivo de trabajo, pero conviene saberlo. Ojo: `/quick` no
    evita que se escriba el contenedor entero de CEROS —eso es `dinamico`, y la
    sección «Cuánto tarda» explica por qué.

    `dinamico` añade `/dynamic`, y quien llama tiene que haber preguntado antes
    por `soporta_dispersos()`: sobre exFAT, VeraCrypt aborta."""
    if IS_WIN:
        extra = ["/dynamic"] if dinamico else []
        return [vc["format"], "/create", str(container),
                "/size", str(size_bytes), "/password", password,
                "/encryption", "AES", "/hash", "sha512",
                "/filesystem", filesystem, "/pim", "0",
                *extra, "/quick", "/silent", "/force"]
    # --stdin: en Linux la contraseña va por la entrada estándar y no aparece en
    # la lista de procesos.
    #
    # Aquí NO hay equivalente de /dynamic —no existe en su CLI— y `--quick`
    # tampoco sirve: en el tag VeraCrypt_1.26.24, TextUserInterface.cpp fuerza
    # `options->Quick = false` en la rama del contenedor-fichero, así que el
    # volumen se escribe entero pase lo que pase y lo único que queda es elegir
    # bien el tamaño. En `master` esa línea ya no está y `--quick` pasa a valer
    # también para contenedores; cuando eso llegue a una release, se revisa.
    return [vc["format"], "--text", "--create", str(container),
            "--volume-type=normal", f"--size={size_bytes}",
            "--encryption=AES", "--hash=sha512", f"--filesystem={filesystem}",
            "--pim=0", "--keyfiles=", "--random-source=/dev/urandom",
            "--stdin", "--non-interactive"]


def mount_command(vc: dict, container: Path, password: str,
                  destino: str | Path, etiqueta: str = "") -> list[str]:
    """La orden de montar.

    `/m rm` monta como MEDIO EXTRAÍBLE, y no es un adorno: sin él Windows crea
    `System Volume Information` y `$RECYCLE.BIN` DENTRO del contenedor —o sea,
    dentro de lo que mira rclone— y además fuerza más desmontajes. `/m` se puede
    repetir: el propio `autorun.inf` que genera VeraCrypt emite `/m rm` y
    `/m ro` en la misma orden (Mount.c, TravelerDlgProc).

    `/m label=` es solo cómo lo llama el Explorador; no toca el sistema de
    ficheros de dentro, así que no depende de haberlo formateado de una manera.

    En POSIX no se pasa `rm`: su propio parser lo tiene bajo `#ifdef TC_WINDOWS`
    (CommandLineInterface.cpp) y allí no hace falta, porque Linux no deja esas
    carpetas."""
    if IS_WIN:
        etiquetado = ["/m", f"label={etiqueta}"] if etiqueta else []
        return [vc["mount"], "/volume", str(container), "/letter", str(destino),
                "/password", password, "/pim", "0", "/cache", "n",
                "/m", "rm", *etiquetado, "/quit", "/silent"]
    return [vc["mount"], "--text", str(container), str(destino),
            "--pim=0", "--keyfiles=", "--protect-hidden=no",
            "--stdin", "--non-interactive"]


def dismount_command(vc: dict, punto: Path) -> list[str]:
    if IS_WIN:
        # En Windows se desmonta por letra, no por ruta.
        return [vc["mount"], "/dismount", str(punto)[0], "/quit", "/silent"]
    return [vc["mount"], "--text", "--dismount", str(punto), "--non-interactive"]


def _run(cmd: list[str], password: str = "", timeout: float | None = None):
    """Lanza una orden de VeraCrypt.

    En POSIX la contraseña va por la entrada estándar (`--stdin`) y así no
    aparece en la lista de procesos. En Windows su CLI no lo admite y va como
    argumento; ahí lo único que se puede hacer es no repetirlo en ningún sitio
    (ver `redact`). La entrada se cierra cuando no se usa: esto corre sin
    terminal y una orden esperando una respuesta se quedaría colgada."""
    kwargs: dict = {"text": True, "encoding": "utf-8", "errors": "replace",
                    "capture_output": True}
    if IS_WIN:
        kwargs["creationflags"] = CREATE_NO_WINDOW
        kwargs["stdin"] = subprocess.DEVNULL
    elif password:
        kwargs["input"] = password + "\n"
    else:
        kwargs["stdin"] = subprocess.DEVNULL
    if timeout is not None:
        kwargs["timeout"] = timeout
    return subprocess.run(cmd, **kwargs)


# ---------------------------------------------------------------------------
# Crear, montar, desmontar
# ---------------------------------------------------------------------------

def create_container(vc: dict, container: Path, size_bytes: int, password: str,
                     filesystem: str = "exFAT", dinamico: bool = False) -> None:
    """Crea el contenedor. Lanza InstallError con lo que dijo VeraCrypt."""
    if container.exists():
        raise InstallError(
            f"Ya existe {container}. Si quieres rehacerlo, bórralo tú a mano: "
            "el instalador no borra contenedores.")
    cmd = create_command(vc, container, size_bytes, password, filesystem, dinamico)
    try:
        res = _run(cmd, password)
    except OSError as e:
        raise InstallError(f"No he podido lanzar VeraCrypt: {e}") from e
    if res.returncode != 0 or not container.exists():
        raise InstallError(
            "VeraCrypt no ha podido crear el contenedor "
            f"(código {res.returncode}).\n\n{_salida(res)}")


def wait_until_readable(punto: Path, timeout: float = MOUNT_TIMEOUT) -> bool:
    """Espera a que el punto de montaje se pueda LEER de verdad.

    Que exista la letra no basta: entre que VeraCrypt dice que ha montado y que
    el volumen contesta pasa un rato, y en ese hueco un `iterdir()` falla."""
    limite = time.monotonic() + timeout
    while time.monotonic() < limite:
        try:
            # Con `default` no lanza StopIteration, así que un volumen recién
            # formateado —vacío— también cuenta como legible.
            next(iter(punto.iterdir()), None)
            return True
        except OSError:
            pass            # todavía no está, o está a medio montar
        time.sleep(MOUNT_POLL)
    return False


def en_uso(container: Path) -> bool:
    """¿Tiene alguien abierto el contenedor? Casi siempre: ya está montado.

    Mismo truco que `components.rclone_en_uso()`: se abre para escritura, que
    contesta sin enumerar procesos. Mientras el volumen está montado, VeraCrypt
    mantiene el `.hc` abierto en exclusiva y Windows devuelve
    ERROR_SHARING_VIOLATION.

    En POSIX esto NO es una respuesta: allí el contenedor se abre por un
    dispositivo de bucle y un segundo `open()` no molesta a nadie. Por eso
    `mounted_container()` pregunta a VeraCrypt y solo cae aquí en Windows."""
    try:
        if not Path(container).is_file():
            return False
        with open(container, "r+b"):
            return False
    except OSError:
        return True


def _volumenes_con_control() -> list[Path]:
    """Las unidades montadas que llevan el fichero de control de prdrive.

    Indirección de módulo, como `_leer_estado_bitlocker()`: los tests la
    sustituyen y así el barrido de unidades no entra en la batería."""
    from . import device
    return [v.root for v in device.list_volumes() if v.has_control]


def mounted_container(vc: dict, container: Path) -> Path | None:
    """Dónde está YA montado ese contenedor, o None.

    En POSIX se le pregunta a VeraCrypt: `--text --list` imprime, por volumen
    montado, la ruta del anfitrión y el punto de montaje
    (CommandLineInterface.cpp registra `--list`). Respuesta exacta.

    En Windows NO hay listado por línea de órdenes —el suyo vive en el driver— y
    hay que ir por el otro lado, con dos condiciones que tienen que darse las
    dos. La primera es `en_uso()`, y es la que impide el falso positivo que
    importa: sin ella, otro prdrive enchufado a la vez —con su fichero de
    control, como es natural— se leería como «aquí está montado el nuestro», y el
    instalador seguiría adelante sobre el dispositivo equivocado. La segunda es
    que haya **exactamente una** unidad candidata, por lo mismo que
    `Conflicto.version(lado)` devuelve None con cero o con dos: cuando hay dos,
    adivinar es peor que no saberlo.

    La asimetría es real y se dice en vez de disimularse: en Windows, un
    contenedor recién creado —que todavía no tiene fichero de control— no se
    reconoce aquí, y el que llama acaba intentando el montaje. No pasa nada: el
    mensaje de `explicar_montaje()` sí sabe leer `en_uso()`."""
    if not IS_WIN:
        try:
            res = _run([vc["mount"], "--text", "--list", "--non-interactive"],
                       timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            return None
        for linea in (res.stdout or "").splitlines():
            # «1: /ruta/PRDRIVE.hc /dev/mapper/veracrypt1 /media/veracrypt1»,
            # y un volumen sin montar deja un '-' en el último campo.
            partes = linea.split()
            if (len(partes) >= 4 and partes[1] == str(container)
                    and partes[3] != "-"):
                return Path(partes[3])
        return None

    if not en_uso(container):
        return None         # nadie lo tiene abierto: no está montado, y punto
    fisico = Path(container).parent
    candidatos = [r for r in _volumenes_con_control() if r != fisico]
    return candidatos[0] if len(candidatos) == 1 else None


def mount_container(vc: dict, container: Path, password: str,
                    letra: str | None = None,
                    etiqueta: str = DEVICE_LABEL) -> Path:
    """Monta el contenedor y devuelve dónde ha quedado.

    NO se mira el código de retorno para decidir si ha ido bien: VeraCrypt eleva
    por UAC a un proceso aparte y lo que devuelve el que lanzamos no dice nada del
    montaje. Lo que decide es que el punto de montaje se pueda leer.

    Si ya estaba montado no se vuelve a montar: montar dos veces el mismo
    contenedor da una segunda letra o un error, y ninguna de las dos cosas es lo
    que quiere quien vuelve atrás en el asistente."""
    if not container.is_file():
        raise InstallError(f"No existe el contenedor {container}.")

    ya = mounted_container(vc, container)
    if ya is not None and wait_until_readable(ya, timeout=MOUNT_POLL):
        return ya

    if IS_WIN:
        destino = (letra or free_drive_letter()).rstrip(":").upper()
        punto = Path(f"{destino}:\\")
    else:
        punto = Path(tempfile.mkdtemp(prefix="prdrive-mnt-"))
        destino = punto

    cmd = mount_command(vc, container, password, destino, etiqueta)
    try:
        res = _run(cmd, password, timeout=MOUNT_TIMEOUT)
    except subprocess.TimeoutExpired:
        res = None      # puede haber montado igualmente; lo dice el punto
    except OSError as e:
        raise InstallError(f"No he podido lanzar VeraCrypt: {e}") from e

    if wait_until_readable(punto):
        return punto

    detalle = _salida(res) if res is not None else "VeraCrypt no ha respondido a tiempo."
    raise InstallError(
        f"El contenedor no se ha montado en {punto}.\n\n{detalle}\n\n"
        + explicar_montaje(res, container))


def dismount(vc: dict, punto: Path) -> None:
    """Desmonta. Que falle no es grave: el usuario puede hacerlo desde VeraCrypt."""
    try:
        res = _run(dismount_command(vc, punto), timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise InstallError(f"No he podido desmontar {punto}: {e}") from e
    if res.returncode != 0:
        raise InstallError(
            f"VeraCrypt no ha podido desmontar {punto} (código {res.returncode}).\n\n"
            f"{_salida(res)}\n\n¿Hay algún programa usando la unidad?")


def _salida(res) -> str:
    if res is None:
        return ""
    return ((res.stdout or "") + "\n" + (res.stderr or "")).strip() or "(sin salida)"


# Agujas concretas en lo que dice VeraCrypt, y su traducción. Mismo criterio que
# `sync.KNOWN_ERRORS`: lo específico primero y, si no casa nada, el texto general
# SIN inventarse una causa. Se comparan en minúsculas.
FALLOS_MONTAJE = (
    ("incorrect password", "La contraseña no es la de este contenedor."),
    ("not a veracrypt volume",
     "Ese fichero no es un contenedor de VeraCrypt, o está dañado."),
    ("administrator privileges",
     "VeraCrypt no ha conseguido permisos de administrador: o se canceló el "
     "aviso, o este usuario no puede darlos."),
    ("no such file", "VeraCrypt dice que no encuentra el contenedor."),
)


def explicar_montaje(res, container: Path) -> str:
    """Por qué no aparece montado el contenedor.

    En Windows `/silent` se traga los mensajes y el código de retorno no dice
    nada del montaje, así que lo normal es no tener ninguna aguja que buscar; ahí
    lo único que se puede afirmar es lo que se ha COMPROBADO —que el fichero
    está abierto— y, si tampoco, el texto general, que dice «lo más habitual» y
    no «ha pasado esto». Una causa inventada es peor que ninguna."""
    salida = _salida(res).lower()
    for aguja, explicacion in FALLOS_MONTAJE:
        if aguja in salida:
            return explicacion
    if IS_WIN and en_uso(container):
        return ("El contenedor está abierto, así que lo más probable es que YA "
                "esté montado: en otra unidad, o por otro usuario. Míralo en "
                "VeraCrypt antes de volver a intentarlo.")
    return ("Lo más habitual: la contraseña no es esa, o se ha cancelado el "
            "aviso de permisos de administrador que pide VeraCrypt para montar.")


# ---------------------------------------------------------------------------
# El favorito: que VeraCrypt monte solo al conectar el dispositivo
# ---------------------------------------------------------------------------

def veracrypt_config_dir() -> Path:
    if IS_WIN:
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "VeraCrypt"
    return Path.home() / ".VeraCrypt"


FAVORITES_FILE = "Favorite Volumes.xml"
CONFIG_FILE = "Configuration.xml"


def volume_guid_path(root: str | Path) -> str | None:
    """`\\\\?\\Volume{GUID}\\` de esa unidad, o None si Windows no lo da.

    Indirección de módulo: los tests la sustituyen, y en POSIX no existe."""
    if not IS_WIN:
        return None
    import ctypes
    from ctypes import c_wchar_p, create_unicode_buffer

    ruta = str(root)
    if not ruta.endswith(("\\", "/")):
        ruta += "\\"
    LARGO = 60          # «\\?\Volume{...}\» son 49; el resto es margen
    buf = create_unicode_buffer(LARGO)
    try:
        ok = ctypes.windll.kernel32.GetVolumeNameForVolumeMountPointW(
            c_wchar_p(ruta), buf, LARGO)
    except OSError:
        return None
    return buf.value or None if ok else None


def ruta_favorita(container: Path) -> str:
    """La ruta del contenedor tal como conviene guardarla en el favorito.

    `P:\\PRDRIVE.hc` deja de valer en cuanto la unidad coge otra letra en otro
    equipo, que en un dispositivo portátil es la norma. La forma
    `\\\\?\\Volume{GUID}\\PRDRIVE.hc` no depende de la letra, y es una que
    VeraCrypt ya maneja en sus favoritos (Favorites.cpp busca `Volume{` en la
    ruta guardada).

    Si Windows no la da, se queda la de siempre: una ruta que funciona hoy es
    mejor que ninguna. Y ojo, esto arregla encontrar el CONTENEDOR, no la letra
    donde se monta —eso sigue siendo el `mountpoint`, con la trampa que avisa
    `write_favorite()`."""
    guid = volume_guid_path(Path(container).parent)
    if not guid:
        return str(container)
    return guid.rstrip("\\/") + "\\" + Path(container).name


def write_favorite(container: Path, letra: str,
                   label: str = DEVICE_LABEL) -> list[str]:
    """Registra el contenedor como favorito con montaje al conectar el dispositivo.

    Es lo que tapa el hueco que deja VeraCrypt: puede montar solo al aparecer el
    dispositivo, pero no sabe lanzar nada después, así que sigue haciendo falta
    penwatch. Con las dos cosas, conectar el dispositivo basta.

    OJO, y hay que decírselo al usuario: esto escribe en la configuración de OTRA
    aplicación. Se deja copia de lo que hubiera, y como el formato es de
    VeraCrypt y puede cambiar entre versiones, conviene confirmarlo abriendo
    VeraCrypt > Favoritos > Organizar volúmenes favoritos. Además, la propia
    documentación de VeraCrypt avisa de que si la letra guardada está ocupada,
    NO monta y NO dice nada."""
    carpeta = veracrypt_config_dir()
    if not carpeta.is_dir():
        raise InstallError(
            f"No encuentro la configuración de VeraCrypt en {carpeta}. "
            "Abre VeraCrypt una vez y vuelve a intentarlo.")

    hechos = []
    destino = carpeta / FAVORITES_FILE
    if destino.exists():
        copia = destino.with_suffix(destino.suffix + ".prdrive.bak")
        shutil.copy2(destino, copia)
        hechos.append(f"Copia de los favoritos anteriores en {copia.name}")

    raiz = ET.Element("VeraCrypt")
    favoritos = ET.SubElement(raiz, "favorites")
    # `removable` es el `/m rm` del montaje a mano: sin él Windows crea
    # `System Volume Information` y `$RECYCLE.BIN` dentro del contenedor.
    # `useLabelInExplorer` solo lo respeta VeraCrypt si NO es de solo lectura
    # (Favorites.cpp), así que los dos van juntos.
    volumen = ET.SubElement(favoritos, "volume", {
        "mountpoint": f"{letra.rstrip(':').upper()}:",
        "mountOnArrival": "1",
        "mountOnLogOn": "0",
        "noHotKeyMount": "0",
        "readonly": "0",
        "removable": "1",
        "system": "0",
        "openExplorerWindow": "0",
        "useLabelInExplorer": "1",
        "label": label,
    })
    volumen.text = ruta_favorita(container)
    ET.ElementTree(raiz).write(destino, encoding="utf-8", xml_declaration=True)
    hechos.append(f"Favorito escrito en {destino}")

    if set_config_flag("StartOnLogon", "1"):
        hechos.append("VeraCrypt arrancará al iniciar sesión (hace falta para "
                      "que vigile la llegada del dispositivo)")
    return hechos


def set_config_flag(clave: str, valor: str) -> bool:
    """Cambia una opción del Configuration.xml de VeraCrypt. True si se tocó.

    El montaje al conectar lo hace la tarea en segundo plano de VeraCrypt, que
    solo existe si VeraCrypt está arrancado: sin StartOnLogon, tras reiniciar no
    hay nadie vigilando."""
    destino = veracrypt_config_dir() / CONFIG_FILE
    try:
        arbol = ET.parse(destino)
    except (OSError, ET.ParseError):
        return False
    for nodo in arbol.getroot().iter("config"):
        if nodo.get("key") == clave:
            if (nodo.text or "").strip() == valor:
                return False
            nodo.text = valor
            copia = destino.with_suffix(destino.suffix + ".prdrive.bak")
            try:
                shutil.copy2(destino, copia)
                arbol.write(destino, encoding="utf-8", xml_declaration=True)
            except OSError:
                return False
            return True
    return False


def open_veracrypt(vc: dict) -> None:
    """Abre la ventana de VeraCrypt, para confirmar el favorito a ojo."""
    try:
        kwargs = {"creationflags": CREATE_NO_WINDOW} if IS_WIN else {}
        subprocess.Popen([vc["mount"]], **kwargs)
    except OSError as e:
        raise InstallError(f"No he podido abrir VeraCrypt: {e}") from e


# ---------------------------------------------------------------------------
# BitLocker
# ---------------------------------------------------------------------------

# El estado de BitLocker se lee por la MISMA vía que usa el Explorador para
# pintar el candado: la propiedad `System.Volume.BitLockerProtection` del almacén
# de propiedades del shell. Que sea esa y no otra importa por dos razones:
#
#   * `Get-BitLockerVolume` y `manage-bde -status` le contestan «acceso denegado»
#     a un usuario normal, así que la comprobación tenía que relanzarse elevada.
#     Un .exe sin firmar, corriendo desde %TEMP%, que lanza un PowerShell ELEVADO
#     y con la ventana oculta es —visto desde un antivirus— la forma exacta de un
#     bypass de UAC: Sophos lo paraba con su mitigación 'Lockdown'. Esto no eleva,
#     no lanza ningún proceso y no enseña ninguna ventana.
#   * La clave canónica hay que PEDÍRSELA a Windows con `PSGetPropertyKeyFromName`.
#     La que circula por ahí —la del conjunto System.Volume.*, {9B174B35-…} pid 8—
#     es otra distinta, y con ella la consulta devuelve ERROR_NOT_FOUND.
#
# Lo que se pierde frente a `Get-BitLockerVolume` es el porcentaje: se sabe que
# se está cifrando, no por cuánto va. A cambio se gana la distinción que el
# código anterior no hacía; ver `BitLockerStatus.protected`.
IID_ISHELLITEM2 = "{7E9FB0D3-919F-4307-AB2E-9B1860310C93}"
PKEY_BITLOCKER_FMTID = "{2D15A9A1-A556-4189-91AD-027458F11A07}"
PKEY_BITLOCKER_PID = 1717

# La enumeración es de Windows, no nuestra: se relee cuando haga falta pasándole
# cada valor a `PSFormatForDisplay` con esa misma clave.
BDE_ON = 1                   # cifrado Y protegido: el único estado que vale
BDE_OFF = 2
BDE_ENCRYPTING = 3
BDE_DECRYPTING = 4
BDE_SUSPENDED = 5
BDE_LOCKED = 6
BDE_NOT_ENCRYPTABLE = 7
BDE_WAITING = 8              # activado, pero con la clave TODAVÍA en claro

BDE_TEXTOS = {
    BDE_ON: "cifrado con BitLocker y protegido",
    BDE_OFF: "el volumen NO está cifrado con BitLocker",
    BDE_ENCRYPTING: "cifrándose ahora mismo; espera a que Windows termine",
    BDE_DECRYPTING: "descifrándose: BitLocker se está quitando de este volumen",
    BDE_SUSPENDED: "cifrado, pero con la protección SUSPENDIDA: la clave está "
                   "accesible en el propio disco",
    BDE_LOCKED: "cifrado y BLOQUEADO: desbloquéalo para poder instalar",
    BDE_NOT_ENCRYPTABLE: "este volumen no se puede cifrar con BitLocker",
    BDE_WAITING: "BitLocker activado pero SIN proteger todavía: la clave sigue "
                 "guardada en claro a la espera de reiniciar",
}


@dataclass(frozen=True)
class BitLockerStatus:
    """Lo que se sabe del cifrado de un volumen.

    `known=False` no es «no está cifrado»: es «no he podido comprobarlo».
    Distinguirlo importa, porque decirle a alguien que su dispositivo está
    cifrado sin haberlo mirado es peor que no decir nada."""
    known: bool
    state: int = 0
    detail: str = ""

    @property
    def protected(self) -> bool:
        """Cifrado Y con la protección puesta. Lo único que autoriza a seguir.

        Antes esto se calculaba como «VolumeStatus empieza por FullyEncrypted, o
        el porcentaje pasa de cero», y el `ProtectionStatus` que la consulta sí
        pedía se tiraba sin llegar a leerlo. Un volumen recién activado —el
        estado 'Waiting for activation'— está cifrado, se lee sin problemas y
        tiene su clave guardada EN CLARO en el propio disco esperando un
        reinicio: pasaba la comprobación, y encima de él se dejaba la clave
        privada del remoto. Aquí solo vale 'On'."""
        return self.state == BDE_ON

    @property
    def resumen(self) -> str:
        if not self.known:
            return f"sin comprobar — {self.detail}"
        return BDE_TEXTOS.get(self.state, f"estado desconocido ({self.state})")


def _leer_estado_bitlocker(ruta: str) -> int:
    """El valor de `System.Volume.BitLockerProtection` de un volumen.

    Con ctypes y a mano porque el proyecto no admite dependencias y la biblioteca
    estándar no trae COM. Son tres llamadas: crear el item del shell para esa
    ruta, pedirle la propiedad como entero, y soltarlo."""
    import ctypes
    from ctypes import POINTER, byref, c_int, c_void_p, c_wchar_p
    from ctypes.wintypes import DWORD, ULONG

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
                    ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]

    class PROPERTYKEY(ctypes.Structure):
        _fields_ = [("fmtid", GUID), ("pid", DWORD)]

    ole32 = ctypes.windll.ole32
    shell32 = ctypes.windll.shell32

    def guid(texto: str) -> GUID:
        g = GUID()
        if ole32.CLSIDFromString(c_wchar_p(texto), byref(g)) < 0:
            raise OSError(f"GUID ilegible: {texto}")
        return g

    clave = PROPERTYKEY()
    clave.fmtid = guid(PKEY_BITLOCKER_FMTID)
    clave.pid = PKEY_BITLOCKER_PID
    iid = guid(IID_ISHELLITEM2)

    # COINIT_APARTMENTTHREADED. Hay que inicializar COM en ESTE hilo, sea cual
    # sea. Un HRESULT negativo aquí es RPC_E_CHANGED_MODE: COM ya estaba puesto
    # en el otro modelo, que para esto sirve igual. Solo se cierra lo que se haya
    # abierto aquí, porque cerrar de más se lleva por delante el COM de los demás.
    hr_init = ole32.CoInitializeEx(None, 2)
    try:
        item = c_void_p()
        hr = shell32.SHCreateItemFromParsingName(
            c_wchar_p(ruta), None, byref(iid), byref(item))
        if hr < 0 or not item:
            raise OSError(f"SHCreateItemFromParsingName: 0x{hr & 0xFFFFFFFF:08X}")
        vtbl = ctypes.cast(item, POINTER(POINTER(c_void_p))).contents
        try:
            # Huecos de la vtabla de IShellItem2: el 2 es Release, de IUnknown, y
            # el 16 es GetInt32 —detrás de los 3 de IUnknown, los 5 de IShellItem
            # y los 8 primeros de IShellItem2—.
            get_int32 = ctypes.WINFUNCTYPE(
                ctypes.c_long, c_void_p, POINTER(PROPERTYKEY),
                POINTER(c_int))(vtbl[16])
            valor = c_int(0)
            hr = get_int32(item, byref(clave), byref(valor))
            if hr < 0:
                raise OSError(f"IShellItem2::GetInt32: 0x{hr & 0xFFFFFFFF:08X}")
            return valor.value
        finally:
            ctypes.WINFUNCTYPE(ULONG, c_void_p)(vtbl[2])(item)
    finally:
        if hr_init >= 0:
            ole32.CoUninitialize()


def bitlocker_status(letra: str) -> BitLockerStatus:
    """Estado de BitLocker de una unidad. Ni eleva, ni lanza nada, ni tarda.

    Cualquier fallo sale como `known=False`, y esa es la dirección segura: quien
    llama solo deja seguir con `protected`, así que no poder comprobarlo frena el
    asistente en vez de dejarlo pasar. Por eso se captura `Exception` y no una
    lista de tipos: aquí debajo hay COM, y equivocarse de excepción significaría
    dar por buena una unidad sin haberla mirado."""
    if not IS_WIN:
        return BitLockerStatus(False, detail="BitLocker es solo de Windows.")
    letra = letra.rstrip(":").upper()
    try:
        estado = _leer_estado_bitlocker(f"{letra}:\\")
    except Exception as e:                        # noqa: BLE001 — ver docstring
        return BitLockerStatus(False, detail=f"Windows no ha contestado ({e})")
    if estado not in BDE_TEXTOS:
        return BitLockerStatus(
            False, detail=f"Windows ha devuelto un estado que no conozco ({estado})")
    return BitLockerStatus(known=True, state=estado,
                           detail=f"BitLockerProtection={estado}")


def open_bitlocker_setup(letra: str) -> None:
    """Abre el asistente de BitLocker de Windows para esa unidad.

    Cifrar lo hace Windows, no nosotros: automatizarlo con manage-bde exige
    permisos, tarda mucho y falla de formas distintas en cada edición. Lo que sí
    aporta el instalador es abrirlo en el sitio y comprobar después.

    Dos `os.startfile` y no un PowerShell con dos `Start-Process`: hacen lo mismo
    sin lanzar un intérprete de órdenes, que es justo lo que mira un antivirus.
    `ms-settings:` abre la página de cifrado, y la unidad abre el Explorador, que
    es donde está «Activar BitLocker» en las ediciones que no traen esa página.

    Los dos se intentan por separado, como los dos `Start-Process` de antes: si
    esta edición de Windows no resuelve el `ms-settings:`, lo que no puede pasar
    es que se lleve por delante la ventana del Explorador, que es la que sirve en
    todas. Solo se da por fallado si no se abre ninguna de las dos."""
    if not IS_WIN:
        raise InstallError("BitLocker es solo de Windows.")
    letra = letra.rstrip(":").upper()
    abiertas, fallos = 0, []
    for destino in ("ms-settings:deviceencryption", f"{letra}:\\"):
        try:
            os.startfile(destino)          # type: ignore[attr-defined]
            abiertas += 1
        except OSError as e:
            fallos.append(f"{destino}: {e}")
    if not abiertas:
        raise InstallError("No he podido abrir el asistente de BitLocker.\n\n"
                           + "\n".join(fallos))
