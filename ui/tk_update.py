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

Aquí viven las dos pantallas de actualizar, que son la misma historia contada
dos veces: `open_dialog()` cambia el PROGRAMA y `open_components_dialog()` los
COMPONENTES —el rclone y el Python que el dispositivo lleva dentro—. Las dos
bajan el mismo zip del código y lanzan el mismo `prdrive-install.py` descargado,
porque `install/` no viaja al dispositivo. La diferencia de fondo: sustituir el
programa obliga a reabrir la ventana (sus módulos ya no son los de disco);
sustituir los componentes no, porque nada de lo que se toca está cargado en
memoria.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import webbrowser
from pathlib import Path

from common import components, model, store, update

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


def open_components_dialog(parent, pends) -> bool:
    """La pantalla de «los componentes están anticuados».

    Devuelve True si se ha tocado algo, para que la ventana relea los sellos y
    repinte. No hace falta reabrir el programa, a diferencia de la otra: lo que
    se sustituye son binarios que este proceso no tiene cargados en memoria."""
    from tkinter import messagebox, ttk

    if not pends:
        return False

    tocado = {"ok": False}
    tag = update.source_tag()

    dlg = modal(parent, "Actualizar componentes")
    marco = cuerpo_visible(dlg, padding=(20, 18, 20, 16))
    marco.columnconfigure(0, weight=1)

    cabecera(marco, "Los componentes del dispositivo están anticuados",
             "El rclone y el Python que lleva dentro no son los que fija esta "
             "versión del programa.", ancho=520,
             estilo="Dialogo.TLabel").grid(row=0, column=0, sticky="w")

    # --- qué lleva y qué toca ------------------------------------------------
    tarjeta = ttk.Frame(marco, style="Card.TFrame", padding=(14, 12))
    tarjeta.grid(row=1, column=0, sticky="ew", pady=(16, 0))
    tarjeta.columnconfigure(1, weight=1)
    for i, p in enumerate(pends):
        ttk.Label(tarjeta, text=p.titulo, style="Card.Campo.TLabel").grid(
            row=i, column=0, sticky="nw", pady=(0, 6), padx=(0, 12))
        ttk.Label(tarjeta, text=f"{p.lleva}  →  {p.deberia}",
                  style="Card.MonoPista.TLabel",
                  wraplength=theme.medida(340), justify="left").grid(
            row=i, column=1, sticky="w", pady=(0, 6))

    # --- qué respalda la descarga, sin adornos -------------------------------
    notas = ttk.Frame(marco, style="Gris.TFrame", padding=(12, 10))
    notas.grid(row=2, column=0, sticky="ew", pady=(14, 0))
    notas.columnconfigure(0, weight=1)
    ttk.Label(notas, text=(
        "Se descargan de su publicador —rclone.org y python-build-standalone— "
        "y se comprueban contra el SHA256 que cada uno publica antes de "
        "escribir nada. No hay firma. Se sustituyen de un renombrado, así que "
        "un corte no puede dejar el dispositivo a medias, y lo que esté en uso "
        "se deja para otro momento. Tu configuración, tus claves y tus datos no "
        "se tocan."), style="Gris.Pista.TLabel",
        wraplength=theme.medida(520), justify="left").grid(row=0, column=0,
                                                           sticky="w")
    fila = 3

    if servicio_vivo():
        bloque_aviso(marco, "El servicio periódico sigue en marcha en este "
                            "equipo. Si está sincronizando, su rclone no se "
                            "podrá sustituir y se dejará para otra vez.",
                     ancho=520).grid(row=fila, column=0, sticky="ew", pady=(14, 0))
        fila += 1

    if not tag:
        bloque_aviso(marco, "Este dispositivo no dice qué versión lleva, así "
                            "que no sé qué código descargar para ponerlo al "
                            "día. Pasa el instalador por encima.",
                     ancho=520).grid(row=fila, column=0, sticky="ew", pady=(14, 0))
        fila += 1

    def actualizar() -> None:
        if not messagebox.askokcancel(TITLE, (
                "Se van a sustituir el rclone y el Python que lleva este "
                "dispositivo por los que fija esta versión del programa.\n\n"
                "El programa, tu configuración, tus claves y tus datos no se "
                "tocan. Lo que esté en uso ahora mismo se dejará para otra vez."),
                parent=dlg):
            return

        # En el temporal del equipo, nunca en el dispositivo: son ~270 KB que se
        # borran a continuación, y no hay por qué gastarle ciclos de escritura.
        staged = Path(tempfile.mkdtemp(prefix="prdrive-components-"))
        try:
            ok, valor = working(dlg, "Descargando el instalador",
                                lambda: update.download(tag, staged),
                                f"Trayendo el código de la {tag}…")
            if not ok:
                messagebox.showerror(TITLE, f"No se ha tocado nada.\n\n{valor}",
                                     parent=dlg)
                return

            rc = output_window("actualizar los componentes",
                               update.components_command(staged, model.DEVICE_ROOT),
                               parent=dlg, subtitulo=str(model.APP_DIR))
            # Se haya podido con todo o no, los sellos ya dicen la verdad: la
            # ventana relee y el aviso se apaga solo si ya no hay motivo.
            tocado["ok"] = True
            if rc != 0:
                messagebox.showerror(TITLE, (
                    f"No se ha podido con todo (código {rc}).\n\n"
                    f"Lo que no se ha sustituido sigue exactamente como estaba. "
                    f"Mira la salida para ver qué ha fallado."), parent=dlg)
                return
        finally:
            shutil.rmtree(staged, ignore_errors=True)
        dlg.destroy()

    botones = ttk.Frame(marco)
    botones.grid(row=fila, column=0, sticky="ew", pady=(16, 0))
    botones.columnconfigure(0, weight=1)
    instalar = ttk.Button(botones, text="Actualizar ahora", style="Primary.TButton",
                          padding=(12, 7), command=actualizar)
    theme.boton_icono(instalar, "down", theme.SUPERFICIE, theme.ACENTO)
    if not tag:
        instalar.configure(state="disabled")
    instalar.grid(row=0, column=1, padx=(0, 6))
    ttk.Button(botones, text="Cerrar", command=dlg.destroy).grid(row=0, column=2)

    mostrar(dlg, parent)
    return tocado["ok"]
