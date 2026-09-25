#!/usr/bin/env python3
"""
El diagnóstico compartido (common/revision.py).

Es la lista de averías que imprime `sync.py --doctor` y que dibuja la pantalla
de «Reparación», y es UNA: si aquí se deja de ver algo, deja de verse en los dos
sitios a la vez. Por eso lo que se comprueba es qué se detecta y con qué
gravedad, no cómo queda escrito.
"""

import hashlib
import shutil
import sys
from datetime import datetime
from pathlib import Path

from _harness import Checks, mkcfg, sandbox

from common import bisync, conflicts, historial, model, results, revision

c = Checks("el diagnóstico compartido")


def claves(hallazgos):
    return sorted({h.clave for h in hallazgos})


def uno(hallazgos, clave):
    return next((h for h in hallazgos if h.clave == clave), None)


def listados(pair, prefijo=None):
    """Un baseline en disco, como lo deja un --resync: los dos listados y el
    md5 de los filtros. Sin el md5 la pareja pide resync con razón, que es
    precisamente una de las averías de más abajo."""
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


# --- desde cuándo falla: el diario de pasadas ----------------------------------------
# El fallo dice desde cuándo y cuántas de las últimas fueron bien. La frase sale
# de common/historial.py y llega a la pantalla y a --doctor desde aquí.
ANO = datetime.now().year


def diario(pareja, codigos, dia=1, ano=ANO):
    """Una pasada por código, un día después de la anterior, empezando el `dia`
    de septiembre."""
    for i, codigo in enumerate(codigos):
        historial.apuntar(historial.Pasada(
            pareja, f"{ano}-09-{dia + i:02d} 10:00:00", codigo, 5.0, None))


def detalle_fallo(cfg):
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

sys.exit(c.report())
