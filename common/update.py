#!/usr/bin/env python3
"""Si hay una versión nueva en GitHub, y cómo traérsela.

Aquí no se copia nada al dispositivo: este módulo mira, compara, descarga y
verifica, y quien escribe es `install/deploy.py`, ejecutado desde el zip recién
descargado (`prdrive-install.py --update`). La separación tiene dos motivos:
- `install/` NO viaja al dispositivo (a propósito, ver `deploy.DEPLOY_FILES`),
  así que el código de a bordo no puede llamar a `deploy_code()`. El zip sí lo
  trae, y así la versión nueva se instala a sí misma.
- Si el aplicador viviera aquí habría una segunda copia del manifiesto de qué
  es el árbol desplegado, y sería la que se quedaría atrás el día que se añada
  un fichero.

Tres reglas, y las tres vienen de que esto lo llama una ventana:
- Mirar nunca es un error: `check()` devuelve `(release, motivo)` y no lanza;
  sin red se enseña lo último que se supo y, si no se supo nada, nada (como
  `catalog.load()`).
- La ventana no espera a la red: `pending()` lee solo la caché y es lo que se
  pregunta al pintar; la consulta de verdad va en un hilo aparte.
- `fetch()` es una función de módulo a propósito y el único sitio por el que
  sale una petición: los tests la sustituyen entera y ninguno toca la red.

Lo que respalda una descarga es TLS con validación de certificado, el CRC del
zip, la lista de ficheros obligatorios y que el `VERSION` de dentro cuadre con
el tag pedido. No hay firma: el repositorio es público y esto es lo que hay.
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

REPO = "Jeremaya25/prdrive"
"""Repositorio del proyecto, de donde sale este mismo programa.

No es un ajuste, por eso está aquí y no en la configuración.
"""
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
"""URL de la API de GitHub con la última release."""
PAGINA = f"https://github.com/{REPO}/releases"
"""Página de releases, para el botón «Ver la página»."""

ZIP_URL = "https://codeload.github.com/" + REPO + "/zip/refs/tags/{tag}"
"""Plantilla de la URL del zip del código de un tag.

Se pide a `codeload` y no al `zipball_url` de la API para no depender de una
redirección más ni de la cuota de la API.
"""

USER_AGENT = f"{APP_NAME}-update (+https://github.com/{REPO})"
"""`User-Agent` de las peticiones a GitHub.

La API responde 403 a una petición sin él (comprobado). `urllib` pone
`Python-urllib/3.x` por su cuenta y con eso ya contesta, pero se manda uno
propio para que en los registros de GitHub se vea quién pregunta.
"""

TIMEOUT_API = 8  # segundos: la ventana no puede esperar más
TIMEOUT_ZIP = 60  # segundos: aquí sí se espera por ancho de banda
CACHE_HORAS = 24  # horas entre consultas a GitHub
NOTAS_MAX = 4000  # caracteres de las notas de la release que se guardan

OBLIGATORIOS = ("VERSION", "sync.py", "runsync.py", "penwatch.py",
                "prdrive-install.py", "common/model.py", "ui/tk.py",
                "install/deploy.py")
"""Ficheros que tiene que traer el zip para que se le deje tocar el dispositivo.

No es la lista de lo que se copia (esa la manda `deploy.DEPLOY_FILES`): es la
comprobación de que lo descargado es este proyecto y está entero.
"""

Progreso = Callable[[str], None]
"""Función que recibe cada mensaje de avance de una descarga."""


class UpdateError(Exception):
    """Algo ha impedido actualizar y se puede contar.

    Es excepción y no `sys.exit`, como `InstallError` y `ConfigError`: esto
    corre con una ventana abierta, y matar el proceso ahí sería cerrársela al
    usuario en la cara en vez de dejarle leer qué ha pasado.
    """


class Release(NamedTuple):
    """Una release de GitHub, con lo poco que hace falta de ella.

    Args:
        tag: Tal como lo publica GitHub, p. ej. `v0.0.2`.
        version: La versión sin la `v`, que es lo que se compara.
        name: El título de la release.
        url: La página, para el botón «Ver la página».
        published: La fecha ISO que devuelve la API.
        notes: El cuerpo, para enseñarlo en la pantalla.
    """
    tag: str
    version: str
    name: str
    url: str
    published: str
    notes: str = ""


def installed_version(root: Path | str | None = None) -> str:
    """Devuelve la versión que lleva puesta este árbol.

    Una cadena vacía es un caso normal y no un fallo: un dispositivo instalado
    antes de que existiera este aviso no tiene `VERSION`, y lo que corresponde
    es tratarlo como más viejo que cualquier release y ofrecerle la
    actualización.

    Args:
        root: Árbol a mirar, para los tests (`tests/_harness.sandbox()` NO
            reengancha `model.APP_DIR`) y para el instalador, que pregunta por
            el árbol que lleva dentro y no por el del dispositivo.
    """
    base = Path(root) if root is not None else model.APP_DIR
    try:
        return (base / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def parse_version(texto: str) -> tuple[int, ...]:
    """Convierte `v0.0.10` en `(0, 0, 10)`.

    Es tolerante porque compara, no valida: lo que no sea un número cuenta como
    0 en vez de reventar, y un tag raro tiene que dar «no hay nada nuevo»,
    nunca una excepción en mitad del arranque.
    """
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
    """Indica si `nueva` es posterior a `actual`.

    Se comparan tuplas de enteros y no cadenas, que es lo que hace que 0.0.10
    vaya después de 0.0.9. Sin versión actual, cualquier cosa es más nueva.
    """
    if not nueva:
        return False
    if not actual:
        return True
    a, b = parse_version(nueva), parse_version(actual)
    largo = max(len(a), len(b))
    return a + (0,) * (largo - len(a)) > b + (0,) * (largo - len(b))


def state_file() -> Path:
    """Devuelve la ruta de lo último que contestó GitHub (`state/update.json`).

    Es función y no constante, como `catalog.cache_toml()`: los tests
    reenganchan `model.STATE_DIR` en caliente.
    """
    return model.STATE_DIR / "update.json"


def _leer_cache(cache: Path | None = None) -> tuple[Release | None, float | None]:
    """Devuelve la release guardada y cuántos segundos hace que se miró.

    Leer nunca es un error: cualquier cosa rara es «aquí no hay nada».

    Args:
        cache: Fichero de caché, para quien no vive en un dispositivo (el
            agente residente la guarda en su carpeta del equipo).
    """
    data = store.read_json(cache if cache is not None else state_file())
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


def _escribir_cache(rel: Release, cache: Path | None = None) -> None:
    """Guarda la release en la caché; si falla no pasa nada.

    El dispositivo puede estar de solo lectura o haberse extraído a media
    frase, y esto es una comodidad y no un dato imprescindible.
    """
    destino = cache if cache is not None else state_file()
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return  # `write_json` no crea el directorio padre
    store.write_json(destino, {"checked": store.stamp(),
                                    "tag": rel.tag,
                                    "version": rel.version,
                                    "name": rel.name,
                                    "url": rel.url,
                                    "published": rel.published,
                                    "notes": rel.notes})


def fetch(url: str, timeout: int) -> bytes:
    """Descarga una URL; es la única puerta de salida a la red del módulo.

    Es función de módulo a propósito: los tests la sustituyen entera
    (`update.fetch = ...`) y así ninguno habla con GitHub. Devuelve bytes y no
    un flujo porque lo más grande que pasa por aquí son los ~270 KB del zip del
    código: no compensa complicar el punto que hay que poder sustituir.
    """
    peticion = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(peticion, timeout=timeout) as resp:
        return resp.read()


def _parse_release(crudo: dict) -> Release:
    """Convierte la respuesta de la API en una `Release`.

    Raises:
        ValueError: Si no trae `tag_name`.
    """
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


def check(force: bool = False,
          cache: Path | None = None) -> tuple[Release | None, str | None]:
    """Devuelve la última release y, si algo no ha ido bien, qué decirle al usuario.

    Nunca lanza, como `catalog.load()`: lo llama un hilo detrás de una ventana
    ya abierta, y ahí un fallo de red no es un error del programa. Con una
    comprobación de hace menos de `CACHE_HORAS` ni siquiera se toca la red.

    Args:
        force: El botón «buscar ahora»: ignora la caché.
        cache: Fichero de caché alternativo.
    """
    copia, edad = _leer_cache(cache)
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

    _escribir_cache(rel, cache)
    return rel, None


def pending(root: Path | str | None = None,
            cache: Path | None = None) -> Release | None:
    """Devuelve la release si es más nueva que lo instalado. Solo caché, JAMÁS red.

    Es lo que pregunta la ventana en su primer pintado, así que tiene que
    contestar sin pensárselo; quien refresca la caché es el hilo de `check()`.
    """
    copia, _ = _leer_cache(cache)
    if copia is None:
        return None
    return copia if is_newer(copia.version, installed_version(root)) else None


def _ruta_segura(nombre: str) -> str | None:
    """Devuelve la ruta relativa de un miembro del zip, o `None` si pretende escaparse.

    Un zip es contenido ajeno aunque venga de nuestro propio repositorio, y
    `extractall()` es el clásico: basta un miembro `../../x` para escribir
    fuera del destino. Se comprueba sobre el nombre, sin tocar el disco.
    """
    limpio = nombre.replace("\\", "/").strip()
    if not limpio or limpio.startswith("/"):
        return None
    partes = PurePosixPath(limpio).parts
    if any(p in ("..", "") for p in partes):
        return None
    if ":" in partes[0]:  # `C:/...` en un zip de Windows
        return None
    return limpio


def _extraer(zf: zipfile.ZipFile, destino: Path) -> None:
    """Vuelca el zip en `destino` quitando el directorio raíz que mete GitHub.

    El zip de un tag viene envuelto en una carpeta con la versión dentro
    (`prdrive-0.0.2/`) y lo que hace falta es su contenido a pelo.

    Raises:
        UpdateError: Si no tiene una sola carpeta en la raíz o algún miembro se
            sale de ella; en ese caso no se extrae nada.
    """
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
    """Comprueba que lo extraído es este proyecto, entero y de la versión pedida.

    Raises:
        UpdateError: Si faltan ficheros obligatorios o el `VERSION` de dentro
            no es el del tag.
    """
    faltan = [n for n in OBLIGATORIOS if not (arbol / n).exists()]
    if faltan:
        raise UpdateError("Lo descargado no parece el código de "
                          f"{APP_NAME}: faltan {', '.join(faltan)}.")
    dentro = installed_version(arbol)
    if dentro != tag.lstrip("vV"):
        raise UpdateError(f"El código descargado dice ser la versión {dentro!r} "
                          f"y se pidió el tag {tag}. No se ha tocado nada.")


def download(tag: str, destino: Path | str, progreso: Progreso | None = None) -> Path:
    """Baja el código del tag, lo verifica y lo deja en `destino`.

    El destino se recibe y no se deduce: se descarga en el temporal del equipo
    y nunca en el dispositivo, tanto por no gastarle ciclos de escritura como
    para que un test pueda dirigirlo adonde quiera.

    Args:
        tag: Tag a descargar.
        destino: Carpeta donde dejar el código.
        progreso: Recibe cada mensaje de avance.

    Returns:
        `destino`.

    Raises:
        UpdateError: Si no se puede descargar, el zip está dañado o lo
            descargado no es este proyecto.
    """
    def decir(msg: str) -> None:
        """Pasa un mensaje a `progreso`, si lo hay."""
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


def apply_command(staged: Path | str, device_root: Path | str,
                  python: str | None = None) -> list[str]:
    """Devuelve la orden que instala lo descargado, que se ejecuta DESDE lo descargado.

    Usa `sys.executable` porque bajo la ventana es `pythonw.exe` y así no
    parpadea ninguna consola. Lleva `-u` porque `output_window` lee línea a
    línea, nadie hace `flush()` en el proyecto y sin esto las líneas llegarían
    todas de golpe al terminar.

    Args:
        staged: Carpeta con el código descargado.
        device_root: Raíz que se actualiza.
        python: El Python del agente, cuando es él quien la actualiza
            (`agente.py actualizar-raiz`).
    """
    return [python or sys.executable, "-u",
            str(Path(staged) / "prdrive-install.py"),
            "--update", str(device_root)]


def source_tag(root: Path | str | None = None) -> str:
    """Devuelve el tag del código que lleva puesto este árbol, o `''` si no se sabe.

    Es lo que hay que descargar para poner al día los COMPONENTES, y no el tag
    de la última release: los pines (`common/pins.py`) viajan con el programa,
    así que la maquinaria que sabe bajar y comprobar rclone y Python es la de
    esta misma versión. La de otra fijaría otras versiones, que no son las que
    este dispositivo espera.
    """
    version = installed_version(root)
    return f"v{version}" if version else ""


CODIGO_RELEVO = 3
"""Código de salida de `--update-components --relevo`.

Significa que ha dejado en marcha el proceso que cambiará el Python de la
ventana en cuanto esta se cierre; la ventana lo lee y se cierra sola. No es 0
ni 1, que ya significan otra cosa.
"""


def components_command(staged: Path | str, device_root: Path | str,
                       relevo: int | None = None) -> list[str]:
    """Devuelve la orden que pone al día los componentes, ejecutada DESDE lo descargado.

    Es la hermana de `apply_command()` y por el mismo motivo: `install/` no
    está en el dispositivo y quien sabe bajar y comprobar rclone y Python es el
    instalador. Aquella cambia el CÓDIGO y deja los componentes; esta cambia
    los componentes y no toca el código. Usa `sys.executable` a propósito: si
    el dispositivo lleva su Python, este ES el suyo, y así
    `install/components.py` reconoce que ese runtime está en uso mirando su
    propio intérprete. El `-u` es el de siempre.

    Args:
        staged: Carpeta con el código descargado.
        device_root: Volumen del dispositivo.
        relevo: Pid de la ventana; solo se pasa cuando uno de los pendientes es
            el Python desde el que está abierta (`components.propio()`). Con
            él, el aplicador deja preparado quién lo cambie después de que se
            cierre y sale con `CODIGO_RELEVO`.
    """
    orden = [sys.executable, "-u",
             str(Path(staged) / "prdrive-install.py"),
             "--update-components", str(device_root)]
    if relevo is not None:
        orden += ["--relevo", str(relevo)]
    return orden


def agent_command(staged: Path | str, python: str | None = None) -> list[str]:
    """Devuelve la orden que pone al día el agente residente.

    Ejecutada DESDE lo descargado.

    Como `apply_command()`: la versión nueva se instala a sí misma.

    Args:
        python: El Python del agente, que es quien la lanza (`agente.py
            actualizar`).
    """
    return [python or sys.executable, "-u",
            str(Path(staged) / "prdrive-install.py"), "--update-agente"]


def relaunch_command() -> list[str]:
    """Devuelve cómo volver a abrir la ventana con el código nuevo ya puesto.

    Hay que reabrir sí o sí: el proceso que actualiza tiene cargados en memoria
    los módulos viejos. Se resuelve `pythonw.exe` igual que en
    `runsync.spawn_daemon` para no dejar una consola detrás.
    """
    exe = sys.executable
    if os.name == "nt":
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        if pythonw.exists():
            exe = str(pythonw)
    return [exe, str(model.APP_DIR / "runsync.py")]
