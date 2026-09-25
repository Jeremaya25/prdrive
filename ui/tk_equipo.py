#!/usr/bin/env python3
"""
tk_equipo.py — Los pasos del asistente «En este equipo».

Solo dibuja. Lo que decide y lo que toca el disco está en `install/agente.py`,
igual que el resto del asistente con `install/`. En esta versión el recorrido es
el de la instalación «solo agente» del diseño: el agente residente, que atiende
las unidades prdrive que se enchufan, sin raíz propia en el equipo.

    Instalación   el código y el Python del agente, en la carpeta del equipo
    Unidades      qué unidades atiende ya y cómo, y el plazo de «unidad nueva»
    Arranque      que arranque al iniciar sesión; penwatch fuera
    Verificación  lo que de verdad quedó puesto

Lo que el asistente va sabiendo vive en el propio `Wizard` (`agente_*`), no en
los widgets: `repintar()` los destruye al cambiar de paso.
"""

from __future__ import annotations

from . import theme
from .tk import working

ANCHO = 780


def _texto(cuerpo, texto: str, fila: int, **kw) -> None:
    from tkinter import ttk
    ttk.Label(cuerpo, justify="left", wraplength=theme.medida(ANCHO), text=texto,
              **kw).grid(row=fila, column=0, sticky="w", pady=(0, 10))


# ---------------------------------------------------------------------------
# Instalación
# ---------------------------------------------------------------------------

def paso_instalar(cuerpo, wiz) -> None:
    from tkinter import ttk

    from common import equipo
    from install import agente

    ya = agente.instalado()
    _texto(cuerpo, (
        f"El agente se queda en este equipo, fuera de toda unidad, en {equipo.DIR}. "
        "Ahí van su código y su propio Python —no depende de ningún Python "
        "instalado— y su configuración. Ni claves, ni rclone.conf, ni listados: "
        "cada unidad trae los suyos, y el agente solo lanza lo que ella lleva."), 0)
    if ya:
        _texto(cuerpo, (f"Ya hay un agente instalado (versión {ya.get('version', '?')}). "
                        "Instalar pone esta versión al lado y la deja en su sitio; su "
                        "lista de unidades se conserva."), 1, foreground=theme.TINTA3)

    resultado = ttk.Label(cuerpo, wraplength=theme.medida(ANCHO), justify="left")
    resultado.grid(row=3, column=0, sticky="w", pady=(12, 0))

    def pintar() -> None:
        prep = wiz.agente_prep
        if prep is None:
            resultado.configure(text="", foreground=theme.TINTA3)
        else:
            resultado.configure(text=f"✔ Código en {prep.codigo}\n✔ Python en {prep.python}",
                                foreground=theme.OK)
        wiz.revisar()

    def instalar() -> None:
        ok, prep = working(wiz.root, "instalando el agente", agente.preparar,
                           "Copiando el agente y su Python a este equipo. La primera "
                           "vez hay que descargar Python (unos 20 MB).")
        if not ok:
            wiz.agente_prep = None
            resultado.configure(text=str(prep), foreground=theme.PELIGRO)
            wiz.revisar()
            wiz.visor.ver(resultado)
            return
        wiz.agente_prep = prep
        pintar()

    ttk.Button(cuerpo, text="Instalar el agente", style="Primary.TButton",
               command=instalar).grid(row=2, column=0, sticky="w")
    pintar()


def ok_instalar(wiz) -> bool:
    return wiz.agente_prep is not None


# ---------------------------------------------------------------------------
# Unidades
# ---------------------------------------------------------------------------

def paso_unidades(cuerpo, wiz) -> None:
    import tkinter as tk
    from tkinter import ttk

    from common import equipo
    from install import agente

    _texto(cuerpo, (
        "Qué unidades atiende el agente, y qué hace con cada una al enchufarla. "
        "Aquí salen las que se saben sin red: la que vigilaba penwatch en este "
        "equipo, las enchufadas ahora y las que el agente ya tenga. Cualquier otra "
        "se pregunta la primera vez que se enchufe: nunca se sincroniza una unidad "
        "sin preguntar."), 0)

    if wiz.agente_unidades is None:
        ofrecidas = agente.candidatas()
        wiz.agente_unidades = {c.id: (c.modo, c.nombre) for c in ofrecidas}
        wiz.agente_origen = {c.id: c.origen for c in ofrecidas}

    tabla = ttk.Frame(cuerpo)
    tabla.grid(row=1, column=0, sticky="w")
    if not wiz.agente_unidades:
        ttk.Label(tabla, style="Pista.TLabel", text=(
            "Ninguna todavía. Enchufa una unidad prdrive y el agente preguntará si "
            "atenderla.")).grid(row=0, column=0, sticky="w")
    else:
        for col, rotulo in enumerate(("Unidad", "Qué hacer al enchufarla", "")):
            ttk.Label(tabla, text=theme.rotulo(rotulo), style="Rotulo.TLabel").grid(
                row=0, column=col, sticky="w", padx=(0, 18))
    etiquetas = {m: equipo.TEXTO_MODO[m] for m in equipo.MODOS}
    por_texto = {v: k for k, v in etiquetas.items()}
    for i, (uid, (modo, nombre)) in enumerate(sorted(wiz.agente_unidades.items()),
                                              start=1):
        ttk.Label(tabla, text=nombre or f"{uid[:8]}…").grid(
            row=i, column=0, sticky="w", padx=(0, 18), pady=2)
        var = tk.StringVar(value=etiquetas[modo])

        def cambiar(_evento=None, u=uid, v=var, n=nombre) -> None:
            wiz.agente_unidades[u] = (por_texto[v.get()], n)

        caja = ttk.Combobox(tabla, textvariable=var, state="readonly",
                            values=[etiquetas[m] for m in equipo.MODOS], width=30)
        caja.bind("<<ComboboxSelected>>", cambiar)
        caja.grid(row=i, column=1, sticky="w", padx=(0, 18), pady=2)
        ttk.Label(tabla, text=wiz.agente_origen.get(uid, ""), style="Pista.TLabel").grid(
            row=i, column=2, sticky="w", pady=2)

    plazo = ttk.Frame(cuerpo)
    plazo.grid(row=2, column=0, sticky="w", pady=(16, 0))
    ttk.Label(plazo, text="Para contestar a una unidad nueva:").grid(row=0, column=0,
                                                                     sticky="w")
    segundos = tk.StringVar(value=f"{wiz.agente_espera:g}")

    def cambiar_plazo(*_) -> None:
        try:
            valor = float(segundos.get())
        except ValueError:
            return
        wiz.agente_espera = min(max(valor, equipo.ESPERA_MINIMA), equipo.ESPERA_MAXIMA)

    # Por los eventos de la caja y no con un `trace` de la variable: el comando
    # Tcl de un trace no muere con el widget (ver AGENTS.md, la ventana principal).
    caja_plazo = ttk.Spinbox(plazo, textvariable=segundos, from_=equipo.ESPERA_MINIMA,
                             to=equipo.ESPERA_MAXIMA, increment=30, width=6,
                             command=cambiar_plazo)
    caja_plazo.grid(row=0, column=1, padx=6)
    caja_plazo.bind("<KeyRelease>", cambiar_plazo)
    caja_plazo.bind("<FocusOut>", cambiar_plazo)
    ttk.Label(plazo, text="segundos. Sin respuesta, cuenta como «Ahora no» hasta "
                          "que se vuelva a enchufar.", style="Pista.TLabel").grid(
        row=0, column=2, sticky="w")


# ---------------------------------------------------------------------------
# Arranque
# ---------------------------------------------------------------------------

def paso_arranque(cuerpo, wiz) -> None:
    from tkinter import ttk

    import penwatch
    from install import agente

    como = ("una tarea programada de tu usuario, que arranca al iniciar sesión"
            if agente.IS_WIN else
            "un autostart del escritorio (~/.config/autostart), porque los avisos y "
            "la pregunta por una unidad nueva necesitan la sesión gráfica")
    _texto(cuerpo, f"El agente se registra con {como}, y se arranca ya. Sin "
                   "administrador.", 0)
    if penwatch.CONFIG_FILE.exists():
        _texto(cuerpo, (
            "penwatch está instalado en este equipo. El agente lo sustituye: lo que "
            "vigilaba ya está en su lista, y penwatch se desinstala al registrar el "
            "agente. Dos vigilantes a la vez se pisarían."), 1, foreground=theme.AVISO)
    _texto(cuerpo, (
        "Un cambio respecto a penwatch: con el agente, abrir la ventana de una "
        "unidad ya no apaga su servicio para siempre, lo pausa mientras está "
        "abierta. Para pararlo: «python agente.py pausa», o el modo «nada» de esa "
        "unidad."), 2, foreground=theme.TINTA3)

    resultado = ttk.Label(cuerpo, wraplength=theme.medida(ANCHO), justify="left")
    resultado.grid(row=4, column=0, sticky="w", pady=(12, 0))

    def activar() -> None:
        ok, msgs = working(wiz.root, "registrando el agente",
                           lambda: agente.activar(wiz.agente_prep,
                                                  dict(wiz.agente_unidades or {}),
                                                  wiz.agente_espera),
                           "Registrando el agente y arrancándolo.")
        if not ok:
            resultado.configure(text=str(msgs), foreground=theme.PELIGRO)
            wiz.revisar()
            wiz.visor.ver(resultado)
            return
        wiz.agente_hecho = list(msgs)
        resultado.configure(text="\n".join(f"✔ {m}" for m in msgs), foreground=theme.OK)
        wiz.revisar()

    ttk.Button(cuerpo, text="Registrar y arrancar", style="Primary.TButton",
               command=activar).grid(row=3, column=0, sticky="w")
    if wiz.agente_hecho:
        resultado.configure(text="\n".join(f"✔ {m}" for m in wiz.agente_hecho),
                            foreground=theme.OK)


def ok_arranque(wiz) -> bool:
    return bool(wiz.agente_hecho)


# ---------------------------------------------------------------------------
# Verificación
# ---------------------------------------------------------------------------

def comprobaciones() -> list[tuple[str, bool, str]]:
    """(qué, bien, detalle) de lo que quedó puesto. Sin Tk: lo mira el test."""
    import penwatch
    from common import equipo
    from install import agente

    filas = []
    inst = agente.instalado()
    filas.append(("Agente instalado", inst is not None,
                  f"versión {inst.get('version')}, en {inst.get('codigo')}" if inst
                  else "no hay instalacion.json con código"))
    if inst:
        filas.append(("Su Python", _existe(inst.get("python")), str(inst.get("python"))))
    registro = (agente.autostart_file().is_file() if not agente.IS_WIN
                else penwatch.run_quiet(["schtasks", "/Query", "/TN",
                                         agente.TAREA]).returncode == 0)
    filas.append(("Arranca al iniciar sesión", registro,
                  "registrado" if registro else "no está registrado"))
    vivo = equipo.agente_vivo()
    filas.append(("En marcha", vivo is not None,
                  f"pid {vivo.get('pid')}" if vivo else
                  "todavía no: puede tardar unos segundos en arrancar"))
    unidades = equipo.leer_ajustes().unidades
    filas.append(("Unidades en su lista", True,
                  ", ".join(u.nombre or u.id[:8] for u in unidades.values())
                  or "ninguna: preguntará por cada una al enchufarla"))
    filas.append(("penwatch", not penwatch.CONFIG_FILE.exists(),
                  "no está instalado: el agente hace su trabajo"
                  if not penwatch.CONFIG_FILE.exists()
                  else "sigue instalado: dos vigilantes se pisarían"))
    if not agente.IS_WIN:
        avisos = _hay_avisos()
        filas.append(("Avisos del escritorio", avisos is not False,
                      {True: "el escritorio los enseña",
                       None: "no se ha podido preguntar al bus de sesión",
                       False: "nadie atiende org.freedesktop.Notifications: los avisos "
                              "quedarán solo en el diario"}[avisos]))
    return filas


def _existe(ruta) -> bool:
    from pathlib import Path
    try:
        return bool(ruta) and Path(ruta).is_file()
    except OSError:
        return False


def _hay_avisos() -> bool | None:
    try:
        from common import avisos, dbus
        with dbus.Conexion.sesion() as bus:
            return bus.tiene_dueno(avisos.NOTIFICACIONES)
    except Exception:                                   # noqa: BLE001
        return None


def paso_final(cuerpo, wiz) -> None:
    from tkinter import ttk

    _texto(cuerpo, "Lo que ha quedado puesto en este equipo.", 0)
    tabla = ttk.Frame(cuerpo)
    tabla.grid(row=1, column=0, sticky="w")

    def revisar() -> None:
        for hijo in tabla.winfo_children():
            hijo.destroy()
        for i, (etiqueta, ok, detalle) in enumerate(comprobaciones()):
            color = theme.OK if ok else theme.PELIGRO
            ttk.Label(tabla, text="✔" if ok else "✘", foreground=color,
                      width=3).grid(row=i, column=0, sticky="w")
            ttk.Label(tabla, text=etiqueta + ":").grid(row=i, column=1, sticky="w")
            ttk.Label(tabla, text=detalle, foreground=color, wraplength=theme.medida(520),
                      justify="left").grid(row=i, column=2, sticky="w", padx=(10, 0))
        wiz.revisar()

    ttk.Button(cuerpo, text="Volver a comprobar", command=revisar).grid(
        row=2, column=0, sticky="w", pady=(14, 0))
    revisar()
