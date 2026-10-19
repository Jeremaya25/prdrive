"""F33: el agente en «Aplicaciones instaladas» y su desinstalación sin rastro (filas U2, U4 y U6).

Con el registro de la máquina (HKCU), su `schtasks` y su `cmd`, sin desplegar
nada ni arrancar el agente: se copia un Python y el código del agente a una
carpeta temporal que hace de `%LOCALAPPDATA%\\prdrive` (el desinstalador la
encuentra por `LOCALAPPDATA`), se registra como lo hace el instalador (con una
tarea programada «prdrive» de las de antes, que tiene que desaparecer) y se
ejecuta la `QuietUninstallString` que quedó en la ficha, como la ejecutaría
Windows, con el Python sin consola de esa carpeta. Lo que se mira es la
frontera: que lo escrito en el registro se lee y se ejecuta tal cual, y que la
carpeta desde la que corre el desinstalador se borra cuando él ya ha salido.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import comun

CODIGO = "F33"
SISTEMA = "W"
QUE = ("el arranque en Run y la ficha de «Aplicaciones instaladas»; su «Desinstalar» "
       "silencioso no deja nada, ni la carpeta desde la que corre")

NO_COPIAR = shutil.ignore_patterns("site-packages", "test", "tests", "idlelib", "turtledemo",
                                   "__pycache__", "*.pyc", "Doc", "Tools", "include", "tcl",
                                   "libs", "Scripts")
"""Lo que el Python copiado no necesita para importar el agente."""


def copiar_agente(base: Path) -> tuple[Path, Path, Path]:
    """Deja en `base/prdrive` un agente como el del instalador.

    Returns:
        `(carpeta, pythonw, código)`.
    """
    carpeta = base / "prdrive"
    shutil.copytree(sys.base_prefix, carpeta / "runtime" / "x", ignore=NO_COPIAR)
    codigo = carpeta / "agente" / "0.0.0"
    codigo.mkdir(parents=True)
    for nombre in ("agente.py", "pregunta.py", "penwatch.py", "VERSION"):
        shutil.copy2(comun.REPO / nombre, codigo / nombre)
    for arbol in ("common", "ui"):
        shutil.copytree(comun.REPO / arbol, codigo / arbol,
                        ignore=shutil.ignore_patterns("__pycache__"))
    return carpeta, carpeta / "runtime" / "x" / "pythonw.exe", codigo


def tarea_existe() -> bool:
    """Indica si hay una tarea programada «prdrive»."""
    return comun.ejecutar(["schtasks", "/Query", "/TN", "prdrive"], callado=True).returncode == 0


def preparar(p: comun.Prueba, nombre: str) -> tuple[Path, Path, dict]:
    """Copia un agente, lo registra como el instalador y devuelve `(carpeta, menú, entorno)`."""
    from common import equipo, presencia, registro

    base = comun.carpeta(nombre)
    carpeta, pythonw, codigo = copiar_agente(base)
    datos = base / "Roaming"
    entorno = {**os.environ, "LOCALAPPDATA": str(base), "APPDATA": str(datos)}
    importa = subprocess.run([str(pythonw.with_name("python.exe")), "-c",
                              "import sys; sys.path.insert(0, sys.argv[1]); import agente",
                              str(codigo)], env=entorno, capture_output=True, text=True,
                             timeout=120)
    p.ver(f"{nombre}: el Python copiado importa el agente desde su carpeta",
          (importa.returncode, importa.stderr.strip()[-300:]), (0, ""))
    equipo.DIR = carpeta
    presencia.registrar_arranque(pythonw, codigo)
    presencia.registrar_ficha(pythonw, codigo, "0.0.0")
    # Lo que escribe Windows al apagarlo en «Aplicaciones de arranque» (REG_BINARY).
    import winreg
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, presencia.CLAVE_APAGADO, 0,
                            winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, "prdrive", 0, winreg.REG_BINARY, b"\x03" + b"\x00" * 11)
    menu = datos / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "prdrive.lnk"
    menu.parent.mkdir(parents=True, exist_ok=True)
    menu.write_bytes(b"lnk")
    p.ver(f"{nombre}: registrado (Run y ficha)",
          (registro.leer(presencia.CLAVE_RUN, "prdrive") is not None,
           presencia.ficha_registrada()), (True, True))
    return carpeta, menu, entorno


def desinstalar(p: comun.Prueba, nombre: str, entorno: dict) -> None:
    """Ejecuta la `QuietUninstallString` de la ficha, como Windows, y mira lo que deja."""
    from common import presencia, registro

    linea = registro.leer(presencia.CLAVE_FICHA, "QuietUninstallString")
    print(f"    QuietUninstallString: {linea}", flush=True)
    try:
        r = subprocess.run(linea, env=entorno, timeout=300)
        rc = r.returncode
    except (OSError, subprocess.TimeoutExpired) as e:
        rc = f"{type(e).__name__}: {e}"
    p.ver(f"{nombre}: el «Desinstalar» silencioso de la ficha acaba bien", rc, 0)
    p.ver(f"{nombre}: fuera el arranque y la ficha",
          (registro.leer(presencia.CLAVE_RUN, "prdrive"),
           registro.vacia(presencia.CLAVE_FICHA)), (None, None))
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, presencia.CLAVE_APAGADO) as k:
            winreg.QueryValueEx(k, "prdrive")
        apagado = True
    except OSError:
        apagado = False
    p.ver(f"{nombre}: ni lo apagado en StartupApproved", apagado, False)


def probar(p: comun.Prueba) -> None:
    """Registra, desinstala por la ficha y mira que no quede nada; con y sin un fichero ocupado."""
    from common import presencia, registro

    # El arranque: el valor de Run, y la tarea programada de antes fuera.
    comun.ejecutar(["schtasks", "/Create", "/TN", "prdrive", "/TR", "cmd /c exit", "/SC",
                    "ONLOGON", "/F"])
    p.ver("hay una tarea «prdrive» de las de antes", tarea_existe(), True)
    carpeta, menu, entorno = preparar(p, "limpia")
    p.ver("registrar quita la tarea programada de antes", tarea_existe(), False)
    leida = comun.ejecutar(["powershell", "-NoProfile", "-Command",
                            "(Get-ItemProperty 'HKCU:\\Software\\Microsoft\\Windows\\"
                            "CurrentVersion\\Uninstall\\prdrive').DisplayName"], callado=True)
    p.ver("la ficha se lee desde PowerShell como la de cualquier programa",
          (leida.stdout or "").strip(), "prdrive")
    paquete = comun.ejecutar(["powershell", "-NoProfile", "-Command",
                              "(Get-Package -ProviderName Programs -Name prdrive "
                              "-ErrorAction SilentlyContinue).Name"], timeout=180, callado=True)
    p.nota(f"Get-Package (proveedor Programs) dice: {(paquete.stdout or '').strip() or 'nada'}")

    desinstalar(p, "limpia", entorno)
    p.ver("limpia: el acceso del menú, fuera", menu.exists(), False)
    p.ver("limpia: la carpeta se borra cuando el desinstalador ya ha salido",
          comun.esperar(lambda: not carpeta.exists(), 60, 0.5), True)
    p.ver("  y su RunOnce se va con ella",
          comun.esperar(lambda: registro.leer(presencia.CLAVE_RUNONCE, "prdrive") is None,
                        10, 0.5), True)

    # Un fichero ocupado dentro: la carpeta espera y se borra al soltarlo.
    carpeta, _menu, entorno = preparar(p, "ocupada")
    ocupado = (carpeta / "ocupado.txt").open("w", encoding="utf-8")
    try:
        desinstalar(p, "ocupada", entorno)
        time.sleep(4)
        p.ver("ocupada: mientras el fichero sigue abierto, la carpeta se queda con su RunOnce",
              (carpeta.exists(), registro.leer(presencia.CLAVE_RUNONCE, "prdrive") is not None),
              (True, True))
        p.nota("lo que queda con el fichero abierto: "
               + ", ".join(sorted(x.name for x in carpeta.iterdir())))
    finally:
        ocupado.close()
    p.ver("ocupada: al soltarlo, el mismo cmd la borra",
          comun.esperar(lambda: not carpeta.exists(), 60, 0.5), True)
    p.ver("  y quita su RunOnce",
          comun.esperar(lambda: registro.leer(presencia.CLAVE_RUNONCE, "prdrive") is None,
                        10, 0.5), True)

    # La línea de RunOnce, ejecutada como al iniciar sesión, borra la carpeta.
    resto = comun.carpeta("resto") / "prdrive"
    (resto / "veracrypt").mkdir(parents=True)
    (resto / "veracrypt" / "veracrypt-x64.sys").write_bytes(b"sys")
    p.ver("apuntar_borrado deja la línea en RunOnce", presencia.apuntar_borrado(resto), True)
    linea = registro.leer(presencia.CLAVE_RUNONCE, "prdrive")
    print(f"    RunOnce: {linea}", flush=True)
    r = subprocess.run(linea, capture_output=True, text=True, timeout=60)
    p.ver("ejecutada tal cual, como la ejecuta Windows, borra la carpeta",
          (r.returncode, resto.exists()), (0, False))
    registro.borrar_valor(presencia.CLAVE_RUNONCE, "prdrive")
