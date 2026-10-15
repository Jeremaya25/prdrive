#!/usr/bin/env python3
"""La ventana de la guía de flags de rclone (`ui/tk_flags_guia.py`), abierta desde el editor de flags.

La lógica (qué fichas hay, cómo se busca, qué se enseña de cada una) se prueba sin
ventana en `test_flags_guia.py`. Aquí se comprueba lo que solo la ventana puede
estropear:

- que se abre desde el editor de flags de la pareja, junto al cuadro donde se escribe, y
  con el flag de la línea del cursor (o el de la fila elegida) ya buscado;
- que escribir, filtrar y elegir fila cambian lo que se ve, y que la ventana solo
  consulta: lo que hay en el cuadro del editor no cambia;
- que no hay nada que se haga a destiempo (ningún reloj) ni nada que la ventana
  principal tenga que saber, y que los widgets no dependen de cuántas filas salgan.

Las teclas solo llegan a una ventana enseñada, así que cada prueba la enseña (bajo
xvfb en la CI).
"""

import os
import sys

from _harness import Checks

c = Checks("guía de flags (ventana)")

try:
    import tkinter as tk
    from tkinter import ttk
    raiz = tk.Tk()
    raiz.withdraw()
except Exception as e:                                   # sin entorno gráfico
    print(f"  (saltado) no hay entorno gráfico: {e}")
    sys.exit(0)

from common import model
from ui import flags_guia as guia
from ui import tk_flags_guia, tk_pairs

errores_de_tk: list[str] = []
tk.Tk.report_callback_exception = lambda self, *a: errores_de_tk.append(repr(a[1]))

BOTON = "Guía de flags…"


def descendientes(w):
    """El widget y todo lo que cuelga de él."""
    pila, salida = [w], []
    while pila:
        x = pila.pop()
        pila += list(x.winfo_children())
        salida.append(x)
    return salida


def ensenar_ventana(dlg) -> None:
    """Enseña la ventana (las teclas y los eventos solo llegan a una enseñada)."""
    dlg.wm_transient("")           # de una raíz oculta, un diálogo nunca llega a verse
    dlg.deiconify()
    dlg.update()
    assert dlg.winfo_ismapped(), "la ventana no se ha enseñado: los eventos no llegarían"


def abrir_editor(guion_editor, guion_guia, flags=None, mode_name="bisync", capa=None,
                 antes=None):
    """Abre el editor de flags, corre `guion_editor(mesa)` y devuelve lo anotado.

    Las dos ventanas son modales y esperan: se sustituye `wait_window` para que, en vez
    de esperar a una persona, el editor corra su guion y la guía, el suyo
    (`guion_guia(guia)`, que recibe la `VentanaGuia`).
    """
    anotado: dict = {"guias": []}

    def _wait(self, *_a, **_k):
        """Corre el guion que toca a la ventana que espera y la cierra."""
        ensenar_ventana(self)
        if hasattr(self, "guia"):
            anotado["guias"].append(self.guia)
            guion_guia(self.guia, anotado)
            self.destroy()
            return
        botones = {w.cget("text"): w for w in descendientes(self) if isinstance(w, ttk.Button)}
        cajas = {int(w.grid_info()["row"]): w for w in descendientes(self)
                 if isinstance(w, tk.Text) and w.grid_info()}
        caja = cajas[min(cajas)]
        guion_editor(self, caja, botones, anotado)
        botones["Cancelar"].invoke()

    tk.Toplevel.wait_window = _wait
    kwargs = {} if capa is None else {"capa": capa}
    datos = tk_pairs.flags_form(raiz, "Flags", "de prueba", dict(flags or {}), [],
                                mode_name=mode_name, defaults_flags=None, **kwargs)
    anotado["datos"] = datos
    return anotado


def filas(guia_) -> list[str]:
    """Los flags de la tabla de la guía, de arriba abajo."""
    return list(guia_.tabla.orden)


def teclear(guia_, texto: str) -> None:
    """Escribe en el cuadro de búsqueda, como una persona: pone el texto y suelta la tecla."""
    guia_.entrada.focus_force()        # sin gestor de ventanas, las teclas solo llegan a quien lo pide
    guia_.entrada.delete(0, "end")
    guia_.entrada.insert(0, texto)
    guia_.entrada.event_generate("<KeyRelease>", keysym="a")
    guia_.ventana.update()


def poner_filtro(guia_, combo, texto: str) -> None:
    """Elige un valor en un desplegable, como lo haría el ratón."""
    combo.set(texto)
    combo.event_generate("<<ComboboxSelected>>")
    guia_.ventana.update()


tk_pairs.mostrar = lambda dlg, parent=None: dlg.wait_window()
tk_flags_guia.mostrar = lambda dlg, parent=None: dlg.wait_window()

# ----------------------------------------------------------------------------
# Se abre desde el editor de flags, junto al cuadro donde se escribe
# ----------------------------------------------------------------------------

def guion_boton(editor, caja, botones, anotado):
    """Mira dónde está el botón de la guía y lo pulsa con el cursor en la línea de max-delete."""
    boton = botones.get(BOTON)
    anotado["hay_boton"] = boton is not None
    anotado["habilitado"] = boton is not None and "disabled" not in boton.state()
    if boton is None:
        return
    anotado["junto_al_cuadro"] = (boton.master is caja.master,
                                  int(boton.grid_info()["row"]) < int(caja.grid_info()["row"]))
    caja.delete("1.0", "end")
    caja.insert("1.0", "transfers = 4\nmax-delete = 10\n")
    caja.mark_set("insert", "2.4")
    anotado["texto_antes"] = caja.get("1.0", "end-1c")
    boton.invoke()
    anotado["texto_despues"] = caja.get("1.0", "end-1c")


def guion_guia_abierta(guia_, anotado):
    """Apunta cómo se ha abierto la guía."""
    anotado["busqueda"] = guia_.entrada.get()
    anotado["elegida"] = guia_.tabla.elegida
    anotado["primera"] = filas(guia_)[:1]
    anotado["detalle"] = guia_.detalle.get("1.0", "end-1c")
    anotado["mapeada"] = guia_.ventana.winfo_ismapped()


nota = abrir_editor(guion_boton, guion_guia_abierta, flags={"transfers": 4})
c("el editor de flags tiene el botón «Guía de flags…»", nota.get("hay_boton"), True)
c("  encendido, aunque lo escrito no valga: consultar no depende de ello", nota["habilitado"], True)
c("  junto al cuadro de flags, encima de él y en su mismo sitio",
  nota["junto_al_cuadro"], (True, True))
c("al pulsarlo se abre la guía, una sola", len(nota["guias"]), 1)
c("  buscando el flag de la línea donde estaba el cursor", nota["busqueda"], "max-delete")
c("  con ese flag el primero y elegido", (nota["primera"], nota["elegida"]),
  (["max-delete"], "max-delete"))
c("  y su explicación a la vista", "freno" in nota["detalle"].lower(), True)
c("  consultar no toca lo escrito en el editor", nota["texto_despues"], nota["texto_antes"])
c("  ni cierra el editor: sigue habiendo datos que devolver al cancelar",
  nota["datos"], None)
c("  la guía se enseñó (era visible)", nota["mapeada"], True)


def guion_fila_elegida(editor, caja, botones, anotado):
    """Sin flag en la línea del cursor, se usa el de la fila elegida de la tabla."""
    caja.delete("1.0", "end")
    caja.insert("1.0", "transfers = 4\n\n")
    caja.mark_set("insert", "2.0")
    editor.tabla.elegir("transfers", False)
    botones[BOTON].invoke()


nota = abrir_editor(guion_fila_elegida, guion_guia_abierta, flags={"transfers": 4})
c("sin flag en la línea del cursor, busca el de la fila elegida de la tabla",
  nota["busqueda"], "transfers")


def guion_sin_nada(editor, caja, botones, anotado):
    """Sin flag en la línea ni fila elegida, se abre la guía entera."""
    caja.delete("1.0", "end")
    caja.mark_set("insert", "1.0")
    editor.tabla.elegir(None, False)
    botones[BOTON].invoke()


def guion_guia_vacia(guia_, anotado):
    """Apunta qué enseña una guía recién abierta sin nada que buscar."""
    anotado["busqueda"] = guia_.entrada.get()
    anotado["filas"] = len(filas(guia_))
    anotado["cuenta"] = guia_.cuenta.cget("text")
    anotado["mas"] = bool(guia_.mas.winfo_manager())


nota = abrir_editor(guion_sin_nada, guion_guia_vacia)
c("sin nada que buscar se abre la guía entera, sin búsqueda", nota["busqueda"], "")
c("  enseñando solo las primeras filas", nota["filas"], tk_flags_guia.MAX_FILAS)
c("  y diciendo cuántos flags hay en total",
  str(len(guia.fichas())) in nota["cuenta"] and str(tk_flags_guia.MAX_FILAS) in nota["cuenta"],
  True)
c("  con «Ver más» para seguir", nota["mas"], True)

# Los flags comunes: [defaults] no tiene modo, y la guía no finge uno.
nota = abrir_editor(guion_boton, lambda g, a: a.update(modo=g.modo_de_la_pareja),
                    capa=model.ORIGEN_DEFAULTS, mode_name=None)
c("en el editor de [defaults] (sin modo) la guía no tiene modo de pareja", nota["modo"], None)
nota = abrir_editor(guion_boton, lambda g, a: a.update(modo=g.modo_de_la_pareja),
                    mode_name="up-mirror")
c("en el de una pareja, la guía conoce su modo", nota["modo"], "up-mirror")

# ----------------------------------------------------------------------------
# Buscar y filtrar
# ----------------------------------------------------------------------------

def abrir_guia(guion, **kwargs):
    """Abre la guía sola, sobre la raíz, con `guion(guia)`."""
    anotado: dict = {}

    def _wait(self, *_a, **_k):
        """Enseña la guía, corre el guion y la cierra."""
        ensenar_ventana(self)
        anotado["guia"] = self.guia
        guion(self.guia, anotado)
        anotado["widgets"] = len(descendientes(self))
        self.destroy()

    tk.Toplevel.wait_window = _wait
    tk_flags_guia.abrir(raiz, **kwargs)
    return anotado


def guion_buscar(guia_, anotado):
    """Escribe una pregunta, la cambia por otra y por una que no encuentra nada."""
    anotado["widgets_al_abrir"] = len(descendientes(guia_.ventana))
    teclear(guia_, "qué hace con los borrados")
    anotado["borrados"] = filas(guia_)
    anotado["borrados_cuenta"] = guia_.cuenta.cget("text")
    anotado["borrados_elegida"] = guia_.tabla.elegida
    teclear(guia_, "cómo ignoro ficheros temporales")
    anotado["temporales"] = filas(guia_)
    teclear(guia_, "zzzqqq")
    anotado["nada"] = filas(guia_)
    anotado["nada_cuenta"] = guia_.cuenta.cget("text")
    anotado["nada_detalle"] = guia_.detalle.get("1.0", "end-1c").strip()
    anotado["nada_mas"] = bool(guia_.mas.winfo_manager())
    teclear(guia_, "")
    anotado["vuelve"] = len(filas(guia_))
    anotado["widgets_tras"] = len(descendientes(guia_.ventana))


nota = abrir_guia(guion_buscar)
c("«qué hace con los borrados» enseña los de borrado primero",
  {"delete-after", "max-delete"} <= set(nota["borrados"]), True)
c("  la primera fila queda elegida y su explicación a la vista",
  nota["borrados_elegida"], nota["borrados"][0])
c("  y se cuenta cuántos encajan",
  "de" in nota["borrados_cuenta"] or "flags" in nota["borrados_cuenta"], True)
c("«cómo ignoro ficheros temporales» da primero el que excluye",
  nota["temporales"][0], "exclude")
c("una búsqueda sin resultado deja la tabla vacía, lo dice y no deja un detalle viejo",
  (nota["nada"], "ningún" in nota["nada_cuenta"].lower(), nota["nada_detalle"]),
  ([], True, ""))
c("  y no ofrece «Ver más»", nota["nada_mas"], False)
c("al borrar la búsqueda vuelven las filas de siempre", nota["vuelve"],
  tk_flags_guia.MAX_FILAS)
c("buscar no crea ni destruye ningún widget: la ventana se pinta una vez",
  nota["widgets_al_abrir"], nota["widgets_tras"])


def guion_ver_mas(guia_, anotado):
    """Pulsa «Ver más» hasta que no quede más que ver."""
    antes = len(filas(guia_))
    guia_.mas.invoke()
    guia_.ventana.update()
    anotado["despues"] = (antes, len(filas(guia_)))
    for _ in range(40):
        if not guia_.mas.winfo_manager():
            break
        guia_.mas.invoke()
        guia_.ventana.update()
    anotado["todas"] = len(filas(guia_))
    anotado["sin_mas"] = not guia_.mas.winfo_manager()


nota = abrir_guia(guion_ver_mas)
c("«Ver más» enseña más filas", nota["despues"][1] > nota["despues"][0], True)
c("  hasta que salen todas los flags, y entonces desaparece",
  (nota["todas"], nota["sin_mas"]), (len(guia.fichas()), True))
c("  sin más widgets que antes: son filas de un lienzo", nota["widgets"] < 40, True)


def guion_filtros(guia_, anotado):
    """Filtra por riesgo, por modo y por tema, y los quita."""
    poner_filtro(guia_, guia_.riesgo, guia.ETIQUETAS_RIESGO[guia.RIESGO_BORRA])
    anotado["borra"] = [guia.ficha(n).riesgo for n in filas(guia_)]
    anotado["borra_total"] = guia_.cuenta.cget("text")
    poner_filtro(guia_, guia_.riesgo, tk_flags_guia.CUALQUIER_RIESGO)
    poner_filtro(guia_, guia_.modo, "up")
    guia_.mas.invoke() if guia_.mas.winfo_manager() else None
    teclear(guia_, "resilient")
    anotado["resilient_en_up"] = "resilient" in filas(guia_)
    poner_filtro(guia_, guia_.modo, "bisync")
    anotado["resilient_en_bisync"] = filas(guia_)[:1]
    poner_filtro(guia_, guia_.modo, tk_flags_guia.CUALQUIER_MODO)
    teclear(guia_, "")
    poner_filtro(guia_, guia_.tema, guia.ETIQUETAS_TEMA[guia.TEMA_TIEMPOS])
    anotado["tiempos"] = {guia.ficha(n).tema for n in filas(guia_)}
    anotado["tiempos_timeout"] = "timeout" in filas(guia_)
    poner_filtro(guia_, guia_.tema, tk_flags_guia.CUALQUIER_TEMA)
    anotado["sin_filtros"] = len(filas(guia_))


nota = abrir_guia(guion_filtros)
c("filtrar por riesgo «borra» deja solo los que borran o reescriben",
  set(nota["borra"]), {guia.RIESGO_BORRA})
c("filtrar por modo: resilient (de bisync) no sale en «up»", nota["resilient_en_up"], False)
c("  y sí en bisync, el primero", nota["resilient_en_bisync"], ["resilient"])
c("filtrar por tema deja los de ese tema", nota["tiempos"], {guia.TEMA_TIEMPOS})
c("  entre ellos timeout", nota["tiempos_timeout"], True)
c("quitar los filtros devuelve la guía de antes", nota["sin_filtros"], tk_flags_guia.MAX_FILAS)

# ----------------------------------------------------------------------------
# Lo que se ve de cada fila, y de cada flag
# ----------------------------------------------------------------------------

def guion_filas(guia_, anotado):
    """Mira cómo se pintan un reservado, uno con valor de prdrive, uno libre y uno sin explicar."""
    teclear(guia_, "")
    guia_.mas.invoke() if guia_.mas.winfo_manager() else None
    for _ in range(40):
        if not guia_.mas.winfo_manager():
            break
        guia_.mas.invoke()
    anotado["fila"] = {n: guia_.tabla.leer()[guia_.tabla.orden.index(n)]
                       for n in ("workdir", "max-delete", "transfers", "use-cookies",
                                 "cpuprofile")}
    for n in ("workdir", "cpuprofile", "use-cookies", "transfers", "stats"):
        guia_.tabla.elegir(n, True)
        guia_.ventana.update()
        anotado[f"detalle_{n}"] = guia_.detalle.get("1.0", "end-1c")
    guia_.tabla.elegir("transfers", True)
    guia_.ventana.update()
    anotado["tags"] = {t for t in guia_.detalle.tag_names() if t in ("rotulo", "nombre")}
    anotado["solo_lectura"] = str(guia_.detalle.cget("state"))


nota = abrir_guia(guion_filas)
fila_fijo, fila_valor, fila_libre, fila_sin, fila_no = (
    nota["fila"][n] for n in ("workdir", "max-delete", "transfers", "use-cookies", "cpuprofile"))
c("la fila de un reservado dice que lo pone prdrive", "prdrive" in " ".join(fila_fijo), True)
c("  la de uno con valor de prdrive también, sin decir que no se pueda cambiar",
  ("prdrive" in " ".join(fila_valor), "no se puede" in " ".join(fila_valor)), (True, False))
c("  la de uno que no admite el config, que no se admite",
  "no se admite" in " ".join(fila_no).lower(), True)
c("  la de uno libre no lleva marca de prdrive", "prdrive" in " ".join(fila_libre), False)
c("  la de uno sin explicación lo dice", "sin clasificar" in " ".join(fila_sin).lower(), True)
c("el detalle de un reservado trae la marca y el motivo del modelo",
  guia.ETIQUETA_ESTADO[guia.ESTADO_FIJO] in nota["detalle_workdir"]
  and model.FLAGS_RESERVADOS["workdir"] in nota["detalle_workdir"], True)
c("  el de uno que el config rechaza, la suya",
  guia.ETIQUETA_ESTADO[guia.ESTADO_NO_ADMITIDO] in nota["detalle_cpuprofile"], True)
c("  el de uno sin explicación marca la ayuda de rclone como inglés",
  "inglés" in nota["detalle_use-cookies"], True)
c("  el de uno libre trae el ejemplo para copiar", "transfers = 8" in nota["detalle_transfers"],
  True)
c("  y el valor que le pone prdrive, el de uno que lo tiene",
  str(model.BASE_FLAGS["stats"]) in nota["detalle_stats"], True)
c("  en un texto con rótulos y nombre destacados, que no se puede escribir encima",
  (nota["tags"], nota["solo_lectura"]), ({"rotulo", "nombre"}, "disabled"))


def guion_modo(guia_, anotado):
    """Con una pareja en modo up-mirror, lo que no sirve ahí sale apagado y se dice."""
    guia_.mas.invoke() if guia_.mas.winfo_manager() else None
    teclear(guia_, "resilient")
    anotado["tono"] = guia_.tabla.filas["resilient"].tono
    guia_.tabla.elegir("resilient", True)
    guia_.ventana.update()
    anotado["detalle"] = guia_.detalle.get("1.0", "end-1c")
    teclear(guia_, "delete-after")
    anotado["tono_sirve"] = guia_.tabla.filas["delete-after"].tono
    guia_.tabla.elegir("delete-after", True)
    guia_.ventana.update()
    anotado["detalle_sirve"] = guia_.detalle.get("1.0", "end-1c")


nota = abrir_guia(guion_modo, modo="up-mirror")
c("con una pareja up-mirror, un flag de bisync sale apagado", nota["tono"], "apagado")
c("  y el detalle dice que no sirve en su pareja",
  "no sirve en tu pareja (up-mirror)" in nota["detalle"].lower(), True)
c("  uno que sí sirve no sale apagado y lo dice", (nota["tono_sirve"],
                                                  "sirve en tu pareja (up-mirror)"
                                                  in nota["detalle_sirve"].lower()),
  ("", True))

# ----------------------------------------------------------------------------
# Teclado, cierre y lo que NO hay
# ----------------------------------------------------------------------------

def guion_teclado(guia_, anotado):
    """Con el foco en el cuadro de búsqueda, Abajo y Arriba recorren la tabla; Escape cierra."""
    anotado["foco"] = guia_.ventana.focus_lastfor() is guia_.entrada
    teclear(guia_, "delete")
    primera = guia_.tabla.elegida
    guia_.entrada.event_generate("<Down>")
    guia_.ventana.update()
    segunda = guia_.tabla.elegida
    guia_.entrada.event_generate("<Up>")
    guia_.ventana.update()
    anotado["recorrido"] = (primera, segunda != primera, guia_.tabla.elegida == primera)
    guia_.entrada.event_generate("<Up>")
    guia_.ventana.update()
    anotado["tope"] = guia_.tabla.elegida == primera
    guia_.ventana.event_generate("<Escape>")
    guia_.ventana.update()
    anotado["cerrada_con_escape"] = not guia_.ventana.winfo_exists()


def _wait_escape(self, *_a, **_k):
    """Lo mismo que `abrir_guia`, pero sin destruir la ventana: la cierra el guion."""
    ensenar_ventana(self)
    guion_teclado(self.guia, nota_teclado)


nota_teclado: dict = {}
tk.Toplevel.wait_window = _wait_escape
tk_flags_guia.abrir(raiz)
c("el foco empieza en el cuadro de búsqueda: se escribe al abrirla", nota_teclado["foco"], True)
c("Abajo y Arriba, desde el cuadro, recorren la tabla sin salir de él",
  nota_teclado["recorrido"][1:], (True, True))
c("  y no se salen por arriba", nota_teclado["tope"], True)
c("Escape cierra la guía", nota_teclado["cerrada_con_escape"], True)


def pulsar(guia_, keysym: str) -> None:
    """Pulsa y SUELTA una tecla en el cuadro de búsqueda, como un teclado de verdad."""
    guia_.entrada.focus_force()
    guia_.entrada.event_generate(f"<KeyPress-{keysym}>")
    guia_.entrada.event_generate(f"<KeyRelease-{keysym}>")
    guia_.ventana.update()


# Alt suelta, generada con `event_generate`, no vuelve nunca en Windows: lo vio `faulthandler`
# en la CI (un traceback dentro de `event_generate`, con `Left`, `Right`, `Shift_L` y `Control_L`
# ya devueltas por el mismo manejador, que no mira qué tecla es). No se sabe por qué, pero la
# guía no entra: por eso ahí no se genera, y en Linux sí.
TECLAS_QUE_NO_ESCRIBEN = ("Left", "Right", "Shift_L", "Control_L") + (
    () if os.name == "nt" else ("Alt_L",))
if os.name == "nt":
    print("  (saltado) Alt suelta: en Windows, generarla con event_generate no vuelve")


def guion_teclas_de_verdad(guia_, anotado):
    """Una tecla de verdad se pulsa Y se suelta: soltarla no puede deshacer lo que hizo."""
    teclear(guia_, "delete")
    orden = list(guia_.tabla.orden)
    anotado["orden"] = orden
    pulsar(guia_, "Down")
    anotado["abajo"] = guia_.tabla.elegida
    pulsar(guia_, "Down")
    anotado["abajo2"] = guia_.tabla.elegida
    pulsar(guia_, "Up")
    anotado["arriba"] = guia_.tabla.elegida
    teclear(guia_, "")
    guia_.mas.invoke()
    guia_.ventana.update()
    anotado["con_mas"] = len(filas(guia_))
    elegida = guia_.tabla.orden[2]
    guia_.tabla.elegir(elegida, True)
    for tecla in TECLAS_QUE_NO_ESCRIBEN:
        pulsar(guia_, tecla)
    anotado["tras_modificadoras"] = (len(filas(guia_)), guia_.tabla.elegida == elegida)
    pulsar(guia_, "Down")
    anotado["tras_abajo_con_mas"] = (len(filas(guia_)),
                                     guia_.tabla.elegida == guia_.tabla.orden[3])
    guia_.entrada.insert("end", "x")
    pulsar(guia_, "x")
    anotado["al_escribir"] = len(filas(guia_))


nota = abrir_guia(guion_teclas_de_verdad)
c("Abajo, pulsada y soltada, pasa a la fila siguiente y se queda en ella",
  (nota["abajo"], nota["abajo2"]), (nota["orden"][1], nota["orden"][2]))
c("  y Arriba vuelve a la anterior", nota["arriba"], nota["orden"][1])
c("soltar Mayúsculas, Control, Alt (donde se puede generar) o las flechas laterales no repinta: "
  "«Ver más» sigue abierto y la fila elegida no se mueve",
  nota["tras_modificadoras"], (tk_flags_guia.MAX_FILAS + tk_flags_guia.PASO_VER_MAS, True))
c("  ni tampoco las flechas, que mueven la fila sin cerrar «Ver más»",
  nota["tras_abajo_con_mas"], (tk_flags_guia.MAX_FILAS + tk_flags_guia.PASO_VER_MAS, True))
c("escribir una letra sí repinta la búsqueda desde las primeras filas",
  nota["al_escribir"] <= tk_flags_guia.MAX_FILAS, True)


def guion_limpieza(guia_, anotado):
    """Hace de todo y mira que no quede ningún reloj de Tk pendiente."""
    teclear(guia_, "borrados")
    poner_filtro(guia_, guia_.riesgo, guia.ETIQUETAS_RIESGO[guia.RIESGO_BORRA])
    guia_.tabla.elegir(filas(guia_)[0], True)
    guia_.ventana.update()
    anotado["relojes"] = list(raiz.tk.call("after", "info"))


antes = list(raiz.tk.call("after", "info"))
nota = abrir_guia(guion_limpieza)
c("la guía no deja relojes de Tk pendientes (se actualiza al instante, no a plazo)",
  nota["relojes"], antes)
c("  ni errores en los manejadores de eventos", errores_de_tk, [])

import re
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
modulo = (REPO / "ui" / "tk_flags_guia.py").read_text(encoding="utf-8")
c("la ventana solo dibuja: no hay decisiones de la guía en ella (todo sale de flags_guia)",
  [n for n in ("ESTADOS_", "BORRADO =", "CHOQUES", "SOLO_SINCRONIZA") if n in modulo], [])
c("  y tkinter solo se importa dentro de las funciones",
  re.findall(r"^(?:import tkinter|from tkinter)", modulo, re.M), [])
c("  ni usa colores a mano: los pone theme.py",
  re.findall(r"#[0-9a-fA-F]{6}\b", modulo), [])

sys.exit(c.report())
