#!/usr/bin/env python3
"""
vestibulo.py — Escribir la entrada de un dispositivo cifrado con VeraCrypt. Sin Tkinter.

Qué es el vestíbulo y por qué existe está en `common/vestibulo.py`. Aquí están
los textos de los lanzadores y la escritura, que es cosa del instalador: se hace
al aprovisionar (paso 5) y en «Añadir plataformas…», y **nunca** al actualizar el
programa, igual que los lanzadores de dentro.

Lo que no se puede relajar, todo contra el código de VeraCrypt (tag
VeraCrypt_1.26.24; las citas, en la spec
`docs/superpowers/specs/2026-09-23-veracrypt-ciclo-de-vida-design.md`):

  * **La contraseña no pasa por aquí.** `VeraCrypt.exe /volume X /quit` sin
    `/password` pide la contraseña con SU diálogo (`Mount/Mount.c`,
    `WM_INITDIALOG`: «Ask user for password»). Ni el `.bat` ni ningún proceso
    nuestro la ven, y no aparece en ninguna línea de órdenes.
  * **El VeraCrypt instalado va antes que el que viaja.** Con otra versión
    instalada y su driver cargado, el que viaja falla con `ERR_DRIVER_VERSION`
    (`Common/Dlgcode.c`, `DriverAttach`).
  * **El código de salida no dice si se ha montado.** El que viaja, sin
    permisos de administrador, se relanza elevado con `/q UAC`, espera dos
    segundos y sale con 0 (`Common/Dlgcode.c`, `InitApp` y
    `LaunchElevatedProcess`): la contraseña la pide la otra instancia. Por eso
    se espera a VER la unidad, y con el que viaja se espera más.
  * **`/dismount`, no `/unmount`**: el segundo no existe antes de la 1.26.24.
  * **Sin `/auto`**: además de montar, abre una ventana del Explorador
    (`ExtractCommandLine`: `bExplore = TRUE`). Con `/quit` y `/volume` ya monta.
  * **La letra no dice si el contenedor está abierto**, en ningún sentido. Tras
    forzar el cierre con algo abierto dentro, la letra se va y Windows sigue
    sin dejar quitar la unidad; tras quitarla sin expulsar, la letra se queda y
    sirve el fichero de control de la caché. Lo que sí lo dice es el propio
    `.hc`: montado, el driver lo retiene. Eso mira `:libre` (`_LIBRE_BAT`).

Los `.bat` siguen las reglas de `runsync.bat` (`deploy.LAUNCHER_BAT`): CRLF, sin
bloques entre paréntesis —una ruta con «)» los rompe— y `chcp 65001` solo antes
de escribir algo con acentos.
"""

from __future__ import annotations

import stat
from pathlib import Path

from common import vestibulo as v

from . import IS_WIN, InstallError
from .device import CONTROL_FILE, Check

URL_VERACRYPT = "https://veracrypt.jp/en/Downloads.html"

# Como se ven en el Explorador, que esconde la extensión.
NOMBRE_ABRIR = Path(v.ABRIR_BAT).stem
NOMBRE_EXPULSAR = Path(v.EXPULSAR_BAT).stem

# Cuánto se espera a ver la unidad después de VeraCrypt, en segundos. Con el
# instalado su código de salida sí es el del montaje; con el que viaja no (ver
# el docstring), y hay que dejarle a la persona el tiempo de escribir la
# contraseña en la ventana elevada.
ESPERA_INSTALADO = 10
ESPERA_VIAJERO = 180

_CONTROL_BAT = str(CONTROL_FILE).replace("/", "\\")

# Buscar la unidad donde ha quedado el contenedor: la que tenga el fichero de
# control con ESTE id. `/b` y no `/x`: el fichero puede venir de Linux (LF) o de
# Windows (CRLF), y el id es un uuid4 de longitud fija, así que empezar igual es
# ser igual. A y B al final, como hace VeraCrypt al elegir letra
# (`GetFirstAvailableDrive`).
_BUSCAR_BAT = (
    ":buscar\n"
    'set "RAIZ="\n'
    "for %%L in (C D E F G H I J K L M N O P Q R S T U V W X Y Z A B) do "
    f'if exist "%%L:\\{_CONTROL_BAT}" '
    f'findstr /b /l /c:"id=%ID%" "%%L:\\{_CONTROL_BAT}" >nul 2>&1 && set "RAIZ=%%L:"\n'
    "exit /b 0\n"
)

# ¿Ha quedado suelto el contenedor? 0 si nadie lo tiene abierto. Con el volumen
# montado, el driver lo tiene abierto sin dejar escribir a nadie más
# (`TCOpenVolume()`, `Driver/Ntvol.c`, con `bExclusiveAccess`), así que abrirlo
# para añadir falla. La excepción: si al montar otro proceso ya tenía el
# fichero abierto, `MountVolume()` (`Common/Dlgcode.c`) monta compartido —con
# `/silent` sin preguntar, sin él preguntando— y entonces esto lo ve suelto
# aunque esté montado. `type nul` no añade nada: ni el contenido ni la fecha
# cambian. Sin el contenedor al lado devuelve 1 y no lo crea: sin él no se
# puede afirmar nada, y quien llama sigue como antes. El `2>nul` va en el `call`
# porque en la misma línea que `>>` no tapa el mensaje de cmd cuando la
# apertura falla, y sin paréntesis no hay otra forma de envolverla.
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

# El VeraCrypt que se usa: el instalado antes que el que viaja.
_ELEGIR_BAT = (
    'set "VC="\n'
    'if exist "%ProgramFiles%\\VeraCrypt\\VeraCrypt.exe" '
    'set "VC=%ProgramFiles%\\VeraCrypt\\VeraCrypt.exe"\n'
    'if not defined VC if exist "%ProgramW6432%\\VeraCrypt\\VeraCrypt.exe" '
    'set "VC=%ProgramW6432%\\VeraCrypt\\VeraCrypt.exe"\n'
    'if not defined VC if exist "%~dp0VeraCrypt\\VeraCrypt.exe" set "VIAJERO=1"\n'
    'if not defined VC if exist "%~dp0VeraCrypt\\VeraCrypt.exe" '
    'set "VC=%~dp0VeraCrypt\\VeraCrypt.exe"\n'
    "if not defined VC goto sin_veracrypt\n"
)

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


def bat_abrir(device_id: str) -> str:
    """`Abrir PRDRIVE.bat`: abre el contenedor y lanza el `runsync.bat` de dentro."""
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
        "rem      instalado, el que viaja no puede cargar su driver). La contrasena\n"
        "rem      la pide VeraCrypt en su ventana: nunca pasa por aqui.\n"
        "rem   3. Busca la unidad por el id del dispositivo y lanza su runsync.bat.\n"
        "rem\n"
        "rem No se fia del codigo de salida: el VeraCrypt que viaja, sin permisos de\n"
        "rem administrador, se relanza elevado y sale enseguida con 0 mientras la\n"
        "rem otra ventana pide la contrasena. Por eso espera a ver la unidad.\n"
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
        + _ELEGIR_BAT +
        f'set "ESPERA={ESPERA_INSTALADO}"\n'
        f'if defined VIAJERO set "ESPERA={ESPERA_VIAJERO}"\n'
        f"echo Abriendo {v.ETIQUETA}: escribe la contrasena en la ventana de VeraCrypt.\n"
        "if defined VIAJERO echo Si la has cancelado, cierra esta ventana.\n"
        f'start "" /wait "%VC%" /volume "%~dp0{v.CONTENEDOR}" /mountoption rm '
        f"/mountoption label={v.ETIQUETA} /history n /cache n /quit\n"
        'if errorlevel 1 if not defined VIAJERO set "ESPERA=1"\n'
        'set "INTENTOS=0"\n'
        ":esperar\n"
        "call :buscar\n"
        "if defined RAIZ goto lanzar\n"
        "set /a INTENTOS+=1\n"
        "if %INTENTOS% geq %ESPERA% goto no_abierto\n"
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
    """`Expulsar PRDRIVE.bat`: cierra el contenedor para poder quitar la unidad."""
    return (
        "@echo off\n"
        f"rem {v.EXPULSAR_BAT} - Cierra el contenedor cifrado de prdrive.\n"
        "rem\n"
        "rem Cierra antes la ventana de prdrive: mientras corre, sus ficheros estan\n"
        "rem abiertos dentro del contenedor. Si queda algo abierto, VeraCrypt\n"
        "rem pregunta si forzar, con su propia ventana (por eso NO va con /silent).\n"
        "rem Espera unos segundos antes: quien lo llama suele ser la propia ventana,\n"
        "rem que se esta cerrando, y VeraCrypt reintenta el desmontaje solo 1,5 s.\n"
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
        'start "" /wait "%VC%" /dismount %RAIZ:~0,1% /quit\n'
        'set "INTENTOS=0"\n'
        ":esperar\n"
        "call :buscar\n"
        "if not defined RAIZ goto sin_letra\n"
        "set /a INTENTOS+=1\n"
        "if %INTENTOS% geq 30 goto sigue_abierto\n"
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
        + _LIBRE_BAT +
        "\n"
        + _SIN_VERACRYPT_BAT
    )


# Dónde monta VeraCrypt en Linux si no se le dice otra cosa:
# `CoreUnix::GetDefaultMountPointPrefix()` (`Core/Unix/CoreUnix.cpp`) elige
# `VERACRYPT_MOUNT_PREFIX`, o /media/veracrypt, /run/media/veracrypt,
# /mnt/veracrypt, o `<tmp>/veracrypt_mnt`, y le añade el número de ranura.
_BUSCAR_SH = (
    "buscar() {\n"
    '    set -- /media/veracrypt* /run/media/veracrypt* /mnt/veracrypt* \\\n'
    '           "${TMPDIR:-/tmp}"/veracrypt_mnt*\n'
    '    if [ -n "$VERACRYPT_MOUNT_PREFIX" ]; then\n'
    '        set -- "$@" "$VERACRYPT_MOUNT_PREFIX"*\n'
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

_SIN_VERACRYPT_SH = (
    "if ! command -v veracrypt >/dev/null 2>&1; then\n"
    '    echo "prdrive: no encuentro VeraCrypt. En Linux tiene que estar instalado" >&2\n'
    f'    echo "  (no viaja en la unidad): {URL_VERACRYPT}" >&2\n'
    "    exit 1\n"
    "fi\n"
)


def sh_abrir(device_id: str) -> str:
    """`abrir-prdrive.sh`: abre el contenedor y lanza el `runsync.sh` de dentro."""
    return (
        "#!/bin/sh\n"
        f"# {v.ABRIR_SH} — Abre el contenedor cifrado de prdrive y lanza la ventana.\n"
        "#\n"
        "# La contraseña la pide VeraCrypt, y también la de administrador, que en\n"
        "# Linux hace falta para montar: nunca pasan por aquí. Con escritorio se usa\n"
        "# su ventana; sin él, --text, que pregunta por esta terminal.\n"
        "#\n"
        "# Lo escribe el instalador de prdrive.\n"
        f'ID="{device_id}"\n'
        'dir="$(cd "$(dirname "$0")" && pwd)"\n'
        f'contenedor="$dir/{v.CONTENEDOR}"\n'
        "\n"
        + _BUSCAR_SH +
        "\n"
        'raiz="$(buscar)"\n'
        'if [ -z "$raiz" ]; then\n'
        + "".join("    " + linea + "\n" for linea in _SIN_VERACRYPT_SH.splitlines()) +
        '    if [ -n "$DISPLAY$WAYLAND_DISPLAY" ]; then\n'
        '        veracrypt "$contenedor"\n'
        "    else\n"
        '        veracrypt --text "$contenedor"\n'
        "    fi\n"
        '    raiz="$(buscar)"\n'
        "fi\n"
        'if [ -z "$raiz" ]; then\n'
        '    echo "prdrive: el contenedor no se ha abierto." >&2\n'
        "    exit 1\n"
        "fi\n"
        'exec sh "$raiz/runsync.sh" "$@"\n'
    )


def sh_expulsar() -> str:
    """`expulsar-prdrive.sh`: cierra el contenedor."""
    return (
        "#!/bin/sh\n"
        f"# {v.EXPULSAR_SH} — Cierra el contenedor cifrado de prdrive.\n"
        "#\n"
        "# Cierra antes la ventana de prdrive. Espera unos segundos: quien lo llama\n"
        "# suele ser la propia ventana, que se está cerrando. `-d` y no `-u`: el\n"
        "# segundo es nuevo y las versiones anteriores no lo conocen.\n"
        "#\n"
        "# Lo escribe el instalador de prdrive.\n"
        'dir="$(cd "$(dirname "$0")" && pwd)"\n'
        f'contenedor="$dir/{v.CONTENEDOR}"\n'
        + _SIN_VERACRYPT_SH +
        "sleep 3\n"
        'if [ -n "$DISPLAY$WAYLAND_DISPLAY" ]; then\n'
        '    veracrypt -d "$contenedor"\n'
        "else\n"
        '    veracrypt --text -d "$contenedor"\n'
        "fi\n"
    )


def leeme() -> str:
    """`LEEME-PRDRIVE.txt`: lo único que se puede leer sin abrir el contenedor."""
    return (
        f"{v.ETIQUETA} — dispositivo de sincronización cifrado con VeraCrypt\n"
        "\n"
        f"Todo lo tuyo está dentro de {v.CONTENEDOR}. No lo borres ni lo muevas.\n"
        "\n"
        "Para abrirlo\n"
        f"  Windows: doble clic en «{NOMBRE_ABRIR}». VeraCrypt te pedirá la\n"
        "           contraseña (y quizá permiso de administrador) y después se\n"
        "           abre la ventana de prdrive.\n"
        f"  Linux:   sh {v.ABRIR_SH}   (VeraCrypt tiene que estar instalado)\n"
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
    )


def marca(device_id: str) -> str:
    """El contenido de `.prdrive-vestibulo`."""
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
    """Deja el vestíbulo en la raíz física. Devuelve lo escrito.

    Se sobrescribe lo que hubiera: es también la forma de ponerlo al día. Lanza
    InstallError si no se puede, porque sin esto el dispositivo solo se abre a
    mano."""
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
    """La fila del último paso: ¿se podrá abrir este dispositivo desde fuera?"""
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
    """Dónde va el vestíbulo de lo que el asistente está preparando, o None.

    Solo cuando el dispositivo vive dentro de un contenedor: `device_root` (lo
    montado) no es `device` (el volumen físico) y en el físico está el `.hc`.
    Se mira el disco y no `state.encryption` porque en el recorrido corto
    —«Añadir plataformas…» sobre un dispositivo que ya existe— lo que cuenta es
    lo que hay, no lo que se eligió en otra pasada."""
    if state.device is None or state.device_root is None:
        return None
    fisica = Path(state.device)
    try:
        if fisica.resolve() == Path(state.device_root).resolve():
            return None
        return fisica if (fisica / v.CONTENEDOR).is_file() else None
    except OSError:
        return None
