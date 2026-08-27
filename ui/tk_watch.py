#!/usr/bin/env python3
"""
tk_watch.py — La pantalla del arranque automático (penwatch.py).

Solo dibuja. Lo que sabe de penwatch está en `ui/watch.py`, y la división es la
misma de siempre: lo que se lee (estado, detección) se pregunta en el sitio, y lo
que escribe en el equipo (instalar, desinstalar) se lanza como proceso y su
salida se enseña en la ventana de salida de siempre. Así se ve exactamente lo que
ha hecho, igual que cuando se lanza una sincronización.

Lo que el diseño cambia aquí es de dónde se lee cada cosa: el estado deja de ser
una lista de pares «etiqueta: valor» a secas y pasa a una tarjeta donde lo que se
mira de un vistazo —si está instalado, si la tarea está activa, si el dispositivo se ve
ahora mismo— son chips, y el resto texto normal.
"""

from __future__ import annotations

from . import theme, watch
from .tk import TITLE, cabecera, modal, mostrar, output_window

# Las filas de estado que además de un valor llevan un veredicto, y por eso se
# pintan como chip en vez de como texto. La clave es la etiqueta tal cual la
# devuelve `penwatch.status_rows()`; lo que no esté aquí sale como texto, así que
# añadir una fila allí no rompe nada aquí.
#
#   etiqueta -> (resumen si va bien, resumen si no, qué palabra decide)
CHIPS = {
    "Registro en el sistema": ("activo", "sin registrar", "NO registrada"),
    "Vigilante": ("en marcha", "parado", "parado"),
    "Dispositivo ahora mismo": ("visible", "no se ve", "no detectado"),
}


def _chip_de(etiqueta: str, valor: str):
    """El chip que le toca a una fila de estado, o None si es texto normal.

    Se decide por la palabra que penwatch usa para el caso malo y no por la
    buena: los valores buenos traen detalles pegados (el pid, la ruta del dispositivo) y
    buscar en ellos sería adivinar."""
    regla = CHIPS.get(etiqueta)
    if regla is None:
        return None
    bien, mal, palabra = regla
    malo = palabra.lower() in valor.lower()
    return (mal if malo else bien, "Aviso." if malo else "Ok.",
            "warn" if malo else "ok")


def open_dialog(parent, config=None) -> None:
    from tkinter import messagebox, ttk

    dlg = modal(parent, "Arranque automático")
    marco = ttk.Frame(dlg, padding=(20, 18, 20, 16))
    marco.grid(sticky="nsew")
    marco.columnconfigure(0, weight=1)

    arriba = ttk.Frame(marco)
    arriba.grid(row=0, column=0, sticky="ew")
    arriba.columnconfigure(0, weight=1)
    cabecera(arriba, "Arranque automático",
             "El vigilante se instala en ESTE equipo, no en el dispositivo, y lanza "
             "prdrive en cuanto detecta el dispositivo y puede leerlo. Sin permisos "
             "administrador y sin dejar rastro en el dispositivo.",
             ancho=560, estilo="Dialogo.TLabel").grid(row=0, column=0, sticky="w")
    chip_estado = {"widget": None}

    tarjeta = ttk.Frame(marco, style="Card.TFrame", padding=(14, 4))
    tarjeta.grid(row=1, column=0, sticky="ew", pady=(16, 0))
    tarjeta.columnconfigure(1, weight=1)

    rotulo_diario = ttk.Frame(marco)
    rotulo_diario.grid(row=2, column=0, sticky="ew", pady=(16, 7))
    rotulo_diario.columnconfigure(0, weight=1)
    titulo_diario = ttk.Label(rotulo_diario, style="Rotulo.TLabel")
    titulo_diario.grid(row=0, column=0, sticky="w")
    ttk.Label(rotulo_diario, text=watch.log_path(), style="MonoPista.TLabel").grid(
        row=0, column=1, sticky="e")

    diario = theme.caja_texto(marco, width=92, height=8, state="disabled",
                              font=theme.fuente("mono_pequena"), wrap="char",
                              foreground=theme.TINTA2, highlightbackground=theme.LINEA)
    diario.grid(row=3, column=0, sticky="ew")

    def pintar(filas, titulo: str, lineas: list[str]) -> None:
        for hijo in tarjeta.winfo_children():
            hijo.destroy()
        for i, (etiqueta, valor) in enumerate(filas):
            linea = i * 2
            if i:
                ttk.Separator(tarjeta, orient="horizontal",
                              style="Card.TSeparator").grid(
                    row=linea - 1, column=0, columnspan=3, sticky="ew")
            if not etiqueta:
                # Una fila sin etiqueta es un aviso de penwatch, no un dato.
                ttk.Label(tarjeta, text=valor, style="Card.Aviso.TLabel",
                          wraplength=740, justify="left").grid(
                    row=linea, column=0, columnspan=3, sticky="w", pady=7)
                continue
            ttk.Label(tarjeta, text=etiqueta, style="Card.Pista.TLabel",
                      width=24).grid(row=linea, column=0, sticky="w", pady=7)
            chip = _chip_de(etiqueta, valor)
            if chip is None:
                ttk.Label(tarjeta, text=valor, style="Card.TLabel", wraplength=520,
                          justify="left").grid(row=linea, column=1, sticky="w",
                                               padx=(12, 0), pady=7)
            else:
                texto, tipo, icono = chip
                theme.chip(tarjeta, texto, tipo, icono).grid(
                    row=linea, column=2, sticky="e", pady=7)
        titulo_diario.configure(text=theme.rotulo(titulo))
        diario.configure(state="normal")
        diario.delete("1.0", "end")
        diario.insert("end", "\n".join(lineas) or "  (vacío)")
        diario.configure(state="disabled")

    def ver_estado() -> None:
        pintar(watch.status_rows(), "Diario del vigilante", watch.log_tail())
        if chip_estado["widget"] is not None:
            chip_estado["widget"].destroy()
        puesto = watch.is_installed()
        chip_estado["widget"] = theme.chip(
            arriba, "instalado" if puesto else "sin instalar",
            "Ok." if puesto else "Apagado.", "ok" if puesto else None)
        chip_estado["widget"].grid(row=0, column=1, sticky="ne", pady=(4, 0))
        instalar_btn.configure(text="Reinstalar…" if puesto else "Instalar…")

    def ver_deteccion() -> None:
        filas = [(raiz, nota) for raiz, nota in watch.probe_rows()]
        pintar(filas, "Dónde se ha buscado el dispositivo", [])

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
                "configuración y su diario.\n\nEl dispositivo no se toca."), parent=dlg):
            return
        lanzar(watch.uninstall_command(), "desinstalar el vigilante")

    botones = ttk.Frame(marco)
    botones.grid(row=4, column=0, sticky="ew", pady=(14, 0))
    botones.columnconfigure(2, weight=1)
    for i, (texto, icono, accion) in enumerate((
            ("Actualizar", "reload", ver_estado),
            ("Detectar el dispositivo", "eye", ver_deteccion))):
        boton = ttk.Button(botones, text=texto, command=accion)
        theme.boton_icono(boton, icono, theme.TINTA2, theme.SUPERFICIE)
        boton.grid(row=0, column=i, sticky="w", padx=(0, 6))
    quitar = ttk.Button(botones, text="Desinstalar…", style="Danger.TButton",
                        command=desinstalar)
    theme.boton_icono(quitar, "trash", theme.PELIGRO, theme.SUPERFICIE)
    quitar.grid(row=0, column=3, padx=(0, 6))
    instalar_btn = ttk.Button(botones, text="Instalar…", style="Primary.TButton",
                              command=instalar)
    theme.boton_icono(instalar_btn, "plug", theme.SUPERFICIE, theme.ACENTO)
    instalar_btn.grid(row=0, column=4, padx=(0, 6))
    ttk.Button(botones, text="Cerrar", command=dlg.destroy).grid(row=0, column=5)

    ver_estado()
    mostrar(dlg, parent)


def formulario_instalacion(parent, config) -> dict | None:
    """Las opciones de `penwatch install`. None si se cancela."""
    import tkinter as tk
    from tkinter import ttk

    dlg = modal(parent, "Instalar el vigilante")
    marco = ttk.Frame(dlg, padding=(20, 18, 20, 16))
    marco.grid(sticky="nsew")
    marco.columnconfigure(2, weight=1)
    resultado: dict = {"opciones": None}
    previas = watch.installed_options()

    ttk.Label(marco, text="Instalar el vigilante en este equipo",
              style="Dialogo.TLabel").grid(row=0, column=0, columnspan=3, sticky="w")
    ttk.Label(marco, style="Pista.TLabel", wraplength=620, justify="left",
              text="Se registra una tarea del usuario que arranca al iniciar "
                   "sesión. Nada de esto se escribe en el dispositivo.").grid(
        row=1, column=0, columnspan=3, sticky="w", pady=(5, 14))

    def etiqueta(texto: str, en: int, arriba: bool = False) -> None:
        ttk.Label(marco, text=texto, style="Campo.TLabel", anchor="e",
                  width=22).grid(row=en, column=0, sticky="ne" if arriba else "e",
                                 padx=(0, 12), pady=(5, 0) if arriba else 3)

    etiqueta("Al detectar el dispositivo", 2)
    modo = tk.StringVar(value=previas.get("mode", "ui"))
    ttk.Combobox(marco, textvariable=modo, state="readonly", width=12,
                 values=list(watch.MODES)).grid(row=2, column=1, sticky="w", pady=3)
    ayuda = ttk.Label(marco, style="Pista.TLabel", wraplength=340, justify="left")
    ayuda.grid(row=2, column=2, sticky="w", padx=(12, 0))

    # Las parejas y el intervalo solo pintan algo en los modos que sincronizan.
    etiqueta("Parejas", 3, arriba=True)
    marco_parejas = ttk.Frame(marco, style="Card.TFrame", padding=(12, 10))
    marco_parejas.grid(row=3, column=1, columnspan=2, sticky="w", pady=(8, 2))
    elegidas: dict[str, tk.BooleanVar] = {}
    nombres = list(config.names) if config is not None else []
    for i, nombre in enumerate(nombres):
        var = tk.BooleanVar(value=nombre in (previas.get("pairs") or []))
        elegidas[nombre] = var
        ttk.Checkbutton(marco_parejas, text=nombre, variable=var,
                        style="Card.TCheckbutton").grid(
            row=i // 3, column=i % 3, sticky="w", padx=(0, 16))
    if not nombres:
        ttk.Label(marco_parejas, text="(no se han podido leer las parejas)",
                  style="Card.Pista.TLabel").grid()
    else:
        ttk.Label(marco_parejas, text="Vacío = todas.", style="Card.Pista.TLabel").grid(
            row=len(nombres) // 3 + 1, column=0, columnspan=3, sticky="w",
            pady=(6, 0))

    fila = 4
    etiqueta("Intervalo del servicio", fila)
    intervalo = tk.StringVar(value=str(previas.get("interval") or ""))
    entrada_intervalo = ttk.Entry(marco, textvariable=intervalo, width=8)
    entrada_intervalo.grid(row=fila, column=1, sticky="w", pady=3)
    ttk.Label(marco, text="minutos; vacío = el de [daemon] del TOML",
              style="Pista.TLabel").grid(row=fila, column=2, sticky="w", padx=(12, 0))
    fila += 1

    etiqueta("Sondeo del dispositivo", fila)
    sondeo = tk.StringVar(value=str(previas.get("poll") or 5))
    ttk.Entry(marco, textvariable=sondeo, width=8).grid(row=fila, column=1,
                                                        sticky="w", pady=3)
    ttk.Label(marco, style="Pista.TLabel", wraplength=340, justify="left",
              text=("Segundos. Se sondea en vez de escuchar al sistema: en un dispositivo "
                    "cifrado el aviso de llegada ocurre mucho antes de que el "
                    "volumen se pueda leer.")).grid(row=fila, column=2, sticky="w",
                                                    padx=(12, 0))
    fila += 1

    etiqueta("Raíces extra", fila, arriba=True)
    raices = theme.caja_texto(marco, width=30, height=3)
    raices.insert("1.0", "\n".join(previas.get("extra_roots") or []))
    raices.grid(row=fila, column=1, columnspan=2, sticky="w", pady=(8, 2))
    fila += 1

    arrancar = tk.BooleanVar(value=True)
    ttk.Checkbutton(marco, variable=arrancar,
                    text="Arrancar el vigilante ahora mismo").grid(
        row=fila, column=1, columnspan=2, sticky="w", pady=(10, 0))
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

    ttk.Separator(marco, orient="horizontal").grid(row=fila, column=0, columnspan=3,
                                                   sticky="ew", pady=(16, 0))
    pie = ttk.Frame(marco)
    pie.grid(row=fila + 1, column=0, columnspan=3, sticky="e", pady=(14, 0))
    ttk.Button(pie, text="Cancelar", command=dlg.destroy).grid(row=0, column=0,
                                                               padx=(0, 6))
    instalar = ttk.Button(pie, text="Instalar", style="Primary.TButton",
                          command=aceptar)
    theme.boton_icono(instalar, "plug", theme.SUPERFICIE, theme.ACENTO)
    instalar.grid(row=0, column=1)

    mostrar(dlg, parent)
    return resultado["opciones"]
