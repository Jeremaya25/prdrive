"""La lista de parejas con filas ligeras: una de las tres que mide la etapa 2 (R3).

TEMPORAL, como todo `etapa2_*`: lo borra la tarea 15 de la etapa 2.

Tiene la API de `ui.tk_pairs.ListaParejas` (`poner`, `elegir`, `fila`, `filas`,
`orden`, `elegida`) con menos widgets por fila: cinco, contra los siete de la
lista de hoy (el fondo, la casilla, el nombre, la ruta, los dos chips y el
separador). La casilla va dentro de la etiqueta del nombre (`compound="left"`),
y las líneas entre filas no son separadores: las filas caen en un marco del
color de la línea y el fondo de cada una deja un píxel al descubierto. Se
diferencia por nombre (una fila que sigue ahí conserva sus widgets y solo se
toca lo que cambió) y elegir otra fila restila dos filas, no todas.

No es una pantalla: solo dibuja lo mismo con otro reparto de widgets, y esa es
toda la medida. Pierde de la lista de hoy el hueco exacto entre la casilla y el
nombre y la lista vacía («No hay ninguna pareja.»), que aquí no se mide. Y los
chips quedan sobre el marco del color de la línea, una superficie que el tema no
tiene: `theme` lo avisa una vez por la salida de error y las esquinas de las
píldoras se asientan sobre la superficie más cercana.
"""

from __future__ import annotations

from functools import partial

from ui import icons, pair_editor, theme
from ui.tk_pairs import ICONO_MODO, TONOS_FILA

ESTILO_LINEA = "Linea.TFrame"
"""El estilo del marco de la lista: su fondo es el color de las líneas entre filas."""


def preparar(raiz) -> None:
    """Crea `ESTILO_LINEA`; hay que llamarla justo después de `theme.apply()`.

    Es la única excepción a «ningún estilo después del primer widget» y solo la
    puede hacer una medición: en la aplicación iría dentro de `theme.apply()`.
    """
    from tkinter import ttk
    ttk.Style(raiz).configure(ESTILO_LINEA, background=theme.LINEA, relief="flat",
                              borderwidth=0)


class ListaLigera:
    """La lista de parejas con cinco widgets por fila.

    Args:
        parent: Dónde va.
        puede_dejar: Se pregunta antes de cambiar de fila; si dice que no, la
            elección no se hace.
        al_elegir: Lo que se llama después de elegir otra.
    """

    COLUMNAS = 4

    def __init__(self, parent, puede_dejar, al_elegir):
        from tkinter import ttk
        self.puede_dejar, self.al_elegir = puede_dejar, al_elegir
        self.marco = ttk.Frame(parent, style=ESTILO_LINEA, takefocus=True,
                               padding=icons.px(parent, 1))
        self.marco.columnconfigure(1, weight=1)
        self.filas: dict[str, dict] = {}
        self.orden: list[str] = []
        self.elegida: str | None = None
        cabeza = ttk.Frame(self.marco, style="Plano.TFrame")
        cabeza.grid(row=0, column=0, columnspan=self.COLUMNAS, sticky="nsew",
                    pady=(0, icons.px(parent, 1)))
        cabeza.lower()
        self.cabecera = [cabeza]
        for col, texto in enumerate(("Pareja", "Local ↔ remoto", "Modo", "Estado")):
            rotulo = ttk.Label(self.marco, text=theme.rotulo(texto), style="Rotulo.TLabel")
            rotulo.grid(row=0, column=col, sticky="w", padx=self._lados(col),
                        pady=theme.E1)
            self.cabecera.append(rotulo)
        self.marco.rowconfigure(0, minsize=icons.px(self.marco, 28))
        self.marco.bind("<Up>", lambda _e: self._mover(-1))
        self.marco.bind("<Down>", lambda _e: self._mover(1))

    @staticmethod
    def _lados(col: int):
        """El hueco a los lados de una celda: el de la rejilla y el borde de la fila."""
        return (theme.E3 if col == 0 else theme.E2,
                theme.E3 if col == ListaLigera.COLUMNAS - 1 else 0)

    @staticmethod
    def _datos(fila, del_catalogo: bool) -> dict:
        """Lo que se ve de una fila: lo que la distingue de otra con el mismo nombre."""
        tono, nota = pair_editor.row_status(fila, del_catalogo)
        sup, tipo = TONOS_FILA[tono]
        if del_catalogo:
            tipo = "Ok."
        return {"fila": fila, "sup": sup, "apagada": tono == "apagado", "nota": nota,
                "tipo": tipo, "espejo": fila.mode in pair_editor.MIRROR_MODES,
                "ruta": f"{fila.local} ↔ {fila.remote}"}

    def _chip_modo(self, d: dict):
        return theme.chip(self.marco, d["fila"].mode, "Peligro." if d["espejo"] else "",
                          ICONO_MODO.get(d["fila"].mode))

    def _chip_estado(self, d: dict):
        return theme.chip(self.marco, d["nota"], d["tipo"])

    def _casilla(self, d: dict):
        return icons.casilla(self.marco, "marcada" if d["fila"].en_pen else "vacia")

    def poner(self, filas, del_catalogo: bool = False) -> None:
        """Pone estas filas (`pair_editor.CatalogRow`): toca solo las que cambian."""
        nuevas = [self._datos(f, del_catalogo) for f in filas]
        nombres = {d["fila"].name for d in nuevas}
        for name in [n for n in self.filas if n not in nombres]:
            f = self.filas.pop(name)
            for w in (f["fondo"], f["nombre"], f["ruta_w"], f["modo"], f["estado"]):
                w.destroy()
        self.orden = []
        for i, d in enumerate(nuevas):
            name = d["fila"].name
            fila_tk = i + 1
            f = self.filas.get(name)
            if f is None:
                f = self.filas[name] = self._crear(d)
                self._colocar(f, fila_tk)
            else:
                self._actualizar(f, d)
                if f["fila_tk"] != fila_tk:
                    self._colocar(f, fila_tk)
            self.orden.append(name)
        if self.elegida not in self.filas:
            self.elegida = None

    def _estilos(self, d: dict, elegida: bool) -> tuple[str, str, str]:
        """Los estilos del fondo, el nombre y la ruta de una fila, según su superficie."""
        sup = "NotaAzul." if elegida else d["sup"]
        return (f"Plano.{sup}TFrame",
                f"{sup}Pista.TLabel" if d["apagada"] else f"{sup}Fuerte.TLabel",
                f"{sup}MonoPista.TLabel" if d["apagada"] else f"{sup}Mono.TLabel")

    def _crear(self, d: dict) -> dict:
        """Crea los cinco widgets de una fila nueva, ya con su superficie."""
        from tkinter import ttk
        estilo_fondo, estilo_nombre, estilo_ruta = self._estilos(
            d, d["fila"].name == self.elegida)
        img = self._casilla(d)
        fondo = ttk.Frame(self.marco, style=estilo_fondo)
        nombre = ttk.Label(self.marco, text=d["fila"].name, style=estilo_nombre,
                           compound="left", image=img)
        nombre.image = img                  # Tk no se queda con la referencia
        ruta = ttk.Label(self.marco, text=d["ruta"], style=estilo_ruta)
        f = {"fondo": fondo, "nombre": nombre, "ruta_w": ruta,
             "modo": self._chip_modo(d), "estado": self._chip_estado(d), **d}
        for w in (fondo, nombre, ruta, f["modo"], f["estado"]):
            w.bind("<Button-1>", partial(self._clic, d["fila"].name))
        return f

    def _colocar(self, f: dict, fila_tk: int) -> None:
        """Pone los cinco widgets de una fila en su fila de la rejilla."""
        f["fila_tk"] = fila_tk
        f["fondo"].grid(row=fila_tk, column=0, columnspan=self.COLUMNAS, sticky="nsew",
                        pady=(0, icons.px(self.marco, 1)))
        f["fondo"].lower()
        for col, w in enumerate((f["nombre"], f["ruta_w"], f["modo"], f["estado"])):
            w.grid(row=fila_tk, column=col, sticky="w", padx=self._lados(col),
                   pady=(theme.E2, theme.E2))
        self.marco.rowconfigure(fila_tk, minsize=icons.px(self.marco, 36))

    def _actualizar(self, f: dict, d: dict) -> None:
        """Pone a una fila que sigue ahí solo lo que ha cambiado."""
        name = d["fila"].name
        if d["fila"].en_pen != f["fila"].en_pen:
            img = self._casilla(d)
            f["nombre"].configure(image=img)
            f["nombre"].image = img
        if d["ruta"] != f["ruta"]:
            f["ruta_w"].configure(text=d["ruta"])
        if (d["fila"].mode, d["espejo"]) != (f["fila"].mode, f["espejo"]):
            f["modo"].destroy()
            f["modo"] = self._chip_modo(d)
            f["modo"].grid(row=f["fila_tk"], column=2, sticky="w", padx=self._lados(2),
                           pady=(theme.E2, theme.E2))
            f["modo"].bind("<Button-1>", partial(self._clic, name))
        if (d["nota"], d["tipo"]) != (f["nota"], f["tipo"]):
            f["estado"].destroy()
            f["estado"] = self._chip_estado(d)
            f["estado"].grid(row=f["fila_tk"], column=3, sticky="w", padx=self._lados(3),
                             pady=(theme.E2, theme.E2))
            f["estado"].bind("<Button-1>", partial(self._clic, name))
        cambia_superficie = (d["sup"], d["apagada"]) != (f["sup"], f["apagada"])
        f.update(d)
        if cambia_superficie:
            self._pintar_fila(name)

    def _pintar_fila(self, name: str) -> None:
        """Pone a una fila su superficie; la elegida, la del acento."""
        f = self.filas[name]
        fondo, nombre, ruta = self._estilos(f, name == self.elegida)
        f["fondo"].configure(style=fondo)
        f["nombre"].configure(style=nombre)
        f["ruta_w"].configure(style=ruta)

    def _clic(self, name: str, _evento=None) -> None:
        """Elige la fila pulsada y le da el foco a la lista, para las flechas."""
        self.marco.focus_set()
        self.elegir(name)

    def _mover(self, paso: int) -> str:
        """Elige la fila de arriba o la de abajo."""
        if self.orden:
            i = self.orden.index(self.elegida) + paso if self.elegida in self.orden else 0
            self.elegir(self.orden[max(0, min(len(self.orden) - 1, i))])
        return "break"

    def elegir(self, name: str | None, avisar: bool = True) -> bool:
        """Elige esa pareja (o ninguna) y lo cuenta, si `avisar`; restila solo dos filas.

        Returns:
            Si la elección se ha hecho: `puede_dejar` puede negarse.
        """
        if name is not None and name not in self.filas:
            name = None
        if name == self.elegida:
            return True
        if avisar and not self.puede_dejar():
            return False
        antes, self.elegida = self.elegida, name
        for x in (antes, name):
            if x in self.filas:
                self._pintar_fila(x)
        if avisar:
            self.al_elegir()
        return True

    def fila(self):
        """Devuelve la `CatalogRow` elegida, o `None`."""
        return self.filas[self.elegida]["fila"] if self.elegida in self.filas else None

    def leer(self) -> list[tuple[str, str, str, str]]:
        """Devuelve lo que dicen las etiquetas, fila a fila: nombre, ruta, modo y estado."""
        return [tuple(str(self.filas[n][w].cget("text"))
                      for w in ("nombre", "ruta_w", "modo", "estado")) for n in self.orden]

    def detalle(self) -> dict:
        """Cuentas propias de esta lista, para el informe."""
        return {}
