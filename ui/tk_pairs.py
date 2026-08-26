#!/usr/bin/env python3
"""
tk_pairs.py — La pantalla de parejas.

Solo dibuja. Todo lo que decide y todo lo que toca el disco está en
`ui/pair_editor.py` (este pen) y `ui/catalog_editor.py` (el catálogo del NAS), y
el guion es siempre el mismo: se pide un plan, se enseñan sus consecuencias, y
solo si el usuario confirma se ejecuta. Ninguna acción de esta pantalla escribe
nada sin haber enseñado antes lo que va a pasar.

La lista es una sola pero los botones van en dos bloques separados, y esa
separación es el asunto de la pantalla: arriba, lo que cambia el catálogo y por
tanto afecta a todos los dispositivos; abajo, lo que cambia solo este pen. Una
pareja se crea o se borra en el catálogo, y después cada pen elige si la usa.
"""

from __future__ import annotations

from common import catalog, config_file, model
from common.model import ConfigError

from . import catalog_editor, flags_editor, pair_editor
from .tk import TITLE, modal, mostrar

COLUMNAS = [
    ("usa", "En el pen", 70),
    ("pareja", "Pareja", 100),
    ("modo", "Modo", 85),
    ("local", "Local", 175),
    ("remoto", "Remoto", 195),
    ("origen", "Origen", 155),
    ("estado", "Estado", 120),
    ("aviso", "", 170),
]

# Los campos de texto del formulario de [defaults]. Los flags tienen su propio
# diálogo, y lo que no sale por ningún sitio (use_filters_file…) se conserva tal
# cual, igual que en las parejas.
DEFAULTS_KEYS = ("remote", "pen_remote", "catalog_path")


def open_dialog(parent, config) -> bool:
    """Abre la pantalla. Devuelve True si se ha cambiado el config de este pen."""
    from tkinter import messagebox, ttk

    dlg = modal(parent, "Parejas")
    raw = config_file.load_raw()
    cat, aviso = catalog.load(raw)
    estado = {"raw": raw, "config": config, "cat": cat, "cambiado": False}

    marco = ttk.Frame(dlg, padding=12)
    marco.grid(sticky="nsew")

    cabecera = ttk.Label(marco, text="", foreground="#666666", wraplength=880,
                         justify="left")
    cabecera.grid(row=0, column=0, columnspan=5, sticky="w")

    # Los [defaults] van con su propia línea y sus propios botones: no son una
    # pareja más, y sus botones dicen casi lo mismo que los de abajo. Juntos se
    # confunden; separados se lee de un vistazo a qué se refiere cada uno.
    fila_defaults = ttk.Frame(marco)
    fila_defaults.grid(row=1, column=0, columnspan=5, sticky="w", pady=(4, 10))
    linea_defaults = ttk.Label(fila_defaults, text="", wraplength=380, justify="left")
    linea_defaults.grid(row=0, column=0, sticky="w", padx=(0, 10))

    tree = ttk.Treeview(marco, columns=[c[0] for c in COLUMNAS],
                        show="headings", height=10, selectmode="browse")
    for clave, titulo, ancho in COLUMNAS:
        tree.heading(clave, text=titulo)
        tree.column(clave, width=ancho, anchor="center" if clave == "usa" else "w")
    tree.grid(row=2, column=0, columnspan=4, sticky="nsew")
    scroll = ttk.Scrollbar(marco, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scroll.set)
    scroll.grid(row=2, column=4, sticky="ns")

    pie = ttk.Label(marco, text="", foreground="#666666", wraplength=880, justify="left")
    pie.grid(row=3, column=0, columnspan=5, sticky="w", pady=(8, 0))

    botones_catalogo: list = []

    def refrescar(nota: str = "") -> None:
        estado["raw"] = config_file.load_raw()
        estado["config"] = model.parse_config(estado["raw"])
        cat = estado["cat"]

        donde = cat.endpoint if cat else catalog.endpoint(estado["raw"])
        if cat is None:
            cabecera.configure(text=f"Catálogo {donde}: {aviso}")
        elif cat.editable:
            cabecera.configure(text=f"Catálogo {donde} — leído: {cat.stamp}")
        else:
            cabecera.configure(text=f"Catálogo {donde} — {aviso}")

        origen, difiere = pair_editor.defaults_origin(estado["raw"], cat)
        detalle = f" ({', '.join(difiere)})" if difiere else ""
        linea_defaults.configure(text=f"[defaults]: {origen}{detalle}")

        tree.delete(*tree.get_children())
        for fila in pair_editor.catalog_rows(estado["config"], estado["raw"], cat):
            marca = "✓" if fila.en_pen else ""
            origen = fila.origen + (f" ({', '.join(fila.difiere)})" if fila.difiere else "")
            tree.insert("", "end", iid=fila.name,
                        values=(marca, fila.name, fila.mode, fila.local, fila.remote,
                                origen, fila.estado, fila.aviso or ""))

        puede = "normal" if (cat is not None and cat.editable) else "disabled"
        for boton in botones_catalogo:
            boton.configure(state=puede)
        pie.configure(text=nota)

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

    def confirmar(plan) -> bool:
        texto = "\n".join(f"• {c}" for c in plan.consequences)
        if plan.warnings:
            texto += "\n\n" + "\n".join(f"⚠ {w}" for w in plan.warnings)
        return bool(messagebox.askokcancel(TITLE, texto + "\n\n¿Seguir adelante?",
                                           parent=dlg))

    def aplicar(plan, del_catalogo: bool = False) -> None:
        """Confirmar y ejecutar. Un plan del catálogo no cambia este pen."""
        if not confirmar(plan):
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

    # --- este pen ----------------------------------------------------------

    def usar_aqui() -> None:
        fila = fila_elegida()
        if fila is None:
            return
        try:
            aplicar(pair_editor.plan_enable(estado["raw"], estado["cat"], fila.name))
        except ConfigError as e:
            fallo(e)

    def quitar() -> None:
        fila = fila_elegida()
        if fila is None:
            return
        if not fila.en_pen:
            messagebox.showinfo(TITLE, f"'{fila.name}' no se está usando en este pen.",
                                parent=dlg)
            return
        limpiar = preguntar_limpieza(dlg, fila.name)
        if limpiar is None:
            return
        try:
            aplicar(pair_editor.plan_remove(estado["raw"], fila.name, clean_state=limpiar))
        except ConfigError as e:
            fallo(e)

    def modificar_aqui() -> None:
        fila = fila_elegida()
        if fila is None:
            return
        if not fila.en_pen:
            messagebox.showinfo(TITLE, f"'{fila.name}' todavía no se usa en este pen: "
                                       f"úsala primero y luego modifícala.", parent=dlg)
            return
        actual = next(p for p in estado["raw"]["pair"] if p.get("name") == fila.name)
        datos = formulario(dlg, estado["raw"], fila.name, actual,
                           catalogo=catalog.find_pair(estado["cat"], fila.name),
                           titulo=f"Modificar '{fila.name}' solo en este pen",
                           subtitulo="El catálogo no cambia: este cambio se queda aquí.")
        if datos is None:
            return
        try:
            aplicar(pair_editor.plan_override(estado["raw"], estado["cat"],
                                              fila.name, datos))
        except ConfigError as e:
            fallo(e)

    def volver_al_catalogo() -> None:
        fila = fila_elegida()
        if fila is None:
            return
        try:
            aplicar(pair_editor.plan_revert(estado["raw"], estado["cat"], fila.name))
        except ConfigError as e:
            fallo(e)

    def defaults_del_pen() -> None:
        cat = estado["cat"]
        actuales = dict(estado["raw"].get("defaults") or {})
        datos = defaults_form(dlg, actuales, cat.defaults if cat else None,
                              "Ajustes generales de este pen",
                              "Valen para todas las parejas de este pen.")
        if datos is None:
            return
        try:
            aplicar(pair_editor.plan_defaults(estado["raw"], datos))
        except ConfigError as e:
            fallo(e)

    def volver_defaults() -> None:
        try:
            aplicar(pair_editor.plan_revert_defaults(estado["raw"], estado["cat"]))
        except ConfigError as e:
            fallo(e)

    # --- catálogo ----------------------------------------------------------

    def catalogo_nueva() -> None:
        datos = formulario(dlg, (estado["cat"].raw if estado["cat"] else {}), None, {},
                           titulo="Nueva pareja en el catálogo",
                           subtitulo="Queda disponible para todos los pens; usarla "
                                     "aquí es el paso siguiente.")
        if datos is None:
            return
        try:
            aplicar(catalog_editor.plan_catalog_save(estado["cat"], datos, None,
                                                     estado["raw"]), del_catalogo=True)
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
                           subtitulo="Afecta a TODOS los dispositivos.")
        if datos is None:
            return
        try:
            aplicar(catalog_editor.plan_catalog_save(estado["cat"], datos, fila.name,
                                                     estado["raw"]), del_catalogo=True)
        except ConfigError as e:
            fallo(e)

    def catalogo_borrar() -> None:
        fila = fila_elegida()
        if fila is None:
            return
        try:
            aplicar(catalog_editor.plan_catalog_remove(estado["cat"], fila.name,
                                                       estado["raw"]), del_catalogo=True)
        except ConfigError as e:
            fallo(e)

    def catalogo_defaults() -> None:
        cat = estado["cat"]
        if cat is None:
            fallo(ConfigError("No hay catálogo que editar."))
            return
        datos = defaults_form(dlg, cat.defaults, None,
                              "Ajustes generales del catálogo",
                              "Afecta a TODOS los dispositivos.")
        if datos is None:
            return
        try:
            aplicar(catalog_editor.plan_catalog_defaults(cat, datos, estado["raw"]),
                    del_catalogo=True)
        except ConfigError as e:
            fallo(e)

    def recargar_catalogo() -> None:
        nonlocal aviso
        estado["cat"], aviso = catalog.load(estado["raw"])
        refrescar("Catálogo releído." if estado["cat"] else "")

    # --- los dos bloques de botones ----------------------------------------

    for i, (texto, accion) in enumerate((
            ("Ajustes de este pen…", defaults_del_pen),
            ("Volver a los del catálogo", volver_defaults)), start=1):
        ttk.Button(fila_defaults, text=texto, command=accion).grid(row=0, column=i, padx=3)
    boton = ttk.Button(fila_defaults, text="Ajustes del catálogo…",
                       command=catalogo_defaults)
    boton.grid(row=0, column=3, padx=3)
    botones_catalogo.append(boton)

    pen = ttk.Frame(marco)
    pen.grid(row=4, column=0, columnspan=5, pady=(12, 0), sticky="w")
    ttk.Label(pen, text="Este pen:", width=11).grid(row=0, column=0, sticky="w")
    for i, (texto, accion) in enumerate((
            ("Usar aquí", usar_aqui),
            ("Quitar…", quitar),
            ("Modificar aquí…", modificar_aqui),
            ("Volver al catálogo", volver_al_catalogo)), start=1):
        ttk.Button(pen, text=texto, command=accion).grid(row=0, column=i, padx=3)

    cat_frame = ttk.Frame(marco)
    cat_frame.grid(row=5, column=0, columnspan=5, pady=(6, 0), sticky="w")
    ttk.Label(cat_frame, text="Catálogo:", width=11).grid(row=0, column=0, sticky="w")
    for i, (texto, accion) in enumerate((
            ("Nueva…", catalogo_nueva),
            ("Editar…", catalogo_editar),
            ("Borrar…", catalogo_borrar)), start=1):
        boton = ttk.Button(cat_frame, text=texto, command=accion)
        boton.grid(row=0, column=i, padx=3)
        botones_catalogo.append(boton)
    ttk.Label(cat_frame, text="(afecta a TODOS los dispositivos)",
              foreground="#775500").grid(row=0, column=4, sticky="w", padx=(8, 0))

    cierre = ttk.Frame(marco)
    cierre.grid(row=6, column=0, columnspan=5, pady=(14, 0), sticky="w")
    ttk.Button(cierre, text="Releer catálogo",
               command=recargar_catalogo).grid(row=0, column=0, padx=3)
    ttk.Button(cierre, text="Cerrar", command=dlg.destroy).grid(row=0, column=1, padx=3)

    refrescar()
    mostrar(dlg, parent)
    return estado["cambiado"]


def preguntar_limpieza(parent, name: str) -> bool | None:
    """¿Apartar también su estado? None = cancelar."""
    import tkinter as tk
    from tkinter import ttk

    dlg = modal(parent, f"Quitar '{name}'")
    marco = ttk.Frame(dlg, padding=12)
    marco.grid(sticky="nsew")
    respuesta = {"valor": None}

    ttk.Label(marco, justify="left", wraplength=420,
              text=(f"'{name}' dejará de sincronizarse en este pen.\n\n"
                    "Los datos NO se tocan, ni en el pen ni en el NAS, y la pareja "
                    "sigue en el catálogo: se puede volver a usar cuando "
                    "quieras.")).grid(row=0, column=0, sticky="w")

    limpiar = tk.BooleanVar(value=False)
    ttk.Checkbutton(marco, variable=limpiar, text=(
        "Apartar también su baseline y borrar sus filtros generados")).grid(
        row=1, column=0, sticky="w", pady=(10, 0))
    ttk.Label(marco, foreground="#666666", wraplength=420, justify="left",
              text=("El baseline se renombra a state/<pareja>.old-<fecha>/, no se "
                    "borra. Si no marcas nada, se queda todo donde está.")).grid(
        row=2, column=0, sticky="w", padx=(24, 0))

    def aceptar():
        respuesta["valor"] = bool(limpiar.get())
        dlg.destroy()

    pie = ttk.Frame(marco)
    pie.grid(row=3, column=0, pady=(14, 0))
    ttk.Button(pie, text="Quitar", command=aceptar).grid(row=0, column=0, padx=3)
    ttk.Button(pie, text="Cancelar", command=dlg.destroy).grid(row=0, column=1, padx=3)

    mostrar(dlg, parent)
    return respuesta["valor"]


def formulario(parent, raw: dict, original_name: str | None, actual: dict,
               catalogo: dict | None = None, titulo: str | None = None,
               subtitulo: str | None = None) -> dict | None:
    """El formulario de una pareja. Devuelve los campos, o None si se cancela.

    `catalogo` es la entrada del catálogo con la que comparar: junto a cada campo
    se enseña lo que dice el catálogo y se marca con ✎ el que difiere, que es lo
    que convierte «modificar aquí» en una decisión informada."""
    import tkinter as tk
    from tkinter import ttk

    dlg = modal(parent, titulo or (f"Editar '{original_name}'" if original_name
                                   else "Nueva pareja"))
    marco = ttk.Frame(dlg, padding=12)
    marco.grid(sticky="nsew")
    resultado: dict = {"datos": None}
    por_defecto = raw.get("defaults", {}).get("remote", model.DEFAULT_REMOTE)
    fila = 0

    if subtitulo:
        ttk.Label(marco, text=subtitulo, foreground="#775500", wraplength=620,
                  justify="left").grid(row=0, column=0, columnspan=3, sticky="w",
                                       pady=(0, 8))
        fila = 1

    def pista(clave: str, por_si_no_hay: str) -> str:
        if catalogo is None:
            return por_si_no_hay
        suyo = catalogo.get(clave)
        marca = "✎ " if str(actual.get(clave, "") or "") != str(suyo or "") else ""
        return f"{marca}catálogo: {suyo if suyo not in (None, '') else '—'}"

    campos: dict[str, tk.StringVar] = {}
    for clave, etiqueta, ayuda in (
            ("name", "Nombre", "identifica la pareja y nombra su carpeta en state/"),
            ("local", "Ruta local", "relativa a la raíz del pen, p. ej. sync-data/notas"),
            ("remote_path", "Ruta remota", "en el NAS, p. ej. /PJ/Notas"),
            ("remote", "Remoto", f"vacío = el de [defaults] ({por_defecto})")):
        ttk.Label(marco, text=etiqueta + ":").grid(row=fila, column=0, sticky="w", pady=2)
        var = tk.StringVar(value=str(actual.get(clave, "")))
        campos[clave] = var
        ttk.Entry(marco, textvariable=var, width=44).grid(row=fila, column=1, sticky="w")
        ttk.Label(marco, text=pista(clave, ayuda), foreground="#666666").grid(
            row=fila, column=2, sticky="w", padx=(8, 0))
        fila += 1

    ttk.Label(marco, text="Modo:").grid(row=fila, column=0, sticky="w", pady=2)
    modo = tk.StringVar(value=actual.get("mode", model.DEFAULT_MODE))
    ttk.Combobox(marco, textvariable=modo, state="readonly", width=42,
                 values=sorted(model.MODES)).grid(row=fila, column=1, sticky="w")
    aviso_modo = ttk.Label(marco, foreground="#775500", wraplength=260, justify="left")
    aviso_modo.grid(row=fila, column=2, sticky="w", padx=(8, 0))

    def modo_cambiado(*_):
        aviso = pair_editor.mirror_warning(modo.get())
        aviso_modo.configure(text=aviso or pista("mode", ""))
    modo.trace_add("write", modo_cambiado)
    modo_cambiado()
    fila += 1

    textos: dict[str, tk.Text] = {}
    for clave, etiqueta in (("include", "Incluir"), ("exclude", "Excluir")):
        ttk.Label(marco, text=f"{etiqueta} (uno por línea):").grid(
            row=fila, column=0, sticky="nw", pady=(8, 2))
        caja = tk.Text(marco, width=44, height=4, font=("Consolas", 9))
        caja.insert("1.0", "\n".join(actual.get(clave, []) or []))
        caja.grid(row=fila, column=1, sticky="w", pady=(8, 2))
        textos[clave] = caja
        if catalogo is not None:
            ttk.Label(marco, foreground="#666666", wraplength=260, justify="left",
                      text=pista(clave, "")).grid(row=fila, column=2, sticky="nw",
                                                  padx=(8, 0))
        fila += 1

    # Los flags viven en su propio diálogo: son muchos, casi siempre no se tocan,
    # y lo que de verdad hay que ver de ellos —cuáles acaban valiendo— no cabe al
    # lado de un campo de texto.
    avanzado = {"flags": dict(actual.get("flags") or {}),
                "extra_flags": list(model._as_tuple(actual.get("extra_flags")))}
    resumen = ttk.Label(marco, foreground="#666666")

    def editar_flags():
        nombre = campos["name"].get().strip() or original_name or "la pareja nueva"
        datos = flags_form(dlg, f"Flags de rclone de {nombre}",
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

    ttk.Button(marco, text="Flags de rclone…", command=editar_flags).grid(
        row=fila, column=1, sticky="w", pady=(10, 0))
    ttk.Label(marco, text="Flags:").grid(row=fila, column=0, sticky="w", pady=(10, 0))
    resumen.configure(text=flags_editor.summary(avanzado["flags"],
                                                avanzado["extra_flags"]))
    resumen.grid(row=fila, column=2, sticky="w", padx=(8, 0), pady=(10, 0))
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

    pie = ttk.Frame(marco)
    pie.grid(row=fila, column=0, columnspan=3, pady=(14, 0))
    ttk.Button(pie, text="Guardar…", command=aceptar).grid(row=0, column=0, padx=3)
    ttk.Button(pie, text="Cancelar", command=dlg.destroy).grid(row=0, column=1, padx=3)

    mostrar(dlg, parent)
    return resultado["datos"]


def defaults_form(parent, actual: dict, catalogo: dict | None,
                  titulo: str, subtitulo: str) -> dict | None:
    """El formulario de [defaults]. Devuelve el bloque entero, o None.

    Lo que no se edita aquí (use_filters_file…) viaja tal cual: este formulario
    devuelve los [defaults] completos, no un parche."""
    import tkinter as tk
    from tkinter import ttk

    dlg = modal(parent, titulo)
    marco = ttk.Frame(dlg, padding=12)
    marco.grid(sticky="nsew")
    resultado: dict = {"datos": None}

    ttk.Label(marco, text=subtitulo, foreground="#775500", wraplength=620,
              justify="left").grid(row=0, column=0, columnspan=3, sticky="w",
                                   pady=(0, 8))
    fila = 1

    def pista(clave: str, ayuda: str) -> str:
        if catalogo is None:
            return ayuda
        suyo = catalogo.get(clave)
        marca = "✎ " if str(actual.get(clave, "") or "") != str(suyo or "") else ""
        return f"{marca}catálogo: {suyo if suyo not in (None, '') else '—'}"

    campos: dict[str, tk.StringVar] = {}
    for clave, etiqueta, ayuda in (
            ("remote", "Remoto", "el nombre del remote en rclone.conf"),
            ("pen_remote", "Remote del pen",
             "vacío = desactivado; cambiarlo invalida los baselines"),
            ("catalog_path", "Ruta del catálogo",
             f"vacío = {catalog.DEFAULT_CATALOG_PATH}")):
        ttk.Label(marco, text=etiqueta + ":").grid(row=fila, column=0, sticky="w", pady=2)
        var = tk.StringVar(value=str(actual.get(clave, "") or ""))
        campos[clave] = var
        ttk.Entry(marco, textvariable=var, width=44).grid(row=fila, column=1, sticky="w")
        ttk.Label(marco, text=pista(clave, ayuda), foreground="#666666").grid(
            row=fila, column=2, sticky="w", padx=(8, 0))
        fila += 1

    guardar_logs = tk.BooleanVar(value=bool(actual.get("keep_logs", False)))
    ttk.Checkbutton(marco, variable=guardar_logs,
                    text="Guardar también los logs de las pasadas que van bien").grid(
        row=fila, column=0, columnspan=2, sticky="w", pady=(8, 2))
    fila += 1

    textos: dict[str, tk.Text] = {}
    for clave, etiqueta in (("include", "Incluir"), ("exclude", "Excluir")):
        ttk.Label(marco, text=f"{etiqueta} en todas (uno por línea):").grid(
            row=fila, column=0, sticky="nw", pady=(8, 2))
        caja = tk.Text(marco, width=44, height=4, font=("Consolas", 9))
        caja.insert("1.0", "\n".join(actual.get(clave, []) or []))
        caja.grid(row=fila, column=1, sticky="w", pady=(8, 2))
        textos[clave] = caja
        fila += 1

    avanzado = {"flags": dict(actual.get("flags") or {}),
                "extra_flags": list(model._as_tuple(actual.get("extra_flags")))}
    resumen = ttk.Label(marco, foreground="#666666")

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

    ttk.Label(marco, text="Flags:").grid(row=fila, column=0, sticky="w", pady=(10, 0))
    ttk.Button(marco, text="Flags de rclone…", command=editar_flags).grid(
        row=fila, column=1, sticky="w", pady=(10, 0))
    resumen.configure(text=flags_editor.summary(avanzado["flags"],
                                                avanzado["extra_flags"]))
    resumen.grid(row=fila, column=2, sticky="w", padx=(8, 0), pady=(10, 0))
    fila += 1

    ttk.Label(marco, foreground="#666666", wraplength=760, justify="left",
              text=("Ojo con 'Remote del pen' y 'Remoto': alimentan los extremos de "
                    "todas las parejas, así que cambiarlos aparta sus baselines.")).grid(
        row=fila, column=0, columnspan=3, sticky="w", pady=(10, 0))
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

    pie = ttk.Frame(marco)
    pie.grid(row=fila, column=0, columnspan=3, pady=(14, 0))
    ttk.Button(pie, text="Guardar…", command=aceptar).grid(row=0, column=0, padx=3)
    ttk.Button(pie, text="Cancelar", command=dlg.destroy).grid(row=0, column=1, padx=3)

    mostrar(dlg, parent)
    return resultado["datos"]


def flags_form(parent, titulo: str, subtitulo: str, flags: dict, extra: list,
               mode_name: str | None, defaults_flags: dict | None,
               catalogo_flags: dict | None = None) -> dict | None:
    """El editor de flags. Devuelve {"flags", "extra_flags"}, o None si se cancela.

    Se edita como texto TOML y no con una fila por flag a propósito: los flags de
    rclone son cientos, cambian con cada versión y ninguna lista que pusiéramos
    aquí estaría al día. Lo que sí se puede dar es lo que no se ve escribiéndolos
    en el TOML —qué queda valiendo al fundir base, modo, [defaults] y pareja—, y
    eso es la tabla de abajo.

    El diálogo NO se cierra si lo escrito no vale: se avisa y se deja el texto
    donde está. Cerrar y perderlo, o peor, guardar solo lo que se entendió, es
    exactamente lo que no puede pasar con un fichero que gobierna borrados."""
    import tkinter as tk
    from tkinter import messagebox, ttk

    dlg = modal(parent, titulo)
    marco = ttk.Frame(dlg, padding=12)
    marco.grid(sticky="nsew")
    resultado: dict = {"datos": None}

    ttk.Label(marco, text=subtitulo, foreground="#775500", wraplength=620,
              justify="left").grid(row=0, column=0, columnspan=2, sticky="w",
                                   pady=(0, 8))

    ttk.Label(marco, justify="left", text="Flags (uno por línea, 'clave = valor'):").grid(
        row=1, column=0, sticky="w")
    caja = tk.Text(marco, width=52, height=8, font=("Consolas", 9))
    caja.insert("1.0", flags_editor.dump(flags))
    caja.grid(row=2, column=0, sticky="w")
    ttk.Label(marco, foreground="#666666", wraplength=300, justify="left",
              text=("Tal cual se escriben en el TOML: transfers = 4, "
                    'conflict-resolve = "newer", checksum = true. Sin los guiones '
                    "de delante.")).grid(row=2, column=1, sticky="nw", padx=(10, 0))

    ttk.Label(marco, text="Argumentos extra (uno por línea):").grid(
        row=3, column=0, sticky="w", pady=(10, 0))
    caja_extra = tk.Text(marco, width=52, height=3, font=("Consolas", 9))
    caja_extra.insert("1.0", flags_editor.dump_extra(extra))
    caja_extra.grid(row=4, column=0, sticky="w")
    ttk.Label(marco, foreground="#666666", wraplength=300, justify="left",
              text=("La salida de emergencia: van a la línea de comandos sin tocar, "
                    "así que --bwlimit y 8M son DOS líneas.")).grid(
        row=4, column=1, sticky="nw", padx=(10, 0))

    if catalogo_flags is not None:
        ttk.Label(marco, foreground="#666666", wraplength=520, justify="left",
                  text="Catálogo: " + (flags_editor.dump(catalogo_flags).replace(
                      "\n", "  ·  ") or "ninguno")).grid(
            row=5, column=0, columnspan=2, sticky="w", pady=(8, 0))

    ttk.Label(marco, text="Lo que acabaría recibiendo rclone:").grid(
        row=6, column=0, sticky="w", pady=(12, 2))
    tabla = ttk.Treeview(marco, columns=("flag", "origen"), show="headings",
                         height=8, selectmode="none")
    tabla.heading("flag", text="Flag")
    tabla.heading("origen", text="Sale de")
    tabla.column("flag", width=330)
    tabla.column("origen", width=120)
    tabla.grid(row=7, column=0, columnspan=2, sticky="nsew")

    def leer() -> dict | None:
        """Lo escrito, ya validado. None si no vale (y ya se ha avisado)."""
        try:
            return {"flags": flags_editor.parse(caja.get("1.0", "end")),
                    "extra_flags": flags_editor.parse_extra(caja_extra.get("1.0", "end"))}
        except ConfigError as e:
            messagebox.showerror(TITLE, str(e), parent=dlg)
            return None

    def repasar():
        datos = leer()
        if datos is None:
            return
        tabla.delete(*tabla.get_children())
        for i, fila in enumerate(flags_editor.effective(mode_name, defaults_flags,
                                                        datos["flags"])):
            tabla.insert("", "end", iid=str(i), values=(fila.flag, fila.origen))
        for arg in datos["extra_flags"]:
            tabla.insert("", "end", values=(arg, "extra"))

    def aceptar():
        datos = leer()
        if datos is None:
            return                       # el diálogo se queda abierto, con el texto
        resultado["datos"] = datos
        dlg.destroy()

    pie = ttk.Frame(marco)
    pie.grid(row=8, column=0, columnspan=2, pady=(14, 0), sticky="w")
    ttk.Button(pie, text="Ver el efecto", command=repasar).grid(row=0, column=0, padx=3)
    ttk.Button(pie, text="Aceptar", command=aceptar).grid(row=0, column=1, padx=3)
    ttk.Button(pie, text="Cancelar", command=dlg.destroy).grid(row=0, column=2, padx=3)

    repasar()
    mostrar(dlg, parent)
    return resultado["datos"]
