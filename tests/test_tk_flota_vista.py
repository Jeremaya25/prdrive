#!/usr/bin/env python3
"""«Dispositivos» rellena su ficha en su sitio, y no pinta una por dispositivo para medirla.

La ficha del elegido es un juego fijo de etiquetas (`tk_fleet.Ficha`) que se
hace al abrir la ventana y se rellena al elegir. Lo que se comprueba:

- los widgets de la ventana, la tabla incluida (un lienzo), son los mismos con 3 y
  con 25 dispositivos, y elegir cada fila no crea ni destruye ninguno;
- la ficha de cada fila enseña, en las mismas celdas y con los mismos huecos,
  lo que una ventana recién abierta con solo ese dispositivo (`tests/_vista`);
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
        nombre="un nombre larguísimo " * 12, last_result=f"fallo en {LARGO}, {LARGO}",
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

c("«Dispositivos» no devuelve nada", DEVUELTO and set(DEVUELTO), {None})
c("nada ha reventado por el camino", errores, [])
uitk.pantalla_util = PANTALLA_REAL
raiz.destroy()
sys.exit(c.report())
