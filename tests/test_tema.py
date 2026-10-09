#!/usr/bin/env python3
"""El tema claro y el oscuro: la misma paleta con otros valores, y quién elige.

Los colores se leen como `theme.X` en el momento de pintar, así que cambiar de
tema es cambiar esos nombres (`theme.usar()`). Aquí se comprueba que las dos
paletas dicen lo mismo con otros valores, que el tema se decide una vez y por
quién, y que los componentes del sistema de diseño (el chip con su disco, el
aviso con su baldosa, la línea de estado) se pintan en los dos sin romperse.
"""

import os
import sys

from _harness import Checks

from ui import icons, theme
from ui.tk import bloque_aviso

c = Checks("tema: claro y oscuro")

# las dos paletas tienen las mismas claves, y todas son colores
c("claro y oscuro nombran los mismos colores",
  sorted(theme.CLARO), sorted(theme.OSCURO))
c("todos son #RRGGBB",
  [k for k, v in {**theme.CLARO, **theme.OSCURO}.items()
   if not (v.startswith("#") and len(v) == 7)], [])
c("y cada nombre existe en el módulo",
  [k for k in theme.CLARO if not hasattr(theme, k)], [])

# usar() cambia los nombres del módulo
theme.usar("oscuro")
c("con el oscuro, el papel es el oscuro", (theme.TEMA, theme.PAPEL),
  ("oscuro", theme.OSCURO["PAPEL"]))
c("  y la letra sobre el acento se oscurece", theme.SOBRE_ACENTO,
  theme.OSCURO["SOBRE_ACENTO"])
theme.usar("claro")
c("de vuelta al claro", (theme.TEMA, theme.PAPEL), ("claro", theme.CLARO["PAPEL"]))
try:
    theme.usar("sepia")
    raro = "aceptado"
except ValueError:
    raro = "ValueError"
c("un tema que no existe no se acepta", raro, "ValueError")

# quién decide: la variable manda, si no el sistema; y solo una vez
real_sistema = theme.sistema_oscuro
antes = os.environ.pop("PRDRIVE_TEMA", None)
try:
    theme.sistema_oscuro = lambda: True
    theme._tema_elegido = False
    c("sin variable, el sistema oscuro da el tema oscuro", theme.elegir_tema(), "oscuro")
    theme.sistema_oscuro = lambda: False
    c("  y ya decidido no se vuelve a preguntar", theme.elegir_tema(), "oscuro")
    theme._tema_elegido = False
    os.environ["PRDRIVE_TEMA"] = "oscuro"
    c("PRDRIVE_TEMA manda sobre el sistema", theme.elegir_tema(), "oscuro")
    theme._tema_elegido = False
    os.environ["PRDRIVE_TEMA"] = "lila"
    c("  y un valor que no vale se ignora", theme.elegir_tema(), "claro")
finally:
    theme.sistema_oscuro = real_sistema
    os.environ.pop("PRDRIVE_TEMA", None)
    if antes is not None:
        os.environ["PRDRIVE_TEMA"] = antes
    theme.usar("claro")
    theme._tema_elegido = False

# los colores no se congelan en los argumentos por defecto
c("boton_icono no lleva colores congelados",
  theme.boton_icono.__defaults__, (None, None, 15))

# la pastilla de la bandeja se recorta del campo: transparente alrededor
rgba = icons._capas_rgba(icons.capas_bandeja(32, icons.AVISO), 64.0, 32)
# el recorte rodea la pastilla (centro 47, radio 16 + 4) por la izquierda
x = round((47 - 18) * 32 / 64)
y = round(47 * 32 / 64)
c("la pastilla se recorta del campo, sin aro: ahí no hay nada",
  rgba[y][x][3] < 0.2, True)
c("  y la esquina de arriba a la izquierda sigue siendo campo",
  rgba[3][3][3] > 0.9, True)

try:
    import tkinter as tk
    from tkinter import ttk
    raiz = tk.Tk()
    raiz.withdraw()
except Exception as e:                                   # sin entorno gráfico
    print(f"  (saltado) no hay entorno gráfico: {e}")
    sys.exit(c.report())

for tema in ("claro", "oscuro"):
    theme.usar(tema)
    theme._puestos.clear()
    theme.apply(raiz)
    marco = ttk.Frame(raiz)
    chip = theme.chip(marco, "al día", "Ok.")
    c(f"{tema}: un chip de estado lleva su disco", bool(chip.cget("image")), True)
    c(f"{tema}: uno neutro no", bool(theme.chip(marco, "bisync").cget("image")), False)
    solido = theme.chip(marco, "falló", "Peligro.", "alert", solido=True)
    c(f"{tema}: el sólido lleva su estilo", str(solido.cget("style")),
      "SolidoPeligro.Chip.TLabel")
    aviso = theme.aviso(marco, "Título", "Cuerpo", tono="Azul.", icono="down")
    c(f"{tema}: el aviso es del fondo de su tono", str(aviso.cget("style")),
      "NotaAzul.TFrame")
    c(f"{tema}:   con su baldosa",
      any(isinstance(w, ttk.Label) and w.cget("image") for w in aviso.winfo_children()),
      True)
    c(f"{tema}:   y da sus etiquetas de título y cuerpo",
      (str(aviso.titulo.cget("text")), str(aviso.cuerpo.cget("text"))), ("Título", "Cuerpo"))
    sin_titulo = theme.aviso(marco, "", "Solo cuerpo")
    sin_cuerpo = theme.aviso(marco, "Solo título")
    c(f"{tema}:   sin título o sin cuerpo, esa etiqueta no se crea",
      (sin_titulo.titulo, sin_cuerpo.cuerpo), (None, None))
    sin_boton = bloque_aviso(marco, "Solo texto")
    con_boton = bloque_aviso(marco, "Título\nCuerpo", boton=("Instalar", lambda: None))
    c(f"{tema}:   bloque_aviso da su botón, o None sin él",
      (sin_boton.boton, str(con_boton.boton.cget("text"))), (None, "Instalar"))
    linea = theme.linea_estado(marco, "llave", "Llaves.kdbx, al día.", "Abrir llavero")
    c(f"{tema}: la línea de estado lleva su acción",
      str(linea.boton.cget("text")), "Abrir llavero")
    c(f"{tema}: el disco y la baldosa se pintan",
      (icons.disco(raiz, "ok", theme.OK, theme.SOBRE_OK, theme.GRIS_FONDO) is not None,
       icons.baldosa(raiz, "alert", theme.AVISO, theme.SOBRE_AVISO,
                     theme.AVISO_FONDO) is not None), (True, True))
    c(f"{tema}: la marca con la pastilla de aviso se pinta",
      icons.marca_estado(raiz, 40, icons.AVISO, fondo=theme.PAPEL) is not None, True)
    marco.destroy()

theme.usar("claro")
theme._puestos.clear()
raiz.destroy()
sys.exit(c.report())
