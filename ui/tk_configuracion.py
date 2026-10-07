#!/usr/bin/env python3
"""«Ajustes → Configuración»: cómo trabaja el servicio, lo que se toca poco.

Solo dibuja. Dos cosas, y la segunda no siempre:
- El intervalo del servicio, el «cada cuánto» que antes estaba junto al pie de
  la ventana principal. Qué se escribe y qué no lo decide `ui/prefs.py`
  (`revisar_intervalo`, `guardar_intervalo`): solo el intervalo, nunca las
  parejas del servicio.
- «Pedir la contraseña al iniciar sesión», solo en la raíz cifrada de un
  equipo. Es un ajuste del agente y no de la raíz, así que no se escribe aquí:
  se le pide por su buzón (`watch.pedir_al_iniciar`, `watch.pedir_ajuste`).

Nada se guarda hasta «Guardar», y lo que no ha cambiado no se escribe. Se
dibuja en `construir()`, que sirve igual para su diálogo y para el apartado de
«Ajustes» (`tk.Panel`).
"""

from __future__ import annotations

from common import model
from common.model import Config

from . import icons, prefs, theme, watch
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


def construir(panel: Panel, config: Config) -> None:
    """Dibuja «Configuración» en `panel`; devuelve `True` por él si guarda algo."""
    import tkinter as tk
    from tkinter import messagebox, ttk

    _parejas, actual, _nota = prefs.startup_defaults(config)
    pedir = watch.pedir_al_iniciar()
    dlg, marco = panel.ventana, panel.marco

    que = "esta carpeta" if model.es_equipo() else "este dispositivo"
    cabecera(marco, "Configuración",
             f"Cómo trabaja el servicio de {que}. Nada cambia hasta pulsar "
             "«Guardar».",
             ancho=540, estilo="Dialogo.TLabel").grid(row=0, column=0, sticky="w")

    # El intervalo del servicio.
    tarjeta = ttk.Frame(marco, style="Card.TFrame", padding=(14, 12, 14, 12))
    tarjeta.grid(row=1, column=0, sticky="ew", pady=(16, 0))
    tarjeta.columnconfigure(3, weight=1)
    img = icons.get(tarjeta, "clock", 15, theme.TINTA3, theme.SUPERFICIE)
    reloj = ttk.Label(tarjeta, style="Card.TLabel")
    if img is not None:
        reloj.configure(image=img)
        reloj.image = img
    reloj.grid(row=0, column=0, sticky="w")
    ttk.Label(tarjeta, text="El servicio repite cada", style="Card.Campo.TLabel").grid(
        row=0, column=1, sticky="w", padx=(8, 10))
    intervalo = tk.StringVar(marco, value=f"{actual:g}")
    ttk.Spinbox(tarjeta, from_=1, to=1440, textvariable=intervalo, width=5,
                font=theme.fuente("mono")).grid(row=0, column=2, sticky="w")
    # La raíz de un equipo no se desenchufa: el servicio repite sin más.
    ttk.Label(tarjeta, text="minutos" if model.es_equipo() else
              "minutos, mientras el dispositivo siga puesto",
              style="Card.Pista.TLabel").grid(row=0, column=3, sticky="w", padx=(10, 0))
    quien = ("Lo usa el servicio de esta carpeta, sea el agente de este equipo o "
             "«Iniciar servicio», y se guarda en ella." if model.es_equipo() else
             "Lo usa el servicio se arranque como se arranque (con «Iniciar "
             "servicio», al enchufarlo o el agente de este equipo) y viaja con el "
             "dispositivo.")
    ttk.Label(tarjeta, style="Card.Pista.TLabel", justify="left",
              wraplength=theme.medida(520),
              text=quien + " Vale desde la próxima vez que se ponga en marcha; "
                           "«Sincronizar ahora» no lo usa.").grid(
        row=1, column=0, columnspan=4, sticky="w", pady=(8, 0))

    # La raíz cifrada de este equipo: si el agente pide su contraseña al
    # iniciar sesión. Es un ajuste del EQUIPO y no de la raíz: se le pide al
    # agente por su buzón, así que lo tiene también quien no tiene bandeja.
    marcada = None
    if pedir is not None:
        cifrada = ttk.Frame(marco, style="Card.TFrame", padding=(14, 12, 14, 12))
        cifrada.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        cifrada.columnconfigure(0, weight=1)
        marcada = tk.BooleanVar(marco, value=pedir)
        ttk.Checkbutton(cifrada, text="Pedir la contraseña al iniciar sesión",
                        variable=marcada,
                        style="Card.Fuerte.TCheckbutton").grid(row=0, column=0,
                                                              sticky="w")
        ttk.Label(cifrada, style="Card.Pista.TLabel", justify="left",
                  wraplength=theme.medida(520),
                  text="Al iniciar sesión, el agente le pide a VeraCrypt que abra "
                       "esta carpeta cifrada, una vez. Sin marcar, se queda "
                       "bloqueada hasta que pidas «Desbloquear». Lo guarda el agente "
                       "de este equipo, no la carpeta.").grid(
            row=1, column=0, sticky="w", pady=(3, 0))

    def guardar() -> None:
        """Guarda lo que ha cambiado y cierra; si algo no se puede, lo dice y se queda."""
        try:
            minutos = prefs.revisar_intervalo(intervalo.get())
        except ValueError as e:
            messagebox.showerror(TITLE, str(e), parent=dlg)
            return
        algo = minutos != actual or (marcada is not None
                                     and bool(marcada.get()) != pedir)
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
        panel.terminar("Guardado." if algo else "")

    botones = pie(marco, 3)
    botones.columnconfigure(0, weight=1)
    ttk.Button(botones, text="Cancelar", command=panel.terminar).grid(
        row=0, column=1, padx=(0, 6))
    ttk.Button(botones, text="Guardar", style="Primary.TButton",
               command=guardar).grid(row=0, column=2)
