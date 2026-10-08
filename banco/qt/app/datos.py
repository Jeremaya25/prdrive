"""La capa de datos: los modulos headless del 0.7.1 del dispositivo, importados en el MISMO proceso que la ventana.

Nada de IPC ni servidor: `from common import model, results, revision, ...` y `ui.pair_editor` / `ui.prefs` /
`ui.watch` (decision sin Tk). Unica trampa: `ui/__init__.py` precarga el Tk con Xft (`tk_con_xft()`) al importarse;
para un frontend Qt eso sobra, asi que se importa con un `_tkinter` de pega (la integracion real partiria
`ui/__init__` en una parte sin Tk).

Es del banco de la interfaz (temporal, ver `banco/LEEME.md`): port del prototipo Qt.
"""
from __future__ import annotations

import os
import sys
import time
import types

M: dict = {}
T: dict = {}


def cargar_modulos(dispositivo: str) -> None:
    app = os.path.join(dispositivo, ".prdrive")
    if app not in sys.path:
        sys.path.insert(0, app)
    os.chdir(app)                     # el motor trabaja con cwd = APP_DIR
    t = time.perf_counter()
    stub = "_tkinter" not in sys.modules
    if stub:
        sys.modules["_tkinter"] = types.ModuleType("_tkinter")
    try:
        from common import bisync, catalog, config_file, fleet, model, results, revision, store  # noqa: F401
        import ui
        from ui import pair_editor, prefs, watch
    finally:
        if stub:
            sys.modules.pop("_tkinter", None)
    M.update(model=model, bisync=bisync, results=results, revision=revision, config_file=config_file,
             catalog=catalog, fleet=fleet, ui=ui, pair_editor=pair_editor, prefs=prefs, watch=watch)
    T["imports_ms"] = (time.perf_counter() - t) * 1000


def estado_principal() -> dict:
    """Lo que pinta la ventana principal (misma logica que `ui/tk.py`: tiempos, notas, marcadas, vigilante)."""
    t = time.perf_counter()
    model, ui, prefs, revision = M["model"], M["ui"], M["prefs"], M["revision"]
    cfg = model.load_config()
    times = ui.pair_times(cfg)
    notes = ui.pair_status_notes(cfg)
    marcadas, minutos, _nota = prefs.startup_defaults(cfg)
    stamps = [x for x in times.values() if x]
    try:
        nombre = M["fleet"].nombre()
    except Exception:                                    # noqa: BLE001
        nombre = ""
    try:
        n_rev = revision.cuenta(revision.revisar(cfg))
    except Exception:                                    # noqa: BLE001
        n_rev = 0
    try:
        res = M["watch"].resumen()
        lin = M["watch"].linea(res)
        vig = {"texto": lin.texto, "ambar": lin.aviso, "boton": lin.boton} if lin else None
    except Exception:                                    # noqa: BLE001
        vig = None
    raiz = str(model.DEVICE_ROOT)
    corto = raiz if len(raiz) <= 30 else "…" + raiz[-29:]
    out = {
        "version": (model.APP_DIR / "VERSION").read_text(encoding="utf-8").strip(),
        "raiz": corto, "nombre": nombre, "remotos": sorted({p.remote_name for p in cfg.pairs}) or ["nas"],
        "estado": ("Aviso", f"{n_rev} que revisar") if n_rev else ("Ok", "al día"),
        "pares": [{"nombre": p.name, "modo": p.mode.name, "marcada": p.name in marcadas,
                   "hora": ui.cuando(times.get(p.name)), "nota": notes.get(p.name)} for p in cfg.pairs],
        "ultima": ui.cuando(max(stamps)) if stamps else "", "vigilante": vig, "minutos": minutos,
        "revisar": n_rev,
    }
    T["estado_ms"] = (time.perf_counter() - t) * 1000
    return out


def parejas() -> dict:
    """Lo que pinta «Parejas»: las filas de `pair_editor.catalog_rows` (el editor headless del 0.7.1)."""
    t = time.perf_counter()
    pe, cat_mod, cf = M["pair_editor"], M["catalog"], M["config_file"]
    cfg = M["model"].load_config()
    raw = cf.load_raw()
    cat = cat_mod.cached()
    filas = pe.catalog_rows(cfg, raw, cat)
    locales = {x.get("name"): x.get("local") for x in raw.get("pair") or []}
    filas = [f._replace(local=locales.get(f.name) or f.local) for f in filas]
    out = []
    for f in filas:
        tono, texto = pe.row_status(f)
        out.append({"nombre": f.name, "modo": f.mode, "local": f.local, "remoto": f.remote, "en_pen": f.en_pen,
                    "tono": tono, "estado": texto})
    d = raw.get("defaults") or {}
    res = {"filas": out, "sello": getattr(cat, "stamp", "") if cat is not None else "",
           "endpoint": getattr(cat, "endpoint", "") if cat is not None else "",
           "remote": d.get("remote", "nas"), "device_remote": d.get("device_remote"),
           "modos": list(M["model"].MODES)}
    T["parejas_ms"] = (time.perf_counter() - t) * 1000
    return res


def reparacion() -> list:
    cfg = M["model"].load_config()
    return [{"titulo": h.titulo, "detalle": h.detalle, "pareja": h.pareja, "gravedad": h.gravedad}
            for h in M["revision"].revisar(cfg)]
