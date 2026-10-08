#!/usr/bin/env python3
"""La conexión con el remoto, como objeto y no como constantes.

Un `Profile` es lo que hace falta para hablar con el remoto **antes** de que
exista ningún dispositivo: cómo se llama el remote, qué opciones lo definen, la
clave privada si el backend usa una y dónde está el catálogo. Quien se baje el
proyecto tiene que poder cambiarlo (por parámetro, fichero o pantalla); no es
un secreto, son rutas y un usuario. De un perfil salen dos cosas distintas que
no hay que confundir:
- el `rclone.conf` EFÍMERO del instalador (`remote.EphemeralConf`), con la
  clave en un temporal que se borra al salir;
- el `rclone.conf` DEL DISPOSITIVO (`deploy.write_device_remote`), con la clave
  en `.prdrive/keys/` y rutas relativas.

Por eso `render_conf()` recibe las rutas de la clave: son lo único que cambia
entre los dos y lo que no se puede guardar dentro del perfil.

De dónde sale un perfil, en orden (`load()`):
- `install/secret.py`, que genera `build_installer.py` al compilar el `.exe`:
  el binario llave en mano que se comparte en privado.
- `keys/` + `prdrive-profile.toml` junto al instalador, al ejecutar el `.py`
  desde un checkout provisionado: el caso de desarrollo.
- Ninguno: `empty()`. No es un error sino el arranque normal de quien acaba de
  clonar el repo: el asistente abre su formulario de conexión en vez de morir
  explicando que falta una clave que nunca ha tenido.

El backend no se interpreta en ningún sitio: `options` es lo que vaya a ir bajo
`[nombre]` en el `rclone.conf`, sea sftp, webdav, s3 o lo que sea. El proyecto
solo sabe de `nombre:ruta`.
"""

from __future__ import annotations

import base64
import binascii
import re
import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Iterable, Mapping

from common import pairing
from common.catalog import DEFAULT_CATALOG_PATH, problema_de_ruta
from common.model import NOMBRE_REMOTE

from . import InstallError, bundle_dir

INJECT_MARKER = "__INJECT"
"""Marcador que deja `build_installer.py` donde falta la clave privada."""
PROFILE_FILE = "prdrive-profile.toml"
"""Fichero con el perfil junto al instalador."""
DEFAULT_KEY_NAME = "id_ed25519"
DEFAULT_REMOTE_NAME = "remote"

RUTAS_DERIVADAS = pairing.RUTAS_DERIVADAS
"""Opciones que NO se guardan en el perfil: `key_file` y `known_hosts_file`.

Son rutas del disco de quien ejecuta y valen una cosa en el temporal del
instalador y otra en el dispositivo; si viajaran dentro de `options`, un
`rclone.conf` importado apuntaría a la clave del equipo del que salió. La lista
es de `pairing`, que es quien lee el `rclone.conf`, y se toma de allí para que
no puedan separarse.
"""

NOMBRE_VALIDO = re.compile(r"[A-Za-z0-9_.-]+")
"""Patrón de los nombres de remote que se aceptan.

rclone acepta bastante más, pero el proyecto lo mete en
`RCLONE_CONFIG_<NOMBRE>_*` cuando hay `device_remote` y ahí no cabe cualquier
cosa. Se valida al entrar, no al fallar tres pasos después. Es la regla de los
nombres que se teclean en el asistente; la de los que ya existen es
`NOMBRE_RCLONE`.
"""

NOMBRE_RCLONE = NOMBRE_REMOTE
"""Regla de rclone para el nombre de un remote (`fullmatch`): `model.NOMBRE_REMOTE`.

Sin `,` `:` `=` ni comillas, sin `[` `]` ni saltos de línea, sin empezar por `-`
ni acabar en espacio. Es la que se exige para ESCRIBIR un `rclone.conf`
(`render_conf`): un remote que ya existe (en un `rclone.conf` importado o en el
`[defaults].remote` de un catálogo) puede llamarse `Mi NAS` o `nas@home`, y
renombrarlo apartaría la base de cada pareja bisync. Es la misma que aplica el
cargador del config, y no una copia, para que no puedan separarse.
"""

CLAVE_VALIDA = re.compile(r"[A-Za-z0-9_]+")
"""Patrón de los nombres de opción que se escriben en un `rclone.conf`."""

SALTO_DE_LINEA = re.compile(r"[\r\n\x0b\x0c\x1c-\x1e\x85\u2028\u2029]")
"""Caracteres que parten una línea al leer un `rclone.conf`.

Son los de `str.splitlines()`, que es como lo lee `parse_rclone_conf`. El
formato no tiene escape para ninguno: un valor que lo lleve escribiría una
opción (u otro remote) que nadie tecleó.
"""

OPCIONES_QUE_EJECUTAN = frozenset({"ssh", "bearer_token_command"})
"""Opciones de rclone cuyo valor es una orden que se ejecuta en este equipo.

- `ssh` (backend sftp): rclone lanza esa orden como su ssh externo.
- `bearer_token_command` (backend webdav): rclone la lanza para pedir el token.

El usuario puede teclearlas en el asistente, que es su equipo; el catálogo no
puede imponerlas, porque lo escribe cualquiera con acceso al remoto y lo leen
todos los dispositivos.
"""

_SECRETAS_EXACTAS = frozenset({"key", "pass", "password", "2fa"})
"""Nombres de opción que son un secreto tal cual (`es_secreta()`)."""

_SECRETAS_CONTIENEN = ("pass", "token", "secret", "credential", "_pem",
                       "sas_url", "account_key", "access_grant",
                       "connection_string", "cookie", "authorization",
                       "headers")
"""Trozos que delatan un secreto en cualquier parte del nombre (`es_secreta()`)."""

_CLAVE_DE_BACKEND = re.compile(r"_key(_|$)")
"""`..._key` como palabra suelta, al final o en medio (`es_secreta()`).

Son `api_key`, `sse_customer_key` o `sse_customer_key_base64`; `es_secreta()`
exceptúa los `..._key_id`.
"""


@dataclass(frozen=True)
class Profile:
    """Todo lo necesario para hablar con el remoto, sin nada del disco de nadie.

    Args:
        remote_name: Nombre del remote.
        options: Lo que irá bajo `[nombre]` en el `rclone.conf`.
        private_key: La clave privada, si el backend usa una.
        known_hosts: Contenido de `known_hosts`, o vacío.
        key_name: Nombre del fichero de la clave.
        catalog_path: Ruta del catálogo dentro del remote.
        origen: De dónde sale (incrustada, tecleada, importada…); lo enseña el
            paso de comprobaciones para que se vea si el instalador lleva la
            conexión dentro o la acaba de teclear el usuario.
    """
    remote_name: str = ""
    options: Mapping[str, str] = field(default_factory=dict)
    private_key: bytes | None = None
    known_hosts: str = ""
    key_name: str = DEFAULT_KEY_NAME
    catalog_path: str = DEFAULT_CATALOG_PATH
    origen: str = "sin configurar"

    @property
    def configured(self) -> bool:
        """Indica si hay al menos un remote con tipo.

        Lo mínimo para intentar conectar.
        """
        return bool(self.remote_name and self.options.get("type"))

    @property
    def needs_key(self) -> bool:
        """Indica si el backend se autentica con un fichero de clave.

        No se deduce del tipo sino de si hay clave: un sftp con contraseña en
        el conf importado es perfectamente válido y no necesita escribir nada.
        """
        return self.private_key is not None

    @property
    def endpoint_catalog(self) -> str:
        """Devuelve el endpoint del catálogo, `remote:ruta`."""
        return f"{self.remote_name}:{self.catalog_path}"

    @property
    def problema_catalogo(self) -> str | None:
        """Devuelve qué le pasa a la ruta del catálogo, o `None`.

        Es aparte de `configured` porque una ruta mala no deja de ser una
        conexión: `load()` no debe saltarse por eso un perfil incrustado, y el
        paso Conexión la enseña.
        """
        return problema_de_ruta(self.catalog_path)

    def describe(self) -> str:
        """Devuelve una línea para la pantalla: el backend y adónde apunta."""
        tipo = self.options.get("type", "?")
        destino = self.options.get("host") or self.options.get("url") or ""
        usuario = self.options.get("user", "")
        cola = f" {usuario}@{destino}" if usuario and destino else f" {destino}"
        return f"{self.remote_name} ({tipo}){cola}".rstrip()


def es_secreta(clave: str) -> bool:
    """Indica si una opción de rclone lleva un secreto (contraseña, token, clave…).

    Es un criterio por el nombre, no una lista de backends: el proyecto no
    interpreta ninguno (ni mira los valores: unas credenciales dentro de una
    `url` no se detectan). Peca de más a propósito, porque lo que marca se
    queda fuera del catálogo. Es secreto un nombre que:
    - sea exactamente `key`, `pass`, `password` o `2fa`;
    - contenga `pass`, `token`, `secret`, `credential`, `_pem`, `sas_url`,
      `account_key`, `access_grant` (Storj), `connection_string` (Azure),
      `cookie` (iCloud), `authorization` (SugarSync) o `headers` (http y
      webdav, que pueden llevar `Authorization`);
    - acabe en `_key` o lleve `_key_` en medio (`api_key`, `sse_customer_key`,
      `sse_customer_key_base64`), salvo si acaba en `_key_id`: eso es un
      identificador y no el secreto (`access_key_id`, `sse_kms_key_id`).
    """
    nombre = clave.strip().lower()
    return (nombre in _SECRETAS_EXACTAS
            or any(trozo in nombre for trozo in _SECRETAS_CONTIENEN)
            or (bool(_CLAVE_DE_BACKEND.search(nombre))
                and not nombre.endswith("_key_id")))


def _linea(clave: str, valor: object) -> str:
    """Devuelve la línea `clave = valor` del `rclone.conf`.

    Raises:
        InstallError: Si el nombre de la opción no vale o el valor lleva un
            salto de línea.
    """
    if not CLAVE_VALIDA.fullmatch(clave):
        raise InstallError(
            f"La opción {clave!r} no vale en un rclone.conf: solo letras, "
            f"números y guión bajo.")
    if SALTO_DE_LINEA.search(str(valor)):
        raise InstallError(
            f"El valor de '{clave}' lleva un salto de línea y un rclone.conf no "
            f"tiene cómo escribirlo.")
    return f"{clave} = {valor}"


def render_conf(profile: Profile, key_file: Path | str | None = None,
                known_file: Path | str | None = None) -> str:
    """Devuelve el texto del `rclone.conf` de este perfil.

    Las dos rutas van por parámetro y no dentro del perfil porque son lo único
    que cambia entre el conf efímero del instalador (temporal, absoluto) y el
    del dispositivo (`keys/…`, relativo). Lo relativo es lo que hace portable
    al dispositivo: rclone las resuelve contra su cwd y todo el proyecto
    ejecuta rclone con `cwd = model.APP_DIR`.

    Args:
        key_file: Ruta de la clave en este conf, o `None` si no hay.
        known_file: Ruta de los known_hosts en este conf, o `None`.

    Raises:
        InstallError: Si el perfil no dice cómo se llama el remote, el nombre no
            vale (`NOMBRE_RCLONE`), el de una opción no vale o un valor lleva
            un salto de línea. Un `rclone.conf` no tiene escape para ellos y
            las opciones pueden venir del catálogo.
    """
    if not profile.remote_name:
        raise InstallError("El perfil no dice cómo se llama el remote.")
    if not NOMBRE_RCLONE.fullmatch(profile.remote_name):
        raise InstallError(
            f"El nombre de remote {profile.remote_name!r} no vale en un "
            f"rclone.conf: no admite , : = [ ] ni comillas ni saltos de línea, "
            f"ni empezar por «-» ni acabar en espacio.")
    lineas = [f"[{profile.remote_name}]"]
    for clave, valor in profile.options.items():
        if clave in RUTAS_DERIVADAS:
            continue                    # se ponen abajo, con la ruta de ahora
        lineas.append(_linea(clave, valor))
    if key_file is not None:
        lineas.append(_linea("key_file", key_file))
    # Sin known_hosts se acepta la clave de host a la primera (TOFU). Es peor,
    # pero escribir la opción apuntando a un fichero vacío lo es más: rclone
    # falla en vez de avisar.
    if known_file is not None and profile.known_hosts.strip():
        lineas.append(_linea("known_hosts_file", known_file))
    return "\n".join(lineas) + "\n"


parse_rclone_conf = pairing.parse_rclone_conf
"""Lector de `rclone.conf` de `common/pairing.py`, reexportado aquí.

Allí porque el dispositivo también tiene que leer su propio `rclone.conf` (para
enseñar el QR de emparejamiento) y `install/` no viaja a él: una sola
implementación, no dos.
"""


def remotes_in(path: Path | str) -> list[str]:
    """Devuelve los remotes que define un `rclone.conf`, para poder ofrecerlos.

    Vive aquí y no en el asistente por la regla de todo `ui/tk_*`: ahí solo se
    dibuja, y elegir de una lista exige antes tener la lista.

    Raises:
        InstallError: Si no se puede leer el fichero.
    """
    ruta = Path(path).expanduser()
    try:
        texto = ruta.read_text(encoding="utf-8")
    except OSError as e:
        raise InstallError(f"No puedo leer {ruta}: {e}") from e
    return sorted(parse_rclone_conf(texto))


def parse_options(texto: str) -> dict[str, str]:
    """Convierte el cuadro de texto del formulario en las opciones del remote.

    Una línea por opción, `clave = valor`, que es exactamente lo que irá al
    `rclone.conf`. Un formulario con un campo por backend sería mentira: rclone
    tiene decenas y cada uno con sus opciones, y el proyecto no interpreta
    ninguna. Es la misma decisión que en el editor de flags: se enseña la
    sintaxis de destino en vez de inventar una intermedia.

    Raises:
        InstallError: Si una línea no tiene `=` ni nombre, o pone una de
            `RUTAS_DERIVADAS`.
    """
    opciones: dict[str, str] = {}
    for numero, linea in enumerate(texto.splitlines(), 1):
        linea = linea.strip()
        if not linea or linea.startswith(("#", ";")):
            continue
        if "=" not in linea:
            raise InstallError(
                f"Línea {numero} de las opciones: falta el '=' en «{linea}».")
        clave, _, valor = linea.partition("=")
        clave, valor = clave.strip(), valor.strip()
        if not clave:
            raise InstallError(f"Línea {numero} de las opciones: falta el nombre.")
        if clave in RUTAS_DERIVADAS:
            raise InstallError(
                f"'{clave}' no se pone aquí: lo escribe el instalador con la ruta "
                f"que tenga la clave en cada sitio.")
        opciones[clave] = valor
    return opciones


def dump_options(profile: Profile) -> str:
    """Devuelve las opciones tal como se enseñan en el formulario.

    Es lo contrario de `parse_options`.
    """
    return "\n".join(f"{k} = {v}" for k, v in profile.options.items())


PLANTILLAS: dict[str, str] = {
    "sftp": ("host = \nport = 22\nuser = \n"
             "disable_hashcheck = true\nshell_type = none"),
    "webdav": "url = \nvendor = other\nuser = ",
    "s3": ("provider = \naccess_key_id = \n"
           "secret_access_key = \nregion = "),
}
"""Puntos de partida para el formulario, por tipo de backend.

No es una lista cerrada: el campo «tipo» acepta cualquier backend de rclone y
las opciones son texto libre.
"""

OBLIGATORIAS: dict[str, tuple[tuple[str, str], ...]] = {
    "sftp": (("host", "saber a qué servidor conectarse"),),
    "webdav": (("url", "saber la dirección del servidor"),),
}
"""Por tipo de backend, lo que NO puede no tener, con para qué sirve.

Criterio conservador: solo lo que rclone marca `Required: true` en la
definición del backend y no admite otra salida, porque esto BLOQUEA («Usar esta
conexión» no hace un perfil sin ello). Lo que rclone rellena por su cuenta (el
puerto, el usuario) no está aquí: eso, si acaso, es un aviso (`avisos()`).
- sftp → `host` (`backend/sftp/sftp.go`). Sin él rclone ni siquiera falla:
  marca `f.opt.Host+":"+f.opt.Port`, o sea `:22`, y Go entiende un host vacío
  como este mismo equipo. La excepción es `ssh`, el ssh externo: con él rclone
  ignora host, user y port del conf (`NewFsWithConnection`) y los espera dentro
  de esa orden.
- webdav → `url` (`backend/webdav/webdav.go`).
- s3 → nada. Sus `Required` son el `endpoint` de proveedores concretos, que la
  plantilla no pone, y sin claves rclone entra como anónimo
  (`AnonymousCredentials` en `backend/s3/s3.go`): mal para escribir el
  catálogo, pero eso lo dice el paso de comprobaciones, no una suposición.

Un tipo que no esté aquí no se valida: rclone tiene decenas de backends y el
proyecto no interpreta ninguno. Tampoco se comprueba que el tipo exista (haría
falta rclone, que se consigue en el paso siguiente): allí rclone lo dice solo.
"""


def faltan(options: Mapping[str, str]) -> list[tuple[str, str]]:
    """Devuelve las opciones obligatorias de ese backend que no están o están vacías.

    Vacías cuentan como ausentes porque es lo que deja la plantilla (`host = `)
    y lo que trae un `rclone.conf` a medio escribir.

    Returns:
        Pares `(clave, para qué sirve)`.
    """
    tipo = str(options.get("type", "")).strip()
    if tipo == "sftp" and str(options.get("ssh", "")).strip():
        return []
    return [(clave, para) for clave, para in OBLIGATORIAS.get(tipo, ())
            if not str(options.get(clave, "")).strip()]


def _falta(options: Mapping[str, str], donde: str) -> str:
    """Devuelve la frase del error de `faltan()`: qué falta, dónde y para qué."""
    falta = faltan(options)
    claves = " y ".join(f"«{clave} = …»" for clave, _ in falta)
    para = " y ".join(para for _, para in falta)
    verbo = "Falta" if len(falta) == 1 else "Faltan"
    return (f"{verbo} {claves} {donde}: un remote {options.get('type')} necesita "
            f"{para}.")


def avisos(perfil: Profile) -> list[str]:
    """Devuelve lo que no impide seguir pero conviene saber antes de probar la conexión.

    No bloquea porque no es seguro que falle: puede funcionar en el equipo
    donde se instala y dejar de hacerlo en otro, que es justo lo que el paso de
    comprobaciones no puede ver.
    """
    notas: list[str] = []
    opciones = perfil.options
    # Sin `user`, rclone usa `currentUser` (`env.CurrentUser()` en
    # `backend/sftp/sftp.go`): el de la sesión del equipo donde se ejecuta, que
    # en Windows además viene como `EQUIPO\usuario`. El dispositivo viaja, así
    # que entra o no según dónde se enchufe. Con `ssh` el usuario va en esa
    # orden.
    if (opciones.get("type") == "sftp"
            and not str(opciones.get("ssh", "")).strip()
            and not str(opciones.get("user", "")).strip()):
        notas.append(
            "Sin «user = …», rclone entrará con el nombre de usuario del equipo "
            "en que se ejecute. El dispositivo va de un equipo a otro: donde ese "
            "nombre no sea el del servidor, no le dejará entrar.")
    return notas


def _leer_clave(options: Mapping[str, str], base: Path) -> tuple[bytes | None, str, str]:
    """Devuelve la clave y los known_hosts a los que apunta un `rclone.conf` importado.

    Se leen ahora y se meten dentro del perfil porque el dispositivo llevará su
    propia copia: dejar la ruta original significaría que solo funciona en el
    equipo del que salió.

    Args:
        options: Opciones del remote importado.
        base: Carpeta contra la que se resuelven las rutas relativas.

    Returns:
        `(clave, known_hosts, nombre de la clave)`; sin `key_file`, `(None, '',
        nombre por defecto)`.

    Raises:
        InstallError: Si no se puede leer la clave.
    """
    key_file = options.get("key_file", "")
    if not key_file:
        return None, "", DEFAULT_KEY_NAME
    ruta = Path(key_file).expanduser()
    if not ruta.is_absolute():
        ruta = base / ruta
    try:
        clave = ruta.read_bytes()
    except OSError as e:
        raise InstallError(
            f"El rclone.conf apunta a la clave {ruta}, pero no puedo leerla: {e}") from e

    conocidos = ""
    known = options.get("known_hosts_file", "")
    if known:
        kruta = Path(known).expanduser()
        if not kruta.is_absolute():
            kruta = base / kruta
        try:
            conocidos = kruta.read_text(encoding="utf-8")
        except OSError:
            conocidos = ""      # sin known_hosts se sigue: es TOFU, no un fallo
    return clave, conocidos, ruta.name


def from_rclone_conf(path: Path | str, remote_name: str,
                     catalog_path: str = DEFAULT_CATALOG_PATH) -> Profile:
    """Importa un remote del `rclone.conf` que ya tenga el usuario.

    Raises:
        InstallError: Si no se puede leer, no define ese remote, le falta el
            tipo o una opción obligatoria, o no se puede leer su clave.
    """
    ruta = Path(path).expanduser()
    try:
        texto = ruta.read_text(encoding="utf-8")
    except OSError as e:
        raise InstallError(f"No puedo leer {ruta}: {e}") from e

    remotes = parse_rclone_conf(texto)
    if not remotes:
        raise InstallError(f"{ruta} no define ningún remote.")
    if remote_name not in remotes:
        raise InstallError(
            f"{ruta} no tiene ningún remote llamado '{remote_name}'. "
            f"Tiene: {', '.join(sorted(remotes))}.")

    options = dict(remotes[remote_name])
    # Se le exige lo mismo que al formulario: sin esto un remote sin `type`
    # salía de aquí como perfil sin estar `configured`, la pantalla lo daba por
    # bueno y «Siguiente» se quedaba gris sin decir por qué.
    donde = f"en el remote '{remote_name}' de {ruta}"
    if not options.get("type", "").strip():
        raise InstallError(
            f"Falta «type = …» {donde}: sin el tipo (sftp, webdav, s3…) rclone "
            f"no sabe con qué backend hablar.")
    if faltan(options):
        raise InstallError(_falta(options, donde))
    clave, conocidos, key_name = _leer_clave(options, ruta.parent)
    for derivada in RUTAS_DERIVADAS:
        options.pop(derivada, None)
    return Profile(
        remote_name=remote_name, options=options, private_key=clave,
        known_hosts=conocidos, key_name=key_name,
        catalog_path=_ruta_catalogo(catalog_path), origen=f"importada de {ruta}")


def from_form(remote_name: str, options: Mapping[str, str],
              key_path: Path | str | None = None,
              known_path: Path | str | None = None,
              catalog_path: str = DEFAULT_CATALOG_PATH) -> Profile:
    """Convierte lo tecleado en el asistente en un perfil.

    Validado antes de intentar nada.

    Raises:
        InstallError: Si falta o no vale el nombre o el tipo, falta una opción
            obligatoria o no se pueden leer los ficheros.
    """
    remote_name = (remote_name or "").strip()
    if not remote_name:
        raise InstallError("Hay que darle un nombre al remote.")
    if not NOMBRE_VALIDO.fullmatch(remote_name):
        raise InstallError(
            f"'{remote_name}' no vale como nombre de remote: solo letras, "
            f"números, punto, guión y guión bajo.")
    limpio = {k: str(v).strip() for k, v in options.items()
              if str(v).strip() and k not in RUTAS_DERIVADAS}
    if not limpio.get("type"):
        raise InstallError("Falta el tipo de remote (sftp, webdav, s3…).")
    if faltan(limpio):
        raise InstallError(_falta(limpio, "en las opciones"))

    clave = conocidos = None
    key_name = DEFAULT_KEY_NAME
    if key_path:
        ruta = Path(key_path).expanduser()
        try:
            clave = ruta.read_bytes()
        except OSError as e:
            raise InstallError(f"No puedo leer la clave {ruta}: {e}") from e
        key_name = ruta.name
    if known_path:
        kruta = Path(known_path).expanduser()
        try:
            conocidos = kruta.read_text(encoding="utf-8")
        except OSError as e:
            raise InstallError(f"No puedo leer {kruta}: {e}") from e

    return Profile(
        remote_name=remote_name, options=limpio, private_key=clave,
        known_hosts=conocidos or "", key_name=key_name,
        catalog_path=_ruta_catalogo(catalog_path),
        origen="configurada en el asistente")


def _ruta_catalogo(ruta: str | None) -> str:
    """Devuelve la ruta del catálogo tecleada: limpia, y la de fábrica si está vacía.

    Raises:
        InstallError: Si nombra una carpeta en vez de un fichero `.toml`; se
            avisa aquí y no en el paso de comprobaciones, con un error de TOML.
    """
    limpia = (ruta or "").strip() or DEFAULT_CATALOG_PATH
    problema = problema_de_ruta(limpia)
    if problema:
        raise InstallError(problema)
    return limpia


def _texto_rclone(valor: object) -> str:
    """Devuelve un valor del catálogo tal como lo escribe rclone en su conf.

    TOML trae booleanos de verdad y `str(True)` da «True», no «true»: el mismo
    valor parecería otra conexión y el conf llevaría una mayúscula que rclone
    no lee como booleano.
    """
    if isinstance(valor, bool):
        return "true" if valor else "false"
    return str(valor)


def _enumerar(claves: Iterable[str]) -> str:
    """Devuelve las claves entre comillas inversas, «`a`, `b` y `c`», ordenadas."""
    nombres = [f"`{k}`" for k in sorted(claves)]
    if len(nombres) == 1:
        return nombres[0]
    return ", ".join(nombres[:-1]) + " y " + nombres[-1]


def _opciones_del_catalogo(
        propias: Mapping[str, str],
        tabla: Mapping[str, object]) -> tuple[dict[str, str] | None, list[str]]:
    """Devuelve las opciones del backend que se heredan del `[remote]` del catálogo.

    El catálogo lo escribe cualquiera con acceso al remoto y lo leen todos los
    dispositivos, así que de él no se hereda lo que ejecuta algo en este equipo
    (`OPCIONES_QUE_EJECUTAN`) ni lo secreto (`es_secreta`): ni lo trae el
    catálogo ni lo guarda `to_catalog_remote()`. Y como el catálogo ya no
    guarda las contraseñas, un perfil que lleva alguna (o una orden) se queda
    como está: es la conexión que el asistente acaba de comprobar, y sus
    secretos no se mezclan con el destino que describa el catálogo, que nadie
    ha comprobado.

    Args:
        propias: Las opciones del perfil con el que se entró.
        tabla: El `[remote]` del catálogo.

    Returns:
        Las opciones que valen, o `None` si no hay nada que adoptar: el
        `[remote]` no trae `type`; el perfil lleva algo secreto o una orden; o
        sin lo que no se hereda le falta algo que rclone exige (`faltan()`).
        En todos esos casos la conexión se deja como está. Y las notas de lo
        que no se ha heredado o de por qué no se usa.
    """
    ejecutan: dict[str, str] = {}
    secretas: list[str] = []
    heredadas: dict[str, str] = {}
    for clave, valor in tabla.items():
        clave = str(clave)
        if clave == "name" or clave in RUTAS_DERIVADAS:
            continue
        if clave in OPCIONES_QUE_EJECUTAN:
            ejecutan[clave] = _texto_rclone(valor)
        elif es_secreta(clave):
            secretas.append(clave)
        else:
            heredadas[clave] = _texto_rclone(valor)
    if not heredadas.get("type"):
        return None, []         # tabla incompleta: no se pisa lo que ya funciona

    notas: list[str] = []
    if ejecutan:
        uno = len(ejecutan) == 1
        notas.append(
            f"El catálogo traía {_enumerar(ejecutan)}: "
            + ("no se hereda, porque es una orden" if uno
               else "no se heredan, porque son órdenes")
            + " de este equipo.")
    if secretas:
        uno = len(secretas) == 1
        notas.append(
            f"El catálogo traía {_enumerar(secretas)}: "
            + ("no se hereda" if uno else "no se heredan")
            + ", porque el catálogo no guarda secretos. "
            + ("Se puede quitar" if uno else "Se pueden quitar")
            + " de su [remote].")

    propias_sensibles = {k for k in propias
                         if k in OPCIONES_QUE_EJECUTAN or es_secreta(k)}
    if propias_sensibles:
        del_perfil = {k: str(v) for k, v in propias.items()
                      if k not in propias_sensibles}
        if heredadas != del_perfil:
            notas.append(
                "El [remote] del catálogo describe otra conexión: este "
                "dispositivo se queda con la que se acaba de comprobar, porque "
                "sus contraseñas, claves y órdenes no se dan a una conexión que "
                "no se ha comprobado.")
        return None, notas

    falta = faltan(heredadas)
    if falta:
        # Solo se atribuye a lo quitado si con ello el [remote] sí valdría.
        sin = ""
        if ejecutan and not faltan({**heredadas, **ejecutan}):
            sin = (f"sin {_enumerar(ejecutan)}, "
                   + ("que no se hereda" if len(ejecutan) == 1
                      else "que no se heredan")
                   + ", ")
        notas.append(
            "No se usa el [remote] del catálogo: " + sin + "le falta "
            + " y ".join(f"«{clave} = …»" for clave, _ in falta) + ".")
        return None, notas
    return heredadas, notas


def with_catalog_remote(profile: Profile, tabla: Mapping[str, object]) -> Profile:
    """Devuelve el perfil con el `[remote]` del catálogo aplicado.

    Es lo que hace que la conexión se teclee UNA vez: el primer dispositivo la
    escribe en el catálogo y todos los demás la heredan. Solo toca las opciones
    del backend (la clave nunca viaja por ahí) y respeta el nombre de remote de
    la tabla, porque es el que usarán los `remote_path` de las parejas. Adopta
    lo mismo que `align_with_catalog()` (ver `_opciones_del_catalogo()`: un
    perfil con secretos u órdenes propios se queda como está), pero sin notas.
    """
    if not tabla:
        return profile
    opciones, _ = _opciones_del_catalogo(profile.options, tabla)
    if opciones is None:
        return profile
    nombre = str(tabla.get("name", "") or profile.remote_name).strip()
    return replace(profile, remote_name=nombre or profile.remote_name,
                   options=opciones)


def align_with_catalog(perfil: Profile,
                       catalog_raw: Mapping[str, object]) -> tuple[Profile, list[str]]:
    """Devuelve el perfil que se escribe al dispositivo, según lo que diga el catálogo.

    Aquí se cierra el círculo: la conexión se teclea UNA vez y el catálogo la
    reparte. Pero hay una regla que manda sobre la comodidad: el nombre del
    remote lo decide el catálogo, no el usuario. Los `remote_path` de todas las
    parejas se resuelven contra `[defaults].remote`, y si el `rclone.conf` del
    dispositivo llamara al remote de otra forma cada sincronización fallaría
    con un «unknown remote» que no se parece a la causa. Las opciones del
    backend sí son del usuario, salvo que el catálogo traiga un `[remote]`
    completo (el que dejó el primer dispositivo), que entonces es la definición
    buena, menos lo que ejecuta algo o es secreto, que no se hereda. Y si la
    conexión del usuario lleva algo secreto o una orden de las suyas, se queda
    tal cual, sin tocar: es la que se acaba de comprobar, y sus contraseñas no
    se mezclan con el destino de un `[remote]` que nadie ha comprobado
    (`_opciones_del_catalogo()`). La clave privada NUNCA sale de aquí ni entra
    por aquí: viaja con el dispositivo.

    Returns:
        El perfil ajustado y las notas de lo que se ha cambiado o dejado de
        heredar, para poder decirlo.
    """
    notas: list[str] = []
    tabla = dict(catalog_raw.get("remote") or {})          # type: ignore[union-attr]
    defaults = dict(catalog_raw.get("defaults") or {})     # type: ignore[union-attr]

    nombre = str(tabla.get("name") or defaults.get("remote") or "").strip()
    ajustado = perfil
    if nombre and nombre != perfil.remote_name:
        ajustado = replace(ajustado, remote_name=nombre)
        notas.append(
            f"En el dispositivo el remote se llamará '{nombre}' y no "
            f"'{perfil.remote_name}': es el nombre que usan los remote_path del "
            f"catálogo.")

    opciones, de_opciones = _opciones_del_catalogo(perfil.options, tabla)
    if opciones is not None:
        if dict(ajustado.options) != opciones:
            notas.append("Las opciones del backend salen del [remote] del "
                         "catálogo, que es el que comparten todos los dispositivos.")
        ajustado = replace(ajustado, options=opciones)
    notas.extend(de_opciones)

    return ajustado, notas


def with_catalog_path(perfil: Profile, ruta: str) -> Profile:
    """Devuelve el mismo perfil con otra ruta de catálogo.

    La ruta se teclea en su propia caja, aparte de la conexión, y por eso puede
    cambiar sin reconstruir el perfil entero. Vacía vuelve a la de por defecto,
    como en `from_form`. A diferencia de `from_form` no rechaza una ruta mala:
    se aplica a cada tecla y a medio escribir ninguna termina en `.toml`; lo
    que impide seguir con ella es la condición del paso
    (`Profile.problema_catalogo`).
    """
    return replace(perfil,
                   catalog_path=(ruta or "").strip() or DEFAULT_CATALOG_PATH)


def to_catalog_remote(profile: Profile) -> dict[str, str]:
    """Devuelve el `[remote]` que se guarda en el catálogo, sin nada secreto dentro.

    Quedan fuera las rutas de la clave, lo que `es_secreta()` marca y las
    `OPCIONES_QUE_EJECUTAN`: cada dispositivo lleva las suyas, las de la
    conexión con la que se instaló (`align_with_catalog()`).
    """
    tabla = {"name": profile.remote_name}
    tabla.update({k: v for k, v in profile.options.items()
                  if k not in RUTAS_DERIVADAS and k not in OPCIONES_QUE_EJECUTAN
                  and not es_secreta(k)})
    return tabla


def dumps(profile: Profile) -> str:
    """Devuelve el perfil como TOML, SIN la clave privada.

    La clave va aparte (en `keys/` o en base64 dentro de `secret.py`) para que
    este texto se pueda enseñar, guardar y versionar sin pensárselo.
    `secret.py` y `prdrive-profile.toml` comparten este formato.
    """
    lineas = [
        f'remote_name = "{profile.remote_name}"',
        f'key_name = "{profile.key_name}"',
        f'catalog_path = "{profile.catalog_path}"',
        "",
        "[options]",
    ]
    lineas += [f'{k} = "{v}"' for k, v in profile.options.items()]
    return "\n".join(lineas) + "\n"


def loads(texto: str, *, private_key: bytes | None = None,
          known_hosts: str = "", origen: str = "") -> Profile:
    """Lee lo que escribió `dumps()` y le engancha la clave, que viaja aparte.

    Raises:
        InstallError: Si no es TOML válido.
    """
    try:
        raw = tomllib.loads(texto)
    except tomllib.TOMLDecodeError as e:
        raise InstallError(f"El perfil de conexión no es TOML válido: {e}") from e
    options = {str(k): str(v) for k, v in (raw.get("options") or {}).items()}
    return Profile(
        remote_name=str(raw.get("remote_name", "") or ""),
        options=options,
        private_key=private_key,
        known_hosts=known_hosts,
        key_name=str(raw.get("key_name", DEFAULT_KEY_NAME) or DEFAULT_KEY_NAME),
        catalog_path=str(raw.get("catalog_path", DEFAULT_CATALOG_PATH)
                         or DEFAULT_CATALOG_PATH),
        origen=origen or "leída de un perfil")


def from_secret() -> Profile | None:
    """Devuelve lo que inyectó `build_installer.py`, si se compiló con perfil, o `None`.

    Raises:
        InstallError: Si quedó el marcador de clave sin sustituir o la clave no
            es base64.
    """
    try:
        from . import secret            # type: ignore[attr-defined]
    except ImportError:
        return None

    perfil_toml = getattr(secret, "PROFILE_TOML", "")
    if not perfil_toml.strip():
        return None

    b64 = getattr(secret, "PRIVATE_KEY_B64", "")
    clave: bytes | None = None
    if b64:
        if b64.startswith(INJECT_MARKER):
            raise InstallError(
                "Este instalador se compiló sin clave privada (quedó el marcador "
                f"{INJECT_MARKER}). Vuelve a compilarlo con build_installer.py "
                "desde un checkout que tenga keys/.")
        try:
            clave = base64.b64decode(b64, validate=True)
        except (binascii.Error, ValueError) as e:
            raise InstallError(f"La clave inyectada no es base64 válido: {e}") from e

    return loads(perfil_toml, private_key=clave,
                 known_hosts=getattr(secret, "KNOWN_HOSTS", ""),
                 origen="incrustada en el instalador")


def from_bundle() -> Profile | None:
    """Devuelve `prdrive-profile.toml` y `keys/` junto al instalador, o `None`.

    `bundle_dir()` se llama aquí y no al importar el módulo porque los tests lo
    sustituyen para apuntar a un directorio de mentira.
    """
    base = bundle_dir()
    fichero = base / PROFILE_FILE
    try:
        if not fichero.is_file():
            return None
        texto = fichero.read_text(encoding="utf-8")
    except OSError:
        return None

    provisional = loads(texto, origen=f"leída de {fichero}")
    keys = base / "keys"
    clave: bytes | None = None
    conocidos = ""
    try:
        key_file = keys / provisional.key_name
        if key_file.is_file():
            clave = key_file.read_bytes()
        known_file = keys / "known_hosts"
        if known_file.is_file():
            conocidos = known_file.read_text(encoding="utf-8")
    except OSError:
        pass        # el perfil vale igual; ya avisará el intento de conexión

    return replace(provisional, private_key=clave, known_hosts=conocidos)


def empty() -> Profile:
    """Devuelve el punto de partida de quien acaba de clonar el repo."""
    return Profile(remote_name=DEFAULT_REMOTE_NAME, options={},
                   origen="sin configurar")


def load() -> Profile:
    """Devuelve el perfil con el que arranca el asistente; NUNCA lanza por no encontrar.

    Que no haya perfil no es un error: es el caso normal la primera vez. Lo que
    sí lanza es un perfil corrupto (un `secret.py` a medio compilar, un TOML
    inválido), porque callarse significaría intentar conectar con basura y
    enseñar el error de rclone en vez del de verdad.
    """
    for fuente in (from_secret, from_bundle):
        perfil = fuente()
        if perfil is not None and perfil.configured:
            return perfil
    return empty()
