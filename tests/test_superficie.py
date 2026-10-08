#!/usr/bin/env python3
"""La superficie de los controles redondeados la ponen bits de estado, no estilos.

Las piezas de un control redondeado son transparentes por fuera de la forma, y
por las esquinas asoma el `background` del control: tiene que ser el color de
la superficie donde cae. Cada estilo redondeado lleva un `style.map` de su
`background` por los bits de estado libres de ttk (`user1`…`user3`), y
`theme._asentar()` enciende los de la superficie del padre al aparecer el
control. Aquí se prueba, en el tema claro y en el oscuro:

- que el mapa devuelve cada superficie, en todos los estilos redondeados y los
  que heredan de ellos por el nombre, y también con el control pulsado, con
  el ratón encima, con foco, desactivado…;
- que cada control, puesto en cada superficie, queda con el fondo de esa
  superficie, sin cambiar de estilo;
- que nada de eso crea, configura ni mapea un estilo con la ventana abierta
  (ningún `<<ThemeChanged>>`);
- que una superficie sin bits cae sobre la más parecida y avisa, y que las
  caras de botón fuera de la paleta pasan a su variante, ya creada;
- y, donde se puede capturar la pantalla (X11 con ImageMagick), que los
  cuatro píxeles de las esquinas de cada control son de la superficie.
"""

from __future__ import annotations

import gc
import shutil
import subprocess
import sys

from _harness import Checks

c = Checks("superficie: las esquinas de los controles redondeados, por bits de estado")

from ui import icons, theme  # noqa: E402

try:
    import tkinter as tk
    from tkinter import ttk
    tk.Tk().destroy()
except Exception as e:                                   # sin entorno gráfico
    print(f"  (saltado) no hay entorno gráfico: {e}")
    sys.exit(c.report())

CLASES = {"TButton", "Toolbutton", "TEntry", "TCombobox", "TSpinbox", "TFrame",
          "TLabel", "TProgressbar"}
"""Cómo acaban los estilos redondeados: de ahí sale la clase de widget que se prueba."""

COLUMNAS = 8
"""Controles por fila en cada panel."""

ESQUINAS = {"Segmento.Toolbutton": "1111", "Primero.Segmento.Toolbutton": "1001",
            "Medio.Segmento.Toolbutton": "0000", "Ultimo.Segmento.Toolbutton": "0110"}
"""Las esquinas redondeadas del grupo de botones (arriba izq., arriba der., abajo der., abajo izq.)."""

FINOS = ("Capa.TLabel", "Horizontal.TProgressbar")
"""Los estilos de esquina de 2 px (`theme.RADIO_FINO`): el píxel de la esquina sale mezclado."""

OTROS_ESTADOS = ([], ["active"], ["pressed"], ["disabled"], ["focus"], ["selected"],
                 ["readonly"], ["invalid"], ["active", "focus"], ["pressed", "focus"])
"""Los estados de ttk que un control puede llevar además de los bits de superficie."""

REPRESENTANTES = ("TButton", "Primary.TButton", "Tonal.TButton", "Danger.TButton",
                  "Quiet.TButton", "Nav.TButton", "Segmento.Toolbutton", "TEntry")
"""Los estilos que se enseñan además en cada estado en la captura de pantalla."""

ESTADOS_DE_VISTA = ([], ["active"], ["pressed"], ["focus"], ["disabled"], ["invalid"])
"""Los estados con los que se captura cada representante."""


def estilos_redondeados() -> list[str]:
    """Devuelve cada estilo redondeado del tema y los que heredan de él por el nombre."""
    salida = []
    for base, redondo in theme._REDONDOS.items():
        if not redondo:
            continue
        salida.append(base)
        for fin, prefijos in theme._PREFIJOS_SOBRE.items():
            if base.endswith(fin):
                salida += [p + base for p in prefijos]
    return salida


def crear(padre, estilo: str, variable):
    """Crea el widget de la clase que corresponde a ese estilo."""
    clase = estilo.rsplit(".", 1)[-1]
    if clase == "TButton":
        return ttk.Button(padre, text="Ok", style=estilo)
    if clase == "Toolbutton":
        return ttk.Radiobutton(padre, text="Ok", value=estilo, variable=variable,
                               style=estilo)
    if clase == "TEntry":
        return ttk.Entry(padre, width=5, style=estilo)
    if clase == "TCombobox":
        return ttk.Combobox(padre, width=4, values=("a",), style=estilo)
    if clase == "TSpinbox":
        return ttk.Spinbox(padre, width=3, from_=0, to=5, style=estilo)
    if clase == "TFrame":
        return ttk.Frame(padre, width=60, height=26, style=estilo)
    if clase == "TLabel":
        return ttk.Label(padre, text="chip", style=estilo)
    if clase == "TProgressbar":
        return ttk.Progressbar(padre, length=60, value=40, style=estilo)
    raise LookupError(clase)


class Pantalla:
    """Los píxeles de una ventana, capturados con `import` de ImageMagick (solo X11).

    Se lee con las coordenadas de la pantalla (`winfo_rootx()`…), no con las
    de la ventana.

    Args:
        raiz: La ventana, ya dibujada.
    """

    def __init__(self, raiz) -> None:
        raiz.update()
        self.origen = raiz.winfo_rootx(), raiz.winfo_rooty()
        r = subprocess.run(["import", "-depth", "8", "-window", str(raiz.winfo_id()),
                            "ppm:-"], capture_output=True, timeout=60)
        if r.returncode != 0:
            raise OSError(r.stderr.decode("utf-8", "replace")[:200])
        datos, trozos = r.stdout, []
        posicion = 0
        while len(trozos) < 4:                      # P6, «ancho alto», máximo y los píxeles
            if datos[posicion:posicion + 1] == b"#":
                posicion = datos.index(b"\n", posicion) + 1
                continue
            fin = posicion
            while datos[fin:fin + 1] not in b" \n\t":
                fin += 1
            trozos.append(datos[posicion:fin])
            posicion = fin + 1
        if trozos[0] != b"P6" or trozos[3] != b"255":
            raise OSError("ImageMagick no ha dado un PPM de 8 bits")
        self.ancho, self.alto = int(trozos[1]), int(trozos[2])
        self.pixeles = datos[posicion:]

    def en(self, x: int, y: int) -> str:
        """Devuelve el píxel (x, y) de la pantalla como «#RRGGBB» en mayúsculas."""
        i = 3 * ((y - self.origen[1]) * self.ancho + x - self.origen[0])
        return "#%02X%02X%02X" % tuple(self.pixeles[i:i + 3])


def puede_capturar(raiz) -> str:
    """Dice por qué no se puede capturar la pantalla, o `""` si se puede."""
    if not sys.platform.startswith("linux"):
        return "solo se captura en X11"
    if not shutil.which("import"):
        return "no hay ImageMagick (`import`)"
    if raiz.winfo_screendepth() < 24:
        return f"la pantalla es de {raiz.winfo_screendepth()} bits: los colores no son exactos"
    return ""


def capturar(raiz) -> tuple[Pantalla | None, str]:
    """Captura la ventana: la captura y `""`, o `None` y por qué no ha podido."""
    try:
        return Pantalla(raiz), ""
    except (OSError, subprocess.SubprocessError) as e:
        return None, f"no se ha podido capturar: {e}"


def esquinas_de(w, forma: str = "1111") -> list[tuple[int, int]]:
    """Devuelve los píxeles de las esquinas redondeadas de un widget, en pantalla."""
    x, y, ancho, alto = w.winfo_rootx(), w.winfo_rooty(), w.winfo_width(), w.winfo_height()
    puntas = [(x, y), (x + ancho - 1, y), (x + ancho - 1, y + alto - 1), (x, y + alto - 1)]
    return [p for p, marca in zip(puntas, forma) if marca == "1"]


def rgb(color: str) -> list[int]:
    """Devuelve los tres canales de un «#RRGGBB»."""
    return [int(color[i:i + 2], 16) for i in (1, 3, 5)]


class Esquinas:
    """Revisa las esquinas de los controles de un panel contra su superficie.

    Con una esquina de 4 px el píxel de más afuera cae fuera de la forma y es
    de la superficie, sin más. Con la de 2 px (`FINOS`) la forma lo cubre un
    poco: Tk compone ese píxel de la pieza, con su alfa `α`, sobre el fondo del
    control. Así que el mismo píxel sobre el papel y sobre otra superficie se
    diferencian en `(1 - α) * (superficie - papel)`, canal a canal: el mismo
    factor en los tres, que se mide y no se supone. Sobre un fondo equivocado
    (el papel donde tocaba la tarjeta) ese factor sale cero o los canales no
    cuadran. Se mide sobre el papel (el primer panel de cada serie) y se
    compara sobre los demás.

    No se compara con el color del borde: lo que tiene la pieza en ese píxel
    lo decide el pintor (con SVG, la esquina mezcla también algo del relleno).

    Args:
        papel: La superficie del primer panel.
    """

    TOLERANCIA = 2
    """Lo que se admite de diferencia por canal frente a lo que da el factor medido."""

    SEPARADOS = 8
    """Los niveles que tienen que separarse papel y superficie en un canal para medir con él."""

    def __init__(self, papel: str) -> None:
        self.papel = papel
        self.en_papel: dict[tuple, list[int]] = {}

    def revisar(self, clave, pantalla: Pantalla, w, estilo: str, superficie: str) -> list:
        """Devuelve las esquinas de `w` que no salen como deben sobre `superficie`.

        Args:
            clave: Quien es este control en todos los paneles de la serie.
            estilo: Su estilo: de él salen las esquinas redondeadas y si es fino.
        """
        malas = []
        base = rgb(superficie)
        fino = estilo in FINOS
        for k, punto in enumerate(esquinas_de(w, ESQUINAS.get(estilo, "1111"))):
            visto = rgb(pantalla.en(*punto))
            if not fino:
                if visto != base:
                    malas.append((clave, punto, visto, base))
                continue
            if superficie == self.papel:
                self.en_papel.setdefault((clave, k), visto)
                continue
            ref = self.en_papel.get((clave, k))
            if ref is None:
                malas.append((clave, punto, visto, "sin la medida sobre el papel"))
                continue
            papel = rgb(self.papel)
            canales = [(v - r, b - p) for v, r, b, p in zip(visto, ref, base, papel)
                       if abs(b - p) >= self.SEPARADOS]
            if not canales:
                continue                # superficie casi igual al papel: no se distingue
            factor = sum(d for d, _ in canales) / sum(t for _, t in canales)
            esperado = [round(r + factor * (b - p)) for r, b, p in zip(ref, base, papel)]
            if (not 0.15 < factor < 1.05
                    or any(abs(v - x) > self.TOLERANCIA for v, x in zip(visto, esperado))):
                malas.append((clave, punto, visto, esperado, round(factor, 2)))
        return malas


def probar_tema(tema: str) -> None:
    """Prueba el mecanismo con el tema `tema`, en un intérprete suyo."""
    theme.usar(tema)
    raiz = tk.Tk()
    raiz.tk.call("tk", "scaling", 1.3333)
    raiz.geometry("+0+0")
    theme.apply(raiz)
    raiz.configure(background=theme.PAPEL)
    style = ttk.Style(raiz)
    asiento = theme._asientos[id(raiz.tk)]
    papel = theme._hex(raiz, theme.PAPEL)
    estilos = estilos_redondeados()
    p = f"{tema}: "

    # 1. la paleta cabe en los bits y el mapa devuelve cada superficie
    esperadas = {theme._hex(raiz, f) for f, _ in theme._superficies().values()} - {papel}
    c(p + "las superficies que no son el papel caben en los siete bits",
      (len(esperadas) <= len(theme._BITS), set(asiento.bits) == esperadas), (True, True))
    c(p + "cada una tiene una combinación distinta",
      len(set(asiento.bits.values())), len(asiento.bits))
    c(p + "todos los estilos redondeados tienen el papel por fondo",
      [e for e in theme._REDONDOS if theme._REDONDOS[e]
       and theme._hex(raiz, style.lookup(e, "background")) != papel], [])
    malos = []
    for estilo in estilos:
        for otros in OTROS_ESTADOS:
            if theme._hex(raiz, style.lookup(estilo, "background", otros)) != papel:
                malos.append((estilo, "papel", otros))
            for color, bits in asiento.bits.items():
                dado = theme._hex(raiz, style.lookup(estilo, "background", [*bits, *otros]))
                if dado != color:
                    malos.append((estilo, color, bits, otros, dado))
    c(p + f"el mapa da cada superficie en {len(estilos)} estilos (los derivados la heredan)"
      " y en todos los estados", malos[:5], [])

    # 2. cada control, en cada superficie, con el fondo de esa superficie
    raiz.update()
    raiz.tk.eval('set ::prdrive_tema 0; bind . <<ThemeChanged>> '
                 '{+ if {"%W" eq "."} {incr ::prdrive_tema}}')
    variable = tk.StringVar(raiz)
    motivo = puede_capturar(raiz)
    capturados = comprobados = 0
    sin_clase, ajenos, estilos_cambiados, sin_esquina = [], [], [], []
    esquinas = Esquinas(papel)
    for sup, (fondo, _letra) in theme._superficies().items():
        esperado = theme._hex(raiz, fondo)
        marco = ttk.Frame(raiz, style=f"{sup}TFrame", padding=theme.E4)
        marco.pack(anchor="nw")
        controles = []
        for n, estilo in enumerate(estilos):
            try:
                w = crear(marco, estilo, variable)
            except LookupError as e:
                sin_clase.append(str(e))
                continue
            w.grid(row=n // COLUMNAS, column=n % COLUMNAS, padx=theme.E1, pady=theme.E1)
            controles.append((estilo, w))
        fila = len(estilos) // COLUMNAS + 1
        for n, base in enumerate(REPRESENTANTES):
            for k, estados in enumerate(ESTADOS_DE_VISTA):
                w = crear(marco, base, variable)
                w.grid(row=fila + n, column=k, padx=theme.E1, pady=theme.E1)
                if estados:
                    w.state(estados)
                controles.append((base, w))
        raiz.update()
        for estilo, w in controles:
            comprobados += 1
            propio = str(w.cget("style"))
            if propio != estilo:
                estilos_cambiados.append((estilo, propio))
            visto = theme._hex(raiz, style.lookup(propio or w.winfo_class(), "background",
                                                  w.state()))
            if visto != esperado:
                ajenos.append((sup, estilo, w.state(), visto, esperado))
        pantalla, motivo = capturar(raiz) if not motivo else (None, motivo)
        if pantalla:
            interior = marco.winfo_rootx() + 4, marco.winfo_rooty() + 4
            if pantalla.en(*interior) != esperado:
                motivo = f"la captura no es de la ventana ({pantalla.en(*interior)} y no {esperado})"
            else:
                capturados += 1
                for n, (estilo, w) in enumerate(controles):
                    sin_esquina += [(sup, estilo, w.state(), *mala) for mala in
                                    esquinas.revisar(n, pantalla, w, estilo, esperado)]
        for _estilo, w in controles:
            w.destroy()
        marco.destroy()
    c(p + "todos los estilos redondeados tienen su clase de widget", sin_clase, [])
    c(p + f"los {comprobados} controles de {len(theme._superficies())} superficies "
      "no cambian de estilo", estilos_cambiados[:5], [])
    c(p + "cada uno ve por fondo el de su superficie (consulta de ttk)", ajenos[:5], [])
    if motivo:
        print(f"  (saltado) {p}las esquinas en pantalla: {motivo}")
    else:
        c(p + f"las esquinas de cada control, en {capturados} capturas, son de su superficie",
          sin_esquina[:5], [])

    # 3. sobre un tk.Frame del color de cada superficie (sin pasar por su estilo)
    sin_esquina, ajenos = [], []
    colores = [papel, *asiento.bits]
    esquinas = Esquinas(papel)
    for color in colores:
        marco = tk.Frame(raiz, background=color, padx=theme.E4, pady=theme.E4)
        marco.pack(anchor="nw")
        controles = [(e, crear(marco, e, variable)) for e in estilos
                     if e.rsplit(".", 1)[-1] != "TFrame" or e == "Card.TFrame"]
        for n, (_e, w) in enumerate(controles):
            w.grid(row=n // COLUMNAS, column=n % COLUMNAS, padx=theme.E1, pady=theme.E1)
        raiz.update()
        for estilo, w in controles:
            visto = theme._hex(raiz, style.lookup(str(w.cget("style")) or w.winfo_class(),
                                                  "background", w.state()))
            if visto != color:
                ajenos.append((color, estilo, visto))
        pantalla, motivo = capturar(raiz) if not motivo else (None, motivo)
        if pantalla:
            for n, (estilo, w) in enumerate(controles):
                sin_esquina += [(color, estilo, *mala) for mala in
                                esquinas.revisar(n, pantalla, w, estilo, color)]
        marco.destroy()
    c(p + f"sobre un tk.Frame de los {len(colores)} colores, cada control ve el suyo",
      ajenos[:5], [])
    if not motivo:
        c(p + "  y sus esquinas en pantalla", sin_esquina[:5], [])

    # 4. un color sin bits cae sobre el más parecido y avisa una vez
    avisos = []
    previo = theme._avisar_superficie
    theme._avisar_superficie = lambda fondo, cercana: avisos.append((fondo, cercana))
    try:
        raro = tk.Frame(raiz, background="#123456")
        raro.pack()
        a = ttk.Button(raro, text="a")
        b = ttk.Entry(raro)
        a.pack()
        b.pack()
        cerca = tk.Frame(raiz, background=papel[:-1] + ("0" if papel[-1] != "0" else "1"))
        cerca.pack()
        e = ttk.Button(cerca, text="e")
        e.pack()
        raiz.update()
    finally:
        theme._avisar_superficie = previo
    mas_cercana = min([papel, *asiento.bits], key=lambda s: sum(
        (int(s[i:i + 2], 16) - int("123456"[i - 1:i + 1], 16)) ** 2 for i in (1, 3, 5)))
    c(p + "un color sin superficie avisa una vez por color", len(avisos), 2)
    c(p + "  y cae sobre la más parecida", avisos[0] if avisos else None,
      ("#123456", mas_cercana))
    c(p + "  los controles quedan con sus bits, no con un estilo nuevo",
      (str(a.cget("style")), str(b.cget("style")), str(e.cget("style"))), ("", "", ""))
    c(p + "  y con el fondo de esa superficie",
      theme._hex(raiz, style.lookup("TButton", "background", a.state())), mas_cercana)
    c(p + "  uno casi igual al papel se asienta sin bits", e.state(), ())

    # 5. las caras de botón fuera de la paleta pasan a su variante, ya creada
    cara = ttk.Button(raiz, text="Guardar", style="Primary.TButton")
    cara.pack()
    sobre_cara = ttk.Label(cara, text="chip", style="Chip.TLabel")
    sobre_cara.place(x=2, y=2)
    raiz.update()
    acento = theme._hex(raiz, theme.ACENTO)
    c(p + "sobre la cara del acento, el chip pasa a la variante de ese color",
      str(sobre_cara.cget("style")), f"Sobre{acento[1:]}.Chip.TLabel")
    c(p + "  que existía antes de abrir ninguna ventana",
      str(sobre_cara.cget("style")) in asiento.variantes, True)
    c(p + "  y ve por fondo el de la cara",
      theme._hex(raiz, style.lookup(str(sobre_cara.cget("style")), "background",
                                    sobre_cara.state())), acento)
    c(p + "  sin bits encendidos", sobre_cara.state(), ())
    sobre_cara.destroy()
    cara.destroy()

    # 6. un control que se desmapea y vuelve a aparecer queda igual
    tarjeta = ttk.Frame(raiz, style="Gris.TFrame", padding=theme.E3)
    tarjeta.pack()
    boton = ttk.Button(tarjeta, text="Otra vez")
    boton.pack()
    raiz.update()
    antes = boton.state()
    boton.pack_forget()
    raiz.update()
    boton.pack()
    raiz.update()
    c(p + "al reaparecer conserva su superficie", (boton.state(), antes != ()),
      (antes, True))

    # 7. cambiar el estilo de un control ya asentado (la barra lateral de «Ajustes»
    # cambia «Nav» por «NavSel») no le quita la superficie: los bits son del widget
    tarjeta = ttk.Frame(raiz, style="Card.TFrame", padding=theme.E3)
    tarjeta.pack()
    lateral = ttk.Button(tarjeta, text="Apartado", style="Nav.TButton")
    lateral.pack()
    raiz.update()
    bits = lateral.state()
    lateral.configure(style="NavSel.TButton")
    raiz.update()
    c(p + "al cambiar de estilo conserva los bits de su superficie",
      (lateral.state(), bits != ()), (bits, True))
    c(p + "  y el estilo nuevo ve esa superficie por fondo",
      theme._hex(raiz, style.lookup("NavSel.TButton", "background", lateral.state())),
      theme._hex(raiz, theme.SUPERFICIE))
    tarjeta.destroy()

    # 8. nada de lo anterior mandó un <<ThemeChanged>>
    c(p + "ningún <<ThemeChanged>> en todo lo anterior",
      int(raiz.tk.eval("set ::prdrive_tema")), 0)

    theme.olvidar(raiz.tk)
    icons.olvidar(raiz.tk)
    raiz.destroy()
    gc.collect()


for tema in ("claro", "oscuro"):
    probar_tema(tema)
theme.usar("claro")

sys.exit(c.report())
