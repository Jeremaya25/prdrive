#!/usr/bin/env python3
"""El llavero con diálogos de Tk: «Abrir llavero» y «Ajustes → Llavero».

Solo dibuja: los pasos, los planes y lo que dicen son de `ui/llavero_editor`, y
lo que se hace, de `common/keepassxc.py` y `common/llavero.py`.

- «Abrir llavero» (`abrir()`): un aviso, la espera (`tk.working()`), la
  pregunta por el fichero llave, que solo pide la ruta (el fichero ni se
  abre), y la confirmación de «Combinar» (`tk_pairs.confirmar_plan()`). Suelto
  es `runsync.py --llavero` (`Llavero.bat`), colgado de una raíz que no se
  enseña.
- «Ajustes → Llavero» (`ajustes()`): se abre en el acto y lee el catálogo en
  segundo plano (el mismo encargo que «Parejas»): lo que se puede hacer depende
  de si el remoto ya tiene llavero. Cada cambio pasa por `confirmar_plan()` y,
  si escribe en el remoto, por `working()`.
"""

from __future__ import annotations

from functools import partial
from pathlib import Path

from common import catalog, keepassxc, llavero, model
from common.model import Config, ConfigError

from . import catalog_editor, llavero_editor, segundo_plano, theme, tk_pairs
from .tk import (TITLE, Indicador, Panel, Sondeo, cabecera, dialogo, mostrar, pie,
                 working)

ACTIVADO = "activado"
"""Lo que devuelve `ajustes()` si ha activado el llavero: toca la primera pasada."""
CAMBIADO = "cambiado"
"""Lo que devuelve `ajustes()` si ha cambiado el config: hay que releerlo."""
NOTA = "Solo se escribe lo que dice la lista"
"""La nota de las confirmaciones de esta pantalla."""


def avisar(parent, texto: str) -> None:
    """Enseña un aviso con «Aceptar». Es de módulo para que los tests lo sustituyan."""
    from tkinter import messagebox
    messagebox.showwarning(llavero_editor.TITULO, texto, parent=parent)


def elegir_llave(parent, nombre: str) -> Path | None:
    """Pregunta dónde está el fichero llave en este equipo; `None` si no se elige ninguno.

    Es de módulo para que los tests lo sustituyan.
    """
    from tkinter import filedialog
    elegido = filedialog.askopenfilename(parent=parent,
                                         title=llavero_editor.pregunta_llave(nombre))
    return Path(elegido) if elegido else None


def guardar_copia_llave(parent) -> Path | None:
    """Pregunta dónde guardar la copia de la llave, fuera del dispositivo; `None` si se cancela.

    Es de módulo para que los tests lo sustituyan.
    """
    from tkinter import filedialog
    elegido = filedialog.asksaveasfilename(
        parent=parent, title="Guarda una copia del fichero llave, fuera de este dispositivo",
        initialfile=model.LLAVERO_LLAVE, defaultextension=".keyx")
    return Path(elegido) if elegido else None


def abrir(parent, config: Config, suelto: bool = False) -> bool:
    """Hace «Abrir llavero» con diálogos que cuelgan de `parent`.

    Args:
        parent: La ventana de prdrive, o la raíz oculta de `abrir_suelto()`.
        config: El del dispositivo.
        suelto: Sin la ventana de prdrive: una pasada que falla se dice con un
            aviso, porque no hay línea del llavero que lo diga.

    Returns:
        True si KeePassXC se ha abierto.
    """
    def esperar(mensaje: str, funcion):
        """Corre `funcion()` con la ventanita de espera."""
        return working(parent, llavero_editor.TITULO, funcion, mensaje, suelto=suelto)

    def confirmar(plan, titulo: str, nota: str) -> bool:
        """Enseña el plan de «Combinar» y dice si se sigue."""
        return tk_pairs.confirmar_plan(parent, plan, titulo, nota, suelto=suelto)

    return llavero_editor.abrir(config, partial(avisar, parent), esperar,
                                partial(elegir_llave, parent), confirmar,
                                decir_sin_traer=suelto)


CERRAR = ("KeePassXC está abierto. ¿Cerrarlo?\n\nSe cierra como si lo cerraras tú: si "
          "tiene algo sin guardar, te lo pregunta.")
"""Lo que se pregunta al expulsar con el KeePassXC de la unidad abierto."""


def cerrar(parent, config: Config) -> bool:
    """Cierra el llavero antes de expulsar o bloquear (§10): KeePassXC, lo pendiente, el navegador.

    Pregunta antes de cerrar KeePassXC; lo demás espera en `working()` y solo
    se dice si algo no ha ido bien.

    Returns:
        True si se puede seguir expulsando; False si KeePassXC sigue abierto
        (no se ha querido cerrar, o no ha salido).
    """
    if config.pareja_llavero is None:
        return True
    programas, _ = keepassxc.procesos_de_la_unidad()
    if programas and not preguntar(parent, CERRAR):
        return False
    ok, cierre = working(parent, llavero_editor.TITULO,
                         partial(keepassxc.cerrar_llavero, config),
                         "Cerrando el llavero: KeePassXC, lo que quede por subir y el "
                         "navegador…")
    if not ok:
        avisar(parent, f"No se ha podido cerrar el llavero del todo ({cierre}). Se sigue "
                       "igualmente: VeraCrypt dirá si algo de dentro sigue abierto.")
        return True
    if cierre.lineas:
        avisar(parent, "\n\n".join(cierre.lineas))
    return cierre.listo


def preguntar(parent, texto: str) -> bool:
    """Pregunta sí o no. Es de módulo para que los tests lo sustituyan."""
    from tkinter import messagebox
    return bool(messagebox.askyesno(llavero_editor.TITULO, texto, parent=parent))


def elegir_base(parent) -> Path | None:
    """Pregunta qué base usar; `None` si no se elige. De módulo para los tests."""
    from tkinter import filedialog
    elegido = filedialog.askopenfilename(
        parent=parent, title="¿Qué base de KeePassXC lleva el llavero?",
        filetypes=[("Bases de KeePassXC", "*.kdbx"), ("Todos los ficheros", "*.*")])
    return Path(elegido) if elegido else None


PREGUNTA_LLAVE = ("¿Esta base usa un fichero llave?\n\n"
                  "Si para abrirla solo escribes la contraseña, es que no.")
"""Lo que se pregunta al activar con una base propia."""
PREGUNTA_LLAVE_ACTUAL = ("¿Esta base ya usa un fichero llave (además de la contraseña)?\n\n"
                         "Hace falta para poder abrirla y dejarla sin contraseña.")
"""Lo que se pregunta al dejar una base sin contraseña: su protección actual se sustituye."""
CAMBIAR_LLAVE = ("Se sustituye el fichero llave que hay en el dispositivo por el que has "
                 "elegido. Si no es el de esta base, KeePassXC no podrá abrirla. ¿Seguir?")
"""Lo que se pregunta al dar otra vez el fichero llave de un llavero sin contraseña."""


def ajustes(parent, raw: dict | None = None) -> str | None:
    """Abre «Ajustes → Llavero».

    Args:
        parent: La ventana de la que cuelga (la principal).
        raw: El `sync_config.toml` en crudo; sin él se lee del disco.

    Returns:
        `ACTIVADO`, `CAMBIADO` o `None` si no ha cambiado nada.
    """
    return dialogo(parent, llavero_editor.TITULO, lambda p: construir_ajustes(p, raw),
                   ensenar=mostrar)


def construir_ajustes(panel: Panel, raw: dict | None = None) -> None:
    """Dibuja «Llavero» en `panel` (su diálogo o «Ajustes»).

    Devuelve por el panel `ACTIVADO` o `CAMBIADO`. Activar y desactivar
    cierran la ventana entera, sea el diálogo o «Ajustes»: la principal relee
    el config, se repinta entera y, tras activar, lanza la primera pasada.
    """
    from tkinter import messagebox, ttk

    raw = catalog_editor.raw_del_dispositivo(raw) or {}
    dlg, marco = panel.ventana, panel.marco
    sondeo = Sondeo(marco)
    estado: dict = {"cat": None, "leido": False}
    cabecera(marco, llavero_editor.TITULO, llavero_editor.EXPLICACION, ancho=560,
             estilo="Dialogo.TLabel").grid(row=0, column=0, sticky="w")
    indicador = Indicador(marco, ancho=560)
    indicador.marco.grid(row=1, column=0, sticky="ew", pady=(12, 0))
    dlg.indicador, dlg.sondeo = indicador, sondeo   # como `visor`: los tests los miran

    tarjeta = ttk.Frame(marco, style="Card.TFrame", padding=(14, 10, 14, 12))
    tarjeta.grid(row=2, column=0, sticky="ew", pady=(14, 0))
    tarjeta.columnconfigure(0, weight=1)
    acciones = ttk.Frame(marco)
    acciones.grid(row=3, column=0, sticky="w", pady=(14, 0))
    botones = pie(marco, 4)
    botones.columnconfigure(0, weight=1)
    pie_nota = ttk.Label(botones, text="", style="MonoPista.TLabel",
                         wraplength=theme.medida(440), justify="left")
    pie_nota.grid(row=0, column=0, sticky="w")
    ttk.Button(botones, text="Cerrar", command=panel.cerrar).grid(
        row=0, column=1, sticky="e", padx=(10, 0))

    def remota() -> dict | None:
        """Devuelve el `[keychain]` del catálogo leído."""
        return llavero_editor.tabla_remota(estado["cat"])

    def pintar(nota: str = "") -> None:
        """Repinta la tarjeta y los botones con lo que hay."""
        sit = llavero_editor.situacion(raw)
        leido = estado["leido"]
        for hijo in tarjeta.winfo_children():
            hijo.destroy()
        for i, linea in enumerate(llavero_editor.lineas(sit, remota(), leido)):
            ttk.Label(tarjeta, text=linea, style="Card.TLabel" if i == 0 else "Card.Pista.TLabel",
                      wraplength=theme.medida(540), justify="left").grid(
                row=i, column=0, sticky="w", pady=(0 if i == 0 else 4, 0))
        pie_nota.configure(text=nota)
        for hijo in acciones.winfo_children():
            hijo.destroy()
        con_remoto = "normal" if leido else "disabled"
        botones: list = []
        if sit.activo:
            if sit.interna:
                botones.append(("Dar el fichero llave…", dar_llave, "normal"))
            else:
                if sit.pide_llave:
                    botones.append(("Dónde está el fichero llave…", donde_esta, "normal"))
                botones.append(("La base ya no pide fichero llave…" if sit.pide_llave
                                else "La base pide fichero llave…", cambiar_pide, con_remoto))
            botones.append(("Desactivar…", desactivar, "normal"))
        else:
            tabla = remota()
            if not (tabla or {}).get("llave_interna"):
                botones.append(("Usar esta base…", usar, con_remoto))
            if tabla is None:
                botones.append(("Usar esta base, sin contraseña…", usar_interna, con_remoto))
            else:
                botones.append(("Traer el del remoto", traer, con_remoto))
        # Sin activar, lo natural va en azul: traer el del remoto si lo hay, si
        # no, dar una base.
        principal = (("Traer el del remoto" if remota() is not None else "Usar esta base…")
                     if not sit.activo else None)
        for col, (texto, orden, apagado) in enumerate(botones):
            peligro = orden is desactivar
            boton = ttk.Button(acciones, text=texto, command=orden, state=apagado,
                               style="Primary.TButton" if texto == principal
                               else "Danger.TButton" if peligro else "TButton")
            if peligro:
                theme.boton_icono(boton, "trash", theme.PELIGRO, theme.SUPERFICIE)
            boton.grid(row=0, column=col, padx=(0, 6))
        panel.ajustar()

    def leer(nota: str = "") -> None:
        """Lee el catálogo en segundo plano y repinta al llegar."""
        estado["leido"] = False
        indicador.poner(llavero_editor.LEYENDO, True)

        def llegada(encargo) -> None:
            """Apunta el catálogo leído y repinta; si no se pudo, lo dice."""
            if encargo.error is not None:
                estado["cat"], aviso = None, str(encargo.error)
            else:
                estado["cat"], aviso = encargo.resultado
            estado["leido"] = estado["cat"] is not None and estado["cat"].editable
            indicador.poner("" if estado["leido"] else
                            f"No se ha podido leer el catálogo del remoto: {aviso}. Sin "
                            "él no se puede activar ni cambiar el llavero.",
                            False, "Pista." if estado["leido"] else "Aviso.")
            pintar(nota)

        sondeo.esperar(segundo_plano.lanzar_sin_repetir(
            "catalogo", raw, partial(catalog.load, dict(raw))), llegada)

    def hacer(pensar, titulo: str, mensaje: str, cerrar: bool) -> None:
        """Pide el plan, lo confirma y lo hace.

        Args:
            pensar: Devuelve el plan.
            titulo: El de la confirmación.
            mensaje: El de la espera.
            cerrar: Si al hacerlo se cierra la pantalla (activar y desactivar:
                la ventana principal relee el config y se repinta entera).
        """
        try:
            plan = pensar()
        except ConfigError as e:
            messagebox.showerror(TITLE, str(e), parent=dlg)
            return
        if not tk_pairs.confirmar_plan(dlg, plan, titulo, NOTA):
            return
        ok, valor = working(dlg, llavero_editor.TITULO, plan.execute, mensaje)
        raw.clear()
        raw.update(catalog_editor.raw_del_dispositivo(None) or {})
        if not ok:
            messagebox.showerror(TITLE, str(valor), parent=dlg)
            leer()
            return
        panel.devolver(ACTIVADO if plan.activa else CAMBIADO)
        if cerrar:
            panel.cerrar()
            return
        leer("  ·  ".join(valor))

    def usar() -> None:
        """«Usar esta base…»: la que se elija, copiada al llavero."""
        origen = elegir_base(dlg)
        if origen is None:
            return
        tabla = remota()
        if tabla is None:
            pide = preguntar(dlg, PREGUNTA_LLAVE)
            nombre = ""
        else:
            pide, nombre = bool(tabla.get("fichero_llave")), str(tabla.get("nombre_llave") or "")
        llave = elegir_llave(dlg, nombre) if pide else None
        nombre = nombre or (llave.name if llave is not None else "")
        hacer(lambda: llavero_editor.plan_activar(raw, estado["cat"], origen, pide, nombre,
                                                  llave),
              "Activar el llavero", "Activando el llavero…", cerrar=True)

    def usar_interna() -> None:
        """«Usar esta base, sin contraseña…»: queda solo con un fichero llave que genera prdrive."""
        origen = elegir_base(dlg)
        if origen is None:
            return
        actual = None
        if preguntar(dlg, PREGUNTA_LLAVE_ACTUAL):
            actual = elegir_llave(dlg, "")
            if actual is None:
                return
        copia = guardar_copia_llave(dlg)
        if copia is None:
            return
        hacer(lambda: llavero_editor.plan_llave_interna(raw, estado["cat"], origen, copia,
                                                        actual),
              "Llavero sin contraseña", "Dejando el llavero sin contraseña…", cerrar=True)

    def dar_llave() -> None:
        """«Dar el fichero llave…»: sustituye el del dispositivo (llavero sin contraseña)."""
        llave = elegir_llave(dlg, "")
        if llave is None or not preguntar(dlg, CAMBIAR_LLAVE):
            return
        try:
            llavero.poner_llave(llave)
        except OSError as e:
            messagebox.showerror(TITLE, f"No se ha podido copiar el fichero llave: {e}",
                                 parent=dlg)
            return
        pintar("Fichero llave puesto en el dispositivo.")

    def traer() -> None:
        """«Traer el del remoto»: la base del catálogo baja con la primera pasada."""
        tabla = remota() or {}
        llave = None
        if tabla.get("fichero_llave"):
            llave = elegir_llave(dlg, str(tabla.get("nombre_llave") or ""))
        hacer(lambda: llavero_editor.plan_activar(raw, estado["cat"], None, llave=llave),
              "Activar el llavero", "Activando el llavero…", cerrar=True)

    def cambiar_pide() -> None:
        """Apunta que la base pide (o ya no) fichero llave, aquí y en el catálogo."""
        sit = llavero_editor.situacion(raw)
        pide = not sit.pide_llave
        llave = elegir_llave(dlg, "") if pide else None
        nombre = llave.name if llave is not None else ""
        hacer(lambda: llavero_editor.plan_pide_llave(raw, estado["cat"], pide, nombre, llave),
              "Fichero llave", "Escribiendo en el catálogo…", cerrar=False)

    def donde_esta() -> None:
        """Apunta dónde está el fichero llave en este equipo; no es un dato de nadie más."""
        sit = llavero_editor.situacion(raw)
        llave = elegir_llave(dlg, sit.nombre_llave)
        if llave is None:
            return
        keepassxc.apuntar_llave(llave)
        pintar(f"Fichero llave en este equipo: {llave}")

    def desactivar() -> None:
        """«Desactivar…»: quita `[keychain]` de aquí; ni la carpeta ni el remoto."""
        hacer(lambda: llavero_editor.plan_desactivar(raw), "Desactivar el llavero",
              "Desactivando el llavero…", cerrar=True)

    pintar()
    leer()
