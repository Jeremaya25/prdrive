#!/usr/bin/env python3
"""
profile.py — La conexión con el remoto, como objeto y no como constantes.

Antes esto eran ocho constantes de módulo con el NAS de una persona dentro. El
problema no era que fueran secretas —no lo son: son rutas y un usuario— sino que
no había ninguna forma de moverlas: ni parámetro, ni fichero, ni pantalla. Quien
se bajara el proyecto no podía usarlo.

Un `Profile` es lo que hace falta para hablar con el remoto **antes** de que
exista ningún dispositivo: cómo se llama el remote, qué opciones lo definen, la
clave privada si el backend usa una, y dónde está el catálogo. De ahí salen dos
cosas distintas y no hay que confundirlas:

  * el `rclone.conf` **efímero** del instalador (`remote.EphemeralConf`), con la
    clave en un temporal que se borra al salir;
  * el `rclone.conf` **del dispositivo** (`deploy.write_device_remote`), con la
    clave en `.prdrive/keys/` y rutas relativas.

Por eso `render_conf()` recibe las rutas de la clave: son lo único que cambia
entre los dos, y son justo lo que no se puede guardar dentro del perfil.

De dónde sale un perfil, en orden (`load()`):

    1. `install/secret.py`, que genera `build_installer.py` al compilar el .exe.
       Es el caso del binario llave en mano que se comparte en privado.
    2. `keys/` + `prdrive-profile.toml` junto al instalador, cuando se ejecuta el
       .py desde un checkout provisionado. Es el caso de desarrollo.
    3. Ninguno: `empty()`. **Esto no es un error**, es el arranque normal de
       quien acaba de clonar el repo, y es la diferencia con lo que había antes:
       el asistente abre su formulario de conexión en vez de morir explicando que
       falta una clave que nunca ha tenido.

El backend no se interpreta en ningún sitio: `options` es lo que vaya a ir bajo
`[nombre]` en el rclone.conf, sea sftp, webdav, s3 o lo que sea. El proyecto solo
sabe de `nombre:ruta`.
"""

from __future__ import annotations

import base64
import binascii
import re
import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Mapping

from common.catalog import DEFAULT_CATALOG_PATH

from . import InstallError, bundle_dir

INJECT_MARKER = "__INJECT"
PROFILE_FILE = "prdrive-profile.toml"
DEFAULT_KEY_NAME = "id_ed25519"
DEFAULT_REMOTE_NAME = "remote"
DEFAULT_RECOVERY_PATH = "/prdrive/_recovery"

# Las dos opciones que NO se guardan en el perfil: son rutas del disco de quien
# ejecuta, y valen una cosa en el temporal del instalador y otra en el
# dispositivo. Si viajaran dentro de `options`, un rclone.conf importado
# apuntaría a la clave del equipo del que salió.
RUTAS_DERIVADAS = ("key_file", "known_hosts_file")

# rclone acepta como nombre de remote bastante más que esto, pero el proyecto lo
# mete en `RCLONE_CONFIG_<NOMBRE>_*` cuando hay `device_remote`, y ahí no cabe
# cualquier cosa. Se valida al entrar, no al fallar tres pasos después.
NOMBRE_VALIDO = re.compile(r"[A-Za-z0-9_.-]+")


@dataclass(frozen=True)
class Profile:
    """Todo lo necesario para hablar con el remoto, sin nada del disco de nadie.

    `origen` no es adorno: es lo que enseña el paso de comprobaciones para que se
    vea si el instalador lleva la conexión dentro o la acaba de teclear el
    usuario."""
    remote_name: str = ""
    options: Mapping[str, str] = field(default_factory=dict)
    private_key: bytes | None = None
    known_hosts: str = ""
    key_name: str = DEFAULT_KEY_NAME
    catalog_path: str = DEFAULT_CATALOG_PATH
    recovery_path: str = DEFAULT_RECOVERY_PATH
    origen: str = "sin configurar"

    @property
    def configured(self) -> bool:
        """¿Hay al menos un remote con tipo? Es lo mínimo para intentar conectar."""
        return bool(self.remote_name and self.options.get("type"))

    @property
    def needs_key(self) -> bool:
        """¿El backend se autentica con un fichero de clave?

        No se deduce del tipo sino de si hay clave: un sftp con contraseña en el
        conf importado es perfectamente válido y no necesita escribir nada."""
        return self.private_key is not None

    @property
    def endpoint_catalog(self) -> str:
        return f"{self.remote_name}:{self.catalog_path}"

    def describe(self) -> str:
        """Una línea para la pantalla: el backend y adónde apunta."""
        tipo = self.options.get("type", "?")
        destino = self.options.get("host") or self.options.get("url") or ""
        usuario = self.options.get("user", "")
        cola = f" {usuario}@{destino}" if usuario and destino else f" {destino}"
        return f"{self.remote_name} ({tipo}){cola}".rstrip()


# ---------------------------------------------------------------------------
# De perfil a rclone.conf
# ---------------------------------------------------------------------------

def render_conf(profile: Profile, key_file: Path | str | None = None,
                known_file: Path | str | None = None) -> str:
    """El texto del rclone.conf de este perfil.

    Las dos rutas van por parámetro y no dentro del perfil porque son lo único
    que cambia entre el conf efímero del instalador (temporal, absoluto) y el del
    dispositivo (`keys/…`, relativo). Relativo es lo que hace portable el
    dispositivo: rclone las resuelve contra su cwd, y todo el proyecto ejecuta
    rclone con `cwd = model.APP_DIR`."""
    if not profile.remote_name:
        raise InstallError("El perfil no dice cómo se llama el remote.")
    lineas = [f"[{profile.remote_name}]"]
    for clave, valor in profile.options.items():
        if clave in RUTAS_DERIVADAS:
            continue                    # se ponen abajo, con la ruta de ahora
        lineas.append(f"{clave} = {valor}")
    if key_file is not None:
        lineas.append(f"key_file = {key_file}")
    # Sin known_hosts se acepta la clave de host a la primera (TOFU). Es peor,
    # pero escribir la opción apuntando a un fichero vacío es peor todavía:
    # rclone falla en vez de avisar.
    if known_file is not None and profile.known_hosts.strip():
        lineas.append(f"known_hosts_file = {known_file}")
    return "\n".join(lineas) + "\n"


# ---------------------------------------------------------------------------
# Leer un rclone.conf de fuera
# ---------------------------------------------------------------------------

def parse_rclone_conf(text: str) -> dict[str, dict[str, str]]:
    """{nombre: {opción: valor}} de un rclone.conf ajeno.

    A mano y no con `configparser` porque rclone escribe algún valor con `%`
    dentro (los `%` de las plantillas de nombre) y `configparser` los interpreta
    como interpolación y revienta. El formato que hace falta entender es una
    cabecera entre corchetes y `clave = valor`; nada más."""
    remotes: dict[str, dict[str, str]] = {}
    actual: dict[str, str] | None = None
    for linea in text.splitlines():
        linea = linea.strip()
        if not linea or linea.startswith(("#", ";")):
            continue
        if linea.startswith("[") and linea.endswith("]"):
            actual = {}
            remotes[linea[1:-1].strip()] = actual
            continue
        if actual is None or "=" not in linea:
            continue
        clave, _, valor = linea.partition("=")
        actual[clave.strip()] = valor.strip()
    return remotes


def remotes_in(path: Path | str) -> list[str]:
    """Los remotes que define un rclone.conf, para poder ofrecerlos.

    Vive aquí y no en el asistente por la misma regla que rige todo `ui/tk_*`:
    ahí solo se dibuja, y elegir de una lista exige antes tener la lista."""
    ruta = Path(path).expanduser()
    try:
        texto = ruta.read_text(encoding="utf-8")
    except OSError as e:
        raise InstallError(f"No puedo leer {ruta}: {e}") from e
    return sorted(parse_rclone_conf(texto))


def parse_options(texto: str) -> dict[str, str]:
    """El cuadro de texto del formulario -> las opciones del remote.

    Una línea por opción, `clave = valor`, que es exactamente lo que va a ir al
    rclone.conf. Un formulario con un campo por backend sería mentira: rclone
    tiene decenas y cada uno con sus opciones, y el proyecto no interpreta
    ninguna. Es la misma decisión que en el editor de flags: se enseña la sintaxis
    de destino en vez de inventar una intermedia."""
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
    """Lo contrario: las opciones tal y como se enseñan en el formulario."""
    return "\n".join(f"{k} = {v}" for k, v in profile.options.items())


PLANTILLAS: dict[str, str] = {
    # Puntos de partida, no una lista cerrada: el campo «tipo» acepta cualquier
    # backend de rclone y las opciones son texto libre.
    "sftp": ("host = \nport = 22\nuser = \n"
             "disable_hashcheck = true\nshell_type = none"),
    "webdav": "url = \nvendor = other\nuser = ",
    "s3": ("provider = \naccess_key_id = \n"
           "secret_access_key = \nregion = "),
}


def _leer_clave(options: Mapping[str, str], base: Path) -> tuple[bytes | None, str, str]:
    """La clave y los known_hosts a los que apunte un rclone.conf importado.

    Se leen ahora y se meten dentro del perfil porque el dispositivo va a llevar
    su propia copia: dejar la ruta original significaría que el dispositivo solo funciona
    en el equipo del que salió."""
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
    """Importar un remote del rclone.conf que ya tenga el usuario."""
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
    clave, conocidos, key_name = _leer_clave(options, ruta.parent)
    for derivada in RUTAS_DERIVADAS:
        options.pop(derivada, None)
    return Profile(
        remote_name=remote_name, options=options, private_key=clave,
        known_hosts=conocidos, key_name=key_name, catalog_path=catalog_path,
        origen=f"importada de {ruta}")


# ---------------------------------------------------------------------------
# El formulario
# ---------------------------------------------------------------------------

def from_form(remote_name: str, options: Mapping[str, str],
              key_path: Path | str | None = None,
              known_path: Path | str | None = None,
              catalog_path: str = DEFAULT_CATALOG_PATH,
              recovery_path: str = DEFAULT_RECOVERY_PATH) -> Profile:
    """Lo que se ha tecleado en el asistente, validado antes de intentar nada."""
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
        catalog_path=(catalog_path or DEFAULT_CATALOG_PATH).strip(),
        recovery_path=(recovery_path or DEFAULT_RECOVERY_PATH).strip(),
        origen="configurada en el asistente")


def with_catalog_remote(profile: Profile, tabla: Mapping[str, object]) -> Profile:
    """El `[remote]` del catálogo, aplicado sobre el perfil que ya conecta.

    Es lo que hace que la conexión se teclee UNA vez: el primer dispositivo la
    escribe en el catálogo y todos los demás la heredan. Solo toca las opciones
    del backend —la clave nunca viaja por ahí— y respeta el nombre de remote de
    la tabla, porque es el que van a usar los `remote_path` de las parejas."""
    if not tabla:
        return profile
    datos = {str(k): v for k, v in tabla.items()}
    nombre = str(datos.pop("name", "") or profile.remote_name).strip()
    options = {k: str(v) for k, v in datos.items() if k not in RUTAS_DERIVADAS}
    if not options.get("type"):
        return profile          # tabla incompleta: no se pisa lo que ya funciona
    return replace(profile, remote_name=nombre or profile.remote_name,
                   options=options)


def align_with_catalog(perfil: Profile,
                       catalog_raw: Mapping[str, object]) -> tuple[Profile, list[str]]:
    """El perfil que se le escribe al dispositivo, según lo que diga el catálogo.

    Aquí se cierra el círculo del encargo: la conexión se teclea UNA vez y el
    catálogo la reparte. Pero hay una regla que manda sobre la comodidad, y es la
    razón de que esto no sea un simple «copia lo que haya»:

    **el nombre del remote lo decide el catálogo, no el usuario.** Los
    `remote_path` de todas las parejas se resuelven contra `[defaults].remote`, y
    si el rclone.conf del dispositivo llamara al remote de otra forma, cada
    sincronización fallaría con un «unknown remote» que no se parece en nada a la
    causa. Da igual cómo lo llamara quien tecleó la conexión: en este dispositivo
    se llama como digan las parejas que va a usar.

    Las opciones del backend sí son del usuario, salvo que el catálogo traiga un
    `[remote]` completo —el que dejó el primer dispositivo—, que entonces es la
    definición buena. La clave privada NUNCA sale de aquí ni entra por aquí: viaja
    con el dispositivo y punto.

    Devuelve el perfil ajustado y qué se ha cambiado, para poder decirlo.
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

    opciones = {k: str(v) for k, v in tabla.items()
                if k != "name" and k not in RUTAS_DERIVADAS}
    if opciones.get("type"):
        if dict(ajustado.options) != opciones:
            notas.append("Las opciones del backend salen del [remote] del "
                         "catálogo, que es el que comparten todos los dispositivos.")
        ajustado = replace(ajustado, options=opciones)

    ruta = str(defaults.get("recovery_path") or "").strip()
    if ruta and ruta != ajustado.recovery_path:
        ajustado = replace(ajustado, recovery_path=ruta)

    return ajustado, notas


def with_catalog_path(perfil: Profile, ruta: str) -> Profile:
    """El mismo perfil con otra ruta de catálogo.

    La ruta se teclea en su propia caja, aparte de la conexión, y por eso puede
    cambiar sin que se vuelva a construir el perfil entero: sin esto, editarla
    con una conexión ya dada no llegaba a ningún sitio. Vacía vuelve a la de por
    defecto, igual que en `from_form`."""
    return replace(perfil,
                   catalog_path=(ruta or "").strip() or DEFAULT_CATALOG_PATH)


def to_catalog_remote(profile: Profile) -> dict[str, str]:
    """El `[remote]` que se guarda en el catálogo. Sin nada secreto dentro."""
    tabla = {"name": profile.remote_name}
    tabla.update({k: v for k, v in profile.options.items()
                  if k not in RUTAS_DERIVADAS})
    return tabla


# ---------------------------------------------------------------------------
# Serialización del perfil (secret.py y prdrive-profile.toml comparten formato)
# ---------------------------------------------------------------------------

def dumps(profile: Profile) -> str:
    """El perfil como TOML, SIN la clave privada.

    La clave va aparte —en `keys/` o en base64 dentro de `secret.py`— para que
    este texto se pueda enseñar, guardar y versionar sin pensárselo."""
    lineas = [
        f'remote_name = "{profile.remote_name}"',
        f'key_name = "{profile.key_name}"',
        f'catalog_path = "{profile.catalog_path}"',
        f'recovery_path = "{profile.recovery_path}"',
        "",
        "[options]",
    ]
    lineas += [f'{k} = "{v}"' for k, v in profile.options.items()]
    return "\n".join(lineas) + "\n"


def loads(texto: str, *, private_key: bytes | None = None,
          known_hosts: str = "", origen: str = "") -> Profile:
    """Lee lo que escribió `dumps()` y le engancha la clave, que viaja aparte."""
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
        recovery_path=str(raw.get("recovery_path", DEFAULT_RECOVERY_PATH)
                          or DEFAULT_RECOVERY_PATH),
        origen=origen or "leída de un perfil")


# ---------------------------------------------------------------------------
# La cascada
# ---------------------------------------------------------------------------

def from_secret() -> Profile | None:
    """Lo que inyectó `build_installer.py`, si es que se compiló con perfil."""
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
    """`prdrive-profile.toml` + `keys/` junto al instalador.

    `bundle_dir()` se llama aquí y no al importar el módulo porque los tests lo
    sustituyen para apuntar a un directorio de mentira."""
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
    """El punto de partida de quien acaba de clonar el repo."""
    return Profile(remote_name=DEFAULT_REMOTE_NAME, options={},
                   origen="sin configurar")


def load() -> Profile:
    """El perfil con el que arranca el asistente. NUNCA lanza por no encontrar.

    Que no haya perfil no es un error: es el caso normal la primera vez. Lo que
    sí lanza es un perfil corrupto —un secret.py a medio compilar, un TOML
    inválido—, porque ahí callarse significaría intentar conectar con basura y
    enseñar el error de rclone en vez del de verdad."""
    for fuente in (from_secret, from_bundle):
        perfil = fuente()
        if perfil is not None and perfil.configured:
            return perfil
    return empty()
