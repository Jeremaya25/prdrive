#!/usr/bin/env python3
"""El nombre de los listados de un remote `alias`, contra el rclone de verdad.

No es un test de `run_all.py` (no empieza por `test_`): baja el rclone fijado
(`install/rclone_bin.py`, comprobado contra su SHA256SUMS) y lanza `rclone
bisync --resync` de verdad. Lo corre `.github/workflows/prefijo-alias-real.yml`
en Linux y en Windows; en un equipo propio, a mano.

Por cada caso monta un `rclone.conf` con remotes `alias` (a una carpeta, a un
remote `local`, a otro alias, con subruta, a un `combine`), lanza el bisync con
el extremo local de un `device_remote` y el remoto de la pareja, tal como los
arma el programa, y compara el nombre del listado que escribió rclone con
`bisync.expected_prefix()`. `tests/test_bisync_prefijo.py` fija esos nombres
con los que escribió rclone en Linux; esto es lo que dice si siguen siendo los
de rclone y si el caso de Windows (`C:\\…`, `\\\\?\\`) lo es de verdad.

Sale con 1 si algún nombre no coincide, y dice cuál.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

IS_WIN = os.name == "nt"
fallos: list[str] = []


def ver(que: str, obtenido, esperado) -> None:
    """Apunta una comprobación y la dice."""
    bien = obtenido == esperado
    print(f"  {'OK   ' if bien else 'FALLO'} {que}" + ("" if bien else
          f"\n          obtenido: {obtenido!r}\n          esperado: {esperado!r}"), flush=True)
    if not bien:
        fallos.append(que)


def casos(raiz: Path) -> list[tuple[str, str, str]]:
    """Devuelve `(descripción, remote de la pareja, remote_path)` y deja el rclone.conf en `raiz`."""
    remoto = raiz / "remoto"
    conf = f"""
[nas]
type = local

[a_carpeta]
type = alias
remote = {remoto}

[a_nas]
type = alias
remote = nas:{remoto}

[base]
type = alias
remote = {remoto}

[de_alias]
type = alias
remote = base:datos

[con_subruta]
type = alias
remote = {remoto / "datos"}

[a_combine]
type = alias
remote = cmb:r

[cmb]
type = combine
upstreams = "r={remoto}"
"""
    (raiz / "rclone.conf").write_text(conf, encoding="utf-8", newline="\n")
    return [
        ("un alias a una carpeta", "a_carpeta", "datos/prueba"),
        ("  con la ruta del remoto absoluta", "a_carpeta", "/datos/prueba"),
        ("  con la ruta sucia (// y ./)", "a_carpeta", "/datos//./prueba/"),
        ("un alias a un remote local", "a_nas", "datos/prueba"),
        ("un alias de otro alias", "de_alias", "prueba"),
        ("un alias con subruta", "con_subruta", "prueba"),
        ("un alias a un combine", "a_combine", "datos/prueba"),
        ("sin alias, un remote local (el control)", "nas", f"{(remoto / 'datos' / 'prueba').as_posix()}"),
    ]


def probar(rclone: Path, raiz: Path, descripcion: str, remote: str, ruta: str) -> None:
    """Lanza un `bisync --resync` de la pareja y compara el listado con el que se espera."""
    from common import bisync, model

    dispositivo = raiz / "dispositivo"
    model.DEVICE_ROOT = dispositivo
    model.STATE_DIR = dispositivo / ".prdrive" / "state"
    model.FILTERS_DIR = dispositivo / ".prdrive" / "filters"
    model.RCLONE_CONF = raiz / "rclone.conf"
    config = model.parse_config(
        {"defaults": {"remote": remote, "device_remote": "disp"},
         "pair": [{"name": "prueba", "local": "sync-data/prueba", "remote_path": ruta,
                   "mode": "bisync"}]})
    pair = config.pairs[0]
    shutil.rmtree(model.STATE_DIR, ignore_errors=True)
    pair.workdir.mkdir(parents=True)
    r = subprocess.run(
        [str(rclone), "bisync", pair.local_endpoint, pair.remote_endpoint, "--resync",
         "--workdir", str(pair.workdir), "--config", str(model.RCLONE_CONF)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env={**os.environ, **config.pen_environment()}, cwd=model.APP_DIR,
        stdin=subprocess.DEVNULL, timeout=120)
    escritos = sorted(p.name[:-len(bisync.PATH1_SUFFIX)]
                      for p in pair.workdir.glob("*" + bisync.PATH1_SUFFIX))
    if r.returncode != 0 or len(escritos) != 1:
        print(f"  FALLO {descripcion}: rclone ha salido con {r.returncode} y escribió {escritos}\n"
              + "\n".join(f"          | {linea}" for linea in (r.stdout + r.stderr).splitlines()[-8:]),
              flush=True)
        fallos.append(descripcion)
        return
    print(f"        rclone escribió: {escritos[0]}", flush=True)
    ver(f"{descripcion}: {remote}:{ruta}", bisync.expected_prefix(pair), escritos[0])
    ver("  y se puede comprobar", bisync.prefijo_comprobable(pair), True)


def main() -> int:
    """Corre todos los casos con el rclone fijado y devuelve el código de salida."""
    if "--de-verdad" not in sys.argv[1:] and not os.environ.get("CI"):
        print("Esto baja rclone y lo lanza de verdad: en un equipo propio, con --de-verdad.")
        return 2
    # En el CI el rclone lo deja listo `tests/_runtime_ci.py rclone` (con caché);
    # a mano, el de la caché del instalador, o uno recién bajado.
    if os.environ.get("PRDRIVE_RCLONE_CI"):
        rclone = Path(os.environ["PRDRIVE_RCLONE_CI"])
    else:
        from install import rclone_bin
        rclone = rclone_bin.cached() or rclone_bin.download_rclone(lambda *_: None)
    raiz = Path(tempfile.mkdtemp(prefix="prdrive-alias-")).resolve()
    try:
        (raiz / "remoto" / "datos" / "prueba").mkdir(parents=True)
        (raiz / "remoto" / "datos" / "prueba" / "a.txt").write_text("a", encoding="utf-8")
        (raiz / "dispositivo" / "sync-data" / "prueba").mkdir(parents=True)
        (raiz / "dispositivo" / "sync-data" / "prueba" / "b.txt").write_text("b", encoding="utf-8")
        (raiz / "dispositivo" / ".prdrive").mkdir()
        print(f"rclone: {rclone}\nsistema: {'Windows' if IS_WIN else 'Linux'}\n"
              f"raíz del remoto: {raiz / 'remoto'}", flush=True)
        for descripcion, remote, ruta in casos(raiz):
            probar(rclone, raiz, descripcion, remote, ruta)
    finally:
        shutil.rmtree(raiz, ignore_errors=True)
    print(f"\n{'FALLAN: ' + ', '.join(fallos) if fallos else 'Todo coincide con rclone.'}")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
