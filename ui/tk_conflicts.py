#!/usr/bin/env python3
"""
tk_conflicts.py — La ventana de los ficheros en conflicto.

Solo dibuja. Qué versión es de quién lo sabe `common/conflicts.py`, y qué pasa
en disco al elegir una lo decide `ui/conflict_editor.py`. El guion es el de la
pantalla de parejas: se pide un plan, se enseñan sus consecuencias en
`tk_pairs.confirmar_plan()` —la misma ventana que gobierna los demás borrados de
la aplicación— y solo si el usuario dice que sí se ejecuta.

La lista es un árbol: cada fichero en conflicto con sus versiones debajo, cada
una con su tamaño y su fecha, que es lo que hace falta para elegir. El sufijo
con el que rclone renombró la copia no aparece por ningún lado: la etiqueta dice
«versión de este dispositivo» o «versión del remoto», y el que quiera ver los
ficheros tiene «Abrir la carpeta».
"""

from __future__ import annotations

from common import conflicts
from common.model import Config

from . import abrir, conflict_editor, icons, theme
from .tk import TITLE, cabecera, cuerpo_visible, modal, mostrar

COLUMNAS = [
    ("pareja", "Pareja", 110),
    ("tamano", "Tamaño", 90),
    ("fecha", "Modificada", 140),
]

NOTA = "Solo cambian ficheros de este dispositivo"


def open_dialog(parent, config: Config) -> bool:
    """Abre la ventana. Devuelve True si se ha resuelto algo."""
    from tkinter import messagebox, ttk

    from . import tk_pairs

    dlg = modal(parent, "Conflictos")
    parejas = {p.name: p for p in config.pairs if p.is_bisync}
    estado: dict = {"conflictos": [], "filas": {}, "cambiado": False}

    marco = cuerpo_visible(dlg, padding=(20, 18, 20, 16))
    marco.columnconfigure(0, weight=1)

    cabecera(marco, "Ficheros en conflicto",
             "Cambiaron en los dos lados entre dos pasadas. rclone se quedó con la "
             "más reciente y guardó la otra al lado, así que ahora hay dos versiones "
             "y se van separando. Elige con cuál te quedas: la otra se borra, y la "
             "próxima sincronización lo lleva al remoto.",
             ancho=640, estilo="Dialogo.TLabel").grid(row=0, column=0, sticky="w")

    tarjeta = ttk.Frame(marco, style="Card.TFrame", padding=(8, 8, 2, 4))
    tarjeta.grid(row=1, column=0, sticky="nsew", pady=(14, 0))
    tarjeta.columnconfigure(0, weight=1)
    tarjeta.rowconfigure(0, weight=1)
    marco.rowconfigure(1, weight=1)

    tree = ttk.Treeview(tarjeta, columns=[c[0] for c in COLUMNAS],
                        show="tree headings", height=8, selectmode="browse")
    tree.heading("#0", text="Fichero / versión", anchor="w")
    tree.column("#0", width=icons.px(tree, 320), anchor="w")
    for clave, titulo, ancho in COLUMNAS:
        tree.heading(clave, text=titulo, anchor="w")
        tree.column(clave, width=icons.px(tree, ancho), anchor="w")
    tree.grid(row=0, column=0, sticky="nsew")
    theme.marcar_lista(tree)
    scroll = ttk.Scrollbar(tarjeta, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scroll.set)
    scroll.grid(row=0, column=1, sticky="ns")

    vacio = ttk.Label(marco, text="No queda ningún fichero en conflicto.",
                      style="Pista.TLabel")

    # --- qué hay elegido --------------------------------------------------------

    def elegido():
        """(conflicto, versión) de la fila elegida; la versión es None si la
        fila es la del fichero y no una de sus versiones."""
        seleccion = tree.selection()
        if not seleccion:
            return None, None
        return estado["filas"].get(seleccion[0], (None, None))

    def repasar_botones(_evento=None) -> None:
        conflicto, version = elegido()
        for boton, lado in ((conservar_aqui, conflicts.DISPOSITIVO),
                            (conservar_remoto, conflicts.REMOTO)):
            boton.configure(state="normal" if conflicto is not None
                            and conflict_editor.puede(conflicto, lado) else "disabled")
        conservar_esta.configure(state="normal" if version is not None else "disabled")
        for boton in (abrir_carpeta, abrir_versiones):
            boton.configure(state="normal" if conflicto is not None else "disabled")

    def refrescar(nota: str = "", escanear: bool = False) -> None:
        """Repinta la lista. Con `escanear`, recorre de nuevo las parejas que
        tenían conflictos: después de resolver uno hay que ver cómo ha quedado
        el disco, no lo que decía el escaneo anterior."""
        if escanear:
            nombres = {x.pareja for x in estado["conflictos"]}
            for nombre in nombres:
                try:
                    conflicts.actualizar_pareja(parejas[nombre])
                except OSError:
                    pass
        cargados = conflicts.cargar(config)
        estado["conflictos"] = [x for nombre in parejas for x in cargados.get(nombre, [])]

        tree.delete(*tree.get_children())
        estado["filas"] = {}
        for i, conflicto in enumerate(estado["conflictos"]):
            padre = f"c{i}"
            tree.insert("", "end", iid=padre, text=conflicto.relativa, open=True,
                        values=(conflicto.pareja, "", ""), tags=("aviso",))
            estado["filas"][padre] = (conflicto, None)
            for j, (version, nombre) in enumerate(conflict_editor.etiquetas(conflicto)):
                hijo = f"{padre}v{j}"
                dato = conflict_editor.huella(version.ruta)
                tree.insert(padre, "end", iid=hijo, text=nombre, tags=("ok",), values=(
                    "", conflict_editor.tamano(dato[0]) if dato else "—",
                    conflict_editor.fecha(dato[1]) if dato else "ya no está"))
                estado["filas"][hijo] = (conflicto, version)
        filas = len(estado["filas"])
        tree.configure(height=min(14, max(5, filas)))
        if estado["conflictos"]:
            vacio.grid_remove()
            tree.selection_set("c0")
        else:
            vacio.grid(row=2, column=0, sticky="w", pady=(10, 0))
        pie_nota.configure(text=nota)
        repasar_botones()

    # --- las acciones ------------------------------------------------------------

    def resolver(pensar, titulo: str) -> None:
        try:
            plan = pensar()
        except conflict_editor.ResolucionImposible as e:
            messagebox.showerror(TITLE, str(e), parent=dlg)
            return
        if not tk_pairs.confirmar_plan(dlg, plan, titulo, NOTA):
            return
        try:
            hechos = plan.execute()
        except conflict_editor.ResolucionImposible as e:
            messagebox.showerror(TITLE, str(e), parent=dlg)
            refrescar(escanear=True)
            return
        estado["cambiado"] = True
        refrescar("  ·  ".join(hechos), escanear=True)

    def por_lado(lado: str) -> None:
        conflicto, _ = elegido()
        if conflicto is None:
            return
        resolver(lambda: conflict_editor.plan_lado(conflicto, lado),
                 f"Quedarse con la {conflict_editor.ETIQUETA_LADO[lado]}")

    def la_elegida() -> None:
        conflicto, version = elegido()
        if version is None:
            return
        resolver(lambda: conflict_editor.plan_conservar(conflicto, version),
                 f"Quedarse con la {conflict_editor.etiqueta(conflicto, version)}")

    def abrir_todo(que) -> None:
        conflicto, _ = elegido()
        if conflicto is None:
            return
        for ruta in que(conflicto):
            try:
                abrir(ruta)
            except OSError as e:
                messagebox.showerror(TITLE, f"No se ha podido abrir:\n\n{ruta}\n\n{e}",
                                     parent=dlg)
                return

    tree.bind("<<TreeviewSelect>>", repasar_botones)

    acciones = ttk.Frame(marco)
    acciones.grid(row=3, column=0, sticky="ew", pady=(14, 0))
    acciones.columnconfigure(3, weight=1)
    conservar_aqui = ttk.Button(acciones, text="Quedarme con la de este dispositivo",
                                command=lambda: por_lado(conflicts.DISPOSITIVO))
    theme.boton_icono(conservar_aqui, "dispositivo", theme.TINTA2, theme.SUPERFICIE)
    conservar_aqui.grid(row=0, column=0, padx=(0, 6))
    conservar_remoto = ttk.Button(acciones, text="Quedarme con la del remoto",
                                  command=lambda: por_lado(conflicts.REMOTO))
    theme.boton_icono(conservar_remoto, "nas", theme.TINTA2, theme.SUPERFICIE)
    conservar_remoto.grid(row=0, column=1, padx=(0, 6))
    conservar_esta = ttk.Button(acciones, text="Quedarme con la elegida",
                                command=la_elegida)
    conservar_esta.grid(row=0, column=2, padx=(0, 6))

    abrir_carpeta = ttk.Button(acciones, text="Abrir la carpeta", style="Quiet.TButton",
                               command=lambda: abrir_todo(lambda x: [x.original.parent]))
    theme.boton_icono(abrir_carpeta, "file", theme.ACENTO, theme.PAPEL)
    abrir_carpeta.grid(row=0, column=4, sticky="e")
    abrir_versiones = ttk.Button(
        acciones, text="Abrir las versiones", style="Quiet.TButton",
        command=lambda: abrir_todo(lambda x: [v.ruta for v in x.versiones]))
    abrir_versiones.grid(row=0, column=5, sticky="e", padx=(4, 0))

    cierre = ttk.Frame(marco)
    cierre.grid(row=4, column=0, sticky="ew", pady=(12, 0))
    cierre.columnconfigure(0, weight=1)
    pie_nota = ttk.Label(cierre, text="", style="MonoPista.TLabel",
                         wraplength=theme.medida(640), justify="left")
    pie_nota.grid(row=0, column=0, sticky="w")
    ttk.Button(cierre, text="Cerrar", command=dlg.destroy).grid(row=0, column=1)

    refrescar()
    mostrar(dlg, parent)
    return estado["cambiado"]
