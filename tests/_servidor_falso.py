#!/usr/bin/env python3
"""Lo que comparten los tests de la ventana «Servidor…»: un `rcd` falso y los ayudantes para manejarla.

Es una copia de lo que `tests/test_tk_servidor.py` tiene a nivel de módulo (los
datos de un servidor, `RcdFalso`, abrir y cerrar la ventana, leer lo que se ve,
bombear el bucle de Tk), más un `RcdGestion` que acepta las órdenes de
`rcd.lanzar_orden()` y las sigue con `job/status`. El test de la pieza 2 no lo
usa: sigue con sus propias copias.

Nada de aquí arranca rclone ni toca la red. El test que lo importa crea la raíz
de Tk y se la da a `usar()` antes de abrir ninguna ventana.
"""

from __future__ import annotations

import time

from common import rcd
from common.model import ConfigError
from ui import tk_servidor

_ESCENA: dict = {"raiz": None}


def usar(raiz) -> None:
    """Fija la raíz de Tk (oculta) sobre la que se abren las ventanas de prueba."""
    _ESCENA["raiz"] = raiz
    rcd.arrancar = arrancar_falso


def item(nombre: str, carpeta: bool = False, tamano: int = 10, **meta) -> dict:
    """Una entrada de `operations/list`."""
    datos = {"Name": nombre, "IsDir": carpeta, "Size": -1 if carpeta else tamano,
             "ModTime": "2026-03-12T09:00:00Z"}
    if meta:
        datos["Metadata"] = {k: str(v) for k, v in meta.items()}
    return datos


def lista(*items) -> dict:
    """La respuesta de `operations/list` con esas entradas."""
    return {"list": list(items)}


class RcdFalso:
    """Un `Rcd` que contesta desde un diccionario `(método, remote) → respuesta o error`."""

    def __init__(self, respuestas: dict) -> None:
        self.respuestas = respuestas
        self.llamadas: list[tuple] = []
        self.paradas = 0
        self.orden: list[str] = []        # métodos llamados y «parar», en el orden en que ocurrieron
        self.esperas = 0
        self.error_esperar: Exception | None = None
        self.vivo = True

    def esperar(self, tope=None) -> None:
        self.esperas += 1
        if self.error_esperar is not None:
            raise self.error_esperar

    def llamar(self, metodo: str, params: dict | None = None,
               timeout: float | None = None) -> dict:
        params = params or {}
        self.llamadas.append((metodo, params))
        self.orden.append(metodo)
        respuesta = self.respuestas[(metodo, params.get("remote"))]
        if callable(respuesta):
            respuesta = respuesta()
        if isinstance(respuesta, Exception):
            raise respuesta
        return respuesta

    def parar(self) -> None:
        self.paradas += 1
        self.orden.append("parar")

    def listados(self) -> list[dict]:
        return [p for m, p in self.llamadas if m == "operations/list"]


FSINFO_NO = {"Features": {"ReadMetadata": False}}

CORRIENDO = {"finished": False}
ACABADO = {"finished": True, "success": True}


def fallado(error: str) -> dict:
    """El `job/status` de una orden que acabó con ese error."""
    return {"finished": True, "success": False, "error": error}


def respuestas(raiz_: dict | Exception | None = None, otras: dict | None = None) -> dict:
    """Las respuestas de un servidor con «datos» (que lleva «notas»), «privado» y un archivo."""
    return {
        ("operations/fsinfo", None): FSINFO_NO,
        ("operations/list", ""): raiz_ if raiz_ is not None else lista(
            item("datos", True), item("privado", True), item("leeme.txt", tamano=2048)),
        ("operations/list", "datos"): lista(item("notas", True), item("a.txt")),
        ("operations/list", "datos/notas"): lista(item("hoy.txt")),
        ("operations/list", "privado"): rcd.ErrorRc("permission denied", 403),
        **(otras or {}),
    }


class RcdGestion(RcdFalso):
    """Un servidor que acepta las órdenes de gestión (`rcd.ORDENES_PERMITIDAS`) y las sigue.

    Cada orden lanzada recibe el `jobid` 1, 2, 3… en el orden en que llega. `job/status`
    del trabajo `n` da, uno por consulta, los estados de `estados[n]` (el último se
    repite); sin ellos, el trabajo acaba bien a la primera. `operations/size` contesta
    desde `tamanos` (por la ruta pedida) con `(archivos, bytes)` o con un error.

    Attributes:
        lanzadas: `(método, parámetros)` de cada orden de gestión, en orden.
        cronologia: `("lanzar", n, método)` y `("estado", n, finished)` en el orden en que ocurrieron.
    """

    def __init__(self, respuestas_: dict, tamanos: dict | None = None,
                 estados: dict | None = None) -> None:
        super().__init__(respuestas_)
        self.tamanos = tamanos or {}
        self.estados = estados or {}
        self.colas: dict[int, list] = {}
        self.lanzadas: list[tuple[str, dict]] = []
        self.cronologia: list[tuple] = []
        self.al_lanzar = None             # `al_lanzar(método, parámetros)`: lo que cambia en el servidor

    def llamar(self, metodo, params=None, timeout=None):
        params = params or {}
        if metodo in rcd.ORDENES_PERMITIDAS:
            self.llamadas.append((metodo, params))
            self.lanzadas.append((metodo, params))
            n = len(self.lanzadas)
            self.cronologia.append(("lanzar", n, metodo))
            if self.al_lanzar is not None:
                self.al_lanzar(metodo, params)
            return {"jobid": n}
        if metodo == "job/status":
            self.llamadas.append((metodo, params))
            n = params["jobid"]
            cola = self.colas.setdefault(n, list(self.estados.get(n, [ACABADO])))
            actual = cola.pop(0) if len(cola) > 1 else cola[0]
            self.cronologia.append(("estado", n, bool(actual.get("finished"))))
            return actual
        if metodo == "core/stats":
            self.llamadas.append((metodo, params))
            return {}
        if metodo == "job/stop":
            self.llamadas.append((metodo, params))
            return {}
        if metodo == "operations/size":
            self.llamadas.append((metodo, params))
            self.orden.append(metodo)
            respuesta = self.tamanos[params["remote"]]
            if isinstance(respuesta, Exception):
                raise respuesta
            return {"count": respuesta[0], "bytes": respuesta[1]}
        return super().llamar(metodo, params, timeout)

    def ordenes(self, metodo: str | None = None) -> list[dict]:
        """Los parámetros de las órdenes de gestión lanzadas (las de ese método, si se dice)."""
        return [p for m, p in self.lanzadas if metodo is None or m == metodo]

    def paradas_de_trabajo(self) -> int:
        return len([m for m, _p in self.llamadas if m == "job/stop"])


ARRANQUES: list = []
LLAMADAS_ARRANCAR: list = []
ABIERTAS: list = []


def no_arranca():
    """Un `rcd.arrancar` que falla, como cuando rclone no se puede ejecutar."""
    raise ConfigError("No se puede ejecutar rclone: nada")


def arrancar_falso() -> RcdFalso:
    LLAMADAS_ARRANCAR.append(1)
    return ARRANQUES.pop(0)


def abrir(*falsos: RcdFalso, config):
    """Abre «Servidor» con esos `rcd` por orden de arranque y devuelve la ventana viva."""
    raiz = _ESCENA["raiz"]
    ARRANQUES[:] = list(falsos)
    LLAMADAS_ARRANCAR.clear()
    ABIERTAS.clear()

    def capturar(dlg, parent=None):
        """Sustituye a `mostrar()`: apunta la ventana, la enseña y no espera."""
        ABIERTAS.append(dlg)
        raiz.deiconify()
        dlg.visor.encajar(dlg)
        dlg.deiconify()
        dlg.update()

    previo = tk_servidor.mostrar
    tk_servidor.mostrar = capturar
    try:
        tk_servidor.open_dialog(raiz, config)
    finally:
        tk_servidor.mostrar = previo
    return ABIERTAS[0]


def cerrar(dlg) -> None:
    dlg.destroy()
    _ESCENA["raiz"].withdraw()


def nombres(dlg) -> list[str]:
    """Los `iid` de la lista, de arriba abajo."""
    return [str(i) for i in dlg.lista.get_children()]


def frase(dlg) -> str:
    """Lo que dice el indicador de la ventana."""
    return str(dlg.indicador.texto.cget("text"))


def pulsar(dlg, secuencia: str) -> None:
    """Genera ese evento en la lista, con el foco en ella."""
    dlg.lista.focus_force()
    dlg.lista.event_generate(secuencia)
    dlg.update()


def bombear(condicion, tope: float = 5.0) -> bool:
    """Deja correr el bucle de Tk hasta que se cumpla la condición."""
    raiz = _ESCENA["raiz"]
    fin = time.monotonic() + tope
    while not condicion() and time.monotonic() < fin:
        raiz.update()
        time.sleep(0.005)
    return bool(condicion())


def panel_a_la_vista(dlg) -> bool:
    return bool(dlg.panel.marco.winfo_manager()) and bool(dlg.panel.titulo.winfo_manager())


def frase_panel(dlg) -> str:
    """El texto del resultado del panel."""
    from tkinter import ttk

    for w in dlg.panel.resultado.winfo_children():
        for h in [w, *w.winfo_children()]:
            if isinstance(h, ttk.Label) and h.cget("text"):
                return str(h.cget("text"))
    return ""
