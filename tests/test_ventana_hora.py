#!/usr/bin/env python3
"""La ventana de hora de rclone (`modify-window`) y lo que no puede mover (#114).

exFAT y FAT32 guardan la hora en saltos de 2 s y Windows la redondea hacia
arriba, también la que pone un programa; rclone mide la precisión del lado local
en la carpeta temporal del equipo (NTFS), no en la unidad. Sin una ventana, lo
que baja del remoto sale cambiado en la pasada siguiente. Lo que se sujeta:
- **El flag llega a rclone** en los cinco modos, también al llavero, y una pareja
  (o `[defaults.flags]`) lo cambia como cualquier otro.
- **Ningún dispositivo necesita `--resync` por él.** Un baseline y un fichero de
  filtros con su md5 escritos por el código de antes, sin el flag, siguen siendo
  de la pareja: no entra en `expected_prefix()` ni en los filtros.
- **`llavero.pendiente()` tolera lo mismo que rclone**: una base con la misma
  medida y la hora a menos de 2 s de la del listado no está pendiente.
"""

import hashlib
import os
import sys
from pathlib import Path

from _harness import Checks, sandbox

import sync
from common import bisync, llavero, model

c = Checks("ventana de hora de rclone (common/model.py, common/llavero.py)")

DEF = {"remote": "nas", "device_remote": "disp", "catalog_path": "/prdrive-catalog/remote.toml"}
NOTAS = {"name": "notas", "local": "sync-data/notas", "remote_path": "/R/notas",
         "mode": "bisync", "include": ["*.md"]}


def config(raw=None, defaults=None, **extra) -> model.Config:
    """La configuración de prueba con una pareja `notas` y, si se dan, `[defaults]` o más tablas."""
    return model.parse_config({"defaults": {**DEF, **(defaults or {})},
                               "pair": [{**NOTAS, **(raw or {})}], **extra})


def orden_de(pair: model.Pair) -> list[str]:
    """La orden de rclone de una pasada normal de esa pareja."""
    ctx = sync.RunContext(binary="rclone", env={}, sello="~SELLO", dry_run=False)
    return sync.build_command(ctx, pair, bisync.ruta_filtros(pair), False)[0]


def valores(cmd: list[str], flag: str) -> list[str]:
    """Los valores con los que aparece `flag` en una orden."""
    return [cmd[i + 1] for i, a in enumerate(cmd[:-1]) if a == flag]


with sandbox() as root:
    # 1. el flag de fábrica llega a la orden de cada modo
    c("BASE_FLAGS lleva la ventana de 2 s", model.BASE_FLAGS.get("modify-window"), "2s")
    for modo in model.MODES:
        p = config({"mode": modo}).pairs[0]
        c(f"{modo}: Pair.flags la trae, de la capa base",
          (p.flags.get("modify-window"), p.origen_flags.get("modify-window")),
          ("2s", model.ORIGEN_BASE))
        c(f"{modo}: y rclone la recibe una vez", valores(orden_de(p), "--modify-window"), ["2s"])
    c("el llavero también la lleva",
      valores(orden_de(model.parse_config({
          "defaults": DEF, "pair": [NOTAS], "keychain": {"base": "personal.kdbx"}
      }).pareja_llavero), "--modify-window"), ["2s"])

    # 2. se cambia como cualquier flag
    propia = config({"flags": {"modify-window": "0"}}).pairs[0]
    c("una pareja la cambia con [pair.flags]",
      (valores(orden_de(propia), "--modify-window"), propia.origen_flags["modify-window"]),
      (["0"], model.ORIGEN_PAREJA))
    comun = config(defaults={"flags": {"modify-window": "1s"}}).pairs[0]
    c("y todas con [defaults.flags]",
      (valores(orden_de(comun), "--modify-window"), comun.origen_flags["modify-window"]),
      (["1s"], model.ORIGEN_DEFAULTS))
    gana = config({"flags": {"modify-window": "0"}},
                  defaults={"flags": {"modify-window": "1s"}}).pairs[0]
    c("la pareja gana a [defaults.flags]", valores(orden_de(gana), "--modify-window"), ["0"])

    # 3. nadie necesita un --resync por ella
    #
    # Un dispositivo ya en uso tiene su baseline y su md5 de filtros escritos con
    # el código de antes, sin el flag. Se monta tal cual lo dejaría y se mira con
    # el de ahora: si la ventana moviera el prefijo o los filtros, la pareja
    # saldría «sin baseline» o «filtros cambiados» y pediría resync.
    real = model.BASE_FLAGS
    model.BASE_FLAGS = {k: v for k, v in real.items() if k != "modify-window"}
    try:
        vieja = config({"exclude": ["*.tmp"]}).pairs[0]
        c("(el código de antes no llevaba la ventana)", "modify-window" in vieja.flags, False)
        prefijo = bisync.expected_prefix(vieja)
        vieja.workdir.mkdir(parents=True)
        for sufijo in (bisync.PATH1_SUFFIX, bisync.PATH2_SUFFIX):
            (vieja.workdir / f"{prefijo}{sufijo}").write_text(
                '# bisync listing v1 from 2026-10-05T06:44:33.246486494+0000\n'
                '- 5 - - 2026-10-05T06:44:29.752645891+0000 "a.md"\n', encoding="utf-8")
        filtros = bisync.filters_file_for(vieja)
        Path(str(filtros) + ".md5").write_text(
            hashlib.md5(filtros.read_bytes()).hexdigest(), encoding="utf-8")
        contenido_viejo = bisync.filters_content(vieja)
        c("(el dispositivo de antes no pide resync)", bisync.resync_reasons(vieja), [])
    finally:
        model.BASE_FLAGS = real

    nueva = config({"exclude": ["*.tmp"]}).pairs[0]
    c("la pareja de ahora lleva la ventana", nueva.flags.get("modify-window"), "2s")
    c("el prefijo del baseline es el mismo",
      bisync.expected_prefix(nueva), prefijo)
    c("el workdir es el mismo", nueva.workdir, vieja.workdir)
    c("los filtros son los mismos, byte a byte", bisync.filters_content(nueva), contenido_viejo)
    c("el baseline de antes sigue siéndolo",
      (bisync.pair_state(nueva).has_baseline, bisync.pair_state(nueva).prefix), (True, prefijo))
    c("el md5 de los filtros sigue valiendo",
      bisync.filters_state(bisync.filters_file_for(nueva)).status, "ok")
    c("y no hace falta ningún --resync", bisync.resync_reasons(nueva), [])


# 4. «pendiente de subir» tolera la misma ventana que rclone

def listar(par: model.Pair, ficheros: dict[str, Path]) -> None:
    """Deja el listado `path1` de una pasada buena con la hora que tienen ahora los ficheros."""
    par.workdir.mkdir(parents=True, exist_ok=True)
    lineas = ["# bisync listing v1 from 2026-10-05T06:44:33.246486494+0000"]
    for nombre, ruta in ficheros.items():
        st = ruta.stat()
        segundos, ns = divmod(st.st_mtime_ns, 1_000_000_000)
        import time as _t
        hora = _t.strftime("%Y-%m-%dT%H:%M:%S", _t.gmtime(segundos)) + f".{ns:09d}+0000"
        lineas.append(f'- {st.st_size:8d} - - {hora} "{nombre}"')
    (par.workdir / f"{bisync.expected_prefix(par)}{bisync.PATH1_SUFFIX}").write_text(
        "\n".join(lineas) + "\n", encoding="utf-8")


def mover_hora(ruta: Path, ns: int) -> None:
    """Cambia la hora de modificación de un fichero en `ns` nanosegundos."""
    st = ruta.stat()
    os.utime(ruta, ns=(st.st_atime_ns, st.st_mtime_ns + ns))


SEG = 1_000_000_000

with sandbox() as root:
    par = model.parse_config({"defaults": DEF, "pair": [NOTAS],
                              "keychain": {"base": "personal.kdbx"}}).pareja_llavero
    carpeta = root / ".keychain"
    carpeta.mkdir()
    base = carpeta / "personal.kdbx"
    base.write_bytes(b"x" * 10)
    # Una hora con fracción, como la que baja de un remoto.
    os.utime(base, ns=(base.stat().st_atime_ns, 1_700_000_000_123_456_789))
    listar(par, {"personal.kdbx": base})
    c("la base como dice el listado, no está pendiente", llavero.pendiente(par), False)

    for ns, texto, esperado in (
            (1_876_543_000, "+1,876543 s (lo que midió Windows en exFAT y FAT32)", False),
            (1_900_000_000, "+1,9 s", False),
            (-1_900_000_000, "-1,9 s (rclone tolera los dos sentidos)", False),
            (2_000_000_000, "+2,0 s justos (rclone: dentro solo si es MENOS que la ventana)", True),
            (2_100_000_000, "+2,1 s", True),
            (-2_100_000_000, "-2,1 s", True)):
        listar(par, {"personal.kdbx": base})
        mover_hora(base, ns)
        c(f"misma medida y la hora {texto}: pendiente", llavero.pendiente(par), esperado)
        mover_hora(base, -ns)

    listar(par, {"personal.kdbx": base})
    mover_hora(base, SEG)
    base.write_bytes(b"y" * 11)
    mover_hora(base, 0)
    c("a 1 s de la hora pero con otra medida: pendiente", llavero.pendiente(par), True)

    base.write_bytes(b"x" * 10)
    os.utime(base, ns=(base.stat().st_atime_ns, 1_700_000_000_123_456_789))
    otra = carpeta / "otra.kdbx"
    otra.write_bytes(b"z" * 4)
    listar(par, {"personal.kdbx": base, "otra.kdbx": otra})
    mover_hora(base, SEG)
    c("dos bases, una dentro de la ventana: no hay nada pendiente", llavero.pendiente(par), False)
    mover_hora(otra, 3 * SEG)
    c("y la otra fuera de ella: sí", llavero.pendiente(par), True)

sys.exit(c.report())
