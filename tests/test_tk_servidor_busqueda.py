#!/usr/bin/env python3
"""«Servidor»: buscar en las subcarpetas desde la barra de direcciones.

Ningún test arranca rclone ni toca la red: el `rcd` es el falso de
`tests/_servidor_falso.py`, que contesta desde un diccionario. Se comprueba lo que
ve la persona:
- Intro en el campo busca desde la carpeta que se ve, en todas las de debajo: la
  lista pasa a resultados (con la columna «Carpeta»), la raíz no se vuelve a pedir y
  una carpeta sin permiso se cuenta y se sigue; al acabar, la línea lo resume;
- escribir sin Intro busca al dejar de teclear; afinar el texto filtra lo ya leído
  sin volver al servidor; un texto que no coincide con nada lo dice;
- en los resultados solo se abre (una carpeta), se va a la ubicación (un archivo,
  que queda elegido) o se usa la botonera de la carpeta de la búsqueda; ni bajar,
  ni renombrar, ni cortar, ni borrar;
- «Atrás» desde una ubicación vuelve a los resultados sin recorrer otra vez; Escape
  vuelve a la carpeta sin pedirla; F5 vuelve a recorrer;
- el tope de elementos para la búsqueda y lo dice;
- «Detener», con hilos de verdad y una lectura en vuelo, no pinta lo que llega tarde;
- dos archivos con el mismo nombre en carpetas distintas son dos filas.
"""

from __future__ import annotations

import sys
import threading

from _harness import Checks, mkcfg, sandbox

from common import config_file, model

c = Checks("«Servidor»: buscar en las subcarpetas")

try:
    import tkinter as tk
    raiz = tk.Tk()
    raiz.withdraw()
except Exception as e:                                   # sin entorno gráfico
    print(f"  (saltado) no hay entorno gráfico: {e}")
    sys.exit(c.report())

import _servidor_falso as F  # noqa: E402
from _servidor_falso import (RcdFalso, bombear, entradas, frase, item, lista,  # noqa: E402
                             nombres)

from ui import icons, segundo_plano, servidor, tk_servidor  # noqa: E402

errores: list[str] = []
raiz.report_callback_exception = (
    lambda tipo, valor, _tb: errores.append(f"{tipo.__name__}: {valor}"))

LANZAR_DE_VERDAD = segundo_plano.lanzar
segundo_plano.lanzar = segundo_plano.en_el_acto
F.usar(raiz)
config_file.load_raw = lambda path=None: {"defaults": {"remote": "nas"}}
CFG = mkcfg((), pairs=[
    {"name": "Notas", "local": "sync-data/notas", "remote_path": "/datos/notas", "remote": "nas"}],
    defaults={"remote": "nas"})
MENUS: list = []
tk_servidor._mostrar_menu = lambda menu, x, y: MENUS.append(menu)


def servidor_falso(otras=None) -> RcdFalso:
    """«/» con datos (notas, a.txt), privado (sin permiso) y leeme.txt; notas lleva otro a.txt."""
    return RcdFalso(F.respuestas(otras={
        ("operations/list", "datos/notas"): lista(item("hoy.txt"), item("a.txt")),
        **(otras or {})}))


def abrir(falso):
    return F.abrir(falso, config=CFG)


def remotes_listados(falso) -> list[str]:
    return [p["remote"] for p in falso.listados()]


def buscar(dlg, texto: str) -> None:
    """Escribe en el campo de búsqueda y pulsa Intro, como la persona."""
    campo = dlg.direcciones.busqueda
    campo.delete(0, "end")
    campo.insert(0, texto)
    campo.focus_force()
    dlg.update()
    campo.event_generate("<Return>")
    dlg.update()


def tecla_en(widget, secuencia: str) -> None:
    widget.focus_force()
    widget.update()
    widget.event_generate(secuencia)
    widget.update()


def carpeta_de(dlg, iid: str) -> str:
    return str(dlg.lista.set(iid, "carpeta"))


def columnas_vistas(dlg) -> list[str]:
    return [str(x) for x in dlg.lista.tk.splitlist(dlg.lista.cget("displaycolumns"))]


def doble_clic(dlg, iid: str) -> None:
    dlg.lista.see(iid)
    dlg.update()
    x, y, ancho, alto = dlg.lista.bbox(iid)
    for t in (0, 50):
        dlg.lista.event_generate("<ButtonPress-1>", x=x + 5, y=y + alto // 2, time=900_000 + t)
        dlg.lista.event_generate("<ButtonRelease-1>", x=x + 5, y=y + alto // 2,
                                 time=900_000 + t + 10)
    dlg.update()


with sandbox():
    model.RCLONE_CONF.write_text("[nas]\ntype = sftp\nhost = h\n", encoding="utf-8")

    # -----------------------------------------------------------------------
    # 1. Intro busca en todas las subcarpetas
    # -----------------------------------------------------------------------
    falso = servidor_falso()
    dlg = abrir(falso)
    antes = remotes_listados(falso)
    c("antes de buscar, la columna «Carpeta» no se ve", "carpeta" in columnas_vistas(dlg), False)
    buscar(dlg, "a.txt")
    c("Intro busca desde la carpeta que se ve, en todas las de debajo",
      sorted(nombres(dlg)), ["/datos/a.txt", "/datos/notas/a.txt"])
    c("  dos archivos con el mismo nombre son dos filas, cada uno con su carpeta",
      [carpeta_de(dlg, i) for i in sorted(nombres(dlg))], ["/datos", "/datos/notas"])
    c("  la lista enseña la columna «Carpeta»",
      (columnas_vistas(dlg)[0], str(dlg.lista.heading("carpeta", "text"))), ("carpeta", "Carpeta"))
    c("  la raíz no se volvió a pedir; las demás, una vez cada una",
      sorted(remotes_listados(falso)[len(antes):]), ["datos", "datos/notas", "privado"])
    c("  la carpeta sin permiso se cuenta y la línea lo resume", frase(dlg),
      "2 encontrados en 3 carpetas · 1 carpeta no se pudo leer")
    c("  y al acabar no queda el botón «Detener»", dlg.accion.winfo_manager(), "")
    dlg.update()
    c("  la columna de más no ensancha la ventana: sin barras del recuadro",
      dlg.visor.barras(), (False, False))
    minimos = (icons.px(dlg.lista, tk_servidor.COLUMNAS[0][1]),
               icons.px(dlg.lista, tk_servidor.COLUMNA_CARPETA[1]))
    c("  y el nombre y la carpeta se reparten el sitio que sobra",
      (int(dlg.lista.column("#0", "width")) > minimos[0],
       int(dlg.lista.column("carpeta", "width")) > minimos[1]), (True, True))
    dlg.geometry("%dx%d" % dlg.minsize())
    for _ in range(3):
        dlg.update()
    c("  ni con la ventana encogida al mínimo", dlg.visor.barras(), (False, False))
    c("  el pie cuenta los resultados", str(dlg.cuenta.cget("text")), "2 elementos")
    dlg.lista.selection_set("/datos/a.txt")
    dlg.update()
    e = dlg.estados_menu()
    c("en los resultados no se baja, renombra, corta ni borra; se va a la ubicación",
      {k: e[k] for k in ("bajar", "renombrar", "cortar", "borrar", "abrir", "ubicacion")},
      {"bajar": False, "renombrar": False, "cortar": False, "borrar": False, "abrir": False,
       "ubicacion": True})
    c("  la botonera sigue valiendo para la carpeta de la búsqueda",
      (e["nueva"], e["archivos"]), (True, True))
    x, y, _a, alto = dlg.lista.bbox("/datos/a.txt")
    dlg.lista.event_generate("<Button-3>", x=x + 5, y=y + alto // 2)
    dlg.update()
    c("  el botón derecho sobre un resultado: abrir y abrir la ubicación",
      entradas(MENUS[-1]), [("Abrir", "disabled"), ("Abrir la ubicación", "normal")])

    # afinar no vuelve al servidor
    n = len(falso.listados())
    buscar(dlg, "notas")
    c("afinar el texto filtra lo ya leído, sin volver al servidor",
      (len(falso.listados()), nombres(dlg)), (n, ["/datos/notas"]))
    buscar(dlg, "zzz")
    c("un texto que no coincide lo dice encima de la lista",
      (nombres(dlg), dlg.vacia.winfo_manager(), str(dlg.vacia.cget("text"))),
      ([], "place", "Nada coincide con «zzz»."))

    # una carpeta encontrada se abre con doble clic
    buscar(dlg, "notas")
    doble_clic(dlg, "/datos/notas")
    c("doble clic en una carpeta encontrada entra en ella y deja de buscar",
      (dlg.direcciones.ruta, nombres(dlg), dlg.direcciones.texto_busqueda.get(),
       "carpeta" in columnas_vistas(dlg)),
      ("/datos/notas", ["a.txt", "hoy.txt"], "", False))
    n = len(falso.listados())
    dlg.direcciones.atras.invoke()
    dlg.update()
    c("«Atrás» vuelve a los resultados, sin recorrer otra vez (solo la carpeta)",
      (dlg.direcciones.ruta, dlg.direcciones.texto_busqueda.get(), nombres(dlg),
       remotes_listados(falso)[n:]),
      ("/", "notas", ["/datos/notas"], [""]))

    # un archivo: a su carpeta, elegido
    buscar(dlg, "a.txt")
    doble_clic(dlg, "/datos/notas/a.txt")
    c("doble clic en un archivo va a su carpeta y lo deja elegido",
      (dlg.direcciones.ruta, list(dlg.lista.selection())), ("/datos/notas", ["a.txt"]))
    dlg.direcciones.atras.invoke()
    dlg.update()
    dlg.lista.selection_set("/datos/a.txt")
    dlg.update()
    dlg.acciones["ubicacion"]()
    dlg.update()
    c("«Abrir la ubicación» hace lo mismo", (dlg.direcciones.ruta, list(dlg.lista.selection())),
      ("/datos", ["a.txt"]))

    # Escape vuelve a la carpeta sin pedirla
    dlg.direcciones.atras.invoke()
    dlg.update()
    n = len(falso.listados())
    tecla_en(dlg.direcciones.busqueda, "<Escape>")
    c("Escape vacía el campo y vuelve a la carpeta, sin pedirla",
      (dlg.direcciones.texto_busqueda.get(), nombres(dlg), len(falso.listados()),
       "carpeta" in columnas_vistas(dlg)),
      ("", ["datos", "privado", "leeme.txt"], n, False))

    # F5 vuelve a recorrer
    buscar(dlg, "a.txt")
    n = len(falso.listados())
    tecla_en(dlg.lista, "<F5>")
    c("F5 con una búsqueda vuelve a recorrer las subcarpetas",
      (sorted(remotes_listados(falso)[n:]), sorted(nombres(dlg))),
      (["datos", "datos/notas", "privado"], ["/datos/a.txt", "/datos/notas/a.txt"]))
    F.cerrar(dlg)

    # -----------------------------------------------------------------------
    # 2. Al dejar de teclear también busca
    # -----------------------------------------------------------------------
    previo_espera = tk_servidor.ESPERA_BUSQUEDA_MS
    tk_servidor.ESPERA_BUSQUEDA_MS = 10
    falso = servidor_falso()
    dlg = abrir(falso)
    dlg.direcciones.busqueda.insert(0, "hoy")
    c("escribir sin Intro busca al dejar de teclear",
      bombear(lambda: nombres(dlg) == ["/datos/notas/hoy.txt"]), True)
    tk_servidor.ESPERA_BUSQUEDA_MS = previo_espera
    F.cerrar(dlg)

    # -----------------------------------------------------------------------
    # 3. El tope de elementos
    # -----------------------------------------------------------------------
    previo_limite = servidor.LIMITE_ELEMENTOS
    servidor.LIMITE_ELEMENTOS = 4
    falso = servidor_falso()
    dlg = abrir(falso)
    buscar(dlg, "a")
    c("pasado el tope se para y lo dice", frase(dlg).endswith(
        "Búsqueda parada: demasiados elementos; busca desde una carpeta más concreta."), True)
    servidor.LIMITE_ELEMENTOS = previo_limite
    F.cerrar(dlg)

    # -----------------------------------------------------------------------
    # 4. «Detener» con una lectura en vuelo (hilos de verdad)
    # -----------------------------------------------------------------------
    segundo_plano.lanzar = LANZAR_DE_VERDAD
    soltar = threading.Event()

    def datos_lento():
        soltar.wait(5)
        return lista(item("tarde.txt"))

    falso = servidor_falso(otras={("operations/list", "datos"): datos_lento})
    dlg = abrir(falso)
    bombear(lambda: nombres(dlg) == ["datos", "privado", "leeme.txt"])
    buscar(dlg, "tarde")
    c("mientras busca, la línea lo dice y ofrece «Detener»",
      bombear(lambda: frase(dlg).startswith("Buscando «tarde»…")
              and str(dlg.accion.cget("text")) == "Detener"), True)
    dlg.accion.invoke()
    dlg.update()
    c("  «Detener» lo para y lo resume", (frase(dlg).startswith("0 encontrados en"),
                                         dlg.accion.winfo_manager()), (True, ""))
    soltar.set()
    for _ in range(30):
        dlg.update()
        bombear(lambda: False, 0.01)
    c("  y lo que llega tarde no se pinta", nombres(dlg), [])
    buscar(dlg, "tarde")
    c("Intro lo reanuda y llega lo que faltaba",
      bombear(lambda: "/datos/tarde.txt" in nombres(dlg)), True)
    F.cerrar(dlg)
    segundo_plano.lanzar = segundo_plano.en_el_acto

    c("ningún error de Tk", errores, [])

raiz.destroy()
sys.exit(c.report())
