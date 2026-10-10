"""BitLocker de un volumen, leído sin elevar: lo comparten el instalador y el dispositivo.

Vive en `common/` y no en `install/` porque quien lo pregunta en ejecución es
`common/cifrada.py` (¿puede esta unidad llevar un llavero sin contraseña?), y
`install/` no viaja al dispositivo. `install/crypto.py` lo reexporta con los
nombres de siempre y sigue dando a `estado_de()` su `IS_WIN` y su
`_leer_estado_bitlocker`, que son los que sustituyen sus tests.

También pregunta aquí el agente del equipo, para reconocer una unidad de su
lista que está enchufada pero bloqueada: el nombre de su volumen
(`volumen_de()`, que se lee igual con el volumen bloqueado) y la orden que saca
la ventana de desbloqueo de Windows (`orden_desbloquear()`).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

IID_ISHELLITEM2 = "{7E9FB0D3-919F-4307-AB2E-9B1860310C93}"
"""IID de la interfaz `IShellItem2`."""
PKEY_BITLOCKER_FMTID = "{2D15A9A1-A556-4189-91AD-027458F11A07}"
"""`fmtid` de la clave `System.Volume.BitLockerProtection`.

La canónica hay que PEDÍRSELA a Windows con `PSGetPropertyKeyFromName`: la que
circula por ahí (la del conjunto System.Volume.*, {9B174B35-…} pid 8) es otra
distinta y con ella la consulta devuelve ERROR_NOT_FOUND.
"""
PKEY_BITLOCKER_PID = 1717
"""`pid` de esa clave."""

# Enumeración de Windows, no nuestra: se relee pasando cada valor a
# `PSFormatForDisplay` con esa misma clave.
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
"""Cómo se cuenta cada estado de BitLocker; el único que deja seguir es `BDE_ON`."""


@dataclass(frozen=True)
class BitLockerStatus:
    """Lo que se sabe del cifrado de un volumen.

    `known=False` no es «no está cifrado»: es «no he podido comprobarlo».
    Distinguirlo importa, porque decirle a alguien que su dispositivo está
    cifrado sin haberlo mirado es peor que no decir nada.

    Args:
        known: Si se ha podido comprobar.
        state: El valor de `System.Volume.BitLockerProtection` (los `BDE_*`).
        detail: Qué ha pasado, para enseñarlo.
    """
    known: bool
    state: int = 0
    detail: str = ""

    @property
    def protected(self) -> bool:
        """Indica si el volumen está cifrado Y con la protección puesta.

        Es lo único que autoriza a seguir. Un volumen recién activado (estado
        «Waiting for activation») está cifrado, se lee sin problemas y tiene su
        clave guardada EN CLARO en el propio disco esperando un reinicio: si
        pasara la comprobación, encima de él se dejaría la clave privada del
        remoto. Aquí solo vale `On`.
        """
        return self.state == BDE_ON

    @property
    def locked(self) -> bool:
        """Indica si se ha comprobado que el volumen está cifrado y bloqueado."""
        return self.known and self.state == BDE_LOCKED

    @property
    def present(self) -> bool:
        """Indica si se ha comprobado que el volumen lleva BitLocker, esté como esté.

        Vale cualquier estado conocido menos «sin cifrar» y «no se puede
        cifrar»: un volumen así puede aparecer bloqueado la próxima vez.
        """
        return self.known and self.state not in (BDE_OFF, BDE_NOT_ENCRYPTABLE)

    @property
    def resumen(self) -> str:
        """Devuelve el estado en palabras."""
        if not self.known:
            return f"sin comprobar — {self.detail}"
        return BDE_TEXTOS.get(self.state, f"estado desconocido ({self.state})")


def _leer_estado_bitlocker(ruta: str) -> int:
    """Devuelve el valor de `System.Volume.BitLockerProtection` de un volumen.

    Se lee por la MISMA vía que usa el Explorador para pintar el candado: la
    propiedad del almacén de propiedades del shell. Que sea esa y no otra
    importa por dos razones:
    - `Get-BitLockerVolume` y `manage-bde -status` contestan «acceso denegado»
      a un usuario normal, así que la comprobación tenía que relanzarse
      elevada. Un .exe sin firmar, corriendo desde %TEMP%, que lanza un
      PowerShell ELEVADO y con la ventana oculta es, visto desde un antivirus,
      la forma exacta de un bypass de UAC: Sophos lo paraba con su mitigación
      «Lockdown». Esto no eleva, no lanza ningún proceso y no enseña ninguna
      ventana.
    - La clave canónica hay que pedírsela a Windows (ver
      `PKEY_BITLOCKER_FMTID`).

    Lo que se pierde frente a `Get-BitLockerVolume` es el porcentaje: se sabe
    que se está cifrando, no por cuánto va. A cambio se distingue lo que otras
    formas no distinguían (ver `BitLockerStatus.protected`).

    Es COM a mano con ctypes porque el proyecto no admite dependencias y la
    biblioteca estándar no trae COM. Son tres llamadas: crear el item del shell
    para esa ruta, pedirle la propiedad como entero y soltarlo.
    """
    import ctypes
    from ctypes import POINTER, byref, c_int, c_void_p, c_wchar_p
    from ctypes.wintypes import DWORD, ULONG

    class GUID(ctypes.Structure):
        """Estructura `GUID` de Windows."""
        _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
                    ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]

    class PROPERTYKEY(ctypes.Structure):
        """Estructura `PROPERTYKEY` de Windows."""
        _fields_ = [("fmtid", GUID), ("pid", DWORD)]

    ole32 = ctypes.windll.ole32
    shell32 = ctypes.windll.shell32

    def guid(texto: str) -> GUID:
        """Convierte un texto `{...}` en un `GUID`."""
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
    # en el otro modelo, que para esto sirve igual. Solo se cierra lo que se
    # haya abierto aquí, porque cerrar de más se lleva por delante el COM de
    # los demás.
    hr_init = ole32.CoInitializeEx(None, 2)
    try:
        item = c_void_p()
        hr = shell32.SHCreateItemFromParsingName(
            c_wchar_p(ruta), None, byref(iid), byref(item))
        if hr < 0 or not item:
            raise OSError(f"SHCreateItemFromParsingName: 0x{hr & 0xFFFFFFFF:08X}")
        vtbl = ctypes.cast(item, POINTER(POINTER(c_void_p))).contents
        try:
            # Huecos de la vtabla de IShellItem2: el 2 es Release, de IUnknown,
            # y el 16 es GetInt32, detrás de los 3 de IUnknown, los 5 de
            # IShellItem y los 8 primeros de IShellItem2.
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


def estado_de(letra: str, leer, es_win: bool = os.name == "nt") -> BitLockerStatus:
    """Devuelve el estado de BitLocker de una unidad: ni eleva, ni lanza nada, ni tarda.

    `leer` es quien pregunta a Windows (`_leer_estado_bitlocker`) y `es_win` si
    se está en Windows: el instalador (`install/crypto.py`) los da por sus
    nombres, que son los que sus tests sustituyen.

    Cualquier fallo sale como `known=False`, y esa es la dirección segura:
    quien llama solo deja seguir con `protected`, así que no poder comprobarlo
    frena el asistente en vez de dejarlo pasar. Por eso se captura `Exception`
    y no una lista de tipos: aquí debajo hay COM, y equivocarse de excepción
    significaría dar por buena una unidad sin haberla mirado.
    """
    if not es_win:
        return BitLockerStatus(False, detail="BitLocker es solo de Windows.")
    letra = letra.rstrip(":").upper()
    try:
        estado = leer(f"{letra}:\\")
    except Exception as e:                        # noqa: BLE001 — ver docstring
        return BitLockerStatus(False, detail=f"Windows no ha contestado ({e})")
    if estado not in BDE_TEXTOS:
        return BitLockerStatus(
            False, detail=f"Windows ha devuelto un estado que no conozco ({estado})")
    return BitLockerStatus(known=True, state=estado,
                           detail=f"BitLockerProtection={estado}")


def bitlocker_status(letra: str) -> BitLockerStatus:
    """Devuelve el estado de BitLocker de una unidad, preguntándoselo a Windows."""
    return estado_de(letra, lambda ruta: _leer_estado_bitlocker(ruta))


def _raiz_de_letra(raiz: Path | str) -> str:
    r"""Devuelve `E:\` si esa ruta es la raíz de una letra de unidad; si no, cadena vacía.

    Se decide con las reglas de rutas de Windows en cualquier sistema, para que
    los tests digan lo mismo en Linux.
    """
    ruta = PureWindowsPath(str(raiz))
    letra = ruta.drive
    if len(letra) != 2 or letra[1] != ":" or not letra[0].isalpha():
        return ""
    if ruta != PureWindowsPath(ruta.anchor):
        return ""
    return letra.upper() + "\\"


def _leer_volumen(raiz: str) -> str:
    r"""Devuelve el nombre de volumen (`\\?\Volume{GUID}\`) de la raíz de una letra.

    Lo da el gestor de montajes (`GetVolumeNameForVolumeMountPointW`), no el
    sistema de ficheros: se lee igual con el volumen bloqueado y sin elevar.

    Raises:
        OSError: Si Windows no lo da.
    """
    import ctypes

    largo = 50                   # «\\?\Volume{GUID}\» son 49 caracteres, y el nulo
    nombre = ctypes.create_unicode_buffer(largo)
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    if not k32.GetVolumeNameForVolumeMountPointW(ctypes.c_wchar_p(raiz), nombre, largo):
        raise ctypes.WinError(ctypes.get_last_error())
    return nombre.value


def volumen_de(raiz: Path | str, es_win: bool = os.name == "nt") -> str:
    r"""Devuelve el nombre de volumen de Windows de la raíz de una unidad, en minúsculas.

    Es con lo que el agente reconoce una unidad de su lista cuando no puede
    leerla. Punto de indirección: los tests lo sustituyen, o sustituyen
    `_leer_volumen()`.

    Args:
        raiz: La raíz de una letra (`E:\`).
        es_win: Si se está en Windows.

    Returns:
        El nombre, o una cadena vacía fuera de Windows, si la ruta no es la
        raíz de una letra o si Windows no contesta. No lanza: se pregunta en
        cada recorrido del agente, y un volumen que se va a media pregunta no
        puede dejar sin recorrer los demás.
    """
    letra = _raiz_de_letra(raiz) if es_win else ""
    if not letra:
        return ""
    try:
        return _leer_volumen(letra).lower()
    except Exception:                               # noqa: BLE001 — ver docstring
        return ""


def orden_desbloquear(raiz: Path | str, es_win: bool = os.name == "nt") -> list[str] | None:
    r"""Devuelve la orden que saca la ventana de desbloqueo de BitLocker de una unidad.

    Es la del verbo `unlock-bde` del Explorador («Desbloquear unidad…», en
    `HKCR\Drive\shell`): `bdeunlock.exe` con la raíz de la letra. Va con su
    ruta completa y sin nada más: la contraseña la pide Windows.

    Args:
        raiz: La raíz de una letra (`E:\`).
        es_win: Si se está en Windows.

    Returns:
        La orden, o `None` fuera de Windows, si la ruta no es la raíz de una
        letra o si este Windows no trae `bdeunlock.exe`.
    """
    letra = _raiz_de_letra(raiz) if es_win else ""
    if not letra:
        return None
    sistema = os.environ.get("SystemRoot") or os.environ.get("WINDIR") or r"C:\Windows"
    exe = Path(sistema) / "System32" / "bdeunlock.exe"
    try:
        hay = exe.is_file()
    except OSError:
        hay = False
    return [str(exe), letra] if hay else None
