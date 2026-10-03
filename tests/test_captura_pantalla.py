#!/usr/bin/env python3
"""La ventana de emparejar no sale en capturas de pantalla (#59), sin Windows.

`tk.proteger_de_capturas()` habla con Windows por una sola llamada,
`_afinidad_de_pantalla()`, y de la ventana solo pide cuatro cosas
(`update_idletasks`, `wm_frame`, `winfo_id`). Aquí se le ponen unas de mentira,
y se comprueba:
- Que fuera de Windows no hace nada y devuelve «sin protección».
- Que prueba primero `WDA_EXCLUDEFROMCAPTURE` (0x11), luego `WDA_MONITOR` (0x1),
  y que si Windows no admite ninguna sigue sin protección: nunca lanza.
- Que el manejador es el del envoltorio de Tk (`wm frame`), no el de la ventana
  propia (`winfo_id()`): en Windows el envoltorio no existe hasta el primer
  reposo del bucle, así que antes hay un `update_idletasks()`, y si aun así no
  está, no se protege nada en vez de proteger la ventana equivocada.
- Que la llamada real a user32 (`_afinidad_de_pantalla`) declara sus tipos y
  pasa lo que debe, contra un `ctypes.WinDLL` de mentira.
- Que `tk_qr.open_dialog()` protege ANTES de `mostrar()`, con la ventana todavía
  retirada, y que la línea que enseña depende de lo que se haya conseguido.

Lo que solo se puede ver en Windows (que `wm frame` dé el envoltorio con la
ventana retirada, y que las capturas de verdad no la recojan) está en
`docs/superpowers/pruebas/2026-10-02-captura-qr-pendiente-en-real.md`.
"""

import ctypes
import sys

from _harness import Checks

from ui import tk as uitk

c = Checks("la ventana de emparejar no sale en capturas")

HIJA = 0x1000
ENVOLTORIO = 0x2000


class VentanaFalsa:
    """Un `Toplevel` de Tk en Windows, de mentira.

    Hasta que no llega el primer reposo (`update_idletasks()`) no hay
    envoltorio, y `wm frame` devuelve la ventana propia, la misma que
    `winfo_id()`: es lo que hace `WmFrameCmd` en `win/tkWinWm.c`.

    Attributes:
        llamadas: Lo que se le ha pedido, en orden.
        envoltorio: Si el envoltorio ya existe.
        crea: Si `update_idletasks()` llega a crearlo.
        roto: Si todo lo que se le pida lanza, como una ventana destruida.
    """

    def __init__(self, crea: bool = True, roto: bool = False):
        """Prepara la ventana, con o sin envoltorio tras el primer reposo."""
        self.llamadas: list = []
        self.envoltorio = False
        self.crea = crea
        self.roto = roto

    def update_idletasks(self):
        """Corre el reposo: crea el envoltorio, oculto."""
        self.llamadas.append("update_idletasks")
        if self.roto:
            raise RuntimeError("la ventana ya no existe")
        self.envoltorio = self.crea

    def wm_frame(self):
        """Devuelve el manejador como lo escribe Tk: «0x…»."""
        self.llamadas.append("wm_frame")
        if self.roto:
            raise RuntimeError("la ventana ya no existe")
        return hex(ENVOLTORIO if self.envoltorio else HIJA)

    def winfo_id(self):
        """Devuelve la ventana propia de Tk, que es la hija del envoltorio."""
        self.llamadas.append("winfo_id")
        return HIJA


class Afinidad:
    """Un `SetWindowDisplayAffinity` de mentira.

    Attributes:
        acepta: Los valores que «admite» esta versión de Windows.
        pedidas: Lo que se le ha pedido, como `(hwnd, valor)`.
        lanza: Si debe lanzar `OSError` (con qué valores), en vez de contestar.
    """

    def __init__(self, acepta=(), lanza=()):
        """Prepara qué valores admite y cuáles hacen saltar una excepción."""
        self.acepta = set(acepta)
        self.lanza = set(lanza)
        self.pedidas: list = []

    def __call__(self, hwnd, valor):
        """Apunta la petición y contesta como Windows."""
        self.pedidas.append((hwnd, valor))
        if valor in self.lanza:
            raise OSError("user32 no responde")
        return valor in self.acepta


def proteger(ventana, afinidad: Afinidad, es_win: bool = True):
    """Llama a `proteger_de_capturas()` con Windows de mentira y deja todo como estaba."""
    previo = (uitk.IS_WIN, uitk._afinidad_de_pantalla)
    uitk.IS_WIN, uitk._afinidad_de_pantalla = es_win, afinidad
    try:
        return uitk.proteger_de_capturas(ventana)
    finally:
        uitk.IS_WIN, uitk._afinidad_de_pantalla = previo


# 1. los valores son los de Windows, y «ninguna» es falsa
c("sin protección es 0 (WDA_NONE)", uitk.CAPTURA_NINGUNA, 0x0)
c("en negro es 0x1 (WDA_MONITOR)", uitk.CAPTURA_EN_NEGRO, 0x1)
c("excluida es 0x11 (WDA_EXCLUDEFROMCAPTURE)", uitk.CAPTURA_EXCLUIDA, 0x11)
c("solo «ninguna» es falsa: vale de booleano",
  [bool(v) for v in (uitk.CAPTURA_NINGUNA, uitk.CAPTURA_EN_NEGRO,
                     uitk.CAPTURA_EXCLUIDA)], [False, True, True])


# 2. fuera de Windows no hace nada
ventana, afinidad = VentanaFalsa(), Afinidad(acepta=(0x11, 0x1))
c("fuera de Windows: sin protección",
  proteger(ventana, afinidad, es_win=False), uitk.CAPTURA_NINGUNA)
c("  no toca la ventana", ventana.llamadas, [])
c("  ni llama a user32", afinidad.pedidas, [])


# 3. Windows reciente: se queda con la primera
ventana, afinidad = VentanaFalsa(), Afinidad(acepta=(0x11, 0x1))
c("Windows 10 2004 o posterior: excluida de la captura",
  proteger(ventana, afinidad), uitk.CAPTURA_EXCLUIDA)
c("  y no sigue probando: una sola llamada, con 0x11",
  [v for _, v in afinidad.pedidas], [0x11])


# 4. Windows anterior: cae a WDA_MONITOR
ventana, afinidad = VentanaFalsa(), Afinidad(acepta=(0x1,))
c("Windows anterior: la ventana sale en negro",
  proteger(ventana, afinidad), uitk.CAPTURA_EN_NEGRO)
c("  probó 0x11 primero y 0x1 después, por ese orden",
  [v for _, v in afinidad.pedidas], [0x11, 0x1])


# 5. ninguna: sigue sin protección y no lanza
ventana, afinidad = VentanaFalsa(), Afinidad(acepta=())
c("si Windows no admite ninguna: sin protección",
  proteger(ventana, afinidad), uitk.CAPTURA_NINGUNA)
c("  y se intentaron las dos", [v for _, v in afinidad.pedidas], [0x11, 0x1])
c("  que es falso para quien solo mira si quedó protegida",
  bool(proteger(VentanaFalsa(), Afinidad())), False)

ventana, afinidad = VentanaFalsa(), Afinidad(lanza=(0x11, 0x1))
c("si user32 lanza en las dos: sin protección, y sin excepción",
  proteger(ventana, afinidad), uitk.CAPTURA_NINGUNA)
ventana, afinidad = VentanaFalsa(), Afinidad(acepta=(0x1,), lanza=(0x11,))
c("si lanza solo en la primera, se prueba la otra",
  proteger(ventana, afinidad), uitk.CAPTURA_EN_NEGRO)


# 6. el manejador: el del envoltorio, y solo cuando existe
ventana, afinidad = VentanaFalsa(), Afinidad(acepta=(0x11,))
proteger(ventana, afinidad)
c("la afinidad se pone en el envoltorio (`wm frame`), no en la ventana propia",
  afinidad.pedidas, [(ENVOLTORIO, 0x11)])
c("  y antes de pedir `wm frame` hay un `update_idletasks()` (sin él, `wm "
  "frame` da la ventana propia)",
  ventana.llamadas.index("update_idletasks") < ventana.llamadas.index("wm_frame"),
  True)

ventana, afinidad = VentanaFalsa(crea=False), Afinidad(acepta=(0x11, 0x1))
c("si el envoltorio sigue sin existir (`wm frame` == `winfo_id`): sin "
  "protección",
  proteger(ventana, afinidad), uitk.CAPTURA_NINGUNA)
c("  y no se llama a user32: protegería la ventana que Tk va a meter dentro "
  "del envoltorio, y se daría por protegida", afinidad.pedidas, [])


# 7. una ventana que ya no existe, o un manejador que no es un número
ventana, afinidad = VentanaFalsa(roto=True), Afinidad(acepta=(0x11,))
c("una ventana destruida no lanza: sin protección",
  proteger(ventana, afinidad), uitk.CAPTURA_NINGUNA)
c("  y no llega a user32", afinidad.pedidas, [])


class SinNumero(VentanaFalsa):
    """Una ventana cuyo `wm frame` no es un número."""

    def wm_frame(self):
        """Devuelve algo que no es un manejador."""
        return "no es un hex"


c("un manejador ilegible tampoco lanza",
  proteger(SinNumero(), Afinidad(acepta=(0x11,))), uitk.CAPTURA_NINGUNA)


# 8. la llamada real a user32, contra un `WinDLL` de mentira
#
# `ctypes.WinDLL` solo existe en Windows; se le pone uno que apunta cómo se
# declara y se llama `SetWindowDisplayAffinity`. Lo que no se puede ver es que
# Windows la acepte de verdad: eso va en la lista de pruebas en real.
class FuncionFalsa:
    """`SetWindowDisplayAffinity` según ctypes: tipos declarados y una llamada."""

    def __init__(self, devuelve: int):
        """Apunta qué contestará, y empieza sin tipos declarados."""
        self.devuelve = devuelve
        self.argtypes = None
        self.restype = None
        self.recibido: list = []

    def __call__(self, *args):
        """Apunta los argumentos y contesta lo que se le dijo."""
        self.recibido.append(args)
        return self.devuelve


class DllFalsa:
    """Lo que devuelve `ctypes.WinDLL("user32")`."""

    abiertas: list = []
    funcion: FuncionFalsa = FuncionFalsa(1)

    def __init__(self, nombre, **opciones):
        """Apunta qué biblioteca se abrió y con qué opciones."""
        DllFalsa.abiertas.append((nombre, opciones))

    @property
    def SetWindowDisplayAffinity(self):                         # noqa: N802
        """La función de user32, con sus tipos por declarar."""
        return DllFalsa.funcion


tenia_windll = hasattr(ctypes, "WinDLL")
windll_real = getattr(ctypes, "WinDLL", None)
ctypes.WinDLL = DllFalsa
try:
    from ctypes import wintypes

    for devuelve, esperado in ((1, True), (0, False)):
        DllFalsa.abiertas, DllFalsa.funcion = [], FuncionFalsa(devuelve)
        c(f"user32 contesta {devuelve}: la llamada real dice {esperado}",
          uitk._afinidad_de_pantalla(0xABCDEF, 0x11), esperado)
    c("abre user32", [n for n, _ in DllFalsa.abiertas], ["user32"])
    c("  con use_last_error, como el resto del proyecto",
      DllFalsa.abiertas[0][1], {"use_last_error": True})
    c("declara (HWND, DWORD) -> BOOL: sin eso un manejador de 64 bits se "
      "trunca", (DllFalsa.funcion.argtypes, DllFalsa.funcion.restype),
      ([wintypes.HWND, wintypes.DWORD], wintypes.BOOL))
    c("pasa el manejador y la afinidad tal cual",
      DllFalsa.funcion.recibido, [(0xABCDEF, 0x11)])
finally:
    if tenia_windll:
        ctypes.WinDLL = windll_real
    else:
        del ctypes.WinDLL


# 9. la ventana de emparejar
try:
    import tkinter as tk
    from tkinter import ttk
    raiz = tk.Tk()
    raiz.withdraw()
except Exception as e:                                   # sin entorno gráfico
    print(f"  (saltado) no hay entorno gráfico: {e}")
    sys.exit(c.report())

from common import pairing  # noqa: E402
from common.model import ConfigError  # noqa: E402
from ui import tk_qr  # noqa: E402

# La carga de una clave ed25519 de verdad, como en `test_tk_medidas`: nada de
# esto toca el rclone.conf de nadie.
construir_real = pairing.construir
pairing.construir = lambda raw=None, app_dir=None: pairing.dumps(
    "nas", {"type": "sftp", "host": "nas.example.org", "port": "22",
            "user": "pere"},
    key_name="id_ed25519", catalog_path="/prdrive-catalog/pairs.toml",
    private_key=(b"-----BEGIN OPENSSH PRIVATE KEY-----\n" + b"b3BlbnNza" * 40
                 + b"\n-----END OPENSSH PRIVATE KEY-----\n"))

proteger_real, mostrar_real = tk_qr.proteger_de_capturas, tk_qr.mostrar
matriz_real = tk_qr.icons.matriz


def textos(widget) -> list[str]:
    """Devuelve el texto de todas las etiquetas bajo `widget`."""
    hallados = []
    pila = [widget]
    while pila:
        w = pila.pop()
        pila += list(w.winfo_children())
        if isinstance(w, ttk.Label) and str(w.cget("text")):
            hallados.append(str(w.cget("text")))
    return hallados


def buscar(widget, estilo: str) -> list:
    """Devuelve los widgets bajo `widget` con ese estilo de ttk."""
    hallados = []
    pila = [widget]
    while pila:
        w = pila.pop()
        pila += list(w.winfo_children())
        if isinstance(w, ttk.Widget) and str(w.cget("style")) == estilo:
            hallados.append(w)
    return hallados


def abrir(resultado=None, protector=True):
    """Abre la ventana con `proteger_de_capturas` y `mostrar` apuntando.

    Args:
        resultado: Lo que «consigue» la protección.
        protector: Si se sustituye `proteger_de_capturas` (con la real, no).

    Returns:
        `(eventos, dlg)`: lo que pasó en orden, con el estado de la ventana en
        cada momento, y la ventana.
    """
    eventos: list = []
    ventanas: list = []

    def falso_proteger(dlg):
        """Apunta que se llama, y con la ventana en qué estado."""
        eventos.append(("proteger", str(dlg.state())))
        ventanas.append(dlg)
        return resultado

    def falso_mostrar(dlg, parent=None):
        """Apunta que se llama, y con la ventana en qué estado."""
        eventos.append(("mostrar", str(dlg.state())))
        ventanas.append(dlg)

    if protector:
        tk_qr.proteger_de_capturas = falso_proteger
    tk_qr.mostrar = falso_mostrar
    try:
        tk_qr.open_dialog(raiz, {})
    finally:
        tk_qr.proteger_de_capturas, tk_qr.mostrar = proteger_real, mostrar_real
    return eventos, ventanas[-1]


try:
    # a) lo que se consigue es lo que se dice
    eventos, dlg = abrir(uitk.CAPTURA_EXCLUIDA)
    c("protege antes de mostrar, y solo una vez",
      [e for e, _ in eventos], ["proteger", "mostrar"])
    c("  y la ventana sigue retirada en los dos momentos: ni un fotograma "
      "sin proteger", [estado for _, estado in eventos],
      ["withdrawn", "withdrawn"])
    dicho = textos(dlg)
    linea = tk_qr.LINEA_CAPTURA[uitk.CAPTURA_EXCLUIDA]
    c("excluida: la ventana dice que no aparece", dicho.count(linea), 1)
    c("  y no dice la otra frase",
      tk_qr.LINEA_CAPTURA[uitk.CAPTURA_EN_NEGRO] in dicho, False)
    aviso = buscar(dlg, "Ambar.TFrame")
    etiquetas = [w for w in buscar(dlg, "Pista.TLabel")
                 if str(w.cget("text")) == linea]
    c("  hay una sola etiqueta con la línea", len(etiquetas), 1)
    fila_linea = int(etiquetas[0].grid_info()["row"])
    c("  la línea va justo debajo del aviso ámbar",
      (len(aviso), int(aviso[0].grid_info()["row"]) + 1), (1, fila_linea))
    c("  y encima de la tarjeta del código",
      fila_linea < int(buscar(dlg, "Card.TFrame")[0].grid_info()["row"]), True)
    dlg.destroy()

    eventos, dlg = abrir(uitk.CAPTURA_EN_NEGRO)
    dicho = textos(dlg)
    c("en negro: la ventana dice que sale en negro",
      dicho.count(tk_qr.LINEA_CAPTURA[uitk.CAPTURA_EN_NEGRO]), 1)
    c("  y en ningún sitio dice «no aparece»: no es verdad",
      any("no aparece" in t for t in dicho), False)
    dlg.destroy()

    # Sin protección: en Windows se dice (el fallo no es silencioso); fuera, no.
    previo_win = uitk.IS_WIN
    uitk.IS_WIN = False
    try:
        eventos, dlg = abrir(uitk.CAPTURA_NINGUNA)
    finally:
        uitk.IS_WIN = previo_win
    c("sin protección fuera de Windows: protege y muestra igual, en ese orden",
      [e for e, _ in eventos], ["proteger", "mostrar"])
    c("  y no promete nada: ninguna línea habla de capturas",
      any("captura" in t.lower() or "compartir" in t.lower()
          for t in textos(dlg)), False)
    c("  pero el aviso ámbar sigue diciendo que una foto basta",
      tk_qr.AVISO in textos(dlg), True)
    dlg.destroy()

    uitk.IS_WIN = True
    try:
        eventos, dlg = abrir(uitk.CAPTURA_NINGUNA)
    finally:
        uitk.IS_WIN = previo_win
    dicho = textos(dlg)
    c("sin protección en Windows: protege y muestra igual, en ese orden",
      [e for e, _ in eventos], ["proteger", "mostrar"])
    c("  y dice que no se ha podido, con esas palabras",
      dicho.count("No se ha podido proteger esta ventana de las capturas de "
                  "pantalla."), 1)
    c("  y no dice ninguna de las otras dos frases",
      [t for t in dicho if t in tk_qr.LINEA_CAPTURA.values()], [])
    etiquetas = [w for w in buscar(dlg, "Pista.TLabel")
                 if str(w.cget("text")) == tk_qr.LINEA_SIN_PROTECCION]
    c("  la línea va justo debajo del aviso ámbar y encima de la tarjeta",
      (len(etiquetas),
       int(etiquetas[0].grid_info()["row"]) - 1
       == int(buscar(dlg, "Ambar.TFrame")[0].grid_info()["row"]),
       int(etiquetas[0].grid_info()["row"])
       < int(buscar(dlg, "Card.TFrame")[0].grid_info()["row"])),
      (1, True, True))
    c("  y el aviso ámbar sigue diciendo que una foto basta",
      tk_qr.AVISO in dicho, True)
    dlg.destroy()

    uitk.IS_WIN = True
    try:
        eventos, dlg = abrir(uitk.CAPTURA_EXCLUIDA)
    finally:
        uitk.IS_WIN = previo_win
    c("con protección en Windows no se añade la frase del fallo",
      tk_qr.LINEA_SIN_PROTECCION in textos(dlg), False)
    dlg.destroy()

    c("las dos frases de la tabla son las que se prueban aquí",
      sorted(tk_qr.LINEA_CAPTURA), sorted([uitk.CAPTURA_EN_NEGRO,
                                           uitk.CAPTURA_EXCLUIDA]))

    # b) sin código a la vista no hay nada que proteger
    pairing.construir = lambda raw=None, app_dir=None: (_ for _ in ()).throw(
        ConfigError("Este dispositivo no tiene conexión"))
    eventos, dlg = abrir(uitk.CAPTURA_EXCLUIDA)
    c("sin conexión que enseñar: no protege, y la ventana se muestra",
      [e for e, _ in eventos], ["mostrar"])
    c("  y no dice nada de capturas",
      any("captura" in t.lower() for t in textos(dlg)), False)
    c("  el motivo sale con el estilo de pista de la tarjeta, que existe",
      [str(w.cget("text")) for w in buscar(dlg, "Card.Pista.TLabel")],
      ["Este dispositivo no tiene conexión"])
    dlg.destroy()
    uitk.IS_WIN = True
    try:
        eventos, dlg = abrir(uitk.CAPTURA_NINGUNA)
    finally:
        uitk.IS_WIN = previo_win
    c("  ni siquiera en Windows: sin código a la vista no hay nada que lamentar",
      any("captura" in t.lower() for t in textos(dlg)), False)
    dlg.destroy()

    pairing.construir = lambda raw=None, app_dir=None: pairing.dumps(
        "nas", {"type": "sftp", "host": "nas.example.org"},
        key_name="id_ed25519", catalog_path="/prdrive-catalog/pairs.toml",
        private_key=b"-----BEGIN OPENSSH PRIVATE KEY-----\nabc\n"
                    b"-----END OPENSSH PRIVATE KEY-----\n")
    tk_qr.icons.matriz = lambda *a, **k: None
    eventos, dlg = abrir(uitk.CAPTURA_EXCLUIDA)
    c("si el código no se pudo dibujar: tampoco protege (no hay nada en pantalla)",
      [e for e, _ in eventos], ["mostrar"])
    c("  y lo dice con el estilo de pista de la tarjeta, que existe",
      [str(w.cget("text")) for w in buscar(dlg, "Card.Pista.TLabel")],
      ["No se ha podido dibujar el código."])
    dlg.destroy()
    tk_qr.icons.matriz = matriz_real

    # c) con la función de verdad, en un sistema que no es Windows
    previo_win = uitk.IS_WIN
    uitk.IS_WIN = False
    try:
        eventos, dlg = abrir(protector=False)
    finally:
        uitk.IS_WIN = previo_win
    c("fuera de Windows la ventana se abre igual, sin ninguna línea de capturas",
      ([e for e, _ in eventos],
       any("captura" in t.lower() for t in textos(dlg))),
      (["mostrar"], False))
    dlg.destroy()
finally:
    pairing.construir = construir_real
    tk_qr.icons.matriz = matriz_real
    tk_qr.proteger_de_capturas, tk_qr.mostrar = proteger_real, mostrar_real
    raiz.destroy()

sys.exit(c.report())
