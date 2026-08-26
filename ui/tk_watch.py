#!/usr/bin/env python3
"""
tk_watch.py — La pantalla del arranque automático (penwatch.py).

Solo dibuja. Lo que sabe de penwatch está en `ui/watch.py`, y la división es la
misma de siempre: lo que se lee (estado, detección) se pregunta en el sitio, y lo
que escribe en el equipo (instalar, desinstalar) se lanza como proceso y su
salida se enseña en la ventana de salida de siempre. Así se ve exactamente lo que
ha hecho, igual que cuando se lanza una sincronización.
"""

from __future__ import annotations

from . import watch
from .tk import TITLE, modal, output_window


def open_dialog(parent, config=None) -> None:
    import tkinter as tk
    from tkinter import messagebox, ttk

    dlg = modal(parent, "Arranque automático")
    marco = ttk.Frame(dlg, padding=12)
    marco.grid(sticky="nsew")

    ttk.Label(marco, justify="left", wraplength=620, text=(
        "El vigilante se instala en ESTE equipo (no en el pen) y lanza runsync en "
        "cuanto detecta el pen y se puede leer. No necesita permisos de "
        "administrador y no deja rastro en el pen.")).grid(
        row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))

    cuerpo = ttk.Frame(marco)
    cuerpo.grid(row=1, column=0, columnspan=2, sticky="w")

    diario = tk.Text(marco, width=92, height=8, state="disabled",
                     font=("Consolas", 8))
    diario.grid(row=2, column=0, columnspan=2, sticky="w", pady=(10, 0))

    def pintar(filas, titulo_diario: str, lineas: list[str]) -> None:
        for hijo in cuerpo.winfo_children():
            hijo.destroy()
        for i, (etiqueta, valor) in enumerate(filas):
            if etiqueta:
                ttk.Label(cuerpo, text=etiqueta + ":").grid(row=i, column=0, sticky="w")
                ttk.Label(cuerpo, text=valor).grid(row=i, column=1, sticky="w", padx=(10, 0))
            else:
                ttk.Label(cuerpo, text=valor, foreground="#775500").grid(
                    row=i, column=0, columnspan=2, sticky="w")
        diario.configure(state="normal")
        diario.delete("1.0", "end")
        diario.insert("end", titulo_diario + "\n" + ("\n".join(lineas) or "  (vacío)"))
        diario.configure(state="disabled")

    def ver_estado() -> None:
        pintar(watch.status_rows(), "--- diario del vigilante ---", watch.log_tail())

    def ver_deteccion() -> None:
        filas = [(raiz, nota) for raiz, nota in watch.probe_rows()]
        pintar(filas, "--- dónde se ha buscado el pen ---", [])

    def lanzar(cmd: list[str], titulo: str) -> None:
        output_window(titulo, cmd, parent=dlg)
        ver_estado()

    def instalar() -> None:
        opciones = formulario_instalacion(dlg, config)
        if opciones is None:
            return
        lanzar(watch.install_command(**opciones), "instalar el vigilante")

    def desinstalar() -> None:
        if not watch.is_installed():
            messagebox.showinfo(TITLE, "En este equipo no hay nada instalado.", parent=dlg)
            return
        if not messagebox.askokcancel(TITLE, (
                "Se quitará el vigilante de este equipo: la tarea programada, su "
                "configuración y su diario.\n\nEl pen no se toca."), parent=dlg):
            return
        lanzar(watch.uninstall_command(), "desinstalar el vigilante")

    botones = ttk.Frame(marco)
    botones.grid(row=3, column=0, columnspan=2, pady=(12, 0), sticky="w")
    for i, (texto, accion) in enumerate((
            ("Actualizar", ver_estado),
            ("Detectar el pen", ver_deteccion),
            ("Instalar…", instalar),
            ("Desinstalar…", desinstalar),
            ("Cerrar", dlg.destroy))):
        ttk.Button(botones, text=texto, command=accion).grid(row=0, column=i, padx=3)

    ver_estado()
    dlg.wait_window()


def formulario_instalacion(parent, config) -> dict | None:
    """Las opciones de `penwatch install`. None si se cancela."""
    import tkinter as tk
    from tkinter import ttk

    dlg = modal(parent, "Instalar el vigilante")
    marco = ttk.Frame(dlg, padding=12)
    marco.grid(sticky="nsew")
    resultado: dict = {"opciones": None}
    previas = watch.installed_options()

    ttk.Label(marco, text="Al detectar el pen:").grid(row=0, column=0, sticky="w")
    modo = tk.StringVar(value=previas.get("mode", "ui"))
    ttk.Combobox(marco, textvariable=modo, state="readonly", width=12,
                 values=list(watch.MODES)).grid(row=0, column=1, sticky="w")
    ayuda = ttk.Label(marco, foreground="#666666", wraplength=380, justify="left")
    ayuda.grid(row=0, column=2, sticky="w", padx=(10, 0))

    # Las parejas y el intervalo solo pintan algo en los modos que sincronizan.
    marco_parejas = ttk.LabelFrame(marco, text="Parejas (vacío = todas)", padding=8)
    marco_parejas.grid(row=1, column=0, columnspan=3, sticky="w", pady=(10, 0))
    elegidas: dict[str, tk.BooleanVar] = {}
    nombres = list(config.names) if config is not None else []
    for i, nombre in enumerate(nombres):
        var = tk.BooleanVar(value=nombre in (previas.get("pairs") or []))
        elegidas[nombre] = var
        ttk.Checkbutton(marco_parejas, text=nombre, variable=var).grid(
            row=i // 3, column=i % 3, sticky="w", padx=(0, 12))
    if not nombres:
        ttk.Label(marco_parejas, text="(no se han podido leer las parejas)").grid()

    fila = 2
    ttk.Label(marco, text="Intervalo del servicio (min):").grid(
        row=fila, column=0, sticky="w", pady=(10, 0))
    intervalo = tk.StringVar(value=str(previas.get("interval") or ""))
    entrada_intervalo = ttk.Entry(marco, textvariable=intervalo, width=8)
    entrada_intervalo.grid(row=fila, column=1, sticky="w", pady=(10, 0))
    ttk.Label(marco, text="vacío = el de [daemon] del TOML",
              foreground="#666666").grid(row=fila, column=2, sticky="w", padx=(10, 0))
    fila += 1

    ttk.Label(marco, text="Sondeo del pen (s):").grid(row=fila, column=0, sticky="w")
    sondeo = tk.StringVar(value=str(previas.get("poll") or 5))
    ttk.Entry(marco, textvariable=sondeo, width=8).grid(row=fila, column=1, sticky="w")
    ttk.Label(marco, foreground="#666666", wraplength=380, justify="left",
              text=("Se sondea en vez de escuchar al sistema: en un pen cifrado el "
                    "aviso de llegada ocurre mucho antes de que el volumen se lea.")
              ).grid(row=fila, column=2, sticky="w", padx=(10, 0))
    fila += 1

    ttk.Label(marco, text="Raíces extra (una por línea):").grid(
        row=fila, column=0, sticky="nw", pady=(10, 0))
    raices = tk.Text(marco, width=32, height=3, font=("Consolas", 9))
    raices.insert("1.0", "\n".join(previas.get("extra_roots") or []))
    raices.grid(row=fila, column=1, columnspan=2, sticky="w", pady=(10, 0))
    fila += 1

    arrancar = tk.BooleanVar(value=True)
    ttk.Checkbutton(marco, variable=arrancar,
                    text="Arrancar el vigilante ahora mismo").grid(
        row=fila, column=0, columnspan=3, sticky="w", pady=(10, 0))
    fila += 1

    def modo_cambiado(*_):
        ayuda.configure(text=watch.MODE_HELP.get(modo.get(), ""))
        sincroniza = modo.get() in ("sync", "daemon")
        for hijo in marco_parejas.winfo_children():
            hijo.configure(state="normal" if sincroniza else "disabled")
        entrada_intervalo.configure(state="normal" if modo.get() == "daemon" else "disabled")
    modo.trace_add("write", modo_cambiado)
    modo_cambiado()

    def aceptar():
        def numero(var):
            try:
                return float(var.get().replace(",", "."))
            except ValueError:
                return None
        resultado["opciones"] = {
            "mode": modo.get(),
            "pairs": [n for n, v in elegidas.items()
                      if v.get() and modo.get() in ("sync", "daemon")],
            "interval": numero(intervalo) if modo.get() == "daemon" else None,
            "poll": numero(sondeo),
            "extra_roots": raices.get("1.0", "end").splitlines(),
            "start": bool(arrancar.get()),
        }
        dlg.destroy()

    pie = ttk.Frame(marco)
    pie.grid(row=fila, column=0, columnspan=3, pady=(14, 0))
    ttk.Button(pie, text="Instalar", command=aceptar).grid(row=0, column=0, padx=3)
    ttk.Button(pie, text="Cancelar", command=dlg.destroy).grid(row=0, column=1, padx=3)

    dlg.wait_window()
    return resultado["opciones"]
