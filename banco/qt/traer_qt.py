#!/usr/bin/env python3
"""Baja de PyPI PySide6-Essentials y shiboken6 (6.12.0) de una plataforma y los poda.

Es del banco de la interfaz (temporal, ver `banco/LEEME.md`). Solo biblioteca estándar
(urllib, zipfile, hashlib): corre con cualquier Python 3.11+, también el de `setup-python`.

Uso: python banco/qt/traer_qt.py PLATAFORMA DESTINO [--cache DIR]

PLATAFORMA es `windows-x64`, `windows-arm64` o `linux-x64`. Pide a la API JSON de PyPI
(https://pypi.org/pypi/<paquete>/6.12.0/json) el wheel de esa plataforma, lo baja,
comprueba su tamaño y su sha256 contra ese JSON y saca de él, sin ejecutar nada, solo
la lista blanca de abajo (QtCore, QtGui, QtWidgets, el plugin de plataforma y lo que
necesitan para cargar). En DESTINO quedan `PySide6/` y `shiboken6/`, listos para ponerse
en `sys.path`. Todo lo demás del wheel (QtQml, Quick, Designer, Svg, Network, las
herramientas, las traducciones salvo es, opengl32sw.dll...) se queda fuera.

Con `--cache DIR` los wheels se guardan (y se reusan si el sha256 cuadra) en DIR; sin
ello van a una carpeta temporal que se borra al terminar.

Imprime los tamaños (cada wheel, lo podado en disco y el número de ficheros) y, al
final, una línea `TRAER_QT {json}` con lo mismo.
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import shutil
import stat
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

VERSION = "6.12.0"
PAQUETES = ("PySide6-Essentials", "shiboken6")
"""Nunca el metapaquete `PySide6`: arrastra Addons, WebEngine y Pdf (cientos de MB)."""
ETIQUETAS = {"windows-x64": "win_amd64", "windows-arm64": "win_arm64",
             "linux-x64": "manylinux_2_34_x86_64"}
API = "https://pypi.org/pypi/{paquete}/{version}/json"

COMUN = [
    "PySide6/__init__.py", "PySide6/_config.py", "PySide6/_git_pyside_version.py",
    "shiboken6/__init__.py", "shiboken6/_config.py", "shiboken6/_git_shiboken_module_version.py",
]
LINUX = COMUN + [
    "PySide6/QtCore.abi3.so", "PySide6/QtGui.abi3.so", "PySide6/QtWidgets.abi3.so",
    "PySide6/libpyside6.abi3.so.6.*", "shiboken6/Shiboken.abi3.so", "shiboken6/libshiboken6.abi3.so.6.*",
    "PySide6/Qt/lib/libQt6Core.so.6", "PySide6/Qt/lib/libQt6Gui.so.6", "PySide6/Qt/lib/libQt6Widgets.so.6",
    "PySide6/Qt/lib/libQt6DBus.so.6", "PySide6/Qt/lib/libQt6XcbQpa.so.6",
    "PySide6/Qt/lib/libQt6WaylandClient.so.6", "PySide6/Qt/lib/libicu*.so.*",
    "PySide6/Qt/plugins/platforms/libqxcb.so", "PySide6/Qt/plugins/platforms/libqwayland.so",
    "PySide6/Qt/plugins/platforms/libqoffscreen.so",
    "PySide6/Qt/plugins/xcbglintegrations/*.so",
    "PySide6/Qt/plugins/wayland-shell-integration/libxdg-shell.so",
    "PySide6/Qt/plugins/wayland-graphics-integration-client/libshm-emulation-server.so",
    "PySide6/Qt/plugins/wayland-decoration-client/libbradient.so",
    "PySide6/Qt/plugins/platforminputcontexts/libcompose*.so",
    "PySide6/Qt/plugins/platforminputcontexts/libibus*.so",
    "PySide6/Qt/plugins/platformthemes/libqxdgdesktopportal.so",
    "PySide6/Qt/translations/qtbase_es.qm", "PySide6/Qt/translations/qt_es.qm",
]
WINDOWS = COMUN + [
    "PySide6/QtCore.pyd", "PySide6/QtGui.pyd", "PySide6/QtWidgets.pyd", "PySide6/pyside6.abi3.dll",
    "shiboken6/Shiboken.pyd", "shiboken6/shiboken6.abi3.dll",
    "PySide6/Qt6Core.dll", "PySide6/Qt6Gui.dll", "PySide6/Qt6Widgets.dll",
    "PySide6/msvcp140.dll", "PySide6/msvcp140_1.dll", "PySide6/msvcp140_2.dll",
    "PySide6/vcruntime140.dll", "PySide6/vcruntime140_1.dll",
    # shiboken6.abi3.dll busca su msvcp140/vcruntime140 en su propia carpeta: el wheel los trae
    # también ahí, y sin ellos dependería de que el equipo tenga instalado el redistribuible.
    "shiboken6/msvcp140.dll", "shiboken6/vcruntime140.dll", "shiboken6/vcruntime140_1.dll",
    "PySide6/plugins/platforms/qwindows.dll", "PySide6/plugins/platforms/qoffscreen.dll",
    "PySide6/plugins/styles/qmodernwindowsstyle.dll",
    "PySide6/translations/qtbase_es.qm", "PySide6/translations/qt_es.qm",
]
LISTAS = {"linux-x64": LINUX, "windows-x64": WINDOWS, "windows-arm64": WINDOWS}
OPCIONALES = {"windows-arm64": {"PySide6/vcruntime140_1.dll", "shiboken6/vcruntime140_1.dll"}}
"""Lo que el wheel de esa plataforma no trae: en ARM64 `vcruntime140_1.dll` no existe."""


class Fallo(Exception):
    """Un error que se cuenta en una línea, sin traza."""


def mb(n: int | float) -> str:
    return f"{n / 1e6:.1f} MB"


def abrir(url: str, intentos: int = 4):
    """Abre una URL con reintentos (red inestable de las máquinas de CI)."""
    peticion = urllib.request.Request(url, headers={"User-Agent": "prdrive-banco/1"})
    for n in range(1, intentos + 1):
        try:
            return urllib.request.urlopen(peticion, timeout=90)
        except urllib.error.HTTPError as e:
            if e.code < 500 and e.code != 429:
                raise Fallo(f"{url}: HTTP {e.code}") from e
            err = e
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            err = e
        if n == intentos:
            raise Fallo(f"{url}: {err}") from err
        espera = 2 ** n
        print(f"  reintento {n}/{intentos - 1} en {espera} s ({err})", file=sys.stderr, flush=True)
        time.sleep(espera)


def descripcion(paquete: str, etiqueta: str) -> dict:
    """Pide a PyPI el fichero de esa plataforma: nombre, URL, tamaño y sha256."""
    with abrir(API.format(paquete=paquete, version=VERSION)) as r:
        meta = json.load(r)
    if meta.get("info", {}).get("version") != VERSION:
        raise Fallo(f"{paquete}: PyPI contesta la versión {meta.get('info', {}).get('version')}")
    candidatos = [f for f in meta.get("urls", [])
                  if f.get("packagetype") == "bdist_wheel" and f["filename"].endswith(f"-{etiqueta}.whl")]
    if len(candidatos) != 1:
        raise Fallo(f"{paquete} {VERSION}: {len(candidatos)} wheels para {etiqueta} (se esperaba 1)")
    f = candidatos[0]
    if f.get("yanked"):
        raise Fallo(f"{f['filename']}: retirado de PyPI (yanked)")
    return {"paquete": paquete, "fichero": f["filename"], "url": f["url"], "tamano": int(f["size"]),
            "sha256": f["digests"]["sha256"].lower()}


def sha256_de(ruta: Path) -> str:
    h = hashlib.sha256()
    with ruta.open("rb") as f:
        for trozo in iter(lambda: f.read(1 << 20), b""):
            h.update(trozo)
    return h.hexdigest()


def conseguir(d: dict, carpeta: Path) -> tuple[Path, str]:
    """Deja el wheel en `carpeta` con el tamaño y el sha256 de PyPI; devuelve (ruta, de dónde)."""
    ruta = carpeta / d["fichero"]
    if ruta.is_file() and ruta.stat().st_size == d["tamano"] and sha256_de(ruta) == d["sha256"]:
        return ruta, "caché"
    parcial = ruta.with_name(ruta.name + ".part")
    print(f"  bajando {d['fichero']} ({mb(d['tamano'])})", flush=True)
    h = hashlib.sha256()
    total = 0
    with abrir(d["url"]) as r, parcial.open("wb") as f:
        for trozo in iter(lambda: r.read(1 << 20), b""):
            h.update(trozo)
            total += len(trozo)
            f.write(trozo)
    if total != d["tamano"]:
        parcial.unlink(missing_ok=True)
        raise Fallo(f"{d['fichero']}: llegaron {total} bytes y PyPI dice {d['tamano']}")
    if h.hexdigest() != d["sha256"]:
        parcial.unlink(missing_ok=True)
        raise Fallo(f"{d['fichero']}: sha256 {h.hexdigest()} y PyPI dice {d['sha256']}")
    os.replace(parcial, ruta)
    return ruta, "descargado"


def seguro(nombre: str) -> bool:
    """Un nombre de miembro del zip que no se sale de la carpeta de destino."""
    partes = nombre.split("/")
    return not (nombre.startswith("/") or "\\" in nombre or ".." in partes or ":" in partes[0])


def podar(ruedas: list[Path], plataforma: str, destino: Path) -> dict:
    """Extrae de los wheels solo lo de la lista blanca; falla si falta algo que debería estar."""
    patrones = LISTAS[plataforma]
    pendientes = {p for p in patrones if p not in OPCIONALES.get(plataforma, set())}
    ficheros = 0
    comprimidos = 0
    for rueda in sorted(ruedas):
        with zipfile.ZipFile(rueda) as z:
            for info in z.infolist():
                if info.is_dir() or not any(fnmatch.fnmatchcase(info.filename, p) for p in patrones):
                    continue
                if not seguro(info.filename):
                    raise Fallo(f"{rueda.name}: nombre sospechoso {info.filename!r}")
                pendientes = {p for p in pendientes if not fnmatch.fnmatchcase(info.filename, p)}
                salida = destino / info.filename
                salida.parent.mkdir(parents=True, exist_ok=True)
                with z.open(info) as origen, salida.open("wb") as f:
                    shutil.copyfileobj(origen, f)
                modo = (info.external_attr >> 16) & 0o777
                if modo and os.name != "nt":                # respeta el bit de ejecución del zip
                    os.chmod(salida, modo | stat.S_IRUSR | stat.S_IWUSR)
                ficheros += 1
                comprimidos += info.compress_size
    if pendientes:
        raise Fallo("el wheel no trae: " + ", ".join(sorted(pendientes)))
    return {"ficheros": ficheros, "comprimidos": comprimidos}


def medir(destino: Path) -> tuple[int, int]:
    """(ficheros, bytes) de PySide6/ y shiboken6/ en disco."""
    n = b = 0
    for sub in ("PySide6", "shiboken6"):
        for carpeta, _dirs, nombres in os.walk(destino / sub):
            for nombre in nombres:
                n += 1
                b += (Path(carpeta) / nombre).stat().st_size
    return n, b


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("plataforma", choices=sorted(ETIQUETAS))
    ap.add_argument("destino")
    ap.add_argument("--cache", help="carpeta donde guardar (y reusar) los wheels")
    a = ap.parse_args()
    destino = Path(a.destino).resolve()
    destino.mkdir(parents=True, exist_ok=True)
    for sub in ("PySide6", "shiboken6"):
        if (destino / sub).exists():
            shutil.rmtree(destino / sub)

    temporal = None
    if a.cache:
        carpeta = Path(a.cache).resolve()
        carpeta.mkdir(parents=True, exist_ok=True)
    else:
        temporal = tempfile.mkdtemp(prefix="traer-qt-")
        carpeta = Path(temporal)
    try:
        print(f"== Qt {VERSION} para {a.plataforma} ({ETIQUETAS[a.plataforma]})", flush=True)
        ruedas, resumen = [], []
        for paquete in PAQUETES:
            d = descripcion(paquete, ETIQUETAS[a.plataforma])
            ruta, origen = conseguir(d, carpeta)
            ruedas.append(ruta)
            resumen.append({"fichero": d["fichero"], "bytes": d["tamano"], "sha256": d["sha256"],
                            "origen": origen})
            print(f"  {d['fichero']}: {d['tamano']:,} bytes ({mb(d['tamano'])}), sha256 {d['sha256']} "
                  f"comprobado ({origen})", flush=True)
        podado = podar(ruedas, a.plataforma, destino)
    except Fallo as e:
        print(f"traer_qt: {e}", file=sys.stderr)
        return 1
    finally:
        if temporal:
            shutil.rmtree(temporal, ignore_errors=True)

    ficheros, bytes_ = medir(destino)
    total_ruedas = sum(r["bytes"] for r in resumen)
    informe = {"plataforma": a.plataforma, "version": VERSION, "ruedas": resumen,
               "ruedas_bytes": total_ruedas, "podado_ficheros": ficheros, "podado_bytes": bytes_,
               "podado_comprimido_bytes": podado["comprimidos"]}
    (destino / "recorte.json").write_text(json.dumps(informe, indent=1), encoding="utf-8")
    print(f"  wheels: {mb(total_ruedas)}; podado en disco: {mb(bytes_)} en {ficheros} ficheros "
          f"({mb(podado['comprimidos'])} comprimidos) -> {destino}", flush=True)
    print("TRAER_QT " + json.dumps(informe), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
