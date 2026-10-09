"""Hijo de la medida de la lista de parejas: una variante, un tamaño (etapa 2, R3).

TEMPORAL, como todo `etapa2_*`: lo borra la tarea 15 de la etapa 2.

    python etapa2_tabla.py VARIANTE N        (por `entrada.py etapa2_tabla VARIANTE N`)

`VARIANTE` es `ref` (la `ListaParejas` del árbol: siete widgets por fila, nueve desde
que cada chip va en una celda con el color de su fila),
`ligera` (`etapa2_ligera.ListaLigera`, cinco) o `lienzo` (`etapa2_lienzo.ListaLienzo`,
ninguno: un solo `tk.Canvas`); `N`, el número de filas: 5, 10, 20 o 50.

Es un proceso nuevo por medida, en frío, como los del driver: importa `ui` antes
que `tkinter`, declara la densidad, abre un `Tk()`, pone el tema, calienta con una
ventana y mide en una ventana oculta con una tarjeta (`Card.TFrame`):

- `construir`: crear la ventana y la lista, ponerle las filas y enseñarla;
- `elegir`: elegir otra fila (`avisar=False`);
- `refrescar`: `poner()` de los mismos nombres con un tercio de los estados cambiados;
- `reemplazar`: `poner()` de filas con nombres nuevos;
- `widgets`: los widgets de la lista tras `construir`.

Cada medida va seguida de un `update()`. Tras cada `poner()` se compara lo que la
lista DIBUJA (el texto de sus etiquetas, o de los elementos del lienzo) con lo que
tiene que decir según el modelo: nombre, «local ↔ remoto», modo y estado. Si
difiere, el hijo falla: una lista más rápida que enseña otra cosa no decide nada.

Variables: `BENCH_DEVICE` (un dispositivo de muestra: su `.prdrive/` lleva el
código), `BENCH_APP` (el código, si no es el del dispositivo) y `BENCH_OUT`.
"""

from __future__ import annotations

import os
import sys
import time
import traceback
from pathlib import Path

VARIANTES = ("ref", "ligera", "lienzo")
TAMANOS = (5, 10, 20, 50)


def _ruta_del_codigo() -> str:
    """Pone el código de la aplicación en `sys.path` y se coloca en él, como el driver."""
    app = os.environ.get("BENCH_APP")
    if not app and os.environ.get("BENCH_DEVICE"):
        app = os.path.join(os.environ["BENCH_DEVICE"], ".prdrive")
    app = os.path.realpath(app or Path(__file__).resolve().parents[2])
    sys.path.insert(0, app)
    os.chdir(app)
    return app


def escribir(escenario: str, ms: float, detalle: dict) -> None:
    """Deja una línea para el orquestador (`utiles.escribir`)."""
    import utiles
    utiles.escribir(escenario, ms, detalle)


# ---------------------------------------------------------------- filas de muestra
PATRONES = (
    # (modo, la usa este dispositivo, aviso, estado, origen)
    ("bisync", True, None, "ok", "catalogo"),
    ("up", True, None, "—", "catalogo"),
    ("down", True, None, "—", "catalogo"),
    ("bisync", True, None, "ok", "catalogo"),
    ("bisync", True, None, "ok", "catalogo"),
    ("up", False, None, "—", "catalogo"),                           # no se usa aquí
    ("up-mirror", True, "espejo: borra en destino", "—", "catalogo"),   # peligro
    ("bisync", True, "pide resync", "ok", "catalogo"),              # aviso
)
"""Los ocho tipos de fila: cada modo, un espejo, una apagada y una con aviso."""
NOMBRES = ("documentos", "fotos", "musica", "trabajo", "notas", "videos", "copias",
           "proyectos")
CINCO = (0, 7, 6, 3, 5)
"""Las cinco filas de la captura del diseño: bien, aviso, espejo, bien y apagada."""


def filas_muestra(n: int, prefijo: str = ""):
    """Devuelve `n` filas de muestra (`pair_editor.CatalogRow`) con nombres distintos."""
    from ui.pair_editor import CatalogRow
    indices = CINCO if n == 5 else [i % len(PATRONES) for i in range(n)]
    filas = []
    for k, p in enumerate(indices):
        modo, en_pen, aviso, estado, origen = PATRONES[p]
        nombre = prefijo + NOMBRES[p] + ("" if n == 5 or k < len(PATRONES)
                                         else f"-{k // len(PATRONES) + 1}")
        filas.append(CatalogRow(nombre, modo, f"sync-data/{nombre}", f"nas:/datos/{nombre}",
                                estado, aviso, en_pen, origen, ()))
    return filas


def variar(filas):
    """Devuelve las mismas filas con el estado de una de cada tres cambiado.

    Cambia si el dispositivo la usa: eso cambia su chip de estado, su casilla y
    su color, que es lo que `refrescar` tiene que tocar.
    """
    return [f._replace(en_pen=not f.en_pen) if i % 3 == 0 else f for i, f in enumerate(filas)]


def esperado(filas, del_catalogo: bool = False) -> list[tuple[str, str, str, str]]:
    """Devuelve lo que tiene que decir la lista de estas filas, según el modelo."""
    from ui import pair_editor
    return [(f.name, f"{f.local} ↔ {f.remote}", f.mode,
             pair_editor.row_status(f, del_catalogo)[1]) for f in filas]


def leer_ref(lista) -> list[tuple[str, str, str, str]]:
    """Devuelve lo que dicen las etiquetas de la `ListaParejas`, fila a fila.

    Las filas empiezan en la 2 de su rejilla (la 0 es la cabecera y la 1 la línea
    de arriba) y llevan en las columnas 1 a 4 el nombre, la ruta, el modo y el
    estado; la 0 es la casilla.
    """
    por_fila: dict[int, dict[int, str]] = {}
    for w in lista.marco.winfo_children():
        info = w.grid_info()
        if not info:
            continue
        fila, col = int(info["row"]), int(info["column"])
        if fila < 2 or col < 1:
            continue
        if w.winfo_class() == "TFrame" and w.winfo_children():
            w = w.winfo_children()[0]               # un chip va en la celda de su fila
        if w.winfo_class() == "TLabel":
            por_fila.setdefault(fila, {})[col] = str(w.cget("text"))
    return [(d[1], d[2], d[3], d[4]) for _, d in sorted(por_fila.items())]


def comprobar(lista, variante: str, filas) -> None:
    """Falla si lo que la lista dibuja no es lo que dicen sus filas.

    Raises:
        AssertionError: Con la primera fila que difiere y lo que había en cada lado.
    """
    visto = leer_ref(lista) if variante == "ref" else lista.leer()
    previsto = esperado(filas)
    if len(visto) != len(previsto):
        raise AssertionError(f"{variante}: dibuja {len(visto)} filas y son {len(previsto)}")
    for i, (a, b) in enumerate(zip(visto, previsto)):
        if tuple(a) != tuple(b):
            raise AssertionError(f"{variante}: la fila {i} dibuja {tuple(a)!r} y debería "
                                 f"decir {tuple(b)!r}")


def contar(widget) -> int:
    """Devuelve los widgets bajo `widget`, él incluido."""
    return 1 + sum(contar(h) for h in widget.winfo_children())


def ms(a: float, b: float) -> float:
    return round((b - a) * 1000, 1)


# ------------------------------------------------------------------------- el hijo
def medir(variante: str, n: int) -> None:
    """Hace las medidas de una variante con `n` filas y las deja en `BENCH_OUT`."""
    import ui  # noqa: F401  -- antes que tkinter: carga el Tk con Xft del runtime (Linux)
    from ui import icons, theme
    from ui import tk as uitk
    theme.nitidez()
    import tkinter as tk
    from tkinter import ttk

    raiz = tk.Tk()
    theme.apply(raiz)
    if variante == "ligera":
        import etapa2_ligera
        etapa2_ligera.preparar(raiz)
        clase = etapa2_ligera.ListaLigera
    elif variante == "lienzo":
        import etapa2_lienzo
        if not etapa2_lienzo.disponible(raiz):
            escribir("saltado", 0, {"motivo": "sin SVG", "variante": variante,
                                    "tk": str(raiz.tk.call("info", "patchlevel"))})
            raiz.destroy()
            return
        clase = etapa2_lienzo.ListaLienzo
    else:
        from ui.tk_pairs import ListaParejas as clase
    ttk.Label(raiz, text="prdrive").grid(padx=40, pady=20)
    raiz.update()
    # Calentamiento: la primera ventana de un proceso paga la conexión con el servidor
    # gráfico y las letras; no es lo que se mide.
    calentar = uitk.modal(raiz, "Calentamiento")
    ttk.Label(calentar, text="x").grid()
    uitk.ensenar(calentar)
    calentar.update()
    calentar.destroy()
    raiz.update()

    filas = filas_muestra(n)
    t0 = time.perf_counter()
    dlg = uitk.modal(raiz, "Parejas")
    tarjeta = ttk.Frame(dlg, style="Card.TFrame", padding=(theme.E5, theme.E4))
    tarjeta.grid(row=0, column=0)
    # La misma anchura para las tres: lo que pide la mayor, 940 px de diseño.
    ttk.Frame(tarjeta, style="Card.TFrame", width=icons.px(tarjeta, 940), height=1).grid(
        row=0, column=0)
    lista = clase(tarjeta, lambda: True, lambda: None)
    lista.marco.grid(row=1, column=0, sticky="ew")
    lista.poner(filas)
    uitk.ensenar(dlg)
    dlg.update()
    t1 = time.perf_counter()
    base = {"variante": variante, "n": n}
    escribir("construir", ms(t0, t1), base)
    escribir("widgets", contar(lista.marco), base)
    comprobar(lista, variante, filas)

    lista.elegir(lista.orden[0], avisar=False)      # que haya otra elegida de la que cambiar
    dlg.update()
    t0 = time.perf_counter()
    lista.elegir(lista.orden[1], avisar=False)
    dlg.update()
    escribir("elegir", ms(t0, time.perf_counter()), base)

    cambiadas = variar(filas)
    t0 = time.perf_counter()
    lista.poner(cambiadas)
    dlg.update()
    escribir("refrescar", ms(t0, time.perf_counter()), base)
    comprobar(lista, variante, cambiadas)

    nuevas = filas_muestra(n, prefijo="x-")
    t0 = time.perf_counter()
    lista.poner(nuevas)
    dlg.update()
    escribir("reemplazar", ms(t0, time.perf_counter()), base)
    comprobar(lista, variante, nuevas)

    escribir("_notes", 0, {
        "variante": variante, "n": n, "tk": str(raiz.tk.call("info", "patchlevel")),
        "python": sys.version.split()[0], "imagenes": len(raiz.image_names()),
        "pintadas": dict(icons.PINTADAS), "lista": lista.detalle() if hasattr(lista, "detalle") else {},
        "pantalla": f"{raiz.winfo_screenwidth()}x{raiz.winfo_screenheight()}"})
    raiz.destroy()


def main() -> None:
    variante, n = sys.argv[1], int(sys.argv[2])
    if variante not in VARIANTES:
        raise SystemExit(f"variante desconocida: {variante} (una de {', '.join(VARIANTES)})")
    _ruta_del_codigo()
    salida = 0
    try:
        medir(variante, n)
    except BaseException:                                 # noqa: BLE001
        escribir("_notes", 0, {"variante": variante, "n": n,
                               "error": traceback.format_exc()[-1800:]})
        salida = 1
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(salida)      # como el driver: lo medido ya está escrito y no se espera a Tk


if __name__ == "__main__":
    main()
