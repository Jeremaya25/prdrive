#!/usr/bin/env python3
"""Los frenos de borrado de rclone (`common/frenos.py`) y su hallazgo en el diagnóstico.

Hay dos y no se miden en lo mismo: el de bisync es un PORCENTAJE del listado
anterior y el de `up-mirror`/`down-mirror` una CUENTA de ficheros (AGENTS.md,
«Safety invariants»). Los logs con los que se prueba son los de verdad
(`tests/_logs_frenos.py`, rclone v1.75.2 lanzado por `sync.run_pair()`), no
frases escritas a mano: lo que rclone dice es justo lo que se reconoce.
"""

import contextlib
import io
import sys
from pathlib import Path

from _harness import Checks, mkcfg, sandbox
from _logs_frenos import (BISYNC_BORRADOS, BISYNC_CAMBIADOS, ESPEJO_DOWN, ESPEJO_UP,
                          SIMULACION_BISYNC, SIMULACION_BISYNC_VERSIONES, SIMULACION_ESPEJO)

import sync
from common import frenos, model, results, revision

c = Checks("los frenos de borrado")

BISYNC = {"name": "notas", "local": "sync-data/notas", "remote_path": "/R/notas"}
SUBIDA = {"name": "espejo", "mode": "up-mirror", "local": "sync-data/espejo",
          "remote_path": "/R/espejo"}
BAJADA = {"name": "bajada", "mode": "down-mirror", "local": "sync-data/bajada",
          "remote_path": "/R/bajada"}
COPIA = {"name": "copia", "mode": "up", "local": "sync-data/copia", "remote_path": "/R/copia"}


def parejas():
    """Devuelve `{nombre: pareja}` con una de cada modo que importa."""
    cfg = mkcfg(None, pairs=[BISYNC, SUBIDA, BAJADA, COPIA])
    return cfg, {p.name: p for p in cfg.pairs}


cfg0, P = parejas()

# ---- Qué dice rclone, reconocido en su log -------------------------------------------

c("bisync: demasiados borrados, con cifras y lado (el dispositivo es Path1)",
  frenos.detectar(BISYNC_BORRADOS, P["notas"]),
  frenos.Freno(frenos.BORRADOS, lados=("local",), borrados=8, total=10, tope=25))
c("  y el porcentaje es el de lo borrado, no el del tope",
  frenos.detectar(BISYNC_BORRADOS, P["notas"]).porcentaje, 80)

en_remoto = BISYNC_BORRADOS.replace('on Path1 "', 'on Path2 "')
c("  si es Path2, el lado es el remoto",
  frenos.detectar(en_remoto, P["notas"]).lados, ("remote",))

# Un dispositivo Windows: rclone cita la ruta con `%q` de Go, que dobla las barras.
windows = ('2026/09/11 12:45:32 ERROR : Safety abort: too many deletes (>25%, 4 of 8) on '
           'Path1 "E:\\\\sync-data\\\\notas\\\\". Run with --force if desired.\n'
           '2026/09/11 12:45:32 NOTICE: Failed to bisync: too many deletes\n')
c("  la ruta de Windows, con las barras dobladas, no estorba",
  frenos.detectar(windows, P["notas"]),
  frenos.Freno(frenos.BORRADOS, lados=("local",), borrados=4, total=8, tope=25))

solo_la_causa = "2026/10/15 09:35:35 NOTICE: Failed to bisync: too many deletes\n"
c("  si rclone cambia la frase pero sigue diciendo por qué falla, se reconoce sin cifras",
  frenos.detectar(solo_la_causa, P["notas"]),
  frenos.Freno(frenos.BORRADOS))

c("bisync: todos los ficheros de un lado han cambiado",
  frenos.detectar(BISYNC_CAMBIADOS, P["notas"]),
  frenos.Freno(frenos.CAMBIADOS, lados=("local",)))
en_los_dos = BISYNC_CAMBIADOS.replace(
    "Run with --force if desired.\n",
    'Run with --force if desired.\n2026/10/15 09:35:36 ERROR : Safety abort: all files were '
    'changed on Path2 "nas:/R/notas/". Run with --force if desired.\n', 1)
c("  y puede ser en los dos",
  frenos.detectar(en_los_dos, P["notas"]).lados, ("local", "remote"))

c("espejo hacia el remoto: borró hasta el tope y paró; el destino es el remoto",
  frenos.detectar(ESPEJO_UP, P["espejo"]),
  frenos.Freno(frenos.ESPEJO, lados=("remote",), borrados=50, pendientes=5))
c("espejo hacia el dispositivo: el destino es el dispositivo",
  frenos.detectar(ESPEJO_DOWN, P["bajada"]),
  frenos.Freno(frenos.ESPEJO, lados=("local",), borrados=50, pendientes=5))
c("  el espejo no tiene porcentaje: su freno es una cuenta",
  frenos.detectar(ESPEJO_UP, P["espejo"]).porcentaje, None)

# ---- Cada freno es de su modo -------------------------------------------------------------

c("un log de bisync no es el freno de un espejo",
  frenos.detectar(BISYNC_BORRADOS, P["espejo"]), None)
c("  ni el de un copy, que no borra",
  frenos.detectar(BISYNC_BORRADOS, P["copia"]), None)
c("el log de un espejo no es el freno de un bisync",
  frenos.detectar(ESPEJO_UP, P["notas"]), None)
c("  ni el de un copy",
  frenos.detectar(ESPEJO_UP, P["copia"]), None)

# `--max-delete-size` es otro freno (bytes) y forzar `--max-delete` no lo quita: no se
# confunde con la cuenta, que es lo que hacía la aguja `--max-delete` a secas.
por_tamano = ESPEJO_UP.replace("--max-delete threshold reached",
                               "--max-delete-size threshold reached")
c("el freno por TAMAÑO de un espejo no es el de la cuenta",
  frenos.detectar(por_tamano, P["espejo"]), None)
c("  la aguja de la cuenta no casa con él",
  (frenos.es_espejo(por_tamano), frenos.es_espejo(ESPEJO_UP)), (False, True))
ayuda = ("Usage:\n  rclone sync source:path dest:path [flags]\nFlags:\n      "
         "--max-delete int   When synchronizing, limit the number of deletes (default -1)\n")
c("  y la ayuda de rclone, que nombra el flag, tampoco", frenos.es_espejo(ayuda), False)
c("un fallo cualquiera no es un freno",
  frenos.detectar("2026/10/15 ERROR : Failed to create file system for \"nas:\"\n",
                  P["notas"]), None)

c("las agujas, una por freno",
  [(f(BISYNC_BORRADOS), f(BISYNC_CAMBIADOS), f(ESPEJO_UP))
   for f in (frenos.es_borrados_bisync, frenos.es_cambiados_bisync, frenos.es_espejo)],
  [(True, False, False), (False, True, False), (False, False, True)])

# ---- Qué borraría una simulación -----------------------------------------------------------

c("una simulación forzada de un espejo dice qué ficheros borraría: los cinco que le faltaban",
  frenos.borrarian(SIMULACION_ESPEJO),
  ["nota07.md", "nota09.md", "nota24.md", "nota39.md", "nota41.md"])
c("  y los de bisync, los ocho que el dispositivo había borrado, en orden",
  frenos.borrarian(SIMULACION_BISYNC), [f"nota{n:02d}.md" for n in range(1, 9)])
c("  con versiones, lo que va a .prversions/ también es un borrado, y lo que solo se sobrescribe no",
  frenos.borrarian(SIMULACION_BISYNC_VERSIONES), [f"nota{n:02d}.md" for n in range(1, 9)])
c("  un log que no es de una simulación no borra nada", frenos.borrarian(ESPEJO_UP), [])
c("  y uno vacío tampoco", frenos.borrarian(""), [])
con_repetidos = SIMULACION_ESPEJO + SIMULACION_ESPEJO
c("  un fichero que sale dos veces cuenta una",
  len(frenos.borrarian(con_repetidos)), 5)
c("  un nombre con dos puntos y espacios se entiende entero",
  frenos.borrarian("2026/10/15 09:44:06 NOTICE: a: b/c d.md: Skipped delete as --dry-run is "
                   "set (size 3)\n"), ["a: b/c d.md"])

# ---- Un log más grande que lo que se lee --------------------------------------------------

with sandbox():
    # Al pintar «Reparación» solo se lee el final del log (`TOPE_LECTURA`): lo que sale de TODO
    # el log, como cuántos ficheros borró un espejo, no se puede decir si no se leyó entero.
    grande = model.LOG_DIR / "espejo_grande.log"
    cola = "".join(ESPEJO_UP.splitlines(keepends=True)[-6:])
    grande.write_text("".join(f"2026/10/15 09:35:36 INFO  : f{i:06d}.md: Deleted\n"
                              for i in range(100_000)) + cola, encoding="utf-8")
    c("el log de prueba pasa del tope de lectura", grande.stat().st_size > frenos.TOPE_LECTURA, True)
    c("leer() da solo el final", len(frenos.leer(grande)) <= frenos.TOPE_LECTURA, True)
    c("  y completo=True, todo", frenos.leer(grande, completo=True).count(": Deleted"), 100_000)
    visto = frenos.detectar_en(grande, P["espejo"])
    c("detectar_en() reconoce el freno por lo que dice el final: lo que faltaba por borrar",
      (visto.tipo, visto.pendientes), (frenos.ESPEJO, 5))
    c("  pero no dice cuántos borró, que cuenta todo el log y no se leyó entero", visto.borrados, None)
    chico = model.LOG_DIR / "espejo_chico.log"
    chico.write_text(ESPEJO_UP, encoding="utf-8")
    c("  con un log que se lee entero, sí", frenos.detectar_en(chico, P["espejo"]).borrados, 50)

# ---- Lo que sale por la consola (KNOWN_ERRORS) --------------------------------------------


def explicar(texto):
    """Devuelve lo que `sync.explain_failure()` dice de un log con ese texto."""
    with sandbox():
        log = sync.temp_log("explicar")
        log.write_text(texto, encoding="utf-8")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            sync.explain_failure(log)
        log.unlink(missing_ok=True)
        return buf.getvalue()


borrados, cambiados, espejo = (explicar(BISYNC_BORRADOS), explicar(BISYNC_CAMBIADOS),
                               explicar(ESPEJO_UP))
c("la consola explica el freno de bisync en porcentaje, sin hablar de cuentas",
  ("porcentaje" in borrados, "cuenta" in borrados), (True, False))
c("  y dice cómo forzar una pasada",
  ("--force" in borrados, "Reparación" in borrados), (True, True))
c("la consola explica el freno del espejo como una cuenta, sin porcentajes",
  ("cuenta de ficheros" in espejo, "%" in espejo, "porcentaje" in espejo), (True, False, False))
c.contains("  y dice cómo forzar una pasada", espejo, "--force")
c.contains("la consola explica el 'todos han cambiado', que antes no tenía explicación",
           cambiados, "todos los ficheros")
c("el freno por tamaño ya no se explica como una cuenta de ficheros",
  "cuenta de ficheros" in explicar(por_tamano), False)

# ---- El hallazgo de «Reparación» y de --doctor --------------------------------------------


def fallar(nombre, texto, codigo=1):
    """Apunta que la última pasada de `nombre` falló y deja su log donde lo guarda `sync.py`."""
    log = model.LOG_DIR / f"{nombre}_20261015_093535.log"
    if texto is not None:
        log.write_text(texto, encoding="utf-8")
    results.apuntar(nombre, codigo, log if texto is not None else None)
    return log


def de(hallazgos, nombre):
    """Devuelve `{clave: hallazgo}` de esa pareja, sin los que no son suyos."""
    return {h.clave: h for h in hallazgos if h.pareja == nombre}


with sandbox():
    cfg, P = parejas()
    log = fallar("notas", BISYNC_BORRADOS)
    hallazgos = revision.revisar(cfg)
    suyos = de(hallazgos, "notas")
    c("el freno es su propio hallazgo y sustituye al fallo genérico de esa pareja",
      ("freno" in suyos, "fallo" in suyos), (True, False))
    h = suyos["freno"]
    c("  es un aviso (hay que hacer algo, pero nada corre peligro)", h.gravedad, revision.AVISO)
    c.contains("  el título nombra la pareja y el freno", h.titulo, "«notas»")
    c.contains("  y dice qué ha pasado, con cifras, porcentaje y lado",
               h.detalle, "8 de 10 ficheros (80 %) en el dispositivo")
    c.contains("  cuánto es el tope, en la misma unidad", h.detalle, "25 %")
    c.contains("  y qué evitó", h.detalle, "no copiar ese borrado al remoto")
    c("  sin mezclar unidades: ni cuentas ni --max-delete a secas",
      ("cuenta" in h.detalle, "--max-delete" in h.detalle), (False, False))
    c("  el dato lleva el log y el freno que lo explica", h.dato, (log, frenos.detectar(
        BISYNC_BORRADOS, P["notas"])))

    texto = "\n".join(revision.informe(cfg))
    c.contains("--doctor lo dice igual, con las mismas cifras", texto,
               "8 de 10 ficheros (80 %) en el dispositivo")

    results.apuntar("notas", 0, None)
    c("cuando la pasada siguiente va bien, el hallazgo se va",
      "freno" in de(revision.revisar(cfg), "notas"), False)

with sandbox():
    # El nombre de una pareja puede llevar espacios: la orden que se sugiere tiene que valer.
    cfg = mkcfg(None, pairs=[dict(BISYNC, name="Mis fotos"), dict(BISYNC, name="notas-2")])
    fallar("Mis fotos", BISYNC_BORRADOS)
    fallar("notas-2", BISYNC_BORRADOS)
    suyos = {h.pareja: h.detalle for h in revision.revisar(cfg) if h.clave == "freno"}
    c.contains("un nombre con espacios va entre comillas en la orden sugerida",
               suyos["Mis fotos"], '`python sync.py "Mis fotos" --force`')
    c.contains("  y uno sin ellos, tal cual", suyos["notas-2"], "`python sync.py notas-2 --force`")

with sandbox():
    # Un nombre que un intérprete de órdenes interpreta no se pega: ni `$`, ni el acento grave,
    # ni `%` (que `cmd` expande aun entre comillas), ni `!`, ni una comilla que cierre las del
    # nombre. El parser los acepta (solo la ventana prohíbe `"`), y el nombre puede llegar de un
    # TOML editado o del catálogo del remoto. Un solo log para todas: el nombre de la pareja
    # no tiene por qué valer como nombre de fichero (`"` en Windows).
    peligrosos = ["Fotos $HOME", "a$(id)", "x`id`", "50%PATH%", "hola!", 'a"b', 'x" & calc & "']
    seguros = ["Mis fotos", "notas-2", "Año_2026.v2", "a+b, c=d@e"]
    cfg = mkcfg(None, pairs=[dict(BISYNC, name=n) for n in peligrosos + seguros])
    log = model.LOG_DIR / "nombres_raros.log"
    log.write_text(BISYNC_BORRADOS, encoding="utf-8")
    for n in peligrosos + seguros:
        results.apuntar(n, 1, log)
    freno = {h.pareja: h for h in revision.revisar(cfg) if h.clave == "freno"}
    informe = "\n".join(revision.informe(cfg))
    c("todas las parejas de nombre raro tienen su hallazgo de freno",
      sorted(freno), sorted(peligrosos + seguros))
    for n in peligrosos:
        d = freno[n].detalle
        c(f"{n!r}: no hay orden literal, ni con su nombre ni entre comillas",
          (d.count("python sync.py "), "python sync.py <pareja> --force" in d,
           f"sync.py {n}" in d, f'sync.py "{n}"' in d), (1, True, False, False))
        c.contains("  y se puede forzar desde «Reparación»", d, "desde «Reparación»")
        c("  --doctor tampoco la da",
          (f"sync.py {n} --force" in informe, f'sync.py "{n}" --force' in informe), (False, False))
    for n, orden in (("Mis fotos", '`python sync.py "Mis fotos" --force`'),
                     ("notas-2", "`python sync.py notas-2 --force`"),
                     ("Año_2026.v2", "`python sync.py Año_2026.v2 --force`"),
                     ("a+b, c=d@e", '`python sync.py "a+b, c=d@e" --force`')):
        c.contains(f"{n!r}: conserva la orden literal", freno[n].detalle, orden)
        c("  y no remite a «<pareja>»", "<pareja>" in freno[n].detalle, False)

with sandbox():
    cfg, P = parejas()
    fallar("notas", BISYNC_BORRADOS.replace('on Path1 "', 'on Path2 "'))
    c.contains("un borrado en el remoto se dice del remoto y se cuida el dispositivo",
               de(revision.revisar(cfg), "notas")["freno"].detalle,
               "en el remoto")
    c.contains("  y qué evitó", de(revision.revisar(cfg), "notas")["freno"].detalle,
               "no copiar ese borrado al dispositivo")

with sandbox():
    cfg, P = parejas()
    fallar("notas", BISYNC_CAMBIADOS)
    h = de(revision.revisar(cfg), "notas")["freno"]
    c.contains("todos cambiados: lo dice con esas palabras", h.detalle,
               "han cambiado todos los ficheros")
    c("  y no habla de borrados", "borrad" in h.detalle, False)

with sandbox():
    cfg, P = parejas()
    fallar("espejo", ESPEJO_UP, 7)
    fallar("bajada", ESPEJO_DOWN, 7)
    hallazgos = revision.revisar(cfg)
    arriba, abajo = de(hallazgos, "espejo"), de(hallazgos, "bajada")
    c("espejo: también es un hallazgo propio, no un fallo",
      ("freno" in arriba, "fallo" in arriba), (True, False))
    d = arriba["freno"].detalle
    c.contains("  dice cuántos borró y que el freno es una cuenta de ficheros", d,
               "borrado 50 ficheros en el remoto")
    c.contains("  y cuántos quedan", d, "faltan 5")
    c("  sin una sola unidad de porcentaje", "%" in d, False)
    c.contains("  hacia el dispositivo, el destino es el dispositivo",
               abajo["freno"].detalle, "borrado 50 ficheros en el dispositivo")

with sandbox():
    cfg, P = parejas()
    fallar("espejo", "".join(f"2026/10/15 09:35:36 INFO  : f{i:06d}.md: Deleted\n"
                             for i in range(100_000)) + "".join(ESPEJO_UP.splitlines(keepends=True)[-6:]), 7)
    d = de(revision.revisar(cfg), "espejo")["freno"].detalle
    c("el hallazgo de un espejo con un log enorme no afirma un número de borrados que no sabe",
      ("Ya ha borrado" in d, "faltan 5 por borrar" in d), (False, True))

with sandbox():
    cfg, P = parejas()
    fallar("notas", "2026/10/15 ERROR : Failed to create file system for \"nas:\"\n")
    fallar("espejo", por_tamano, 7)
    fallar("bajada", None, 7)
    fallar("copia", BISYNC_BORRADOS, 1)
    hallazgos = revision.revisar(cfg)
    def fallo_sin_freno(nombre):
        """Devuelve si esa pareja tiene un `fallo` y no tiene un `freno`."""
        suyos = de(hallazgos, nombre)
        return ("fallo" in suyos, "freno" in suyos)

    c("un fallo que no es un freno sigue siendo un fallo",
      fallo_sin_freno("notas"), (True, False))
    c("  el del freno por tamaño también, que forzar la cuenta no lo quita",
      fallo_sin_freno("espejo"), (True, False))
    c("  y el que no dejó log, que no hay nada que reconocer",
      fallo_sin_freno("bajada"), (True, False))
    c("  y un log de bisync en una pareja que no es bisync",
      fallo_sin_freno("copia"), (True, False))

sys.exit(c.report())
