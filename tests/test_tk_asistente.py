#!/usr/bin/env python3
"""El asistente, camino de una unidad: pinta primero y lee después.

Cada paso que leía el disco, el sistema o la red en el clic (la lista de
unidades, la ruta a mano, el Python del equipo, la verificación, la nota de la
flota) lo hace ahora en un hilo (`ui.segundo_plano`) o en `working()`, y lo
recoge con un `Sondeo` colgado del propio paso. Con Tk de verdad y, donde hace
falta, hilos de verdad, se comprueba:

- que nada de eso corre en el hilo de Tk, y que mientras se lee el paso lo dice
  y deja apagado lo que depende de la lectura («Siguiente», «Actualizar
  lista», «Volver a comprobar», «Desmontar el contenedor»);
- que solo cuenta la última elección: la lista que llega tarde no pisa una ruta
  a mano, una ruta a mano que llega tarde no pisa la fila elegida después, y
  «Siguiente» no deja seguir con la unidad de antes mientras se mira la ruta;
- que una ruta a mano que no vale vuelve a la elección de ANTES de la primera
  pulsación de su tanda, también en una segunda tanda, y tras elegir una fila o
  tras «Actualizar lista»;
- que cambiar de paso con una lectura en vuelo no deja espera ni llegada;
- que cerrar el asistente desde su propio bucle (`run_wizard()`) espera a la
  medida de escritura que va en vuelo, no deja su temporal en la unidad y cierra
  su `rclone.conf` efímero;
- y que cada paso de los tres recorridos de una unidad cabe en 40 widgets,
  salvo tres estados que se miden y se fijan («Conexión» con «Importar», 41;
  «Instalación» con el programa, 42, y con una unidad ajena, 45), y
  «Verificación», que crece 4 por comprobación sobre una parte fija.

Las ventanas se crean ocultas; el bucle de eventos se mueve a mano
(`dar_vueltas`), que es lo que hace llegar el resultado.
"""

import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

from _harness import Checks, tmpdir

c = Checks("asistente: lo de una unidad se lee después de pintar")

try:
    import tkinter as tk
    from tkinter import messagebox, ttk
    raiz = tk.Tk()
    raiz.withdraw()
except Exception as e:                                   # sin entorno gráfico
    print(f"  (saltado) no hay entorno gráfico: {e}")
    sys.exit(c.report())

from install import crypto, deploy, device, profile, rclone_bin, remote  # noqa: E402
from ui import lecturas_asistente, segundo_plano, tk_install  # noqa: E402
from ui import tk as uitk  # noqa: E402

HILO_TK = threading.get_ident()

# Una excepción dentro de un callback de Tk no revienta el test: Tkinter la
# imprime y sigue. Aquí se apunta, porque pintar en un paso que ya no está es
# justo eso.
errores: list[str] = []
raiz.report_callback_exception = (
    lambda tipo, valor, _tb: errores.append(f"{tipo.__name__}: {valor}"))
dichos: list[str] = []                    # lo que el asistente enseña con `error()`
messagebox.showerror = lambda titulo, texto=None, **k: dichos.append(str(texto))
messagebox.showinfo = lambda *a, **k: None
messagebox.askokcancel = lambda *a, **k: True

# `working()` de verdad (su hilo y su sondeo), sin centrar ni enseñar su
# ventanita: espera a que se cierre, que es lo que hace al terminar el trabajo.
uitk.mostrar = lambda dlg, parent=None: dlg.wait_window()

LANZAR_REAL = segundo_plano.lanzar

# Las cinco parejas del catálogo de la auditoría, dos elegidas.
CATALOGO = '[defaults]\nremote = "nas"\n\n' + "".join(
    f'[[pair]]\nname = "p{i}"\nlocal = "sync-data/p{i}"\n'
    f'remote_path = "/R/p{i}"\nmode = "bisync"\n\n' for i in range(5))
PERFIL = profile.from_form("nas", {"type": "sftp", "host": "nas.example", "user": "u"})
RCLONE_FALSO = tmpdir() / "rclone-de-mentira"
RCLONE_FALSO.write_bytes(b"MZ")

PASO = {t: i for i, (t, _, _) in enumerate(tk_install.PASOS_INSTALACION)}


# Lo que lee: cada sustituto apunta en qué hilo corre.
hilos: dict[str, list[int]] = {}


def apuntar(nombre: str, funcion):
    """Devuelve `funcion` envuelta para apuntar el hilo de cada llamada."""
    def envuelta(*a, **k):
        """Apunta el hilo y llama a la de verdad."""
        hilos.setdefault(nombre, []).append(threading.get_ident())
        return funcion(*a, **k)
    return envuelta


UNIDAD_A, UNIDAD_B = tmpdir("prdrive-asis-a-"), tmpdir("prdrive-asis-b-")
VOLUMENES = [device.Volume(root=UNIDAD_A, label="PEN-A", filesystem="exFAT",
                           drive_type="Removable", size=8 * 2 ** 30, free=7 * 2 ** 30),
             device.Volume(root=UNIDAD_B, label="PEN-B", filesystem="exFAT",
                           drive_type="Removable", size=8 * 2 ** 30, free=7 * 2 ** 30)]
COMPROBACIONES = {"n": 3}                  # cuántas devuelve la verificación de mentira

puerta_lista = threading.Event()        # cerrada, la lista no contesta
puerta_lista.set()


def volumenes_falsos() -> list:
    """Devuelve las unidades de mentira cuando la puerta está abierta."""
    puerta_lista.wait(5)
    return list(VOLUMENES)


device.list_volumes = apuntar("list_volumes", volumenes_falsos)
device.volume_for = apuntar("volume_for", lambda root: device.Volume(
    root=Path(root), label=Path(root).name))
device.check_python = apuntar("check_python", lambda root=None: device.Check(
    "Python en este equipo", True, "el de mentira (con Tkinter)"))
device.verify_device = apuntar("verify_device", lambda root, esperadas=None, key_name=None: [
    device.Check(f"Comprobación {i}", True, f"detalle {i}")
    for i in range(COMPROBACIONES["n"])])
deploy.publish_fleet_note = apuntar(
    "publish_fleet_note",
    lambda rclone, raiz_, endpoint, timeout=45.0: "nas:/prdrive-catalog/flota/x.toml")

# «Comprobar» sin red: rclone, el conf y el catálogo, de mentira.
rclone_bin.ensure_rclone = lambda progreso=None, allow_download=False: RCLONE_FALSO
remote.sweep_stale = lambda base=None: 0
remote.Rclone.check_connection = lambda self, timeout=45.0: None
remote.pull_catalog = lambda rclone, ruta, *a, **k: remote.parse_catalog(CATALOGO)


def widgets(w, tipo=object):
    """Devuelve los widgets de ese tipo que cuelgan de `w`, sin contar `w`."""
    pila, salida = list(w.winfo_children()), []
    while pila:
        actual = pila.pop()
        pila += list(actual.winfo_children())
        if isinstance(actual, tipo):
            salida.append(actual)
    return salida


def boton(wiz, texto):
    """Devuelve el botón del paso con ese texto, o `None`."""
    return next((b for b in widgets(wiz.cuerpo, ttk.Button)
                 if b.cget("text") == texto), None)


def estado_de(wiz, texto) -> str:
    """Devuelve el estado del botón del paso con ese texto, o «no está»."""
    b = boton(wiz, texto)
    return str(b.cget("state")) if b is not None else "no está"


def siguiente(wiz) -> str:
    """Devuelve el estado de «Siguiente»."""
    return str(wiz.boton_siguiente.cget("state"))


def textos(wiz) -> list[str]:
    """Devuelve los textos de las etiquetas que se ven en el paso."""
    return [str(l.cget("text")) for l in widgets(wiz.cuerpo, ttk.Label)
            if l.winfo_manager() and l.master.winfo_manager()]


def arbol(wiz):
    """Devuelve la lista de unidades del paso «Dispositivo», o `None`."""
    return next(iter(widgets(wiz.cuerpo, ttk.Treeview)), None)


def entrada_ruta(wiz):
    """Devuelve la caja de la ruta a mano del paso «Dispositivo»."""
    return next(iter(widgets(wiz.cuerpo, ttk.Entry)), None)


def indicador(wiz):
    """Devuelve `(barra puesta, frase)` de la línea de espera del paso.

    La línea es la de `tk.Indicador`: una barra y una frase. Sin línea a la
    vista, `(False, '')`.
    """
    for barra in widgets(wiz.cuerpo, ttk.Progressbar):
        linea = barra.master
        if not linea.winfo_manager():
            continue
        frase = next((str(l.cget("text")) for l in linea.winfo_children()
                      if isinstance(l, ttk.Label)), "")
        return bool(barra.winfo_manager()), frase
    return False, ""


def sondeo_de(w):
    """Devuelve el `Sondeo` que un paso cuelga de ese marco, o `None`."""
    return getattr(w, "sondeo", None) if w is not None else None


def escribir_ruta(wiz, texto) -> None:
    """Escribe una ruta en la caja de la ruta a mano."""
    caja = entrada_ruta(wiz)
    caja.delete(0, "end")
    caja.insert(0, str(texto))


def elegir_fila(wiz, iid) -> None:
    """Elige una fila de la lista como lo haría un clic: el evento llega al mover el bucle."""
    arbol(wiz).selection_set(iid)
    raiz.update()


def dar_vueltas(condicion, limite: float = 2.0) -> bool:
    """Mueve el bucle de Tk hasta que se cumpla la condición o pase el límite."""
    fin = time.monotonic() + limite
    while time.monotonic() < fin:
        raiz.update()
        if condicion():
            return True
        time.sleep(0.01)
    return False


class AMano:
    """Un `lanzar()` que deja cada encargo sin correr hasta que el test lo suelta.

    Attributes:
        encargos: Los encargos pedidos, en orden.
    """

    def __init__(self) -> None:
        """Empieza sin encargos."""
        self.encargos: list[segundo_plano.Encargo] = []

    def __call__(self, funcion) -> segundo_plano.Encargo:
        """Apunta el encargo sin correrlo."""
        encargo = segundo_plano.Encargo(funcion)
        self.encargos.append(encargo)
        return encargo

    def ultimo(self) -> segundo_plano.Encargo:
        """Devuelve el último encargo pedido (uno vacío si no se ha pedido ninguno)."""
        return self.encargos[-1] if self.encargos else segundo_plano.Encargo(lambda: None)


def con_lanzar(funcion) -> None:
    """Pone ese `lanzar()` y olvida las lecturas vivas del anterior."""
    segundo_plano.lanzar = funcion
    segundo_plano.olvidar_lecturas()


def nuevo_asistente(dispositivo=None, selected=("p0", "p1")):
    """Devuelve un asistente con la conexión y el catálogo ya dados por buenos."""
    root = tk.Toplevel(raiz)
    root.withdraw()
    wiz = tk_install.build(root)
    wiz.perfil = PERFIL
    wiz.catalog = remote.parse_catalog(CATALOGO)
    wiz.rclone = remote.Rclone("RCLONE", "CONF", remote_name="nas")
    wiz.binario = str(RCLONE_FALSO)
    wiz.state.device = dispositivo
    wiz.state.device_root = dispositivo
    wiz.state.selected = list(selected)
    return wiz


def en_paso(wiz, indice) -> None:
    """Lleva el asistente a ese paso y lo pinta."""
    wiz.indice = indice
    wiz.repintar()


def fuera_del_hilo_de_tk(nombre) -> tuple[bool, bool]:
    """Devuelve si se llamó y si ninguna llamada fue en el hilo de Tk."""
    llamadas = hilos.get(nombre, [])
    return bool(llamadas), all(h != HILO_TK for h in llamadas)


# 1. «Dispositivo» se pinta sin leer: un encargo que no termina nunca
con_lanzar(segundo_plano.Encargo)
hilos.clear()
wiz = nuevo_asistente(UNIDAD_A)
en_paso(wiz, PASO["Dispositivo"])
c("«Dispositivo» se pinta sin preguntar las unidades en el clic",
  hilos.get("list_volumes", []), [])
c("  con la lista vacía", arbol(wiz).get_children() if arbol(wiz) else "sin lista", ())
c("  y la línea «Buscando unidades…» con su barra", indicador(wiz),
  (True, "Buscando unidades…"))
c("  «Actualizar lista» apagado mientras lee", estado_de(wiz, "Actualizar lista"),
  "disabled")
c("  y «Siguiente» también: la unidad de antes no vale hasta verla en la lista",
  (siguiente(wiz), wiz.state.device), ("disabled", None))
wiz.root.destroy()


# 2. Con hilos de verdad, nada de lo que lee corre en el hilo de Tk
con_lanzar(LANZAR_REAL)
hilos.clear()
wiz = nuevo_asistente(UNIDAD_A)
en_paso(wiz, PASO["Dispositivo"])
llego = dar_vueltas(lambda: bool(arbol(wiz).get_children()))
c("la lista de unidades llega", llego, True)
c("  preguntada fuera del hilo de Tk", fuera_del_hilo_de_tk("list_volumes"), (True, True))
c("  con las dos unidades", arbol(wiz).get_children(), (str(UNIDAD_A), str(UNIDAD_B)))
c("  y vuelve a quedar elegida la que ya lo estaba",
  (arbol(wiz).selection(), wiz.state.device), ((str(UNIDAD_A),), UNIDAD_A))
c("  sin la línea de espera", indicador(wiz), (False, ""))
c("  con «Actualizar lista» y «Siguiente» encendidos",
  (estado_de(wiz, "Actualizar lista"), siguiente(wiz)), ("normal", "normal"))

hilos.clear()
puerta_lista.clear()
boton(wiz, "Actualizar lista").invoke()
c("«Actualizar lista» lee igual: la lista se vacía y lo dice",
  (arbol(wiz).get_children(), indicador(wiz)[1], estado_de(wiz, "Actualizar lista"),
   siguiente(wiz)),
  ((), "Buscando unidades…", "disabled", "disabled"))
puerta_lista.set()
dar_vueltas(lambda: bool(arbol(wiz).get_children()))
c("  y al llegar deja elegida la de antes, leída fuera del hilo de Tk",
  (fuera_del_hilo_de_tk("list_volumes"), wiz.state.device), ((True, True), UNIDAD_A))

# La ruta a mano: `is_dir()` y `volume_for()`, también en el hilo.
A_MANO = tmpdir("prdrive-asis-mano-")
is_dir_real = Path.is_dir


def is_dir_apuntado(self, *a, **k):
    """Apunta el hilo cuando se pregunta por la ruta a mano."""
    if str(self) == str(A_MANO):
        hilos.setdefault("is_dir", []).append(threading.get_ident())
    return is_dir_real(self, *a, **k)


Path.is_dir = is_dir_apuntado
try:
    escribir_ruta(wiz, A_MANO)
    boton(wiz, "Usar esta ruta").invoke()
    llego = dar_vueltas(lambda: wiz.state.device == A_MANO)
finally:
    Path.is_dir = is_dir_real
c("«Usar esta ruta» deja la ruta como destino", (llego, wiz.state.device), (True, A_MANO))
c("  mirando si es carpeta fuera del hilo de Tk", fuera_del_hilo_de_tk("is_dir"),
  (True, True))
c("  y su unidad también", fuera_del_hilo_de_tk("volume_for"), (True, True))
c("  dice el destino", f"Destino: {A_MANO}" in textos(wiz), True)
c("  y quita la fila elegida", arbol(wiz).selection(), ())
raiz.update()
c("la ruta a mano gana a la fila elegida antes, también cuando llega el evento de la lista",
  (wiz.state.device, siguiente(wiz)), (A_MANO, "normal"))

# Una ruta que no existe no deja nada a medias: lo dice y vuelve lo de antes.
elegir_fila(wiz, str(UNIDAD_B))
c("elegir una fila la deja como destino", wiz.state.device, UNIDAD_B)
dichos.clear()
escribir_ruta(wiz, A_MANO / "no-existe")
boton(wiz, "Usar esta ruta").invoke()
dar_vueltas(lambda: bool(dichos))
c("una ruta que no existe lo dice", any("No existe la carpeta" in d for d in dichos), True)
raiz.update()
c("  y deja la fila de antes, elegida y como destino",
  (arbol(wiz).selection(), wiz.state.device, siguiente(wiz)),
  ((str(UNIDAD_B),), UNIDAD_B, "normal"))
wiz.root.destroy()

# Dos pulsaciones de «Usar esta ruta» mientras se mira la ruta, y la ruta no vale:
# vuelve la elección de ANTES de la primera pulsación, no el estado intermedio.
lanzar_previo = segundo_plano.lanzar
con_lanzar(LANZAR_REAL)
wiz = nuevo_asistente(UNIDAD_A)
en_paso(wiz, PASO["Dispositivo"])
dar_vueltas(lambda: bool(arbol(wiz).get_children()))
elegir_fila(wiz, str(UNIDAD_B))
dichos.clear()
amano = AMano()
con_lanzar(amano)
escribir_ruta(wiz, A_MANO / "no-existe")
boton(wiz, "Usar esta ruta").invoke()
boton(wiz, "Usar esta ruta").invoke()        # la segunda, con la primera aún pendiente
c("con la ruta pendiente, la segunda pulsación no la vuelve a encargar",
  len(amano.encargos), 1)
amano.ultimo().correr()                       # llega el resultado: la ruta no vale
dar_vueltas(lambda: bool(dichos))
raiz.update()
c("la ruta que no vale se dice, y vuelve la unidad de ANTES de la primera pulsación",
  (any("No existe la carpeta" in d for d in dichos), wiz.state.device,
   arbol(wiz).selection(), siguiente(wiz)),
  (True, UNIDAD_B, (str(UNIDAD_B),), "normal"))
c("  sin ningún callback de Tk fallido", errores, [])
wiz.root.destroy()
con_lanzar(lanzar_previo)

# Una segunda tanda de «Usar esta ruta». Vuelve la elección de ANTES de la
# primera pulsación de la tanda: ni la ruta buena de la tanda anterior, ni la fila
# que se eligió en medio, ni lo que dejó «Actualizar lista».
real_antes = segundo_plano.lanzar

amano = AMano()
con_lanzar(amano)
wiz = nuevo_asistente(UNIDAD_A)
en_paso(wiz, PASO["Dispositivo"])
amano.ultimo().correr()
dar_vueltas(lambda: bool(arbol(wiz).get_children()))
escribir_ruta(wiz, A_MANO)
boton(wiz, "Usar esta ruta").invoke()
amano.ultimo().correr()
dar_vueltas(lambda: wiz.state.device == A_MANO)
c("primera tanda: una ruta que vale queda como destino", wiz.state.device, A_MANO)
dichos.clear()
escribir_ruta(wiz, A_MANO / "no-existe")
boton(wiz, "Usar esta ruta").invoke()
amano.ultimo().correr()
dar_vueltas(lambda: bool(dichos))
raiz.update()
c("segunda tanda: una ruta que no vale lo dice",
  any("No existe la carpeta" in d for d in dichos), True)
c("  y vuelve la ruta buena de la primera tanda, no la unidad de antes",
  (wiz.state.device, siguiente(wiz)), (A_MANO, "normal"))
wiz.root.destroy()

amano = AMano()
con_lanzar(amano)
wiz = nuevo_asistente(UNIDAD_A)
en_paso(wiz, PASO["Dispositivo"])
amano.ultimo().correr()
dar_vueltas(lambda: bool(arbol(wiz).get_children()))
dichos.clear()
escribir_ruta(wiz, A_MANO / "pendiente")
boton(wiz, "Usar esta ruta").invoke()
pendiente = amano.ultimo()
elegir_fila(wiz, str(UNIDAD_B))
c("pulsar y elegir una fila deja la fila como destino",
  (wiz.state.device, siguiente(wiz)), (UNIDAD_B, "normal"))
pendiente.correr()
dar_vueltas(lambda: False, 0.2)
c("  y la ruta que llega después no se dice ni pisa la fila",
  (wiz.state.device, dichos, arbol(wiz).selection()), (UNIDAD_B, [], (str(UNIDAD_B),)))
escribir_ruta(wiz, A_MANO / "no-existe-b")
boton(wiz, "Usar esta ruta").invoke()
amano.ultimo().correr()
dar_vueltas(lambda: bool(dichos))
raiz.update()
c("volver a pulsar con una ruta que no vale vuelve a esa fila",
  (wiz.state.device, arbol(wiz).selection(), siguiente(wiz)),
  (UNIDAD_B, (str(UNIDAD_B),), "normal"))
wiz.root.destroy()

amano = AMano()
con_lanzar(amano)
wiz = nuevo_asistente(UNIDAD_A)
en_paso(wiz, PASO["Dispositivo"])
amano.ultimo().correr()
dar_vueltas(lambda: bool(arbol(wiz).get_children()))
escribir_ruta(wiz, A_MANO / "pendiente-c")
boton(wiz, "Usar esta ruta").invoke()
pendiente = amano.ultimo()
boton(wiz, "Actualizar lista").invoke()
amano.ultimo().correr()
dar_vueltas(lambda: bool(arbol(wiz).get_children()))
pendiente.correr()
dar_vueltas(lambda: False, 0.2)
c("«Actualizar lista» deja la lista sin destino, y la ruta pendiente no vuelve",
  (wiz.state.device, arbol(wiz).selection(), siguiente(wiz)), (None, (), "disabled"))
dichos.clear()
escribir_ruta(wiz, A_MANO / "no-existe-c")
boton(wiz, "Usar esta ruta").invoke()
amano.ultimo().correr()
dar_vueltas(lambda: bool(dichos))
raiz.update()
c("después, una ruta que no vale vuelve a lo que dejó la lista: sin destino",
  (wiz.state.device, arbol(wiz).selection(), siguiente(wiz)), (None, (), "disabled"))
c("  sin ningún callback de Tk fallido", errores, [])
wiz.root.destroy()
con_lanzar(real_antes)

# «Comprobaciones»: el Python del equipo va en el trabajo de «Comprobar».
hilos.clear()
wiz = nuevo_asistente(UNIDAD_A)
wiz.catalog = wiz.rclone = None
wiz.conf = SimpleNamespace(path="CONF", close=lambda: None)
en_paso(wiz, PASO["Comprobaciones"])
c("«Comprobaciones» se pinta sin preguntar por el Python del equipo",
  hilos.get("check_python", []), [])
boton(wiz, "Comprobar").invoke()
c("«Comprobar» pregunta por el Python del equipo fuera del hilo de Tk",
  fuera_del_hilo_de_tk("check_python"), (True, True))
c("  y lo guarda en el asistente", getattr(wiz, "python_equipo", None),
  device.Check("Python en este equipo", True, "el de mentira (con Tkinter)"))
c("  y lo enseña", "el de mentira (con Tkinter)" in textos(wiz), True)
c("  con el remoto comprobado", siguiente(wiz), "normal")
llamadas = len(hilos["check_python"])
en_paso(wiz, PASO["Comprobaciones"])
c("pintar el paso otra vez enseña lo guardado sin volver a preguntar",
  (len(hilos["check_python"]), "el de mentira (con Tkinter)" in textos(wiz)),
  (llamadas, True))

check_python_bueno = device.check_python


def check_python_roto(root=None):
    """Un Python del equipo que no se deja preguntar."""
    raise OSError("el lanzador de Python no contesta")


device.check_python = check_python_roto
wiz.catalog = wiz.rclone = None
en_paso(wiz, PASO["Comprobaciones"])
boton(wiz, "Comprobar").invoke()
vistos = textos(wiz)
c("si el Python del equipo falla, el remoto sigue comprobado",
  (wiz.catalog is not None, siguiente(wiz)), (True, "normal"))
c("  y su fila sale «sin comprobar»",
  "Python en este equipo" in vistos and "sin comprobar" in vistos, True)
device.check_python = check_python_bueno

# «Parejas y configuración»: la nota de la flota va por `working()`.
working_real = tk_install.working
titulos: list[str] = []


def working_apuntado(parent, titulo, funcion, mensaje="", progreso=None):
    """Apunta el título y deja hacer al `working()` de verdad."""
    titulos.append(titulo)
    return working_real(parent, titulo, funcion, mensaje, progreso)


tk_install.working = working_apuntado
try:
    hilos.clear()
    dispositivo = tmpdir("prdrive-asis-parejas-")
    wiz.state.device = wiz.state.device_root = dispositivo
    en_paso(wiz, PASO["Parejas y configuración"])
    boton(wiz, "Guardar el config y crear las carpetas").invoke()
    c("la nota de la flota se publica dentro de `working()`", titulos, ["flota"])
    c("  fuera del hilo de Tk", fuera_del_hilo_de_tk("publish_fleet_note"), (True, True))
    c("  y se dice dónde quedó",
      any("Apuntado en la flota: nas:/prdrive-catalog/flota/x.toml." in t
          for t in textos(wiz)), True)
    c("  con el config escrito", (wiz.state.config_written, siguiente(wiz)),
      (True, "normal"))
    tk_install.working = lambda parent, titulo, funcion, mensaje="", progreso=None: (
        False, RuntimeError("se cerró"))
    en_paso(wiz, PASO["Parejas y configuración"])
    boton(wiz, "Guardar el config y crear las carpetas").invoke()
    c("si `working()` falla, la nota queda para la primera pasada",
      any("No se ha podido apuntar en la flota" in t for t in textos(wiz)), True)
finally:
    tk_install.working = working_real
wiz.root.destroy()

# «Verificación»: la tabla llega del hilo.
hilos.clear()
wiz = nuevo_asistente(UNIDAD_A)
en_paso(wiz, PASO["Verificación"])
llego = dar_vueltas(lambda: "Comprobación 0" in textos(wiz))
c("la verificación llega", llego, True)
c("  preguntada fuera del hilo de Tk", fuera_del_hilo_de_tk("verify_device"), (True, True))
c("  sin la línea de espera", indicador(wiz), (False, ""))
c("  y con «Volver a comprobar» y «Desmontar el contenedor» encendidos",
  (estado_de(wiz, "Volver a comprobar"), estado_de(wiz, "Desmontar el contenedor")),
  ("normal", "normal"))
hilos.clear()
boton(wiz, "Volver a comprobar").invoke()
dar_vueltas(lambda: bool(hilos.get("verify_device")) and not indicador(wiz)[0])
c("«Volver a comprobar» vuelve a mirar fuera del hilo de Tk",
  fuera_del_hilo_de_tk("verify_device"), (True, True))
c("  y deja una sola tabla", textos(wiz).count("Comprobación 0"), 1)
wiz.root.destroy()


# Lo que mira el hilo de la verificación: con VeraCrypt, también la unidad de
# fuera (la entrada, el VeraCrypt que viaja y los restos en claro).
mirado: list = []
reales_vc = (tk_install.vestibulo.comprobar, tk_install.traveler.comprobar,
             tk_install.crypto.comprobar_restos)
tk_install.vestibulo.comprobar = lambda unidad, ident: (
    mirado.append(("entrada", unidad, ident)) or [device.Check("Entrada", True, "")])
tk_install.traveler.comprobar = lambda unidad: (
    mirado.append(("viajero", unidad)) or [device.Check("VeraCrypt", True, "")])
tk_install.crypto.comprobar_restos = lambda unidad: (
    mirado.append(("restos", unidad)) or [device.Check("Restos", "aviso", "x")])
comprobaciones = getattr(lecturas_asistente, "comprobaciones_dispositivo",
                         lambda *a: [("no existe comprobaciones_dispositivo", False, "")])
try:
    filas = comprobaciones(UNIDAD_A, ["p0"], None, "veracrypt", UNIDAD_B)
    c("con VeraCrypt, la verificación mira también la unidad de fuera",
      ([f[0] for f in filas][-3:], [m[:2] for m in mirado]),
      (["Entrada", "VeraCrypt", "Restos"],
       [("entrada", UNIDAD_B), ("viajero", UNIDAD_B), ("restos", UNIDAD_B)]))
    c("  y devuelve filas de datos: nombre, estado y detalle", filas[-1],
      ("Restos", "aviso", "x"))
    mirado.clear()
    filas = comprobaciones(UNIDAD_A, ["p0"], None, "none", UNIDAD_B)
    c("  sin contenedor, solo el dispositivo", (len(filas), mirado),
      (COMPROBACIONES["n"], []))
finally:
    (tk_install.vestibulo.comprobar, tk_install.traveler.comprobar,
     tk_install.crypto.comprobar_restos) = reales_vc


# 3. Lo que llega tarde: solo cuenta la última elección
a_mano = AMano()
con_lanzar(a_mano)

wiz = nuevo_asistente(UNIDAD_A)
en_paso(wiz, PASO["Dispositivo"])
lista = a_mano.ultimo()
escribir_ruta(wiz, A_MANO)
boton(wiz, "Usar esta ruta").invoke()
ruta = a_mano.ultimo()
c("«Usar esta ruta» se mira aparte de la lista", ruta is not lista, True)
ruta.correr()
dar_vueltas(lambda: wiz.state.device == A_MANO)
c("una ruta a mano mientras se busca la lista queda como destino",
  wiz.state.device, A_MANO)
lista.correr()
dar_vueltas(lambda: bool(arbol(wiz).get_children()))
raiz.update()
c("la lista que llega tarde no pisa la ruta a mano",
  (bool(arbol(wiz).get_children()), wiz.state.device, arbol(wiz).selection(),
   siguiente(wiz)),
  (True, A_MANO, (), "normal"))
c("  que sigue diciéndose", f"Destino: {A_MANO}" in textos(wiz), True)
wiz.root.destroy()

wiz = nuevo_asistente(UNIDAD_A)
en_paso(wiz, PASO["Dispositivo"])
a_mano.ultimo().correr()
dar_vueltas(lambda: bool(arbol(wiz).get_children()))
c("sin nada a mano, al llegar la lista vuelve la unidad de antes",
  (wiz.state.device, siguiente(wiz)), (UNIDAD_A, "normal"))
escribir_ruta(wiz, A_MANO)
boton(wiz, "Usar esta ruta").invoke()
ruta = a_mano.ultimo()
c("mientras se mira la ruta, «Siguiente» no deja seguir con la unidad de antes",
  (siguiente(wiz), wiz.state.device), ("disabled", None))
c("  y el destino dice que se está mirando", "Comprobando la ruta…" in textos(wiz), True)
elegir_fila(wiz, str(UNIDAD_B))
c("elegir otra fila mientras tanto la deja como destino",
  (wiz.state.device, siguiente(wiz)), (UNIDAD_B, "normal"))
ruta.correr()
dar_vueltas(lambda: False, 0.3)
c("una ruta a mano que llega tarde no pisa la fila elegida después",
  (wiz.state.device, arbol(wiz).selection(), siguiente(wiz)),
  (UNIDAD_B, (str(UNIDAD_B),), "normal"))
c("  ni el destino que se dice", f"Destino: {UNIDAD_B}" in textos(wiz)
  and f"Destino: {A_MANO}" not in textos(wiz), True)

escribir_ruta(wiz, A_MANO)
boton(wiz, "Usar esta ruta").invoke()
ruta = a_mano.ultimo()
boton(wiz, "Actualizar lista").invoke()
lista = a_mano.ultimo()
ruta.correr()
dar_vueltas(lambda: False, 0.3)
c("«Actualizar lista» también deja atrás una ruta que aún se miraba",
  (wiz.state.device, siguiente(wiz)), (None, "disabled"))
lista.correr()
dar_vueltas(lambda: bool(arbol(wiz).get_children()))
c("  y al llegar la lista no elige nada por su cuenta",
  (wiz.state.device, arbol(wiz).selection()), (None, ()))
wiz.root.destroy()

# Cambiar de paso con una lectura en vuelo: ni espera pendiente ni llegada.
llegadas: list = []


def espiar(sondeo):
    """Envuelve lo que el sondeo llamará al llegar, para ver si llega."""
    if sondeo is None or sondeo._al_llegar is None:
        return
    original = sondeo._al_llegar
    sondeo._al_llegar = lambda encargo: (llegadas.append(encargo), original(encargo))


wiz = nuevo_asistente(UNIDAD_A)
en_paso(wiz, PASO["Dispositivo"])
lista = a_mano.ultimo()
sondeo_lista = sondeo_de(arbol(wiz).master)
escribir_ruta(wiz, A_MANO)
boton(wiz, "Usar esta ruta").invoke()
ruta = a_mano.ultimo()
sondeo_ruta = sondeo_de(entrada_ruta(wiz).master)
c("el paso cuelga sus dos esperas de sus marcos, y esperan",
  (getattr(sondeo_lista, "esperando", None), getattr(sondeo_ruta, "esperando", None)),
  (True, True))
espiar(sondeo_lista)
espiar(sondeo_ruta)
en_paso(wiz, 0)
c("cambiar de paso cancela las dos esperas",
  [(getattr(s, "_id", "?"), getattr(s, "esperando", "?"))
   for s in (sondeo_lista, sondeo_ruta)], [(None, False), (None, False)])
lista.correr()
ruta.correr()
dar_vueltas(lambda: False, 0.3)
c("  y lo que llega después no se recoge", (llegadas, errores), ([], []))
c("  ni toca el destino", wiz.state.device, None)
wiz.root.destroy()

# «Verificación» mientras lee.
wiz = nuevo_asistente(UNIDAD_A)
en_paso(wiz, PASO["Verificación"])
verificacion = a_mano.ultimo()
c("«Verificación» se pinta con su línea de espera", indicador(wiz),
  (True, "Comprobando el dispositivo…"))
c("  sin tabla todavía", "Comprobación 0" in textos(wiz), False)
c("  con «Volver a comprobar» y «Desmontar el contenedor» apagados",
  (estado_de(wiz, "Volver a comprobar"), estado_de(wiz, "Desmontar el contenedor")),
  ("disabled", "disabled"))
c("  y «Llevar VeraCrypt en el dispositivo» encendido",
  estado_de(wiz, "Llevar VeraCrypt en el dispositivo"), "normal")
marco_tabla = next((b.master.master for b in widgets(wiz.cuerpo, ttk.Progressbar)), None)
sondeo_tabla = sondeo_de(marco_tabla)
espiar(sondeo_tabla)
en_paso(wiz, 0)
c("cambiar de paso cancela la espera de la verificación",
  (getattr(sondeo_tabla, "_id", "?"), getattr(sondeo_tabla, "esperando", "?")),
  (None, False))
verificacion.correr()
dar_vueltas(lambda: False, 0.3)
c("  y lo que llega después no se recoge", (llegadas, errores), ([], []))
wiz.root.destroy()


# 3b. Una lectura que falla se dice y no deja el paso a medias
con_lanzar(segundo_plano.en_el_acto)


def que_falle(nombre: str, mensaje: str):
    """Devuelve una función que lanza `OSError(mensaje)` y apunta que se llamó."""
    def falla(*a, **k):
        """Falla como lo haría un lector, una red o un disco que no contestan."""
        raise OSError(mensaje)
    return apuntar(nombre, falla)


list_volumes_real = device.list_volumes
device.list_volumes = que_falle("list_volumes", "el lector no contesta")
try:
    wiz = nuevo_asistente(UNIDAD_A)
    en_paso(wiz, PASO["Dispositivo"])
    c("si la lista de unidades falla, el paso lo dice con un aviso",
      indicador(wiz), (False, "No se han podido leer las unidades: el lector no contesta"))
    c("  deja la lista vacía y sin destino",
      (arbol(wiz).get_children(), wiz.state.device, siguiente(wiz)),
      ((), None, "disabled"))
    c("  y «Actualizar lista» vuelve a estar encendido", estado_de(wiz, "Actualizar lista"),
      "normal")
    device.list_volumes = list_volumes_real
    boton(wiz, "Actualizar lista").invoke()
    c("  y leer otra vez, con el lector de vuelta, trae la lista",
      (arbol(wiz).get_children(), indicador(wiz)),
      ((str(UNIDAD_A), str(UNIDAD_B)), (False, "")))
    wiz.root.destroy()
finally:
    device.list_volumes = list_volumes_real

volume_for_real = device.volume_for
device.volume_for = que_falle("volume_for", "la carpeta de red no contesta")
try:
    wiz = nuevo_asistente(UNIDAD_A)
    en_paso(wiz, PASO["Dispositivo"])
    dichos.clear()
    escribir_ruta(wiz, A_MANO)
    boton(wiz, "Usar esta ruta").invoke()
    c("si mirar la ruta a mano falla, lo dice",
      any("No se ha podido mirar" in d and "la carpeta de red no contesta" in d
          for d in dichos), True)
    c("  y vuelve lo de antes, como destino y con «Siguiente» encendido",
      (wiz.state.device, arbol(wiz).selection(), siguiente(wiz)),
      (UNIDAD_A, (str(UNIDAD_A),), "normal"))
    wiz.root.destroy()
finally:
    device.volume_for = volume_for_real

verify_device_real = device.verify_device
device.verify_device = que_falle("verify_device", "el dispositivo no contesta")
try:
    wiz = nuevo_asistente(UNIDAD_A)
    en_paso(wiz, PASO["Verificación"])
    c("si la verificación falla, el paso lo dice con un aviso y sin tabla",
      (indicador(wiz), "Comprobación 0" in textos(wiz)),
      ((False, "No se ha podido comprobar el dispositivo: el dispositivo no contesta"),
       False))
    c("  y se puede volver a comprobar",
      (estado_de(wiz, "Volver a comprobar"), estado_de(wiz, "Desmontar el contenedor")),
      ("normal", "normal"))
    device.verify_device = verify_device_real
    boton(wiz, "Volver a comprobar").invoke()
    c("  y volver a comprobar, con el dispositivo de vuelta, pinta la tabla",
      ("Comprobación 0" in textos(wiz), indicador(wiz)), (True, (False, "")))
    wiz.root.destroy()
finally:
    device.verify_device = verify_device_real
c("  sin ningún callback de Tk fallido", errores, [])


# El Python comprobado es de un recorrido y de una conexión: al soltar una, o al
# cambiar de recorrido, no se enseña en el otro.
lanzar_previo = segundo_plano.lanzar
con_lanzar(LANZAR_REAL)
wiz = nuevo_asistente(UNIDAD_A)
wiz.catalog = wiz.rclone = None
wiz.conf = SimpleNamespace(path="CONF", close=lambda: None)
en_paso(wiz, PASO["Comprobaciones"])
boton(wiz, "Comprobar").invoke()
c("«Comprobar» en una unidad guarda el Python comprobado", wiz.python_equipo is not None, True)
wiz.soltar_conexion()
c("soltar la conexión suelta también el Python comprobado", wiz.python_equipo, None)
wiz.conf = SimpleNamespace(path="CONF", close=lambda: None)
wiz.rclone = remote.Rclone("RCLONE", "CONF", remote_name="nas")
wiz.catalog = remote.parse_catalog(CATALOGO)
boton(wiz, "Comprobar").invoke()
en_paso(wiz, PASO["¿Dónde?"])
next(b for b in widgets(wiz.cuerpo, ttk.Radiobutton) if b.cget("text") == "En este equipo").invoke()
c("cambiar a «En este equipo» olvida el Python comprobado de la unidad",
  wiz.python_equipo, None)
next(b for b in widgets(wiz.cuerpo, ttk.Radiobutton) if b.cget("text") == "En una unidad").invoke()
en_paso(wiz, PASO["Comprobaciones"])
vistos = textos(wiz)
c("volver a «En una unidad» no enseña un Python que no se ha comprobado allí",
  ("el de mentira (con Tkinter)" in vistos, "Python en este equipo" in vistos),
  (False, True))
wiz.root.destroy()
con_lanzar(lanzar_previo)

# Cerrar el asistente con una medida de escritura en vuelo: se espera a que
# acabe y quite su temporal, antes de que el proceso termine.
medir_real = crypto.medir_escritura


def medir_lenta(root, muestra=0):
    """Una medida que tarda: deja su temporal mientras escribe y lo quita al acabar."""
    temporal = Path(root) / crypto.SONDA_NOMBRE
    try:
        temporal.write_bytes(b"\0" * 4096)
        time.sleep(0.4)
        return 10 * 1024 ** 2
    finally:
        temporal.unlink(missing_ok=True)


crypto.medir_escritura = medir_lenta
lanzar_previo = segundo_plano.lanzar
try:
    con_lanzar(LANZAR_REAL)
    wiz = nuevo_asistente(UNIDAD_A)
    temporal = UNIDAD_A / crypto.SONDA_NOMBRE
    sonda = lecturas_asistente.sonda_de(wiz.state)
    dar_vueltas(temporal.exists)
    wiz.root.destroy()
    tk_install.cerrar(wiz)
    c("cerrar el asistente espera a la medida que escribe", sonda.encargo.hecho, True)
    c("  y su temporal no queda en la unidad", temporal.exists(), False)
finally:
    crypto.medir_escritura = medir_real
    con_lanzar(lanzar_previo)


# El asistente cerrado desde su propio bucle (`run_wizard()`, que es lo que pasa
# al cerrar la ventana): la medida en vuelo se espera, y su temporal no se queda
# en la unidad. El bucle de Tk se sustituye por uno que deja la medida corriendo
# y destruye la raíz, como si la persona cerrase la ventana en ese momento.
ventanas: list = []                     # los asistentes que construye `run_wizard()`
cierres: list = []                      # (sonda, si el temporal existía al cerrar)
cierres_conf: list = []                 # cada close() del rclone.conf del asistente
build_real, tk_raiz_real = tk_install.build, tk.Tk


def build_que_guarda(root):
    """Construye el asistente de verdad y se queda con él para el test."""
    wiz_ = build_real(root)
    ventanas.append(wiz_)
    return wiz_


class RaizQueSeCierra(tk_raiz_real):
    """Una raíz cuyo bucle se acaba al momento."""

    def mainloop(self, n=0):
        """Deja una medida en vuelo sobre la unidad y destruye la ventana."""
        estado = ventanas[-1].state
        estado.device = str(UNIDAD_A)
        temporal_ = UNIDAD_A / crypto.SONDA_NOMBRE
        temporal_.unlink(missing_ok=True)
        sonda_ = lecturas_asistente.sonda_de(estado)
        fin = time.monotonic() + 2.0
        while not temporal_.exists() and time.monotonic() < fin:
            time.sleep(0.01)
        cierres.append((sonda_, temporal_.exists()))
        ventanas[-1].conf = SimpleNamespace(path="CONF",
                                            close=lambda: cierres_conf.append("close"))
        self.destroy()


lanzar_previo = segundo_plano.lanzar
tk.Tk = RaizQueSeCierra
tk_install.build = build_que_guarda
crypto.medir_escritura = medir_lenta
try:
    con_lanzar(LANZAR_REAL)
    rc_bucle = tk_install.run_wizard()
finally:
    tk.Tk = tk_raiz_real
    tk_install.build = build_real
    crypto.medir_escritura = medir_real
    con_lanzar(lanzar_previo)
sonda_bucle, existia_al_cerrar = cierres[0]
c("el asistente cerrado desde su bucle devuelve 0", rc_bucle, 0)
c("  con la medida todavía escribiendo al cerrar la ventana", existia_al_cerrar, True)
c("  y al volver, la medida ya acabó", sonda_bucle.encargo.hecho, True)
c("  y su temporal no queda en la unidad", (UNIDAD_A / crypto.SONDA_NOMBRE).exists(), False)
c("  y cierra el rclone.conf efímero de la conexión, una sola vez", cierres_conf, ["close"])


# 4. Lo que cabe en cada paso
con_lanzar(segundo_plano.en_el_acto)
tk_install.working = lambda parent, titulo, funcion, mensaje="", progreso=None: (
    True, funcion())


def contar(wiz) -> int:
    """Devuelve cuántos widgets cuelgan del cuerpo del paso."""
    return len(widgets(wiz.cuerpo))


TOPE = 40
"""Los widgets que puede tener el cuerpo de un paso (R5)."""

# Un dispositivo sin instalar (`.prdrive` solo, con su VERSION para la pantalla
# de actualizar, se lee como vacío), en la lista de unidades y elegido.
dispositivo = tmpdir("prdrive-asis-cuenta-")
(dispositivo / ".prdrive").mkdir()
(dispositivo / ".prdrive" / "VERSION").write_text("0.0.1", encoding="utf-8")
VOLUMENES.insert(0, device.Volume(root=dispositivo, label="PRDRIVE", filesystem="exFAT",
                                  drive_type="Removable", size=8 * 2 ** 30,
                                  free=7 * 2 ** 30))
cuentas: dict[str, int] = {}
for recorrido, pasos in (("instalación", tk_install.PASOS_INSTALACION),
                         ("actualización", tk_install.PASOS_ACTUALIZACION),
                         ("plataformas", tk_install.PASOS_PLATAFORMAS)):
    wiz = nuevo_asistente(dispositivo)
    for i, (titulo, _, _) in enumerate(pasos):
        if titulo == "Verificación":
            continue
        # «Dispositivo» rehace la lista de pasos y la elección: cada paso, con
        # la suya.
        wiz.pasos = pasos
        wiz.state.device = wiz.state.device_root = dispositivo
        en_paso(wiz, i)
        cuentas[f"{recorrido} · {titulo}"] = n = contar(wiz)
        c(f"«{titulo}» ({recorrido}) cabe en {TOPE} widgets: {n}", n <= TOPE, True)
    wiz.root.destroy()

# «Verificación» crece con sus filas: una más son 4 widgets (nombre, chip,
# detalle y la línea que la separa de la anterior).
wiz = nuevo_asistente(dispositivo)
por_filas = {}
for n in (8, 9):
    COMPROBACIONES["n"] = n
    en_paso(wiz, PASO["Verificación"])
    por_filas[n] = contar(wiz)
fija = por_filas[8] - (4 * 8 - 1)
c(f"«Verificación»: una comprobación más son 4 widgets ({por_filas[8]} → {por_filas[9]})",
  por_filas[9] - por_filas[8], 4)
c(f"  sobre una parte fija de 13 como mucho, con su línea de espera: {fija}",
  fija <= 13, True)
COMPROBACIONES["n"] = 3
wiz.root.destroy()
print(f"  widgets por paso: {cuentas}; «Verificación» fija {fija} + 4 por fila − 1")

# «Conexión»: el formulario de importar se hace la primera vez que se elige.
wiz = nuevo_asistente(dispositivo)
en_paso(wiz, PASO["Conexión"])
sin_importar = contar(wiz)


def radio(wiz, prefijo):
    """Devuelve el radiobutton del paso cuyo texto empieza así."""
    return next(r for r in widgets(wiz.cuerpo, ttk.Radiobutton)
                if str(r.cget("text")).startswith(prefijo))


caja_opciones = widgets(wiz.cuerpo, tk.Text)[0]
caja_opciones.delete("1.0", "end")
caja_opciones.insert("1.0", "host = mi.nas\n")
radio(wiz, "Importar").invoke()
con_importar = contar(wiz)
c(f"«Conexión» se pinta sin el formulario de importar ({sin_importar} widgets)",
  con_importar > sin_importar, True)
caja_conf = next(e for e in widgets(wiz.cuerpo, ttk.Entry)
                 if not isinstance(e, ttk.Combobox)
                 and e.winfo_manager() and e.master.winfo_manager()
                 and e.master.master.winfo_manager()
                 and "rclone.conf" in " ".join(str(l.cget("text"))
                                               for l in e.master.winfo_children()
                                               if isinstance(l, ttk.Label)))
caja_conf.insert(0, "/home/alguien/.config/rclone/rclone.conf")
radio(wiz, "Configurar").invoke()
c("  volver a «nuevo» no lo deshace", contar(wiz), con_importar)
c("  y lo escrito en «nuevo» sigue ahí", caja_opciones.get("1.0", "end").strip(),
  "host = mi.nas")
radio(wiz, "Importar").invoke()
c("  elegir otra vez «importar» no lo rehace", contar(wiz), con_importar)
c("  y lo escrito en él sigue ahí", caja_conf.get(),
  "/home/alguien/.config/rclone/rclone.conf")
wiz.root.destroy()
c("«Conexión» sin «Importar» tiene 34 widgets", sin_importar, 34)
c("  y con «Importar» elegido, 41 (fuera del presupuesto de 40)", con_importar, 41)


def instalacion_en(carpeta) -> int:
    """Cuántos widgets tiene «Instalación» con esa carpeta como destino."""
    wiz = nuevo_asistente(carpeta)
    wiz.pasos = tk_install.PASOS_INSTALACION
    en_paso(wiz, PASO["Instalación"])
    n = contar(wiz)
    wiz.root.destroy()
    return n


vacia = tmpdir("prdrive-asis-vacia-")
con_programa = tmpdir("prdrive-asis-programa-")
(con_programa / ".prdrive").mkdir()
(con_programa / ".prdrive" / "sync.py").write_text("# de mentira\n", encoding="utf-8")
ajena = tmpdir("prdrive-asis-ajena-")
(ajena / "fotos.txt").write_text("mis cosas", encoding="utf-8")
c("«Instalación» en una unidad vacía: 39 widgets", instalacion_en(vacia), 39)
c("  con un prdrive ya puesto (la marca y su botón): 42", instalacion_en(con_programa), 42)
c("  con una unidad ajena (el aviso ámbar): 45", instalacion_en(ajena), 45)

c("ningún callback de Tk ha fallado", errores, [])

raiz.destroy()
sys.exit(c.report())
