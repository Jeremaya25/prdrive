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

from ui import icons, segundo_plano, servidor, theme, tk_servidor  # noqa: E402

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

c("nada ha reventado por el camino", errores, [])
raiz.destroy()
sys.exit(c.report())
