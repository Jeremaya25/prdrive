#!/usr/bin/env python3
"""«Ajustes» cambia en su sitio: la barra no se repinta y los apartados se guardan.

Lo que se comprueba, con Tk de verdad y sin entrar nunca en el bucle de eventos:

- la barra lateral se dibuja una vez: cambiar de apartado cambia el estilo de
  exactamente dos botones, no crea ni destruye ningún widget de la barra, y los
  chips de dentro de los botones toman la superficie nueva de su botón (antes
  se quedaban con las esquinas del botón de antes);
- los chips se recalculan con la lectura compartida de la ventana principal y
  solo cambia el que ha cambiado;
- cada apartado se dibuja la primera vez que se elige y se conserva escondido:
  volver a uno ya visto es enseñar el mismo marco, y un apartado visto tras
  una serie de visitas enseña lo mismo que uno recién abierto;
- el código QR no se conserva nunca (al irse se destruye su marco y con él se
  levanta la protección contra capturas);
- lo que un apartado da por terminado lo rehace con la nota y tira los demás;
- un apartado que se dibuja antes de que llegue la lectura compartida no cae a
  la pantalla de penwatch por falta de datos, y «Actualizaciones» espera con un
  indicador y se rehace al llegar;
- la baja de la suscripción es la de la ventana, no la de cualquiera de sus hijos.
"""

import random
import sys

from _harness import Checks, sandbox

import _vista

c = Checks("«Ajustes» en su sitio (barra, apartados guardados, lectura compartida)")

from ui import instantanea, tk_doctor, watch  # noqa: E402

# 0. Lo que se decide sin Tk.
c("sin hallazgos ni versión nueva, «Reparación» no lleva chip",
  tk_doctor.chip_de("reparacion", 0, None, []), None)
c("con tres cosas que revisar, su número en un chip de aviso",
  tk_doctor.chip_de("reparacion", 3, None, []), ("3", "Aviso.", "warn"))
c("«Actualizaciones» dice la versión nueva si la hay",
  tk_doctor.chip_de("actualizaciones", 0, type("V", (), {"version": "0.9.0"})(), ["x"]),
  ("0.9.0", "Acento.", "down"))
c("  y si no, que hay componentes",
  tk_doctor.chip_de("actualizaciones", 0, None, ["rclone"]),
  ("componentes", "Aviso.", "warn"))
c("  y si no hay nada, nada", tk_doctor.chip_de("actualizaciones", 0, None, []), None)
c("los demás apartados no llevan chip", tk_doctor.chip_de("volumen", 9, None, ["x"]), None)
c("solo el código QR se tira al dejarlo", tk_doctor.EFIMEROS, ("qr",))

try:
    import tkinter as tk
    from tkinter import ttk
    raiz = tk.Tk()
    raiz.withdraw()
except Exception as e:                                   # sin entorno gráfico
    print(f"  (saltado) no hay entorno gráfico: {e}")
    sys.exit(c.report())

from common import catalog, model, update  # noqa: E402
from ui import (segundo_plano, theme, tk_update, tk_versions, tk_watch,  # noqa: E402
                versions_editor)
from ui import tk as uitk  # noqa: E402

# Lo que los apartados leen del remoto o del equipo llega en el acto: aquí no se
# entra nunca en el bucle de eventos. Se sustituyen la lectura y el `working` de
# «Versiones» y el catálogo del «Llavero», de modo que valga igual antes y
# después de que los apartados lean en segundo plano.
segundo_plano.lanzar = segundo_plano.en_el_acto
tk_versions.working = lambda parent, title, funcion, mensaje="", **_k: (True, funcion())
versions_editor.leer_local = lambda pair: versions_editor.Lado(
    versions_editor.DISPOSITIVO, str(pair.local_abs), True, "", ())
versions_editor.leer_remoto = lambda pair: versions_editor.Lado(
    versions_editor.REMOTO, pair.versions_path2, True, "", ())
catalog.load = lambda raw_local=None: (None, "sin red")
update.pending = lambda root=None: None

errores: list[str] = []
raiz.report_callback_exception = (
    lambda tipo, valor, _tb: errores.append(f"{tipo.__name__}: {valor}"))

RAW = {"defaults": {"remote": "nas"},
       "pair": [{"name": "notas", "local": "sync-data/notas", "remote_path": "/R/notas",
                 "mode": "bisync", "versions": True},
                {"name": "fotos", "local": "sync-data/fotos", "remote_path": "/R/fotos",
                 "mode": "bisync", "versions": True}]}
ROTULOS = {a.clave: a.rotulo for _g, aps in tk_doctor.GRUPOS for a in aps}
"""El rótulo de cada apartado en la barra."""
CLAVES = ("volumen", "configuracion", "llavero", "versiones", "arranque", "qr",
          "reparacion", "actualizaciones")
"""Los apartados que salen siempre (el de «Catálogo del remoto» solo a veces)."""
AGENTE = watch.Resumen("agente", "ui", True)
"""Un vigilante que no lee nada del equipo: el apartado «Arranque» es el del agente."""


def lectura(**campos):
    """Devuelve una `Instantanea` con huella, como la que entrega un hilo que leyó bien."""
    return instantanea.Instantanea(huella=("de prueba",), **campos)


def recorrer(w):
    """Recorre los widgets que cuelgan de `w`, en profundidad."""
    for hijo in w.winfo_children():
        yield hijo
        yield from recorrer(hijo)


def barra(dlg) -> dict:
    """Devuelve los botones de la barra lateral de «Ajustes» por su rótulo."""
    return {b.cget("text"): b for b in recorrer(dlg) if isinstance(b, ttk.Button)
            and str(b.cget("style")) in ("Nav.TButton", "NavSel.TButton")}


def estilos(dlg) -> dict:
    """Devuelve el estilo de cada botón de la barra."""
    return {t: str(b.cget("style")) for t, b in barra(dlg).items()}


def elegir(dlg, clave: str) -> None:
    """Pulsa el botón del apartado, como quien lo usa."""
    barra(dlg)[ROTULOS[clave]].invoke()


def chips_de(dlg) -> dict:
    """Devuelve los chips de la barra: rótulo del botón -> las etiquetas que lleva dentro."""
    return {t: [w for w in b.winfo_children() if isinstance(w, ttk.Label)]
            for t, b in barra(dlg).items()}


def textos(w) -> list[str]:
    """Devuelve los textos de las etiquetas a la vista bajo `w`."""
    return [str(x.cget("text")) for x in _vista.visibles(w) if isinstance(x, ttk.Label)]


def abrir(conducir, cfg=None, mapeada=False, **kw):
    """Abre «Ajustes» y, en vez de dejarla esperar, ejecuta `conducir(dlg)`.

    Con `mapeada` la ventana se enseña de verdad, que es cuando los controles
    toman la superficie del sitio donde caen.
    """
    cfg = cfg or model.parse_config(RAW)

    def mostrar(dlg, parent=None):
        """Hace lo que toque con la ventana ya montada, y la cierra."""
        if mapeada:
            uitk.ensenar(dlg)
            dlg.update()
        try:
            conducir(dlg)
        finally:
            if dlg.winfo_exists():
                dlg.destroy()
    tk_doctor.mostrar = mostrar
    kw.setdefault("vigilante", AGENTE)
    return tk_doctor.open_dialog(raiz, cfg, lambda *a: None, **kw)


# 1. La barra: dos botones, ningún widget nuevo.
with sandbox():
    visto: dict = {}

    def conmutar(dlg):
        """Cambia de apartado varias veces y apunta qué cambió en la barra."""
        botones = list(barra(dlg).values())
        frame = botones[0].master
        todos = lambda: {str(w) for w in recorrer(frame)}          # noqa: E731
        visto["al abrir"] = estilos(dlg)
        visto["widgets"] = todos()
        configurados: list = []
        real = ttk.Button.configure

        def espiar(self, *a, **k):
            """Apunta qué botón de la barra se reconfigura."""
            if self in botones and (a or k):
                configurados.append(str(self))
            return real(self, *a, **k)

        ttk.Button.configure = espiar
        try:
            antes = estilos(dlg)
            elegir(dlg, "versiones")
            despues = estilos(dlg)
        finally:
            ttk.Button.configure = real
        visto["cambiados"] = sorted(t for t in antes if antes[t] != despues[t])
        visto["reconfigurados"] = sorted(set(configurados))
        visto["elegido"] = [t for t, e in despues.items() if e == "NavSel.TButton"]
        for clave in ("reparacion", "volumen", "qr", "arranque", "configuracion"):
            elegir(dlg, clave)
        visto["widgets despues"] = todos()
        visto["elegido al final"] = [t for t, e in estilos(dlg).items()
                                     if e == "NavSel.TButton"]

    abrir(conmutar)
    c("al abrir sale elegido «Configuración» y los demás no",
      [t for t, e in visto["al abrir"].items() if e == "NavSel.TButton"], ["Configuración"])
    c("cambiar de apartado cambia el estilo de dos botones: el que se deja y el que se elige",
      visto["cambiados"], ["Configuración", "Versiones"])
    c("  y no reconfigura ningún otro botón de la barra",
      visto["reconfigurados"] and len(visto["reconfigurados"]), 2)
    c("  queda elegido uno solo", visto["elegido"], ["Versiones"])
    c("tras seis cambios de apartado, la barra tiene los mismos widgets: ninguno nuevo ni perdido",
      visto["widgets despues"], visto["widgets"])
    c("  y uno solo elegido, el último", visto["elegido al final"], ["Configuración"])
    c("sin errores en los manejadores de Tk", errores, [])


# 2. Los chips: se recalculan con la lectura compartida y solo cambia el que cambió.
with sandbox():
    comp = instantanea.Compartida()
    visto = {}

    def con_lectura(dlg):
        """Entrega lecturas a la ventana abierta y apunta qué chips cambian."""
        visto["al abrir"] = {t: len(v) for t, v in chips_de(dlg).items() if v}
        antes = chips_de(dlg)
        comp.poner(lectura(cuenta=2))
        despues = chips_de(dlg)
        visto["llega"] = {t: [x.cget("text") for x in v] for t, v in despues.items() if v}
        visto["nuevos"] = sorted(t for t in despues if despues[t] != antes[t])
        mismo = chips_de(dlg)
        comp.poner(lectura(cuenta=2))                     # otra lectura, la misma cuenta
        visto["igual"] = [t for t, v in chips_de(dlg).items() if v != mismo[t]]
        otro = chips_de(dlg)
        comp.poner(lectura(cuenta=5))
        visto["otra cuenta"] = sorted(t for t, v in chips_de(dlg).items() if v != otro[t])
        visto["texto"] = [x.cget("text") for x in chips_de(dlg)["Reparación"]]
        visto["viejo vivo"] = any(x.winfo_exists() for x in otro["Reparación"])
        comp.poner(lectura(cuenta=0))
        visto["sin cuenta"] = chips_de(dlg)["Reparación"]

    abrir(con_lectura, compartida=comp)
    c("sin lectura todavía, ningún apartado lleva chip", visto["al abrir"], {})
    c("llega una lectura con dos cosas que revisar: el chip sale en «Reparación»",
      visto["llega"], {"Reparación": ["2"]})
    c("  y es el único chip nuevo", visto["nuevos"], ["Reparación"])
    c("otra lectura con la misma cuenta no cambia ningún chip", visto["igual"], [])
    c("con otra cuenta, cambia exactamente el chip de «Reparación»",
      visto["otra cuenta"], ["Reparación"])
    c("  que dice la cuenta nueva", visto["texto"], ["5"])
    c("  y el viejo ya no existe", visto["viejo vivo"], False)
    c("con la cuenta a cero el chip se va", visto["sin cuenta"], [])

with sandbox():
    # Una lectura que no sirve (vacía, o con `hallazgos` fallido) no borra lo que la
    # ventana principal ya había contado: se queda con los hallazgos que se le dieron.
    comp = instantanea.Compartida()
    hallazgo = tk_doctor.revision.Hallazgo("lock", "t", "d", "notas")
    visto = {}

    def lectura_mala(dlg):
        """Entrega lecturas sin valor y apunta qué chip queda."""
        visto["de los hallazgos"] = [x.cget("text") for x in chips_de(dlg)["Reparación"]]
        comp.poner(instantanea.vacia(model.parse_config(RAW)))
        visto["vacia"] = [x.cget("text") for x in chips_de(dlg)["Reparación"]]
        comp.poner(lectura(cuenta=0, fallos={"hallazgos": "OSError()"}))
        visto["fallida"] = [x.cget("text") for x in chips_de(dlg)["Reparación"]]
        comp.poner(lectura(cuenta=4))
        visto["buena"] = [x.cget("text") for x in chips_de(dlg)["Reparación"]]

    abrir(lectura_mala, compartida=comp, hallazgos=[hallazgo])
    c("con `hallazgos` y sin lectura, el chip es el de esos hallazgos",
      visto["de los hallazgos"], ["1"])
    c("una lectura vacía no lo borra", visto["vacia"], ["1"])
    c("ni una donde `hallazgos` falló", visto["fallida"], ["1"])
    c("pero una buena sí lo cambia", visto["buena"], ["4"])


# 3. Los chips toman la superficie de su botón cuando este cambia de cara.
with sandbox():
    comp = instantanea.Compartida()
    comp.poner(lectura(cuenta=3))
    visto = {}
    style = ttk.Style(raiz)

    def esquinas(chip) -> str:
        """Devuelve el color de debajo del chip, el que asoma por sus esquinas."""
        return theme._hex(raiz, style.lookup(str(chip.cget("style")), "background",
                                             chip.state()))

    def con_el_boton(dlg):
        """Apunta de qué color son las esquinas del chip con el botón elegido y sin elegir."""
        chip = chips_de(dlg)["Reparación"][0]
        visto["sin elegir"] = esquinas(chip)
        elegir(dlg, "reparacion")
        dlg.update()
        visto["elegido"] = esquinas(chip)
        elegir(dlg, "volumen")
        dlg.update()
        visto["otra vez sin elegir"] = esquinas(chip)

    abrir(con_el_boton, mapeada=True, compartida=comp)
    papel, suave = theme._hex(raiz, theme.PAPEL), theme._hex(raiz, theme.ACENTO_SUAVE)
    c("el chip de un botón sin elegir tiene las esquinas del papel", visto["sin elegir"], papel)
    c("al elegir su botón, las esquinas del chip son las de la cara del botón elegido",
      visto["elegido"], suave)
    c("al dejarlo, vuelven al papel", visto["otra vez sin elegir"], papel)


# 4. Los apartados se guardan.
class EspiaPanel:
    """Apunta, por clase, qué `Panel` se oculta o se vuelve a enseñar."""

    def __init__(self):
        self.registro: list[tuple[str, str]] = []

    def __enter__(self):
        self.ocultado, self.mostrado = uitk.Panel.ocultado, uitk.Panel.mostrado
        registro, ocultado, mostrado = self.registro, self.ocultado, self.mostrado

        def al_ocultar(panel):
            registro.append(("ocultado", panel._clave))
            return ocultado(panel)

        def al_mostrar(panel):
            registro.append(("mostrado", panel._clave))
            return mostrado(panel)

        uitk.Panel.ocultado, uitk.Panel.mostrado = al_ocultar, al_mostrar
        return self

    def __exit__(self, *_a):
        uitk.Panel.ocultado, uitk.Panel.mostrado = self.ocultado, self.mostrado


with sandbox():
    visto = {}

    def visitas(dlg):
        """Visita «Configuración», «Versiones», «Nombre e icono» y vuelve a «Configuración»."""
        visto["abiertos"] = sorted(dlg.paneles)
        configuracion = dlg.paneles["configuracion"]
        visto["panel"] = dlg.panel is configuracion[1]
        elegir(dlg, "versiones")
        visto["tras versiones"] = sorted(dlg.paneles)
        visto["escondida"] = _vista.a_la_vista(configuracion[0])
        elegir(dlg, "volumen")
        elegir(dlg, "configuracion")
        visto["mismo marco"] = dlg.paneles["configuracion"][0] is configuracion[0]
        visto["mismo panel"] = dlg.paneles["configuracion"][1] is configuracion[1]
        visto["vuelve a la vista"] = _vista.a_la_vista(configuracion[0])
        visto["panel vuelto"] = dlg.panel is configuracion[1]
        visto["guardados"] = sorted(dlg.paneles)
        visto["ocultos"] = sorted(k for k, (m, _p) in dlg.paneles.items()
                                  if not _vista.a_la_vista(m))

    with EspiaPanel() as espia:
        abrir(visitas)
    c("al abrir solo está dibujado el apartado con que se abre", visto["abiertos"],
      ["configuracion"])
    c("  y es el que `dlg.panel` dice", visto["panel"], True)
    c("tras elegir «Versiones» se guardan los dos", visto["tras versiones"],
      ["configuracion", "versiones"])
    c("  y «Configuración» queda escondida, no destruida", visto["escondida"], False)
    c("volver a «Configuración» enseña el mismo marco", visto["mismo marco"], True)
    c("  con el mismo panel", visto["mismo panel"], True)
    c("  que vuelve a estar a la vista", visto["vuelve a la vista"], True)
    c("  y `dlg.panel` es otra vez el suyo", visto["panel vuelto"], True)
    c("se conservan los tres visitados", visto["guardados"],
      ["configuracion", "versiones", "volumen"])
    c("  y los dos que no están a la vista, escondidos", visto["ocultos"],
      ["versiones", "volumen"])
    c("dejar un apartado llama a su `ocultado()` una vez, y volver a su `mostrado()` una vez",
      espia.registro,
      [("ocultado", "configuracion"), ("ocultado", "versiones"),
       ("ocultado", "volumen"), ("mostrado", "configuracion")])
    c("sin errores en los manejadores de Tk", errores, [])

with sandbox():
    visto = {}

    def con_qr(dlg):
        """Visita el código QR y se va, y lo vuelve a visitar."""
        elegir(dlg, "qr")
        marco = dlg.paneles["qr"][0]
        visto["dentro"] = "qr" in dlg.paneles
        elegir(dlg, "configuracion")
        visto["fuera"] = "qr" in dlg.paneles
        visto["marco vivo"] = bool(marco.winfo_exists())
        elegir(dlg, "qr")
        visto["otro marco"] = dlg.paneles["qr"][0] is not marco

    with EspiaPanel() as espia:
        abrir(con_qr)
    c("el QR, mientras se ve, está en la lista de dibujados", visto["dentro"], True)
    c("  al irse ya no está: nunca se conserva", visto["fuera"], False)
    c("  y su marco se destruye, que es lo que levanta la protección de capturas",
      visto["marco vivo"], False)
    c("  al volver se dibuja de nuevo, en un marco nuevo", visto["otro marco"], True)
    c("  dejarlo también llama a su `ocultado()`",
      ("ocultado", "qr") in espia.registro, True)


# 4a. El código QR dentro de «Ajustes»: se protege al enseñarlo y se suelta al irse.
with sandbox():
    from common import pairing
    from ui import tk_qr

    construir_real, reales = pairing.construir, (tk_qr.proteger_de_capturas,
                                                 tk_qr.soltar_capturas)
    pairing.construir = lambda raw=None, app_dir=None: pairing.dumps(
        "nas", {"type": "sftp", "host": "nas.example.org", "port": "22", "user": "pere"},
        key_name="id_ed25519", catalog_path="/prdrive-catalog/pairs.toml",
        private_key=(b"-----BEGIN OPENSSH PRIVATE KEY-----\n" + b"b3BlbnNza" * 40
                     + b"\n-----END OPENSSH PRIVATE KEY-----\n"))
    eventos: list = []
    tk_qr.proteger_de_capturas = lambda dlg: eventos.append("proteger") or uitk.CAPTURA_EXCLUIDA
    tk_qr.soltar_capturas = lambda dlg: eventos.append("soltar")
    visto = {}

    def qr_y_vuelta(dlg):
        """Entra en el QR, sale, entra otra vez y apunta qué protección hay en cada momento."""
        elegir(dlg, "qr")
        dlg.update()
        visto["dentro"] = list(eventos)
        elegir(dlg, "configuracion")
        visto["fuera"] = list(eventos)
        elegir(dlg, "qr")
        dlg.update()
        visto["otra vez"] = list(eventos)

    try:
        abrir(qr_y_vuelta, raw_local={})
        visto["al cerrar"] = list(eventos)
    finally:
        pairing.construir = construir_real
        tk_qr.proteger_de_capturas, tk_qr.soltar_capturas = reales
    c("el QR protege la ventana al enseñar el código", visto["dentro"], ["proteger"])
    c("  al irse del apartado se suelta (su marco se destruye)", visto["fuera"],
      ["proteger", "soltar"])
    c("  al volver se protege otra vez: es un código nuevo", visto["otra vez"],
      ["proteger", "soltar", "proteger"])
    c("  y al cerrar «Ajustes» con el QR a la vista, se suelta",
      visto["al cerrar"], ["proteger", "soltar", "proteger", "soltar"])


# 4b. Lo que se ve tras una serie de visitas es lo que se ve recién abierto.
def leer_apartado(dlg, clave):
    """Devuelve lo que enseña el apartado, ya a la vista."""
    return _vista.leer_vista(dlg.paneles[clave][0])


with sandbox():
    azar = random.Random(20261008)
    diferencias: list = []
    vacios: list = []
    vistos_tras: dict = {}
    for clave in CLAVES:
        recorrido = [azar.choice(CLAVES) for _ in range(5)]
        leido: dict = {}

        def tras_visitas(dlg):
            """Visita al azar cinco apartados y acaba en `clave`."""
            for otra in recorrido:
                elegir(dlg, otra)
            elegir(dlg, clave)
            leido["visitado"] = leer_apartado(dlg, clave)

        def recien_abierto(dlg):
            """Lee el apartado nada más abrir."""
            leido["nuevo"] = leer_apartado(dlg, clave)

        abrir(tras_visitas)
        abrir(recien_abierto, inicial=clave)
        vistos_tras[clave] = len(leido["nuevo"])
        if not leido["nuevo"]:
            vacios.append(clave)
        if leido["visitado"] != leido["nuevo"]:
            diferencias.append((clave, recorrido))
    c("cada apartado enseña lo mismo tras cinco visitas al azar que recién abierto",
      diferencias, [])
    c("  (y todos los comparados enseñan algo)", vacios, [])
    c("sin errores en los manejadores de Tk", errores, [])

with sandbox():
    visto = {}

    def terminar(dlg):
        """Da por terminado un apartado con una nota y mira qué queda."""
        elegir(dlg, "versiones")
        elegir(dlg, "volumen")
        viejo = dlg.paneles["volumen"][0]
        visto["antes"] = sorted(dlg.paneles)
        dlg.panel.terminar("Guardado.")
        visto["despues"] = sorted(dlg.paneles)
        visto["rehecho"] = dlg.paneles["volumen"][0] is not viejo
        visto["viejo vivo"] = bool(viejo.winfo_exists())
        visto["nota"] = "Guardado." in textos(dlg.paneles["volumen"][0])
        visto["a la vista"] = _vista.a_la_vista(dlg.paneles["volumen"][0])
        elegir(dlg, "configuracion")
        elegir(dlg, "volumen")
        visto["nota al volver"] = "Guardado." in textos(dlg.paneles["volumen"][0])

    abrir(terminar)
    c("antes de terminar hay tres apartados guardados", visto["antes"],
      ["configuracion", "versiones", "volumen"])
    c("terminar rehace el apartado a la vista y tira los demás", visto["despues"],
      ["volumen"])
    c("  el apartado es un marco nuevo y el viejo ya no existe",
      (visto["rehecho"], visto["viejo vivo"]), (True, False))
    c("  lleva la nota arriba y está a la vista", (visto["nota"], visto["a la vista"]),
      (True, True))
    c("al irse y volver ya no lleva la nota: se dibuja como una apertura nueva",
      visto["nota al volver"], False)


# 5. Un apartado que se dibuja antes de que llegue la lectura compartida.
with sandbox():
    llamadas = {"penwatch": 0, "agente": [], "resumen": 0}
    reales = (tk_watch.construir, tk_watch.construir_agente, watch.resumen)

    def penwatch_falso(panel):
        """Apunta que se ha dibujado la pantalla de penwatch."""
        llamadas["penwatch"] += 1
        ttk.Label(panel.marco, text="penwatch").grid()

    def agente_falso(panel, res):
        """Apunta que se ha dibujado la del agente, y para quién."""
        llamadas["agente"].append(res.estado)
        ttk.Label(panel.marco, text="agente").grid()

    def resumen_falso():
        """Hace de `watch.resumen()`: apunta que se ha leído y dice que hay agente."""
        llamadas["resumen"] += 1
        return AGENTE

    tk_watch.construir, tk_watch.construir_agente, watch.resumen = (
        penwatch_falso, agente_falso, resumen_falso)
    try:
        def casos(inicial, **kw):
            llamadas.update(penwatch=0, agente=[], resumen=0)
            abrir(lambda dlg: None, inicial="arranque", **kw)
            return dict(llamadas)

        comp = instantanea.Compartida()
        sin_nada = casos("arranque", compartida=comp, vigilante=None)
        c("sin lectura ni parámetro, mira por su cuenta lo que hace el equipo",
          sin_nada["resumen"], 1)
        c("  y dibuja el del agente, no la pantalla de penwatch",
          (sin_nada["penwatch"], sin_nada["agente"]), (0, ["agente"]))

        comp.poner(lectura(vigilante=watch.Resumen("agente_raiz", "ui")))
        de_la_lectura = casos("arranque", compartida=comp, vigilante=AGENTE)
        c("con una lectura buena, sale de ella y no se lee nada",
          (de_la_lectura["resumen"], de_la_lectura["agente"]), (0, ["agente_raiz"]))

        comp.poner(lectura(vigilante=watch.Resumen("sin_instalar"),
                           fallos={"vigilante": "OSError()"}))
        fallida = casos("arranque", compartida=comp, vigilante=AGENTE)
        c("con una lectura donde `vigilante` falló, vale el parámetro",
          (fallida["resumen"], fallida["agente"]), (0, ["agente"]))

        comp.poner(instantanea.vacia(model.parse_config(RAW)))
        vacia = casos("arranque", compartida=comp, vigilante=None)
        c("con una lectura vacía y sin parámetro, se lee: nunca cae a penwatch por falta de datos",
          (vacia["resumen"], vacia["penwatch"], vacia["agente"]), (1, 0, ["agente"]))

        sin_compartida = casos("arranque", vigilante=watch.Resumen("sin_instalar"))
        c("el equipo sin agente sigue dibujando la pantalla de penwatch",
          (sin_compartida["penwatch"], sin_compartida["agente"], sin_compartida["resumen"]),
          (1, [], 0))
    finally:
        tk_watch.construir, tk_watch.construir_agente, watch.resumen = reales

with sandbox():
    llamadas: list = []
    real = tk_update.construir_componentes

    def componentes_falso(panel, componentes):
        """Apunta qué componentes dibuja la pantalla de componentes."""
        llamadas.append(tuple(componentes))
        ttk.Label(panel.marco, text="componentes viejos").grid()

    tk_update.construir_componentes = componentes_falso
    visto = {}
    try:
        comp = instantanea.Compartida()

        def esperando(dlg):
            """Abre «Actualizaciones» antes de que llegue la lectura y mira cómo espera."""
            marco = dlg.paneles["actualizaciones"][0]
            visto["indicador"] = [w for w in _vista.visibles(marco, "TProgressbar")]
            visto["dice"] = textos(marco)
            visto["al dia"] = tk_doctor.AL_DIA in textos(marco)
            visto["boton"] = [w for w in _vista.visibles(marco, "TButton")]
            comp.poner(lectura(componentes=("rclone",)))
            visto["llamadas"] = list(llamadas)
            visto["mismo marco"] = dlg.paneles["actualizaciones"][0] is marco
            visto["marco vivo"] = bool(marco.winfo_exists())
            nuevo = dlg.paneles["actualizaciones"][0]
            visto["sin barra"] = _vista.visibles(nuevo, "TProgressbar")
            visto["chip"] = [x.cget("text") for x in chips_de(dlg)["Actualizaciones"]]
            comp.poner(lectura(componentes=("rclone",)))
            visto["otra igual"] = dlg.paneles["actualizaciones"][0] is nuevo

        abrir(esperando, inicial="actualizaciones", compartida=comp, componentes=None)
        c("antes de la lectura, «Actualizaciones» enseña un indicador esperando",
          len(visto["indicador"]), 1)
        c("  no dice «al día» ni ofrece nada que pulsar todavía",
          (visto["al dia"], visto["boton"]), (False, []))
        c("  al llegar la lectura con un componente viejo, se dibuja la pantalla de componentes",
          visto["llamadas"], [("rclone",)])
        c("  en un marco nuevo, sin el indicador",
          (visto["mismo marco"], visto["marco vivo"], visto["sin barra"]), (False, False, []))
        c("  y el chip de la barra dice que hay componentes", visto["chip"], ["componentes"])
        c("otra lectura que dice lo mismo no rehace el apartado", visto["otra igual"], True)

        visto.clear()

        def sin_novedades(dlg):
            """Lo mismo, pero la lectura trae todo al día."""
            comp.poner(lectura())
            marco = dlg.paneles["actualizaciones"][0]
            visto["al dia"] = tk_doctor.AL_DIA in textos(marco)
            visto["boton"] = [b.cget("text") for b in _vista.visibles(marco, "TButton")]

        comp = instantanea.Compartida()
        abrir(sin_novedades, inicial="actualizaciones", compartida=comp,
              buscar_version=lambda responder: None)
        c("con la lectura al día, el apartado dice «al día» y ofrece buscar a mano",
          (visto["al dia"], visto["boton"]), (True, ["Buscar actualizaciones"]))

        # Una lectura que llega sin componentes (el hilo falló, o el campo falló) no deja
        # el apartado esperando para siempre: los mira él.
        from common import components
        reales_pendientes = components.pendientes
        mirados: list = []
        components.pendientes = lambda *a, **k: mirados.append(1) or ["python"]
        try:
            for nombre, mala in (("vacía", instantanea.vacia(model.parse_config(RAW))),
                                 ("con `componentes` fallido",
                                  lectura(fallos={"componentes": "OSError()"}))):
                llamadas.clear()
                mirados.clear()
                visto.clear()
                comp = instantanea.Compartida()

                def llega_mala(dlg):
                    comp.poner(mala)
                    visto["barras"] = _vista.visibles(dlg.paneles["actualizaciones"][0],
                                                      "TProgressbar")

                abrir(llega_mala, inicial="actualizaciones", compartida=comp, componentes=None)
                c(f"una lectura {nombre} no deja «Actualizaciones» esperando: los mira ella",
                  (visto["barras"], mirados, llamadas), ([], [1], [("python",)]))
        finally:
            components.pendientes = reales_pendientes

        # Y si la lectura mala llegó antes de abrir, tampoco se espera a otra.
        components.pendientes = lambda *a, **k: mirados.append(1) or ["python"]
        try:
            mirados.clear()
            llamadas.clear()
            visto.clear()
            comp = instantanea.Compartida()
            comp.poner(instantanea.vacia(model.parse_config(RAW)))

            def abierta_despues(dlg):
                visto["barras"] = _vista.visibles(dlg.paneles["actualizaciones"][0],
                                                  "TProgressbar")

            abrir(abierta_despues, inicial="actualizaciones", compartida=comp,
                  componentes=None)
            c("abrir «Actualizaciones» con una lectura vacía ya entregada no espera: mira él",
              (visto["barras"], mirados, llamadas), ([], [1], [("python",)]))
        finally:
            components.pendientes = reales_pendientes

        llamadas.clear()
        visto.clear()
        comp = instantanea.Compartida()

        def lejos(dlg):
            """La lectura llega con «Actualizaciones» ya dejada: se rehace al volver."""
            elegir(dlg, "actualizaciones")
            elegir(dlg, "volumen")
            visto["antes"] = "actualizaciones" in dlg.paneles
            comp.poner(lectura(componentes=("python",)))
            visto["despues"] = "actualizaciones" in dlg.paneles
            visto["llamadas"] = list(llamadas)
            elegir(dlg, "actualizaciones")
            visto["al volver"] = list(llamadas)

        abrir(lejos, compartida=comp, componentes=None)
        c("si la lectura llega con el apartado escondido, no se rehace a escondidas",
          (visto["antes"], visto["despues"], visto["llamadas"]), (True, False, []))
        c("  se dibuja al volver, ya con los componentes", visto["al volver"], [("python",)])

        # Sin lectura compartida y sin lista de componentes, no hay nada que esperar:
        # es la ventana de siempre.
        visto.clear()

        def sin_comp(dlg):
            marco = dlg.paneles["actualizaciones"][0]
            visto["barra"] = _vista.visibles(marco, "TProgressbar")
            visto["al dia"] = tk_doctor.AL_DIA in textos(marco)

        abrir(sin_comp, inicial="actualizaciones")
        c("sin lectura compartida (la ventana de siempre) no espera a nada",
          (visto["barra"], visto["al dia"]), ([], True))
    finally:
        tk_update.construir_componentes = real


# 5b. «Reparación» dentro de «Ajustes» pinta de la lectura compartida de la principal.
with sandbox():
    from ui import tk_repair

    recibidas: list = []
    real_construir = tk_repair.construir

    def construir_espia(panel, config, lanzar, marcadas=None, compartida=None):
        """Apunta qué recibe «Reparación» y dibuja la de verdad."""
        recibidas.append((compartida, marcadas))
        real_construir(panel, config, lanzar, marcadas, compartida)

    tk_repair.construir = construir_espia
    comp = instantanea.Compartida()
    try:
        abrir(lambda dlg: elegir(dlg, "reparacion"), compartida=comp, marcadas=["notas"])
        abrir(lambda dlg: elegir(dlg, "reparacion"))
    finally:
        tk_repair.construir = real_construir
    c("«Reparación» recibe la lectura compartida de la ventana principal y las marcadas",
      (recibidas[0][0] is comp, recibidas[0][1]), (True, ["notas"]))
    c("  y sin lectura compartida recibe `None`, como siempre", recibidas[1][0], None)


# 6. La baja de la suscripción es la de la ventana.
with sandbox():
    comp = instantanea.Compartida()
    visto = {}

    def bajas(dlg):
        """Destruye el marco del QR (un hijo) y comprueba que la ventana sigue suscrita."""
        visto["suscritos"] = len(comp._suscritos)
        elegir(dlg, "qr")
        elegir(dlg, "configuracion")                     # destruye el marco del QR
        visto["tras el qr"] = len(comp._suscritos)
        comp.poner(lectura(cuenta=2))
        visto["chip"] = [x.cget("text") for x in chips_de(dlg)["Reparación"]]
        elegir(dlg, "versiones")
        elegir(dlg, "reparacion")
        elegir(dlg, "qr")
        visto["tras tres cambios"] = len(comp._suscritos)

    abrir(bajas, compartida=comp)
    c("la ventana se suscribe una vez", visto["suscritos"], 1)
    c("destruir el marco de un apartado no da de baja la suscripción de la ventana",
      visto["tras el qr"], 1)
    c("  y la ventana sigue recibiendo lecturas", visto["chip"], ["2"])
    c("  ni lo hace ningún otro cambio de apartado", visto["tras tres cambios"], 1)
    c("al cerrar la ventana, sí", len(comp._suscritos), 0)
    comp.poner(lectura(cuenta=9))
    c("  y entregar otra lectura después no falla", errores, [])

sys.exit(c.report())
