#!/usr/bin/env python3
"""La letra: una tabla de métricas por intérprete, las fuentes sujetas y la carga de la propia.

Con Xft, medir una fuente que ningún widget tiene puesta reabre la cara: 0,55
ms cada vez. Por eso `relleno_control()` e `icono_linea()` no crean una
`tkfont.Font` por control:

- una letra se mide **una vez por intérprete y escala** (`theme._metricas()`) y
  los números son los de siempre (los mide una `Font` hecha como antes);
- las fuentes de esa tabla y las de los roles (`theme.fuente_tk()`) se hacen una
  vez y las **sujeta un lienzo oculto** (`theme.ANCLA`), que no ve
  `winfo_children()`;
- todo eso es de UN intérprete y se suelta en `theme.olvidar()`: el aviso de
  fallo del servicio abre intérpretes seguidos en el mismo hilo y cada uno debe
  tener la suya;
- `familia()` enumera las familias una sola vez, y `cargar_fuentes()` abre
  fontconfig por su nombre antes de pagar `find_library` (que lanza `ldconfig`).

La primera parte no necesita pantalla; la segunda se salta sin ella.
"""

from __future__ import annotations

import sys
import time

from _harness import Checks

from ui import icons, theme

c = Checks("letra: tabla de métricas, fuentes sujetas, familias y fontconfig")

ROLES = ("texto", "fuerte", "pista", "rotulo", "mono", "mono_pequena", "etiqueta",
         "titulo", "dialogo", "seccion")

# --- cargar_fuentes(): fontconfig por su nombre, sin find_library ---------------
import ctypes  # noqa: E402
import ctypes.util  # noqa: E402

nombres: list[str] = []


class FcFalsa:
    """Una libfontconfig de mentira: acepta todos los ficheros."""

    def __init__(self) -> None:
        """Guarda la función que `cargar_fuentes()` le pone `argtypes`."""
        self.FcConfigAppFontAddFile = lambda config, ruta: 1


def cdll_falsa(nombre, *a, **k):
    """`ctypes.CDLL` de mentira: apunta el nombre y entrega la falsa."""
    nombres.append(nombre)
    return FcFalsa()


def cdll_que_falla_la_primera(nombre, *a, **k):
    """Como `cdll_falsa`, pero el nombre de siempre no se encuentra."""
    nombres.append(nombre)
    if nombre == "libfontconfig.so.1":
        raise OSError("no such file")
    return FcFalsa()


def cdll_que_nunca_abre(nombre, *a, **k):
    """`ctypes.CDLL` que no encuentra nada."""
    nombres.append(nombre)
    raise OSError("no such file")


def sin_find_library(*a, **k):
    """`find_library` que no debe llamarse: es el `ldconfig` que se quiere evitar."""
    raise AssertionError("find_library no debería llamarse")


real = (ctypes.CDLL, ctypes.util.find_library, sys.platform, theme._fuentes_cargadas)
try:
    sys.platform = "linux"                      # la rama de Linux, también en Windows
    ctypes.util.find_library = sin_find_library
    ctypes.CDLL = cdll_falsa
    theme._fuentes_cargadas = None
    c("cargar_fuentes abre libfontconfig por su nombre, sin find_library",
      (theme.cargar_fuentes(), nombres), (True, ["libfontconfig.so.1"]))

    nombres.clear()
    ctypes.util.find_library = lambda nombre: "libfontconfig.so.9"
    ctypes.CDLL = cdll_que_falla_la_primera
    theme._fuentes_cargadas = None
    c("  si el nombre de siempre no está, prueba el que dé find_library",
      (theme.cargar_fuentes(), nombres), (True, ["libfontconfig.so.1", "libfontconfig.so.9"]))

    nombres.clear()
    ctypes.util.find_library = lambda nombre: None
    ctypes.CDLL = cdll_que_nunca_abre
    theme._fuentes_cargadas = None
    c("  y si no hay ninguna no lanza: la letra es un adorno",
      (theme.cargar_fuentes(), nombres), (False, ["libfontconfig.so.1"] * 2))
finally:
    ctypes.CDLL, ctypes.util.find_library, sys.platform, theme._fuentes_cargadas = real

# --- familia(): una enumeración para las tres -----------------------------------
try:
    import tkinter as tk
    from tkinter import font as tkfont, ttk
except Exception as e:                                   # noqa: BLE001
    print(f"  (saltado) no hay tkinter: {e}")
    sys.exit(c.report())

llamadas: list[int] = []
real_families = tkfont.families
guardado = (dict(theme._elegidas), theme._instaladas, theme._fuentes_cargadas)
try:
    theme._fuentes_cargadas = False             # solo cuenta lo que diga Tk
    tkfont.families = lambda *a, **k: (llamadas.append(1), ("Noto Sans", "DejaVu Sans"))[1]
    theme._elegidas.clear()
    theme._instaladas = None
    elegidas = [theme.familia(rol) for rol in ("texto", "fuerte", "mono")]
    c("las tres familias se eligen con UNA enumeración", len(llamadas), 1)
    c("  y la elección es la de siempre (la primera instalada de cada papel)",
      elegidas, ["Noto Sans", "Noto Sans", "TkFixedFont"])
    theme.familia("texto")
    c("  repetir no vuelve a preguntar", len(llamadas), 1)

    def sin_raiz(*a, **k):
        """`families()` antes de que exista ningún Tk."""
        llamadas.append(1)
        raise RuntimeError("Too early to use font.families(): no default root window")

    llamadas.clear()
    tkfont.families = sin_raiz
    theme._elegidas.clear()
    theme._instaladas = None
    theme.familia("texto")
    theme.familia("fuerte")
    c("sin Tk todavía no se apunta la enumeración: se reintenta",
      (theme._instaladas, len(llamadas)), (None, 2))
finally:
    tkfont.families = real_families
    theme._elegidas.clear()
    theme._elegidas.update(guardado[0])
    theme._instaladas, theme._fuentes_cargadas = guardado[1], guardado[2]

# --- con pantalla ----------------------------------------------------------------
try:
    raiz = tk.Tk()
    raiz.withdraw()
except Exception as e:                                   # noqa: BLE001
    print(f"  (saltado) no hay entorno gráfico: {e}")
    sys.exit(c.report())

theme.nitidez()
theme.apply(raiz)


def ficha_de(r):
    """La ficha de letra del intérprete de `r`, o `None`."""
    return theme._LETRA.get(id(r.tk))


def medidas_directas(r, letra) -> tuple[int, int, int]:
    """`(linespace, ascent, tamaño)` como los daba una `Font` nueva por llamada."""
    f = tkfont.Font(root=r, font=letra)
    m = f.metrics()
    return m["linespace"], m["ascent"], f.actual("size")


# la tabla da lo mismo que medir con una Font nueva, a cualquier escala
distintas, valores = [], {}
escala_real = float(raiz.tk.call("tk", "scaling"))
for escala in (1.0, 1.3333, 2.0, 2.6667):
    raiz.tk.call("tk", "scaling", escala)
    for rol in ROLES:
        letra = theme.fuente(rol)
        tabla = theme._metricas(raiz, letra)
        if tabla != medidas_directas(raiz, letra):
            distintas.append((escala, rol, tabla, medidas_directas(raiz, letra)))
        valores[(escala, rol)] = tabla
    c(f"a escala {escala}: relleno_control = la fórmula de siempre con la Font de siempre",
      [theme.relleno_control(raiz, alto, rol, lados) for alto, rol, lados in
       ((34, "fuerte", 16), (24, "pista", 8), (42, "fuerte", 24), (34, "mono", 12))],
      [(theme.medida(lados),
        max(0, (icons.px(raiz, alto) - medidas_directas(raiz, theme.fuente(rol))[0]
                - 2 * icons.px(raiz, 1)) // 2))
       for alto, rol, lados in ((34, "fuerte", 16), (24, "pista", 8), (42, "fuerte", 24),
                                (34, "mono", 12))])
c("la tabla = tkfont.Font(...).metrics() y .actual('size'), en los 10 roles y 4 escalas",
  distintas, [])
c("  una fuente sujeta NO se queda con la escala a la que se abrió",
  valores[(2.6667, "texto")][0] > valores[(1.0, "texto")][0], True)
c("  y son enteros",
  all(isinstance(x, int) for v in valores.values() for x in v), True)
raiz.tk.call("tk", "scaling", escala_real)

# la letra de un estilo (cadena) y la del rol (tupla) son la misma entrada
fuerte_estilo = ttk.Style(raiz).lookup("Primary.TButton", "font")
c("la cadena de un estilo y la tupla del rol comparten clave",
  theme._clave_letra(raiz, fuerte_estilo), theme._clave_letra(raiz, theme.fuente("fuerte")))
antes = len(ficha_de(raiz).fuentes)
theme._metricas(raiz, fuerte_estilo)
c("  y no se mide otra vez", len(ficha_de(raiz).fuentes), antes)

# las fuentes de los roles: una vez, y la misma
c("fuente_tk devuelve la misma Font cada vez",
  theme.fuente_tk(raiz, "rotulo") is theme.fuente_tk(raiz, "rotulo"), True)
c("  y mide como una nueva",
  theme.fuente_tk(raiz, "rotulo").measure(theme.rotulo("Este dispositivo")),
  tkfont.Font(root=raiz, font=theme.fuente("rotulo")).measure(theme.rotulo("Este dispositivo")))
c("ancho_rotulo mide con la de su rol",
  theme.ancho_rotulo(raiz, "Este dispositivo"),
  theme.fuente_tk(raiz, "rotulo").measure(theme.rotulo("Este dispositivo")))

# la ancla: oculta para Python, presente para Tcl, sin mapear
c("la ancla existe en Tcl", int(raiz.tk.call("winfo", "exists", theme.ANCLA)), 1)
c("  no está en winfo_children() (las pruebas y las pantallas recorren el árbol)",
  [w for w in raiz.winfo_children() if str(w) == theme.ANCLA], [])
c("  y no está mapeada: no se pinta", int(raiz.tk.call("winfo", "ismapped", theme.ANCLA)), 0)

# sujetar sirve: medir una fuente sujeta es mucho más rápido que una suelta
def mejor_us(f, veces: int = 15) -> float:
    """Devuelve lo que tarda `f` en su mejor vuelta, en microsegundos."""
    mejor = float("inf")
    for _ in range(veces):
        t = time.perf_counter()
        f()
        mejor = min(mejor, time.perf_counter() - t)
    return mejor * 1e6


suelta = tkfont.Font(root=raiz, font=theme.fuente("texto"))
sujeta = theme.fuente_tk(raiz, "texto")
us_suelta, us_sujeta = mejor_us(suelta.metrics), mejor_us(sujeta.metrics)
if us_suelta < 100:
    print(f"  (saltado) aquí medir una fuente suelta cuesta {us_suelta:.0f} µs: "
          "no reabre la cara (es cosa de Xft)")
else:
    c(f"sujeta: metrics() es al menos 10 veces más rápido ({us_sujeta:.0f} µs frente a "
      f"{us_suelta:.0f} µs)", us_sujeta * 10 < us_suelta, True)

# cuántas Font se crean: una por letra distinta, no una por control
creadas: list[int] = []
original_init = tkfont.Font.__init__


def contado(self, *a, **k):
    """`Font.__init__` que apunta cada fuente que se crea."""
    creadas.append(1)
    original_init(self, *a, **k)


tkfont.Font.__init__ = contado
try:
    r2 = tk.Tk()
    r2.withdraw()
    theme.apply(r2)
    en_apply = len(creadas)
    c("apply() crea una Font por letra distinta (hoy 5), no una por relleno_control (25)",
      (en_apply <= 8, en_apply == len(ficha_de(r2).fuentes)), (True, True))
    marco = ttk.Frame(r2)
    for i in range(12):
        theme.chip(marco, f"c{i}", "Ok." if i % 2 else "", "alert" if i % 3 == 0 else None)
    for tono in ("Ambar.", "Rojo.", "Azul."):
        theme.aviso(marco, "Título", "Cuerpo", tono=tono)
    for estilo in ("Primary.TButton", "Quiet.TButton", "TButton", "Tonal.TButton"):
        theme.boton_icono(ttk.Button(marco, text="x", style=estilo), "parejas", theme.ACENTO)
    theme.etiqueta_icono(marco, "ok", theme.TINTA3)
    theme.linea_estado(marco, "llave", "texto", "Abrir")
    c("  12 chips, 3 avisos, 4 botones con icono y 2 filas más: ninguna Font nueva",
      len(creadas), en_apply)
finally:
    tkfont.Font.__init__ = original_init

# …y sin ancla (no se pudo hacer el lienzo) funciona igual, solo más despacio
r3 = tk.Tk()
r3.withdraw()
r3.tk.call("frame", theme.ANCLA)                # el nombre ya está cogido: canvas falla
spec = theme.fuente("fuerte")
c("sin poder hacer la ancla, la tabla da las mismas medidas",
  (theme._metricas(r3, spec) == medidas_directas(r3, spec), ficha_de(r3).ancla),
  (True, ""))

# olvidar(): la ficha, la ancla y las fuentes con nombre se van con el intérprete
r4 = tk.Tk()
r4.withdraw()
theme.apply(r4)
theme.fuente_tk(r4, "mono")
suyas = {f.name for f in ficha_de(r4).fuentes.values()}
c("antes de olvidar, sus fuentes existen en Tk",
  suyas <= set(r4.tk.splitlist(r4.tk.call("font", "names"))), True)
interp4 = r4.tk
theme.olvidar(interp4)
c("olvidar suelta la ficha", id(interp4) in theme._LETRA, False)
c("  destruye la ancla", int(r4.tk.call("winfo", "exists", theme.ANCLA)), 0)
c("  y borra sus fuentes con nombre",
  suyas & set(r4.tk.splitlist(r4.tk.call("font", "names"))), set())
theme.olvidar(interp4)
c("  olvidar dos veces no falla", id(interp4) in theme._LETRA, False)
r4.destroy()

# el aviso de fallo del servicio: un intérprete tras otro en el mismo hilo
ra = tk.Tk()
ra.withdraw()
theme.apply(ra)
fuente_a, ficha_a, interp_a = theme.fuente_tk(ra, "texto"), ficha_de(ra), ra.tk
ra.destroy()                                    # como al cerrarse la ventanita…
theme.olvidar(interp_a)                         # …y lo que hace `tk.aviso_fallo()` después
icons.olvidar(interp_a)
rb = tk.Tk()
rb.withdraw()
theme.apply(rb)
fuente_b, ficha_b = theme.fuente_tk(rb, "texto"), ficha_de(rb)
c("el segundo intérprete tiene su ficha y sus fuentes, no las del primero",
  (ficha_b is not ficha_a, fuente_b is not fuente_a, ficha_b.interp is rb.tk,
   ficha_a.fuentes, ficha_a.ancla), (True, True, True, {}, None))
c("  y funcionan: miden", fuente_b.measure("Hola") > 0, True)
c("  y la tabla del segundo da las medidas de siempre",
  theme._metricas(rb, theme.fuente("texto")), medidas_directas(rb, theme.fuente("texto")))
c("  `_LETRA` tiene los intérpretes vivos y no el cerrado",
  sorted(theme._LETRA) == sorted({id(raiz.tk), id(r2.tk), id(r3.tk), id(rb.tk)}), True)

for r in (rb, r3, r2, raiz):
    theme.olvidar(r.tk)
    r.destroy()
c("al olvidarlos todos no queda letra de ningún intérprete", theme._LETRA, {})
sys.exit(c.report())
