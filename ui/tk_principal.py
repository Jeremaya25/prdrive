#!/usr/bin/env python3
"""La ventana principal dibujada una vez y cambiada en su sitio.

`VistaPrincipal` dibuja lo que dice un `principal.Estado` y, cuando le llega
otro, cambia solo lo que difiere: un bloque cuyo trozo del estado es igual no se
toca, uno que aparece se crea la primera vez que hace falta y después solo se
enseña o se esconde (`grid`/`grid_remove`), y las filas de las parejas se
emparejan por nombre. Aquí no se decide nada: qué se ve y qué se puede pulsar lo
dice `principal.controles()`, y lo que hace cada botón, las `Acciones` que le da
la ventana principal (`ui.tk.main_window`).

Se carga antes del primer pintado, así que sigue la regla de `ui/principal.py`:
arriba no importa nada que lea el dispositivo (ni `ui.watch` ni
`ui.llavero_editor` ni lo de `common/` que va con ellos), y tkinter solo dentro
de las funciones.
"""

from __future__ import annotations

from typing import Callable, NamedTuple

from . import principal, theme
from .tk import bloque_aviso, separador_fila

FILAS = {"cabecera": 0, "aviso": 1, "reparacion": 2, "version": 3, "componentes": 4,
         "rotulo": 5, "tarjeta": 6, "llavero": 7, "pantallas": 8, "arranque": 9,
         "pausa": 10, "pie": 11}
"""La fila de la rejilla de cada bloque, siempre la misma.

Un bloque escondido deja su fila vacía, y una fila sin nada no ocupa sitio: la
ventana queda igual que si las filas se numeraran seguidas.
"""

CHIP_RESERVADO = ("al día", "Ok.", "ok")
"""El chip de la cabecera que mide el hueco que se le reserva.

Es el de un dispositivo sin nada que revisar (`principal.estado`). Mientras llega
la lectura la cabecera lleva una píldora «…», más estrecha: con el hueco
reservado, la cabecera no cambia de ancho cuando llega «al día».
"""

HOLGURA_MARCAR = 10  # píxeles
"""Lo que se reserva de más a «Marcar todas», como siempre se hizo."""


class Acciones(NamedTuple):
    """Lo que hace cada control de la ventana principal.

    Args:
        sincronizar: «Sincronizar ahora».
        servicio: El botón del servicio; recibe la acción que enseña
            (`principal.INICIAR`, o la del agente: pausar, reanudar, seguir).
        parejas: «Parejas…».
        ajustes: «Ajustes…».
        reparacion: «Reparación…», el botón de la línea de cosas que revisar.
        llavero: «Abrir llavero».
        expulsar: «Expulsar».
        bloquear: «Bloquear».
        arranque: El botón de la línea del arranque automático.
        descartar: «Descartar», el del aviso de arranque.
        actualizar: «Actualizar…» del aviso de versión nueva.
        componentes: «Actualizar…» del aviso de componentes.
        al_marcar: Lo que hace una casilla al tocarla.
        marcar_todas: «Marcar todas» / «Desmarcar todas».
    """
    sincronizar: Callable[[], None]
    servicio: Callable[[str], None]
    parejas: Callable[[], None]
    ajustes: Callable[[], None]
    reparacion: Callable[[], None]
    llavero: Callable[[], None]
    expulsar: Callable[[], None]
    bloquear: Callable[[], None]
    arranque: Callable[[], None]
    descartar: Callable[[], None]
    actualizar: Callable[[], None]
    componentes: Callable[[], None]
    al_marcar: Callable[[], None]
    marcar_todas: Callable[[], None]


def a_la_vista(widget) -> bool:
    """Indica si el widget y todo lo que lo contiene hasta su ventana están colocados.

    Un widget quitado con `grid_remove`, o que cuelga de uno quitado, no lo está.
    """
    try:
        ventana = str(widget.winfo_toplevel())
        actual = widget
        while str(actual) != ventana:
            if not actual.winfo_manager():
                return False
            actual = actual.master
    except Exception:                                    # noqa: BLE001 — ya no existe
        return False
    return True


class VistaPrincipal:
    """Los widgets de la ventana principal, que se cambian en su sitio.

    Lo fijo (la cabecera, el rótulo y la tarjeta de las parejas, «Parejas…» y
    «Ajustes…», el pie) se crea al construirla. Cada bloque que solo sale a
    veces (el aviso de arranque, la línea de «Reparación…», los avisos de versión
    y de componentes, la línea del llavero, la del arranque automático y su
    frase, «Expulsar» o «Bloquear», «Marcar todas») se crea la primera vez que un
    `Estado` lo pide, y luego solo se enseña o se esconde.

    Args:
        marco: Donde se dibuja (el `cuerpo_visible` de la ventana), con su
            columna 0 estirándose.
        acciones: Lo que hace cada control.

    Attributes:
        casillas: La variable de la casilla de cada pareja, por nombre.
        filas: Los widgets de cada fila, por nombre: `casilla`, `modo`,
            `cuando`, `chip` (o `None`), `dato` (la `Fila` que pinta) y
            `linea` (su fila de la rejilla).
    """

    def __init__(self, marco, acciones: Acciones) -> None:
        """Construye lo fijo; lo demás espera al primer `aplicar()`."""
        from tkinter import ttk

        self.marco = marco
        self._acciones = acciones
        self._e: principal.Estado | None = None
        self.casillas: dict = {}
        self.filas: dict[str, dict] = {}
        self._orden: list[str] = []
        self._separadores: list = []
        self._bloques: dict = {}
        self._chip = None

        # Quién es este dispositivo y cómo está.
        arriba = ttk.Frame(marco)
        arriba.grid(row=FILAS["cabecera"], column=0, sticky="ew")
        arriba.columnconfigure(0, weight=1)
        titulo = ttk.Frame(arriba)
        titulo.grid(row=0, column=0, sticky="w")
        ttk.Label(titulo, text="Sincronizar", style="Titulo.TLabel").grid(
            row=0, column=0, sticky="w")
        extremos = ttk.Frame(titulo)
        extremos.grid(row=1, column=0, sticky="w", pady=(theme.E2, 0))
        self._extremos = []
        for col, icono in enumerate(("dispositivo", "nas")):
            if col:
                ttk.Label(extremos, text="·", style="Apagado.TLabel").grid(
                    row=0, column=2, padx=theme.E2)
            marca = theme.etiqueta_icono(extremos, icono, theme.TINTA3, "mono_pequena", 14)
            marca.grid(row=0, column=col * 3, sticky="w")
            texto = ttk.Label(extremos, style="MonoPista.TLabel")
            texto.grid(row=0, column=col * 3 + 1, sticky="w", padx=(theme.E1, 0))
            self._extremos.append(texto)
        self._arriba = arriba
        # Un chip de «al día», hecho solo para medirlo: su ancho es el hueco que
        # se le reserva a la columna (ttk calcula lo que pide un widget al
        # configurarlo, sin esperar a que se pinte). Su imagen se queda en la
        # caché de iconos para cuando haga falta de verdad.
        medida = theme.chip(arriba, *CHIP_RESERVADO)
        arriba.columnconfigure(1, minsize=medida.winfo_reqwidth())
        medida.destroy()

        # El rótulo de la lista, con el «N de M» a la derecha.
        rotulo = ttk.Frame(marco)
        rotulo.grid(row=FILAS["rotulo"], column=0, sticky="ew", pady=(theme.E5, theme.E2))
        rotulo.columnconfigure(2, weight=1)
        ttk.Label(rotulo, text=theme.rotulo("Parejas"), style="Rotulo.TLabel").grid(
            row=0, column=0, sticky="w")
        self._resumen = ttk.Label(rotulo, style="Pista.TLabel")
        self._resumen.grid(row=0, column=3, sticky="e")
        self._rotulo = rotulo
        self._todas = None
        self._ancho_todas = 0

        # La lista de parejas.
        self._tarjeta = ttk.Frame(marco, style="Card.TFrame", padding=(theme.E3, theme.E1))
        self._tarjeta.grid(row=FILAS["tarjeta"], column=0, sticky="ew")
        self._tarjeta.columnconfigure(2, weight=1)
        self._vacia = None

        # Las pantallas de las que se vuelve aquí.
        pantallas = ttk.Frame(marco)
        pantallas.grid(row=FILAS["pantallas"], column=0, sticky="ew", pady=(theme.E3, 0))
        pantallas.columnconfigure(1, weight=1)
        self._parejas = ttk.Button(pantallas, text="Parejas…", style="Quiet.TButton",
                                   command=acciones.parejas)
        theme.boton_icono(self._parejas, "parejas", theme.ACENTO, theme.PAPEL)
        self._parejas.grid(row=0, column=0, sticky="w")
        self._ajustes = ttk.Button(pantallas, text="Ajustes…", style="Quiet.TButton",
                                   command=acciones.ajustes)
        theme.boton_icono(self._ajustes, "gear", theme.ACENTO, theme.PAPEL)
        self._ajustes.grid(row=0, column=2, sticky="e")

        # La acción principal, en grande; sin filete encima: la separa el aire.
        pie = ttk.Frame(marco)
        pie.grid(row=FILAS["pie"], column=0, sticky="ew", pady=(theme.E5, 0))
        pie.columnconfigure(0, weight=1)
        self._sincronizar = ttk.Button(pie, text="Sincronizar ahora",
                                       style="Grande.Primary.TButton",
                                       command=acciones.sincronizar)
        theme.boton_icono(self._sincronizar, "sync", theme.SOBRE_ACENTO, theme.ACENTO, 16)
        self._sincronizar.grid(row=0, column=0, sticky="ew", padx=(0, theme.E2))
        self._servicio = ttk.Button(pie, style="Grande.TButton",
                                    command=self._pulsar_servicio)
        self._servicio.grid(row=0, column=1)
        self._pie = pie
        self._fijos = {"cabecera": arriba, "rotulo": rotulo, "tarjeta": self._tarjeta,
                       "pantallas": pantallas, "pie": pie}

    @property
    def estado(self) -> principal.Estado | None:
        """El último `Estado` aplicado, o `None` antes del primero."""
        return self._e

    def aplicar(self, e: principal.Estado) -> bool:
        """Deja la ventana como dice `e`, tocando solo lo que ha cambiado.

        Un `Estado` igual al último no toca nada. Si no, cada bloque se compara
        con su trozo del último y solo se cambia el que difiere; los botones
        que se apagan o se encienden se ponen al final, de `principal.controles()`.

        Returns:
            Si lo que pide la ventana puede haber cambiado de tamaño: un bloque
            que aparece, se va o cambia de texto, una fila que entra o sale. Un
            botón que solo se apaga o se enciende no lo cambia.
        """
        if e == self._e:
            return False
        antes, ctl = self._e, principal.controles(e)
        self._e = e
        tam = False
        for paso in (self._pintar_cabecera, self._pintar_aviso, self._pintar_reparacion,
                     self._pintar_version, self._pintar_componentes, self._pintar_lista,
                     self._pintar_llavero, self._pintar_arranque, self._pintar_pie):
            tam = paso(antes, e, ctl) or tam
        self._poner_activos(ctl)
        return tam

    def contar(self) -> None:
        """Pone el «N de M» y el texto de «Marcar todas» según las casillas.

        Lo llama la ventana con cada casilla que se toca (su `command`, no un
        `trace` de la variable: la orden de un widget se borra con él y la de un
        trace no, así que desde Tcl seguiría sujetando la ventana entera hasta
        cerrar el intérprete).
        """
        e = self._e
        if e is None:
            return
        marcadas = sum(1 for v in self.casillas.values() if v.get())
        total = len(e.filas)
        self._resumen.configure(text=principal.resumen_de_marcadas(marcadas, total, e.ultima))
        if self._todas is not None:
            self._todas.configure(text=principal.texto_de_marcar_todas(marcadas, total))

    def controles_tk(self) -> dict[str, tuple[bool, bool]]:
        """Devuelve, de cada control de `principal.controles()`, si se ve y si se puede pulsar.

        Lo lee de los widgets, no de lo que se le pidió: es lo que los tests
        comparan con la tabla. Un control que aún no existe es `(False, False)`.
        """
        pie = [b for b in (self._bloques.get("expulsar"), self._bloques.get("bloquear"))
               if b is not None]
        botones = {
            "sincronizar": self._sincronizar, "servicio": self._servicio,
            "parejas": self._parejas, "ajustes": self._ajustes,
            "reparacion": getattr(self._bloques.get("reparacion"), "boton", None),
            "llavero": getattr(self._bloques.get("llavero"), "boton", None),
            "pie": next((b for b in pie if a_la_vista(b)), pie[0] if pie else None),
            "componentes": getattr(self._bloques.get("componentes"), "boton", None),
            "version": getattr(self._bloques.get("version"), "boton", None),
            "descartar": getattr(self._bloques.get("aviso"), "boton", None),
            "arranque": getattr(self._bloques.get("arranque"), "boton", None),
            "marcar_todas": self._todas,
        }
        return {clave: ((a_la_vista(b), not b.instate(["disabled"])) if b is not None
                        else (False, False))
                for clave, b in botones.items()}

    # --- lo que hace la vista con sus propios botones -------------------------

    def _pulsar_servicio(self) -> None:
        """Pasa a la ventana la acción que el botón del servicio enseña ahora."""
        if self._e is not None:
            self._acciones.servicio(self._e.servicio[0])

    # --- piezas ---------------------------------------------------------------

    def _colocar(self, bloque, clave: str, **opciones) -> None:
        """Pone un bloque del marco en su fila, con lo que lleve de margen."""
        bloque.grid(row=FILAS[clave], column=0, **opciones)

    def _en_orden(self, bloque, clave: str) -> None:
        """Deja un bloque recién hecho en el orden del Tab: antes del siguiente que ya está.

        Tk recorre con el tabulador los hijos en su orden de apilado, que es el de
        creación; un bloque creado después que los de debajo se saltaría ese orden.
        """
        siguientes = [(FILAS[k], w) for k, w in {**self._fijos, **self._bloques}.items()
                      if k in FILAS and FILAS[k] > FILAS[clave] and w is not None
                      and w.master is bloque.master]
        if siguientes:
            bloque.lower(min(siguientes, key=lambda par: par[0])[1])

    def _nuevo_bloque(self, clave: str, bloque):
        """Guarda un bloque recién hecho del marco y lo pone en el orden del Tab."""
        anterior = self._bloques.get(clave)
        if anterior is not None:
            anterior.destroy()
        self._bloques[clave] = bloque
        self._en_orden(bloque, clave)
        return bloque

    def _esconder(self, clave: str) -> bool:
        """Esconde un bloque si está a la vista y devuelve si lo estaba."""
        bloque = self._bloques.get(clave)
        if bloque is None or not bloque.winfo_manager():
            return False
        bloque.grid_remove()
        return True

    @staticmethod
    def _activar(boton, activo: bool) -> None:
        """Enciende o apaga un botón si no lo está ya."""
        if boton is None:
            return
        quiere = "normal" if activo else "disabled"
        if str(boton.cget("state")) != quiere:
            boton.configure(state=quiere)

    # --- los bloques, de arriba abajo ----------------------------------------
    #
    # Cada uno recibe el `Estado` anterior (o `None`), el nuevo y la tabla de
    # controles, no hace nada si su trozo no ha cambiado y devuelve si ha podido
    # cambiar el tamaño.

    def _pintar_cabecera(self, antes, e, ctl) -> bool:
        """El dispositivo, los remotos y el chip de la cabecera."""
        if antes is not None and (antes.dispositivo, antes.remotos, antes.chip) == (
                e.dispositivo, e.remotos, e.chip):
            return False
        for etiqueta, texto in zip(self._extremos, (e.dispositivo, e.remotos)):
            if str(etiqueta.cget("text")) != texto:
                etiqueta.configure(text=texto)
        if antes is None or antes.chip != e.chip:
            # Se cambia la etiqueta entera: el texto, el tipo y el icono van juntos
            # (`theme.chip`), y la imagen ya está en la caché de iconos.
            if self._chip is not None:
                self._chip.destroy()
            self._chip = theme.chip(self._arriba, *e.chip)
            self._chip.grid(row=0, column=1, sticky="ne", pady=(theme.E1, 0))
        return True

    def _pintar_aviso(self, antes, e, ctl) -> bool:
        """El aviso de arranque, con su «Descartar»."""
        if antes is not None and antes.aviso == e.aviso:
            return False
        if not ctl["descartar"].visible:
            return self._esconder("aviso")
        caja = self._bloques.get("aviso")
        if caja is None or caja.texto != e.aviso:
            # Con botón para descartarlo: es el único aviso que no describe un
            # estado del dispositivo sino algo que acaba de pasar.
            caja = bloque_aviso(self.marco, e.aviso, ancho=400,
                                boton=("Descartar", self._acciones.descartar))
            caja.texto, caja.boton = e.aviso, caja.acciones.winfo_children()[0]
            self._nuevo_bloque("aviso", caja)
        self._colocar(caja, "aviso", sticky="ew", pady=(theme.E4, 0))
        return True

    def _pintar_reparacion(self, antes, e, ctl) -> bool:
        """La línea de cuántas cosas hay que revisar, con «Reparación…».

        Una línea y no un recuadro por cada cosa: lo que dicen y lo que se hace
        con ello está en «Reparación». Mientras sincroniza no se enseña: no se
        repara bajo los pies de rclone.
        """
        if antes is not None and (antes.reparacion, antes.en_curso) == (e.reparacion,
                                                                         e.en_curso):
            return False
        if not ctl["reparacion"].visible:
            return self._esconder("reparacion")
        from tkinter import ttk

        linea = self._bloques.get("reparacion")
        frase = principal.frase_reparacion(e.reparacion)
        if linea is None:
            linea = ttk.Frame(self.marco)
            linea.columnconfigure(1, weight=1)
            marca = theme.etiqueta_icono(linea, "warn", theme.AVISO)
            marca.grid(row=0, column=0, sticky="w", padx=(0, theme.E2))
            linea.texto = ttk.Label(linea, text=frase)
            linea.texto.grid(row=0, column=1, sticky="w")
            linea.boton = ttk.Button(linea, text="Reparación…", style="Quiet.TButton",
                                     command=self._acciones.reparacion)
            theme.boton_icono(linea.boton, "doctor", theme.ACENTO, theme.PAPEL)
            linea.boton.grid(row=0, column=2, sticky="e")
            self._nuevo_bloque("reparacion", linea)
        elif str(linea.texto.cget("text")) != frase:
            linea.texto.configure(text=frase)
        self._colocar(linea, "reparacion", sticky="ew", pady=(theme.E4, 0))
        return True

    def _pintar_version(self, antes, e, ctl) -> bool:
        """El aviso de versión nueva, con «Actualizar…»."""
        if antes is not None and antes.version == e.version:
            return False
        if not ctl["version"].visible:
            return self._esconder("version")
        caja = self._bloques.get("version")
        if caja is None or caja.texto != e.version:
            caja = bloque_aviso(self.marco, e.version, ancho=420, icono="down", tono="Azul.",
                                boton=("Actualizar…", self._acciones.actualizar))
            caja.texto, caja.boton = e.version, caja.acciones.winfo_children()[0]
            self._nuevo_bloque("version", caja)
        self._colocar(caja, "version", sticky="ew", pady=(theme.E4, 0))
        return True

    def _pintar_componentes(self, antes, e, ctl) -> bool:
        """El aviso de componentes anticuados, con «Actualizar…» si se puede.

        Sin botón si lo único pendiente es lo que no arregla «Actualizar…» (el
        VeraCrypt sin sello de un dispositivo de antes): el texto ya lo dice.
        """
        dato = (e.componentes, e.componentes_boton)
        if antes is not None and (antes.componentes, antes.componentes_boton) == dato:
            return False
        if e.componentes is None:
            return self._esconder("componentes")
        caja = self._bloques.get("componentes")
        if caja is None or caja.dato != dato:
            caja = bloque_aviso(
                self.marco, e.componentes, ancho=420, icono="down", tono="Azul.",
                boton=(("Actualizar…", self._acciones.componentes)
                       if e.componentes_boton else None))
            caja.dato = dato
            botones = caja.acciones.winfo_children()
            caja.boton = botones[0] if botones else None
            self._nuevo_bloque("componentes", caja)
        self._colocar(caja, "componentes", sticky="ew", pady=(theme.E4, 0))
        return True

    def _pintar_lista(self, antes, e, ctl) -> bool:
        """Las filas de las parejas, por nombre, y «Marcar todas».

        Una fila que sigue conserva su casilla tal como esté; una nueva nace
        marcada si su pareja está en `e.marcadas`. Lo demás de la fila (modo,
        hora, chip) se cambia solo si ha cambiado, y una fila que cambia de
        puesto se mueve sin rehacerse.
        """
        if antes is not None and (antes.filas, antes.ultima) == (e.filas, e.ultima):
            return False
        import tkinter as tk
        from tkinter import ttk

        tarjeta = self._tarjeta
        nombres = [f.nombre for f in e.filas]
        for nombre in [n for n in self.filas if n not in nombres]:
            fila = self.filas.pop(nombre)
            for clave in ("casilla", "modo", "cuando", "chip"):
                if fila[clave] is not None:
                    fila[clave].destroy()
            del self.casillas[nombre]
        for i, dato in enumerate(e.filas):
            linea = 2 * i
            fila = self.filas.get(dato.nombre)
            if fila is None:
                var = tk.BooleanVar(self.marco, value=dato.nombre in e.marcadas)
                self.casillas[dato.nombre] = var
                casilla = ttk.Checkbutton(tarjeta, text=dato.nombre, variable=var,
                                          command=self._acciones.al_marcar,
                                          style="Card.Fuerte.TCheckbutton")
                casilla.grid(row=linea, column=0, sticky="w", pady=theme.E2)
                modo = ttk.Label(tarjeta, text=dato.modo, style="Card.Pista.TLabel")
                modo.grid(row=linea, column=1, sticky="w", padx=(theme.E3, 0))
                cuando = ttk.Label(tarjeta, text=dato.cuando, style="Card.MonoPista.TLabel")
                cuando.grid(row=linea, column=3, sticky="e", padx=(theme.E3, theme.E2))
                fila = self.filas[dato.nombre] = {"casilla": casilla, "modo": modo,
                                                  "cuando": cuando, "chip": None,
                                                  "dato": None, "linea": linea}
            elif fila["linea"] != linea:
                for clave in ("casilla", "modo", "cuando", "chip"):
                    if fila[clave] is not None:
                        fila[clave].grid_configure(row=linea)
                fila["linea"] = linea
            viejo = fila["dato"]
            if viejo is not None and viejo.modo != dato.modo:
                fila["modo"].configure(text=dato.modo)
            if viejo is not None and viejo.cuando != dato.cuando:
                fila["cuando"].configure(text=dato.cuando)
            if viejo is None or viejo.chip != dato.chip:
                if fila["chip"] is not None:
                    fila["chip"].destroy()
                    fila["chip"] = None
                if dato.chip is not None:
                    # Se queda hasta que no quede ninguna copia en disco: no es
                    # un suceso que se lee y se olvida, es un estado de la carpeta.
                    fila["chip"] = theme.chip(tarjeta, *dato.chip)
                    fila["chip"].grid(row=linea, column=4, sticky="e")
            fila["dato"] = dato
        if self._orden != nombres:
            # El tabulador recorre las casillas en su orden de apilado, que ha de
            # ser el de la lista y no el de creación.
            for nombre in nombres:
                self.filas[nombre]["casilla"].lift()
            self._orden = nombres
        # Una línea fina entre cada dos filas: son todas iguales, así que van por
        # posición y no por pareja.
        while len(self._separadores) > max(0, len(nombres) - 1):
            self._separadores.pop().destroy()
        while len(self._separadores) < len(nombres) - 1:
            fila_sep = 2 * len(self._separadores) + 1
            separador_fila(tarjeta, fila_sep, 5)
            self._separadores.append(next(
                w for w in tarjeta.grid_slaves(row=fila_sep, column=0)
                if w.winfo_class() == "TSeparator"))
        if not nombres:
            if self._vacia is None:
                self._vacia = ttk.Label(tarjeta, text="No hay ninguna pareja configurada.",
                                        style="Card.Pista.TLabel")
            self._vacia.grid(row=0, column=0, pady=theme.E3)
        elif self._vacia is not None and self._vacia.winfo_manager():
            self._vacia.grid_remove()
        self._pintar_marcar_todas(ctl)
        self.contar()
        return True

    def _pintar_marcar_todas(self, ctl) -> bool:
        """«Marcar todas», con dos parejas o más; su sitio, medido para sus dos textos.

        El texto dice lo que hará, y cambia: se reserva el ancho del más largo,
        o el resumen de la derecha bailaría con cada clic.
        """
        from tkinter import ttk

        visible = ctl["marcar_todas"].visible
        if self._todas is None:
            if not visible:
                return False
            self._todas = ttk.Button(self._rotulo, text=principal.DESMARCAR_TODAS,
                                     style="Quiet.TButton", command=self._acciones.marcar_todas)
            # ttk calcula lo que pide un botón al configurarlo: no hace falta
            # esperar a que se pinte para medirlo.
            ancho = self._todas.winfo_reqwidth()
            self._todas.configure(text=principal.MARCAR_TODAS)
            self._ancho_todas = max(ancho, self._todas.winfo_reqwidth()) + HOLGURA_MARCAR
        elif visible == bool(self._todas.winfo_manager()):
            return False
        if visible:
            self._todas.grid(row=0, column=1, sticky="w", padx=(theme.E3, 0))
            self._rotulo.columnconfigure(1, minsize=self._ancho_todas)
        else:
            self._todas.grid_remove()
            self._rotulo.columnconfigure(1, minsize=0)
        return True

    def _pintar_llavero(self, antes, e, ctl) -> bool:
        """La línea del llavero, con «Abrir llavero».

        Es de cada día, así que va aquí y no detrás del engranaje. Su botón se
        apaga o se enciende con los demás (`_poner_activos`).
        """
        dato = None if e.llavero is None else e.llavero[:3]
        if antes is not None and (None if antes.llavero is None else antes.llavero[:3]) == dato:
            return False
        if dato is None:
            return self._esconder("llavero")
        linea = self._bloques.get("llavero")
        if linea is None or linea.dato != dato:
            texto, aviso, boton = dato
            linea = theme.linea_estado(self.marco, "llave", texto, boton,
                                       self._acciones.llavero,
                                       tono="Ambar." if aviso else "", ancho=420)
            linea.dato = dato
            self._nuevo_bloque("llavero", linea)
        self._colocar(linea, "llavero", sticky="ew", pady=(theme.E4, 0))
        return True

    def _pintar_arranque(self, antes, e, ctl) -> bool:
        """La línea del arranque automático y la frase de la pausa debajo.

        Sigue encendida mientras sincroniza: el vigilante no toca nada del
        dispositivo.
        """
        if antes is not None and (antes.arranque, antes.pausa) == (e.arranque, e.pausa):
            return False
        from tkinter import ttk

        tam = False
        if antes is None or antes.arranque != e.arranque:
            tam = True
            if e.arranque is None:
                self._esconder("arranque")
            else:
                linea = self._bloques.get("arranque")
                dato = e.arranque[:3]
                if linea is None or linea.dato != dato:
                    texto, aviso, boton = dato
                    linea = theme.linea_estado(self.marco, "arranque", texto, boton,
                                               self._acciones.arranque,
                                               tono="Ambar." if aviso else "", ancho=420)
                    linea.dato = dato
                    self._nuevo_bloque("arranque", linea)
                self._colocar(linea, "arranque", sticky="ew", pady=(theme.E4, 0))
        if antes is None or antes.pausa != e.pausa:
            tam = True
            if e.pausa is None:
                self._esconder("pausa")
            else:
                # El vigilante no lanza nada mientras esta ventana esté abierta;
                # sin decirlo, enchufar con ella abierta parecería un arranque
                # automático roto.
                frase = self._bloques.get("pausa")
                if frase is None:
                    frase = ttk.Label(self.marco, style="Pista.TLabel",
                                      wraplength=theme.medida(560), justify="left")
                    self._nuevo_bloque("pausa", frase)
                if str(frase.cget("text")) != e.pausa:
                    frase.configure(text=e.pausa)
                self._colocar(frase, "pausa", sticky="w", pady=(theme.E1, 0))
        return tam

    def _pintar_pie(self, antes, e, ctl) -> bool:
        """El botón del servicio y, si toca, «Expulsar» o «Bloquear».

        «Iniciar servicio» no lleva icono; «Pausar», «Reanudar» y «Reanudar
        todo» (el agente como servicio de esta raíz) llevan el suyo.
        """
        tam = False
        if antes is None or antes.servicio != e.servicio:
            tam = True
            accion, texto = e.servicio
            self._servicio.configure(text=texto)
            if accion == principal.INICIAR:
                self._servicio.configure(image="", compound="")
                self._servicio.image = None
            else:
                from . import watch

                theme.boton_icono(self._servicio,
                                  "pausa" if accion == watch.PAUSAR else "play",
                                  theme.TINTA, theme.SUPERFICIE)
        if antes is None or antes.pie != e.pie:
            tam = True
            for clave in ("expulsar", "bloquear"):
                if clave != e.pie:
                    self._esconder(clave)
            if e.pie is not None:
                self._boton_pie(e.pie).grid(row=0, column=2, padx=(theme.E2, 0))
        return tam

    def _boton_pie(self, clave: str):
        """Devuelve «Expulsar» o «Bloquear», hecho la primera vez que hace falta."""
        from tkinter import ttk

        boton = self._bloques.get(clave)
        if boton is None:
            texto, orden = ((
                "Expulsar", self._acciones.expulsar) if clave == principal.EXPULSAR
                else ("Bloquear", self._acciones.bloquear))
            boton = ttk.Button(self._pie, text=texto, style="Grande.TButton", command=orden)
            theme.boton_icono(boton, "expulsar", theme.TINTA, theme.SUPERFICIE)
            self._bloques[clave] = boton
        return boton

    def _poner_activos(self, ctl) -> None:
        """Enciende o apaga cada control según la tabla de «desactivado ⇔ ocupado».

        Solo los que pueden apagarse: los demás nacen encendidos y lo siguen.
        """
        self._activar(self._sincronizar, ctl["sincronizar"].activo)
        self._activar(self._servicio, ctl["servicio"].activo)
        self._activar(self._parejas, ctl["parejas"].activo)
        self._activar(self._ajustes, ctl["ajustes"].activo)
        self._activar(getattr(self._bloques.get("llavero"), "boton", None),
                      ctl["llavero"].activo)
        self._activar(getattr(self._bloques.get("componentes"), "boton", None),
                      ctl["componentes"].activo)
        for clave in ("expulsar", "bloquear"):
            self._activar(self._bloques.get(clave), ctl["pie"].activo)
