#!/usr/bin/env python3
"""La ventana de la flota: qué otros dispositivos llevan este catálogo.

Solo dibuja. Quién es cada uno, cuándo se le vio por última vez y a partir de
cuándo eso es demasiado tiempo lo sabe `common/fleet.py`, que no importa Tk y
se prueba sin pantalla.

Cuelga de la pantalla de parejas y no de la principal a propósito: es
información para cuando uno se pregunta «¿dónde estaba el otro pendrive?», no
algo que haya que ver cada vez que se sincroniza. La ventana principal ya tiene
sus avisos, y son los urgentes.

De la nota de otro dispositivo, desde aquí solo se puede hacer una cosa:
**quitarla de la lista**. Ningún dispositivo escribe la nota de otro (por eso
son ficheros separados) y quitarla no es escribirla: es borrar un rastro que el
dueño vuelve a dejar en cuanto se enchufa. El contenido de una nota lo sigue
decidiendo solo quien la firma, y el nombre de ESTE dispositivo no se cambia
aquí sino en «Nombre e icono de la unidad…» (`ui/tk_volumen.py`): esta ventana
solo lo enseña.

Debajo de la lista va la **ficha** del elegido: versión, plataformas, desde
cuándo falla y en qué equipos ha estado. Va en la misma ventana y no en otra:
sería el tercer modal en fila (principal → Parejas → Dispositivos → Ficha). Lo
que dice la ficha lo decide `ficha()`, que no toca Tk; aquí solo se dibuja.
"""

from __future__ import annotations

from typing import NamedTuple

from common import fleet
from common.model import Config

from . import cuando_sello, icons, theme
from .tk import TITLE, cabecera, cuerpo_visible, modal, mostrar

COLUMNAS = [
    ("aqui", "Este", 46),
    ("nombre", "Dispositivo", 250),
    ("visto", "Visto", 100),
    ("equipo", "Último equipo", 150),
    ("estado", "Última pasada", 250),
]
"""Las columnas de la tabla: clave, título y ancho en medidas del diseño.

La versión y las plataformas se fueron a la ficha: en la tabla queda lo que se
compara de un vistazo entre dispositivos. «Último equipo» es solo el más
reciente (`Dispositivo.ultimo_equipo`); la lista entera, con sus fechas, está en
el apartado «Equipos» de la ficha.
"""

SIN_DATO = "—"
"""Lo que se enseña en una celda de la tabla de la que la nota no dice nada."""

SIN_NOTA = ("Todavía no hay ningún dispositivo apuntado. Cada uno deja su nota al "
            "sincronizar, así que aparecerán aquí en cuanto se usen.")
"""Lo que se dice cuando todavía no hay ningún dispositivo apuntado."""

ROTULOS_FICHA = ("Versión", "Para", "Estado", "Equipos")
"""Los rótulos de los apartados de la ficha."""
ESTE_EQUIPO = " · este equipo"
"""Lo que se añade al nombre del equipo desde el que se mira."""
SIN_EQUIPOS = "No consta: las versiones anteriores no lo apuntaban."
"""Lo que se dice de un dispositivo que no apuntó dónde ha estado."""
SIN_BUENA = "No consta ninguna pasada buena."
"""Lo que se dice cuando no consta ninguna pasada buena."""
EN_UN_EQUIPO = "Una carpeta de un equipo, no una unidad"
"""Lo que dice el apartado «Para» de la raíz de un equipo."""
MARCA_EQUIPO = " (equipo)"
"""Lo que se añade al nombre en la tabla para la raíz de un equipo."""
MARCA_EQUIPO_CIFRADO = " (equipo, cifrado)"
"""Lo mismo para la raíz de un equipo cifrada."""
EN_UN_EQUIPO_CIFRADO = "Una carpeta de un equipo, cifrada con VeraCrypt"
"""Lo que dice el apartado «Para» de la raíz de un equipo cifrada."""


class Linea(NamedTuple):
    """Una línea de la ficha.

    Args:
        texto: Lo que dice.
        fecha: Cuándo, a la derecha y en monoespaciada.
        pista: Si acompaña al dato en vez de ser el dato.
    """
    texto: str
    fecha: str = ""
    pista: bool = False


class Fila(NamedTuple):
    """Un apartado de la ficha: su rótulo y sus líneas.

    Args:
        rotulo: El título del apartado.
        lineas: Lo que dice.
        reserva: Las líneas que se reservan aunque no haya tantas, que es lo
            que hace que la ficha mida lo mismo con un equipo que con cinco.
    """
    rotulo: str
    lineas: tuple[Linea, ...]
    reserva: int = 0


def _fecha(sello: str) -> str:
    """Devuelve una fecha de la nota como se enseña en la tabla.

    Las recientes llevan el formato de la ventana («ayer», «08:20»); las de
    hace una semana o más, la fecha entera. Aquí sí hace falta el año, a
    diferencia del resto de la aplicación: entre un dispositivo visto hace tres
    semanas y otro visto hace dos años, un «12/09» a secas no distingue nada, y
    distinguirlos es justo para lo que se abre esta lista.
    """
    if not sello:
        return "—"
    if fleet.sello_obsoleto(sello):
        return sello[:10]
    return cuando_sello(sello) or sello[:10]


def ultimo_equipo(disp: fleet.Dispositivo) -> str:
    """Devuelve lo que dice la columna «Último equipo» de un dispositivo.

    El equipo desde el que publicó por última vez, o `SIN_DATO` si su nota no
    lo apunta (una de una versión que aún no llevaba la lista de equipos).
    """
    return disp.ultimo_equipo or SIN_DATO


def ficha(disp: fleet.Dispositivo, equipo_aqui: str) -> list[Fila]:
    """Devuelve lo que dice la ficha de un dispositivo, apartado por apartado.

    Args:
        disp: El dispositivo.
        equipo_aqui: El nombre de red de este equipo: la entrada que coincide
            se marca, y eso contesta sin más si el otro pendrive ha estado en
            este ordenador.
    """
    estado = [Linea(disp.last_result)]
    if disp.ultima_buena == fleet.SIN_BUENA:
        estado.append(Linea(SIN_BUENA, pista=True))
    elif disp.ultima_buena:
        estado.append(Linea(f"Última pasada buena: {_fecha(disp.ultima_buena)}",
                            pista=True))
    equipos = []
    for equipo in disp.equipos:
        marca = ESTE_EQUIPO if equipo_aqui and equipo.nombre == equipo_aqui else ""
        equipos.append(Linea(equipo.nombre + marca, _fecha(equipo.visto)))
    if not equipos:
        equipos.append(Linea(SIN_EQUIPOS, pista=True))
    version, para, est, eqs = ROTULOS_FICHA
    # La raíz de un equipo no se enchufa en ningún sitio: su «para» es el equipo
    # donde vive, y lo que lleva es rclone para él (el Python es el del agente).
    para_que = ((EN_UN_EQUIPO_CIFRADO if disp.cifrado else EN_UN_EQUIPO)
                if disp.es_equipo else ", ".join(disp.plataformas) or "—")
    return [Fila(version, (Linea(disp.version),)),
            Fila(para, (Linea(para_que),)),
            Fila(est, tuple(estado)),
            Fila(eqs, tuple(equipos), reserva=fleet.MAX_EQUIPOS)]


def marca(disp: fleet.Dispositivo) -> str:
    """Devuelve lo que se le añade al nombre en la tabla: nada en una unidad."""
    if not disp.es_equipo:
        return ""
    return MARCA_EQUIPO_CIFRADO if disp.cifrado else MARCA_EQUIPO


def _tono(disp: fleet.Dispositivo) -> str:
    """Devuelve el color de una fila: apagado, ok o aviso.

    Sale apagado el que lleva una semana sin aparecer y en aviso el que acabó
    mal. El olvido va antes que el fallo a propósito: de uno que no se enchufa
    desde hace un mes, lo que falló hace un mes ya no es la noticia.
    """
    if disp.obsoleto():
        return "apagado"
    return "ok" if disp.bien else "aviso"


def open_dialog(parent, config: Config, raw: dict | None = None) -> None:
    """Abre la ventana; no devuelve nada.

    Lo único que escribe es quitar la nota de otro dispositivo del remoto, y no
    hay nada local que repintar después.

    Args:
        parent: La ventana de la que cuelga.
        config: El config de este dispositivo. Esta ventana no lo usa: la flota
            sale del remoto y el dispositivo no se publica desde aquí.
        raw: El config en bruto, para saber dónde está el catálogo y, junto a
            él, la flota.
    """
    from tkinter import messagebox, ttk

    dlg = modal(parent, "Dispositivos")
    estado: dict = {"flota": []}
    yo = fleet.device_id()

    marco = cuerpo_visible(dlg, padding=(20, 18, 20, 16))
    marco.columnconfigure(0, weight=1)

    arriba = ttk.Frame(marco)
    arriba.grid(row=0, column=0, sticky="ew")
    arriba.columnconfigure(0, weight=1)
    # Lo de los equipos se dice aquí, a la vista, y no en una ayuda: es el nombre
    # de red de los ordenadores de cada uno, y se publica siempre.
    cabecera(arriba, "Dispositivos",
             "Todos los que comparten este catálogo. Cada uno deja una nota al "
             "sincronizar —quién es, qué versión lleva, cómo le fue y en qué "
             "equipos se ha enchufado, por su nombre de red—, y nadie escribe la "
             "de otro. Los que llevan más de una semana sin aparecer salen "
             "apagados. El nombre de este dispositivo se cambia en «Ajustes» → "
             "«Nombre e icono de la unidad…».",
             ancho=620, estilo="Dialogo.TLabel").grid(row=0, column=0, sticky="w")

    donde = ttk.Frame(arriba)
    donde.grid(row=0, column=1, sticky="ne")
    donde.columnconfigure(0, weight=1)
    chip = {"widget": None}
    endpoint = ttk.Label(donde, style="MonoPista.TLabel", text=fleet.carpeta(raw))
    endpoint.grid(row=1, column=0, sticky="e", pady=(6, 0))

    tarjeta = ttk.Frame(marco, style="Card.TFrame", padding=(8, 8, 2, 4))
    tarjeta.grid(row=1, column=0, sticky="nsew", pady=(14, 0))
    tarjeta.columnconfigure(0, weight=1)
    tarjeta.rowconfigure(0, weight=1)
    marco.rowconfigure(1, weight=1)

    tree = ttk.Treeview(tarjeta, columns=[c[0] for c in COLUMNAS],
                        show="headings", height=6, selectmode="browse")
    for clave, titulo, ancho in COLUMNAS:
        sitio = "center" if clave == "aqui" else "w"
        tree.heading(clave, text=titulo, anchor=sitio)
        tree.column(clave, width=icons.px(tree, ancho), anchor=sitio)
    tree.grid(row=0, column=0, sticky="nsew")
    theme.marcar_lista(tree)
    scroll = ttk.Scrollbar(tarjeta, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scroll.set)
    scroll.grid(row=0, column=1, sticky="ns")

    vacio = ttk.Label(marco, text=SIN_NOTA, style="Pista.TLabel",
                      wraplength=theme.medida(620), justify="left")

    # La ficha del elegido. `hueco` es el sitio que se le reserva y `hoja` lo
    # que se pinta dentro: van separados porque el sitio se mide para la ficha
    # más grande de la flota (`reservar()`). El `Visor` encaja una sola vez, al
    # abrir; sin la reserva, elegir una ficha más larga que la primera hacía
    # crecer el contenido y sacaba una barra de desplazamiento que al abrir no
    # estaba.
    hueco = ttk.Frame(marco)
    hueco.grid(row=2, column=0, sticky="ew", pady=(10, 0))
    hueco.columnconfigure(0, weight=1)
    hoja = ttk.Frame(hueco, style="Card.TFrame", padding=(14, 10, 14, 12))
    hoja.grid(row=0, column=0, sticky="nsew")
    canalon = theme.ancho_rotulo(marco, *ROTULOS_FICHA) + icons.px(marco, 14)
    hoja.columnconfigure(0, minsize=canalon)
    hoja.columnconfigure(1, weight=1)
    aqui = fleet.equipo_actual()

    def pintar_ficha(disp: fleet.Dispositivo) -> None:
        """Pinta la ficha de ese dispositivo en `hoja`."""
        for widget in hoja.winfo_children():
            widget.destroy()
        ttk.Label(hoja, text=disp.nombre, style="Card.Fuerte.TLabel",
                  wraplength=theme.medida(460), justify="left").grid(
            row=0, column=0, columnspan=2, sticky="w")
        # El id corto: dos dispositivos aprovisionados en el mismo equipo
        # empiezan con el mismo nombre, y el id es lo único que los distingue
        # (y el nombre de su fichero en `devices/`).
        ttk.Label(hoja, text=f"id {disp.id[:8]}", style="Card.MonoPista.TLabel").grid(
            row=0, column=2, sticky="ne", padx=(12, 0))
        fila = 1
        for apartado in ficha(disp, aqui):
            ttk.Label(hoja, text=theme.rotulo(apartado.rotulo),
                      style="Card.Rotulo.TLabel").grid(row=fila, column=0,
                                                       sticky="nw", pady=(9, 0))
            lineas = list(apartado.lineas)
            lineas += [Linea(" ")] * (apartado.reserva - len(lineas))
            for i, linea in enumerate(lineas):
                aire = (8, 0) if i == 0 else (2, 0)
                ttk.Label(hoja, text=linea.texto, justify="left",
                          style="Card.Pista.TLabel" if linea.pista else "Card.TLabel",
                          wraplength=theme.medida(440)).grid(
                    row=fila, column=1, sticky="w", pady=aire)
                if linea.fecha:
                    ttk.Label(hoja, text=linea.fecha, style="Card.MonoPista.TLabel").grid(
                        row=fila, column=2, sticky="e", padx=(12, 0), pady=aire)
                fila += 1

    def reservar() -> None:
        """Reserva el sitio de la ficha: el que pide la más grande de esta flota.

        Los equipos ya reservan siempre sus `MAX_EQUIPOS` líneas, pero hay
        texto que sí cambia de alto (un «fallo en a, b, c…» que parte en dos
        líneas, un nombre largo) y medirlo es la única forma de no suponerlo.
        """
        ancho = alto = 0
        for disp in estado["flota"]:
            pintar_ficha(disp)
            hoja.update_idletasks()
            ancho = max(ancho, hoja.winfo_reqwidth())
            alto = max(alto, hoja.winfo_reqheight())
        hueco.columnconfigure(0, minsize=ancho)
        hueco.rowconfigure(0, minsize=alto)

    def pintar_chip(texto: str, tipo: str, icono: str) -> None:
        """Cambia el chip de arriba a la derecha."""
        if chip["widget"] is not None:
            chip["widget"].destroy()
        chip["widget"] = theme.chip(donde, texto, tipo, icono)
        chip["widget"].grid(row=0, column=0, sticky="e")

    def refrescar(nota: str = "") -> None:
        """Relee la flota y repinta la tabla y la ficha."""
        flota, aviso = fleet.leer(raw)
        estado["flota"] = flota
        if aviso:
            pintar_chip("sin conexión", "Aviso.", "warn")
        else:
            pintar_chip(f"{len(flota)} dispositivo(s)", "Acento.", "ok")

        tree.delete(*tree.get_children())
        for disp in flota:
            tree.insert("", "end", iid=disp.id, tags=(_tono(disp),),
                        values=("✓" if disp.id == yo else "",
                                disp.nombre + marca(disp),
                                _fecha(disp.last_seen),
                                ultimo_equipo(disp),
                                disp.last_result))
        # La lista es más baja porque la ficha se lleva parte de la ventana.
        tree.configure(height=min(8, max(3, len(flota))))
        reservar()
        if flota:
            vacio.grid_remove()
            tree.selection_set(flota[0].id)
        else:
            vacio.grid(row=2, column=0, sticky="w", pady=(10, 0))
        repasar()
        pie_nota.configure(text=nota or (aviso or ""))
        # Releer puede traer una ficha más grande que las que había al abrir:
        # entonces el recuadro crece, en vez de meter la ventana tras una barra.
        if dlg.winfo_ismapped():
            dlg.visor.crecer(dlg)

    def elegido() -> fleet.Dispositivo | None:
        """Devuelve el dispositivo de la fila elegida, o `None`."""
        seleccion = tree.selection()
        if not seleccion:
            return None
        return next((d for d in estado["flota"] if d.id == seleccion[0]), None)

    def repasar(_evento=None) -> None:
        """Repinta lo que cuelga de la fila elegida: su ficha y el botón de quitar.

        Sin nada elegido (flota vacía, o recién quitado uno) la ficha se
        esconde entera. «Quitar de la lista» se apaga sobre este mismo
        dispositivo: `fleet` lo rechaza igualmente (la regla es suya), pero un
        botón encendido que siempre contesta que no es peor que uno apagado.
        """
        disp = elegido()
        if disp is None:
            hueco.grid_remove()
        else:
            pintar_ficha(disp)
            hueco.grid()
        quitar.configure(state="normal" if disp is not None and disp.id != yo
                         else "disabled")

    def quitar_de_la_lista() -> None:
        """Quita la nota de un dispositivo que ya no existe.

        Es un `askokcancel` y no `confirmar_plan()`: esa ventana gobierna los
        borrados que pierden datos y esto no pierde ninguno (si el dispositivo
        vuelve a enchufarse, publica otra vez y reaparece). Lo que sí hace
        falta es decirlo, porque «quitar» suena a más de lo que es.
        """
        disp = elegido()
        if disp is None or disp.id == yo:
            return
        if not messagebox.askokcancel(
                TITLE,
                f"¿Quitar «{disp.nombre}» de la lista?\n\n"
                f"Se borra su nota del remoto, no el dispositivo. Si vuelve a "
                f"enchufarse en algún sitio, se apuntará solo y reaparecerá aquí.",
                parent=dlg):
            return
        fallo = fleet.olvidar(disp.id, raw)
        if fallo:
            refrescar(fallo)
            return
        refrescar(f"«{disp.nombre}» ya no está en la lista.")

    acciones = ttk.Frame(marco)
    acciones.grid(row=3, column=0, sticky="ew", pady=(14, 0))
    acciones.columnconfigure(1, weight=1)
    quitar = ttk.Button(acciones, text="Quitar de la lista…", style="Danger.TButton",
                        command=quitar_de_la_lista, state="disabled")
    theme.boton_icono(quitar, "trash", theme.PELIGRO, theme.SUPERFICIE)
    quitar.grid(row=0, column=0, sticky="w")
    tree.bind("<<TreeviewSelect>>", repasar)
    releer = ttk.Button(acciones, text="Releer", style="Quiet.TButton",
                        command=lambda: refrescar("Flota releída."))
    theme.boton_icono(releer, "reload", theme.ACENTO, theme.PAPEL)
    releer.grid(row=0, column=2, sticky="e")

    cierre = ttk.Frame(marco)
    cierre.grid(row=4, column=0, sticky="ew", pady=(12, 0))
    cierre.columnconfigure(0, weight=1)
    pie_nota = ttk.Label(cierre, text="", style="MonoPista.TLabel",
                         wraplength=theme.medida(620), justify="left")
    pie_nota.grid(row=0, column=0, sticky="w")
    ttk.Button(cierre, text="Cerrar", command=dlg.destroy).grid(row=0, column=1)

    refrescar()
    mostrar(dlg, parent)
