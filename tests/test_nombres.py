#!/usr/bin/env python3
"""El nombre que se enseña de una unidad sin nombre propio (`common/nombres.py`).

Es lo que decide la bandeja, los avisos y el diario del agente, en un solo
sitio. Sin Tk y sin tocar el sistema:
- Sin nombre propio, sale la etiqueta del volumen si la tiene y, si no,
  «prdrive · <4 primeros del id>». Una etiqueta que prdrive mismo escribe
  («PRDRIVE») no distingue nada y cuenta como ninguna.
- El nombre del equipo que aprovisionó la unidad (el que el instalador guardó
  en su `state/fleet.json`) no es un nombre propio: se reconoce porque es uno
  de los equipos desde los que ha publicado. Salvo si es también el `label=`
  de su `autorun.inf`, que solo escribe «Nombre e icono»: entonces alguien la
  llamó así a propósito.
- Lo que alguien puso nunca se toca.
- Solo si aun así dos unidades se llaman igual se añade, como sufijo, el nombre
  del equipo; y el id si ni así.
- `etiqueta_de()` lee la etiqueta del sistema (Windows: `GetVolumeInformationW`;
  Linux: `/dev/disk/by-label`), sin lanzar nunca.
"""

import os
from pathlib import Path

from _harness import Checks, tmpdir

from common import nombres

c = Checks("nombre por defecto de una unidad")

UID = "a1b2c3d4" + "0" * 24
OTRO = "a1b2ffff" + "0" * 24          # empieza igual que UID: sus 4 primeros coinciden

# --- sin nombre propio: la etiqueta, o el principio del id
c("con etiqueta, la etiqueta", nombres.por_defecto(UID, "PENDRIVE AZUL"), "PENDRIVE AZUL")
c("  sin sobrantes", nombres.por_defecto(UID, "  SANDISK \n"), "SANDISK")
c("sin etiqueta, «prdrive · 4 del id»", nombres.por_defecto(UID, ""), "prdrive · a1b2")
c("  una etiqueta en blanco es ninguna", nombres.por_defecto(UID, "   "), "prdrive · a1b2")
c("  y la que escribe prdrive, también", nombres.por_defecto(UID, "PRDRIVE"), "prdrive · a1b2")
c("  sin importar las mayúsculas", nombres.por_defecto(UID, "prdrive"), "prdrive · a1b2")
c("  pero no una que solo la lleva dentro",
  nombres.por_defecto(UID, "PRDRIVE-2"), "PRDRIVE-2")
c("dos unidades sin etiqueta, ids distintos, nombres distintos",
  nombres.por_defecto(UID, "") != nombres.por_defecto("c3d4" + "0" * 28, ""), True)

# --- cuál es el nombre del equipo y cuál uno propio
c("el del equipo que la aprovisionó",
  nombres.es_del_equipo("DESKTOP-PERE", ("LAPTOP-ANA", "DESKTOP-PERE")), True)
c("  sin importar las mayúsculas", nombres.es_del_equipo("desktop-pere", ("DESKTOP-PERE",)), True)
c("uno que alguien puso, no", nombres.es_del_equipo("Pendrive azul", ("DESKTOP-PERE",)), False)
c("sin equipos conocidos, nada lo es", nombres.es_del_equipo("DESKTOP-PERE", ()), False)
c("un nombre en blanco no es de ningún equipo", nombres.es_del_equipo("  ", ("DESKTOP-PERE",)), False)

# --- elegir
n = nombres.elegir(UID, "Pendrive azul", "SANDISK", ("DESKTOP-PERE",))
c("lo que alguien puso, tal cual, aunque haya etiqueta", (n.texto, n.propio, n.equipo),
  ("Pendrive azul", True, ""))
n = nombres.elegir(UID, "DESKTOP-PERE", "SANDISK", ("DESKTOP-PERE",))
c("el nombre del equipo se cambia por la etiqueta", (n.texto, n.propio), ("SANDISK", False))
c("  y se sabe de qué equipo venía", n.equipo, "DESKTOP-PERE")
n = nombres.elegir(UID, "DESKTOP-PERE", "", ("DESKTOP-PERE",))
c("  sin etiqueta, por el id", n.texto, "prdrive · a1b2")
n = nombres.elegir(UID, "", "", ())
c("sin nada guardado, el del id", (n.texto, n.propio, n.equipo), ("prdrive · a1b2", False, ""))
n = nombres.elegir(UID, "", "SANDISK", ())
c("  o la etiqueta", (n.texto, n.propio), ("SANDISK", False))
n = nombres.elegir(UID, "Pendrive de Pere", "", ())
c("un nombre guardado que no es de equipo alguno es propio (también el de un equipo viejo)",
  (n.texto, n.propio), ("Pendrive de Pere", True))

# --- el que alguien puso igual que el equipo: lo dice el `label=` del autorun.inf
n = nombres.elegir(UID, "PERETATIL", "PRDRIVE", ("Peretatil",), "PERETATIL")
c("llamada como el equipo en «Nombre e icono», es propio", (n.texto, n.propio),
  ("PERETATIL", True))
n = nombres.elegir(UID, "Peretatil", "", ("Peretatil",), "  peretatil ")
c("  sin importar mayúsculas ni sobrantes", (n.texto, n.propio), ("Peretatil", True))
n = nombres.elegir(UID, "Peretatil", "", ("Peretatil",), "Pendrive azul")
c("un `label=` distinto no dice nada del guardado", (n.texto, n.propio),
  ("prdrive · a1b2", False))
n = nombres.elegir(UID, "", "", ("Peretatil",), "Pendrive azul")
c("  ni sin nombre guardado lo pone él", (n.texto, n.propio), ("prdrive · a1b2", False))

# --- distinguir
sin_choque = nombres.Nombre("SANDISK", False, "DESKTOP-PERE")
c("sin otra que se llame igual, el nombre", nombres.distinguir(sin_choque, UID, ["KINGSTON"]),
  "SANDISK")
c("  sin otras", nombres.distinguir(sin_choque, UID, []), "SANDISK")
c("con otra igual, el nombre del equipo detrás",
  nombres.distinguir(sin_choque, UID, ["SANDISK", "KINGSTON"]), "SANDISK (DESKTOP-PERE)")
c("  sin importar las mayúsculas",
  nombres.distinguir(sin_choque, UID, ["sandisk"]), "SANDISK (DESKTOP-PERE)")
c("si ni con el equipo, el id",
  nombres.distinguir(sin_choque, UID, ["SANDISK", "SANDISK (DESKTOP-PERE)"]),
  "SANDISK (DESKTOP-PERE) · a1b2c3d4")
c("sin equipo conocido, el id",
  nombres.distinguir(nombres.Nombre("SANDISK", False, ""), UID, ["SANDISK"]),
  "SANDISK · a1b2c3d4")
c("los 4 del id de dos unidades pueden coincidir: el nombre del id choca y se resuelve",
  nombres.distinguir(nombres.Nombre(nombres.por_defecto(UID), False, ""), UID,
                     [nombres.por_defecto(OTRO)]), "prdrive · a1b2 · a1b2c3d4")
c("lo que alguien puso no se toca, ni aunque choque",
  nombres.distinguir(nombres.Nombre("Pendrive", True, ""), UID, ["Pendrive"]), "Pendrive")

# --- etiqueta_de(): el sistema (Linux: /dev/disk/by-label)
t = tmpdir()
por_etiqueta = t / "by-label"
por_etiqueta.mkdir()
# udev escapa lo que no es seguro en un nombre de fichero: `\x20` es un espacio.
# Los enlaces no se resuelven (apuntan a un `/dev` que aquí no existe): se mira su nombre.
enlaces = {"SANDISK": "../../sdb1", "MI\\x20PEN": "../../sdc1"}
if os.name != "nt":
    for etiqueta, destino in enlaces.items():
        (por_etiqueta / etiqueta).symlink_to(destino)
    reales_linux = (nombres.POR_ETIQUETA, nombres._origen)
    try:
        nombres.POR_ETIQUETA = por_etiqueta
        raiz = Path("/media/x")
        nombres._origen = lambda r: "/dev/sdb1"
        c("Linux: la etiqueta del dispositivo montado en la raíz",
          nombres._etiqueta_linux(raiz), "SANDISK")
        nombres._origen = lambda r: "/dev/sdc1"
        c("  con lo que udev escapa deshecho", nombres._etiqueta_linux(raiz), "MI PEN")
        nombres._origen = lambda r: "/dev/sdd1"
        c("  un dispositivo sin etiqueta no da ninguna", nombres._etiqueta_linux(raiz), "")
        nombres._origen = lambda r: None
        c("  una raíz que no es un punto de montaje, tampoco", nombres._etiqueta_linux(raiz), "")
        nombres.POR_ETIQUETA = t / "no-existe"
        nombres._origen = lambda r: "/dev/sdb1"
        c("  sin /dev/disk/by-label, ninguna", nombres._etiqueta_linux(raiz), "")
    finally:
        nombres.POR_ETIQUETA, nombres._origen = reales_linux

visto = []
reales = (nombres._etiqueta_windows, nombres._etiqueta_linux, nombres.IS_WIN)
try:
    nombres.IS_WIN = True
    nombres._etiqueta_windows = lambda raiz: visto.append(("w", raiz)) or "  WIN  "
    nombres._etiqueta_linux = lambda raiz: visto.append(("l", raiz)) or "LIN"
    c("etiqueta_de() en Windows pregunta a Windows y limpia", nombres.etiqueta_de(Path("E:\\")), "WIN")
    nombres.IS_WIN = False
    c("  y en Linux a udev", nombres.etiqueta_de(Path("/media/x")), "LIN")
    c("  cada una con su raíz", [v[0] for v in visto], ["w", "l"])

    def falla(raiz):
        raise OSError("no se puede")
    nombres._etiqueta_linux = falla
    c("lo que el sistema no deja leer es «sin etiqueta», sin lanzar",
      nombres.etiqueta_de(Path("/media/x")), "")
finally:
    nombres._etiqueta_windows, nombres._etiqueta_linux, nombres.IS_WIN = reales

raise SystemExit(c.report())
