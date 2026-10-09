#!/usr/bin/env python3
"""Los pasos del asistente «En este equipo».

Solo dibuja. Lo que decide y lo que toca el disco está en `install/agente.py` y
`install/raiz_equipo.py`, igual que el resto del asistente con `install/`. Hay
dos recorridos, que elige el paso «Raíz» (ver `tk_install.PASOS_EQUIPO`):

    Raíz           la raíz de este equipo: carpeta propia, la personal, o ninguna
    Cifrado        sin cifrar, o en un contenedor VeraCrypt (solo la carpeta propia;
                   el instalado, o el oficial sin instalar, que se lleva el agente).
                   Va antes que «Carpeta» porque cambia qué carpeta se pide
    Carpeta        sin cifrar, la raíz; cifrada, dónde va el contenedor y dónde se
                   abre: lo crea, lo monta y lo deja abierto
    Conexión, Comprobaciones        los del recorrido de una unidad, tal cual
    Instalación    .prdrive/ + rclone en la raíz; el agente y su Python en el equipo
    Parejas        las del catálogo, con la ruta de cada una EN ESTE equipo
    Inicialización el de siempre, con el Python del agente
    Unidades       qué unidades atiende ya y cómo, y el plazo de «unidad nueva»
    Arranque       que arranque al iniciar sesión; penwatch fuera
    Verificación   lo que de verdad quedó puesto

Con «Ninguna: solo atender unidades» sobran conexión, catálogo y parejas: cada
unidad trae los suyos. Es la instalación «solo agente».

Lo que el asistente va sabiendo vive en el propio `Wizard` (`agente_*`,
`equipo_*`) y no en los widgets: `repintar()` los destruye al cambiar de paso.

Lo que mira el disco o el sistema no corre en el hilo de Tk: las carpetas que
se escriben se examinan al dejar de teclear (`ExamenDiferido`) y «Verificación»
comprueba en otro hilo, con `ui.segundo_plano` y un `Sondeo` del paso.
"""

from __future__ import annotations

from functools import partial
from pathlib import Path

from . import segundo_plano, theme, watch
from .tk import Indicador, Resultado, Sondeo, bloque_aviso, tabla_estado, working

ANCHO = 780
"""El ancho del texto de los pasos, en medidas del diseño."""

ESPERA_TECLA_MS = 250
"""Milisegundos sin teclear antes de examinar lo escrito en una caja.

Se lee en cada tecla, no al importar: los tests lo ponen a 0 y mueven el bucle
de eventos después de escribir.
"""
MIRANDO = "Mirando la carpeta…"
"""Lo que dice la línea de debajo de una caja mientras se examina lo escrito."""

PREGUNTAR = "preguntar"
"""Una opción de la lista de «Unidades» además de los modos del agente.

Es no meterla en su lista y que pregunte al enchufarla. Es lo que se propone
para las que salen de la flota: nunca se sincroniza una unidad sin que se haya
dicho que sí.
"""
TEXTO_PREGUNTAR = "preguntar al enchufarla"
"""Cómo se llama en la lista la opción `PREGUNTAR`."""


def _texto(cuerpo, texto: str, fila: int, **kw) -> None:
    """Pone un párrafo de texto en la fila de un paso."""
    from tkinter import ttk
    kw.setdefault("style", "Campo.TLabel")
    ttk.Label(cuerpo, justify="left", wraplength=theme.medida(ANCHO), text=texto,
              **kw).grid(row=fila, column=0, sticky="w", pady=(0, theme.E3))


def _ambar(cuerpo, texto: str, fila: int):
    """Pone un recuadro ámbar en la fila de un paso y lo devuelve."""
    caja = bloque_aviso(cuerpo, texto, ancho=ANCHO - 80)
    caja.grid(row=fila, column=0, sticky="ew", pady=(0, theme.E3))
    return caja


def al_cambiar(entrada, funcion) -> None:
    """Llama a `funcion(texto)` con cada cambio de la caja, tecleado o no.

    Se hace con `validatecommand` y no con un `trace` de la variable: el
    comando se registra en la propia caja y muere con ella (`Misc.destroy()`
    borra sus `_tclCommands`), mientras que el de un trace sobrevive al widget
    y retiene la ventana entera (`docs/agents/reference/ui.md`, la ventana
    principal). Se llama ANTES de que el texto cambie, por eso recibe el nuevo;
    y devuelve siempre `True`, porque si no, Tk apagaría la validación de la
    caja para siempre.
    """
    def validar(nuevo: str) -> bool:
        """Llama a `funcion` con el texto nuevo y deja siempre que cambie."""
        # Sin `return` en un `finally`, que Python 3.14 avisa como
        # SyntaxWarning (PEP 765): el fallo se traga igual y se devuelve True.
        try:
            funcion(nuevo)
        except Exception:                               # noqa: BLE001
            pass
        return True
    entrada.configure(validate="key",
                      validatecommand=(entrada.register(validar), "%P"))


class ExamenDiferido:
    """Examina lo escrito en una o varias cajas fuera del hilo de Tk, al dejar de teclear.

    Cada tecla (`tecla()`) deja en el acto lo que depende del examen como
    pendiente (`al_teclear`) y rearma una única espera de `ESPERA_TECLA_MS`
    colgada de `ancla`, nunca de la ventana: cambiar de paso destruye la caja
    y la espera muere con ella sin examinar nada. Al vencer, o con `ya()`, se
    lee la clave (lo escrito AHORA, no el texto que vio `validatecommand`) y
    el examen va a `segundo_plano.lanzar()` como `partial(funcion, *clave)`; lo
    recoge un `Sondeo` también colgado de `ancla`. Lo que llega solo cuenta si
    la clave sigue siendo la misma: el examen de un texto viejo no cuenta.

    Args:
        ancla: La caja de la que cuelgan la espera y el sondeo.
        clave: Devuelve lo que se examina, leído de las cajas en el hilo de Tk.
        funcion: El examen. Recibe la clave desplegada, no toca Tk y es una
            función de módulo (o un `partial` de datos).
        al_teclear: Deja en el acto lo que depende del examen como pendiente.
        al_llegar: Recibe el `Encargo` del examen de lo que sigue escrito.

    Attributes:
        examinada: La clave del último examen que contó, o `None` desde la
            última tecla.
        resultado: Lo que devolvió ese examen (`None` si falló).
        sondeo: El `Sondeo` del examen en curso.
    """

    def __init__(self, ancla, clave, funcion, al_teclear, al_llegar) -> None:
        """Engancha la espera a la caja; no examina nada todavía."""
        self.ancla = ancla
        self.clave = clave
        self.funcion = funcion
        self.al_teclear = al_teclear
        self.al_llegar = al_llegar
        self.examinada = None
        self.resultado = None
        self.sondeo = Sondeo(ancla)
        self._id = None
        ancla.bind("<Destroy>", self._al_destruir, add="+")

    def tecla(self, *_) -> None:
        """Deja el examen pendiente y rearma la espera; es lo que hace cada tecla."""
        self._olvidar()
        self.al_teclear()
        self._quitar_espera()
        self._id = self.ancla.after(ESPERA_TECLA_MS, self._vencer)

    def ya(self) -> None:
        """Examina lo escrito ahora mismo, sin esperar a que se deje de teclear."""
        self._quitar_espera()
        self._olvidar()
        self._lanzar()

    def vigente(self):
        """Devuelve el último examen si es de lo que hay escrito ahora, o `None`."""
        if self.examinada is not None and self.examinada == self.clave():
            return self.resultado
        return None

    def _olvidar(self) -> None:
        """Da por caducado el último examen."""
        self.examinada = self.resultado = None

    def _lanzar(self) -> None:
        """Encarga el examen de lo escrito ahora."""
        clave = self.clave()
        encargo = segundo_plano.lanzar(partial(self.funcion, *clave))
        self.sondeo.esperar(encargo, partial(self._llega, clave))

    def _llega(self, clave, encargo) -> None:
        """Aplica el examen si lo escrito sigue siendo lo examinado."""
        if clave != self.clave():
            return               # se escribió otra cosa: su examen está en camino
        self.examinada = clave
        self.resultado = encargo.resultado if encargo.error is None else None
        self.al_llegar(encargo)

    def _vencer(self) -> None:
        """Se ha dejado de teclear: examina."""
        self._id = None
        self._lanzar()

    def _quitar_espera(self) -> None:
        """Cancela la espera de la última tecla, si la hay."""
        if self._id is not None:
            try:
                self.ancla.after_cancel(self._id)
            except Exception:                            # noqa: BLE001 — ya no está
                pass
            self._id = None

    def _al_destruir(self, evento) -> None:
        """Cancela la espera si lo que se destruye es la caja, no un hijo suyo."""
        if str(evento.widget) == str(self.ancla):
            self._quitar_espera()


def examen_contenedor(fisica: str, carpeta: str, forma: str, con_punto: bool):
    """Examina dónde irá el contenedor y, si se monta en una carpeta, esa carpeta.

    No toca Tk: es lo que corre en el hilo del paso del contenedor. En Linux la
    carpeta donde se abre es la raíz, así que también tiene que poder serlo.

    Args:
        fisica: Dónde va el `.hc`.
        carpeta: Dónde se monta (Linux) o la carpeta de la raíz (Windows).
        forma: La forma de la raíz (`raiz_equipo.PROPIA`, …).
        con_punto: Si se monta en `carpeta` (Linux).

    Returns:
        El `raiz_equipo.Examen` que manda: el de la carpeta si no vale, si no
        el del contenedor.
    """
    from install import raiz_equipo
    examen = raiz_equipo.examinar_contenedor(fisica, carpeta, forma)
    if con_punto:
        raiz_examen = raiz_equipo.examinar(carpeta, forma)
        if not raiz_examen.vale:
            examen = raiz_examen
    return examen


def _fallido(encargo):
    """Devuelve el examen que se enseña cuando el examen mismo ha fallado."""
    from install import raiz_equipo
    return raiz_equipo.Examen(raiz_equipo.NO_VALE,
                              f"No se ha podido examinar la carpeta: {encargo.error}")


def con_raiz(wiz) -> bool:
    """Indica si este recorrido pone una raíz en el equipo o es «solo agente»."""
    from install import raiz_equipo
    return wiz.equipo_forma != raiz_equipo.NINGUNA


def raiz(wiz) -> Path | None:
    """Devuelve la raíz de este equipo, o `None` en el recorrido «solo agente»."""
    return wiz.state.device_root if con_raiz(wiz) else None


def paso_raiz(cuerpo, wiz) -> None:
    """Pinta el paso que pregunta qué raíz tiene este equipo.

    Es una carpeta propia, la personal o ninguna. Solo la forma: si va cifrada
    lo pregunta «Cifrado» y la carpeta exacta «Carpeta», por ese orden, porque
    cifrar cambia qué carpeta se pide. Cambiar de respuesta cambia la lista de
    pasos (`tk_install.pasos_equipo`), como «¿Dónde?».
    """
    import tkinter as tk
    from tkinter import ttk

    from install import raiz_equipo as re_

    _texto(cuerpo, "¿Dónde deja este equipo lo que se sincroniza con el remoto? Es "
                   "su raíz, lo mismo que la de una unidad: las parejas del catálogo "
                   "caen en carpetas de dentro, y el programa va en .prdrive/. Aquí "
                   "no se crean parejas, solo se elige dónde viven. Si se cifra, y "
                   "la carpeta exacta, en los pasos siguientes.", 0)
    eleccion = tk.StringVar(value=wiz.equipo_forma)

    def elegir() -> None:
        """Apunta la forma elegida y rehace la lista de pasos."""
        forma = eleccion.get()
        if forma != wiz.equipo_forma:
            wiz.equipo_forma = forma
            por_defecto = re_.por_defecto(forma)
            wiz.equipo_ruta = str(por_defecto) if por_defecto else ""
        from .tk_install import pasos_equipo
        wiz.pasos = pasos_equipo(wiz)
        wiz.repintar()

    opciones = (
        (re_.PROPIA, "Una carpeta propia (recomendado)",
         f"{re_.carpeta_propia()}, u otra que elijas: prdrive y tus parejas dentro, "
         "como la carpeta de Dropbox. Nada de fuera de ella se toca. Se puede "
         "cifrar."),
        (re_.PERSONAL, "Tu carpeta personal",
         f"{re_.carpeta_personal()}: sincroniza carpetas que ya tienes, como "
         "Documentos/Obsidian, sin moverlas. A cambio, el límite es todo tu usuario, "
         "y no se puede cifrar."),
        (re_.NINGUNA, "Ninguna: solo atender unidades",
         "Sin conexión ni clave en este equipo: el agente sincroniza las unidades "
         "prdrive que enchufes, y cada una trae las suyas."),
    )
    for i, (valor, titulo, texto) in enumerate(opciones):
        tarjeta = ttk.Frame(cuerpo, style="Card.TFrame", padding=(theme.E4, theme.E2))
        tarjeta.grid(row=1 + i, column=0, sticky="ew", pady=(0, theme.E2))
        tarjeta.columnconfigure(0, weight=1)
        ttk.Radiobutton(tarjeta, text=titulo, value=valor, variable=eleccion,
                        style="Card.Fuerte.TRadiobutton", command=elegir).grid(
            row=0, column=0, sticky="w")
        ttk.Label(tarjeta, text=texto, style="Card.Pista.TLabel", justify="left",
                  wraplength=theme.medida(720)).grid(row=1, column=0, sticky="w",
                                                     pady=(theme.E1, 0))
    if not con_raiz(wiz):
        wiz.state.device_root = None


def cifrada(wiz) -> bool:
    """Indica si la raíz de este equipo va en un contenedor VeraCrypt."""
    from install import raiz_equipo
    return con_raiz(wiz) and wiz.equipo_cifrado == raiz_equipo.VERACRYPT


def paso_cifrado(cuerpo, wiz) -> None:
    """Pinta el paso que elige entre sin cifrar y un contenedor VeraCrypt.

    Va antes de pedir la carpeta: sin cifrar, «Carpeta» pide la raíz; cifrada,
    dónde va el contenedor y dónde se abre (una letra fija en Windows, una
    carpeta vacía en Linux), y ESE volumen es la raíz. Aquí solo se elige y se
    consigue VeraCrypt si falta.
    """
    import tkinter as tk
    from tkinter import messagebox, ttk

    from install import IS_WIN, raiz_equipo as re_

    from .tk import TITLE

    vc = re_.veracrypt_para_raiz()
    personal = wiz.equipo_forma == re_.PERSONAL
    puede = vc is not None and not personal
    if not puede:
        wiz.equipo_cifrado = re_.SIN_CIFRAR
    eleccion = tk.StringVar(value=wiz.equipo_cifrado)

    def elegir() -> None:
        """Apunta si se cifra y repinta."""
        wiz.equipo_cifrado = eleccion.get()
        wiz.repintar()

    _texto(cuerpo, "¿Cifrar la raíz de este equipo? Se sincroniza lo mismo; lo que "
                   "cambia es que todo queda dentro de un fichero cifrado.", 0)
    donde = ("como una unidad con letra fija (P:, por ejemplo)" if IS_WIN else
             "en una carpeta vacía que eliges")
    opciones = (
        (re_.SIN_CIFRAR, "Sin cifrar",
         "La carpeta que elijas en el paso siguiente es la raíz, tal cual. La clave "
         "del remoto queda en claro en el disco (el paso «Instalación» dice si el "
         "disco tiene BitLocker)."),
        (re_.VERACRYPT, "En un contenedor VeraCrypt",
         "Todo va DENTRO de un fichero cifrado: el programa, la clave y las carpetas "
         "de las parejas con tus datos. Fuera solo queda ese fichero. Abierto, su "
         f"contenido aparece {donde}, y ahí trabajas. Cerrado, no hay nada que leer "
         "ni que sincronizar por error. Lo abre el agente al iniciar sesión "
         "(VeraCrypt pide la contraseña en su ventana) y lo cierras con «Bloquear». "
         "En el paso siguiente eliges dónde va el fichero, su tamaño y la "
         "contraseña, y se crea."))
    for i, (valor, titulo, texto) in enumerate(opciones):
        tarjeta = ttk.Frame(cuerpo, style="Card.TFrame", padding=(theme.E4, theme.E2))
        tarjeta.grid(row=1 + i, column=0, sticky="ew", pady=(0, theme.E2))
        tarjeta.columnconfigure(0, weight=1)
        radio = ttk.Radiobutton(tarjeta, text=titulo, value=valor, variable=eleccion,
                                style="Card.Fuerte.TRadiobutton", command=elegir)
        radio.grid(row=0, column=0, sticky="w")
        if valor == re_.VERACRYPT and not puede:
            radio.configure(state="disabled")
        ttk.Label(tarjeta, text=texto, style="Card.Pista.TLabel", justify="left",
                  wraplength=theme.medida(720)).grid(row=1, column=0, sticky="w",
                                                     pady=(theme.E1, 0))
    if not puede:
        caja = _ambar(cuerpo, re_.examinar_contenedor("x", wiz.equipo_ruta,
                                                      wiz.equipo_forma).texto
                      if personal else re_.COMO_INSTALAR, 3)
        if not personal:
            # Sin VeraCrypt instalado no hace falta instalarlo: el Portable
            # oficial en Windows, el AppImage en Linux, bajado y comprobado
            # (`install/veracrypt_bin.py`), el mismo que se llevará el agente
            # para abrirla y cerrarla.
            def descargar() -> None:
                """Baja VeraCrypt sin instalarlo y repinta si se ha podido."""
                from common import pins
                from install import veracrypt_bin
                ok, res = working(
                    wiz.root, "descargando VeraCrypt",
                    lambda: veracrypt_bin.para_este_equipo(),
                    f"Descargando VeraCrypt {pins.VERACRYPT_VERSION} y "
                    f"comprobándolo.")
                if ok and re_.veracrypt_para_raiz() is not None:
                    wiz.repintar()
                    return
                messagebox.showerror(TITLE, (
                    f"No se ha podido usar VeraCrypt sin instalar:\n\n{res}" if not ok
                    else "El VeraCrypt descargado no trae los ejecutables de este "
                         "equipo."), parent=wiz.root)

            ttk.Button(caja, text=("Descargar VeraCrypt Portable" if IS_WIN else
                                   "Descargar VeraCrypt (AppImage)"),
                       style="Primary.TButton", command=descargar).grid(
                row=1, column=0, sticky="w", pady=(theme.E2, 0))
    elif re_.portatil(vc):
        _ambar(cuerpo, re_.AVISO_PORTATIL, 3)

    if wiz.equipo_cifrado == re_.VERACRYPT:
        wiz.state.encryption = "veracrypt"
        wiz.state.veracrypt = vc
    else:
        wiz.state.encryption = None


def ok_cifrado(wiz) -> bool:
    """Indica si se puede seguir desde el paso de cifrado."""
    return True


def paso_carpeta(cuerpo, wiz) -> None:
    """Pinta el paso de la carpeta exacta, según lo elegido en «Cifrado».

    Sin cifrar es la raíz; cifrada, el contenedor (`_carpeta_cifrada`). La
    carpeta escrita se examina fuera del hilo de Tk (`ExamenDiferido`): al
    pintar, en el acto; al teclear, al dejar de hacerlo. Mientras, la raíz no
    está fijada y «Siguiente» está apagado.
    """
    if cifrada(wiz):
        _carpeta_cifrada(cuerpo, wiz)
        return
    import tkinter as tk
    from tkinter import filedialog, ttk

    from install import raiz_equipo as re_

    wiz.state.encryption = None
    personal = wiz.equipo_forma == re_.PERSONAL
    _texto(cuerpo, (
        "Tu carpeta personal es la raíz: las parejas pueden caer en cualquier "
        "carpeta de tu usuario, y el programa va en .prdrive/." if personal else
        "¿En qué carpeta? Es la raíz: las parejas son carpetas de dentro, y el "
        "programa va en .prdrive/."), 0)
    fila = ttk.Frame(cuerpo)
    fila.grid(row=1, column=0, sticky="ew", pady=(theme.E1, 0))
    fila.columnconfigure(1, weight=1)
    ttk.Label(fila, text="Carpeta:").grid(row=0, column=0, sticky="w")
    ruta = tk.StringVar(value=wiz.equipo_ruta)
    entrada = ttk.Entry(fila, textvariable=ruta, style="Mono.TEntry")
    entrada.grid(row=0, column=1, sticky="ew", padx=theme.E2)
    examen = ttk.Label(cuerpo, justify="left", wraplength=theme.medida(ANCHO),
                       text=MIRANDO, foreground=theme.TINTA3)
    examen.grid(row=2, column=0, sticky="w", pady=(theme.E2, 0))
    _texto(cuerpo, "Se elige ahora y no se cambia después: mover la raíz deja cada "
                   "pareja sin su carpeta, y cambiarla es volver a instalar.", 3,
           style="Pista.TLabel")

    def pendiente() -> None:
        """Deja la raíz sin fijar mientras se examina lo escrito."""
        wiz.equipo_examen = None
        wiz.state.device_root = None
        examen.configure(text=MIRANDO, foreground=theme.TINTA3)
        wiz.revisar()

    def llega(encargo) -> None:
        """Dice si la carpeta examinada vale como raíz, y la fija si vale."""
        texto = diferido.examinada[0]
        ex = encargo.resultado if encargo.error is None else _fallido(encargo)
        wiz.equipo_ruta = texto
        wiz.equipo_examen = ex
        wiz.state.device_root = Path(texto.strip()).expanduser() if ex.vale else None
        color = (theme.PELIGRO if not ex.vale else
                 theme.AVISO if ex.aviso else theme.TINTA3)
        examen.configure(text=ex.texto, foreground=color)
        wiz.revisar()

    diferido = ExamenDiferido(entrada, lambda: (ruta.get(), wiz.equipo_forma),
                              re_.examinar, pendiente, llega)

    def tecla(texto: str) -> None:
        """Apunta la carpeta tecleada y deja su examen para cuando se pare."""
        wiz.equipo_ruta = texto
        diferido.tecla()

    def examinar_carpeta() -> None:
        """Deja elegir la carpeta con el diálogo del sistema y la examina ya."""
        elegida = filedialog.askdirectory(parent=wiz.root, mustexist=False,
                                          initialdir=str(Path.home()))
        if elegida:
            ruta.set(elegida)               # `set` no valida: se examina a mano
            wiz.equipo_ruta = elegida
            pendiente()
            diferido.ya()

    boton = ttk.Button(fila, text="Examinar…", command=examinar_carpeta)
    boton.grid(row=0, column=2, sticky="e")
    if personal:
        entrada.configure(state="readonly")     # la personal es la personal
        boton.configure(state="disabled")
    al_cambiar(entrada, tecla)
    entrada.diferido = diferido              # colgado como `visor`: los tests lo miran
    wiz.equipo_examen = wiz.state.device_root = None
    diferido.ya()


def ok_carpeta(wiz) -> bool:
    """Indica si se puede seguir desde el paso de la carpeta."""
    if cifrada(wiz):
        return wiz.equipo_montada is not None
    return not con_raiz(wiz) or wiz.state.device_root is not None


def _existente(ruta: Path) -> Path:
    """Devuelve la carpeta que ya existe más cerca de `ruta`.

    Es el disco del que se pregunta el sitio libre y si admite dispersos antes
    de crear nada.
    """
    for candidata in (ruta, *ruta.parents):
        try:
            if candidata.is_dir():
                return candidata
        except OSError:
            continue
    return ruta


def _carpeta_cifrada(cuerpo, wiz) -> None:
    """Pinta el paso del contenedor.

    Dice dónde se guarda, dónde se abre y con qué contraseña. Se crea donde se
    diga (al lado de la carpeta propia, de salida), se monta en una letra fija
    (Windows) o en una carpeta vacía (Linux, `equipo_ruta`) y ESE volumen es la
    raíz. La contraseña se pide aquí para crear y montar, una vez; a partir de
    ahí abrir y cerrar es del agente, con la ventana de VeraCrypt, y nada la
    guarda.

    Las dos cajas son UN examen (`examen_contenedor`), hecho fuera del hilo de
    Tk con todo lo escrito: dónde va el contenedor, dónde se abre y la forma.
    Cualquiera de las dos lo rearma y apaga el botón en el acto, y solo crea
    un examen de lo que sigue escrito: `abrir_o_crear` no vuelve a mirar si
    la carpeta donde se monta está vacía, y lo que hubiera quedaría tapado.
    """
    import shutil
    import tkinter as tk
    from tkinter import messagebox, ttk

    from common import vestibulo
    from install import IS_WIN, crypto, raiz_equipo as re_

    from .tk import TITLE

    vc = re_.veracrypt_para_raiz()
    wiz.state.encryption = "veracrypt"
    wiz.state.veracrypt = vc
    wiz.state.device_root = wiz.equipo_montada
    if not wiz.equipo_fisica:
        wiz.equipo_fisica = str(re_.fisica_por_defecto(wiz.equipo_ruta))
    _texto(cuerpo, (
        "El contenedor: dónde se guarda el fichero cifrado, en qué letra se abre, "
        "su tamaño y la contraseña. Abierto, esa letra es la raíz." if IS_WIN else
        "El contenedor: dónde se guarda el fichero cifrado, en qué carpeta se abre, "
        "su tamaño y la contraseña. Abierto, esa carpeta es la raíz."), 0)
    formulario = ttk.Frame(cuerpo)
    formulario.grid(row=1, column=0, sticky="ew")
    formulario.columnconfigure(1, weight=1)
    ttk.Label(formulario, text="Contenedor en:").grid(row=0, column=0, sticky="w")
    fisica = tk.StringVar(value=wiz.equipo_fisica)
    caja = ttk.Entry(formulario, textvariable=fisica, style="Mono.TEntry")
    caja.grid(row=0, column=1, columnspan=2, sticky="ew", padx=theme.E2)
    examen = ttk.Label(formulario, justify="left", wraplength=theme.medida(ANCHO - 60),
                       text=MIRANDO, style="Pista.TLabel")
    examen.grid(row=1, column=0, columnspan=3, sticky="w", pady=(theme.E1, theme.E2))

    fila = 2
    letra = tk.StringVar(value=wiz.equipo_letra or re_.LETRA_PREFERIDA)
    punto = None
    if IS_WIN:
        libres = re_.letras_libres()
        if wiz.equipo_letra not in libres and libres:
            letra.set(libres[0])
        ttk.Label(formulario, text="Letra:").grid(row=fila, column=0, sticky="w")
        ttk.Combobox(formulario, textvariable=letra, state="readonly", width=4,
                     values=libres).grid(row=fila, column=1, sticky="w", padx=theme.E2)
        ttk.Label(formulario, style="Pista.TLabel", text=(
            "siempre la misma: los programas apuntarán a ella")).grid(
            row=fila, column=2, sticky="w")
    else:
        # En Linux se monta en una carpeta, que es la raíz: vacía, porque lo que
        # hubiera quedaría tapado (`examinar_contenedor`).
        ttk.Label(formulario, text="Se abre en:").grid(row=fila, column=0, sticky="w")
        # El texto va en la caja y no en una StringVar: sin nadie que la
        # retenga al salir de aquí, Python la recoge y la caja se queda vacía.
        punto = ttk.Entry(formulario, style="Mono.TEntry")
        punto.insert(0, wiz.equipo_ruta)
        punto.grid(row=fila, column=1, columnspan=2, sticky="ew", padx=theme.E2)
    fila += 1

    base = _existente(Path(wiz.equipo_fisica).expanduser())
    try:
        libre = shutil.disk_usage(str(base)).free
    except OSError:
        libre = 0
    disperso = crypto.creacion_dispersa(base, vc)
    dinamico = disperso is True
    tam = tk.StringVar(value=wiz.equipo_tamano or crypto.suggested_size(libre, dinamico))
    tam_fila = ttk.Frame(formulario)
    ttk.Label(formulario, text="Tamaño:").grid(row=fila, column=0, sticky="w")
    tam_fila.grid(row=fila, column=1, columnspan=2, sticky="w", padx=theme.E2)
    ttk.Entry(tam_fila, textvariable=tam, width=8).grid(row=0, column=0)
    ttk.Label(tam_fila, style="Pista.TLabel", text=(
        f"libre: {libre / 1024 ** 3:.1f} GiB — "
        + ("dinámico: solo ocupa lo que guardes" if dinamico else
           "con VeraCrypt 1.26.29 o posterior solo ocupa lo que guardes; con uno "
           "anterior se escribe entero al crearlo" if disperso is None else
           "se escribe entero al crearlo: elige con cabeza"))).grid(
        row=0, column=1, padx=(theme.E2, 0))
    fila += 1
    pw1, pw2 = tk.StringVar(), tk.StringVar()
    ttk.Label(formulario, text="Contraseña:").grid(row=fila, column=0, sticky="w")
    ttk.Entry(formulario, textvariable=pw1, show="•", width=32).grid(
        row=fila, column=1, columnspan=2, sticky="w", padx=theme.E2)
    fila += 1
    repite = ttk.Label(formulario, text="Repítela:")
    repite_caja = ttk.Entry(formulario, textvariable=pw2, show="•", width=32)
    repite.grid(row=fila, column=0, sticky="w")
    repite_caja.grid(row=fila, column=1, columnspan=2, sticky="w", padx=theme.E2)
    fila += 1
    pedir = tk.BooleanVar(value=wiz.equipo_pedir)
    ttk.Checkbutton(formulario, variable=pedir,
                    command=lambda: setattr(wiz, "equipo_pedir", bool(pedir.get())),
                    text="Pedir la contraseña al iniciar sesión").grid(
        row=fila, column=0, columnspan=3, sticky="w", pady=(theme.E2, 0))
    fila += 1
    ttk.Label(formulario, style="Peligro.TLabel", justify="left",
              wraplength=theme.medida(ANCHO - 60), text=(
        "La contraseña no se guarda en ningún sitio. Si la pierdes, el contenedor "
        "no se recupera: apúntala en tu gestor de contraseñas antes de seguir."
        + ("" if IS_WIN else " En Linux, VeraCrypt pide además la de "
           "administrador para montar."))).grid(
        row=fila, column=0, columnspan=3, sticky="w", pady=(theme.E2, 0))

    restos = re_.restos(wiz.equipo_ruta) if IS_WIN else []
    if restos:
        from .tk import bloque_aviso
        bloque_aviso(cuerpo, re_.aviso_restos(restos, wiz.equipo_ruta), ancho=ANCHO - 40,
                     tipo="Rojo").grid(row=2, column=0, sticky="ew", pady=(theme.E2, 0))

    botones = ttk.Frame(cuerpo)
    botones.grid(row=3, column=0, sticky="w", pady=(theme.E3, 0))
    boton = ttk.Button(botones, style="Primary.TButton", text="Crear y montar",
                       state="disabled")
    boton.grid(row=0, column=0)
    hecho = ttk.Frame(botones)
    hecho.grid(row=0, column=1, padx=(theme.E3, 0))

    def clave() -> tuple[str, str, str]:
        """Lo que se examina: dónde va el contenedor, dónde se abre y la forma."""
        return (caja.get(), punto.get() if punto is not None else wiz.equipo_ruta,
                wiz.equipo_forma)

    def pendiente() -> None:
        """Apaga el botón mientras se examina lo escrito."""
        examen.configure(text=MIRANDO, style="Pista.TLabel")
        boton.configure(state="disabled")
        wiz.revisar()

    def llega(encargo) -> None:
        """Dice si el contenedor puede ir donde se ha escrito, y enciende el botón si vale."""
        ex = encargo.resultado if encargo.error is None else _fallido(encargo)
        wiz.equipo_fisica, wiz.equipo_ruta, _ = diferido.examinada
        examen.configure(text=ex.texto, style="Peligro.TLabel" if not ex.vale
                         else "Pista.TLabel")
        existe = ex.estado == re_.YA_EQUIPO
        for w in (repite, repite_caja):
            w.grid() if not existe else w.grid_remove()
        boton.configure(text="Abrir el contenedor" if existe else "Crear y montar",
                        state="normal" if ex.vale else "disabled")
        wiz.revisar()

    diferido = ExamenDiferido(caja, clave,
                              partial(examen_contenedor, con_punto=punto is not None),
                              pendiente, llega)

    def tecla_caja(texto: str) -> None:
        """Apunta dónde va el contenedor y deja su examen para cuando se pare."""
        wiz.equipo_fisica = texto
        diferido.tecla()

    def tecla_punto(texto: str) -> None:
        """Mueve el contenedor con la carpeta mientras sea el de salida, y rearma el examen."""
        if fisica.get() == str(re_.fisica_por_defecto(wiz.equipo_ruta)):
            fisica.set(str(re_.fisica_por_defecto(texto)))   # `set` no valida
        wiz.equipo_fisica = fisica.get()
        wiz.equipo_ruta = texto
        diferido.tecla()

    def crear() -> None:
        """Comprueba la contraseña y crea o abre el contenedor, dejándolo montado.

        Solo con el examen de lo que hay escrito ahora, y si dice que vale: es
        el único que mira que la carpeta donde se monta esté vacía.
        """
        ex = diferido.vigente()
        if ex is None or not ex.vale:
            return
        examinada = diferido.examinada
        existe = ex.estado == re_.YA_EQUIPO
        password = pw1.get()
        error, aviso = (crypto.revisar_contrasena(password) if not existe
                        else (None if password else "Falta la contraseña.", None))
        if error:
            messagebox.showwarning(TITLE, error, parent=wiz.root)
            return
        if not existe and password != pw2.get():
            messagebox.showwarning(TITLE, "Las dos contraseñas no coinciden.",
                                   parent=wiz.root)
            return
        if aviso and not messagebox.askyesno(TITLE, aviso, default="no",
                                             icon="warning", parent=wiz.root):
            return
        if diferido.vigente() is not ex:
            return                   # las cajas cambiaron mientras se preguntaba
        wiz.equipo_fisica, wiz.equipo_ruta, _ = examinada
        wiz.equipo_letra = letra.get()
        wiz.equipo_tamano = tam.get()
        ok, res = working(wiz.root, "el contenedor",
                          partial(re_.abrir_o_crear, vc, wiz.equipo_fisica, wiz.equipo_ruta,
                                  wiz.equipo_letra, password, wiz.equipo_tamano),
                          ("Abriendo" if existe else "Creando y montando")
                          + " el contenedor. VeraCrypt puede pedir permisos de "
                            "administrador: acepta el aviso.")
        if not ok:
            messagebox.showerror(TITLE, str(res) or "Falló.", parent=wiz.root)
            return
        montada = Path(res)
        wiz.equipo_montada = montada
        wiz.equipo_contenedor = str(Path(wiz.equipo_fisica).expanduser()
                                    / vestibulo.CONTENEDOR)
        wiz.equipo_examen = re_.examinar(montada)
        wiz.state.device_root = montada
        wiz.state.mounted_by_us = True
        wiz.repintar()

    boton.configure(command=crear)
    if wiz.equipo_montada is not None:
        theme.chip(hecho, f"abierto en {wiz.equipo_montada}", "Ok.").grid(
            row=0, column=0)
    al_cambiar(caja, tecla_caja)
    if punto is not None:
        al_cambiar(punto, tecla_punto)
    caja.diferido = diferido                 # colgado como `visor`: los tests lo miran
    diferido.ya()


def paso_instalar(cuerpo, wiz) -> None:
    """Pinta el paso que instala el programa en la raíz y el agente en el equipo."""
    from tkinter import ttk

    from common import equipo
    from install import agente, deploy, raiz_equipo

    donde = raiz(wiz)
    ya = agente.instalado()
    fila = 0
    if donde is not None:
        _texto(cuerpo, (
            f"En {deploy.app_dir(donde)}: el programa, rclone para este equipo, la "
            f"conexión y su clave. Sin Python propio ni lanzadores: la raíz la "
            f"sincroniza el agente, con el suyo, y su ventana se abre desde el menú "
            f"del sistema («{agente.APP_NAME}»)."), fila)
        fila += 1
        if cifrada(wiz):
            _texto(cuerpo, (
                f"Todo eso va DENTRO del contenedor ({wiz.equipo_contenedor}); fuera "
                f"solo queda su marca, con el mismo id, para reconocerlo cerrado."),
                fila, style="Pista.TLabel")
        else:
            avisos = [raiz_equipo.AVISO_CLAVE]
            disco = raiz_equipo.cifrado_del_disco(donde)
            if disco:
                avisos.append(disco)
            _ambar(cuerpo, "\n\n".join(avisos), fila)
        fila += 1
    _texto(cuerpo, (
        f"El agente se queda en este equipo, fuera de toda raíz, en {equipo.DIR}: su "
        "código y su propio Python —no depende de ningún Python instalado— y su "
        "configuración. Ahí no hay claves, ni rclone.conf, ni listados."), fila)
    fila += 1
    reusar = agente.misma_version()
    if reusar:
        _texto(cuerpo, (f"El agente de esta versión ({ya.get('version', '?')}) ya está "
                        "instalado y no se reinstala: lo que elijas a continuación se le "
                        "pide por su buzón, sin pararlo."), fila, style="Pista.TLabel")
        fila += 1
    elif ya:
        _texto(cuerpo, (f"Ya hay un agente instalado (versión {ya.get('version', '?')}). "
                        "Instalar pone esta versión al lado y la deja en su sitio; su "
                        "lista de unidades se conserva."), fila, style="Pista.TLabel")
        fila += 1

    boton = ttk.Button(cuerpo, text="Instalar", style="Primary.TButton")
    boton.grid(row=fila, column=0, sticky="w")
    resultado = Resultado(cuerpo, ancho=ANCHO).grid(row=fila + 1, column=0, sticky="ew",
                                                    pady=(theme.E3, 0))

    def pintar() -> None:
        """Enseña lo que ya se ha instalado y revisa los botones del asistente."""
        lineas = []
        if donde is not None and wiz.state.deployed and wiz.equipo_id:
            lineas.append(f"Programa en {deploy.app_dir(donde)} "
                          f"(id {wiz.equipo_id[:8]}…)")
        prep = wiz.agente_prep
        if prep is not None and wiz.agente_reusado:
            lineas.append(f"El agente ya estaba: {prep.codigo}")
        elif prep is not None:
            lineas += [f"Agente en {prep.codigo}", f"Su Python: {prep.python}"]
        if prep is not None and prep.veracrypt is not None:
            lineas.append(f"Su VeraCrypt (Portable): {prep.veracrypt}")
        resultado.poner("\n".join(["Instalado"] + lineas) if lineas else "", "ok")
        wiz.revisar()

    def instalar() -> None:
        """Instala, en un hilo, lo que toque."""
        def trabajo():
            """Instala la raíz y prepara el agente, o reusa el que ya hay."""
            ident = None
            if donde is not None:
                fisica = (Path(wiz.equipo_contenedor).parent if cifrada(wiz)
                          else None)
                _, ident = raiz_equipo.instalar(donde, wiz.perfil_final,
                                                fisica=fisica)
            if reusar:
                prep = agente.instalado_prep()
                if prep is not None and cifrada(wiz):
                    prep = agente.asegurar_veracrypt(prep)
                return ident, prep
            return ident, agente.preparar(cifrada=cifrada(wiz))

        ok, res = working(wiz.root, "instalando", trabajo,
                          "Copiando el programa, rclone y el Python del agente. La "
                          "primera vez hay que descargarlos.")
        if not ok:
            resultado.poner(f"No se ha podido instalar\n{res}", "peligro")
            wiz.revisar()
            wiz.visor.ver(resultado.marco)
            return
        ident, wiz.agente_prep = res
        wiz.agente_reusado = reusar
        if ident:
            wiz.equipo_id = ident
            wiz.state.deployed = True
        pintar()

    boton.configure(command=instalar)
    pintar()


def ok_instalar(wiz) -> bool:
    """Indica si se puede seguir desde el paso de la instalación."""
    if con_raiz(wiz) and not wiz.state.deployed:
        return False
    return wiz.agente_prep is not None


def paso_parejas(cuerpo, wiz) -> None:
    """Pinta el paso de las parejas, con la ruta de cada una en ESTE equipo.

    Es como el paso «Parejas» de una unidad, más una cosa: la ruta resuelta de
    cada pareja, que se puede cambiar solo en este equipo. Con la carpeta
    personal, una ruta pensada para una unidad (`sync-data/…`) caería suelta en
    `~`; y una carpeta que ya sincroniza otro programa se dice en ámbar.

    Cada ruta se examina fuera del hilo de Tk (`ExamenDiferido`), y teclear
    solo cambia la línea de debajo: «Siguiente» depende de haber guardado, y
    guardar vuelve a revisar las elegidas en el acto, antes de escribir.
    """
    import tkinter as tk
    from tkinter import ttk

    from install import InstallError, deploy, raiz_equipo

    donde = wiz.state.device_root
    _texto(cuerpo, (
        "Qué carpetas sincroniza este equipo, y dónde cae cada una. La ruta se puede "
        "cambiar aquí sin tocar el catálogo: la pareja queda como «modificada aquí»."
        ), 0)

    tabla = ttk.Frame(cuerpo)
    tabla.grid(row=1, column=0, sticky="ew")
    tabla.columnconfigure(1, weight=1)
    elegidas: dict[str, tk.BooleanVar] = {}
    cajas: dict[str, tk.StringVar] = {}
    notas: dict[str, object] = {}

    def examinada(nombre: str, caja) -> ExamenDiferido:
        """Devuelve el examen diferido de la ruta de una pareja."""
        ruta_lbl, nota_lbl = notas[nombre]

        def pendiente() -> None:
            """Dice que se mira la ruta escrita."""
            ruta_lbl.configure(text="")
            nota_lbl.configure(text=MIRANDO, style="Pista.TLabel")
            wiz.revisar()

        def llega(encargo) -> None:
            """Dice dónde cae la ruta examinada y qué avisos tiene."""
            info = encargo.resultado
            ruta_lbl.configure(text=str(info.ruta) if info is not None and info.ruta
                               else "")
            if info is None:
                nota_lbl.configure(text=f"No se ha podido examinar: {encargo.error}",
                                   style="Peligro.TLabel")
            elif info.error:
                nota_lbl.configure(text=info.error, style="Peligro.TLabel")
            else:
                nota_lbl.configure(text="; ".join(info.avisos), style="Aviso.TLabel")
            wiz.revisar()

        diferido = ExamenDiferido(caja, lambda: (caja.get(),),
                                  partial(raiz_equipo.revisar_local, donde),
                                  pendiente, llega)

        def tecla(texto: str) -> None:
            """Apunta la ruta tecleada y deja su examen para cuando se pare."""
            wiz.equipo_locales[nombre] = texto
            diferido.tecla()

        al_cambiar(caja, tecla)
        caja.diferido = diferido             # colgado como `visor`: los tests lo miran
        return diferido

    fila = 0
    for pareja in wiz.catalog.pairs:
        nombre = pareja.get("name", "")
        modo = pareja.get("mode", "bisync")
        var = tk.BooleanVar(value=nombre in wiz.state.selected or not wiz.state.selected)
        elegidas[nombre] = var
        ttk.Checkbutton(tabla, variable=var, text=f"{nombre}   [{modo}]").grid(
            row=fila, column=0, sticky="w", padx=(0, theme.E3))
        cajas[nombre] = tk.StringVar(
            value=wiz.equipo_locales.get(nombre, str(pareja.get("local", ""))))
        caja = ttk.Entry(tabla, textvariable=cajas[nombre], style="Mono.TEntry",
                         width=30)
        caja.grid(row=fila, column=1, sticky="ew")
        ttk.Label(tabla, style="Pista.TLabel",
                  text=f"↔  {pareja.get('remote_path', '?')}").grid(
            row=fila, column=2, sticky="w", padx=(theme.E3, 0))
        debajo = ttk.Frame(tabla)
        debajo.grid(row=fila + 1, column=1, columnspan=2, sticky="w", pady=(0, theme.E2))
        notas[nombre] = (
            ttk.Label(debajo, style="MonoPista.TLabel"),
            ttk.Label(debajo, style="Pista.TLabel", justify="left", text=MIRANDO,
                      wraplength=theme.medida(560)))
        notas[nombre][0].grid(row=0, column=0, sticky="w")
        notas[nombre][1].grid(row=1, column=0, sticky="w")
        if modo in ("up-mirror", "down-mirror"):
            destino = "el remoto" if modo == "up-mirror" else "este equipo"
            ttk.Label(tabla, style="Peligro.TLabel",
                      text=f"espejo: borra en {destino}").grid(
                row=fila + 1, column=0, sticky="nw")
        wiz.equipo_locales[nombre] = cajas[nombre].get()
        examinada(nombre, caja).ya()
        fila += 2

    resultado = Resultado(cuerpo, ancho=ANCHO).grid(row=3, column=0, sticky="ew",
                                                    pady=(theme.E3, 0))

    def guardar() -> None:
        """Escribe el config con las parejas elegidas y crea sus carpetas."""
        seleccion = [n for n, v in elegidas.items() if v.get()]
        malas = [n for n in seleccion
                 if raiz_equipo.revisar_local(donde, cajas[n].get()).error]
        if malas:
            resultado.poner("Arregla antes la ruta de: " + ", ".join(malas), "peligro")
            return
        locales = {n: raiz_equipo.revisar_local(donde, cajas[n].get()).local
                   for n in seleccion}
        try:
            destino = deploy.write_device_config(
                donde, wiz.catalog, seleccion, endpoint=wiz.perfil.endpoint_catalog,
                catalog_path=wiz.perfil.catalog_path, locales=locales)
            creadas = deploy.make_local_dirs(donde, wiz.catalog, seleccion, locales)
        except InstallError as e:
            wiz.error(str(e))
            return
        except Exception as e:                       # noqa: BLE001
            wiz.error(f"{type(e).__name__}: {e}")
            return
        wiz.state.selected = seleccion
        wiz.state.config_written = True
        # Un `rclone` de hasta 45 s contra el remoto: con su barra, y de mejor
        # esfuerzo (lo que no llegue se apunta al sincronizar).
        ok, nota = working(wiz.root, "flota",
                           partial(deploy.publish_fleet_note, wiz.rclone, donde,
                                   wiz.perfil.endpoint_catalog),
                           "Apuntando este equipo en la flota del remoto.")
        nota = nota if ok else None
        detalle = f"Escrito {destino} con {len(seleccion)} pareja(s)\n"
        if creadas:
            detalle += "Carpetas creadas: " + ", ".join(str(p) for p in creadas) + ". "
        detalle += ("Apuntado en la flota: " + nota + "." if nota else
                    "No se ha podido apuntar en la flota; se hará al sincronizar.")
        resultado.poner(detalle, "ok")
        wiz.revisar()

    ttk.Button(cuerpo, text="Guardar el config y crear las carpetas",
               style="Primary.TButton", command=guardar).grid(
        row=2, column=0, sticky="w", pady=(theme.E3, 0))


def ok_parejas(wiz) -> bool:
    """Indica si se puede seguir desde el paso de las parejas."""
    return wiz.state.config_written


def paso_unidades(cuerpo, wiz) -> None:
    """Pinta el paso que elige qué unidades atiende el agente y cómo."""
    import tkinter as tk
    from tkinter import ttk

    from common import equipo
    from install import agente, raiz_equipo

    _texto(cuerpo, (
        "Qué unidades atiende el agente, y qué hace con cada una al enchufarla. "
        "Aquí salen las que se saben sin red —la que vigilaba penwatch en este "
        "equipo, las enchufadas ahora y las que el agente ya tenga— y, con "
        "conexión, las de la flota. Cualquier otra se pregunta la primera vez que "
        "se enchufe: nunca se sincroniza una unidad sin preguntar."), 0)

    if wiz.agente_unidades is None:
        ofrecidas = agente.candidatas()
        wiz.agente_unidades = {c.id: (c.modo, c.nombre) for c in ofrecidas}
        wiz.agente_origen = {c.id: c.origen for c in ofrecidas}

    tabla = ttk.Frame(cuerpo)
    tabla.grid(row=1, column=0, sticky="w")
    if not wiz.agente_unidades:
        ttk.Label(tabla, style="Pista.TLabel", text=(
            "Ninguna todavía. Enchufa una unidad prdrive y el agente preguntará si "
            "atenderla.")).grid(row=0, column=0, sticky="w")
    else:
        for col, rotulo in enumerate(("Unidad", "Qué hacer al enchufarla", "")):
            ttk.Label(tabla, text=theme.rotulo(rotulo), style="Rotulo.TLabel").grid(
                row=0, column=col, sticky="w", padx=(0, theme.E4))
    etiquetas = {m: equipo.TEXTO_MODO[m] for m in equipo.MODOS}
    etiquetas[PREGUNTAR] = TEXTO_PREGUNTAR
    por_texto = {v: k for k, v in etiquetas.items()}
    for i, (uid, (modo, nombre)) in enumerate(sorted(wiz.agente_unidades.items()),
                                              start=1):
        ttk.Label(tabla, text=nombre or f"{uid[:8]}…").grid(
            row=i, column=0, sticky="w", padx=(0, theme.E4), pady=theme.E1)
        var = tk.StringVar(value=etiquetas[modo])

        def cambiar(_evento=None, u=uid, v=var, n=nombre) -> None:
            """Apunta el modo elegido para una unidad."""
            wiz.agente_unidades[u] = (por_texto[v.get()], n)

        caja = ttk.Combobox(tabla, textvariable=var, state="readonly",
                            values=[etiquetas[m] for m in (*equipo.MODOS, PREGUNTAR)],
                            width=30)
        caja.bind("<<ComboboxSelected>>", cambiar)
        caja.grid(row=i, column=1, sticky="w", padx=(0, theme.E4), pady=theme.E1)
        ttk.Label(tabla, text=wiz.agente_origen.get(uid, ""), style="Pista.TLabel").grid(
            row=i, column=2, sticky="w", pady=theme.E1)

    if wiz.rclone is not None and con_raiz(wiz):
        def de_la_flota() -> None:
            """Añade, para preguntar al enchufarlas, las unidades que anota la flota."""
            ok, flota = working(wiz.root, "leyendo la flota",
                                lambda: raiz_equipo.de_la_flota(
                                    wiz.rclone, wiz.perfil.endpoint_catalog),
                                "Leyendo las notas de la flota en el remoto.")
            if not ok:
                wiz.error(str(flota))
                return
            for disp in flota:
                if disp.id not in wiz.agente_unidades and disp.id != wiz.equipo_id:
                    wiz.agente_unidades[disp.id] = (PREGUNTAR, disp.nombre)
                    wiz.agente_origen[disp.id] = "en la flota"
            wiz.repintar()

        ttk.Button(cuerpo, text="Añadir las de la flota", command=de_la_flota).grid(
            row=2, column=0, sticky="w", pady=(theme.E3, 0))

    plazo = ttk.Frame(cuerpo)
    plazo.grid(row=3, column=0, sticky="w", pady=(theme.E4, 0))
    ttk.Label(plazo, text="Para contestar a una unidad nueva:").grid(row=0, column=0,
                                                                     sticky="w")
    segundos = tk.StringVar(value=f"{wiz.agente_espera:g}")

    def cambiar_plazo(*_) -> None:
        """Apunta el plazo para contestar a una unidad nueva, acotado."""
        try:
            valor = float(segundos.get())
        except ValueError:
            return
        wiz.agente_espera = min(max(valor, equipo.ESPERA_MINIMA), equipo.ESPERA_MAXIMA)

    # Por los eventos de la caja y no con un `trace` de la variable: el comando
    # Tcl de un trace no muere con el widget (ver `docs/agents/reference/ui.md`,
    # la ventana principal).
    caja_plazo = ttk.Spinbox(plazo, textvariable=segundos, from_=equipo.ESPERA_MINIMA,
                             to=equipo.ESPERA_MAXIMA, increment=30, width=6,
                             command=cambiar_plazo)
    caja_plazo.grid(row=0, column=1, padx=theme.E2)
    caja_plazo.bind("<KeyRelease>", cambiar_plazo)
    caja_plazo.bind("<FocusOut>", cambiar_plazo)
    ttk.Label(plazo, text="segundos. Sin respuesta, cuenta como «Ahora no» hasta "
                          "que se vuelva a enchufar.", style="Pista.TLabel").grid(
        row=0, column=2, sticky="w")


def elegidas(wiz) -> dict[str, tuple[str, str]]:
    """Devuelve las unidades que entran en la lista del agente.

    No entran las de «preguntar».
    """
    return {uid: (modo, nombre) for uid, (modo, nombre)
            in (wiz.agente_unidades or {}).items() if modo != PREGUNTAR}


def la_raiz(wiz):
    """Devuelve la raíz de este equipo como entrada de la lista del agente, o `None`."""
    from common import equipo
    from install import raiz_equipo
    donde = raiz(wiz)
    if donde is None or not wiz.equipo_id:
        return None
    return equipo.Unidad(wiz.equipo_id, equipo.DAEMON, raiz_equipo.nombre(donde),
                         str(donde), wiz.equipo_contenedor if cifrada(wiz) else "")


def paso_arranque(cuerpo, wiz) -> None:
    """Pinta el paso que registra y arranca el agente."""
    from tkinter import ttk

    import penwatch
    from install import agente

    como = ("una tarea programada de tu usuario, que arranca al iniciar sesión"
            if agente.IS_WIN else
            "un autostart del escritorio (~/.config/autostart), porque los avisos y "
            "la pregunta por una unidad nueva necesitan la sesión gráfica")
    if wiz.agente_reusado:
        _texto(cuerpo, "El agente ya está registrado y en su sitio: no se toca. Lo "
                       "elegido se le pide por su buzón y lo aplica él, sin pararse "
                       "(si no está en marcha, se arranca).", 0)
    else:
        _texto(cuerpo, f"El agente se registra con {como}, y se arranca ya. Sin "
                       "administrador."
               + ("" if agente.IS_WIN else
                  f" Su icono va en la bandeja; donde no la hay, hace sus veces el "
                  f"acceso «{agente.APP_NAME}» del menú."), 0)
    if raiz(wiz) is not None:
        _texto(cuerpo, (
            f"Sincroniza {raiz(wiz)} en segundo plano, con las parejas y el intervalo "
            f"de su servicio, y deja en el menú del sistema un acceso «{agente.APP_NAME}» "
            "que abre su ventana."
            + (" El contenedor se queda abierto: el agente lo recibe así, y "
               + ("pedirá la contraseña al iniciar sesión." if wiz.equipo_pedir else
                  "no pedirá nada al iniciar sesión («python agente.py desbloquear» "
                  "lo abre).") + " Para cerrarlo, «Bloquear» en su ventana."
               if cifrada(wiz) else "")), 1)
    if penwatch.CONFIG_FILE.exists():
        _texto(cuerpo, (
            "penwatch está instalado en este equipo. El agente lo sustituye: lo que "
            "vigilaba ya está en su lista, y penwatch se desinstala al registrar el "
            "agente. Dos vigilantes a la vez se pisarían."), 2, style="Aviso.TLabel")
    _texto(cuerpo, (
        "Un cambio respecto a penwatch: con el agente, abrir la ventana de una "
        "unidad ya no apaga su servicio para siempre, lo pausa mientras está "
        "abierta. Para pararlo: «python agente.py pausa», o el modo «nada» de esa "
        "unidad."), 3, style="Pista.TLabel")

    resultado = Resultado(cuerpo, ancho=ANCHO).grid(row=5, column=0, sticky="ew",
                                                    pady=(theme.E3, 0))

    def activar() -> None:
        """Registra el agente o se lo pide por su buzón, y cuenta qué ha hecho."""
        pedir = wiz.equipo_pedir if cifrada(wiz) else None
        if wiz.agente_reusado:
            ok, msgs = working(wiz.root, "pidiéndoselo al agente",
                               lambda: agente.anadir(elegidas(wiz), wiz.agente_espera,
                                                     raiz=la_raiz(wiz),
                                                     pedir_al_iniciar=pedir),
                               "Dejándole lo elegido en su buzón.")
        else:
            # Si el agente de antes tiene una pasada en marcha, se espera a que
            # acabe (`parar_agente()`), y eso se dice debajo de la barra.
            avance: list = []
            ok, msgs = working(wiz.root, "registrando el agente",
                               lambda: agente.activar(
                                   wiz.agente_prep, elegidas(wiz), wiz.agente_espera,
                                   raiz=la_raiz(wiz), pedir_al_iniciar=pedir,
                                   avance=lambda f, t: avance.append((f, t))),
                               "Registrando el agente y arrancándolo.",
                               progreso=lambda: avance[-1] if avance else None)
        if not ok:
            resultado.poner(f"No se ha podido\n{msgs}", "peligro")
            wiz.revisar()
            wiz.visor.ver(resultado.marco)
            return
        wiz.agente_hecho = list(msgs)
        resultado.poner("\n".join(["Hecho"] + list(msgs)), "ok")
        wiz.revisar()

    ttk.Button(cuerpo, text="Pedírselo al agente" if wiz.agente_reusado
               else "Registrar y arrancar", style="Primary.TButton",
               command=activar).grid(row=4, column=0, sticky="w")
    if wiz.agente_hecho:
        resultado.poner("\n".join(["Hecho"] + list(wiz.agente_hecho)), "ok")


def ok_arranque(wiz) -> bool:
    """Indica si se puede seguir desde el paso del arranque."""
    return bool(wiz.agente_hecho)


def comprobaciones(donde: Path | None = None, esperadas: list[str] | None = None,
                   clave: str | None = None, contenedor: str | None = None,
                   carpeta_clara: str | None = None) -> list[tuple[str, bool, str]]:
    """Devuelve `(qué, bien, detalle)` de lo que quedó puesto; lo mira el test, sin Tk.

    Con `donde`, primero la raíz de este equipo: lo que
    `device.verify_device()` pide a cualquier raíz y que esté en la lista del
    agente con esa ruta.
    """
    import penwatch
    from common import equipo
    from install import agente, device, raiz_equipo

    filas = []
    if donde is not None:
        for chk in raiz_equipo.verificar(donde, esperadas, clave, contenedor):
            filas.append((chk.etiqueta, chk.ok, chk.detalle))
        if contenedor and carpeta_clara:
            # Pasar a cifrado deja la raíz en claro donde estaba, con la clave:
            # fila roja, y nada la borra.
            from install import crypto
            for chk in crypto.comprobar_restos(carpeta_clara):
                filas.append((chk.etiqueta, chk.ok, chk.detalle))
        uid = device.control_id(donde)
        en_lista = equipo.leer_ajustes().unidades.get(uid or "")
        pedida = en_lista is None and agente.raiz_pedida(uid)
        filas.append(("En la lista del agente",
                      bool(en_lista and en_lista.ruta == str(donde)
                           and en_lista.contenedor == (contenedor or "")) or pedida,
                      f"raíz de este equipo, modo {en_lista.modo}"
                      + (", cifrada" if en_lista.cifrada else "") if en_lista else
                      "pedido: el agente la añade al leer su buzón" if pedida else
                      "no está: registra y arranca el agente"))
    if agente.quiere_menu(donde is not None):
        menu = agente.acceso_menu()
        filas.append(("Acceso del menú", menu.exists(), str(menu) if menu.exists()
                      else "no está: «agente.py abrir» hace lo mismo"))
    inst = agente.instalado()
    filas.append(("Agente instalado", inst is not None,
                  f"versión {inst.get('version')}, en {inst.get('codigo')}" if inst
                  else "no hay instalacion.json con código"))
    if inst:
        filas.append(("Su Python", _existe(inst.get("python")), str(inst.get("python"))))
    if agente.IS_WIN:
        res = watch.consulta(["schtasks", "/Query", "/TN", agente.TAREA])
        registro = res.returncode == 0
        sin_decir = ("el sistema no contesta" if res.returncode == watch.CODIGO_TIEMPO
                     else "no está registrado")
    else:
        registro, sin_decir = agente.autostart_file().is_file(), "no está registrado"
    filas.append(("Arranca al iniciar sesión", registro,
                  "registrado" if registro else sin_decir))
    vivo = equipo.agente_vivo()
    filas.append(("En marcha", vivo is not None,
                  f"pid {vivo.get('pid')}" if vivo else
                  "todavía no: puede tardar unos segundos en arrancar"))
    unidades = [u for u in equipo.leer_ajustes().unidades.values() if not u.es_raiz]
    filas.append(("Unidades en su lista", True,
                  ", ".join(u.nombre or u.id[:8] for u in unidades)
                  or "ninguna: preguntará por cada una al enchufarla"))
    filas.append(("penwatch", not penwatch.CONFIG_FILE.exists(),
                  "no está instalado: el agente hace su trabajo"
                  if not penwatch.CONFIG_FILE.exists()
                  else "sigue instalado: dos vigilantes se pisarían"))
    if not agente.IS_WIN:
        avisos, hay_bandeja = escritorio()
        filas.append(("Avisos del escritorio", avisos is not False,
                      {True: "el escritorio los enseña",
                       None: "no se ha podido preguntar al bus de sesión",
                       False: "nadie atiende org.freedesktop.Notifications: los avisos "
                              "quedarán solo en el diario"}[avisos]))
        filas.append(("Bandeja", hay_bandeja is not False,
                      {True: "el icono del agente va en la bandeja del escritorio",
                       None: "no se ha podido preguntar al bus de sesión",
                       False: SIN_BANDEJA}[hay_bandeja]))
    return filas


EXTENSION_GNOME = "AppIndicator and KStatusNotifierItem Support"
"""La extensión que pone la bandeja en GNOME (sección 5 del diseño)."""
SIN_BANDEJA = (f"este escritorio no tiene bandeja. En GNOME la pone la extensión "
               f"«{EXTENSION_GNOME}» (Ubuntu ya la trae); mientras, el acceso «prdrive» "
               f"del menú de aplicaciones hace sus veces")
"""Lo que dice «Verificación» en un escritorio sin StatusNotifierWatcher."""


def _existe(ruta) -> bool:
    """Indica si hay un fichero en esa ruta."""
    try:
        return bool(ruta) and Path(ruta).is_file()
    except OSError:
        return False


def escritorio() -> tuple[bool | None, bool | None]:
    """Devuelve si hay avisos y si hay bandeja en el bus de sesión.

    Pregunta quién atiende `org.freedesktop.Notifications` y
    `org.kde.StatusNotifierWatcher`; `None` es lo que no se ha podido
    preguntar. Es un punto de indirección para los tests.
    """
    try:
        from common import avisos, dbus
        from ui import bandeja_linux
        with dbus.Conexion.sesion() as bus:
            return (bus.tiene_dueno(avisos.NOTIFICACIONES),
                    bandeja_linux.hay_bandeja(bus))
    except Exception:                                   # noqa: BLE001
        return None, None


def paso_final(cuerpo, wiz) -> None:
    """Pinta el paso de verificación: lo que ha quedado puesto en este equipo.

    Se pinta primero y comprueba después: `comprobaciones()` pregunta al
    sistema (`schtasks`, el bus de sesión) y lee la raíz, así que va en otro
    hilo, con un indicador mientras y «Volver a comprobar» apagado. La tabla
    aparece cuando llega.
    """
    from tkinter import ttk

    _texto(cuerpo, "Lo que ha quedado puesto en este equipo.", 0)
    tabla = ttk.Frame(cuerpo)
    tabla.grid(row=1, column=0, sticky="ew")
    tabla.columnconfigure(0, weight=1)
    # El indicador va debajo de donde irá la tabla: mientras comprueba no hay
    # tabla, y cuando la hay la línea ya no está.
    indicador = Indicador(tabla, ancho=ANCHO)
    indicador.marco.grid(row=1, column=0, sticky="w")
    sondeo = Sondeo(tabla)
    hecha: list = []

    def llega(encargo) -> None:
        """Pinta la tabla de lo comprobado, o dice por qué no se ha podido."""
        otra_vez.configure(state="normal")
        if encargo.error is not None:
            indicador.poner(f"No se ha podido comprobar: {encargo.error}", False,
                            "Aviso.")
        else:
            indicador.poner("", False)
            hecha.append(tabla_estado(tabla, list(encargo.resultado),
                                      ("está", "falta", "sin mirar", "aviso"),
                                      ancho_nombre=200))
            hecha[-1].grid(row=0, column=0, sticky="ew")
        wiz.revisar()

    def revisar() -> None:
        """Vuelve a comprobar, en otro hilo."""
        while hecha:
            hecha.pop().destroy()
        otra_vez.configure(state="disabled")
        indicador.poner("Comprobando lo instalado…", True)
        perfil = wiz.perfil_final
        clave = perfil.key_name if con_raiz(wiz) and perfil.needs_key else None
        encargo = segundo_plano.lanzar(partial(
            comprobaciones, raiz(wiz), list(wiz.state.selected), clave,
            wiz.equipo_contenedor if cifrada(wiz) else None,
            wiz.equipo_ruta if cifrada(wiz) else None))
        sondeo.esperar(encargo, llega)

    otra_vez = ttk.Button(cuerpo, text="Volver a comprobar", command=revisar)
    theme.boton_icono(otra_vez, "reload", theme.TINTA2)
    otra_vez.grid(row=2, column=0, sticky="w", pady=(theme.E4, 0))
    revisar()
