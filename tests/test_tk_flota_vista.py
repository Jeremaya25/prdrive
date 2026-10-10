#!/usr/bin/env python3
"""«Dispositivos» rellena su ficha en su sitio, y no pinta una por dispositivo para medirla.

La ficha del elegido es un juego fijo de etiquetas (`tk_fleet.Ficha`) que se
hace la primera vez que hace falta, y se rellena al elegir. Lo que se comprueba:

- los widgets de la ventana, la tabla incluida (un lienzo), son los mismos con 3 y
  con 25 dispositivos, y elegir cada fila no crea ni destruye ninguno;
- con la flota vacía no se hace ninguna etiqueta de la ficha, y la primera flota
  con notas la hace: lo que se elige después enseña lo mismo que una ventana
  recién abierta con ese dispositivo;
- la ficha de cada fila enseña, en las mismas celdas y con los mismos huecos,
  lo que una ventana recién abierta con solo ese dispositivo (`tests/_vista`);
- a 100 %, la ficha de cada dispositivo tiene el mismo texto en el mismo sitio y
  con el mismo tamaño que la tarjeta que pintaba la versión anterior;
- `_pide()` es lo que mide `grid` en cada dispositivo, también con un nombre que
  ocupa dos columnas y con otro que pasa de ellas por poco (el que se busca en
  cada escala, no uno fijo), y la reserva es la mayor de esas medidas;
- las filas fluyen: «Estado» de una línea deja subir a «Equipos», y lo que no
  se usa (la segunda línea de «Estado», una fecha) está fuera de la rejilla y
  sin texto;
- el sitio que se reserva es el que pide la ficha más grande pintada en una
  tarjeta aparte, con un reposo del bucle de eventos por dispositivo (lo que
  mide `grid` de verdad), y `reservar()` ni crea widgets ni espera a ningún
  reposo;
- soltar una flota con una ficha mayor hace crecer el recuadro, y el aviso de
  que aún no hay nadie se hace la primera vez que hace falta.
"""

from __future__ import annotations

import sys

from _harness import Checks, sandbox
from _vista import leer_vista, visibles

from common import fleet

c = Checks("«Dispositivos» en su sitio")

try:
    import tkinter as tk
    from tkinter import messagebox, ttk
    raiz = tk.Tk()
    raiz.withdraw()
except Exception as e:                                   # sin entorno gráfico
    print(f"  (saltado) no hay entorno gráfico: {e}")
    sys.exit(c.report())

from ui import segundo_plano, theme, tk_fleet  # noqa: E402
from ui import tk as uitk  # noqa: E402

errores: list[str] = []
raiz.report_callback_exception = (
    lambda tipo, valor, _tb: errores.append(f"{tipo.__name__}: {valor}"))
messagebox.showerror = lambda titulo, texto=None, **k: errores.append(str(texto))
messagebox.askokcancel = lambda *a, **k: True
# La flota llega en el sitio: aquí no se entra en el bucle de eventos. Con hilos
# de verdad se prueba en test_tk_segundo_plano.py.
segundo_plano.lanzar = segundo_plano.en_el_acto

E = fleet.Equipo
AQUI = "PORTATIL"
fleet.device_id = lambda app_dir=None: "disp0000xxxxxxxx"
fleet.equipo_actual = lambda: AQUI
LEIDA: list = []
fleet.leer = lambda raw=None: (list(LEIDA), None)
RAW = {"defaults": {"remote": "nas"}, "pair": []}

LARGO = ("documentos, fotos, música, vídeos, trabajo, copias, descargas, libros, "
         "recetas, facturas, planos, proyectos")


def dispositivo(i: int, fechas: int = fleet.MAX_EQUIPOS) -> fleet.Dispositivo:
    """Un dispositivo de los seis tipos que importan a la ficha, el `i`-ésimo.

    Con fechas fijas y viejas: lo que enseña la ficha no depende de la hora.
    """
    base = dict(id=f"disp{i:04d}xxxxxxxx", nombre=f"el {i}", version="0.7.1",
                plataformas=("windows-x64",), last_seen="2026-01-01 08:00:00",
                last_result="ok")
    tipo = i % 6
    if tipo == 0:                                       # corto, con todos sus equipos
        base["equipos"] = tuple(E(f"EQUIPO-{k}", f"2026-01-0{k + 1} 09:00:00")
                                for k in range(fechas))
    elif tipo == 1:                                     # nombre y fallo que parten
        base.update(nombre="el pendrive de la oficina de arriba del edificio grande "
                            "de la calle larga del centro, el número doce",
                    last_result=f"fallo en {LARGO}", ultima_buena="2025-12-01 08:00:00",
                    plataformas=("windows-x64", "linux-x64", "windows-arm64"),
                    equipos=(E("A", "2026-01-02 09:00:00"), E(AQUI, "2026-01-01 09:00:00")))
    elif tipo == 2:                                     # sin equipos: lo dice en pista
        base.update(plataformas=())
    elif tipo == 3:                                     # la raíz de un equipo, cifrada
        base.update(tipo="equipo", cifrado="veracrypt",
                    equipos=(E("SOBREMESA", "2026-01-02 09:00:00"),))
    elif tipo == 4:                                     # un fallo sin pasada buena
        base.update(last_result="fallo en fotos", ultima_buena=fleet.SIN_BUENA,
                    equipos=tuple(E(f"E{k}", f"2026-01-0{k + 1} 09:00:00") for k in range(3)))
    else:                                               # uno viejo
        base.update(last_seen="2025-01-01 08:00:00", version="0.2.0",
                    equipos=(E("VIEJO", "2025-01-01 08:00:00"),))
    return fleet.Dispositivo(**base)


def flota(n: int, fechas: int = fleet.MAX_EQUIPOS) -> list[fleet.Dispositivo]:
    """`n` dispositivos variados; el primero lleva `fechas` equipos con fecha."""
    return [dispositivo(i, fechas) for i in range(n)]


SPAN = fleet.Dispositivo(id="span0000xxxxxxxx", nombre="copias de seguridad del taller",
                         version="0.7.1", plataformas=("linux-x64",),
                         last_seen="2026-01-01 08:00:00", last_result="ok",
                         equipos=(E("PC", "2026-01-01 09:00:00"),))
"""Un nombre de 30 letras con una ficha corta: su nombre ocupa las dos primeras columnas y sobra."""
SOBRA = SPAN._replace(id="sobra0000xxxxxxx", nombre="copias de seguridad de")
"""Un nombre corto, con los datos de `SPAN`. No está pensado para desbordar: que pase de sus
dos columnas depende de la fuente y de la escala, así que la sección 10 no se fía de él y
busca el que pasa por poco en cada escala (`pasa_por_poco`)."""
FRASE = ("copias de seguridad del taller de la oficina de arriba del edificio grande "
         "de la calle larga del centro")
"""Lo que se alarga, letra a letra, el nombre que pasa por poco (`pasa_por_poco`)."""


def todos(widget) -> list:
    """El widget y todo lo que cuelga de él, a la vista o no."""
    salida = [widget]
    for hijo in widget.winfo_children():
        salida += todos(hijo)
    return salida


def nombres(widget) -> set[str]:
    """Los nombres de Tk de lo que cuelga de `widget` (sin él)."""
    return {str(w) for w in todos(widget)} - {str(widget)}


def buscar(ventana, clase, texto):
    """El primer widget de esa clase y con ese texto."""
    return next((w for w in todos(ventana)
                 if isinstance(w, clase) and str(w.cget("text")) == texto), None)


CENTRADAS: list = []
DEVUELTO: list = []
tk_fleet.centrar = lambda win, parent=None: CENTRADAS.append((win, parent))
# La pantalla no limita lo que crece el recuadro: lo que se mide es la ficha.
PANTALLA_REAL = uitk.pantalla_util
uitk.pantalla_util = lambda win: (3000, 3000)
ABIERTAS: list = []


def abrir(lista: list, mostrar: bool = False):
    """Abre «Dispositivos» con esa flota y devuelve la ventana viva, sin esperar.

    Con `mostrar`, encajada y a la vista, como la deja `mostrar()` antes de
    esperar: sin eso no crece (`winfo_ismapped()`).
    """
    LEIDA[:] = lista
    ABIERTAS.clear()

    def capturar(dlg, parent=None):
        """Sustituye a `mostrar()`: apunta la ventana y no espera."""
        ABIERTAS.append(dlg)
        if mostrar:
            raiz.deiconify()
            dlg.visor.encajar(dlg)
            dlg.deiconify()
        dlg.update()

    previo = tk_fleet.mostrar
    tk_fleet.mostrar = capturar
    try:
        DEVUELTO.append(tk_fleet.open_dialog(raiz, None, dict(RAW)))
    finally:
        tk_fleet.mostrar = previo
    return ABIERTAS[0]


def creaciones(accion) -> list[str]:
    """Devuelve el padre de cada widget que crea `accion`, aunque luego lo destruya.

    Contar los widgets de antes y de después no ve lo que se hace y se deshace:
    una tarjeta pintada para medirla y borrada acaba igual que empezó.
    """
    hechas: list[str] = []
    original = tk.BaseWidget._setup

    def vigilar(self, master, cnf):
        """Apunta el padre del widget que se crea."""
        hechas.append(str(master))
        return original(self, master, cnf)

    tk.BaseWidget._setup = vigilar
    try:
        accion()
    finally:
        tk.BaseWidget._setup = original
    return hechas


def cerrar(dlg) -> None:
    """Cierra la ventana."""
    dlg.destroy()
    raiz.withdraw()


def huecos(widget) -> tuple:
    """Dónde está cada widget a la vista de `widget` y con qué huecos."""
    return tuple((str(w.cget("text")), int(w.grid_info()["row"]), int(w.grid_info()["column"]),
                  str(w.grid_info()["padx"]), str(w.grid_info()["pady"]),
                  str(w.grid_info()["sticky"])) for w in visibles(widget))


def hoja_antigua(padre):
    """La tarjeta vacía que pintaba `ui/tk_fleet.py` antes de rellenar la ficha en su sitio.

    Una `Card.TFrame` con el canalón de los rótulos en la columna 0 y la columna
    del texto estirable, como la hacía la versión anterior.
    """
    hoja = ttk.Frame(padre, style="Card.TFrame",
                     padding=(theme.E4, theme.E3, theme.E4, theme.E3))
    canalon = theme.ancho_rotulo(padre, *tk_fleet.ROTULOS_FICHA) + tk_fleet.icons.px(padre, 14)
    hoja.columnconfigure(0, minsize=canalon)
    hoja.columnconfigure(1, weight=1)
    return hoja


def pintar_ficha_antigua(hoja, disp: fleet.Dispositivo, aqui: str) -> None:
    """Pinta en `hoja` la ficha de ese dispositivo como la pintaba la versión anterior.

    Es el `pintar_ficha` de `git show 8678a5b:ui/tk_fleet.py`, copiado aquí como
    vara: los huecos entre líneas son los literales de 8 y 2 píxeles de entonces,
    y el código nuevo no se usa para medirse a sí mismo.
    """
    for widget in hoja.winfo_children():
        widget.destroy()
    ttk.Label(hoja, text=disp.nombre, style="Card.Fuerte.TLabel",
              wraplength=theme.medida(460), justify="left").grid(
        row=0, column=0, columnspan=2, sticky="w")
    ttk.Label(hoja, text=f"id {disp.id[:8]}", style="Card.MonoPista.TLabel").grid(
        row=0, column=2, sticky="ne", padx=(theme.E3, 0))
    fila = 1
    for apartado in tk_fleet.ficha(disp, aqui):
        ttk.Label(hoja, text=theme.rotulo(apartado.rotulo),
                  style="Card.Rotulo.TLabel").grid(row=fila, column=0,
                                                   sticky="nw", pady=(theme.E2, 0))
        lineas = list(apartado.lineas)
        lineas += [tk_fleet.Linea(" ")] * (apartado.reserva - len(lineas))
        for i, linea in enumerate(lineas):
            aire = (8, 0) if i == 0 else (2, 0)
            ttk.Label(hoja, text=linea.texto, justify="left",
                      style="Card.Pista.TLabel" if linea.pista else "Card.TLabel",
                      wraplength=theme.medida(440)).grid(
                row=fila, column=1, sticky="w", pady=aire)
            if linea.fecha:
                ttk.Label(hoja, text=linea.fecha, style="Card.MonoPista.TLabel").grid(
                    row=fila, column=2, sticky="e", padx=(theme.E3, 0), pady=aire)
            fila += 1


def geometria(tarjeta) -> tuple:
    """Lo que enseña una tarjeta: su tamaño pedido y, por etiqueta a la vista, su texto y su sitio.

    Cada etiqueta va con su `x`, `y`, `ancho` y `alto` dentro de la tarjeta, así que
    dos tarjetas en ventanas distintas se comparan. Lo que `grid_remove` quita no se
    enseña y no cuenta.

    Returns:
        `(ancho pedido, alto pedido, [(texto, x, y, ancho, alto), ...])`, con las
        etiquetas ordenadas.
    """
    tarjeta.update_idletasks()
    etiquetas = sorted(
        (str(h.cget("text")), h.winfo_x(), h.winfo_y(), h.winfo_width(), h.winfo_height())
        for h in tarjeta.winfo_children() if h.winfo_manager() == "grid")
    return tarjeta.winfo_reqwidth(), tarjeta.winfo_reqheight(), etiquetas


def comparar_con_antigua(dlg, lista_de: list, aparte) -> tuple[list[str], bool]:
    """Compara la ficha de cada dispositivo, elegido en `dlg`, con la tarjeta antigua.

    La tarjeta antigua se pinta en `aparte` con el mismo tamaño que la ficha de la
    ventana (la columna y la fila de la reserva), para que las dos se estiren igual.

    Returns:
        Los ids de los dispositivos cuya ficha no enseña lo mismo, y si la vara
        tiene de verdad sus etiquetas, con tamaño (un `winfo_width()` de 1 haría
        iguales dos cosas distintas).
    """
    distintas, sanos = [], True
    for disp in lista_de:
        dlg.tabla.elegir(disp.id)
        dlg.update()
        tarjeta = dlg.ficha.marco
        nueva = geometria(tarjeta)
        aparte.columnconfigure(0, minsize=tarjeta.winfo_width())
        aparte.rowconfigure(0, minsize=tarjeta.winfo_height())
        hoja = hoja_antigua(aparte)
        hoja.grid(row=0, column=0, sticky="nsew")
        pintar_ficha_antigua(hoja, disp, AQUI)
        vieja = geometria(hoja)
        hoja.destroy()
        sanos = sanos and len(vieja[2]) >= 10 and all(
            ancho > 1 and alto > 1 for _t, _x, _y, ancho, alto in vieja[2])
        if nueva != vieja:
            distintas.append(disp.id)
    return distintas, sanos


c("la ficha tiene etiquetas de línea para cada uno de sus apartados",
  len(tk_fleet.LINEAS_FICHA), len(tk_fleet.ROTULOS_FICHA))

with sandbox():
    # -----------------------------------------------------------------------
    # 1. Con 3 y con 25 dispositivos hay los mismos widgets, la tabla incluida
    # -----------------------------------------------------------------------
    cuentas = {}
    for n in (3, 25):
        dlg = abrir(flota(n))
        total = len(todos(dlg))
        tabla = len(todos(dlg.tabla.marco))
        cuentas[n] = (total, tabla, total - tabla)
        print(f"  (cuenta) {n} dispositivos: {total} widgets, de ellos {tabla} de la tabla "
              f"y {total - tabla} del resto; fechas: {len(dlg.ficha.fechas)}")
        cerrar(dlg)
    c("los widgets de la ventana son los mismos con 3 y con 25 dispositivos",
      cuentas[3][0], cuentas[25][0])
    c("  la tabla es uno solo, el lienzo, con cualquier flota", (cuentas[3][1], cuentas[25][1]),
      (1, 1))

    # -----------------------------------------------------------------------
    # 2. Elegir cada fila no crea ni destruye nada, y la ficha enseña lo que
    #    una ventana recién abierta con solo ese dispositivo
    # -----------------------------------------------------------------------
    lista = flota(12)
    dlg = abrir(lista)
    antes = nombres(dlg)
    fichas, pidos = {}, set()
    iguales_en_su_sitio = True
    hechas: list[str] = []
    for disp in lista:
        hechas += creaciones(lambda: (dlg.tabla.elegir(disp.id), dlg.update()))
        iguales_en_su_sitio = iguales_en_su_sitio and nombres(dlg) == antes
        fichas[disp.id] = (leer_vista(dlg.ficha.marco), huecos(dlg.ficha.marco))
        pidos.add((dlg.visor.interior.winfo_reqwidth(), dlg.visor.interior.winfo_reqheight()))
    c("elegir cada fila de la flota no crea ni destruye ningún widget",
      (iguales_en_su_sitio, hechas), (True, []))
    c("  ni cambia lo que pide la ventana", len(pidos), 1)
    c("  la ficha está a la vista", bool(fichas[lista[0].id][0]), True)
    cerrar(dlg)

    distintas = []
    for disp in lista:
        nueva = abrir([disp])
        vista, hueco = leer_vista(nueva.ficha.marco), huecos(nueva.ficha.marco)
        if (vista, hueco) != fichas[disp.id]:
            distintas.append(disp.id)
        cerrar(nueva)
    c("la ficha de cada dispositivo enseña, en sus celdas y con sus huecos, "
      "lo que una ventana recién abierta con él solo", distintas, [])

    # -----------------------------------------------------------------------
    # 3. Las filas fluyen: lo que sobra se quita de la rejilla y queda vacío
    # -----------------------------------------------------------------------
    solo_ok = dispositivo(2)                       # «Estado» de una línea, sin fechas
    con_buena = dispositivo(1)                     # «Estado» de dos líneas, con fechas
    dlg = abrir([solo_ok, con_buena])
    ficha = dlg.ficha

    def fila_de(etiqueta) -> int | None:
        """La fila de la rejilla de esa etiqueta, o `None` si está quitada."""
        return int(etiqueta.grid_info()["row"]) if etiqueta.winfo_manager() else None

    dlg.tabla.elegir(solo_ok.id)
    dlg.update()
    una = [fila_de(r) for r in ficha.rotulos]
    c("«Estado» de una línea: Versión, Para, Estado y Equipos en las filas 1, 2, 3 y 4",
      una, [1, 2, 3, 4])
    c("  la segunda línea de «Estado» no está en la rejilla y no dice nada",
      (fila_de(ficha.lineas[2][1]), str(ficha.lineas[2][1].cget("text"))), (None, ""))
    c("  sin fechas, ninguna etiqueta de fecha a la vista",
      [fila_de(f) for f in ficha.fechas if f.winfo_manager()], [])
    c("  y los equipos que sobran son líneas en blanco, que guardan la altura",
      [str(e.cget("text")) for e in ficha.lineas[3]],
      [tk_fleet.SIN_EQUIPOS, " ", " ", " ", " "])
    dlg.tabla.elegir(con_buena.id)
    dlg.update()
    dos = [fila_de(r) for r in ficha.rotulos]
    c("«Estado» de dos líneas baja «Equipos» una fila: 1, 2, 3 y 5", dos, [1, 2, 3, 5])
    c("  y la segunda línea de «Estado» está en la fila 4, en pista",
      (fila_de(ficha.lineas[2][1]), str(ficha.lineas[2][1].cget("style"))),
      (4, "Card.Pista.TLabel"))
    c("  con una fecha por equipo: dos, en las filas de sus nombres",
      sorted((fila_de(f), str(f.cget("text"))) for f in ficha.fechas if f.winfo_manager()),
      [(5, "2026-01-02"), (6, "2026-01-01")])
    dlg.tabla.elegir(solo_ok.id)
    dlg.update()
    c("y de vuelta, «Equipos» sube y las fechas de más se van",
      ([fila_de(r) for r in ficha.rotulos],
       [str(f.cget("text")) for f in ficha.fechas if f.winfo_manager()]),
      ([1, 2, 3, 4], []))
    cerrar(dlg)

    # -----------------------------------------------------------------------
    # 4. Lo que se reserva: lo mismo que pintando una tarjeta por dispositivo
    # -----------------------------------------------------------------------
    def reserva_antigua(padre, lista_de: list) -> tuple[int, int]:
        """Reserva midiendo una tarjeta pintada por dispositivo, con un reposo por cada una.

        Es la vara de `Ficha.reservar()`: etiquetas nuevas para cada
        dispositivo en una tarjeta aparte, y lo que pide `grid` de verdad una
        vez en reposo, con los huecos de línea de 8 y 2 píxeles.
        """
        hoja = ttk.Frame(padre, style="Card.TFrame",
                         padding=(theme.E4, theme.E3, theme.E4, theme.E3))
        hoja.grid(row=0, column=0)
        padre.update_idletasks()
        canalon = (theme.ancho_rotulo(padre, *tk_fleet.ROTULOS_FICHA)
                   + tk_fleet.icons.px(padre, 14))
        hoja.columnconfigure(0, minsize=canalon)
        hoja.columnconfigure(1, weight=1)
        ancho = alto = 0
        for disp in lista_de:
            for hijo in hoja.winfo_children():
                hijo.destroy()
            ttk.Label(hoja, text=disp.nombre, style="Card.Fuerte.TLabel",
                      wraplength=theme.medida(460), justify="left").grid(
                row=0, column=0, columnspan=2, sticky="w")
            ttk.Label(hoja, text=f"id {disp.id[:8]}", style="Card.MonoPista.TLabel").grid(
                row=0, column=2, sticky="ne", padx=(theme.E3, 0))
            fila = 1
            for apartado in tk_fleet.ficha(disp, AQUI):
                ttk.Label(hoja, text=theme.rotulo(apartado.rotulo),
                          style="Card.Rotulo.TLabel").grid(
                    row=fila, column=0, sticky="nw", pady=(theme.E2, 0))
                lineas = list(apartado.lineas)
                lineas += [tk_fleet.Linea(" ")] * (apartado.reserva - len(lineas))
                for i, linea in enumerate(lineas):
                    aire = (8, 0) if i == 0 else (2, 0)
                    ttk.Label(hoja, text=linea.texto, justify="left",
                              style="Card.Pista.TLabel" if linea.pista else "Card.TLabel",
                              wraplength=theme.medida(440)).grid(
                        row=fila, column=1, sticky="w", pady=aire)
                    if linea.fecha:
                        ttk.Label(hoja, text=linea.fecha, style="Card.MonoPista.TLabel").grid(
                            row=fila, column=2, sticky="e", padx=(theme.E3, 0), pady=aire)
                    fila += 1
            hoja.update_idletasks()
            ancho = max(ancho, hoja.winfo_reqwidth())
            alto = max(alto, hoja.winfo_reqheight())
        hoja.destroy()
        return ancho, alto

    def reserva_geometria(dlg, lista_de: list) -> tuple[int, int]:
        """Lo mismo, pero con la ficha de la ventana: un reposo por dispositivo, a ver qué pide `grid`."""
        ancho = alto = 0
        for disp in lista_de:
            dlg.ficha.poner(disp, AQUI)
            dlg.ficha.marco.update_idletasks()
            ancho = max(ancho, dlg.ficha.marco.winfo_reqwidth())
            alto = max(alto, dlg.ficha.marco.winfo_reqheight())
        return ancho, alto

    APARTE = tk.Toplevel(raiz)             # donde se pinta la tarjeta de la vara
    APARTE.withdraw()
    PEOR = [dispositivo(1)._replace(
        id="peor0000xxxxxxxx", nombre="un nombre larguísimo " * 12,
        last_result=f"fallo en {LARGO}, {LARGO}",
        equipos=tuple(E(("sala-de-reuniones-%d-del-edificio-de-la-oficina-de-arriba-" % k) * 2,
                        f"2026-01-0{k + 1} 09:00:00") for k in range(fleet.MAX_EQUIPOS)))]
    escala_real = float(raiz.tk.call("tk", "scaling"))
    for escala in (1.3333, 1.0, 2.0):
        raiz.tk.call("tk", "scaling", escala)
        for que, lista_de in (("12 variados", flota(12)), ("25 variados", flota(25)),
                              ("el peor", PEOR), ("uno sin fechas", [dispositivo(2)])):
            dlg = abrir(lista_de)
            reservado = dlg.ficha.reserva
            c(f"al {escala}: {que}: lo reservado es lo que pide la ficha más grande "
              "(medido con un reposo por dispositivo)",
              reservado, reserva_geometria(dlg, lista_de))
            if escala == 1.3333:
                c(f"al {escala}: {que}: y lo que reservaba la ventana pintando una tarjeta "
                  "por dispositivo", reservado, reserva_antigua(dlg.visor.interior, lista_de))
            cerrar(dlg)
    raiz.tk.call("tk", "scaling", escala_real)
    APARTE.destroy()

    # `reservar()` no crea widgets ni espera a ningún reposo del bucle de eventos
    dlg = abrir(flota(25))
    idle = []
    original = tk.Misc.update_idletasks

    def contar(self):
        """Cuenta los reposos que se piden."""
        idle.append(str(self))
        return original(self)

    antes, previa = nombres(dlg), dlg.ficha.reserva
    tk.Misc.update_idletasks = contar
    try:
        hechas = creaciones(lambda: dlg.ficha.reservar(flota(25), AQUI))
        reservado = dlg.ficha.reserva
    finally:
        tk.Misc.update_idletasks = original
    c("`reservar()` no crea ningún widget, ni siquiera para deshacerlo",
      (nombres(dlg) == antes, hechas), (True, []))
    c("  ni espera a ningún reposo del bucle de eventos", idle, [])
    c("  y reserva lo mismo que al llegar", reservado, previa)
    # y la llegada entera, con la ventana sin enseñar, tampoco
    idle.clear()
    tk.Misc.update_idletasks = contar
    try:
        hechas = creaciones(lambda: (buscar(dlg, ttk.Button, "Releer").invoke(), dlg.update()))
    finally:
        tk.Misc.update_idletasks = original
    print(f"  (cuenta) reposos pedidos al llegar la flota con la ventana sin enseñar: {len(idle)}")
    c("al llegar la flota no se crea ningún widget en la ficha, ni para deshacerlo",
      [h for h in hechas if h.startswith(str(dlg.ficha.marco))], [])
    c("releer la misma flota no crea ni destruye ningún widget de la ficha",
      {n for n in nombres(dlg) if str(dlg.ficha.marco) in n}
      == {n for n in antes if str(dlg.ficha.marco) in n}, True)
    cerrar(dlg)

    # -----------------------------------------------------------------------
    # 5. Las fechas se hacen cuando una flota las pide, y no se destruyen
    # -----------------------------------------------------------------------
    dlg = abrir(flota(4, fechas=2))
    c("con dos equipos con fecha, dos etiquetas de fecha", len(dlg.ficha.fechas), 2)
    hechos = len(todos(dlg))
    LEIDA[:] = flota(4, fechas=5)
    buscar(dlg, ttk.Button, "Releer").invoke()
    dlg.update()
    c("una flota con cinco las hace", len(dlg.ficha.fechas), 5)
    c("  y la ventana tiene tres widgets más, no más", len(todos(dlg)) - hechos, 3)
    LEIDA[:] = flota(4, fechas=2)
    buscar(dlg, ttk.Button, "Releer").invoke()
    dlg.update()
    c("de vuelta a una de dos, las cinco siguen ahí", (len(dlg.ficha.fechas),
      len(todos(dlg)) - hechos), (5, 3))
    c("  y las que sobran, fuera de la rejilla y sin texto",
      [(f.winfo_manager(), str(f.cget("text"))) for f in dlg.ficha.fechas[2:]],
      [("", "")] * 3)
    cerrar(dlg)

    # Una nota con más equipos de los que se reservan (`fleet.parse()` los corta, pero
    # un `Dispositivo` hecho a mano no): sus líneas se hacen y se enseñan todas
    muchos = dispositivo(0)._replace(equipos=tuple(
        E(f"EQUIPO-{k}", f"2026-01-0{k + 1} 09:00:00") for k in range(fleet.MAX_EQUIPOS + 2)))
    dlg = abrir([muchos])
    enseñadas = [str(e.cget("text")) for e in dlg.ficha.lineas[3] if e.winfo_manager()]
    c("con más equipos que MAX_EQUIPOS, se enseñan todos",
      enseñadas, [f"EQUIPO-{k}" for k in range(fleet.MAX_EQUIPOS + 2)])
    LEIDA[:] = flota(2)
    buscar(dlg, ttk.Button, "Releer").invoke()
    dlg.update()
    c("  y con una flota normal las dos de más se van, sin destruirse",
      (len(dlg.ficha.lineas[3]),
       [(e.winfo_manager(), str(e.cget("text"))) for e in dlg.ficha.lineas[3][fleet.MAX_EQUIPOS:]]),
      (fleet.MAX_EQUIPOS + 2, [("", "")] * 2))
    cerrar(dlg)

    # -----------------------------------------------------------------------
    # 6. Una flota con una ficha mayor hace crecer el recuadro, como siempre
    # -----------------------------------------------------------------------
    corta = [dispositivo(0), dispositivo(2)]
    dlg = abrir(corta, mostrar=True)
    CENTRADAS.clear()
    alto_antes, medida_antes = dlg.ficha.reserva[1], dlg.visor._medida()
    LEIDA[:] = corta + [dispositivo(1)._replace(
        last_result=f"fallo en {LARGO}, {LARGO}, {LARGO}, {LARGO}")]
    buscar(dlg, ttk.Button, "Releer").invoke()
    dlg.update()
    c("«Releer» con un «Estado» más largo hace la reserva más alta",
      dlg.ficha.reserva[1] > alto_antes, True)
    c("  y crece el recuadro, sin sacar una barra", (
        dlg.visor._medida()[1] > medida_antes[1], bool(dlg.visor.vertical.grid_info())),
      (True, False))
    c("  y la ventana se recoloca, sobre su padre, una sola vez",
      [(w is dlg, p is raiz) for w, p in CENTRADAS], [(True, True)])
    CENTRADAS.clear()
    buscar(dlg, ttk.Button, "Releer").invoke()
    dlg.update()
    c("releer lo mismo no hace crecer nada, y la ventana no se mueve", CENTRADAS, [])
    # quitar la larga: la reserva se queda en lo que hace falta ahora
    LEIDA[:] = corta
    buscar(dlg, ttk.Button, "Releer").invoke()
    dlg.update()
    c("si la ficha larga se va, la reserva vuelve a lo que pide la flota",
      dlg.ficha.reserva[1], alto_antes)
    cerrar(dlg)

    # -----------------------------------------------------------------------
    # 7. Sin nadie apuntado: el aviso se hace la primera vez que hace falta
    # -----------------------------------------------------------------------
    dlg = abrir(flota(3))
    c("con notas no hay aviso de que no haya nadie",
      buscar(dlg, ttk.Label, tk_fleet.SIN_NOTA), None)
    LEIDA[:] = []
    buscar(dlg, ttk.Button, "Releer").invoke()
    dlg.update()
    aviso = buscar(dlg, ttk.Label, tk_fleet.SIN_NOTA)
    marco = aviso.master
    c("sin ninguna, el aviso está en la fila 2 del marco, solo",
      marco.grid_slaves(row=2), [aviso])
    c("  y la ficha, escondida y sin hueco reservado",
      (dlg.ficha.marco.winfo_manager(), dlg.ficha.rotulo.winfo_manager(),
       dlg.ficha.reserva, marco.grid_rowconfigure(3)["minsize"]), ("", "", (0, 0), 0))
    hechos = len(todos(dlg))
    LEIDA[:] = flota(3)
    buscar(dlg, ttk.Button, "Releer").invoke()
    dlg.update()
    c("con notas otra vez, el aviso se quita (no se destruye)",
      (aviso.winfo_manager(), aviso.winfo_exists()), ("", 1))
    c("  y la ficha vuelve a su fila, con su hueco",
      (dlg.ficha.marco.winfo_manager(), int(dlg.ficha.marco.grid_info()["row"]),
       dlg.ficha.reserva[1] > 0), ("grid", 3, True))
    LEIDA[:] = []
    buscar(dlg, ttk.Button, "Releer").invoke()
    dlg.update()
    c("y sin ninguna otra vez, es el mismo aviso: no se hace otro",
      (buscar(dlg, ttk.Label, tk_fleet.SIN_NOTA) is aviso, len(todos(dlg)) == hechos), (True, True))
    cerrar(dlg)

    # -----------------------------------------------------------------------
    # 8. Con la flota vacía no se hace la ficha; la primera vez que hace falta, sí
    # -----------------------------------------------------------------------
    vacia = abrir([])
    c("con la flota vacía no se ha hecho la ficha: ni su tarjeta ni su rótulo",
      (vacia.ficha.marco, vacia.ficha.rotulo), (None, None))
    con_tres = abrir(flota(3))
    c("  y la diferencia con una con notas es lo que pesa la tarjeta, porque su rótulo y el "
      "aviso de «no hay nadie» pesan lo mismo",
      len(todos(con_tres)) - len(todos(vacia)), len(todos(con_tres.ficha.marco)))
    LEIDA[:] = flota(3)
    buscar(vacia, ttk.Button, "Releer").invoke()
    vacia.update()
    c("«Releer» con notas hace la ficha: la ventana tiene los de abrirla con ellas, más el aviso",
      len(todos(vacia)) - len(todos(con_tres)), 1)
    cerrar(con_tres)
    LEIDA[:] = flota(3)
    distintas = []
    for disp in flota(3):
        vacia.tabla.elegir(disp.id)
        vacia.update()
        nueva = (leer_vista(vacia.ficha.marco), huecos(vacia.ficha.marco))
        recien = abrir([disp])
        if nueva != (leer_vista(recien.ficha.marco), huecos(recien.ficha.marco)):
            distintas.append(disp.id)
        cerrar(recien)
    c("y elegir después cada uno enseña lo que una ventana recién abierta con él solo",
      distintas, [])
    cerrar(vacia)

    # -----------------------------------------------------------------------
    # 9. A 100 %, cada ficha se ve como la tarjeta que pintaba la versión anterior
    # -----------------------------------------------------------------------
    escala_inicial = float(raiz.tk.call("tk", "scaling"))
    raiz.tk.call("tk", "scaling", 1.3333)              # el 100 %: 96 ppp
    aparte = tk.Toplevel(raiz)
    aparte.withdraw()
    lista = flota(25) + [SPAN, SOBRA, PEOR[0]]
    dlg = abrir(lista)
    distintas, sanos = comparar_con_antigua(dlg, lista, aparte)
    c("a 100 %, la ficha de cada dispositivo tiene los mismos textos, en los mismos sitios "
      "y con el mismo tamaño que la tarjeta antigua", distintas, [])
    c("  y la tarjeta antigua tiene de verdad sus etiquetas, con tamaño", sanos, True)
    cerrar(dlg)
    dlg = abrir([])
    LEIDA[:] = lista
    buscar(dlg, ttk.Button, "Releer").invoke()
    dlg.update()
    distintas, sanos = comparar_con_antigua(dlg, lista, aparte)
    c("  y lo mismo cuando la flota llega a una ventana abierta vacía",
      (distintas, sanos), ([], True))
    cerrar(dlg)
    aparte.destroy()
    raiz.tk.call("tk", "scaling", escala_inicial)

    # -----------------------------------------------------------------------
    # 10. `_pide()` es lo que mide `grid` en cada dispositivo, y la reserva es la mayor
    # -----------------------------------------------------------------------
    def pasa_de_dos_columnas(ficha, disp: fleet.Dispositivo) -> int:
        """Cuánto pasa el nombre de `disp` de lo que ocupan sus dos primeras columnas.

        Las columnas se miden sin estirar: el canalón y la línea más ancha. Lo que
        pasa lo añade `_pide()` a la última columna.
        """
        ficha._colocar(disp, AQUI)
        ficha.marco.update_idletasks()
        columna0 = max([int(ficha.marco.columnconfigure(0)["minsize"])]
                       + [r.winfo_reqwidth() for r in ficha.rotulos])
        columna1 = max(e.winfo_reqwidth() for grupo in ficha.lineas for e in grupo
                       if e.winfo_manager() == "grid")
        return ficha.nombre.winfo_reqwidth() - (columna0 + columna1)

    def pasa_por_poco(ficha, base: fleet.Dispositivo) -> tuple[fleet.Dispositivo, int]:
        """El nombre de `base` que pasa de sus dos columnas por poco, y cuánto pasa.

        Alarga `FRASE` letra a letra y para en la primera que pasa. Cada letra mueve el
        nombre lo que mide una letra, unos pocos píxeles, así que lo que pasa es poco con
        cualquier fuente: no hace falta saber cuál es la de este sistema. Si ninguna pasa,
        devuelve la más larga y lo que le falta (no es > 0): la comprobación dice con qué
        nombre ha fallado.
        """
        for n in range(1, len(FRASE) + 1):
            candidato = base._replace(id="poco0000xxxxxxxx", nombre=FRASE[:n].rstrip())
            pasa = pasa_de_dos_columnas(ficha, candidato)
            if pasa > 0:
                break
        return candidato, pasa

    escala_inicial = float(raiz.tk.call("tk", "scaling"))
    for escala in (1.0, 1.3333, 2.0):
        raiz.tk.call("tk", "scaling", escala)
        # El nombre que pasa por poco se mide en esta escala y con la fuente de este
        # sistema, en una ventana con solo `SPAN`: así no depende de lo que haya en la flota.
        sonda = abrir([SPAN])
        justo, _ = pasa_por_poco(sonda.ficha, SPAN)
        cerrar(sonda)
        lista = flota(12) + [SPAN, justo, PEOR[0]]
        dlg = abrir(lista)
        ficha = dlg.ficha
        medidas, fallos = [], []
        for disp in lista:
            pide = ficha._pide(ficha._colocar(disp, AQUI))
            ficha.marco.update_idletasks()
            real = (ficha.marco.winfo_reqwidth(), ficha.marco.winfo_reqheight())
            medidas.append(real)
            if pide != real:
                fallos.append((disp.id, pide, real))
        c(f"al {escala}: `_pide()` es lo que mide `grid` en cada dispositivo", fallos, [])
        mayor = (max(w for w, _ in medidas), max(h for _, h in medidas))
        reservado_col = int(ficha.padre.columnconfigure(ficha.columna)["minsize"])
        reservado_fila = int(ficha.padre.rowconfigure(ficha.fila + 1)["minsize"])
        c("  la reserva es la mayor de esas medidas, y es el minsize de la columna y la fila",
          (ficha.reserva, (reservado_col, reservado_fila)), (mayor, mayor))
        c("  el nombre de 30 letras pasa de sus dos columnas, y es lo que hace crecer la última",
          pasa_de_dos_columnas(ficha, SPAN) > 0, True)
        pasa = pasa_de_dos_columnas(ficha, justo)
        c(f"  y el que pasa por poco («{justo.nombre}», {pasa} px, menos de 40) también se suma",
          0 < pasa <= 40, True)
        cerrar(dlg)
    raiz.tk.call("tk", "scaling", escala_inicial)

c("«Dispositivos» no devuelve nada", DEVUELTO and set(DEVUELTO), {None})
c("nada ha reventado por el camino", errores, [])
uitk.pantalla_util = PANTALLA_REAL
raiz.destroy()
sys.exit(c.report())
