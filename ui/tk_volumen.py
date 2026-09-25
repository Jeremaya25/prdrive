#!/usr/bin/env python3
"""
tk_volumen.py — «Nombre e icono de la unidad»: cómo la enseña el Explorador.

Solo dibuja. Qué hay puesto, qué se puede poner y cómo se escribe lo decide
`ui/volumen.py`, que no importa Tk y se prueba sin pantalla.

Cuelga de «Ajustes» porque se hace una vez —o cuando se tiene un segundo
dispositivo y hace falta distinguirlos—, no cada vez que se sincroniza.

Tres cosas se dicen en la propia ventana porque sin ellas parece que no funciona:
el Explorador lee el fichero **al llegar la unidad**, así que el cambio se ve la
próxima vez que se conecte, no al pulsar «Guardar»; con BitLocker no lo lee
mientras esté bloqueada; y con VeraCrypt lo que cambia es la unidad que se
enchufa, no el volumen que aparece al abrir el contenedor.
"""

from __future__ import annotations

from common import autorun

from . import icons, theme, volumen
from .tk import TITLE, cabecera, corto, cuerpo_visible, modal, mostrar, working

# El lado de las muestras de color, en medidas del diseño.
MUESTRA = 32


def open_dialog(parent) -> None:
    """Abre la ventana. No devuelve nada: lo que cambia es un fichero de la
    raíz de la unidad, y nada de lo que enseña la ventana principal depende de él."""
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    estado = volumen.leer()
    dlg = modal(parent, "Nombre e icono de la unidad")
    marco = cuerpo_visible(dlg, padding=(22, 20, 22, 18))
    marco.columnconfigure(1, weight=1)

    cabecera(marco, "Nombre e icono de la unidad",
             "Con qué nombre y qué icono la enseña el Explorador de Windows al "
             "conectarla, en vez de «Disco extraíble». No cambia nada de lo que "
             "se sincroniza.",
             ancho=560, estilo="Dialogo.TLabel").grid(row=0, column=0, columnspan=2,
                                                      sticky="w")

    def etiqueta(texto: str, fila: int, arriba: bool = False) -> None:
        ttk.Label(marco, text=texto, style="Campo.TLabel").grid(
            row=fila, column=0, sticky="nw" if arriba else "w", padx=(0, 14),
            pady=(18, 0))

    # --- el nombre ---------------------------------------------------------
    etiqueta("Nombre", 1)
    nombre = tk.StringVar(value=estado.nombre)
    ttk.Entry(marco, textvariable=nombre, width=autorun.MAX_NOMBRE + 2).grid(
        row=1, column=1, sticky="w", pady=(18, 0))
    ttk.Label(marco, style="Pista.TLabel",
              text=f"Hasta {autorun.MAX_NOMBRE} caracteres. Vacío, el que le "
                   "ponga Windows.").grid(row=2, column=1, sticky="w", pady=(4, 0))

    # --- el icono ----------------------------------------------------------
    etiqueta("Icono", 3, arriba=True)
    eleccion = tk.StringVar(value=estado.clave)
    iconos = ttk.Frame(marco)
    iconos.grid(row=3, column=1, sticky="w", pady=(18, 0))

    # Los cinco colores de la marca, en fila y con su muestra encima: es lo que
    # distingue un dispositivo de otro, así que se ve antes de elegirlo.
    colores = ttk.Frame(iconos)
    colores.grid(row=0, column=0, sticky="w")
    lado = icons.px(colores, MUESTRA)
    for i, marca in enumerate(volumen.MARCAS):
        radio = ttk.Radiobutton(colores, text=marca.nombre, value=marca.clave,
                                variable=eleccion, compound="top")
        muestra = icons.app_icon(colores, lado, marca.campo, theme.PAPEL)
        if muestra is not None:
            radio.configure(image=muestra)
            radio.image = muestra           # type: ignore[attr-defined]
        radio.grid(row=0, column=i, sticky="w", padx=(0, 16))

    otros = ttk.Frame(iconos)
    otros.grid(row=1, column=0, sticky="w", pady=(10, 0))
    fila = 0
    if estado.veracrypt or estado.clave == volumen.VERACRYPT:
        ttk.Radiobutton(otros, text="El de VeraCrypt, que viaja en la unidad",
                        value=volumen.VERACRYPT, variable=eleccion).grid(
            row=fila, column=0, columnspan=3, sticky="w")
        fila += 1

    # Uno propio: el fichero se elige aquí, pero no se copia hasta «Guardar».
    propio: dict = {"datos": None}
    ttk.Radiobutton(otros, text="Uno tuyo (.ico)", value=volumen.PROPIO,
                    variable=eleccion).grid(row=fila, column=0, sticky="w")
    # El nombre del fichero que hay puesto no le dice nada a nadie (lleva un
    # trozo de hash): se dice que hay uno, y la ruta solo cuando se elige otro.
    elegido = ttk.Label(otros, style="Pista.TLabel",
                        text="el que tiene ahora" if estado.clave == volumen.PROPIO
                        else "")

    def elegir() -> None:
        ruta = filedialog.askopenfilename(
            parent=dlg, title="Un icono para la unidad",
            filetypes=[("Iconos de Windows", "*.ico"), ("Todos los ficheros", "*")])
        if not ruta:
            return
        try:
            propio["datos"] = volumen.leer_ico(ruta)
        except volumen.VolumenError as e:
            messagebox.showerror(TITLE, str(e), parent=dlg)
            return
        elegido.configure(text=corto(ruta, 40), style="MonoPista.TLabel")
        eleccion.set(volumen.PROPIO)

    ttk.Button(otros, text="Elegir…", command=elegir).grid(
        row=fila, column=1, sticky="w", padx=(10, 0))
    elegido.grid(row=fila, column=2, sticky="w", padx=(10, 0))
    fila += 1

    if estado.clave == volumen.OTRO:
        ttk.Radiobutton(otros, text=f"El que ya tiene ({corto(estado.icono, 40)})",
                        value=volumen.OTRO, variable=eleccion).grid(
            row=fila, column=0, columnspan=3, sticky="w")
        fila += 1
    ttk.Radiobutton(otros, text="Ninguno: el de Windows", value=volumen.NINGUNO,
                    variable=eleccion).grid(row=fila, column=0, columnspan=3,
                                            sticky="w")

    # --- dónde se escribe y cuándo se ve ------------------------------------
    inf = estado.raiz / autorun.FICHERO
    if estado.fisica:
        donde = (f"Se guarda en {inf}, fuera del contenedor, con el icono al "
                 "lado y oculto: es la unidad que se enchufa, y lo de dentro el "
                 "Explorador no lo ve hasta abrirlo. La que aparece al abrirlo "
                 "conserva su nombre.")
    else:
        donde = (f"Se guarda en {inf}, y el icono dentro de {estado.carpeta}. "
                 "Con BitLocker, Windows no puede leerlo mientras la unidad "
                 "esté bloqueada.")
    notas = [donde,
             "Ese fichero no ejecuta nada: Windows no arranca programas al "
             "conectar una unidad extraíble, pero sí lee de ahí el nombre y el "
             "icono, al llegar la unidad. El cambio se verá la próxima vez que "
             "la conectes."]
    ttk.Label(marco, text="\n".join(notas), style="Pista.TLabel", justify="left",
              wraplength=theme.medida(560)).grid(row=4, column=0, columnspan=2,
                                                 sticky="w", pady=(18, 0))

    def guardar() -> None:
        try:
            texto = volumen.revisar_nombre(nombre.get())
        except volumen.VolumenError as e:
            messagebox.showerror(TITLE, str(e), parent=dlg)
            return
        # Pintar un color de la marca son un par de segundos: en un hilo.
        ok, valor = working(dlg, "Guardando",
                            lambda: volumen.guardar(estado, texto, eleccion.get(),
                                                    propio["datos"]),
                            "Guardando el nombre y el icono de la unidad…")
        if not ok:
            messagebox.showerror(TITLE, str(valor), parent=dlg)
            return
        messagebox.showinfo(TITLE, "Guardado. Se verá la próxima vez que "
                                   "conectes la unidad.", parent=dlg)
        dlg.destroy()

    ttk.Separator(marco, orient="horizontal").grid(row=5, column=0, columnspan=2,
                                                   sticky="ew", pady=(16, 0))
    pie = ttk.Frame(marco)
    pie.grid(row=6, column=0, columnspan=2, sticky="e", pady=(14, 0))
    ttk.Button(pie, text="Cancelar", command=dlg.destroy).grid(row=0, column=0,
                                                               padx=(0, 6))
    ttk.Button(pie, text="Guardar", style="Primary.TButton",
               command=guardar).grid(row=0, column=1)

    mostrar(dlg, parent)
