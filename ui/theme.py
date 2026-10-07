#!/usr/bin/env python3
"""El sistema visual del rediseño, traducido a ttk.

Papel cálido, tinta casi negra y un solo acento azul; el vocabulario que la
aplicación ya tenía (gris para las pistas, ámbar para los avisos, monoespaciada
para rutas y flags) con forma. Sin esquinas redondeadas y sin sombras, porque
son las dos cosas que ttk no sabe pintar y fingirlas con imágenes sería cambiar
de tecnología para adornar.

El tema es **clam** y no el nativo: es el único de los que trae Tk que deja
elegir el color de cada borde (`bordercolor`, `lightcolor`, `darkcolor`) y sin
eso no hay forma de que un botón sea una caja de 1 px del color que dice el
diseño. A cambio, hay que repintarlo todo, que es lo que hace `apply()`.

Los estilos se generan cruzando **rol** (normal, pista, rótulo, monoespaciada…)
con **superficie** (papel, tarjeta, franja gris, bloque de aviso). Hace falta
cruzarlos porque una `ttk.Label` no hereda el fondo de su padre: una pista
sobre una tarjeta blanca y la misma pista sobre el papel son dos estilos
distintos, y la alternativa (dar el color a mano en cada llamada) es la que
garantiza que alguno se quede sin cambiar el día que se retoque la paleta.

`import tkinter` va dentro de las funciones, como en todo `ui/`: este módulo lo
puede importar quien no tenga entorno gráfico.
"""

from __future__ import annotations

import sys

_densidad_declarada = False
"""Si ya se declaró la densidad de pantalla en este proceso."""


def nitidez() -> None:
    """Declara ante Windows que la aplicación dibuja a la densidad real.

    Todo lo de este módulo (los tamaños en puntos, los iconos de `icons.px`) da
    por hecho que Tk sabe cuántos píxeles tiene de verdad la pantalla, y no lo
    sabe por defecto: ahí es donde se pierde la nitidez. Un proceso que no lo
    declara es «no consciente de ppp» y Windows le miente sobre la pantalla: en
    un 4K al 200 % le dice que mide 1472x920 a 96 ppp en lugar de 2944x1840 a
    192. Tk dibuja a esa medida de mentira y el compositor **estira** después
    el mapa de bits hasta el panel de verdad. Ese estirado es lo que se ve
    borroso y no hay nada en la tipografía que lo arregle: la letra se está
    pintando con la mitad de los píxeles que hay para pintarla.

    Declarada la densidad, Tk mide la pantalla entera, `tk scaling` pasa de
    1,33 a 2,67 y crece solo todo lo que va en puntos (toda la tipografía de
    `fuente()`), ya sin estirar nada.

    **Consciencia del sistema y no por monitor**, a propósito: Tk 8.6 no
    atiende `WM_DPICHANGED`, así que no sabe redibujarse cuando la ventana pasa
    a una pantalla con otro zoom. Con la del sistema, Windows estira la ventana
    en ese caso (borrosa, pero del tamaño que toca); con la de por monitor no
    la estiraría y la ventana saldría a la mitad de su tamaño físico, que es
    peor que borrosa. Cuando el proyecto llegue a Tk 9, esta es la línea que
    cambia.

    Tiene que correr **antes** del primer `Tk()`: Tk lee la densidad al
    arrancar su intérprete y no la vuelve a mirar. Es una propiedad del
    proceso, así que basta una vez; se llama desde todos los sitios que abren
    una raíz porque cuál de ellos es el primero depende de por dónde se haya
    entrado.
    """
    global _densidad_declarada
    if _densidad_declarada or sys.platform != "win32":
        return
    _densidad_declarada = True

    import ctypes

    # De la más nueva a la más vieja. Todas fallan sin ruido (devolviendo cero,
    # o un HRESULT que no es cero, o no existiendo) si esta versión de Windows
    # no las conoce o si la consciencia ya venía puesta desde el manifiesto del
    # .exe, que es un sitio perfectamente válido para haberla puesto.
    try:                                        # Windows 10 1703 en adelante
        if ctypes.windll.user32.SetProcessDpiAwarenessContext(
                ctypes.c_void_p(-2)):           # ..._SYSTEM_AWARE
            return
    except Exception:                           # noqa: BLE001
        pass
    try:                                        # Windows 8.1
        if ctypes.windll.shcore.SetProcessDpiAwareness(1) == 0:  # PROCESS_SYSTEM_DPI_AWARE
            return
    except Exception:                           # noqa: BLE001
        pass
    try:                                        # Windows Vista
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:                           # noqa: BLE001
        pass


def medida(px_diseno: int) -> str:
    """Devuelve una distancia del diseño en la unidad que Tk sí escala: puntos.

    Tk convierte un número suelto en píxeles tal cual, y un número con «p» en
    puntos, que multiplica por `tk scaling`. Un ancho de corte de párrafo
    escrito como 760 mide 760 px tanto al 100 % como al 200 %, así que en una
    pantalla densa el mismo texto (que sí ha crecido) se queda en una columna
    de la mitad de ancho y el triple de alta. Escrito como `medida(760)`
    acompaña a la letra.

    La conversión es la de 96 ppp, que es la densidad para la que están
    pensadas las medidas del diseño, y sale exacta: 760 px son 570 puntos
    justos.

    Es hermana de `icons.px()` y con el mismo cometido; son dos porque van a
    sitios distintos. `px()` devuelve un entero, para lo que Tk no sabe escalar
    de ninguna manera (los mapas de bits de los iconos) y para lo que solo
    admite un entero (`rowheight`); `medida()` devuelve la distancia de Tk, que
    no necesita tener el widget a mano para calcularse.
    """
    return f"{round(px_diseno * 72 / 96)}p"


CLARO = {
    "PAPEL": "#FAF9F7",            # fondo de toda ventana
    "SUPERFICIE": "#FFFFFF",       # tarjetas, listas, campos y tablas
    "GRIS_FONDO": "#F4F2EE",       # la franja hundida: [defaults], el valle de una barra
    "APAGADO_FONDO": "#F6F4F0",    # relleno de un control desactivado
    "TINTA": "#1C1A17",            # texto principal
    "TINTA2": "#5C564C",           # etiquetas de campo y rutas
    "TINTA3": "#6B655A",           # pistas, rótulos y cabeceras (5,2:1 como mínimo)
    "APAGADO": "#A9A398",          # lo que está ahí pero no se usa
    "LINEA": "#E4E0D8",            # separador y borde de tarjeta: decorativo
    "LINEA_SUAVE": "#EFEBE4",      # la línea entre filas de una lista
    "BORDE": "#8C8678",            # borde de lo que se pulsa o se escribe (3:1)
    "ACENTO": "#3D5A80",           # acción principal, enlaces, foco y selección
    "ACENTO_OSCURO": "#33506F",    # pulsado; texto de chip y franja azul
    "ACENTO_SUAVE": "#EDF1F6",     # fila elegida, chip y franja azul
    "ACENTO_BORDE": "#C6D3E2",
    "SOBRE_ACENTO": "#FFFFFF",     # letra e icono sobre un relleno de acento
    "OK": "#2D6A5A",               # al día, terminado bien
    "OK_FONDO": "#E7F0EE",
    "OK_BORDE": "#C3DAD4",
    "SOBRE_OK": "#FFFFFF",
    "AVISO": "#8A5A00",            # resync, espejo, max-delete
    "AVISO_TEXTO": "#7A4F00",
    "AVISO_FONDO": "#FBF2E2",
    "AVISO_BORDE": "#E8D6AE",
    "AVISO_BORDE_BOTON": "#DCCBA6",
    "SOBRE_AVISO": "#FFFFFF",
    "PELIGRO": "#A0392E",          # fallo, borrar
    "PELIGRO_FONDO": "#F9EBE8",
    "PELIGRO_BORDE": "#E4C6C0",
    "SOBRE_PELIGRO": "#FFFFFF",
}
"""El tema claro: los tokens del sistema de diseño «prdrive» con nombre de aquí.

Respecto de la primera versión del diseño se oscurecen `TINTA3` (era #8A8477,
3,3:1) y `BORDE` (era #CFC9BE, 1,6:1) hasta el contraste que pide WCAG, y el
verde de `OK` se desplaza hacia el verde azulado para que no se distinga del
rojo solo por el matiz.
"""

OSCURO = {
    "PAPEL": "#171512",
    "SUPERFICIE": "#201D19",
    "GRIS_FONDO": "#121110",
    "APAGADO_FONDO": "#1B1915",
    "TINTA": "#F2EEE7",
    "TINTA2": "#CBC4B7",
    "TINTA3": "#A59E90",
    "APAGADO": "#6A645A",
    "LINEA": "#34302A",
    "LINEA_SUAVE": "#292621",
    "BORDE": "#7D776B",
    "ACENTO": "#8DB0DE",
    "ACENTO_OSCURO": "#A9C5EA",
    "ACENTO_SUAVE": "#222D3C",
    "ACENTO_BORDE": "#3C4D66",
    "SOBRE_ACENTO": "#0F1826",
    "OK": "#7CC5AE",
    "OK_FONDO": "#17302A",
    "OK_BORDE": "#2C5246",
    "SOBRE_OK": "#0B1F1A",
    "AVISO": "#E6B45E",
    "AVISO_TEXTO": "#EDC27A",
    "AVISO_FONDO": "#2A2214",
    "AVISO_BORDE": "#5A4524",
    "AVISO_BORDE_BOTON": "#6B5530",
    "SOBRE_AVISO": "#261A06",
    "PELIGRO": "#F0897D",
    "PELIGRO_FONDO": "#301D1A",
    "PELIGRO_BORDE": "#5E322C",
    "SOBRE_PELIGRO": "#2B0F0C",
}
"""El tema oscuro, con las mismas claves que `CLARO`.

`ACENTO_OSCURO` conserva el nombre aunque aquí sea más CLARO que el acento: es
el «acento fuerte» del diseño, el que se usa para pulsar y para escribir sobre
`ACENTO_SUAVE`, y en oscuro fuerte quiere decir más luz. Por lo mismo las
letras `SOBRE_*` se oscurecen: el relleno de color se aclara.
"""

# Los nombres de la paleta como globales del módulo, para que se escriban
# `theme.PAPEL` en todas partes. Valen los del tema claro hasta que `usar()`
# ponga otro; se declaran a mano (y no solo con `globals().update`) para que
# quien lea el código los encuentre.
PAPEL = SUPERFICIE = GRIS_FONDO = APAGADO_FONDO = ""
TINTA = TINTA2 = TINTA3 = APAGADO = LINEA = LINEA_SUAVE = BORDE = ""
ACENTO = ACENTO_OSCURO = ACENTO_SUAVE = ACENTO_BORDE = SOBRE_ACENTO = ""
OK = OK_FONDO = OK_BORDE = SOBRE_OK = ""
AVISO = AVISO_TEXTO = AVISO_FONDO = AVISO_BORDE = AVISO_BORDE_BOTON = SOBRE_AVISO = ""
PELIGRO = PELIGRO_FONDO = PELIGRO_BORDE = SOBRE_PELIGRO = ""

# El ámbar #E0A34A de la marca no está aquí: solo sale en el icono de la
# aplicación y lo define `icons.AMBAR`, que es donde se usa.

TEMA = "claro"
"""El tema que está puesto: `'claro'` u `'oscuro'`."""
_tema_elegido = False
"""Si ya se decidió el tema en este proceso."""


def usar(tema: str) -> None:
    """Pone la paleta de un tema en los nombres del módulo.

    Es de proceso, como `nitidez()`: los intérpretes que ya tengan el tema
    pintado lo conservan (`apply()` se hace una vez por intérprete), así que se
    decide antes de abrir la primera ventana y no se cambia después. Las
    pruebas sí lo cambian, olvidando antes los intérpretes (`_puestos`).

    Raises:
        ValueError: Si no es `'claro'` ni `'oscuro'`.
    """
    global TEMA, _tema_elegido
    if tema not in ("claro", "oscuro"):
        raise ValueError(f"tema desconocido: {tema}")
    globals().update(OSCURO if tema == "oscuro" else CLARO)
    TEMA, _tema_elegido = tema, True


usar("claro")
_tema_elegido = False


def sistema_oscuro() -> bool:
    """Dice si el sistema pide a las aplicaciones el tema oscuro.

    En Windows es el valor `AppsUseLightTheme` de la personalización (0 es
    oscuro); en Linux, la preferencia de GNOME (`color-scheme`, que también
    siguen KDE y el portal de escritorio) o, sin ella, un tema GTK cuyo nombre
    acabe en «dark». Cualquier cosa que falle lee como claro: el oscuro es una
    preferencia, y equivocarse hacia el claro deja la ventana como estaba.

    Es un punto de sustitución para las pruebas.
    """
    import os
    try:
        if sys.platform == "win32":
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion"
                                r"\Themes\Personalize") as clave:
                return winreg.QueryValueEx(clave, "AppsUseLightTheme")[0] == 0
        if sys.platform.startswith("linux"):
            import subprocess
            try:
                salida = subprocess.run(
                    ["gsettings", "get", "org.gnome.desktop.interface",
                     "color-scheme"], capture_output=True, text=True,
                    timeout=2, stdin=subprocess.DEVNULL).stdout
                if "dark" in salida:
                    return True
                if "default" in salida or "light" in salida:
                    return False
            except (OSError, subprocess.SubprocessError):
                pass
            return os.environ.get("GTK_THEME", "").lower().endswith("dark")
    except Exception:                               # noqa: BLE001
        pass
    return False


def barra_titulo(ventana) -> None:
    """Pone oscura la barra de título de una ventana en Windows, con el tema oscuro.

    La barra la pinta el sistema y no Tk: sin esto una ventana oscura lleva
    encima una franja blanca. Es el atributo 20 de DWM
    (`DWMWA_USE_IMMERSIVE_DARK_MODE`, Windows 10 20H1 en adelante); en uno
    más viejo la llamada falla sin ruido y la barra se queda clara. No hace
    nada con el tema claro ni fuera de Windows.
    """
    if TEMA != "oscuro" or sys.platform != "win32":
        return
    try:
        import ctypes
        ventana.update_idletasks()
        hwnd = int(ventana.wm_frame(), 16)
        valor = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            ctypes.c_void_p(hwnd), 20, ctypes.byref(valor), ctypes.sizeof(valor))
    except Exception:                               # noqa: BLE001
        pass


def elegir_tema() -> str:
    """Decide el tema de este proceso, si no estaba decidido, y lo devuelve.

    Manda la variable `PRDRIVE_TEMA` (`claro` u `oscuro`) si está puesta; si
    no, el sistema (`sistema_oscuro()`).
    """
    import os
    if not _tema_elegido:
        pedido = os.environ.get("PRDRIVE_TEMA", "").strip().lower()
        if pedido not in ("claro", "oscuro"):
            pedido = "oscuro" if sistema_oscuro() else "claro"
        usar(pedido)
    return TEMA

_FAMILIAS = {
    "texto": ("Segoe UI", "Noto Sans", "DejaVu Sans", "TkDefaultFont"),
    "fuerte": ("Segoe UI Semibold", "Segoe UI", "Noto Sans", "TkDefaultFont"),
    "mono": ("Consolas", "DejaVu Sans Mono", "Menlo", "TkFixedFont"),
}
"""Las familias de letra que valen para cada papel, por orden de preferencia.

Los tamaños de `fuente()` son los de la hoja de estilo y van en PUNTOS, no en
píxeles: en puntos es Tk quien los escala si la pantalla tiene más densidad, y
en píxeles saldría todo diminuto en un portátil moderno.
"""
_elegidas: dict[str, str] = {}
"""La familia que se eligió para cada papel."""


def familia(cual: str) -> str:
    """Devuelve la primera familia instalada de las que valen para ese papel."""
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
    """Devuelve la fuente de un rol, en el formato que aceptan tanto tk como ttk."""
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


def fuente_tcl(rol: str = "texto") -> str:
    """Devuelve la misma fuente como **lista de Tcl** en una sola cadena.

    Hace falta allí donde el valor no lo pone tkinter sino la base de opciones
    (`option_add`), que guarda texto: Tcl lo parte por espacios y «Segoe UI 10»
    se lee como familia «Segoe», tamaño «UI». Ese error no aparece al crear el
    widget sino cuando ttk crea la listbox del desplegable, y entonces
    `ttk::combobox::Post` se corta y la lista no llega a abrirse.
    """
    familia_, *resto = fuente(rol)
    if " " in familia_:
        familia_ = "{%s}" % familia_
    return " ".join([familia_] + [str(x) for x in resto])


def rotulo(texto: str) -> str:
    """Devuelve un rótulo de sección: mayúsculas y letras separadas.

    Tk no sabe de `letter-spacing`, así que el espaciado se hace a mano: un
    espacio fino entre las letras de cada palabra y TRES espacios entre
    palabras. Tres y no uno porque el espacio de Segoe UI mide casi lo mismo
    que el fino, y con uno solo «ESTE PEN» se lee «ESTEPEN».
    """
    return "   ".join(" ".join(p) for p in texto.upper().split())


def ancho_rotulo(widget, *textos: str) -> int:
    """Devuelve lo que ocupa el más ancho de esos rótulos, en píxeles de esta pantalla.

    Para reservarles canalón hay que medirlos con su fuente, no contar sus
    letras. Un `width=` en un `ttk.Label` son caracteres del ancho MEDIO de la
    fuente y `rotulo()` separa las letras a mano: «Este dispositivo» sale de
    ahí con 31 caracteres, no 16. Un `width=18` calibrado con «Catálogo» (que
    espaciado son 15) parecía de sobra y cortaba el otro por la mitad.

    Se le pasan los textos SIN espaciar, los mismos que reciben `rotulo()`, y
    mide el espaciado, que es el que se pinta. Devuelve 0 si no se puede medir
    y entonces el canalón se queda en lo que pida la rejilla: un rótulo pegado
    a su fila de botones se lee, uno cortado no.
    """
    from tkinter import font as tkfont
    try:
        letra = tkfont.Font(root=widget, font=fuente("rotulo"))
        return max(letra.measure(rotulo(t)) for t in textos)
    except Exception:                                # noqa: BLE001
        return 0


def _roles() -> dict[str, tuple[str, str]]:
    """Devuelve cada rol de texto: color de letra y fuente.

    El fondo lo pone la superficie. Es una función, y no una tabla, porque los
    colores son los del tema puesto (`usar()`).
    """
    return {
        "": (TINTA, "texto"),
        "Fuerte.": (TINTA, "fuerte"),
        "Pista.": (TINTA3, "pista"),
        "Rotulo.": (TINTA3, "rotulo"),
        "Mono.": (TINTA2, "mono"),
        "MonoPista.": (TINTA3, "mono_pequena"),
        "Campo.": (TINTA2, "texto"),
        "Apagado.": (APAGADO, "pista"),
        "Titulo.": (TINTA, "titulo"),
        "Dialogo.": (TINTA, "dialogo"),
        "Seccion.": (TINTA, "seccion"),
        "Ok.": (OK, "texto"),
        "Aviso.": (AVISO, "texto"),
        "Peligro.": (PELIGRO, "texto"),
        "Acento.": (ACENTO, "texto"),
    }


def _superficies() -> dict[str, tuple[str, str | None]]:
    """Devuelve cada superficie: fondo y color de letra que manda sobre el del rol, o `None`.

    Las `Nota*` son el fondo de un aviso con baldosa (`aviso()`): ahí la letra
    es la de siempre, tinta para el título y tinta suave para el cuerpo, porque
    el color ya lo lleva la baldosa.
    """
    return {
        "": (PAPEL, None),
        "Card.": (SUPERFICIE, None),
        "Gris.": (GRIS_FONDO, None),
        "Ambar.": (AVISO_FONDO, AVISO_TEXTO),
        "Rojo.": (PELIGRO_FONDO, PELIGRO),
        "Azul.": (ACENTO_SUAVE, ACENTO_OSCURO),
        "NotaAmbar.": (AVISO_FONDO, None),
        "NotaRojo.": (PELIGRO_FONDO, None),
        "NotaAzul.": (ACENTO_SUAVE, None),
        "NotaVerde.": (OK_FONDO, None),
    }


def _chips() -> dict[str, tuple[str, str, str, str | None]]:
    """Devuelve los chips: fondo, borde, letra y color del disco de cada estado.

    El color de un estado va SOLO en el disco que el chip lleva delante (el de
    la pastilla de la bandeja); la palabra va en tinta sobre el gris hundido.
    El apagado es la excepción: sin relleno, con el disco hueco.
    """
    return {
        "": (GRIS_FONDO, LINEA, TINTA, None),
        "Ok.": (GRIS_FONDO, LINEA, TINTA, OK),
        "Aviso.": (GRIS_FONDO, LINEA, TINTA, AVISO),
        "Peligro.": (GRIS_FONDO, LINEA, TINTA, PELIGRO),
        "Acento.": (GRIS_FONDO, LINEA, TINTA, ACENTO),
        "Apagado.": (PAPEL, BORDE, TINTA3, TINTA3),
    }


def _chips_solidos() -> dict[str, tuple[str, str]]:
    """Devuelve los chips enfáticos: todo el chip del color, letra encima.

    Son para la excepción que hay que ver desde lejos (falló, borra), no para
    la norma.
    """
    return {"Ok.": (OK, SOBRE_OK), "Aviso.": (AVISO, SOBRE_AVISO),
            "Peligro.": (PELIGRO, SOBRE_PELIGRO), "Acento.": (ACENTO, SOBRE_ACENTO)}


_GLIFO_CHIP = {"Ok.": "ok", "Aviso.": "alert", "Peligro.": "close",
               "Acento.": "sync", "Apagado.": "clock"}
"""El glifo del disco de un chip de estado al que no se le da icono."""

_puestos: dict[int, object] = {}
"""Los intérpretes de Tk que ya tienen el tema, por `id`."""


def olvidar(interp) -> None:
    """Deja de recordar un intérprete ya cerrado.

    Es hermana de `icons.olvidar()` y por lo mismo: el de la ventanita del
    servicio vive en otro hilo y, si este diccionario lo retuviera, lo acabaría
    soltando el hilo principal.
    """
    if _puestos.get(id(interp)) is interp:
        del _puestos[id(interp)]
        _imagenes.pop(id(interp), None)


def _casilla_propia(widget, style) -> None:
    """Cambia el indicador del Checkbutton por el cuadrado del diseño.

    El de clam pinta una especie de aspa y no hay forma de decirle que dibuje
    un visto: lo único que deja elegir son los colores. Así que el indicador
    pasa a ser un elemento de imagen, con una imagen por estado, y el resto de
    la disposición se conserva tal cual. Si algo falla se deja el de clam: una
    casilla fea sigue marcándose y una ventana que no abre no.
    """
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


_imagenes: dict[int, list] = {}
"""Las imágenes de los elementos del tema, por intérprete: Tk no las retiene."""


def _filetes(widget, style) -> None:
    """Cambia el separador de ttk por un filete plano de 1 px del color de la línea.

    El elemento de serie pinta un surco en relieve con dos tonos sacados de su
    fondo, uno más oscuro que el otro, y el diseño pide una línea plana y
    decorativa. Se pinta con un elemento de imagen de 1×1 que se estira.
    """
    import tkinter as tk
    try:
        guardadas = _imagenes.setdefault(id(widget.tk), [])
        for estilo, color in (("TSeparator", LINEA), ("Card.TSeparator", LINEA_SUAVE)):
            img = tk.PhotoImage(master=widget, width=1, height=1)
            img.put(color, to=(0, 0))
            guardadas.append(img)
            elemento = f"Prdrive.{estilo}.filete"
            style.element_create(elemento, "image", img, border=0, sticky="nswe")
            style.layout(estilo, [(elemento, {"sticky": "nswe"})])
    except Exception:                               # noqa: BLE001
        style.configure("TSeparator", background=LINEA)
        style.configure("Card.TSeparator", background=LINEA_SUAVE)


def apply(widget) -> None:
    """Pinta el tema en el intérprete de Tk al que pertenece `widget`.

    Se hace una sola vez por intérprete (los estilos son globales dentro de
    uno) y hay más de uno a lo largo de una sesión: la ventana principal abre
    el suyo, lo cierra y el asistente abre otro.
    """
    interp = widget.tk
    if _puestos.get(id(interp)) is interp:
        return
    elegir_tema()

    from tkinter import ttk

    from . import icons
    style = ttk.Style(widget)
    try:
        style.theme_use("clam")
    except Exception:
        pass                                    # sin clam se pinta lo que haya

    borde = dict(bordercolor=BORDE, lightcolor=BORDE, darkcolor=BORDE)
    linea = dict(bordercolor=LINEA, lightcolor=LINEA, darkcolor=LINEA)

    style.configure(".", background=PAPEL, foreground=TINTA, font=fuente(),
                    focuscolor=ACENTO, troughcolor=GRIS_FONDO, **linea)

    # Superficies y textos.
    for sup, (fondo, manda) in _superficies().items():
        style.configure(f"{sup}TFrame", background=fondo)
        for rol, (color, tipo) in _roles().items():
            style.configure(f"{sup}{rol}TLabel", background=fondo,
                            foreground=manda or color, font=fuente(tipo))
        style.configure(f"{sup}TCheckbutton", background=fondo,
                        foreground=manda or TINTA)
        style.configure(f"{sup}Fuerte.TCheckbutton", background=fondo,
                        foreground=manda or TINTA, font=fuente("fuerte"))
        style.configure(f"{sup}Pista.TCheckbutton", background=fondo,
                        foreground=TINTA3, font=fuente("pista"))
        # La opción de una tarjeta que se elige entera (el «¿Dónde?» del
        # asistente): el radio con el fondo de su superficie y letra de título.
        style.configure(f"{sup}Fuerte.TRadiobutton", background=fondo,
                        foreground=manda or TINTA, font=fuente("fuerte"))
        style.map(f"{sup}Fuerte.TRadiobutton", background=[("active", fondo)])

    # La tarjeta y las franjas de color: un borde de 1 px y nada más.
    for nombre, (fondo, color) in (("Card.TFrame", (SUPERFICIE, LINEA)),
                                   ("Gris.TFrame", (GRIS_FONDO, LINEA)),
                                   ("Ambar.TFrame", (AVISO_FONDO, AVISO_BORDE)),
                                   ("Rojo.TFrame", (PELIGRO_FONDO, PELIGRO_BORDE)),
                                   ("Azul.TFrame", (ACENTO_SUAVE, ACENTO_BORDE)),
                                   ("NotaAmbar.TFrame", (AVISO_FONDO, AVISO_BORDE)),
                                   ("NotaRojo.TFrame", (PELIGRO_FONDO, PELIGRO_BORDE)),
                                   ("NotaAzul.TFrame", (ACENTO_SUAVE, ACENTO_BORDE)),
                                   ("NotaVerde.TFrame", (OK_FONDO, OK_BORDE))):
        style.configure(nombre, background=fondo, relief="solid", borderwidth=1,
                        bordercolor=color, lightcolor=color, darkcolor=color)
    # …y la misma tarjeta sin borde, para lo que ya va dentro de otra.
    for sup in ("Card.", "NotaAmbar.", "NotaRojo.", "NotaAzul.", "NotaVerde."):
        style.configure(f"Plano.{sup}TFrame", relief="flat", borderwidth=0)

    _filetes(widget, style)

    # Chips.
    style.configure("Chip.TLabel", padding=(8, 2), relief="solid", borderwidth=1,
                    font=fuente("pista"))
    for tipo, (fondo, color, letra, _disco) in _chips().items():
        style.configure(f"{tipo}Chip.TLabel", background=fondo, foreground=letra,
                        bordercolor=color, lightcolor=color, darkcolor=color)
    for tipo, (fondo, letra) in _chips_solidos().items():
        style.configure(f"Solido{tipo}Chip.TLabel", background=fondo,
                        foreground=letra, bordercolor=fondo, lightcolor=fondo,
                        darkcolor=fondo)
    # La etiqueta de capa del editor de flags: un chip aún más discreto.
    style.configure("Capa.TLabel", padding=(7, 1), relief="solid", borderwidth=1,
                    font=fuente("etiqueta"), background=GRIS_FONDO,
                    foreground=TINTA3, bordercolor=LINEA, lightcolor=LINEA,
                    darkcolor=LINEA)

    # Botones. Jerarquía: sólido (Primary) > tonal > contorno > silencioso;
    # todos en seminegrita menos el silencioso. Al pasar por encima el de
    # contorno se hunde y su borde se oscurece; el color queda para el sólido.
    def bordes(**estados):
        """El mismo mapa de estados para los tres colores del borde de clam."""
        return {k: list(estados.items())
                for k in ("bordercolor", "lightcolor", "darkcolor")}

    style.configure("TButton", background=SUPERFICIE, foreground=TINTA,
                    padding=(12, 5), relief="solid", borderwidth=1,
                    font=fuente("fuerte"), **borde)
    style.map("TButton",
              background=[("pressed", LINEA), ("active", GRIS_FONDO),
                          ("disabled", APAGADO_FONDO)],
              foreground=[("disabled", APAGADO)],
              **bordes(disabled=LINEA, active=TINTA2))

    style.configure("Primary.TButton", background=ACENTO, foreground=SOBRE_ACENTO,
                    font=fuente("fuerte"), bordercolor=ACENTO,
                    lightcolor=ACENTO, darkcolor=ACENTO)
    style.map("Primary.TButton",
              background=[("disabled", APAGADO_FONDO), ("pressed", ACENTO_OSCURO),
                          ("active", ACENTO_OSCURO)],
              foreground=[("disabled", APAGADO)],
              **bordes(disabled=LINEA, pressed=ACENTO_OSCURO,
                       active=ACENTO_OSCURO))

    style.configure("Tonal.TButton", background=ACENTO_SUAVE,
                    foreground=ACENTO_OSCURO, bordercolor=ACENTO_SUAVE,
                    lightcolor=ACENTO_SUAVE, darkcolor=ACENTO_SUAVE)
    style.map("Tonal.TButton",
              background=[("disabled", APAGADO_FONDO), ("pressed", ACENTO_BORDE),
                          ("active", ACENTO_BORDE)],
              foreground=[("disabled", APAGADO)],
              **bordes(disabled=APAGADO_FONDO, pressed=ACENTO_BORDE,
                       active=ACENTO_BORDE))

    style.configure("Danger.TButton", foreground=PELIGRO, bordercolor=PELIGRO,
                    lightcolor=PELIGRO, darkcolor=PELIGRO)
    style.map("Danger.TButton",
              background=[("disabled", APAGADO_FONDO), ("pressed", PELIGRO_FONDO),
                          ("active", PELIGRO_FONDO)],
              foreground=[("disabled", APAGADO)],
              **bordes(disabled=LINEA, active=PELIGRO, pressed=PELIGRO))

    style.configure("DangerSolid.TButton", background=PELIGRO,
                    foreground=SOBRE_PELIGRO, bordercolor=PELIGRO,
                    lightcolor=PELIGRO, darkcolor=PELIGRO)
    style.map("DangerSolid.TButton",
              background=[("disabled", APAGADO_FONDO)],
              foreground=[("disabled", APAGADO)],
              **bordes(disabled=LINEA, active=TINTA, pressed=TINTA))

    # Tamaños: el grande es la acción principal de una pantalla («Sincronizar
    # ahora»), 42 px; el pequeño, el que va dentro de una franja o una fila.
    for base in ("TButton", "Primary.TButton", "Tonal.TButton",
                 "Danger.TButton", "DangerSolid.TButton"):
        style.configure(f"Grande.{base}", padding=(24, 10))
        style.configure(f"Pequeno.{base}", padding=(10, 2))

    # El botón de texto: sin caja, solo el acento. Su fondo tiene que ser el de
    # la superficie donde cae, porque un botón sin borde que no la iguale se ve
    # como un recorte de otro color.
    for sup, fondo in (("Quiet.", PAPEL), ("CardQuiet.", SUPERFICIE),
                       ("GrisQuiet.", GRIS_FONDO)):
        style.configure(f"{sup}TButton", background=fondo, foreground=ACENTO,
                        relief="flat", borderwidth=1, padding=(8, 4),
                        font=fuente(), bordercolor=fondo, lightcolor=fondo,
                        darkcolor=fondo)
        style.map(f"{sup}TButton",
                  background=[("pressed", ACENTO_SUAVE), ("active", ACENTO_SUAVE),
                              ("disabled", fondo)],
                  bordercolor=[("active", ACENTO_SUAVE)],
                  lightcolor=[("active", ACENTO_SUAVE)],
                  darkcolor=[("active", ACENTO_SUAVE)],
                  foreground=[("disabled", APAGADO)])
    style.configure("AmbarQuiet.TButton", background=AVISO_FONDO,
                    foreground=AVISO_TEXTO, relief="flat", borderwidth=1,
                    padding=(8, 4), font=fuente(),
                    bordercolor=AVISO_FONDO, lightcolor=AVISO_FONDO,
                    darkcolor=AVISO_FONDO)
    style.map("AmbarQuiet.TButton",
              background=[("pressed", AVISO_BORDE), ("active", AVISO_BORDE)],
              bordercolor=[("active", AVISO_BORDE)],
              lightcolor=[("active", AVISO_BORDE)],
              darkcolor=[("active", AVISO_BORDE)],
              foreground=[("disabled", APAGADO)])

    # La barra lateral de «Ajustes»: filas planas del ancho de la barra; la
    # elegida, sobre el azul suave con su filete y en seminegrita.
    style.configure("Nav.TButton", background=PAPEL, foreground=TINTA,
                    relief="flat", borderwidth=1, padding=(10, 6), anchor="w",
                    font=fuente(), bordercolor=PAPEL, lightcolor=PAPEL,
                    darkcolor=PAPEL)
    style.map("Nav.TButton",
              background=[("pressed", LINEA), ("active", GRIS_FONDO)],
              **bordes(pressed=LINEA, active=GRIS_FONDO))
    style.configure("NavSel.TButton", background=ACENTO_SUAVE, foreground=TINTA,
                    relief="solid", borderwidth=1, padding=(10, 6), anchor="w",
                    font=fuente("fuerte"), bordercolor=ACENTO_BORDE,
                    lightcolor=ACENTO_BORDE, darkcolor=ACENTO_BORDE)
    style.map("NavSel.TButton", background=[("active", ACENTO_SUAVE)])

    # El grupo de botones (`grupo_botones`): radios con forma de botón; el
    # pulsado, en azul suave con el borde del acento.
    style.configure("Segmento.Toolbutton", background=SUPERFICIE, foreground=TINTA,
                    relief="solid", borderwidth=1, padding=(12, 5),
                    font=fuente("fuerte"), anchor="center", **borde)
    style.map("Segmento.Toolbutton",
              background=[("selected", ACENTO_SUAVE), ("pressed", LINEA),
                          ("active", GRIS_FONDO), ("disabled", APAGADO_FONDO)],
              foreground=[("disabled", APAGADO), ("selected", ACENTO_OSCURO)],
              **bordes(selected=ACENTO, disabled=LINEA, active=TINTA2))

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

    # Lo que se marca y lo que se escribe.
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
                          ("*TCombobox*Listbox.font", fuente_tcl())):
        try:
            raiz.option_add(opcion, valor)
        except Exception:
            pass

    # Listas, barras y demás.
    style.configure("Treeview", background=SUPERFICIE, fieldbackground=SUPERFICIE,
                    foreground=TINTA, rowheight=icons.px(widget, 28),
                    borderwidth=0, relief="flat",
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


def chip(parent, texto: str, tipo: str = "", icono: str | None = None,
         solido: bool = False):
    """Devuelve una etiqueta de estado.

    Un chip de estado lleva delante un disco del color de su tono con un glifo
    dentro, el mismo disco que la pastilla de la bandeja; la palabra va en
    tinta. Un chip neutro (un modo, un dato) no lleva disco.

    Args:
        tipo: `''`, `'Ok.'`, `'Aviso.'`, `'Peligro.'`, `'Acento.'` o
            `'Apagado.'`.
        icono: El glifo del disco; sin él, el de su tono. En un chip neutro es
            un icono pequeño en tinta suave. «warn» se dibuja como «alert»: el
            triángulo no cabe en el disco.
        solido: Todo el chip del color del tono, para la excepción que hay que
            ver desde lejos (falló, borra). No vale para `''` ni `'Apagado.'`.
    """
    from tkinter import ttk

    from . import icons

    solido = solido and tipo in _chips_solidos()
    estilo = f"{'Solido' if solido else ''}{tipo}Chip.TLabel"
    etiqueta = ttk.Label(parent, text=texto, style=estilo)
    fondo, _borde, letra, disco = _chips().get(tipo, _chips()[""])
    glifo = "alert" if icono == "warn" else icono or _GLIFO_CHIP.get(tipo)
    img = None
    if solido:
        fondo, letra = _chips_solidos()[tipo]
        img = icons.get(parent, glifo, 12, letra, fondo) if glifo else None
    elif disco is not None and glifo:
        img = icons.disco(parent, glifo, disco, _sobre(disco), fondo,
                          hueco=tipo == "Apagado.")
    elif icono:
        img = icons.get(parent, icono, 12, TINTA2, fondo)
    if img is not None:
        etiqueta.configure(image=img, compound="left",
                           padding=(2 if disco is not None and not solido else 6,
                                    1, 8, 1))
        etiqueta.image = img            # Tk no se queda con la referencia
    return etiqueta


def _sobre(color: str) -> str:
    """Devuelve la letra que va sobre un relleno de ese color del tema."""
    return {OK: SOBRE_OK, AVISO: SOBRE_AVISO, PELIGRO: SOBRE_PELIGRO,
            ACENTO: SOBRE_ACENTO}.get(color, SUPERFICIE)


_NOTAS = {"Ambar.": ("NotaAmbar.", "alert", "AVISO", "SOBRE_AVISO"),
          "Rojo.": ("NotaRojo.", "close", "PELIGRO", "SOBRE_PELIGRO"),
          "Azul.": ("NotaAzul.", "doctor", "ACENTO", "SOBRE_ACENTO"),
          "Verde.": ("NotaVerde.", "ok", "OK", "SOBRE_OK")}
"""Cada tono de aviso: su superficie, su glifo y los nombres de sus colores.

Van por nombre y no por valor porque los valores son los del tema puesto.
"""


def aviso(parent, titulo: str, cuerpo: str = "", tono: str = "Ambar.",
          icono: str | None = None, ancho: int = 480):
    """Devuelve un aviso: una baldosa de color con su glifo, título y cuerpo.

    La baldosa es la de la marca, sólida y del color del tono; el título va en
    tinta y en seminegrita, y el cuerpo en tinta suave, todo sobre el fondo
    suave del tono. Es la franja que pide atención (un espejo que borra, una
    actualización que hay); la que solo informa sigue siendo una pista.

    Args:
        tono: `'Ambar.'`, `'Rojo.'`, `'Azul.'` o `'Verde.'`.
        icono: El glifo de la baldosa; sin él, el de su tono.
        ancho: Dónde se corta el texto, en píxeles del diseño.

    Returns:
        El marco del aviso. Su columna 1 se estira, y quien quiera añadirle
        botones los pone en la fila 2 de esa columna (`marco.acciones`, un
        marco ya colocado, vacío hasta entonces).
    """
    from tkinter import ttk

    from . import icons

    sup, glifo, color, sobre = _NOTAS[tono]
    fondo = _superficies()[sup][0]
    marco = ttk.Frame(parent, style=f"{sup}TFrame", padding=(12, 10, 16, 10))
    marco.columnconfigure(1, weight=1)
    icono = "alert" if icono == "warn" else icono
    img = icons.baldosa(marco, icono or glifo, globals()[color],
                        globals()[sobre], fondo)
    if img is not None:
        baldosa = ttk.Label(marco, image=img, style=f"{sup}TLabel")
        baldosa.image = img
        baldosa.grid(row=0, column=0, rowspan=3, sticky="nw", padx=(0, 12))
    # Sin título, el cuerpo hace de texto principal: en tinta, y centrado con
    # la baldosa si cabe en una línea (el alto mínimo de la fila es el suyo).
    marco.rowconfigure(0, minsize=icons.px(marco, 32) if not titulo else 0)
    if titulo:
        ttk.Label(marco, text=titulo, style=f"{sup}Fuerte.TLabel",
                  wraplength=medida(ancho), justify="left").grid(
            row=0, column=1, sticky="w", pady=(6 if not cuerpo else 0, 0))
    if cuerpo:
        ttk.Label(marco, text=cuerpo,
                  style=f"{sup}{'Campo.' if titulo else ''}TLabel",
                  wraplength=medida(ancho), justify="left").grid(
            row=1 if titulo else 0, column=1, sticky="w",
            pady=(4, 0) if titulo else 0)
    marco.acciones = ttk.Frame(marco, style=f"Plano.{sup}TFrame")
    marco.acciones.grid(row=2, column=1, sticky="w")
    marco.superficie = sup
    return marco


def linea_estado(parent, icono: str, texto: str, accion: str | None = None,
                 orden=None, tono: str = "", ancho: int = 380):
    """Devuelve una línea de estado: icono, frase y, a la derecha, una acción.

    Es la del llavero y la del arranque de la ventana principal: un filete
    arriba, el icono en gris y la frase en tinta suave. Con `tono='Ambar.'` la
    línea entera se pone sobre el fondo ámbar y el icono pasa a ir en un disco,
    para lo que hay que atender.

    Returns:
        El marco. La acción, si la hay, queda en `marco.boton`.
    """
    from tkinter import ttk

    from . import icons

    ambar = tono == "Ambar."
    fondo = AVISO_FONDO if ambar else PAPEL
    sup = "NotaAmbar." if ambar else ""
    marco = ttk.Frame(parent, style=f"Plano.{sup}TFrame" if ambar else "TFrame")
    marco.columnconfigure(1, weight=1)
    ttk.Separator(marco).grid(row=0, column=0, columnspan=3, sticky="ew")
    if ambar:
        img = icons.disco(marco, "alert" if icono == "warn" else icono, AVISO,
                          SOBRE_AVISO, fondo)
    else:
        img = icons.get(marco, icono, 16, TINTA3, fondo)
    if img is not None:
        dibujo = ttk.Label(marco, image=img, style=f"{sup}TLabel")
        dibujo.image = img
        dibujo.grid(row=1, column=0, sticky="w", padx=(12, 12), pady=8)
    ttk.Label(marco, text=texto, style=f"{sup}{'' if ambar else 'Campo.'}TLabel",
              wraplength=medida(ancho), justify="left").grid(
        row=1, column=1, sticky="w", pady=8)
    marco.boton = None
    if accion:
        marco.boton = ttk.Button(marco, text=accion, command=orden,
                                 style="AmbarQuiet.TButton" if ambar
                                 else "Quiet.TButton")
        marco.boton.grid(row=1, column=2, sticky="e", padx=(8, 4))
    return marco


def grupo_botones(parent, opciones, variable, orden=None, superficie: str = ""):
    """Devuelve un grupo de botones pegados donde solo uno está pulsado.

    Es el `ButtonGroup` del diseño: hace lo que un desplegable de pocas
    opciones, pero las enseña todas. Son radios de ttk con la forma de botón
    (`Segmento.Toolbutton`), así que la elegida es el valor de `variable`.

    Args:
        opciones: `(rotulo, valor)` por botón, en orden.
        variable: La `StringVar` que guarda el valor elegido.
        orden: Lo que se llama al cambiar de botón, o `None`.
        superficie: El prefijo de la superficie donde cae (`'Card.'`…), para
            que el marco tenga su fondo.

    Returns:
        El marco, con los botones en `marco.botones`.
    """
    from tkinter import ttk
    marco = ttk.Frame(parent, style=f"Plano.{superficie}TFrame" if superficie
                      else "TFrame")
    marco.botones = []
    for i, (rotulo, valor) in enumerate(opciones):
        boton = ttk.Radiobutton(marco, text=rotulo, value=valor, variable=variable,
                                command=orden, style="Segmento.Toolbutton",
                                takefocus=True)
        boton.grid(row=0, column=i, sticky="ns")
        marco.botones.append(boton)
    return marco


def boton_icono(boton, nombre: str, color: str | None = None,
                fondo: str | None = None, size: int = 15):
    """Le pone un icono a la izquierda del texto a un botón ya creado y lo devuelve.

    El icono va bajado un poco dentro de su propia imagen. ttk la centra en la
    caja de la línea (ascenso + descenso), pero el texto no ocupa esa caja: sus
    mayúsculas empiezan bastante por debajo del ascenso, que reserva sitio para
    las tildes (y en castellano se usan). Ese hueco de arriba deja la masa del
    texto más baja que el centro de la caja y el icono se veía flotando por
    encima: medido sobre la ventana de verdad, 1 px a 96 ppp.

    La imagen se hace tan alta como la línea y el dibujo se baja el descenso,
    sin pasarse de lo que quepa. Dando la altura entera el botón no crece (si
    creciera volvería a mover el texto y no se llegaría nunca) y el descenso es
    la medida que Tk sí da y que acompaña al tamaño de la fuente.

    Si el icono no se puede pintar el botón se queda con su texto y ya está: un
    adorno no puede dejar sin usar una acción.
    """
    from tkinter import font as tkfont
    from . import icons
    color, fondo = color or TINTA, fondo or PAPEL
    real, alto, bajar = icons.px(boton, size), None, 0
    try:
        m = tkfont.Font(root=boton, font=fuente("normal")).metrics()
        alto = max(m["linespace"], real)
        bajar = max(0, min(m["descent"], alto - real))
    except Exception:                           # noqa: BLE001
        alto = None                             # sin métricas, como estaba
    img = icons.get(boton, nombre, size, color, fondo, bajar=bajar, alto=alto)
    if img is not None:
        boton.configure(image=img, compound="left")
        boton.image = img
    return boton


def caja_texto(parent, **kw):
    """Devuelve un `tk.Text` con la ropa del diseño.

    Sigue siendo un `tk.Text` pelado: lo que se le pide es un fondo blanco, un
    borde de 1 px y la monoespaciada.
    """
    import tkinter as tk
    opciones = dict(background=SUPERFICIE, foreground=TINTA, font=fuente("mono"),
                    relief="flat", borderwidth=0, highlightthickness=1,
                    highlightbackground=BORDE, highlightcolor=ACENTO,
                    insertbackground=TINTA, selectbackground=ACENTO_SUAVE,
                    selectforeground=TINTA, padx=8, pady=6, wrap="none")
    opciones.update(kw)
    return tk.Text(parent, **opciones)


def marcar_lista(tree) -> None:
    """Configura los colores de fila de una lista de parejas, por estado.

    El diseño pide un chip de color en la columna de estado y una
    `ttk.Treeview` no sabe pintar una celda suelta, así que el color va a la
    fila entera: fondo para lo que hay que mirar (ámbar si pide un resync, rojo
    si es un espejo que borra) y letra gris para lo que está ahí pero este
    dispositivo no usa. Fondo y no letra porque una ruta monoespaciada en ámbar
    se lee peor y porque así el azul de la fila elegida sigue viéndose encima.
    """
    tree.tag_configure("ok", background=SUPERFICIE, foreground=TINTA)
    tree.tag_configure("aviso", background=AVISO_FONDO, foreground=TINTA)
    tree.tag_configure("peligro", background=PELIGRO_FONDO, foreground=PELIGRO)
    tree.tag_configure("apagado", background=SUPERFICIE, foreground=TINTA3,
                       font=(familia("texto"), 10, "italic"))
