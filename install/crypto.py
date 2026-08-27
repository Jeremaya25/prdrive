#!/usr/bin/env python3
"""
crypto.py — VeraCrypt y BitLocker. Sin Tkinter.

Dos formas de cifrar el dispositivo, con repartos de trabajo muy distintos:

  * **VeraCrypt** hace un contenedor `PRDRIVE.hc` en la raíz del volumen físico. Lo
    crea y lo monta este módulo, y la estructura del dispositivo vive DENTRO. Es lo que
    hace portable el cifrado: no depende de la edición de Windows ni de nada
    instalado en el equipo salvo el propio VeraCrypt.

  * **BitLocker** cifra el volumen entero, y aquí solo se guía y se comprueba:
    cifrar de verdad lo hace el diálogo de Windows. Comprobarlo NO se puede sin
    permisos de administrador —ni `manage-bde` ni `Get-BitLockerVolume` sueltan
    nada sin elevar—, así que «no he podido comprobarlo» es una respuesta de
    primera clase y no se disfraza de «está todo bien».

Dos reglas que no se pueden relajar:

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

from . import CREATE_NO_WINDOW, IS_WIN, InstallError

MOUNT_TIMEOUT = 90.0        # VeraCrypt puede pedir UAC y tardar lo suyo
MOUNT_POLL = 0.5
PASSWORD_MARK = "***"

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


def suggested_size(free: int) -> str:
    """Lo que se propone por defecto: el hueco menos un giga de respiro."""
    gib = free / 1024 ** 3
    return f"{max(1, int(gib) - 1)}G"


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
                   filesystem: str) -> list[str]:
    """La orden de crear el contenedor.

    /quick (Windows) evita rellenar el fichero entero de datos aleatorios, que en
    un contenedor de varios gigas sobre USB son horas. A cambio, el espacio libre
    de dentro no queda indistinguible del contenido: no es un problema para un dispositivo
    de trabajo, pero conviene saberlo."""
    if IS_WIN:
        return [vc["format"], "/create", str(container),
                "/size", str(size_bytes), "/password", password,
                "/encryption", "AES", "/hash", "sha512",
                "/filesystem", filesystem, "/pim", "0",
                "/quick", "/silent", "/force"]
    # --stdin: en Linux la contraseña va por la entrada estándar y no aparece en
    # la lista de procesos. --quick no aplica a contenedores-fichero.
    return [vc["format"], "--text", "--create", str(container),
            "--volume-type=normal", f"--size={size_bytes}",
            "--encryption=AES", "--hash=sha512", f"--filesystem={filesystem}",
            "--pim=0", "--keyfiles=", "--random-source=/dev/urandom",
            "--stdin", "--non-interactive"]


def mount_command(vc: dict, container: Path, password: str,
                  destino: str | Path) -> list[str]:
    if IS_WIN:
        return [vc["mount"], "/volume", str(container), "/letter", str(destino),
                "/password", password, "/pim", "0", "/cache", "n",
                "/quit", "/silent"]
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
                     filesystem: str = "exFAT") -> None:
    """Crea el contenedor. Lanza InstallError con lo que dijo VeraCrypt."""
    if container.exists():
        raise InstallError(
            f"Ya existe {container}. Si quieres rehacerlo, bórralo tú a mano: "
            "el instalador no borra contenedores.")
    cmd = create_command(vc, container, size_bytes, password, filesystem)
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


def mount_container(vc: dict, container: Path, password: str,
                    letra: str | None = None) -> Path:
    """Monta el contenedor y devuelve dónde ha quedado.

    NO se mira el código de retorno para decidir si ha ido bien: VeraCrypt eleva
    por UAC a un proceso aparte y lo que devuelve el que lanzamos no dice nada del
    montaje. Lo que decide es que el punto de montaje se pueda leer."""
    if not container.is_file():
        raise InstallError(f"No existe el contenedor {container}.")

    if IS_WIN:
        destino = (letra or free_drive_letter()).rstrip(":").upper()
        punto = Path(f"{destino}:\\")
    else:
        punto = Path(tempfile.mkdtemp(prefix="prdrive-mnt-"))
        destino = punto

    cmd = mount_command(vc, container, password, destino)
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
        "Lo más habitual: la contraseña no es esa, o se ha cancelado el aviso de "
        "permisos de administrador que pide VeraCrypt para montar.")


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


def write_favorite(container: Path, letra: str, label: str = "PRDRIVE") -> list[str]:
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
    volumen = ET.SubElement(favoritos, "volume", {
        "mountpoint": f"{letra.rstrip(':').upper()}:",
        "mountOnArrival": "1",
        "mountOnLogOn": "0",
        "noHotKeyMount": "0",
        "readonly": "0",
        "removable": "0",
        "system": "0",
        "openExplorerWindow": "0",
        "useLabelInExplorer": "0",
        "label": label,
    })
    volumen.text = str(container)
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

@dataclass(frozen=True)
class BitLockerStatus:
    """Lo que se sabe del cifrado de un volumen.

    `known=False` no es «no está cifrado»: es «no he podido comprobarlo», que es
    lo que pasa siempre sin permisos de administrador. Distinguirlo importa,
    porque decirle a alguien que su dispositivo está cifrado sin haberlo mirado es peor
    que no decir nada."""
    known: bool
    encrypted: bool = False
    unlocked: bool = False
    percent: float = 0.0
    detail: str = ""

    @property
    def resumen(self) -> str:
        if not self.known:
            return f"sin comprobar — {self.detail}"
        if not self.encrypted:
            return "el volumen NO está cifrado con BitLocker"
        estado = "desbloqueado" if self.unlocked else "BLOQUEADO"
        return f"cifrado al {self.percent:g}% y {estado}"


PS_BITLOCKER = (
    "$v = Get-BitLockerVolume -MountPoint '{letra}:' -ErrorAction Stop; "
    "[pscustomobject]@{{ VolumeStatus=[string]$v.VolumeStatus; "
    "ProtectionStatus=[string]$v.ProtectionStatus; LockStatus=[string]$v.LockStatus; "
    "Percent=[double]$v.EncryptionPercentage }} | ConvertTo-Json -Compress"
)


def bitlocker_status(letra: str, elevate: bool = False) -> BitLockerStatus:
    """Estado de BitLocker de una unidad.

    Sin elevar no hay nada que hacer: tanto `manage-bde` como
    `Get-BitLockerVolume` contestan «acceso denegado» a un usuario normal. Con
    `elevate=True` se relanza la consulta pidiendo permisos —solo lectura, es un
    -status— y el usuario verá el aviso de UAC."""
    if not IS_WIN:
        return BitLockerStatus(False, detail="BitLocker es solo de Windows.")
    letra = letra.rstrip(":").upper()
    script = PS_BITLOCKER.format(letra=letra)

    salida = _ps_json(script) if not elevate else _ps_json_elevated(script)
    if not salida:
        return BitLockerStatus(
            False, detail=("hacen falta permisos de administrador"
                           if not elevate else "la consulta con permisos no ha devuelto nada"))
    import json
    try:
        data = json.loads(salida)
    except ValueError:
        return BitLockerStatus(False, detail="respuesta ilegible de Windows")

    volumen = str(data.get("VolumeStatus", ""))
    return BitLockerStatus(
        known=True,
        encrypted=volumen.lower().startswith("fullyencrypted")
        or float(data.get("Percent") or 0) > 0,
        unlocked=str(data.get("LockStatus", "")).lower() != "locked",
        percent=float(data.get("Percent") or 0),
        detail=f"VolumeStatus={volumen}",
    )


def _ps_json(script: str, timeout: float = 30.0) -> str:
    kwargs = {"creationflags": CREATE_NO_WINDOW} if IS_WIN else {}
    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            text=True, encoding="utf-8", errors="replace",
            capture_output=True, timeout=timeout, **kwargs)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return (res.stdout or "").strip() if res.returncode == 0 else ""


def _ps_json_elevated(script: str, timeout: float = 180.0) -> str:
    """La misma consulta, pero elevando. El resultado viaja por un fichero.

    Start-Process -Verb RunAs abre otro proceso con su propia consola, así que no
    se puede leer su salida directamente: se le dice que la escriba y la leemos
    nosotros."""
    tmp = Path(tempfile.mkdtemp(prefix="prdrive-bde-")) / "estado.json"
    interior = script + f" | Out-File -FilePath '{tmp}' -Encoding utf8"
    lanzador = (
        "Start-Process powershell -Verb RunAs -Wait -WindowStyle Hidden "
        f"-ArgumentList '-NoProfile','-NonInteractive','-Command',\"{interior}\""
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", lanzador],
            capture_output=True, text=True, timeout=timeout,
            **({"creationflags": CREATE_NO_WINDOW} if IS_WIN else {}))
        return tmp.read_text(encoding="utf-8-sig").strip()
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return ""
    finally:
        shutil.rmtree(tmp.parent, ignore_errors=True)


PS_RECOVERY = (
    "$v = Get-BitLockerVolume -MountPoint '{letra}:' -ErrorAction Stop; "
    "($v.KeyProtector | Where-Object {{ $_.KeyProtectorType -eq 'RecoveryPassword' }} "
    "| ForEach-Object {{ \"$($_.KeyProtectorId) $($_.RecoveryPassword)\" }}) -join \"`n\""
)


def bitlocker_recovery_key(letra: str) -> str:
    """La clave de recuperación de esa unidad, elevando para poder leerla.

    Devuelve cadena vacía si no se ha podido: no hay clave de recuperación, o el
    usuario ha dicho que no al aviso de permisos."""
    if not IS_WIN:
        return ""
    return _ps_json_elevated(PS_RECOVERY.format(letra=letra.rstrip(":").upper()))


def open_bitlocker_setup(letra: str) -> None:
    """Abre el asistente de BitLocker de Windows para esa unidad.

    Cifrar lo hace Windows, no nosotros: automatizarlo con manage-bde exige
    permisos, tarda mucho y falla de formas distintas en cada edición. Lo que sí
    aporta el instalador es abrirlo en el sitio y comprobar después."""
    if not IS_WIN:
        raise InstallError("BitLocker es solo de Windows.")
    letra = letra.rstrip(":").upper()
    try:
        subprocess.Popen(
            ["powershell", "-NoProfile", "-Command",
             f"Start-Process 'ms-settings:deviceencryption'; "
             f"Start-Process -FilePath 'explorer.exe' -ArgumentList '{letra}:'"],
            creationflags=CREATE_NO_WINDOW)
    except OSError as e:
        raise InstallError(f"No he podido abrir el asistente de BitLocker: {e}") from e
