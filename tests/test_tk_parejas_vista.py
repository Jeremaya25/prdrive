#!/usr/bin/env python3
"""«Parejas» cambia en su sitio: lo que llega, lo que se elige y lo que se teclea.

Cada pieza se prueba contra lo que se vería si se dibujara de nuevo:

- `ListaParejas.poner()` con filas que van y vienen, se reordenan y cambian de
  chip dibuja lo mismo que una lista recién hecha con las filas finales (lo que
  lee `leer()` y cada elemento de su lienzo), y repetir las mismas filas no toca
  nada; elegir cambia dos filas, no todas. La lista es un solo widget, un lienzo
  (`ui/tk_tabla.py`, probada a fondo en `tests/test_tk_tabla.py`);
- los chips de una fila caen sobre el fondo de su fila, también cuando se elige
  (lo que asoma por sus esquinas);
- la pantalla entera: el catálogo que llega sin cambiar nada no rehace nada, el
  bloque del catálogo se crea al verlo por primera vez, «Avanzado» se construye
  al desplegarlo, lo que se edita a mano en `sync_config.toml` mientras la
  pantalla está abierta no se pisa, y una pantalla vuelta a poner (`aplicar()`)
  enseña lo que una recién abierta.
"""

from __future__ import annotations

import random
import re
import subprocess
import sys
import threading
import time

from _harness import Checks, sandbox
from _vista import leer_vista, visibles

from common import bisync, catalog, config_file, model, store

c = Checks("«Parejas» en su sitio")

try:
    import tkinter as tk
    from tkinter import messagebox, ttk
    raiz = tk.Tk()
    raiz.withdraw()
except Exception as e:                                   # sin entorno gráfico
    print(f"  (saltado) no hay entorno gráfico: {e}")
    sys.exit(c.report())

from ui import instantanea, pair_editor, segundo_plano, theme, tk_pairs  # noqa: E402
from ui import tk as uitk  # noqa: E402

errores: list[str] = []
raiz.report_callback_exception = (
    lambda tipo, valor, _tb: errores.append(f"{tipo.__name__}: {valor}"))
messagebox.showerror = lambda titulo, texto=None, **k: errores.append(str(texto))
messagebox.showinfo = lambda *a, **k: None
messagebox.askokcancel = lambda *a, **k: True

Fila = pair_editor.CatalogRow


def todos(widget) -> list:
    """El widget y todo lo que cuelga de él, escondido o no."""
    salida = [widget]
    for hijo in widget.winfo_children():
        salida += todos(hijo)
    return salida


def conjunto(widget) -> set:
    """Los widgets de debajo de `widget` (sin él), por nombre de Tk."""
    return {str(w) for w in todos(widget)} - {str(widget)}


def sin_chips(widget) -> set:
    """Lo mismo que `conjunto()`, sin los chips: se sustituyen cuando cambia lo que dicen."""
    return {str(w) for w in todos(widget)
            if w is not widget and "Chip" not in str(w.cget("style") if "style" in w.keys()
                                                     else "")}


def lista_nueva(padre, **k):
    """Una `ListaParejas` colocada en una tarjeta, como en la pantalla."""
    lista = tk_pairs.ListaParejas(padre, k.get("puede_dejar", lambda: True),
                                  k.get("al_elegir", lambda: None))
    lista.marco.grid(row=0, column=0, sticky="ew")
    return lista


def a_la_vista(cv) -> list[int]:
    """Los elementos del lienzo menos los textos ocultos que sujetan las letras."""
    return [i for i in cv.find_all() if "letra" not in cv.gettags(i)]


def elementos(lista) -> dict:
    """Cada elemento a la vista del lienzo de la lista, con lo que se ve de él.

    Tipo, sitio y aspecto, sin las etiquetas internas de cada fila (`r<n>`), que
    dependen del orden en que llegaron.
    """
    cv = lista.marco
    salida = {}
    for i in a_la_vista(cv):
        tipo = cv.type(i)
        claves = {"rectangle": ("fill", "outline"), "text": ("text", "fill", "font"),
                  "image": ("image",)}.get(tipo, ())
        etiquetas = tuple(sorted(t for t in cv.gettags(i)
                                 if not (t[:1] == "r" and t[1:].isdigit()) and t != "current"))
        salida[i] = (tipo, tuple(round(float(x)) for x in cv.coords(i)),
                     tuple(str(cv.itemcget(i, k)) for k in claves), etiquetas)
    return salida


def dibujo(lista) -> list:
    """Todo lo que dibuja la lista, ordenado: el orden en que se dibujó no cuenta."""
    return sorted(elementos(lista).values())


# ---------------------------------------------------------------------------
# 1. La lista, sola
# ---------------------------------------------------------------------------
MODOS = ("bisync", "up", "down", "up-mirror", "down-mirror")
ESTADOS = ("ok", "fresh", "broken", "—")
ORIGENES = (pair_editor.ORIGEN_CATALOGO, pair_editor.ORIGEN_LOCAL,
            pair_editor.ORIGEN_HUERFANA, pair_editor.ORIGEN_SIN_USAR)
LOCALES = ("sync-data/a", "docs", "sync-data/una-carpeta-algo-mas-larga", "fotos/2026")


def fila_de(rng: random.Random, nombre: str) -> Fila:
    """Una fila al azar: cualquier modo, estado, origen y uso."""
    modo = rng.choice(MODOS)
    espejo = modo in pair_editor.MIRROR_MODES
    return Fila(nombre, modo, rng.choice(LOCALES), f"nas:/R/{nombre}",
                rng.choice(ESTADOS),
                pair_editor.mirror_warning(modo) if espejo
                else rng.choice((None, "requiere resync")),
                rng.random() < 0.7, rng.choice(ORIGENES), ())


def cambiar(rng: random.Random, fila: Fila) -> Fila:
    """La misma pareja con algo distinto: el modo, el estado, el uso o la ruta."""
    campo = rng.choice(("mode", "estado", "en_pen", "local", "aviso"))
    otra = fila_de(rng, fila.name)
    return fila._replace(**{campo: getattr(otra, campo)})


def secuencia(rng: random.Random, pasos: int) -> list[tuple[list[Fila], bool]]:
    """Una secuencia de listas: se añaden, se quitan, se reordenan y cambian filas."""
    nombres = [f"p{i}" for i in range(9)]
    actuales: dict[str, Fila] = {}
    salida = []
    for _ in range(pasos):
        elegidos = rng.sample(nombres, rng.randint(0, 7))
        siguientes = {}
        for n in elegidos:
            previa = actuales.get(n)
            if previa is None:
                siguientes[n] = fila_de(rng, n)
            else:
                siguientes[n] = cambiar(rng, previa) if rng.random() < 0.4 else previa
        actuales = siguientes
        salida.append((list(actuales.values()), rng.random() < 0.3))
    return salida


def probar_la_lista(tema: str) -> None:
    """La lista en el tema `tema`, con un intérprete suyo."""
    theme.usar(tema)
    r = tk.Tk()
    r.withdraw()
    dlg = uitk.modal(r, "Parejas")
    tarjeta = ttk.Frame(dlg, style="Card.TFrame", padding=theme.E4)
    tarjeta.grid(row=0, column=0)
    p = f"{tema}: "

    # 1a. el diferencial: lo mismo que una lista hecha de nuevo con las filas finales
    rng = random.Random(7)
    lista = lista_nueva(tarjeta)
    distintas, comparadas = [], 0
    for n_seq in range(50):
        lista.poner([], False)
        for filas, del_cat in secuencia(rng, 5):
            lista.poner(filas, del_cat)
            if lista.elegida is None or rng.random() < 0.5:
                lista.elegir(rng.choice(lista.orden) if lista.orden else None,
                             avisar=False)
            sitio = ttk.Frame(tarjeta, style="Card.TFrame")
            sitio.grid(row=1, column=0)
            fresca = tk_pairs.ListaParejas(sitio, lambda: True, lambda: None)
            fresca.marco.grid(row=0, column=0, sticky="ew")
            fresca.poner(filas, del_cat)
            fresca.elegir(lista.elegida, avisar=False)
            comparadas += 1
            if (lista.leer(), dibujo(lista)) != (fresca.leer(), dibujo(fresca)):
                distintas.append((n_seq, [f.name for f in filas], del_cat))
            if (lista.orden != fresca.orden or lista.elegida != fresca.elegida
                    or sorted(lista.filas) != sorted(fresca.filas)):
                distintas.append(("orden o elegida", n_seq))
            sitio.destroy()
    c(p + f"50 secuencias de filas que van, vienen y cambian ({comparadas} listas): "
      "siempre se dibuja lo de una lista nueva", distintas[:3], [])
    c(p + "la lista es un solo widget, sin hijos", (lista.marco.winfo_class(),
                                                     conjunto(lista.marco)), ("Canvas", set()))
    lista.marco.destroy()

    # 1b. lo mismo otra vez: nada se toca
    lista = lista_nueva(tarjeta)
    base = [Fila(f"q{i}", "bisync", f"sync-data/q{i}", f"nas:/R/q{i}", "ok", None, i < 4,
                 pair_editor.ORIGEN_CATALOGO, ()) for i in range(5)]
    lista.poner(base, False)      # la de abajo no se usa aquí: su chip es el más ancho
    antes = elementos(lista)
    cambio = lista.poner(list(base), False)
    c(p + "poner las mismas filas no toca ningún elemento", elementos(lista), antes)
    c(p + "  y dice que el tamaño no ha cambiado", cambio, False)
    c(p + "leer(): casilla, nombre, ruta, modo y estado de cada fila",
      lista.leer()[0], ("☑", "q0", "sync-data/q0 ↔ nas:/R/q0", "bisync", "ok"))

    de_q0 = set(lista.tabla.elementos("q0"))
    cambio = lista.poner([base[0]._replace(estado="broken"), *base[1:]], False)
    despues = elementos(lista)
    tocados = {i for i in set(antes) | set(despues) if antes.get(i) != despues.get(i)}
    c(p + "un chip de estado que cambia solo toca elementos de su fila",
      tocados - de_q0 - set(lista.tabla.elementos("q0")), set())
    c(p + "  y las demás filas siguen con los mismos elementos, iguales",
      all(antes[i] == despues[i] for n in lista.orden[1:] for i in lista.tabla.elementos(n)),
      True)
    c(p + "  ni crea widgets", conjunto(lista.marco), set())
    c(p + "  y se lee el estado nuevo", lista.leer()[0][4], "broken")
    c(p + "  un chip que no es el más ancho no cambia el tamaño", cambio, False)
    cambio = lista.poner([base[0]._replace(estado="broken"), *base[1:]], False)
    c(p + "  repetirlo ya no cambia nada", (cambio, elementos(lista)), (False, despues))

    # Una fila que pasa a ámbar cambia de color, no de tamaño
    en_ambar = base[1]._replace(aviso="requiere resync")
    cambio = lista.poner([base[0]._replace(estado="broken"), en_ambar, *base[2:]], False)
    c(p + "una fila que pasa a ámbar lo dice", (lista.filas["q1"]["sup"], lista.leer()[1][4]),
      ("NotaAmbar.", "requiere resync"))
    c(p + "  y si su chip es el más ancho de la columna, la lista pide otro ancho", cambio, True)
    lista.poner(base, False)

    # Una fila que se va se lleva sus elementos; una que llega trae los suyos
    lleno = len(a_la_vista(lista.marco))
    propios = len(lista.tabla.elementos(base[4].name))
    cambio = lista.poner(base[:4], False)
    c(p + "una fila que se va se lleva sus elementos, y la lista pide menos alto",
      (lista.tabla.elementos(base[4].name), len(a_la_vista(lista.marco)) + propios, cambio),
      ((), lleno, True))
    cambio = lista.poner(base, False)
    c(p + "  y al volver, tantos como se fueron", (len(a_la_vista(lista.marco)), cambio),
      (lleno, True))
    antes = elementos(lista)
    cambio = lista.poner(list(reversed(base)), False)
    c(p + "reordenar no cambia el tamaño y recoloca las filas",
      (cambio, lista.orden), (False, [f.name for f in reversed(base)]))
    c(p + "  sin crear ni borrar elementos", sorted(elementos(lista)), sorted(antes))

    # 1c. elegir cambia dos filas, no todas
    lista.poner(base, False)
    lista.elegir(base[0].name, avisar=False)
    antes = elementos(lista)
    lista.elegir(base[3].name, avisar=False)
    despues = elementos(lista)
    c(p + "elegir otra fila cambia los elementos de exactamente dos filas",
      sorted({n for n in lista.orden for i in lista.tabla.elementos(n)
              if antes[i] != despues[i]}), sorted([base[0].name, base[3].name]))
    c(p + "  y vuelve a lo de antes al volver a elegir",
      (lista.elegir(base[0].name, avisar=False), elementos(lista)), (True, antes))
    lista.marco.destroy()

    # 1d. los chips caen sobre el fondo de su fila
    lista = lista_nueva(tarjeta)
    ok = Fila("ok", "bisync", "sync-data/ok", "nas:/R/ok", "ok", None, True,
              pair_editor.ORIGEN_CATALOGO, ())
    ambar = Fila("ambar", "up", "sync-data/ambar", "nas:/R/ambar", "—", "requiere resync",
                 True, pair_editor.ORIGEN_CATALOGO, ())
    roja = Fila("roja", "up-mirror", "sync-data/roja", "nas:/R/roja", "—",
                pair_editor.mirror_warning("up-mirror"), True, pair_editor.ORIGEN_CATALOGO, ())
    otra = Fila("otra", "down", "sync-data/otra", "nas:/R/otra", "—", None, True,
                pair_editor.ORIGEN_CATALOGO, ())
    lista.poner([ok, ambar, roja, otra], False)
    lista.elegir("ok", avisar=False)
    r.deiconify()                  # un diálogo colgado de una raíz oculta no llega a verse
    uitk.ensenar(dlg)
    dlg.update()
    cv = lista.marco

    def bajo_los_chips() -> dict:
        """Por fila, el color de lo que hay debajo de las esquinas de sus dos chips."""
        visto = {}
        for n in lista.orden:
            colores = set()
            for chip in [i for i in lista.tabla.elementos(n) if "pildora" in cv.gettags(i)]:
                todos = list(cv.find_all())
                debajo = set(todos[:todos.index(chip)])
                x0, y0, x1, y1 = cv.bbox(chip)
                for x, y in ((x0, y0), (x1 - 1, y0), (x0, y1 - 1), (x1 - 1, y1 - 1)):
                    rect = [i for i in cv.find_overlapping(x, y, x, y)
                            if i in debajo and cv.type(i) == "rectangle"]
                    colores.add(cv.itemcget(rect[-1], "fill"))
            visto[n] = colores
        return visto

    azul, tarjeta_c = {theme.ACENTO_SUAVE}, {theme.SUPERFICIE}
    ambar_c, rojo_c = {theme.AVISO_FONDO}, {theme.PELIGRO_FONDO}
    visto = bajo_los_chips()
    c(p + "los chips de la elegida caen sobre su azul", visto["ok"], azul)
    c(p + "  los de una fila en ámbar sobre el ámbar", visto["ambar"], ambar_c)
    c(p + "  los de una fila roja sobre el rojo", visto["roja"], rojo_c)
    c(p + "  y los de una fila normal sobre la tarjeta", visto["otra"], tarjeta_c)
    lista.elegir("otra", avisar=False)
    dlg.update()
    visto = bajo_los_chips()
    c(p + "al elegir otra, sus chips pasan al azul", visto["otra"], azul)
    c(p + "  y los de la que se deja vuelven a su fondo", visto["ok"], tarjeta_c)
    for n, color in (("ambar", ambar_c), ("roja", rojo_c)):
        lista.elegir(n, avisar=False)
        dlg.update()
        elegida = bajo_los_chips()[n]
        lista.elegir("otra", avisar=False)
        dlg.update()
        c(p + f"una fila {n} que se elige pasa al azul y, al dejarla, vuelve a su color",
          (elegida, bajo_los_chips()[n]), (azul, color))

    # Una fila que llega ya elegida, con la lista a la vista
    lista.poner([ok, ambar, roja, otra, otra._replace(name="nueva")], False)
    lista.elegir("nueva", avisar=False)
    dlg.update()
    c(p + "una fila nueva que se elige también", bajo_los_chips()["nueva"], azul)

    dlg.destroy()
    theme.olvidar(r.tk)
    r.destroy()


for tema in ("claro", "oscuro"):
    probar_la_lista(tema)
theme.usar("claro")

# ---------------------------------------------------------------------------
# 2. El editor: «Avanzado» se construye al desplegarlo
# ---------------------------------------------------------------------------
RAW_EDITOR = {"defaults": {"remote": "nas"}}
PAREJA = {"name": "notas", "local": "sync-data/notas", "remote_path": "/R/notas",
          "mode": "bisync", "include": ["*.md", "docs/**"], "exclude": ["*.tmp"],
          "flags": {"transfers": 4}}


def probar_el_editor() -> None:
    """`EditorPareja` plegable: los patrones viven en memoria hasta que se despliega."""
    dlg = uitk.modal(raiz, "Editor")
    marco = ttk.Frame(dlg)
    marco.grid()
    editor = tk_pairs.EditorPareja(marco, dlg)
    editor.marco.grid()
    editor.cargar(RAW_EDITOR, PAREJA, "notas")
    c("editor plegado: no hay cajas de patrones todavía", editor.textos, {})
    c("  ni el botón de los flags", getattr(editor, "boton_flags", None), None)
    antes = editor.datos()
    c("  pero `datos()` ya devuelve los patrones y los flags",
      (antes["include"], antes["exclude"], antes["flags"]),
      (["*.md", "docs/**"], ["*.tmp"], {"transfers": 4}))
    c("  y el resumen de «Avanzado» los cuenta",
      str(editor.resumen.cget("text")),
      "Incluir, excluir y flags de rclone · 2 con patrones · 1 flag")
    resumen_plegado = str(editor.resumen.cget("text"))

    antes_widgets = conjunto(editor.marco)
    editor.plegar()
    nuevos = conjunto(editor.marco) - antes_widgets
    c("al desplegar se construye el bloque", (sorted(editor.textos), len(nuevos) > 5),
      (["exclude", "include"], True))
    c("  con lo que `datos()` ya había devuelto", editor.datos(), antes)
    c("  en las cajas", (editor.textos["include"].get("1.0", "end").splitlines(),
                         editor.textos["exclude"].get("1.0", "end").splitlines()),
      (["*.md", "docs/**"], ["*.tmp"]))
    c("  y el mismo resumen", str(editor.resumen.cget("text")), resumen_plegado)
    c("  el botón de los flags dice lo que hay",
      (editor.boton_flags.cget("text"), str(editor.boton_flags.cget("state"))),
      ("Editar flags…", "normal"))
    editor.plegar()
    editor.plegar()
    c("plegar y desplegar otra vez no construye nada más",
      conjunto(editor.marco), antes_widgets | nuevos)

    editor.textos["exclude"].insert("end", "\n*.bak")
    c("lo que se teclea en las cajas es lo que devuelve `datos()`",
      editor.datos()["exclude"], ["*.tmp", "*.bak"])
    editor.cargar(RAW_EDITOR, {**PAREJA, "include": [], "exclude": ["x"]}, "notas")
    c("cargar otra pareja con el bloque construido escribe en las cajas",
      (editor.textos["include"].get("1.0", "end").splitlines(),
       editor.textos["exclude"].get("1.0", "end").splitlines()), ([""], ["x"]))
    editor.cargar(RAW_EDITOR, PAREJA, "notas", editable=False)
    c("  y apaga las cajas si no se puede editar",
      (str(editor.textos["include"].cget("state")), str(editor.boton_flags.cget("state"))),
      ("disabled", "disabled"))

    # Sin patrones, lo mismo antes y después de desplegar (Tk acaba su texto con una línea)
    vacio = tk_pairs.EditorPareja(marco, dlg)
    vacio.marco.grid()
    vacio.cargar(RAW_EDITOR, {k: v for k, v in PAREJA.items()
                              if k not in ("include", "exclude", "flags")}, "notas")
    plegado = vacio.datos()
    vacio.plegar()
    c("sin patrones, `datos()` no cambia al desplegar", vacio.datos(), plegado)
    c("  así que no hay «cambios sin guardar» por abrir «Avanzado»",
      (plegado["include"], plegado["exclude"]), ([""], [""]))

    # El alta lo trae todo a la vista
    alta = tk_pairs.EditorPareja(marco, dlg, sup="", dos_columnas=False, plegable=False)
    alta.marco.grid()
    c("el editor del alta construye «Avanzado» de entrada", sorted(alta.textos),
      ["exclude", "include"])
    alta.cargar(RAW_EDITOR, PAREJA, "notas")
    c("  y lo carga", alta.datos()["include"], ["*.md", "docs/**"])
    dlg.destroy()


probar_el_editor()


# ---------------------------------------------------------------------------
# 3. La pantalla entera, con el catálogo llegando de verdad (con hilos)
# ---------------------------------------------------------------------------
BASE = {"defaults": {"remote": "nas"},
        "pair": [{"name": "notas", "local": "sync-data/notas",
                  "remote_path": "/R/notas", "mode": "bisync"},
                 {"name": "subida", "local": "sync-data/subida",
                  "remote_path": "/R/subida", "mode": "up"}]}
CAT_LOCAL = {"defaults": {"remote": "nas"}, "pair": [dict(p) for p in BASE["pair"]]}
CAT_MAS = {"defaults": {"remote": "nas"},
           "pair": [*(dict(p) for p in BASE["pair"]),
                    {"name": "fotos", "local": "sync-data/fotos",
                     "remote_path": "/R/fotos", "mode": "up"}]}
CUANDO = "2026-09-30 08:00:00"
ENDPOINT = "nas:/prdrive-catalog/remote.toml"
BOTONES_CATALOGO = ("Nueva pareja…", "Borrar del catálogo…", "Guardar en el catálogo…",
                    "Ajustes del catálogo…", "Releer")


class RemotoLento:
    """Un `catalog.run()` que no contesta hasta que se le suelta."""

    def __init__(self, texto: str = "", rc: int = 0, stderr: str = "") -> None:
        self.texto, self.rc, self.stderr = texto, rc, stderr
        self.soltar = threading.Event()

    def __call__(self, args):
        self.soltar.wait(10)
        return subprocess.CompletedProcess(args, self.rc,
                                           stdout=self.texto if self.rc == 0 else "",
                                           stderr=self.stderr)


def nadie(args):
    """Ningún test habla con un remoto que no ha puesto."""
    raise AssertionError(f"nadie debería hablar con el remoto: {args}")


catalog.run = nadie
segundo_plano.olvidar_lecturas()


def dar_vueltas(condicion, limite=5.0) -> bool:
    """Mueve el bucle de eventos hasta que se cumpla la condición o pase el límite."""
    fin = time.monotonic() + limite
    while time.monotonic() < fin:
        raiz.update()
        if condicion():
            return True
        time.sleep(0.02)
    return False


def preparar(raw: dict = BASE):
    """Escribe el config de prueba y lo devuelve ya parseado."""
    model.CONFIG_FILE.write_text(config_file.dumps(raw), encoding="utf-8")
    return model.parse_config(raw)


def dejar_copia(datos: dict) -> None:
    """Deja en `state/` una copia local del catálogo, de `CUANDO`."""
    catalog.cache_toml().parent.mkdir(parents=True, exist_ok=True)
    catalog.cache_toml().write_text(config_file.dumps(datos), encoding="utf-8")
    store.write_json(catalog.cache_meta(), {"pulled_at": CUANDO, "endpoint": ENDPOINT})


def buscar(ventana, clase, texto=None):
    """El primer widget de esa clase (y con ese texto, si se dice), escondido o no."""
    for w in todos(ventana):
        if isinstance(w, clase) and (texto is None or str(w.cget("text")) == texto):
            return w
    return None


def pulsar(ventana, texto: str, clase=ttk.Button) -> None:
    """Pulsa el widget con ese texto."""
    buscar(ventana, clase, texto).invoke()


def ver_catalogo(dlg) -> None:
    """Pasa la pantalla a editar el catálogo, con su botón."""
    pulsar(dlg, "Catálogo", ttk.Radiobutton)


def ver_dispositivo(dlg) -> None:
    """Vuelve a este dispositivo, con su botón."""
    pulsar(dlg, "Este dispositivo", ttk.Radiobutton)


def vista(dlg) -> tuple:
    """Lo que enseña la pantalla: sus widgets (`leer_vista`) y lo que dibuja su lista."""
    return leer_vista(dlg), dlg.lista.leer()


def cadena_del_tab(dlg) -> list[tuple[str, str]]:
    """Lo que recorre el Tab desde la primera opción del interruptor hasta volver a ella.

    Returns:
        Por paso, `(clase, texto)`: el texto del widget, o su clase si no tiene;
        la lista visible es `("Lista", "")`.
    """
    inicio = buscar(dlg, ttk.Radiobutton, "Este dispositivo")
    cadena, actual = [], inicio
    for _ in range(200):
        texto = str(actual.cget("text")) if "text" in actual.keys() else ""
        clase = "Lista" if actual is dlg.lista.marco else actual.winfo_class()
        cadena.append((clase, texto or clase))
        actual = actual.tk_focusNext()
        if actual is None or actual is inicio:
            break
    return cadena


def textos_a_la_vista(dlg) -> list[str]:
    """Los textos de las etiquetas que se ven."""
    return [str(w.cget("text")) for w in visibles(dlg, "TLabel")]


def estado_de(dlg, texto: str) -> str:
    """El estado de ese botón."""
    return str(buscar(dlg, ttk.Button, texto).cget("state"))


PANTALLA_REAL = uitk.pantalla_util


def enseñada(dlg) -> None:
    """Deja la pantalla puesta y visible, como la deja `mostrar()` antes de esperar."""
    raiz.deiconify()
    dlg.visor.encajar(dlg)
    dlg.deiconify()
    dlg.update()


def abrir(cfg, conducir, compartida=None, destruir: bool = True):
    """Abre la pantalla y, donde `mostrar()` esperaría, deja que `conducir(dlg)` la maneje.

    Returns:
        Lo que devuelve `open_dialog()`.
    """
    def mostrar(dlg, parent=None, **_k):
        """Sustituye a `mostrar()`: conduce la pantalla y la cierra, si se quiere."""
        try:
            conducir(dlg)
        finally:
            if destruir and dlg.winfo_exists():
                dlg.destroy()

    tk_pairs.mostrar = mostrar
    if compartida is None:
        return tk_pairs.open_dialog(raiz, cfg)
    return tk_pairs.open_dialog(raiz, cfg, compartida)


def con_remoto(texto_remoto: dict, copia: dict | None = CAT_LOCAL, raw: dict = BASE,
               rc: int = 0, stderr: str = ""):
    """Prepara el dispositivo, su copia local y un remoto callado; devuelve `(cfg, remoto)`."""
    cfg = preparar(raw)
    if copia is not None:
        dejar_copia(copia)
    remoto = RemotoLento(config_file.dumps(texto_remoto), rc, stderr)
    catalog.run = remoto
    segundo_plano.olvidar_lecturas()
    return cfg, remoto


def probar_la_pantalla() -> None:
    """Lo que la pantalla hace con lo que llega, lo que se elige y lo que se pide."""
    tk.Toplevel.wait_window = lambda self, *a, **k: None
    uitk.pantalla_util = lambda win: (3000, 3000)

    # 3a. el catálogo que llega con las mismas parejas no rehace nada
    with sandbox():
        cfg, remoto = con_remoto(CAT_LOCAL)
        visto: dict = {}

        def llega_igual(dlg):
            """Elige una pareja, deja llegar el mismo catálogo y mira qué cambió."""
            enseñada(dlg)
            dlg.lista.elegir("notas")
            cargas = []
            real = dlg.editor.cargar
            dlg.editor.cargar = lambda *a, **k: (cargas.append(1), real(*a, **k))[1]
            crecidas = []
            real_crecer = dlg.visor.crecer
            dlg.visor.crecer = lambda *a, **k: (crecidas.append(1), real_crecer(*a, **k))[1]
            visto["antes"] = conjunto(dlg)
            visto["vista_antes"] = leer_vista(dlg)
            remoto.soltar.set()
            visto["llego"] = dar_vueltas(lambda: not dlg.sondeo.esperando)
            visto["despues"] = conjunto(dlg)
            visto["cargas"], visto["crecidas"] = len(cargas), len(crecidas)
            visto["chip"] = [t for t in textos_a_la_vista(dlg) if "catálogo leído" in t]
            visto["nuevos"] = [w for w in todos(dlg) if str(w) in visto["despues"] - visto["antes"]]
            ver_catalogo(dlg)
            visto["botones"] = [estado_de(dlg, b) for b in BOTONES_CATALOGO]
            visto["elegida"] = dlg.lista.elegida

        abrir(cfg, llega_igual)
        c("llega el catálogo con las mismas parejas: el catálogo llega", visto["llego"], True)
        c("  solo se sustituye el chip del catálogo (uno sale, uno entra)",
          (len(visto["antes"] - visto["despues"]), len(visto["despues"] - visto["antes"])),
          (1, 1))
        c("  y el que entra dice que está leído",
          (len(visto["nuevos"]), visto["chip"] != [] ), (1, True))
        c("  el editor no se recarga", visto["cargas"], 0)
        c("  ni la ventana se agranda ni se recoloca", visto["crecidas"], 0)
        c("  el bloque del catálogo se enciende", visto["botones"], ["normal"] * 5)
        c("  y la pareja elegida sigue siendo la misma", visto["elegida"], "notas")
        c("  nada ha reventado", errores, [])

    # 3b. el bloque del catálogo se crea al verlo y ya no se rehace
    with sandbox():
        cfg, remoto = con_remoto(CAT_MAS)
        remoto.soltar.set()
        visto = {}

        def alternar(dlg):
            """Mira qué hay en la vista de este dispositivo, pasa al catálogo y vuelve."""
            dar_vueltas(lambda: not dlg.sondeo.esperando)
            lista_d = dlg.lista
            visto["sin_bloque"] = [b for b in BOTONES_CATALOGO if buscar(dlg, ttk.Button, b)]
            visto["aviso"] = buscar(dlg, ttk.Label, "Estás editando el catálogo")
            visto["vista_d"] = vista(dlg)
            antes = conjunto(dlg)
            ver_catalogo(dlg)
            lista_c = dlg.lista
            visto["listas"] = (lista_c is not lista_d, lista_c.marco.winfo_manager() != "",
                               lista_d.marco.winfo_manager() == "")
            visto["filas_c"] = list(lista_c.filas)
            visto["bloque"] = [b for b in BOTONES_CATALOGO if buscar(dlg, ttk.Button, b)]
            visto["aviso_c"] = buscar(dlg, ttk.Label, "Estás editando el catálogo")
            nuevos = conjunto(dlg) - antes
            visto["creados"] = ({str(lista_c.marco), *(str(buscar(dlg, ttk.Button, b))
                                                       for b in BOTONES_CATALOGO)} <= nuevos)
            en_catalogo = sin_chips(dlg)
            vista_c = vista(dlg)
            ver_dispositivo(dlg)
            visto["vuelve"] = (dlg.lista is lista_d, sin_chips(dlg) - en_catalogo == set(),
                               vista(dlg) == visto["vista_d"])
            visto["quedan"] = (len(en_catalogo - sin_chips(dlg)) == 0)
            ver_catalogo(dlg)
            visto["otra_vez"] = (dlg.lista is lista_c, sin_chips(dlg) == en_catalogo,
                                 vista(dlg) == vista_c)

        abrir(cfg, alternar)
        c("abrir en este dispositivo no crea el bloque del catálogo",
          (visto["sin_bloque"], visto["aviso"]), ([], None))
        c("  la primera vez que se ve el catálogo se crea (su lista, su barra y su aviso)",
          (visto["listas"], visto["bloque"] == list(BOTONES_CATALOGO), visto["aviso_c"] is not None,
           visto["creados"]), ((True, True, True), True, True, True))
        c("  con sus parejas", visto["filas_c"], ["notas", "subida", "fotos"])
        c("  volver y pasar otra vez no crea ni destruye nada (salvo los chips), y se ve lo mismo",
          (visto["vuelve"], visto["quedan"], visto["otra_vez"]),
          ((True, True, True), True, (True, True, True)))
        c("  nada ha reventado", errores, [])

    # 3c. «Avanzado» se construye al desplegarlo, con la pantalla entera
    with sandbox():
        cfg, remoto = con_remoto(CAT_LOCAL)
        remoto.soltar.set()
        visto = {}

        def desplegar(dlg):
            """Despliega «Avanzado» de la pareja elegida."""
            dar_vueltas(lambda: not dlg.sondeo.esperando)
            dlg.lista.elegir("notas")
            visto["antes"] = (dict(dlg.editor.textos), dlg.editor.datos())
            visto["cambios"] = dlg.estado["cargado"] != dlg.editor.datos()
            pulsar(dlg, "Mostrar")
            visto["despues"] = (sorted(dlg.editor.textos), dlg.editor.datos())
            visto["sin_cambios"] = dlg.estado["cargado"] == dlg.editor.datos()

        abrir(cfg, desplegar)
        c("«Avanzado» sin desplegar: sin cajas, y los patrones los trae `datos()`",
          (visto["antes"][0], visto["cambios"]), ({}, False))
        c("  «Mostrar» las crea, con lo mismo, y no cuenta como cambio",
          (visto["despues"][0], visto["despues"][1] == visto["antes"][1],
           visto["sin_cambios"]), (["exclude", "include"], True, True))

    # 3d. lo que se edita a mano mientras la pantalla está abierta no se pisa
    with sandbox():
        cfg, remoto = con_remoto(CAT_LOCAL)
        remoto.soltar.set()
        planes: list = []
        tk_pairs.confirmar_plan = lambda *a, **k: planes.append(a[1]) or True
        visto = {}
        a_mano = {**BASE, "pair": [*BASE["pair"], {
            "name": "manual", "local": "sync-data/manual", "remote_path": "/R/manual",
            "mode": "up"}]}

        def editar_a_mano(dlg):
            """Cambia el config por fuera y pulsa «Guardar aquí…»."""
            dar_vueltas(lambda: not dlg.sondeo.esperando)
            dlg.lista.elegir("notas")
            dlg.editor.campos["remote_path"].set("/R/otra")
            model.CONFIG_FILE.write_text(config_file.dumps(a_mano), encoding="utf-8")
            pulsar(dlg, "Guardar aquí…")
            visto["planes"] = len(planes)
            visto["cambiado"] = dlg.estado["cambiado"]
            visto["pie"] = [t for t in textos_a_la_vista(dlg) if "ha cambiado fuera" in t]
            visto["filas"] = list(dlg.lista.filas)
            visto["raw"] = [p["name"] for p in dlg.estado["raw"]["pair"]]
            visto["fichero"] = model.CONFIG_FILE.read_text(encoding="utf-8")
            visto["escrito"] = dlg.editor.campos["remote_path"].get()
            # y con el config ya releído, guardar sí hace su plan
            pulsar(dlg, "Guardar aquí…")
            visto["planes_despues"] = len(planes)

        abrir(cfg, editar_a_mano)
        c("una edición a mano entre dos guardados no se pierde: no se hace ningún plan",
          (visto["planes"], visto["cambiado"]), (0, False))
        c("  el pie dice que ha cambiado y que se vuelva a guardar",
          [t for t in visto["pie"] if "Revisa y vuelve a guardar" in t] != [], True)
        c("  la pantalla ya enseña lo escrito a mano", (visto["filas"], visto["raw"]),
          (["notas", "subida", "manual"], ["notas", "subida", "manual"]))
        c("  y el fichero queda como se escribió", visto["fichero"],
          config_file.dumps(a_mano))
        c("  lo tecleado en el editor sigue donde estaba", visto["escrito"], "/R/otra")
        c("  la siguiente vez, con el config ya releído, sí se pide el plan",
          visto["planes_despues"], 1)

    # 3e. ni siquiera con la confirmación abierta: el sí no escribe encima
    with sandbox():
        cfg, remoto = con_remoto(CAT_LOCAL)
        remoto.soltar.set()
        visto = {}
        a_mano = {**BASE, "pair": [*BASE["pair"], {
            "name": "manual", "local": "sync-data/manual", "remote_path": "/R/manual",
            "mode": "up"}]}

        def confirmar_y_editar(parent, plan, titulo, nota, **k):
            """Mientras se confirma, alguien edita el config a mano; y se contesta que sí."""
            model.CONFIG_FILE.write_text(config_file.dumps(a_mano), encoding="utf-8")
            return True

        tk_pairs.confirmar_plan = confirmar_y_editar

        def guardar(dlg):
            """Pulsa «Guardar aquí…» con un cambio hecho."""
            dar_vueltas(lambda: not dlg.sondeo.esperando)
            dlg.lista.elegir("notas")
            dlg.editor.campos["remote_path"].set("/R/otra")
            pulsar(dlg, "Guardar aquí…")
            visto["fichero"] = model.CONFIG_FILE.read_text(encoding="utf-8")
            visto["pie"] = [t for t in textos_a_la_vista(dlg) if "ha cambiado fuera" in t]
            visto["filas"] = list(dlg.lista.filas)

        cambiado = abrir(cfg, guardar)
        c("confirmar mientras se edita a mano: no se escribe nada encima",
          (visto["fichero"], cambiado), (config_file.dumps(a_mano), False))
        c("  se dice en el pie y la pantalla se vuelve a leer",
          (visto["pie"] != [], visto["filas"]), (True, ["notas", "subida", "manual"]))
        tk_pairs.confirmar_plan = lambda *a, **k: True

    # 3f. los estados ya leídos no se vuelven a leer
    with sandbox():
        cfg, remoto = con_remoto(CAT_LOCAL)
        remoto.soltar.set()
        pares = []
        real_par, real_fil = bisync.pair_state, bisync.filters_state

        def espia(nombre, real):
            """`bisync.<nombre>` apuntando a qué pareja o fichero se le pide."""
            def llama(*a, **k):
                pares.append(nombre)
                return real(*a, **k)
            return llama

        bisync.pair_state = espia("pair_state", real_par)
        bisync.filters_state = espia("filters_state", real_fil)
        try:
            abrir(cfg, lambda dlg: dar_vueltas(lambda: not dlg.sondeo.esperando))
            sin_compartida = list(pares)
            c("sin lectura compartida, abrir lee el baseline y los filtros de las bisync",
              sorted(sin_compartida), ["filters_state", "pair_state"])

            pares.clear()
            inst = instantanea.Instantanea(estados=pair_editor.estados_de(cfg),
                                           firma=instantanea.firma(cfg),
                                           huella=instantanea.tomar_huella(cfg))
            compartida = instantanea.Compartida()
            compartida.poner(inst)
            pares.clear()
            abrir(cfg, lambda dlg: dar_vueltas(lambda: not dlg.sondeo.esperando), compartida)
            c("con una lectura compartida que vale, no se lee nada del disco", pares, [])

            # El config cambió por fuera después de que la principal lo leyera: otra
            # definición de pareja, otros estados: la lectura compartida no vale para él
            model.CONFIG_FILE.write_text(config_file.dumps(a_mano), encoding="utf-8")
            pares.clear()
            abrir(cfg, lambda dlg: dar_vueltas(lambda: not dlg.sondeo.esperando), compartida)
            c("si el config ya no es el de la lectura compartida, se lee lo suyo",
              sorted(set(pares)), ["filters_state", "pair_state"])
        finally:
            bisync.pair_state, bisync.filters_state = real_par, real_fil

    # 3g. el editor solo se recarga cuando cambian sus campos
    with sandbox():
        cfg, remoto = con_remoto(CAT_LOCAL)
        remoto.soltar.set()
        visto = {}
        otra_ruta = {**CAT_LOCAL, "pair": [{**CAT_LOCAL["pair"][0], "remote_path": "/R/notas-v2"},
                                           *CAT_LOCAL["pair"][1:]]}

        def releer(dlg):
            """Pide el catálogo otra vez y espera a que llegue."""
            pulsar(dlg, "Releer")
            dar_vueltas(lambda: not dlg.sondeo.esperando)

        def recargas(dlg):
            """Cuántas veces se recarga el editor y qué dice al acabar el catálogo cambiado."""
            dar_vueltas(lambda: not dlg.sondeo.esperando)
            montar_el_catalogo(dlg)
            dlg.lista.elegir("notas")
            cargas = []
            real = dlg.editor.cargar
            dlg.editor.cargar = lambda *a, **k: (cargas.append(1), real(*a, **k))[1]
            remoto.texto = config_file.dumps(otra_ruta)
            releer(dlg)
            visto["catalogo_cambia"] = (len(cargas), "/R/notas-v2" in str(
                dlg.editor.pistas["remote_path"].cget("text")))
            # Lo de este dispositivo cambia por fuera: la pareja elegida es otra y se recarga
            nuevo = {**BASE, "pair": [{**BASE["pair"][0], "remote_path": "/R/mio"},
                                      *BASE["pair"][1:]]}
            model.CONFIG_FILE.write_text(config_file.dumps(nuevo), encoding="utf-8")
            releer(dlg)
            visto["local_cambia"] = (len(cargas), dlg.editor.campos["remote_path"].get())
            releer(dlg)
            visto["nada"] = len(cargas)

        def montar_el_catalogo(dlg):
            """Crea el bloque del catálogo y vuelve a este dispositivo."""
            ver_catalogo(dlg)
            ver_dispositivo(dlg)

        abrir(cfg, recargas)
        c("el catálogo cambia lo que rodea al editor, no sus campos: no se recarga",
          visto["catalogo_cambia"], (0, True))
        c("  la pareja de este dispositivo cambia por fuera: se recarga, una vez",
          visto["local_cambia"], (1, "/R/mio"))
        c("  y releer sin cambios no vuelve a cargar nada", visto["nada"], 1)

    # 3h. la ventana solo se agranda cuando algo ha podido pedir más sitio
    with sandbox():
        cfg, remoto = con_remoto(CAT_MAS)
        visto = {}

        def llega_con_una_mas(dlg):
            """Con la pantalla a la vista llega un catálogo con una pareja más."""
            enseñada(dlg)
            crecidas = []
            real = dlg.visor.crecer
            dlg.visor.crecer = lambda *a, **k: (crecidas.append(1), real(*a, **k))[1]
            remoto.soltar.set()
            dar_vueltas(lambda: not dlg.sondeo.esperando)
            visto["una_mas"] = (len(crecidas), list(dlg.lista.filas))

        abrir(cfg, llega_con_una_mas)
        c("llega una pareja más: la ventana comprueba si ha de crecer",
          visto["una_mas"], (1, ["notas", "subida", "fotos"]))

    # 3i. una pantalla vuelta a poner enseña lo de una recién abierta
    with sandbox():
        cfg, remoto = con_remoto(CAT_MAS)
        remoto.soltar.set()
        dlgs: list = []
        tk_pairs.confirmar_plan = lambda *a, **k: True

        def asentada(dlg):
            """Espera a que acabe de llegar el catálogo y la guarda."""
            dar_vueltas(lambda: not dlg.sondeo.esperando)
            dlgs.append(dlg)

        abrir(cfg, asentada, destruir=False)
        usada = dlgs[0]
        ver_catalogo(usada)
        usada.lista.elegir("fotos")
        pulsar(usada, "Mostrar")
        usada.editor.campos["remote_path"].set("/R/escrito")
        usada.editor.textos["exclude"].insert("1.0", "*.tmp")
        usada.estado["cambiado"] = True
        usada.estado["cargado"] = None            # lo escrito se da por guardado o descartado
        pie = next(w for w in todos(usada) if isinstance(w, ttk.Label)
                   and str(w.cget("text")).startswith("Antes de guardar"))
        pie.configure(text="algo que se ha hecho")
        antes_widgets = conjunto(usada)
        usada.aplicar()
        dar_vueltas(lambda: not usada.sondeo.esperando)
        abrir(cfg, asentada, destruir=False)
        nueva = dlgs[1]
        c("aplicar(): la pantalla vuelve a este dispositivo y a su primera pareja",
          (usada.estado["vista"], usada.lista.elegida, usada.estado["cambiado"]),
          (False, nueva.lista.elegida, False))
        def sin_hora(vista: list) -> list:
            """La vista sin la hora de lectura del catálogo, que es la de cada apertura."""
            return [tuple(re.sub(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d", "<hora>", x)
                          if isinstance(x, str) else x for x in fila) for fila in vista]

        distintas = [(a, b) for a, b in zip(sin_hora(leer_vista(usada)),
                                            sin_hora(leer_vista(nueva))) if a != b]
        c("  y enseña lo mismo que una recién abierta",
          (distintas, len(leer_vista(usada)) == len(leer_vista(nueva)),
           usada.lista.leer() == nueva.lista.leer()), ([], True, True))
        c("  con «Avanzado» plegado y lo escrito fuera",
          (usada.editor.plegado.get(), usada.editor.campos["remote_path"].get()),
          (True, nueva.editor.campos["remote_path"].get()))
        c("  sin crear nada que no hubiera ya, salvo chips",
          sin_chips(usada) - antes_widgets, set())
        usada.destroy()
        nueva.destroy()
        tk_pairs.confirmar_plan = lambda *a, **k: True
        c("  nada ha reventado", errores, [])

    # 3j. el Tab recorre cada vista de arriba abajo, también la del catálogo, hecha tarde
    with sandbox():
        cfg, remoto = con_remoto(CAT_MAS)
        remoto.soltar.set()
        cadenas: dict = {}

        def tabular(dlg):
            """Apunta la cadena del Tab de cada vista: dispositivo, catálogo y vuelta."""
            enseñada(dlg)
            dar_vueltas(lambda: not dlg.sondeo.esperando)
            cadenas["dispositivo"] = cadena_del_tab(dlg)
            ver_catalogo(dlg)
            dlg.update()
            cadenas["catalogo"] = cadena_del_tab(dlg)
            ver_dispositivo(dlg)
            dlg.update()
            cadenas["vuelta"] = cadena_del_tab(dlg)

        abrir(cfg, tabular)
        for vista_, franja, barra in (
                ("dispositivo", "Volver a los del catálogo",
                 ["Simular", "Quitar…", "Descartar", "Guardar aquí…"]),
                ("catalogo", "Ajustes del catálogo…",
                 ["Nueva pareja…", "Borrar del catálogo…", "Releer", "Descartar",
                  "Guardar en el catálogo…"])):
            cadena = cadenas[vista_]
            textos = [t for _clase, t in cadena]
            pos = {t: i for i, t in enumerate(textos)}
            lista_en = next((i for i, (clase, _t) in enumerate(cadena) if clase == "Lista"),
                            None)
            campos = [i for i, (clase, _t) in enumerate(cadena) if clase in ("TEntry", "Text")]
            en_barra = [t for t in textos if t in barra]
            c(f"Tab en la vista «{vista_}»: la lista va tras la franja de [defaults] y antes "
              "del editor",
              (lista_en, lista_en == min(campos) - 1 if campos else None),
              (pos.get(franja, -2) + 1, True))
            c("  la barra de acciones va tras el editor, en su orden, y antes de "
              "«Dispositivos…»",
              (en_barra, min(pos[t] for t in barra) > max(campos),
               max(pos[t] for t in barra) < pos.get("Dispositivos…", -1)),
              (barra, True, True))
            c("  y «Cerrar» es lo último", textos[-1], "Cerrar")
        c("volver a este dispositivo deja el Tab como estaba",
          cadenas["vuelta"], cadenas["dispositivo"])
        c("  nada ha reventado", errores, [])

    uitk.pantalla_util = PANTALLA_REAL


probar_la_pantalla()


# ---------------------------------------------------------------------------
# 6. Lo que dice cada fila: la casilla, el chip de modo y el chip de estado
# ---------------------------------------------------------------------------
def fila_con(nombre: str, modo: str = "bisync", en_pen: bool = True, estado: str = "ok",
             aviso: str | None = None, origen: str = pair_editor.ORIGEN_CATALOGO) -> Fila:
    """Una pareja con lo justo para su fila; su ruta es «docs ↔ nas:/R/<nombre>»."""
    return Fila(nombre, modo, "docs", f"nas:/R/{nombre}", estado, aviso, en_pen, origen, ())


sano = fila_con("sano")
espejo = fila_con("copia", modo="up-mirror", aviso=pair_editor.mirror_warning("up-mirror"))
local = fila_con("local", origen=pair_editor.ORIGEN_LOCAL)
apagada = fila_con("apagada", en_pen=False)
casos = []
for fila_, nombre_caso in ((sano, "sana"), (espejo, "espejo"), (local, "modificada aquí"),
                           (apagada, "no se usa aquí")):
    tono_, nota_ = pair_editor.row_status(fila_, False)
    casos.append((nombre_caso, tono_, nota_, tk_pairs.ListaParejas.fila_tabla(fila_, tono_, nota_, False)))
dibujadas = {nombre_caso: (tono_, fila_tabla) for nombre_caso, tono_, _nota, fila_tabla in casos}
c("una pareja sana: casilla marcada, modo sin aviso y estado «Ok.»",
  dibujadas["sana"],
  ("ok", uitk.FilaTabla("sano", (tk_pairs.CeldaCasilla(True), uitk.CeldaTexto("sano", "Fuerte."),
                               uitk.CeldaTexto("docs ↔ nas:/R/sano", "Mono."),
                               uitk.CeldaChip("bisync", "", "both"),
                               uitk.CeldaChip("ok", "Ok.", None)), "")))
c("un espejo: tono de peligro, modo en rojo con su icono de subida y estado «espejo» en rojo",
  dibujadas["espejo"][0], "peligro")
c("  el modo y el estado", dibujadas["espejo"][1].celdas[3:],
  (uitk.CeldaChip("up-mirror", "Peligro.", "up"), uitk.CeldaChip("espejo", "Peligro.", None)))
c("una pareja modificada aquí: tono de aviso y su origen como estado «Aviso.»",
  (dibujadas["modificada aquí"][0], dibujadas["modificada aquí"][1].celdas[4]),
  ("aviso", uitk.CeldaChip(pair_editor.ORIGEN_LOCAL, "Aviso.", None)))
c("una pareja que no se usa aquí: casilla vacía, tono apagado y «Apagado.»",
  (dibujadas["no se usa aquí"][0], dibujadas["no se usa aquí"][1].celdas[0],
   dibujadas["no se usa aquí"][1].celdas[4]),
  ("apagado", tk_pairs.CeldaCasilla(False), uitk.CeldaChip(pair_editor.NO_SE_USA, "Apagado.", None)))
c("en la vista del catálogo el estado de un espejo sigue en rojo, pero su chip dice «Ok.»",
  (pair_editor.row_status(espejo, True)[0],
   tk_pairs.ListaParejas.fila_tabla(espejo, "peligro", pair_editor.EN_EL_CATALOGO, True).celdas[4]),
  ("peligro", uitk.CeldaChip(pair_editor.EN_EL_CATALOGO, "Ok.", None)))

lista_t = lista_nueva(ttk.Frame(raiz))
lista_t.poner([sano, espejo, local, apagada])
leido = lista_t.leer()
c("leer(): la casilla de una pareja que no se usa aquí es ☐, y la de una que sí es ☑",
  (leido[0][0], leido[3][0]), ("☑", "☐"))
c("  y el modo y el estado tal como se ven",
  [(f[3], f[4]) for f in leido],
  [("bisync", "ok"), ("up-mirror", "espejo"), ("bisync", pair_editor.ORIGEN_LOCAL),
   ("bisync", pair_editor.NO_SE_USA)])
c("nada ha reventado", errores, [])


sys.exit(c.report())
