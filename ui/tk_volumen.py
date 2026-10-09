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

**Se pinta antes de leer la unidad.** Qué tiene puesto la unidad (`volumen.leer()`:
su `autorun.inf`, la raíz física del contenedor, que en Windows recorre las
letras de unidad) se lee en un hilo (`segundo_plano`) mientras la pantalla ya
está entera, con una línea de espera; el campo del nombre, los iconos y
«Guardar» se quedan apagados hasta que llega, y entonces se rellenan.
"""

from __future__ import annotations

from common import autorun

from . import icons, segundo_plano, theme, volumen
from .principal import corto
from .tk import TITLE, Panel, cabecera, dialogo, mostrar, pie, working

MUESTRA = 32
"""El lado de las muestras de color, en medidas del diseño."""
LEYENDO = "Mirando cómo está la unidad…"
"""Lo que dice la línea de espera mientras se lee la unidad."""


def open_dialog(parent) -> None:
    """Abre la ventana; no devuelve nada.

    Lo que cambia es un fichero de la raíz de la unidad y el nombre de este
    dispositivo en `state/fleet.json`; nada de lo que enseña la ventana
    principal depende de ellos.
    """
    dialogo(parent, "Nombre e icono de la unidad", construir, ensenar=mostrar)


def construir(panel: Panel) -> None:
    """Dibuja «Nombre e icono de la unidad» en `panel` (su diálogo o «Ajustes»).

    Se pinta entera sin saber qué tiene puesto la unidad: lo que depende de
    ello (el campo del nombre, los iconos, «Guardar») queda apagado y vacío
    hasta que llega la lectura, y entonces se rellena y se enciende.
    """
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    dlg, marco = panel.ventana, panel.marco
    marco.columnconfigure(0, weight=0)
    marco.columnconfigure(1, weight=1)
    sondeo = panel.sondeo()
    indicador = panel.indicador(marco, ancho=560)
    dlg.indicador, dlg.sondeo = indicador, sondeo   # como `visor`: los tests los miran
    leido: dict = {"estado": None}
    dependientes: list = []

    cabecera(marco, "Nombre e icono de la unidad",
             "Con qué nombre y qué icono la enseña el Explorador de Windows al "
             "conectarla, en vez de «Disco extraíble». No cambia nada de lo que "
             "se sincroniza.",
             ancho=560, estilo="Dialogo.TLabel").grid(row=0, column=0, columnspan=2,
                                                      sticky="w")
    indicador.marco.grid(row=1, column=0, columnspan=2, sticky="w", pady=(theme.E3, 0))

    def etiqueta(texto: str, fila: int, arriba: bool = False) -> None:
        """Pone la etiqueta de un campo en la columna de la izquierda."""
        ttk.Label(marco, text=texto, style="Campo.TLabel").grid(
            row=fila, column=0, sticky="nw" if arriba else "w", padx=(0, theme.E4),
            pady=(theme.E4, 0))

    # El nombre.
    etiqueta("Nombre", 2)
    nombre = tk.StringVar(marco)
    campo = ttk.Entry(marco, textvariable=nombre, width=autorun.MAX_NOMBRE + 2)
    campo.grid(row=2, column=1, sticky="w", pady=(theme.E4, 0))
    dependientes.append(campo)
    pista = ttk.Label(marco, style="Pista.TLabel", wraplength=theme.medida(460),
                      justify="left")
    pista.grid(row=3, column=1, sticky="w", pady=(theme.E1, 0))

    # El icono.
    etiqueta("Icono", 4, arriba=True)
    eleccion = tk.StringVar(marco)
    iconos = ttk.Frame(marco)
    iconos.grid(row=4, column=1, sticky="w", pady=(theme.E4, 0))

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
        radio.grid(row=0, column=i, sticky="w", padx=(0, theme.E4))
        dependientes.append(radio)

    otros = ttk.Frame(iconos)
    otros.grid(row=1, column=0, sticky="w", pady=(theme.E3, 0))
    # Uno propio: el fichero se elige aquí, pero no se copia hasta «Guardar».
    propio: dict = {"datos": None}
    uno_tuyo = ttk.Radiobutton(otros, text="Uno tuyo (.ico)", value=volumen.PROPIO,
                               variable=eleccion)
    uno_tuyo.grid(row=0, column=0, sticky="w")
    # El nombre del fichero que hay puesto no le dice nada a nadie (lleva un
    # trozo de hash): se dice que hay uno, y la ruta solo cuando se elige otro.
    elegido = ttk.Label(otros, style="Pista.TLabel")

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

    elegir_btn = ttk.Button(otros, text="Elegir…", command=elegir)
    elegir_btn.grid(row=0, column=1, sticky="w", padx=(theme.E3, 0))
    elegido.grid(row=0, column=2, sticky="w", padx=(theme.E3, 0))
    # La fila 1 es para «El que ya tiene», que solo sale si hay un `icon=` que no
    # es nuestro y eso se sabe al leer; vacía no ocupa nada.
    ninguno = ttk.Radiobutton(otros, text="Ninguno: el de Windows", value=volumen.NINGUNO,
                              variable=eleccion)
    ninguno.grid(row=2, column=0, columnspan=3, sticky="w")
    dependientes += [uno_tuyo, elegir_btn, ninguno]

    # Dónde se escribe y cuándo se ve: depende de la unidad, así que llega con ella.
    notas = ttk.Label(marco, style="Pista.TLabel", justify="left",
                      wraplength=theme.medida(560))
    notas.grid(row=5, column=0, columnspan=2, sticky="w", pady=(theme.E4, 0))

    def guardar() -> None:
        """Guarda el nombre y el icono, en un hilo, y cierra la ventana."""
        estado = leido["estado"]
        if estado is None:
            return
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

    botones = pie(marco, 6, columnas=2)
    botones.columnconfigure(0, weight=1)
    ttk.Button(botones, text="Cancelar", command=panel.terminar).grid(
        row=0, column=1, padx=(0, theme.E2))
    guardar_btn = ttk.Button(botones, text="Guardar", style="Primary.TButton",
                             command=guardar)
    guardar_btn.grid(row=0, column=2)
    dependientes.append(guardar_btn)
    for control in dependientes:
        control.state(["disabled"])

    def llegada(encargo) -> None:
        """Rellena la pantalla con lo que tiene la unidad y enciende lo que esperaba."""
        if encargo.error is not None:
            indicador.poner(f"No se ha podido leer la unidad: {encargo.error}", False,
                            "Aviso.")
            return
        estado = encargo.resultado
        leido["estado"] = estado
        indicador.poner("", False)
        nombre.set(estado.nombre)
        eleccion.set(estado.clave)
        pista.configure(text=volumen.pista_nombre(estado))
        elegido.configure(text="el que tiene ahora" if estado.clave == volumen.PROPIO
                          else "")
        if estado.clave == volumen.OTRO:
            ttk.Radiobutton(otros, text=f"El que ya tiene ({corto(estado.icono, 40)})",
                            value=volumen.OTRO, variable=eleccion).grid(
                row=1, column=0, columnspan=3, sticky="w")
        inf = estado.raiz / autorun.FICHERO
        if estado.fuera is not None:
            donde = (f"Se guarda en {inf}, y el icono dentro de {estado.carpeta}: "
                     "es el volumen que aparece al abrir el contenedor. El pendrive "
                     f"que lo lleva ({estado.fuera}) conserva su nombre y su icono.")
        else:
            donde = (f"Se guarda en {inf}, y el icono dentro de {estado.carpeta}. "
                     "Con BitLocker, Windows no puede leerlo mientras la unidad "
                     "esté bloqueada.")
        notas.configure(text="\n".join((
            donde,
            "Ese fichero no ejecuta nada: Windows no arranca programas al conectar "
            "una unidad extraíble, pero sí lee de ahí el nombre y el icono, al "
            f"llegar la unidad. El cambio se verá {volumen.cuando_se_ve(estado)}.")))
        for control in dependientes:
            control.state(["!disabled"])
        panel.ajustar()

    indicador.poner(LEYENDO, True)
    sondeo.esperar(segundo_plano.lanzar_sin_repetir("volumen", None, volumen.leer),
                   llegada)
