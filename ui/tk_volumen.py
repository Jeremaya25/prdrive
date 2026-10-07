#!/usr/bin/env python3
"""«Nombre e icono de la unidad»: cómo la enseña el Explorador.

Solo dibuja. Qué hay puesto, qué se puede poner y cómo se escribe lo decide
`ui/volumen.py`, que no importa Tk y se prueba sin pantalla.

Cuelga de «Ajustes» porque se hace una vez (o cuando se tiene un segundo
dispositivo y hace falta distinguirlos), no cada vez que se sincroniza. Es el
único sitio donde se cambia el nombre del dispositivo: «Dispositivos…» solo lo
enseña.

Tres cosas se dicen en la propia ventana porque sin ellas parece que no
funciona: el Explorador lee el fichero **al llegar la unidad**, así que el
cambio se ve la próxima vez que se conecte (con VeraCrypt, que se abra) y no al
pulsar «Guardar»; con BitLocker no lo lee mientras esté bloqueada; y con
VeraCrypt lo que cambia es el volumen que aparece al abrir el contenedor, no el
pendrive que se enchufa.
"""

from __future__ import annotations

from common import autorun

from . import icons, theme, volumen
from .tk import TITLE, Panel, cabecera, corto, dialogo, mostrar, pie, working

MUESTRA = 32
"""El lado de las muestras de color, en medidas del diseño."""


def open_dialog(parent) -> None:
    """Abre la ventana; no devuelve nada.

    Lo que cambia es un fichero de la raíz de la unidad y el nombre de este
    dispositivo en `state/fleet.json`; nada de lo que enseña la ventana
    principal depende de ellos.
    """
    dialogo(parent, "Nombre e icono de la unidad", construir, ensenar=mostrar)


def construir(panel: Panel) -> None:
    """Dibuja «Nombre e icono de la unidad» en `panel` (su diálogo o «Ajustes»)."""
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    estado = volumen.leer()
    dlg, marco = panel.ventana, panel.marco
    marco.columnconfigure(0, weight=0)
    marco.columnconfigure(1, weight=1)

    cabecera(marco, "Nombre e icono de la unidad",
             "Con qué nombre y qué icono la enseña el Explorador de Windows al "
             "conectarla, en vez de «Disco extraíble». No cambia nada de lo que "
             "se sincroniza.",
             ancho=560, estilo="Dialogo.TLabel").grid(row=0, column=0, columnspan=2,
                                                      sticky="w")

    def etiqueta(texto: str, fila: int, arriba: bool = False) -> None:
        """Pone la etiqueta de un campo en la columna de la izquierda."""
        ttk.Label(marco, text=texto, style="Campo.TLabel").grid(
            row=fila, column=0, sticky="nw" if arriba else "w", padx=(0, 14),
            pady=(18, 0))

    # El nombre.
    etiqueta("Nombre", 1)
    nombre = tk.StringVar(marco, value=estado.nombre)
    ttk.Entry(marco, textvariable=nombre, width=autorun.MAX_NOMBRE + 2).grid(
        row=1, column=1, sticky="w", pady=(18, 0))
    ttk.Label(marco, style="Pista.TLabel", text=volumen.pista_nombre(estado),
              wraplength=theme.medida(460), justify="left").grid(
        row=2, column=1, sticky="w", pady=(4, 0))

    # El icono.
    etiqueta("Icono", 3, arriba=True)
    eleccion = tk.StringVar(marco, value=estado.clave)
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
        """Deja elegir un `.ico` propio y lo lee."""
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

    # Dónde se escribe y cuándo se ve.
    inf = estado.raiz / autorun.FICHERO
    if estado.fuera is not None:
        donde = (f"Se guarda en {inf}, y el icono dentro de {estado.carpeta}: "
                 "es el volumen que aparece al abrir el contenedor. El pendrive "
                 f"que lo lleva ({estado.fuera}) conserva su nombre y su icono.")
    else:
        donde = (f"Se guarda en {inf}, y el icono dentro de {estado.carpeta}. "
                 "Con BitLocker, Windows no puede leerlo mientras la unidad "
                 "esté bloqueada.")
    notas = [donde,
             "Ese fichero no ejecuta nada: Windows no arranca programas al "
             "conectar una unidad extraíble, pero sí lee de ahí el nombre y el "
             "icono, al llegar la unidad. El cambio se verá "
             f"{volumen.cuando_se_ve(estado)}."]
    ttk.Label(marco, text="\n".join(notas), style="Pista.TLabel", justify="left",
              wraplength=theme.medida(560)).grid(row=4, column=0, columnspan=2,
                                                 sticky="w", pady=(18, 0))

    def guardar() -> None:
        """Guarda el nombre y el icono, en un hilo, y cierra la ventana."""
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
        messagebox.showinfo(TITLE, volumen.mensaje_guardado(estado, texto), parent=dlg)
        panel.terminar("Guardado.")

    botones = pie(marco, 5, columnas=2)
    botones.columnconfigure(0, weight=1)
    ttk.Button(botones, text="Cancelar", command=panel.terminar).grid(
        row=0, column=1, padx=(0, 6))
    ttk.Button(botones, text="Guardar", style="Primary.TButton",
               command=guardar).grid(row=0, column=2)
