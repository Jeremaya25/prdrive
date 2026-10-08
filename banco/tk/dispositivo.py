#!/usr/bin/env python3
"""Construye un dispositivo de muestra aprovisionado, con 5 parejas, desde un árbol de código.

Uso: python dispositivo.py <árbol-de-código> <raíz-del-dispositivo>

Lo deja como lo deja `install/deploy.py` (`<raíz>/.prdrive/` con `sync.py`,
`runsync.py`, `penwatch.py`, `VERSION`, `common/` y `ui/`, nada más) y escribe,
con los módulos DE ESE ÁRBOL (así el formato del estado es el de esa versión):
`sync_config.toml` con 5 parejas, el fichero de control, un nombre de flota, una
última pasada buena de cada pareja, las bases de bisync de las parejas bisync,
la copia local del catálogo (las mismas 5 parejas y una que el dispositivo no
usa) y las carpetas locales con unos ficheros. Al final compila el código (un
dispositivo de verdad ya tiene `__pycache__` tras su primer uso).

Sin enlaces simbólicos y con rutas de cualquier sistema: corre igual en Windows y
Linux. El árbol de código solo se lee; todo se escribe bajo la raíz.
"""
import compileall
import hashlib
import os
import shutil
import sys
import tomllib
from pathlib import Path

PAREJAS = [
    {"name": "documentos", "local": "sync-data/documentos", "remote_path": "/datos/documentos",
     "mode": "bisync"},
    {"name": "fotos", "local": "sync-data/fotos", "remote_path": "/datos/fotos", "mode": "up"},
    {"name": "musica", "local": "sync-data/musica", "remote_path": "/datos/musica", "mode": "down"},
    {"name": "trabajo", "local": "sync-data/trabajo", "remote_path": "/datos/trabajo",
     "mode": "bisync"},
    {"name": "notas", "local": "sync-data/notas", "remote_path": "/datos/notas", "mode": "bisync"},
]


def main() -> None:
    src = Path(sys.argv[1]).resolve()
    raiz = Path(sys.argv[2]).resolve()
    app = raiz / ".prdrive"
    if raiz.exists():
        shutil.rmtree(raiz)
    app.mkdir(parents=True)
    ign = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo")
    for f in ("sync.py", "runsync.py", "penwatch.py", "VERSION"):
        if (src / f).exists():
            shutil.copy2(src / f, app / f)
    for d in ("common", "ui"):
        shutil.copytree(src / d, app / d, ignore=ign)

    sys.path.insert(0, str(app))
    os.chdir(app)
    from common import bisync, catalog, config_file, fleet, model, results  # noqa: E402

    base = {"defaults": {"remote": "nas"},
            "daemon": {"pairs": ["documentos", "notas"], "interval_minutes": 15},
            "pair": PAREJAS}
    model.CONFIG_FILE.write_text(config_file.dumps(base), encoding="utf-8")
    for d in (model.STATE_DIR, model.LOG_DIR, model.FILTERS_DIR):
        d.mkdir(parents=True, exist_ok=True)
    (app / "PRDRIVE").write_text("id=bench-0000-0000-0001\n", encoding="utf-8")
    (app / "rclone.conf").write_text("[nas]\ntype = sftp\nhost = nas.local\nuser = bench\n",
                                     encoding="utf-8")
    try:
        fleet.guardar_nombre("pendrive azul")
    except Exception as e:                               # noqa: BLE001
        print("nombre de flota:", e, file=sys.stderr)

    cfg = model.load_config()
    for p in cfg.pairs:
        local = Path(p.local) if Path(p.local).is_absolute() else model.DEVICE_ROOT / p.local
        local.mkdir(parents=True, exist_ok=True)
        for i in range(5):
            (local / f"fichero-{i}.txt").write_text("x" * 100, encoding="utf-8")
        if p.is_bisync:
            p.workdir.mkdir(parents=True, exist_ok=True)
            pre = bisync.expected_prefix(p)
            for suf in (bisync.PATH1_SUFFIX, bisync.PATH2_SUFFIX):
                (p.workdir / f"{pre}{suf}").write_text("# rclone lsf\n", encoding="utf-8")
            # Lo que bisync deja tras un --resync: el md5 del fichero de filtros al lado.
            filtros = bisync.filters_file_for(p)
            if filtros is not None:
                Path(str(filtros) + ".md5").write_text(
                    hashlib.md5(filtros.read_bytes()).hexdigest(), encoding="utf-8")
        results.apuntar(p.name, 0, None)

    catalogo = {"defaults": {"remote": "nas"},
                "pair": [dict(p) for p in PAREJAS] + [
                    {"name": "videos", "local": "sync-data/videos",
                     "remote_path": "/datos/videos", "mode": "up"}]}
    texto = config_file.dumps(catalogo)
    catalog._write_cache(catalog.Catalog(raw=tomllib.loads(texto), text=texto, source="remote",
                                         stamp="2026-10-01 10:00:00",
                                         endpoint="nas:/prdrive-catalog/remote.toml"))

    notas = {}
    for p in cfg.pairs:
        try:
            motivos = bisync.resync_reasons(p)
        except Exception as e:                           # noqa: BLE001
            motivos = [repr(e)]
        if motivos:
            notas[p.name] = motivos
    print(f"dispositivo listo en {raiz}; parejas={len(cfg.pairs)}; resync={notas}",
          file=sys.stderr)

    compileall.compile_dir(str(app), quiet=1)


if __name__ == "__main__":
    main()
