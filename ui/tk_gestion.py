"""«Servidor…»: el diálogo de nombre, la barra de gestión y el menú contextual; solo dibujan.

Qué nombre vale lo decide quien llama con `validar` (`ui/gestion.py`); qué se
puede hacer con lo elegido, también: esta capa pone los textos y los botones y
avisa de las pulsaciones a las acciones que le dan (`ui/tk_servidor.py`). Nada
de aquí lee disco ni red.
"""

from __future__ import annotations

from collections.abc import Callable

from . import theme
from .tk import _suelto, cuerpo_visible, modal, mostrar

ANCHO_MOTIVO = 420
"""Ancho (px del diseño) donde se corta el motivo bajo el campo."""
ANCHO_CAMPO = 40
"""Ancho (en caracteres) del campo del nombre."""
ROTULOS = {"nueva": "Nueva carpeta…", "renombrar": "Renombrar…", "cortar": "Cortar",
           "pegar": "Pegar aquí", "borrar": "Borrar…"}
"""El rótulo de cada acción, en la barra y en el menú."""
ORDEN_BARRA = ("nueva", "renombrar", "cortar", "borrar")
"""Las acciones de la barra, de izquierda a derecha («Pegar aquí» sale en la línea del corte)."""
ORDEN_MENU = ("nueva", "renombrar", "cortar", "pegar", "borrar")
"""Las entradas del menú contextual, de arriba abajo."""


def _fin_de_seleccion(inicial: str, es_archivo: bool) -> int:
    """Hasta dónde se selecciona el nombre al abrir el diálogo.

    Args:
        inicial: El nombre con el que se abre.
        es_archivo: Si es un archivo, que lleva extensión tras el último punto.

    Returns:
        La posición del último punto de un archivo (si no es el primer
        carácter, como en `.bashrc`); en cualquier otro caso, todo el texto.
    """
    if es_archivo:
        punto = inicial.rfind(".")
        if punto > 0:
            return punto
    return len(inicial)


def pedir_nombre(parent, titulo: str, inicial: str, validar: Callable[[str], str | None],
                 es_archivo: bool = False) -> str | None:
    """Pide un nombre con un diálogo del tema de un solo campo y devuelve lo escrito.

    «Aceptar» está apagado mientras `validar` dé un motivo, y ese motivo sale
    bajo el campo. Con el inicial vacío (una carpeta nueva) no se dice nada hasta
    que se escribe algo. Intro acepta si se puede (con el foco en un botón, lo
    pulsa); Escape y la X cancelan. Es de módulo para que los tests de la ventana
    lo sustituyan. Los widgets quedan en el diálogo (`entrada`, `motivo`,
    `aceptar`, `cancelar`) para que los tests los manejen.

    Args:
        parent: La ventana de la que cuelga; puede ser la raíz oculta.
        titulo: Lo que dice la barra de la ventana y su primera línea.
        inicial: El texto con el que se abre el campo.
        validar: Da el motivo por el que un texto no vale, o `None` si vale.
        es_archivo: Si el nombre es el de un archivo, la selección inicial deja
            fuera la extensión.

    Returns:
        El texto tal como se escribió, sin recortar, o `None` si se canceló.
    """
    import tkinter as tk
    from tkinter import ttk

    dlg = modal(parent, titulo, suelto=_suelto(parent))
    respuesta: dict[str, str | None] = {"v": None}
    marco = cuerpo_visible(dlg, padding=(theme.E5, theme.E5, theme.E5, theme.E4))
    marco.columnconfigure(0, weight=1)
    ttk.Label(marco, text=titulo, style="Dialogo.TLabel").grid(row=0, column=0, sticky="w")
    texto = tk.StringVar(master=dlg, value=inicial)
    entrada = ttk.Entry(marco, textvariable=texto, width=ANCHO_CAMPO)
    entrada.grid(row=1, column=0, sticky="ew", pady=(theme.E3, 0))
    motivo = ttk.Label(marco, text="", style="Pista.TLabel",
                       wraplength=theme.medida(ANCHO_MOTIVO), justify="left")
    motivo.grid(row=2, column=0, sticky="w", pady=(theme.E2, 0))
    ttk.Separator(marco, orient="horizontal").grid(row=3, column=0, sticky="ew",
                                                   pady=(theme.E4, 0))
    pie = ttk.Frame(marco)
    pie.grid(row=4, column=0, sticky="e", pady=(theme.E4, 0))

    def cancelar(_evento=None):
        """Cierra sin respuesta."""
        respuesta["v"] = None
        dlg.destroy()

    def aceptar(_evento=None):
        """Da lo escrito y cierra, si vale."""
        if validar(texto.get()) is None:
            respuesta["v"] = texto.get()
            dlg.destroy()

    boton_cancelar = ttk.Button(pie, text="Cancelar", command=cancelar)
    boton_cancelar.grid(row=0, column=0, padx=(0, theme.E2))
    boton_aceptar = ttk.Button(pie, text="Aceptar", style="Primary.TButton", command=aceptar)
    boton_aceptar.grid(row=0, column=1)

    tocado = {"v": False}

    def revisar(*_args) -> None:
        """Pone el motivo y enciende o apaga «Aceptar» según lo escrito."""
        escrito = texto.get()
        razon = validar(escrito)
        if escrito or tocado["v"]:
            motivo.configure(text=razon or "")
        boton_aceptar.state(["disabled"] if razon is not None else ["!disabled"])

    def cambio(*_args) -> None:
        """Anota que se ha escrito algo y revisa."""
        tocado["v"] = True
        revisar()

    revisar()
    texto.trace_add("write", cambio)

    def intro(evento):
        """Pulsa el botón con el foco; con el foco en el campo, acepta."""
        if evento.widget.winfo_class() in ("TButton", "Button"):
            evento.widget.invoke()
        else:
            aceptar()

    dlg.bind("<Return>", intro)
    dlg.bind("<KP_Enter>", intro)
    dlg.bind("<Escape>", cancelar)
    dlg.entrada, dlg.motivo = entrada, motivo
    dlg.aceptar, dlg.cancelar = boton_aceptar, boton_cancelar
    entrada.focus_set()
    entrada.selection_range(0, _fin_de_seleccion(inicial, es_archivo))
    entrada.icursor("end")
    # En Windows, al mapearse la ventana el foco se va a la propia ventana y se pierde
    # el del campo: se vuelve a poner cuando ya está a la vista, para escribir sin clic.
    dlg.after_idle(entrada.focus_set)
    mostrar(dlg, parent)
    return respuesta["v"]


class Barra:
    """La barra de gestión del explorador: «Nueva carpeta…», «Renombrar…», «Cortar» y «Borrar…».

    `marco` lo coloca con `grid` quien la usa. Los botones nacen apagados:
    `encender()` los enciende según lo que se pueda hacer con lo elegido.

    Args:
        padre: El contenedor del que cuelga `marco`.
        acciones: Qué hace cada botón, por `"nueva"`, `"renombrar"`, `"cortar"` y
            `"borrar"`; se consulta al pulsar.

    Attributes:
        marco: El marco con los botones.
        nueva, renombrar, cortar, borrar: Los botones.
    """

    def __init__(self, padre, acciones: dict[str, Callable[[], None]]) -> None:
        from tkinter import ttk

        self.marco = ttk.Frame(padre)
        for columna, clave in enumerate(ORDEN_BARRA):
            boton = ttk.Button(self.marco, text=ROTULOS[clave], style="Quiet.TButton",
                               command=lambda k=clave: acciones[k]())
            boton.grid(row=0, column=columna, padx=(0 if columna == 0 else theme.E2, 0))
            boton.state(["disabled"])
            setattr(self, clave, boton)

    def encender(self, nueva: bool, renombrar: bool, cortar: bool, borrar: bool) -> None:
        """Enciende los botones que se dicen y apaga los demás."""
        for clave, encendido in zip(ORDEN_BARRA, (nueva, renombrar, cortar, borrar)):
            getattr(self, clave).state(["!disabled" if encendido else "disabled"])


ANCHO_CORTE = 380
"""Ancho (px del diseño) donde se corta el texto de la línea de lo cortado."""


def linea_corte(padre, al_pegar: Callable[[], None], al_cancelar: Callable[[], None]):
    """Devuelve la línea de lo cortado: su texto y los botones «Pegar aquí» y «Cancelar».

    Es un `ttk.Frame` sin colocar (lo hace quien la usa con `grid`) cuyas partes quedan en
    atributos para que la ventana las ponga y los tests las manejen: `texto` (la
    etiqueta), `pegar` y `cancelar` (los botones).

    Args:
        padre: El contenedor del que cuelga.
        al_pegar: Lo que hace «Pegar aquí»; se consulta al pulsar.
        al_cancelar: Lo que hace «Cancelar».
    """
    from tkinter import ttk

    marco = ttk.Frame(padre)
    marco.columnconfigure(0, weight=1)
    marco.texto = ttk.Label(marco, text="", style="Pista.TLabel",
                            wraplength=theme.medida(ANCHO_CORTE), justify="left")
    marco.texto.grid(row=0, column=0, sticky="w")
    marco.pegar = ttk.Button(marco, text=ROTULOS["pegar"], style="Quiet.TButton",
                             command=lambda: al_pegar())
    marco.pegar.grid(row=0, column=1, sticky="e", padx=(theme.E3, 0))
    marco.cancelar = ttk.Button(marco, text="Cancelar", style="Quiet.TButton",
                                command=lambda: al_cancelar())
    marco.cancelar.grid(row=0, column=2, sticky="e", padx=(theme.E2, 0))
    return marco


def menu_contextual(padre, acciones: dict[str, Callable[[], None]],
                    estados: dict[str, bool]) -> "tk.Menu":
    """Devuelve el menú del botón derecho, listo para que la ventana lo enseñe.

    Args:
        padre: El widget del que cuelga.
        acciones: Qué hace cada entrada, por `"nueva"`, `"renombrar"`, `"cortar"`,
            `"pegar"` y `"borrar"`; se consulta al elegirla.
        estados: Si cada entrada está encendida, por las mismas claves.

    Returns:
        Un `tk.Menu` sin asa con las cinco entradas; las de estado falso, apagadas.
    """
    import tkinter as tk

    menu = tk.Menu(padre, tearoff=0, background=theme.SUPERFICIE, foreground=theme.TINTA,
                   activebackground=theme.ACENTO_SUAVE, activeforeground=theme.TINTA,
                   disabledforeground=theme.APAGADO, font=theme.fuente(), borderwidth=0)
    for clave in ORDEN_MENU:
        menu.add_command(label=ROTULOS[clave], command=lambda k=clave: acciones[k](),
                         state="normal" if estados.get(clave) else "disabled")
    return menu
