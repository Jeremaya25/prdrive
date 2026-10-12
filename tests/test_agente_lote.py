#!/usr/bin/env python3
"""El agente pasa en un solo `sync.py` las parejas de una raíz a las que les toca a la vez.

Solo cuando el `sync.py` de esa raíz ya ha dicho, con su parte
(`common/parte.py`), cómo le fue a una pareja: entonces el resultado de cada una
sale de su parte y de su trozo de la salida. El llavero va siempre solo, y lo
que no toca todavía no se arrastra.
"""

from _harness import Checks

import _agente_falso as F
import agente
from common import consumo, equipo, parte, store
from common import planificador as pl

c = Checks("agente: varias parejas en un sync.py")

F.preparar()
UID = "lote-0001"
MIN = 60.0
raiz = F.unidad(UID, parejas=("docs", "fotos", "notas"),
                daemon='[daemon]\npairs = ["docs", "fotos", "notas"]\ninterval_minutes = 5\n')
equipo.guardar_ajustes(equipo.leer_ajustes().con_unidad(
    equipo.Unidad(UID, equipo.DAEMON, "U", codigo=agente.huella(raiz) or "")))
F.RAICES[:] = [raiz]
ag = F.nuevo()
F.vueltas(ag, 3)
con = ag.conexiones[UID]


def nombres(proc) -> list[str]:
    """Las parejas que pasa ese `sync.py`: lo que va detrás de `--`."""
    return proc.args[proc.args.index("--") + 1:]


def salida(*partes_, final: str = "") -> str:
    """La salida de un `sync.py` con esas parejas: su cabecera, su línea y su parte."""
    texto = ""
    for p, extra in partes_:
        texto += f"\n=== {p.pareja} (bisync) ===\n{extra}{parte.linea(p)}\n"
    return texto + final


def bien(pareja: str, movio: bool = True) -> tuple:
    return parte.Parte(pareja, 0, movio, 1, 100), f"[{pareja}] OK.\n"


def acabar(texto: str, rc: int = 0) -> None:
    F.acabar(ag.pasada.proc, rc, texto)
    F.vueltas(ag, 1)


c("la primera pasada de la conexión va sola: aún no se sabe si su sync.py escribe partes",
  (nombres(ag.pasada.proc), con.con_partes), (["docs"], False))
acabar("[docs] OK.\n\nHecho. 1/1 parejas OK.\n")
c("  y con un sync.py de antes (sin parte) las siguientes siguen yendo de una en una",
  (nombres(ag.pasada.proc), con.con_partes), (["fotos"], False))
acabar(salida(bien("fotos")))
c("en cuanto una dice cómo le fue con su parte, se sabe que se puede", con.con_partes, True)
c("  (la tercera, que aún no se había pasado, sale ya)", nombres(ag.pasada.proc), ["notas"])
acabar(salida(bien("notas")))

n = len(F.pasadas(raiz))
F.pasar(5 * MIN)
F.vueltas(ag, 2)
c("al tocarles a las tres a la vez, van en UN sync.py",
  (len(F.pasadas(raiz)) - n, sorted(nombres(ag.pasada.proc))), (1, ["docs", "fotos", "notas"]))
c("  el estado dice las tres", ag.resumen()["pasada"]["pareja"].count(","), 2)
c("  y el registro de la pasada en curso las lleva (por si la corta el instalador)",
  sorted(store.read_json(equipo.pasada_json()).get("parejas") or []),
  ["docs", "fotos", "notas"])
antes = consumo.del_dia(UID)
orden = nombres(ag.pasada.proc)
F.pasar(6.0)
duro = F.reloj() - ag.pasada.desde
acabar(salida(bien(orden[0], False), bien(orden[1]), bien(orden[2], False),
              final="\nHecho. 3/3 parejas OK.\n"))
hoy = consumo.del_dia(UID)
c("cada una con lo suyo: tres pasadas apuntadas, dos sin nada que hacer",
  (hoy.pasadas - antes.pasadas, hoy.vacias - antes.vacias), (3, 2))
c("  un proceso de sync.py para las tres, más sus tres rclone",
  hoy.procesos - antes.procesos, 4)
c("  y lo que duró el proceso, una vez", round(hoy.segundos - antes.segundos), round(duro))
c("  la que no movió nada lo lleva en su marca; la que movió, no",
  (ag.marcas[(UID, orden[0])].vacias, ag.marcas[(UID, orden[1])].vacias), (1, 0))

# Una falla, otra se salta, otra va bien: a cada una lo suyo.
F.pasar(5 * MIN)
F.vueltas(ag, 2)
orden = nombres(ag.pasada.proc)
F.AVISOS.clear()
falla = (parte.Parte(orden[0], 3, None, 1, 0),
         f"[{orden[0]}] FALLÓ (código 3). Log: x\n  un error cualquiera\n")
salta =(parte.Parte(orden[1], parte.SALTADA),
         f"[{orden[1]}] Saltada: requiere --resync y no está aprobado.\n")
acabar(salida(falla, salta, bien(orden[2]),
              final="\nHecho. 1/3 parejas OK, 1 saltada(s), 1 con errores.\n"), rc=1)
c("la que falla suma su fallo, con el código de su parte y no el del proceso",
  (ag.marcas[(UID, orden[0])].fallos, any(f"{orden[0]}: FALLÓ (rc=3" in d for d in F.DIARIO)),
  (1, True))
c("  la que se salta queda como saltada, y se avisa de ella",
  (ag.marcas[(UID, orden[1])].saltada, [t for t, _ in F.AVISOS if "--resync" in t]),
  (True, [f"{orden[1]} necesita --resync"]))
c("  y la que va bien, bien: ni fallo ni saltada",
  (ag.marcas[(UID, orden[2])].fallos, ag.marcas[(UID, orden[2])].saltada), (0, False))

# El proceso muere antes de acabar: las que no dejaron parte fallan con su código.
for clave in list(ag.marcas):
    ag.marcas[clave] = pl.Marca(F.reloj() - 5 * MIN - 1, 0)
ag.saltadas.clear()
F.vueltas(ag, 2)
orden = nombres(ag.pasada.proc)
c("(les toca a las tres otra vez)", len(orden), 3)
acabar(salida(bien(orden[0])) + f"\n=== {orden[1]} (bisync) ===\nTraceback: algo se rompió\n", rc=1)
c("si el proceso muere a medias, la que dejó su parte vale y las demás cuentan como fallo",
  [ag.marcas[(UID, n)].fallos for n in orden], [0, 1, 1])

# Una pareja que tarda en mover lo suyo llena la salida de líneas de progreso: el parte de
# la que fue delante no puede perderse por leer solo la cola.
for clave in list(ag.marcas):
    ag.marcas[clave] = pl.Marca(F.reloj() - 5 * MIN - 1, 0)
F.vueltas(ag, 2)
orden = nombres(ag.pasada.proc)
relleno = "  progreso: 1,0 MB de 9,9 GB · 0 % · 1,1 MB/s\n" * (3 * agente.COLA_SALIDA // 40)
larga = (parte.Parte(orden[1], 0, True, 1, 100), relleno + f"[{orden[1]}] OK.\n")
acabar(salida(bien(orden[0], False), larga, bien(orden[2])))
c("con una salida de varias veces la cola, el parte de la primera se lee igual",
  ([ag.marcas[(UID, n)].fallos for n in orden], ag.marcas[(UID, orden[0])].vacias),
  ([0, 0, 0], 1))
for clave in list(ag.marcas):
    ag.marcas[clave] = pl.Marca(F.reloj() - 5 * MIN - 1, 0)
F.vueltas(ag, 2)
orden = nombres(ag.pasada.proc)
F.AVISOS.clear()
acabar(salida(bien(orden[0]), bien(orden[2])))           # falta el parte de la segunda, y rc = 0
c("si falta un parte pero el proceso acabó en 0, a esa pareja no se le apunta un fallo",
  ([ag.marcas[(UID, n)].fallos for n in orden], [t for t, _ in F.AVISOS if "falla" in t]),
  ([0, 0, 0], []))
c("resto: lo que salió detrás del último parte",
  (parte.resto("a\n" + parte.linea(parte.Parte("x", 0)) + "\nb\nc"), parte.resto("a\nb")),
  ("b\nc", "a\nb"))

# Lo que no toca todavía no se arrastra.
for clave in list(ag.marcas):
    ag.marcas[clave] = pl.Marca(F.reloj(), 0)
ag.marcas[(UID, "docs")] = pl.Marca(F.reloj() - 5 * MIN - 1, 0)
F.vueltas(ag, 2)
c("si solo le toca a una, va sola", nombres(ag.pasada.proc), ["docs"])
acabar(salida(bien("docs")))

# «Sincronizar ahora» de dos: juntas, y solo ellas.
equipo.pedir({"pide": equipo.PIDE_PASADA, "id": UID, "parejas": ["fotos", "notas"]})
F.vueltas(ag, 2)
c("«Sincronizar ahora» de dos parejas las pasa juntas, y solo a ellas",
  (sorted(nombres(ag.pasada.proc)), ag.urgentes), (["fotos", "notas"], []))
acabar(salida(bien("fotos"), bien("notas")))

# El tope del lote.
c("un lote tiene tope", agente.LOTE >= 2, True)

# Un fallo de red se le apunta a la pareja que lo dijo, no a las tres.
for clave in list(ag.marcas):
    ag.marcas[clave] = pl.Marca(F.reloj() - 5 * MIN - 1, 0)
F.vueltas(ag, 2)
orden = nombres(ag.pasada.proc)
sin_red = (parte.Parte(orden[1], 1, None, 1, 0),
           f"[{orden[1]}] FALLÓ (código 1). Log: x\n  dial tcp: i/o timeout\n")
acabar(salida(bien(orden[0]), sin_red, bien(orden[2])), rc=1)
c("la que falla por la red deja su remoto sin conexión y no suma un fallo; las otras dos, bien",
  ((UID, "nas") in ag.entorno.sin_conexion, [ag.marcas[(UID, n)].fallos for n in orden],
   ag.marcas[(UID, orden[1])].ultimo_intento), (True, [0, 0, 0], None))

# --- los trozos de la salida
falla = (falla[0], falla[1] + "  dial tcp: i/o timeout\n")
texto = salida(falla, salta, bien("z"), final="\nHecho. 1/3 parejas OK, 1 saltada(s).\n")
t = parte.trozos(texto)
c("trozos: cada pareja con lo suyo, sin el resumen del final",
  ("timeout" in t[falla[0].pareja], "Saltada" in t[salta[0].pareja],
   "Saltada" in t["z"] or "saltada" in t["z"], "Hecho" in "".join(t.values())),
  (True, True, False, False))
c("  de una salida sin partes no sale ninguno", parte.trozos("[docs] OK.\n"), {})

raise SystemExit(c.report())
