"""F34 (Windows): `deploy_code()` con una fuente de `ui/fuentes/` registrada por otro proceso (#179).

La ventana registra sus fuentes con `AddFontResourceExW(…, FR_PRIVATE)` y sigue
viva mientras corre el aplicador de «Actualizar…». Aquí otro proceso hace lo
mismo con un `.ttf` de un `.prdrive/` temporal y, mientras sigue vivo:

1. se mira si Windows deja sobrescribir ese fichero (la causa del #179);
2. `deploy_code()` desde un origen idéntico (con otro `VERSION`) termina sin
   error y deja el `VERSION` nuevo;
3. desde un origen con ese `.ttf` cambiado, lanza `CopiaIncompleta` que lo
   nombra y deja el `VERSION` de antes.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import comun

CODIGO = "F34"
SISTEMA = "W"
QUE = ("deploy_code() con una fuente registrada por otro proceso con AddFontResourceExW: "
       "lo idéntico se salta y lo distinto se apunta sin marcar VERSION")

FUENTE = "NotoSans-Bold.ttf"

_REGISTRAR = '''\
import ctypes, sys
n = ctypes.windll.gdi32.AddFontResourceExW(sys.argv[1], 0x10, None)  # FR_PRIVATE
print("registradas", n, flush=True)
sys.stdin.read()
'''
"""Lo que corre el otro proceso: registra la fuente y espera a que se le cierre la entrada."""


def _origen(version: str) -> Path:
    """Un origen con el programa del repositorio y `VERSION` = `version`."""
    from install import deploy
    base = comun.carpeta("f34-origen")
    for nombre in deploy.DEPLOY_FILES:
        shutil.copy2(comun.REPO / nombre, base / nombre)
    for nombre in deploy.DEPLOY_TREES:
        shutil.copytree(comun.REPO / nombre, base / nombre, ignore=deploy.NO_COPIAR)
    (base / "VERSION").write_text(f"{version}\n", encoding="utf-8")
    return base


def probar(p: comun.Prueba) -> None:
    """Registra una fuente del dispositivo en otro proceso y despliega encima."""
    if not comun.IS_WIN:
        raise comun.Saltada("es de Windows")
    from install import InstallError, deploy

    raiz = comun.carpeta("f34-unidad")
    deploy.deploy_code(raiz, origen=_origen("0.0.1"), con_pyc=False)
    app = deploy.app_dir(raiz)
    fuente = app / "ui" / "fuentes" / FUENTE
    p.ver("la instalación limpia deja la fuente", fuente.is_file(), True)

    otro = subprocess.Popen([sys.executable, "-c", _REGISTRAR, str(fuente)],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        linea = otro.stdout.readline().strip()
        p.ver("el otro proceso registra la fuente", linea.startswith("registradas")
              and linea != "registradas 0", True)

        try:
            shutil.copy2(fuente, fuente.with_name("copia.ttf"))
            shutil.copy2(fuente.with_name("copia.ttf"), fuente)
            p.nota("Windows deja sobrescribir la fuente registrada: el #179 no se reproduce así")
        except OSError as e:
            p.nota(f"sobrescribirla a mano falla: winerror {getattr(e, 'winerror', None)}")
        finally:
            fuente.with_name("copia.ttf").unlink(missing_ok=True)

        try:
            deploy.deploy_code(raiz, origen=_origen("0.0.2"), con_pyc=False)
            p.ver("desde un origen idéntico, sin error", True, True)
        except InstallError as e:
            p.ver("desde un origen idéntico, sin error", str(e), "")
        p.ver("  y deja el VERSION nuevo",
              (app / "VERSION").read_text(encoding="utf-8"), "0.0.2\n")

        cambiado = _origen("0.0.3")
        ttf = cambiado / "ui" / "fuentes" / FUENTE
        ttf.write_bytes(ttf.read_bytes() + b"\0")
        try:
            deploy.deploy_code(raiz, origen=cambiado, con_pyc=False)
            p.ver("con la fuente cambiada, CopiaIncompleta", "sin error", "CopiaIncompleta")
        except deploy.CopiaIncompleta as e:
            p.ver("con la fuente cambiada, CopiaIncompleta que la nombra",
                  [r for r, _ in e.pendientes], [f"ui/fuentes/{FUENTE}"])
            p.ver("  diciendo que la tiene otro programa", "otro programa" in str(e), True)
        except InstallError as e:
            p.ver("con la fuente cambiada, CopiaIncompleta", type(e).__name__,
                  "CopiaIncompleta")
        p.ver("  y deja el VERSION de antes",
              (app / "VERSION").read_text(encoding="utf-8"), "0.0.2\n")
    finally:
        otro.stdin.close()
        otro.wait(10)
