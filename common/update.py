#!/usr/bin/env python3
"""
update.py — Si hay una versión nueva en GitHub, y cómo traérsela.

Aquí no se copia nada al dispositivo. Este módulo mira, compara, descarga y
verifica; quien escribe es `install/deploy.py`, ejecutado desde el zip recién
descargado (`prdrive-install.py --update`). Esa separación no es capricho:

  * `install/` NO viaja al dispositivo —a propósito, ver `deploy.DEPLOY_FILES`—,
    así que el código de a bordo no puede llamar a `deploy_code()`. El zip sí lo
    trae, y así **la versión nueva se instala a sí misma**.
  * Si el aplicador viviera aquí habría una segunda copia del manifiesto de qué
    es el árbol desplegado, y sería la que se quedaría atrás el día que se añada
    un fichero.

Tres reglas, y las tres vienen de que esto lo llama una ventana:

  * **Mirar nunca es un error.** `check()` devuelve `(release, motivo)` y no
    lanza: sin red se enseña lo último que se supo, y si no se supo nada, nada.
    Igual que `catalog.load()`.
  * **La ventana no espera a la red.** `pending()` lee solo la caché y es lo que
    se pregunta al pintar; la consulta de verdad va en un hilo aparte.
  * **`fetch()` es una función de módulo a propósito**, y es el único sitio por
    el que sale una petición. Los tests la sustituyen entera, y así ninguno toca
    la red.

Lo que respalda una descarga es TLS con validación de certificado, el CRC del
zip, la lista de ficheros obligatorios y que el `VERSION` de dentro cuadre con
el tag pedido. **No hay firma**: el repositorio es público y esto es lo que hay.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import sys
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Callable, NamedTuple

from . import APP_NAME, model, store

# El repositorio del proyecto. Está aquí y no en la configuración porque no es
# un ajuste: es de dónde sale este mismo programa.
REPO = "Jeremaya25/prdrive"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
PAGINA = f"https://github.com/{REPO}/releases"

# El zip del código de un tag. Se pide a codeload y no al `zipball_url` de la
# API para no depender de un redirección más ni de la cuota de la API.
ZIP_URL = "https://codeload.github.com/" + REPO + "/zip/refs/tags/{tag}"

# Comprobado: la API de GitHub responde 403 a una petición sin User-Agent.
# urllib pone `Python-urllib/3.x` por su cuenta y con eso ya contesta, pero se
# manda uno propio para que en los registros de GitHub se vea quién pregunta.
USER_AGENT = f"{APP_NAME}-update (+https://github.com/{REPO})"

TIMEOUT_API = 8            # la ventana no puede quedarse esperando más
TIMEOUT_ZIP = 60           # aquí sí se espera por ancho de banda
CACHE_HORAS = 24           # cada cuánto se vuelve a preguntar
NOTAS_MAX = 4000           # las notas de la release, recortadas para el estado

# Lo que tiene que traer el zip para que se le deje tocar el dispositivo. No es
# la lista de lo que se copia —esa la manda `deploy.DEPLOY_FILES`, y vive allí—:
# es la comprobación de que lo descargado es este proyecto y está entero.
OBLIGATORIOS = ("VERSION", "sync.py", "runsync.py", "penwatch.py",
                "prdrive-install.py", "common/model.py", "ui/tk.py",
                "install/deploy.py")

Progreso = Callable[[str], None]


class UpdateError(Exception):
    """Algo ha impedido actualizar, y se puede contar.

    Excepción y no `sys.exit`, por lo mismo que `InstallError` y `ConfigError`:
    esto corre con una ventana abierta, y matar el proceso ahí es cerrársela al
    usuario en la cara en vez de dejarle leer qué ha pasado."""


class Release(NamedTuple):
    """Una release de GitHub, con lo poco que hace falta de ella."""
    tag: str                   # 'v0.0.2', tal cual lo publica GitHub
    version: str               # '0.0.2', que es lo que se compara
    name: str                  # el título de la release
    url: str                   # la página, para el botón «Ver la página»
    published: str             # la fecha ISO que devuelve la API
    notes: str = ""            # el cuerpo, para enseñarlo en la pantalla


# ---------------------------------------------------------------------------
# La versión instalada
# ---------------------------------------------------------------------------

def installed_version(root: Path | str | None = None) -> str:
    """La versión que lleva puesta este árbol, o cadena vacía si no se sabe.

    Vacía es un caso normal, no un fallo: un dispositivo instalado antes de que
    existiera este aviso no tiene `VERSION`, y lo que corresponde es tratarlo
    como más viejo que cualquier release y ofrecerle la actualización.

    El `root` se puede pasar porque `tests/_harness.sandbox()` NO reengancha
    `model.APP_DIR`, y porque el instalador pregunta por el árbol que lleva
    dentro, que no es el del dispositivo."""
    base = Path(root) if root is not None else model.APP_DIR
    try:
        return (base / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def parse_version(texto: str) -> tuple[int, ...]:
    """'v0.0.10' -> (0, 0, 10). Tolerante porque compara, no valida.

    Lo que no sea un número cuenta como 0 en vez de reventar: un tag raro tiene
    que dar «no hay nada nuevo», nunca una excepción en mitad del arranque."""
    limpio = texto.strip().lstrip("vV")
    partes: list[int] = []
    for trozo in limpio.split("."):
        digitos = ""
        for ch in trozo:
            if not ch.isdigit():
                break
            digitos += ch
        partes.append(int(digitos) if digitos else 0)
    return tuple(partes) or (0,)


def is_newer(nueva: str, actual: str) -> bool:
    """¿`nueva` es posterior a `actual`?

    Se comparan tuplas de enteros y no cadenas, que es lo que hace que 0.0.10
    vaya después de 0.0.9. Sin versión actual, cualquier cosa es más nueva."""
    if not nueva:
        return False
    if not actual:
        return True
    a, b = parse_version(nueva), parse_version(actual)
    largo = max(len(a), len(b))
    return a + (0,) * (largo - len(a)) > b + (0,) * (largo - len(b))


# ---------------------------------------------------------------------------
# La caché: lo último que se supo
# ---------------------------------------------------------------------------

def state_file() -> Path:
    """Lo último que contestó GitHub, para no preguntárselo en cada apertura.

    Función y no constante, igual que `catalog.cache_toml()`: los tests
    reenganchan `model.STATE_DIR` en caliente y una constante calculada al
    importar se quedaría apuntando al dispositivo de verdad."""
    return model.STATE_DIR / "update.json"


def _leer_cache() -> tuple[Release | None, float | None]:
    """La release guardada y cuántos segundos hace que se miró.

    Leer nunca es un error: cualquier cosa rara es «aquí no hay nada»."""
    data = store.read_json(state_file())
    tag = str(data.get("tag") or "")
    if not tag:
        return None, None
    rel = Release(tag=tag,
                  version=str(data.get("version") or "").strip(),
                  name=str(data.get("name") or tag),
                  url=str(data.get("url") or PAGINA),
                  published=str(data.get("published") or ""),
                  notes=str(data.get("notes") or ""))
    try:
        visto = datetime.strptime(str(data["checked"]), "%Y-%m-%d %H:%M:%S")
        edad = (datetime.now() - visto).total_seconds()
    except (KeyError, TypeError, ValueError):
        edad = None
    return rel, edad


def _escribir_cache(rel: Release) -> None:
    """Guardar es best-effort: que falle no puede estropear una comprobación.

    El dispositivo puede estar de solo lectura o haberse extraído a media frase,
    y esto es una comodidad, no un dato imprescindible."""
    try:
        state_file().parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return                      # write_json no crea el directorio padre
    store.write_json(state_file(), {"checked": store.stamp(),
                                    "tag": rel.tag,
                                    "version": rel.version,
                                    "name": rel.name,
                                    "url": rel.url,
                                    "published": rel.published,
                                    "notes": rel.notes})


# ---------------------------------------------------------------------------
# La red
# ---------------------------------------------------------------------------

def fetch(url: str, timeout: int) -> bytes:
    """La única puerta de salida a la red de todo el módulo.

    Función de módulo a propósito: los tests la sustituyen entera
    (`update.fetch = ...`) y así ninguno habla con GitHub. Devuelve bytes y no
    un flujo porque lo más grande que pasa por aquí son los ~270 KB del zip del
    código: no compensa complicar el punto que hay que poder sustituir."""
    peticion = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(peticion, timeout=timeout) as resp:
        return resp.read()


def _parse_release(crudo: dict) -> Release:
    tag = str(crudo.get("tag_name") or "").strip()
    if not tag:
        raise ValueError("la respuesta de GitHub no trae tag_name")
    notas = str(crudo.get("body") or "").strip()
    return Release(tag=tag,
                   version=tag.lstrip("vV"),
                   name=str(crudo.get("name") or tag).strip() or tag,
                   url=str(crudo.get("html_url") or PAGINA),
                   published=str(crudo.get("published_at") or ""),
                   notes=notas[:NOTAS_MAX])


def check(force: bool = False) -> tuple[Release | None, str | None]:
    """La última release, y si algo no ha ido bien, qué decirle al usuario.

    Nunca lanza, igual que `catalog.load()`: esto lo llama un hilo detrás de una
    ventana ya abierta, y ahí un fallo de red no es un error del programa. Con
    una comprobación de hace menos de `CACHE_HORAS` no se toca la red siquiera;
    `force=True` es el botón de «buscar ahora»."""
    copia, edad = _leer_cache()
    if not force and copia is not None and edad is not None \
            and 0 <= edad < CACHE_HORAS * 3600:
        return copia, None

    try:
        rel = _parse_release(json.loads(fetch(API_LATEST, TIMEOUT_API)))
    except (OSError, ValueError, TypeError, KeyError) as e:
        motivo = f"No he podido preguntarle a GitHub si hay versión nueva: {e}"
        if copia is not None:
            return copia, f"{motivo}\nSe enseña lo último que se supo."
        return None, motivo

    _escribir_cache(rel)
    return rel, None


def pending(root: Path | str | None = None) -> Release | None:
    """¿Hay algo más nuevo que lo instalado? Solo caché, JAMÁS red.

    Es lo que pregunta la ventana en su primer pintado, así que tiene que
    contestar sin pensárselo. Quien refresca la caché es el hilo de `check()`."""
    copia, _ = _leer_cache()
    if copia is None:
        return None
    return copia if is_newer(copia.version, installed_version(root)) else None


# ---------------------------------------------------------------------------
# Traerse el código
# ---------------------------------------------------------------------------

def _ruta_segura(nombre: str) -> str | None:
    """La ruta relativa de un miembro del zip, o None si pretende escaparse.

    Un zip es contenido ajeno aunque venga de nuestro propio repositorio, y
    `extractall()` es el clásico: basta un miembro `../../x` para escribir fuera
    del destino. Se comprueba sobre el nombre, sin tocar el disco."""
    limpio = nombre.replace("\\", "/").strip()
    if not limpio or limpio.startswith("/"):
        return None
    partes = PurePosixPath(limpio).parts
    if any(p in ("..", "") for p in partes):
        return None
    if ":" in partes[0]:                     # 'C:/...' en un zip de Windows
        return None
    return limpio


def _extraer(zf: zipfile.ZipFile, destino: Path) -> None:
    """Vuelca el zip en `destino` quitando el directorio raíz que mete GitHub.

    El zip de un tag viene envuelto en una carpeta con la versión dentro
    (`prdrive-0.0.2/`), y lo que hace falta es su contenido a pelo."""
    raices = {n.replace("\\", "/").split("/", 1)[0]
              for n in zf.namelist() if n.strip()}
    if len(raices) != 1:
        raise UpdateError("El zip descargado no tiene la forma esperada: "
                          f"trae {len(raices)} carpetas en la raíz y debería "
                          "traer una.")
    raiz = raices.pop()

    for info in zf.infolist():
        seguro = _ruta_segura(info.filename)
        if seguro is None:
            raise UpdateError(f"El zip descargado trae una ruta que se sale de "
                              f"su carpeta ({info.filename!r}). No se ha "
                              f"extraído nada.")
        rel = seguro[len(raiz):].lstrip("/")
        if not rel:
            continue
        objetivo = destino / rel
        if info.is_dir():
            objetivo.mkdir(parents=True, exist_ok=True)
            continue
        objetivo.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info) as src, open(objetivo, "wb") as dst:
            shutil.copyfileobj(src, dst)


def _verificar(arbol: Path, tag: str) -> None:
    """Que lo extraído sea este proyecto, entero y de la versión pedida."""
    faltan = [n for n in OBLIGATORIOS if not (arbol / n).exists()]
    if faltan:
        raise UpdateError("Lo descargado no parece el código de "
                          f"{APP_NAME}: faltan {', '.join(faltan)}.")
    dentro = installed_version(arbol)
    if dentro != tag.lstrip("vV"):
        raise UpdateError(f"El código descargado dice ser la versión {dentro!r} "
                          f"y se pidió el tag {tag}. No se ha tocado nada.")


def download(tag: str, destino: Path | str, progreso: Progreso | None = None) -> Path:
    """Baja el código del tag, lo verifica y lo deja en `destino`. Devuelve `destino`.

    El destino se recibe y no se deduce: esto se descarga en el temporal del
    equipo, nunca en el dispositivo, tanto por no gastarle ciclos de escritura
    como para que un test pueda dirigirlo a donde quiera."""
    def decir(msg: str) -> None:
        if progreso:
            progreso(msg)

    raiz = Path(destino)
    url = ZIP_URL.format(tag=tag)
    decir(f"Descargando {url}")
    try:
        datos = fetch(url, TIMEOUT_ZIP)
    except OSError as e:
        raise UpdateError(f"No he podido descargar {url}: {e}\n"
                          f"Puedes bajarte el instalador a mano desde "
                          f"{PAGINA}.") from e

    decir(f"Descargados {len(datos) / 1024:.0f} KB; comprobando")
    try:
        with zipfile.ZipFile(io.BytesIO(datos)) as zf:
            dañado = zf.testzip()
            if dañado is not None:
                raise UpdateError(f"El zip descargado está dañado ({dañado}). "
                                  f"No se ha extraído nada.")
            raiz.mkdir(parents=True, exist_ok=True)
            _extraer(zf, raiz)
    except zipfile.BadZipFile as e:
        raise UpdateError(f"Lo descargado de {url} no es un zip válido: {e}") from e

    _verificar(raiz, tag)
    decir(f"Código de la {tag} listo en {raiz}")
    return raiz


def apply_command(staged: Path | str, device_root: Path | str) -> list[str]:
    """La orden que instala lo descargado, que se ejecuta DESDE lo descargado.

    `sys.executable` porque bajo la ventana es `pythonw.exe` y así no parpadea
    ninguna consola. `-u` porque `output_window` lee línea a línea, en el
    proyecto nadie hace `flush()`, y sin esto las líneas llegarían todas de
    golpe al terminar."""
    return [sys.executable, "-u",
            str(Path(staged) / "prdrive-install.py"),
            "--update", str(device_root)]


def relaunch_command() -> list[str]:
    """Cómo volver a abrir la ventana con el código nuevo ya puesto.

    Hay que reabrir sí o sí: el proceso que actualiza tiene cargados en memoria
    los módulos viejos. Se resuelve `pythonw.exe` igual que en
    `runsync.spawn_daemon`, para no dejar una consola detrás."""
    exe = sys.executable
    if os.name == "nt":
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        if pythonw.exists():
            exe = str(pythonw)
    return [exe, str(model.APP_DIR / "runsync.py")]
