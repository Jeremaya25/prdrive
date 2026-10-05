#!/usr/bin/env python3
"""«Ajustes → Llavero…» y su entrada en «Ajustes», conducidos sin nadie delante.

Como en `test_tk_screens`: el cableado, no el aspecto. Las ventanas se montan
de verdad y no se entra en el bucle de eventos: lo que la pantalla preguntaría
(qué base, si pide fichero llave, la confirmación) se contesta aquí, y la
lectura del catálogo llega en el acto. Lo que se sujeta:
- Qué botones salen en cada caso y cuáles esperan al catálogo.
- «Usar esta base…» activa y cierra con `ACTIVADO`; «Desactivar…», con
  `CAMBIADO`; «Dónde está el fichero llave…» solo apunta la ruta.
- La entrada «Llavero…» de «Ajustes» cierra «Ajustes» y lo abre la principal,
  que relee el config y lanza la primera pasada.
"""

import struct
import sys
from pathlib import Path

from _harness import Checks, mkcfg, sandbox, tmpdir

c = Checks("«Ajustes → Llavero…» (cableado)")

try:
    import tkinter as tk
    from tkinter import messagebox, ttk
    raiz = tk.Tk()
    raiz.withdraw()
except Exception as e:                                   # sin entorno gráfico
    print(f"  (saltado) no hay entorno gráfico: {e}")
    sys.exit(c.report())

from common import catalog, config_file, kdbx, keepassxc, llavero  # noqa: E402
from ui import segundo_plano, tk_doctor, tk_llavero, tk_pairs  # noqa: E402

segundo_plano.lanzar = segundo_plano.en_el_acto
errores: list[str] = []
messagebox.showerror = lambda titulo, texto=None, **k: errores.append(str(texto))
tk_llavero.working = lambda parent, titulo, funcion, mensaje="", **k: (True, funcion())
tk_pairs.confirmar_plan = lambda parent, plan, titulo, nota, **k: True
keepassxc.ejecutable = lambda: Path("/no/esta/KeePassXC.exe")

DEF = {"remote": "nas", "catalog_path": "/prdrive-catalog/remote.toml"}
NOTAS = {"name": "notas", "local": "sync-data/notas", "remote_path": "/R/notas"}
LOCAL = {"defaults": DEF, "pair": [NOTAS]}
REMOTO = {"defaults": {"remote": "nas"}, "pair": [NOTAS]}


def leido(raw):
    """`catalog.load()` de mentira: el catálogo recién leído del remoto."""
    texto = config_file.dumps(raw)
    return lambda raw_local=None: (catalog.Catalog(
        raw=dict(raw), text=texto, source="remote", stamp="2026-10-05 10:00:00",
        endpoint="nas:/prdrive-catalog/remote.toml"), None)


def recorrer(w):
    """Recorre los widgets que cuelgan de `w`, en profundidad."""
    for hijo in w.winfo_children():
        yield hijo
        yield from recorrer(hijo)


def botones(w) -> dict:
    """Devuelve los botones de `w` por su texto, con su estado."""
    return {b.cget("text"): str(b.cget("state")) for b in recorrer(w)
            if isinstance(b, ttk.Button)}


def pulsar(w, texto):
    """Pulsa el botón de `w` con ese texto."""
    next(b for b in recorrer(w) if isinstance(b, ttk.Button)
         and b.cget("text") == texto).invoke()


def ajustes(conducir, raw=None):
    """Abre la pantalla y, en vez de enseñarla, ejecuta `conducir(dlg)`."""
    vistos: list = []

    def mostrar(dlg, parent=None):
        vistos.append(botones(dlg))
        conducir(dlg)
    tk_llavero.mostrar = mostrar
    return tk_llavero.ajustes(raiz, raw), vistos


subidas: list = []
catalog.push = lambda new_raw, base_text, raw_local=None: (
    subidas.append(dict(new_raw)), ["catálogo subido"])[1]

# sin llavero, y un remoto sin llavero
with sandbox():
    config_file.save(LOCAL)
    catalog.load = leido(REMOTO)
    resultado, vistos = ajustes(lambda dlg: None)
    c("sin llavero: «Usar esta base…», y sin «Traer el del remoto»",
      vistos[0], {"Usar esta base…": "normal", "Cerrar": "normal"})
    c("  cerrar sin hacer nada no cambia nada", resultado, None)

    catalog.load = leido({**REMOTO, "keychain": {"base": "personal.kdbx"}})
    _, vistos = ajustes(lambda dlg: None)
    c("con llavero en el remoto, también «Traer el del remoto»",
      vistos[0], {"Usar esta base…": "normal", "Traer el del remoto": "normal",
                  "Cerrar": "normal"})

    catalog.load = lambda raw_local=None: (None, "sin red")
    _, vistos = ajustes(lambda dlg: None)
    c("sin poder leer el catálogo, activar espera", vistos[0]["Usar esta base…"], "disabled")

# «Usar esta base…»: elegir, decir que no pide fichero llave, confirmar
with sandbox() as root:
    config_file.save(LOCAL)
    catalog.load = leido(REMOTO)
    base = tmpdir("prdrive-tkbase-") / "personal.kdbx"
    # Las firmas de KeePassXC con una versión que no se conoce: entra, avisando.
    base.write_bytes(struct.pack("<IIHH", kdbx.FIRMA_1, kdbx.FIRMA_2, 0, 5) + b"\0" * 50)
    tk_llavero.elegir_base = lambda parent: base
    tk_llavero.preguntar = lambda parent, texto: False
    resultado, _ = ajustes(lambda dlg: pulsar(dlg, "Usar esta base…"))
    c("activar con una base cierra con ACTIVADO", resultado, tk_llavero.ACTIVADO)
    c("  y la deja en el llavero, con [keychain] aquí y en el catálogo",
      ((llavero.carpeta() / "personal.kdbx").is_file(),
       config_file.load_raw()["keychain"]["base"], subidas[-1]["keychain"]["base"]),
      (True, "personal.kdbx", "personal.kdbx"))
    c("  sin errores", errores, [])

# activo, con fichero llave
with sandbox() as root:
    config_file.save({**LOCAL, "keychain": {"base": "personal.kdbx", "fichero_llave": True,
                                            "nombre_llave": "personal.keyx"}})
    catalog.load = leido({**REMOTO, "keychain": {"base": "personal.kdbx"}})
    llave = root / "personal.keyx"
    tk_llavero.elegir_llave = lambda parent, nombre: llave
    resultado, vistos = ajustes(lambda dlg: pulsar(dlg, "Dónde está el fichero llave…"))
    c("con llavero: el fichero llave, si la base lo pide, y desactivar",
      vistos[0], {"Dónde está el fichero llave…": "normal",
                  "La base ya no pide fichero llave…": "normal", "Desactivar…": "normal",
                  "Cerrar": "normal"})
    c("«Dónde está…» solo apunta la ruta de este equipo",
      (resultado, keepassxc.llave_apuntada()), (None, llave))

    llavero.escribir_lanzador()
    resultado, _ = ajustes(lambda dlg: pulsar(dlg, "Desactivar…"))
    c("desactivar cierra con CAMBIADO y quita [keychain]",
      (resultado, "keychain" in config_file.load_raw(), (root / llavero.LANZADOR).exists()),
      (tk_llavero.CAMBIADO, False, False))

    # un plan que no se puede pensar se dice, y no cierra
    config_file.save({**LOCAL, "keychain": {"base": "personal.kdbx"}})
    catalog.load = leido(REMOTO)
    errores.clear()
    resultado, _ = ajustes(lambda dlg: pulsar(dlg, "La base pide fichero llave…"))
    c("con un remoto que no tiene este llavero, el cambio se niega y se dice",
      (resultado, len(errores)), (None, 1))

# la entrada de «Ajustes»
with sandbox():
    abiertos: list = []
    tk_doctor.mostrar = lambda dlg, parent=None: pulsar(dlg, "Llavero…")
    tk_doctor.open_dialog(raiz, mkcfg(["notas"]), lambda *a: None,
                          abrir_llavero=lambda: abiertos.append("llavero"))
    c("«Ajustes» tiene «Llavero…», que lo abre la principal", abiertos, ["llavero"])

sys.exit(c.report())
