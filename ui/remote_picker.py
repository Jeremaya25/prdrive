#!/usr/bin/env python3
"""Recorrer el remoto para elegir una carpeta, sin Tkinter.

Crear una pareja era teclear `remote_path` a ciegas y enterarse del error en la
primera sincronización, cuando rclone se quejaba de una ruta que no existía (o,
peor, no se quejaba y creaba una carpeta con la errata dentro). Esto es lo
mínimo para no teclear a ciegas: listar lo que hay, bajar un nivel, subir otro
y, si hace falta, crear la carpeta que falta.

Lo que se dibuja está en `ui/tk_pairs.py`; aquí vive lo que se puede probar sin
pantalla: cómo se lee la salida de `rclone lsd`, cómo se navega una ruta y qué
nombres de carpeta se admiten.

Se habla con el remoto por `catalog.run()`, el mismo punto por el que pasa el
catálogo: lleva puesto el `rclone.conf` del dispositivo, el `cwd` contra el que
ese fichero resuelve sus rutas relativas y los tiempos de espera cortos que
evitan que una wifi mala congele la ventana. Y es lo que los tests sustituyen,
así que ninguno toca la red.
"""

from __future__ import annotations

import re
import subprocess

from common import catalog, model
from common.model import ConfigError

RAIZ = "/"
"""Raíz del remoto: el techo de la navegación."""

PROHIBIDOS = set('/\\')
"""Caracteres que no puede llevar el nombre de una carpeta nueva.

La barra y la contrabarra partirían la ruta: crear `a/b` desde aquí sería crear
dos carpetas sin decirlo.
"""
RESERVADOS = {".", ".."}
"""Nombres que no son carpetas."""


def normalizar(ruta: str) -> str:
    """Devuelve una ruta del remoto como la escribe el proyecto.

    Es absoluta y sin barra final. Los `remote_path` del catálogo son absolutos
    (`/datos/notas`), así que el recorrido empieza en la raíz del remoto y no
    en el directorio por defecto del backend: son dos sitios distintos en SFTP
    y la pareja acabaría apuntando al que no es.
    """
    limpia = str(ruta or "").replace("\\", "/").strip()
    partes = [t for t in limpia.split("/") if t not in ("", ".")]
    return RAIZ + "/".join(partes)


def endpoint(remote: str, ruta: str) -> str:
    """Devuelve `remote:ruta` para esa ruta del remoto."""
    return f"{remote}:{normalizar(ruta)}"


def subir(ruta: str) -> str:
    """Devuelve el padre de la ruta; la raíz es el techo y no se sube más."""
    actual = normalizar(ruta)
    if actual == RAIZ:
        return RAIZ
    return normalizar(actual.rsplit("/", 1)[0])


def entrar(ruta: str, nombre: str) -> str:
    """Devuelve la ruta de la carpeta `nombre` dentro de `ruta`."""
    return normalizar(f"{normalizar(ruta)}/{nombre}")


def carpeta_de(ruta_de_pareja: str) -> str:
    """Devuelve por dónde abrir el explorador para una pareja que ya tiene ruta.

    Se abre en la carpeta que la contiene y no en ella misma: quien pulsa
    «Examinar…» con `/datos/notas` escrito casi siempre quiere mirar qué más
    hay en `/datos`.
    """
    return subir(ruta_de_pareja) if normalizar(ruta_de_pareja) != RAIZ else RAIZ


_LINEA = re.compile(
    r"^\s*(-?\d+)\s+\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}(?:\.\d+)?\s+(-?\d+)\s+(.+?)\s*$")
"""Una línea de `rclone lsd`: tamaño, fecha, hora, número de entradas y nombre.

Es el formato de `operations.ListDir` y de `cmd/lsd`. Se reconoce entera y no
se parte por espacios a ojo, por dos motivos: el nombre puede llevar espacios y
tiene que llegar completo, y una línea que no sea un listado no puede colarse
como si fuera una carpeta.
"""


def parse_lsd(texto: str) -> list[str]:
    """Devuelve los nombres de carpeta de la salida de `rclone lsd`.

    Lo que no cuadre se ignora en vez de romper: esta lista es para elegir una
    carpeta y una línea rara no puede tumbar el diálogo. Una línea válida es
    así:

        '          -1 2026-01-01 12:00:00        -1 documentos'
    """
    nombres = []
    for linea in texto.splitlines():
        encaje = _LINEA.match(linea)
        if encaje and encaje.group(3):
            nombres.append(encaje.group(3))
    return sorted(nombres, key=str.lower)


def listar(remote: str, ruta: str) -> list[str]:
    """Devuelve las carpetas que hay en esa ruta del remoto.

    Raises:
        ConfigError: Con lo que haya dicho rclone.
    """
    donde = endpoint(remote, ruta)
    try:
        res = catalog.run(["lsd", donde])
    except (OSError, subprocess.SubprocessError) as e:
        raise ConfigError(f"No he podido leer {donde}: {e}") from e
    if res.returncode != 0:
        raise ConfigError(f"No he podido leer {donde}:\n\n{(res.stderr or '').strip()}")
    return parse_lsd(res.stdout or "")


def validar_nombre(nombre: str) -> str:
    """Devuelve el nombre de una carpeta nueva, ya limpio.

    Raises:
        ConfigError: Si el nombre no vale.
    """
    limpio = str(nombre or "").strip()
    if not limpio:
        raise ConfigError("Escribe un nombre para la carpeta.")
    if PROHIBIDOS & set(limpio) or limpio in RESERVADOS:
        raise ConfigError("El nombre de la carpeta no puede llevar / ni \\, y no "
                          "puede ser '.' ni '..'. Para crear varios niveles, entra "
                          "en cada uno y créalos por separado.")
    return limpio


def crear(remote: str, ruta: str, nombre: str) -> str:
    """Crea una carpeta en el remoto y devuelve su ruta.

    Es lo único de este módulo que ESCRIBE en el remoto y lo hace en la única
    forma que no puede estropear nada: `mkdir` no toca lo que ya hay. Borrar
    carpetas no se ofrece a propósito: un remoto es de toda la flota y aquí no
    hay ninguna ceremonia de consecuencias que lo respalde.

    Raises:
        ConfigError: Si el nombre no vale o rclone no la ha podido crear.
    """
    limpio = validar_nombre(nombre)
    destino = entrar(ruta, limpio)
    donde = endpoint(remote, destino)
    try:
        res = catalog.run(["mkdir", donde])
    except (OSError, subprocess.SubprocessError) as e:
        raise ConfigError(f"No he podido crear {donde}: {e}") from e
    if res.returncode != 0:
        raise ConfigError(f"No he podido crear {donde}:\n\n{(res.stderr or '').strip()}")
    return destino


def remote_de(raw: dict | None, propio: str = "") -> str:
    """Devuelve contra qué remote se navega: el de la pareja o el de `[defaults]`."""
    if propio.strip():
        return propio.strip()
    defaults = dict((raw or {}).get("defaults") or {})
    return str(defaults.get("remote") or model.DEFAULT_REMOTE)
