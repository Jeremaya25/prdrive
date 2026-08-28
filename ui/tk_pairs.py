#!/usr/bin/env python3
"""
tk_pairs.py — La pantalla de parejas.

Solo dibuja. Todo lo que decide y todo lo que toca el disco está en
`ui/pair_editor.py` (este dispositivo) y `ui/catalog_editor.py` (el catálogo del remoto), y
el guion es siempre el mismo: se pide un plan, se enseñan sus consecuencias, y
solo si el usuario confirma se ejecuta. Ninguna acción de esta pantalla escribe
nada sin haber enseñado antes lo que va a pasar.

La lista es una sola pero los botones van en dos bloques separados, y esa
separación es el asunto de la pantalla: el bloque que cambia el catálogo —y por
tanto TODOS los dispositivos— va sobre fondo ámbar, el mismo con el que la
aplicación avisa de lo demás; el que cambia solo este dispositivo va sobre el papel, con
su única acción principal en azul. Una pareja se crea o se borra en el catálogo,
y después cada dispositivo elige si la usa.

Las consecuencias ya no se enseñan en un `messagebox`: `confirmar_plan()` es una
ventana de verdad, con las consecuencias como lista y los avisos en su recuadro
ámbar. Un `askokcancel` con seis líneas de texto corrido es justo lo que nadie
lee, y esto gobierna borrados.
"""

from __future__ import annotations

from common import catalog, config_file, model
from common.model import ConfigError

from . import catalog_editor, flags_editor, icons, pair_editor, theme
from .tk import TITLE, bloque_aviso, cabecera, cuerpo_visible, modal, mostrar

COLUMNAS = [
    ("usa", "En el dispositivo", 62),
    ("pareja", "Pareja", 110),
    ("modo", "Modo", 95),
    ("local", "Local", 180),
    ("remoto", "Remoto", 205),
    ("origen", "Origen", 160),
    ("estado", "Estado", 150),
]

# Los campos de texto del formulario de [defaults]. Los flags tienen su propio
# diálogo, y lo que no sale por ningún sitio (use_filters_file…) se conserva tal
# cual, igual que en las parejas.
DEFAULTS_KEYS = ("remote", "device_remote", "catalog_path")

NOTA_PEN = "Se guardará copia en sync_config.toml.bak"
NOTA_CATALOGO = "Se guardará copia en pairs.toml.bak, en el remoto"


def _tono(fila) -> str:
    """El color de una fila, por lo que hay que mirar de ella.

    Una `ttk.Treeview` no sabe pintar una celda suelta —los chips del diseño no
    caben ahí—, pero sí toda la fila por etiquetas, que es justo lo que dice la
    hoja de estilo para esta tabla."""
    if not fila.en_pen:
        return "apagado"
    if fila.aviso and "espejo" in fila.aviso:
        return "peligro"
    if fila.aviso:
        return "aviso"
    return "ok"


def _estado(fila) -> str:
    """Lo que va en la columna Estado: el estado del baseline y, si es un espejo,
    que lo es —que es la mitad de lo que hay que saber de esa pareja—."""
    if fila.aviso and "espejo" in fila.aviso:
        return f"{fila.estado} · espejo"
    if fila.aviso:
        return fila.aviso
    return fila.estado


def open_dialog(parent, config) -> bool:
    """Abre la pantalla. Devuelve True si se ha cambiado el config de este dispositivo."""
    from tkinter import messagebox, ttk

    dlg = modal(parent, "Parejas")
    raw = config_file.load_raw()
    cat, aviso = catalog.load(raw)
    estado = {"raw": raw, "config": config, "cat": cat, "cambiado": False}

    marco = cuerpo_visible(dlg, padding=(20, 18, 20, 16))
    marco.columnconfigure(0, weight=1)

    # --- de qué va esta pantalla, y de dónde sale el catálogo ---------------
    arriba = ttk.Frame(marco)
    arriba.grid(row=0, column=0, sticky="ew")
    arriba.columnconfigure(0, weight=1)
    cabecera(arriba, "Parejas",
             "Una pareja se crea o se borra en el catálogo, que es igual para "
             "todos los dispositivos. Cada dispositivo elige después cuáles usa.",
             ancho=620, estilo="Dialogo.TLabel").grid(row=0, column=0, sticky="w")

    donde = ttk.Frame(arriba)
    donde.grid(row=0, column=1, sticky="ne")
    donde.columnconfigure(0, weight=1)
    chip_cat = {"widget": None}
    endpoint = ttk.Label(donde, style="MonoPista.TLabel")
    endpoint.grid(row=1, column=0, sticky="e", pady=(6, 0))

    # --- la franja de [defaults] --------------------------------------------
    # Van con su propia línea y sus propios botones: no son una pareja más, y sus
    # botones dicen casi lo mismo que los de abajo. Juntos se confunden.
    fila_defaults = ttk.Frame(marco, style="Gris.TFrame", padding=(12, 8))
    fila_defaults.grid(row=1, column=0, sticky="ew", pady=(16, 0))
    fila_defaults.columnconfigure(3, weight=1)
    ttk.Label(fila_defaults, text=theme.rotulo("[defaults]"),
              style="Gris.Rotulo.TLabel").grid(row=0, column=0, sticky="w")
    origen_defaults = {"widget": None}
    linea_defaults = ttk.Label(fila_defaults, style="Gris.Pista.TLabel",
                               wraplength=420, justify="left")
    linea_defaults.grid(row=0, column=2, sticky="w", padx=(10, 0))

    # --- la lista ------------------------------------------------------------
    tarjeta = ttk.Frame(marco, style="Card.TFrame", padding=(8, 8, 2, 4))
    tarjeta.grid(row=2, column=0, sticky="nsew", pady=(14, 0))
    tarjeta.columnconfigure(0, weight=1)
    tarjeta.rowconfigure(0, weight=1)
    marco.rowconfigure(2, weight=1)

    tree = ttk.Treeview(tarjeta, columns=[c[0] for c in COLUMNAS],
                        show="headings", height=11, selectmode="browse")
    for clave, titulo, ancho in COLUMNAS:
        sitio = "center" if clave == "usa" else "w"
        tree.heading(clave, text=titulo, anchor=sitio)
        tree.column(clave, width=ancho, anchor=sitio)
    tree.grid(row=0, column=0, sticky="nsew")
    theme.marcar_lista(tree)
    scroll = ttk.Scrollbar(tarjeta, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scroll.set)
    scroll.grid(row=0, column=1, sticky="ns")

    botones_catalogo: list = []

    def refrescar(nota: str = "") -> None:
        estado["raw"] = config_file.load_raw()
        estado["config"] = model.parse_config(estado["raw"])
        cat = estado["cat"]

        sitio = cat.endpoint if cat else catalog.endpoint(estado["raw"])
        if cat is None:
            texto, tipo, icono = aviso or "sin catálogo", "Peligro.", "warn"
        elif cat.editable:
            texto, tipo, icono = f"catálogo leído · {cat.stamp}", "Acento.", "ok"
        else:
            texto, tipo, icono = aviso or "copia local", "Aviso.", "warn"
        if chip_cat["widget"] is not None:
            chip_cat["widget"].destroy()
        chip_cat["widget"] = theme.chip(donde, texto, tipo, icono)
        chip_cat["widget"].grid(row=0, column=0, sticky="e")
        endpoint.configure(text=sitio)

        origen, difiere = pair_editor.defaults_origin(estado["raw"], cat)
        if origen_defaults["widget"] is not None:
            origen_defaults["widget"].destroy()
        origen_defaults["widget"] = theme.chip(
            fila_defaults, origen,
            "Aviso." if difiere else ("Apagado." if origen == "—" else ""))
        origen_defaults["widget"].grid(row=0, column=1, sticky="w", padx=(10, 0))
        linea_defaults.configure(text=_resumen_defaults(estado["raw"], difiere))

        tree.delete(*tree.get_children())
        filas = pair_editor.catalog_rows(estado["config"], estado["raw"], cat)
        # La lista crece con lo que hay, hasta un tope: dejar hueco vacío por si
        # algún día hay más parejas es dejar la mitad de la ventana en blanco.
        tree.configure(height=min(14, max(5, len(filas))))
        for fila in filas:
            marca = "✓" if fila.en_pen else ""
            origen = fila.origen + (f" ({', '.join(fila.difiere)})" if fila.difiere else "")
            tree.insert("", "end", iid=fila.name, tags=(_tono(fila),),
                        values=(marca, fila.name, fila.mode, fila.local, fila.remote,
                                origen, _estado(fila)))

        puede = "normal" if (cat is not None and cat.editable) else "disabled"
        for boton in botones_catalogo:
            boton.configure(state=puede)
        pie_nota.configure(text=nota)

    def fila_elegida():
        """La fila seleccionada, ya resuelta contra el catálogo. None = ninguna."""
        elegido = tree.selection()
        if not elegido:
            messagebox.showinfo(TITLE, "Elige antes una pareja de la lista.", parent=dlg)
            return None
        for fila in pair_editor.catalog_rows(estado["config"], estado["raw"], estado["cat"]):
            if fila.name == elegido[0]:
                return fila
        return None

    def aplicar(plan, del_catalogo: bool = False, titulo: str = "") -> None:
        """Confirmar y ejecutar. Un plan del catálogo no cambia este dispositivo."""
        if not confirmar_plan(dlg, plan, titulo or "Confirmar el cambio",
                              NOTA_CATALOGO if del_catalogo else NOTA_PEN):
            return
        try:
            hechos = plan.execute()
        except (ConfigError, OSError) as e:
            messagebox.showerror(TITLE, f"No se ha podido guardar:\n\n{e}", parent=dlg)
            return
        if del_catalogo:
            estado["cat"], _ = catalog.load(estado["raw"])
        else:
            estado["cambiado"] = True
        refrescar("  ·  ".join(hechos))

    def fallo(e) -> None:
        messagebox.showerror(TITLE, str(e), parent=dlg)

    # --- este dispositivo ----------------------------------------------------------

    def usar_aqui() -> None:
        fila = fila_elegida()
        if fila is None:
            return
        try:
            aplicar(pair_editor.plan_enable(estado["raw"], estado["cat"], fila.name),
                    titulo=f"Usar '{fila.name}' en este dispositivo")
        except ConfigError as e:
            fallo(e)

    def quitar() -> None:
        fila = fila_elegida()
        if fila is None:
            return
        if not fila.en_pen:
            messagebox.showinfo(TITLE, f"'{fila.name}' no se está usando en este dispositivo.",
                                parent=dlg)
            return
        limpiar = preguntar_limpieza(dlg, fila.name)
        if limpiar is None:
            return
        try:
            aplicar(pair_editor.plan_remove(estado["raw"], fila.name, clean_state=limpiar),
                    titulo=f"Quitar '{fila.name}' de este dispositivo")
        except ConfigError as e:
            fallo(e)

    def modificar_aqui() -> None:
        fila = fila_elegida()
        if fila is None:
            return
        if not fila.en_pen:
            messagebox.showinfo(TITLE, f"'{fila.name}' todavía no se usa en este dispositivo: "
                                       f"úsala primero y luego modifícala.", parent=dlg)
            return
        actual = next(p for p in estado["raw"]["pair"] if p.get("name") == fila.name)
        datos = formulario(dlg, estado["raw"], fila.name, actual,
                           catalogo=catalog.find_pair(estado["cat"], fila.name),
                           titulo=f"Modificar '{fila.name}' solo en este dispositivo",
                           marca="el catálogo no cambia",
                           subtitulo="Este cambio se queda aquí, los demás "
                                     "dispositivos siguen igual.")
        if datos is None:
            return
        try:
            aplicar(pair_editor.plan_override(estado["raw"], estado["cat"],
                                              fila.name, datos),
                    titulo=f"Modificar '{fila.name}' en este dispositivo")
        except ConfigError as e:
            fallo(e)

    def volver_al_catalogo() -> None:
        fila = fila_elegida()
        if fila is None:
            return
        try:
            aplicar(pair_editor.plan_revert(estado["raw"], estado["cat"], fila.name),
                    titulo=f"Devolver '{fila.name}' a lo que dice el catálogo")
        except ConfigError as e:
            fallo(e)

    def defaults_del_pen() -> None:
        cat = estado["cat"]
        actuales = dict(estado["raw"].get("defaults") or {})
        datos = defaults_form(dlg, actuales, cat.defaults if cat else None,
                              "Ajustes generales de este dispositivo",
                              "Valen para todas las parejas de este dispositivo.",
                              marca="el catálogo no cambia")
        if datos is None:
            return
        try:
            aplicar(pair_editor.plan_defaults(estado["raw"], datos),
                    titulo="Cambiar los ajustes de este dispositivo")
        except ConfigError as e:
            fallo(e)

    def volver_defaults() -> None:
        try:
            aplicar(pair_editor.plan_revert_defaults(estado["raw"], estado["cat"]),
                    titulo="Devolver los ajustes a los del catálogo")
        except ConfigError as e:
            fallo(e)

    # --- catálogo ----------------------------------------------------------

    def catalogo_nueva() -> None:
        datos = formulario(dlg, (estado["cat"].raw if estado["cat"] else {}), None, {},
                           titulo="Nueva pareja en el catálogo",
                           marca="afecta a TODOS los dispositivos",
                           subtitulo="Queda disponible para todos los dispositivos; usarla "
                                     "aquí es el paso siguiente.")
        if datos is None:
            return
        try:
            aplicar(catalog_editor.plan_catalog_save(estado["cat"], datos, None,
                                                     estado["raw"]),
                    del_catalogo=True, titulo="Dar de alta en el catálogo")
        except ConfigError as e:
            fallo(e)

    def catalogo_editar() -> None:
        fila = fila_elegida()
        if fila is None:
            return
        entrada = catalog.find_pair(estado["cat"], fila.name)
        if entrada is None:
            messagebox.showinfo(TITLE, f"'{fila.name}' no está en el catálogo.", parent=dlg)
            return
        datos = formulario(dlg, estado["cat"].raw, fila.name, entrada,
                           titulo=f"Editar '{fila.name}' en el catálogo",
                           marca="afecta a TODOS los dispositivos",
                           subtitulo="Lo que se cambie aquí lo verán todos los dispositivos "
                                     "la próxima vez que lean el catálogo.")
        if datos is None:
            return
        try:
            aplicar(catalog_editor.plan_catalog_save(estado["cat"], datos, fila.name,
                                                     estado["raw"]),
                    del_catalogo=True, titulo=f"Editar '{fila.name}' en el catálogo")
        except ConfigError as e:
            fallo(e)

    def catalogo_borrar() -> None:
        fila = fila_elegida()
        if fila is None:
            return
        try:
            aplicar(catalog_editor.plan_catalog_remove(estado["cat"], fila.name,
                                                       estado["raw"]),
                    del_catalogo=True, titulo=f"Borrar '{fila.name}' del catálogo")
        except ConfigError as e:
            fallo(e)

    def catalogo_defaults() -> None:
        cat = estado["cat"]
        if cat is None:
            fallo(ConfigError("No hay catálogo que editar."))
            return
        datos = defaults_form(dlg, cat.defaults, None,
                              "Ajustes generales del catálogo",
                              "Los heredan todos los dispositivos que no tengan los suyos.",
                              marca="afecta a TODOS los dispositivos")
        if datos is None:
            return
        try:
            aplicar(catalog_editor.plan_catalog_defaults(cat, datos, estado["raw"]),
                    del_catalogo=True, titulo="Cambiar los ajustes del catálogo")
        except ConfigError as e:
            fallo(e)

    def recargar_catalogo() -> None:
        nonlocal aviso
        estado["cat"], aviso = catalog.load(estado["raw"])
        refrescar("Catálogo releído." if estado["cat"] else "")

    # --- los dos bloques de botones ----------------------------------------

    for i, (texto, accion) in enumerate((
            ("Ajustes de este dispositivo…", defaults_del_pen),
            ("Volver a los del catálogo", volver_defaults)), start=4):
        ttk.Button(fila_defaults, text=texto, style="GrisQuiet.TButton",
                   command=accion).grid(row=0, column=i, padx=(4, 0))
    boton = ttk.Button(fila_defaults, text="Ajustes del catálogo…",
                       style="GrisQuiet.TButton", command=catalogo_defaults)
    boton.grid(row=0, column=6, padx=(4, 0))
    botones_catalogo.append(boton)

    dispositivo = ttk.Frame(marco)
    dispositivo.grid(row=3, column=0, sticky="ew", pady=(14, 0))
    ttk.Label(dispositivo, text=theme.rotulo("Este dispositivo"), style="Rotulo.TLabel",
              width=18).grid(row=0, column=0, sticky="w")
    for i, (texto, icono, estilo, accion) in enumerate((
            ("Usar aquí", "plus", "Primary.TButton", usar_aqui),
            ("Modificar aquí…", "edit", "TButton", modificar_aqui),
            ("Volver al catálogo", "back", "TButton", volver_al_catalogo),
            ("Quitar…", "trash", "Danger.TButton", quitar)), start=1):
        boton = ttk.Button(dispositivo, text=texto, style=estilo, command=accion)
        color = {"Primary.TButton": theme.SUPERFICIE,
                 "Danger.TButton": theme.PELIGRO}.get(estilo, theme.TINTA2)
        fondo = theme.ACENTO if estilo == "Primary.TButton" else theme.SUPERFICIE
        theme.boton_icono(boton, icono, color, fondo)
        boton.grid(row=0, column=i, padx=(0, 6))

    # El bloque del catálogo va sobre ámbar: es lo que toca a todos los equipos.
    cat_frame = ttk.Frame(marco, style="Ambar.TFrame", padding=(10, 7))
    cat_frame.grid(row=4, column=0, sticky="ew", pady=(8, 0))
    cat_frame.columnconfigure(5, weight=1)
    ttk.Label(cat_frame, text=theme.rotulo("Catálogo"),
              style="Ambar.Rotulo.TLabel", width=18).grid(row=0, column=0, sticky="w")
    for i, (texto, icono, estilo, accion) in enumerate((
            ("Nueva…", "plus", "Ambar.TButton", catalogo_nueva),
            ("Editar…", "edit", "Ambar.TButton", catalogo_editar),
            ("Borrar…", "trash", "AmbarDanger.TButton", catalogo_borrar)), start=1):
        boton = ttk.Button(cat_frame, text=texto, style=estilo, command=accion)
        theme.boton_icono(boton, icono,
                          theme.PELIGRO if "Danger" in estilo else theme.TINTA2,
                          theme.SUPERFICIE)
        boton.grid(row=0, column=i, padx=(0, 6))
        botones_catalogo.append(boton)
    ttk.Label(cat_frame, text="Afecta a TODOS los dispositivos",
              style="Ambar.Pista.TLabel").grid(row=0, column=4, sticky="w", padx=(4, 0))
    releer = ttk.Button(cat_frame, text="Releer", style="AmbarQuiet.TButton",
                        command=recargar_catalogo)
    theme.boton_icono(releer, "reload", theme.AVISO, theme.AVISO_FONDO)
    releer.grid(row=0, column=6, sticky="e")

    cierre = ttk.Frame(marco)
    cierre.grid(row=5, column=0, sticky="ew", pady=(12, 0))
    cierre.columnconfigure(0, weight=1)
    pie_nota = ttk.Label(cierre, text="", style="MonoPista.TLabel", wraplength=760,
                         justify="left")
    pie_nota.grid(row=0, column=0, sticky="w")
    ttk.Button(cierre, text="Cerrar", command=dlg.destroy).grid(row=0, column=1)

    refrescar()
    mostrar(dlg, parent)
    return estado["cambiado"]


def _resumen_defaults(raw, difiere) -> str:
    """La línea de una sola frase que resume los [defaults] de este dispositivo."""
    d = raw.get("defaults") or {}
    trozos = [f"remote {d.get('remote', model.DEFAULT_REMOTE)}"]
    trozos.append(f"device_remote {d['device_remote']}" if d.get("device_remote")
                  else "sin device_remote")
    flags = len(d.get("flags") or {})
    trozos.append(f"{flags} flags comunes" if flags else "sin flags comunes")
    if difiere:
        trozos.append("difiere en " + ", ".join(difiere))
    return " · ".join(trozos)


# ---------------------------------------------------------------------------
# Confirmar un plan
# ---------------------------------------------------------------------------

def confirmar_plan(parent, plan, titulo: str, nota: str) -> bool:
    """Enseña lo que va a pasar y espera un sí. Todavía no se ha escrito nada.

    Cada consecuencia es una línea con su punto, y cada aviso su recuadro ámbar:
    lo que se está confirmando aquí puede apartar un baseline o subir un cambio
    al remoto, y en un `askokcancel` todo eso queda en un párrafo que se despacha
    con un clic sin leerlo."""
    from tkinter import ttk

    dlg = modal(parent, titulo)
    respuesta = {"sigue": False}
    marco = cuerpo_visible(dlg, padding=(22, 20, 22, 18))
    marco.columnconfigure(0, weight=1)

    ttk.Label(marco, text=titulo, style="Dialogo.TLabel").grid(
        row=0, column=0, sticky="w")
    ttk.Label(marco, text="Esto es lo que va a pasar. Nada se ha escrito todavía.",
              style="Pista.TLabel").grid(row=1, column=0, sticky="w", pady=(5, 0))

    tarjeta = ttk.Frame(marco, style="Card.TFrame", padding=(14, 4))
    tarjeta.grid(row=2, column=0, sticky="ew", pady=(14, 0))
    tarjeta.columnconfigure(1, weight=1)
    for i, texto in enumerate(plan.consequences or ["(sin cambios)"]):
        if i:
            ttk.Separator(tarjeta, orient="horizontal", style="Card.TSeparator").grid(
                row=i * 2 - 1, column=0, columnspan=2, sticky="ew")
        ttk.Label(tarjeta, text="•", style="Card.Apagado.TLabel").grid(
            row=i * 2, column=0, sticky="nw", pady=7)
        ttk.Label(tarjeta, text=texto, style="Card.TLabel", wraplength=470,
                  justify="left").grid(row=i * 2, column=1, sticky="w",
                                       padx=(9, 0), pady=7)

    fila = 3
    for texto in plan.warnings:
        bloque_aviso(marco, texto, ancho=470).grid(row=fila, column=0, sticky="ew",
                                                   pady=(12, 0))
        fila += 1

    ttk.Separator(marco, orient="horizontal").grid(row=fila, column=0, sticky="ew",
                                                   pady=(16, 0))
    pie = ttk.Frame(marco)
    pie.grid(row=fila + 1, column=0, sticky="ew", pady=(14, 0))
    pie.columnconfigure(0, weight=1)
    ttk.Label(pie, text=nota, style="Pista.TLabel").grid(row=0, column=0, sticky="w")

    def seguir():
        respuesta["sigue"] = True
        dlg.destroy()

    ttk.Button(pie, text="Cancelar", command=dlg.destroy).grid(row=0, column=1,
                                                               padx=(10, 6))
    ttk.Button(pie, text="Seguir adelante", style="Primary.TButton",
               command=seguir).grid(row=0, column=2)

    mostrar(dlg, parent)
    return respuesta["sigue"]


def preguntar_limpieza(parent, name: str) -> bool | None:
    """¿Apartar también su estado? None = cancelar."""
    import tkinter as tk
    from tkinter import ttk

    dlg = modal(parent, f"Quitar '{name}'")
    marco = cuerpo_visible(dlg, padding=(22, 20, 22, 18))
    marco.columnconfigure(0, weight=1)
    respuesta = {"valor": None}

    ttk.Label(marco, text=f"Quitar '{name}' de este dispositivo",
              style="Dialogo.TLabel").grid(row=0, column=0, sticky="w")
    ttk.Label(marco, justify="left", wraplength=440, style="Pista.TLabel",
              text=("Los datos NO se tocan, ni en el dispositivo ni en el remoto, y la pareja "
                    "sigue en el catálogo: se puede volver a usar cuando "
                    "quieras.")).grid(row=1, column=0, sticky="w", pady=(5, 0))

    limpiar = tk.BooleanVar(value=False)
    caja = ttk.Frame(marco, style="Card.TFrame", padding=(14, 12))
    caja.grid(row=2, column=0, sticky="ew", pady=(14, 0))
    ttk.Checkbutton(caja, variable=limpiar, style="Card.TCheckbutton", text=(
        "Apartar también su baseline y borrar sus filtros generados")).grid(
        row=0, column=0, sticky="w")
    ttk.Label(caja, style="Card.Pista.TLabel", wraplength=430, justify="left",
              text=("El baseline se renombra a state/<pareja>.old-<fecha>/, no se "
                    "borra. Si no marcas nada, se queda todo donde está.")).grid(
        row=1, column=0, sticky="w", padx=(24, 0), pady=(4, 0))

    def aceptar():
        respuesta["valor"] = bool(limpiar.get())
        dlg.destroy()

    ttk.Separator(marco, orient="horizontal").grid(row=3, column=0, sticky="ew",
                                                   pady=(16, 0))
    pie = ttk.Frame(marco)
    pie.grid(row=4, column=0, sticky="e", pady=(14, 0))
    ttk.Button(pie, text="Cancelar", command=dlg.destroy).grid(row=0, column=0,
                                                               padx=(0, 6))
    quitar = ttk.Button(pie, text="Quitar", style="Danger.TButton", command=aceptar)
    theme.boton_icono(quitar, "trash", theme.PELIGRO, theme.SUPERFICIE)
    quitar.grid(row=0, column=1)

    mostrar(dlg, parent)
    return respuesta["valor"]


# ---------------------------------------------------------------------------
# El formulario de una pareja
# ---------------------------------------------------------------------------

def _cabecera_form(marco, titulo: str, marca: str | None, subtitulo: str | None,
                   fila: int) -> int:
    """Título, chip de alcance y frase. Devuelve la fila siguiente.

    El chip es lo que contesta de un vistazo a la única pregunta que importa
    antes de tocar nada: si esto se queda aquí o lo van a ver todos los dispositivos."""
    from tkinter import ttk
    ttk.Label(marco, text=titulo, style="Dialogo.TLabel").grid(
        row=fila, column=0, columnspan=3, sticky="w")
    fila += 1
    if marca or subtitulo:
        linea = ttk.Frame(marco)
        linea.grid(row=fila, column=0, columnspan=3, sticky="w", pady=(6, 0))
        col = 0
        if marca:
            theme.chip(linea, marca, "Aviso.", "warn").grid(row=0, column=0,
                                                            sticky="w")
            col = 1
        if subtitulo:
            ttk.Label(linea, text=subtitulo, style="Pista.TLabel", wraplength=520,
                      justify="left").grid(row=0, column=col, sticky="w",
                                           padx=(8, 0) if col else 0)
        fila += 1
    return fila


def formulario(parent, raw: dict, original_name: str | None, actual: dict,
               catalogo: dict | None = None, titulo: str | None = None,
               subtitulo: str | None = None, marca: str | None = None) -> dict | None:
    """El formulario de una pareja. Devuelve los campos, o None si se cancela.

    `catalogo` es la entrada del catálogo con la que comparar: junto a cada campo
    se enseña lo que dice el catálogo y se marca con ✎ el que difiere, que es lo
    que convierte «modificar aquí» en una decisión informada."""
    import tkinter as tk
    from tkinter import ttk

    dlg = modal(parent, titulo or (f"Editar '{original_name}'" if original_name
                                   else "Nueva pareja"))
    marco = cuerpo_visible(dlg, padding=(20, 18, 20, 16))
    marco.columnconfigure(2, weight=1)
    resultado: dict = {"datos": None}
    por_defecto = raw.get("defaults", {}).get("remote", model.DEFAULT_REMOTE)

    fila = _cabecera_form(marco, titulo or "Pareja", marca, subtitulo, 0)

    def pista(clave: str, por_si_no_hay: str) -> str:
        if catalogo is None:
            return por_si_no_hay
        suyo = catalogo.get(clave)
        marca_dif = "✎ " if str(actual.get(clave, "") or "") != str(suyo or "") else ""
        return f"{marca_dif}catálogo: {suyo if suyo not in (None, '') else '—'}"

    def etiqueta(texto: str, en: int, arriba: bool = False) -> None:
        ttk.Label(marco, text=texto, style="Campo.TLabel", anchor="e",
                  width=13).grid(row=en, column=0, sticky="ne" if arriba else "e",
                                 padx=(0, 12), pady=(5, 0) if arriba else 0)

    campos: dict[str, tk.StringVar] = {}
    for clave, titulo_campo, ayuda, mono in (
            ("name", "Nombre", "nombra también su carpeta en state/", False),
            ("local", "Ruta local", "relativa a la raíz del dispositivo", True),
            ("remote_path", "Ruta remota", "en el remoto, p. ej. /datos/notas", True),
            ("remote", "Remoto", f"vacío = el de [defaults] ({por_defecto})", True)):
        etiqueta(titulo_campo, fila)
        var = tk.StringVar(value=str(actual.get(clave, "")))
        campos[clave] = var
        ttk.Entry(marco, textvariable=var, width=38,
                  style="Mono.TEntry" if mono else "TEntry").grid(
            row=fila, column=1, sticky="w", pady=3)
        ttk.Label(marco, text=pista(clave, ayuda), style="Pista.TLabel",
                  wraplength=250, justify="left").grid(row=fila, column=2,
                                                       sticky="w", padx=(12, 0))
        fila += 1

    etiqueta("Modo", fila)
    modo = tk.StringVar(value=actual.get("mode", model.DEFAULT_MODE))
    ttk.Combobox(marco, textvariable=modo, state="readonly", width=36,
                 values=sorted(model.MODES)).grid(row=fila, column=1, sticky="w",
                                                  pady=3)
    aviso_modo = ttk.Label(marco, style="Aviso.TLabel", wraplength=250,
                           justify="left")
    aviso_modo.grid(row=fila, column=2, sticky="w", padx=(12, 0))

    def modo_cambiado(*_):
        aviso = pair_editor.mirror_warning(modo.get())
        aviso_modo.configure(text=aviso or pista("mode", ""),
                             style="Aviso.TLabel" if aviso else "Pista.TLabel")
    modo.trace_add("write", modo_cambiado)
    modo_cambiado()
    fila += 1

    textos: dict[str, tk.Text] = {}
    for clave, titulo_campo in (("include", "Incluir"), ("exclude", "Excluir")):
        etiqueta(titulo_campo, fila, arriba=True)
        caja = theme.caja_texto(marco, width=38, height=4)
        caja.insert("1.0", "\n".join(actual.get(clave, []) or []))
        caja.grid(row=fila, column=1, sticky="w", pady=(8, 2))
        textos[clave] = caja
        ttk.Label(marco, style="Pista.TLabel", wraplength=250, justify="left",
                  text=pista(clave, "Un patrón por línea. Vacío = todo.")).grid(
            row=fila, column=2, sticky="nw", padx=(12, 0), pady=(8, 0))
        fila += 1

    # Los flags viven en su propio diálogo: son muchos, casi siempre no se tocan,
    # y lo que de verdad hay que ver de ellos —cuáles acaban valiendo— no cabe al
    # lado de un campo de texto.
    avanzado = {"flags": dict(actual.get("flags") or {}),
                "extra_flags": list(model._as_tuple(actual.get("extra_flags")))}

    caja_flags = ttk.Frame(marco, style="Card.TFrame", padding=(12, 10))
    caja_flags.grid(row=fila, column=0, columnspan=3, sticky="ew", pady=(14, 0))
    caja_flags.columnconfigure(1, weight=1)
    img = icons.get(caja_flags, "flag", 18, theme.TINTA2, theme.SUPERFICIE)
    marca_flags = ttk.Label(caja_flags, style="Card.TLabel")
    if img is not None:
        marca_flags.configure(image=img)
        marca_flags.image = img
    marca_flags.grid(row=0, column=0, rowspan=2, sticky="w", padx=(0, 10))
    ttk.Label(caja_flags, text="Flags de rclone",
              style="Card.Fuerte.TLabel").grid(row=0, column=1, sticky="w")
    resumen = ttk.Label(caja_flags, style="Card.Pista.TLabel", wraplength=420,
                        justify="left")
    resumen.grid(row=1, column=1, sticky="w")

    def editar_flags():
        nombre = campos["name"].get().strip() or original_name or "la pareja nueva"
        datos = flags_form(dlg, f"Flags de rclone de '{nombre}'",
                           "Se guardan en [pair.flags]; los que no pongas salen del "
                           "modo y de [defaults].",
                           avanzado["flags"], avanzado["extra_flags"],
                           mode_name=modo.get(),
                           defaults_flags=(raw.get("defaults") or {}).get("flags"),
                           catalogo_flags=(catalogo or {}).get("flags") if catalogo else None)
        if datos is None:
            return
        avanzado.update(datos)
        resumen.configure(text=flags_editor.summary(avanzado["flags"],
                                                    avanzado["extra_flags"]))

    resumen.configure(text=flags_editor.summary(avanzado["flags"],
                                                avanzado["extra_flags"]))
    ttk.Button(caja_flags, text="Editar flags…", command=editar_flags).grid(
        row=0, column=2, rowspan=2, sticky="e")
    fila += 1

    def aceptar():
        resultado["datos"] = {
            **{k: v.get() for k, v in campos.items()},
            "mode": modo.get(),
            **{k: caja.get("1.0", "end").splitlines() for k, caja in textos.items()},
            "flags": dict(avanzado["flags"]),
            "extra_flags": list(avanzado["extra_flags"]),
        }
        dlg.destroy()

    ttk.Separator(marco, orient="horizontal").grid(row=fila, column=0, columnspan=3,
                                                   sticky="ew", pady=(16, 0))
    pie = ttk.Frame(marco)
    pie.grid(row=fila + 1, column=0, columnspan=3, sticky="ew", pady=(14, 0))
    pie.columnconfigure(0, weight=1)
    ttk.Label(pie, text="Antes de guardar se enseña qué va a pasar.",
              style="Pista.TLabel").grid(row=0, column=0, sticky="w")
    ttk.Button(pie, text="Cancelar", command=dlg.destroy).grid(row=0, column=1,
                                                               padx=(10, 6))
    ttk.Button(pie, text="Guardar…", style="Primary.TButton",
               command=aceptar).grid(row=0, column=2)

    mostrar(dlg, parent)
    return resultado["datos"]


def defaults_form(parent, actual: dict, catalogo: dict | None,
                  titulo: str, subtitulo: str, marca: str | None = None) -> dict | None:
    """El formulario de [defaults]. Devuelve el bloque entero, o None.

    Lo que no se edita aquí (use_filters_file…) viaja tal cual: este formulario
    devuelve los [defaults] completos, no un parche."""
    import tkinter as tk
    from tkinter import ttk

    dlg = modal(parent, titulo)
    marco = cuerpo_visible(dlg, padding=(20, 18, 20, 16))
    marco.columnconfigure(2, weight=1)
    resultado: dict = {"datos": None}

    fila = _cabecera_form(marco, titulo, marca, subtitulo, 0)

    def pista(clave: str, ayuda: str) -> str:
        if catalogo is None:
            return ayuda
        suyo = catalogo.get(clave)
        dif = "✎ " if str(actual.get(clave, "") or "") != str(suyo or "") else ""
        return f"{dif}catálogo: {suyo if suyo not in (None, '') else '—'}"

    def etiqueta(texto: str, en: int, arriba: bool = False) -> None:
        ttk.Label(marco, text=texto, style="Campo.TLabel", anchor="e",
                  width=16).grid(row=en, column=0, sticky="ne" if arriba else "e",
                                 padx=(0, 12), pady=(5, 0) if arriba else 0)

    campos: dict[str, tk.StringVar] = {}
    for clave, titulo_campo, ayuda in (
            ("remote", "Remoto", "el nombre del remote en rclone.conf"),
            ("device_remote", "Remote del dispositivo",
             "vacío = desactivado; cambiarlo invalida los baselines"),
            ("catalog_path", "Ruta del catálogo",
             f"vacío = {catalog.DEFAULT_CATALOG_PATH}")):
        etiqueta(titulo_campo, fila)
        var = tk.StringVar(value=str(actual.get(clave, "") or ""))
        campos[clave] = var
        ttk.Entry(marco, textvariable=var, width=38, style="Mono.TEntry").grid(
            row=fila, column=1, sticky="w", pady=3)
        ttk.Label(marco, text=pista(clave, ayuda), style="Pista.TLabel",
                  wraplength=260, justify="left").grid(row=fila, column=2,
                                                       sticky="w", padx=(12, 0))
        fila += 1

    guardar_logs = tk.BooleanVar(value=bool(actual.get("keep_logs", False)))
    ttk.Checkbutton(marco, variable=guardar_logs,
                    text="Guardar también los logs de las pasadas que van bien").grid(
        row=fila, column=1, columnspan=2, sticky="w", pady=(10, 2))
    fila += 1

    textos: dict[str, tk.Text] = {}
    for clave, titulo_campo in (("include", "Incluir en todas"),
                                ("exclude", "Excluir en todas")):
        etiqueta(titulo_campo, fila, arriba=True)
        caja = theme.caja_texto(marco, width=38, height=4)
        caja.insert("1.0", "\n".join(actual.get(clave, []) or []))
        caja.grid(row=fila, column=1, sticky="w", pady=(8, 2))
        textos[clave] = caja
        ttk.Label(marco, style="Pista.TLabel", wraplength=260, justify="left",
                  text="Un patrón por línea. Vale para todas las parejas.").grid(
            row=fila, column=2, sticky="nw", padx=(12, 0), pady=(8, 0))
        fila += 1

    avanzado = {"flags": dict(actual.get("flags") or {}),
                "extra_flags": list(model._as_tuple(actual.get("extra_flags")))}

    caja_flags = ttk.Frame(marco, style="Card.TFrame", padding=(12, 10))
    caja_flags.grid(row=fila, column=0, columnspan=3, sticky="ew", pady=(14, 0))
    caja_flags.columnconfigure(1, weight=1)
    img = icons.get(caja_flags, "flag", 18, theme.TINTA2, theme.SUPERFICIE)
    marca_flags = ttk.Label(caja_flags, style="Card.TLabel")
    if img is not None:
        marca_flags.configure(image=img)
        marca_flags.image = img
    marca_flags.grid(row=0, column=0, rowspan=2, sticky="w", padx=(0, 10))
    ttk.Label(caja_flags, text="Flags de rclone comunes",
              style="Card.Fuerte.TLabel").grid(row=0, column=1, sticky="w")
    resumen = ttk.Label(caja_flags, style="Card.Pista.TLabel", wraplength=420,
                        justify="left")
    resumen.grid(row=1, column=1, sticky="w")

    def editar_flags():
        datos = flags_form(dlg, "Flags de rclone comunes",
                           "Se guardan en [defaults.flags] y valen para todas las "
                           "parejas que no lleven el suyo.",
                           avanzado["flags"], avanzado["extra_flags"],
                           mode_name=None,
                           defaults_flags=None,
                           catalogo_flags=(catalogo or {}).get("flags") if catalogo else None)
        if datos is None:
            return
        avanzado.update(datos)
        resumen.configure(text=flags_editor.summary(avanzado["flags"],
                                                    avanzado["extra_flags"]))

    resumen.configure(text=flags_editor.summary(avanzado["flags"],
                                                avanzado["extra_flags"]))
    ttk.Button(caja_flags, text="Editar flags…", command=editar_flags).grid(
        row=0, column=2, rowspan=2, sticky="e")
    fila += 1

    bloque_aviso(marco, "Ojo con 'Remote del dispositivo' y 'Remoto': alimentan los "
                        "extremos de todas las parejas, así que cambiarlos aparta "
                        "sus baselines.", ancho=620).grid(
        row=fila, column=0, columnspan=3, sticky="ew", pady=(12, 0))
    fila += 1

    def aceptar():
        datos = {k: v for k, v in actual.items() if k not in DEFAULTS_KEYS
                 and k not in ("keep_logs", "include", "exclude",
                               "flags", "extra_flags")}
        if avanzado["flags"]:
            datos["flags"] = dict(avanzado["flags"])
        if avanzado["extra_flags"]:
            datos["extra_flags"] = list(avanzado["extra_flags"])
        for clave, var in campos.items():
            valor = var.get().strip()
            if valor:
                datos[clave] = valor
        if guardar_logs.get():
            datos["keep_logs"] = True
        for clave, caja in textos.items():
            patrones = [x.strip() for x in caja.get("1.0", "end").splitlines() if x.strip()]
            if patrones:
                datos[clave] = patrones
        resultado["datos"] = datos
        dlg.destroy()

    ttk.Separator(marco, orient="horizontal").grid(row=fila, column=0, columnspan=3,
                                                   sticky="ew", pady=(16, 0))
    pie = ttk.Frame(marco)
    pie.grid(row=fila + 1, column=0, columnspan=3, sticky="ew", pady=(14, 0))
    pie.columnconfigure(0, weight=1)
    ttk.Label(pie, text="Antes de guardar se enseña qué va a pasar.",
              style="Pista.TLabel").grid(row=0, column=0, sticky="w")
    ttk.Button(pie, text="Cancelar", command=dlg.destroy).grid(row=0, column=1,
                                                               padx=(10, 6))
    ttk.Button(pie, text="Guardar…", style="Primary.TButton",
               command=aceptar).grid(row=0, column=2)

    mostrar(dlg, parent)
    return resultado["datos"]


# ---------------------------------------------------------------------------
# El editor de flags
# ---------------------------------------------------------------------------

def flags_form(parent, titulo: str, subtitulo: str, flags: dict, extra: list,
               mode_name: str | None, defaults_flags: dict | None,
               catalogo_flags: dict | None = None) -> dict | None:
    """El editor de flags. Devuelve {"flags", "extra_flags"}, o None si se cancela.

    Se edita como texto TOML y no con una fila por flag a propósito: los flags de
    rclone son cientos, cambian con cada versión y ninguna lista que pusiéramos
    aquí estaría al día. Lo que sí se puede dar es lo que no se ve escribiéndolos
    en el TOML —qué queda valiendo al fundir base, modo, [defaults] y pareja—, y
    eso es la tabla de la derecha.

    El diálogo NO se cierra si lo escrito no vale, y el motivo se enseña DENTRO,
    en un recuadro rojo bajo el texto, no en un `messagebox`: el aviso tiene que
    poder leerse mientras se corrige lo escrito. Cerrar y perderlo, o peor,
    guardar solo lo que se entendió, es exactamente lo que no puede pasar con un
    fichero que gobierna borrados."""
    from tkinter import ttk

    dlg = modal(parent, titulo)
    marco = cuerpo_visible(dlg, padding=(20, 18, 20, 16))
    marco.columnconfigure(1, weight=1)
    resultado: dict = {"datos": None}

    ttk.Label(marco, text=titulo, style="Dialogo.TLabel").grid(
        row=0, column=0, columnspan=2, sticky="w")
    ttk.Label(marco, text=subtitulo, style="Pista.TLabel", wraplength=600,
              justify="left").grid(row=1, column=0, columnspan=2, sticky="w",
                                   pady=(5, 0))

    # --- lo que se escribe ---------------------------------------------------
    izquierda = ttk.Frame(marco)
    izquierda.grid(row=2, column=0, sticky="nsew", pady=(16, 0))

    ttk.Label(izquierda, text=theme.rotulo("Lo que escribes"),
              style="Rotulo.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 7))
    caja = theme.caja_texto(izquierda, width=40, height=8)
    caja.insert("1.0", flags_editor.dump(flags))
    caja.grid(row=1, column=0, sticky="ew")
    ttk.Label(izquierda, style="Pista.TLabel", wraplength=330, justify="left",
              text=("Tal cual se escriben en el TOML: transfers = 4, "
                    'conflict-resolve = "newer", checksum = true. Sin los guiones '
                    "de delante.")).grid(row=2, column=0, sticky="w", pady=(7, 0))

    problema = ttk.Frame(izquierda)      # el recuadro rojo, vacío mientras todo vale
    problema.grid(row=3, column=0, sticky="ew", pady=(8, 0))
    problema.columnconfigure(0, weight=1)

    ttk.Label(izquierda, text=theme.rotulo("Argumentos extra"),
              style="Rotulo.TLabel").grid(row=4, column=0, sticky="w", pady=(16, 7))
    caja_extra = theme.caja_texto(izquierda, width=40, height=3)
    caja_extra.insert("1.0", flags_editor.dump_extra(extra))
    caja_extra.grid(row=5, column=0, sticky="ew")
    ttk.Label(izquierda, style="Pista.TLabel", wraplength=330, justify="left",
              text=("Van a la línea de comandos sin tocar: --bwlimit y 8M son DOS "
                    "líneas.")).grid(row=6, column=0, sticky="w", pady=(7, 0))

    if catalogo_flags is not None:
        ttk.Label(izquierda, style="MonoPista.TLabel", wraplength=330,
                  justify="left",
                  text="Catálogo: " + (flags_editor.dump(catalogo_flags).replace(
                      "\n", "  ·  ") or "ninguno")).grid(row=7, column=0,
                                                         sticky="w", pady=(8, 0))

    # --- lo que acabaría recibiendo rclone -----------------------------------
    derecha = ttk.Frame(marco)
    derecha.grid(row=2, column=1, sticky="nsew", pady=(16, 0), padx=(18, 0))
    derecha.columnconfigure(0, weight=1)
    derecha.rowconfigure(1, weight=1)

    titulo_tabla = ttk.Frame(derecha)
    titulo_tabla.grid(row=0, column=0, sticky="ew", pady=(0, 7))
    titulo_tabla.columnconfigure(0, weight=1)
    ttk.Label(titulo_tabla, text=theme.rotulo("Lo que acabaría recibiendo rclone"),
              style="Rotulo.TLabel").grid(row=0, column=0, sticky="w")

    tarjeta = ttk.Frame(derecha, style="Card.TFrame", padding=(6, 6, 2, 4))
    tarjeta.grid(row=1, column=0, sticky="nsew")
    tarjeta.columnconfigure(0, weight=1)
    tarjeta.rowconfigure(0, weight=1)
    tabla = ttk.Treeview(tarjeta, columns=("flag", "origen"), show="headings",
                         height=12, selectmode="none")
    tabla.heading("flag", text="Flag")
    tabla.heading("origen", text="Sale de")
    tabla.column("flag", width=290)
    tabla.column("origen", width=110)
    tabla.grid(row=0, column=0, sticky="nsew")
    tabla.tag_configure("propio", foreground=theme.OK)
    tabla.tag_configure("heredado", foreground=theme.TINTA2)
    tabla.tag_configure("base", foreground=theme.TINTA3)

    ttk.Label(derecha, style="Pista.TLabel", wraplength=380, justify="left",
              text="Se funden en este orden: siempre → modo → [defaults] → esta "
                   "pareja.").grid(row=2, column=0, sticky="w", pady=(8, 0))

    def avisar(texto: str | None) -> None:
        for hijo in problema.winfo_children():
            hijo.destroy()
        if texto:
            bloque_aviso(problema, texto, ancho=300, tipo="Rojo").grid(
                row=0, column=0, sticky="ew")

    def leer() -> dict | None:
        """Lo escrito, ya validado. None si no vale (y ya se ha avisado)."""
        try:
            datos = {"flags": flags_editor.parse(caja.get("1.0", "end")),
                     "extra_flags": flags_editor.parse_extra(caja_extra.get("1.0", "end"))}
        except ConfigError as e:
            avisar(str(e))
            return None
        avisar(None)
        return datos

    def repasar():
        datos = leer()
        if datos is None:
            return
        tabla.delete(*tabla.get_children())
        for i, fila in enumerate(flags_editor.effective(mode_name, defaults_flags,
                                                        datos["flags"])):
            etiqueta = ("propio" if fila.origen == "esta pareja"
                        else "base" if fila.origen == "siempre" else "heredado")
            tabla.insert("", "end", iid=str(i), tags=(etiqueta,),
                         values=(fila.flag, fila.origen))
        for arg in datos["extra_flags"]:
            tabla.insert("", "end", tags=("propio",), values=(arg, "extra"))

    def aceptar():
        datos = leer()
        if datos is None:
            return                       # el diálogo se queda abierto, con el texto
        resultado["datos"] = datos
        dlg.destroy()

    ver = ttk.Button(titulo_tabla, text="Ver el efecto", style="Quiet.TButton",
                     command=repasar)
    theme.boton_icono(ver, "eye", theme.ACENTO, theme.PAPEL, 14)
    ver.grid(row=0, column=1, sticky="e")

    ttk.Separator(marco, orient="horizontal").grid(row=3, column=0, columnspan=2,
                                                   sticky="ew", pady=(16, 0))
    pie = ttk.Frame(marco)
    pie.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(14, 0))
    pie.columnconfigure(0, weight=1)
    ttk.Label(pie, text="Si algo no vale, el diálogo no se cierra: lo escrito se "
                        "queda.", style="Pista.TLabel").grid(row=0, column=0,
                                                             sticky="w")
    ttk.Button(pie, text="Cancelar", command=dlg.destroy).grid(row=0, column=1,
                                                               padx=(10, 6))
    ttk.Button(pie, text="Aceptar", style="Primary.TButton",
               command=aceptar).grid(row=0, column=2)

    repasar()
    mostrar(dlg, parent)
    return resultado["datos"]
