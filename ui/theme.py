#!/usr/bin/env python3
"""
theme.py — El sistema visual del rediseño, traducido a ttk.

Papel cálido, tinta casi negra, un solo acento azul; el vocabulario que la
aplicación ya tenía —gris para las pistas, ámbar para los avisos, monoespaciada
para rutas y flags— con forma. Sin esquinas redondeadas y sin sombras, porque
son las dos cosas que ttk no sabe pintar y fingirlas con imágenes sería cambiar
de tecnología para adornar.

El tema es **clam** y no el nativo: es el único de los que trae Tk que deja
elegir el color de cada borde (`bordercolor`, `lightcolor`, `darkcolor`), y sin
eso no hay forma de que un botón sea una caja de 1 px del color que dice el
diseño. A cambio, hay que repintarlo todo, que es lo que hace `apply()`.

Los estilos se generan cruzando **rol** (normal, pista, rótulo, monoespaciada…)
con **superficie** (papel, tarjeta, franja gris, bloque de aviso). Hace falta
cruzarlos porque una `ttk.Label` no hereda el fondo de su padre: una pista sobre
una tarjeta blanca y la misma pista sobre el papel son dos estilos distintos, y
la alternativa —dar el color a mano en cada llamada— es la que garantiza que
alguno se quede sin cambiar el día que se retoque la paleta.

`import tkinter` va dentro de las funciones, como en todo `ui/`: este módulo lo
puede importar quien no tenga entorno gráfico.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Color
# ---------------------------------------------------------------------------

PAPEL = "#FAF9F7"           # fondo de toda ventana
SUPERFICIE = "#FFFFFF"      # listas, cajas, tablas
TINTA = "#1C1A17"           # texto principal
TINTA2 = "#5C564C"          # etiquetas de campo
TINTA3 = "#8A8477"          # pistas y rótulos
LINEA = "#E4E0D8"           # separadores y bordes
LINEA_SUAVE = "#EFEBE4"     # la línea entre filas de una lista
BORDE = "#CFC9BE"           # borde de los controles que se pulsan o se escriben

ACENTO = "#3D5A80"          # acción principal, enlaces
ACENTO_OSCURO = "#33506F"
ACENTO_SUAVE = "#EDF1F6"    # fila elegida, chip
ACENTO_BORDE = "#C6D3E2"

OK = "#3F6B4A"              # al día, terminado bien
OK_FONDO = "#EAF0EA"
OK_BORDE = "#CBDCCE"

AVISO = "#8A5A00"           # resync, espejo, max-delete
AVISO_TEXTO = "#7A4F00"
AVISO_FONDO = "#FBF2E2"
AVISO_BORDE = "#E8D6AE"
AVISO_BORDE_BOTON = "#DCCBA6"

PELIGRO = "#A0392E"         # fallo, borrar
PELIGRO_FONDO = "#F9EBE8"
PELIGRO_BORDE = "#E4C6C0"

# El ámbar #E0A34A del diseño no está aquí porque solo sale en el icono de la
# aplicación, y ahí lo define `icons.AMBAR`: un color con un único sitio donde
# se usa vive en ese sitio.

GRIS_FONDO = "#F4F2EE"      # la franja de [defaults]
APAGADO = "#A9A398"         # lo que está ahí pero no cuenta
APAGADO_FONDO = "#F6F4F0"


# ---------------------------------------------------------------------------
# Tipografía
#
# Los tamaños son los de la hoja de estilo y van en PUNTOS, no en píxeles: en
# puntos es Tk quien los escala si la pantalla tiene más densidad, y en píxeles
# saldría todo diminuto en un portátil moderno.
# ---------------------------------------------------------------------------

_FAMILIAS = {
    "texto": ("Segoe UI", "Noto Sans", "DejaVu Sans", "TkDefaultFont"),
    "fuerte": ("Segoe UI Semibold", "Segoe UI", "Noto Sans", "TkDefaultFont"),
    "mono": ("Consolas", "DejaVu Sans Mono", "Menlo", "TkFixedFont"),
}
_elegidas: dict[str, str] = {}


def familia(cual: str) -> str:
    """La primera familia instalada de las que valen para ese papel."""
    if cual not in _elegidas:
        from tkinter import font
        try:
            hay = set(font.families())
        except Exception:                       # sin Tk montado todavía
            hay = set()
        _elegidas[cual] = next((f for f in _FAMILIAS[cual] if f in hay),
                               _FAMILIAS[cual][-1])
    return _elegidas[cual]


def fuente(rol: str = "texto"):
    """La fuente de un rol, en el formato que aceptan tanto tk como ttk."""
    if rol == "titulo":
        return (familia("fuerte"), 16)
    if rol == "dialogo":
        return (familia("fuerte"), 14)
    if rol == "seccion":
        return (familia("fuerte"), 11)
    if rol == "rotulo":
        return (familia("texto"), 8, "bold")
    if rol == "fuerte":
        return (familia("fuerte"), 10)
    if rol == "pista":
        return (familia("texto"), 9)
    if rol == "mono":
        return (familia("mono"), 9)
    if rol == "mono_pequena":
        return (familia("mono"), 8)
    if rol == "etiqueta":
        return (familia("texto"), 8)
    return (familia("texto"), 10)


def rotulo(texto: str) -> str:
    """Un rótulo de sección: mayúsculas y letras separadas.

    Tk no sabe de `letter-spacing`, así que el espaciado se hace a mano: un
    espacio fino entre las letras de cada palabra, y TRES espacios entre
    palabras. Tres y no uno porque el espacio de Segoe UI mide casi lo mismo que
    el fino, y con uno solo «ESTE PEN» se lee «ESTEPEN»."""
    return "   ".join(" ".join(p) for p in texto.upper().split())


# ---------------------------------------------------------------------------
# Los estilos
# ---------------------------------------------------------------------------

# rol -> (color de letra, fuente). El fondo lo pone la superficie.
_ROLES = {
    "": (TINTA, "texto"),
    "Fuerte.": (TINTA, "fuerte"),
    "Pista.": (TINTA3, "pista"),
    "Rotulo.": (TINTA3, "rotulo"),
    "Mono.": (TINTA2, "mono"),
    "MonoPista.": (APAGADO, "mono_pequena"),
    "Campo.": (TINTA2, "texto"),
    "Apagado.": (APAGADO, "pista"),
    "Titulo.": (TINTA, "titulo"),
    "Dialogo.": (TINTA, "dialogo"),
    "Ok.": (OK, "texto"),
    "Aviso.": (AVISO, "texto"),
    "Peligro.": (PELIGRO, "texto"),
}

# superficie -> (fondo, color de letra que manda sobre el del rol o None)
_SUPERFICIES = {
    "": (PAPEL, None),
    "Card.": (SUPERFICIE, None),
    "Gris.": (GRIS_FONDO, None),
    "Ambar.": (AVISO_FONDO, AVISO_TEXTO),
    "Rojo.": (PELIGRO_FONDO, PELIGRO),
    "Azul.": (ACENTO_SUAVE, ACENTO_OSCURO),
}

# Los chips: fondo, borde y letra de cada estado.
_CHIPS = {
    "": (SUPERFICIE, LINEA, TINTA2),
    "Ok.": (OK_FONDO, OK_BORDE, OK),
    "Aviso.": (AVISO_FONDO, AVISO_BORDE, AVISO),
    "Peligro.": (PELIGRO_FONDO, PELIGRO_BORDE, PELIGRO),
    "Acento.": (ACENTO_SUAVE, ACENTO_BORDE, ACENTO_OSCURO),
    "Apagado.": (GRIS_FONDO, LINEA, TINTA3),
}

_puestos: dict[int, object] = {}


def _casilla_propia(widget, style) -> None:
    """Cambia el indicador del Checkbutton por el cuadrado del diseño.

    El de clam pinta una especie de aspa y no hay forma de decirle que dibuje un
    visto: lo único que deja elegir son los colores. Así que el indicador pasa a
    ser un elemento de imagen, con una imagen por estado, y el resto de la
    disposición se conserva tal cual. Si algo falla se deja el de clam: una
    casilla fea sigue marcándose, y una ventana que no abre no."""
    from . import icons
    try:
        estados = {e: icons.casilla(widget, e)
                   for e in ("marcada", "vacia", "apagada", "apagada-marcada")}
        style.element_create(
            "Prdrive.Checkbutton.indicator", "image", estados["vacia"],
            ("disabled", "selected", estados["apagada-marcada"]),
            ("disabled", estados["apagada"]),
            ("selected", estados["marcada"]),
            border=0, sticky="")
        style.layout("TCheckbutton", [
            ("Checkbutton.padding", {"sticky": "nswe", "children": [
                ("Prdrive.Checkbutton.indicator", {"side": "left", "sticky": ""}),
                ("Checkbutton.focus", {"side": "left", "sticky": "w", "children": [
                    ("Checkbutton.label", {"sticky": "nswe"})]})]})])
    except Exception:
        pass


def apply(widget) -> None:
    """Pinta el tema en el intérprete de Tk al que pertenece `widget`.

    Se hace una sola vez por intérprete —los estilos son globales dentro de
    uno—, y hay más de uno a lo largo de una sesión: la ventana principal abre
    el suyo, lo cierra, y el asistente abre otro."""
    interp = widget.tk
    if _puestos.get(id(interp)) is interp:
        return

    from tkinter import ttk
    style = ttk.Style(widget)
    try:
        style.theme_use("clam")
    except Exception:
        pass                                    # sin clam se pinta lo que haya

    borde = dict(bordercolor=BORDE, lightcolor=BORDE, darkcolor=BORDE)
    linea = dict(bordercolor=LINEA, lightcolor=LINEA, darkcolor=LINEA)

    style.configure(".", background=PAPEL, foreground=TINTA, font=fuente(),
                    focuscolor=ACENTO, troughcolor=GRIS_FONDO, **linea)

    # --- superficies y textos ----------------------------------------------
    for sup, (fondo, manda) in _SUPERFICIES.items():
        style.configure(f"{sup}TFrame", background=fondo)
        for rol, (color, tipo) in _ROLES.items():
            style.configure(f"{sup}{rol}TLabel", background=fondo,
                            foreground=manda or color, font=fuente(tipo))
        style.configure(f"{sup}TCheckbutton", background=fondo,
                        foreground=manda or TINTA)
        style.configure(f"{sup}Fuerte.TCheckbutton", background=fondo,
                        foreground=manda or TINTA, font=fuente("fuerte"))
        style.configure(f"{sup}Pista.TCheckbutton", background=fondo,
                        foreground=TINTA3, font=fuente("pista"))

    # La tarjeta y las franjas de color: un borde de 1 px y nada más.
    for nombre, (fondo, color) in (("Card.TFrame", (SUPERFICIE, LINEA)),
                                   ("Gris.TFrame", (GRIS_FONDO, LINEA)),
                                   ("Ambar.TFrame", (AVISO_FONDO, AVISO_BORDE)),
                                   ("Rojo.TFrame", (PELIGRO_FONDO, PELIGRO_BORDE)),
                                   ("Azul.TFrame", (ACENTO_SUAVE, ACENTO_BORDE))):
        style.configure(nombre, background=fondo, relief="solid", borderwidth=1,
                        bordercolor=color, lightcolor=color, darkcolor=color)
    # …y la misma tarjeta sin borde, para lo que ya va dentro de otra.
    style.configure("Plano.Card.TFrame", relief="flat", borderwidth=0)

    style.configure("TSeparator", background=LINEA)
    style.configure("Card.TSeparator", background=LINEA_SUAVE)

    # --- chips --------------------------------------------------------------
    style.configure("Chip.TLabel", padding=(8, 2), relief="solid", borderwidth=1,
                    font=fuente("pista"))
    for tipo, (fondo, color, letra) in _CHIPS.items():
        style.configure(f"{tipo}Chip.TLabel", background=fondo, foreground=letra,
                        bordercolor=color, lightcolor=color, darkcolor=color)
    # La etiqueta de capa del editor de flags: un chip aún más discreto.
    style.configure("Capa.TLabel", padding=(7, 1), relief="solid", borderwidth=1,
                    font=fuente("etiqueta"), background=GRIS_FONDO,
                    foreground=TINTA3, bordercolor=LINEA, lightcolor=LINEA,
                    darkcolor=LINEA)

    # --- botones ------------------------------------------------------------
    style.configure("TButton", background=SUPERFICIE, foreground=TINTA,
                    padding=(12, 5), relief="solid", borderwidth=1,
                    font=fuente(), **borde)
    style.map("TButton",
              background=[("pressed", GRIS_FONDO), ("active", ACENTO_SUAVE),
                          ("disabled", APAGADO_FONDO)],
              foreground=[("disabled", APAGADO)],
              bordercolor=[("active", ACENTO_BORDE), ("disabled", LINEA)],
              lightcolor=[("active", ACENTO_BORDE), ("disabled", LINEA)],
              darkcolor=[("active", ACENTO_BORDE), ("disabled", LINEA)])

    style.configure("Primary.TButton", background=ACENTO, foreground=SUPERFICIE,
                    font=fuente("fuerte"), bordercolor=ACENTO_OSCURO,
                    lightcolor=ACENTO_OSCURO, darkcolor=ACENTO_OSCURO)
    style.map("Primary.TButton",
              background=[("pressed", ACENTO_OSCURO), ("active", ACENTO_OSCURO),
                          ("disabled", APAGADO_FONDO)],
              foreground=[("disabled", APAGADO)],
              bordercolor=[("disabled", LINEA)], lightcolor=[("disabled", LINEA)],
              darkcolor=[("disabled", LINEA)])

    style.configure("Danger.TButton", foreground=PELIGRO,
                    bordercolor=PELIGRO_BORDE, lightcolor=PELIGRO_BORDE,
                    darkcolor=PELIGRO_BORDE)
    style.map("Danger.TButton",
              background=[("pressed", PELIGRO_FONDO), ("active", PELIGRO_FONDO),
                          ("disabled", APAGADO_FONDO)],
              foreground=[("disabled", APAGADO)])

    # El botón de texto: sin caja, solo el acento. Su fondo tiene que ser el de
    # la superficie donde cae, porque un botón sin borde que no la iguale se ve
    # como un recorte de otro color.
    for sup, fondo in (("Quiet.", PAPEL), ("CardQuiet.", SUPERFICIE),
                       ("GrisQuiet.", GRIS_FONDO)):
        style.configure(f"{sup}TButton", background=fondo, foreground=ACENTO,
                        relief="flat", borderwidth=1, padding=(8, 4),
                        bordercolor=fondo, lightcolor=fondo, darkcolor=fondo)
        style.map(f"{sup}TButton",
                  background=[("pressed", ACENTO_SUAVE), ("active", ACENTO_SUAVE),
                              ("disabled", fondo)],
                  bordercolor=[("active", ACENTO_SUAVE)],
                  lightcolor=[("active", ACENTO_SUAVE)],
                  darkcolor=[("active", ACENTO_SUAVE)],
                  foreground=[("disabled", APAGADO)])
    style.configure("AmbarQuiet.TButton", background=AVISO_FONDO,
                    foreground=AVISO, relief="flat", borderwidth=1, padding=(8, 4),
                    bordercolor=AVISO_FONDO, lightcolor=AVISO_FONDO,
                    darkcolor=AVISO_FONDO)
    style.map("AmbarQuiet.TButton",
              background=[("pressed", AVISO_BORDE), ("active", AVISO_BORDE)],
              bordercolor=[("active", AVISO_BORDE)],
              lightcolor=[("active", AVISO_BORDE)],
              darkcolor=[("active", AVISO_BORDE)],
              foreground=[("disabled", APAGADO)])

    # Los del bloque del catálogo: fondo ámbar, para que se vea que van juntos.
    for nombre, color in (("Ambar.TButton", TINTA),
                          ("AmbarDanger.TButton", PELIGRO)):
        style.configure(nombre, background=SUPERFICIE, foreground=color,
                        bordercolor=AVISO_BORDE_BOTON,
                        lightcolor=AVISO_BORDE_BOTON, darkcolor=AVISO_BORDE_BOTON)
        style.map(nombre,
                  background=[("pressed", AVISO_FONDO), ("active", AVISO_FONDO),
                              ("disabled", APAGADO_FONDO)],
                  foreground=[("disabled", APAGADO)])

    # --- lo que se marca y lo que se escribe --------------------------------
    style.configure("TCheckbutton", padding=(0, 3), focuscolor=PAPEL)
    style.map("TCheckbutton", foreground=[("disabled", APAGADO)])
    _casilla_propia(widget, style)
    style.configure("TRadiobutton", padding=(0, 3))

    for nombre in ("TEntry", "TCombobox", "TSpinbox"):
        style.configure(nombre, fieldbackground=SUPERFICIE, background=SUPERFICIE,
                        foreground=TINTA, insertcolor=TINTA, arrowcolor=TINTA3,
                        padding=(6, 4), selectbackground=ACENTO_SUAVE,
                        selectforeground=TINTA, **borde)
        style.map(nombre,
                  bordercolor=[("focus", ACENTO), ("disabled", LINEA)],
                  lightcolor=[("focus", ACENTO), ("disabled", LINEA)],
                  darkcolor=[("focus", ACENTO), ("disabled", LINEA)],
                  fieldbackground=[("disabled", APAGADO_FONDO),
                                   ("readonly", SUPERFICIE)],
                  foreground=[("disabled", APAGADO)])
    style.configure("Mono.TEntry", font=fuente("mono"))
    style.configure("Mono.TCombobox", font=fuente("mono"))

    # El desplegable de un Combobox es una listbox de tk, no un widget de ttk:
    # no le llega nada de lo de arriba y hay que vestirlo por la vía de options.
    raiz = widget.winfo_toplevel()
    for opcion, valor in (("*TCombobox*Listbox.background", SUPERFICIE),
                          ("*TCombobox*Listbox.foreground", TINTA),
                          ("*TCombobox*Listbox.selectBackground", ACENTO_SUAVE),
                          ("*TCombobox*Listbox.selectForeground", TINTA),
                          ("*TCombobox*Listbox.font", " ".join(
                              str(x) for x in fuente()))):
        try:
            raiz.option_add(opcion, valor)
        except Exception:
            pass

    # --- listas, barras y demás --------------------------------------------
    style.configure("Treeview", background=SUPERFICIE, fieldbackground=SUPERFICIE,
                    foreground=TINTA, rowheight=28, borderwidth=0, relief="flat",
                    font=fuente())
    style.map("Treeview",
              background=[("selected", ACENTO_SUAVE)],
              foreground=[("selected", TINTA)])
    style.configure("Treeview.Heading", background=PAPEL, foreground=TINTA3,
                    font=fuente("rotulo"), relief="flat", padding=(8, 4, 8, 7),
                    borderwidth=0)
    style.map("Treeview.Heading", background=[("active", PAPEL)],
              relief=[("active", "flat")])
    style.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])

    for orientacion in ("Vertical", "Horizontal"):
        style.configure(f"{orientacion}.TScrollbar", background=LINEA,
                        troughcolor=PAPEL, arrowcolor=TINTA3, gripcount=0,
                        borderwidth=0, relief="flat", **linea)
        style.map(f"{orientacion}.TScrollbar",
                  background=[("pressed", TINTA3), ("active", BORDE)])

    style.configure("Horizontal.TProgressbar", background=ACENTO,
                    troughcolor=GRIS_FONDO, borderwidth=0,
                    bordercolor=LINEA, lightcolor=ACENTO, darkcolor=ACENTO)

    style.configure("TLabelframe", background=PAPEL, relief="solid",
                    borderwidth=1, **linea)
    style.configure("TLabelframe.Label", background=PAPEL, foreground=TINTA3,
                    font=fuente("rotulo"))

    _puestos[id(interp)] = interp


# ---------------------------------------------------------------------------
# Piezas que se repiten
# ---------------------------------------------------------------------------

def chip(parent, texto: str, tipo: str = "", icono: str | None = None):
    """Una etiqueta de estado. `tipo` es '', 'Ok.', 'Aviso.', 'Peligro.',
    'Acento.' o 'Apagado.'; el icono, si se pide, va del color del chip."""
    from tkinter import ttk

    from . import icons

    estilo = f"{tipo}Chip.TLabel"
    etiqueta = ttk.Label(parent, text=texto, style=estilo)
    if icono:
        fondo, _borde, color = _CHIPS.get(tipo, _CHIPS[""])
        img = icons.get(parent, icono, 12, color, fondo)
        if img is not None:
            etiqueta.configure(image=img, compound="left", padding=(6, 2))
            etiqueta.image = img            # Tk no se queda con la referencia
    return etiqueta


def boton_icono(boton, nombre: str, color: str = TINTA, fondo: str = PAPEL,
                size: int = 15):
    """Le pone un icono a la izquierda del texto a un botón ya creado.

    Si el icono no se puede pintar el botón se queda con su texto y ya está: un
    adorno no puede dejar sin usar una acción."""
    from . import icons
    img = icons.get(boton, nombre, size, color, fondo)
    if img is not None:
        boton.configure(image=img, compound="left")
        boton.image = img
    return boton


def caja_texto(parent, **kw):
    """Un `tk.Text` con la ropa del diseño. Sigue siendo un tk.Text pelado: lo
    que se le pide es un fondo blanco, un borde de 1 px y la monoespaciada."""
    import tkinter as tk
    opciones = dict(background=SUPERFICIE, foreground=TINTA, font=fuente("mono"),
                    relief="flat", borderwidth=0, highlightthickness=1,
                    highlightbackground=BORDE, highlightcolor=ACENTO,
                    insertbackground=TINTA, selectbackground=ACENTO_SUAVE,
                    selectforeground=TINTA, padx=8, pady=6, wrap="none")
    opciones.update(kw)
    return tk.Text(parent, **opciones)


def marcar_lista(tree) -> None:
    """Los colores de fila de una lista de parejas, por estado.

    El diseño pide un chip de color en la columna de estado y una `ttk.Treeview`
    no sabe pintar una celda suelta, así que el color va a la fila entera: fondo
    para lo que hay que mirar —ámbar si pide un resync, rojo si es un espejo que
    borra— y letra gris para lo que está ahí pero este dispositivo no usa. Fondo y no
    letra porque una ruta monoespaciada en ámbar se lee peor, y porque así el
    azul de la fila elegida sigue viéndose encima."""
    tree.tag_configure("ok", background=SUPERFICIE, foreground=TINTA)
    tree.tag_configure("aviso", background=AVISO_FONDO, foreground=TINTA)
    tree.tag_configure("peligro", background=PELIGRO_FONDO, foreground=PELIGRO)
    tree.tag_configure("apagado", background=SUPERFICIE, foreground=APAGADO)
