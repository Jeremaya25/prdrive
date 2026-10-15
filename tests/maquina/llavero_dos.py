#!/usr/bin/env python3
"""El llavero entre dos dispositivos de verdad (#115 y #116): lo común de F32.

Dos «dispositivos», cada uno en su disco virtual (el primero en NTFS o ext4, el segundo en
exFAT), montados como los monta el instalador (`install/deploy`), con el rclone fijado y
contra el mismo remoto `local`. Todo lo de cada uno lo hace SU código, en su proceso, como la
ventana: «Usar esta base…» y «Traer el del remoto» (`llavero_editor.plan_activar`) y las
pasadas de `sync.py keychain`. Lo único que no es de prdrive son los guardados: los hace el
guion, con una base KDBX 4 de mentira pero entera (`kdbx.comprobar()` la da por buena y su
semilla cambia en cada guardado, como en uno de verdad), con la hora que él elige.

Los guiones de las pruebas del 12/10/2026 se perdieron con su rama: esto los escribe otra vez
a partir de los issues.
- **LL-6** (#115): A activa el llavero y pasa; B, en exFAT, lo «trae del remoto» y pasa; A
  tiene que seguir pasando bien, sin «all files were changed».
- **LL-7** (#116): B no toca nada. A guarda y pasa; B pasa; A guarda otra vez y pasa; B pasa.
  Con los dos guardados de A a menos de 2 s y a más. B no puede tener un conflicto, ni ganar
  su copia vieja.
- **Lo de la repetición** (#115): el remoto cambia de hora los dos ficheros, como hacía el
  segundo dispositivo, y a A le llega «all files were changed»: la pasada se repite una vez
  con `--force` y A sigue pasando.

Lo que se comprueba es la frontera con el sistema: la hora que guarda de verdad cada sistema
de ficheros y lo que hace rclone con ella. En Linux, sin redondeo, las mismas pasadas tienen
que ir igual de bien.
"""

from __future__ import annotations

import hashlib
import json
import os
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import comun

REPO = comun.REPO
BASE = "Pruebas.kdbx"
SALIDA_UTIL = ("File changed", "File is new", "Safety abort", "WARNING", "Renaming",
               "winner", "Updated modification", "Copied", "No changes found",
               "Bisync aborted", "Failed to bisync", "New or changed in both")
"""Lo que se enseña de cada log de rclone: lo que cuenta qué decidió bisync."""

ACTIVAR = '''
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from common import catalog, config_file
from ui import llavero_editor
raw = config_file.load_raw()
cat, _ = catalog.load(raw)
plan = llavero_editor.plan_activar(raw, cat, Path(sys.argv[2]) if sys.argv[2] else None)
print(*plan.execute(), sep="\\n")
'''
"""«Usar esta base…» (con ruta) o «Traer el del remoto» (sin ella), con el código del dispositivo."""
ESTADO = '''
import json, sys
sys.path.insert(0, sys.argv[1])
from common import llavero, model
pareja = model.load_config().pareja_llavero
donde = pareja.local_abs
leeme = donde / llavero.LEEME
print(json.dumps({
    "pendiente": llavero.pendiente(pareja), "sin_listar": llavero.sin_listar(pareja),
    "bases": {r.name: [r.stat().st_size, r.stat().st_mtime_ns] for r in llavero.bases(donde)},
    "leeme": leeme.stat().st_mtime_ns if leeme.is_file() else None,
    "leeme_fija": getattr(llavero, "LEEME_HORA", None)}))
'''
"""Lo que el dispositivo cree de su llavero: lo pendiente, lo sin listar y las horas."""


def base_de_mentira(version: int) -> bytes:
    """Una base KDBX 4 entera (cabecera, su suma y bloques que acaban en uno vacío).

    La semilla (campo 4 de la cabecera) y el cuerpo cambian con `version`, como en un
    guardado de verdad, que cambia las semillas cada vez.
    """
    from common import kdbx
    cab = struct.pack("<IIHH", kdbx.FIRMA_1, kdbx.FIRMA_2, 1, 4)
    semilla = hashlib.sha256(f"semilla-{version}".encode()).digest()
    for campo, valor in ((4, semilla), (0, b"\r\n\r\n")):
        cab += struct.pack("<BI", campo, len(valor)) + valor
    datos = cab + hashlib.sha256(cab).digest() + b"\x01" * 32
    for bloque in (b"x" * (100 + version), b""):
        datos += b"\x02" * 32 + struct.pack("<i", len(bloque)) + bloque
    return datos


def guardar(base: Path, version: int, hora_ns: int) -> None:
    """Guarda la base como KeePassXC (a un temporal y renombrando) y le pone esa hora."""
    temporal = base.with_name(base.name + ".tmp")
    temporal.write_bytes(base_de_mentira(version))
    os.utime(temporal, ns=(hora_ns, hora_ns))
    os.replace(temporal, base)


def montar(raiz: Path, remoto: Path, catalogo: dict, ruta_catalogo: str, cabecera: str) -> Path:
    """Monta un dispositivo en `raiz` como el instalador; devuelve su `.prdrive`."""
    sys.path.insert(0, str(REPO))
    from install import deploy, device
    from install.profile import Profile
    from install.remote import Catalog

    deploy.deploy_code(raiz, comun.rclone_fijado())
    deploy.write_device_remote(raiz, Profile(remote_name="nas", options={"type": "local"},
                                             catalog_path=ruta_catalogo))
    deploy.write_device_config(raiz, Catalog(raw=catalogo, head=cabecera,
                                             endpoint=f"nas:{ruta_catalogo}"),
                               ["notas"], catalog_path=ruta_catalogo)
    deploy.write_launchers(raiz)
    device.ensure_control_file(raiz)
    (raiz / "sync-data" / "notas").mkdir(parents=True, exist_ok=True)
    return deploy.app_dir(raiz)


def remoto_vacio() -> tuple[Path, dict, str, str]:
    """Prepara el remoto `local` con su catálogo; devuelve la carpeta, el catálogo, su ruta y su cabecera."""
    sys.path.insert(0, str(REPO))
    from common import config_file
    remoto = comun.carpeta("llavero-remoto")
    (remoto / "prdrive-catalog").mkdir(parents=True)
    (remoto / "notas").mkdir()
    ruta = f"{remoto.as_posix()}/prdrive-catalog/remote.toml"
    catalogo = {"defaults": {"remote": "nas", "catalog_path": ruta},
                "pair": [{"name": "notas", "local": "sync-data/notas",
                          "remote_path": f"{remoto.as_posix()}/notas", "mode": "bisync"}]}
    cabecera = "# catálogo de prueba\n"
    (remoto / "prdrive-catalog" / "remote.toml").write_text(
        config_file.dumps(catalogo, cabecera), encoding="utf-8")
    return remoto, catalogo, ruta, cabecera


def entorno() -> dict[str, str]:
    """El entorno de un proceso hijo: el de ahora, con la consola en UTF-8."""
    return {**os.environ, "PYTHONIOENCODING": "utf-8"}


def en_dispositivo(app: Path, codigo: str, *args: str) -> str:
    """Corre un trozo de Python con el código de ese dispositivo; devuelve su salida (lanza si falla)."""
    r = subprocess.run([sys.executable, "-c", codigo, str(app), *args], capture_output=True,
                       text=True, encoding="utf-8", errors="replace", env=entorno(),
                       cwd=tempfile.gettempdir(), timeout=300)
    if r.returncode != 0:
        raise RuntimeError(f"{r.stdout}\n{r.stderr}".strip())
    return r.stdout.strip()


def estado(app: Path) -> dict:
    """Lo que el dispositivo cree de su llavero (`ESTADO`)."""
    return json.loads(en_dispositivo(app, ESTADO).splitlines()[-1])


def pasada(app: Path, etiqueta: str) -> tuple[int, str]:
    """Una pasada de `sync.py keychain` de ese dispositivo; devuelve su código y lo que imprimió.

    Se guarda el log de rclone aunque vaya bien (`--keep-logs`) para enseñar lo que decidió
    bisync. Sin terminal, como el servicio: un resync del llavero no pregunta.
    """
    r = subprocess.run([sys.executable, str(app / "sync.py"), "keychain", "--keep-logs"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env=entorno(), cwd=tempfile.gettempdir(), stdin=subprocess.DEVNULL,
                       timeout=300)
    salida = (r.stdout or "") + (r.stderr or "")
    print(f"    [{etiqueta}] sync.py keychain -> {r.returncode}", flush=True)
    for linea in salida.splitlines():
        if linea.startswith("[keychain]") or "se repite" in linea or linea.lstrip().startswith(">>"):
            print(f"      | {linea.strip()}", flush=True)
    logs = sorted((app / "logs").glob("keychain_*.log"), key=lambda p: p.stat().st_mtime)
    if logs:
        for linea in logs[-1].read_text(encoding="utf-8", errors="replace").splitlines():
            if any(k in linea for k in SALIDA_UTIL):
                print(f"      | {linea.split(': ', 1)[-1].strip()}", flush=True)
    return r.returncode, salida


def bases_en(carpeta: Path) -> dict[str, bytes]:
    """Los ficheros de esa carpeta (con sus subcarpetas, sin `.prversions/`) y lo que dicen."""
    if not carpeta.is_dir():
        return {}
    return {p.relative_to(carpeta).as_posix(): p.read_bytes() for p in sorted(carpeta.rglob("*"))
            if p.is_file() and ".prversions" not in p.relative_to(carpeta).parts}


def copias_de_conflicto(*carpetas: Path) -> list[str]:
    """Las copias de conflicto de la base que hay en esas carpetas."""
    return sorted(f"{c.parent.name}/{n}" for c in carpetas for n in bases_en(c) if "conflicto" in n)


def escenario(p: comun.Prueba, nombre_a: str, raiz_a: Path, nombre_b: str, raiz_b: Path) -> None:
    """Hace LL-6, LL-7 y la repetición con dos dispositivos, `A` en `raiz_a` y `B` en `raiz_b`."""
    remoto, catalogo, ruta, cabecera = remoto_vacio()
    llavero_remoto = remoto / "prdrive-catalog" / "keychain"
    app_a = montar(raiz_a, remoto, catalogo, ruta, cabecera)
    app_b = montar(raiz_b, remoto, catalogo, ruta, cabecera)
    keychain_a, keychain_b = raiz_a / ".keychain", raiz_b / ".keychain"
    a, b = f"A ({nombre_a})", f"B ({nombre_b})"
    desvio = comun.medir_hora(raiz_b)
    p.nota(f"{nombre_b}: una hora con fracción queda {desvio / 1e9:+.3f} s respecto a la pedida")

    # Una hora con fracción, de ahora: lo que redondea exFAT en Windows. Los guardados siguientes
    # van siempre más adelante, como los de una persona (la primera copia a `.keychain/` es de ahora).
    hora = (time.time_ns() // 1_000_000_000) * 1_000_000_000 + 123_456_789
    version = 1
    origen = comun.carpeta("origen") / BASE
    guardar(origen, version, hora)

    print(f"  -- LL-6: {b} trae el llavero de {a}", flush=True)
    print(en_dispositivo(app_a, ACTIVAR, str(origen)), flush=True)
    rc, salida = pasada(app_a, a + " activa")
    p.ver(f"LL-6: {a} activa el llavero y pasa", rc, 0)
    p.ver("  y la base y su compañero están en el remoto", sorted(bases_en(llavero_remoto)),
          ["LEEME.txt", BASE])
    print(en_dispositivo(app_b, ACTIVAR, ""), flush=True)
    rc, salida = pasada(app_b, b + " trae el del remoto")
    p.ver(f"LL-6: {b} trae el llavero del remoto y pasa", rc, 0)
    p.ver("  con la misma base que A", bases_en(keychain_b).get(BASE), base_de_mentira(version))
    for nombre, app in ((a, app_a), (b, app_b)):
        rc, salida = pasada(app, f"{nombre} otra vez")
        p.ver(f"LL-6: {nombre} sigue pasando bien, sin 'all files were changed'",
              (rc, "all files were changed" in salida), (0, False))
    for nombre, app in ((a, app_a), (b, app_b)):
        est = estado(app)
        p.ver(f"LL-6: {nombre} no tiene nada pendiente de subir (la hora de lo que bajó no cuenta)",
              (est["pendiente"], est["sin_listar"]), (False, []))
    fija = estado(app_a)["leeme_fija"]
    if fija is None:
        p.nota("el código no lleva LEEME_HORA: este dispositivo sigue con las horas de antes de #115")
    else:
        horas = {"A": estado(app_a)["leeme"], "B": estado(app_b)["leeme"],
                 "remoto": (llavero_remoto / "LEEME.txt").stat().st_mtime_ns}
        p.ver("LL-6: LEEME.txt tiene la misma hora en los dos dispositivos y en el remoto "
              "(la que dice el código, con lo que redondee cada sistema)",
              {k: abs(v - fija * 1_000_000_000) < 2_000_000_000 for k, v in horas.items()},
              {"A": True, "B": True, "remoto": True})

    for separacion, etiqueta in ((1_200_000_000, "a 1,2 s"), (6_500_000_000, "a más de 2 s")):
        print(f"  -- LL-7: dos guardados de {a} {etiqueta}", flush=True)
        hora += 60_000_000_000
        version += 1
        guardar(keychain_a / BASE, version, hora)
        rc, _ = pasada(app_a, f"{a} guarda (v{version}) y pasa")
        p.ver(f"LL-7 {etiqueta}: {a} guarda y sube", (rc, bases_en(llavero_remoto).get(BASE)),
              (0, base_de_mentira(version)))
        rc, _ = pasada(app_b, f"{b} pasa")
        est = estado(app_b)
        p.ver(f"LL-7 {etiqueta}: {b} baja la base y no se ve con cambios sin subir (paso 2)",
              (rc, bases_en(keychain_b).get(BASE) == base_de_mentira(version), est["pendiente"]),
              (0, True, False))
        hora += separacion
        version += 1
        guardar(keychain_a / BASE, version, hora)
        rc, _ = pasada(app_a, f"{a} guarda otra vez (v{version}) y pasa")
        p.ver(f"LL-7 {etiqueta}: {a} guarda otra vez y sube", (rc, bases_en(llavero_remoto).get(BASE)),
              (0, base_de_mentira(version)))
        rc, salida = pasada(app_b, f"{b} pasa")
        p.ver(f"LL-7 {etiqueta}: {b}, que no ha tocado la base, no tiene conflicto",
              (rc, copias_de_conflicto(keychain_a, keychain_b, llavero_remoto),
               "New or changed in both" in salida), (0, [], False))
        p.ver(f"LL-7 {etiqueta}: y no gana su copia vieja: B y el remoto tienen el último guardado",
              (bases_en(keychain_b).get(BASE) == base_de_mentira(version),
               bases_en(llavero_remoto).get(BASE) == base_de_mentira(version)), (True, True))
        rc, _ = pasada(app_a, f"{a} pasa")
        p.ver(f"LL-7 {etiqueta}: {a} sigue pasando bien", rc, 0)

    print("  -- Lo de la repetición: el remoto cambia de hora los dos ficheros", flush=True)
    nueva = hora + 30_000_000_000 + 654_321_000
    for fichero in (BASE, "LEEME.txt"):
        os.utime(llavero_remoto / fichero, ns=(nueva, nueva))
    rc, salida = pasada(app_a, f"{a}, con los dos ficheros cambiados en el remoto")
    p.ver(f"{a}, con los dos ficheros cambiados de hora en el remoto, pasa", rc, 0)
    repetida = "se repite la pasada una vez con --force" in salida
    veces = sum(1 for linea in salida.splitlines() if "ejecutando" in linea and " bisync " in linea)
    if fija is None:
        p.nota("sin LEEME_HORA tampoco hay repetición con --force")
    else:
        p.ver("  se repite UNA vez, con --force (o ni hace falta: no pasó a toparse con el freno)",
              (repetida, veces) in ((True, 2), (False, 1)), True)
        p.nota(f"la repetición con --force {'hizo falta' if repetida else 'no hizo falta'}")
    rc, salida = pasada(app_a, f"{a} otra vez")
    p.ver(f"  y {a} sigue pasando, sin repetir", (rc, "--force" in salida), (0, False))
    rc, _ = pasada(app_b, f"{b} pasa")
    p.ver(f"  y {b} también, sin conflictos", (rc, copias_de_conflicto(keychain_a, keychain_b,
                                                                         llavero_remoto)),
          (0, []))
