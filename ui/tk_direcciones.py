"""«Servidor…»: la barra de direcciones, como la del Explorador; solo dibuja.

Atrás, adelante, arriba y releer (botones de icono solo); las migas de la ruta en un
solo lienzo, con el icono del servidor delante y su menú; la ruta escrita a mano (un
clic en el hueco de las migas) y el campo de búsqueda. Qué ruta es cada miga lo
decide `servidor.migas` y cuántas se recogen en «…», `servidor.recoger`; qué se hace
al pulsar, quien la usa (`ui/tk_servidor.py`), por las acciones que le da.

Las migas son textos e iconos de un `tk.Canvas` y no un botón por carpeta: en
Windows cada widget es una ventana del sistema, y redimensionar una fila de botones
los mueve y repinta todos; en el lienzo solo se recolocan unos textos, y solo cuando
cambia su ancho.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from . import icons, servidor, theme, tk_gestion

PUNTOS = "…"
"""El tramo que ocupa el sitio de las migas recogidas."""
ANCHO_BUSQUEDA = 24
"""Ancho (en caracteres) del campo de búsqueda."""
ANCHO_MIGAS = 160
"""Ancho (px del diseño) que piden las migas: el mínimo; estiran con la ventana."""
HUECO_MIGA = 6
"""Relleno (px del diseño) a cada lado del texto de una miga: lo que se resalta."""
MARGEN_MIGAS = 4
"""Margen (px del diseño) a la izquierda y a la derecha del lienzo."""
LADO_ICONO = 16
"""Lado (px del diseño) del icono del servidor."""
LADO_FLECHA = 12
"""Lado (px del diseño) de la flecha del servidor y de los separadores «›»."""
ROTULOS = {"atras": "Atrás", "adelante": "Adelante", "arriba": "Arriba", "releer": "Releer"}
"""El nombre de cada botón de navegación (solo enseñan el icono; el nombre queda)."""
ICONOS = {"atras": "back", "adelante": "adelante", "arriba": "arriba", "releer": "reload"}
"""El icono de cada botón de navegación."""


class Direcciones:
    """La barra de direcciones del explorador del servidor.

    `marco` lo coloca con `grid` quien la usa. Lo que enseña lo pone `poner()`; qué se
    puede pulsar, `encender()`. Los menús (servidores, migas recogidas) los enseña
    `mostrar_menu`, que es de quien la usa porque `tk_popup` toma el ratón y los tests
    lo sustituyen.

    Args:
        padre: El contenedor del que cuelga `marco`.
        acciones: Qué hace cada cosa: `atras`, `adelante`, `arriba` y `releer` (sin
            argumentos); `ir(ruta)` (una miga); `servidor(nombre)` (el menú de
            servidores); `escrita(texto)` (Intro al escribir la ruta); `buscar(texto)`
            (cada cambio del campo de búsqueda); `buscar_ya(texto)` (Intro en él) y
            `vaciar()` (Escape en él). Se consultan al pulsar.
        mostrar_menu: `mostrar_menu(menu, x, y)` enseña un menú en esa posición de la
            pantalla.

    Attributes:
        marco: La barra entera.
        atras, adelante, arriba, releer: Los botones de navegación.
        lienzo: El `tk.Canvas` de las migas.
        campo: El `ttk.Entry` de la ruta escrita (fuera de la rejilla mientras no se
            escribe).
        busqueda: El `ttk.Entry` de la búsqueda.
        texto_busqueda: Su `StringVar`.
        remote: El remote que se enseña.
        ruta: La carpeta que se enseña.
    """

    def __init__(self, padre, acciones: dict[str, Callable], mostrar_menu: Callable) -> None:
        import tkinter as tk
        from tkinter import ttk

        self._acciones = acciones
        self._mostrar_menu = mostrar_menu
        self.remote = ""
        self.ruta = servidor.RAIZ
        self._remotes: list[str] = []
        self._servidor_encendido = True
        self._editando = False
        self._avisar = True
        self._ancho = 0
        self._vistas: list[tuple[str, str | None]] = []
        self._recogidas: list[tuple[str, str]] = []
        self._zonas: list[tuple[int, int, str, object]] = []
        self._resaltada: str | None = None
        self._var_servidor = None
        self._menus: dict[str, object] = {}

        self.marco = ttk.Frame(padre)
        self.marco.columnconfigure(4, weight=1)
        for columna, clave in enumerate(ROTULOS):
            boton = ttk.Button(self.marco, text=ROTULOS[clave], style="Quiet.TButton",
                               command=lambda k=clave: self._acciones[k]())
            theme.boton_icono(boton, ICONOS[clave], theme.ACENTO, theme.PAPEL)
            boton.configure(compound="image")      # el texto queda como nombre; sin icono, se ve él
            boton.grid(row=0, column=columna, sticky="w",
                       padx=(0 if columna == 0 else theme.E1, 0))
            setattr(self, clave, boton)

        self.campo = ttk.Entry(self.marco)
        self._sitio = dict(row=0, column=4, sticky="ew", padx=(theme.E3, theme.E3))
        borde = 1
        self.lienzo = tk.Canvas(
            self.marco, width=icons.px(self.marco, ANCHO_MIGAS),
            height=max(1, self.campo.winfo_reqheight() - 2 * borde),
            background=theme.SUPERFICIE, highlightthickness=borde,
            highlightbackground=theme.LINEA, highlightcolor=theme.ACENTO, borderwidth=0)
        self.lienzo.grid(**self._sitio)
        self.campo.bind("<Return>", self._escrita)
        self.campo.bind("<KP_Enter>", self._escrita)
        self.campo.bind("<Escape>", lambda _e: (self._dejar(), "break")[1])
        self.campo.bind("<FocusOut>", lambda _e: self._dejar())
        self.lienzo.bind("<Configure>", self._al_cambiar_tamano)
        self.lienzo.bind("<Motion>", lambda e: self._resaltar(self._zona_en(e.x)))
        self.lienzo.bind("<Leave>", lambda _e: self._resaltar(None))
        self.lienzo.bind("<Button-1>", lambda e: self._clic(e.x))

        self.texto_busqueda = tk.StringVar(self.marco)
        self.busqueda = ttk.Entry(self.marco, textvariable=self.texto_busqueda,
                                  width=ANCHO_BUSQUEDA)
        self.busqueda.grid(row=0, column=5, sticky="e")
        self._texto_pista = ""
        self._pista = theme.pista_campo(self.busqueda, "")
        self.texto_busqueda.trace_add("write", self._escrito)
        for tecla in ("<Return>", "<KP_Enter>"):
            self.busqueda.bind(tecla, lambda _e: (
                self._acciones["buscar_ya"](self.texto_busqueda.get()), "break")[1])
        self.busqueda.bind("<Escape>", lambda _e: (self._acciones["vaciar"](), "break")[1])

    # -- lo que se enseña ------------------------------------------------------

    def poner(self, remote: str, ruta: str, remotes: Sequence[str]) -> None:
        """Enseña esa carpeta de ese remote: las migas y la pista de la búsqueda."""
        self.remote, self.ruta, self._remotes = remote, servidor.ruta_escrita(ruta), list(remotes)
        tramos = servidor.migas(remote, self.ruta)
        self._poner_pista(f"Buscar en {tramos[-1][0]}" if tramos[-1][0] else "Buscar")
        self._dibujar()

    def encender(self, atras: bool, adelante: bool, arriba: bool, releer: bool,
                 servidor: bool, buscar: bool) -> None:
        """Enciende lo que se dice y apaga lo demás.

        Args:
            atras, adelante, arriba, releer: Los botones de navegación.
            servidor: Si el icono del servidor abre su menú.
            buscar: Si se puede escribir en la búsqueda.
        """
        for boton, encendido in ((self.atras, atras), (self.adelante, adelante),
                                 (self.arriba, arriba), (self.releer, releer)):
            boton.state(["!disabled" if encendido else "disabled"])
        self._servidor_encendido = servidor
        self.busqueda.state(["!disabled" if buscar else "disabled"])

    def tramos(self) -> list[tuple[str, str | None]]:
        """Las migas que se ven, de izquierda a derecha: `(rótulo, ruta)`; «…» lleva `None`."""
        return list(self._vistas)

    def pista(self) -> str:
        """La pista que enseña el campo de búsqueda vacío."""
        return self._texto_pista

    def poner_busqueda(self, texto: str) -> None:
        """Pone ese texto en el campo de búsqueda sin avisar a `buscar`."""
        self._avisar = False
        try:
            self.texto_busqueda.set(texto)
        finally:
            self._avisar = True

    @property
    def editando(self) -> bool:
        """Si la barra está en modo texto (escribiendo la ruta)."""
        return self._editando

    # -- lo que se pulsa -------------------------------------------------------

    def pulsar(self, i: int) -> None:
        """Hace lo que un clic en la miga `i` de `tramos()`."""
        for _x0, _x1, tipo, valor in self._zonas:
            if tipo != "servidor" and valor == i:
                self._hacer(tipo, valor)
                return

    def pulsar_servidor(self) -> None:
        """Hace lo que un clic en el icono del servidor: su menú, si está encendido."""
        if not self._servidor_encendido:
            return
        x0 = next((z[0] for z in self._zonas if z[2] == "servidor"), 0)
        self._mostrar_menu(self.menu_servidores(), self.lienzo.winfo_rootx() + x0,
                           self.lienzo.winfo_rooty() + self.lienzo.winfo_height())

    def _nuevo_menu(self, clase: str):
        """Un menú del tema; el anterior de su clase se destruye (Windows tiene un tope)."""
        import tkinter as tk

        viejo = self._menus.get(clase)
        if viejo is not None:
            try:
                viejo.destroy()
            except tk.TclError:
                pass                            # ya no estaba
        menu = self._menus[clase] = tk_gestion.menu_del_tema(self.lienzo)
        return menu

    def menu_servidores(self):
        """Devuelve el menú con todos los servidores; el que se ve, marcado."""
        import tkinter as tk

        menu = self._nuevo_menu("servidores")
        menu.configure(selectcolor=theme.TINTA)
        self._var_servidor = tk.StringVar(self.lienzo, value=self.remote)
        for nombre in self._remotes:
            menu.add_radiobutton(label=nombre, value=nombre, variable=self._var_servidor,
                                 command=lambda n=nombre: self._acciones["servidor"](n))
        return menu

    def menu_recogidas(self):
        """Devuelve el menú con las migas recogidas en «…», de la raíz hacia dentro."""
        menu = self._nuevo_menu("recogidas")
        for rotulo, ruta in self._recogidas:
            menu.add_command(label=rotulo, command=lambda r=ruta: self._acciones["ir"](r))
        return menu

    def editar(self) -> None:
        """Cambia las migas por el campo de la ruta, con ella seleccionada entera."""
        if self._editando:
            return
        self._editando = True
        self.lienzo.grid_remove()
        self.campo.grid(**self._sitio)
        self.campo.delete(0, "end")
        self.campo.insert(0, self.ruta)
        self.campo.select_range(0, "end")
        self.campo.icursor("end")
        self.campo.focus_set()

    def enfocar_busqueda(self) -> None:
        """Lleva el foco al campo de búsqueda, con lo que tenga seleccionado."""
        self.busqueda.focus_set()
        self.busqueda.select_range(0, "end")

    # -- por dentro --------------------------------------------------------------

    def _poner_pista(self, texto: str) -> None:
        """Cambia la pista del campo de búsqueda (la de Tk 9 o la etiqueta de Tk 8.6)."""
        import tkinter as tk

        self._texto_pista = texto
        if self._pista is not None:
            self._pista.configure(text=texto)
            return
        try:
            self.busqueda.configure(placeholder=texto)
        except tk.TclError:                          # Tk 8.6 sin pista propia
            self._pista = theme.pista_etiqueta(self.busqueda, texto)

    def _escrito(self, *_args) -> None:
        if self._avisar:
            self._acciones["buscar"](self.texto_busqueda.get())

    def _escrita(self, _evento=None) -> str:
        texto = self.campo.get()
        self._dejar()
        self._acciones["escrita"](texto)
        return "break"

    def _dejar(self) -> None:
        """Vuelve de la ruta escrita a las migas, sin decir nada."""
        if not self._editando:
            return
        self._editando = False
        self.campo.grid_remove()
        self.lienzo.grid()

    def _al_cambiar_tamano(self, evento) -> None:
        """Vuelve a colocar las migas solo si cambió el ancho del lienzo."""
        if evento.width != self._ancho:
            self._ancho = evento.width
            self._dibujar()

    def _zona_en(self, x: int) -> int | None:
        for i, (x0, x1, _tipo, _valor) in enumerate(self._zonas):
            if x0 <= x < x1:
                return i
        return None

    def _resaltar(self, zona: int | None) -> None:
        """Pone el fondo de resalte a la zona bajo el ratón y se lo quita a la de antes."""
        etiqueta = None if zona is None else f"z{zona}"
        if etiqueta == self._resaltada:
            return
        if self._resaltada is not None:
            self.lienzo.itemconfigure(self._resaltada, fill="")
        if etiqueta is not None:
            self.lienzo.itemconfigure(etiqueta, fill=theme.ACENTO_SUAVE)
        self._resaltada = etiqueta

    def _clic(self, x: int) -> None:
        zona = self._zona_en(x)
        if zona is None:
            self.editar()
            return
        _x0, _x1, tipo, valor = self._zonas[zona]
        self._hacer(tipo, valor)

    def _hacer(self, tipo: str, valor) -> None:
        """Lo que hace una zona del lienzo: el menú de servidores, el de «…» o ir a una miga."""
        if tipo == "servidor":
            self.pulsar_servidor()
            return
        if tipo == "puntos":
            x0 = next(z[0] for z in self._zonas if z[2] == "puntos")
            self._mostrar_menu(self.menu_recogidas(), self.lienzo.winfo_rootx() + x0,
                               self.lienzo.winfo_rooty() + self.lienzo.winfo_height())
            return
        self._acciones["ir"](self._vistas[valor][1])

    def _cortar(self, letra, texto: str, cabe: int) -> str:
        """Recorta `texto` con «…» hasta que quepa en `cabe` píxeles."""
        if letra.measure(texto) <= cabe:
            return texto
        bajo, alto = 0, len(texto)
        while bajo < alto:
            medio = (bajo + alto + 1) // 2
            if letra.measure(texto[:medio] + PUNTOS) <= cabe:
                bajo = medio
            else:
                alto = medio - 1
        return texto[:bajo] + PUNTOS

    def _dibujar(self) -> None:
        """Coloca el icono del servidor y las migas que caben en el ancho de ahora."""
        lienzo = self.lienzo
        lienzo.delete("all")
        self._zonas, self._resaltada = [], None
        # Antes de colocarse mide 1: entonces vale lo que pide.
        ancho = lienzo.winfo_width() if lienzo.winfo_width() > 1 else int(lienzo.cget("width"))
        alto = lienzo.winfo_height() if lienzo.winfo_height() > 1 else int(lienzo.cget("height"))
        letra = theme.fuente_tk(lienzo)
        fuente = theme.fuente()
        hueco = icons.px(lienzo, HUECO_MIGA)
        margen = icons.px(lienzo, MARGEN_MIGAS)
        medio_y = alto // 2
        fondo = theme.SUPERFICIE
        self._imagenes = [icons.get(lienzo, "nas", LADO_ICONO, theme.TINTA2, fondo),
                          icons.get(lienzo, "abajo", LADO_FLECHA, theme.TINTA3, fondo),
                          icons.get(lienzo, "derecha", LADO_FLECHA, theme.TINTA3, fondo)]
        nas, flecha, separador = self._imagenes
        lado = icons.px(lienzo, LADO_ICONO)
        lado_flecha = icons.px(lienzo, LADO_FLECHA)

        # el servidor: su icono y la flecha de su menú
        x = margen
        fin = x + hueco + lado + lado_flecha + hueco
        lienzo.create_rectangle(x, 1, fin, alto - 1, fill="", outline="", tags=("z0",))
        if nas is not None:
            lienzo.create_image(x + hueco, medio_y, image=nas, anchor="w")
        if flecha is not None:
            lienzo.create_image(x + hueco + lado, medio_y, image=flecha, anchor="w")
        self._zonas.append((x, fin, "servidor", None))
        x = fin

        tramos = [t for t in servidor.migas(self.remote, self.ruta) if t[0]]
        ancho_sep = lado_flecha
        anchos = [letra.measure(rotulo) + 2 * hueco + (ancho_sep if i < len(tramos) - 1 else 0)
                  for i, (rotulo, _ruta) in enumerate(tramos)]
        disponible = max(0, ancho - x - margen)
        k = servidor.recoger(anchos, disponible, letra.measure(PUNTOS) + 2 * hueco + ancho_sep)
        self._recogidas = list(tramos[1:1 + k])
        self._vistas = (tramos[:1] + ([(PUNTOS, None)] if k else []) + tramos[1 + k:]
                        if tramos else [])
        for i, (rotulo, ruta) in enumerate(self._vistas):
            ultimo = i == len(self._vistas) - 1
            texto = rotulo
            if ultimo:
                texto = self._cortar(letra, rotulo, max(0, ancho - margen - x - 2 * hueco))
            w = letra.measure(texto) + 2 * hueco
            n = len(self._zonas)
            lienzo.create_rectangle(x, 1, x + w, alto - 1, fill="", outline="", tags=(f"z{n}",))
            lienzo.create_text(x + hueco, medio_y, text=texto, anchor="w", font=fuente,
                               fill=theme.TINTA)
            self._zonas.append((x, x + w, "puntos" if ruta is None else "miga", i))
            x += w
            if not ultimo and separador is not None:
                lienzo.create_image(x, medio_y, image=separador, anchor="w")
            if not ultimo:
                x += ancho_sep
