#!/usr/bin/env python3
"""El sistema visual del rediseño, traducido a ttk.

Papel cálido, tinta casi negra y un solo acento azul; el vocabulario que la
aplicación ya tenía (gris para las pistas, ámbar para los avisos, monoespaciada
para rutas y flags) con forma, y la letra del diseño, que viaja con el programa
(`cargar_fuentes()`).

Los controles que el diseño redondea (botones, campos, tarjetas, avisos,
chips) no los pinta clam: son elementos de imagen con piezas que dibuja
`icons.caja()` con los colores de aquí («Los controles dibujados», más abajo).
Sin sombras: no hacen falta en una ventana plana.

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

import re
import sys
from pathlib import Path

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
    cargar_fuentes()                # también antes del primer Tk(): ver allí
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


FUENTES = Path(__file__).resolve().parent / "fuentes"
"""La letra que viaja con el programa: Noto Sans y Noto Sans Mono.

Son de la licencia SIL Open Font License (`fuentes/OFL.txt`), que deja
llevarlas dentro de un programa y recortarlas. Van recortadas a los alfabetos
latinos, la puntuación, las flechas y los dibujos de caja: lo que escribe la
interfaz. Un carácter que no esté lo pinta el sistema con la letra que tenga,
como antes.
"""

_FAMILIAS_PROPIAS = ("Noto Sans", "Noto Sans SemiBold", "Noto Sans Mono")
"""Las familias que ponen los ficheros de `FUENTES`, una vez cargados."""

_fuentes_cargadas: bool | None = None
"""`None` si aún no se intentó; si no, si la letra propia está disponible."""


def cargar_fuentes() -> bool:
    """Hace que la letra de `FUENTES` la vea este proceso, sin instalarla, y dice si lo logró.

    Es **privada del proceso**: no se instala nada en el equipo, no pide
    permisos y desaparece al cerrar. En Windows es `AddFontResourceExW` con
    `FR_PRIVATE`; en Linux, `FcConfigAppFontAddFile` de fontconfig, que es de
    donde saca la letra el Tk de X11 (Xft). En otro sistema, o si algo falla,
    no se carga nada y `familia()` se queda con la del sistema: la letra es un
    adorno y no puede impedir que se abra la ventana.

    Tiene que correr antes del primer `Tk()` por lo mismo que `nitidez()`, que
    la llama; `apply()` la vuelve a llamar por si se entró por otro sitio. Es de
    proceso, así que basta una vez.
    """
    global _fuentes_cargadas
    if _fuentes_cargadas is not None:
        return _fuentes_cargadas
    _fuentes_cargadas = False
    try:
        ficheros = sorted(FUENTES.glob("*.ttf"))
        if not ficheros:
            return False
        import ctypes
        if sys.platform == "win32":
            gdi = ctypes.windll.gdi32
            gdi.AddFontResourceExW.argtypes = (ctypes.c_wchar_p, ctypes.c_uint,
                                               ctypes.c_void_p)
            hechos = [gdi.AddFontResourceExW(str(f), 0x10, None)  # FR_PRIVATE
                      for f in ficheros]
        elif sys.platform.startswith("linux"):
            import ctypes.util
            fc = ctypes.CDLL(ctypes.util.find_library("fontconfig")
                             or "libfontconfig.so.1")
            fc.FcConfigAppFontAddFile.argtypes = (ctypes.c_void_p, ctypes.c_char_p)
            hechos = [fc.FcConfigAppFontAddFile(None, bytes(f))
                      for f in ficheros]
        else:
            return False
        _fuentes_cargadas = all(hechos)
    except Exception:                               # noqa: BLE001
        _fuentes_cargadas = False
    return _fuentes_cargadas


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


E1, E2, E3, E4, E5, E6, E7 = (medida(n) for n in (4, 8, 12, 16, 24, 32, 48))
"""La escala de espacios del diseño (`space-1` … `space-7`), en puntos.

Todo hueco entre cosas sale de aquí y de ningún otro número: `padx=(E2, 0)`,
`padding=(E4, E3)`. Para qué es cada uno, según el sistema de diseño:

- `E1` (4): entre un rótulo y su campo; dentro de un chip.
- `E2` (8): entre botones de una fila; entre un icono y su texto.
- `E3` (12): entre filas de un formulario; el relleno de un aviso.
- `E4` (16): el relleno de una tarjeta; el margen de una ventana.
- `E5` (24): entre bloques de una pantalla.
- `E6` (32): entre secciones; arriba de un diálogo.
- `E7` (48): el aire de un estado vacío.

Van en puntos (`medida`) y no en píxeles para que crezcan con la letra en una
pantalla densa, como el resto.
"""

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
    "texto": ("Noto Sans", "Segoe UI", "DejaVu Sans", "TkDefaultFont"),
    "fuerte": ("Noto Sans SemiBold", "Segoe UI Semibold", "Segoe UI",
               "Noto Sans", "TkDefaultFont"),
    "mono": ("Noto Sans Mono", "Consolas", "DejaVu Sans Mono", "Menlo",
             "TkFixedFont"),
}
"""Las familias de letra que valen para cada papel, por orden de preferencia.

La primera es la que viaja con el programa (`FUENTES`), así que se ve igual en
todos los equipos; las siguientes son las de la hoja de estilo, por si no se
pudo cargar. La seminegrita va como familia aparte («Noto Sans SemiBold»)
porque Tk solo sabe pedir normal o negrita, y el diseño quiere el peso de en
medio.

Los tamaños de `fuente()` son los de la hoja de estilo y van en PUNTOS, no en
píxeles: en puntos es Tk quien los escala si la pantalla tiene más densidad, y
en píxeles saldría todo diminuto en un portátil moderno.
"""
_elegidas: dict[str, str] = {}
"""La familia que se eligió para cada papel."""


def familia(cual: str) -> str:
    """Devuelve la primera familia instalada de las que valen para ese papel.

    Las propias cuentan como instaladas si se cargaron: la seminegrita no sale
    en la lista de Tk en Linux, que da solo el primer nombre de cada fichero
    («Noto Sans»), y sin embargo fontconfig la encuentra por el segundo.
    """
    if cual not in _elegidas:
        from tkinter import font
        try:
            hay = set(font.families())
        except Exception:                       # sin Tk montado todavía
            hay = set()
        if cargar_fuentes():
            hay.update(_FAMILIAS_PROPIAS)
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


def fondo_de(superficie: str) -> str:
    """Devuelve el color de fondo de una superficie (`'Card.'`, `'NotaAzul.'`…)."""
    return _superficies().get(superficie, _superficies()[""])[0]


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
        _sobres.pop(id(interp), None)


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


# ---------------------------------------------------------------------------
# Los controles dibujados: piezas de imagen con esquinas redondeadas.
#
# clam pinta cajas de bordes rectos, y ese era el límite del tema. Aquí cada
# control que el diseño redondea (botones, campos, tarjetas, avisos, chips)
# deja de pintarse con los elementos de clam y pasa a ser un ELEMENTO DE
# IMAGEN: una pieza pequeña que `icons.caja()` dibuja con los colores del tema
# y que ttk parte en nueve trozos para estirarla al tamaño del control. Una
# pieza por estado (normal, encima, pulsado, foco, desactivado).
#
# Las piezas son transparentes por fuera de la forma y ttk rellena el control
# con su `background` antes de pintarlas, así que lo que asoma por las esquinas
# es el `background` del estilo. Tiene que ser el color de la superficie donde
# cae el control, y eso solo se sabe al ponerlo: lo hace `_asentar()`, que
# mira el fondo del padre cuando el control aparece y, si no es el papel, le
# pone una variante del estilo con ese fondo («Sobre<color>.<estilo>»). Nadie
# tiene que acordarse de pedir el botón «de tarjeta».
# ---------------------------------------------------------------------------

RADIO = 4
"""El radio de botones, campos, tarjetas y avisos (`radius-md`)."""
RADIO_PILDORA = 10
"""El de los chips de estado, que acaban redondos (`radius-pill`) a su alto."""
RADIO_FINO = 2
"""El de la etiqueta de capa y la barra de progreso (`radius-sm`)."""

_REDONDOS: dict[str, bool] = {}
"""Por estilo, si lleva piezas con esquinas transparentes y hay que asentarlo.

Un `False` corta la búsqueda por sufijos de `_redondo()`: «Plano.Card.TFrame»
termina como la tarjeta, pero es plano y no se asienta.
"""
_CARA: dict[str, str] = {}
"""Los marcos con cara de imagen: el color que enseñan a sus hijos.

Su `background` es el de DEBAJO (asoma por las esquinas), así que no sirve
para saber sobre qué color caen los controles de dentro.
"""

_sobres: dict[int, set[str]] = {}
"""Las variantes «Sobre…» ya creadas, por intérprete (ver `_asentar`)."""

_SOBRE = re.compile(r"^Sobre[0-9A-F]{6}\.")
"""El prefijo que pone `_asentar()`."""


def _redondo(estilo: str) -> bool:
    """Dice si un estilo, o el del que hereda por su nombre, lleva piezas redondeadas."""
    partes = estilo.split(".")
    for i in range(len(partes)):
        valor = _REDONDOS.get(".".join(partes[i:]))
        if valor is not None:
            return valor
    return False


def _hex(widget, color: str) -> str | None:
    """Devuelve un color de Tk como «#RRGGBB» en mayúsculas, o `None`."""
    try:
        r, g, b = widget.winfo_rgb(color)
    except Exception:                               # noqa: BLE001
        return None
    return "#%02X%02X%02X" % (r // 257, g // 257, b // 257)


def _fondo_de(padre) -> str | None:
    """Devuelve el color sobre el que caen los hijos de `padre`."""
    from tkinter import TclError, ttk
    try:
        estilo = str(padre.cget("style")) or padre.winfo_class()
    except TclError:                                # un widget de tk, sin estilo
        try:
            return _hex(padre, padre.cget("background"))
        except TclError:
            return None
    base = _SOBRE.sub("", estilo)
    if base in _CARA:
        return _CARA[base]
    return _hex(padre, ttk.Style(padre).lookup(estilo, "background"))


def _asentar(evento) -> None:
    """Le da a un control redondeado el fondo de la superficie donde ha caído.

    Corre al aparecer cada control (`<Map>` de su clase) y solo toca los que
    llevan piezas redondeadas. Si el fondo del padre es el del estilo, no hace
    nada; si no, le pone «Sobre<color>.<estilo>», que hereda todo del estilo
    por el nombre y solo cambia el `background`. Nada de aquí puede romper una
    ventana: si algo falla, las esquinas se quedan del color del papel.
    """
    w = evento.widget
    if isinstance(w, str):                          # un widget que tkinter no creó
        return
    try:
        from tkinter import ttk
        estilo = str(w.cget("style")) or w.winfo_class()
        base = _SOBRE.sub("", estilo)
        if not _redondo(base):
            return
        fondo = _fondo_de(w.master)
        if fondo is None:
            return
        style = ttk.Style(w)
        nuevo = base
        if _hex(w, style.lookup(base, "background")) != fondo:
            nuevo = f"Sobre{fondo[1:]}.{base}"
            # Una sola vez por intérprete: cada `style.configure` le dice a
            # TODOS los widgets que el tema ha cambiado y se vuelven a medir.
            # Hecho en cada `<Map>`, una ventana de cientos de controles
            # tardaba más de un minuto en aparecer.
            hechos = _sobres.setdefault(id(w.tk), set())
            if nuevo not in hechos:
                style.configure(nuevo, background=fondo)
                hechos.add(nuevo)
        if nuevo != estilo:
            w.configure(style=nuevo)
    except Exception:                               # noqa: BLE001
        pass


def _pieza(widget, style, nombre: str, estados, radio: float = RADIO,
           esquinas: str = "1111", **opciones) -> None:
    """Crea el elemento de imagen `nombre`, con una pieza por estado.

    Args:
        estados: `(estado, tonos)` por pieza, en el orden en que ttk las
            prueba (la primera que encaje gana); `estado` es una tupla de
            nombres de estado. La última es la de por defecto y su estado se
            ignora. `tonos` es lo que recibe `icons.caja()`.
        opciones: Las de `element create` (`padding`, `sticky`…).

    Raises:
        RuntimeError: Si una pieza no se puede pintar; quien llama deja ese
            control como lo pinta clam.
    """
    from . import icons
    guardadas = _imagenes.setdefault(id(widget.tk), [])
    piezas, borde = [], 0
    for estado, tonos in estados:
        img, borde = icons.caja(widget, tonos, radio, esquinas)
        if img is None:
            raise RuntimeError(f"no se pudo pintar {nombre}")
        guardadas.append(img)
        piezas.append((estado, img))
    *especiales, (_, defecto) = piezas
    opciones.setdefault("padding", icons.px(widget, 1))
    opciones.setdefault("sticky", "nswe")
    # El mínimo del control son sus bordes, no lo que mide la pieza: su centro
    # es grande a propósito (`icons.CENTRO_ANCHO`), y sin esto cada botón
    # mediría eso como poco.
    opciones.setdefault("width", 2 * borde)
    opciones.setdefault("height", 2 * borde)
    style.element_create(nombre, "image", defecto,
                         *[(*estado, img) for estado, img in especiales],
                         border=borde, **opciones)


def _tonos(relleno: str | None, borde: str | None = None) -> list:
    """Los tonos de una caja: el borde de 1 px por fuera y el relleno dentro."""
    if borde is None or borde == relleno:
        return [(relleno, 0)]
    return [(borde, 0), (relleno, 1)]


def _foco(relleno: str | None, borde: str | None, anillo: str | None) -> list:
    """Los tonos de la misma caja con el foco del teclado.

    El anillo va por DENTRO, 2 px del acento en lugar del borde: por fuera
    haría falta reservar sitio alrededor de cada control. En un control
    relleno del propio acento el anillo no se vería, y ahí va un filete de la
    letra (`anillo`) a 1 px del canto.
    """
    if anillo:
        return [(relleno, 0), (anillo, 1), (relleno, 2)]
    return [(ACENTO, 0), (relleno, 2)]


def _botones_propios(widget, style) -> None:
    """Los botones: una pieza por estado, del diseño (`.pd-btn`)."""
    # normal, encima, pulsado y desactivado, cada uno (relleno, borde); el
    # último, el color del anillo de foco si el botón va relleno del acento.
    apagado = (APAGADO_FONDO, LINEA)
    nada = (None, None)
    botones = {
        "TButton": ((SUPERFICIE, BORDE), (GRIS_FONDO, TINTA2), (LINEA, TINTA2),
                    apagado, None),
        "Primary.TButton": ((ACENTO, None), (ACENTO_OSCURO, None),
                            (ACENTO_OSCURO, None), apagado, SOBRE_ACENTO),
        "Tonal.TButton": ((ACENTO_SUAVE, None), (ACENTO_BORDE, None),
                          (ACENTO_BORDE, None), (APAGADO_FONDO, None), None),
        "Danger.TButton": ((SUPERFICIE, PELIGRO), (PELIGRO_FONDO, PELIGRO),
                           (PELIGRO_FONDO, PELIGRO), apagado, None),
        "DangerSolid.TButton": ((PELIGRO, None), (PELIGRO, TINTA),
                                (PELIGRO, TINTA), apagado, SOBRE_PELIGRO),
        "Ambar.TButton": ((SUPERFICIE, AVISO_BORDE_BOTON), (AVISO_FONDO, AVISO),
                          (AVISO_FONDO, AVISO), apagado, None),
        "AmbarDanger.TButton": ((SUPERFICIE, AVISO_BORDE_BOTON),
                                (AVISO_FONDO, PELIGRO), (AVISO_FONDO, PELIGRO),
                                apagado, None),
        "Quiet.TButton": (nada, (ACENTO_SUAVE, None), (ACENTO_SUAVE, None),
                          nada, None),
        "CardQuiet.TButton": (nada, (ACENTO_SUAVE, None), (ACENTO_SUAVE, None),
                              nada, None),
        "GrisQuiet.TButton": (nada, (ACENTO_SUAVE, None), (ACENTO_SUAVE, None),
                              nada, None),
        "AmbarQuiet.TButton": (nada, (AVISO_BORDE, None), (AVISO_BORDE, None),
                               nada, None),
        "Nav.TButton": (nada, (GRIS_FONDO, None), (LINEA, None), nada, None),
        "NavSel.TButton": ((ACENTO_SUAVE, ACENTO_BORDE), (ACENTO_SUAVE, ACENTO_BORDE),
                           (ACENTO_SUAVE, ACENTO_BORDE), apagado, None),
    }
    for estilo, (normal, encima, pulsado, quieto, anillo) in botones.items():
        try:
            elemento = f"Prdrive.{estilo}.cara"
            _pieza(widget, style, elemento, [
                (("disabled",), _tonos(*quieto)),
                (("pressed", "focus"), _foco(pulsado[0], pulsado[1], anillo)),
                (("pressed",), _tonos(*pulsado)),
                (("active", "focus"), _foco(encima[0], encima[1], anillo)),
                (("active",), _tonos(*encima)),
                (("focus",), _foco(normal[0], normal[1], anillo)),
                ((), _tonos(*normal))])
            style.layout(estilo, [(elemento, {"sticky": "nswe", "children": [
                ("Button.padding", {"sticky": "nswe", "children": [
                    ("Button.label", {"sticky": "nswe"})]})]})])
            # El fondo ya no es la cara del botón: es lo que asoma por las
            # esquinas. La cara la ponen las piezas, por estado.
            if not estilo.endswith("Quiet.TButton"):
                style.configure(estilo, background=PAPEL)
            if normal[0] is not None:
                # Lo que se pone ENCIMA de un botón (el chip de una fila de
                # la barra lateral) cae sobre su cara, no sobre su fondo.
                _CARA[estilo] = normal[0]
            style.map(estilo, background=[], bordercolor=[], lightcolor=[],
                      darkcolor=[])
            _REDONDOS[estilo] = True
        except Exception:                           # noqa: BLE001
            pass                                    # se queda el de clam


def _segmentos_propios(widget, style) -> None:
    """El grupo de botones: el primero y el último redondeados por fuera.

    Los de en medio no llevan borde a la izquierda: el borde derecho del de
    antes hace de separador, como el `margin-left: -1px` del diseño.
    """
    formas = {"Segmento.Toolbutton": ("1111", 1),
              "Primero.Segmento.Toolbutton": ("1001", 1),
              "Medio.Segmento.Toolbutton": ("0000", (0, 1, 1, 1)),
              "Ultimo.Segmento.Toolbutton": ("0110", (0, 1, 1, 1))}
    for estilo, (esquinas, dentro) in formas.items():
        try:
            def caja(relleno, borde, ancho=dentro):
                """Borde por fuera y relleno metido `ancho`."""
                return [(borde, 0), (relleno, ancho)]
            elemento = f"Prdrive.{estilo}.cara"
            _pieza(widget, style, elemento, [
                (("disabled",), caja(APAGADO_FONDO, LINEA)),
                (("selected", "focus"), caja(ACENTO_SUAVE, ACENTO, 2)),
                (("selected",), caja(ACENTO_SUAVE, ACENTO, 1)),
                (("pressed",), caja(LINEA, TINTA2)),
                (("active", "focus"), caja(GRIS_FONDO, ACENTO, 2)),
                (("active",), caja(GRIS_FONDO, TINTA2)),
                (("focus",), caja(SUPERFICIE, ACENTO, 2)),
                ((), caja(SUPERFICIE, BORDE))], esquinas=esquinas)
            style.layout(estilo, [(elemento, {"sticky": "nswe", "children": [
                ("Toolbutton.padding", {"sticky": "nswe", "children": [
                    ("Toolbutton.label", {"sticky": "nswe"})]})]})])
            style.configure(estilo, background=PAPEL)
            style.map(estilo, background=[], bordercolor=[], lightcolor=[],
                      darkcolor=[])
            _REDONDOS[estilo] = True
        except Exception:                           # noqa: BLE001
            pass


def _campos_propios(widget, style) -> None:
    """Los campos (entrada, desplegable, numérico) y sus flechas.

    Las flechas de clam son cajas con borde y relleno propios; las del diseño
    son un galón suelto dentro del campo. Se llaman como las de clam
    («…downarrow», «…uparrow») porque los bindings de ttk deciden por ese
    nombre si el clic cae en la flecha.
    """
    from . import icons
    campo = [(("disabled",), _tonos(APAGADO_FONDO, LINEA)),
             (("invalid", "focus"), [(PELIGRO, 0), (SUPERFICIE, 2)]),
             (("invalid",), _tonos(SUPERFICIE, PELIGRO)),
             (("focus",), [(ACENTO, 0), (SUPERFICIE, 2)]),
             ((), _tonos(SUPERFICIE, BORDE))]
    guardadas = _imagenes.setdefault(id(widget.tk), [])

    def flecha(nombre, glifo, size, **opciones):
        """Un galón como elemento, gris y apagado al desactivar."""
        normal = icons.get(widget, glifo, size, TINTA3)
        quieto = icons.get(widget, glifo, size, APAGADO)
        if normal is None or quieto is None:
            raise RuntimeError(f"no se pudo pintar {nombre}")
        guardadas.extend((normal, quieto))
        style.element_create(nombre, "image", normal, ("disabled", quieto),
                             sticky="", **opciones)

    try:
        _pieza(widget, style, "Prdrive.Entry.field", campo)
        style.layout("TEntry", [("Prdrive.Entry.field", {"sticky": "nswe", "children": [
            ("Entry.padding", {"sticky": "nswe", "children": [
                ("Entry.textarea", {"sticky": "nswe"})]})]})])
        _REDONDOS["TEntry"] = True
    except Exception:                               # noqa: BLE001
        pass
    try:
        _pieza(widget, style, "Prdrive.Combobox.field", campo)
        flecha("Prdrive.Combobox.downarrow", "abajo", 12,
               width=icons.px(widget, 26))
        style.layout("TCombobox", [("Prdrive.Combobox.field", {
            "sticky": "nswe", "children": [
                ("Prdrive.Combobox.downarrow", {"side": "right", "sticky": "ns"}),
                ("Combobox.padding", {"expand": "1", "sticky": "nswe", "children": [
                    ("Combobox.textarea", {"sticky": "nswe"})]})]})])
        _REDONDOS["TCombobox"] = True
    except Exception:                               # noqa: BLE001
        pass
    try:
        _pieza(widget, style, "Prdrive.Spinbox.field", campo)
        flecha("Prdrive.Spinbox.uparrow", "arriba", 10, width=icons.px(widget, 20))
        flecha("Prdrive.Spinbox.downarrow", "abajo", 10, width=icons.px(widget, 20))
        style.layout("TSpinbox", [("Prdrive.Spinbox.field", {
            "side": "top", "sticky": "we", "children": [
                ("null", {"side": "right", "sticky": "", "children": [
                    ("Prdrive.Spinbox.uparrow", {"side": "top", "sticky": "e"}),
                    ("Prdrive.Spinbox.downarrow", {"side": "bottom", "sticky": "e"})]}),
                ("Spinbox.padding", {"sticky": "nswe", "children": [
                    ("Spinbox.textarea", {"sticky": "nswe"})]})]})])
        _REDONDOS["TSpinbox"] = True
    except Exception:                               # noqa: BLE001
        pass
    for nombre in ("TEntry", "TCombobox", "TSpinbox"):
        if _REDONDOS.get(nombre):
            style.configure(nombre, background=PAPEL)
            style.map(nombre, fieldbackground=[], bordercolor=[], lightcolor=[],
                      darkcolor=[])


def _marcos_propios(widget, style) -> None:
    """Las tarjetas y los avisos: borde de 1 px y esquinas de 4.

    Su `background` pasa a ser el de debajo y el color que enseñan se apunta
    en `_CARA`. La variante «Plano.» sigue siendo un rectángulo del color de
    la tarjeta, sin borde: va dentro de otra.
    """
    marcos = {"Card.TFrame": (SUPERFICIE, LINEA), "Gris.TFrame": (GRIS_FONDO, LINEA),
              "Ambar.TFrame": (AVISO_FONDO, AVISO_BORDE),
              "Rojo.TFrame": (PELIGRO_FONDO, PELIGRO_BORDE),
              "Azul.TFrame": (ACENTO_SUAVE, ACENTO_BORDE),
              "NotaAmbar.TFrame": (AVISO_FONDO, AVISO_BORDE),
              "NotaRojo.TFrame": (PELIGRO_FONDO, PELIGRO_BORDE),
              "NotaAzul.TFrame": (ACENTO_SUAVE, ACENTO_BORDE),
              "NotaVerde.TFrame": (OK_FONDO, OK_BORDE)}
    for estilo, (fondo, borde) in marcos.items():
        try:
            elemento = f"Prdrive.{estilo}.cara"
            _pieza(widget, style, elemento, [((), _tonos(fondo, borde))])
            style.layout(estilo, [(elemento, {"sticky": "nswe"})])
            style.configure(estilo, background=PAPEL)
            _CARA[estilo] = fondo
            _REDONDOS[estilo] = True
            plano = f"Plano.{estilo}"
            style.layout(plano, [("Frame.border", {"sticky": "nswe"})])
            style.configure(plano, background=fondo, relief="flat", borderwidth=0)
            _REDONDOS[plano] = False
        except Exception:                           # noqa: BLE001
            pass


def _chips_propios(widget, style) -> None:
    """Los chips: píldoras con su borde; la etiqueta de capa, apenas redondeada."""
    piezas = {f"{tipo}Chip.TLabel": (_tonos(fondo, borde) if fondo != PAPEL
                                     else [(borde, 0), (None, 1)], RADIO_PILDORA)
              for tipo, (fondo, borde, _letra, _disco) in _chips().items()}
    piezas.update({f"Solido{tipo}Chip.TLabel": ([(fondo, 0)], RADIO_PILDORA)
                   for tipo, (fondo, _letra) in _chips_solidos().items()})
    piezas["Capa.TLabel"] = (_tonos(GRIS_FONDO, LINEA), RADIO_FINO)
    for estilo, (tonos, radio) in piezas.items():
        try:
            elemento = f"Prdrive.{estilo}.cara"
            _pieza(widget, style, elemento, [((), tonos)], radio=radio)
            style.layout(estilo, [(elemento, {"sticky": "nswe", "children": [
                ("Label.padding", {"sticky": "nswe", "children": [
                    ("Label.label", {"sticky": "nswe"})]})]})])
            style.configure(estilo, background=PAPEL)
            _REDONDOS[estilo] = True
        except Exception:                           # noqa: BLE001
            pass


def _opcion_propia(widget, style) -> None:
    """El botón de opción del diseño: un aro con el punto del acento.

    Como la casilla (`_casilla_propia`): cambia el indicador por una imagen y
    deja el resto de la disposición.
    """
    from . import icons
    try:
        estados = {e: icons.opcion(widget, e)
                   for e in ("marcada", "vacia", "apagada", "apagada-marcada")}
        if None in estados.values():
            return
        _imagenes.setdefault(id(widget.tk), []).extend(estados.values())
        style.element_create(
            "Prdrive.Radiobutton.indicator", "image", estados["vacia"],
            ("disabled", "selected", estados["apagada-marcada"]),
            ("disabled", estados["apagada"]),
            ("selected", estados["marcada"]),
            border=0, sticky="")
        style.layout("TRadiobutton", [
            ("Radiobutton.padding", {"sticky": "nswe", "children": [
                ("Prdrive.Radiobutton.indicator", {"side": "left", "sticky": ""}),
                ("Radiobutton.focus", {"side": "left", "sticky": "w", "children": [
                    ("Radiobutton.label", {"sticky": "nswe"})]})]})])
    except Exception:                               # noqa: BLE001
        pass


def _barra_propia(widget, style) -> None:
    """La barra de progreso: valle hundido con su filete y relleno del acento."""
    try:
        _pieza(widget, style, "Prdrive.Progressbar.trough",
               [((), _tonos(GRIS_FONDO, LINEA))], radio=RADIO_FINO)
        _pieza(widget, style, "Prdrive.Progressbar.pbar",
               [((), [(ACENTO, 0)])], radio=RADIO_FINO, padding=0)
        style.layout("Horizontal.TProgressbar", [
            ("Prdrive.Progressbar.trough", {"sticky": "nswe", "children": [
                ("Prdrive.Progressbar.pbar", {"side": "left", "sticky": "ns"})]})])
        style.configure("Horizontal.TProgressbar", background=PAPEL)
        _REDONDOS["Horizontal.TProgressbar"] = True
    except Exception:                               # noqa: BLE001
        pass


_CLASES_ASENTADAS = ("TButton", "TRadiobutton", "TLabel", "TEntry", "TCombobox",
                     "TSpinbox", "TFrame", "TProgressbar")
"""Las clases de widget cuyos controles redondeados se asientan al aparecer."""


def _controles(widget, style) -> None:
    """Cambia los controles de clam por los dibujados, y asienta los que vengan."""
    _botones_propios(widget, style)
    _segmentos_propios(widget, style)
    _campos_propios(widget, style)
    _marcos_propios(widget, style)
    _chips_propios(widget, style)
    _opcion_propia(widget, style)
    _barra_propia(widget, style)
    for clase in _CLASES_ASENTADAS:
        try:
            widget.bind_class(clase, "<Map>", _asentar, add="+")
        except Exception:                           # noqa: BLE001
            pass


def relleno_control(widget, alto: int, rol: str = "texto", lados: int = 16):
    """Devuelve el `padding` que da a un control el alto del diseño: `(lados, arriba_y_abajo)`.

    El diseño da los controles por su ALTO (34 un botón o un campo, 28 el
    pequeño, 42 el grande, 24 un chip) y ttk por su relleno. El relleno de
    arriba y abajo sale de restar al alto la línea de su letra y el borde de
    1 px de cada lado; el de los lados es un escalón de la escala. Si no hay
    métricas, el de una línea de 18 px.
    """
    from tkinter import font as tkfont

    from . import icons
    try:
        linea = tkfont.Font(root=widget, font=fuente(rol)).metrics("linespace")
    except Exception:                               # noqa: BLE001
        linea = icons.px(widget, 18)
    vertical = max(0, (icons.px(widget, alto) - linea - 2 * icons.px(widget, 1)) // 2)
    return (medida(lados), vertical)


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
    cargar_fuentes()

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
        # Al pasar por encima, clam pinta un recuadro gris detrás de la opción:
        # el diseño no lo tiene (lo que cambia es la casilla, no su fondo).
        style.configure(f"{sup}TRadiobutton", background=fondo,
                        foreground=manda or TINTA)
        for clase in ("TCheckbutton", "TRadiobutton"):
            style.map(f"{sup}{clase}", background=[("active", fondo)])

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
    style.configure("Chip.TLabel", padding=relleno_control(widget, 24, "pista", 8),
                    relief="solid", borderwidth=1,
                    font=fuente("pista"))
    for tipo, (fondo, color, letra, _disco) in _chips().items():
        style.configure(f"{tipo}Chip.TLabel", background=fondo, foreground=letra,
                        bordercolor=color, lightcolor=color, darkcolor=color)
    for tipo, (fondo, letra) in _chips_solidos().items():
        style.configure(f"Solido{tipo}Chip.TLabel", background=fondo,
                        foreground=letra, bordercolor=fondo, lightcolor=fondo,
                        darkcolor=fondo)
    # La etiqueta de capa del editor de flags: un chip aún más discreto.
    style.configure("Capa.TLabel", padding=relleno_control(widget, 20, "etiqueta", 8),
                    relief="solid", borderwidth=1,
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
                    padding=relleno_control(widget, 34, "fuerte", 16),
                    relief="solid", borderwidth=1, font=fuente("fuerte"), **borde)
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
        style.configure(f"Grande.{base}",
                        padding=relleno_control(widget, 42, "fuerte", 24))
        style.configure(f"Pequeno.{base}",
                        padding=relleno_control(widget, 28, "fuerte", 12))

    # El botón de texto: sin caja, solo el acento. Su fondo tiene que ser el de
    # la superficie donde cae, porque un botón sin borde que no la iguale se ve
    # como un recorte de otro color.
    for sup, fondo in (("Quiet.", PAPEL), ("CardQuiet.", SUPERFICIE),
                       ("GrisQuiet.", GRIS_FONDO)):
        style.configure(f"{sup}TButton", background=fondo, foreground=ACENTO,
                        relief="flat", borderwidth=1,
                        padding=relleno_control(widget, 34, "texto", 12),
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
                    padding=relleno_control(widget, 34, "texto", 12), font=fuente(),
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
                    relief="flat", borderwidth=1,
                    padding=relleno_control(widget, 32, "texto", 12), anchor="w",
                    font=fuente(), bordercolor=PAPEL, lightcolor=PAPEL,
                    darkcolor=PAPEL)
    style.map("Nav.TButton",
              background=[("pressed", LINEA), ("active", GRIS_FONDO)],
              **bordes(pressed=LINEA, active=GRIS_FONDO))
    style.configure("NavSel.TButton", background=ACENTO_SUAVE, foreground=TINTA,
                    relief="solid", borderwidth=1,
                    padding=relleno_control(widget, 32, "fuerte", 12), anchor="w",
                    font=fuente("fuerte"), bordercolor=ACENTO_BORDE,
                    lightcolor=ACENTO_BORDE, darkcolor=ACENTO_BORDE)
    style.map("NavSel.TButton", background=[("active", ACENTO_SUAVE)])

    # El grupo de botones (`grupo_botones`): radios con forma de botón; el
    # pulsado, en azul suave con el borde del acento.
    style.configure("Segmento.Toolbutton", background=SUPERFICIE, foreground=TINTA,
                    relief="solid", borderwidth=1,
                    padding=relleno_control(widget, 34, "fuerte", 16),
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
                        padding=relleno_control(widget, 34, "texto", 12),
                        selectbackground=ACENTO_SUAVE,
                        selectforeground=TINTA, placeholderforeground=TINTA3, **borde)
        style.map(nombre,
                  bordercolor=[("focus", ACENTO), ("disabled", LINEA)],
                  lightcolor=[("focus", ACENTO), ("disabled", LINEA)],
                  darkcolor=[("focus", ACENTO), ("disabled", LINEA)],
                  fieldbackground=[("disabled", APAGADO_FONDO),
                                   ("readonly", SUPERFICIE)],
                  foreground=[("disabled", APAGADO)])
    for nombre in ("Mono.TEntry", "Mono.TCombobox"):
        style.configure(nombre, font=fuente("mono"),
                        padding=relleno_control(widget, 34, "mono", 12))

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
                    font=fuente("rotulo"), relief="flat", padding=(E2, E1, E2, E2),
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

    _controles(widget, style)
    _sobres[id(interp)] = set()         # un `id` puede ser de un intérprete ya muerto
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
                           padding=(icons.px(parent, 2), icons.px(parent, 2),
                                    E2, icons.px(parent, 2))
                           if disco is not None and not solido else
                           (E2, relleno_control(parent, 24, "pista")[1]))
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
    marco = ttk.Frame(parent, style=f"{sup}TFrame", padding=(E4, E3))
    marco.columnconfigure(1, weight=1)
    icono = "alert" if icono == "warn" else icono
    img = icons.baldosa(marco, icono or glifo, globals()[color],
                        globals()[sobre], fondo)
    if img is not None:
        baldosa = ttk.Label(marco, image=img, style=f"{sup}TLabel")
        baldosa.image = img
        baldosa.grid(row=0, column=0, rowspan=3, sticky="nw", padx=(0, E3))
    # Sin título, el cuerpo hace de texto principal: en tinta, y centrado con
    # la baldosa si cabe en una línea (el alto mínimo de la fila es el suyo).
    marco.rowconfigure(0, minsize=icons.px(marco, 32) if not titulo else 0)
    # Un título solo se centra con la baldosa: lo que le sobra a su línea
    # hasta los 32 de la baldosa, la mitad arriba.
    centrado = relleno_control(marco, 32, "fuerte")[1]
    if titulo:
        ttk.Label(marco, text=titulo, style=f"{sup}Fuerte.TLabel",
                  wraplength=medida(ancho), justify="left").grid(
            row=0, column=1, sticky="w", pady=(centrado if not cuerpo else 0, 0))
    if cuerpo:
        ttk.Label(marco, text=cuerpo,
                  style=f"{sup}{'Campo.' if titulo else ''}TLabel",
                  wraplength=medida(ancho), justify="left").grid(
            row=1 if titulo else 0, column=1, sticky="w",
            pady=(E1, 0) if titulo else 0)
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
        img = icono_linea(marco, icono, TINTA3, "texto", 16)
    if img is not None:
        dibujo = ttk.Label(marco, image=img, style=f"{sup}TLabel")
        dibujo.image = img
        dibujo.grid(row=1, column=0, sticky="w" if ambar else "nw",
                    padx=(E3, E3), pady=E2)
    ttk.Label(marco, text=texto, style=f"{sup}{'' if ambar else 'Campo.'}TLabel",
              wraplength=medida(ancho), justify="left").grid(
        row=1, column=1, sticky="w" if ambar else "nw", pady=E2)
    marco.boton = None
    if accion:
        marco.boton = ttk.Button(marco, text=accion, command=orden,
                                 style="AmbarQuiet.TButton" if ambar
                                 else "Quiet.TButton")
        marco.boton.grid(row=1, column=2, sticky="e", padx=(E2, E1))
    return marco


def grupo_botones(parent, opciones, variable, orden=None, superficie: str = ""):
    """Devuelve un grupo de botones pegados donde solo uno está pulsado.

    Es el `ButtonGroup` del diseño: hace lo que un desplegable de pocas
    opciones, pero las enseña todas. Son radios de ttk con la forma de botón
    (`Segmento.Toolbutton`), así que la elegida es el valor de `variable`.

    Args:
        opciones: `(rotulo, valor)` por botón, en orden, o `(rotulo, valor,
            icono)` para llevar un icono delante del rótulo.
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
    opciones = list(opciones)
    for i, (rotulo, valor, *icono) in enumerate(opciones):
        # Solo el primero y el último llevan las esquinas redondeadas.
        sitio = ("" if len(opciones) == 1 else "Primero." if i == 0
                 else "Ultimo." if i == len(opciones) - 1 else "Medio.")
        boton = ttk.Radiobutton(marco, text=rotulo, value=valor, variable=variable,
                                command=orden, style=f"{sitio}Segmento.Toolbutton",
                                takefocus=True)
        if icono:
            boton_icono(boton, icono[0], TINTA2)
        boton.grid(row=0, column=i, sticky="ns")
        marco.botones.append(boton)
    return marco


ALTURA_MAYUSCULAS = 0.714
"""La altura de las mayúsculas de Noto Sans, en «em» (714 de 1000).

Es la medida a la que se alinean los iconos (`icono_linea`): Tk da el ascenso
y el descenso de la letra, pero no dónde acaban sus mayúsculas, y es ahí donde
el ojo pone el centro de una línea de texto. La de Segoe UI, si la letra
propia no se pudo cargar, es 0,70: el mismo píxel.
"""


def icono_linea(widget, nombre: str, color: str | None = None,
                rol: str = "texto", size: int = 16, letra=None):
    """Devuelve un icono tan alto como una línea de texto y centrado en ella.

    El centro no es el de la caja de la línea (ascenso + descenso): el ascenso
    reserva sitio para las tildes y el descenso para las colas, y la masa del
    texto queda entre la línea base y la altura de las mayúsculas. El icono se
    centra ahí: su centro cae `ALTURA_MAYUSCULAS / 2` por encima de la línea
    base, con decimales (`icons.get` dibuja la fracción de píxel en lugar de
    redondearla).

    Las medidas son las de `letra` (una fuente de Tk, la que de verdad lleva
    el texto de al lado) o, sin ella, las del rol `rol`. Importa: si la letra
    real fuera otra (la del sistema, porque la propia no se cargó) y se
    midiera la del rol, el icono caería donde no está el texto.

    Como la imagen mide lo mismo que la línea, al lado de su texto en una fila
    de la rejilla (los dos con `sticky="nw"`, o los dos centrados) queda
    alineado sin más, y dentro de un botón (`compound="left"`) no lo hace
    crecer. Devuelve `None` si no se puede pintar.
    """
    from tkinter import font as tkfont

    from . import icons
    real, alto, bajar = icons.px(widget, size), None, 0.0
    try:
        fuente_tk = tkfont.Font(root=widget, font=letra or fuente(rol))
        m = fuente_tk.metrics()
        tam = fuente_tk.actual("size")
        em = -tam if tam < 0 else tam * float(widget.tk.call("tk", "scaling"))
        alto = max(m["linespace"], real + 1)
        centro = m["ascent"] - ALTURA_MAYUSCULAS * em / 2
        bajar = max(0.0, min(centro - real / 2, alto - real - 1))
    except Exception:                           # noqa: BLE001
        alto, bajar = None, 0.0                 # sin métricas: el icono suelto
    return icons.get(widget, nombre, size, color or TINTA, bajar=bajar, alto=alto)


def etiqueta_icono(parent, nombre: str, color: str | None = None,
                   rol: str = "texto", size: int = 16, superficie: str = ""):
    """Devuelve una etiqueta con solo el icono, para ponerla delante de un texto.

    Va con `icono_linea`, así que en la misma fila que una etiqueta de ese
    rol queda alineada con ella; si el texto ocupa varias líneas, las dos con
    `sticky="nw"` y el icono acompaña a la primera.
    """
    from tkinter import ttk
    marca = ttk.Label(parent, style=f"{superficie}TLabel")
    img = icono_linea(parent, nombre, color, rol, size)
    if img is not None:
        marca.configure(image=img)
        marca.image = img
    return marca


def boton_icono(boton, nombre: str, color: str | None = None,
                fondo: str | None = None, size: int = 15):
    """Le pone un icono a la izquierda del texto a un botón ya creado y lo devuelve.

    El icono es el de `icono_linea`, medido con la letra que el estilo del
    botón le da de verdad (la seminegrita de un botón no es la del texto
    corriente): tan alto como la línea y centrado en sus mayúsculas, así que
    el botón no crece y el icono no flota.
    `fondo` ya no hace falta (el icono lleva su alfa) y se acepta por las
    llamadas de antes.

    Si el icono no se puede pintar el botón se queda con su texto y ya está: un
    adorno no puede dejar sin usar una acción.
    """
    letra = None
    try:
        from tkinter import ttk
        estilo = str(boton.cget("style")) or boton.winfo_class()
        letra = ttk.Style(boton).lookup(estilo, "font") or None
    except Exception:                           # noqa: BLE001
        pass                                    # se mide la del rol
    img = icono_linea(boton, nombre, color, "texto", size, letra=letra)
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
                    selectforeground=TINTA, padx=E3, pady=E2, wrap="none")
    opciones.update(kw)
    return tk.Text(parent, **opciones)


def pista_campo(entrada, texto: str):
    """Pone en un campo vacío una pista en gris («Buscar un ajuste…»).

    Con Tk 9 es la del propio campo (`-placeholder`; su gris es el
    `placeholderforeground` del estilo, que pone `apply()`): Tk la pinta
    mientras el campo esté vacío y no la escribe en él, así que su variable
    sigue vacía. Tk 8.6 no la tiene (`pista_etiqueta`).

    Returns:
        `None` con la pista de Tk 9; con Tk 8.6, la etiqueta que hace de pista.
    """
    import tkinter as tk
    try:
        entrada.configure(placeholder=texto)
        return None
    except tk.TclError:                          # Tk 8.6: no hay -placeholder
        return pista_etiqueta(entrada, texto)


def pista_etiqueta(entrada, texto: str):
    """La pista de un campo para Tk 8.6, que no tiene `-placeholder`; la devuelve.

    Es una etiqueta colocada DENTRO del campo, donde empieza el texto: no se
    escribe en el campo, así que su variable sigue vacía y nadie tiene que
    saber que está ahí. Se va en cuanto el campo tiene el foco o algo escrito y
    vuelve al salir de él vacío; un clic en ella pone el cursor en el campo.
    """
    from tkinter import ttk

    from . import icons
    pista = ttk.Label(entrada, text=texto, style="Card.Pista.TLabel",
                      cursor="xterm", font=fuente())
    # Donde empieza el texto: el relleno del campo más su borde.
    x = icons.px(entrada, 12) + icons.px(entrada, 1)

    variable = str(entrada.cget("textvariable"))

    def mirar(_evento=None) -> None:
        """Enseña la pista solo si el campo está vacío y sin el foco.

        Se lee la variable y no el campo: su `trace` salta antes de que el
        campo se entere del cambio, y `get()` daría el texto de antes.
        """
        try:
            vacio = not (entrada.getvar(variable) if variable else entrada.get())
            enfocado = entrada.focus_get() is entrada
        except Exception:                       # noqa: BLE001
            return
        if vacio and not enfocado:
            pista.place(x=x, rely=0.5, anchor="w")
        else:
            pista.place_forget()

    pista.bind("<Button-1>", lambda _e: (entrada.focus_set(), mirar()))
    for evento in ("<FocusIn>", "<FocusOut>", "<KeyRelease>"):
        entrada.bind(evento, mirar, add="+")
    if variable:
        entrada.tk.call("trace", "add", "variable", variable, "write",
                        entrada.register(lambda *_a: mirar()))
    mirar()
    return pista


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
