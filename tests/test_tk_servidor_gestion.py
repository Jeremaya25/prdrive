#!/usr/bin/env python3
"""«Servidor…» (pieza 3): la barra de gestión, las teclas, el menú y los flujos de nueva carpeta, renombrar y borrar.

Ningún test arranca rclone ni toca la red: `rcd.arrancar` devuelve un `RcdGestion`
(`tests/_servidor_falso.py`) que contesta desde un diccionario y acepta las órdenes
de `rcd.lanzar_orden()`. Los diálogos (`tk_gestion.pedir_nombre`,
`tk_pairs.confirmar_plan`, `tk_servidor.avisar`/`preguntar`) se sustituyen y apuntan
lo que se les pidió. Lo que se comprueba es lo que ve y lo que dispara la persona:

- la barra («Nueva carpeta…», «Renombrar…», «Cortar», «Borrar…») y cuándo se enciende:
  sin selección, con una fila, con dos, con un lote en marcha y sin `rcd`;
- F2, Supr y Ctrl+Mayús+N, y el menú del botón derecho (que elige primero la fila de debajo);
- renombrar un archivo (`operations/movefile`) y una carpeta (`sync/move`) tras releer los
  nombres del destino; un nombre ocupado ahora (aunque la pantalla no lo sepa) se rechaza
  sin lanzar nada; el mismo nombre no hace nada;
- nueva carpeta (`operations/mkdir`) y que lo creado quede elegido tras releer;
- borrar: un `operations/size` por carpeta, la confirmación con sus líneas, un «no» que no
  lanza nada, un «sí» que lanza `purge` y luego `deletefile` en ese orden, un bloqueo de
  pareja y del catálogo, el aviso de pareja y un fallo al contar con «Reintentar»;
- cortar y pegar: la línea del corte, «Pegar aquí» (botón, Ctrl+V y menú), los rechazos
  (misma carpeta, dentro de sí misma, nombre ocupado, otro remote), el bloqueo de un
  up-mirror y el aviso de una pareja, el orden de las órdenes, cancelar y fallar a mitad;
- cerrar con un cambio en marcha.
"""

from __future__ import annotations

import sys

from _harness import Checks, mkcfg, sandbox

from common import config_file, model, rcd

c = Checks("«Servidor»: gestionar el servidor")

try:
    import tkinter as tk
    raiz = tk.Tk()
    raiz.withdraw()
except Exception as e:                                   # sin entorno gráfico
    print(f"  (saltado) no hay entorno gráfico: {e}")
    sys.exit(c.report())

import _servidor_falso as F  # noqa: E402
from _servidor_falso import (ACABADO, CORRIENDO, RcdGestion, bombear, fallado,  # noqa: E402
                             frase, frase_panel, item, lista, nombres, panel_a_la_vista,
                             pulsar)

from ui import segundo_plano, tk_gestion, tk_pairs, tk_servidor  # noqa: E402

errores: list[str] = []
raiz.report_callback_exception = (
    lambda tipo, valor, _tb: errores.append(f"{tipo.__name__}: {valor}"))

segundo_plano.lanzar = segundo_plano.en_el_acto
F.usar(raiz)
tk_servidor.INTERVALO_PROGRESO_MS = 5

RAW = {"defaults": {"remote": "nas", "catalog_path": "/datos/cat/remote.toml"}}
config_file.load_raw = lambda path=None: RAW

CFG = mkcfg((), pairs=[
    {"name": "Notas", "local": "sync-data/notas", "remote_path": "/datos/notas",
     "remote": "nas", "mode": "bisync"}], defaults={"remote": "nas"})

MB5 = 5 * 1024 * 1024

# Lo que hay en «/datos», que el test cambia cuando el servidor "lo hace".
CONTENIDO = {"datos": []}


def restablecer() -> None:
    CONTENIDO["datos"] = [item("cat", True), item("fotos", True), item("notas", True),
                          item("a.txt", tamano=2048), item("b.txt", tamano=12)]


def servidor_gestion(estados=None, tamanos=None, otras=None) -> RcdGestion:
    """Un servidor con «/datos» (cat, fotos, notas, a.txt y b.txt) que acepta órdenes de gestión."""
    restablecer()
    return RcdGestion(F.respuestas(otras={
        ("operations/list", "datos"): lambda: lista(*CONTENIDO["datos"]),
        ("operations/list", "datos/notas"): lista(item("hoy.txt")),
        **(otras or {})}),
        tamanos=tamanos if tamanos is not None else {"datos/fotos": (12, MB5)},
        estados=estados)


def abrir(*falsos, cfg=CFG):
    return F.abrir(*falsos, config=cfg)


def entrar_en(dlg, carpeta: str) -> None:
    """Entra en esa carpeta de la que se ve, con Intro."""
    dlg.lista.selection_set(carpeta)
    pulsar(dlg, "<Return>")


def elegir(dlg, *iids) -> None:
    dlg.lista.selection_set(*iids)
    dlg.update()


def encendidos(dlg) -> tuple[bool, bool, bool, bool]:
    """Si están encendidos «Nueva carpeta…», «Renombrar…», «Cortar» y «Borrar…»."""
    b = dlg.barra
    return tuple(not w.instate(["disabled"]) for w in (b.nueva, b.renombrar, b.cortar, b.borrar))


def listados_de(falso, remote: str) -> int:
    return len([p for p in falso.listados() if p["remote"] == remote])


def seleccion(dlg) -> list[str]:
    return sorted(str(i) for i in dlg.lista.selection())


# --- los diálogos sustituidos ----------------------------------------------------
NOMBRE = {"respuesta": None, "llamadas": []}
CONFIRMAR = {"respuesta": True, "llamadas": []}
DIALOGOS = {"avisar": [], "preguntar": [], "menus": []}
RESPUESTA_PREGUNTAR = {"v": True}


def falso_pedir_nombre(parent, titulo, inicial, validar, es_archivo=False):
    NOMBRE["llamadas"].append((titulo, inicial, es_archivo, validar))
    return NOMBRE["respuesta"]


def falso_confirmar(parent, plan, titulo, nota, suelto=False):
    CONFIRMAR["llamadas"].append((titulo, nota, plan.consequences, plan.warnings))
    return CONFIRMAR["respuesta"]


def falso_avisar(parent, titulo, texto, tono="Azul."):
    DIALOGOS["avisar"].append((titulo, texto))


def falso_preguntar(parent, titulo, texto, aceptar="Aceptar", cancelar="Cancelar"):
    DIALOGOS["preguntar"].append((titulo, texto, aceptar, cancelar))
    return RESPUESTA_PREGUNTAR["v"]


def falso_menu(menu, x, y):
    DIALOGOS["menus"].append(menu)


tk_gestion.pedir_nombre = falso_pedir_nombre
tk_pairs.confirmar_plan = falso_confirmar
tk_servidor.avisar, tk_servidor.preguntar = falso_avisar, falso_preguntar
tk_servidor._mostrar_menu = falso_menu


def dialogos(nombre=None, confirmar=True, preguntar=True) -> None:
    """Reinicia lo apuntado y fija lo que contestan los diálogos."""
    NOMBRE["llamadas"].clear()
    CONFIRMAR["llamadas"].clear()
    for v in DIALOGOS.values():
        v.clear()
    NOMBRE["respuesta"] = nombre
    CONFIRMAR["respuesta"] = confirmar
    RESPUESTA_PREGUNTAR["v"] = preguntar


with sandbox():
    model.RCLONE_CONF.write_text("[nas]\ntype = sftp\nhost = h\n", encoding="utf-8")

    # -----------------------------------------------------------------------
    # 1. La barra y cuándo se enciende
    # -----------------------------------------------------------------------
    dialogos()
    falso = servidor_gestion(estados={1: [CORRIENDO]})
    dlg = abrir(falso)
    b = dlg.barra
    c("los cuatro botones llevan su rótulo",
      tuple(str(w.cget("text")) for w in (b.nueva, b.renombrar, b.cortar, b.borrar)),
      ("Nueva carpeta…", "Renombrar…", "Cortar", "Borrar…"))
    c("la barra va entre la línea del indicador y la lista",
      int(b.marco.grid_info()["row"]) < int(dlg.lista.master.grid_info()["row"]), True)
    c("sin selección solo «Nueva carpeta…»", encendidos(dlg), (True, False, False, False))
    elegir(dlg, "datos")
    c("con una fila todos", encendidos(dlg), (True, True, True, True))
    elegir(dlg, "datos", "leeme.txt")
    c("con dos, «Renombrar…» se apaga", encendidos(dlg), (True, False, True, True))
    dlg.lista.selection_remove("datos", "leeme.txt")
    dlg.update()
    c("quitar la selección los apaga", encendidos(dlg), (True, False, False, False))
    entrar_en(dlg, "datos")
    dialogos(nombre="n1")
    dlg.barra.nueva.invoke()
    c("un cambio en marcha los apaga todos", (bombear(lambda: panel_a_la_vista(dlg)),
                                              encendidos(dlg)), (True, (False,) * 4))
    elegir(dlg, "a.txt")
    c("  y elegir una fila no los enciende", encendidos(dlg), (False,) * 4)
    n = len(falso.ordenes())
    dlg.barra.nueva.invoke()
    dlg.barra.borrar.invoke()
    c("  pulsarlos a la fuerza no lanza otro", (len(falso.ordenes()), len(NOMBRE["llamadas"])),
      (n, 1))
    F.cerrar(dlg)

    F.ARRANQUES[:] = []
    rcd.arrancar = F.no_arranca
    F.ABIERTAS.clear()
    previo = tk_servidor.mostrar
    tk_servidor.mostrar = lambda dlg_, parent=None: (F.ABIERTAS.append(dlg_), dlg_.update())
    tk_servidor.open_dialog(raiz, CFG)
    tk_servidor.mostrar = previo
    dlg = F.ABIERTAS[0]
    c("sin rcd la barra entera está apagada", encendidos(dlg), (False,) * 4)
    F.cerrar(dlg)
    rcd.arrancar = F.arrancar_falso

    # -----------------------------------------------------------------------
    # 2. Renombrar un archivo con F2
    # -----------------------------------------------------------------------
    dialogos(nombre="c.txt")
    falso = servidor_gestion()
    dlg = abrir(falso)
    entrar_en(dlg, "datos")
    vistos: list[int] = []

    def servidor_cambia(_metodo, _params) -> None:
        """Al lanzarse el `movefile`: apunta cuántas veces se había leído «datos» y cambia el nombre."""
        vistos.append(listados_de(falso, "datos"))
        CONTENIDO["datos"] = [e for e in CONTENIDO["datos"] if e["Name"] != "a.txt"] + [
            item("c.txt", tamano=2048)]

    falso.al_lanzar = servidor_cambia
    elegir(dlg, "a.txt")
    antes = listados_de(falso, "datos")
    pulsar(dlg, "<F2>")
    c("F2 abre el diálogo con el nombre del archivo y su aviso de extensión",
      [(t, i, a) for t, i, a, _v in NOMBRE["llamadas"]], [("Renombrar", "a.txt", True)])
    validar = NOMBRE["llamadas"][0][3]
    c("  su `validar` rechaza un nombre ocupado (sin mayúsculas) y deja el propio",
      (validar("B.TXT"), validar("a.txt"), validar("zzz")),
      ("Ya hay algo que se llama «B.TXT» en esta carpeta.", None, None))
    c("se releyó la carpeta del destino (una vez) antes de lanzar", vistos, [antes + 1])
    c("se lanzó UNA orden, `operations/movefile`", [m for m, _p in falso.lanzadas],
      ["operations/movefile"])
    p = falso.ordenes()[0]
    c("  con el origen, el destino y el grupo",
      (p["srcFs"], p["srcRemote"], p["dstFs"], p["dstRemote"], p["_group"]),
      ("nas:/", "datos/a.txt", "nas:/", "datos/c.txt", "gestion-1"))
    c("  y no hay `sync/sync` ni `job/batch`",
      [m for m, _p in falso.llamadas if m in ("sync/sync", "job/batch")], [])
    c("el resultado va a la línea de la ventana, sin panel",
      (bombear(lambda: frase(dlg) == "Renombrado a «c.txt»."), panel_a_la_vista(dlg)),
      (True, False))
    c("la carpeta se releyó y el nombre nuevo queda elegido",
      (nombres(dlg), seleccion(dlg)), (["cat", "fotos", "notas", "b.txt", "c.txt"], ["c.txt"]))
    c("  y los botones vuelven", encendidos(dlg), (True, True, True, True))
    F.cerrar(dlg)

    # Renombrar una carpeta: `sync/move`, y el panel no sale si acaba al primer sondeo
    dialogos(nombre="imagenes")
    falso = servidor_gestion()
    dlg = abrir(falso)
    entrar_en(dlg, "datos")
    elegir(dlg, "fotos")
    dlg.barra.renombrar.invoke()
    c("una carpeta no avisa de extensión", NOMBRE["llamadas"][0][:3],
      ("Renombrar", "fotos", False))
    p = falso.ordenes("sync/move")[0] if falso.ordenes("sync/move") else {}
    c("una carpeta se renombra con `sync/move` a un destino nuevo",
      (p.get("srcFs"), p.get("dstFs"), p.get("deleteEmptySrcDirs")),
      ("nas:/datos/fotos", "nas:/datos/imagenes", True))
    F.cerrar(dlg)

    # El mismo nombre exacto no hace nada
    dialogos(nombre="a.txt")
    falso = servidor_gestion()
    dlg = abrir(falso)
    entrar_en(dlg, "datos")
    elegir(dlg, "a.txt")
    antes = listados_de(falso, "datos")
    dlg.barra.renombrar.invoke()
    c("renombrar al mismo nombre no mira, ni lanza, ni avisa",
      (listados_de(falso, "datos") - antes, falso.lanzadas, DIALOGOS["avisar"],
       encendidos(dlg)), (0, [], [], (True, True, True, True)))
    F.cerrar(dlg)

    # Un nombre que la pantalla no sabe ocupado, pero el servidor sí: se rechaza sin lanzar
    dialogos(nombre="B.TXT")
    falso = servidor_gestion()
    dlg = abrir(falso)
    entrar_en(dlg, "datos")
    elegir(dlg, "a.txt")
    dlg.barra.renombrar.invoke()
    c("un nombre ocupado en el servidor se rechaza con «No se puede»",
      DIALOGOS["avisar"], [("No se puede", "Ya hay algo que se llama «B.TXT» en esta carpeta.")])
    c("  sin lanzar nada y con la ventana libre", (falso.lanzadas, encendidos(dlg)),
      ([], (True, True, True, True)))
    c("  y se dijo «Mirando el destino…» mientras se miraba", tk_servidor.MIRANDO,
      "Mirando el destino…")
    F.cerrar(dlg)

    # El nombre se ocupa en el servidor entre que se abre el diálogo y se lanza
    dialogos(nombre="nuevo")
    falso = servidor_gestion()
    dlg = abrir(falso)
    entrar_en(dlg, "datos")
    elegir(dlg, "a.txt")
    CONTENIDO["datos"].append(item("Nuevo", tamano=1))      # otro lo crea; la pantalla no lo sabe
    c("la pantalla no lo sabía", "Nuevo" in nombres(dlg), False)
    dlg.barra.renombrar.invoke()
    c("  y se rechaza al releer, sin lanzar",
      (DIALOGOS["avisar"], falso.lanzadas),
      ([("No se puede", "Ya hay algo que se llama «nuevo» en esta carpeta.")], []))
    F.cerrar(dlg)

    # -----------------------------------------------------------------------
    # 3. Nueva carpeta, con la tecla y con el botón
    # -----------------------------------------------------------------------
    for como in ("botón", "teclas"):
        dialogos(nombre="nueva")
        falso = servidor_gestion()
        dlg = abrir(falso)
        entrar_en(dlg, "datos")
        falso.al_lanzar = lambda m, p: CONTENIDO["datos"].insert(0, item("nueva", True))
        dlg.lista.selection_remove(*dlg.lista.selection())
        if como == "botón":
            dlg.barra.nueva.invoke()
        else:
            pulsar(dlg, "<Control-N>")
        c(f"[{como}] «Nueva carpeta» pide el nombre con el campo vacío y sin extensión",
          [(t, i, a) for t, i, a, _v in NOMBRE["llamadas"]], [("Nueva carpeta", "", False)])
        p = falso.ordenes("operations/mkdir")
        c("  lanza `operations/mkdir` en la carpeta que se ve",
          [(x["fs"], x["remote"], x["_group"]) for x in p],
          [("nas:/", "datos/nueva", "gestion-1")])
        c("  dice «Creada…» en la línea y deja la carpeta elegida tras releer",
          (bombear(lambda: frase(dlg) == "Creada «nueva»."), seleccion(dlg)),
          (True, ["nueva"]))
        F.cerrar(dlg)

    # Cancelar el diálogo no lanza nada
    dialogos(nombre=None)
    falso = servidor_gestion()
    dlg = abrir(falso)
    dlg.barra.nueva.invoke()
    c("cancelar el diálogo no mira ni lanza", (falso.lanzadas, listados_de(falso, "datos")),
      ([], 0))
    F.cerrar(dlg)

    # Si no se puede mirar el destino: el panel lo dice con «Reintentar» y no se lanza nada
    dialogos(nombre="otra")
    falso = servidor_gestion()
    dlg = abrir(falso)
    entrar_en(dlg, "datos")
    fallos = [rcd.ErrorRc("permission denied", 403)]
    falso.respuestas[("operations/list", "datos")] = (
        lambda: (_ for _ in ()).throw(fallos.pop()) if fallos else lista(*CONTENIDO["datos"]))
    dlg.barra.nueva.invoke()
    c("si no se puede mirar el destino se dice con «Reintentar» y no se lanza",
      (frase_panel(dlg), bool(dlg.panel.reintentar.winfo_manager()), falso.lanzadas),
      ("No tienes permiso para ver esta carpeta.", True, []))
    dlg.panel.reintentar.invoke()
    c("  «Reintentar» vuelve a mirar y crea la carpeta",
      (bombear(lambda: len(falso.lanzadas) == 1), falso.lanzadas[0][0]),
      (True, "operations/mkdir"))
    F.cerrar(dlg)

    # Nueva carpeta dentro de una pareja: avisa y pide confirmar
    dialogos(nombre="semana", confirmar=False)
    falso = servidor_gestion()
    dlg = abrir(falso)
    entrar_en(dlg, "datos")
    entrar_en(dlg, "notas")
    dlg.barra.nueva.invoke()
    c("crear dentro de una pareja enseña el plan con el aviso",
      CONFIRMAR["llamadas"],
      [("Carpeta de una pareja", "", ("Se creará la carpeta «semana» en /datos/notas.",),
        ("La próxima pasada de «Notas» lo copiará al dispositivo.",))])
    c("  y un «no» no lanza nada y libera la ventana",
      (falso.lanzadas, encendidos(dlg)[0]), ([], True))
    F.cerrar(dlg)

    # -----------------------------------------------------------------------
    # 4. Borrar
    # -----------------------------------------------------------------------
    dialogos(confirmar=False)
    falso = servidor_gestion(estados={1: [CORRIENDO, CORRIENDO, ACABADO]})
    dlg = abrir(falso)
    entrar_en(dlg, "datos")
    elegir(dlg, "fotos", "a.txt")
    dlg.barra.borrar.invoke()
    c("borrar cuenta una sola vez, y solo la carpeta",
      [p for m, p in falso.llamadas if m == "operations/size"],
      [{"fs": "nas:/", "remote": "datos/fotos"}])
    c("  la confirmación lleva el título, la nota y una línea por elemento",
      CONFIRMAR["llamadas"],
      [("Borrar del servidor", "El servidor no tiene papelera.",
        ("Se borrará para siempre «fotos», con 12 archivos (5 MB).",
         "Se borrará para siempre «a.txt» (2 KB)."), ())])
    c("  un «no» no lanza nada y libera la ventana",
      (falso.lanzadas, encendidos(dlg), frase(dlg)), ([], (True, False, True, True), ""))

    dialogos(confirmar=True)
    n_listados = listados_de(falso, "datos")
    dlg.barra.borrar.invoke()
    c("un «sí» enseña el panel del borrado",
      bombear(lambda: panel_a_la_vista(dlg) and
              str(dlg.panel.titulo.cget("text")) == "Borrando en /datos"), True)
    c("  y acaba con `purge` y luego `deletefile`, en ese orden",
      (bombear(lambda: frase_panel(dlg) == "Borrados 2."),
       [m for m, _p in falso.lanzadas]), (True, ["operations/purge", "operations/deletefile"]))
    c("  con lo que hay que borrar en cada una",
      [(p["fs"], p["remote"]) for p in falso.ordenes()],
      [("nas:/", "datos/fotos"), ("nas:/", "datos/a.txt")])
    cron = falso.cronologia
    c("  la segunda solo tras el `finished` de la primera",
      cron.index(("estado", 1, True)) < cron.index(("lanzar", 2, "operations/deletefile")),
      True)
    c("  las dos en un mismo grupo (el del segundo intento: el «no» gastó el primero)",
      {p["_group"] for p in falso.ordenes()}, {"gestion-2"})
    c("  y la carpeta se releyó", listados_de(falso, "datos") > n_listados, True)
    F.cerrar(dlg)

    # Supr y el menú llegan al mismo flujo
    dialogos(confirmar=False)
    falso = servidor_gestion()
    dlg = abrir(falso)
    entrar_en(dlg, "datos")
    elegir(dlg, "b.txt")
    pulsar(dlg, "<Delete>")
    c("Supr con una fila abre la confirmación de borrar", [t[0] for t in CONFIRMAR["llamadas"]],
      ["Borrar del servidor"])
    dlg.update()
    x, y, ancho, alto = dlg.lista.bbox("a.txt")
    dlg.lista.event_generate("<Button-3>", x=x + 5, y=y + 3)
    dlg.update()
    c("el botón derecho sobre una fila no elegida la elige", seleccion(dlg), ["a.txt"])
    menu = DIALOGOS["menus"][-1]
    etiquetas = [menu.entrycget(i, "label") for i in range(menu.index("end") + 1)]
    c("  y el menú trae las cinco entradas en su orden",
      etiquetas, ["Nueva carpeta…", "Renombrar…", "Cortar", "Pegar aquí", "Borrar…"])
    c("  con «Pegar aquí» apagado (nada cortado)",
      [str(menu.entrycget(i, "state")) for i in range(5)],
      ["normal", "normal", "normal", "disabled", "normal"])
    dialogos(confirmar=False)
    menu.invoke(4)
    c("«Borrar…» del menú abre la misma confirmación",
      [(t[0], t[2]) for t in CONFIRMAR["llamadas"]],
      [("Borrar del servidor", ("Se borrará para siempre «a.txt» (2 KB).",))])
    # el botón derecho sobre una fila ya elegida no cambia la selección
    elegir(dlg, "a.txt", "b.txt")
    dlg.lista.event_generate("<Button-3>", x=x + 5, y=y + 3)
    c("sobre una fila ya elegida no cambia la selección", seleccion(dlg), ["a.txt", "b.txt"])
    menu = DIALOGOS["menus"][-1]
    c("  y con dos filas «Renombrar…» está apagado",
      str(menu.entrycget(1, "state")), "disabled")
    F.cerrar(dlg)

    # Un bloqueo: la raíz de una pareja
    dialogos()
    falso = servidor_gestion()
    dlg = abrir(falso)
    entrar_en(dlg, "datos")
    elegir(dlg, "notas")
    dlg.barra.borrar.invoke()
    c("borrar la carpeta de una pareja se bloquea con su texto",
      DIALOGOS["avisar"],
      [("No se puede",
        "Ahí está la carpeta de la pareja «Notas»: tocarla desde aquí rompería la pareja.")])
    c("  sin contar, sin preguntar ni lanzar, y con la ventana libre",
      ([m for m, _p in falso.llamadas if m == "operations/size"], CONFIRMAR["llamadas"],
       falso.lanzadas, encendidos(dlg)), ([], [], [], (True, True, True, True)))
    # y la carpeta del catálogo
    DIALOGOS["avisar"].clear()
    elegir(dlg, "cat")
    dlg.barra.borrar.invoke()
    c("la carpeta del catálogo también (sale de `defaults.catalog_path`)",
      DIALOGOS["avisar"],
      [("No se puede", "Ahí está el catálogo de las parejas: tocarlo desde aquí dejaría a los "
                       "dispositivos sin él.")])
    F.cerrar(dlg)

    # Un aviso de pareja: borrar dentro de «Notas»
    dialogos(confirmar=False)
    falso = servidor_gestion()
    dlg = abrir(falso)
    entrar_en(dlg, "datos")
    entrar_en(dlg, "notas")
    elegir(dlg, "hoy.txt")
    dlg.barra.borrar.invoke()
    c("borrar dentro de una pareja enseña el plan con el aviso del modo",
      CONFIRMAR["llamadas"],
      [("Borrar del servidor", "El servidor no tiene papelera.",
        ("Se borrará para siempre «hoy.txt» (10 B).",),
        ("La próxima pasada de «Notas» lo quitará también del dispositivo.",))])
    c("  un archivo no se cuenta con `operations/size`",
      [m for m, _p in falso.llamadas if m == "operations/size"], [])
    F.cerrar(dlg)

    # Contar falla: se dice con «Reintentar» y no se lanza nada
    dialogos(confirmar=True)
    falso = servidor_gestion(tamanos={"datos/fotos": rcd.ErrorRc("permission denied", 403)})
    dlg = abrir(falso)
    entrar_en(dlg, "datos")
    elegir(dlg, "fotos")
    dlg.barra.borrar.invoke()
    c("si contar falla, el panel lo dice y no se pregunta ni se lanza",
      (frase_panel(dlg), CONFIRMAR["llamadas"], falso.lanzadas),
      ("No tienes permiso para ver esta carpeta.", [], []))
    c("  con «Reintentar» y la ventana libre",
      (bool(dlg.panel.reintentar.winfo_manager()), encendidos(dlg)[0]), (True, True))
    falso.tamanos["datos/fotos"] = (3, 300)
    dlg.panel.reintentar.invoke()
    c("  «Reintentar» vuelve a contar y sigue",
      (bombear(lambda: len(falso.lanzadas) == 1), [t[2] for t in CONFIRMAR["llamadas"]]),
      (True, [("Se borrará para siempre «fotos», con 3 archivos (300 B).",)]))
    F.cerrar(dlg)

    # Un borrado que falla a mitad se dice en el panel, sin «Reintentar»
    dialogos(confirmar=True)
    falso = servidor_gestion(estados={1: [ACABADO], 2: [fallado("object not found")]})
    dlg = abrir(falso)
    entrar_en(dlg, "datos")
    elegir(dlg, "b.txt", "a.txt")
    dlg.barra.borrar.invoke()
    c("un fallo al borrar el segundo se cuenta con lo hecho y sin «Reintentar»",
      (bombear(lambda: frase_panel(dlg) != ""), frase_panel(dlg),
       bool(dlg.panel.reintentar.winfo_manager())),
      (True, "Borrados 1 de 2: «b.txt» no se pudo: ya no estaba", False))
    F.cerrar(dlg)

    # -----------------------------------------------------------------------
    # 5. Cerrar con un cambio en marcha
    # -----------------------------------------------------------------------
    espera_previa = rcd.ESPERA_QUIT
    rcd.ESPERA_QUIT = 1.0
    for decision in (False, True):
        dialogos(confirmar=True, preguntar=decision)
        falso = servidor_gestion(estados={1: [CORRIENDO, CORRIENDO, CORRIENDO,
                                              fallado("context canceled")]})
        dlg = abrir(falso)
        entrar_en(dlg, "datos")
        elegir(dlg, "fotos")
        dlg.barra.borrar.invoke()
        c("el borrado está en marcha", bombear(lambda: panel_a_la_vista(dlg)), True)
        dlg.tk.call(dlg.protocol("WM_DELETE_WINDOW"))
        c("cerrar con un cambio en marcha pregunta con su texto", DIALOGOS["preguntar"],
          [("Cambio en marcha", "Hay un cambio en marcha en el servidor. ¿Cancelarlo y cerrar?",
            "Cancelar y cerrar", "Seguir")])
        if decision:
            c("  «Cancelar y cerrar»: se manda `job/stop` y se cierra",
              (bombear(lambda: not dlg.winfo_exists()), falso.paradas_de_trabajo()), (True, 1))
            c("  y el rcd se paró una vez", falso.paradas, 1)
        else:
            c("  «Seguir»: la ventana sigue y no se paró nada",
              (bool(dlg.winfo_exists()), falso.paradas, falso.paradas_de_trabajo()),
              (True, 0, 0))
            F.cerrar(dlg)
    rcd.ESPERA_QUIT = espera_previa

    # -----------------------------------------------------------------------
    # 6. Cortar y pegar aquí
    # -----------------------------------------------------------------------
    model.RCLONE_CONF.write_text("[nas]\ntype = sftp\nhost = h\n\n[otro]\ntype = sftp\nhost = h\n",
                                 encoding="utf-8")
    CONTENIDO_OTRA = {"v": []}

    def servidor_mover(estados=None, otra=None, tamanos=None) -> RcdGestion:
        """Un servidor con «/datos» y «/otra» (con `otra`) además de la raíz con las dos."""
        CONTENIDO_OTRA["v"] = list(otra if otra is not None else [item("viejo.txt")])
        return servidor_gestion(estados=estados, tamanos=tamanos, otras={
            ("operations/list", ""): lista(item("datos", True), item("otra", True),
                                           item("leeme.txt", tamano=2048)),
            ("operations/list", "otra"): lambda: lista(*CONTENIDO_OTRA["v"]),
            ("operations/list", "datos/fotos"): lista(item("sub", True)),
            ("operations/list", "datos/fotos/sub"): lista()})

    def al_mover(falso) -> None:
        """Que el servidor haga lo que hacen las órdenes: lo movido aparece en «/otra»."""
        def hace(metodo, params) -> None:
            nombre = (params["dstFs"].rsplit("/", 1)[-1] if metodo == "sync/move"
                      else params["dstRemote"].rsplit("/", 1)[-1])
            CONTENIDO_OTRA["v"].append(item(nombre, metodo == "sync/move"))
        falso.al_lanzar = hace

    def linea(dlg) -> tuple[bool, str, bool]:
        """Si la línea del corte se ve, lo que dice y si «Pegar aquí» está encendido."""
        k = dlg.cortado
        return (bool(k.winfo_manager()), str(k.texto.cget("text")),
                not k.pegar.instate(["disabled"]))

    def a(dlg, carpeta: str) -> None:
        """Va a esa carpeta del mismo remote: sube hasta la raíz y baja tramo a tramo."""
        while str(dlg.ruta.cget("text")) != "/":
            antes = str(dlg.ruta.cget("text"))
            pulsar(dlg, "<BackSpace>")
            bombear(lambda: str(dlg.ruta.cget("text")) != antes)
        for tramo in [t for t in carpeta.split("/") if t]:
            entrar_en(dlg, tramo)
            bombear(lambda: str(dlg.ruta.cget("text")).endswith(tramo))

    # -- la línea del corte y el paso de una carpeta a otra
    dialogos()
    falso = servidor_mover()
    al_mover(falso)
    dlg = abrir(falso)
    c("sin cortar no hay línea", linea(dlg)[0], False)
    entrar_en(dlg, "datos")
    dlg.lista.event_generate("<Button-3>", x=5, y=5)
    dlg.update()
    c("  ni nada que pegar en el menú", str(DIALOGOS["menus"][-1].entrycget(3, "state")),
      "disabled")
    elegir(dlg, "fotos", "a.txt")
    dlg.barra.cortar.invoke()
    c("«Cortar» enseña la línea: cuántos y desde dónde, con «Pegar aquí» encendido",
      linea(dlg), (True, "2 elementos para mover desde /datos", True))
    c("  la línea va entre la barra y la lista",
      int(dlg.barra.marco.grid_info()["row"]) < int(dlg.cortado.grid_info()["row"])
      < int(dlg.lista.master.grid_info()["row"]), True)
    c("  con sus dos botones",
      (str(dlg.cortado.pegar.cget("text")), str(dlg.cortado.cancelar.cget("text"))),
      ("Pegar aquí", "Cancelar"))
    c("  y la barra sigue como estaba (con dos filas, sin «Renombrar…»)", encendidos(dlg),
      (True, False, True, True))
    a(dlg, "otra")
    c("al navegar la línea sigue igual", linea(dlg), (True, "2 elementos para mover desde /datos", True))
    elegir(dlg, "viejo.txt")                     # una fila elegida en el destino no es lo cortado
    antes = listados_de(falso, "otra")
    pulsar(dlg, "<Control-v>")
    c("Ctrl+V pega: lanza `sync/move` y `movefile`, en ese orden",
      (bombear(lambda: len(falso.lanzadas) == 2), [m for m, _p in falso.lanzadas]),
      (True, ["sync/move", "operations/movefile"]))
    p1, p2 = falso.ordenes()
    c("  la carpeta: origen, destino y `deleteEmptySrcDirs`",
      (p1["srcFs"], p1["dstFs"], p1["deleteEmptySrcDirs"], p1["_group"]),
      ("nas:/datos/fotos", "nas:/otra/fotos", True, "gestion-1"))
    c("  el archivo: `movefile` entre sus rutas, en el mismo grupo",
      (p2["srcFs"], p2["srcRemote"], p2["dstFs"], p2["dstRemote"], p2["_group"]),
      ("nas:/", "datos/a.txt", "nas:/", "otra/a.txt", "gestion-1"))
    c("  y nada sale de la fila elegida en el destino",
      {x for p in falso.ordenes() for x in p.values() if isinstance(x, str) and "viejo" in x},
      set())
    c("  la segunda solo tras el `finished` de la primera",
      falso.cronologia.index(("estado", 1, True))
      < falso.cronologia.index(("lanzar", 2, "operations/movefile")), True)
    c("  y no hay `sync/sync` ni `job/batch`",
      [m for m, _p in falso.llamadas if m in ("sync/sync", "job/batch")], [])
    c("al acabar, la línea del corte desaparece y el resultado va a la línea de la ventana",
      (bombear(lambda: frase(dlg) == "Movidos 2 a /otra."), linea(dlg)[0], panel_a_la_vista(dlg)),
      (True, False, False))
    c("  y «/otra» se leyó dos veces: al mirar el destino y al releer tras pegar",
      listados_de(falso, "otra") - antes, 2)
    c("  la carpeta de destino se releyó y lo movido queda elegido",
      (nombres(dlg), seleccion(dlg)), (["fotos", "a.txt", "viejo.txt"], ["a.txt", "fotos"]))
    c("  y los botones vuelven", encendidos(dlg), (True, False, True, True))
    F.cerrar(dlg)

    # -- uno solo: singular; «Cancelar» quita lo cortado; cortar de nuevo lo sustituye
    dialogos()
    falso = servidor_mover()
    dlg = abrir(falso)
    entrar_en(dlg, "datos")
    elegir(dlg, "b.txt")
    dlg.barra.cortar.invoke()
    c("con uno la línea va en singular", linea(dlg)[1], "1 elemento para mover desde /datos")
    elegir(dlg, "a.txt")
    pulsar(dlg, "<Control-x>")
    dlg.update()
    c("cortar otra vez sustituye lo cortado (Ctrl+X)", linea(dlg)[1],
      "1 elemento para mover desde /datos")
    dlg.cortado.cancelar.invoke()
    c("«Cancelar» de la línea la quita", linea(dlg)[0], False)
    pulsar(dlg, "<Control-v>")
    c("  y Ctrl+V ya no hace nada", (falso.lanzadas, DIALOGOS["avisar"]), ([], []))
    F.cerrar(dlg)

    # -- los rechazos: la misma carpeta, dentro de sí misma, nombres ocupados
    dialogos()
    falso = servidor_mover(otra=[item("viejo.txt"), item("A.TXT"), item("FOTOS", True)])
    dlg = abrir(falso)
    entrar_en(dlg, "datos")
    elegir(dlg, "fotos", "a.txt")
    dlg.barra.cortar.invoke()
    dlg.cortado.pegar.invoke()
    c("pegar en la misma carpeta se rechaza y la línea sigue",
      (DIALOGOS["avisar"], linea(dlg)[0], falso.lanzadas, encendidos(dlg)[0]),
      ([("No se puede", "Ya están en esta carpeta.")], True, [], True))
    DIALOGOS["avisar"].clear()
    entrar_en(dlg, "fotos")
    bombear(lambda: str(dlg.ruta.cget("text")) == "/datos/fotos")
    entrar_en(dlg, "sub")
    bombear(lambda: str(dlg.ruta.cget("text")) == "/datos/fotos/sub")
    dlg.cortado.pegar.invoke()
    c("pegar una carpeta dentro de sí misma se rechaza",
      (DIALOGOS["avisar"], linea(dlg)[0], falso.lanzadas),
      ([("No se puede", "No se puede mover una carpeta dentro de sí misma.")], True, []))
    DIALOGOS["avisar"].clear()
    a(dlg, "otra")
    bombear(lambda: str(dlg.ruta.cget("text")) == "/otra")
    listas = listados_de(falso, "otra")
    dlg.cortado.pegar.invoke()
    c("un nombre ya ocupado en el destino (sin mayúsculas) se rechaza, con el primero y cuántos más",
      DIALOGOS["avisar"],
      [("No se puede", "Ya hay «fotos» y 1 más en /otra: renómbralos antes.")])
    c("  se miró el destino una vez, sin lanzar nada, con la línea y los botones",
      (listados_de(falso, "otra") - listas, falso.lanzadas, linea(dlg)[0], encendidos(dlg)[0]),
      (1, [], True, True))
    DIALOGOS["avisar"].clear()
    CONTENIDO_OTRA["v"] = [item("LEEME.TXT"), item("A.TXT")]
    dlg.cortado.pegar.invoke()
    c("  con una sola se dice cuál", DIALOGOS["avisar"],
      [("No se puede", "Ya hay «a.txt» en /otra: renómbralo antes.")])
    F.cerrar(dlg)

    # -- el nombre se ocupa en el servidor entre que se pulsa y se mira: la pantalla no lo sabe
    dialogos()
    falso = servidor_mover(otra=[item("viejo.txt")])
    dlg = abrir(falso)
    entrar_en(dlg, "datos")
    elegir(dlg, "b.txt")
    dlg.barra.cortar.invoke()
    a(dlg, "otra")
    bombear(lambda: str(dlg.ruta.cget("text")) == "/otra")
    CONTENIDO_OTRA["v"].append(item("B.txt"))
    c("la pantalla no lo sabía", "B.txt" in nombres(dlg), False)
    dlg.cortado.pegar.invoke()
    c("  y se rechaza al releer", (DIALOGOS["avisar"], falso.lanzadas),
      ([("No se puede", "Ya hay «b.txt» en /otra: renómbralo antes.")], []))
    F.cerrar(dlg)

    # -- otro remote: «Pegar aquí» apagado, y el texto lo dice; al volver se enciende
    dialogos()
    falso = servidor_mover()
    dlg = abrir(falso)
    entrar_en(dlg, "datos")
    elegir(dlg, "b.txt")
    dlg.barra.cortar.invoke()
    dlg.elegido.set("otro")
    dlg.elegido.event_generate("<<ComboboxSelected>>")
    bombear(lambda: linea(dlg)[1].endswith("servidor."))
    c("en otro remote la línea añade que solo se pega en el mismo servidor",
      linea(dlg), (True, "1 elemento para mover desde /datos · "
                         "Solo se puede pegar en el mismo servidor.", False))
    pulsar(dlg, "<Control-v>")
    dlg.lista.event_generate("<Button-3>", x=5, y=5)
    dlg.update()
    menu = DIALOGOS["menus"][-1]
    c("  Ctrl+V y el menú tampoco pegan", (falso.lanzadas, str(menu.entrycget(3, "state"))),
      ([], "disabled"))
    dlg.elegido.set("nas")
    dlg.elegido.event_generate("<<ComboboxSelected>>")
    bombear(lambda: linea(dlg)[1] == "1 elemento para mover desde /datos")
    c("  al volver al remote del corte se enciende", linea(dlg), (
        True, "1 elemento para mover desde /datos", True))
    F.cerrar(dlg)

    # -- el menú: «Pegar aquí» encendido con algo cortado, y pega
    dialogos()
    falso = servidor_mover()
    al_mover(falso)
    dlg = abrir(falso)
    entrar_en(dlg, "datos")
    elegir(dlg, "b.txt")
    dlg.barra.cortar.invoke()
    a(dlg, "otra")
    bombear(lambda: str(dlg.ruta.cget("text")) == "/otra")
    dlg.lista.event_generate("<Button-3>", x=5, y=5)
    dlg.update()
    menu = DIALOGOS["menus"][-1]
    c("el menú trae «Pegar aquí» encendido", str(menu.entrycget(3, "state")), "normal")
    menu.invoke(3)
    c("  y pega", (bombear(lambda: len(falso.lanzadas) == 1), falso.lanzadas[0][0]),
      (True, "operations/movefile"))
    F.cerrar(dlg)

    # -- una pareja que no admite lo que llega: espejo de subida; y el aviso de otra
    cfg_espejo = mkcfg((), pairs=[
        {"name": "Notas", "local": "sync-data/notas", "remote_path": "/datos/notas",
         "remote": "nas", "mode": "bisync"},
        {"name": "Espejo", "local": "sync-data/espejo", "remote_path": "/otra",
         "remote": "nas", "mode": "up-mirror"}], defaults={"remote": "nas"})
    dialogos()
    falso = servidor_mover()
    dlg = abrir(falso, cfg=cfg_espejo)
    entrar_en(dlg, "datos")
    elegir(dlg, "b.txt")
    dlg.barra.cortar.invoke()
    a(dlg, "otra")
    bombear(lambda: str(dlg.ruta.cget("text")) == "/otra")
    dlg.cortado.pegar.invoke()
    c("pegar dentro de una pareja up-mirror se bloquea con su texto, sin lanzar y con el corte",
      (DIALOGOS["avisar"], falso.lanzadas, CONFIRMAR["llamadas"], linea(dlg)[0]),
      ([("No se puede", "«Espejo» deja el servidor igual que el dispositivo: lo que pongas "
                        "aquí lo borraría su próxima pasada.")], [], [], True))
    F.cerrar(dlg)

    dialogos(confirmar=False)
    falso = servidor_mover()
    al_mover(falso)
    dlg = abrir(falso)
    entrar_en(dlg, "datos")
    elegir(dlg, "b.txt")
    dlg.barra.cortar.invoke()
    entrar_en(dlg, "notas")
    bombear(lambda: str(dlg.ruta.cget("text")) == "/datos/notas")
    dlg.cortado.pegar.invoke()
    c("pegar dentro de una pareja bisync enseña el plan con su aviso",
      CONFIRMAR["llamadas"],
      [("Carpeta de una pareja", "", ("Se moverá «b.txt» de /datos a /datos/notas.",),
        ("La próxima pasada de «Notas» lo copiará al dispositivo.",))])
    c("  un «no» no lanza nada y deja el corte y la ventana libre",
      (falso.lanzadas, linea(dlg)[0], encendidos(dlg)[0]), ([], True, True))
    dialogos(confirmar=True)
    dlg.cortado.pegar.invoke()
    c("  un «sí» lanza", (bombear(lambda: len(falso.lanzadas) == 1), falso.lanzadas[0][1]["dstRemote"]),
      (True, "datos/notas/b.txt"))
    c("  y quita el corte", (bombear(lambda: not linea(dlg)[0]), linea(dlg)[0]), (True, False))
    F.cerrar(dlg)

    # -- cancelar durante el primer movimiento: el segundo no sale
    for estados, dicho in (
            ({1: [CORRIENDO] * 60 + [fallado("context canceled")]},
             "Cancelado: movidos 0 de 2 · «fotos» puede haber quedado a medias"),
            ({1: [CORRIENDO] * 60 + [ACABADO]}, "Cancelado: movidos 1 de 2")):
        dialogos()
        falso = servidor_mover(estados=estados)
        al_mover(falso)
        dlg = abrir(falso)
        entrar_en(dlg, "datos")
        elegir(dlg, "fotos", "a.txt")
        dlg.barra.cortar.invoke()
        a(dlg, "otra")
        bombear(lambda: str(dlg.ruta.cget("text")) == "/otra")
        dlg.cortado.pegar.invoke()
        c("durante el pegado el panel dice a dónde se mueve y «Pegar aquí» está apagado",
          (bombear(lambda: panel_a_la_vista(dlg)), str(dlg.panel.titulo.cget("text")),
           linea(dlg)[2]), (True, "Moviendo a /otra", False))
        dlg.panel.cancelar.invoke()
        c("  cancelar a mitad: " + dicho,
          (bombear(lambda: frase_panel(dlg) == dicho), len(falso.lanzadas)), (True, 1))
        c("  el corte se quita y la carpeta se relee",
          (bombear(lambda: not linea(dlg)[0]), linea(dlg)[0]), (True, False))
        F.cerrar(dlg)

    # -- falla el segundo: se cuenta y el corte se quita
    dialogos()
    falso = servidor_mover(estados={1: [ACABADO], 2: [fallado("object not found")]})
    al_mover(falso)
    dlg = abrir(falso)
    entrar_en(dlg, "datos")
    elegir(dlg, "fotos", "a.txt")
    dlg.barra.cortar.invoke()
    a(dlg, "otra")
    bombear(lambda: str(dlg.ruta.cget("text")) == "/otra")
    dlg.cortado.pegar.invoke()
    c("un fallo en el segundo movimiento se cuenta, sin «Reintentar»",
      (bombear(lambda: frase_panel(dlg) != ""), frase_panel(dlg),
       bool(dlg.panel.reintentar.winfo_manager())),
      (True, "Movidos 1 de 2: «a.txt» no se pudo: ya no estaba", False))
    c("  y el corte se quita", (bombear(lambda: not linea(dlg)[0]), linea(dlg)[0]), (True, False))
    F.cerrar(dlg)

    # -- no se puede mirar el destino: «Reintentar», nada lanzado y el corte sigue
    dialogos()
    falso = servidor_mover()
    al_mover(falso)
    dlg = abrir(falso)
    entrar_en(dlg, "datos")
    elegir(dlg, "b.txt")
    dlg.barra.cortar.invoke()
    a(dlg, "otra")
    bombear(lambda: str(dlg.ruta.cget("text")) == "/otra")
    fallos = [rcd.ErrorRc("permission denied", 403)]
    falso.respuestas[("operations/list", "otra")] = (
        lambda: (_ for _ in ()).throw(fallos.pop()) if fallos else lista(*CONTENIDO_OTRA["v"]))
    dlg.cortado.pegar.invoke()
    c("si no se puede mirar el destino se dice con «Reintentar» y no se lanza",
      (frase_panel(dlg), bool(dlg.panel.reintentar.winfo_manager()), falso.lanzadas,
       linea(dlg)[0]),
      ("No tienes permiso para ver esta carpeta.", True, [], True))
    dlg.panel.reintentar.invoke()
    c("  «Reintentar» vuelve a mirar y mueve",
      (bombear(lambda: len(falso.lanzadas) == 1), bombear(lambda: not linea(dlg)[0])),
      (True, True))
    F.cerrar(dlg)

    # -- «Reintentar» tras no poder mirar el destino, con lo cortado ya cambiado
    for que in ("«Cancelar» de la línea", "cortar otra cosa"):
        dialogos()
        falso = servidor_mover()
        al_mover(falso)
        dlg = abrir(falso)
        entrar_en(dlg, "datos")
        elegir(dlg, "b.txt")
        dlg.barra.cortar.invoke()
        a(dlg, "otra")
        bombear(lambda: str(dlg.ruta.cget("text")) == "/otra")
        fallos = [rcd.ErrorRc("permission denied", 403)]
        falso.respuestas[("operations/list", "otra")] = (
            lambda: (_ for _ in ()).throw(fallos.pop()) if fallos
            else lista(*CONTENIDO_OTRA["v"]))
        dlg.cortado.pegar.invoke()
        c(f"[{que}] la lectura del destino falló y el panel ofrece «Reintentar»",
          bool(dlg.panel.reintentar.winfo_manager()), True)
        if que.startswith("«"):
            dlg.cortado.cancelar.invoke()
            c("  «Cancelar» de la línea la quita (la ventana está libre)", linea(dlg)[0], False)
        else:
            a(dlg, "datos")
            elegir(dlg, "a.txt")
            dlg.barra.cortar.invoke()
            a(dlg, "otra")
            c("  lo cortado ahora es otra cosa", linea(dlg)[1],
              "1 elemento para mover desde /datos")
        dlg.panel.reintentar.invoke()
        dlg.update()
        c("  «Reintentar» no mueve lo viejo ni lanza nada",
          (falso.lanzadas, bool(dlg.panel.reintentar.winfo_manager())), ([], False))
        if not que.startswith("«"):
            dlg.cortado.pegar.invoke()
            c("  y lo cortado de ahora se pega bien (solo el nuevo)",
              (bombear(lambda: len(falso.lanzadas) == 1), falso.lanzadas[0][1]["srcRemote"]),
              (True, "datos/a.txt"))
        F.cerrar(dlg)

    # -- «Cancelar» de la línea se apaga mientras corre un cambio
    dialogos()
    falso = servidor_mover(estados={1: [CORRIENDO] * 60 + [ACABADO]})
    dlg = abrir(falso)
    entrar_en(dlg, "datos")
    elegir(dlg, "fotos")
    dlg.barra.cortar.invoke()
    c("con la ventana libre «Cancelar» de la línea está encendido",
      not dlg.cortado.cancelar.instate(["disabled"]), True)
    a(dlg, "otra")
    dlg.cortado.pegar.invoke()
    bombear(lambda: panel_a_la_vista(dlg))
    c("  y mientras corre el pegado, apagado", dlg.cortado.cancelar.instate(["disabled"]), True)
    F.cerrar(dlg)

    # -- cerrar la ventana de en medio de un pegado
    dialogos(preguntar=False)
    falso = servidor_mover(estados={1: [CORRIENDO] * 60 + [ACABADO]})
    dlg = abrir(falso)
    entrar_en(dlg, "datos")
    elegir(dlg, "fotos")
    dlg.barra.cortar.invoke()
    a(dlg, "otra")
    bombear(lambda: str(dlg.ruta.cget("text")) == "/otra")
    dlg.cortado.pegar.invoke()
    bombear(lambda: panel_a_la_vista(dlg))
    dlg.tk.call(dlg.protocol("WM_DELETE_WINDOW"))
    c("cerrar a mitad de un pegado pregunta con el texto de los cambios",
      DIALOGOS["preguntar"][0][:2],
      ("Cambio en marcha", "Hay un cambio en marcha en el servidor. ¿Cancelarlo y cerrar?"))
    F.cerrar(dlg)

    # Mientras corre, la línea de «Sin respuesta…» de un cambio dice que sigue en marcha
    c("la línea de «sin respuesta» de un cambio",
      tk_servidor.SIN_RESPUESTA_GESTION,
      "Sin respuesta de rclone… el cambio sigue en marcha; se vuelve a intentar.")
    c("  y las de cierre", (tk_servidor.TITULO_CIERRE_GESTION, tk_servidor.TEXTO_CIERRE_GESTION),
      ("Cambio en marcha", "Hay un cambio en marcha en el servidor. ¿Cancelarlo y cerrar?"))

c("nada ha reventado por el camino", errores, [])
raiz.destroy()
sys.exit(c.report())
