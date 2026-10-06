#!/usr/bin/env python3
"""Lo que el agente mide fuera antes de sincronizar.

El planificador (`common/planificador.py`) decide con datos; esto los consigue.
Cada sonda es una función de módulo para que los tests pongan la suya, y
ninguna lanza: no saber algo cuenta como «lo normal» (enchufado, red sin
medir), porque dejar de sincronizar por una sonda rota sería peor que
sincronizar en una red cara.
- `energia()`: ¿va a batería, con cuánta, y está el sistema en modo de ahorro
  de energía? Windows con `GetSystemPowerStatus`; Linux con
  `/sys/class/power_supply/*` y el perfil de power-profiles-daemon, leído con
  `common/dbus.py`. Sin power-profiles-daemon no hay ahorro.
- `red_medida()`: ¿es la red de uso medido? Windows con
  `INetworkCostManager::GetCost` (COM por vtabla, como `IShellItem2` en
  `install/crypto.py`); Linux con la propiedad `Metered` de NetworkManager,
  leída con `common/dbus.py`. Sin NetworkManager no se sabe.
- `es_de_red(texto)`: ¿ese fallo de rclone es de la red? Son las mismas agujas
  que `sync.KNOWN_ERRORS` usa para explicarlo y viven aquí porque el agente no
  lleva `sync.py`: lo que ejecuta es el de cada raíz.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path

IS_WIN = os.name == "nt"

ERRORES_DE_RED = (
    "no such host",
    "temporary failure in name resolution",
    "dial tcp",
    "connection refused",
    "actively refused it",
    "no route to host",
    "network is unreachable",
    "i/o timeout",
    "context deadline exceeded",
    "tls handshake timeout",
    "couldn't connect ssh",
    "did not properly respond after a period of time",
)
"""Agujas, en minúsculas, de lo que escriben rclone y Go cuando no llegan al otro lado.

Son la resolución de nombres (`net.DNSError`: «no such host» y, en Windows, «No
such host is known»), el dial que no conecta (`dial tcp`, «connection refused»,
«actively refused it», «no route to host», «network is unreachable»), los
plazos (`--contimeout`: «i/o timeout»; los de contexto: «context deadline
exceeded»), el SFTP que no llega a abrir su SSH («couldn't connect SSH») y el
TLS que no termina su saludo.

Todas son de CONEXIÓN: un remoto que contesta con un error propio
(credenciales, permisos, una ruta que no existe) no es un problema de red y no
tiene que marcarse «sin conexión».
"""

EXPLICACION_RED = (
    "No se ha podido llegar al remoto: sin red, el servidor apagado o un nombre "
    "que no se resuelve. No es un fallo de la pareja; cuando vuelva la conexión, "
    "la siguiente pasada seguirá donde lo dejó.")
"""Lo que se le dice al usuario cuando un fallo es de red."""


def es_de_red(texto: str) -> bool:
    """Indica si lo que ha escrito una pasada fallida dice que no llegó al remoto."""
    bajo = texto.lower()
    return any(aguja in bajo for aguja in ERRORES_DE_RED)


@dataclass(frozen=True)
class Energia:
    """Cómo está la alimentación del equipo.

    Args:
        con_bateria: Si está funcionando ahora a batería.
        porcentaje: Carga de la batería, o `None` si no se sabe o no hay
            batería.
        ahorro: Si el sistema está en modo de ahorro de energía (el «ahorro de
            batería» o «ahorro de energía» de Windows, el perfil `power-saver`
            de Linux), enchufado o no.
    """
    con_bateria: bool = False
    porcentaje: int | None = None
    ahorro: bool = False


# Sustituible por los tests: dónde mira Linux.
POWER_SUPPLY = Path("/sys/class/power_supply")


def energia() -> Energia:
    """Devuelve cómo está la alimentación ahora; nunca lanza.

    Si no puede saberlo, devuelve «enchufado».
    """
    try:
        if IS_WIN:
            return _energia_windows()
        return replace(_energia_linux(), ahorro=_ahorro_linux())
    except Exception:                                   # noqa: BLE001
        return Energia()


def energia_de_windows(linea_ac: int, bandera: int, porcentaje: int,
                       ahorro: int) -> Energia:
    """Traduce los campos de `SYSTEM_POWER_STATUS` a una `Energia`.

    Args:
        linea_ac: `ACLineStatus`: 0 desenchufado, 1 enchufado, 255 desconocido.
        bandera: `BatteryFlag`; 128 es «No system battery».
        porcentaje: `BatteryLifePercent`; 255 es desconocido.
        ahorro: `SystemStatusFlag`: 1 es el ahorro de batería encendido. Cuenta
            también sin batería: un sobremesa puede tener el ahorro de energía.
    """
    en_ahorro = ahorro == 1
    if bandera == 128:
        return Energia(ahorro=en_ahorro)
    return Energia(linea_ac == 0, None if porcentaje == 255 else int(porcentaje), en_ahorro)


def _energia_windows() -> Energia:
    """Lee la alimentación con `GetSystemPowerStatus`."""
    import ctypes

    class SYSTEM_POWER_STATUS(ctypes.Structure):
        """Estructura `SYSTEM_POWER_STATUS` de Windows."""
        _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte),
                    ("BatteryLifePercent", ctypes.c_ubyte),
                    ("SystemStatusFlag", ctypes.c_ubyte),
                    ("BatteryLifeTime", ctypes.c_ulong),
                    ("BatteryFullLifeTime", ctypes.c_ulong)]

    estado = SYSTEM_POWER_STATUS()
    if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(estado)):
        return Energia()
    return energia_de_windows(estado.ACLineStatus, estado.BatteryFlag,
                              estado.BatteryLifePercent, estado.SystemStatusFlag)


def _leer(ruta: Path) -> str:
    """Devuelve el contenido de un fichero de `/sys` sin espacios.

    Vacío si no se lee.
    """
    try:
        return ruta.read_text(encoding="ascii", errors="replace").strip()
    except OSError:
        return ""


def _energia_linux() -> Energia:
    """Lee la alimentación de `/sys/class/power_supply`.

    `type` dice qué es cada fuente: `Mains`/`USB` es enchufada si `online` es
    1; `Battery` trae su `capacity` y su `status` («Discharging» es ir a
    batería). Las baterías de un ratón o unos auriculares llevan `scope =
    Device`: no alimentan el equipo y no cuentan.
    """
    try:
        fuentes = sorted(POWER_SUPPLY.iterdir())
    except OSError:
        return Energia()
    enchufado = False
    baterias: list[tuple[int | None, str]] = []
    for fuente in fuentes:
        tipo = _leer(fuente / "type")
        if _leer(fuente / "scope").lower() == "device":
            continue
        if tipo in ("Mains", "USB", "USB_C", "USB_PD") and _leer(fuente / "online") == "1":
            enchufado = True
        elif tipo == "Battery":
            capacidad = _leer(fuente / "capacity")
            baterias.append((int(capacidad) if capacidad.isdigit() else None,
                             _leer(fuente / "status")))
    if not baterias:
        return Energia()
    conocidas = [p for p, _ in baterias if p is not None]
    porcentaje = min(conocidas) if conocidas else None
    estados = {s for _, s in baterias}
    if "Discharging" in estados:
        return Energia(True, porcentaje)
    # Cargando, llena o «sin cargar» (el umbral de carga de muchos portátiles)
    # es que hay corriente, aunque el equipo no publique su fuente `Mains`.
    if enchufado or estados & {"Charging", "Full", "Not charging"}:
        return Energia(False, porcentaje)
    return Energia(True, porcentaje)


PPD = "org.freedesktop.UPower.PowerProfiles"
"""Nombre en el bus del sistema, e interfaz, de power-profiles-daemon (0.20 en adelante).

Es el servicio que manejan GNOME, KDE y `powerprofilesctl`; `tuned-ppd`
contesta por el mismo nombre. Su propiedad `ActiveProfile` es `power-saver`,
`balanced` o `performance`.
"""
PPD_RUTA = "/org/freedesktop/UPower/PowerProfiles"
PPD_ANTIGUO = "net.hadess.PowerProfiles"
"""El nombre de power-profiles-daemon anterior a la 0.20, que aún contesta en muchas distros."""
PPD_ANTIGUO_RUTA = "/net/hadess/PowerProfiles"
PERFIL_AHORRO = "power-saver"


def _ahorro_linux() -> bool:
    """Indica si power-profiles-daemon tiene puesto el perfil de ahorro; nunca lanza.

    Pregunta por el nombre actual y, si no contesta, por el antiguo. Sin el
    servicio (otro gestor de energía, o ninguno) no hay ahorro.
    """
    from . import dbus
    try:
        with dbus.Conexion.sistema() as bus:
            for nombre, ruta in ((PPD, PPD_RUTA), (PPD_ANTIGUO, PPD_ANTIGUO_RUTA)):
                try:
                    perfil = bus.propiedad(nombre, ruta, nombre, "ActiveProfile", espera=2.0)
                except Exception:                       # noqa: BLE001
                    continue
                return perfil == PERFIL_AHORRO
    except Exception:                                   # noqa: BLE001
        return False
    return False


# NetworkManager, `NMMetered` (libnm/nm-dbus-interface.h): 0 desconocido, 1 sí,
# 2 no, 3 se supone que sí, 4 se supone que no.
NM_METERED_SI = (1, 3)
NM = "org.freedesktop.NetworkManager"
NM_RUTA = "/org/freedesktop/NetworkManager"

# `INetworkCostManager` (netlistmgr.h): el CLSID de `NetworkListManager`, el
# IID de la interfaz y los bits de `NLM_CONNECTION_COST`.
CLSID_NETWORK_LIST_MANAGER = "{DCB00C01-570F-4A9B-8D69-199FDBA5723B}"
IID_INETWORK_COST_MANAGER = "{DCB00008-570F-4A9B-8D69-199FDBA5723B}"
NLM_COST_UNRESTRICTED = 0x1
NLM_COST_FIXED = 0x2
NLM_COST_VARIABLE = 0x4
NLM_COST_OVERDATALIMIT = 0x10000
NLM_COST_ROAMING = 0x40000
_COSTE_MEDIDO = (NLM_COST_FIXED | NLM_COST_VARIABLE | NLM_COST_OVERDATALIMIT
                 | NLM_COST_ROAMING)


def coste_medido(coste: int) -> bool:
    """Indica si ese `NLM_CONNECTION_COST` es una red de uso medido.

    Es lo que Windows enseña como «conexión de uso medido»: tarifa fija o
    variable, pasado del límite o en itinerancia.
    """
    return bool(coste & _COSTE_MEDIDO)


def red_medida() -> bool | None:
    """Indica si es de uso medido la red por la que sale el equipo.

    Returns:
        True o False, o `None` si no se sabe.
    """
    try:
        return _medida_windows() if IS_WIN else _medida_linux()
    except Exception:                                   # noqa: BLE001
        return None


def _medida_linux() -> bool | None:
    """Lee la propiedad `Metered` de NetworkManager por el bus del sistema.

    Returns:
        True o False, o `None` si NetworkManager no lo sabe.
    """
    from . import dbus
    with dbus.Conexion.sistema() as bus:
        valor = bus.propiedad(NM, NM_RUTA, NM, "Metered", espera=2.0)
    if valor in NM_METERED_SI:
        return True
    return False if valor in (2, 4) else None


def _medida_windows() -> bool | None:
    """Pide el coste de la conexión a `INetworkCostManager` por COM.

    Returns:
        True o False, o `None` si no se puede saber.
    """
    import ctypes
    from ctypes import POINTER, byref, c_void_p, c_wchar_p
    from ctypes.wintypes import DWORD, ULONG

    class GUID(ctypes.Structure):
        """Estructura `GUID` de Windows."""
        _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
                    ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]

    ole32 = ctypes.windll.ole32

    def guid(texto: str) -> GUID:
        """Convierte un texto `{...}` en un `GUID`.

        Raises:
            OSError: Si el texto no es un GUID.
        """
        g = GUID()
        if ole32.CLSIDFromString(c_wchar_p(texto), byref(g)) < 0:
            raise OSError(f"GUID ilegible: {texto}")
        return g

    clsid, iid = guid(CLSID_NETWORK_LIST_MANAGER), guid(IID_INETWORK_COST_MANAGER)
    # `COINIT_MULTITHREADED`: el agente no tiene ventana ni bucle de mensajes
    # en este hilo. Un HRESULT negativo es que ya estaba en otro modelo, que
    # sirve igual; solo se cierra lo que se abre aquí.
    hr_init = ole32.CoInitializeEx(None, 0)
    try:
        objeto = c_void_p()
        CLSCTX_ALL = 0x17
        hr = ole32.CoCreateInstance(byref(clsid), None, CLSCTX_ALL, byref(iid),
                                    byref(objeto))
        if hr < 0 or not objeto:
            return None
        vtbl = ctypes.cast(objeto, POINTER(POINTER(c_void_p))).contents
        try:
            # Detrás de los 3 de IUnknown, el 3 es GetCost(DWORD *pCost,
            # NLM_SOCKADDR *pDestIPAddr); NULL pide el coste de la máquina.
            get_cost = ctypes.WINFUNCTYPE(ctypes.c_long, c_void_p, POINTER(DWORD),
                                          c_void_p)(vtbl[3])
            coste = DWORD(0)
            if get_cost(objeto, byref(coste), None) < 0:
                return None
            return coste_medido(coste.value)
        finally:
            ctypes.WINFUNCTYPE(ULONG, c_void_p)(vtbl[2])(objeto)
    finally:
        if hr_init >= 0:
            ole32.CoUninitialize()
