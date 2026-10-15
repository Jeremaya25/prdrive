#!/usr/bin/env python3
"""«Resincronizar…» en la ficha de una pareja (#97): lo que dibuja `tk_pairs`.

Lo que se decide (cuándo se ofrece, qué plan, qué orden) está en `pair_editor` y
en `repair`, y lo comprueban `test_pair_editor.py` y `test_repair.py`. Aquí se
mira el cableado de la ventana de una pareja:

- el bloque vive en «Avanzado», que no tiene widgets hasta que se despliega, y
  solo en una pareja bisync de ESTE dispositivo, con algo con lo que lanzar la
  pasada;
- la casilla de apartar la referencia sale marcada;
- cancelar no hace nada: ni lanza ni aparta;
- confirmar aparta (si la casilla está marcada), cierra la pantalla (es modal: con
  ella delante no se podría usar la ventana de salida, que cuelga de la principal) y
  lanza la orden de «Reparación» con `lanzar`;
- con campos sin guardar, con el config editado a mano o con la carpeta local
  fuera de su sitio no se pregunta ni se lanza nada, tampoco si cambian mientras la
  confirmación está abierta.
"""

from __future__ import annotations

import gc
import hashlib
import inspect
import shutil
import subprocess
import sys
import time
from pathlib import Path

from _harness import Checks, sandbox
from _vista import visibles

from common import bisync, catalog, config_file, model, store

c = Checks("«Resincronizar…» en «Parejas»")

try:
    import tkinter as tk
    from tkinter import messagebox, ttk
    raiz = tk.Tk()
    raiz.withdraw()
except Exception as e:                                   # sin entorno gráfico
    print(f"  (saltado) no hay entorno gráfico: {e}")
    sys.exit(c.report())

from ui import pair_editor, repair, segundo_plano, tk_pairs  # noqa: E402
from ui import tk as uitk  # noqa: E402

errores: list[str] = []
raiz.report_callback_exception = (
    lambda tipo, valor, _tb: errores.append(f"{tipo.__name__}: {valor}"))

RAW = {"defaults": {"remote": "nas"},
       "pair": [{"name": "notas", "local": "sync-data/notas", "remote_path": "/R/notas",
                 "mode": "bisync"},
                {"name": "subida", "local": "sync-data/subida", "remote_path": "/R/subida",
                 "mode": "up"},
                {"name": "copia", "local": "sync-data/copia", "remote_path": "/R/copia",
                 "mode": "up-mirror"}]}
CASILLA = "Apartar la referencia actual antes"
BOTON = repair.ETIQUETA_RESYNC


def sin_red(args):
    """Ningún test habla con un remoto: la lectura del catálogo falla enseguida."""
    return subprocess.CompletedProcess(args, 1, stdout="", stderr="sin conexión")


def dar_vueltas(condicion, limite=5.0) -> bool:
    """Mueve el bucle de eventos hasta que se cumpla la condición o pase el límite."""
    fin = time.monotonic() + limite
    while time.monotonic() < fin:
        raiz.update()
        if condicion():
            return True
        time.sleep(0.02)
    return False


def buscar(ventana, clase, texto):
    """El primer widget de esa clase con ese texto, escondido o no."""
    pendientes = [ventana]
    while pendientes:
        w = pendientes.pop(0)
        if isinstance(w, clase) and str(w.cget("text")) == texto:
            return w
        pendientes += w.winfo_children()
    return None


def pulsar(ventana, texto: str, clase=ttk.Button) -> None:
    """Pulsa el widget con ese texto."""
    buscar(ventana, clase, texto).invoke()


def enseñada(ventana) -> None:
    """Deja la ventana puesta y visible, como la deja `mostrar()` antes de esperar."""
    raiz.deiconify()
    ventana.visor.encajar(ventana)
    ventana.deiconify()
    ventana.update()


def preparar() -> model.Config:
    """Escribe el config, deja a «notas» con carpeta y baseline, y una copia del catálogo."""
    model.CONFIG_FILE.write_text(config_file.dumps(RAW), encoding="utf-8")
    cfg = model.parse_config(RAW)
    notas = next(p for p in cfg.pairs if p.name == "notas")
    notas.local_abs.mkdir(parents=True, exist_ok=True)
    notas.workdir.mkdir(parents=True, exist_ok=True)
    prefijo = bisync.expected_prefix(notas)
    for sufijo in (bisync.PATH1_SUFFIX, bisync.PATH2_SUFFIX):
        (notas.workdir / f"{prefijo}{sufijo}").write_text("x", encoding="utf-8")
    ffile = bisync.filters_file_for(notas)
    if ffile:
        Path(str(ffile) + ".md5").write_text(hashlib.md5(ffile.read_bytes()).hexdigest(),
                                             encoding="utf-8")
    catalog.cache_toml().parent.mkdir(parents=True, exist_ok=True)
    catalog.cache_toml().write_text(config_file.dumps(RAW), encoding="utf-8")
    store.write_json(catalog.cache_meta(), {"pulled_at": "2026-09-30 08:00:00",
                                            "endpoint": "nas:/prdrive-catalog/remote.toml"})
    catalog.run = sin_red
    segundo_plano.olvidar_lecturas()
    return cfg


def escenario(pareja: str, hacer=None, *, con_lanzar: bool = True, catalogo: bool = False,
              confirma: bool = True, antes=None, durante=None, lanzar_falla: bool = False,
              desplegar: bool = True) -> dict:
    """Abre «Parejas», la ficha de esa pareja, y deja que `hacer(ventana, visto)` la maneje.

    Args:
        pareja: La ficha que se abre.
        hacer: Lo que se hace con la ventana de la pareja, ya con «Avanzado» desplegado.
        con_lanzar: Si `open_dialog()` recibe con qué lanzar la pasada.
        catalogo: Si la ficha es la del catálogo en vez de la de este dispositivo.
        confirma: Lo que contesta la confirmación del plan.
        antes: Se llama con el config antes de abrir nada (para estropear algo).
        durante: Se llama con el config mientras la confirmación está abierta, antes de
            contestarla (lo que pasa en los minutos que la persona tarda en decidir).
        lanzar_falla: Si el `lanzar` de la ventana principal lanza una excepción.
        desplegar: Si se pulsa «Mostrar» antes de `hacer`.

    Returns:
        Lo visto: `lanzadas`, `planes`, `avisos`, `botones` (texto y estado) y `casillas`
        (texto) de la ficha, `devuelve` (lo que dio `open_dialog()`), `pantalla_viva` (si «Parejas»
        seguía abierta al lanzar) y el estado de «notas» al acabar (`baseline`, `apartados`).
    """
    visto: dict = {"lanzadas": [], "planes": [], "avisos": [], "pantalla_viva": None}
    with sandbox():
        cfg = preparar()
        if antes is not None:
            antes(cfg)
        notas = next(p for p in cfg.pairs if p.name == "notas")

        def lanzar(titulo, args):
            """El `lanzar` de la ventana principal: apunta qué se pide y si «Parejas» seguía."""
            visto["lanzadas"].append((titulo, list(args)))
            visto["pantalla_viva"] = visto["dlg"].winfo_exists()
            if lanzar_falla:
                raise RuntimeError("no se abre la ventana de salida")

        def confirmar(parent, plan, titulo, nota, suelto=False):
            """Apunta el plan que se enseña y contesta lo que toque."""
            visto["planes"].append(plan)
            if durante is not None:
                durante(cfg)
            return confirma

        def avisar(titulo, texto=None, **_k):
            """Apunta lo que se le dice a la persona."""
            visto["avisos"].append(str(texto))

        tk_pairs.confirmar_plan = confirmar
        messagebox.showinfo = messagebox.showerror = avisar
        messagebox.askokcancel = lambda *a, **k: True
        gc.collect()

        def conducir(dlg):
            """Espera al catálogo, elige la pareja y abre su ficha."""
            visto["dlg"] = dlg
            dar_vueltas(lambda: not dlg.sondeo.esperando)
            enseñada(dlg)
            if catalogo:
                pulsar(dlg, "Catálogo", ttk.Radiobutton)
            dlg.lista.elegir(pareja)
            fuera = tk_pairs.mostrar

            def en_ella(ventana, parent=None, **_k):
                """Sustituye a `mostrar()` mientras dura la ventana: la conduce y la cierra."""
                tk_pairs.mostrar = fuera
                try:
                    enseñada(ventana)
                    visto["antes_de_desplegar"] = buscar(ventana, ttk.Button, BOTON) is not None
                    if desplegar:
                        pulsar(ventana, "Mostrar")
                    visto["botones"] = [(str(w.cget("text")), str(w.cget("state")))
                                        for w in visibles(ventana, "TButton", BOTON)]
                    visto["casillas"] = [str(w.cget("text"))
                                         for w in visibles(ventana, "TCheckbutton", CASILLA)]
                    if hacer is not None:
                        hacer(ventana, visto)
                finally:
                    if ventana.winfo_exists():
                        ventana.destroy()

            tk_pairs.mostrar = en_ella
            try:
                visibles(dlg, "TButton", "Modificar…")[0].invoke()
            finally:
                tk_pairs.mostrar = fuera

        def mostrar(dlg, parent=None, **_k):
            """Sustituye a `mostrar()`: conduce la pantalla y la cierra si sigue abierta."""
            try:
                conducir(dlg)
            finally:
                if dlg.winfo_exists():
                    dlg.destroy()

        tk.Toplevel.wait_window = lambda self, *a, **k: None
        uitk.pantalla_util = lambda win: (3000, 3000)
        tk_pairs.mostrar = mostrar
        kw = {"lanzar": lanzar} if con_lanzar else {}
        visto["devuelve"] = tk_pairs.open_dialog(raiz, cfg, **kw)
        visto["baseline"] = notas.workdir.is_dir()
        visto["apartados"] = len(list(model.STATE_DIR.glob("notas.old-*")))
        visto["cfg"] = cfg
    return visto


# ---------------------------------------------------------------------------
# 1. Cuándo se ofrece
# ---------------------------------------------------------------------------
visto = escenario("notas", desplegar=False)
c("«Avanzado» plegado no tiene widgets, tampoco el de «Resincronizar…»",
  visto["antes_de_desplegar"], False)

visto = escenario("notas")
c("una pareja bisync de este dispositivo: el botón está, en «Avanzado», y encendido aunque "
  "el diagnóstico no vea motivo para un resync", visto["botones"], [(BOTON, "normal")])
c("  con la casilla de apartar la referencia", visto["casillas"], [CASILLA])

for pareja, modo in (("subida", "up"), ("copia", "up-mirror")):
    visto = escenario(pareja)
    c(f"{pareja} ({modo}): ni botón ni casilla", (visto["botones"], visto["casillas"]), ([], []))

visto = escenario("notas", con_lanzar=False)
c("sin con qué lanzar la pasada no se ofrece", (visto["botones"], visto["casillas"]), ([], []))

visto = escenario("notas", catalogo=True)
c("en la ficha del catálogo no se ofrece: una pareja del catálogo no tiene referencia aquí",
  (visto["botones"], visto["casillas"]), ([], []))


# ---------------------------------------------------------------------------
# 2. Lo que pasa al pulsarlo
# ---------------------------------------------------------------------------
def marcada(ventana) -> bool:
    """Si la casilla de apartar está marcada en esa ventana."""
    return bool(ventana.editor.apartar.get())


def pulsar_resync(ventana, visto) -> None:
    """Pulsa «Resincronizar…» con la casilla como esté."""
    visto["marcada"] = marcada(ventana)
    visibles(ventana, "TButton", BOTON)[0].invoke()


visto = escenario("notas", pulsar_resync, confirma=False)
notas = next(p for p in visto["cfg"].pairs if p.name == "notas")
c("la casilla sale marcada", visto["marcada"], True)
c("cancelar: se enseñó un plan y no se lanza nada", (len(visto["planes"]), visto["lanzadas"]),
  (1, []))
c("  ni se aparta la referencia", (visto["baseline"], visto["apartados"]), (True, 0))
c("  y «Parejas» sigue abierta: no se ha cerrado nada", visto["devuelve"], False)

plan = visto["planes"][0]
c("el plan que se enseña es el de «Reparación»: título, avisos y orden",
  (plan.titulo, plan.warnings, plan.args),
  (repair.aviso_resync(repair.hallazgo_resync(notas)).titulo,
   repair.aviso_resync(repair.hallazgo_resync(notas)).warnings,
   repair.args_resync(repair.hallazgo_resync(notas))))
c("  con la casilla marcada, avisa de dónde queda la referencia",
  any("state/notas.old-" in x for x in plan.consequences), True)

visto = escenario("notas", pulsar_resync)
notas = next(p for p in visto["cfg"].pairs if p.name == "notas")
pedido = repair.hallazgo_resync(notas)
c("confirmar lanza la orden de «Reparación» con `lanzar`, una vez",
  visto["lanzadas"], [(repair.aviso_resync(pedido).titulo, repair.args_resync(pedido))])
c("  la orden es la de un resync aprobado", visto["lanzadas"][0][1], ["notas", "--resync", "--yes"])
c("  con la casilla marcada, la referencia queda apartada antes de lanzar",
  (visto["baseline"], visto["apartados"]), (False, 1))
c("  «Parejas» se cierra antes, que con su captura delante no se podría usar la ventana de salida",
  visto["pantalla_viva"], False)
c("  no marca el config como cambiado: la principal ya relee `state/` al cerrarse la ventana "
  "de salida, y una lectura antes dejaría ver «necesita un --resync» mientras `sync.py` escribe",
  visto["devuelve"], False)


def sin_apartar(ventana, visto) -> None:
    """Desmarca la casilla y pulsa «Resincronizar…»."""
    pulsar(ventana, CASILLA, ttk.Checkbutton)
    pulsar_resync(ventana, visto)


visto = escenario("notas", sin_apartar)
c("sin la casilla, se lanza lo mismo", visto["lanzadas"][0][1], ["notas", "--resync", "--yes"])
c("  pero la referencia no se toca", (visto["marcada"], visto["baseline"], visto["apartados"]),
  (False, True, 0))
c("  y el plan lo dice", any("no se aparta" in x for x in visto["planes"][0].consequences), True)


def con_cambios(ventana, visto) -> None:
    """Escribe en un campo sin guardar y pulsa «Resincronizar…»."""
    ventana.editor.campos["remote_path"].set("/R/otra")
    visto["hay_cambios"] = ventana.ventana.hay_cambios()
    pulsar_resync(ventana, visto)


visto = escenario("notas", con_cambios)
c("con campos sin guardar no se pregunta ni se lanza: el resync usa la pareja guardada",
  (visto["hay_cambios"], visto["planes"], visto["lanzadas"]), (True, [], []))
c.contains("  y se dice por qué", " ".join(visto["avisos"]), "sin guardar")
c("  ni se toca la referencia", (visto["baseline"], visto["apartados"]), (True, 0))


def sin_carpeta(cfg) -> None:
    """Quita la carpeta local de «notas», que tiene baseline."""
    shutil.rmtree(next(p for p in cfg.pairs if p.name == "notas").local_abs)


visto = escenario("notas", pulsar_resync, antes=sin_carpeta)
c("con la carpeta local fuera de su sitio no se pregunta ni se lanza",
  (visto["planes"], visto["lanzadas"]), ([], []))
c.contains("  y se dice que no existe", " ".join(visto["avisos"]), "no existe")
c("  ni se aparta la referencia, que es lo que frena la pasada",
  (visto["baseline"], visto["apartados"]), (True, 0))


def pulsar_y_leer_nota(ventana, visto) -> None:
    """Pulsa «Resincronizar…» y apunta lo que dice el pie de «Parejas» después."""
    pulsar_resync(ventana, visto)
    visto["nota"] = visto["dlg"].pantalla.pie_nota.cget("text")


def editada_a_mano(ventana, visto) -> None:
    """Edita `sync_config.toml` por fuera y pulsa «Resincronizar…»."""
    nuevo = {**RAW, "pair": [*RAW["pair"], {"name": "otra", "local": "sync-data/otra",
                                            "remote_path": "/R/otra", "mode": "up"}]}
    model.CONFIG_FILE.write_text(config_file.dumps(nuevo), encoding="utf-8")
    pulsar_y_leer_nota(ventana, visto)


visto = escenario("notas", editada_a_mano)
c("si el config se ha editado a mano mientras tanto, no se pregunta ni se lanza",
  (visto["planes"], visto["lanzadas"]), ([], []))
c("  ni se toca la referencia", (visto["baseline"], visto["apartados"]), (True, 0))
c("  y el pie dice qué hacer: volver a pulsar «Resincronizar…», no «guardar»",
  visto["nota"], tk_pairs.AVISO_CAMBIADO_RESYNC)


# ---------------------------------------------------------------------------
# 3. Lo que pasa mientras la confirmación está abierta (puede estarlo minutos)
# ---------------------------------------------------------------------------
def edita_el_config(cfg) -> None:
    """Edita `sync_config.toml` por fuera: cambia el remoto de «notas»."""
    nuevo = {**RAW, "pair": [{**RAW["pair"][0], "remote_path": "/R/otra-ruta"},
                             *RAW["pair"][1:]]}
    model.CONFIG_FILE.write_text(config_file.dumps(nuevo), encoding="utf-8")


def desmonta_el_volumen(cfg) -> None:
    """Quita la carpeta local de «notas», como un volumen que se desmonta."""
    shutil.rmtree(next(p for p in cfg.pairs if p.name == "notas").local_abs)


visto = escenario("notas", pulsar_y_leer_nota, durante=edita_el_config)
c("si el config se edita a mano con la confirmación abierta, el «sí» no hace nada",
  (len(visto["planes"]), visto["lanzadas"]), (1, []))
c("  ni aparta la referencia de la definición de antes", (visto["baseline"], visto["apartados"]),
  (True, 0))
c("  y el pie lo dice", visto["nota"], tk_pairs.AVISO_CAMBIADO_RESYNC)

for que, hacer in (("con la casilla", pulsar_resync), ("sin ella", sin_apartar)):
    visto = escenario("notas", hacer, durante=desmonta_el_volumen)
    c(f"si la carpeta local desaparece con la confirmación abierta ({que}), el «sí» no lanza nada",
      (len(visto["planes"]), visto["lanzadas"]), (1, []))
    c.contains("  y dice que no existe", " ".join(visto["avisos"]), "no existe")
    c("  ni aparta la referencia: sin ella, `sync.py` no abortaría y crearía la carpeta vacía",
      (visto["baseline"], visto["apartados"]), (True, 0))

visto = escenario("notas", pulsar_resync, lanzar_falla=True)
c("si `lanzar` falla después de apartar la referencia, el error sigue su camino",
  errores, ["RuntimeError: no se abre la ventana de salida"])
errores.clear()
c("  y entonces sí avisa a la principal de que hay algo que releer",
  (visto["devuelve"], visto["baseline"], visto["apartados"]), (True, False, 1))

# ---------------------------------------------------------------------------
# 4. Cómo se llama
# ---------------------------------------------------------------------------
for nombre, funcion in (("open_dialog", tk_pairs.open_dialog),
                        ("PantallaParejas", tk_pairs.PantallaParejas.__init__)):
    parametros = inspect.signature(funcion).parameters
    c(f"{nombre}: `lanzar` y `compartida` solo se pasan por nombre (una por posición entraría "
      "como la otra sin avisar)",
      (parametros["lanzar"].kind, parametros["compartida"].kind),
      (inspect.Parameter.KEYWORD_ONLY, inspect.Parameter.KEYWORD_ONLY))

c("nada ha reventado", errores, [])

sys.exit(c.report())
