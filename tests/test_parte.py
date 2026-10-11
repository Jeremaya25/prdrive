#!/usr/bin/env python3
"""El parte de una pareja (`common/parte.py`) y la cuenta de lo gastado (`common/consumo.py`).

La línea que `sync.py` escribe para el agente, lo que el agente lee de ella, cómo
se sabe que una pasada bisync no movió nada (sus listados, sin la primera línea)
y cómo se suma lo gastado por días en la carpeta del equipo.
"""

from pathlib import Path

from _harness import Checks, mkcfg, sandbox, tmpdir

from common import bisync, consumo, equipo, parte, store

c = Checks("parte de una pareja y consumo")

# --- la línea
p = parte.Parte("docs", 0, False, 1, 2048)
c("la línea empieza por la marca", parte.linea(p).startswith(parte.MARCA), True)
c("  y va y vuelve", parte.leer(parte.linea(p)), {"docs": p})
c("  entre lo que lee una persona",
  parte.leer("\n=== docs (bisync) ===\n[docs] OK.\n" + parte.linea(p) + "\n\nHecho. 1/1 parejas OK.\n"),
  {"docs": p})
c("una pareja con tildes y espacios", parte.leer(parte.linea(parte.Parte("mis fotos é", 0, True))),
  {"mis fotos é": parte.Parte("mis fotos é", 0, True)})
c("sin saber si movió, `None`", parte.leer(parte.linea(parte.Parte("a", 0, None)))["a"].movio, None)
c("la línea de una saltada no dice «saltada» (el agente busca esa palabra)",
  "saltada" in parte.linea(parte.Parte("a", -1)).lower(), False)
c("varias parejas en una salida",
  sorted(parte.leer(parte.linea(parte.Parte("a", 0, False)) + "\n" + parte.linea(parte.Parte("b", 1)))),
  ["a", "b"])
c("la salida de un sync.py de antes no lleva ninguno", parte.leer("[docs] OK.\n\nHecho.\n"), {})
c("lo que no se entiende se ignora",
  parte.leer(parte.MARCA + "{roto\n" + parte.MARCA + '{"rc": 0}\n' + parte.MARCA + '[1, 2]\n'
             + parte.MARCA + '{"pareja": "a", "rc": "x"}\n'), {})
c("un `movio` que no es un booleano es «no se sabe»",
  parte.leer(parte.MARCA + '{"pareja": "a", "rc": 0, "movio": "no"}')["a"].movio, None)
c("vacía: fue bien y se sabe que no movió nada",
  [parte.Parte("a", 0, False).vacia, parte.Parte("a", 0, True).vacia,
   parte.Parte("a", 0, None).vacia, parte.Parte("a", 1, False).vacia], [True, False, False, False])

# --- los listados de una pareja bisync
with sandbox():
    par = mkcfg(["docs"]).pairs[0]
    pre = bisync.expected_prefix(par)
    par.workdir.mkdir(parents=True, exist_ok=True)
    l1, l2 = par.workdir / (pre + bisync.PATH1_SUFFIX), par.workdir / (pre + bisync.PATH2_SUFFIX)

    def listados(fecha: str, cuerpo: str = "- 10 - - 2026-01-01T00:00:00 \"a.txt\"\n") -> None:
        """Deja los dos listados como los deja rclone: una cabecera con la fecha y el cuerpo."""
        for ruta in (l1, l2):
            ruta.write_text(f"# bisync listing v1 from: {fecha}\n{cuerpo}", encoding="utf-8")

    c("sin base no hay foto", parte.base(par), {})
    listados("2026-10-11T10:00:00")
    c("la foto lleva los dos listados", sorted(parte.base(par)), sorted([l1.name, l2.name]))
    (par.workdir / "otra-cosa.lst").write_text("x", encoding="utf-8")
    c("  y nada que no lleve su prefijo", len(parte.base(par)), 2)

    m = parte.Medida(par, 3)
    listados("2026-10-11T10:05:00")
    dicho = m.acabar(0, 4)
    c("reescritos con otra fecha y el mismo cuerpo: no movió nada", dicho.movio, False)
    c("  una orden de rclone", dicho.ordenes, 1)
    c("  y lo reescrito son los dos listados enteros", dicho.escrito,
      l1.stat().st_size + l2.stat().st_size)

    m = parte.Medida(par, 0)
    listados("2026-10-11T10:10:00", "- 11 - - 2026-10-11T10:09:00 \"a.txt\"\n")
    c("con otro cuerpo: movió", m.acabar(0, 1).movio, True)

    m = parte.Medida(par, 0)
    c("sin tocar nada no se reescribe nada", m.acabar(0, 0).escrito, 0)

    m = parte.Medida(par, 0)
    m.resync = True
    listados("2026-10-11T10:15:00", "- 11 - - 2026-10-11T10:09:00 \"a.txt\"\n")
    c("un --resync siempre mueve", m.acabar(0, 1).movio, True)

    m = parte.Medida(par, 0)
    listados("2026-10-11T10:20:00", "- 11 - - 2026-10-11T10:09:00 \"a.txt\"\n")
    c("una pasada que falla no dice si había algo", m.acabar(1, 1).movio, None)
    c("  ni una que se salta", parte.Medida(par, 0).acabar(-1, 0).movio, None)

    m = parte.Medida(par, 0)
    l2.unlink()
    c("si al acabar falta un listado, no se da por quieta", m.acabar(0, 1).movio, True)

    m = parte.Medida(par, 0, medir=False)
    c("un simulacro no mide", (m.antes, m.acabar(0, 1).movio), (None, None))

    # una pareja que no es bisync: lo que diga su log
    sube = mkcfg(["fotos"], pairs=[{"name": "fotos", "local": "sync-data/fotos",
                                    "remote_path": "/R/fotos", "mode": "up"}]).pairs[0]
    m = parte.Medida(sube, 0)
    c("una pareja `up` no tiene listados", m.antes, None)
    c("  sin log no se sabe", m.acabar(0, 1).movio, None)
    m.quieta = True
    c("  si el log dice que no había nada, no movió", m.acabar(0, 1).movio, False)
    m.quieta = False
    c("  y si hizo algo, movió", m.acabar(0, 1).movio, True)

# --- el log de un copy o un sync
d = tmpdir()


def log(texto: str) -> Path:
    ruta = d / "x.log"
    ruta.write_text(texto, encoding="utf-8")
    return ruta


NADA = "2026/10/11 10:00:00 INFO  : There was nothing to transfer\n"
c("sin log no se sabe", parte.sin_actividad(None), None)
c("un log que no está", parte.sin_actividad(d / "no-esta.log"), None)
c("«nada que transferir» y nada más: quieta", parte.sin_actividad(log(NADA)), True)
c("con un fichero copiado, no",
  parte.sin_actividad(log("2026/10/11 10:00:00 INFO  : a.txt: Copied (new)\n")), False)
c("un borrado tampoco (un espejo borra sin transferir)",
  parte.sin_actividad(log("2026/10/11 10:00:00 INFO  : a.txt: Deleted\n" + NADA)), False)
c("ni una carpeta creada",
  parte.sin_actividad(log("2026/10/11 10:00:00 INFO  : sub: Made directory\n" + NADA)), False)
c("sin ninguna de las dos cosas no se sabe", parte.sin_actividad(log("otra cosa\n")), None)
c("un log enorme no se lee", parte.sin_actividad(log(NADA + "x" * parte.TOPE_LOG)), None)

# --- lo gastado, por días
equipo.DIR = tmpdir("prdrive-equipo-")
c("sin fichero no hay cuentas", consumo.leer(), {})
c("  y lo de hoy es cero", consumo.del_dia("u1"), consumo.Cuenta())
consumo.apuntar("u1", consumo.Cuenta(1, 1, 2, 0.7, 30000), dia="2026-10-11")
consumo.apuntar("u1", consumo.Cuenta(1, 0, 3, 1.5, 0), dia="2026-10-11")
consumo.apuntar("u2", consumo.Cuenta(1, 0, 1, 0.2, 0), dia="2026-10-11")
c("se suma por unidad y día", consumo.del_dia("u1", "2026-10-11"),
  consumo.Cuenta(2, 1, 5, 2.2, 30000))
c("  cada unidad lo suyo", consumo.del_dia("u2", "2026-10-11").pasadas, 1)
c("  otro día, nada", consumo.del_dia("u1", "2026-10-12"), consumo.Cuenta())
for i in range(1, consumo.DIAS + 3):
    consumo.apuntar("u1", consumo.Cuenta(1, 0, 1, 0.1, 0), dia=f"2026-11-{i:02d}")
c("solo se guardan los últimos días", len(consumo.leer()), consumo.DIAS)
c("  los más nuevos", "2026-10-11" in consumo.leer(), False)
store.write_json(equipo.DIR / consumo.FICHERO, {"dias": {"2026-10-11": {"u1": {"pasadas": "x", "vacias": -3}}}})
c("un fichero con basura no rompe nada", consumo.del_dia("u1", "2026-10-11"), consumo.Cuenta())
(equipo.DIR / consumo.FICHERO).write_text("{roto", encoding="utf-8")
c("ni uno roto", consumo.leer(), {})
c("el texto de un día", consumo.texto(consumo.Cuenta(212, 198, 424, 131.4, 43 * 1024 * 1024)),
  "212 pasadas (198 sin nada que hacer), 424 procesos, 131 s, 43,0 MB reescritos en la unidad")
c("  de una sola pasada, sin escrituras", consumo.texto(consumo.Cuenta(1, 0, 2, 3.0, 0)),
  "1 pasada, 2 procesos, 3 s")
c("  y de ninguna", consumo.texto(consumo.Cuenta()), "ninguna pasada")

raise SystemExit(c.report())
