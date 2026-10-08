#!/usr/bin/env python3
"""El diagnóstico compartido (`common/revision.py`).

Es la lista de averías que imprime `sync.py --doctor` y que dibuja la pantalla
de «Reparación», y es UNA: si aquí se deja de ver algo, deja de verse en los
dos sitios a la vez. Por eso lo que se comprueba es qué se detecta y con qué
gravedad, no cómo queda escrito.
"""

import contextlib
import hashlib
import io
import shutil
import sys
from datetime import datetime
from pathlib import Path

from _harness import Checks, mkcfg, sandbox

import sync
import ui
import ui.console
from common import bisync, conflicts, historial, model, results, revision

c = Checks("el diagnóstico compartido")


def claves(hallazgos):
    """Devuelve las claves de los hallazgos, ordenadas y sin repetir."""
    return sorted({h.clave for h in hallazgos})


def uno(hallazgos, clave):
    """Devuelve el hallazgo con esa clave, o `None`."""
    return next((h for h in hallazgos if h.clave == clave), None)


def listados(pair, prefijo=None):
    """Deja un baseline en disco, como lo deja un `--resync`.

    Son los dos listados y el md5 de los filtros. Sin el md5 la pareja pide
    resync con razón, que es precisamente una de las averías de más abajo.
    """
    prefijo = prefijo or bisync.expected_prefix(pair)
    pair.workdir.mkdir(parents=True, exist_ok=True)
    for sufijo in (bisync.PATH1_SUFFIX, bisync.PATH2_SUFFIX):
        (pair.workdir / f"{prefijo}{sufijo}").write_text("listado\n", encoding="utf-8")
    ffile = bisync.filters_file_for(pair)
    if ffile is not None:
        Path(str(ffile) + ".md5").write_text(
            hashlib.md5(ffile.read_bytes()).hexdigest(), encoding="utf-8")


with sandbox():
    cfg = mkcfg(["notas"])
    pair = cfg.pairs[0]

    # Una pareja recién configurada: la carpeta no está y no hay baseline. Ni
    # una cosa ni la otra son una avería grave —la carpeta la crea la primera
    # pasada—, pero el resync sí hay que hacerlo.
    hallazgos = revision.revisar(cfg)
    c("una pareja nueva: falta la carpeta y falta el resync",
      claves(hallazgos), ["local", "resync"])
    c("que no haya carpeta todavía es solo una nota",
      uno(hallazgos, "local").gravedad, revision.NOTA)
    c("y el resync, un aviso", uno(hallazgos, "resync").gravedad, revision.AVISO)
    c("las notas no entran en la cuenta de la ventana", revision.cuenta(hallazgos), 1)

    pair.local_abs.mkdir(parents=True, exist_ok=True)
    listados(pair)
    c("con carpeta y baseline al día, no hay nada que revisar",
      revision.revisar(cfg), [])

with sandbox():
    cfg = mkcfg(["notas"])
    pair = cfg.pairs[0]
    pair.local_abs.mkdir(parents=True, exist_ok=True)
    listados(pair)

    # La carpeta local desaparece CON baseline: esto es lo grave, y es lo único
    # de la lista que no se repara desde el programa.
    shutil.rmtree(pair.local_abs)
    hallazgos = revision.revisar(cfg)
    c("sin carpeta local pero con baseline, es grave",
      uno(hallazgos, "local").gravedad, revision.GRAVE)
    c.contains("y se dice que no se arregla creándola",
               uno(hallazgos, "local").detalle, "no lo arregles")

with sandbox():
    cfg = mkcfg(["notas"])
    pair = cfg.pairs[0]
    pair.local_abs.mkdir(parents=True, exist_ok=True)
    listados(pair, "otro-destino-cualquiera")
    hallazgos = revision.revisar(cfg)
    c("un baseline con otro prefijo se detecta", uno(hallazgos, "prefijo") is not None, True)
    c("y es grave", uno(hallazgos, "prefijo").gravedad, revision.GRAVE)
    c("lo más grave va primero", hallazgos[0].clave, "prefijo")

with sandbox():
    cfg = mkcfg(["notas"])
    pair = cfg.pairs[0]
    pair.local_abs.mkdir(parents=True, exist_ok=True)
    listados(pair)
    (pair.workdir / "algo.lck").write_text("", encoding="utf-8")
    hallazgos = revision.revisar(cfg)
    c("un lock suelto se detecta", uno(hallazgos, "lock") is not None, True)
    c("y se lleva su ruta puesta, para no recorrer el disco dos veces",
      uno(hallazgos, "lock").dato, (pair.workdir / "algo.lck",))

with sandbox():
    cfg = mkcfg(["notas"])
    pair = cfg.pairs[0]
    pair.local_abs.mkdir(parents=True, exist_ok=True)
    listados(pair)

    # Conflictos y fallos: los dos salen de lo que ya está apuntado en state/,
    # sin recorrer nada, porque esto lo llama la ventana mientras se pinta.
    conflicts.ruta_estado().write_text(
        '{"parejas": {"notas": ["sync-data/notas/a.conflicto-remoto1"]}}',
        encoding="utf-8")
    (pair.local_abs / "a.conflicto-remoto1").write_text("x", encoding="utf-8")
    results.apuntar("notas", 1, None)

    hallazgos = revision.revisar(cfg)
    c("los conflictos son una avería más", uno(hallazgos, "conflicto") is not None, True)
    c("y la última pasada fallida también", uno(hallazgos, "fallo") is not None, True)
    c("las dos cuentan para la ventana", revision.cuenta(hallazgos), 2)

    (model.STATE_DIR / "viejo.lst").write_text("", encoding="utf-8")
    hallazgos = revision.revisar(cfg)
    c("los listados del reparto antiguo se ven", uno(hallazgos, "listados") is not None, True)
    c("pero son una nota: se reparten solos",
      uno(hallazgos, "listados").gravedad, revision.NOTA)

    # El informe es el mismo diagnóstico en texto: lo que imprime --doctor.
    texto = "\n".join(revision.informe(cfg))
    c.contains("el informe dice dónde está el dispositivo", texto, str(model.DEVICE_ROOT))
    c.contains("enseña la pareja", texto, "[notas]")
    c.contains("y acaba con las averías", texto, "cosa(s) que revisar")
    c.contains("con el fallo dentro", texto, "la última pasada falló")

with sandbox():
    cfg = mkcfg(["notas"])
    cfg.pairs[0].local_abs.mkdir(parents=True, exist_ok=True)
    listados(cfg.pairs[0])
    c.contains("sin averías, el informe lo dice",
               "\n".join(revision.informe(cfg)), "Sin incidencias.")


# Los `.lst-err` que deja una pasada abortada (H3, #41). No los borra nadie: ni
# rclone ni nosotros. Lo que se hace es decir qué son, sin llamarlos «residuales»
# a secas, y no tocarlos.
with sandbox():
    cfg = mkcfg(["notas"])
    pair = cfg.pairs[0]
    pair.local_abs.mkdir(parents=True, exist_ok=True)
    listados(pair)
    prefijo = bisync.expected_prefix(pair)
    errores = [pair.workdir / f"{prefijo}{suf}-err" for suf in (".path1.lst", ".path2.lst")]
    for e in errores:
        e.write_text("listado de la pasada abortada\n", encoding="utf-8")
    estado = bisync.pair_state(pair)
    c("con un baseline bueno y `.lst-err` detrás, el baseline vale",
      (estado.status, estado.prefix), ("ok", prefijo))
    c.contains("el estado cuenta cuántos son", estado.detail, "+2 .lst-err")
    c.contains("dice qué son: el baseline que rclone apartó al abortar", estado.detail,
               "el baseline que rclone apartó al abortar una pasada")
    c.contains("que ya no lo usa y se puede borrar a mano", estado.detail,
               "ya no lo usa y se puede borrar a mano")
    c("sin la palabra que no explicaba nada", "residuales" in estado.detail, False)
    c("no es una avería: no sale en «Reparación»", uno(revision.revisar(cfg), "listados"),
      None)
    c("y lo dice también el informe de `--doctor`",
      "se puede borrar a mano" in "\n".join(revision.informe(cfg)), True)
    c("nada se borra: los `.lst-err` siguen donde estaban",
      all(e.is_file() for e in errores), True)

with sandbox():
    cfg = mkcfg(["notas"])
    pair = cfg.pairs[0]
    pair.workdir.mkdir(parents=True, exist_ok=True)
    errores = [pair.workdir / f"{bisync.expected_prefix(pair)}{suf}-err"
               for suf in (".path1.lst", ".path2.lst")]
    for e in errores:
        e.write_text("x\n", encoding="utf-8")
    estado = bisync.pair_state(pair)
    c("solo `.lst-err`, sin listados buenos: baseline roto", estado.status, "broken")
    c.contains("y dice por qué están así: rclone aparta el baseline al abortar",
               estado.detail, "rclone aparta así el baseline")
    c.contains("para que no empiece otra pasada", estado.detail, "bloquear las siguientes")
    c("sigue pidiendo --resync, que es lo que lo arregla",
      any("--resync" in h.titulo for h in revision.revisar(cfg)), True)
    c("y tampoco aquí se borra nada", all(e.is_file() for e in errores), True)


# desde cuándo falla: el diario de pasadas
#
# El fallo dice desde cuándo y cuántas de las últimas fueron bien. La frase
# sale de common/historial.py y llega a la pantalla y a --doctor desde aquí.
ANO = datetime.now().year


def diario(pareja, codigos, dia=1, ano=ANO):
    """Apunta una pasada por código, un día después de la anterior.

    Empieza el `dia` de septiembre.
    """
    for i, codigo in enumerate(codigos):
        historial.apuntar(historial.Pasada(
            pareja, f"{ano}-09-{dia + i:02d} 10:00:00", codigo, 5.0, None))


def detalle_fallo(cfg):
    """Devuelve el detalle del hallazgo `fallo`."""
    return uno(revision.revisar(cfg), "fallo").detalle


with sandbox():
    cfg = mkcfg(["notas"])
    cfg.pairs[0].local_abs.mkdir(parents=True, exist_ok=True)
    listados(cfg.pairs[0])
    results.apuntar("notas", 1, None)
    sin_diario = detalle_fallo(cfg)
    c("sin diario, el fallo sale como antes, sin la frase", "Falla" in sin_diario, False)
    c("entero", sin_diario.endswith("Mientras no se arregle, eso no está sincronizado."),
      True)

    diario("notas", [0, 0, 1, 0, 1, 1, 1], dia=6)
    c.contains("falla desde hace 3: desde la primera de la racha, y cuántas bien",
               detalle_fallo(cfg), "Falla desde el 10/09 · 3 de las últimas 7 bien.")
    c.contains("lo de antes sigue ahí", detalle_fallo(cfg), "Acabó con código 1")
    c.contains("y llega igual a --doctor", "\n".join(revision.informe(cfg)),
               "Falla desde el 10/09 · 3 de las últimas 7 bien.")
    c("sigue siendo un solo hallazgo", revision.cuenta(revision.revisar(cfg)), 1)

with sandbox():
    cfg = mkcfg(["notas", "fotos", "docs"])
    for pair in cfg.pairs:
        pair.local_abs.mkdir(parents=True, exist_ok=True)
        listados(pair)
    for nombre in ("notas", "fotos", "docs"):
        results.apuntar(nombre, 1, None)
    diario("notas", [1, 1, 1, 1], dia=12)
    diario("fotos", [1], dia=20)
    diario("docs", [0, 1], dia=3, ano=ANO - 1)
    por_pareja = {h.pareja: h.detalle for h in revision.revisar(cfg) if h.clave == "fallo"}
    c.contains("nunca ha ido bien: «al menos», que pudo empezar antes del diario",
               por_pareja["notas"], "Falla al menos desde el 12/09 · 0 de las últimas 4 bien.")
    c.contains("una sola pasada no es «0 de las últimas 1»",
               por_pareja["fotos"], "Falla al menos desde el 20/09 · es la única pasada "
                                    "que consta.")
    c.contains("de otro año, con el año", por_pareja["docs"],
               f"Falla desde el 04/09/{ANO - 1} · 1 de las últimas 2 bien.")

with sandbox():
    # El diario dice que la última fue bien y last_run.json que falló: se ha
    # perdido una línea. Mejor ninguna frase que una que contradice al título.
    cfg = mkcfg(["notas"])
    cfg.pairs[0].local_abs.mkdir(parents=True, exist_ok=True)
    listados(cfg.pairs[0])
    diario("notas", [1, 0])
    results.apuntar("notas", 1, None)
    c("si el diario no acaba en un fallo, no se dice nada de él",
      "Falla" in detalle_fallo(cfg), False)

    historial.ruta().write_text("basura\n", encoding="utf-8")
    c("un diario ilegible tampoco estorba al fallo", "Falla" in detalle_fallo(cfg), False)

with sandbox():
    # Los dos nombres del catálogo a la vez, apuntados la última vez que alguien
    # miró la carpeta: se dice sin red, y deja de decirse cuando se borra.
    from common import catalog
    cfg = mkcfg(["notas"])
    cfg.pairs[0].local_abs.mkdir(parents=True, exist_ok=True)
    listados(cfg.pairs[0])
    catalog.apuntar_duplicado("nas:/prdrive-catalog/pairs.toml")
    dos = [h for h in revision.revisar(cfg) if h.clave == "catalogo"]
    c("dos catálogos en el remoto es un aviso", [h.gravedad for h in dos], [revision.AVISO])
    c.contains("  que dice cuál vale", dos[0].detalle if dos else "", "Vale remote.toml")
    c("  y cuenta en la ventana", revision.cuenta(dos), 1)
    catalog.apuntar_duplicado(None)
    c("  y se va cuando ya no los hay",
      [h for h in revision.revisar(cfg) if h.clave == "catalogo"], [])

with sandbox():
    # Una pareja de la raíz entera de antes de `REGLA_SIN_PROGRAMA`: su fichero
    # de filtros ha cambiado y pide un --resync. Si el remoto trae la carpeta
    # del programa, el hallazgo dice dónde está, para borrarla a mano.
    cfg = mkcfg([], pairs=[{"name": "todo", "local": ".", "remote_path": "R/todo"},
                           {"name": "notas", "local": "sync-data/notas", "remote_path": "R/notas"}])
    todo, notas = cfg.pairs
    programa = f'- 10 - - 2026-01-01T00:00:00.000000000+0000 "{model.APP_DIR.name}/rclone.conf"\n'
    for pareja in cfg.pairs:
        pareja.local_abs.mkdir(parents=True, exist_ok=True)
        listados(pareja)
        viejo = model.FILTERS_DIR / f"{pareja.name}.txt"
        # la de una carpeta no ha cambiado de contenido: la fuerza un md5 de otro
        viejo.write_text(bisync.FILTERS_HEADER + "\n" + ("" if pareja.es_raiz else "- x\n"),
                         encoding="utf-8", newline="\n")
        Path(str(viejo) + ".md5").write_text(hashlib.md5(viejo.read_bytes()).hexdigest())
    resync = {h.pareja: h for h in revision.revisar(cfg) if h.clave == "resync"}
    c("las dos piden su resync", sorted(resync), ["notas", "todo"])
    c("  sin la carpeta del programa en el remoto, no lleva dato", resync["todo"].dato, ())
    c("  ni lo dice en el detalle", "carpeta del programa" in resync["todo"].detalle, False)
    for pareja in (todo, notas):
        (pareja.workdir / (bisync.expected_prefix(pareja) + bisync.PATH2_SUFFIX)
         ).write_text(programa, encoding="utf-8")
    resync = {h.pareja: h for h in revision.revisar(cfg) if h.clave == "resync"}
    c("  con ella, el dato es dónde borrarla",
      resync["todo"].dato, (f"nas:R/todo/{model.APP_DIR.name}/",))
    c.contains("  y el detalle dice que la subía", resync["todo"].detalle, "subía la carpeta del programa")
    c("una pareja de una carpeta no la mira (sería del usuario)", resync["notas"].dato, ())

# Dónde está en el remoto la copia del programa que subió una pareja de la raíz,
# y que el hallazgo, la ventana y la consola digan lo mismo antes del resync.
PROGRAMA = model.APP_DIR.name


def con_programa(pareja) -> None:
    """Deja en el listado path2 de esa pareja la carpeta del programa."""
    lst = pareja.workdir / (bisync.expected_prefix(pareja) + bisync.PATH2_SUFFIX)
    lst.parent.mkdir(parents=True, exist_ok=True)
    lst.write_text(f'- 10 - - 2026-01-01T00:00:00.000000000+0000 "{PROGRAMA}/rclone.conf"\n',
                   encoding="utf-8")


with sandbox():
    # `remote_path` se usa tal como está: sin cortarlo antes, "" y "/" serían lo
    # mismo, y en SFTP uno es relativo al origen del remote y el otro absoluto.
    for n, (ruta, esperado) in enumerate((
            ("", f"nas:{PROGRAMA}/"), ("/", f"nas:/{PROGRAMA}/"),
            ("R/p", f"nas:R/p/{PROGRAMA}/"), ("R/p/", f"nas:R/p/{PROGRAMA}/"),
            ("/copia", f"nas:/copia/{PROGRAMA}/"))):
        # una pareja por caso: "" y "/", o "R/p" y "R/p/", dan el mismo listado
        pareja = mkcfg([], pairs=[{"name": f"todo{n}", "local": ".", "remote_path": ruta}]).pairs[0]
        c(f"remote_path {ruta!r} sin listado: no hay carpeta que decir",
          revision.carpeta_programa_en_remoto(pareja), None)
        con_programa(pareja)
        c(f"remote_path {ruta!r} con ella: {esperado}",
          revision.carpeta_programa_en_remoto(pareja), esperado)
    notas = mkcfg(["notas"]).pairs[0]
    con_programa(notas)
    c("una pareja de una carpeta no la mira, aunque el listado la tenga",
      revision.carpeta_programa_en_remoto(notas), None)
    c.contains("la frase dice dónde borrarla y que no la borra el programa",
               revision.aviso_carpeta_programa("nas:R/p/.prdrive/"),
               "no la borra del remoto: bórrala tú de nas:R/p/.prdrive/, que lleva la clave.")

with sandbox():
    cfg = mkcfg([], pairs=[{"name": "todo", "local": ".", "remote_path": "R/todo"},
                           {"name": "otra", "local": ".", "remote_path": "R/otra"},
                           {"name": "notas", "local": "sync-data/notas", "remote_path": "R/notas"}])
    todo, otra, notas = cfg.pairs
    for pareja in cfg.pairs:            # filtros de antes: las tres piden resync
        viejo = model.FILTERS_DIR / f"{pareja.name}.txt"
        viejo.write_text("# de antes\n", encoding="utf-8", newline="\n")
        Path(str(viejo) + ".md5").write_text(hashlib.md5(viejo.read_bytes()).hexdigest())
    con_programa(todo)
    carpeta = f"nas:R/todo/{PROGRAMA}/"

    # la consola (`sync.py`): lo dice ANTES de preguntar, que después no se ve
    vistos = []
    pregunta_real = sync.ask_yes_no
    sync.ask_yes_no = lambda q, default=False: (vistos.append(salida.getvalue()), False)[1]
    salida = io.StringIO()
    try:
        with contextlib.redirect_stdout(salida):
            aprobado = sync.resolve_resync_approval([todo, otra, notas], assume_yes=False)
    finally:
        sync.ask_yes_no = pregunta_real
    c("consola: sin aprobar, el resync no se hace", aprobado, False)
    c.contains("  dice dónde está la copia de la pareja que subió el programa",
               salida.getvalue(), f"todo            {revision.aviso_carpeta_programa(carpeta)}")
    c("  una sola vez: ni la otra raíz ni la de una carpeta lo llevan",
      salida.getvalue().count("bórrala tú"), 1)
    c("  y ya estaba dicho cuando se preguntó", "bórrala tú de " + carpeta in vistos[0], True)
    salida = io.StringIO()
    with contextlib.redirect_stdout(salida):
        aprobado = sync.resolve_resync_approval([todo], assume_yes=True)
    c("consola con --yes: se aprueba y también se dice",
      (aprobado, "bórrala tú de " + carpeta in salida.getvalue()), (True, True))

    # la ventana: la decisión es de `ui`, el cuadro solo la dibuja
    c("ui: las carpetas de las parejas que preguntan, solo las que subieron el programa",
      ui.carpetas_del_programa(cfg, ["todo", "otra", "notas"]), {"todo": carpeta})
    c("  y solo de las que se piden", ui.carpetas_del_programa(cfg, ["otra", "notas"]), {})
    c("  cada una con su frase",
      ui.avisos_de_resync({"todo": carpeta}), [f"todo: {revision.aviso_carpeta_programa(carpeta)}"])
    preguntas = []

    def aprueba(pendientes, carpetas):
        """Anota lo que se le pregunta a quien elige, y dice que sí."""
        preguntas.append((list(pendientes), dict(carpetas)))
        return True

    c("ui: la pasada manual añade --yes si se aprueba",
      ui.manual_args(cfg, ["todo", "notas"], aprueba), ["todo", "notas", "--yes"])
    c("  y le pasa a quien pregunta las parejas y la carpeta",
      preguntas, [(["todo", "notas"], {"todo": carpeta})])
    c("  sin la raíz que subió el programa, no pasa carpetas",
      (ui.manual_args(cfg, ["otra"], lambda p, f: (preguntas.append((p, f)), False)[1]),
       preguntas[-1]), (["otra"], (["otra"], {})))
    c("la consola de menú no pregunta (sync.py lo hará): sigue siendo un no",
      ui.console.ConsoleFrontend().approve_resync(["todo"], {"todo": carpeta}), False)

sys.exit(c.report())
