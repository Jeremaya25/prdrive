#!/usr/bin/env python3
"""El asistente lee después de pintar: «En este equipo» y la sonda del cifrado.

Lo que se comprueba es lo que cuida los datos de la persona:
- La sonda de escritura de una unidad (8 MiB con `fsync`) corre en otro hilo y
  UNA sola vez por unidad: ni repintar el panel, ni un hilo que acaba sin que
  nadie lo haya mirado, ni volver a la unidad la lanzan otra vez. «Crear y
  montar» está apagado mientras escribe, hasta su tope (`TOPE_SONDA_S`).
- Las carpetas de «En este equipo» se examinan cuando se deja de teclear, fuera
  del hilo de Tk, y un examen que llega para un texto que ya no está escrito no
  cuenta: ni enciende «Siguiente» ni deja crear un contenedor que se montaría
  sobre una carpeta con cosas.
- «Verificación» comprueba en otro hilo, con su indicador.
- En Windows, «Contenedor en» sale con la carpeta propuesta y sigue así cuando
  llega el examen: su variable tiene que seguir viva, o Tk vacía la caja.
- Ningún paso de «En este equipo» pasa de 40 widgets, salvo «Verificación», que
  crece 4 por fila.

Nada toca una unidad ni el equipo de verdad: la sonda, los exámenes de carpeta
y la verificación se sustituyen por apuntadores, y la carpeta del agente va a
un temporal. Donde importa el orden, los `after` de las cajas se mueven a mano
(`Reloj`); donde hay hilos de verdad, el bucle de eventos se mueve hasta que se
cumple la condición, con un tope de 2 s (`dar_vueltas`).
"""

import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

from _harness import Checks, tmpdir

c = Checks("asistente: lecturas fuera del hilo de Tk (en este equipo y la sonda)")

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    raiz = tk.Tk()
    raiz.withdraw()
except Exception as e:                                   # sin entorno gráfico
    print(f"  (saltado) no hay entorno gráfico: {e}")
    sys.exit(0)

import install                                           # noqa: E402
import penwatch                                          # noqa: E402
from common import equipo                                # noqa: E402
from install import agente as ia                         # noqa: E402
from install import crypto, deploy, profile, raiz_equipo, remote  # noqa: E402
from ui import (lecturas_asistente, segundo_plano, tk_crypto, tk_equipo,  # noqa: E402
                tk_install, watch)
from ui import tk as uitk                                # noqa: E402

PRINCIPAL = threading.get_ident()

messagebox.showinfo = lambda *a, **k: None
messagebox.showerror = lambda *a, **k: None
messagebox.showwarning = lambda *a, **k: None
messagebox.askokcancel = lambda *a, **k: True
messagebox.askyesno = lambda *a, **k: True

# Nada del equipo de verdad: la carpeta del agente, penwatch, los clientes de
# sincronización, el bus de sesión y `schtasks`.
equipo.DIR = tmpdir("prdrive-lecturas-agente-")
penwatch.CONFIG_FILE = tmpdir("prdrive-lecturas-pw-") / "watch.json"
raiz_equipo.carpetas_sincronizadas = lambda: []
raiz_equipo.veracrypt_instalado = lambda: None
raiz_equipo.veracrypt_portatil = lambda: None
ia.candidatas = lambda: [ia.Candidata("u" * 32, "PRDRIVE-2", equipo.DAEMON,
                                      "enchufada ahora")]
tk_equipo.escritorio = lambda: (True, True)
watch.consulta = lambda cmd, timeout=None: SimpleNamespace(returncode=1)
tk_install.output_window = lambda titulo, cmd, parent=None: 0
esperas: list[str] = []


def directo(parent, titulo, funcion, mensaje="", progreso=None):
    """Sustituye a `working()`: hace el trabajo en el sitio y apunta su título."""
    esperas.append(titulo)
    return True, funcion()


tk_install.working = tk_crypto.working = tk_equipo.working = directo

CATALOGO = "[defaults]\nremote = \"nas\"\n\n" + "".join(
    f"[[pair]]\nname = \"p{i}\"\nlocal = \"sync-data/p{i}\"\n"
    f"remote_path = \"/datos/p{i}\"\nmode = \"bisync\"\n\n" for i in range(5))
PERFIL = profile.from_form("nas", {"type": "sftp", "host": "nas.example"})
LANZAR_REAL = segundo_plano.lanzar
ESPERA_REAL = getattr(lecturas_asistente, "ESPERA_TECLA_MS", 250)
MIRANDO = "Mirando la carpeta…"


class Pendientes:
    """Un `lanzar()` que no corre nada: guarda cada encargo para soltarlo a mano.

    Attributes:
        encargos: Los encargos lanzados, en orden.
    """

    def __init__(self) -> None:
        """Empieza sin encargos."""
        self.encargos: list = []

    def __call__(self, funcion):
        """Devuelve un encargo sin correrlo."""
        encargo = segundo_plano.Encargo(funcion)
        self.encargos.append(encargo)
        return encargo

    def ultimo(self):
        """El último encargo, o uno vacío si no se ha lanzado ninguno."""
        return self.encargos[-1] if self.encargos else segundo_plano.Encargo(None)


class Reloj:
    """Los `after` de las cajas, a mano: se apuntan y los dispara el test.

    Sustituye `after`/`after_cancel` de `ttk.Entry` mientras dura el `with`, así
    que cubre la espera de cada tecla y el `Sondeo` que cuelga de la caja. Uno
    cuya caja ya no existe no se dispara, como hace Tk.

    Attributes:
        pendientes: `id → (widget, ms, función, argumentos)`.
        plazos: El plazo de cada `after` pedido, en orden.
    """

    def __init__(self) -> None:
        """Empieza sin nada pendiente."""
        self.pendientes: dict = {}
        self.plazos: list[int] = []
        self._n = 0

    def __enter__(self):
        """Pone el reloj a mano en las cajas."""
        reloj = self

        def after(widget, ms, func=None, *args):
            reloj._n += 1
            ident = f"reloj#{reloj._n}"
            reloj.pendientes[ident] = (widget, ms, func, args)
            reloj.plazos.append(ms)
            return ident

        def after_cancel(widget, ident):
            if ident in reloj.pendientes:
                del reloj.pendientes[ident]
            else:
                tk.Misc.after_cancel(widget, ident)

        ttk.Entry.after, ttk.Entry.after_cancel = after, after_cancel
        return self

    def __exit__(self, *_) -> None:
        """Devuelve a las cajas el reloj de Tk."""
        del ttk.Entry.after
        del ttk.Entry.after_cancel

    def de(self, ms: int) -> list:
        """Los pendientes de ese plazo: `(widget, función)`."""
        return [(w, f) for w, plazo, f, _ in self.pendientes.values() if plazo == ms]

    def disparar(self, ms: int) -> int:
        """Dispara los pendientes de ese plazo y devuelve cuántos había."""
        listos = [i for i, v in self.pendientes.items() if v[1] == ms]
        for ident in listos:
            widget, _, func, args = self.pendientes.pop(ident)
            if widget.winfo_exists():
                func(*args)
        return len(listos)


class AfterAnotado:
    """Apunta los `after` de los marcos y cuáles se cancelan, sin cambiarlos.

    Attributes:
        puestos: `id → ms` de cada `after` con función que se ha pedido.
        cancelados: Los ids que se han cancelado.
    """

    def __enter__(self):
        """Empieza a apuntar los `after` de los `ttk.Frame`."""
        self.puestos: dict = {}
        self.cancelados: list = []
        anotado = self

        def after(widget, ms, func=None, *args):
            ident = tk.Misc.after(widget, ms, func, *args)
            if func is not None:
                anotado.puestos[ident] = ms
            return ident

        def after_cancel(widget, ident):
            anotado.cancelados.append(ident)
            return tk.Misc.after_cancel(widget, ident)

        ttk.Frame.after, ttk.Frame.after_cancel = after, after_cancel
        return self

    def __exit__(self, *_) -> None:
        """Devuelve a los marcos el reloj de Tk."""
        del ttk.Frame.after
        del ttk.Frame.after_cancel


def dar_vueltas(condicion, tope: float = 2.0) -> bool:
    """Mueve el bucle de eventos hasta que se cumple la condición, como mucho `tope` s."""
    fin = time.monotonic() + tope
    while time.monotonic() < fin:
        raiz.update()
        if condicion():
            return True
        time.sleep(0.005)
    return bool(condicion())


def widgets(w, tipo=None) -> list:
    """Devuelve los widgets que cuelgan de `w` (sin él), de ese tipo si se da."""
    pila, salida = list(w.winfo_children()), []
    while pila:
        actual = pila.pop()
        pila += list(actual.winfo_children())
        if tipo is None or isinstance(actual, tipo):
            salida.append(actual)
    return salida


def boton(w, texto):
    """Devuelve el botón con ese texto, o `None`."""
    return next((b for b in widgets(w, ttk.Button) if b.cget("text") == texto), None)


def estado(widget) -> str:
    """El estado de un botón, o `ausente` si no está."""
    return "ausente" if widget is None else str(widget.cget("state"))


def textos(w) -> list[str]:
    """Los textos de las etiquetas que cuelgan de `w`."""
    return [str(e.cget("text")) for e in widgets(w, ttk.Label)]


def asistente(dispositivo=None):
    """Un asistente con la conexión y el catálogo ya dados por buenos."""
    top = tk.Toplevel(raiz)
    top.withdraw()
    wiz = tk_install.build(top)
    wiz.perfil = PERFIL
    wiz.catalog = remote.parse_catalog(CATALOGO)
    wiz.rclone = remote.Rclone("RCLONE", "CONF", remote_name="nas")
    wiz.state.device = dispositivo
    wiz.state.device_root = dispositivo
    wiz.state.selected = ["p0", "p1"]
    return wiz


def en_paso(wiz, titulo: str) -> None:
    """Lleva el asistente al paso con ese título y lo pinta."""
    wiz.indice = [t for t, _, _ in wiz.pasos].index(titulo)
    wiz.repintar()


def asistente_equipo(forma=raiz_equipo.PROPIA, cifrado=False, ruta=None):
    """Un asistente en el recorrido «En este equipo»."""
    wiz = asistente(None)
    wiz.donde = "equipo"
    wiz.equipo_forma = forma
    wiz.equipo_cifrado = raiz_equipo.VERACRYPT if cifrado else raiz_equipo.SIN_CIFRAR
    if ruta is not None:
        wiz.equipo_ruta = str(ruta)
    wiz.pasos = tk_install.pasos_equipo(wiz)
    return wiz


def siguiente(wiz) -> str:
    """El estado de «Siguiente»."""
    return str(wiz.boton_siguiente.cget("state"))


# 1. la sonda de escritura del panel de VeraCrypt
#
# Una unidad sin dispersos: el contenedor se escribe entero y el panel dice
# cuánto tardará, midiéndolo con 8 MiB. Eso escribe en la unidad de la persona.
sondas_reales = {n: getattr(crypto, n) for n in (
    "find_veracrypt", "soporta_dispersos", "sistema_de_ficheros", "medir_escritura",
    "create_container", "mount_container")}
medidas: list = []
VELOCIDAD = 10 * 1024 ** 2


def medir(root, muestra=0):
    """La sonda de mentira: apunta en qué hilo y dónde mide, y no escribe nada."""
    medidas.append((threading.get_ident(), Path(root)))
    return VELOCIDAD


creados: list = []
crypto.find_veracrypt = lambda extra_dir=None: {"mount": "VeraCrypt.exe",
                                                "format": "VeraCrypt Format.exe"}
crypto.soporta_dispersos = lambda root: False
crypto.sistema_de_ficheros = lambda root: "NTFS"
crypto.medir_escritura = medir
crypto.create_container = lambda *a, **k: creados.append(a)
crypto.mount_container = lambda *a, **k: tmpdir()
PREFIJOS_ESPERA = ("Midiendo", "Hay que escribir", "Creación")


def linea_espera(wiz) -> str:
    """Lo que dice la línea de la espera del panel de VeraCrypt."""
    return next((t for t in textos(wiz.cuerpo) if t.startswith(PREFIJOS_ESPERA)), "")


def caja_tamano(wiz):
    """La caja del tamaño del contenedor (la única sin `show`)."""
    return next(e for e in widgets(wiz.cuerpo, ttk.Entry)
                if not e.cget("show") and not isinstance(e, ttk.Combobox))


def con_tamano(wiz, texto: str) -> str:
    """Escribe un tamaño, como tecleado, y devuelve la estimación que le toca."""
    caja = caja_tamano(wiz)
    caja.delete(0, "end")
    caja.insert(0, texto)
    return texto


def division(wiz, texto: str, velocidad: float) -> str:
    """La frase que debe decir la línea para ese tamaño y esa velocidad."""
    bytes_ = crypto.size_to_bytes(texto, lecturas_asistente.libre(wiz.state.device), None)
    return f"Hay que escribir el contenedor entero: {crypto.describir_espera(bytes_ / velocidad)}."


def panel_vc(dispositivo):
    """Un asistente en el paso de cifrado con VeraCrypt, sobre esa unidad."""
    wiz = asistente(dispositivo)
    wiz.state.device_root = None
    wiz.state.encryption = "veracrypt"
    en_paso(wiz, "Cifrado")
    return wiz


tope_real = getattr(lecturas_asistente, "TOPE_SONDA_S", 60.0)
try:
    # Con hilos de verdad: la sonda no corre en el de Tk.
    segundo_plano.lanzar = LANZAR_REAL
    vc = panel_vc(tmpdir())
    llego = dar_vueltas(lambda: linea_espera(vc).startswith("Hay que escribir"))
    c("la sonda llega sola, sin que nadie pulse nada", llego, True)
    c("  y se mide en otro hilo, no en el de Tk",
      [hilo != PRINCIPAL for hilo, _ in medidas], [True])
    c("  en la unidad elegida", [donde for _, donde in medidas], [vc.state.device])
    c("  al llegar, «Crear y montar» se enciende",
      estado(boton(vc.cuerpo, "Crear y montar")), "normal")
    for t in ("100M", "200M", "300M", "400M", "500M"):
        con_tamano(vc, t)
    c("teclear el tamaño cinco veces no lanza otra sonda", len(medidas), 1)
    c("  y la estimación es la división del tamaño por lo medido", linea_espera(vc),
      division(vc, "500M", VELOCIDAD))

    # Una sonda que no acaba: el contenedor va al lado de lo que escribe.
    pendientes = Pendientes()
    segundo_plano.lanzar = pendientes
    medidas.clear()
    lenta = panel_vc(tmpdir())
    c("la sonda va por segundo_plano: un encargo, y nada escrito en el hilo de Tk",
      (len(pendientes.encargos), medidas), (1, []))
    c("  mientras mide, «Crear y montar» está apagado",
      estado(boton(lenta.cuerpo, "Crear y montar")), "disabled")
    c("  y la línea dice que mide", linea_espera(lenta), "Midiendo lo que escribe la unidad…")
    for e in widgets(lenta.cuerpo, ttk.Entry):
        if e.cget("show"):
            e.insert(0, "una contraseña bastante larga")
    boton(lenta.cuerpo, "Crear y montar").invoke()
    c("no se crea el contenedor mientras se mide", creados, [])
    con_tamano(lenta, "300M")
    c("  ni teclear el tamaño enciende el botón",
      estado(boton(lenta.cuerpo, "Crear y montar")), "disabled")
    # `invoke()` no ejecuta un botón apagado: se llama a su comando directamente.
    creados_antes = len(creados)
    raiz.tk.call(boton(lenta.cuerpo, "Crear y montar").cget("command"))
    c("con la sonda escribiendo, el comando de «Crear y montar» no crea nada",
      len(creados), creados_antes)

    # El hilo acaba y nadie lo ha mirado todavía (el sondeo no ha pasado).
    encargo = pendientes.ultimo()
    encargo.resultado, encargo.hecho = 2 * VELOCIDAD, True
    for t in ("100M", "200M", "300M", "400M", "500M"):
        con_tamano(lenta, t)
    c("una sola sonda aunque el hilo acabe antes de mirarlo",
      (len(pendientes.encargos), medidas), (1, []))
    c("  la división usa su resultado", linea_espera(lenta),
      division(lenta, "500M", 2 * VELOCIDAD))
    c("  y lo guarda en el estado", lenta.state.velocidad_escritura, 2 * VELOCIDAD)
    c("  y «Crear y montar» vuelve", estado(boton(lenta.cuerpo, "Crear y montar")),
      "normal")

    # Repintar mientras mide: el sondeo muere con el panel, la sonda no.
    pendientes = Pendientes()
    segundo_plano.lanzar = pendientes
    medidas.clear()
    repinta = panel_vc(tmpdir())
    repinta.repintar()
    c("repintar con la sonda escribiendo no lanza otra", len(pendientes.encargos), 1)
    c("  y «Crear y montar» sigue apagado",
      estado(boton(repinta.cuerpo, "Crear y montar")), "disabled")
    pendientes.ultimo().correr()
    en_paso(repinta, "¿Dónde?")
    en_paso(repinta, "Cifrado")
    tam = caja_tamano(repinta).get()
    c("una sola sonda aunque se repinte el panel",
      (len(pendientes.encargos), len(medidas)), (1, 1))
    c("  y al volver al panel se enseña su resultado", linea_espera(repinta),
      division(repinta, tam, VELOCIDAD))

    # Otra unidad es otra sonda; volver a la primera no la repite.
    primera = repinta.state.device
    repinta.state.device = tmpdir()
    repinta.repintar()
    c("otra unidad, otra sonda", len(pendientes.encargos), 2)
    repinta.state.device = primera
    repinta.repintar()
    c("  y volver a la primera no la repite: una por unidad", len(pendientes.encargos), 2)
    c("  y enseña lo medido en ella", linea_espera(repinta),
      division(repinta, caja_tamano(repinta).get(), VELOCIDAD))

    # El tope solo se espera mientras la sonda escribe.
    pendientes = Pendientes()
    segundo_plano.lanzar = pendientes
    with AfterAnotado() as marcos:
        con_tope = panel_vc(tmpdir())
        topes = [i for i, ms in marcos.puestos.items() if ms > 10_000]
        c("con la sonda escribiendo se arma una sola espera de su tope", len(topes), 1)
        encargo = pendientes.ultimo()
        encargo.resultado, encargo.hecho = VELOCIDAD, True
        con_tamano(con_tope, "100M")
        c("  y al contestar la sonda esa espera se quita",
          topes[0] in marcos.cancelados, True)

    # El tope: una unidad que no contesta no deja el botón apagado para siempre.
    pendientes = Pendientes()
    segundo_plano.lanzar = pendientes
    lecturas_asistente.TOPE_SONDA_S = 0.2
    colgada = panel_vc(tmpdir())
    c("con la sonda colgada, «Crear y montar» empieza apagado",
      estado(boton(colgada.cuerpo, "Crear y montar")), "disabled")
    vuelve = dar_vueltas(lambda: estado(boton(colgada.cuerpo, "Crear y montar")) == "normal")
    c("  y vuelve al pasar su tope", vuelve, True)
    c("  diciendo que no se ha podido medir", linea_espera(colgada),
      "Hay que escribir el contenedor entero: "
      + crypto.describir_espera(None) + ".")
    pendientes.ultimo().correr()
    guardada = dar_vueltas(lambda: colgada.state.velocidad_escritura == VELOCIDAD)
    c("  y si la sonda contesta después, se guarda", guardada, True)
    c("  y se usa", linea_espera(colgada),
      division(colgada, caja_tamano(colgada).get(), VELOCIDAD))
    c("  sin lanzar otra", len(pendientes.encargos), 1)
    lecturas_asistente.TOPE_SONDA_S = tope_real

    # Un contenedor dinámico no mide nada, como siempre.
    crypto.soporta_dispersos = lambda root: True
    crypto.find_veracrypt = lambda extra_dir=None: {
        "mount": "VeraCrypt.exe", "format": "VeraCrypt Format.exe", "appimage": True}
    pendientes = Pendientes()
    segundo_plano.lanzar = pendientes
    medidas.clear()
    dinamico = panel_vc(tmpdir())
    c("un contenedor dinámico no lanza la sonda", (pendientes.encargos, medidas), ([], []))
    c("  y «Crear y montar» está encendido",
      estado(boton(dinamico.cuerpo, "Crear y montar")), "normal")
finally:
    lecturas_asistente.TOPE_SONDA_S = tope_real
    segundo_plano.lanzar = LANZAR_REAL
    for nombre, funcion in sondas_reales.items():
        setattr(crypto, nombre, funcion)
# De aquí en adelante, ni la pregunta de los dispersos escribe en el disco.
crypto.soporta_dispersos = lambda root: False


# 2. «Carpeta» sin cifrar: se examina al dejar de teclear, y fuera del hilo de Tk
examinadas: list = []
examinar_real = raiz_equipo.examinar


def examinar_apuntado(ruta, forma=raiz_equipo.PROPIA):
    """`raiz_equipo.examinar` de verdad, apuntando en qué hilo y qué texto."""
    examinadas.append((threading.get_ident(), str(ruta)))
    return examinar_real(ruta, forma)


raiz_equipo.examinar = examinar_apuntado
BASE = tmpdir("prdrive-lecturas-raiz-")
RAIZ = BASE / "PRDRIVE"


def caja_carpeta(wiz):
    """La caja de la carpeta del paso «Carpeta» sin cifrar."""
    return next(iter(widgets(wiz.cuerpo, ttk.Entry)))


def linea_carpeta(wiz) -> str:
    """Lo que dice la línea de debajo de la caja de «Carpeta»."""
    return next((t for t in textos(wiz.cuerpo)
                 if t == MIRANDO or str(RAIZ) in t or "ruta completa" in t), "")


try:
    segundo_plano.lanzar = LANZAR_REAL
    lecturas_asistente.ESPERA_TECLA_MS = ESPERA_REAL
    examinadas.clear()
    hilo = asistente_equipo(ruta=RAIZ)
    en_paso(hilo, "Carpeta")
    llega = dar_vueltas(lambda: hilo.state.device_root is not None)
    c("«Carpeta»: el examen de lo que hay escrito al pintar llega solo", llega, True)
    c("  y se ha hecho en otro hilo, no en el de Tk",
      [h != PRINCIPAL for h, _ in examinadas], [True])
    c("  y enciende «Siguiente» con la raíz fijada",
      (hilo.state.device_root, siguiente(hilo)), (RAIZ, "normal"))

    # Cinco teclas seguidas: un examen, el del último texto.
    segundo_plano.lanzar = segundo_plano.en_el_acto
    with Reloj() as reloj:
        teclas = asistente_equipo(ruta=RAIZ)
        en_paso(teclas, "Carpeta")
        entrada = caja_carpeta(teclas)
        examinadas.clear()
        reloj.plazos.clear()
        for letra in "abcde":
            entrada.insert("end", letra)
        c("cinco teclas seguidas no examinan nada todavía", examinadas, [])
        c("  dejan la raíz sin fijar y «Siguiente» apagado en el acto",
          (teclas.state.device_root, siguiente(teclas)), (None, "disabled"))
        c("  y la línea de debajo dice que mira", linea_carpeta(teclas), MIRANDO)
        c("  cada tecla rearma una espera de 250 ms", reloj.plazos, [ESPERA_REAL] * 5)
        c("  de la que queda una sola, colgada de la caja y no de la ventana",
          [w is entrada for w, _ in reloj.de(ESPERA_REAL)], [True])
        reloj.disparar(ESPERA_REAL)
        escrito = str(RAIZ) + "abcde"
        c("al dejar de teclear, un solo examen, del último texto",
          [t for _, t in examinadas], [escrito])
        hoy = examinar_real(escrito, raiz_equipo.PROPIA)
        c("  y el paso queda como hoy: la misma frase y la misma raíz",
          (linea_carpeta(teclas) == hoy.texto or hoy.texto in textos(teclas.cuerpo),
           teclas.state.device_root, siguiente(teclas)),
          (True, Path(escrito), "normal"))

        # «Examinar…» elige con el diálogo: se examina en el acto, sin esperar.
        dialogo_real = filedialog.askdirectory
        elegida = BASE / "elegida"
        filedialog.askdirectory = lambda **k: str(elegida)
        try:
            examinadas.clear()
            boton(teclas.cuerpo, "Examinar…").invoke()
            c("«Examinar…» examina en el acto, sin esperar a ninguna tecla",
              ([t for _, t in examinadas], teclas.state.device_root),
              ([str(elegida)], elegida))
        finally:
            filedialog.askdirectory = dialogo_real

    # El examen de un texto viejo no cuenta.
    pendientes = Pendientes()
    segundo_plano.lanzar = pendientes
    with Reloj() as reloj:
        viejo = asistente_equipo(ruta=RAIZ)
        en_paso(viejo, "Carpeta")
        c("al pintar, el examen se lanza en el acto, sin esperar a una tecla",
          (len(pendientes.encargos), reloj.de(ESPERA_REAL)), (1, []))
        c("  y mientras llega, «Siguiente» está apagado",
          (viejo.state.device_root, siguiente(viejo)), (None, "disabled"))
        pendientes.ultimo().correr()
        reloj.disparar(uitk.SONDEO_MS)
        c("  al llegar, cuenta: es lo que sigue escrito",
          (viejo.state.device_root, siguiente(viejo)), (RAIZ, "normal"))
        entrada = caja_carpeta(viejo)
        primero = str(BASE / "uno")
        entrada.delete(0, "end")
        entrada.insert(0, primero)
        reloj.disparar(ESPERA_REAL)
        c("  al dejar de teclear se lanza el examen de lo escrito",
          len(pendientes.encargos), 2)
        entrada.insert("end", "-dos")
        pendientes.ultimo().correr()
        reloj.disparar(uitk.SONDEO_MS)
        c("el examen de un texto viejo no cuenta: ni raíz, ni examen, ni «Siguiente»",
          (viejo.state.device_root, viejo.equipo_examen, siguiente(viejo)),
          (None, None, "disabled"))
        c("  y la línea sigue diciendo que mira", linea_carpeta(viejo), MIRANDO)
        reloj.disparar(ESPERA_REAL)
        pendientes.ultimo().correr()
        reloj.disparar(uitk.SONDEO_MS)
        c("  el del texto de ahora sí", (viejo.state.device_root, siguiente(viejo)),
          (Path(primero + "-dos"), "normal"))

    # Un cambio de paso con una tecla pendiente: la espera muere con la caja.
    segundo_plano.lanzar = segundo_plano.en_el_acto
    errores: list = []
    raiz.report_callback_exception = lambda *a: errores.append(a[1])
    cambia = asistente_equipo(ruta=RAIZ)
    en_paso(cambia, "Carpeta")
    examinadas.clear()
    caja_carpeta(cambia).insert("end", "z")
    en_paso(cambia, "Raíz")
    centinela: list = []
    raiz.after(2 * ESPERA_REAL, lambda: centinela.append(1))
    dar_vueltas(lambda: bool(centinela))
    c("un cambio de paso con una tecla pendiente no examina nada ni da error",
      (bool(centinela), examinadas, errores), (True, [], []))
finally:
    segundo_plano.lanzar = LANZAR_REAL
    lecturas_asistente.ESPERA_TECLA_MS = ESPERA_REAL
    raiz.__dict__.pop("report_callback_exception", None)


# 3. «Carpeta» cifrada: un examen por TODO lo escrito
#
# En Linux el contenedor se monta en una carpeta que tiene que estar vacía: lo
# que hubiera quedaría tapado. El examen depende de las dos cajas («Contenedor
# en» y «Se abre en»), así que uno hecho con otra carpeta de montaje no vale
# para encender «Crear y montar». Se fuerza la forma de Linux (la caja «Se abre
# en») y el examen se sustituye, para que valga en los dos sistemas.
CON_COSAS = tmpdir("prdrive-lecturas-con-cosas-")
(CON_COSAS / "mis-fotos").mkdir()
contenedores: list = []
real_contenedor = raiz_equipo.examinar_contenedor
real_abrir = raiz_equipo.abrir_o_crear
real_win = install.IS_WIN
abiertos: list = []


def examinar_contenedor_falso(fisica, carpeta, forma=raiz_equipo.PROPIA):
    """Lo que diría el examen en Linux: la carpeta con cosas no vale para montar."""
    contenedores.append((threading.get_ident(), str(fisica), str(carpeta)))
    if Path(str(carpeta).strip()) == CON_COSAS:
        return raiz_equipo.Examen(raiz_equipo.NO_VALE, f"{carpeta} tiene cosas, y es "
                                                        "donde se monta el contenedor")
    return raiz_equipo.Examen(raiz_equipo.NUEVA, f"Se creará {fisica}/PRDRIVE.hc")


def abrir_o_crear_falso(vc, fisica, carpeta, letra, password, tamano):
    """Apunta qué se crearía y dónde se montaría, y no crea nada."""
    abiertos.append((str(fisica), str(carpeta)))
    return tmpdir("prdrive-lecturas-volumen-")


raiz_equipo.examinar_contenedor = examinar_contenedor_falso
raiz_equipo.abrir_o_crear = abrir_o_crear_falso
raiz_equipo.veracrypt_instalado = lambda: {"mount": "vc", "format": "vc"}
install.IS_WIN = False
FISICA = tmpdir("prdrive-lecturas-fisica-") / "PRDRIVE-cifrado"
PUNTO0 = tmpdir("prdrive-lecturas-punto-") / "PRDRIVE"
PUNTO1 = tmpdir("prdrive-lecturas-punto-") / "PRDRIVE"


def cajas_contenedor(wiz):
    """Las cajas «Contenedor en» y «Se abre en» del paso del contenedor."""
    cajas = [e for e in widgets(wiz.cuerpo, ttk.Entry)
             if not e.cget("show") and not isinstance(e, ttk.Combobox)]
    fisica = next(e for e in cajas if e.get() == str(FISICA))
    punto = next(e for e in cajas if e is not fisica and e.get() == str(PUNTO0))
    return fisica, punto


def teclear(entrada, texto: str) -> None:
    """Borra e inserta, como teclearlo: pasa por la validación de la caja."""
    entrada.delete(0, "end")
    entrada.insert(0, texto)


try:
    pendientes = Pendientes()
    segundo_plano.lanzar = pendientes
    with Reloj() as reloj:
        cifra = asistente_equipo(cifrado=True, ruta=PUNTO0)
        cifra.equipo_fisica = str(FISICA)
        en_paso(cifra, "Carpeta")
        caja, punto = cajas_contenedor(cifra)
        crear = boton(cifra.cuerpo, "Crear y montar")
        c("el contenedor: el examen va por segundo_plano, en el acto al pintar",
          len(pendientes.encargos), 1)
        c("  y mientras llega, «Crear y montar» está apagado", estado(crear), "disabled")
        pendientes.ultimo().correr()
        reloj.disparar(uitk.SONDEO_MS)
        c("  al llegar (contenedor y carpeta de montaje examinados), se enciende",
          estado(crear), "normal")
        teclear(punto, str(PUNTO1))
        c("una tecla en «Se abre en» lo apaga en el acto", estado(crear), "disabled")
        reloj.disparar(ESPERA_REAL)
        encargado = getattr(pendientes.ultimo()._funcion, "args", ())
        c("  y al dejar de teclear se encarga el examen de todo lo escrito",
          tuple(encargado[:2]), (str(FISICA), str(PUNTO1)))
        teclear(punto, str(CON_COSAS))
        pendientes.ultimo().correr()                     # el examen de PUNTO1, ya viejo
        reloj.disparar(uitk.SONDEO_MS)
        diferido = getattr(caja, "diferido", None)
        c("el examen del contenedor con otro punto de montaje no cuenta",
          (estado(crear), getattr(diferido, "examinada", "sin examen diferido")),
          ("disabled", None))
        c("  y la línea sigue diciendo que mira", MIRANDO in textos(cifra.cuerpo), True)
        for e in widgets(cifra.cuerpo, ttk.Entry):
            if e.cget("show"):
                teclear(e, "una-contraseña-larga-de-prueba")
        crear.configure(state="normal")             # aunque el botón se encendiera
        crear.invoke()
        c("  y crear no monta nada sobre una carpeta que no se ha examinado", abiertos, [])
        reloj.disparar(ESPERA_REAL)
        pendientes.ultimo().correr()
        reloj.disparar(uitk.SONDEO_MS)
        c("el examen de lo escrito ahora dice que tiene cosas, y el botón sigue apagado",
          (estado(crear), any("tiene cosas" in t for t in textos(cifra.cuerpo))),
          ("disabled", True))
        crear.configure(state="normal")
        crear.invoke()
        c("  y crear tampoco: ese examen dice que no vale", abiertos, [])
        teclear(punto, str(PUNTO1))
        reloj.disparar(ESPERA_REAL)
        pendientes.ultimo().correr()
        reloj.disparar(uitk.SONDEO_MS)
        # Lo escrito cambia mientras la pregunta por el aviso sigue abierta: el
        # examen de antes ya no es de lo que hay, y no se monta con él.
        revisar_real = crypto.revisar_contrasena
        pregunta_real = messagebox.askyesno

        def cambia_mientras_pregunta(*_a, **_k):
            """Teclea otra carpeta de montaje mientras la pregunta sigue abierta."""
            teclear(punto, str(PUNTO0))
            return True

        crypto.revisar_contrasena = lambda password: (None, "Aviso de prueba.")
        messagebox.askyesno = cambia_mientras_pregunta
        try:
            antes_de_preguntar = len(abiertos)
            crear.invoke()
        finally:
            crypto.revisar_contrasena = revisar_real
            messagebox.askyesno = pregunta_real
        c("si lo escrito cambia mientras se pregunta por el aviso, no se monta nada",
          len(abiertos), antes_de_preguntar)
        teclear(punto, str(PUNTO1))
        reloj.disparar(ESPERA_REAL)
        pendientes.ultimo().correr()
        reloj.disparar(uitk.SONDEO_MS)
        crear.invoke()
        c("con lo escrito examinado y bueno, crea y monta justo eso",
          abiertos, [(str(FISICA), str(PUNTO1))])
finally:
    install.IS_WIN = real_win
    raiz_equipo.examinar_contenedor = real_contenedor
    raiz_equipo.abrir_o_crear = real_abrir
    raiz_equipo.veracrypt_instalado = lambda: None
    segundo_plano.lanzar = LANZAR_REAL


# 3b. «Carpeta» cifrada en Windows: «Contenedor en» sale propuesta y se queda así
#
# En Windows no hay caja «Se abre en»: la letra va en un Combobox y la única caja
# del contenedor es «Contenedor en». Su texto está en una StringVar que tiene que
# seguir viva: si nada la retiene al salir del paso, Python la libera y Tk vacía
# la caja, aunque el examen ya haya fijado la ruta. Se fuerza la rama de Windows
# de `_carpeta_cifrada` y se sustituye lo que solo existe allí: las letras libres,
# los restos sin cifrar y la prueba de dispersos (que ya es `False` desde arriba).
RUTA_WIN = tmpdir("prdrive-lecturas-win-") / "PRDRIVE"
OTRA_WIN = tmpdir("prdrive-lecturas-win-otra-") / "OTRA-cifrado"
antes_win = (install.IS_WIN, raiz_equipo.IS_WIN, raiz_equipo.letras_libres,
             raiz_equipo.restos, raiz_equipo.veracrypt_instalado,
             crypto.soporta_dispersos, segundo_plano.lanzar)


def caja_del_contenedor(wiz):
    """La caja «Contenedor en» del paso: la que lleva su examen diferido, o `None`."""
    return next((e for e in widgets(wiz.cuerpo, ttk.Entry)
                 if getattr(e, "diferido", None) is not None), None)


try:
    install.IS_WIN = True
    raiz_equipo.IS_WIN = True
    raiz_equipo.letras_libres = lambda preferida="P": ["P", "Q"]
    raiz_equipo.restos = lambda carpeta: []
    raiz_equipo.veracrypt_instalado = lambda: {"mount": "vc", "format": "vc"}
    crypto.soporta_dispersos = lambda root: False
    segundo_plano.lanzar = segundo_plano.en_el_acto
    win = asistente_equipo(cifrado=True, ruta=RUTA_WIN)
    esperada = str(raiz_equipo.fisica_por_defecto(RUTA_WIN))
    en_paso(win, "Carpeta")
    caja_win = caja_del_contenedor(win)
    c("Windows: «Contenedor en» sale con la carpeta propuesta, «…-cifrado»",
      caja_win.get() if caja_win is not None else "sin caja", esperada)
    caja_win.diferido.ya()                               # el examen llega de nuevo
    raiz.update()
    c("  y sigue así cuando llega el examen, que es lo que se examina y lo que se ve",
      (caja_win.get(), win.equipo_fisica), (esperada, esperada))
    with Reloj() as reloj:
        teclear(caja_win, str(OTRA_WIN))
        reloj.disparar(ESPERA_REAL)
    c("  al teclear otra, el examen va con lo escrito y «Crear y montar» se enciende",
      (win.equipo_fisica, estado(boton(win.cuerpo, "Crear y montar"))),
      (str(OTRA_WIN), "normal"))
finally:
    (install.IS_WIN, raiz_equipo.IS_WIN, raiz_equipo.letras_libres, raiz_equipo.restos,
     raiz_equipo.veracrypt_instalado, crypto.soporta_dispersos,
     segundo_plano.lanzar) = antes_win


# 4. «Parejas» de este equipo: cada ruta, al dejar de teclear y fuera del hilo
locales: list = []
revisar_real = raiz_equipo.revisar_local


def revisar_apuntado(raiz_, local):
    """`raiz_equipo.revisar_local` de verdad, apuntando en qué hilo y qué ruta."""
    locales.append((threading.get_ident(), str(local)))
    return revisar_real(raiz_, local)


raiz_equipo.revisar_local = revisar_apuntado
publicadas: list = []
publicar_real = deploy.publish_fleet_note
deploy.publish_fleet_note = lambda rc, raiz_, endpoint, timeout=45.0: (
    publicadas.append((threading.get_ident(), raiz_)) or "devices/x.toml")
RAIZ_PAREJAS = tmpdir("prdrive-lecturas-parejas-") / "PRDRIVE"
(RAIZ_PAREJAS / ".prdrive").mkdir(parents=True)
(RAIZ_PAREJAS / ".prdrive" / "PRDRIVE").write_text("id=" + "e" * 32 + "\ntipo=equipo\n",
                                                   encoding="utf-8")


def parejas(wiz):
    """Lleva el asistente a «Parejas» con la raíz ya instalada."""
    wiz.state.device_root = RAIZ_PAREJAS
    en_paso(wiz, "Parejas y configuración")


def caja_pareja(wiz, local: str):
    """La caja de la pareja que tiene ese `local`."""
    return next(e for e in widgets(wiz.cuerpo, ttk.Entry) if e.get() == local)


try:
    segundo_plano.lanzar = LANZAR_REAL
    locales.clear()
    hilos = asistente_equipo(ruta=RAIZ_PAREJAS)
    parejas(hilos)
    llegan = dar_vueltas(lambda: all(str(RAIZ_PAREJAS / "sync-data" / f"p{i}")
                                     in textos(hilos.cuerpo) for i in range(5)))
    c("«Parejas»: la ruta de cada pareja llega sola", llegan, True)
    c("  y se ha examinado en otro hilo, no en el de Tk",
      sorted({h != PRINCIPAL for h, _ in locales}), [True])

    segundo_plano.lanzar = segundo_plano.en_el_acto
    with Reloj() as reloj:
        rapida = asistente_equipo(ruta=RAIZ_PAREJAS)
        parejas(rapida)
        rapida.state.config_written = True
        rapida.revisar()
        caja = caja_pareja(rapida, "sync-data/p1")
        locales.clear()
        reloj.plazos.clear()
        caja.insert("end", "x")
        caja.insert("end", "y")
        caja.insert("end", "z")
        c("tres teclas en una pareja no examinan nada todavía", locales, [])
        c("  su línea dice que mira", MIRANDO in textos(rapida.cuerpo), True)
        c("  y «Siguiente» sigue como estaba (es «config escrito»)", siguiente(rapida),
          "normal")
        c("  con una sola espera de 250 ms, colgada de su caja",
          ([w is caja for w, _ in reloj.de(ESPERA_REAL)], set(reloj.plazos)),
          ([True], {ESPERA_REAL}))
        reloj.disparar(ESPERA_REAL)
        c("al dejar de teclear, un examen de la ruta escrita",
          [t for _, t in locales], ["sync-data/p1xyz"])
        c("  y la línea dice dónde cae", str(RAIZ_PAREJAS / "sync-data" / "p1xyz")
          in textos(rapida.cuerpo), True)

    pendientes = Pendientes()
    segundo_plano.lanzar = pendientes
    with Reloj() as reloj:
        lenta = asistente_equipo(ruta=RAIZ_PAREJAS)
        parejas(lenta)
        c("al pintar, cada pareja lanza su examen en el acto", len(pendientes.encargos), 5)
        for encargo in pendientes.encargos:
            encargo.correr()
        reloj.disparar(uitk.SONDEO_MS)
        caja = caja_pareja(lenta, "sync-data/p2")
        teclear(caja, "uno")
        reloj.disparar(ESPERA_REAL)
        caja.insert("end", "-dos")
        pendientes.ultimo().correr()
        reloj.disparar(uitk.SONDEO_MS)
        c("el examen de una ruta vieja no cuenta: la línea sigue mirando",
          (str(RAIZ_PAREJAS / "uno") in textos(lenta.cuerpo), MIRANDO in textos(lenta.cuerpo)),
          (False, True))
        reloj.disparar(ESPERA_REAL)
        pendientes.ultimo().correr()
        reloj.disparar(uitk.SONDEO_MS)
        c("  el de la de ahora sí", str(RAIZ_PAREJAS / "uno-dos") in textos(lenta.cuerpo),
          True)

    # Guardar escribe en local y apunta la nota de la flota con su barra.
    segundo_plano.lanzar = segundo_plano.en_el_acto
    guarda = asistente_equipo(ruta=RAIZ_PAREJAS)
    parejas(guarda)
    esperas.clear()
    boton(guarda.cuerpo, "Guardar el config y crear las carpetas").invoke()
    c("guardar apunta la nota de la flota con la barra de working() («flota»)",
      (esperas, [r for _, r in publicadas]), (["flota"], [RAIZ_PAREJAS]))
    c("  y el config queda escrito", guarda.state.config_written, True)
finally:
    segundo_plano.lanzar = LANZAR_REAL
    raiz_equipo.revisar_local = revisar_real
    deploy.publish_fleet_note = publicar_real


# 5. «Verificación»: se comprueba en otro hilo, con su indicador
hechas: list = []
comprobaciones_real = tk_equipo.comprobaciones
FILAS = [("Fichero de control", True, "id"), ("rclone.conf", True, "x"),
         ("Agente instalado", False, "no")]


def comprobaciones_apuntadas(*a, **k):
    """Apunta en qué hilo se comprueba y devuelve tres filas."""
    hechas.append(threading.get_ident())
    return list(FILAS)


try:
    tk_equipo.comprobaciones = comprobaciones_apuntadas
    segundo_plano.lanzar = LANZAR_REAL
    final = asistente_equipo(ruta=RAIZ_PAREJAS)
    final.state.device_root = RAIZ_PAREJAS
    en_paso(final, "Verificación")
    llega = dar_vueltas(lambda: "Fichero de control" in textos(final.cuerpo))
    c("«Verificación»: la tabla llega sola", llega, True)
    c("  y se ha comprobado en otro hilo, no en el de Tk",
      [h != PRINCIPAL for h in hechas], [True])
    c("  y «Volver a comprobar» se enciende",
      estado(boton(final.cuerpo, "Volver a comprobar")), "normal")

    pendientes = Pendientes()
    segundo_plano.lanzar = pendientes
    boton(final.cuerpo, "Volver a comprobar").invoke()
    c("mientras comprueba, el indicador lo dice y la tabla no está",
      ("Comprobando lo instalado…" in textos(final.cuerpo),
       "Fichero de control" in textos(final.cuerpo)), (True, False))
    c("  y «Volver a comprobar» está apagado",
      estado(boton(final.cuerpo, "Volver a comprobar")), "disabled")
    pendientes.ultimo().correr()
    llega = dar_vueltas(lambda: "Fichero de control" in textos(final.cuerpo))
    c("  al llegar, la tabla aparece y el indicador se va",
      (llega, "Comprobando lo instalado…" in textos(final.cuerpo),
       estado(boton(final.cuerpo, "Volver a comprobar"))), (True, False, "normal"))
finally:
    tk_equipo.comprobaciones = comprobaciones_real
    segundo_plano.lanzar = LANZAR_REAL


# 6. los widgets de cada paso de «En este equipo» (R5)
#
# Con las lecturas en el sitio (`en_el_acto`), cinco parejas en el catálogo y
# dos elegidas, como la auditoría de pantallas. Los pasos que pinta
# `ui/tk_equipo.py` no pasan de 40; «Verificación» tiene una parte fija (con el
# indicador) y 4 por fila de comprobación (nombre, chip, detalle y la línea que
# la separa de la anterior). Los pasos compartidos con el recorrido de una unidad
# («¿Dónde?», «Conexión», «Comprobaciones», «Inicialización») se cuentan en
# `tests/test_tk_asistente.py`; aquí solo se enseñan.
PROPIOS = {"Raíz", "Cifrado", "Carpeta", "Instalación", "Parejas y configuración",
           "Unidades", "Arranque"}
segundo_plano.lanzar = segundo_plano.en_el_acto
lecturas_asistente.ESPERA_TECLA_MS = 0
try:
    for nombre_ruta, forma in (("PASOS_EQUIPO", raiz_equipo.PROPIA),
                               ("PASOS_EQUIPO_SOLO", raiz_equipo.NINGUNA)):
        cuenta = asistente_equipo(forma=forma, ruta=RAIZ_PAREJAS)
        cuenta.state.device_root = RAIZ_PAREJAS if forma != raiz_equipo.NINGUNA else None
        for titulo, _, _ in cuenta.pasos:
            if titulo == "Verificación":
                continue
            en_paso(cuenta, titulo)
            n = len(widgets(cuenta.cuerpo))
            print(f"  {nombre_ruta} «{titulo}»: {n} widgets")
            if titulo in PROPIOS:
                c(f"{nombre_ruta}: «{titulo}» no pasa de 40 widgets", n <= 40, True)
    raiz_equipo.veracrypt_instalado = lambda: {"mount": "vc", "format": "vc"}
    cerrado = asistente_equipo(cifrado=True, ruta=RAIZ_PAREJAS)
    for titulo in ("Cifrado", "Carpeta"):
        en_paso(cerrado, titulo)
        n = len(widgets(cerrado.cuerpo))
        print(f"  PASOS_EQUIPO con VeraCrypt «{titulo}»: {n} widgets")
        c(f"con VeraCrypt: «{titulo}» no pasa de 40 widgets", n <= 40, True)
    raiz_equipo.veracrypt_instalado = lambda: None

    def contar_verificacion(filas: int) -> int:
        """Los widgets de «Verificación» con tantas filas de comprobación."""
        tk_equipo.comprobaciones = lambda *a, **k: [(f"fila {i}", True, "bien")
                                                    for i in range(filas)]
        verif = asistente_equipo(ruta=RAIZ_PAREJAS)
        verif.state.device_root = RAIZ_PAREJAS
        en_paso(verif, "Verificación")
        return len(widgets(verif.cuerpo))

    con_17, con_18 = contar_verificacion(17), contar_verificacion(18)
    fija = con_17 - (4 * 17 - 1)
    print(f"  «Verificación»: {con_17} widgets con 17 filas, {con_18} con 18; "
          f"parte fija {fija}")
    c("«Verificación»: una fila más son exactamente 4 widgets más", con_18 - con_17, 4)
    c("  y la parte fija, con el indicador, no pasa de 7", fija <= 7, True)
finally:
    tk_equipo.comprobaciones = comprobaciones_real
    lecturas_asistente.ESPERA_TECLA_MS = ESPERA_REAL
    segundo_plano.lanzar = LANZAR_REAL
    raiz_equipo.examinar = examinar_real

sys.exit(c.report())
