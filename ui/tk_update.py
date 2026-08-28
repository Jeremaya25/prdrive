#!/usr/bin/env python3
"""
tk_update.py — La pantalla de «hay versión nueva».

Solo dibuja. Lo que sabe de versiones, descargas y verificación está en
`common/update.py`, que no importa Tk y se prueba sin ventana.

El reparto de las tres formas de enseñar algo en marcha es el de siempre:

  * la descarga va en `working()` —son unos segundos y no tienen nada que
    contar—,
  * y la instalación en `output_window()`, porque sustituir ficheros dentro del
    dispositivo es exactamente lo que hay que poder mirar. Es la misma decisión
    que toma `tk_watch` al lanzar `penwatch install`.

Y al terminar bien no se vuelve aquí: se relanza el programa y se cierra la
ventana. No es una cortesía, es obligatorio: este proceso tiene cargados en
memoria los módulos que se acaban de sustituir en disco.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import webbrowser
from pathlib import Path

from common import model, store, update

from . import prefs, theme
from .tk import (TITLE, bloque_aviso, cabecera, cuerpo_visible, modal, mostrar,
                 output_window, working)


def servicio_vivo() -> bool:
    """¿Hay un servicio periódico corriendo en este equipo ahora mismo?

    `ui_flow()` lo para antes de abrir la ventana, pero `stop_previous_daemon()`
    se rinde a los 15 segundos y devuelve un mensaje conforme si el servicio
    está a media pareja. Ese es el único caso en que actualizar pilla a otro
    proceso usando el código, así que se avisa. Avisar y no impedir: es raro, y
    quien decide es quien mira."""
    info = store.read_json(model.STATE_DIR / "daemon.lock.json")
    try:
        return (info.get("host") == prefs.HOST
                and store.pid_alive(int(info.get("pid", -1))))
    except (TypeError, ValueError):
        return False


def open_dialog(parent, nueva) -> bool:
    """La pantalla. Devuelve True si se ha actualizado y hay que cerrar todo."""
    from tkinter import messagebox, ttk

    if nueva is None:
        return False

    actual = update.installed_version() or "desconocida"
    hecho = {"ok": False}

    dlg = modal(parent, "Actualizar")
    marco = cuerpo_visible(dlg, padding=(20, 18, 20, 16))
    marco.columnconfigure(0, weight=1)

    arriba = ttk.Frame(marco)
    arriba.grid(row=0, column=0, sticky="ew")
    arriba.columnconfigure(0, weight=1)
    cabecera(arriba, f"Hay una versión nueva: {nueva.tag}",
             f"Este dispositivo lleva la {actual}.", ancho=520,
             estilo="Dialogo.TLabel").grid(row=0, column=0, sticky="w")
    theme.chip(arriba, nueva.version, "Acento.").grid(row=0, column=1,
                                                      sticky="ne", pady=(4, 0))

    # --- qué se sustituye y qué se conserva ----------------------------------
    tarjeta = ttk.Frame(marco, style="Card.TFrame", padding=(14, 12))
    tarjeta.grid(row=1, column=0, sticky="ew", pady=(16, 0))
    tarjeta.columnconfigure(1, weight=1)

    filas = [("Se sustituye", "el programa: sync.py, runsync.py, penwatch.py, "
                              "common/, ui/ y los lanzadores del volumen"),
             ("Se conserva", "tu configuración, tus claves, el estado de bisync, "
                             "los filtros, los diarios y el rclone"),
             ("Publicada", nueva.published[:10] or "—")]
    for i, (etiqueta, valor) in enumerate(filas):
        ttk.Label(tarjeta, text=etiqueta, style="Card.Campo.TLabel").grid(
            row=i, column=0, sticky="nw", pady=(0, 6), padx=(0, 12))
        ttk.Label(tarjeta, text=valor, style="Card.TLabel", wraplength=theme.medida(380),
                  justify="left").grid(row=i, column=1, sticky="w", pady=(0, 6))

    fila = 2
    if nueva.notes:
        ttk.Label(marco, text=theme.rotulo("Novedades"),
                  style="Rotulo.TLabel").grid(row=fila, column=0, sticky="w",
                                              pady=(16, 7))
        fila += 1
        notas = ttk.Frame(marco, style="Gris.TFrame", padding=(12, 10))
        notas.grid(row=fila, column=0, sticky="ew")
        notas.columnconfigure(0, weight=1)
        ttk.Label(notas, text=nueva.notes.strip()[:1200], style="Gris.Pista.TLabel",
                  wraplength=theme.medida(520),
                  justify="left").grid(row=0, column=0, sticky="w")
        fila += 1

    if servicio_vivo():
        bloque_aviso(marco, "El servicio periódico sigue en marcha en este "
                            "equipo. Puede estar sincronizando ahora mismo: "
                            "espera a que termine antes de actualizar.",
                     ancho=520).grid(row=fila, column=0, sticky="ew", pady=(14, 0))
        fila += 1

    # --- lo que hace el botón ------------------------------------------------
    def actualizar() -> None:
        if not messagebox.askokcancel(TITLE, (
                f"Se va a sustituir el programa de este dispositivo por la "
                f"{nueva.tag}.\n\n"
                f"Tu configuración, tus claves y tus datos no se tocan. Al "
                f"terminar, la ventana se cerrará y volverá a abrirse sola."),
                parent=dlg):
            return

        # En el temporal del equipo y nunca en el dispositivo: no hay por qué
        # gastarle ciclos de escritura para algo que se borra a continuación.
        staged = Path(tempfile.mkdtemp(prefix="prdrive-update-"))
        try:
            ok, valor = working(dlg, "Descargando la actualización",
                                lambda: update.download(nueva.tag, staged),
                                f"Trayendo el código de la {nueva.tag}…")
            if not ok:
                messagebox.showerror(TITLE, f"No se ha actualizado nada.\n\n{valor}",
                                     parent=dlg)
                return

            rc = output_window(f"actualizar a la {nueva.tag}",
                               update.apply_command(staged, model.DEVICE_ROOT),
                               parent=dlg,
                               subtitulo=str(model.APP_DIR))
            if rc != 0:
                messagebox.showerror(TITLE, (
                    f"La actualización ha fallado (código {rc}).\n\n"
                    f"El dispositivo puede haber quedado con parte del código "
                    f"nuevo. Vuelve a intentarlo, y si sigue fallando pasa el "
                    f"instalador sobre esta unidad."), parent=dlg)
                return
        finally:
            shutil.rmtree(staged, ignore_errors=True)

        # Relanzar y cerrar. No se puede seguir con esta ventana: sus módulos
        # son los de la versión anterior, ya sustituida en disco.
        try:
            subprocess.Popen(update.relaunch_command(),
                             cwd=tempfile.gettempdir(),
                             stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL,
                             close_fds=True)
        except OSError:
            messagebox.showinfo(TITLE, (
                f"Actualizado a la {nueva.tag}.\n\n"
                f"Cierra esta ventana y vuelve a abrir el programa."), parent=dlg)
        hecho["ok"] = True
        dlg.destroy()

    botones = ttk.Frame(marco)
    botones.grid(row=fila, column=0, sticky="ew", pady=(16, 0))
    botones.columnconfigure(1, weight=1)
    ver = ttk.Button(botones, text="Ver la página",
                     command=lambda: webbrowser.open(nueva.url))
    theme.boton_icono(ver, "eye", theme.TINTA2, theme.PAPEL)
    ver.grid(row=0, column=0, sticky="w")
    instalar = ttk.Button(botones, text="Actualizar ahora", style="Primary.TButton",
                          padding=(12, 7), command=actualizar)
    theme.boton_icono(instalar, "down", theme.SUPERFICIE, theme.ACENTO)
    instalar.grid(row=0, column=2, padx=(0, 6))
    ttk.Button(botones, text="Cerrar", command=dlg.destroy).grid(row=0, column=3)

    mostrar(dlg, parent)
    return hecho["ok"]
