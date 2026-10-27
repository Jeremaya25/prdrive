"""El panel de progreso de «Servidor…» y el aviso de choques; solo dibujan.

Qué se copia, cuánto va y cómo acabó lo decide `ui/transferencia.py` (sin Tk);
esta ventana pone los textos que le dan en sus etiquetas y avisa de los botones
con dos atributos que pone quien la usa (`ui/tk_servidor.py`). Nada de aquí lee
disco ni red.
"""

from __future__ import annotations

from collections.abc import Callable

from . import theme, transferencia
from .tk import _arrancar_barra, _suelto, bloque_aviso, cuerpo_visible, modal, mostrar

TITULO_CHOQUES = "Ya existen"
"""Título del aviso de choques."""
CANCELANDO = "Cancelando…"
"""Lo que dice el panel desde que se pide cancelar hasta que rclone para."""
ANCHO_TEXTO = 440
"""Ancho (px del diseño) donde se cortan los textos del aviso de choques."""
ANCHO_RESULTADO = 520
"""Ancho (px del diseño) del aviso con el resultado."""


class Panel:
    """El panel al pie del explorador: progreso de un lote, su resultado y sus botones.

    `marco` lo coloca con `grid` quien lo usa. Sin nada que enseñar el marco no
    tiene hijos a la vista, así que no ocupa sitio; `ocultar()` además lo quita
    de la rejilla y cualquier `mostrar_*` lo devuelve a ella.

    Args:
        padre: El contenedor del que cuelga `marco`.

    Attributes:
        al_cancelar: Se llama, sin argumentos, al pulsar «Cancelar».
        al_reintentar: Se llama, sin argumentos, al pulsar «Reintentar».
        titulo, archivo, cuenta, ritmo: Las etiquetas de texto del progreso.
        barra: La `ttk.Progressbar`.
        cancelar: El botón «Cancelar».
        resultado: El marco donde sale el aviso de cómo acabó.
        reintentar: El botón «Reintentar».
    """

    def __init__(self, padre) -> None:
        from tkinter import ttk

        self.al_cancelar: Callable[[], None] | None = None
        self.al_reintentar: Callable[[], None] | None = None
        self._girando = False
        self.marco = ttk.Frame(padre)
        self.marco.columnconfigure(0, weight=1)
        self.titulo = ttk.Label(self.marco, text="", style="Fuerte.TLabel")
        self.archivo = ttk.Label(self.marco, text="", style="Pista.TLabel")
        self.cuenta = ttk.Label(self.marco, text="", style="Pista.TLabel")
        self.barra = ttk.Progressbar(self.marco, mode="determinate", maximum=100)
        self.ritmo = ttk.Label(self.marco, text="", style="Pista.TLabel")
        self.cancelar = ttk.Button(self.marco, text="Cancelar", command=self._cancelar)
        self.resultado = ttk.Frame(self.marco)
        self.resultado.columnconfigure(0, weight=1)
        self.reintentar = ttk.Button(self.marco, text="Reintentar", command=self._reintentar)
        self._progreso = (
            (self.titulo, dict(row=0, column=0, sticky="w", pady=(theme.E3, 0))),
            (self.archivo, dict(row=1, column=0, sticky="w")),
            (self.cuenta, dict(row=2, column=0, sticky="w")),
            (self.barra, dict(row=3, column=0, sticky="ew", pady=(theme.E2, 0))),
            (self.ritmo, dict(row=4, column=0, sticky="w")),
            (self.cancelar, dict(row=0, column=1, rowspan=5, sticky="e", padx=(theme.E4, 0))),
        )
        self._quitar_todo()

    # -- lo que se ve --------------------------------------------------------

    def _quitar_todo(self) -> None:
        """Esconde el progreso, el resultado y «Reintentar»."""
        self._parar_barra()
        for w, _opciones in self._progreso:
            w.grid_remove()
        self.resultado.grid_remove()
        self.reintentar.grid_remove()

    def _parar_barra(self) -> None:
        """Detiene la barra si iba y venía."""
        if self._girando:
            self.barra.stop()
            self._girando = False

    def _poner(self, *widgets) -> None:
        """Pone en la rejilla, con su sitio de siempre, los widgets del progreso que se dicen."""
        for w, opciones in self._progreso:
            if w in widgets:
                w.grid(**opciones)

    def _enseñar(self) -> None:
        """Devuelve `marco` a su sitio si `ocultar()` lo quitó."""
        self.marco.grid()

    def _cancelar(self) -> None:
        """Avisa de que se pulsó «Cancelar»."""
        if self.al_cancelar is not None:
            self.al_cancelar()

    def _reintentar(self) -> None:
        """Avisa de que se pulsó «Reintentar»."""
        if self.al_reintentar is not None:
            self.al_reintentar()

    # -- lo que se dice ------------------------------------------------------

    def mostrar_progreso(self, p: transferencia.Progreso) -> None:
        """Enseña cómo va el lote.

        Args:
            p: Los textos y la fracción; `fraccion` `None` pone la barra a ir y venir.
        """
        self._enseñar()
        self._quitar_todo_menos_progreso()
        self.titulo.configure(text=p.titulo)
        self.archivo.configure(text=p.archivo)
        self.cuenta.configure(text=p.cuenta)
        self.ritmo.configure(text=p.ritmo)
        self.cancelar.configure(state="normal")
        if p.fraccion is None:
            if not self._girando:
                self.barra.configure(mode="indeterminate")
                _arrancar_barra(self.barra)
                self._girando = True
        else:
            self._parar_barra()
            self.barra.configure(mode="determinate", value=max(0.0, min(1.0, p.fraccion)) * 100)

    def _quitar_todo_menos_progreso(self) -> None:
        """Deja a la vista solo el progreso (quita el resultado y «Reintentar»)."""
        self.resultado.grid_remove()
        self.reintentar.grid_remove()
        self._poner(self.titulo, self.archivo, self.cuenta, self.barra, self.ritmo, self.cancelar)

    def mostrar_cancelando(self) -> None:
        """Dice «Cancelando…» y deja «Cancelar» sin efecto hasta el siguiente progreso."""
        self._enseñar()
        self._quitar_todo_menos_progreso()
        self.archivo.configure(text=CANCELANDO)
        self.cancelar.configure(state="disabled")

    def mostrar_resultado(self, r: transferencia.Resultado) -> None:
        """Esconde el progreso y enseña cómo acabó el lote.

        Args:
            r: El texto, su tono (`"ok"` o `"aviso"`) y si se ofrece «Reintentar».
        """
        self._enseñar()
        self._quitar_todo()
        for hijo in self.resultado.winfo_children():
            hijo.destroy()
        caja = bloque_aviso(self.resultado, r.texto, ancho=ANCHO_RESULTADO,
                            tono="Verde." if r.tono == "ok" else "Ambar.")
        caja.grid(row=0, column=0, sticky="ew")
        self.resultado.grid(row=0, column=0, sticky="ew", pady=(theme.E3, 0))
        if r.reintentar:
            self.reintentar.grid(row=0, column=1, sticky="e", padx=(theme.E4, 0),
                                 pady=(theme.E3, 0))

    def ocultar(self) -> None:
        """Quita el panel entero de la rejilla."""
        self._quitar_todo()
        self.marco.grid_remove()


def preguntar_choques(parent, texto: str) -> str | None:
    """Pregunta qué hacer con lo que ya existe en el destino y devuelve la respuesta.

    Un diálogo del tema con «Sobrescribir», «Omitir» y «Cancelar». El foco al
    abrir está en «Cancelar»: Intro no sobrescribe nada por descuido. Escape y la
    X cancelan. Es de módulo para que los tests de la ventana lo sustituyan.

    Args:
        parent: La ventana de la que cuelga.
        texto: La pregunta, ya escrita (`N elementos ya existen en …`).

    Returns:
        `"sobrescribir"`, `"omitir"` o `None` (cancelar).
    """
    from tkinter import ttk

    dlg = modal(parent, TITULO_CHOQUES, suelto=_suelto(parent))
    respuesta: dict[str, str | None] = {"v": None}
    marco = cuerpo_visible(dlg, padding=(theme.E5, theme.E5, theme.E5, theme.E4))
    marco.columnconfigure(0, weight=1)
    ttk.Label(marco, text=TITULO_CHOQUES, style="Dialogo.TLabel").grid(row=0, column=0, sticky="w")
    ttk.Label(marco, text=texto, wraplength=theme.medida(ANCHO_TEXTO), justify="left").grid(
        row=1, column=0, sticky="w", pady=(theme.E3, 0))
    ttk.Separator(marco, orient="horizontal").grid(row=2, column=0, sticky="ew",
                                                   pady=(theme.E4, 0))
    pie = ttk.Frame(marco)
    pie.grid(row=3, column=0, sticky="e", pady=(theme.E4, 0))

    def elegir(valor: str | None):
        """Devuelve un mando que guarda la respuesta y cierra."""
        def mando():
            respuesta["v"] = valor
            dlg.destroy()
        return mando

    ttk.Button(pie, text="Sobrescribir", command=elegir("sobrescribir")).grid(
        row=0, column=0, padx=(0, theme.E2))
    ttk.Button(pie, text="Omitir", command=elegir("omitir")).grid(
        row=0, column=1, padx=(0, theme.E2))
    cancelar = ttk.Button(pie, text="Cancelar", style="Primary.TButton", command=elegir(None))
    cancelar.grid(row=0, column=2)

    def intro(evento):
        """Pulsa el botón con el foco; con el foco en otro sitio, cancela."""
        if evento.widget.winfo_class() in ("TButton", "Button"):
            evento.widget.invoke()
        else:
            elegir(None)()

    dlg.bind("<Return>", intro)
    dlg.bind("<KP_Enter>", intro)
    dlg.bind("<Escape>", lambda _e: elegir(None)())
    cancelar.focus_set()
    mostrar(dlg, parent)
    return respuesta["v"]
