#!/usr/bin/env python3
"""Hornea los tokens y los glifos del 0.7.1 en modulos Python sin dependencias de Tk.

Es del banco de la interfaz (temporal, ver `banco/LEEME.md`). Ya esta hecho: `app/tokens.py` y
`app/glifos.py` salen identicos de correrlo contra el repo; solo hace falta si cambia `ui/theme.py`
o `ui/icons.py`.

Uso: python3 gen_assets.py <src-071> <destino app/>

Lee ui/theme.py y ui/icons.py CON importlib desde su fichero (no importa el paquete `ui`, que precarga el
Tk con Xft) y escribe:
  tokens.py  CLARO, OSCURO, tamanos de fuente por rol (pt), escala E1..E7 (px a 96 ppp)
  glifos.py  GLIFOS (tabla de primitivas sobre rejilla de 16), VISTO, TRAZO
Es el equivalente de lo que haria un paso de build: la tabla de colores y de glifos ya existe como datos puros.
"""
import importlib.util
import pprint
import sys
from pathlib import Path

src, dst = Path(sys.argv[1]), Path(sys.argv[2])


def cargar(nombre, fichero):
    spec = importlib.util.spec_from_file_location(nombre, fichero)
    m = importlib.util.module_from_spec(spec)
    sys.modules[nombre] = m
    spec.loader.exec_module(m)
    return m


theme = cargar("theme_fuente", src / "ui" / "theme.py")
icons = cargar("icons_fuente", src / "ui" / "icons.py")

# theme.fuente() llama a familia(), que necesita tkinter: la tabla de tamanos se reproduce aqui con los
# mismos valores y se comprueba contra la fuente mas abajo.
ROLES = {  # (familia, pt, negrita)   copiado de theme.fuente()
    "titulo": ("fuerte", 16, False), "dialogo": ("fuerte", 14, False), "seccion": ("fuerte", 11, False),
    "rotulo": ("texto", 8, True), "fuerte": ("fuerte", 10, False), "pista": ("texto", 9, False),
    "mono": ("mono", 9, False), "mono_pequena": ("mono", 8, False), "etiqueta": ("texto", 8, False),
    "texto": ("texto", 10, False),
}
fuente_src = (src / "ui" / "theme.py").read_text(encoding="utf-8")
for rol, (fam, pt, neg) in ROLES.items():   # comprobacion barata de que no ha cambiado el tamano
    assert f'(familia("{fam}"), {pt}' in fuente_src, rol

with open(dst / "tokens.py", "w", encoding="utf-8") as f:
    f.write('"""GENERADO por lib/gen_assets.py a partir de ui/theme.py (0.7.1). No editar."""\n\n')
    f.write("CLARO = " + pprint.pformat(theme.CLARO, sort_dicts=False) + "\n\n")
    f.write("OSCURO = " + pprint.pformat(theme.OSCURO, sort_dicts=False) + "\n\n")
    f.write("ROLES = " + pprint.pformat(ROLES, sort_dicts=False) + "\n\n")
    f.write("# Escala de espacios del diseno, en px a 96 ppp (medida(n) = n*72/96 pt = n px)\n")
    f.write("E1, E2, E3, E4, E5, E6, E7 = 4, 8, 12, 16, 24, 32, 48\n")
    f.write("RADIO = 4\nALTO_CONTROL = 34\nALTO_PEQUENO = 28\nALTO_GRANDE = 42\nALTO_FILA_LATERAL = 32\nALTO_CHIP = 24\n")

with open(dst / "glifos.py", "w", encoding="utf-8") as f:
    f.write('"""GENERADO por lib/gen_assets.py a partir de ui/icons.py (0.7.1). No editar."""\n\n')
    f.write(f"TRAZO = {icons.TRAZO!r}\n")
    f.write(f"VISTO = {icons._VISTO!r}\n")
    f.write("GLIFOS = " + pprint.pformat(icons.GLIFOS, sort_dicts=False, width=110) + "\n")
print("ok", dst, len(icons.GLIFOS), "glifos", file=sys.stderr)
