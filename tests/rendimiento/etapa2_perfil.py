"""Hijo del perfil: a qué se van los milisegundos de los momentos lentos (etapa 2).

TEMPORAL, como todo `etapa2_*`: lo borra la tarea 15 de la etapa 2.

    python etapa2_perfil.py                (por `entrada.py etapa2_perfil`)

Corre la ventana principal real del dispositivo de muestra (`etapa2_marco.correr`) y
pone un `cProfile` alrededor de cada momento, por separado:

- `abrir-parejas`: del clic en «Parejas…» a la ventana enseñada;
- `catalogo-llega`: llega el catálogo del remoto y la pantalla se repinta con él
  (`dlg.sondeo._mirar()` y el `update()` que sigue, como hace el driver);
- `abrir-ajustes`: del clic en «Ajustes…» a la ventana enseñada;
- `apartado-reparacion` y `apartado-configuracion`: el clic en cada apartado, en
  ese orden. «Ajustes» abre en «Configuración» (`tk_doctor.INICIAL`), así que
  hacer clic en ella primero no haría nada; yendo antes a «Reparación» las dos se
  construyen de verdad.

Por momento deja una línea `perfil-<momento>` con las 25 funciones que más tiempo
gastan por sí mismas (`tottime`) y cuánto del total cae en llamadas a Tcl/Tk
(`_tkinter.tkapp.call` y compañía): si es casi todo, el coste es de Tk (repintar,
reorganizar la rejilla, crear widgets) y no del Python que lo pide. Un perfil
alarga todo lo que es Python: los tiempos de aquí no son los del driver, solo
dicen en qué se reparten.
"""

from __future__ import annotations

import cProfile
import os
import pstats
import time

import etapa2_marco as marco
from etapa2_marco import ms, record

TOP = 25
"""Las funciones que se guardan de cada momento."""
ESPERA_CATALOGO = 5.0
"""Segundos que se espera a que acabe la lectura del catálogo."""


def etiqueta(clave: tuple) -> str:
    """Devuelve un nombre corto y legible para una función de `pstats`."""
    fichero, linea, nombre = clave
    if fichero == "~":
        return nombre
    return f"{os.path.basename(fichero)}:{linea}({nombre})"


def resumir(perfil: cProfile.Profile, momento: str, valor_ms: float, **detalle) -> None:
    """Guarda el resumen de un perfil: sus mayores funciones y el peso de Tk."""
    estadisticas = pstats.Stats(perfil)
    todas = estadisticas.stats
    total = sum(v[2] for v in todas.values())
    mayores = sorted(todas.items(), key=lambda kv: kv[1][2], reverse=True)[:TOP]
    llamadas_tk = sum(v[2] for k, v in todas.items() if "'call' of '_tkinter.tkapp'" in k[2])
    todo_tk = sum(v[2] for k, v in todas.items() if "_tkinter" in k[2] or "_tkinter" in k[0])
    record("perfil-" + momento, valor_ms, total_ms=round(total * 1000, 1),
           tk_call_ms=round(llamadas_tk * 1000, 1), tk_ms=round(todo_tk * 1000, 1),
           tk_call_parte=round(llamadas_tk / total, 3) if total else None,
           tk_parte=round(todo_tk / total, 3) if total else None,
           top=[{"funcion": etiqueta(k), "llamadas": v[1], "propio_ms": round(v[2] * 1000, 1),
                 "acumulado_ms": round(v[3] * 1000, 1)} for k, v in mayores], **detalle)


def perfilado(momento: str):
    """Devuelve `(perfil, parar)`: el perfil encendido y la función que lo para y lo guarda."""
    perfil = cProfile.Profile()
    t0 = time.perf_counter()
    perfil.enable()

    def parar(**detalle) -> float:
        perfil.disable()
        valor = ms(t0, time.perf_counter())
        resumir(perfil, momento, valor, **detalle)
        return valor
    return perfil, parar


def abrir(raiz, texto: str, momento: str, despues=None) -> None:
    """Pulsa un botón de la ventana principal con el perfil encendido hasta que se ve la ventana.

    Args:
        texto: El texto del botón.
        momento: El nombre del perfil.
        despues: `despues(dlg)`, si se da, corre con la ventana ya enseñada y antes de
            destruirla (sin perfil encendido, salvo el que se ponga ahí).
    """
    boton = marco.find_button(raiz, texto + "…", texto)
    if boton is None:
        marco.NOTES["error"] = f"no hay botón «{texto}…»"
        return
    marco.retener_catalogo()
    raiz.update()
    estado = {}

    def al_mostrar(dlg, hora) -> bool:
        estado["parar"](widgets=marco.contar(dlg))
        if despues is not None:
            despues(dlg)
        dlg.destroy()
        raiz.update()
        marco.soltar_catalogo()
        return True

    _perfil, estado["parar"] = perfilado(momento)
    marco.HOOK["al_mostrar"] = al_mostrar
    boton.invoke()


def llega_el_catalogo(dlg) -> None:
    """Suelta el catálogo y perfila el repintado de «Parejas» con él."""
    sondeo = getattr(dlg, "sondeo", None)
    encargo = getattr(sondeo, "_encargo", None)
    marco.soltar_catalogo()
    if encargo is None:
        marco.NOTES["llegada"] = "la ventana no tiene sondeo con encargo"
        return
    limite = time.time() + ESPERA_CATALOGO
    while not encargo.hecho and time.time() < limite:
        time.sleep(0.001)
    _perfil, parar = perfilado("catalogo-llega")
    sondeo._mirar()
    dlg.update()
    parar(widgets=marco.contar(dlg))


def apartados(dlg) -> None:
    """Perfila el clic en «Reparación» y luego en «Configuración» de «Ajustes»."""
    for texto, momento in (("Reparación", "apartado-reparacion"),
                           ("Configuración", "apartado-configuracion")):
        boton = marco.find_button(dlg, texto)
        if boton is None:
            marco.NOTES.setdefault("sin_apartado", []).append(texto)
            continue
        dlg.update()
        _perfil, parar = perfilado(momento)
        boton.invoke()
        dlg.update()
        parar(widgets=marco.contar(dlg))


def sonda(raiz) -> None:
    abrir(raiz, "Parejas", "abrir-parejas", despues=llega_el_catalogo)
    abrir(raiz, "Ajustes", "abrir-ajustes", despues=apartados)


def main() -> None:
    marco.correr(sonda)


if __name__ == "__main__":
    main()
