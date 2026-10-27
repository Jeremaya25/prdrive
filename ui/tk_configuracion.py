#!/usr/bin/env python3
"""«Ajustes → Configuración»: cómo trabaja el servicio, lo que se toca poco.

Solo dibuja. Tres cosas, y las dos últimas no siempre:
- El intervalo del servicio, el «cada cuánto» que antes estaba junto al pie de
  la ventana principal. Qué se escribe y qué no lo decide `ui/prefs.py`
  (`revisar_intervalo`, `guardar_intervalo`): solo el intervalo, nunca las
  parejas del servicio.
- «Pedir la contraseña al iniciar sesión», solo en la raíz cifrada de un
  equipo. Es un ajuste del agente y no de la raíz, así que no se escribe aquí:
  se le pide por su buzón (`watch.pedir_al_iniciar`, `watch.pedir_ajuste`).
- «Pedir la contraseña al conectarla», solo en una unidad cifrada (VeraCrypt o
  BitLocker) que el agente atiende. También es del agente y se le pide por su
  buzón (`watch.pedir_al_conectar`, `watch.pedir_ajuste_unidad`). Cada una va
  en su propia fila (`_casilla()`), de modo que no se pisan aunque algún día
  salgan a la vez.
- «Bloquearla al bloquear la sesión / al suspender / al cerrar sesión o
  apagar», solo las que el agente dice que puede cumplir en esta raíz cifrada
  (`watch.bloquear_solo`). También del agente: una petición por casilla
  cambiada (`watch.pedir_ajuste_unidad`).

Nada se guarda hasta «Guardar», y lo que no ha cambiado no se escribe. Se
dibuja en `construir()`, que sirve igual para su diálogo y para el apartado de
«Ajustes» (`tk.Panel`).
"""

from __future__ import annotations

from common import model
from common.model import Config

from . import prefs, theme, watch
from .tk import TITLE, Panel, cabecera, dialogo, mostrar, pie


def open_dialog(parent, config: Config) -> bool:
    """Abre «Configuración» y devuelve si se ha guardado algo.

    Args:
        parent: La ventana de la que cuelga.
        config: La configuración del dispositivo: de ella salen el intervalo
            actual y las parejas que `guardar_intervalo` conserva.
    """
    return dialogo(parent, "Configuración", lambda p: construir(p, config),
                   defecto=False, ensenar=mostrar)


def _casilla(marco, fila: int, texto: str, valor: bool, ayuda: str):
    """Dibuja una tarjeta con una casilla y su ayuda en esa fila de `marco`.

    Args:
        marco: Donde va la tarjeta.
        fila: La fila de su rejilla; cada tarjeta, la suya.
        texto: Lo que dice la casilla.
        valor: Si empieza marcada.
        ayuda: La frase de debajo, que dice qué hace; vacía, ninguna.

    Returns:
        La variable de la casilla, para leer al «Guardar» si ha cambiado.
    """
    import tkinter as tk
    from tkinter import ttk

    tarjeta = ttk.Frame(marco, style="Card.TFrame",
                        padding=(theme.E4, theme.E3, theme.E4, theme.E3))
    tarjeta.grid(row=fila, column=0, sticky="ew", pady=(theme.E3, 0))
    tarjeta.columnconfigure(0, weight=1)
    marcada = tk.BooleanVar(marco, value=valor)
    ttk.Checkbutton(tarjeta, text=texto, variable=marcada,
                    style="Card.Fuerte.TCheckbutton").grid(row=0, column=0, sticky="w")
    if ayuda:
        ttk.Label(tarjeta, style="Card.Pista.TLabel", justify="left",
                  wraplength=theme.medida(520), text=ayuda).grid(
            row=1, column=0, sticky="w", pady=(theme.E1, 0))
    return marcada


def construir(panel: Panel, config: Config) -> None:
    """Dibuja «Configuración» en `panel`; devuelve `True` por él si guarda algo."""
    import tkinter as tk
    from tkinter import messagebox, ttk

    _parejas, actual, _nota = prefs.startup_defaults(config)
    pedir = watch.pedir_al_iniciar()
    conectar = watch.pedir_al_conectar()
    solos = watch.bloquear_solo() or {}
    dlg, marco = panel.ventana, panel.marco

    que = "esta carpeta" if model.es_equipo() else "este dispositivo"
    cabecera(marco, "Configuración",
             f"Cómo trabaja el servicio de {que}. Nada cambia hasta pulsar "
             "«Guardar».",
             ancho=540, estilo="Dialogo.TLabel").grid(row=0, column=0, sticky="w")

    # El intervalo del servicio.
    tarjeta = ttk.Frame(marco, style="Card.TFrame", padding=(theme.E4, theme.E3, theme.E4, theme.E3))
    tarjeta.grid(row=1, column=0, sticky="ew", pady=(theme.E4, 0))
    tarjeta.columnconfigure(3, weight=1)
    reloj = theme.etiqueta_icono(tarjeta, "clock", theme.TINTA3, size=15,
                                 superficie="Card.")
    reloj.grid(row=0, column=0, sticky="w")
    ttk.Label(tarjeta, text="El servicio repite cada", style="Card.Campo.TLabel").grid(
        row=0, column=1, sticky="w", padx=(theme.E2, theme.E3))
    intervalo = tk.StringVar(marco, value=f"{actual:g}")
    ttk.Spinbox(tarjeta, from_=1, to=1440, textvariable=intervalo, width=5,
                font=theme.fuente("mono")).grid(row=0, column=2, sticky="w")
    # La raíz de un equipo no se desenchufa: el servicio repite sin más.
    ttk.Label(tarjeta, text="minutos" if model.es_equipo() else
              "minutos, mientras el dispositivo siga puesto",
              style="Card.Pista.TLabel").grid(row=0, column=3, sticky="w", padx=(theme.E3, 0))
    quien = ("Lo usa el servicio de esta carpeta, sea el agente de este equipo o "
             "«Iniciar servicio», y se guarda en ella." if model.es_equipo() else
             "Lo usa el servicio se arranque como se arranque (con «Iniciar "
             "servicio», al enchufarlo o el agente de este equipo) y viaja con el "
             "dispositivo.")
    ttk.Label(tarjeta, style="Card.Pista.TLabel", justify="left",
              wraplength=theme.medida(520),
              text=quien + " Vale desde la próxima vez que se ponga en marcha; "
                           "«Sincronizar ahora» no lo usa.").grid(
        row=1, column=0, columnspan=4, sticky="w", pady=(theme.E2, 0))

    # Las casillas de contraseña, cada una en su fila: la raíz cifrada de este equipo
    # (si el agente pide su contraseña al iniciar sesión) y una unidad cifrada (si se
    # la pide al conectarla). Son ajustes del EQUIPO y no de la raíz ni de la unidad:
    # se le piden al agente por su buzón, así que los tiene también quien no tiene
    # bandeja.
    fila = 2
    marcada = conectada = None
    if pedir is not None:
        marcada = _casilla(
            marco, fila, "Pedir la contraseña al iniciar sesión", pedir,
            "Al iniciar sesión, el agente le pide a VeraCrypt que abra esta carpeta "
            "cifrada, una vez. Sin marcar, se queda bloqueada hasta que pidas "
            "«Desbloquear». Lo guarda el agente de este equipo, no la carpeta.")
        fila += 1
    if conectar is not None:
        conectada = _casilla(
            marco, fila, "Pedir la contraseña al conectarla", conectar.valor,
            watch.ayuda_al_conectar(conectar.cifrado)
            + " Lo guarda el agente de este equipo, no la unidad.")
        fila += 1
    # Las de bloquearla sola: una por evento de Windows; la ayuda, común, bajo la última.
    bloquear: dict = {}
    for n, (clave, valor) in enumerate(solos.items()):
        bloquear[clave] = _casilla(
            marco, fila, watch.TEXTO_BLOQUEAR_SOLO[clave], valor,
            watch.ayuda_bloquear_solo() + f" Lo guarda el agente de este equipo, no {que}."
            if n == len(solos) - 1 else "")
        fila += 1

    def guardar() -> None:
        """Guarda lo que ha cambiado y cierra; si algo no se puede, lo dice y se queda."""
        try:
            minutos = prefs.revisar_intervalo(intervalo.get())
        except ValueError as e:
            messagebox.showerror(TITLE, str(e), parent=dlg)
            return
        cambia_conectar = conectada is not None and bool(conectada.get()) != conectar.valor
        cambian = {k: bool(v.get()) for k, v in bloquear.items() if bool(v.get()) != solos[k]}
        algo = minutos != actual or (marcada is not None
                                     and bool(marcada.get()) != pedir) or cambia_conectar \
            or bool(cambian)
        if minutos != actual:
            if not prefs.guardar_intervalo(config, minutos):
                messagebox.showerror(TITLE, f"No he podido guardar el intervalo en "
                                            f"{prefs.PREFS}.", parent=dlg)
                return
            panel.devolver(True)
        if marcada is not None and bool(marcada.get()) != pedir:
            if not watch.pedir_ajuste("pedir_al_iniciar", bool(marcada.get())):
                messagebox.showerror(TITLE, "No he podido dejarle la petición al "
                                            "agente.", parent=dlg)
                return
            panel.devolver(True)
        if cambia_conectar:
            if not watch.pedir_ajuste_unidad("pedir_al_conectar", bool(conectada.get())):
                messagebox.showerror(TITLE, "No he podido dejarle la petición al "
                                            "agente.", parent=dlg)
                return
            panel.devolver(True)
        for clave, valor in cambian.items():
            if not watch.pedir_ajuste_unidad(clave, valor):
                messagebox.showerror(TITLE, "No he podido dejarle la petición al "
                                            "agente.", parent=dlg)
                return
            panel.devolver(True)
        panel.terminar("Guardado." if algo else "")

    botones = pie(marco, fila)
    botones.columnconfigure(0, weight=1)
    ttk.Button(botones, text="Cancelar", command=panel.terminar).grid(
        row=0, column=1, padx=(0, theme.E2))
    ttk.Button(botones, text="Guardar", style="Primary.TButton",
               command=guardar).grid(row=0, column=2)
