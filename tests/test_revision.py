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
from pathlib import Path

from _harness import Checks, mkcfg, sandbox

from common import bisync, conflicts, model, results, revision

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

sys.exit(c.report())
