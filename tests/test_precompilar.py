#!/usr/bin/env python3
"""Los `.pyc` del dispositivo: `deploy.precompilar()` y quién la llama.

Una vez de verdad (con el intérprete que ejecuta el test, sobre un árbol
temporal) y el resto con `precompilar()` sustituida:
- Qué escribe: `common/`, `ui/` y `penwatch.py`, en modo `checked-hash`, con la
  etiqueta del intérprete que los hizo; nada de `sync.py` ni `runsync.py`, que
  se ejecutan y no se importan.
- Que un `.pyc` de hash vale aunque cambie la hora de la fuente (FAT32/exFAT
  entre Windows y Linux) y se rehace si cambia su contenido, aunque tenga el
  mismo tamaño y la misma hora.
- Que no reescribe lo que ya está al día, que con `prefijo` no ensucia el
  árbol y que ante un plazo corto, una unidad que no deja escribir o un
  intérprete que no existe no lanza nada.
- Quién la llama: `deploy_code()`, `apply_platforms()` y el cambio de
  componentes, y con qué intérprete; y que una raíz del equipo (sin runtime) no
  precompila.
- Que `BIBLIOTECA` lleva todo lo que importa el programa.

La biblioteca estándar del intérprete que corre el test no se toca: la parte de
la biblioteca se hace siempre con `prefijo`, que la lleva a un temporal.
"""

import ast
import importlib.util
import os
import subprocess
import sys
import time
from pathlib import Path

from _harness import REPO, Checks, tmpdir

from common import pins
from install import deploy, platforms

c = Checks("precompilar el programa del dispositivo")

ETIQUETA = sys.implementation.cache_tag          # cpython-311, cpython-314…


def cabecera(pyc: Path) -> tuple[int, bytes]:
    """Devuelve `(banderas, hash)` de un `.pyc`: bytes 4-8 y 8-16 de su cabecera."""
    datos = pyc.read_bytes()[:16]
    return int.from_bytes(datos[4:8], "little"), datos[8:16]


def arbol() -> Path:
    """Un `.prdrive/` de mentira con lo que se importa y lo que se ejecuta."""
    app = tmpdir() / deploy.APP_SUBDIR
    (app / "common").mkdir(parents=True)
    (app / "ui").mkdir()
    (app / "common" / "uno.py").write_text("VALOR = 1\n", encoding="utf-8")
    (app / "ui" / "dos.py").write_text("import json\nVALOR = 2\n", encoding="utf-8")
    for nombre in ("penwatch.py", "sync.py", "runsync.py"):
        (app / nombre).write_text(f"# {nombre}\nVALOR = 3\n", encoding="utf-8")
    return app


def importar(app: Path, modulo: str) -> str:
    """Importa `modulo` desde `app` en un proceso nuevo y devuelve su VALOR."""
    res = subprocess.run([sys.executable, "-I", "-c",
                          f"import sys; sys.path.insert(0, sys.argv[1]); "
                          f"import {modulo}; print({modulo}.VALOR)", str(app)],
                         capture_output=True, text=True, timeout=60)
    return res.stdout.strip()


# lo que escribe, de verdad
app = arbol()
progreso: list[str] = []
c("con el intérprete del dispositivo acaba bien",
  deploy.precompilar(app, sys.executable, biblioteca=False, progreso=progreso.append), True)
c("  y lo dice", len(progreso) >= 1, True)
uno = app / "common" / "__pycache__" / f"uno.{ETIQUETA}.pyc"
dos = app / "ui" / "__pycache__" / f"dos.{ETIQUETA}.pyc"
pen = app / "__pycache__" / f"penwatch.{ETIQUETA}.pyc"
c("deja el .pyc de common/, el de ui/ y el de penwatch.py",
  (uno.is_file(), dos.is_file(), pen.is_file()), (True, True, True))
c("  con la etiqueta del intérprete que los hizo", ETIQUETA.startswith("cpython-"), True)
c("  y ninguno de los scripts, que no se importan",
  sorted(p.name for p in app.rglob("*.pyc")
         if p.name.split(".")[0] in ("sync", "runsync")), [])
c("son de hash comprobado (banderas 0b11)", cabecera(uno)[0], 0b11)
c("  y el hash es el de la fuente",
  cabecera(uno)[1],
  importlib.util.source_hash((app / "common" / "uno.py").read_bytes()))

# la hora de la fuente no vale ni quita nada
antes = uno.stat().st_mtime_ns
fuente = app / "common" / "uno.py"
viejo = fuente.stat().st_mtime - 7 * 3600           # otro huso, otro equipo
os.utime(fuente, (viejo, viejo))
c("con otra hora en la fuente, el .pyc se sigue usando",
  (importar(app, "common.uno"), uno.stat().st_mtime_ns), ("1", antes))

# el contenido sí: mismo tamaño y misma hora, otro contenido
fuente.write_text("VALOR = 9\n", encoding="utf-8")
os.utime(fuente, (viejo, viejo))
c("con otro contenido (mismo tamaño y misma hora) se rehace al importar",
  importar(app, "common.uno"), "9")
c("  y lo que se rehace sigue siendo de hash", cabecera(uno)[0], 0b11)

# repetir no reescribe lo que ya vale
dos_antes, pen_antes = dos.stat().st_mtime_ns, pen.stat().st_mtime_ns
time.sleep(0.05)
c("otra vez, acaba bien", deploy.precompilar(app, sys.executable, biblioteca=False), True)
c("  y no reescribe lo que ya estaba al día",
  (dos.stat().st_mtime_ns, pen.stat().st_mtime_ns), (dos_antes, pen_antes))
fuente.write_text("VALOR = 10\n", encoding="utf-8")
deploy.precompilar(app, sys.executable, biblioteca=False)
c("  pero sí lo que ha cambiado", cabecera(uno)[1], importlib.util.source_hash(b"VALOR = 10\n"))

# un .py roto no impide los demás
(app / "common" / "roto.py").write_text("def (:\n", encoding="utf-8")
c("un .py con errores no impide los demás",
  (deploy.precompilar(app, sys.executable, biblioteca=False),
   (app / "common" / "__pycache__" / f"roto.{ETIQUETA}.pyc").exists()), (True, False))

# con prefijo: a su caché, y la biblioteca
app = arbol()
cache = tmpdir() / "pycache"
stdlib_json = Path(importlib.util.find_spec("json").origin).parent / "__pycache__"
tocados = {p: p.stat().st_mtime_ns for p in stdlib_json.glob("*.pyc")}
c("con prefijo y biblioteca, acaba bien",
  deploy.precompilar(app, sys.executable, prefijo=cache), True)
c("  el árbol no se ensucia", list(app.rglob("__pycache__")), [])
en_cache = sorted(p.relative_to(cache).parts[-1] for p in cache.rglob("*.pyc"))
c("  los .pyc del programa están en la caché", f"uno.{ETIQUETA}.pyc" in en_cache, True)
c("  y los de la biblioteca que usa", all(f"{n}.{ETIQUETA}.pyc" in en_cache
                                           for n in ("subprocess", "shutil", "dataclasses")), True)
bib = next(cache.rglob(f"shutil.{ETIQUETA}.pyc"))
c("  también de hash comprobado", cabecera(bib)[0], 0b11)
c("  y la biblioteca del intérprete no se ha tocado",
  {p: p.stat().st_mtime_ns for p in stdlib_json.glob("*.pyc")}, tocados)

# plazos y fallos: nunca lanza
app = arbol()
t0 = time.monotonic()
c("con un plazo que no da tiempo, devuelve False sin lanzar",
  deploy.precompilar(app, sys.executable, tope=0.001), False)
c("  y no se queda esperando", time.monotonic() - t0 < 20, True)
c("sin intérprete (instalación ligera, raíz del equipo), no hace nada",
  (deploy.precompilar(app, None), list(app.rglob("__pycache__"))), (False, []))
c("con un intérprete que no existe, tampoco",
  deploy.precompilar(app, app / "bin" / "python3"), False)
c("un pythonw.exe se cambia por el python.exe de al lado, que aquí no está",
  deploy.precompilar(app, app / "pythonw.exe"), False)
c("sin carpeta de código, no hay nada que hacer",
  deploy.precompilar(app / "no-existe", sys.executable), False)
(app / "common" / "__pycache__").write_text("no soy una carpeta", encoding="utf-8")
c("si no se puede escribir (aquí, un fichero donde va la caché) devuelve False",
  deploy.precompilar(app, sys.executable, biblioteca=False), False)
c("  y no deja a medias lo demás", (app / "ui" / "__pycache__").is_dir(), False)

# quién la llama
llamadas: list[tuple] = []
real = deploy.precompilar
deploy.precompilar = lambda destino, python, **k: llamadas.append((Path(destino), python, k)) or True
try:
    host = platforms.host()
    origen = tmpdir() / "origen"
    (origen / "common").mkdir(parents=True)
    (origen / "ui").mkdir()
    for nombre in deploy.DEPLOY_FILES:
        (origen / nombre).write_text("#\n", encoding="utf-8")

    # una unidad sin runtime (ligera) y una raíz del equipo: nada
    sin = tmpdir() / "unidad-ligera"
    deploy.deploy_code(sin, origen=origen)
    c("una unidad sin runtime precompila con None: no hay Python del que fiarse",
      [(d, p) for d, p, _ in llamadas], [(deploy.app_dir(sin), None)])

    # una unidad con el runtime de este equipo: con su intérprete de consola
    llamadas.clear()
    con = tmpdir() / "unidad-completa"
    for plat in platforms.candidates(host)[:1]:
        carpeta = platforms.runtime_dir(con, plat)
        (carpeta / plat.interprete_consola).parent.mkdir(parents=True)
        (carpeta / plat.interprete_consola).write_bytes(b"py")
        (carpeta / plat.interprete).write_bytes(b"py")
        (carpeta / "PRDRIVE-RUNTIME").write_text("python = 3.14.8\n", encoding="utf-8")
        esperado = carpeta / plat.interprete_consola
    mensajes: list[str] = []
    deploy.deploy_code(con, origen=origen, progreso=mensajes.append)
    c("deploy_code() precompila al final con el intérprete de consola del runtime de este equipo",
      [(d, p) for d, p, _ in llamadas], [(deploy.app_dir(con), esperado)])
    c("  y pasa lo que se dice", llamadas[0][2].get("progreso") is not None, True)

    # la instalación nueva: el código llega ANTES que el Python (paso 5), así que
    # es `apply_platforms()` quien precompila cuando el Python de este equipo llega
    llamadas.clear()
    nueva = tmpdir() / "unidad-nueva"
    deploy.deploy_code(nueva, origen=origen)
    c("en la instalación nueva, deploy_code() aún no tiene Python", llamadas[-1][1], None)
    real_install = deploy.install_runtime

    def instalar_falso(device_root, plat, archivo):
        """`install_runtime()` de mentira: deja el intérprete y el sello donde van."""
        carpeta = platforms.runtime_dir(device_root, plat)
        (carpeta / plat.interprete_consola).parent.mkdir(parents=True, exist_ok=True)
        (carpeta / plat.interprete_consola).write_bytes(b"py")
        (carpeta / plat.interprete).write_bytes(b"py")
        (carpeta / "PRDRIVE-RUNTIME").write_text("python = 3.14.8\n", encoding="utf-8")
        return carpeta
    deploy.install_runtime = instalar_falso
    try:
        otra = next(p for p in pins.PLATAFORMAS if p not in platforms.candidates(host))
        for plan_runtime, quien in (([otra], "el Python de OTRA plataforma"),
                                    ([host], "el de este equipo")):
            llamadas.clear()
            deploy.apply_platforms(
                nueva, platforms.Plan(rclone=[], runtime=plan_runtime, borrar=[], completa=True),
                conseguido=deploy.Conseguido(runtime={p.clave: Path("x") for p in plan_runtime}))
            c(f"apply_platforms() con {quien}: " + ("precompila" if quien.startswith("el de")
                                                     else "no precompila"),
              [(d, Path(p).name) for d, p, _ in llamadas],
              [(deploy.app_dir(nueva), host.interprete_consola.split("/")[-1])]
              if quien.startswith("el de") else [])
    finally:
        deploy.install_runtime = real_install
finally:
    deploy.precompilar = real

# BIBLIOTECA lleva todo lo que importa el programa
necesarios: set[str] = set()
for ruta in [*(REPO / "common").rglob("*.py"), *(REPO / "ui").rglob("*.py"),
             *(REPO / n for n in ("runsync.py", "sync.py", "penwatch.py"))]:
    for nodo in ast.walk(ast.parse(ruta.read_text(encoding="utf-8"))):
        if isinstance(nodo, ast.Import):
            necesarios |= {a.name for a in nodo.names}
        elif isinstance(nodo, ast.ImportFrom) and nodo.level == 0 and nodo.module:
            necesarios.add(nodo.module)
            necesarios |= {f"{nodo.module}.{a.name}" for a in nodo.names}


def con_fuente(nombre: str) -> bool:
    """Indica si `nombre` es un módulo de la biblioteca con un `.py` (no interno ni de C)."""
    if nombre.split(".")[0] not in sys.stdlib_module_names:
        return False
    try:
        spec = importlib.util.find_spec(nombre)
    except (ImportError, ValueError):
        return False
    return spec is not None and str(spec.origin).endswith(".py")


faltan = sorted(n for n in necesarios if con_fuente(n) and n not in deploy.BIBLIOTECA
                and n not in ("__future__", "collections.abc"))
c("BIBLIOTECA lleva todo lo que el programa importa de la biblioteca estándar", faltan, [])

raise SystemExit(c.report())
