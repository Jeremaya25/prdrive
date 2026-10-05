#!/usr/bin/env python3
"""«Ajustes»: lo que se hace de vez en cuando y no cada vez.

Era «Doctor», un botón que lanzaba `sync.py --doctor` y nada más. Se convirtió
en una pantalla por una razón concreta: la ventana principal ya está llena (sus
avisos, la lista de parejas, tres botones y dos acciones) y todo lo que se hace
una vez en la vida del dispositivo tiene que caber en algún sitio que no sea
esa ventana. Esta es ese sitio.

En la ventana se llama «Ajustes», detrás de un engranaje, y no «Doctor»: el
doctor es una de sus entradas (la primera), no la pantalla, y aquí es donde va
también lo que se configura. El módulo conserva su nombre porque el subcomando
`sync.py --doctor` no cambia y porque es a esta pantalla a la que apunta el
rediseño de la pantalla de reparación.

Solo dibuja, y menos que ninguna otra: no escribe nada y no decide nada. Cada
entrada es un botón y una frase que dice qué pasa al pulsarlo; lo que pasa lo
hace el módulo de turno. Lo que se configura (el intervalo del servicio y, en
la raíz cifrada de un equipo, si se pide la contraseña al iniciar sesión) va en
«Configuración…» (`ui/tk_configuracion.py`). Una entrada sale solo a veces:
«Renombrar el catálogo…», mientras el remoto conserve su `pairs.toml`, y eso
lo dice `catalog_editor.ofrecer_renombrado()` sin red (`OCASIONALES`).

`lanzar` llega desde la ventana principal en vez de importarse: la comprobación
se enseña en su ventana de salida, que es hija de la principal y no de esta, y
que además se apaga sola mientras hay otra pasada en curso. Esta pantalla no
tiene por qué saber nada de eso.
"""

from __future__ import annotations

from common.model import Config

from . import catalog_editor, theme
from .tk import cabecera, cuerpo_visible, modal, mostrar, separador_fila

ENTRADAS = (
    ("Reparación…", "doctor",
     "Lo que está mal en este dispositivo y qué hacer con ello: baselines que no "
     "son de su pareja, bloqueos sueltos, ficheros en conflicto. Nada se toca "
     "sin confirmarlo.",
     "reparacion"),
    ("Configuración…", "clock",
     "Cada cuánto sincroniza el servicio y, en la carpeta cifrada de un equipo, "
     "si el agente pide la contraseña al iniciar sesión.",
     "configuracion"),
    ("Emparejar un móvil…", "dispositivo",
     "Enseña la conexión con el remoto como código QR para que la lea otro "
     "aparato. Lleva la clave privada dentro: el código avisa.",
     "qr"),
    ("Versiones…", "file",
     "Lo guardado en .prversions/ por las parejas que versionan: cuánto ocupa "
     "en cada lado, abrir la carpeta de aquí y purgar lo anterior a una fecha.",
     "versiones"),
    ("Nombre e icono de la unidad…", "edit",
     "Cómo la enseña el Explorador de Windows al conectarla. Útil para "
     "distinguir un dispositivo de otro a simple vista.",
     "volumen"),
    ("Renombrar el catálogo…", "edit",
     "El catálogo de este remoto conserva su nombre de antes, pairs.toml. "
     "Pasarlo a remote.toml es opcional, y solo se puede cuando todos los "
     "dispositivos de la flota saben leer el nombre nuevo.",
     "renombrar"),
)
"""Las entradas de la pantalla: rótulo del botón, icono, frase y clave de la acción."""

OCASIONALES = {"renombrar": catalog_editor.ofrecer_renombrado}
"""Las entradas que solo salen a veces: su clave y quién dice, sin red, si sale."""


def open_dialog(parent, config: Config, lanzar, raw_local: dict | None = None,
                abrir_reparacion=None) -> None:
    """Abre «Ajustes»; no devuelve nada.

    De aquí no sale ninguna decisión que quien llama tenga que repintar. Lo que
    cambia estado (si algún día algo lo hace) abrirá su propia ventana y se
    encargará él.

    Args:
        config: La configuración, que se pasa a las pantallas que la necesitan.
        lanzar: `lanzar(titulo, args)`, el de la ventana principal.
        raw_local: El `sync_config.toml` en crudo, para el emparejamiento.
        abrir_reparacion: Llega de la ventana principal por lo mismo que
            `lanzar`: «Reparación» puede acabar lanzando una pasada y su
            ventana de salida es hija de la principal, no de esta. Además esta
            se cierra antes de abrirla, para no tener dos modales disputándose
            la captura del ratón.
    """
    from tkinter import ttk

    dlg = modal(parent, "Ajustes")
    marco = cuerpo_visible(dlg, padding=(22, 20, 22, 18))
    marco.columnconfigure(0, weight=1)

    cabecera(marco, "Ajustes",
             "Lo que se mira o se hace de tarde en tarde, para que la ventana "
             "principal se quede con lo de todos los días.",
             ancho=560, estilo="Dialogo.TLabel").grid(row=0, column=0, sticky="w")

    def reparacion() -> None:
        """Cierra «Ajustes» y abre «Reparación».

        Se abre desde la principal y por eso esta se cierra antes: son dos
        modales y la de allí puede abrir a su vez la ventana de salida, que es
        hija de la principal.
        """
        dlg.destroy()
        if abrir_reparacion is not None:
            abrir_reparacion()

    def configuracion() -> None:
        """Abre «Configuración»: el intervalo del servicio y lo del agente."""
        from . import tk_configuracion
        tk_configuracion.open_dialog(dlg, config)

    def emparejar() -> None:
        """Abre el emparejamiento de un móvil."""
        from . import tk_qr
        tk_qr.open_dialog(dlg, raw_local)

    def versiones() -> None:
        """Abre las versiones guardadas."""
        from . import tk_versions
        tk_versions.open_dialog(dlg, config)

    def nombre_e_icono() -> None:
        """Abre el nombre y el icono de la unidad."""
        from . import tk_volumen
        tk_volumen.open_dialog(dlg)

    def renombrar() -> None:
        """Abre «Renombrar el catálogo»."""
        from . import tk_renombrar
        tk_renombrar.open_dialog(dlg, raw)

    acciones = {"reparacion": reparacion, "configuracion": configuracion,
                "qr": emparejar, "versiones": versiones, "volumen": nombre_e_icono,
                "renombrar": renombrar}
    raw = catalog_editor.raw_del_dispositivo(raw_local)
    entradas = [e for e in ENTRADAS
                if e[3] not in OCASIONALES or OCASIONALES[e[3]](raw)]

    tarjeta = ttk.Frame(marco, style="Card.TFrame", padding=(14, 12, 14, 12))
    tarjeta.grid(row=1, column=0, sticky="ew", pady=(16, 0))
    tarjeta.columnconfigure(0, weight=1)

    fila = 0
    for rotulo, icono, frase, clave in entradas:
        if fila:
            separador_fila(tarjeta, fila, 1)
            fila += 1
        boton = ttk.Button(tarjeta, text=rotulo, style="CardQuiet.TButton",
                           command=acciones[clave])
        theme.boton_icono(boton, icono, theme.ACENTO, theme.SUPERFICIE)
        boton.grid(row=fila, column=0, sticky="w", pady=(8, 0))
        fila += 1
        ttk.Label(tarjeta, text=frase, style="Card.Pista.TLabel", justify="left",
                  wraplength=theme.medida(540)).grid(row=fila, column=0,
                                                     sticky="w", pady=(3, 10))
        fila += 1

    ttk.Separator(marco, orient="horizontal").grid(row=2, column=0, sticky="ew",
                                                   pady=(16, 0))
    pie = ttk.Frame(marco)
    pie.grid(row=3, column=0, sticky="e", pady=(14, 0))
    ttk.Button(pie, text="Cerrar", command=dlg.destroy).grid(row=0, column=0)

    mostrar(dlg, parent)
