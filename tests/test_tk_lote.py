#!/usr/bin/env python3
"""`ui/tk_lote.Seguimiento` sigue una lista de órdenes de `rcd` una tras otra.

Ningún test arranca rclone ni toca la red: un `RcdFalso` contesta `job/status` por
`jobid` y `core/stats`, y `segundo_plano.lanzar` corre en el acto. Lo que se
comprueba es lo que ve la persona y lo que le llega a rclone:

- tres lanzadores corren en orden (jobid 1, 2, 3), cada uno solo cuando el
  anterior dio `finished`, y `resultado` recibe los tres estados;
- un estado fallido en medio no corta el siguiente;
- «Cancelar» durante la primera: un solo `job/stop` con su jobid, las demás
  órdenes sin lanzar y `resultado(..., cancelado=True)`; si lo que iba acabó bien
  y no quedó nada por hacer, no se dice «cancelado»;
- `panel_tardio`: sin panel mientras todo acaba al primer sondeo (y el texto ok
  va a la línea de la ventana), con panel en cuanto un sondeo dice que sigue;
- «job not found» acaba todo el lote con «No se sabe cómo acabó…» y no lanza más;
- un `rcd` muerto con el seguimiento fallando: «Reconectar» y `perdida`;
- sin respuesta con el `rcd` vivo: la línea tras `fallos_para_avisar` fallos y
  se quita al contestar; el lote no se suelta;
- un fallo antes de lanzar (`acabar_con_error`), «Reintentar», `soltar()`;
- cerrar con trabajo lanzado: `job/stop` y espera antes de `despues()`.
"""

from __future__ import annotations

import sys
import threading
import time

from _harness import Checks

from common import rcd

c = Checks("«Servidor»: el seguimiento de un lote")

try:
    import tkinter as tk
    raiz = tk.Tk()
    raiz.withdraw()
except Exception as e:                                   # sin entorno gráfico
    print(f"  (saltado) no hay entorno gráfico: {e}")
    sys.exit(c.report())

from ui import segundo_plano, tk_lote, tk_transferencia, transferencia  # noqa: E402
from ui.tk import Sondeo  # noqa: E402

errores: list[str] = []
raiz.report_callback_exception = (
    lambda tipo, valor, _tb: errores.append(f"{tipo.__name__}: {valor}"))
LANZAR_DE_VERDAD = segundo_plano.lanzar
segundo_plano.lanzar = segundo_plano.en_el_acto

CORRIENDO = {"finished": False}
ACABADO = {"finished": True, "success": True}
FALLADO = {"finished": True, "success": False, "error": "permission denied"}
CANCELADO = {"finished": True, "success": False, "error": "context canceled"}
PERDIDA = "Se perdió la conexión con rclone."
FALLOS = 3


class RcdFalso:
    """Un `Rcd` que da `job/status` por `jobid` y apunta lo que le piden, en orden."""

    def __init__(self, estados: dict[int, list]) -> None:
        self.estados = {k: list(v) for k, v in estados.items()}
        self.orden: list[tuple] = []
        self.vivo = True
        self.al_estado = None              # función (jobid) → respuesta o excepción, si se da
        self.parar_con = CANCELADO         # el estado que deja `job/stop`

    def llamar(self, metodo, params=None, timeout=None):
        params = params or {}
        if metodo == "core/stats":
            return {"transfers": 1, "totalTransfers": 3}
        if metodo == "job/stop":
            self.orden.append(("stop", params["jobid"]))
            self.estados[params["jobid"]] = [self.parar_con]
            return {}
        if metodo == "job/status":
            jobid = params["jobid"]
            if self.al_estado is not None:
                respuesta = self.al_estado(jobid)
                if isinstance(respuesta, Exception):
                    self.orden.append(("estado", jobid, "error"))
                    raise respuesta
                if respuesta is not None:
                    self.orden.append(("estado", jobid, bool(respuesta.get("finished"))))
                    return respuesta
            cola = self.estados[jobid]
            respuesta = cola.pop(0) if len(cola) > 1 else cola[0]
            self.orden.append(("estado", jobid, bool(respuesta.get("finished"))))
            return respuesta
        raise AssertionError(metodo)

    def paradas(self) -> list[int]:
        return [o[1] for o in self.orden if o[0] == "stop"]


class Escena:
    """Una ventana con su panel, su sondeo y un `Seguimiento`, y lo que éste dijo."""

    def __init__(self, falso: RcdFalso) -> None:
        self.falso = falso
        self.ventana = tk.Toplevel(raiz)
        self.ventana.withdraw()
        self.panel = tk_transferencia.Panel(self.ventana)
        self.panel.marco.grid(row=0, column=0)
        self.panel.ocultar()
        self.dichos: list[tuple] = []
        self.cambios = 0
        self.panel_enseñado: list[str] = []
        original = self.panel.mostrar_progreso
        self.panel.mostrar_progreso = lambda p: (self.panel_enseñado.append(p.titulo),
                                                 original(p))[1]
        self.cancelando: list[str] = []
        original_c = self.panel.mostrar_cancelando
        self.panel.mostrar_cancelando = lambda *a: (self.cancelando.append(a[0] if a else ""),
                                                    original_c(*a))[1]
        self.sondeo = Sondeo(self.ventana)
        self.seg = tk_lote.Seguimiento(
            self.ventana, self.panel, self.sondeo,
            decir=lambda texto, tono="Peligro.", boton=None: self.dichos.append(
                (texto, tono, boton)),
            intervalo_ms=lambda: 5, fallos_para_avisar=lambda: FALLOS, perdida=PERDIDA,
            al_cambiar=self.cambio)
        self.lanzados: list[int] = []
        self.resultados: list[tuple] = []
        self.acabados: list[transferencia.Resultado] = []
        self.reintentos = 0

    def cambio(self) -> None:
        self.cambios += 1

    def lanzador(self, jobid: int):
        """Un lanzador que apunta que se llamó y devuelve su jobid."""
        def lanzar(r, grupo):
            self.lanzados.append(jobid)
            r.orden.append(("lanzar", jobid, grupo))
            return jobid
        return lanzar

    def trabajo(self, jobids=(1, 2, 3), **campos) -> tk_lote.Trabajo:
        def resultado(estados, stats, cancelado):
            self.resultados.append((list(estados), dict(stats), cancelado))
            ok = all(e.get("success") for e in estados) and not cancelado
            return transferencia.Resultado(f"fin {len(estados)}", "ok" if ok else "aviso", False)
        datos = dict(
            rcd=self.falso, grupo="gestion-1",
            lanzadores=[self.lanzador(j) for j in jobids],
            progreso=lambda s, hechos, total: transferencia.Progreso(
                f"orden {hechos} de {total}", "", "", 0.5, ""),
            resultado=resultado, al_acabar=self.acabados.append,
            cancelando=lambda i: f"Cancelando la {i}")
        datos.update(campos)
        return tk_lote.Trabajo(**datos)

    def empezar(self, **campos) -> tk_lote.Trabajo:
        t = self.trabajo(**campos)
        self.seg.abrir(t)
        self.seg.lanzar(t)
        return t

    def frases(self) -> list[str]:
        return [d[0] for d in self.dichos]

    def a_la_vista(self) -> bool:
        return bool(self.panel.marco.winfo_manager())

    def frase_panel(self) -> str:
        from tkinter import ttk
        for w in self.panel.resultado.winfo_children():
            for h in [w, *w.winfo_children()]:
                if isinstance(h, ttk.Label) and h.cget("text"):
                    return str(h.cget("text"))
        return ""

    def cerrar(self) -> None:
        self.seg.parar()
        self.ventana.destroy()


def bombear(condicion, tope: float = 5.0) -> bool:
    fin = time.monotonic() + tope
    while not condicion() and time.monotonic() < fin:
        raiz.update()
        time.sleep(0.003)
    return bool(condicion())


def pausa(veces: int = 30) -> None:
    for _ in range(veces):
        raiz.update()
        time.sleep(0.003)


# --- 1. tres órdenes, una tras otra --------------------------------------------
e = Escena(RcdFalso({1: [CORRIENDO, ACABADO], 2: [CORRIENDO, CORRIENDO, ACABADO],
                     3: [ACABADO]}))
e.panel.mostrar_progreso(transferencia.Progreso("viejo", "", "", 0.1, ""))
t = e.trabajo()
e.seg.abrir(t)
c("abrir deja el panel oculto y avisa del cambio",
  (e.seg.activo is t, e.a_la_vista(), e.cambios >= 1), (True, False, True))
e.seg.lanzar(t)
c("termina con el resultado de las tres", bombear(lambda: e.resultados != []), True)
c("  lanzadas en orden", e.lanzados, [1, 2, 3])
c("  `resultado` recibió los tres estados, sin cancelar",
  ([len(r[0]) for r in e.resultados], [r[2] for r in e.resultados]), ([3], [False]))
orden = e.falso.orden
c("  cada una solo tras el `finished` de la anterior",
  (orden.index(("estado", 1, True)) < orden.index(("lanzar", 2, "gestion-1")),
   orden.index(("estado", 2, True)) < orden.index(("lanzar", 3, "gestion-1"))), (True, True))
c("  las tres con el mismo grupo",
  {o[2] for o in orden if o[0] == "lanzar"}, {"gestion-1"})
c("  el panel enseña el resultado", e.frase_panel(), "fin 3")
c("  `al_acabar` lo recibe y el trabajo se suelta", (len(e.acabados), e.seg.activo),
  (1, None))
c("  el progreso sabe cuántas van hechas y cuántas son",
  {"orden 0 de 3", "orden 1 de 3", "orden 2 de 3"} <= set(e.panel_enseñado), True)
e.cerrar()

# --- 2. un estado fallido en medio no corta el siguiente ------------------------
e = Escena(RcdFalso({1: [ACABADO], 2: [FALLADO], 3: [ACABADO]}))
e.empezar()
c("se lanzan las tres aunque la segunda falle", (bombear(lambda: e.resultados != []), e.lanzados),
  (True, [1, 2, 3]))
c("  y los tres estados llegan a `resultado`, con el fallido en su sitio",
  [r.get("success") for r in e.resultados[0][0]], [True, False, True])
e.cerrar()

# --- 3. cancelar durante la primera ---------------------------------------------
e = Escena(RcdFalso({1: [CORRIENDO], 2: [ACABADO], 3: [ACABADO]}))
t = e.empezar()
c("la primera orden va y el panel está a la vista",
  (bombear(lambda: ("estado", 1, False) in e.falso.orden), e.a_la_vista()), (True, True))
e.seg.cancelar()
c("«Cancelar» dice «Cancelando…» con el texto del que va", e.cancelando[:1], ["Cancelando la 0"])
e.seg.cancelar()
c("  y solo manda un `job/stop`, al jobid de la que va", e.falso.paradas(), [1])
c("  acaba sin lanzar las demás", (bombear(lambda: e.resultados != []), e.lanzados), (True, [1]))
c("  `resultado` recibe un estado y cancelado=True",
  ([len(r[0]) for r in e.resultados], [r[2] for r in e.resultados]), ([1], [True]))
c("  el trabajo se suelta", e.seg.activo, None)
e.cerrar()

# cancelar con la última orden en marcha, que acaba bien: no queda nada sin hacer
e = Escena(RcdFalso({1: [ACABADO], 2: [CORRIENDO]}))
e.falso.parar_con = ACABADO             # el stop llega tarde: la orden ya acabó bien
e.empezar(jobids=(1, 2))
bombear(lambda: ("estado", 2, False) in e.falso.orden)
e.seg.cancelar()
bombear(lambda: e.resultados != [])
c("cancelar la última cuando ésta acaba bien no cuenta como cancelado",
  [r[2] for r in e.resultados], [False])
e.cerrar()

# cancelar con la primera en marcha y que ésta acabe bien: la siguiente no se lanza
e = Escena(RcdFalso({1: [CORRIENDO], 2: [ACABADO]}))
e.falso.parar_con = ACABADO             # acaba bien justo cuando se pide cancelar
e.empezar(jobids=(1, 2))
bombear(lambda: ("estado", 1, False) in e.falso.orden)
e.seg.cancelar()
bombear(lambda: e.resultados != [])
c("cancelar la primera y que acabe bien: la siguiente no se lanza y se dice cancelado",
  (e.lanzados, [r[2] for r in e.resultados], len(e.resultados[0][0])), ([1], [True], 1))
e.cerrar()

# --- 4. panel_tardio: todo acaba al primer sondeo -----------------------------
e = Escena(RcdFalso({1: [ACABADO]}))
e.empezar(jobids=(1,), panel_tardio=True)
c("`panel_tardio` y todo acabado al primer sondeo: la línea dice el texto ok",
  (bombear(lambda: e.resultados != []), e.dichos[-1]), (True, ("fin 1", "Pista.", None)))
c("  y el panel nunca se enseñó", (e.a_la_vista(), e.panel_enseñado), (False, []))
c("  el trabajo se suelta y `al_acabar` se entera", (e.seg.activo, len(e.acabados)), (None, 1))
e.cerrar()

# tardío pero con un fallo: el panel sí lo cuenta
e = Escena(RcdFalso({1: [FALLADO]}))
e.empezar(jobids=(1,), panel_tardio=True)
bombear(lambda: e.resultados != [])
c("`panel_tardio` con un resultado de aviso: sale en el panel, no en la línea",
  (e.a_la_vista(), e.frase_panel(), e.frases()), (True, "fin 1", []))
e.cerrar()

# --- 5. panel_tardio: el primer sondeo dice que sigue -------------------------
e = Escena(RcdFalso({1: [CORRIENDO, CORRIENDO, ACABADO]}))
e.empezar(jobids=(1,), panel_tardio=True)
c("`panel_tardio` y un primer sondeo sin acabar: el panel sale",
  bombear(lambda: e.a_la_vista() and bool(e.panel.titulo.winfo_manager())), True)
c("  mientras tanto, nada en la línea", e.frases(), [])
bombear(lambda: e.resultados != [])
c("  y al acabar, el resultado en el panel", e.frase_panel(), "fin 1")
e.cerrar()

# sin `panel_tardio` el panel sale al lanzar
e = Escena(RcdFalso({1: [CORRIENDO]}))
e.empezar(jobids=(1,))
c("sin `panel_tardio` el panel sale en cuanto se lanza", e.a_la_vista(), True)
e.cerrar()

# --- 6. «job not found» en la segunda ---------------------------------------
e = Escena(RcdFalso({1: [ACABADO], 2: [CORRIENDO]}))
e.falso.al_estado = lambda j: rcd.ErrorRc("job not found", 500) if j == 2 else None
e.empezar(sin_respuesta="Sin respuesta…")
c("«job not found» en la segunda acaba todo el lote",
  (bombear(lambda: e.frase_panel() != ""), e.frase_panel()),
  (True, "No se sabe cómo acabó: revisa la carpeta."))
c("  sin lanzar la tercera", e.lanzados, [1, 2])
c("  el lote se suelta, sin `resultado` del trabajo ni «Reintentar»",
  (e.seg.activo, e.resultados, bool(e.panel.reintentar.winfo_manager())), (None, [], False))
e.cerrar()

# --- 7. rcd muerto con el seguimiento fallando --------------------------------
e = Escena(RcdFalso({1: [CORRIENDO]}))
e.falso.al_estado = lambda j: rcd.RcdCaido("se cortó")
e.falso.vivo = False
e.empezar(jobids=(1,), sin_respuesta="Sin respuesta…")
c("con el `rcd` muerto el fallo se dice con «Reconectar»",
  (bombear(lambda: e.seg.activo is None), e.dichos[-1][2]), (True, "Reconectar"))
c("  el panel dice que se perdió la conexión, sin «Reintentar»",
  (e.frase_panel(), bool(e.panel.reintentar.winfo_manager())), (PERDIDA, False))
c("  y `al_acabar` no se llama (no se relee con la conexión perdida)", e.acabados, [])
e.cerrar()

# --- 8. sin respuesta con el rcd vivo ----------------------------------------
e = Escena(RcdFalso({1: [CORRIENDO]}))
fallos_ = [0]
sana = [False]


def intermitente(jobid):
    if sana[0]:
        return CORRIENDO
    fallos_[0] += 1
    return rcd.RcdCaido("timed out")


e.falso.al_estado = intermitente
e.empezar(jobids=(1,), sin_respuesta="Sin respuesta…")
c("tras `fallos_para_avisar` fallos la línea dice «Sin respuesta…»",
  bombear(lambda: "Sin respuesta…" in e.frases()), True)
c("  con tono de aviso y sin botón", e.dichos[-1], ("Sin respuesta…", "Aviso.", None))
c("  y el trabajo sigue en marcha", e.seg.activo is not None, True)
pausa()
c("  tras mucho tiempo sin contestar no se soltó", e.seg.activo is not None, True)
sana[0] = True
c("  al contestar otra vez la línea se quita",
  (bombear(lambda: e.dichos[-1][0] == ""), e.dichos[-1][1]), (True, "Pista."))
e.falso.al_estado = lambda j: ACABADO
c("  y al acabar acaba bien", bombear(lambda: e.resultados != []), True)
e.cerrar()

# --- 9. fallo antes de lanzar --------------------------------------------------
e = Escena(RcdFalso({}))


def reintento():
    e.reintentos += 1


t = e.trabajo(jobids=(1,))
e.seg.abrir(t)
e.seg.acabar_con_error(t, rcd.ErrorRc("boom", 500), reintento)
c("un fallo antes de lanzar sale en el panel, con su `resultado`",
  (len(e.resultados), e.resultados[0][0], e.seg.activo), (1, [{"success": False, "error": "boom"}], None))
c("  `al_acabar` se entera", len(e.acabados), 1)
c("  «Reintentar» no se ofrece si el resultado no lo pide", e.seg.reintento, None)
e.cerrar()

e = Escena(RcdFalso({}))
t = e.trabajo(jobids=(1,),
              resultado=lambda es, s, ca: transferencia.Resultado("falló", "aviso", True))
e.seg.abrir(t)
e.seg.acabar_con_error(t, rcd.ErrorRc("boom", 500), reintento)
c("si el resultado pide «Reintentar», se ofrece el que se dio",
  (e.seg.reintento is reintento, bool(e.panel.reintentar.winfo_manager())), (True, True))
e.seg.reintentar()
c("  y `reintentar()` lo llama", e.reintentos, 1)
e.seg.abrir(e.trabajo(jobids=(1,)))
e.seg.reintentar()
c("  con un trabajo en marcha no se llama", e.reintentos, 1)
e.cerrar()

e = Escena(RcdFalso({}))
t = e.trabajo(jobids=(1,))
e.seg.abrir(t)
e.seg.acabar_con_error(t, rcd.RcdCaido("sin rcd"), None)
c("un `rcd` caído antes de lanzar: «Reconectar» y la conexión perdida",
  (e.dichos[-1][2], e.frase_panel(), e.acabados), ("Reconectar", PERDIDA, []))
e.cerrar()

e = Escena(RcdFalso({}))
t = e.trabajo(jobids=(1,))
e.seg.abrir(t)
e.seg.acabar_con_error(t, ValueError("no vale"), reintento)
c("otro error antes de lanzar se dice con su frase y se puede reintentar",
  (e.frase_panel() != "", e.seg.reintento is reintento, e.resultados), (True, True, []))
e.cerrar()

# --- 10. soltar y vigente -------------------------------------------------------
e = Escena(RcdFalso({1: [CORRIENDO]}))
t = e.trabajo(jobids=(1,))
e.seg.abrir(t)
c("el trabajo abierto es el vigente", e.seg.vigente(t), True)
cambios = e.cambios
e.seg.soltar()
c("`soltar()` lo deja sin resultado y avisa del cambio",
  (e.seg.activo, e.seg.vigente(t), e.cambios > cambios, e.resultados), (None, False, True, []))
otro = e.trabajo(jobids=(1,))
e.seg.abrir(otro)
c("uno nuevo no es el viejo", (e.seg.vigente(t), e.seg.vigente(otro)), (False, True))
e.seg.parar()
c("al `parar()` ninguno es vigente", e.seg.vigente(otro), False)
e.cerrar()

# --- 11. cerrar con trabajo lanzado --------------------------------------------
e = Escena(RcdFalso({1: [CORRIENDO]}))
llamado: list[str] = []
t = e.trabajo(jobids=(1,))
e.seg.abrir(t)
c("sin nada lanzado, `cerrar_cancelando` no espera a nada",
  e.seg.cerrar_cancelando(lambda: llamado.append("x")), False)
e.seg.lanzar(t)
bombear(lambda: ("estado", 1, False) in e.falso.orden)
c("con trabajo lanzado se pide parar y se espera", e.seg.cerrar_cancelando(
    lambda: llamado.append("cerrado")), True)
c("  el trabajo queda cerrando y cancelado", (t.cerrando, t.cancelado), (True, True))
c("  `job/stop` con su jobid, y después `despues()`",
  (e.falso.paradas(), bombear(lambda: llamado == ["cerrado"])), ([1], True))
c("  dejó de ser vigente, así que ya no pinta", e.seg.vigente(t), False)
e.cerrar()

# --- 12. el hueco entre dos órdenes (con hilos de verdad) -----------------------
class Hueco:
    """Tres lanzadores donde el segundo se queda esperando dentro del hilo hasta que se le suelta."""

    def __init__(self, falla: Exception | None = None) -> None:
        self.e = Escena(RcdFalso({1: [ACABADO], 2: [CORRIENDO], 3: [ACABADO]}))
        self.entrado = threading.Event()
        self.soltar = threading.Event()
        self.falla = falla
        self.t = self.e.trabajo()
        original = self.t.lanzadores[1]

        def segundo(r, grupo):
            self.entrado.set()
            self.soltar.wait(5)
            if self.falla is not None:
                raise self.falla
            return original(r, grupo)
        self.t.lanzadores[1] = segundo

    def hasta_el_hueco(self) -> None:
        """Abre el trabajo, lo lanza y espera a que el segundo lanzador esté dentro del hilo."""
        segundo_plano.lanzar = LANZAR_DE_VERDAD
        self.e.seg.abrir(self.t)
        self.e.seg.lanzar(self.t)
        bombear(self.entrado.is_set)

    def fin(self) -> None:
        self.soltar.set()
        segundo_plano.lanzar = segundo_plano.en_el_acto
        self.e.cerrar()


# cerrar en el hueco: se espera al `jobid` de la que se lanza y se para ELLA antes de cerrar
h = Hueco()
h.hasta_el_hueco()
c("el segundo lanzador está en vuelo; el primero ya acabó", (h.t.lanzando, h.t.jobid, h.t.estados),
  (True, 1, [ACABADO]))
cerrado: list[list[int]] = []
c("cerrar en el hueco espera (True)",
  h.e.seg.cerrar_cancelando(lambda: cerrado.append(h.e.falso.paradas())), True)
pausa(10)
c("  mientras la orden se lanza no se cierra", cerrado, [])
h.soltar.set()
c("  al llegar su `jobid` se para ELLA y solo entonces se cierra",
  bombear(lambda: cerrado != []), True)
c("  el `job/stop` fue a la orden 2 antes de `despues()`", 2 in cerrado[0], True)
c("  y la tercera no se lanzó", h.e.lanzados, [1, 2])
h.fin()

# cerrar en el hueco y que la orden no llegue a lanzarse: se cierra igual
h = Hueco(falla=rcd.ErrorRc("boom", 500))
h.hasta_el_hueco()
cerrado = []
h.e.seg.cerrar_cancelando(lambda: cerrado.append(h.e.falso.paradas()))
h.soltar.set()
c("si la orden en vuelo falla, se cierra igual, sin parar nada",
  (bombear(lambda: cerrado != []), cerrado), (True, [[]]))
h.fin()

# «Cancelar» en el hueco: la orden que sale se para al recibir su jobid y no sigue ninguna
h = Hueco()
h.hasta_el_hueco()
h.e.seg.cancelar()
h.soltar.set()
c("«Cancelar» en el hueco: la orden que salió se para también",
  bombear(lambda: 2 in h.e.falso.paradas()), True)
c("  acaba sin lanzar la tercera, con cancelado=True y los dos estados",
  (bombear(lambda: h.e.resultados != []), h.e.lanzados, [r[2] for r in h.e.resultados],
   [len(r[0]) for r in h.e.resultados]), (True, [1, 2], [True], [2]))
h.fin()

# «Cancelar» en el hueco y que la orden en vuelo falle: el resultado sabe que se canceló
h = Hueco(falla=rcd.ErrorRc("boom", 500))
h.hasta_el_hueco()
h.e.seg.cancelar()
h.soltar.set()
c("«Cancelar» y la orden siguiente falla al lanzar: `resultado` recibe cancelado=True",
  (bombear(lambda: h.e.resultados != []), [r[2] for r in h.e.resultados],
   [[e.get("success") for e in r[0]] for r in h.e.resultados]), (True, [True], [[True, False]]))
h.fin()

c("nada ha reventado por el camino", errores, [])
sys.exit(c.report())
