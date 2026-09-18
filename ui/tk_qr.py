#!/usr/bin/env python3
"""
tk_qr.py — La ventana que enseña la conexión como código QR, para emparejar un
móvil con este dispositivo.

Solo dibuja. Qué va dentro del código lo decide `common/pairing.py` —que lee el
rclone.conf del dispositivo y su clave— y convertirlo en módulos lo hace
`ui/qr.py`; ninguno de los dos importa Tk y los dos se prueban sin pantalla.

**Esto enseña una clave privada en pantalla, y hay que decirlo.** No es un
código de invitación que caduca ni un token de un solo uso: es la misma clave
que está en `keys/`, y quien fotografíe la pantalla se lleva el acceso al
remoto entero. De ahí el recuadro ámbar, que no es adorno: es la única barrera
que hay. Por eso también la ventana no guarda nada, no copia nada al
portapapeles y el código desaparece al cerrarla.

Cuelga de Doctor y no de la ventana principal porque emparejar un móvil se hace
una vez, no cada vez que se sincroniza.
"""

from __future__ import annotations

from common import pairing
from common.model import ConfigError

from . import icons, qr, theme
from .tk import cabecera, cuerpo_visible, bloque_aviso, modal, mostrar

AVISO = ("El código lleva dentro la clave privada de la conexión. Cualquiera "
         "que le haga una foto a esta pantalla tendrá el mismo acceso al "
         "remoto que este dispositivo. Enséñalo solo al móvil que vayas a "
         "emparejar y ciérralo al terminar.")

PISTA = ("Abre prdrive en el móvil, elige «Escanear código» y apunta la cámara "
         "aquí. El móvil se queda con la conexión y con el catálogo; las "
         "parejas las elige después, él solo.")

# El lado del dibujo al que se apunta, en medidas del diseño. De ahí sale cuánto
# mide cada módulo, y no al revés: lo que tiene que ser entero es el módulo —un
# módulo de 3,5 px deja de ser una rejilla—, así que se elige el entero que más
# se acerca y el código sale del tamaño que salga. 380 está elegido para que una
# carga normal (una clave ed25519, que deja el código en unos 93x93 módulos)
# salga a 3 px por módulo, que es donde una cámara de móvil deja de dudar.
LADO = 380
MODULO_MINIMO = 2

# Corrección L, y no la M que trae `qr.py` por defecto, por dos razones que solo
# valen aquí: el soporte es una pantalla —ni arrugas, ni reflejos de impresión,
# ni suciedad—, así que la redundancia sobra; y la carga puede ser grande, que
# una clave RSA de 3072 bits no cabe en NINGUNA versión con corrección M. Lo que
# escasea es capacidad, no tolerancia al borrón.
CORRECCION = "L"

DEMASIADO = ("La clave de este dispositivo es demasiado grande para caber en un "
             "código QR ({e}).\n\nEmparejar por QR funciona con claves ed25519, "
             "que es lo que usa prdrive por defecto. Con una clave RSA grande "
             "habrá que llevar la conexión al móvil de otra manera.")


def _escala(widget, codigo: qr.Codigo) -> int:
    """Cuántos píxeles de lado le tocan a cada módulo en esta pantalla.

    Se escala con la densidad como el resto del diseño (`icons.px`), pero
    redondeando a entero y sin bajar de dos: por debajo de dos píxeles por
    módulo no hay cámara de móvil que lo lea."""
    total = icons.px(widget, LADO)
    return max(MODULO_MINIMO,
               total // (codigo.tamano + icons.QR_SILENCIO * 2))


def open_dialog(parent, raw_local: dict | None = None) -> None:
    """Abre la ventana. No devuelve nada: aquí no se decide nada, se enseña.

    `raw_local` es el `sync_config.toml` en crudo; se pasa desde donde ya está
    leído para no volver a tocar el disco, y `pairing.construir()` lo lee él
    mismo si no se da."""
    from tkinter import ttk

    dlg = modal(parent, "Emparejar un móvil")
    marco = cuerpo_visible(dlg, padding=(22, 20, 22, 18))
    marco.columnconfigure(0, weight=1)

    cabecera(marco, "Emparejar un móvil",
             "Este código lleva la conexión con el remoto: el backend, sus "
             "opciones, dónde está el catálogo y la clave.",
             ancho=560, estilo="Dialogo.TLabel").grid(row=0, column=0, sticky="w")

    bloque_aviso(marco, AVISO, ancho=560).grid(row=1, column=0, sticky="ew",
                                               pady=(14, 0))

    # La tarjeta blanca donde cae el código. El QR se compone contra blanco puro
    # —lo dice `icons.matriz`—, así que el papel cálido de la ventana no puede
    # llegar hasta el borde del dibujo: la zona de silencio tiene que ser blanca
    # o el lector se come una fila de módulos.
    tarjeta = ttk.Frame(marco, style="Card.TFrame", padding=(16, 16, 16, 16))
    tarjeta.grid(row=2, column=0, pady=(16, 0))

    try:
        texto = pairing.construir(raw_local)
        codigo = qr.codificar(texto, CORRECCION)
    except (ConfigError, qr.QRError) as e:
        # Sin conexión que enseñar no hay ventana a medias: se dice por qué y se
        # deja cerrar. Es el caso de un checkout sin provisionar, que es normal.
        # Que no quepa es distinto y merece su propia frase: el usuario no tiene
        # por qué saber qué es una versión de código QR.
        fallo = DEMASIADO.format(e=e) if isinstance(e, qr.QRError) else str(e)
        ttk.Label(tarjeta, text=fallo, style="CardPista.TLabel", justify="left",
                  wraplength=theme.medida(500)).grid(row=0, column=0)
        codigo = None
    else:
        imagen = icons.matriz(tarjeta, codigo.modulos, _escala(tarjeta, codigo))
        if imagen is None:
            ttk.Label(tarjeta, text="No se ha podido dibujar el código.",
                      style="CardPista.TLabel").grid(row=0, column=0)
        else:
            # `Card.TLabel` y no un color propio: la superficie de la tarjeta es
            # blanca, que es justo el papel contra el que se compone el código.
            etiqueta = ttk.Label(tarjeta, image=imagen, style="Card.TLabel")
            # La referencia se guarda en el widget: `icons.matriz` no cachea, y
            # una PhotoImage que solo viva en una variable local se la lleva el
            # recolector en cuanto vuelve esta función.
            etiqueta.imagen = imagen        # type: ignore[attr-defined]
            etiqueta.grid(row=0, column=0)

    ttk.Label(marco, text=PISTA, style="Pista.TLabel", justify="left",
              wraplength=theme.medida(560)).grid(row=3, column=0, sticky="w",
                                                 pady=(14, 0))

    if codigo is not None:
        ttk.Label(marco, style="MonoPista.TLabel",
                  text=f"versión {codigo.version} · corrección {codigo.nivel} "
                       f"· {codigo.tamano}×{codigo.tamano} módulos").grid(
            row=4, column=0, sticky="w", pady=(6, 0))

    ttk.Separator(marco, orient="horizontal").grid(row=5, column=0, sticky="ew",
                                                   pady=(16, 0))
    pie = ttk.Frame(marco)
    pie.grid(row=6, column=0, sticky="e", pady=(14, 0))
    ttk.Button(pie, text="Cerrar", style="Primary.TButton",
               command=dlg.destroy).grid(row=0, column=0)

    mostrar(dlg, parent)
