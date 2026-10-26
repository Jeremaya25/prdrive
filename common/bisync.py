#!/usr/bin/env python3
"""Todo lo que replica el comportamiento interno de `rclone bisync`.

Aquí vive la parte incómoda del proyecto, y junta a propósito: bisync guarda su
baseline en ficheros cuyo nombre deduce de los dos extremos y no perdona que
ese nombre cambie. Saber calcular ANTES de ejecutar el nombre que rclone va a
buscar permite decidir si el baseline que hay en disco sirve para esta pareja o
hay que apartarlo y rehacerlo (`ui/pair_editor.py`).

Los listados NO se renombran jamás: renombrar es decirle a bisync que el
listado del destino ANTERIOR describe el NUEVO, y no hay forma de distinguir el
caso benigno del maligno. El nombre no depende de la máquina porque el lado
local va como `device_remote` (un remote `combine` propio).

Cada apartado cita el fichero de rclone cuyo comportamiento imita: es contra
esas fuentes contra lo que hay que contrastar cualquier cambio.
"""

from __future__ import annotations

import hashlib
import ntpath
import os
import posixpath
import re
import shutil
import threading
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

from . import model
from .model import Pair

PATH1_SUFFIX = ".path1.lst"
PATH2_SUFFIX = ".path2.lst"
ERR_SUFFIX = ".lst-err"

MISSING_LISTINGS = "cannot find prior Path1 or Path2 listings"
"""Mensaje con el que rclone se queja de que no encuentra el baseline."""


_NON_CANONICAL = re.compile(r"[\t\n\f\r \\/:?*]")
r"""El `[\s\\/:?*]` de `canonical.go`, escrito como lo lee Go.

En RE2 `\s` es solo `[\t\n\f\r ]`; el de Python es Unicode y casaría también
con `\x0b`, `\x1c`-`\x1f`, `\x85`, `\xa0` o el espacio de ancho completo, que
rclone deja tal cual en el nombre de la sesión.
"""


def canonical_path(remote: str) -> str:
    r"""Réplica de `CanonicalPath` (cmd/bisync/bilib/canonical.go, rclone v1.75.2).

    Quita `/` y `\` de los extremos y sustituye `[\s\\/:?*]` por `_`, con el
    `\s` de Go (`_NON_CANONICAL`).
    """
    return _NON_CANONICAL.sub("_", remote.strip("\\/"))


def strip_hex_string(path: str) -> str:
    """Quita el sufijo `{hexstring}` que rclone añade a la ruta.

    rclone lo añade cuando la config del remote viene de flags, entorno o
    connection string.
    """
    opening, closing = path.find("{"), path.find("}")
    if opening >= 0 and closing > opening:
        return path[:opening] + path[closing + 1:]
    return path


def fs_path_local(p: str) -> str:
    r"""Réplica de `FsPath` de canonical.go para el backend local: `F:\ruta\`.

    Termina siempre en el separador del sistema; en Windows quita el prefijo
    `\\?\`.
    """
    sep = "\\" if IS_WIN else "/"
    if IS_WIN:
        p = p.replace("/", sep)
        if p.startswith("\\\\?\\"):
            p = p[4:]
    return p if p.endswith(sep) else p + sep


def fs_path_remote(s: str, tipos: dict[str, TipoRemote] | None = None) -> str:
    """Réplica de `FsPath` de canonical.go para un remote con nombre: `remote:ruta/`.

    `FsPath` pone `nombre + ":" + f.Root()`, y casi siempre `Root()` es la ruta
    tal cual. Dos tipos de remote son la excepción (`tipos_de_remote()`): uno
    `local` tiene por `Root()` la ruta limpia (`raiz_local()`), y uno `alias`
    ni siquiera es él: se escribe el destino (`resolver_extremo()`).

    Si pasa por un alias que no se puede resolver, lo deja como viene: es la
    mejor estimación que queda, y `prefijo_comprobable()` avisa de que no es de
    fiar.

    Args:
        tipos: Los remotes del `rclone.conf` ya leídos (`tipos_de_remote()`),
            para que quien calcula varios extremos lo lea una sola vez; `None`
            lo lee aquí.
    """
    resuelto = resolver_extremo(s, tipos)
    if resuelto is not None:
        return resuelto
    return s if s.endswith("/") else s + "/"


IS_WIN = os.name == "nt"
"""Si `raiz_local()` hace lo de Windows; de módulo para que los tests prueben las dos."""
_UNIDAD = re.compile(r"^[a-zA-Z]:\\")

TOPE_ALIAS = 8
"""Cuántos alias encadenados se siguen antes de darlos por un ciclo."""


class TipoRemote(NamedTuple):
    """Lo que hace falta saber de un remote del `rclone.conf` para nombrar su extremo.

    Args:
        tipo: Su `type`, o `None` si el remote no lo dice.
        nounc: Si tiene `nounc = true`; solo cuenta en un remote `local`.
        destino: Su opción `remote`, vacía si no la tiene; solo un `alias` la lleva.
    """
    tipo: str | None
    nounc: bool
    destino: str


def tipos_de_remote() -> dict[str, TipoRemote]:
    """Devuelve `{remote: TipoRemote}` del `rclone.conf` del dispositivo.

    Lo lee `pairing.parse_rclone_conf()`, el único lector del proyecto. Sin
    fichero, o sin leerse, vacío: el nombre se calcula como el de cualquier
    remote.
    """
    from .pairing import parse_rclone_conf
    try:
        texto = model.RCLONE_CONF.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    return {nombre: TipoRemote(opciones.get("type"),
                               opciones.get("nounc", "").lower() == "true",
                               opciones.get("remote", ""))
            for nombre, opciones in parse_rclone_conf(texto).items()}


def resolver_extremo(s: str, tipos: dict[str, TipoRemote] | None = None) -> str | None:
    """Devuelve el extremo `remote:ruta/` tal como lo escribe `FsPath`, o `None` si no se sabe.

    Un remote `alias` no tiene nombre propio: su `NewFs` devuelve el `Fs` del
    destino (`cache.Get(ctx, fspath.JoinRootPath(opt.Remote, root))`,
    backend/alias/alias.go), y `FsPath` ve el `Name()` y el `Root()` de ese
    destino. Se sigue la cadena como rclone, con el `rclone.conf` del
    dispositivo:

    - un destino que es una ruta suelta (`/datos`, `C:\\datos`) es el backend
      local de nombre `local`, que `FsPath` escribe sin `nombre:` y con el
      separador del sistema (`fs_path_local()` sobre su `Root()`);
    - uno que es otro remote se nombra por él, con la regla de su tipo
      (`local`: `raiz_local()`; otro `alias`: se sigue; cualquier otro, tal
      cual).

    Los demás envoltorios (`crypt`, `union`, `combine`, `chunker`, `hasher`,
    `compress`) devuelven su propio `Fs`, con el nombre de su sección, y no
    necesitan nada de esto.

    Args:
        tipos: Los remotes del `rclone.conf` ya leídos (`tipos_de_remote()`);
            `None` lo lee aquí. Un diccionario vacío es un `rclone.conf` sin
            remotes, no «sin leer».

    Returns:
        El extremo, o `None` si pasa por un alias que no se puede seguir: sin
        `remote`, un ciclo (`TOPE_ALIAS`), un destino que no está en el
        `rclone.conf` o una cadena de conexión (`:backend,…:ruta`), que no se
        modela.
    """
    nombre, dos_puntos, ruta = s.partition(":")
    if not dos_puntos:
        return s if s.endswith("/") else s + "/"
    return _extremo(nombre, ruta, tipos_de_remote() if tipos is None else tipos, 0)


def _extremo(nombre: str, ruta: str, tipos: dict[str, TipoRemote], saltos: int) -> str | None:
    """Devuelve el extremo de `nombre:ruta` con la regla de su tipo; ver `resolver_extremo()`."""
    tipo = tipos.get(nombre, TipoRemote(None, False, ""))
    if tipo.tipo == "alias":
        return _extremo_alias(nombre, tipo, ruta, tipos, saltos)
    if tipo.tipo == "local":
        ruta = raiz_local(ruta, tipo.nounc)
    extremo = f"{nombre}:{ruta}"
    return extremo if extremo.endswith("/") else extremo + "/"


def _extremo_alias(nombre: str, tipo: TipoRemote, ruta: str, tipos: dict[str, TipoRemote],
                   saltos: int) -> str | None:
    """Sigue un alias hasta su destino, con la raíz `ruta` que le llega a su `NewFs`."""
    if not tipo.destino or saltos >= TOPE_ALIAS:
        return None
    partido = _partir_remote(tipo.destino)
    if partido is None:
        return None
    destino, base = partido
    raiz = _unir_raiz(base, ruta, bool(destino))
    if not destino:
        return fs_path_local(raiz_local(raiz))
    if destino not in tipos:
        return None
    return _extremo(destino, raiz, tipos, saltos + 1)


def _partir_remote(texto: str) -> tuple[str, str] | None:
    """Réplica reducida de `fspath.Parse` (fs/fspath/path.go) para la opción `remote` de un alias.

    Returns:
        `(nombre, ruta)`, con el nombre vacío si es una ruta local (también
        `C:\\ruta` en Windows, donde una sola letra es una unidad: no hay
        unidades en `driveletter.IsDriveLetter` fuera de Windows). `None` si
        no hay nada, o si es una cadena de conexión (`:backend:ruta`, o con
        parámetros `nombre,clave=valor:ruta`).
    """
    if not texto or texto.startswith(":"):
        return None
    ruta_local = texto.replace("\\", "/") if IS_WIN else texto   # `filepath.ToSlash`
    if ":" not in texto:
        return "", ruta_local
    for i, letra in enumerate(texto):
        if letra in "/\\":
            return "", ruta_local        # un `:` tras una barra es de la ruta
        if letra == ",":
            return None
        if letra == ":":
            nombre, resto = texto[:i], texto[i + 1:]
            if IS_WIN and len(nombre) == 1 and nombre.isascii() and nombre.isalpha():
                return "", ruta_local
            return nombre, resto.replace("\\", "/") if IS_WIN else resto
    return None


def _limpiar(ruta: str) -> str:
    """Réplica de `path.Clean` de Go: como `posixpath.normpath`, sin guardar las dos barras."""
    limpia = posixpath.normpath(ruta)
    return limpia[1:] if limpia.startswith("//") else limpia


def _unir(*partes: str) -> str:
    """Réplica de `path.Join` de Go: ignora lo vacío y limpia el resultado."""
    partes = tuple(p for p in partes if p)
    return _limpiar("/".join(partes)) if partes else ""


def _unir_raiz(base: str, ruta: str, con_nombre: bool) -> str:
    """Réplica de `fspath.JoinRootPath` (fs/fspath/path.go) con el remote ya separado de su ruta.

    Args:
        base: La ruta del remote del alias (lo que va detrás de `nombre:`).
        ruta: La raíz con la que llega al alias; se hace absoluta antes de
            unirla, para que no pueda salirse de él (`makeAbsolute`).
        con_nombre: Si el destino es un remote con nombre y no una ruta local.
    """
    if not ruta:
        return base
    ruta = ruta.replace("\\", "/") if IS_WIN else ruta
    con_barra = ruta.startswith("/")
    absoluta = _limpiar("/" + ruta)
    ruta = absoluta if con_barra else absoluta[1:]
    if not con_nombre and base.startswith("//"):
        return "/" + _unir(base, ruta)       # las rutas de red de Windows guardan sus dos barras
    unida = _unir(base, ruta)
    return "" if con_nombre and unida == "." else unida


_CITA = "\u201b"
"""El `QuoteRune` de lib/encoder (‛): delante de un símbolo, dice que es el símbolo y no lo que codifica."""
_SIMBOLO = 0x2400
"""El `symbolOffset` de lib/encoder (␀): un carácter de control `c` se escribe `chr(_SIMBOLO + c)`."""


def _codificar(nombre: str, estandar: bool) -> str:
    """Réplica de `MultiEncoder.Encode` (lib/encoder/encoder.go) para un tramo.

    Solo con las dos máscaras que pasan por el `Root()` del backend local en
    POSIX: `encoder.Standard` (`estandar`: `EncodeZero | EncodeSlash | EncodeCtl
    | EncodeDel | EncodeDot`) y `encoder.Base`, el `encoder.OS` de POSIX
    (`EncodeZero | EncodeSlash | EncodeDot`).
    """
    if nombre in (".", ".."):
        return "\uff0e" * len(nombre)
    if nombre in ("\uff0e", "\uff0e\uff0e"):
        return (_CITA + "\uff0e") * len(nombre)
    salida = []
    for ch in nombre:
        o = ord(ch)
        if ch == "\0":
            salida.append(chr(_SIMBOLO))
        elif ch in (chr(_SIMBOLO), _CITA, "\uff0f"):
            salida.append(_CITA + ch)
        elif ch == "/":
            salida.append("\uff0f")
        elif estandar and ch == "\x7f":
            salida.append("\u2421")
        elif estandar and 1 <= o <= 0x1F:
            salida.append(chr(_SIMBOLO + o))
        elif estandar and (ch == "\u2421" or _SIMBOLO < o <= _SIMBOLO + 0x1F):
            salida.append(_CITA + ch)
        else:
            salida.append(ch)
    return "".join(salida)


def _decodificar(nombre: str, estandar: bool) -> str:
    """Réplica de `MultiEncoder.Decode` (lib/encoder/encoder.go) para un tramo.

    Deshace `_codificar()` con la misma máscara. Una `‛` que no va delante de un
    símbolo se queda como está.
    """
    if nombre in ("\uff0e", "\uff0e\uff0e"):
        return "." * len(nombre)
    if nombre in (_CITA + "\uff0e", (_CITA + "\uff0e") * 2):
        return "\uff0e" * (len(nombre) // 2)
    salida = []
    citar = False
    for ch in nombre:
        citado, citar = citar, False
        o = ord(ch)
        if ch == _CITA and not citado:
            citar = True
            continue
        if ch == chr(_SIMBOLO):
            salida.append(ch if citado else "\0")
        elif ch == "\uff0f":
            salida.append(ch if citado else "/")
        elif estandar and ch == "\u2421":
            salida.append(ch if citado else "\x7f")
        elif estandar and _SIMBOLO < o <= _SIMBOLO + 0x1F:
            salida.append(ch if citado else chr(o - _SIMBOLO))
        else:
            salida.append(_CITA + ch if citado and ch != _CITA else ch)
    if citar:
        salida.append(_CITA)
    return "".join(salida)


def raiz_local(ruta: str, nounc: bool = False) -> str:
    r"""Réplica del `Root()` del backend local de rclone (backend/local/local.go).

    Es `cleanRootPath()` y después `Root()`, contrastado con rclone v1.75.2. En
    POSIX, cada tramo que no es `.` ni `..` pasa a la codificación del sistema
    (`encoder.OS.FromStandardName`), la ruta se limpia (`filepath.Clean`: `a//b`
    y `a/./b` son `a/b`), y `Root()` devuelve cada tramo en la codificación
    estándar (`ToStandardPath`): un `.` o `..` suelto sale como `．`/`．．`, un
    carácter de control como su símbolo (`\x0b` → `␋`, `\x7f` → `␡`) y una `‛`
    suelta, doble (`it‛s` → `it‛‛s`). En Windows, absoluta (`filepath.Abs`, y
    rclone corre con cwd en `model.APP_DIR`) y con `\\?\` delante
    (`file.UNCPath()`, lib/file/unc_windows.go) salvo con `nounc = true`:
    `D:\datos` es `//?/D:/datos`, y `\\nas\datos`, `//?/UNC/nas/datos`. Allí el
    codificador es otro (lib/encoder/os_windows.go) y no se replica: no se ha
    contrastado con un rclone de Windows.
    """
    if IS_WIN:
        limpia = ntpath.normpath(ntpath.join(str(model.APP_DIR), ruta.replace("/", "\\")))
        if not nounc and not limpia.startswith("\\\\?\\"):
            if limpia.startswith("\\\\"):
                limpia = "\\\\?\\UNC\\" + limpia[2:]
            elif _UNIDAD.match(limpia):
                limpia = "\\\\?\\" + limpia
        return limpia.replace("\\", "/")
    tramos = [t if t in (".", "..") else _codificar(_decodificar(t, True), False)
              for t in (ruta or "").split("/")]
    limpia = posixpath.normpath("/".join(tramos) or ".")
    if limpia.startswith("//"):
        limpia = limpia[1:]          # `filepath.Clean` no guarda las dos barras de POSIX
    return "/".join(_codificar(_decodificar(t, False), True) for t in limpia.split("/"))


def session_name(path1: str, path2: str) -> str:
    """Réplica de `SessionName` de canonical.go.

    Es `CanonicalPath(path1) + ".." + CanonicalPath(path2)`, sin el sufijo
    `{hexstring}`.
    """
    return strip_hex_string(canonical_path(path1)) + ".." + strip_hex_string(canonical_path(path2))


def expected_prefix(pair: Pair, tipos: dict[str, TipoRemote] | None = None) -> str:
    """Devuelve el nombre base de los `.path1.lst` y `.path2.lst` que rclone buscará.

    Args:
        tipos: Los remotes del `rclone.conf` ya leídos (`tipos_de_remote()`);
            `None` lo lee cada vez que hace falta.
    """
    def render(kind: str) -> str:
        """Devuelve el extremo tal como lo escribe rclone al nombrar la sesión."""
        endpoint = pair.endpoint(kind)
        if kind == "local" and not pair.device_remote:
            # El backend `local` sin nombre: su `Root()` también codifica los tramos
            # (`raiz_local()`). En Windows no se ha contrastado y va tal cual.
            return fs_path_local(endpoint if IS_WIN else raiz_local(endpoint))
        return fs_path_remote(endpoint, tipos)

    return session_name(render(pair.mode.source), render(pair.mode.dest))


def prefijo_comprobable(pair: Pair, tipos: dict[str, TipoRemote] | None = None) -> bool:
    """Indica si `expected_prefix()` es el nombre que rclone escribirá, y no una estimación.

    No lo es cuando un extremo pasa por un alias que no se puede seguir
    (`resolver_extremo()`): entonces el prefijo esperado es el del alias sin
    resolver, y comparar con él un baseline que rclone escribió con el destino
    daría un «no es de esta pareja» falso. Quien diagnostica no debe acusar con
    él.

    Args:
        tipos: Los remotes del `rclone.conf` ya leídos (`tipos_de_remote()`);
            `None` lo lee cada vez que hace falta.
    """
    for kind in (pair.mode.source, pair.mode.dest):
        if kind == "local" and not pair.device_remote:
            continue
        if resolver_extremo(pair.endpoint(kind), tipos) is None:
            return False
    return True


FILTERS_HEADER = (
    "# Generado por sync.py desde sync_config.toml. No editar a mano:\n"
    "# se regenera en cada ejecución. Cambiar los patrones exige --resync."
)
"""Cabecera del fichero de filtros generado."""


class FiltersState(NamedTuple):
    """Si el fichero de filtros coincide con el que se usó en el último resync.

    Args:
        status: `ok`, `new` (sin hash previo) o `changed`.
        detail: Frase que lo explica.
    """
    status: str
    detail: str

    @property
    def needs_resync(self) -> bool:
        """Indica si hace falta un `--resync` por culpa de los filtros."""
        return self.status != "ok"


def filters_content(pair: Pair) -> str:
    """Devuelve el contenido del fichero de filtros de la pareja.

    Las reglas van en orden de prioridad: gana la primera que casa.
    """
    lines = [FILTERS_HEADER]
    if pair.versions:
        # No es filtrado: es la condición de rclone para que `.prversions/`
        # viva dentro del pair. Sin ella `--backup-dir1` solapa con Path1 y la
        # pasada muere con «destination and parameter to --backup-dir mustn't
        # overlap», error crítico que invalida el baseline. Va PRIMERA: rclone
        # aplica las reglas en orden y detrás de un `+ **/*.md` no excluiría
        # nada.
        lines.append(f"- {model.VERSIONS_DIR}/**")
    # Las del código van antes que las del TOML: las del llavero son toda su
    # lista, y `REGLA_SIN_LLAVERO` tiene que ganar a cualquier `+` de la pareja.
    lines += list(pair.reglas)
    lines += [f"+ {p}" for p in pair.includes]
    lines += [f"- {p}" for p in pair.excludes]
    if pair.includes:
        # Como `--include`: si hay reglas `+`, todo lo demás queda fuera.
        lines.append("- **")
    return "\n".join(lines) + "\n"


def _escribir_filtros(path: Path, content: str) -> None:
    """Escribe el fichero de filtros de golpe: quien lo lee ve el anterior o el nuevo entero.

    Lo regenera quien lo necesita primero: la pasada, o la ventana desde un hilo
    mientras otra pantalla lo lee desde el de Tk. Un fichero a medias tiene otro
    md5 y se leería como «los filtros han cambiado», así que se escribe en un
    temporal con nombre propio (dos hilos no comparten el suyo) y se renombra
    encima. Si el renombrado no se deja (Windows no sustituye un fichero que otro
    tiene abierto) se escribe en el sitio: lo que falla de verdad sigue siendo un
    error.
    """
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        tmp.write_text(content, encoding="utf-8", newline="\n")
        os.replace(tmp, path)
        return
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
    path.write_text(content, encoding="utf-8", newline="\n")


def ruta_filtros(pair: Pair) -> Path | None:
    """Devuelve dónde está el fichero de filtros de la pareja, sin tocar el disco.

    Es la ruta que `filters_file_for()` genera y la que `sync.py` le pasa a
    rclone; la vista previa de la orden la usa sin escribir nada.

    Returns:
        La ruta, o `None` si la pareja no usa fichero de filtros.
    """
    return model.FILTERS_DIR / f"{pair.name}.txt" if pair.wants_filters_file else None


def filters_file_for(pair: Pair) -> Path | None:
    """Genera `filters/<pareja>.txt` si hace falta y devuelve su ruta.

    El contenido es determinista: si no cambia no se reescribe el fichero, para
    no gastar ciclos del dispositivo ni invalidar el md5 sin motivo. Cuando
    cambia se escribe de golpe (`_escribir_filtros()`).

    Returns:
        La ruta (`ruta_filtros()`), o `None` si la pareja no usa fichero de
        filtros.
    """
    path = ruta_filtros(pair)
    if path is None:
        return None

    content = filters_content(pair)
    model.FILTERS_DIR.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.read_text(encoding="utf-8") != content:
        _escribir_filtros(path, content)
    return path


def filters_state(ffile: Path | None) -> FiltersState:
    """Compara el fichero de filtros con el `.md5` que dejó el último resync.

    bisync guarda el md5 junto al propio fichero (`filtersFile + ".md5"`,
    cmd/bisync/cmd.go: `applyFilters`) y solo lo escribe durante un `--resync`;
    si el fichero cambia sin resync aborta con error crítico. Aquí se compara
    ANTES de ejecutar y se trata como «hace falta resync», que es una
    conversación y no un log rojo.

    Args:
        ffile: El fichero de filtros, o `None` si la pareja no tiene.
    """
    if ffile is None:
        return FiltersState("ok", "sin fichero de filtros")
    digest = hashlib.md5(ffile.read_bytes()).hexdigest()
    hash_file = Path(str(ffile) + ".md5")
    if not hash_file.exists():
        return FiltersState("new", f"{ffile.name} sin hash previo")
    if hash_file.read_text(encoding="utf-8").strip() != digest:
        return FiltersState("changed", f"{ffile.name} ha cambiado desde el último resync")
    return FiltersState("ok", f"{ffile.name} sin cambios")


class PairState(NamedTuple):
    """El estado real del baseline de una pareja.

    Args:
        status: `fresh` (sin listados), `ok` o `broken`.
        detail: Frase que lo explica.
        prefix: Prefijo de los listados; solo con `status == "ok"`.
    """
    status: str
    detail: str
    prefix: str | None

    @property
    def has_baseline(self) -> bool:
        """Indica si hay un baseline utilizable."""
        return self.status == "ok"


def _prefixes(paths: list[Path], suffix: str) -> set[str]:
    """Devuelve los prefijos de los listados, sin el sufijo `suffix`."""
    return {p.name[: -len(suffix)] for p in paths}


def pair_state(pair: Pair) -> PairState:
    """Devuelve el estado real del baseline, mirando los `.lst` del workdir."""
    workdir = pair.workdir
    if not workdir.exists():
        return PairState("fresh", "sin workdir (nunca sincronizada)", None)

    # Los `.lst-err` no los limpia nadie (rclone solo renombra `.lst` a
    # `.lst-err` al abortar; cmd/bisync/operations.go): si después hay un juego
    # de listados válido, el baseline es bueno y esos son residuo.
    #
    # Contra rclone v1.75.1: ante un error crítico `Bisync()` renombra los dos
    # listados a `.lst-err` («the prior listings are renamed to .lst-err to lock
    # out further runs»), y una interrupción que no se cierra bien hace lo mismo
    # con `markFailed()` (cmd/bisync/lockfile.go), que antes borra el `-err` que
    # hubiera. Con `--recover` la pasada siguiente vuelve a los `.lst-old` y
    # rehace los `.lst` (operations.go, «Reverting to prior backup»), y los
    # `-err` se quedan como estaban: ahí no se vuelven a leer, solo se
    # renombran. Se explican, nunca se borran: lo que hay en el workdir de
    # bisync no es cosa nuestra.
    path1 = sorted(workdir.glob("*" + PATH1_SUFFIX))
    path2 = sorted(workdir.glob("*" + PATH2_SUFFIX))
    errors = sorted(workdir.glob("*" + ERR_SUFFIX))
    residuo = (f" (+{len(errors)} {ERR_SUFFIX}: el baseline que rclone apartó al "
               f"abortar una pasada; ya no lo usa y se puede borrar a mano)"
               if errors else "")

    if path1 and path2:
        pre1 = _prefixes(path1, PATH1_SUFFIX)
        pre2 = _prefixes(path2, PATH2_SUFFIX)
        common = pre1 & pre2
        if len(common) != 1 or len(pre1) != 1 or len(pre2) != 1:
            return PairState("broken", f"varios juegos de listados: {sorted(pre1 | pre2)}", None)
        prefix = common.pop()
        return PairState("ok", f"baseline '{prefix}'{residuo}", prefix)

    if errors:
        return PairState(
            "broken",
            f"{len(errors)} listado(s) {ERR_SUFFIX}: rclone aparta así el baseline "
            f"cuando una pasada aborta con un error crítico, para bloquear las "
            f"siguientes",
            None)
    if path1 or path2:
        return PairState("broken", "falta uno de los dos listados (.path1/.path2)", None)
    return PairState("fresh", "sin listados previos", None)


def last_run(pair: Pair) -> float | None:
    """Devuelve cuándo fue la última pasada buena.

    No hay registro de pasadas ni hace falta inventarlo: bisync reescribe sus
    dos listados justo al terminar bien (cmd/bisync/operations.go), así que la
    fecha del más nuevo ES la de la última sincronización correcta. Fuera de
    bisync no queda rastro (un `copy` no deja estado) y esas parejas se quedan
    sin hora antes que enseñar una inventada.

    Returns:
        La marca de tiempo, o `None` si no se puede saber.
    """
    if not pair.is_bisync:
        return None
    try:
        marcas = [p.stat().st_mtime
                  for sufijo in (PATH1_SUFFIX, PATH2_SUFFIX)
                  for p in pair.workdir.glob("*" + sufijo)]
    except OSError:
        return None  # el dispositivo ya no está
    return max(marcas) if marcas else None


def programa_en_listado(pair: Pair) -> bool:
    """Indica si el último listado del remoto trae la carpeta del programa.

    Lo mira en el `path2.lst` del baseline, que describe el lado remoto tal
    como quedó en la última pasada buena. Es la señal de que una pareja de la
    raíz entera subió `.prdrive/` (con su clave y su `rclone.conf`) antes de
    que `model.REGLA_SIN_PROGRAMA` la dejara fuera: la regla no la borra del
    remoto, y tras el `--resync` el listado nuevo ya no la enseña. Solo tiene
    sentido para una pareja de la raíz entera (`Pair.es_raiz`): en otra, una
    carpeta con ese nombre sería del usuario.

    Es información de cortesía y no decide nada, así que un listado que falta
    o que no se puede leer cuenta como que no.

    Returns:
        `True` si alguna ruta del listado cuelga de la carpeta del programa.
    """
    lst = pair.workdir / (expected_prefix(pair) + PATH2_SUFFIX)
    # Cada línea es `flags tamaño hash id fecha "ruta"` (cmd/bisync/listing.go):
    # la ruta empieza en la primera comilla, y la cabecera `# …` no lleva ruta.
    carpeta = model.APP_DIR.name + "/"
    try:
        with lst.open(encoding="utf-8", errors="replace") as f:
            for linea in f:
                _, comilla, ruta = linea.partition('"')
                if comilla and not linea.startswith("#") and ruta.startswith(carpeta):
                    return True
    except OSError:
        pass
    return False


def _sin_entradas(lst: Path) -> bool:
    """Indica si un listado de bisync no trae ni un fichero ni una carpeta.

    Es `fileList.empty()` de rclone (`cmd/bisync/listing.go`, igual en v1.75.1
    y v1.75.2) sobre lo que `loadListing()` deja en la lista: no cuentan las líneas en blanco ni las
    que empiezan por `#` (la cabecera `# bisync listing v1 from …`), y sí cuenta
    cualquier otra, sea fichero (`-`) o carpeta (`d`, con
    `create-empty-src-dirs`). Una línea que rclone descartaría por rota
    (`lineRegex`) cuenta aquí como contenido, a propósito: decir «vacío» de
    más rehace una referencia que sí tenía algo que proteger, y decirlo de
    menos solo deja el fallo de siempre. Un listado que no se puede leer no
    está vacío.
    """
    try:
        with lst.open(encoding="utf-8", errors="replace") as f:
            for linea in f:
                linea = linea.rstrip("\n")
                if linea and not linea.startswith("#"):
                    return False
    except OSError:
        return False
    return True


def referencia_vacia(pair: Pair, state: PairState | None = None,
                     tipos: dict[str, TipoRemote] | None = None) -> bool:
    """Indica si la pasada va a rehacer sola el baseline de la pareja, por estar vacío.

    Un baseline vacío es lo que deja un `--resync` sobre dos lados vacíos, y
    rclone aborta con él toda pasada que no sea otro `--resync`
    (`checkListing()`, «Empty prior Path1 listing», código 7) porque no sabe
    distinguir una carpeta vacía de una sin montar. Con la referencia vacía no
    queda nada que proteger, y la rehace sola `sync._bisync_preflight()`. Esa
    decisión es esta función, y `--doctor` dice lo mismo porque la usa también.
    Tiene que cumplirse todo:

    - El baseline es de ESTA pareja: su prefijo es el esperado
      (`expected_prefix()`) y ese prefijo se puede comprobar
      (`prefijo_comprobable()`). Si un extremo cambió sin apartarlo (el TOML a
      mano, el destino de un `alias`), rclone no lo encontraría, y rehacer sin
      preguntar contra los extremos nuevos es decisión de una persona
      («Reparación», hallazgo `prefijo`). Si el prefijo es una estimación (un
      alias que no se puede seguir), que el baseline lleve ese nombre no prueba
      nada, y no se decide por él.
    - La carpeta local existe. Sin ella, con baseline, la pasada aborta con 2
      y no crea nada: un lado vacío se lee como «han borrado todo».
    - Los DOS listados están vacíos. Si solo lo está uno, un lado se ha vaciado
      desde la última pasada buena y rclone debe pararla.

    Args:
        state: El estado ya calculado, para no recorrer otra vez el workdir.
        tipos: Los remotes del `rclone.conf` ya leídos (`tipos_de_remote()`),
            para no volver a leerlo; `None` lo lee aquí, una sola vez y solo si
            la pareja tiene baseline.

    Returns:
        `True` si se cumple todo lo anterior; `False` si no, si falta un
        listado o no se puede leer, y fuera de bisync.
    """
    if not pair.is_bisync:
        return False
    if state is None:
        state = pair_state(pair)
    if not state.has_baseline:
        return False
    if tipos is None:
        tipos = tipos_de_remote()
    if not prefijo_comprobable(pair, tipos) or state.prefix != expected_prefix(pair, tipos):
        return False
    if not pair.local_abs.exists():
        return False
    return all(_sin_entradas(pair.workdir / (state.prefix + sufijo))
               for sufijo in (PATH1_SUFFIX, PATH2_SUFFIX))


def resync_reasons(pair: Pair, state: PairState | None = None) -> list[str]:
    """Devuelve por qué esta pareja necesita `--resync`.

    Args:
        state: El estado ya calculado, para no recorrer otra vez el workdir.

    Returns:
        Los motivos; lista vacía si no lo necesita (también fuera de bisync).
    """
    if not pair.is_bisync:
        return []
    if state is None:
        state = pair_state(pair)
    reasons = []
    if not state.has_baseline:
        reasons.append(f"estado {state.status}: {state.detail}")
    filters = filters_state(filters_file_for(pair))
    if filters.needs_resync:
        reasons.append(f"filtros {filters.status}: {filters.detail}")
    return reasons


def migrate_legacy_state(pair: Pair) -> None:
    """Mueve los listados del layout antiguo al workdir de la pareja.

    El layout antiguo los tenía sueltos en `state/`. La pareja se identifica
    por el token del remoto en el nombre; si no es inequívoca no se toca nada.
    """
    workdir = pair.workdir
    if workdir.exists() and any(workdir.glob("*.lst")):
        return
    token = canonical_path(pair.remote_endpoint)
    candidates = {
        f.name[: -len(PATH1_SUFFIX)]
        for f in model.STATE_DIR.glob("*" + PATH1_SUFFIX)
        if token in f.name
    }
    if len(candidates) != 1:
        return
    prefix = candidates.pop()
    workdir.mkdir(parents=True, exist_ok=True)
    moved = 0
    for f in model.STATE_DIR.iterdir():
        if f.is_file() and f.name.startswith(prefix):
            shutil.move(str(f), str(workdir / f.name))
            moved += 1
    if moved:
        print(f"  migrados {moved} fichero(s) de estado a {workdir}")


def pair_state_paths(name: str) -> list[Path]:
    """Devuelve lo que hay en disco atado a esa pareja.

    Son su workdir y su fichero de filtros. Sirve para avisar de qué queda
    huérfano al quitar una pareja y para limpiarlo si se pide.
    """
    encontrados = [model.STATE_DIR / name]
    encontrados += [model.FILTERS_DIR / f"{name}.txt",
                    model.FILTERS_DIR / f"{name}.txt.md5"]
    return [p for p in encontrados if p.exists()]


def shelve_baseline(name: str) -> Path | None:
    """Aparta el baseline de una pareja: `state/<n>/` pasa a `state/<n>.old-<fecha>/`.

    Es lo que hay que hacer cuando cambia un EXTREMO de la pareja (`local`,
    `remote`, `remote_path` o `mode`): reaprovechar los listados con el prefijo
    nuevo diría a bisync que el listado del destino VIEJO describe el NUEVO, y
    todo lo que falte en el nuevo se leería como borrado y se propagaría.
    Apartándolo, la pareja queda `fresh` y exige un `--resync` explícito.

    Se renombra en vez de borrar por si hay que volver atrás; el directorio
    apartado queda inerte porque lo que recorre `state/` solo mira su primer
    nivel.

    Returns:
        Dónde ha quedado, o `None` si no había baseline que apartar.
    """
    workdir = model.STATE_DIR / name
    if not workdir.is_dir():
        return None
    sello = f"{datetime.now():%Y%m%d_%H%M%S}"
    destino = model.STATE_DIR / f"{name}.old-{sello}"
    n = 1
    while destino.exists():
        destino = model.STATE_DIR / f"{name}.old-{sello}_{n}"
        n += 1
    workdir.rename(destino)
    return destino


def rename_pair_state(old: str, new: str) -> list[tuple[Path, Path]]:
    """Mueve el estado de una pareja cuando solo cambia su nombre.

    El prefijo de los listados NO depende del nombre (sale de los extremos:
    `expected_prefix`), así que renombrar no invalida el baseline. Lo que
    cuelga del nombre son `state/<nombre>/` y `filters/<nombre>.txt` con su
    `.md5`, que se mueven juntos para que el hash que guarda bisync siga
    cuadrando.

    Returns:
        Los movimientos como `(origen, destino)`, para poder deshacerlos.
    """
    movimientos: list[tuple[Path, Path]] = []
    origen, destino = model.STATE_DIR / old, model.STATE_DIR / new
    if origen.is_dir() and not destino.exists():
        origen.rename(destino)
        movimientos.append((origen, destino))
    for sufijo in (".txt", ".txt.md5"):
        f_old = model.FILTERS_DIR / f"{old}{sufijo}"
        f_new = model.FILTERS_DIR / f"{new}{sufijo}"
        if f_old.exists() and not f_new.exists():
            f_old.rename(f_new)
            movimientos.append((f_old, f_new))
    return movimientos
