#!/usr/bin/env python3
"""Escribir la entrada de un dispositivo cifrado con VeraCrypt. Sin Tkinter.

Qué es el vestíbulo y por qué existe está en `common/vestibulo.py`. Aquí están
los textos de los lanzadores y su escritura, que es cosa del instalador: se
hace al aprovisionar (paso 5) y en «Añadir plataformas…», y NUNCA al actualizar
el programa, igual que los lanzadores de dentro.

Lo que no se puede relajar, todo contra el código de VeraCrypt (tag
VeraCrypt_1.26.24; las citas, en la spec
`docs/superpowers/specs/2026-09-23-veracrypt-ciclo-de-vida-design.md`):
- La contraseña no pasa por aquí: `VeraCrypt.exe /volume X /quit` sin
  `/password` la pide con SU diálogo (`Mount/Mount.c`, `WM_INITDIALOG`: «Ask
  user for password»). Ni el `.bat` ni ningún proceso nuestro la ven, y no
  aparece en ninguna línea de órdenes.
- El VeraCrypt instalado va antes que el que viaja: con otra versión instalada
  y su driver cargado, el que viaja falla con `ERR_DRIVER_VERSION`
  (`Common/Dlgcode.c`, `DriverAttach`).
- El código de salida no dice si se ha montado: el que viaja, sin permisos de
  administrador, se relanza elevado con `/q UAC`, espera dos segundos y sale
  con 0 (`Common/Dlgcode.c`, `InitApp` y `LaunchElevatedProcess`); la
  contraseña la pide la otra instancia. Por eso se espera a VER la unidad, y
  con el que viaja se espera sin contar mientras esa copia siga viva
  (`:vc_pendiente`): cuando sale sin que aparezca la unidad, la contraseña se
  ha cancelado y no hay nada más que esperar. Esa espera sin contar tiene un
  tope explícito (`ESPERA_PENDIENTE`, 10 minutos): pasado, la ventana de la
  contraseña o del aviso de permisos puede estar tapada por otras y la consola
  lo dice en vez de quedarse colgada.
- `/dismount`, no `/unmount`: el segundo no existe antes de la 1.26.24.
- Sin `/auto`: además de montar, abre una ventana del Explorador
  (`ExtractCommandLine`: `bExplore = TRUE`). Con `/quit` y `/volume` ya monta.
- La letra no dice si el contenedor está abierto, en ningún sentido: tras
  forzar el cierre con algo abierto dentro la letra se va y Windows sigue sin
  dejar quitar la unidad; tras quitarla sin expulsar la letra se queda y sirve
  el fichero de control de la caché. Lo que sí lo dice es el propio `.hc`:
  montado, el driver lo retiene. Eso mira `:libre` (`_LIBRE_BAT`).

Los `.bat` siguen las reglas de `runsync.bat` (`deploy.LAUNCHER_BAT`): CRLF,
sin bloques entre paréntesis (una ruta con «)» los rompe) y `chcp 65001` solo
antes de escribir algo con acentos.

Linux sin VeraCrypt: en Linux no viaja VeraCrypt, pero un volumen como los que
crea prdrive (AES, SHA-512, PIM 0, sin oculto) lo abren también dos
herramientas que traen casi todas las distribuciones. `abrir-prdrive.sh` usa la
primera que haya, por este orden. Va contra el código de udisks (`master`) y
cryptsetup (`main`), con las citas en la spec; lo de cada distribución puede
diferir y está sin probar en hardware:

1. VeraCrypt instalado, como siempre: su ventana pide la contraseña y la de
administrador que montar exige.

2. udisks2, sin administrador, si reconoce contenedores VeraCrypt. Su cabecera
no tiene firma, así que udisks solo da un dispositivo desconocido por cifrado
(`IdType` `crypto_unknown` y, con él, la interfaz `Encrypted` que `Unlock`
exige) con `enable_tcrypt` activo (`src/udiskslinuxblock.c`,
`bd_crypto_device_seems_encrypted()`; `encrypted_check()` en
`src/udiskslinuxblockobject.c`), y eso es que exista `TCRYPT_CONF` al arrancar
el servicio (`src/main.c`). Con él, polkit deja a quien tiene la sesión activa
`loop-setup`, `encrypted-unlock` y `filesystem-mount` sin contraseña de
administrador (`data/org.freedesktop.UDisks2.policy.in`), porque el loop lo ha
puesto él (`udisks_daemon_util_setup_by_user()`). Abre siempre en modo
VeraCrypt (`tcrypt_open_job_func()`, `veracrypt = TRUE`) y con PIM 0. prdrive
NO crea ese fichero (es tocar `/etc` como root y reiniciar un servicio del
sistema, y eso lo decide quien administra el equipo): se dice cómo
(`ACTIVAR_UDISKS`).

3. cryptsetup, con sudo (device-mapper es de root). VeraCrypt va por defecto
(`--veracrypt` se ignora en las versiones nuevas y en las viejas hacía falta,
así que se pasa siempre; `man/common_options.adoc`) y con un fichero pone el
loop él solo (`man/cryptsetup.8.adoc`, «Notes on loopback device use»). Monta
en `PUNTO_CRYPTSETUP`.

La contraseña no pasa por aquí: `udisksctl unlock` la lee de la terminal que
controla el proceso (`read_passphrase()` en `tools/udisksctl.c`, con
`ctermid()`) y cryptsetup de la terminal si stdin lo es y, si no, DE STDIN
(`tools_get_key()` en `src/utils_password.c`). Por eso sin VeraCrypt hace falta
una terminal, y por eso NO se abre con `pkexec`: sin terminal cryptsetup leería
la contraseña de lo que llegara por stdin, y dársela así es justo lo que no se
hace. `pkexec` sí vale para cerrar: ahí no hay contraseña del contenedor.

Se cierra con lo mismo que abrió, y eso no se apunta: se deduce (`estado` en
`_ESTADO_SH`). `losetup -j` da el loop que tiene el contenedor,
`/sys/block/loopN/holders/` el dm que cuelga de él y su nombre quién lo abrió:
`veracryptN` es VeraCrypt (`MountVolumeNative()` en
`Core/Unix/Linux/CoreLinux.cpp` pone el fichero en un loop y llama así al dm),
`prdrive-<id>` es cryptsetup desde aquí y cualquier otro es udisks2
(`tcrypt-…`, `udisks_linux_block_make_dm_name()`). `/proc/mounts` dice dónde
está montado. Sin loop, VeraCrypt si está: sin el cifrado del kernel no usa
ninguno.
"""

from __future__ import annotations

import stat
from pathlib import Path

from common import components, llavero
from common import vestibulo as v

from . import IS_WIN, InstallError
from .device import CONTROL_FILE, Check

URL_VERACRYPT = "https://veracrypt.jp/en/Downloads.html"
"""Dónde descargar VeraCrypt."""

NOMBRE_ABRIR = Path(v.ABRIR_BAT).stem
"""Nombre de los lanzadores como se ven en el Explorador, que esconde la extensión."""
NOMBRE_EXPULSAR = Path(v.EXPULSAR_BAT).stem
"""Nombre del lanzador de expulsar, sin extensión."""

ESPERA_INSTALADO = 10
"""Segundos que se espera a ver la unidad tras lanzar el VeraCrypt instalado.

Con el instalado su código de salida sí es el del montaje.
"""
ESPERA_VIAJERO = 180
"""Segundos que se espera a ver la unidad tras lanzar el VeraCrypt que viaja.

Solo cuando no se puede saber si la copia elevada sigue viva: con un VeraCrypt
del mismo nombre ya en marcha (`VC_ANTES`) `:vc_pendiente` no distingue cuál es
el nuestro. Su código de salida no vale (ver el docstring del módulo) y hay que
dejar a la persona el tiempo de escribir la contraseña en la ventana elevada.
Con la copia a la vista no se cuenta; cuando sale, valen `ESPERA_INSTALADO`.
"""

ESPERA_PENDIENTE = 600
"""Vueltas de un segundo que «Abrir» espera sin contar a la copia elevada: 10 minutos.

Mientras `:vc_pendiente` vea viva la copia elevada del VeraCrypt que viaja, la
espera no gasta `ESPERA`: la persona está escribiendo la contraseña o decidiendo
el aviso de permisos. Sin tope, una ventana que se quedó detrás de otras (o un
aviso de UAC sin responder) dejaría la consola colgada para siempre. Al
cumplirse dice que la ventana puede estar oculta y qué hacer (`:sin_respuesta`).
Se cuenta en vueltas de la espera, de un segundo más lo que tarde `tasklist`, así
que son «unos 10 minutos» y no un reloj exacto: un `.bat` sin paréntesis no tiene
otra forma barata de contar. «Expulsar» no lo usa.
"""

_CONTROL_BAT = str(CONTROL_FILE).replace("/", "\\")

_APP_BAT = str(CONTROL_FILE.parent).replace("/", "\\")
"""La carpeta del programa dentro del contenedor (`.prdrive`), para el Python del llavero."""

_LLAVERO_BAT = (
    ":llavero\n"
    f'if not exist "%RAIZ%\\{llavero.LANZADOR}" exit /b 0\n'
    'set "PYL="\n'
    f'set "RTL=%RAIZ%\\{_APP_BAT}\\{components.RUNTIME_SUBDIR}"\n'
    'if /i "%PROCESSOR_ARCHITECTURE%"=="ARM64" if exist "%RTL%\\windows-arm64\\python.exe" '
    'set "PYL=%RTL%\\windows-arm64\\python.exe"\n'
    'if not defined PYL if exist "%RTL%\\windows-x64\\python.exe" '
    'set "PYL=%RTL%\\windows-x64\\python.exe"\n'
    "if not defined PYL exit /b 0\n"
    f'"%PYL%" "%RAIZ%\\{_APP_BAT}\\runsync.py" --cerrar-llavero\n'
    "exit /b\n"
)
"""Subrutina `:llavero`: cierra el llavero antes de desmontar (`runsync.py --cerrar-llavero`).

Solo si la unidad lo lleva (su `Llavero.bat`): cierra KeePassXC y su proxy,
para el vigilante, sube lo pendiente y deja el registro del navegador como
estaba. Con el Python de consola del dispositivo, el mismo orden que
`runsync.bat`, y esperándolo: tiene que haber acabado antes del desmontaje, y
mientras corre retiene el volumen. Sale con 1 si KeePassXC sigue abierto.
"""

_BUSCAR_BAT = (
    ":buscar\n"
    'set "RAIZ="\n'
    "for %%L in (C D E F G H I J K L M N O P Q R S T U V W X Y Z A B) do "
    f'if exist "%%L:\\{_CONTROL_BAT}" '
    f'findstr /b /l /c:"id=%ID%" "%%L:\\{_CONTROL_BAT}" >nul 2>&1 && set "RAIZ=%%L:"\n'
    "exit /b 0\n"
)
"""Subrutina `:buscar`: la unidad donde ha quedado el contenedor.

Es la que tenga el fichero de control con ESTE id. Usa `/b` y no `/x`: el
fichero puede venir de Linux (LF) o de Windows (CRLF) y el id es un uuid4 de
longitud fija, así que empezar igual es ser igual. A y B van al final, como
hace VeraCrypt al elegir letra (`GetFirstAvailableDrive`).
"""

_LIBRE_BAT = (
    ":libre\n"
    f'if not exist "%~dp0{v.CONTENEDOR}" exit /b 1\n'
    "call :tocar 2>nul\n"
    "exit /b\n"
    "\n"
    ":tocar\n"
    f'>>"%~dp0{v.CONTENEDOR}" type nul || exit /b 1\n'
    "exit /b 0\n"
)
"""Subrutina `:libre`: devuelve 0 si nadie tiene abierto el contenedor.

Es la pregunta «¿ha quedado suelto?». Con el volumen montado, el driver lo
tiene abierto sin dejar escribir a nadie más (`TCOpenVolume()`,
`Driver/Ntvol.c`, con `bExclusiveAccess`), así que abrirlo para añadir falla.
La excepción: si al montar otro proceso ya tenía el fichero abierto,
`MountVolume()` (`Common/Dlgcode.c`) monta compartido (con `/silent` sin
preguntar, sin él preguntando) y entonces esto lo ve suelto aunque esté
montado. `type nul` no añade nada: ni el contenido ni la fecha cambian. Sin el
contenedor al lado devuelve 1 y no lo crea: sin él no se puede afirmar nada. El
`2>nul` va en el `call` porque en la misma línea que `>>` no tapa el mensaje de
cmd cuando la apertura falla, y sin paréntesis no hay otra forma de envolverla.
"""

_VC_ANTES_BAT = (
    'set "VC_ANTES="\n'
    'tasklist /fi "imagename eq %VC_IMAGEN%" /nh 2>nul '
    '| find /i "%VC_IMAGEN%" >nul && set "VC_ANTES=1"\n'
)
"""Apunta en `VC_ANTES` si ya había un VeraCrypt de la imagen `VC_IMAGEN`.

Va antes de lanzar el nuestro: `:vc_pendiente` solo sirve si al empezar no había
ninguno.
"""

_VC_PENDIENTE_BAT = (
    ":vc_pendiente\n"
    "if defined VC_ANTES exit /b 1\n"
    'tasklist /fi "imagename eq %VC_IMAGEN%" /nh 2>nul | find /i "%VC_IMAGEN%" >nul\n'
    "exit /b\n"
)
"""Subrutina `:vc_pendiente`: ¿sigue VeraCrypt con lo que se le ha pedido?

Devuelve 0 si hay que seguir esperando sin contar. El que viaja, sin
administrador, se relanza elevado y sale a los dos segundos (`InitApp`,
`LaunchElevatedProcess` en `Common/Dlgcode.c`), así que `start /wait` no espera
a la copia elevada, que es la que pregunta: al desmontar, si forzar (los 30
intentos se gastaban mientras la pregunta seguía en pantalla); al montar, la
contraseña (y cuando sale sin que aparezca la unidad es que se ha cancelado, sin
esperar los 180 s). `tasklist` ve el nombre de un proceso elevado sin serlo. La
copia elevada es la misma imagen (`InitApp` relanza lo que le da
`GetModuleFileNameW`), así que se busca por el nombre del que se ha lanzado,
`VC_IMAGEN`: `VeraCrypt.exe` instalado o de antes, `VeraCrypt-x64.exe` o
`VeraCrypt-arm64.exe` del portable. Solo vale si al empezar no había ninguno
(`VC_ANTES`): con uno en segundo plano no se sabe cuál es el nuestro y se cuenta
como siempre. La subrutina no tiene tope, como `start /wait` con el instalado:
el de «Abrir» lo pone quien la llama (`ESPERA_PENDIENTE`) y «Expulsar» espera lo
que tarde la respuesta.
"""

_VIAJERO_BAT = f"%~dp0{v.TRAVELER}\\{v.TRAVELER_PORTATIL.format(arq='%VC_ARQ%')}"
"""Ruta del VeraCrypt portable que viaja.

Con los nombres del portable oficial (`veracrypt_bin`): uno por arquitectura.

`%PROCESSOR_ARCHITECTURE%` dice la verdad aquí porque cmd corre nativo (lo
mismo que ya da por hecho `runsync.bat`), y hay que elegir la de este equipo:
`IsARM()` escoge el driver por la máquina NATIVA y un driver no se emula (ver
`install/traveler.py`).
"""
_VIAJERO_IMAGEN = v.TRAVELER_PORTATIL.format(arq="%VC_ARQ%")
_VIAJERO_ANTES_BAT = f"%~dp0{v.TRAVELER}\\{v.TRAVELER_EXE}"

_ELEGIR_BAT = (
    'set "VC="\n'
    'set "VC_IMAGEN=VeraCrypt.exe"\n'
    'set "VC_ARQ=x64"\n'
    'if /i "%PROCESSOR_ARCHITECTURE%"=="ARM64" set "VC_ARQ=arm64"\n'
    'if exist "%ProgramFiles%\\VeraCrypt\\VeraCrypt.exe" '
    'set "VC=%ProgramFiles%\\VeraCrypt\\VeraCrypt.exe"\n'
    'if not defined VC if exist "%ProgramW6432%\\VeraCrypt\\VeraCrypt.exe" '
    'set "VC=%ProgramW6432%\\VeraCrypt\\VeraCrypt.exe"\n'
    f'if not defined VC if exist "{_VIAJERO_BAT}" set "VIAJERO=1"\n'
    f'if not defined VC if exist "{_VIAJERO_BAT}" set "VC_IMAGEN={_VIAJERO_IMAGEN}"\n'
    f'if not defined VC if exist "{_VIAJERO_BAT}" set "VC={_VIAJERO_BAT}"\n'
    f'if not defined VC if exist "{_VIAJERO_ANTES_BAT}" set "VIAJERO=1"\n'
    f'if not defined VC if exist "{_VIAJERO_ANTES_BAT}" '
    f'set "VC={_VIAJERO_ANTES_BAT}"\n'
    "if not defined VC goto sin_veracrypt\n"
)
r"""Elige el VeraCrypt que se usa: el instalado antes que el que viaja.

Del que viaja, el portable de la arquitectura de este equipo antes que la copia
de una instalación que dejaban versiones anteriores
(`VeraCrypt\VeraCrypt.exe`).
"""

_SIN_VERACRYPT_BAT = (
    ":sin_veracrypt\n"
    "chcp 65001 >nul\n"
    "echo.\n"
    "echo   No encuentro VeraCrypt: ni instalado en este equipo ni en la carpeta\n"
    "echo   VeraCrypt de esta unidad. Instálalo desde\n"
    f"echo   {URL_VERACRYPT}\n"
    f"echo   y vuelve a intentarlo. Más en {v.LEEME}.\n"
    "echo.\n"
    "pause\n"
    "exit /b 1\n"
)
"""Subrutina `:sin_veracrypt`: el mensaje cuando no hay VeraCrypt."""


def bat_abrir(device_id: str) -> str:
    """Devuelve `Abrir PRDRIVE.bat`.

    Abre el contenedor y lanza el `runsync.bat` de dentro.
    """
    return (
        "@echo off\n"
        f"rem {v.ABRIR_BAT} - Abre el contenedor cifrado de prdrive y lanza la ventana.\n"
        "rem\n"
        "rem   1. Si el contenedor ya esta abierto en alguna unidad, lanza prdrive.\n"
        "rem      Pero si una unidad dice ser este dispositivo y el contenedor de\n"
        "rem      aqui esta suelto, es lo que quedo al quitar la unidad sin\n"
        "rem      expulsarla (Windows la deja puesta y sirve lo que tenia en\n"
        "rem      cache): no se lanza desde ella.\n"
        "rem   2. Si no, lo abre con VeraCrypt: el instalado antes que el que viaja\n"
        "rem      en la carpeta VeraCrypt de esta unidad (con otro VeraCrypt\n"
        "rem      instalado, el que viaja no puede cargar su driver). Del que viaja,\n"
        "rem      el de la arquitectura de este equipo (x64 o ARM64). La contrasena\n"
        "rem      la pide VeraCrypt en su ventana: nunca pasa por aqui.\n"
        "rem   3. Busca la unidad por el id del dispositivo y lanza su runsync.bat.\n"
        "rem\n"
        "rem No se fia del codigo de salida: el VeraCrypt que viaja, sin permisos de\n"
        "rem administrador, se relanza elevado y sale enseguida con 0 mientras la\n"
        "rem otra ventana pide la contrasena. Por eso espera a ver la unidad.\n"
        "rem Mientras esa copia siga viva, la espera no cuenta, hasta unos 10 minutos\n"
        "rem (despues avisa de que la ventana puede estar tapada); si sale sin que\n"
        "rem haya unidad, la contrasena se ha cancelado y no espera mas.\n"
        "rem\n"
        "rem Lo escribe el instalador de prdrive. Sin bloques entre parentesis a\n"
        "rem proposito: una ruta con \")\" los romperia.\n"
        "setlocal\n"
        'cd /d "%~dp0"\n'
        f'set "ID={device_id}"\n'
        "call :buscar\n"
        "if not defined RAIZ goto montar\n"
        "call :libre\n"
        "if errorlevel 1 goto lanzar\n"
        "goto fantasma\n"
        "\n"
        ":montar\n"
        'set "VIAJERO="\n'
        + _ELEGIR_BAT
        + _VC_ANTES_BAT +
        f'set "ESPERA={ESPERA_INSTALADO}"\n'
        f'set "ESPERA_PENDIENTE={ESPERA_PENDIENTE}"\n'
        f'if defined VIAJERO if defined VC_ANTES set "ESPERA={ESPERA_VIAJERO}"\n'
        f"echo Abriendo {v.ETIQUETA}: escribe la contrasena en la ventana de VeraCrypt.\n"
        "if defined VIAJERO if defined VC_ANTES "
        "echo Si la has cancelado, cierra esta ventana.\n"
        f'start "" /wait "%VC%" /volume "%~dp0{v.CONTENEDOR}" /mountoption rm '
        f"/mountoption label={v.ETIQUETA} /history n /cache n /quit\n"
        'if errorlevel 1 if not defined VIAJERO set "ESPERA=1"\n'
        'set "INTENTOS=0"\n'
        'set "PENDIENTE=0"\n'
        ":esperar\n"
        "call :buscar\n"
        "if defined RAIZ goto lanzar\n"
        "call :vc_pendiente\n"
        "if not errorlevel 1 goto esperar_pendiente\n"
        "set /a INTENTOS+=1\n"
        "if %INTENTOS% geq %ESPERA% goto no_abierto\n"
        "goto esperar_vc\n"
        ":esperar_pendiente\n"
        "set /a PENDIENTE+=1\n"
        "if %PENDIENTE% geq %ESPERA_PENDIENTE% goto sin_respuesta\n"
        ":esperar_vc\n"
        "timeout /t 1 /nobreak >nul\n"
        "goto esperar\n"
        "\n"
        ":lanzar\n"
        'if not exist "%RAIZ%\\runsync.bat" goto sin_programa\n'
        'call "%RAIZ%\\runsync.bat"\n'
        "exit /b 0\n"
        "\n"
        + _BUSCAR_BAT +
        "\n"
        + _LIBRE_BAT +
        "\n"
        + _VC_PENDIENTE_BAT +
        "\n"
        + _SIN_VERACRYPT_BAT +
        "\n"
        ":fantasma\n"
        "chcp 65001 >nul\n"
        "echo.\n"
        f"echo   {v.ETIQUETA} aparece abierto en %RAIZ%, pero el contenedor de esta\n"
        "echo   unidad no lo está: lo más probable es que sea lo que quedó al\n"
        "echo   quitarla sin expulsarla. Lo que se guarde ahí se pierde, así que no\n"
        f"echo   lo abro. Ciérralo con «{NOMBRE_EXPULSAR}» y vuelve a abrir\n"
        f"echo   «{NOMBRE_ABRIR}».\n"
        "echo.\n"
        "pause\n"
        "exit /b 1\n"
        "\n"
        ":no_abierto\n"
        "chcp 65001 >nul\n"
        "echo.\n"
        "echo   El contenedor no se ha abierto: la contraseña no era esa, se ha\n"
        "echo   cancelado, o no se ha aceptado el aviso de permisos de administrador.\n"
        "echo.\n"
        "pause\n"
        "exit /b 1\n"
        "\n"
        ":sin_respuesta\n"
        "chcp 65001 >nul\n"
        "echo.\n"
        "echo   VeraCrypt lleva unos 10 minutos esperando una respuesta. La ventana\n"
        "echo   de la contraseña, o el aviso de permisos de administrador, puede\n"
        "echo   haber quedado detrás de otras: búscala en la barra de tareas o con\n"
        "echo   Alt+Tab y contéstala, o ciérrala para cancelar. Cuando el contenedor\n"
        f"echo   esté abierto, vuelve a abrir «{NOMBRE_ABRIR}».\n"
        "echo.\n"
        "pause\n"
        "exit /b 1\n"
        "\n"
        ":sin_programa\n"
        "chcp 65001 >nul\n"
        "echo.\n"
        "echo   El contenedor está abierto en %RAIZ%, pero dentro no está prdrive.\n"
        "echo   Vuelve a pasar el instalador de prdrive sobre esta unidad.\n"
        "echo.\n"
        "pause\n"
        "exit /b 1\n"
    )


def bat_expulsar(device_id: str) -> str:
    """Devuelve `Expulsar PRDRIVE.bat`.

    Cierra el contenedor para poder quitar la unidad.
    """
    return (
        "@echo off\n"
        f"rem {v.EXPULSAR_BAT} - Cierra el contenedor cifrado de prdrive.\n"
        "rem\n"
        "rem Cierra antes la ventana de prdrive: mientras corre, sus ficheros estan\n"
        "rem abiertos dentro del contenedor. Si queda algo abierto, VeraCrypt\n"
        "rem pregunta si forzar, con su propia ventana (por eso NO va con /silent).\n"
        "rem Espera unos segundos antes: quien lo llama suele ser la propia ventana,\n"
        "rem que se esta cerrando, y VeraCrypt reintenta el desmontaje solo 1,5 s.\n"
        "rem Mientras VeraCrypt siga preguntando (el que viaja lo hace desde una\n"
        "rem copia elevada que no esperamos con /wait), la espera no cuenta.\n"
        "rem No dice que se puede quitar la unidad hasta ver suelto el contenedor:\n"
        "rem si se fuerza el cierre con algo abierto dentro, la letra se va pero el\n"
        "rem contenedor sigue retenido y Windows no deja quitarla.\n"
        "rem\n"
        "rem Lo escribe el instalador de prdrive. Sin bloques entre parentesis a\n"
        "rem proposito: una ruta con \")\" los romperia.\n"
        "setlocal\n"
        'cd /d "%~dp0"\n'
        f'set "ID={device_id}"\n'
        "call :buscar\n"
        "if not defined RAIZ goto ya_cerrado\n"
        'set "VIAJERO="\n'
        + _ELEGIR_BAT +
        f"echo Cerrando {v.ETIQUETA}...\n"
        "timeout /t 3 /nobreak >nul\n"
        "call :llavero\n"
        "if errorlevel 1 goto llavero_abierto\n"
        + _VC_ANTES_BAT +
        'start "" /wait "%VC%" /dismount %RAIZ:~0,1% /quit\n'
        'set "INTENTOS=0"\n'
        ":esperar\n"
        "call :buscar\n"
        "if not defined RAIZ goto sin_letra\n"
        "call :vc_pendiente\n"
        "if not errorlevel 1 goto esperar_vc\n"
        "set /a INTENTOS+=1\n"
        "if %INTENTOS% geq 30 goto sigue_abierto\n"
        ":esperar_vc\n"
        "timeout /t 1 /nobreak >nul\n"
        "goto esperar\n"
        "\n"
        ":sin_letra\n"
        f'if not exist "%~dp0{v.CONTENEDOR}" goto cerrado\n'
        'set "INTENTOS=0"\n'
        ":esperar_suelto\n"
        "call :libre\n"
        "if not errorlevel 1 goto cerrado\n"
        "set /a INTENTOS+=1\n"
        "if %INTENTOS% geq 10 goto retenido\n"
        "timeout /t 1 /nobreak >nul\n"
        "goto esperar_suelto\n"
        "\n"
        ":cerrado\n"
        "chcp 65001 >nul\n"
        "echo.\n"
        f"echo   {v.ETIQUETA} está cerrado. Ya puedes quitar la unidad.\n"
        "echo.\n"
        "timeout /t 5 >nul\n"
        "exit /b 0\n"
        "\n"
        ":ya_cerrado\n"
        "call :libre\n"
        f'if errorlevel 1 if exist "%~dp0{v.CONTENEDOR}" goto retenido\n'
        "chcp 65001 >nul\n"
        "echo.\n"
        f"echo   {v.ETIQUETA} ya estaba cerrado. Puedes quitar la unidad.\n"
        "echo.\n"
        "timeout /t 5 >nul\n"
        "exit /b 0\n"
        "\n"
        ":sigue_abierto\n"
        "chcp 65001 >nul\n"
        "echo.\n"
        "echo   El contenedor sigue abierto en %RAIZ%. ¿Queda algún programa usando\n"
        "echo   la unidad? Ciérralo y vuelve a intentarlo. No quites la unidad todavía.\n"
        "echo.\n"
        "pause\n"
        "exit /b 1\n"
        "\n"
        ":llavero_abierto\n"
        "chcp 65001 >nul\n"
        "echo.\n"
        f"echo   No se ha cerrado {v.ETIQUETA}: KeePassXC sigue abierto. Ciérralo y vuelve\n"
        f"echo   a abrir «{NOMBRE_EXPULSAR}». No quites la unidad todavía.\n"
        "echo.\n"
        "pause\n"
        "exit /b 1\n"
        "\n"
        ":retenido\n"
        "chcp 65001 >nul\n"
        "echo.\n"
        f"echo   El contenedor de {v.ETIQUETA} sigue abierto aunque ya no tiene letra:\n"
        "echo   pasa cuando se cierra a la fuerza con algo de dentro todavía en uso.\n"
        "echo   Windows no te dejará quitar la unidad. Cierra los programas que usaban\n"
        f"echo   {v.ETIQUETA} y vuelve a abrir «{NOMBRE_EXPULSAR}». Si sigue igual,\n"
        "echo   reinicia el equipo antes de quitarla.\n"
        "echo.\n"
        "pause\n"
        "exit /b 1\n"
        "\n"
        + _BUSCAR_BAT +
        "\n"
        + _LLAVERO_BAT +
        "\n"
        + _LIBRE_BAT +
        "\n"
        + _VC_PENDIENTE_BAT +
        "\n"
        + _SIN_VERACRYPT_BAT
    )


# Lo que hace que udisks2 reconozca contenedores VeraCrypt, y cómo se activa: una
# vez por equipo. penwatch repite la ruta (no importa nada del proyecto) y un
# test comprueba que no se separan.
TCRYPT_CONF = "/etc/udisks2/tcrypt.conf"
"""Fichero que hace que udisks2 reconozca contenedores VeraCrypt.

Se crea una vez por equipo (ver `ACTIVAR_UDISKS`). penwatch repite la ruta (no
importa nada del proyecto) y un test comprueba que no se separan.
"""
ACTIVAR_UDISKS = f"sudo touch {TCRYPT_CONF} && sudo systemctl restart udisks2"
"""Orden que activa `TCRYPT_CONF` y reinicia udisks2."""

PREFIJO_MAPEO = f"{v.ETIQUETA.lower()}-"
"""Prefijo del nombre del mapeo de cryptsetup.

Que lleva ocho cifras del id del dispositivo.

El nombre del mapeo y el punto de montaje son fijos y distintos para cada
dispositivo, así que dos no se pisan y cerrar lo reconoce por el nombre.
"""
PUNTO_CRYPTSETUP = "/mnt"
"""Carpeta donde monta cryptsetup.

Es `/mnt` porque es donde el FHS pone lo que se monta a mano: ningún escritorio
se lo disputa (udisks2 usa `/media/$USER` y `/run/media/$USER`) y el vigilante
ya mira ahí (`penwatch.posix_roots()`). El directorio vacío se queda al cerrar:
quitarlo sería otra orden con sudo.
"""

VAR_SISTEMA = "PRDRIVE_SISTEMA"
"""Variable de entorno solo para los tests: la raíz del sistema que miran los `.sh`.

Cubre `/etc`, `/sys`, `/proc`, `/media`, `/mnt` y `/sbin`. Vacía, que es lo
normal, es el de verdad.
"""


def mapeo(device_id: str) -> str:
    """Devuelve el nombre del mapeo de cryptsetup.

    Que es también el de su punto de montaje.
    """
    return PREFIJO_MAPEO + device_id[:8]


def _cabecera_sh() -> str:
    """Devuelve el arranque común de los `.sh`.

    Ruta del contenedor, raíz del sistema y `PATH`.
    """
    return (
        'dir="$(cd "$(dirname "$0")" && pwd)"\n'
        f'contenedor="$dir/{v.CONTENEDOR}"\n'
        "# Solo para las pruebas: dónde empieza el sistema del equipo (/etc, /sys,\n"
        "# /proc, /media, /mnt, /sbin). Vacío, que es lo normal, el de verdad.\n"
        f'sistema="${{{VAR_SISTEMA}:-}}"\n'
        "# losetup y cryptsetup viven en /sbin, que Debian no pone en el PATH de un\n"
        "# usuario. Detrás: lo del usuario va antes.\n"
        'PATH="$PATH:$sistema/usr/sbin:$sistema/sbin"\n'
    )


_ESTADO_SH = (
    "estado() {\n"
    '    loop=""; dm=""; nombre=""; montado=""\n'
    '    loop="$(losetup -j "$contenedor" 2>/dev/null | sed -n \'1s/:.*//p\')"\n'
    '    [ -n "$loop" ] || return 0\n'
    '    for h in "$sistema/sys/block/${loop##*/}/holders/"*; do\n'
    '        if [ -e "$h" ]; then dm="${h##*/}"; fi\n'
    "    done\n"
    '    [ -n "$dm" ] || return 0\n'
    '    nombre="$(cat "$sistema/sys/block/$dm/dm/name" 2>/dev/null)"\n'
    '    [ -r "$sistema/proc/mounts" ] || return 0\n'
    "    while read -r disp punto_m resto; do\n"
    '        if [ "$disp" = "/dev/$dm" ] || [ "$disp" = "/dev/mapper/$nombre" ]; then\n'
    "            montado=\"$(printf '%b' \"$punto_m\")\"\n"
    "            return 0\n"
    "        fi\n"
    '    done < "$sistema/proc/mounts"\n'
    "    return 0\n"
    "}\n"
)
r"""Función `estado()` de los `.sh`: lo que el sistema dice del contenedor.

Nada se apunta en ningún sitio: el loop que lo tiene, el dm que cuelga de ese
loop, su nombre y dónde está montado. `/proc/mounts` escapa los espacios como
`\040` y `printf %b` los devuelve.
"""

_BUSCAR_SH = (
    "buscar() {\n"
    "    estado\n"
    '    set -- "$sistema"/media/veracrypt* "$sistema"/run/media/veracrypt* \\\n'
    '           "$sistema"/mnt/veracrypt* "${TMPDIR:-/tmp}"/veracrypt_mnt* \\\n'
    '           "$sistema/media/$usuario"/* "$sistema/run/media/$usuario"/* \\\n'
    f'           "$sistema"{PUNTO_CRYPTSETUP}/{PREFIJO_MAPEO}*\n'
    '    if [ -n "$VERACRYPT_MOUNT_PREFIX" ]; then\n'
    '        set -- "$@" "$VERACRYPT_MOUNT_PREFIX"*\n'
    "    fi\n"
    '    if [ -n "$montado" ]; then\n'
    '        set -- "$montado" "$@"\n'
    "    fi\n"
    '    for d in "$@"; do\n'
    # `^id=` y no `-x`: un fichero de control escrito en Windows lleva CRLF.
    f'        if [ -f "$d/{CONTROL_FILE.as_posix()}" ] && '
    f'grep -q "^id=$ID" "$d/{CONTROL_FILE.as_posix()}" 2>/dev/null; then\n'
    '            echo "$d"\n'
    "            return 0\n"
    "        fi\n"
    "    done\n"
    "    return 1\n"
    "}\n"
)
"""Función `buscar()` de los `.sh`: dónde puede estar abierto el contenedor.

Es donde diga `estado` y, además, donde montan los tres. VeraCrypt:
`CoreUnix::GetDefaultMountPointPrefix()` (`Core/Unix/CoreUnix.cpp`) elige
`VERACRYPT_MOUNT_PREFIX`, o `/media/veracrypt`, `/run/media/veracrypt`,
`/mnt/veracrypt` o `<tmp>/veracrypt_mnt`, y le añade el número de ranura.
udisks2: `/media/$USER/<etiqueta>` (Debian, Ubuntu) o
`/run/media/$USER/<etiqueta>` (Fedora, Arch). cryptsetup: `PUNTO_CRYPTSETUP`.
Lo que decide es el id del fichero de control, no el nombre de la carpeta.
"""

_ABRIR_UDISKS_SH = (
    "abrir_udisks() {\n"
    "    estado\n"
    '    if [ -z "$loop" ]; then\n'
    '        udisksctl loop-setup -f "$contenedor" || return 2\n'
    "        estado\n"
    '        if [ -z "$loop" ]; then return 2; fi\n'
    "    fi\n"
    '    if [ -z "$dm" ]; then\n'
    "        n=0\n"
    '        until udisksctl info -b "$loop" 2>/dev/null | grep -q \'UDisks2\\.Encrypted:\'; do\n'
    "            n=$((n + 1))\n"
    '            if [ "$n" -ge 5 ]; then\n'
    '                udisksctl loop-delete -b "$loop" >/dev/null 2>&1\n'
    '                echo "prdrive: udisks2 no reconoce el contenedor. Si acabas de crear" >&2\n'
    f'                echo "  {TCRYPT_CONF}, reinicia udisks2: sudo systemctl restart udisks2" >&2\n'
    "                return 2\n"
    "            fi\n"
    "            sleep 1\n"
    "        done\n"
    '        if ! udisksctl unlock -b "$loop"; then\n'
    '            udisksctl loop-delete -b "$loop" >/dev/null 2>&1\n'
    "            return 1\n"
    "        fi\n"
    "        estado\n"
    '        if [ -z "$dm" ]; then return 1; fi\n'
    "    fi\n"
    '    if [ -z "$montado" ]; then\n'
    '        udisksctl mount -b "/dev/$dm"\n'
    "    fi\n"
    "    return 0\n"
    "}\n"
)
"""Función `abrir_udisks()` de los `.sh`.

Devuelve 0 si abre, 1 si no (la contraseña no era, o se ha cancelado) y 2 si
udisks2 no lo reconoce y hay que probar otra vía. El loop que se pone y no se
llega a abrir se quita: si no, retiene el contenedor y la unidad no se puede
quitar. `unlock` lo mira udisks al aparecer el loop, así que se le deja un
momento.
"""

_ABRIR_CRYPTSETUP_SH = (
    "abrir_cryptsetup() {\n"
    '    echo "Sin VeraCrypt: lo abro con cryptsetup. sudo te pedirá tu contraseña de"\n'
    '    echo "administrador, y cryptsetup la del contenedor."\n'
    "    if command -v udisksctl >/dev/null 2>&1; then\n"
    f'        echo "(Para no necesitar sudo, una vez en este equipo: {ACTIVAR_UDISKS})"\n'
    "    fi\n"
    "    estado\n"
    '    if [ -n "$montado" ]; then return 0; fi\n'
    '    sudo mkdir -p "$punto_cs" || return 1\n'
    '    if [ "$nombre" != "$mapeo" ]; then\n'
    '        sudo cryptsetup open --type tcrypt --veracrypt "$contenedor" "$mapeo" || return 1\n'
    "    fi\n"
    '    if sudo mount -o "uid=$(id -u),gid=$(id -g)" "/dev/mapper/$mapeo" "$punto_cs" 2>/dev/null; then\n'
    "        return 0\n"
    "    fi\n"
    '    if sudo mount "/dev/mapper/$mapeo" "$punto_cs"; then\n'
    "        return 0\n"
    "    fi\n"
    '    sudo cryptsetup close "$mapeo"\n'
    "    return 1\n"
    "}\n"
)
"""Función `abrir_cryptsetup()` de los `.sh`: devuelve 0 si abre y 1 si no.

Usa `uid`/`gid` porque exFAT y NTFS no guardan dueño y sin ellos todo sería de
root; ext4 (un contenedor hecho en Linux) no los admite y sus ficheros ya
tienen dueño, así que se monta sin ellos. Si no se monta, el mapeo no se queda
abierto.
"""


def _sin_via_sh() -> str:
    """Devuelve la función `sin_via()` de los `.sh`.

    El mensaje de las tres salidas cuando no hay con qué abrirlo.
    """
    lineas = (
        "prdrive: no encuentro con qué abrir el contenedor. En Linux vale cualquiera de",
        "  estas tres cosas:",
        f"  - VeraCrypt: {URL_VERACRYPT}",
        "  - udisks2 (el de casi cualquier escritorio), dejando que reconozca",
        "    contenedores VeraCrypt. Una vez en este equipo, como administrador:",
        f"      {ACTIVAR_UDISKS}",
        "  - cryptsetup (el paquete cryptsetup): pedirá sudo cada vez que lo abras.",
        f"  Más en {v.LEEME}.",
    )
    return ("sin_via() {\n"
            + "".join(f'    echo "{ln}" >&2\n' for ln in lineas)
            + "}\n")


_SIN_TERMINAL_SH = (
    "sin_terminal() {\n"
    '    echo "prdrive: sin VeraCrypt, este equipo abre el contenedor con $1, que pide" >&2\n'
    '    echo "  la contraseña por una terminal. Abre una y escribe:" >&2\n'
    f'    echo "    sh \\"$dir/{v.ABRIR_SH}\\"" >&2\n'
    "}\n"
)
"""Función `sin_terminal()` de los `.sh`: sin VeraCrypt hace falta una terminal."""


def sh_abrir(device_id: str) -> str:
    """Devuelve `abrir-prdrive.sh`.

    Abre el contenedor y lanza el `runsync.sh` de dentro.
    """
    return (
        "#!/bin/sh\n"
        f"# {v.ABRIR_SH} — Abre el contenedor cifrado de prdrive y lanza la ventana.\n"
        "#\n"
        "# Con lo primero que haya en este equipo, por este orden:\n"
        "#   1. VeraCrypt instalado. Pide la contraseña, y la de administrador que\n"
        "#      montar exige, en su ventana; sin escritorio, por esta terminal.\n"
        "#   2. udisks2, si reconoce contenedores VeraCrypt (existe\n"
        f"#      {TCRYPT_CONF}). Sin ser administrador.\n"
        "#   3. cryptsetup, con sudo. Monta en "
        f"{PUNTO_CRYPTSETUP}/{mapeo(device_id)}.\n"
        "# Sin VeraCrypt hace falta una terminal: udisksctl y cryptsetup piden ahí la\n"
        "# contraseña. Nunca pasa por aquí: ni en una línea de órdenes ni por tubería.\n"
        "#\n"
        "# Lo escribe el instalador de prdrive.\n"
        f'ID="{device_id}"\n'
        + _cabecera_sh() +
        'usuario="${USER:-$(id -un 2>/dev/null)}"\n'
        f'mapeo="{mapeo(device_id)}"\n'
        f'punto_cs="$sistema{PUNTO_CRYPTSETUP}/$mapeo"\n'
        "\n"
        + _ESTADO_SH +
        "\n"
        + _BUSCAR_SH +
        "\n"
        + _ABRIR_UDISKS_SH +
        "\n"
        + _ABRIR_CRYPTSETUP_SH +
        "\n"
        + _sin_via_sh() +
        "\n"
        + _SIN_TERMINAL_SH +
        "\n"
        'raiz="$(buscar)"\n'
        'if [ -z "$raiz" ]; then\n'
        "    if command -v veracrypt >/dev/null 2>&1; then\n"
        '        if [ -n "$DISPLAY$WAYLAND_DISPLAY" ]; then\n'
        '            veracrypt "$contenedor"\n'
        "        else\n"
        '            veracrypt --text "$contenedor"\n'
        "        fi\n"
        "    else\n"
        '        via=""\n'
        "        if command -v udisksctl >/dev/null 2>&1 && "
        f'[ -f "$sistema{TCRYPT_CONF}" ]; then\n'
        "            via=udisks2\n"
        "        elif command -v cryptsetup >/dev/null 2>&1; then\n"
        "            via=cryptsetup\n"
        "        fi\n"
        '        if [ -z "$via" ]; then\n'
        "            sin_via\n"
        "            exit 1\n"
        "        fi\n"
        "        if [ ! -t 0 ]; then\n"
        '            sin_terminal "$via"\n'
        "            exit 1\n"
        "        fi\n"
        "        r=2\n"
        '        if [ "$via" = udisks2 ]; then\n'
        "            abrir_udisks\n"
        "            r=$?\n"
        "        fi\n"
        '        if [ "$r" -eq 2 ] && command -v cryptsetup >/dev/null 2>&1; then\n'
        "            abrir_cryptsetup\n"
        "        fi\n"
        "    fi\n"
        '    raiz="$(buscar)"\n'
        "fi\n"
        'if [ -z "$raiz" ]; then\n'
        '    echo "prdrive: el contenedor no se ha abierto." >&2\n'
        "    exit 1\n"
        "fi\n"
        'exec sh "$raiz/runsync.sh" "$@"\n'
    )


_CERRAR_SH = (
    "sigue_abierto() {\n"
    '    echo "prdrive: el contenedor sigue abierto. ¿Queda algún programa usando la" >&2\n'
    '    echo "  unidad? Ciérralo y vuelve a intentarlo. No quites la unidad todavía." >&2\n'
    "    exit 1\n"
    "}\n"
    "\n"
    "cerrar_veracrypt() {\n"
    "    if ! command -v veracrypt >/dev/null 2>&1; then\n"
    '        echo "prdrive: lo abrió VeraCrypt y no lo encuentro para cerrarlo." >&2\n'
    "        exit 1\n"
    "    fi\n"
    '    if [ -n "$DISPLAY$WAYLAND_DISPLAY" ]; then\n'
    '        veracrypt -d "$contenedor"\n'
    "    else\n"
    '        veracrypt --text -d "$contenedor"\n'
    "    fi\n"
    "}\n"
    "\n"
    # El orden inverso al de abrir: desmontar, cerrar el cifrado, soltar el
    # loop.
    "cerrar_udisks() {\n"
    '    if [ -n "$montado" ] && ! udisksctl unmount -b "/dev/$dm"; then\n'
    "        sigue_abierto\n"
    "    fi\n"
    '    if [ -n "$dm" ] && ! udisksctl lock -b "$loop"; then\n'
    "        sigue_abierto\n"
    "    fi\n"
    '    udisksctl loop-delete -b "$loop"\n'
    "}\n"
    "\n"
    # Una sola orden con privilegios, así que con `pkexec` sale una sola
    # ventana. En una terminal, `sudo`; sin ella (el botón «Expulsar» de la
    # ventana lo lanza suelto), `pkexec`, que la pide con el diálogo del
    # escritorio. El loop se suelta solo al cerrar: lo puso cryptsetup.
    "cerrar_cryptsetup() {\n"
    "    if [ -t 0 ]; then\n"
    "        como=sudo\n"
    "    elif command -v pkexec >/dev/null 2>&1; then\n"
    "        como=pkexec\n"
    "    else\n"
    '        echo "prdrive: lo abrió cryptsetup, y cerrarlo pide ser administrador." >&2\n'
    f'        echo "  Abre una terminal y escribe: sh \\"$dir/{v.EXPULSAR_SH}\\"" >&2\n'
    "        exit 1\n"
    "    fi\n"
    '    "$como" sh -c \'if [ -n "$1" ]; then umount "$1" || exit 1; fi; '
    'cryptsetup close "$2"\' \\\n'
    '        sh "$montado" "$nombre" || sigue_abierto\n'
    "}\n"
)
"""Funciones de los `.sh` para cerrar, por cada vía.

`sigue_abierto` sale: lo que queda es no quitar la unidad.
"""


_APP_SH = CONTROL_FILE.parent.as_posix()
"""La carpeta del programa dentro del contenedor (`.prdrive`), para el Python del llavero."""

_LLAVERO_SH = (
    "llavero() {\n"
    '    [ -n "$montado" ] || return 0\n'
    f'    [ -f "$montado/{llavero.LANZADOR_LINUX}" ] || [ -f "$montado/{llavero.LANZADOR}" ] '
    "|| return 0\n"
    '    case "$(uname -m)" in\n'
    f'        x86_64|amd64) py="$montado/{_APP_SH}/{components.RUNTIME_SUBDIR}/linux-x64/bin/python3" ;;\n'
    f'        aarch64|arm64) py="$montado/{_APP_SH}/{components.RUNTIME_SUBDIR}/linux-arm64/bin/python3" ;;\n'
    '        *) py="" ;;\n'
    "    esac\n"
    '    if [ -z "$py" ] || [ ! -x "$py" ]; then\n'
    "        command -v python3 >/dev/null 2>&1 || return 0\n"
    "        py=python3\n"
    "    fi\n"
    f'    "$py" "$montado/{_APP_SH}/runsync.py" --cerrar-llavero\n'
    "}\n"
)
"""Función `llavero()` de `expulsar-prdrive.sh`: lo de `:llavero` del `.bat`.

Solo si la unidad lo lleva (`llavero.sh`, o el `Llavero.bat` de una activación
de antes de Linux) y está montada: cierra KeePassXC, para el vigilante, sube lo
pendiente y quita los manifiestos del navegador (`runsync.py --cerrar-llavero`).
Con el Python del dispositivo para esta CPU o, si no se puede ejecutar desde el
montaje (exFAT, `noexec`), el del equipo; sin ninguno, no hace nada. Sale con 1
si KeePassXC sigue abierto. En Linux KeePassXC no retiene el volumen (corre
extraído en el equipo), pero así lo último sube y el navegador queda como
estaba.
"""


def sh_expulsar() -> str:
    """Devuelve `expulsar-prdrive.sh`.

    Cierra el contenedor con lo mismo que lo abrió.
    """
    return (
        "#!/bin/sh\n"
        f"# {v.EXPULSAR_SH} — Cierra el contenedor cifrado de prdrive.\n"
        "#\n"
        "# Cierra antes la ventana de prdrive. Espera unos segundos: quien lo llama\n"
        "# suele ser la propia ventana, que se está cerrando.\n"
        "#\n"
        "# Con lo mismo que lo abrió, y eso no se apunta: se deduce. El loop que\n"
        "# tiene el contenedor (losetup -j), el dm que cuelga de él y su nombre dicen\n"
        f"# quién: veracryptN es VeraCrypt, {PREFIJO_MAPEO}<id> es cryptsetup desde\n"
        f"# {v.ABRIR_SH}, y cualquier otro es udisks2. Sin loop, VeraCrypt si está.\n"
        "# Con VeraCrypt, `-d` y no `-u`: el segundo es nuevo y las versiones\n"
        "# anteriores no lo conocen.\n"
        "#\n"
        "# Lo escribe el instalador de prdrive.\n"
        + _cabecera_sh() +
        "\n"
        + _ESTADO_SH +
        "\n"
        + _CERRAR_SH +
        "\n"
        + _LLAVERO_SH +
        "\n"
        "sleep 3\n"
        "estado\n"
        "if ! llavero; then\n"
        f'    echo "prdrive: no he cerrado {v.ETIQUETA}: KeePassXC sigue abierto. Ciérralo y" >&2\n'
        '    echo "  vuelve a expulsar. No quites la unidad todavía." >&2\n'
        "    exit 1\n"
        "fi\n"
        'via=""\n'
        'case "$nombre" in\n'
        "    veracrypt*) via=veracrypt ;;\n"
        f"    {PREFIJO_MAPEO}*) via=cryptsetup ;;\n"
        "    ?*) via=udisks2 ;;\n"
        "esac\n"
        # Un loop sin abrir: lo que deja udisks2 si se corta entre `loop-setup` y
        # `unlock` sin llegar a soltarlo.
        'if [ -z "$via" ] && [ -n "$loop" ] && command -v udisksctl >/dev/null 2>&1; then\n'
        "    via=udisks2\n"
        "fi\n"
        'if [ -z "$via" ] && [ -z "$loop" ] && command -v veracrypt >/dev/null 2>&1; then\n'
        "    via=veracrypt\n"
        "fi\n"
        'case "$via" in\n'
        "    veracrypt)\n"
        "        cerrar_veracrypt\n"
        "        exit\n"
        "        ;;\n"
        "    udisks2) cerrar_udisks ;;\n"
        "    cryptsetup) cerrar_cryptsetup ;;\n"
        "    *)\n"
        '        if [ -n "$loop" ]; then\n'
        '            echo "prdrive: $loop tiene el contenedor y no sé soltarlo:" >&2\n'
        '            echo "  sudo losetup -d $loop" >&2\n'
        "            exit 1\n"
        "        fi\n"
        "        if ! command -v losetup >/dev/null 2>&1; then\n"
        '            echo "prdrive: sin losetup (util-linux) no sé si está abierto." >&2\n'
        "            exit 1\n"
        "        fi\n"
        f'        echo "{v.ETIQUETA} ya estaba cerrado. Puedes quitar la unidad."\n'
        "        exit 0\n"
        "        ;;\n"
        "esac\n"
        # No se da por hecho: se mira. El loop de cryptsetup se suelta solo al
        # cerrar, y el kernel puede tardar un momento en hacerlo.
        "n=0\n"
        "estado\n"
        'while [ -n "$loop" ] && [ "$n" -lt 10 ]; do\n'
        "    sleep 1\n"
        "    n=$((n + 1))\n"
        "    estado\n"
        "done\n"
        'if [ -n "$dm" ]; then\n'
        "    sigue_abierto\n"
        "fi\n"
        'if [ -n "$loop" ]; then\n'
        '    echo "prdrive: el contenedor está cerrado, pero $loop todavía lo tiene: no" >&2\n'
        '    echo "  quites la unidad hasta que desaparezca (losetup -j lo dice)." >&2\n'
        "    exit 1\n"
        "fi\n"
        f'echo "{v.ETIQUETA} está cerrado. Ya puedes quitar la unidad."\n'
    )


def leeme() -> str:
    """Devuelve `LEEME-PRDRIVE.txt`.

    Lo único que se puede leer sin abrir el contenedor.
    """
    return (
        f"{v.ETIQUETA} — dispositivo de sincronización cifrado con VeraCrypt\n"
        "\n"
        f"Todo lo tuyo está dentro de {v.CONTENEDOR}. No lo borres ni lo muevas.\n"
        "\n"
        "Para abrirlo\n"
        f"  Windows: doble clic en «{NOMBRE_ABRIR}». VeraCrypt te pedirá la\n"
        "           contraseña (y quizá permiso de administrador) y después se\n"
        "           abre la ventana de prdrive.\n"
        f"  Linux:   sh {v.ABRIR_SH}   en una terminal. Vale cualquiera de estas\n"
        "           tres cosas: VeraCrypt instalado; udisks2 preparado para\n"
        "           VeraCrypt (sin administrador); o cryptsetup (con sudo).\n"
        "\n"
        "Para quitarlo\n"
        "  Cierra antes el contenedor: «Expulsar» en la ventana de prdrive, o\n"
        f"  doble clic en «{NOMBRE_EXPULSAR}» (Linux: sh {v.EXPULSAR_SH}). Si quitas\n"
        "  la unidad con el contenedor abierto, puede estropearse lo de dentro.\n"
        "\n"
        "Si el equipo no tiene VeraCrypt\n"
        "  La carpeta VeraCrypt de esta unidad, si está, lleva uno que funciona sin\n"
        "  instalar en Windows (pide permiso de administrador). Si no, instálalo:\n"
        f"  {URL_VERACRYPT}\n"
        "  En Linux no hace falta: udisks2 y cryptsetup vienen en casi todas las\n"
        "  distribuciones. Para que udisks2 lo abra sin administrador, una vez en\n"
        "  cada equipo:\n"
        f"    {ACTIVAR_UDISKS}\n"
        f"  Sin eso, {v.ABRIR_SH} usa cryptsetup y pide sudo cada vez.\n"
    )


def marca(device_id: str) -> str:
    """Devuelve el contenido de `.prdrive-vestibulo`."""
    return (
        f"# {v.ETIQUETA} — entrada de un dispositivo prdrive cifrado con VeraCrypt. "
        "NO LA BORRES.\n"
        f"# El dispositivo está dentro de {v.CONTENEDOR}; esta marca es lo que "
        "permite\n"
        "# reconocerlo desde fuera, antes de abrirlo.\n"
        f"id={device_id}\n"
        f"contenedor={v.CONTENEDOR}\n"
    )


def escribir(raiz_fisica: Path | str, device_id: str) -> list[Path]:
    """Deja el vestíbulo en la raíz física y devuelve lo escrito.

    Sobrescribe lo que hubiera: es también la forma de ponerlo al día.

    Raises:
        InstallError: Si no hay id o no se puede escribir; sin esto el
            dispositivo solo se abre a mano.
    """
    if not device_id:
        raise InstallError("Sin el id del dispositivo no se puede escribir su "
                           "entrada: nadie sabría reconocerlo desde fuera.")
    raiz = Path(raiz_fisica)
    ficheros = (
        (v.ABRIR_BAT, bat_abrir(device_id), "\r\n", "utf-8"),
        (v.EXPULSAR_BAT, bat_expulsar(device_id), "\r\n", "utf-8"),
        (v.ABRIR_SH, sh_abrir(device_id), "\n", "utf-8"),
        (v.EXPULSAR_SH, sh_expulsar(), "\n", "utf-8"),
        # Con BOM: el Bloc de notas de Windows antiguo no adivina UTF-8 sin él.
        (v.LEEME, leeme(), "\r\n", "utf-8-sig"),
        (v.MARCA, marca(device_id), "\n", "utf-8"),
    )
    from .deploy import hide, unhide
    # Al ponerlo al día la marca ya está oculta, y Windows no deja reescribir un
    # fichero oculto con `open(…, "w")` (ver `unhide()`): se destapa, se escribe
    # y se vuelve a ocultar abajo.
    unhide(raiz / v.MARCA)
    escrito = []
    for nombre, texto, fin, codificacion in ficheros:
        ruta = raiz / nombre
        try:
            ruta.write_text(texto, encoding=codificacion, newline=fin)
        except OSError as e:
            raise InstallError(f"No he podido escribir {ruta}: {e}") from e
        escrito.append(ruta)
    hide(raiz / v.MARCA)
    if not IS_WIN:
        for nombre in (v.ABRIR_SH, v.EXPULSAR_SH):
            try:
                sh = raiz / nombre
                sh.chmod(sh.stat().st_mode | stat.S_IXUSR)
            except OSError:
                pass        # exFAT: no hay bit de ejecución, y `sh x.sh` va igual
    return escrito


def comprobar(raiz_fisica: Path | str, device_id: str | None) -> list[Check]:
    """Devuelve la fila del último paso.

    ¿se podrá abrir este dispositivo desde fuera?
    """
    raiz = Path(raiz_fisica)
    try:
        faltan = [n for n in (v.ABRIR_BAT, v.EXPULSAR_BAT, v.ABRIR_SH,
                              v.EXPULSAR_SH, v.LEEME) if not (raiz / n).is_file()]
    except OSError as e:
        return [Check("Entrada del dispositivo", False, f"no se puede leer: {e}")]
    marcado = v.leer_id(raiz)
    if marcado is None:
        return [Check("Entrada del dispositivo", False,
                      f"falta {v.MARCA}: desde fuera no se reconocerá")]
    if device_id and marcado != device_id:
        return [Check("Entrada del dispositivo", False,
                      "la marca es de otro dispositivo: vuelve a instalar")]
    if faltan:
        return [Check("Entrada del dispositivo", False, "falta " + ", ".join(faltan))]
    return [Check("Entrada del dispositivo", True,
                  f"«{NOMBRE_ABRIR}» y «{NOMBRE_EXPULSAR}» en {raiz}")]


def destino(state) -> Path | None:
    """Devuelve dónde va el vestíbulo de lo que el asistente está preparando, o `None`.

    Solo cuando el dispositivo vive dentro de un contenedor: `device_root` (lo
    montado) no es `device` (el volumen físico) y en el físico está el `.hc`.
    Se mira el disco y no `state.encryption` porque en el recorrido corto
    («Añadir plataformas…» sobre un dispositivo que ya existe) lo que cuenta es
    lo que hay y no lo que se eligió en otra pasada.
    """
    if state.device is None or state.device_root is None:
        return None
    fisica = Path(state.device)
    try:
        if fisica.resolve() == Path(state.device_root).resolve():
            return None
        return fisica if (fisica / v.CONTENEDOR).is_file() else None
    except OSError:
        return None
