#!/usr/bin/env python3
"""La ventana «Servidor» recorre el remoto, lo dice cuando falla y para el `rcd` al cerrarse.

Ningún test arranca rclone ni toca la red: `rcd.arrancar` devuelve un `RcdFalso`
que contesta desde un diccionario y apunta cada llamada. Lo que se comprueba es
lo que ve la persona:

- la lista (una `ttk.Treeview`) con las filas de «/», lo que SE VE en ella (el
  texto del árbol con el nombre y la marca de pareja, el icono, tamaño, fecha y la
  columna de permisos en «—»), y qué se le
  pidió al servidor (`noMimeType` y nada más) mientras `fsinfo` no dice que sabe
  dar permisos;
- doble clic, Intro, Retroceso, «↑», «Releer» y el desplegable de remotes;
- la carpeta de una pareja marcada, y el aviso al estar dentro de ella;
- un permiso denegado deja la lista como estaba, lo dice y pone el candado;
- `rcd` caído → «Reconectar» (lo relanza y repite la petición); puerto ocupado
  → un solo reintento; sin red al abrir → «Reintentar»; sin remotes → no se
  arranca nada;
- con permisos (SFTP + `ReadMetadata`): el listado pide metadatos, la columna
  enseña `755` y una carpeta ajena sin acceso sale con candado antes de entrar;
- una carpeta de 5 000 entradas se abre y se ve entera (la tabla de un lienzo
  moría con `BadAlloc` pasadas ~850 filas);
- cerrar la ventana con un listado en vuelo, con hilos de verdad: `parar()` una
  vez y ninguna excepción de Tk;
- bajar y subir (pieza 2): los tres botones y cuándo se encienden, selección
  múltiple, el bloqueo y el aviso por pareja, el aviso de choques con sus tres
  respuestas, el filtro escapado que llega a `sync/copy`, el panel con un
  progreso que avanza, el resultado, «Cancelar» (una sola vez), «Reintentar»,
  la conexión perdida a mitad (con el proceso muerto), un seguimiento sin respuesta
  con el `rcd` vivo (el lote no se libera ni hay segundo `sync/copy`), el destino
  fijado antes del diálogo del sistema, y cerrar con un lote en marcha (con hilos de
  verdad: `job/stop` antes de `parar()`, ninguna excepción de Tk).
"""

from __future__ import annotations

import sys
import threading
import time

from _harness import Checks, mkcfg, sandbox, tmpdir

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

from ui import icons, segundo_plano, servidor, theme, tk_servidor, tk_transferencia  # noqa: E402

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
        self.orden: list[str] = []        # métodos llamados y «parar», en el orden en que ocurrieron
        self.esperas = 0
        self.error_esperar: Exception | None = None
        self.vivo = True

    def esperar(self, tope=None) -> None:
        self.esperas += 1
        if self.error_esperar is not None:
            raise self.error_esperar

    def llamar(self, metodo: str, params: dict | None = None,
               timeout: float | None = None) -> dict:
        params = params or {}
        self.llamadas.append((metodo, params))
        self.orden.append(metodo)
        respuesta = self.respuestas[(metodo, params.get("remote"))]
        if callable(respuesta):
            respuesta = respuesta()
        if isinstance(respuesta, Exception):
            raise respuesta
        return respuesta

    def parar(self) -> None:
        self.paradas += 1
        self.orden.append("parar")

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


def no_arranca():
    """Un `rcd.arrancar` que falla, como cuando rclone no se puede ejecutar."""
    raise ConfigError("No se puede ejecutar rclone: nada")


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
    """Los `iid` de la lista, de arriba abajo."""
    return [str(i) for i in dlg.lista.get_children()]


def frase(dlg) -> str:
    return str(dlg.indicador.texto.cget("text"))


def boton(dlg) -> str:
    """El texto del botón de acción si está a la vista, o `""`."""
    return str(dlg.accion.cget("text")) if dlg.accion.winfo_manager() else ""


def dice_vacia(dlg) -> bool:
    """Si la etiqueta «Esta carpeta está vacía.» está puesta sobre la lista."""
    return dlg.vacia.winfo_manager() == "place" and str(dlg.vacia.cget("text")) == tk_servidor.VACIA


def texto(dlg, iid: str) -> str:
    """Lo que se lee en la columna del árbol: el nombre y, si la hay, la marca de pareja."""
    return str(dlg.lista.item(iid, "text")).strip()


def valores(dlg, iid: str) -> tuple[str, str, str]:
    """Tamaño, fecha y permisos tal como se ven."""
    return tuple(str(dlg.lista.set(iid, c)) for c in ("tamano", "modificado", "permisos"))


def imagen(dlg, iid: str) -> str:
    """El nombre de la imagen de la fila en Tk (`""` si no lleva)."""
    foto = dlg.lista.item(iid, "image")
    return " ".join(str(f) for f in foto) if isinstance(foto, (tuple, list)) else str(foto)


def icono(dlg, iid: str) -> str:
    """El nombre del icono de la fila, comparando su imagen con las del tema."""
    foto = imagen(dlg, iid)
    for nombre in ("carpeta", "file", "candado"):
        if foto == str(icons.get(dlg.lista, nombre, 16, theme.TINTA3, theme.SUPERFICIE)):
            return nombre
    return foto


def tono(dlg, iid: str) -> str:
    return " ".join(str(t) for t in dlg.lista.item(iid, "tags"))


def lo_que_se_ve(dlg) -> list[tuple]:
    """Todo lo que la lista dibuja, fila a fila."""
    return [(i, texto(dlg, i), valores(dlg, i), icono(dlg, i), tono(dlg, i)) for i in nombres(dlg)]


def cabeceras(dlg) -> list[str]:
    return [str(dlg.lista.heading(c, "text")) for c in ("#0", "tamano", "modificado", "permisos")]


def elegir(dlg, iid: str) -> None:
    dlg.lista.selection_set(iid)
    dlg.lista.focus(iid)


def pulsar(dlg, secuencia: str) -> None:
    dlg.lista.focus_force()
    dlg.lista.event_generate(secuencia)
    dlg.update()


TIEMPO = [0]


def doble_clic(dlg, x: int, y: int) -> None:
    """Dos pulsaciones seguidas en el mismo sitio de la lista."""
    lista = dlg.lista
    TIEMPO[0] += 10_000          # lejos del doble clic anterior: dos seguidos serían un triple
    for paso in (0, 50):
        lista.event_generate("<ButtonPress-1>", x=x, y=y, time=TIEMPO[0] + paso)
        lista.event_generate("<ButtonRelease-1>", x=x, y=y, time=TIEMPO[0] + paso + 10)
    dlg.update()


def centro(dlg, iid: str) -> tuple[int, int]:
    """El centro de la fila `iid` en la lista (tiene que estar a la vista)."""
    dlg.update()
    x, y, ancho, alto = dlg.lista.bbox(iid)
    return x + ancho // 2, y + alto // 2


def elegir_y_entrar(dlg, iid: str) -> None:
    """Doble clic sobre la fila."""
    doble_clic(dlg, *centro(dlg, iid))


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
    c("la lista tiene las filas de «/»: carpetas primero", nombres(dlg),
      ["datos", "privado", "leeme.txt"])
    c("la columna Permisos dice «—» en todas", {valores(dlg, i)[2] for i in nombres(dlg)}, {"—"})
    c("el tamaño de una carpeta es «—» y el de un archivo, legible",
      (valores(dlg, "datos")[0], valores(dlg, "leeme.txt")[0]), ("—", "2 KB"))
    c("la fecha se lee", valores(dlg, "leeme.txt")[1].endswith(":00"), True)
    c("las columnas", cabeceras(dlg), ["Nombre", "Tamaño", "Modificado", "Permisos"])
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
      (icono(dlg, "datos"), icono(dlg, "leeme.txt")), ("carpeta", "file"))
    c("«datos» no es la carpeta de ninguna pareja: sin marca", texto(dlg, "datos"), "datos")
    # Lo que SE VE: el texto del árbol, la imagen y los valores de cada fila.
    vista = [(i, str(dlg.lista.item(i, "text")), tuple(map(str, dlg.lista.item(i, "values"))),
              imagen(dlg, i)) for i in nombres(dlg)]
    c("cada fila dice su nombre en el árbol",
      [v[1].strip() for v in vista], ["datos", "privado", "leeme.txt"])
    c("  y sus valores (tamaño, fecha, permisos)",
      [(v[2][0], v[2][2]) for v in vista], [("—", "—"), ("—", "—"), ("2 KB", "—")])
    c("  y todas llevan una imagen", all(v[3] for v in vista), True)
    c("  y se ve la columna del árbol, con el nombre", sorted(str(x) for x in dlg.lista.cget("show")), ["headings", "tree"])

    # -----------------------------------------------------------------------
    # 2. Entrar con doble clic, la marca de la pareja, el aviso y subir
    # -----------------------------------------------------------------------
    elegir_y_entrar(dlg, "datos")
    c("doble clic en «datos» lista «datos»", falso.listados()[-1]["remote"], "datos")
    c("la ruta de arriba dice «/datos»", dlg.ruta.cget("text"), "/datos")
    c("la lista tiene lo de «datos»", nombres(dlg), ["notas", "a.txt"])
    c("la carpeta de la pareja enseña «  · pareja «Notas»» en el texto que se ve",
      (texto(dlg, "notas"), "· pareja «Notas»" in str(dlg.lista.item("notas", "text"))),
      ("notas  · pareja «Notas»", True))
    c("un archivo no lleva marca", texto(dlg, "a.txt"), "a.txt")
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
    elegir(dlg, "datos")
    pulsar(dlg, "<Return>")
    c("Intro entra en la carpeta elegida", dlg.ruta.cget("text"), "/datos")
    elegir(dlg, "a.txt")
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
    c("una carpeta con filas no dice que esté vacía", dice_vacia(dlg), False)
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
    c("una carpeta vacía lo dice", dice_vacia(dlg), True)
    cerrar(dlg)

    # -----------------------------------------------------------------------
    # 4. Un permiso denegado deja la lista, lo dice y pone el candado
    # -----------------------------------------------------------------------
    falso = RcdFalso(respuestas())
    dlg = abrir(falso)
    antes = lo_que_se_ve(dlg)
    elegir_y_entrar(dlg, "privado")
    c("la lista sigue con las filas de antes (salvo el candado)",
      (nombres(dlg), [f[:3] for f in lo_que_se_ve(dlg)]),
      (["datos", "privado", "leeme.txt"], [f[:3] for f in antes]))
    c("la ruta no cambia", dlg.ruta.cget("text"), "/")
    c("el indicador lo dice", frase(dlg), "No tienes permiso para ver esta carpeta.")
    c("y no hay botón", boton(dlg), "")
    c("«privado» lleva candado y tono apagado",
      (icono(dlg, "privado"), tono(dlg, "privado")), ("candado", "apagado"))
    c("las demás no", (icono(dlg, "datos"), tono(dlg, "datos")), ("carpeta", "ok"))
    c("el tono apagado es el de la tinta suave del tema",
      str(dlg.lista.tag_configure("apagado", "foreground")), theme.TINTA3)
    cerrar(dlg)

    # -----------------------------------------------------------------------
    # 5. Otro error corriente se dice con la frase de `servidor`
    # -----------------------------------------------------------------------
    falso = RcdFalso(respuestas(otras={("operations/list", "datos"): rcd.ErrorRc("directory not found", 404)}))
    dlg = abrir(falso)
    elegir_y_entrar(dlg, "datos")
    c("una carpeta que ya no existe", frase(dlg), "Esa carpeta ya no existe en el servidor.")
    c("y la lista sigue", nombres(dlg), ["datos", "privado", "leeme.txt"])
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
    c("la lista sigue", dlg.ruta.cget("text"), "/")
    dlg.accion.invoke()
    c("se relanzó rcd", len(LLAMADAS_ARRANCAR), 2)
    c("el viejo se paró", primero.paradas, 1)
    c("el nuevo se esperó y repitió «datos»",
      (segundo.esperas, segundo.listados()[-1]["remote"]), (1, "datos"))
    c("la lista ya tiene lo de «datos» y no queda botón",
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
    c("  y la lista sale", nombres(dlg), ["datos", "privado", "leeme.txt"])
    c("  sin error", (frase(dlg), boton(dlg)), ("", ""))
    c("  y el que no pudo abrir el puerto se paró (no queda apuntado)", uno.paradas, 1)
    cerrar(dlg)

    uno, dos = RcdFalso(respuestas()), RcdFalso(respuestas())
    uno.error_esperar = dos.error_esperar = ocupado
    dlg = abrir(uno, dos)
    c("PuertoOcupado dos veces: no se prueba una tercera", len(LLAMADAS_ARRANCAR), 2)
    c("  el indicador dice el error y deja reintentarlo", (frase(dlg), boton(dlg)),
      (str(ocupado), "Reintentar"))
    c("  y la lista sigue vacía", nombres(dlg), [])
    cerrar(dlg)

    # -----------------------------------------------------------------------
    # 8. Sin red al abrir: «Reintentar» repite la apertura sin relanzar rcd
    # -----------------------------------------------------------------------
    falso = RcdFalso(respuestas(rcd.ErrorRc(
        "couldn't connect: dial tcp 10.0.0.1:22: connection refused", 500)))
    dlg = abrir(falso)
    c("la primera petición falla sin red", frase(dlg), "No hay conexión con el servidor.")
    c("sale «Reintentar»", boton(dlg), "Reintentar")
    c("la lista no dice «vacía» sobre un servidor que no contesta", dice_vacia(dlg), False)
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
    c("  la lista es la de la raíz del otro", nombres(dlg), ["raiz-de-otro"])
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
    c("un cambio de remote fallido deja la lista y el desplegable en el de antes",
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
      {i: valores(dlg, i)[2] for i in nombres(dlg)},
      {"publica": "755", "ajena": "700", "mia": "700", "a.txt": "644"})
    c("la carpeta 0o40700 de otro dueño sale con candado antes de entrar",
      (icono(dlg, "ajena"), tono(dlg, "ajena")), ("candado", "apagado"))
    c("la mía, con la misma máscara, no", icono(dlg, "mia"), "carpeta")
    c("la pública tampoco", icono(dlg, "publica"), "carpeta")
    cerrar(dlg)

    # un remote `local`: mi uid es el del proceso, y no se pregunta por el stat del cwd del rcd
    model.RCLONE_CONF.write_text("[nas]\ntype = local\n", encoding="utf-8")
    uid_previo = servidor.uid_del_proceso
    servidor.uid_del_proceso = lambda: 1000
    en_local = RcdFalso({
        ("operations/fsinfo", None): FSINFO_SI,
        ("operations/list", ""): lista(
            item("ajena", True, mode="40700", uid=1001, gid=1001),
            item("mia", True, mode="40700", uid=1000, gid=1000)),
    })
    dlg = abrir(en_local)
    c("en local no se pide el stat de `<remote>:`",
      [m for m, _p in en_local.llamadas if m == "operations/stat"], [])
    c("  la carpeta ajena lleva candado y la mía no (uid = el del proceso)",
      (icono(dlg, "ajena"), icono(dlg, "mia")), ("candado", "carpeta"))
    cerrar(dlg)
    servidor.uid_del_proceso = uid_previo
    model.RCLONE_CONF.write_text("[nas]\ntype = sftp\nhost = h\n\n[otro]\ntype = webdav\n",
                                 encoding="utf-8")

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
    # 11b. Doble clic solo sobre una fila, Intro, y «vacía» solo con un listado delante
    # -----------------------------------------------------------------------
    model.RCLONE_CONF.write_text("[nas]\ntype = sftp\nhost = h\n\n[otro]\ntype = webdav\n",
                                 encoding="utf-8")
    falso = RcdFalso(respuestas())
    dlg = abrir(falso)
    elegir(dlg, "datos")
    n = len(falso.listados())
    cx, cy = centro(dlg, "datos")
    c("la cabecera es la cabecera para Tk", dlg.lista.identify_region(cx, 2), "heading")
    doble_clic(dlg, cx, 2)                                  # sobre la cabecera
    c("doble clic en la cabecera con una fila elegida no entra en ella",
      (len(falso.listados()), dlg.ruta.cget("text"), dlg.lista.selection()), (n, "/", ("datos",)))
    doble_clic(dlg, 1, 2)                                   # sobre «Nombre», en el borde
    c("  ni en el borde de la cabecera", (len(falso.listados()), dlg.ruta.cget("text")), (n, "/"))
    cx, cy = centro(dlg, "datos")
    doble_clic(dlg, cx, cy)
    c("doble clic en una fila sí entra", (dlg.ruta.cget("text"), nombres(dlg)),
      ("/datos", ["notas", "a.txt"]))
    elegir(dlg, "a.txt")
    n = len(falso.listados())
    doble_clic(dlg, *centro(dlg, "a.txt"))
    c("doble clic en un archivo no hace nada", (len(falso.listados()), dlg.ruta.cget("text")),
      (n, "/datos"))
    # Tk en Windows no tiene `KP_Enter` (`win/tkWinKey.c`: VK_RETURN es siempre `Return`): allí
    # el Intro del teclado numérico llega como `<Return>`, ya comprobado, y generar `<KP_Enter>`
    # no llega a ningún sitio (como en `test_tk_dialogos.py`).
    if raiz.tk.call("tk", "windowingsystem") == "win32":
        print("  (saltado) <KP_Enter>: en Windows Tk lo da como <Return>, ya comprobado")
    else:
        elegir(dlg, "notas")
        pulsar(dlg, "<KP_Enter>")
        c("Intro del teclado numérico entra en la carpeta elegida", dlg.ruta.cget("text"),
          "/datos/notas")
    cerrar(dlg)

    # iids que podrían confundirse con otra cosa: números, llaves, espacios
    raros = ["123", "{llave}", "con espacio", "a\\b", "0"]
    falso = RcdFalso(respuestas(lista(*[item(n_, True) for n_ in raros],
                                      item("zeta.txt", tamano=1))))
    dlg = abrir(falso)
    c("nombres raros son iids distintos y completos",
      sorted(nombres(dlg)), sorted([*raros, "zeta.txt"]))
    c("  y se leen tal cual en el árbol", sorted(texto(dlg, i) for i in raros), sorted(raros))
    elegir_y_entrar(dlg, "123")
    c("  y se entra en una carpeta de nombre numérico", falso.listados()[-1]["remote"], "123")
    cerrar(dlg)

    # «Esta carpeta está vacía.» solo con un listado delante
    lento_ = threading.Event()
    segundo_plano.lanzar = LANZAR_DE_VERDAD
    tarda = RcdFalso(respuestas(lambda: (lento_.wait(5), lista())[1]))
    dlg = abrir(tarda)
    c("mientras conecta, la lista no dice que esté vacía", dice_vacia(dlg), False)
    lento_.set()
    fin = time.monotonic() + 5
    while not dlg.cuenta.cget("text") and time.monotonic() < fin:
        raiz.update()
        time.sleep(0.01)
    c("llegado el listado (vacío), sí lo dice", dice_vacia(dlg), True)
    cerrar(dlg)
    segundo_plano.lanzar = segundo_plano.en_el_acto

    # -----------------------------------------------------------------------
    # 11c. Una carpeta de miles de entradas: la lista solo pinta las que se ven
    # -----------------------------------------------------------------------
    MUCHAS = 5000
    grande = RcdFalso(respuestas(lista(*[item(f"f{n_:05d}.txt", tamano=n_) for n_ in range(MUCHAS)],
                                        *[item(f"d{n_:03d}", True) for n_ in range(20)])))
    errores.clear()
    dlg = abrir(grande)
    dlg.update()
    c("5 000 entradas: la ventana abre, sin error de Tk", errores, [])
    c("  y la lista tiene todas", len(nombres(dlg)), MUCHAS + 20)
    c("  y el pie las cuenta", dlg.cuenta.cget("text"), f"{MUCHAS + 20} elementos")
    c("  y la lista no pide un alto de miles de píxeles", dlg.lista.winfo_reqheight() < 2000, True)
    c("  y la ventana tampoco", dlg.winfo_reqheight() < 3000, True)
    c("  las carpetas van primero y se leen", (nombres(dlg)[0], texto(dlg, "d000")),
      ("d000", "d000"))
    c("  y la última fila se lee", (valores(dlg, "f04999.txt")[0], texto(dlg, "f04999.txt")),
      ("4,9 KB", "f04999.txt"))
    dlg.lista.see("f04999.txt")
    dlg.update()
    c("  se puede desplazar hasta la última fila y verla",
      dlg.lista.bbox("f04999.txt") != "", True)
    cerrar(dlg)

    # un cambio de remote sin rcd (rclone no arrancó) deja el desplegable en el de antes
    rcd.arrancar = no_arranca
    ABIERTAS.clear()
    previo = tk_servidor.mostrar
    tk_servidor.mostrar = lambda dlg_, parent=None: (ABIERTAS.append(dlg_), dlg_.update())
    tk_servidor.open_dialog(raiz, CFG)
    tk_servidor.mostrar = previo
    dlg = ABIERTAS[0]
    dlg.elegido.set("otro")
    dlg.elegido.event_generate("<<ComboboxSelected>>")
    dlg.update()
    c("sin rcd, elegir otro remote devuelve el desplegable al que se enseña",
      (dlg.elegido.get(), frase(dlg), boton(dlg)),
      ("nas", "No se puede ejecutar rclone: nada", "Reintentar"))
    cerrar(dlg)
    rcd.arrancar = arrancar_falso

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

    # -----------------------------------------------------------------------
    # 13. Bajar y subir (pieza 2)
    # -----------------------------------------------------------------------
    model.RCLONE_CONF.write_text("[nas]\ntype = sftp\nhost = h\n\n[otro]\ntype = webdav\n",
                                 encoding="utf-8")
    tk_servidor.INTERVALO_PROGRESO_MS = 5
    CFG2 = mkcfg((), pairs=[
        {"name": "Copia", "local": "sync-data/copia", "remote_path": "/datos/copia",
         "remote": "nas", "mode": "up-mirror"},
        {"name": "Notas", "local": "sync-data/notas", "remote_path": "/datos/notas",
         "remote": "nas", "mode": "bisync"},
        {"name": "Baja", "local": "sync-data/baja", "remote_path": "/datos/baja",
         "remote": "nas", "mode": "down"},
        {"name": "Espejo", "local": "sync-data/espejo", "remote_path": "/datos/espejo",
         "remote": "nas", "mode": "down-mirror"},
        {"name": "Sube", "local": "sync-data/sube", "remote_path": "/datos/sube",
         "remote": "nas", "mode": "up"}], defaults={"remote": "nas"})

    CORRIENDO = {"finished": False}
    ACABADO = {"finished": True, "success": True}
    FALLADO = {"finished": True, "success": False, "error": "permission denied"}

    def stats(hechos=0, total=0, enviados=0, total_bytes=0, **mas) -> dict:
        return {"transfers": hechos, "totalTransfers": total, "bytes": enviados,
                "totalBytes": total_bytes, "speed": 2048, "eta": 5, **mas}

    def secuencia(*items):
        """Una respuesta que va dando `items` y se queda en el último."""
        cola = list(items)
        return lambda: cola.pop(0) if len(cola) > 1 else cola[0]

    class RcdLote(RcdFalso):
        """Un servidor donde lo que no se ha dicho que exista, no existe (`stat` → 404)."""

        def llamar(self, metodo, params=None, timeout=None):
            params = params or {}
            if metodo == "operations/stat" and (metodo, params.get("remote")) not in self.respuestas:
                self.llamadas.append((metodo, params))
                self.orden.append(metodo)
                raise rcd.ErrorRc("object not found", 404)
            return super().llamar(metodo, params, timeout)

    def servidor_lote(estadisticas=(stats(),), estados=(ACABADO,), otras=None) -> RcdFalso:
        """Un servidor que acepta un `sync/copy` (jobid 7) y cuenta cómo va."""
        return RcdLote(respuestas(otras={
            ("sync/copy", None): {"jobid": 7},
            ("core/stats", None): secuencia(*estadisticas),
            ("job/status", None): secuencia(*estados),
            ("job/stop", None): {},
            ("operations/list", "datos/notas"): lista(item("hoy.txt")),
            ("operations/stat", "leeme.txt"): {"item": item("leeme.txt")},
            **(otras or {})}))

    def bombear(condicion, tope: float = 5.0) -> bool:
        """Deja correr el bucle de Tk hasta que se cumpla la condición."""
        fin = time.monotonic() + tope
        while not condicion() and time.monotonic() < fin:
            raiz.update()
            time.sleep(0.005)
        return bool(condicion())

    def estado_de(widget) -> str:
        return str(widget.cget("state"))

    def botones_de(dlg) -> tuple[str, str, str]:
        return (estado_de(dlg.bajar), estado_de(dlg.subir_archivos), estado_de(dlg.subir_carpeta))

    def elegir_varias(dlg, *iids) -> None:
        dlg.lista.selection_set(*iids)
        dlg.update()

    def copias(falso) -> list[dict]:
        return [p for m, p in falso.llamadas if m == "sync/copy"]

    def paradas_de_trabajo(falso) -> int:
        return len([m for m, _p in falso.llamadas if m == "job/stop"])

    def listados_vistos(falso) -> list[dict]:
        """Los listados de una carpeta (no los recursivos de contar choques)."""
        return [p for p in falso.listados() if not p["opt"].get("recurse")]

    def panel_a_la_vista(dlg) -> bool:
        return bool(dlg.panel.marco.winfo_manager()) and bool(dlg.panel.titulo.winfo_manager())

    def frase_panel(dlg) -> str:
        """El texto del resultado del panel."""
        for w in dlg.panel.resultado.winfo_children():
            for h in [w, *w.winfo_children()]:
                if isinstance(h, ttk.Label) and h.cget("text"):
                    return str(h.cget("text"))
        return ""

    LLAMADAS_DIALOGOS: dict[str, list] = {"avisar": [], "preguntar": [], "choques": [],
                                          "destino": [], "archivos": [], "carpeta": []}
    RESPUESTAS_DIALOGOS: dict = {"preguntar": True, "choques": "sobrescribir",
                                 "destino": None, "archivos": [], "carpeta": None}

    def falso_avisar(parent, titulo, texto, tono="Azul."):
        LLAMADAS_DIALOGOS["avisar"].append((titulo, texto))

    def falso_preguntar(parent, titulo, texto, aceptar="Aceptar", cancelar="Cancelar"):
        LLAMADAS_DIALOGOS["preguntar"].append((titulo, texto, aceptar, cancelar))
        return RESPUESTAS_DIALOGOS["preguntar"]

    def falso_choques(parent, texto):
        LLAMADAS_DIALOGOS["choques"].append(texto)
        return RESPUESTAS_DIALOGOS["choques"]

    def falso_destino(parent, inicial):
        LLAMADAS_DIALOGOS["destino"].append(inicial)
        return RESPUESTAS_DIALOGOS["destino"]

    def falso_archivos(parent, inicial):
        LLAMADAS_DIALOGOS["archivos"].append(inicial)
        return RESPUESTAS_DIALOGOS["archivos"]

    def falso_carpeta(parent, inicial):
        LLAMADAS_DIALOGOS["carpeta"].append(inicial)
        return RESPUESTAS_DIALOGOS["carpeta"]

    def dialogos(**respuestas_) -> None:
        """Reinicia lo apuntado y fija lo que contestan los diálogos."""
        for lista_ in LLAMADAS_DIALOGOS.values():
            lista_.clear()
        RESPUESTAS_DIALOGOS.update({"preguntar": True, "choques": "sobrescribir",
                                    "destino": None, "archivos": [], "carpeta": None})
        RESPUESTAS_DIALOGOS.update(respuestas_)

    tk_servidor.avisar, tk_servidor.preguntar = falso_avisar, falso_preguntar
    tk_transferencia.preguntar_choques = falso_choques
    tk_servidor.elegir_destino, tk_servidor.elegir_archivos = falso_destino, falso_archivos
    tk_servidor.elegir_carpeta = falso_carpeta

    # --- 13a. Los botones y cuándo se encienden --------------------------------
    dialogos()
    falso = servidor_lote(estados=(CORRIENDO,))
    dlg = abrir(falso)
    c("los tres botones llevan su rótulo",
      (str(dlg.bajar.cget("text")), str(dlg.subir_archivos.cget("text")),
       str(dlg.subir_carpeta.cget("text"))), ("Bajar…", "Subir archivos…", "Subir carpeta…"))
    c("con rcd y sin selección: «Bajar…» apagado, las dos «Subir…» encendidas",
      botones_de(dlg), ("disabled", "normal", "normal"))
    elegir_varias(dlg, "datos")
    c("con una fila elegida «Bajar…» se enciende", botones_de(dlg)[0], "normal")
    elegir_varias(dlg, "datos", "leeme.txt")
    c("la lista admite varias filas a la vez", sorted(dlg.lista.selection()), ["datos", "leeme.txt"])
    c("  y «Bajar…» sigue encendido", botones_de(dlg)[0], "normal")
    n = len(falso.listados())
    pulsar(dlg, "<Return>")
    c("Intro con dos filas elegidas no entra en ninguna", (len(falso.listados()), dlg.ruta.cget("text")),
      (n, "/"))
    elegir_varias(dlg, "datos")
    dlg.lista.selection_remove("datos")
    dlg.update()
    c("quitar la selección apaga «Bajar…»", botones_de(dlg)[0], "disabled")
    # a mitad de un lote, los tres apagados
    dialogos(destino=str(tmpdir()))
    elegir_varias(dlg, "leeme.txt")
    dlg.bajar.invoke()
    c("el panel sale y enseña el título", bombear(lambda: panel_a_la_vista(dlg)), True)
    c("durante el lote los tres botones están apagados", botones_de(dlg),
      ("disabled", "disabled", "disabled"))
    elegir_varias(dlg, "datos")
    c("  y elegir otra fila no enciende «Bajar…»", botones_de(dlg)[0], "disabled")
    dlg.bajar.invoke()
    dlg.subir_archivos.invoke()
    c("  pulsarlos a la fuerza no lanza otro lote", (len(copias(falso)), LLAMADAS_DIALOGOS["archivos"]),
      (1, []))
    cerrar(dlg)

    # sin rcd (rclone no arrancó) no se enciende ninguno
    rcd.arrancar = no_arranca
    ABIERTAS.clear()
    previo = tk_servidor.mostrar
    tk_servidor.mostrar = lambda dlg_, parent=None: (ABIERTAS.append(dlg_), dlg_.update())
    tk_servidor.open_dialog(raiz, CFG)
    tk_servidor.mostrar = previo
    dlg = ABIERTAS[0]
    c("sin rcd los tres botones están apagados", botones_de(dlg),
      ("disabled", "disabled", "disabled"))
    cerrar(dlg)
    rcd.arrancar = arrancar_falso

    # --- 13b. Bajar con su estructura, el progreso y el resultado ---------------
    destino = tmpdir()
    (destino / "datos").mkdir()
    (destino / "datos" / "a.txt").write_text("viejo", encoding="utf-8")
    (destino / "leeme.txt").write_text("viejo", encoding="utf-8")
    dialogos(destino=str(destino), choques="omitir")
    falso = servidor_lote(
        estadisticas=(stats(), stats(3, 10, 1024, 4096, transferring=[{"name": "datos/b.txt"}]),
                      stats(3, 10, 4096, 4096, checks=5)),
        estados=(CORRIENDO, CORRIENDO, ACABADO),
        otras={("operations/list", "datos"): lista(item("notas", True), item("a.txt"))})
    # el listado recursivo de «datos» da rutas relativas a «datos»
    listado_normal = falso.respuestas[("operations/list", "datos")]
    falso.respuestas[("operations/list", "datos")] = lambda: listado_normal
    dlg = abrir(falso)
    elegir_varias(dlg, "datos", "leeme.txt")
    dlg.bajar.invoke()
    c("«Bajar…» empieza el diálogo en una carpeta del equipo",
      len(LLAMADAS_DIALOGOS["destino"]), 1)
    c("el aviso de choques salió una vez, con el plural y el destino",
      LLAMADAS_DIALOGOS["choques"], [f"2 elementos ya existen en {destino}. ¿Sobrescribirlos u omitirlos?"])
    c("se lanzó un solo sync/copy", len(copias(falso)), 1)
    cp = copias(falso)[0]
    c("  de «nas:/» a la carpeta elegida", (cp["srcFs"], cp["dstFs"]), ("nas:/", str(destino)))
    c("  con la estructura del servidor: «datos» entera y «leeme.txt»",
      sorted(cp["_filter"]["IncludeRule"]), ["/datos/**", "/leeme.txt"])
    c("  con «Omitir»: IgnoreExisting", cp.get("_config"), {"IgnoreExisting": True})
    c("  asíncrono, con su grupo y carpetas vacías",
      (cp["_async"], cp["_group"], cp["createEmptySrcDirs"]), (True, "lote-1", True))
    c("  y nada que borre", [m for m, _p in falso.llamadas
                            if m in ("sync/sync", "sync/move", "operations/purge",
                                     "operations/deletefile")], [])
    c("el panel enseña el título del lote en curso",
      bombear(lambda: dlg.panel.titulo.cget("text") == f"Bajando a {destino}"), True)
    c("el progreso avanza en el panel",
      bombear(lambda: str(dlg.panel.cuenta.cget("text")).startswith("3 de 10 archivos")), True)
    c("  con el archivo en curso", str(dlg.panel.archivo.cget("text")), "datos/b.txt")
    c("al acabar, «Copiados … · omitidos …» (los dos choques que se omitieron)",
      bombear(lambda: frase_panel(dlg) == "Copiados 3 · omitidos 2"), True)
    c("  el progreso se esconde y no hay «Reintentar»",
      (bool(dlg.panel.titulo.winfo_manager()), bool(dlg.panel.reintentar.winfo_manager())),
      (False, False))
    c("  y los botones vuelven", botones_de(dlg)[0], "normal")
    dlg.bajar.invoke()
    c("  la última carpeta del equipo se recuerda: el segundo diálogo empieza en ella",
      LLAMADAS_DIALOGOS["destino"][-1], str(destino))
    c("  y el grupo del segundo lote es otro",
      copias(falso)[-1]["_group"], "lote-2")
    cerrar(dlg)

    # sin choques: no se pregunta, y «Sobrescribir» no pone IgnoreExisting
    dialogos(destino=str(tmpdir()), choques="sobrescribir")
    falso = servidor_lote(estados=(ACABADO,), estadisticas=(stats(1, 1, 5, 5),))
    dlg = abrir(falso)
    elegir_varias(dlg, "leeme.txt")
    falso.respuestas[("operations/stat", "leeme.txt")] = {"item": item("leeme.txt")}
    dlg.bajar.invoke()
    bombear(lambda: frase_panel(dlg) != "")
    c("sin nada que choque no se pregunta y se copia sin IgnoreExisting",
      (LLAMADAS_DIALOGOS["choques"], "_config" in copias(falso)[0]), ([], False))
    c("  «Copiados 1» sin omitidos", frase_panel(dlg), "Copiados 1")
    cerrar(dlg)

    # un choque: singular; «Sobrescribir» no pone IgnoreExisting; Cancelar no copia
    unico = tmpdir()
    (unico / "leeme.txt").write_text("viejo", encoding="utf-8")
    for respuesta, copia, omite in (("sobrescribir", True, False), ("omitir", True, True),
                                    (None, False, False)):
        dialogos(destino=str(unico), choques=respuesta)
        falso = servidor_lote()
        dlg = abrir(falso)
        elegir_varias(dlg, "leeme.txt")
        dlg.bajar.invoke()
        bombear(lambda: frase_panel(dlg) != "" or not copia)
        c(f"un choque, respuesta {respuesta!r}: el texto va en singular",
          LLAMADAS_DIALOGOS["choques"],
          [f"1 elemento ya existe en {unico}. ¿Sobrescribirlo u omitirlo?"])
        c("  se copia o no según la respuesta", len(copias(falso)), 1 if copia else 0)
        if copia:
            c("  y IgnoreExisting solo con «Omitir»", "_config" in copias(falso)[0], omite)
        else:
            c("  «Cancelar» no deja nada en el panel y devuelve los botones",
              (panel_a_la_vista(dlg), botones_de(dlg)[0]), (False, "normal"))
        cerrar(dlg)

    # «omitidos» es el número de choques que se omitieron, no lo que cuente `checks`
    for respuesta, esperado in (("sobrescribir", "Copiados 3"), ("omitir", "Copiados 3 · omitidos 1")):
        dialogos(destino=str(unico), choques=respuesta)
        falso = servidor_lote(estadisticas=(stats(3, 3, 9, 9, checks=5),))
        dlg = abrir(falso)
        elegir_varias(dlg, "leeme.txt")
        dlg.bajar.invoke()
        c(f"el resultado con {respuesta!r} y 5 comprobados: la cuenta no sale de `checks`",
          bombear(lambda: frase_panel(dlg) == esperado), True)
        cerrar(dlg)
    dialogos(destino=str(unico), choques="omitir")
    falso = servidor_lote(estadisticas=(stats(3, 3, 9, 9, checks=5),), estados=(FALLADO,))
    dlg = abrir(falso)
    elegir_varias(dlg, "leeme.txt")
    dlg.bajar.invoke()
    bombear(lambda: bool(dlg.panel.reintentar.winfo_manager()))
    falso.respuestas[("job/status", None)] = ACABADO
    dlg.panel.reintentar.invoke()
    c("«Reintentar» tras «Omitir» conserva los omitidos del lote",
      bombear(lambda: frase_panel(dlg) == "Copiados 3 · omitidos 1"), True)
    cerrar(dlg)

    # --- 13c. Un nombre con caracteres de patrón llega escapado a sync/copy -----
    dialogos(destino=str(tmpdir()))
    falso = servidor_lote(otras={
        ("operations/list", ""): lista(item("raro [1]*"), item("!x.txt"), item("a b?.txt"),
                                       item("dir{1}", True)),
        ("operations/stat", "raro [1]*"): {"item": item("raro [1]*")},
        ("operations/stat", "!x.txt"): {"item": item("!x.txt")},
        ("operations/stat", "a b?.txt"): {"item": item("a b?.txt")},
        ("operations/list", "dir{1}"): lista()})
    dlg = abrir(falso)
    elegir_varias(dlg, "raro [1]*", "!x.txt", "a b?.txt", "dir{1}")
    dlg.bajar.invoke()
    bombear(lambda: frase_panel(dlg) != "")
    c("las reglas que llegan a sync/copy están escapadas y son solo lo elegido",
      sorted(copias(falso)[0]["_filter"]["IncludeRule"]),
      sorted(["/raro \\[1\\]\\*", "/!x.txt", "/a b\\?.txt", "/dir\\{1\\}/**"]))
    c("  y se miró cada archivo por su nombre sin escapar (stat) y la carpeta (list recursivo)",
      sorted(p["remote"] for m, p in falso.llamadas
             if m == "operations/stat" and p["remote"] not in ("",)),
      sorted(["raro [1]*", "!x.txt", "a b?.txt"]))
    cerrar(dlg)

    # --- 13d. Subir: bloqueo, aviso por modo y choques --------------------------
    origen = tmpdir()
    (origen / "uno.txt").write_text("1", encoding="utf-8")
    (origen / "dos.txt").write_text("2", encoding="utf-8")
    (origen / "fotos").mkdir()
    (origen / "fotos" / "a.jpg").write_text("a", encoding="utf-8")
    (origen / "fotos" / "b.jpg").write_text("b", encoding="utf-8")
    nuevo_rcd = lambda o=None: servidor_lote(otras={  # noqa: E731
        ("operations/list", "datos/copia"): lista(), ("operations/list", "datos/baja"): lista(),
        ("operations/list", "datos/espejo"): lista(), ("operations/list", "datos/sube"): lista(),
        ("operations/list", "datos/notas"): lista(item("hoy.txt")), **(o or {})})

    dialogos(archivos=[str(origen / "uno.txt")])
    falso = nuevo_rcd()
    dlg = abrir(falso, config=CFG2)
    elegir_y_entrar(dlg, "datos")
    elegir_varias(dlg)
    falso.respuestas[("operations/list", "datos")] = lista(
        item("copia", True), item("notas", True), item("baja", True), item("espejo", True),
        item("sube", True), item("fotos", True))
    dlg.arriba.invoke()
    elegir_y_entrar(dlg, "datos")
    elegir_y_entrar(dlg, "copia")
    c("estamos dentro de «Copia» (up-mirror)", dlg.ruta.cget("text"), "/datos/copia")
    dlg.subir_archivos.invoke()
    c("subir a una pareja up-mirror se bloquea con «No se puede»",
      LLAMADAS_DIALOGOS["avisar"],
      [("No se puede", "«Copia» deja el servidor igual que el dispositivo: lo que subas aquí lo "
                       "borraría su próxima pasada. Súbelo a su carpeta del dispositivo.")])
    c("  y no se copia ni se mira el destino",
      (copias(falso), [p for p in falso.listados() if p["opt"].get("recurse")]), ([], []))
    c("  ni queda un lote en marcha", (panel_a_la_vista(dlg), botones_de(dlg)[1]), (False, "normal"))

    dialogos(archivos=[str(origen / "uno.txt")], preguntar=False)
    dlg.arriba.invoke()
    elegir_y_entrar(dlg, "notas")
    c("estamos dentro de «Notas» (bisync)", dlg.ruta.cget("text"), "/datos/notas")
    dlg.subir_archivos.invoke()
    c("subir a una pareja bisync pregunta con el texto del modo",
      LLAMADAS_DIALOGOS["preguntar"],
      [("Carpeta de una pareja",
        "Lo que subas a «Notas» lo bajará al dispositivo su próxima pasada; si sobrescribes "
        "algo que también ha cambiado allí, saldrá un conflicto.", "Seguir", "Cancelar")])
    c("  «Cancelar» no copia nada y deja los botones", (copias(falso), botones_de(dlg)[1]),
      ([], "normal"))
    dialogos(archivos=[str(origen / "uno.txt")], preguntar=True)
    dlg.subir_archivos.invoke()
    c("  «Seguir» copia: «uno.txt» a la raíz absoluta de la carpeta",
      bombear(lambda: len(copias(falso)) == 1), True)
    cp = copias(falso)[0]
    c("  de la carpeta del equipo a «nas:/datos/notas», con su regla",
      (cp["srcFs"], cp["dstFs"], cp["_filter"]["IncludeRule"]),
      (str(origen), "nas:/datos/notas", ["/uno.txt"]))
    c("  sin choques (el servidor tiene «hoy.txt», no «uno.txt»)",
      (LLAMADAS_DIALOGOS["choques"], "_config" in cp), ([], False))
    c("  el título del panel es «Subiendo a /datos/notas»",
      bombear(lambda: frase_panel(dlg) != ""), True)
    c("  y al acabar relee la carpeta que se ve",
      listados_vistos(falso)[-1]["remote"], "datos/notas")
    n_antes = len(listados_vistos(falso))
    dialogos(archivos=[str(origen / "uno.txt")], preguntar=True)
    dlg.subir_archivos.invoke()
    bombear(lambda: len(copias(falso)) == 2 and frase_panel(dlg) != "")
    bombear(lambda: len(listados_vistos(falso)) > n_antes)
    c("  tras cada subida a la carpeta que se ve hay un listado nuevo de ella",
      len(listados_vistos(falso)) > n_antes, True)
    cerrar(dlg)

    # los demás modos avisan con su texto (up, down, down-mirror)
    for pareja, carpeta_, texto_ in (
            ("Baja", "baja", "Lo que subas a «Baja» lo bajará al dispositivo su próxima pasada."),
            ("Espejo", "espejo", "Lo que subas a «Espejo» lo bajará al dispositivo su próxima pasada."),
            ("Sube", "sube", "«Sube» solo sube del dispositivo: lo que subas aquí se quedará en el servidor.")):
        dialogos(archivos=[str(origen / "uno.txt")], preguntar=False)
        falso = nuevo_rcd()
        dlg = abrir(falso, config=CFG2)
        falso.respuestas[("operations/list", "")] = lista(item("datos", True))
        dlg.arriba.invoke()
        falso.respuestas[("operations/list", "datos")] = lista(item(carpeta_, True))
        elegir_y_entrar(dlg, "datos")
        elegir_y_entrar(dlg, carpeta_)
        dlg.subir_archivos.invoke()
        c(f"subir a «{pareja}» avisa con el texto de su modo",
          [t[1] for t in LLAMADAS_DIALOGOS["preguntar"]], [texto_])
        cerrar(dlg)

    # --- 13e. Subir una carpeta y los choques de la subida ---------------------
    dialogos(carpeta=str(origen / "fotos"), choques=None)
    falso = nuevo_rcd({
        ("operations/list", "fotos"): lista(item("a.jpg"), item("b.jpg"), item("c.jpg"))})
    falso.respuestas[("operations/list", "")] = lista(item("datos", True), item("fotos", True))
    dlg = abrir(falso)
    # el listado recursivo de «fotos» trae las rutas bajo «fotos»
    falso.respuestas[("operations/list", "fotos")] = lambda: {"list": [
        {"Name": "a.jpg", "Path": "a.jpg", "IsDir": False, "Size": 1},
        {"Name": "b.jpg", "Path": "b.jpg", "IsDir": False, "Size": 1},
        {"Name": "sub", "Path": "sub", "IsDir": True, "Size": -1}]}
    dlg.subir_carpeta.invoke()
    c("subir una carpeta pregunta por los choques: dos archivos coinciden (la subcarpeta no cuenta)",
      LLAMADAS_DIALOGOS["choques"], ["2 elementos ya existen en /. ¿Sobrescribirlos u omitirlos?"])
    c("  la recursión se pidió solo de «fotos» en el servidor",
      [p["remote"] for p in falso.listados() if p["opt"].get("recurse")], ["fotos"])
    c("  «Cancelar» no copia nada", copias(falso), [])
    dialogos(carpeta=str(origen / "fotos"), choques="omitir")
    dlg.subir_carpeta.invoke()
    bombear(lambda: len(copias(falso)) == 1)
    cp = copias(falso)[0]
    c("  «Omitir» copia la carpeta entera con IgnoreExisting",
      (cp["srcFs"], cp["dstFs"], cp["_filter"]["IncludeRule"], cp.get("_config")),
      (str(origen), "nas:/", ["/fotos/**"], {"IgnoreExisting": True}))
    bombear(lambda: frase_panel(dlg) != "")
    c("  al acabar en la raíz que se ve, relee la raíz", listados_vistos(falso)[-1]["remote"], "")
    # raíz de una unidad
    dialogos(carpeta="/")
    n = len(copias(falso))
    dlg.subir_carpeta.invoke()
    c("la raíz de una unidad no se sube: se dice", (len(copias(falso)), LLAMADAS_DIALOGOS["avisar"]),
      (n, [("No se puede", tk_servidor.SIN_RAIZ)]))
    cerrar(dlg)

    # un destino que no existe en el servidor no choca (404 = «no está»)
    dialogos(archivos=[str(origen / "uno.txt")])
    falso = nuevo_rcd({("operations/stat", ""): {"item": None}})
    dlg = abrir(falso)
    falso.respuestas[("operations/stat", "uno.txt")] = rcd.ErrorRc("object not found", 404)
    dlg.subir_archivos.invoke()
    bombear(lambda: len(copias(falso)) == 1)
    c("un archivo que no existe en el servidor (404) no choca y se copia",
      (LLAMADAS_DIALOGOS["choques"], len(copias(falso))), ([], 1))
    cerrar(dlg)

    # un error de verdad al contar se dice con «Reintentar»; no copia
    dialogos(archivos=[str(origen / "uno.txt")])
    falso = nuevo_rcd()
    falso.respuestas[("operations/stat", "uno.txt")] = rcd.ErrorRc("permission denied", 403)
    dlg = abrir(falso)
    dlg.subir_archivos.invoke()
    c("un error al mirar el destino sale en el panel, sin copiar",
      (frase_panel(dlg), copias(falso), botones_de(dlg)[1]),
      ("No tienes permiso para escribir en /.", [], "normal"))
    c("  con «Reintentar»", bool(dlg.panel.reintentar.winfo_manager()), True)
    falso.respuestas[("operations/stat", "uno.txt")] = rcd.ErrorRc("object not found", 404)
    dlg.panel.reintentar.invoke()
    bombear(lambda: len(copias(falso)) == 1)
    c("  «Reintentar» repite el lote desde el principio", len(copias(falso)), 1)
    cerrar(dlg)

    # bajar dentro de la carpeta local de una pareja
    espejo = str(model.DEVICE_ROOT / "sync-data" / "espejo")
    dialogos(destino=espejo)
    falso = servidor_lote()
    dlg = abrir(falso, config=CFG2)
    elegir_varias(dlg, "leeme.txt")
    dlg.bajar.invoke()
    c("bajar a la carpeta de una pareja down-mirror se bloquea",
      (LLAMADAS_DIALOGOS["avisar"], copias(falso)),
      ([("No se puede", "«Espejo» deja su carpeta igual que el servidor: lo que bajes aquí lo "
                        "borraría su próxima pasada. Bájalo fuera de ella.")], []))
    dialogos(destino=str(model.DEVICE_ROOT / "sync-data" / "notas"), preguntar=False)
    dlg.bajar.invoke()
    c("  y a la de una bisync avisa antes de seguir",
      [t[:2] for t in LLAMADAS_DIALOGOS["preguntar"]],
      [("Carpeta de una pareja",
        "Lo que bajes a la carpeta de «Notas» lo subirá al servidor su próxima pasada.")])
    c("  y con «Cancelar» no copia", copias(falso), [])
    cerrar(dlg)

    # --- 13f. Cancelar ---------------------------------------------------------
    dialogos(destino=str(tmpdir()))
    parado = threading.Event()
    estados_cancelar = lambda: ({"finished": True, "success": False, "error": "context canceled"}  # noqa: E731
                                if parado.is_set() else CORRIENDO)

    def parar_trabajo():
        parado.set()
        return {}
    falso = servidor_lote(
        estadisticas=(stats(3, 8, 100, 800),), estados=(CORRIENDO,),
        otras={("job/status", None): estados_cancelar, ("job/stop", None): parar_trabajo})
    dlg = abrir(falso)
    elegir_varias(dlg, "leeme.txt")
    falso.respuestas[("operations/stat", "leeme.txt")] = {"item": item("leeme.txt")}
    dlg.bajar.invoke()
    bombear(lambda: str(dlg.panel.cuenta.cget("text")).startswith("3 de 8 archivos"))
    dlg.panel.cancelar.invoke()
    dlg.panel.cancelar.invoke()
    dlg.panel.cancelar.invoke()
    c("«Cancelar» manda job/stop una sola vez, aunque se pulse tres", paradas_de_trabajo(falso), 1)
    c("  y con el jobid del lote", [p for m, p in falso.llamadas if m == "job/stop"], [{"jobid": 7}])
    c("el panel dijo «Cancelando…» en el acto y dejó el botón apagado",
      (str(dlg.panel.archivo.cget("text")), estado_de(dlg.panel.cancelar)),
      ("Cancelando…", "disabled"))
    c("al acabar el trabajo: «Cancelado: copiados 3 de 8»",
      bombear(lambda: frase_panel(dlg) == "Cancelado: copiados 3 de 8"), True)
    c("  sin «Reintentar» y con los botones de vuelta",
      (bool(dlg.panel.reintentar.winfo_manager()), botones_de(dlg)[0]), (False, "normal"))
    cerrar(dlg)

    # --- 13g. Un fallo del trabajo: la frase y «Reintentar» --------------------
    destino = str(tmpdir())
    dialogos(destino=destino)
    falso = servidor_lote(estados=(FALLADO,), estadisticas=(stats(2, 5),))
    dlg = abrir(falso)
    elegir_varias(dlg, "leeme.txt")
    falso.respuestas[("operations/stat", "leeme.txt")] = {"item": item("leeme.txt")}
    dlg.bajar.invoke()
    c("un trabajo que falla por permiso lo dice en llano",
      bombear(lambda: frase_panel(dlg) == f"No tienes permiso para escribir en {destino}."), True)
    c("  y ofrece «Reintentar»", bool(dlg.panel.reintentar.winfo_manager()), True)
    falso.respuestas[("job/status", None)] = ACABADO
    dlg.panel.reintentar.invoke()
    bombear(lambda: frase_panel(dlg).startswith("Copiados"))
    c("  «Reintentar» repite el mismo lote con las mismas reglas y otro grupo",
      ([c_["_filter"] for c_ in copias(falso)], [c_["_group"] for c_ in copias(falso)]),
      ([{"IncludeRule": ["/leeme.txt"]}] * 2, ["lote-1", "lote-2"]))
    c("  y acaba bien", frase_panel(dlg), "Copiados 2")
    cerrar(dlg)

    # --- 13h. La conexión se pierde a mitad de un lote -------------------------
    dialogos(destino=str(tmpdir()))
    hay = threading.Event()

    def se_cae():
        if hay.is_set():
            falso.vivo = False                  # el proceso murió: la copia murió con él
            raise rcd.RcdCaido("Connection refused")
        return CORRIENDO
    falso = servidor_lote(otras={("job/status", None): se_cae})
    dlg = abrir(falso)
    elegir_varias(dlg, "leeme.txt")
    falso.respuestas[("operations/stat", "leeme.txt")] = {"item": item("leeme.txt")}
    dlg.bajar.invoke()
    bombear(lambda: panel_a_la_vista(dlg))
    hay.set()
    c("una conexión perdida a mitad: el panel lo dice",
      bombear(lambda: frase_panel(dlg) == "Se perdió la conexión con rclone."), True)
    c("  el indicador ofrece «Reconectar»", (boton(dlg), frase(dlg)),
      ("Reconectar", "Se ha perdido la conexión con rclone."))
    c("  los botones vuelven y el lote no se reanuda solo",
      (botones_de(dlg)[0], bool(dlg.panel.reintentar.winfo_manager()), len(copias(falso))),
      ("normal", False, 1))
    cerrar(dlg)

    # lo mismo si el seguimiento falla con un error de rclone y el proceso ya murió
    dialogos(destino=str(tmpdir()))
    hay = threading.Event()

    def se_cae_con_error():
        if hay.is_set():
            falso.vivo = False
            raise rcd.ErrorRc("HTTP 500", 500)
        return CORRIENDO
    falso = servidor_lote(otras={("job/status", None): se_cae_con_error})
    dlg = abrir(falso)
    elegir_varias(dlg, "leeme.txt")
    falso.respuestas[("operations/stat", "leeme.txt")] = {"item": item("leeme.txt")}
    dlg.bajar.invoke()
    bombear(lambda: panel_a_la_vista(dlg))
    hay.set()
    c("un ErrorRc del seguimiento con el proceso muerto también es conexión perdida",
      bombear(lambda: frase_panel(dlg) == "Se perdió la conexión con rclone."), True)
    c("  con «Reconectar», los botones libres y sin «Reintentar»",
      (boton(dlg), botones_de(dlg)[0], bool(dlg.panel.reintentar.winfo_manager())),
      ("Reconectar", "normal", False))
    cerrar(dlg)

    # --- 13h2. Un seguimiento que falla con el rcd vivo no libera el lote -------
    # Mientras el proceso viva la copia puede seguir: nada de «Reintentar» ni de
    # un segundo `sync/copy`; solo acaba cuando `job/status` dice `finished`.
    for variante in ("se recupera", "sigue sin contestar"):
        dialogos(destino=str(tmpdir()), preguntar=False)
        recupera = threading.Event()
        fallos_ = [0]
        fallan = tk_servidor.FALLOS_PARA_AVISAR + 1

        def seguimiento():
            if recupera.is_set():
                return ACABADO
            fallos_[0] += 1
            if fallos_[0] > fallan and variante == "se recupera":
                return CORRIENDO
            if fallos_[0] % 2:
                raise rcd.RcdCaido("timed out")
            raise rcd.ErrorRc("HTTP 500", 500)
        falso = servidor_lote(otras={("job/status", None): seguimiento})
        dlg = abrir(falso)
        elegir_varias(dlg, "leeme.txt")
        falso.respuestas[("operations/stat", "leeme.txt")] = {"item": item("leeme.txt")}
        dlg.bajar.invoke()
        c(f"[{variante}] el seguimiento falla varias veces y se dice en la ventana",
          bombear(lambda: frase(dlg) == tk_servidor.SIN_RESPUESTA), True)
        c("  el lote sigue: los tres botones apagados, el panel a la vista, sin «Reintentar»",
          (botones_de(dlg), panel_a_la_vista(dlg), bool(dlg.panel.reintentar.winfo_manager()),
           boton(dlg)), (("disabled", "disabled", "disabled"), True, False, ""))
        dlg.bajar.invoke()
        dlg.subir_archivos.invoke()
        c("  pulsarlos a la fuerza no lanza otro lote", (len(copias(falso)), LLAMADAS_DIALOGOS["archivos"]),
          (1, []))
        LLAMADAS_DIALOGOS["preguntar"].clear()
        dlg.tk.call(dlg.protocol("WM_DELETE_WINDOW"))
        c("  cerrar sigue preguntando (la copia puede estar en marcha)",
          (len(LLAMADAS_DIALOGOS["preguntar"]), bool(dlg.winfo_exists()), falso.paradas),
          (1, True, 0))
        if variante == "sigue sin contestar":
            for _ in range(40):                 # y se sigue intentando, sin acabar
                raiz.update()
                time.sleep(0.005)
            c("  tras mucho tiempo sin respuesta el lote no se dio por acabado",
              (botones_de(dlg), len(copias(falso)), fallos_[0] > fallan), (("disabled",) * 3, 1, True))
        else:
            c("  al contestar otra vez la línea de aviso se quita y el lote sigue",
              (bombear(lambda: fallos_[0] > fallan + 2 and frase(dlg) == ""), botones_de(dlg)[0],
               len(copias(falso))), (True, "disabled", 1))
        recupera.set()
        c("  cuando por fin contesta que acabó, acaba bien y los botones vuelven",
          bombear(lambda: frase_panel(dlg) == "Copiados 0"), True)
        c("  la línea de aviso se quita", frase(dlg) != tk_servidor.SIN_RESPUESTA, True)
        c("  y nunca hubo un segundo sync/copy", (len(copias(falso)), botones_de(dlg)[0]),
          (1, "normal"))
        cerrar(dlg)

    # --- 13h4. «job not found»: rclone olvidó un trabajo que ya acabó ----------
    # Con el rcd vivo, rclone borra los trabajos ~60 s después de acabar: un
    # seguimiento que ya no lo encuentra da el lote por acabado, sin colgar el panel.
    dialogos(destino=str(tmpdir()))
    fallos_ = [0]

    def olvidado():
        fallos_[0] += 1
        if fallos_[0] <= tk_servidor.FALLOS_PARA_AVISAR:
            raise rcd.RcdCaido("timed out")         # primero la línea de aviso se enciende
        raise rcd.ErrorRc("job not found", 500)
    falso = servidor_lote(otras={("job/status", None): olvidado})
    dlg = abrir(falso)
    elegir_varias(dlg, "leeme.txt")
    falso.respuestas[("operations/stat", "leeme.txt")] = {"item": item("leeme.txt")}
    dlg.bajar.invoke()
    c("«job not found» con el rcd vivo: el panel dice que no se sabe cómo acabó",
      bombear(lambda: frase_panel(dlg) == "No se sabe cómo acabó: revisa la carpeta."), True)
    c("  sin «Reintentar», los tres botones libres y la línea de aviso se quita",
      (bool(dlg.panel.reintentar.winfo_manager()), botones_de(dlg), frase(dlg)),
      (False, ("normal",) * 3, ""))
    c("  y nunca hubo un segundo sync/copy", len(copias(falso)), 1)
    cerrar(dlg)

    # un fallo suelto (menos que FALLOS_PARA_AVISAR) ni siquiera se dice
    dialogos(destino=str(tmpdir()))
    fallos_ = [0]

    def un_tropiezo():
        fallos_[0] += 1
        if fallos_[0] == 1:
            raise rcd.RcdCaido("timed out")
        return ACABADO
    falso = servidor_lote(otras={("job/status", None): un_tropiezo})
    dlg = abrir(falso)
    elegir_varias(dlg, "leeme.txt")
    falso.respuestas[("operations/stat", "leeme.txt")] = {"item": item("leeme.txt")}
    dlg.bajar.invoke()
    c("un solo fallo del seguimiento: el lote acaba bien, sin avisos ni segundo copy",
      (bombear(lambda: frase_panel(dlg) == "Copiados 0"), frase(dlg), len(copias(falso))),
      (True, "", 1))
    cerrar(dlg)

    # --- 13h3. Un listado que llega con el diálogo abierto no cambia a dónde va el lote
    # El diálogo del sistema corre su propio bucle de eventos: mientras está abierto
    # puede llegar el listado de otra carpeta y mover `nav`.
    destino_ = tmpdir()
    origen_ = tmpdir()
    (origen_ / "sube.txt").write_text("x", encoding="utf-8")
    (origen_ / "carpeta").mkdir()
    (origen_ / "carpeta" / "dentro.txt").write_text("x", encoding="utf-8")
    ventana: dict = {}

    def entrar_durante_el_dialogo(respuesta):
        """Un diálogo que, mientras está abierto, deja llegar el listado de «datos»."""
        def dialogo(parent, inicial):
            dlg_ = ventana["dlg"]
            elegir_y_entrar(dlg_, "datos")
            bombear(lambda: str(dlg_.ruta.cget("text")) == "/datos")
            return respuesta
        return dialogo

    previos_ = (tk_servidor.elegir_destino, tk_servidor.elegir_archivos, tk_servidor.elegir_carpeta)
    for nombre_, boton_, ajustar in (
            ("bajar", "bajar", lambda: setattr(tk_servidor, "elegir_destino",
                                                entrar_durante_el_dialogo(str(destino_)))),
            ("subir archivos", "subir_archivos", lambda: setattr(
                tk_servidor, "elegir_archivos",
                entrar_durante_el_dialogo([str(origen_ / "sube.txt")]))),
            ("subir carpeta", "subir_carpeta", lambda: setattr(
                tk_servidor, "elegir_carpeta", entrar_durante_el_dialogo(str(origen_ / "carpeta"))))):
        dialogos()
        falso = servidor_lote(estados=(ACABADO,), estadisticas=(stats(1, 1, 5, 5),),
                              otras={("operations/list", "carpeta"): lista()})
        dlg = abrir(falso)
        ventana["dlg"] = dlg
        ajustar()
        elegir_varias(dlg, "leeme.txt")
        getattr(dlg, boton_).invoke()
        c(f"[{nombre_}] mientras el diálogo estaba abierto se entró en «datos»",
          bombear(lambda: len(copias(falso)) == 1) and str(dlg.ruta.cget("text")), "/datos")
        cp = copias(falso)[0]
        c("  y el lote va a donde se vio al pulsar: la raíz, no «datos»",
          (cp["srcFs"], cp["dstFs"]) if nombre_ == "bajar" else (cp["dstFs"],),
          ("nas:/", str(destino_)) if nombre_ == "bajar" else ("nas:/",))
        if nombre_ == "bajar":
            c("  con la selección de entonces", cp["_filter"]["IncludeRule"], ["/leeme.txt"])
        cerrar(dlg)
        (tk_servidor.elegir_destino, tk_servidor.elegir_archivos,
         tk_servidor.elegir_carpeta) = previos_

    # --- 13i. Cerrar con un lote en marcha, con hilos de verdad -----------------
    segundo_plano.lanzar = LANZAR_DE_VERDAD
    espera_previa = rcd.ESPERA_QUIT
    rcd.ESPERA_QUIT = 1.0
    for decision in (False, True):
        dialogos(destino=str(tmpdir()), preguntar=decision)
        parado = threading.Event()
        bloqueado = threading.Event()
        suelto_ = threading.Event()
        primera = [True]

        def estado_cierre():
            if primera[0] and not parado.is_set():
                primera[0] = False
                bloqueado.set()
                suelto_.wait(5)            # una respuesta de progreso en vuelo al cerrar
                return CORRIENDO
            return ({"finished": True, "success": False, "error": "context canceled"}
                    if parado.is_set() else CORRIENDO)

        def parar_cierre():
            parado.set()
            return {}
        falso = servidor_lote(
            estadisticas=(stats(1, 4, 10, 40),),
            otras={("job/status", None): estado_cierre, ("job/stop", None): parar_cierre})
        errores.clear()
        dlg = abrir(falso)
        elegir_varias(dlg, "leeme.txt")
        falso.respuestas[("operations/stat", "leeme.txt")] = {"item": item("leeme.txt")}
        dlg.bajar.invoke()
        c("el trabajo está en marcha y su progreso en vuelo", bombear(bloqueado.is_set), True)
        dlg.tk.call(dlg.protocol("WM_DELETE_WINDOW"))
        c("cerrar con un lote en marcha pregunta antes",
          LLAMADAS_DIALOGOS["preguntar"],
          [("Transferencia en marcha", "Hay una transferencia en marcha. ¿Cancelarla y cerrar?",
            "Cancelar y cerrar", "Seguir")])
        if not decision:
            c("  «Seguir»: la ventana sigue y no se paró nada",
              (bool(dlg.winfo_exists()), falso.paradas, paradas_de_trabajo(falso)), (True, 0, 0))
            suelto_.set()
            for _ in range(20):
                raiz.update()
                time.sleep(0.01)
            c("  y el lote sigue (el panel a la vista)", panel_a_la_vista(dlg), True)
            parado.set()
            c("  hasta que acaba por su cuenta y lo dice",
              bombear(lambda: frase_panel(dlg) != ""), True)
            cerrar(dlg)
            bombear(lambda: falso.paradas >= 1)
        else:
            c("  «Cancelar y cerrar»: se cerró la ventana",
              bombear(lambda: not dlg.winfo_exists()), True)
            c("  se mandó job/stop antes de parar el rcd",
              (paradas_de_trabajo(falso), falso.orden.index("job/stop") < falso.orden.index("parar")),
              (1, True))
            c("  y el rcd se paró una vez", falso.paradas, 1)
            suelto_.set()                  # llega tarde la respuesta del progreso en vuelo
            for _ in range(30):
                raiz.update()
                time.sleep(0.01)
            c("  una respuesta tardía no pinta nada ni lanza excepciones de Tk", errores, [])
            c("  sigue siendo una sola parada", falso.paradas, 1)
            raiz.withdraw()
    rcd.ESPERA_QUIT = espera_previa
    segundo_plano.lanzar = segundo_plano.en_el_acto

c("nada ha reventado por el camino", errores, [])
raiz.destroy()
sys.exit(c.report())
