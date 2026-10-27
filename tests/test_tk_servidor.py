#!/usr/bin/env python3
"""La ventana «Servidor» recorre el remoto, lo dice cuando falla y para el `rcd` al cerrarse.

Ningún test arranca rclone ni toca la red: `rcd.arrancar` devuelve un `RcdFalso`
que contesta desde un diccionario y apunta cada llamada. Lo que se comprueba es
lo que ve la persona:

- la tabla con las filas de «/», la columna de permisos en «—» y qué se le
  pidió al servidor (`noMimeType` y nada más) mientras `fsinfo` no dice que sabe
  dar permisos;
- doble clic, Intro, Retroceso, «↑», «Releer» y el desplegable de remotes;
- la carpeta de una pareja marcada, y el aviso al estar dentro de ella;
- un permiso denegado deja la tabla como estaba, lo dice y pone el candado;
- `rcd` caído → «Reconectar» (lo relanza y repite la petición); puerto ocupado
  → un solo reintento; sin red al abrir → «Reintentar»; sin remotes → no se
  arranca nada;
- con permisos (SFTP + `ReadMetadata`): el listado pide metadatos, la columna
  enseña `755` y una carpeta ajena sin acceso sale con candado antes de entrar;
- cerrar la ventana con un listado en vuelo, con hilos de verdad: `parar()` una
  vez y ninguna excepción de Tk.
"""

from __future__ import annotations

import sys
import threading
import time

from _harness import Checks, mkcfg, sandbox

from common import config_file, model, rcd
from common.model import ConfigError

c = Checks("«Servidor»: la ventana")

try:
    import tkinter as tk
    from tkinter import ttk
    raiz = tk.Tk()
    raiz.withdraw()
except Exception as e:                                   # sin entorno gráfico
    print(f"  (saltado) no hay entorno gráfico: {e}")
    sys.exit(c.report())

from ui import segundo_plano, tk_servidor  # noqa: E402

errores: list[str] = []
raiz.report_callback_exception = (
    lambda tipo, valor, _tb: errores.append(f"{tipo.__name__}: {valor}"))

LANZAR_DE_VERDAD = segundo_plano.lanzar
segundo_plano.lanzar = segundo_plano.en_el_acto      # con hilos de verdad, solo el test 10
config_file.load_raw = lambda path=None: {"defaults": {"remote": "nas"}}

CFG = mkcfg((), pairs=[
    {"name": "Notas", "local": "sync-data/notas", "remote_path": "/datos/notas", "remote": "nas"}],
    defaults={"remote": "nas"})


def item(nombre: str, carpeta: bool = False, tamano: int = 10, **meta) -> dict:
    """Una entrada de `operations/list`."""
    datos = {"Name": nombre, "IsDir": carpeta, "Size": -1 if carpeta else tamano,
             "ModTime": "2026-03-12T09:00:00Z"}
    if meta:
        datos["Metadata"] = {k: str(v) for k, v in meta.items()}
    return datos


def lista(*items) -> dict:
    return {"list": list(items)}


class RcdFalso:
    """Un `Rcd` que contesta desde un diccionario `(método, remote) → respuesta o error`."""

    def __init__(self, respuestas: dict) -> None:
        self.respuestas = respuestas
        self.llamadas: list[tuple] = []
        self.paradas = 0
        self.esperas = 0
        self.error_esperar: Exception | None = None
        self.vivo = True

    def esperar(self, tope=None) -> None:
        self.esperas += 1
        if self.error_esperar is not None:
            raise self.error_esperar

    def llamar(self, metodo: str, params: dict | None = None) -> dict:
        params = params or {}
        self.llamadas.append((metodo, params))
        respuesta = self.respuestas[(metodo, params.get("remote"))]
        if callable(respuesta):
            respuesta = respuesta()
        if isinstance(respuesta, Exception):
            raise respuesta
        return respuesta

    def parar(self) -> None:
        self.paradas += 1

    def listados(self) -> list[dict]:
        return [p for m, p in self.llamadas if m == "operations/list"]


FSINFO_NO = {"Features": {"ReadMetadata": False}}
FSINFO_SI = {"Features": {"ReadMetadata": True}}


def respuestas(raiz_: dict | Exception | None = None, otras: dict | None = None) -> dict:
    """Las respuestas de un servidor con «datos» (que lleva «notas»), «privado» y un archivo."""
    return {
        ("operations/fsinfo", None): FSINFO_NO,
        ("operations/list", ""): raiz_ if raiz_ is not None else lista(
            item("datos", True), item("privado", True), item("leeme.txt", tamano=2048)),
        ("operations/list", "datos"): lista(item("notas", True), item("a.txt")),
        ("operations/list", "datos/notas"): lista(item("hoy.txt")),
        ("operations/list", "privado"): rcd.ErrorRc("permission denied", 403),
        **(otras or {}),
    }


ARRANQUES: list = []
LLAMADAS_ARRANCAR: list = []


def arrancar_falso() -> RcdFalso:
    LLAMADAS_ARRANCAR.append(1)
    return ARRANQUES.pop(0)


rcd.arrancar = arrancar_falso
ABIERTAS: list = []


def abrir(*falsos: RcdFalso, config=CFG):
    """Abre «Servidor» con esos `rcd` por orden de arranque y devuelve la ventana viva."""
    ARRANQUES[:] = list(falsos)
    LLAMADAS_ARRANCAR.clear()
    ABIERTAS.clear()

    def capturar(dlg, parent=None):
        """Sustituye a `mostrar()`: apunta la ventana, la enseña (un ratón no llega a una oculta) y no espera."""
        ABIERTAS.append(dlg)
        raiz.deiconify()
        dlg.visor.encajar(dlg)
        dlg.deiconify()
        dlg.update()

    previo = tk_servidor.mostrar
    tk_servidor.mostrar = capturar
    try:
        tk_servidor.open_dialog(raiz, config)
    finally:
        tk_servidor.mostrar = previo
    return ABIERTAS[0]


def cerrar(dlg) -> None:
    dlg.destroy()
    raiz.withdraw()


def nombres(dlg) -> list[str]:
    return list(dlg.tabla.orden)


def frase(dlg) -> str:
    return str(dlg.indicador.texto.cget("text"))


def boton(dlg) -> str:
    """El texto del botón de acción si está a la vista, o `""`."""
    return str(dlg.accion.cget("text")) if dlg.accion.winfo_manager() else ""


def textos_del_lienzo(dlg) -> list[str]:
    marco = dlg.tabla.marco
    return [marco.itemcget(i, "text") for i in marco.find_all() if marco.type(i) == "text"]


def fila(dlg, iid: str):
    return dlg.tabla._lienzo.filas[iid]


def pulsar(dlg, secuencia: str) -> None:
    dlg.tabla.marco.focus_force()
    dlg.tabla.marco.event_generate(secuencia)
    dlg.update()


TIEMPO = [0]


def elegir_y_entrar(dlg, iid: str) -> None:
    """Doble clic sobre la fila: dos pulsaciones seguidas en el mismo sitio."""
    x0, y0, x1, y1 = dlg.tabla._lienzo.caja(iid)
    marco = dlg.tabla.marco
    TIEMPO[0] += 10_000          # lejos del doble clic anterior: dos seguidos serían un triple
    for paso in (0, 50):
        marco.event_generate("<ButtonPress-1>", x=(x0 + x1) // 2, y=(y0 + y1) // 2,
                             time=TIEMPO[0] + paso)
        marco.event_generate("<ButtonRelease-1>", x=(x0 + x1) // 2, y=(y0 + y1) // 2,
                             time=TIEMPO[0] + paso + 10)
    dlg.update()


with sandbox():
    model.RCLONE_CONF.write_text("[nas]\ntype = sftp\nhost = h\n\n[otro]\ntype = webdav\n",
                                 encoding="utf-8")

    # -----------------------------------------------------------------------
    # 1. Abrir: las filas de «/» y la columna de permisos en «—»
    # -----------------------------------------------------------------------
    falso = RcdFalso(respuestas())
    dlg = abrir(falso)
    c("el título de la ventana", dlg.title().endswith("Servidor"), True)
    c("se arrancó un solo rcd, en el hilo de Tk", len(LLAMADAS_ARRANCAR), 1)
    c("se esperó a que contestara", falso.esperas, 1)
    c("la tabla tiene las filas de «/»: carpetas primero", nombres(dlg),
      ["datos", "privado", "leeme.txt"])
    c("la columna Permisos dice «—» en todas", {dlg.tabla.filas[i][3] for i in nombres(dlg)}, {"—"})
    c("el tamaño de una carpeta es «—» y el de un archivo, legible",
      (dlg.tabla.filas["datos"][1], dlg.tabla.filas["leeme.txt"][1]), ("—", "2 KB"))
    c("las columnas", dlg.tabla.cabeceras, ["Nombre", "Tamaño", "Modificado", "Permisos"])
    c("se pidió fsinfo y no metadata",
      [p["opt"] for p in falso.listados()], [{"noMimeType": True}])
    c("fsinfo con el mismo fs que los listados",
      [p for m, p in falso.llamadas if m == "operations/fsinfo"], [{"fs": "nas:/"}])
    c("no se pidió el stat: no hay permisos",
      [m for m, _p in falso.llamadas if m == "operations/stat"], [])
    c("la ruta de arriba", dlg.ruta.cget("text"), "/")
    c("el pie cuenta", dlg.cuenta.cget("text"), "3 elementos")
    c("el indicador no dice nada y no hay botón", (frase(dlg), boton(dlg)), ("", ""))
    c("el desplegable enseña el remote", dlg.elegido.get(), "nas")
    c("una carpeta y un archivo llevan su icono",
      (fila(dlg, "datos").celdas[0].nombre, fila(dlg, "leeme.txt").celdas[0].nombre),
      ("carpeta", "file"))
    c("«datos» no es la carpeta de ninguna pareja: sin marca", dlg.tabla.filas["datos"][0], "datos")

    # -----------------------------------------------------------------------
    # 2. Entrar con doble clic, la marca de la pareja, el aviso y subir
    # -----------------------------------------------------------------------
    elegir_y_entrar(dlg, "datos")
    c("doble clic en «datos» lista «datos»", falso.listados()[-1]["remote"], "datos")
    c("la ruta de arriba dice «/datos»", dlg.ruta.cget("text"), "/datos")
    c("la tabla tiene lo de «datos»", nombres(dlg), ["notas", "a.txt"])
    c("la carpeta de la pareja enseña «  ⇄ Notas»", dlg.tabla.filas["notas"][0], "notas  ⇄ Notas")
    c("un archivo no lleva marca", dlg.tabla.filas["a.txt"][0], "a.txt")
    c("fuera de la pareja el indicador calla", frase(dlg), "")
    elegir_y_entrar(dlg, "notas")
    c("dentro de la pareja: el indicador lo dice", frase(dlg), "Estás dentro de la pareja «Notas».")
    c("  y la ruta es la de dentro", dlg.ruta.cget("text"), "/datos/notas")
    pulsar(dlg, "<BackSpace>")
    c("Retroceso sube", (dlg.ruta.cget("text"), frase(dlg)), ("/datos", ""))
    dlg.arriba.invoke()
    c("«↑» sube hasta la raíz", dlg.ruta.cget("text"), "/")
    n = len(falso.listados())
    dlg.arriba.invoke()
    c("«↑» en la raíz no pide nada", len(falso.listados()), n)
    dlg.tabla.elegir("datos")
    pulsar(dlg, "<Return>")
    c("Intro entra en la carpeta elegida", dlg.ruta.cget("text"), "/datos")
    dlg.tabla.elegir("a.txt")
    n = len(falso.listados())
    pulsar(dlg, "<Return>")
    c("Intro en un archivo no hace nada", (len(falso.listados()), dlg.ruta.cget("text")),
      (n, "/datos"))
    cerrar(dlg)
    c("cerrar con «Cerrar»/destroy paró el rcd una sola vez", falso.paradas, 1)

    # -----------------------------------------------------------------------
    # 3. «Releer» repite la carpeta que se ve, y un vacío lo dice
    # -----------------------------------------------------------------------
    falso = RcdFalso(respuestas())
    dlg = abrir(falso)
    c("una carpeta con filas no dice que esté vacía", tk_servidor.VACIA in textos_del_lienzo(dlg), False)
    elegir_y_entrar(dlg, "datos")
    falso.respuestas[("operations/list", "datos")] = lista()
    botones = []

    def buscar(widget, texto):
        for h in widget.winfo_children():
            if isinstance(h, ttk.Button) and str(h.cget("text")) == texto:
                botones.append(h)
            buscar(h, texto)
    buscar(dlg, "Releer")
    buscar(dlg, "↑")
    c("están «Releer» y «↑»", [str(b.cget("text")) for b in botones], ["Releer", "↑"])
    botones[0].invoke()
    c("«Releer» vuelve a pedir la carpeta y se ve vacía",
      (falso.listados()[-1]["remote"], nombres(dlg), dlg.cuenta.cget("text")),
      ("datos", [], "0 elementos"))
    c("una carpeta vacía lo dice", tk_servidor.VACIA in textos_del_lienzo(dlg), True)
    cerrar(dlg)

    # -----------------------------------------------------------------------
    # 4. Un permiso denegado deja la tabla, lo dice y pone el candado
    # -----------------------------------------------------------------------
    falso = RcdFalso(respuestas())
    dlg = abrir(falso)
    antes = dlg.tabla.leer()
    elegir_y_entrar(dlg, "privado")
    c("la tabla sigue con las filas de antes", (nombres(dlg), dlg.tabla.leer()),
      (["datos", "privado", "leeme.txt"], antes))
    c("la ruta no cambia", dlg.ruta.cget("text"), "/")
    c("el indicador lo dice", frase(dlg), "No tienes permiso para ver esta carpeta.")
    c("y no hay botón", boton(dlg), "")
    c("«privado» lleva candado y tono apagado",
      (fila(dlg, "privado").celdas[0].nombre, fila(dlg, "privado").tono), ("candado", "apagado"))
    c("las demás no", (fila(dlg, "datos").celdas[0].nombre, fila(dlg, "datos").tono),
      ("carpeta", ""))
    cerrar(dlg)

    # -----------------------------------------------------------------------
    # 5. Otro error corriente se dice con la frase de `servidor`
    # -----------------------------------------------------------------------
    falso = RcdFalso(respuestas(otras={("operations/list", "datos"): rcd.ErrorRc("directory not found", 404)}))
    dlg = abrir(falso)
    elegir_y_entrar(dlg, "datos")
    c("una carpeta que ya no existe", frase(dlg), "Esa carpeta ya no existe en el servidor.")
    c("y la tabla sigue", nombres(dlg), ["datos", "privado", "leeme.txt"])
    cerrar(dlg)

    # -----------------------------------------------------------------------
    # 6. Un rcd caído: «Reconectar» lo relanza y repite la última petición
    # -----------------------------------------------------------------------
    primero = RcdFalso(respuestas(otras={("operations/list", "datos"): rcd.RcdCaido("Connection refused")}))
    segundo = RcdFalso(respuestas())
    dlg = abrir(primero, segundo)
    elegir_y_entrar(dlg, "datos")
    c("se dice que se perdió rclone", frase(dlg), "Se ha perdido la conexión con rclone.")
    c("sale «Reconectar», no «Reintentar»", boton(dlg), "Reconectar")
    c("la tabla sigue", dlg.ruta.cget("text"), "/")
    dlg.accion.invoke()
    c("se relanzó rcd", len(LLAMADAS_ARRANCAR), 2)
    c("el viejo se paró", primero.paradas, 1)
    c("el nuevo se esperó y repitió «datos»",
      (segundo.esperas, segundo.listados()[-1]["remote"]), (1, "datos"))
    c("la tabla ya tiene lo de «datos» y no queda botón",
      (nombres(dlg), boton(dlg), frase(dlg)), (["notas", "a.txt"], "", ""))
    cerrar(dlg)
    c("al cerrar solo se para el que vive", (primero.paradas, segundo.paradas), (1, 1))

    # -----------------------------------------------------------------------
    # 7. Puerto ocupado: un reintento y no más
    # -----------------------------------------------------------------------
    ocupado = rcd.PuertoOcupado("El puerto que se eligió para rclone ya lo usa otro programa.")
    uno, dos = RcdFalso(respuestas()), RcdFalso(respuestas())
    uno.error_esperar = ocupado
    dlg = abrir(uno, dos)
    c("PuertoOcupado una vez: se relanza una sola vez", len(LLAMADAS_ARRANCAR), 2)
    c("  y la tabla sale", nombres(dlg), ["datos", "privado", "leeme.txt"])
    c("  sin error", (frase(dlg), boton(dlg)), ("", ""))
    c("  y el que no pudo abrir el puerto se paró (no queda apuntado)", uno.paradas, 1)
    cerrar(dlg)

    uno, dos = RcdFalso(respuestas()), RcdFalso(respuestas())
    uno.error_esperar = dos.error_esperar = ocupado
    dlg = abrir(uno, dos)
    c("PuertoOcupado dos veces: no se prueba una tercera", len(LLAMADAS_ARRANCAR), 2)
    c("  el indicador dice el error y deja reintentarlo", (frase(dlg), boton(dlg)),
      (str(ocupado), "Reintentar"))
    c("  y la tabla sigue vacía", nombres(dlg), [])
    cerrar(dlg)

    # -----------------------------------------------------------------------
    # 8. Sin red al abrir: «Reintentar» repite la apertura sin relanzar rcd
    # -----------------------------------------------------------------------
    falso = RcdFalso(respuestas(rcd.ErrorRc(
        "couldn't connect: dial tcp 10.0.0.1:22: connection refused", 500)))
    dlg = abrir(falso)
    c("la primera petición falla sin red", frase(dlg), "No hay conexión con el servidor.")
    c("sale «Reintentar»", boton(dlg), "Reintentar")
    c("la tabla no dice «vacía» sobre un servidor que no contesta",
      tk_servidor.VACIA in textos_del_lienzo(dlg), False)
    falso.respuestas[("operations/list", "")] = lista(item("x.txt"))
    dlg.accion.invoke()
    c("«Reintentar» repite la petición de apertura sin relanzar rcd",
      (len(LLAMADAS_ARRANCAR), nombres(dlg), boton(dlg), frase(dlg)), (1, ["x.txt"], "", ""))
    c("  y pregunta otra vez por los permisos del remote",
      len([m for m, _p in falso.llamadas if m == "operations/fsinfo"]), 2)
    cerrar(dlg)

    # un rcd que murió mientras tanto sí se relanza
    muerto = RcdFalso(respuestas(rcd.ErrorRc("dial tcp: connection refused", 500)))
    vivo = RcdFalso(respuestas())
    dlg = abrir(muerto, vivo)
    muerto.vivo = False
    dlg.accion.invoke()
    c("«Reintentar» con el rcd muerto lo relanza", (len(LLAMADAS_ARRANCAR), nombres(dlg)),
      (2, ["datos", "privado", "leeme.txt"]))
    cerrar(dlg)

    # un arranque que falla se dice, con «Reintentar»
    def no_arranca():
        raise ConfigError("No se puede ejecutar rclone: nada")
    rcd.arrancar = no_arranca
    ABIERTAS.clear()
    previo = tk_servidor.mostrar
    tk_servidor.mostrar = lambda dlg_, parent=None: (ABIERTAS.append(dlg_), dlg_.update())
    tk_servidor.open_dialog(raiz, CFG)
    tk_servidor.mostrar = previo
    dlg = ABIERTAS[0]
    c("si rclone no se puede ejecutar, el indicador lo dice y hay «Reintentar»",
      (frase(dlg), boton(dlg)), ("No se puede ejecutar rclone: nada", "Reintentar"))
    cerrar(dlg)
    rcd.arrancar = arrancar_falso

    # -----------------------------------------------------------------------
    # 9. Cambiar de remote
    # -----------------------------------------------------------------------
    nuevo = RcdFalso({**respuestas(), ("operations/list", ""): lista(item("raiz-de-otro", True))})
    nuevo.respuestas[("operations/fsinfo", None)] = FSINFO_NO
    dlg = abrir(nuevo)
    c("el desplegable ofrece los remotes del rclone.conf, el de [defaults] primero",
      list(dlg.elegido.cget("values")), ["nas", "otro"])
    dlg.elegido.set("otro")
    dlg.elegido.event_generate("<<ComboboxSelected>>")
    dlg.update()
    c("elegir otro remote lista su raíz con su fs", nuevo.listados()[-1]["fs"], "otro:/")
    c("  y pregunta por sus permisos con ese mismo fs",
      [p for m, p in nuevo.llamadas if m == "operations/fsinfo"][-1], {"fs": "otro:/"})
    c("  la tabla es la de la raíz del otro", nombres(dlg), ["raiz-de-otro"])
    elegir_y_entrar(dlg, "raiz-de-otro")
    c("  y los listados siguientes van al otro remote", nuevo.listados()[-1]["fs"], "otro:/")
    cerrar(dlg)

    # un cambio de remote que falla no cambia nada
    falso = RcdFalso({**respuestas(), ("operations/list", ""): lista(item("x.txt")),
                      ("operations/fsinfo", None): FSINFO_NO})
    dlg = abrir(falso)
    antes = nombres(dlg)
    falso.respuestas[("operations/fsinfo", None)] = rcd.ErrorRc("no existe", 500)
    dlg.elegido.set("otro")
    dlg.elegido.event_generate("<<ComboboxSelected>>")
    dlg.update()
    c("un cambio de remote fallido deja la tabla y el desplegable en el de antes",
      (nombres(dlg), dlg.elegido.get(), frase(dlg)),
      (antes, "nas", "rclone dice: no existe"))
    cerrar(dlg)

    # -----------------------------------------------------------------------
    # 10. Con permisos: SFTP + ReadMetadata
    # -----------------------------------------------------------------------
    conmeta = RcdFalso({
        ("operations/fsinfo", None): FSINFO_SI,
        ("operations/stat", ""): {"item": {"Metadata": {"uid": "1000"}}},
        ("operations/list", ""): lista(
            item("publica", True, mode="40755", uid=1000, gid=1000),
            item("ajena", True, mode="40700", uid=1001, gid=1001),
            item("mia", True, mode="40700", uid=1000, gid=1000),
            item("a.txt", mode="100644", uid=1000, gid=1000)),
    })
    dlg = abrir(conmeta)
    c("el listado lleva metadata", [p["opt"] for p in conmeta.listados()],
      [{"noMimeType": True, "metadata": True}])
    c("se preguntó por mi uid en la carpeta de inicio",
      [p for m, p in conmeta.llamadas if m == "operations/stat"],
      [{"fs": "nas:", "remote": "", "opt": {"metadata": True}}])
    c("la columna enseña los permisos",
      {i: dlg.tabla.filas[i][3] for i in nombres(dlg)},
      {"publica": "755", "ajena": "700", "mia": "700", "a.txt": "644"})
    c("la carpeta 0o40700 de otro dueño sale con candado antes de entrar",
      (fila(dlg, "ajena").celdas[0].nombre, fila(dlg, "ajena").tono), ("candado", "apagado"))
    c("la mía, con la misma máscara, no", fila(dlg, "mia").celdas[0].nombre, "carpeta")
    c("la pública tampoco", fila(dlg, "publica").celdas[0].nombre, "carpeta")
    cerrar(dlg)

    webdav = RcdFalso({("operations/fsinfo", None): FSINFO_SI,
                       ("operations/list", ""): lista(item("a.txt"))})
    model.RCLONE_CONF.write_text("[nas]\ntype = webdav\n", encoding="utf-8")
    dlg = abrir(webdav)
    c("un backend que no saca los metadatos del listado no los recibe, aunque diga ReadMetadata",
      [p["opt"] for p in webdav.listados()], [{"noMimeType": True}])
    cerrar(dlg)

    # -----------------------------------------------------------------------
    # 11. Sin remotes: solo la frase, y rcd no se arranca
    # -----------------------------------------------------------------------
    model.RCLONE_CONF.write_text("[local-del-aparato]\ntype = alias\nremote = /x\n",
                                 encoding="utf-8")
    dlg = abrir(RcdFalso(respuestas()))
    c("sin remotes, el indicador lo dice", frase(dlg),
      "Este dispositivo no tiene conexión con ningún servidor.")
    c("y no se arranca rcd", len(LLAMADAS_ARRANCAR), 0)
    c("ni queda nada que pulsar", (boton(dlg), nombres(dlg)), ("", []))
    cerrar(dlg)
    model.RCLONE_CONF.unlink()
    dlg = abrir(RcdFalso(respuestas()))
    c("sin rclone.conf tampoco", (frase(dlg), len(LLAMADAS_ARRANCAR)),
      ("Este dispositivo no tiene conexión con ningún servidor.", 0))
    cerrar(dlg)
    model.RCLONE_CONF.write_text("[nas]\ntype = sftp\n", encoding="utf-8")

    # -----------------------------------------------------------------------
    # 12. Cerrar con un listado en vuelo, con hilos de verdad
    # -----------------------------------------------------------------------
    segundo_plano.lanzar = LANZAR_DE_VERDAD
    suelto = threading.Event()
    en_vuelo = threading.Event()

    def espera():
        en_vuelo.set()
        suelto.wait(5)
        return lista(item("tarde.txt"))
    lento = RcdFalso(respuestas(espera))
    errores.clear()
    dlg = abrir(lento)
    c("con el listado en vuelo el indicador dice que conecta",
      (frase(dlg), dlg.indicador.esperando), ("Conectando con el servidor…", True))
    c("el hilo está dentro del listado", en_vuelo.wait(5), True)
    dlg.tk.call(dlg.protocol("WM_DELETE_WINDOW"))     # la X de la ventana: cierra y destruye
    fin = time.monotonic() + 5
    while lento.paradas < 1 and time.monotonic() < fin:
        raiz.update()
        time.sleep(0.01)
    c("cerrar paró el rcd", lento.paradas, 1)
    suelto.set()
    for _ in range(30):                                # la respuesta tardía llega a nadie
        raiz.update()
        time.sleep(0.01)
    c("sigue siendo una sola parada tras destruirse la ventana (X y <Destroy>)", lento.paradas, 1)
    c("la ventana ya no existe", bool(dlg.winfo_exists()), False)
    c("ninguna excepción de Tk", errores, [])
    raiz.withdraw()
    segundo_plano.lanzar = segundo_plano.en_el_acto

    # y cerrar mientras arranca (esperar aún no ha acabado)
    segundo_plano.lanzar = LANZAR_DE_VERDAD
    tardio = RcdFalso(respuestas())
    espera_arranque = threading.Event()
    tardio.esperar = lambda tope=None: espera_arranque.wait(5)
    dlg = abrir(tardio)
    dlg.destroy()
    fin = time.monotonic() + 5
    while tardio.paradas < 1 and time.monotonic() < fin:
        raiz.update()
        time.sleep(0.01)
    espera_arranque.set()
    for _ in range(30):
        raiz.update()
        time.sleep(0.01)
    c("cerrar mientras arranca también para el rcd, una vez", tardio.paradas, 1)
    c("  y sin excepciones", errores, [])
    raiz.withdraw()
    segundo_plano.lanzar = segundo_plano.en_el_acto

c("nada ha reventado por el camino", errores, [])
raiz.destroy()
sys.exit(c.report())
