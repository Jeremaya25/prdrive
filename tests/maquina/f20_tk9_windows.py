"""F20: la interfaz con el Python del dispositivo en Windows (3.14, Tk 9.0.4).

Desde que `common/pins.py` fija Python 3.14, el runtime de Windows trae Tk 9.0.4
(antes, 8.6.15). La suite de `tests.yml` corre con el Python 3.11 de
`setup-python` (Tk 8.6), así que no lo ve: aquí se baja el runtime fijado con el
propio instalador (`install/runtime_bin.py`, comprobado contra su SHA256SUMS),
se extrae ya podado, y con SU intérprete se mira lo que depende de Windows:

- que Tk sea el 9.0.4 y la ventana abra con el tema y los controles dibujados;
- que la letra de `ui/fuentes/` se cargue privada (`AddFontResourceExW`);
- que la protección de capturas del QR (#59) quede puesta y se suelte, leída
  con `GetWindowDisplayAffinity` sobre el marco (`wm frame`) de Tk 9;
- y que los scripts de tests de la interfaz pasen con ese intérprete.
"""

from __future__ import annotations

import json

import comun

CODIGO = "F20"
SISTEMA = "W"
QUE = "la interfaz con el Python 3.14 del dispositivo (Tk 9): ventana, letra, capturas y tests"

SONDA = r'''
import ctypes, json, sys
sys.path.insert(0, sys.argv[1])
import ui                                   # antes que tkinter, como runsync.py
from ui import theme, tk as uitk
theme.nitidez()
import tkinter as tk
from tkinter import ttk
fuera = {"tk": tk.Tcl().eval("info patchlevel"),
         "fuentes": theme.cargar_fuentes(),
         "familias": [theme.familia(r) for r in ("texto", "fuerte", "mono")]}
raiz = tk.Tk()
theme.apply(raiz)
raiz.configure(background=theme.PAPEL)
boton = ttk.Button(raiz, text="Guardar", style="Primary.TButton")
boton.pack(padx=20, pady=20)
raiz.update()
fuera["pieza"] = "Prdrive." in str(ttk.Style(raiz).layout("Primary.TButton"))
fuera["alto_boton"] = boton.winfo_reqheight()
from ui import icons
from tkinter import font as tkfont
fuera["alto_esperado"] = icons.px(raiz, 34)
fuera["letra_real"] = tkfont.Font(root=raiz, font=theme.fuente()).actual("family")
ventana = tk.Toplevel(raiz)
ttk.Label(ventana, text="QR").pack()
ventana.update()
puesta = uitk.proteger_de_capturas(ventana)
hwnd = int(ventana.wm_frame(), 16)
leer = ctypes.WinDLL("user32").GetWindowDisplayAffinity
valor = ctypes.c_uint32()
leer(ctypes.c_void_p(hwnd), ctypes.byref(valor))
fuera["captura"] = [puesta, valor.value]
uitk.soltar_capturas(ventana)
leer(ctypes.c_void_p(hwnd), ctypes.byref(valor))
fuera["captura_suelta"] = valor.value
raiz.destroy()
print("SONDA " + json.dumps(fuera))
'''

TESTS = ("test_controles", "test_iconos", "test_tema", "test_tk_densidad",
         "test_captura_pantalla", "test_tk_medidas")


def probar(p: comun.Prueba) -> None:
    """Baja el runtime fijado, abre la ventana con él y corre los tests de la interfaz."""
    from common import pins
    from install import runtime_bin

    plat = pins.plataforma("windows-x64")
    archivo = runtime_bin.ensure_runtime(plat, lambda m: print(f"    {m}", flush=True))
    sha = runtime_bin.recorded_sha256(archivo) or runtime_bin.file_sha256(archivo)
    destino = comun.carpeta("runtime-windows-x64")
    runtime_bin.extract(archivo, destino, plat, sha)
    python = destino / plat.interprete_consola
    p.ver("el runtime fijado se baja, se comprueba y se extrae", python.is_file(), True)
    p.nota(f"Python {pins.PYTHON_VERSION} ({pins.PYTHON_RELEASE})")

    sonda = comun.carpeta("sonda") / "sonda.py"
    sonda.write_text(SONDA, encoding="utf-8")
    r = comun.ejecutar([str(python), str(sonda), str(comun.REPO)], timeout=180)
    linea = next((l for l in (r.stdout or "").splitlines() if l.startswith("SONDA ")), "")
    p.ver("la ventana abre con ese Python", r.returncode == 0 and bool(linea), True)
    if not linea:
        return
    d = json.loads(linea[len("SONDA "):])
    p.ver("Tk es el 9.0.4", d["tk"], "9.0.4")
    p.ver("la letra propia se carga privada", d["fuentes"], True)
    p.ver("  y los roles la eligen", d["familias"],
          ["Noto Sans", "Noto Sans SemiBold", "Noto Sans Mono"])
    p.ver("  y es la que dibuja Windows", d["letra_real"], "Noto Sans")
    p.ver("los controles son los dibujados", d["pieza"], True)
    p.ver("un botón mide el alto del diseño, a un píxel",
          abs(d["alto_boton"] - d["alto_esperado"]) <= 1, True)
    p.ver("la protección de capturas queda puesta (lo que dice = lo que hay)",
          d["captura"][0] == d["captura"][1] and d["captura"][0] != 0, True)
    p.nota(f"afinidad {d['captura'][1]:#x}")
    p.ver("  y se suelta", d["captura_suelta"], 0)

    for nombre in TESTS:
        r = comun.ejecutar([str(python), str(comun.REPO / "tests" / f"{nombre}.py")],
                           timeout=1500)
        p.ver(f"tests/{nombre}.py pasa con Tk 9", r.returncode, 0)
