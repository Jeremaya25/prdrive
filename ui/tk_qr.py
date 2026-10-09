#!/usr/bin/env python3
"""La ventana que enseña la conexión como código QR, para emparejar un móvil.

Solo dibuja. Qué va dentro del código lo decide `common/pairing.py` (que lee el
`rclone.conf` del dispositivo y su clave) y convertirlo en módulos lo hace
`ui/qr.py`; ninguno de los dos importa Tk y los dos se prueban sin pantalla.

**Esto enseña una clave privada en pantalla, y hay que decirlo.** No es un
código de invitación que caduca ni un token de un solo uso: es la misma clave
que está en `keys/` y quien fotografíe la pantalla se lleva el acceso al remoto
entero. De ahí el recuadro ámbar, que no es adorno: es la única barrera que
hay. Por eso también la ventana no guarda nada, no copia nada al portapapeles y
el código desaparece al cerrarla.

Cuelga de «Ajustes» y no de la ventana principal porque emparejar un móvil se
hace una vez, no cada vez que se sincroniza.

En Windows la ventana se excluye además de las capturas de pantalla y de
compartir pantalla (`tk.proteger_de_capturas`), y lo dice con una línea bajo el
aviso según lo que haya conseguido; si no ha conseguido nada, también lo dice.
Es un descuido lo que evita, no un atacante: una foto con otro móvil no la
para, y por eso el recuadro ámbar sigue siendo la barrera principal. Dentro de
«Ajustes» se protege la ventana entera mientras el código está a la vista, y se
le quita la protección al pasar a otro apartado.

**La ventana se pinta antes de que exista el código.** Montar la carga (que lee
el `rclone.conf` y la clave del dispositivo) y codificarla es trabajo de un hilo
(`preparar_codigo`); mientras tanto la tarjeta dice «Preparando el código…». Al
llegar, y por este orden: se protege la ventana, se dibuja el código y se ponen
las líneas que dependen de él. Así no hay un solo instante con el código a la
vista y la ventana sin proteger, aunque la ventana ya estuviera abierta. Si el
apartado se deja antes de que llegue, la espera muere con su marco: no se crea
ninguna imagen ni se protege nada. La lectura no pasa por
`segundo_plano.lanzar_sin_repetir`: su tabla de lecturas vivas guardaría el
resultado después de irse el apartado.
"""

from __future__ import annotations

from functools import partial

from common import pairing
from common.model import ConfigError

from . import icons, qr, segundo_plano, theme
from . import tk as uitk
from .tk import (CAPTURA_EN_NEGRO, CAPTURA_EXCLUIDA, Panel, bloque_aviso, cabecera,
                 dialogo, mostrar, pie, proteger_de_capturas, soltar_capturas)

AVISO = ("Ojo: el código lleva la clave privada\n"
         "Quien le haga una foto a esta pantalla tendrá el mismo acceso al "
         "remoto que este dispositivo. Enséñalo solo al móvil que vayas a "
         "emparejar y ciérralo al terminar.")
"""Lo que se dice en el recuadro ámbar sobre la clave privada."""

LINEA_CAPTURA = {
    CAPTURA_EXCLUIDA: "Esta ventana no aparece en capturas de pantalla ni al "
                      "compartir pantalla.",
    CAPTURA_EN_NEGRO: "En las capturas de pantalla y al compartir pantalla, "
                      "esta ventana sale en negro.",
}
"""La línea bajo el aviso, según la protección que ha quedado puesta.

Solo dice lo que hay: con `CAPTURA_EN_NEGRO` la ventana sí sale en la captura,
así que «no aparece» sería falso. Sin protección, `linea_de_captura()` decide
qué se dice.
"""

LINEA_SIN_PROTECCION = ("No se ha podido proteger esta ventana de las capturas de "
                        "pantalla.")
"""Lo que se dice en Windows cuando ninguna protección ha quedado puesta.

Es verdad en ese caso y solo en ese: la persona que comparte pantalla tiene que
saber que esta ventana sí se vería. El aviso ámbar sigue diciendo que una foto
basta.
"""

PISTA = ("Abre prdrive en el móvil, elige «Escanear código» y apunta la cámara "
         "aquí. El móvil se queda con la conexión y con el catálogo; las "
         "parejas las elige después, él solo.")
"""Cómo se usa el código en el móvil."""

PREPARANDO = "Preparando el código…"
"""Lo que dice la tarjeta mientras se monta y se codifica la carga."""

LADO = 380
"""El lado del dibujo al que se apunta, en medidas del diseño.

De ahí sale cuánto mide cada módulo y no al revés: lo que tiene que ser entero
es el módulo (uno de 3,5 px deja de ser una rejilla), así que se elige el
entero que más se acerca y el código sale del tamaño que salga. 380 está
elegido para que una carga normal (una clave ed25519, que deja el código en
unos 93x93 módulos) salga a 3 px por módulo, que es donde una cámara de móvil
deja de dudar.
"""
MODULO_MINIMO = 2
"""Píxeles mínimos por módulo."""

CORRECCION = "L"
"""El nivel de corrección del código: L y no la M que trae `qr.py` por defecto.

Hay dos razones que solo valen aquí: el soporte es una pantalla (ni arrugas, ni
reflejos de impresión, ni suciedad), así que la redundancia sobra; y la carga
puede ser grande, que una clave RSA de 3072 bits no cabe en NINGUNA versión con
corrección M. Lo que escasea es capacidad, no tolerancia al borrón.
"""

DEMASIADO = ("La clave de este dispositivo es demasiado grande para caber en un "
             "código QR ({e}).\n\nEmparejar por QR funciona con claves ed25519, "
             "que es lo que usa prdrive por defecto. Con una clave RSA grande "
             "habrá que llevar la conexión al móvil de otra manera.")
"""Lo que se dice cuando la clave no cabe en un código QR."""


def linea_de_captura(proteccion: int) -> str | None:
    """Devuelve la línea que va bajo el aviso ámbar, o `None` si no hay nada que decir.

    Con una protección puesta, la que corresponde (`LINEA_CAPTURA`). Sin ella,
    en Windows se dice que no se ha podido (`LINEA_SIN_PROTECCION`: el fallo no
    puede ser silencioso, hay quien comparte pantalla confiando en la
    protección). Fuera de Windows no hay protección que prometer ni que
    lamentar (Linux no tiene equivalente: X11 no ofrece ninguna API y Wayland lo
    decide el portal), y callar no promete nada.

    Args:
        proteccion: Lo que devolvió `tk.proteger_de_capturas()`.
    """
    linea = LINEA_CAPTURA.get(proteccion)
    if linea is None and uitk.IS_WIN:
        return LINEA_SIN_PROTECCION
    return linea


def _escala(widget, codigo: qr.Codigo) -> int:
    """Devuelve cuántos píxeles de lado le tocan a cada módulo en esta pantalla.

    Se escala con la densidad como el resto del diseño (`icons.px`), pero
    redondeando a entero y sin bajar de dos: por debajo de dos píxeles por
    módulo no hay cámara de móvil que lo lea.
    """
    total = icons.px(widget, LADO)
    return max(MODULO_MINIMO,
               total // (codigo.tamano + icons.QR_SILENCIO * 2))


def preparar_codigo(raw_local: dict | None = None) -> qr.Codigo:
    """Monta la carga de emparejamiento y la codifica como código QR.

    Es el trabajo que corre en un hilo (`segundo_plano.lanzar`) mientras la
    ventana ya está pintada, y un punto de indirección: los tests la sustituyen.
    La carga lleva la clave privada del dispositivo: su texto no sale de esta
    función, ni se devuelve ni se guarda; solo salen los módulos del código. Ni
    siquiera en un fallo: si no cabe, el error que sale es uno nuevo, sin los
    marcos de `qr.codificar()` (que llevan la carga en sus variables) colgando
    de su traza.

    Args:
        raw_local: El `sync_config.toml` en crudo, o `None` para que
            `pairing.construir()` lo lea.

    Returns:
        El código, en corrección `CORRECCION`.

    Raises:
        ConfigError: Si el dispositivo no tiene conexión que enseñar.
        qr.QRError: Si la carga no cabe en ninguna versión de código QR.
    """
    texto = pairing.construir(raw_local)
    try:
        return qr.codificar(texto, CORRECCION)
    except qr.QRError as e:
        no_cabe = str(e)
    finally:
        del texto
    raise qr.QRError(no_cabe)


def open_dialog(parent, raw_local: dict | None = None) -> None:
    """Abre la ventana; no devuelve nada: aquí no se decide nada, se enseña.

    Args:
        raw_local: El `sync_config.toml` en crudo; se pasa desde donde ya está
            leído para no volver a tocar el disco, y `pairing.construir()` lo
            lee él mismo si no se da.
    """
    dialogo(parent, "Emparejar un móvil", lambda p: construir(p, raw_local),
            ensenar=mostrar)


def construir(panel: Panel, raw_local: dict | None = None) -> None:
    """Dibuja «Emparejar un móvil» en `panel` (su diálogo o «Ajustes»).

    Pinta el aviso y la tarjeta vacía («Preparando el código…») y pide el
    código a un hilo; lo que depende de él se pone al llegar (`llegada()`).
    """
    from tkinter import ttk

    dlg, marco = panel.ventana, panel.marco

    cabecera(marco, "Emparejar un móvil",
             "Este código lleva la conexión con el remoto: el backend, sus "
             "opciones, dónde está el catálogo y la clave.",
             ancho=560, estilo="Dialogo.TLabel").grid(row=0, column=0, sticky="w")

    bloque_aviso(marco, AVISO, ancho=560).grid(row=1, column=0, sticky="ew",
                                               pady=(theme.E4, 0))

    # La tarjeta blanca donde cae el código. El QR se compone contra blanco
    # puro (lo dice `icons.matriz`), así que el papel cálido de la ventana no
    # puede llegar hasta el borde del dibujo: la zona de silencio tiene que ser
    # blanca o el lector se come una fila de módulos.
    tarjeta = ttk.Frame(marco, style="Card.TFrame", padding=(theme.E4, theme.E4, theme.E4, theme.E4))
    tarjeta.grid(row=3, column=0, pady=(theme.E4, 0))
    espera = ttk.Label(tarjeta, text=PREPARANDO, style="Card.Pista.TLabel")
    espera.grid(row=0, column=0)

    ttk.Label(marco, text=PISTA, style="Pista.TLabel", justify="left",
              wraplength=theme.medida(560)).grid(row=4, column=0, sticky="w",
                                                 pady=(theme.E4, 0))

    botones = pie(marco, 6)
    botones.columnconfigure(0, weight=1)
    ttk.Button(botones, text="Cerrar", style="Primary.TButton",
               command=panel.cerrar).grid(row=0, column=1)

    def llegada(encargo) -> None:
        """Pone el código en la tarjeta, o dice por qué no hay.

        Con código, por este orden: la protección de la ventana, la imagen y
        las líneas que dependen de ellas. La protección va la primera para que
        no haya un instante con la imagen a la vista y la ventana sin proteger;
        en «Ajustes», donde la ventana ya está a la vista, el código no se
        pinta hasta que Tk descansa, y eso es después de esto. Al irse del
        apartado se le quita, que los demás sí pueden salir en una captura.
        """
        espera.destroy()
        if encargo.error is not None:
            # Sin conexión que enseñar no hay ventana a medias: se dice por qué y
            # se deja cerrar. Es el caso de un checkout sin provisionar, que es
            # normal. Que no quepa es distinto y merece su propia frase: la persona
            # no tiene por qué saber qué es una versión de código QR.
            e = encargo.error
            if isinstance(e, qr.QRError):
                fallo = DEMASIADO.format(e=e)
            elif isinstance(e, ConfigError):
                fallo = str(e)
            else:
                fallo = f"No se ha podido preparar el código: {e}"
            ttk.Label(tarjeta, text=fallo, style="Card.Pista.TLabel", justify="left",
                      wraplength=theme.medida(500)).grid(row=0, column=0)
            panel.ajustar()
            return
        codigo = encargo.resultado
        if panel.incrustado:
            marco.bind("<Destroy>", lambda e: soltar_capturas(dlg)
                       if e.widget is marco else None, add="+")
        # La línea se decide con lo que Windows haya aceptado y ocupa la fila 2,
        # que sin ella queda vacía.
        linea = linea_de_captura(proteger_de_capturas(dlg))
        imagen = icons.matriz(tarjeta, codigo.modulos, _escala(tarjeta, codigo))
        if imagen is None:
            # Sin código a la vista no hay nada que proteger, y una ventana que
            # no sale en las capturas tampoco deja fotografiar el error.
            soltar_capturas(dlg)
            ttk.Label(tarjeta, text="No se ha podido dibujar el código.",
                      style="Card.Pista.TLabel").grid(row=0, column=0)
        else:
            # `Card.TLabel` y no un color propio: la superficie de la tarjeta
            # es blanca, que es justo el papel contra el que se compone el
            # código.
            etiqueta = ttk.Label(tarjeta, image=imagen, style="Card.TLabel")
            # La referencia se guarda en el widget: `icons.matriz` no cachea y
            # una `PhotoImage` que solo viva en una variable local se la lleva
            # el recolector en cuanto vuelve esta función.
            etiqueta.imagen = imagen        # type: ignore[attr-defined]
            etiqueta.grid(row=0, column=0)
            if linea is not None:
                ttk.Label(marco, text=linea, style="Pista.TLabel", justify="left",
                          wraplength=theme.medida(560)).grid(row=2, column=0,
                                                             sticky="w", pady=(theme.E2, 0))
        ttk.Label(marco, style="MonoPista.TLabel",
                  text=f"versión {codigo.version} · corrección {codigo.nivel} "
                       f"· {codigo.tamano}×{codigo.tamano} módulos").grid(
            row=5, column=0, sticky="w", pady=(theme.E2, 0))
        panel.ajustar()

    # Un `lanzar` simple y no `lanzar_sin_repetir`: su tabla de lecturas vivas
    # guardaría el código después de irse el apartado. La espera cuelga del
    # marco, así que dejarlo antes de que llegue la cancela: no se protege nada
    # ni se crea ninguna imagen.
    panel.sondeo().esperar(segundo_plano.lanzar(partial(preparar_codigo, raw_local)),
                           llegada)
