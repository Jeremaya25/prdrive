#!/usr/bin/env python3
"""Los controles dibujados: piezas redondeadas, su asiento, la letra y la escala.

El tema deja de pintar con clam los controles que el diseño redondea y los
pinta con piezas de imagen (`theme._controles`, `icons.caja`). Aquí se
comprueba lo que, si falla, no se ve en una prueba de pantallas:

- que la pieza es de verdad transparente por fuera de la forma (si no, las
  esquinas saldrían cuadradas de otro color);
- que un control que cae sobre una tarjeta toma el fondo de la tarjeta
  (`_asentar`: enciende los bits de estado de esa superficie, sin cambiar de
  estilo), y uno sobre el papel no enciende ninguno (todas las superficies,
  en los dos temas, con sus esquinas: `test_superficie.py`);
- que la letra propia se carga y es la que eligen los roles;
- que un botón mide el alto del diseño;
- y que en `ui/tk*.py` no queda ningún espaciado fuera de la escala `E1…E7`.
"""

from __future__ import annotations

import gc
import re
import sys

from _harness import REPO, Checks

c = Checks("controles: piezas redondeadas, asiento, letra y escala")

from ui import icons, theme  # noqa: E402

theme.nitidez()

# 1. ningún espaciado fuera de la escala
#
# Va antes que nada que necesite pantalla: es lo que más fácil se rompe (un
# `padx=10` nuevo) y no hace falta Tk para verlo.
SUELTO = re.compile(r"\b(?:padx|pady|padding|ipadx|ipady)=\(?\s*(-?\d+)\s*(?:,\s*(-?\d+)\s*)*\)?")
fuera = []
for ruta in sorted((REPO / "ui").glob("tk*.py")):
    for n, linea in enumerate(ruta.read_text(encoding="utf-8").splitlines(), 1):
        for m in SUELTO.finditer(linea):
            numeros = re.findall(r"-?\d+", m.group(0))
            if any(x != "0" for x in numeros):
                fuera.append(f"{ruta.name}:{n}: {m.group(0)}")
c("ningún espaciado de ui/tk*.py se sale de la escala E1…E7", fuera, [])

try:
    import tkinter as tk
    from tkinter import ttk
    raiz = tk.Tk()
except Exception as e:                                   # sin entorno gráfico
    print(f"  (saltado) no hay entorno gráfico: {e}")
    sys.exit(c.report())

raiz.tk.call("tk", "scaling", 1.3333)
theme.apply(raiz)
raiz.configure(background=theme.PAPEL)     # como toda ventana de la aplicación
style = ttk.Style(raiz)

# 2. la pieza es transparente por fuera y opaca por dentro
img, borde = icons.caja(raiz, [(theme.BORDE, 0), (theme.SUPERFICIE, 1)])
c("la pieza se pinta", img is not None, True)
c("con un borde de nueve trozos mayor que el radio", borde > icons.px(raiz, theme.RADIO), True)
c("la esquina es transparente", img.transparency_get(0, 0), True)
c("el centro no", img.transparency_get(img.width() // 2, img.height() // 2), False)
aro, _ = icons.caja(raiz, [(theme.ACENTO, 0), (None, 2)])
c("un tono None recorta: el aro es hueco",
  aro.transparency_get(aro.width() // 2, aro.height() // 2), True)

# 3. los estilos usan las piezas, no los elementos de clam
for estilo in ("TButton", "Primary.TButton", "Quiet.TButton", "TEntry",
               "TCombobox", "TSpinbox", "Card.TFrame", "Ok.Chip.TLabel",
               "Primero.Segmento.Toolbutton"):
    c(f"{estilo} lleva su pieza", "Prdrive." in str(style.layout(estilo)), True)
c("las flechas se llaman como las de clam: los bindings deciden por el nombre",
  "downarrow" in str(style.layout("TCombobox")), True)

# 4. el asiento: sobre la tarjeta enciende los bits de su fondo, sobre el papel
# ninguno, y en los dos casos el control conserva su estilo
raiz.geometry("+0+0")
tarjeta = ttk.Frame(raiz, style="Card.TFrame", padding=theme.E4)
tarjeta.pack()
en_tarjeta = ttk.Button(tarjeta, text="Guardar", style="Primary.TButton")
en_tarjeta.pack()
en_papel = ttk.Button(raiz, text="Cancelar")
en_papel.pack()
plano = ttk.Frame(tarjeta, style="Plano.Card.TFrame")
plano.pack()
grupo = theme.grupo_botones(raiz, [("Uno", "1"), ("Dos", "2"), ("Tres", "3")],
                            tk.StringVar(raiz, "1"))
grupo.pack()
raiz.update()

asiento = theme._asientos[id(raiz.tk)]
blanco = theme._hex(raiz, theme.SUPERFICIE)
c("el botón de la tarjeta enciende los bits de ese fondo",
  tuple(sorted(en_tarjeta.state())), tuple(sorted(asiento.bits[blanco])))
c("  sin cambiar de estilo", str(en_tarjeta.cget("style")), "Primary.TButton")
c("  y ve por fondo el de la tarjeta",
  theme._hex(raiz, style.lookup("Primary.TButton", "background", en_tarjeta.state())),
  blanco)
c("  con la misma pieza", "Prdrive." in str(style.layout("Primary.TButton")), True)
c("el del papel no enciende ninguno", en_papel.state(), ())
c("  y ve el papel por fondo",
  theme._hex(raiz, style.lookup("TButton", "background", en_papel.state())),
  theme._hex(raiz, theme.PAPEL))
c("  con su estilo", str(en_papel.cget("style")), "")
c("un marco plano no se asienta", (str(plano.cget("style")), plano.state()),
  ("Plano.Card.TFrame", ()))
c("el grupo redondea solo por fuera",
  [str(b.cget("style")) for b in grupo.botones],
  ["Primero.Segmento.Toolbutton", "Medio.Segmento.Toolbutton",
   "Ultimo.Segmento.Toolbutton"])
c("  y los tres ven el papel por fondo",
  {theme._hex(raiz, style.lookup(str(b.cget("style")), "background", b.state()))
   for b in grupo.botones}, {theme._hex(raiz, theme.PAPEL)})

# 4b. asentar no crea estilos: los bits ya están en el mapa de cada estilo.
# Crear uno (o configurarlo, mapearlo, cambiarle la disposición) le dice a todos
# los widgets que el tema ha cambiado, y abrir una pantalla costaba varias
# vueltas enteras de repintado.
cambios = []
raiz.bind_all("<<ThemeChanged>>", lambda e: cambios.append(e.widget), add="+")
gris = ttk.Frame(raiz, style="Gris.TFrame", padding=theme.E3)
gris.pack()
estilos_gris = ("Grande.Primary.TButton", "Pequeno.TButton", "Mono.TEntry",
                "Ok.Chip.TLabel")
nuevos = [ttk.Button(gris, text="Grande", style=estilos_gris[0]),
          ttk.Button(gris, text="Pequeño", style=estilos_gris[1]),
          ttk.Entry(gris, style=estilos_gris[2]),
          ttk.Label(gris, text="ok", style=estilos_gris[3])]
for w in nuevos:
    w.pack()
aviso = ttk.Frame(raiz, style="NotaAmbar.TFrame")
aviso.pack()
ttk.Button(aviso, text="Abrir", style="Quiet.TButton").pack()
raiz.update()
gris_hex = theme._hex(raiz, theme.GRIS_FONDO)
c("sobre el gris, cada control conserva su estilo (los derivados heredan el mapa)",
  [str(w.cget("style")) for w in nuevos], list(estilos_gris))
c("  y enciende los bits del gris",
  [tuple(sorted(w.state())) for w in nuevos],
  [tuple(sorted(asiento.bits[gris_hex]))] * 4)
c("  con el gris por fondo",
  [theme._hex(raiz, style.lookup(e, "background", w.state()))
   for e, w in zip(estilos_gris, nuevos)], [gris_hex] * 4)
c("  sin crear ningún estilo: ningún <<ThemeChanged>>", len(cambios), 0)

# 4d. las pantallas de verdad, con el programa ya abierto: abrir «Parejas» o
# «Ajustes» tampoco manda ningún <<ThemeChanged>> (es el techo `tema.abrir.*` de
# la comprobación de tiempos) ni deja un control sobre una superficie sin bits.
import tomllib  # noqa: E402

from _harness import mkcfg, sandbox  # noqa: E402
from common import catalog, config_file  # noqa: E402
from ui import segundo_plano, tk_doctor, tk_pairs  # noqa: E402

raiz.tk.eval('set ::prdrive_tema 0; bind . <<ThemeChanged>> '
             '{+ if {"%W" eq "."} {incr ::prdrive_tema}}')
ttk.Style(raiz).configure("Control.TLabel", background="#FF00FF")
raiz.update()
c("el contador de <<ThemeChanged>> cuenta: configurar un estilo manda uno",
  int(raiz.tk.eval("set ::prdrive_tema")), 1)

reales = (segundo_plano.lanzar, catalog.load, catalog.run, tk_pairs.mostrar,
          tk_pairs.working, tk_doctor.mostrar, theme._avisar_superficie)
cuentas, sin_superficie = {}, []


def enseñar(nombre):
    """Sustituye a `mostrar()`: enseña la pantalla, la deja pintar y la cierra."""
    def mostrar(dlg, parent=None) -> None:
        raiz.tk.eval("set ::prdrive_tema 0")
        dlg.deiconify()
        dlg.update()
        dlg.update()
        cuentas[nombre] = int(raiz.tk.eval("set ::prdrive_tema"))
        dlg.destroy()
    return mostrar


parejas = [{"name": n, "local": f"sync-data/{n}", "remote_path": f"/R/{n}"}
           for n in ("notas", "fotos")]
catalogo = config_file.dumps({"defaults": {"remote": "nas"}, "pair": parejas})
try:
    segundo_plano.lanzar = segundo_plano.en_el_acto
    catalog.load = lambda raw=None: (catalog.Catalog(
        raw=tomllib.loads(catalogo), text=catalogo, source="remote",
        stamp="2026-01-01 00:00:00", endpoint="nas:/prdrive-catalog/pairs.toml"), None)
    catalog.run = lambda args: (_ for _ in ()).throw(
        AssertionError("ningún test puede hablar con el remoto"))
    tk_pairs.working = lambda parent, titulo, funcion, mensaje="", **k: (True, funcion())
    tk_pairs.mostrar = enseñar("parejas")
    tk_doctor.mostrar = enseñar("ajustes")
    theme._avisar_superficie = lambda fondo, cercana: sin_superficie.append(fondo)
    with sandbox():
        cfg = mkcfg(["notas", "fotos"])
        config_file.save({"defaults": {"remote": "nas"}, "pair": parejas})
        tk_pairs.open_dialog(raiz, cfg)
        tk_doctor.open_dialog(raiz, cfg, lambda *a: None)
finally:
    (segundo_plano.lanzar, catalog.load, catalog.run, tk_pairs.mostrar,
     tk_pairs.working, tk_doctor.mostrar, theme._avisar_superficie) = reales
c("«Parejas» y «Ajustes» se abren y se pintan", sorted(cuentas), ["ajustes", "parejas"])
c("abrir «Parejas» con el programa abierto: ningún <<ThemeChanged>>",
  cuentas.get("parejas"), 0)
c("abrir «Ajustes»: ninguno", cuentas.get("ajustes"), 0)
c("ningún control de esas pantallas cae sobre una superficie sin bits",
  sin_superficie, [])

# 4c. el pulgar de la barra de desplazamiento es liso en todos sus estados:
# sin agarre (Tk 9 lo llama gripsize e ignora gripcount) y con el borde del
# color del relleno, o al pulsarlo asomaban los filetes claros.
for orientacion in ("Vertical", "Horizontal"):
    barra = f"{orientacion}.TScrollbar"
    c(f"{barra}: sin agarre", (str(style.lookup(barra, "gripcount")),
                               str(style.lookup(barra, "gripsize"))), ("0", "0"))
    relleno = style.map(barra, "background")
    c(f"{barra}: el borde sigue al relleno al pulsar y al pasar",
      [style.map(barra, o) for o in ("bordercolor", "lightcolor", "darkcolor")],
      [relleno] * 3)

# 4b. la pista de un campo: dentro del campo vacío, fuera en cuanto se escribe
texto = tk.StringVar(raiz)
campo = ttk.Entry(raiz, textvariable=texto)
campo.pack()
TK9 = raiz.tk.call("info", "patchlevel").startswith("9")
pista = theme.pista_campo(campo, "Buscar un ajuste…")
raiz.update()
c("y su variable sigue vacía: la pista no se escribe en el campo", texto.get(), "")
if TK9:
    # Con Tk 9 la pinta el propio campo; que se vaya al escribir es cosa de Tk.
    c("con Tk 9 es la pista del propio campo",
      (pista, str(campo.cget("placeholder"))), (None, "Buscar un ajuste…"))
    c("  en el gris de las pistas",
      theme._hex(raiz, style.lookup("TEntry", "placeholderforeground")),
      theme._hex(raiz, theme.TINTA3))
    pista = theme.pista_etiqueta(campo, "Buscar un ajuste…")   # y la de Tk 8.6
    raiz.update()
else:
    print("  (saltado) la pista nativa es de Tk 9; este es", raiz.tk.call("info", "patchlevel"))
c("con el campo vacío se ve la pista de Tk 8.6", pista.winfo_ismapped(), True)
texto.set("llav")
raiz.update()
c("al escribir, se va", pista.winfo_ismapped(), False)
texto.set("")
raiz.update()
c("al borrarlo, vuelve", pista.winfo_ismapped(), True)

# 5. un botón mide el alto del diseño
c("un botón mide 34 px, a uno", abs(en_papel.winfo_reqheight() - 34) <= 1, True)

# 5b. pintar muchos controles no puede tardar: ttk repite el centro de cada
# pieza como un azulejo, y con un centro pequeño 300 controles tardaban 36 s
# en X11 (cada copia con transparencia relee el servidor). Con el centro de
# `icons.CENTRO_ANCHO` son décimas.
import time  # noqa: E402
muchos = ttk.Frame(raiz, style="Card.TFrame")
muchos.pack()
for i in range(150):
    ttk.Button(muchos, text=f"B{i}").grid(row=i // 15, column=i % 15)
    ttk.Entry(muchos, width=4).grid(row=10 + i // 15, column=i % 15)
inicio = time.monotonic()
raiz.update()
c("300 controles se pintan en menos de 5 s", time.monotonic() - inicio < 5, True)
muchos.destroy()

# 6. la letra propia
if sys.platform == "win32" or sys.platform.startswith("linux"):
    c("la letra de ui/fuentes/ se carga", theme.cargar_fuentes(), True)
    c("y es la del texto", theme.familia("texto"), "Noto Sans")
    c("la seminegrita es su propia familia", theme.familia("fuerte"),
      "Noto Sans SemiBold")
    c("y la monoespaciada", theme.familia("mono"), "Noto Sans Mono")
else:
    print("  (saltado) la letra propia solo se carga en Windows y Linux")
c("la licencia viaja con la letra", (theme.FUENTES / "OFL.txt").is_file(), True)

# Las imágenes se sueltan con su intérprete: si siguieran vivas al salir, Python
# las borraría con tkinter ya medio descargado.
theme.olvidar(raiz.tk)
icons.olvidar(raiz.tk)
raiz.destroy()
gc.collect()
sys.exit(c.report())
