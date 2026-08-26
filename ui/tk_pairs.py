#!/usr/bin/env python3
"""
tk_pairs.py — La pantalla de gestión de parejas.

Solo dibuja. Todo lo que decide y todo lo que toca el disco está en
`ui/pair_editor.py`, y el guion es siempre el mismo: se pide un plan, se enseñan
sus consecuencias, y solo si el usuario confirma se ejecuta. Ninguna acción de
esta pantalla escribe nada sin haber enseñado antes lo que va a pasar.
"""

from __future__ import annotations

from common import config_file, model
from common.model import ConfigError

from . import pair_editor
from .tk import TITLE, modal

COLUMNAS = [
    ("pareja", "Pareja", 110),
    ("modo", "Modo", 90),
    ("local", "Local", 190),
    ("remoto", "Remoto", 210),
    ("estado", "Estado", 130),
    ("aviso", "", 190),
]


def open_dialog(parent, config) -> bool:
    """Abre la pantalla. Devuelve True si se ha cambiado el config."""
    import tkinter as tk
    from tkinter import messagebox, ttk

    dlg = modal(parent, "Parejas")
    estado = {"raw": config_file.load_raw(), "config": config, "cambiado": False}

    marco = ttk.Frame(dlg, padding=12)
    marco.grid(sticky="nsew")

    tree = ttk.Treeview(marco, columns=[c[0] for c in COLUMNAS],
                        show="headings", height=9, selectmode="browse")
    for clave, titulo, ancho in COLUMNAS:
        tree.heading(clave, text=titulo)
        tree.column(clave, width=ancho, anchor="w")
    tree.grid(row=0, column=0, columnspan=4, sticky="nsew")
    scroll = ttk.Scrollbar(marco, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scroll.set)
    scroll.grid(row=0, column=4, sticky="ns")

    pie = ttk.Label(marco, text="", foreground="#666666", wraplength=800, justify="left")
    pie.grid(row=1, column=0, columnspan=5, sticky="w", pady=(8, 0))

    def refrescar(nota: str = "") -> None:
        estado["raw"] = config_file.load_raw()
        estado["config"] = model.parse_config(estado["raw"])
        tree.delete(*tree.get_children())
        for fila in pair_editor.rows(estado["config"]):
            tree.insert("", "end", iid=fila.name,
                        values=(fila.name, fila.mode, fila.local, fila.remote,
                                fila.estado, fila.aviso or ""))
        pie.configure(text=nota)

    def seleccionada() -> str | None:
        elegido = tree.selection()
        if not elegido:
            messagebox.showinfo(TITLE, "Elige antes una pareja de la lista.", parent=dlg)
            return None
        return elegido[0]

    def confirmar(plan) -> bool:
        texto = "\n".join(f"• {c}" for c in plan.consequences)
        if plan.warnings:
            texto += "\n\n" + "\n".join(f"⚠ {w}" for w in plan.warnings)
        return bool(messagebox.askokcancel(TITLE, texto + "\n\n¿Seguir adelante?",
                                           parent=dlg))

    def aplicar(plan) -> None:
        if not confirmar(plan):
            return
        try:
            hechos = plan.execute()
        except (ConfigError, OSError) as e:
            messagebox.showerror(TITLE, f"No se ha podido guardar:\n\n{e}", parent=dlg)
            return
        estado["cambiado"] = True
        refrescar("  ·  ".join(hechos))

    def anadir() -> None:
        datos = formulario(dlg, estado["raw"], None, {})
        if datos is None:
            return
        try:
            plan = pair_editor.plan_save(estado["raw"], datos, None)
        except ConfigError as e:
            messagebox.showerror(TITLE, str(e), parent=dlg)
            return
        aplicar(plan)

    def editar() -> None:
        name = seleccionada()
        if not name:
            return
        actual = next(p for p in estado["raw"]["pair"] if p.get("name") == name)
        datos = formulario(dlg, estado["raw"], name, actual)
        if datos is None:
            return
        try:
            plan = pair_editor.plan_save(estado["raw"], datos, name)
        except ConfigError as e:
            messagebox.showerror(TITLE, str(e), parent=dlg)
            return
        aplicar(plan)

    def quitar() -> None:
        name = seleccionada()
        if not name:
            return
        limpiar = preguntar_limpieza(dlg, name)
        if limpiar is None:
            return
        try:
            plan = pair_editor.plan_remove(estado["raw"], name, clean_state=limpiar)
        except ConfigError as e:
            messagebox.showerror(TITLE, str(e), parent=dlg)
            return
        aplicar(plan)

    botones = ttk.Frame(marco)
    botones.grid(row=2, column=0, columnspan=5, pady=(12, 0), sticky="w")
    ttk.Button(botones, text="Añadir…", command=anadir).grid(row=0, column=0, padx=3)
    ttk.Button(botones, text="Editar…", command=editar).grid(row=0, column=1, padx=3)
    ttk.Button(botones, text="Quitar…", command=quitar).grid(row=0, column=2, padx=3)
    ttk.Button(botones, text="Cerrar", command=dlg.destroy).grid(row=0, column=3, padx=3)

    refrescar()
    dlg.wait_window()
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
              text=(f"Se quitará '{name}' del config.\n\n"
                    "Los datos sincronizados NO se tocan, ni en el pen ni en el NAS: "
                    "solo deja de sincronizarse.")).grid(row=0, column=0, sticky="w")

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

    dlg.wait_window()
    return respuesta["valor"]


def formulario(parent, raw: dict, original_name: str | None, actual: dict) -> dict | None:
    """El formulario de una pareja. Devuelve los campos, o None si se cancela."""
    import tkinter as tk
    from tkinter import ttk

    titulo = f"Editar '{original_name}'" if original_name else "Nueva pareja"
    dlg = modal(parent, titulo)
    marco = ttk.Frame(dlg, padding=12)
    marco.grid(sticky="nsew")
    resultado: dict = {"datos": None}
    por_defecto = raw.get("defaults", {}).get("remote", model.DEFAULT_REMOTE)

    campos: dict[str, tk.StringVar] = {}
    fila = 0
    for clave, etiqueta, pista in (
            ("name", "Nombre", "identifica la pareja y nombra su carpeta en state/"),
            ("local", "Ruta local", "relativa a la raíz del pen, p. ej. sync-data/notas"),
            ("remote_path", "Ruta remota", "en el NAS, p. ej. /PJ/Notas"),
            ("remote", "Remoto", f"vacío = el de [defaults] ({por_defecto})")):
        ttk.Label(marco, text=etiqueta + ":").grid(row=fila, column=0, sticky="w", pady=2)
        var = tk.StringVar(value=str(actual.get(clave, "")))
        campos[clave] = var
        ttk.Entry(marco, textvariable=var, width=44).grid(row=fila, column=1, sticky="w")
        ttk.Label(marco, text=pista, foreground="#666666").grid(
            row=fila, column=2, sticky="w", padx=(8, 0))
        fila += 1

    ttk.Label(marco, text="Modo:").grid(row=fila, column=0, sticky="w", pady=2)
    modo = tk.StringVar(value=actual.get("mode", model.DEFAULT_MODE))
    combo = ttk.Combobox(marco, textvariable=modo, state="readonly", width=42,
                         values=sorted(model.MODES))
    combo.grid(row=fila, column=1, sticky="w")
    aviso_modo = ttk.Label(marco, foreground="#775500", wraplength=260, justify="left")
    aviso_modo.grid(row=fila, column=2, sticky="w", padx=(8, 0))

    def modo_cambiado(*_):
        aviso = pair_editor.mirror_warning(modo.get())
        aviso_modo.configure(text=aviso or "")
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
        fila += 1

    ttk.Label(marco, foreground="#666666", wraplength=760, justify="left",
              text=("Los flags de rclone no se editan aquí: van en sync_config.toml, "
                    "que es donde el proyecto quiere que vivan.")).grid(
        row=fila, column=0, columnspan=3, sticky="w", pady=(10, 0))
    fila += 1

    def aceptar():
        resultado["datos"] = {
            **{k: v.get() for k, v in campos.items()},
            "mode": modo.get(),
            **{k: caja.get("1.0", "end").splitlines() for k, caja in textos.items()},
        }
        dlg.destroy()

    pie = ttk.Frame(marco)
    pie.grid(row=fila, column=0, columnspan=3, pady=(14, 0))
    ttk.Button(pie, text="Guardar…", command=aceptar).grid(row=0, column=0, padx=3)
    ttk.Button(pie, text="Cancelar", command=dlg.destroy).grid(row=0, column=1, padx=3)

    dlg.wait_window()
    return resultado["datos"]
