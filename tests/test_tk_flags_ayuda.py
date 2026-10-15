#!/usr/bin/env python3
"""El editor de flags de una pareja con su ayuda: desplegable y avisos (cableado).

La lógica (qué se sugiere, qué valor vale, qué se avisa) se prueba sin ventana en
`test_flags_ayuda.py`. Aquí se comprueba lo que solo la ventana puede estropear:
que el desplegable salga y se pueda usar con el teclado y con el ratón, que acepte
justo lo que se ve, que los avisos aparezcan junto al flag y que NUNCA impidan
guardar, que un valor de tipo malo sí impida cerrar, y que un flag que no está en la
lista de rclone se pueda escribir y guardar.

Las teclas solo llegan a una ventana enseñada, así que cada prueba la enseña (bajo
xvfb en la CI).
"""

import sys
import time

from _harness import Checks

c = Checks("editor de flags: desplegable y avisos (cableado)")

try:
    import tkinter as tk
    from tkinter import ttk
    raiz = tk.Tk()
    raiz.withdraw()
except Exception as e:                                   # sin entorno gráfico
    print(f"  (saltado) no hay entorno gráfico: {e}")
    sys.exit(0)

from ui import flags_editor, tk_pairs

tk_pairs.mostrar = lambda dlg, parent=None: dlg.wait_window()

errores_de_tk: list[str] = []
tk.Tk.report_callback_exception = lambda self, *a: errores_de_tk.append(repr(a[1]))

SIMBOLOS = {"-": "minus", "_": "underscore", " ": "space", "=": "equal", '"': "quotedbl",
            "[": "bracketleft", "]": "bracketright"}


def descendientes(w):
    """El widget y todo lo que cuelga de él."""
    pila, salida = [w], []
    while pila:
        x = pila.pop()
        pila += list(x.winfo_children())
        salida.append(x)
    return salida


class Mesa:
    """Lo que un guion ve y toca de un editor de flags abierto."""

    def __init__(self, dlg):
        """Enseña la ventana y recoge sus piezas."""
        self.dlg = dlg
        dlg.wm_transient("")           # de una raíz oculta, un diálogo nunca llega a verse
        dlg.deiconify()
        dlg.update()
        assert dlg.winfo_ismapped(), "el diálogo no se ha enseñado: las teclas no llegarían"
        todos = descendientes(dlg)
        cajas = {int(w.grid_info()["row"]): w for w in todos if isinstance(w, tk.Text)
                 and w.grid_info()}
        self.caja = cajas[min(cajas)]
        self.botones = {w.cget("text"): w for w in todos if isinstance(w, ttk.Button)}
        self.caja.focus_force()
        dlg.update()

    def texto(self):
        """Lo que hay en el cuadro de flags."""
        return self.caja.get("1.0", "end-1c")

    def poner(self, texto):
        """Deja el cuadro con ese texto y el cursor al final."""
        self.caja.delete("1.0", "end")
        self.caja.insert("1.0", texto)
        self.caja.mark_set("insert", "end-1c")

    def teclear(self, texto):
        """Escribe letra a letra, como una persona: inserta y suelta la tecla."""
        for ch in texto:
            self.caja.insert("insert", ch)
            self.caja.event_generate("<KeyRelease>", keysym=SIMBOLOS.get(ch, ch))
        self.dlg.update()

    def tecla(self, keysym):
        """Pulsa y suelta una tecla de edición (Down, Tab, Escape…)."""
        self.caja.event_generate(f"<KeyPress-{keysym}>")
        self.caja.event_generate(f"<KeyRelease-{keysym}>")
        self.dlg.update()

    def lista(self):
        """El desplegable si se ve, o `None`."""
        for w in descendientes(self.dlg):
            if isinstance(w, tk.Listbox) and w.winfo_manager():
                return w
        return None

    def sugerido(self):
        """Los nombres que enseña el desplegable, en orden (vacío si no se ve)."""
        lista = self.lista()
        return [lista.get(i).split()[0] for i in range(lista.size())] if lista else []

    def amarillos(self):
        """Los avisos que se ven: `[texto del cuerpo]` de cada recuadro ámbar en la rejilla."""
        salida = []
        for w in descendientes(self.dlg):
            if (isinstance(w, ttk.Frame) and str(w.cget("style")) == "NotaAmbar.TFrame"
                    and w.winfo_manager()):
                salida += [str(e.cget("text")) for e in descendientes(w)
                           if isinstance(e, ttk.Label) and str(e.cget("text"))]
        return salida

    def rojos(self):
        """Los textos del recuadro rojo si se ve."""
        salida = []
        for w in descendientes(self.dlg):
            if (isinstance(w, ttk.Frame) and str(w.cget("style")) == "NotaRojo.TFrame"
                    and w.winfo_manager()):
                salida += [str(e.cget("text")) for e in descendientes(w)
                           if isinstance(e, ttk.Label) and str(e.cget("text"))]
        return salida

    def esperar(self, condicion, segundos=3.0):
        """Deja correr el bucle de eventos hasta que `condicion()` o se acabe el tiempo."""
        tope = time.monotonic() + segundos
        while time.monotonic() < tope:
            self.dlg.update()
            if condicion():
                return True
            time.sleep(0.02)
        return bool(condicion())


def sesion(guion, flags=None, boton="Aceptar", mode_name="bisync", defaults_flags=None,
           capa=None, extra=()):
    """Abre el editor, corre `guion(mesa)` y pulsa un botón; devuelve lo que devuelve el diálogo."""
    anotado = {}

    def _wait(self, *_a, **_k):
        """En vez de esperar al usuario, deja actuar al guion y pulsa el botón."""
        mesa = Mesa(self)
        guion(mesa, anotado)
        mesa.botones[boton].invoke()

    tk.Toplevel.wait_window = _wait
    kwargs = {} if capa is None else {"capa": capa}
    datos = tk_pairs.flags_form(raiz, "Flags", "de prueba", dict(flags or {}), list(extra),
                                mode_name=mode_name, defaults_flags=defaults_flags, **kwargs)
    return datos, anotado


# El desplegable: salir, moverse, aceptar y cerrar.

def guion_sugerir(mesa, anotado):
    """Escribe «transf»: sale `transfers`; con Abajo y Tab se acepta."""
    mesa.poner("")
    mesa.teclear("transf")
    anotado["sale"] = mesa.sugerido()
    anotado["sitio"] = mesa.lista().winfo_manager() if mesa.lista() else None
    mesa.tecla("Down")
    mesa.tecla("Tab")
    anotado["despues"] = mesa.texto()
    anotado["queda"] = mesa.sugerido()
    anotado["cursor"] = mesa.caja.index("insert")


_, nota = sesion(guion_sugerir, boton="Cancelar")
c("al escribir un principio sale el desplegable con lo que encaja", nota["sale"][:1],
  ["transfers"])
c("  puesto bajo el cursor, sin ser una ventana aparte", nota["sitio"], "place")
c("Tab acepta lo elegido: el nombre y el igual", nota["despues"][:12], "transfers = ")
c("  y el desplegable se va", nota["queda"], [])
c("  con el cursor donde se escribe el valor", nota["cursor"], "1.12")


def guion_escape(mesa, anotado):
    """Escape cierra el desplegable sin tocar lo escrito."""
    mesa.poner("")
    mesa.teclear("delete")
    anotado["antes"] = mesa.sugerido()
    mesa.tecla("Escape")
    anotado["despues"] = (mesa.sugerido(), mesa.texto())


_, nota = sesion(guion_escape, boton="Cancelar")
c("con «delete» salen los de borrado primero", nota["antes"][:3],
  ["delete-after", "delete-before", "delete-during"])
c("Escape lo cierra y no toca lo escrito", nota["despues"], ([], "delete"))


def guion_intro(mesa, anotado):
    """Intro solo acepta si se ha elegido con las flechas: si no, es un salto de línea."""
    mesa.poner("")
    mesa.teclear("checksum")
    anotado["una_sola"] = mesa.sugerido()
    mesa.poner("")
    mesa.teclear("trans")
    mesa.tecla("Return")
    anotado["sin_elegir"] = (mesa.texto(), mesa.sugerido())
    mesa.poner("")
    mesa.teclear("trans")
    mesa.tecla("Down")
    mesa.tecla("Return")
    anotado["elegido"] = (mesa.texto(), mesa.sugerido())


_, nota = sesion(guion_intro, boton="Cancelar")
c("un nombre ya escrito entero no se sigue sugiriendo (aunque otros lo contengan)",
  nota["una_sola"], [])
c("Intro sin haber elegido no acepta nada: es un salto de línea, y se cierra el desplegable",
  nota["sin_elegir"], ("trans\n", []))
c("con una flecha de por medio, sí acepta lo marcado", nota["elegido"], ("transfers = ", []))


def guion_modo(mesa, anotado):
    """Un flag solo de bisync no se sugiere en una pareja que no lo es."""
    mesa.poner("")
    mesa.teclear("resil")
    anotado["lista"] = mesa.sugerido()


_, nota = sesion(guion_modo, boton="Cancelar", mode_name="bisync")
c("en bisync se sugiere lo de bisync", nota["lista"], ["resilient"])
_, nota = sesion(guion_modo, boton="Cancelar", mode_name="up-mirror")
c("en un espejo, no: rclone no lo conoce allí", nota["lista"], [])


def guion_reservado(mesa, anotado):
    """Lo que se rechazaría no se ofrece."""
    mesa.poner("")
    mesa.teclear("workd")
    anotado["lista"] = mesa.sugerido()


_, nota = sesion(guion_reservado, boton="Cancelar")
c("un reservado no se sugiere", nota["lista"], [])


def guion_raton(mesa, anotado):
    """Un clic sobre una fila acepta esa fila."""
    mesa.poner("")
    mesa.teclear("max-del")
    lista = mesa.lista()
    anotado["filas"] = mesa.sugerido()
    x, y, ancho, alto = lista.bbox(1)
    lista.event_generate("<Button-1>", x=x + 4, y=y + alto // 2)
    mesa.dlg.update()
    anotado["despues"] = mesa.texto()
    anotado["queda"] = mesa.sugerido()


_, nota = sesion(guion_raton, boton="Cancelar")
c("hay más de una opción para elegir con el ratón", len(nota["filas"]) > 1, True)
c("un clic acepta la fila de debajo del puntero",
  nota["despues"].startswith(nota["filas"][1] + " = "), True)
c("  y cierra el desplegable", nota["queda"], [])


def guion_aceptado(mesa, anotado):
    """Después de aceptar se escribe el valor y se guarda lo escrito."""
    mesa.poner("")
    mesa.teclear("transf")
    mesa.tecla("Tab")
    mesa.teclear("6")


datos, _ = sesion(guion_aceptado)
c("lo completado más el valor es un flag como los demás", datos["flags"], {"transfers": 6})


# Los avisos: junto al flag, y sin bloquear.

def guion_borrado(mesa, anotado):
    """Un flag de borrado pone un aviso ámbar y marca su línea; quitarlo, los quita."""
    mesa.poner("transfers = 8\ndelete-excluded = true")
    mesa.teclear(" ")                                    # una tecla suelta: arranca el reloj
    mesa.poner("transfers = 8\ndelete-excluded = true")
    mesa.botones["Ver el efecto"].invoke()
    mesa.dlg.update()
    anotado["avisos"] = mesa.amarillos()
    anotado["marcadas"] = [mesa.caja.tag_ranges("ojo")]
    anotado["linea"] = [mesa.caja.get(a, b) for a, b in zip(mesa.caja.tag_ranges("ojo")[::2],
                                                            mesa.caja.tag_ranges("ojo")[1::2])]
    mesa.poner("transfers = 8")
    mesa.botones["Ver el efecto"].invoke()
    mesa.dlg.update()
    anotado["sin_avisos"] = (mesa.amarillos(), list(mesa.caja.tag_ranges("ojo")))


datos, nota = sesion(guion_borrado, flags={}, mode_name="up-mirror")
c("un flag que borra avisa, y manda a «Simular»",
  any("--delete-excluded" in t and "Simular" in t for t in nota["avisos"]), True)
c("  la línea del flag queda marcada en el propio cuadro", nota["linea"],
  ["delete-excluded = true"])
c("  y al quitar el flag se va el aviso y la marca", nota["sin_avisos"], ([], []))
c("los avisos no impiden guardar: con uno puesto, Aceptar devuelve los flags",
  sesion(lambda m, a: m.poner("delete-excluded = true"), mode_name="up-mirror")[0]["flags"],
  {"delete-excluded": True})


def guion_ya_puesto(mesa, anotado):
    """Una pareja que ya trae un flag con aviso abre con su aviso puesto, sin tocar nada."""
    anotado["avisos"] = mesa.amarillos()
    anotado["linea"] = [mesa.caja.get(a, b) for a, b in zip(mesa.caja.tag_ranges("ojo")[::2],
                                                            mesa.caja.tag_ranges("ojo")[1::2])]


_, nota = sesion(guion_ya_puesto, flags={"transfers": 8, "delete-after": True},
                 mode_name="up-mirror", boton="Cancelar")
c("al abrir con un flag que avisa, el aviso ya está", any("--delete-after" in t for t in
                                                         nota["avisos"]), True)
c("  y su línea ya está marcada", nota["linea"], ["delete-after = true"])

def guion_modo_aviso(mesa, anotado):
    """Un flag de bisync en un espejo avisa de que la pasada fallaría."""
    mesa.poner("resilient = true")
    mesa.botones["Ver el efecto"].invoke()
    anotado["avisos"] = mesa.amarillos()


datos, nota = sesion(guion_modo_aviso, mode_name="up-mirror")
c("un flag de otro modo avisa", any("bisync" in t and "fallaría" in t for t in nota["avisos"]),
  True)
c("  y se puede guardar igual (rclone tiene la última palabra)", datos["flags"],
  {"resilient": True})


def guion_choque(mesa, anotado):
    """Un flag que choca con otro ya puesto avisa; el otro puede venir de [defaults]."""
    mesa.poner("delete-before = true")
    mesa.botones["Ver el efecto"].invoke()
    anotado["avisos"] = mesa.amarillos()


datos, nota = sesion(guion_choque, mode_name="up-mirror", defaults_flags={"delete-after": True})
c("un flag que choca con uno heredado avisa",
  any("--delete-before" in t and "--delete-after" in t and "solo uno" in t
      for t in nota["avisos"]), True)


def guion_avisos_en_la_fila(mesa, anotado):
    """Elegida la fila del flag, la nota de debajo de la tabla repite el aviso."""
    mesa.poner("delete-excluded = true")
    mesa.botones["Ver el efecto"].invoke()
    mesa.dlg.tabla.elegir("delete-excluded")
    mesa.dlg.update()
    notas = [str(w.cget("text")) for w in descendientes(mesa.dlg)
             if isinstance(w, ttk.Label) and "Si lo quitas" in str(w.cget("text"))]
    anotado["nota"] = notas


_, nota = sesion(guion_avisos_en_la_fila, mode_name="up-mirror", boton="Cancelar")
c("la nota de la fila elegida lleva el aviso de ese flag",
  any("Simular" in t for t in nota["nota"]), True)


def guion_en_defaults(mesa, anotado):
    """En los comunes no hay modo: un flag de bisync afecta a las parejas que no lo son."""
    mesa.poner("resilient = true")
    mesa.botones["Ver el efecto"].invoke()
    anotado["avisos"] = mesa.amarillos()
    mesa.poner("")
    mesa.teclear("resil")
    anotado["lista"] = mesa.sugerido()


_, nota = sesion(guion_en_defaults, boton="Cancelar", mode_name=None,
                 capa=tk_pairs.model.ORIGEN_DEFAULTS)
c("en [defaults], un flag de bisync avisa de las demás parejas",
  any("otros modos" in t for t in nota["avisos"]), True)
c("  y no se sugiere, porque afectaría a todas", nota["lista"], [])


# Un valor de tipo malo sí impide cerrar; un flag desconocido, no.

def guion_tipo(mesa, anotado):
    """Un entero que no lo es: el diálogo no se cierra y lo dice en el recuadro rojo."""
    mesa.poner('transfers = "cuatro"')
    mesa.botones["Aceptar"].invoke()
    anotado["rojo"] = mesa.rojos()
    anotado["sigue"] = bool(mesa.dlg.winfo_exists())
    mesa.poner("transfers = 4")


datos, nota = sesion(guion_tipo)
c("un tipo malo no deja cerrar", nota["sigue"], True)
c("  y dice qué se esperaba",
  any("número entero" in t for t in nota["rojo"]), True)
c("  con el título de un texto que no vale", flags_editor.TITULO_NO_VALE in nota["rojo"], True)
c("corregido, se guarda", datos["flags"], {"transfers": 4})

datos, _ = sesion(lambda m, a: m.poner('flag-nuevo-de-rclone = "lo-que-sea"\notro = 3'))
c("un flag que no está en la lista de rclone se escribe y se guarda (sin lista blanca)",
  datos["flags"], {"flag-nuevo-de-rclone": "lo-que-sea", "otro": 3})

# Nada se queda colgado de una ventana que ya no está.
raiz.update()
time.sleep(0.5)
raiz.update()
c("cerrar el editor no deja relojes que fallen después", errores_de_tk, [])

sys.exit(c.report())
