#!/usr/bin/env python3
"""Lo que dice rclone al fallar, en llano: el catálogo de errores conocidos.

Cada entrada reconoce un error de rclone por las agujas que deja en el log y dice,
para la persona que usa el disco, qué significa, si por sí solo arriesga datos y
qué hacer. Lo leen las tres salidas que explican un fallo: la consola de `sync.py`
(`KNOWN_ERRORS`, que se construye desde aquí), `sync.py --doctor` y «Reparación»
(las dos a través de `common/revision.py`). Vive en `common/` porque `sync.py` no
importa `ui/`: una sola tabla, un solo texto.

No reconoce los frenos de borrados: eso es de `common/frenos.py`, que se mira antes
y tiene su propio hallazgo. Las agujas de red viven en `common/moderacion.py`
porque el agente residente las comparte y no lleva `sync.py`.

Reglas del catálogo:

- **Gana la primera entrada que casa**, en el orden de `ENTRADAS`. Lo concreto va
  antes que lo general: la autenticación SFTP antes que la red (rclone envuelve
  los dos en `couldn't connect SSH`, `backend/sftp/sftp.go:817`), cualquier causa
  antes que `Failed to create file system` y que el aborto crítico de bisync, y
  los errores de arranque de rclone (flags) al final.
- **No se inventa nada.** Un texto que no casa da `None`, y quien enseña el fallo
  enseña entonces lo que dijo rclone tal cual. Un `EINVAL` suelto (`invalid
  argument` sin «for "…" flag») no se interpreta: no hay forma de saber su causa.
- **Cada aguja está comprobada** contra el rclone fijado en `common/pins.py`
  (`comprobado`): en su código fuente o en un log capturado con él. Las que no
  salen de su árbol (`x/crypto/ssh`, la API de Google, los textos de Windows) se
  comprueban en el módulo de la versión que fija su `go.mod`, o en el sistema.
  Cuando se mueve `RCLONE_VERSION`, se revisa este catálogo (`updating.md`).

Las agujas de texto se comparan sin distinguir mayúsculas; las expresiones
regulares, tal como están escritas.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from . import bisync, frenos, moderacion

REINTENTAR = "reintentar"
"""Arreglo: una pasada normal, la misma que haría el servicio."""
RESYNC = "resync"
"""Arreglo: rehacer la referencia de bisync («Resincronizar…» de «Reparación»)."""
LOCK = "lock"
"""Arreglo: borrar los `.lck` que quedaron («Borrar los bloqueos…» de «Reparación»)."""
ARREGLOS = frozenset({REINTENTAR, RESYNC, LOCK})
"""Los arreglos que una entrada puede proponer: los botones que ya existen."""

COMPROBADO = "v1.75.2"
"""La versión de rclone contra la que se comprobaron las agujas de este catálogo."""

Aguja = str | re.Pattern | Callable[[str], object]
"""Una aguja: texto (sin mayúsculas), expresión regular o función sobre el log."""


@dataclass(frozen=True)
class Causa:
    """Un error de rclone reconocido, explicado para quien usa el disco.

    Args:
        clave: Qué error es, para el código (`"red"`, `"bloqueo"`…).
        nombre: Cómo se llama, en llano y en una frase corta.
        explicacion: Qué significa y la causa más probable.
        riesgo: Una frase: si este error, por sí solo, arriesga datos.
        a_mano: Qué hacer a mano, o `None` si basta con el arreglo.
        arreglos: Los arreglos que se proponen, de `ARREGLOS`, en su orden.
        comprobado: La versión de rclone con la que se comprobaron sus agujas.
    """
    clave: str
    nombre: str
    explicacion: str
    riesgo: str
    a_mano: str | None = None
    arreglos: tuple[str, ...] = ()
    comprobado: str = COMPROBADO

    @property
    def texto(self) -> str:
        """La explicación y, si lo hay, qué hacer a mano: lo que imprime la consola."""
        return f"{self.explicacion} {self.a_mano}" if self.a_mano else self.explicacion


_COMO_RESYNC = ("Se rehace con un resync: «Resincronizar…» en «Reparación», o "
                "`python sync.py <pareja> --resync`.")
"""Lo que se hace a mano cuando bisync pide rehacer su referencia."""

SIN_REFERENCIA = Causa(
    "sin_referencia", "No está la referencia de la última sincronización",
    "bisync no encuentra los listados de la última sincronización buena: es la "
    "primera vez, la ruta de la pareja cambió o un fallo grave anterior los invalidó. "
    "Sin ellos no sabe qué se ha borrado en cada lado, así que no sigue.",
    "Por sí solo no arriesga nada: no ha tocado ningún fichero.",
    _COMO_RESYNC, (RESYNC,))
FILTROS = Causa(
    "filtros", "Han cambiado los filtros",
    "Han cambiado los filtros de la pareja (lo que se excluye), o es la primera vez que "
    "se usan. bisync no puede saber qué ficheros excluidos existían antes y pide rehacer "
    "la referencia.",
    "Por sí solo no arriesga nada: bisync se paró antes de copiar.",
    _COMO_RESYNC, (RESYNC,))
AUTENTICACION = Causa(
    "autenticacion", "El remoto no acepta la conexión",
    "El remoto contesta, pero rechaza el inicio de sesión: la contraseña o la clave ya "
    "no valen, o el permiso que se le dio a rclone (el token) ha caducado o se ha "
    "retirado.",
    "No arriesga datos: no se ha podido entrar, así que no se ha tocado nada.",
    "Vuelve a autorizar el remoto: `rclone config reconnect <remoto>:` con el "
    "`rclone.conf` de `.prdrive/`, o rehaz la conexión con el instalador.")
LIMITE_API = Causa(
    "limite_api", "El servicio ha puesto un límite de uso",
    "El remoto (un servicio en la nube, como Google Drive) ha rechazado peticiones por "
    "pasarse de su límite de uso. El límite se levanta solo con el tiempo.",
    "No arriesga datos: lo que no se copió se copia en una pasada posterior.",
    "Reinténtalo más tarde. Si pasa en cada pasada, baja `transfers` y `checkers` en "
    "los flags de la pareja.", (REINTENTAR,))
REMOTO_LLENO = Causa(
    "remoto_lleno", "El remoto está lleno",
    "Se ha acabado el espacio (la cuota) de la cuenta del remoto y no admite más "
    "ficheros.",
    "Lo que ya estaba no corre peligro, pero lo nuevo no llega al remoto hasta que haya "
    "sitio.",
    "Libera espacio en el remoto, o amplía la cuota; la siguiente pasada sube lo que "
    "falte.")
DISCO_LLENO = Causa(
    "disco_lleno", "No queda sitio en el disco",
    "Se ha llenado el disco en el que se estaba escribiendo (el dispositivo o, si el "
    "remoto es una carpeta, el suyo) y la copia se cortó a medias.",
    "Lo que ya estaba no se ha tocado: rclone tira el fichero que dejó a medio escribir.",
    "Libera sitio donde se escribía; la siguiente pasada copia lo que falte.")
EN_USO = Causa(
    "en_uso", "Un fichero está en uso",
    "Fichero bloqueado por otro proceso (Obsidian, KeePass, antivirus): Windows no deja "
    "tocarlo mientras otro programa lo tiene abierto.",
    "No arriesga datos: ese fichero se queda como estaba hasta la próxima pasada.",
    "Cierra el programa que lo tiene abierto y reinténtalo.", (REINTENTAR,))
PERMISO = Causa(
    "permiso", "Permiso denegado",
    "rclone no tiene permiso para leer o escribir una carpeta o un fichero: en este "
    "equipo (la carpeta local) o en el remoto (el usuario con el que se entra).",
    "No arriesga datos: lo que no se pudo leer o escribir se queda como estaba.",
    "Revisa los permisos de esa carpeta (el log dice cuál) en este equipo, o los del "
    "usuario del remoto.")
NOMBRE_INVALIDO = Causa(
    "nombre_invalido", "Un nombre no vale en el destino",
    "Un fichero o una carpeta tiene un nombre, o una ruta, que el otro lado no admite: "
    "demasiado largo, o con caracteres que ese sistema de ficheros no acepta.",
    "No arriesga datos: ese fichero no se copia y se queda como estaba.",
    "Busca en el log el nombre que falla y acórtalo o cámbialo en el lado de donde sale.")
SIN_SECCION = Causa(
    "sin_seccion", "El remoto de la pareja no está en rclone.conf",
    "La pareja usa un remoto que no está definido en el `rclone.conf` de este "
    "dispositivo: falta su sección, o el nombre está mal escrito.",
    "No arriesga datos: rclone no ha llegado a empezar.",
    "Revisa en «Parejas» qué remoto usa la pareja. Si es el bueno, falta en "
    "`rclone.conf`: rehaz la conexión con el instalador.")
CARPETA_REMOTA = Causa(
    "carpeta_remota", "No se encuentra la carpeta",
    "Una de las carpetas de la pareja no existe: casi siempre la del remoto, que se ha "
    "movido, renombrado o borrado.",
    "Por sí solo no ha borrado nada, pero no la crees vacía: un lado vacío se lee como "
    "«se ha borrado todo».",
    "Comprueba en el remoto que la carpeta sigue ahí con el mismo nombre. Si la has "
    "movido, cambia su ruta en «Parejas».")
KNOWN_HOSTS = Causa(
    "known_hosts", "No se puede leer known_hosts",
    "rclone no puede leer el fichero de known_hosts indicado en rclone.conf (no existe o "
    "está mal formado).",
    "No arriesga datos: no se ha llegado a conectar.",
    "Las rutas relativas de rclone.conf se resuelven contra .prdrive/; comprueba que "
    "keys/known_hosts existe ahí.")
BLOQUEO = Causa(
    "bloqueo", "Hay un bloqueo de otra pasada",
    "bisync ha encontrado el bloqueo (.lck) de otra pasada de esta pareja: o sigue en "
    "marcha, o se cortó sin terminar y lo dejó.",
    "No arriesga datos: se ha parado justo para no pisar a la otra pasada.",
    "Si no hay ninguna sincronización en marcha, borra el .lck del workdir de la "
    "pareja («Borrar los bloqueos…» en «Reparación»).", (LOCK,))
RED = Causa(
    "red", "Sin conexión con el remoto",
    moderacion.EXPLICACION_RED,
    "No arriesga datos: no ha llegado a tocar nada.",
    None, (REINTENTAR,))
SIN_EXTREMO = Causa(
    "sin_extremo", "rclone no ha podido abrir un extremo",
    "rclone no ha podido montar uno de los dos extremos. Suele ser una ruta o "
    "credencial mal resuelta en rclone.conf (revisa key_file y known_hosts_file), o el "
    "remoto inalcanzable.",
    "No arriesga datos: rclone no ha llegado a empezar.",
    "La línea «Failed to create file system» del log dice qué extremo y por qué.")
CRITICO = Causa(
    "critico", "bisync se ha parado con un error grave",
    "bisync se ha parado con un error crítico (está en las líneas de arriba del log) y "
    "ha invalidado su referencia: exige rehacerla.",
    "Por sí solo no arriesga nada, pero hasta rehacerla esta pareja no se sincroniza.",
    _COMO_RESYNC, (RESYNC,))
FLAG_DESCONOCIDO = Causa(
    "flag_desconocido", "rclone no conoce un flag",
    "rclone no conoce uno de los flags. Está escrito en sync_config.toml (o en el editor "
    "de flags de la ventana de parejas): rclone lo rechaza antes de empezar, por eso no "
    "hay más log que este.",
    "No arriesga datos: rclone no ha llegado a empezar.",
    "Corrígelo en «Parejas», en los flags de la pareja.")
FLAG_VALOR = Causa(
    "flag_valor", "Un flag tiene un valor que no vale",
    "rclone rechaza el VALOR de un flag: no es de los que admite (por ejemplo "
    "conflict-resolve = \"new\" cuando lo válido es \"newer\"). El mensaje del log dice "
    "qué espera.",
    "No arriesga datos: rclone no ha llegado a empezar.",
    "Corrígelo en «Parejas», en los flags de la pareja (o en sync_config.toml).")

ENTRADAS: tuple[tuple[tuple[Aguja, ...], Causa], ...] = (
    # Lo que bisync escribe al no encontrar sus listados (cmd/bisync/operations.go).
    ((bisync.MISSING_LISTINGS,), SIN_REFERENCIA),
    # cmd/bisync/operations.go; las dos llevan detrás «(must run --resync)», así que
    # van antes que `CRITICO`.
    (("filters file has changed", "filters file md5 hash not found"), FILTROS),
    # Aquí van los frenos de `frenos.ENTRADAS` (ver `agujas_de_consola()`).
    #
    # Antes que la red: backend/sftp/sftp.go:817 envuelve en «couldn't connect SSH»
    # también el rechazo de x/crypto/ssh v0.57.0 (ssh/client_auth.go:154, «ssh:
    # unable to authenticate»). Los de OAuth: lib/oauthutil/oauthutil.go:186, 292,
    # 302 y 341 («rclone config reconnect») y 368 («couldn't fetch token»).
    (("rclone config reconnect", "couldn't fetch token", "unable to authenticate"),
     AUTENTICACION),
    # Los motivos de la API de Google (backend/drive/drive.go:959), que
    # googleapi.Error.Error() escribe tras la coma (google.golang.org/api v0.293.0,
    # googleapi/googleapi.go:117).
    (("rateLimitExceeded",), LIMITE_API),
    # drive.go:968; la expresión no casa con `downloadQuotaExceeded`, que es otro
    # límite. «Insufficient Storage» es el estado HTTP 507 que rclone escribe cuando
    # el servidor no da un error propio (backend/onedrive/onedrive.go:1055,
    # lib/rest/rest.go:73: `resp.Status`), como un WebDAV lleno.
    ((re.compile(r"(?<![A-Za-z])(?:storageQuotaExceeded|quotaExceeded)\b"),
      "Insufficient Storage"), REMOTO_LLENO),
    # ENOSPC (capturado en Linux), el aviso de lib/file/preallocate.go:6 (capturado)
    # y FormatMessage(112) de Windows, en inglés y en español.
    (("no space left on device", "file too big for remaining disk space",
      "There is not enough space on the disk", "No hay espacio suficiente en el disco"),
     DISCO_LLENO),
    # FormatMessage(5) y (32) de Windows, en inglés y en español.
    (("Access is denied", "being used by another process", "Acceso denegado",
      "está siendo utilizado por otro proceso"), EN_USO),
    # fs/fs.go:49, y el EACCES del sistema (capturado).
    (("permission denied",), PERMISO),
    # fs/fs.go:53 y ENAMETOOLONG (capturado); FormatMessage(123) de Windows.
    (("file name too long",
      "The filename, directory name, or volume label syntax is incorrect",
      "La sintaxis del nombre de archivo"), NOMBRE_INVALIDO),
    # fs/fs.go:27 (capturado).
    (("didn't find section in config file",), SIN_SECCION),
    # fs/fs.go:36 (capturado).
    (("directory not found",), CARPETA_REMOTA),
    # Lo que dice sftp cuando `knownhosts.New()` no puede abrir o leer el fichero
    # (`NewFs`, backend/sftp/sftp.go). «known_hosts_file» a secas casaría también con
    # el NOTICE «No host key validation is being performed» de cada pasada a un
    # remoto sin ese fichero.
    (("couldn't parse known_hosts_file",), KNOWN_HOSTS),
    # cmd/bisync/lockfile.go, `setLockFile`. «lock file» a secas casaría también con
    # el «lock file renewed» de `--max-lock`.
    (("prior lock file found",), BLOQUEO),
    # Ya cubre los plazos (`i/o timeout`, `context deadline exceeded`, `tls
    # handshake timeout`). Va antes de la siguiente, que suele acompañarla.
    ((moderacion.es_de_red,), RED),
    (("Failed to create file system",), SIN_EXTREMO),
    # El aborto crítico de bisync (cmd/bisync/operations.go: «Bisync aborted. Must
    # run --resync to recover.»). Suele seguir a una causa que ya explica una entrada
    # de arriba: por eso va detrás de todas las de causas concretas.
    (("Must run --resync",), CRITICO),
    # Errores de ARRANQUE: rclone rechaza la orden antes de instalar `--log-file`.
    # Van al final para que gane cualquier error ocurrido durante la sincronización.
    # El de valor es el texto de pflag: un `invalid argument` suelto es un EINVAL.
    (("unknown flag",), FLAG_DESCONOCIDO),
    ((re.compile(r'invalid argument ".*" for ".*" flag'),), FLAG_VALOR),
)
"""El catálogo, en orden: cada entrada son sus agujas y la causa que reconocen."""

_TRAS_LOS_FRENOS = 2
"""Cuántas entradas de `ENTRADAS` van antes que los frenos en la consola."""


def casa(aguja: Aguja, texto: str, bajo: str | None = None) -> bool:
    """Indica si una aguja está en el texto.

    Args:
        aguja: Texto (se busca sin distinguir mayúsculas), expresión regular o función.
        texto: Donde se busca.
        bajo: `texto` ya en minúsculas, si quien llama lo tiene (un log grande y
            muchas agujas).
    """
    if isinstance(aguja, str):
        return aguja.lower() in (texto.lower() if bajo is None else bajo)
    if isinstance(aguja, re.Pattern):
        return aguja.search(texto) is not None
    return bool(aguja(texto))


def clasificar(texto: str) -> Causa | None:
    """Devuelve la causa del fallo que cuenta ese log, o `None` si no se reconoce.

    No reconoce los frenos de borrados: eso lo hace `frenos`, antes.

    Args:
        texto: El log de la pasada, o su final.
    """
    bajo = texto.lower()
    for agujas, causa in ENTRADAS:
        if any(casa(aguja, texto, bajo) for aguja in agujas):
            return causa
    return None


def agujas_de_consola() -> list[tuple[Aguja, str]]:
    """Devuelve el catálogo como `(aguja, explicación)`, con los frenos en su sitio.

    Es lo que la consola de `sync.py` recorre (`KNOWN_ERRORS`): una entrada por
    aguja, en el orden de `ENTRADAS`, y las de `frenos.ENTRADAS` tras las de los
    filtros. Las expresiones regulares van como función (su `search`).
    """
    def plana(entradas):
        return [(aguja.search if isinstance(aguja, re.Pattern) else aguja, causa.texto)
                for agujas, causa in entradas for aguja in agujas]

    return [*plana(ENTRADAS[:_TRAS_LOS_FRENOS]), *frenos.ENTRADAS,
            *plana(ENTRADAS[_TRAS_LOS_FRENOS:])]


_LINEA_DE_ERROR = re.compile(r"ERROR :|\bError:|Fatal error:|\bFailed to ")
"""Las líneas de un log que dicen un error: las que se enseñan de un fallo sin clasificar."""
_FECHA = re.compile(r"^\d{4}/\d\d/\d\d \d\d:\d\d:\d\d(?:\.\d+)? ")
"""La fecha y hora con que empieza cada línea de rclone."""
TOPE_LINEA = 200
"""Caracteres de la línea de error que se enseñan como mucho."""


def ultima_linea_de_error(texto: str) -> str | None:
    """Devuelve la última línea de error del log, sin la fecha y recortada.

    Es lo que se enseña, tal cual, de un fallo que el catálogo no reconoce.

    Returns:
        La línea (como mucho `TOPE_LINEA` caracteres, con «…» si se recortó), o
        `None` si el texto no tiene ninguna.
    """
    for linea in reversed(texto.splitlines()):
        if _LINEA_DE_ERROR.search(linea):
            linea = _FECHA.sub("", linea.strip())
            return linea if len(linea) <= TOPE_LINEA else linea[:TOPE_LINEA - 1] + "…"
    return None
