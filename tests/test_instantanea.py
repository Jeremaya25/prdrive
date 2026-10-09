#!/usr/bin/env python3
"""La lectura de una sola vez de la ventana (`ui/instantanea.py`).

La ventana principal, «Parejas» y «Ajustes» leían el dispositivo cada una por
su cuenta y en el hilo de Tk (seis veces el estado de cada pareja, tres veces
la raíz física...). `instantanea.leer()` lo lee todo UNA vez, en un hilo y sin
Tk, y `Compartida` lo reparte. Lo que se comprueba:
- Una pasada, sin repetir: la raíz física se busca una vez y se la pasan los
  lectores que la necesitan (`revision`, `cifrado`, `components`).
- Cada campo sale de su lector, y el que falla deja su valor por defecto y una
  línea en `fallos` sin impedir que se lea el resto. Sin fallos, `fallos` va
  vacío.
- Sin Tk: en un intérprete limpio, `tkinter` no queda cargado.
- Cuándo vale: la huella de lo que se leyó (fechas y tamaños, no una carpeta
  entera). Lo que cambia una pasada, un conflicto, el catálogo, los filtros o el
  workdir de una pareja la caduca; lo que escribe la propia ventana
  (`ui_prefs.json`, `ui.lock.json`, el buzón del servicio) no.
- La lectura no deja nada a medias en `filters/`: lo regenera antes de tomar la
  huella.
"""

import inspect
import json
import os
import shutil
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

from _harness import REPO, Checks, mkcfg, sandbox, tmpdir

from common import bisync, components, conflicts, fleet, model, results, revision, vestibulo
from ui import cifrado, instantanea, watch

c = Checks("la lectura de una sola vez de la ventana")

ID = "3f9c1a2b4d5e6f708192a3b4c5d6e7f8"


@contextmanager
def parchado(*cambios):
    """Sustituye `(módulo, nombre, valor)` mientras dure el bloque y lo devuelve al salir."""
    guardado = [(m, n, getattr(m, n)) for m, n, _ in cambios]
    try:
        for m, n, v in cambios:
            setattr(m, n, v)
        yield
    finally:
        for m, n, v in reversed(guardado):
            setattr(m, n, v)


def listados(pair, prefijo=None):
    """Deja un baseline en disco, como lo deja un `--resync`."""
    import hashlib
    prefijo = prefijo or bisync.expected_prefix(pair)
    pair.workdir.mkdir(parents=True, exist_ok=True)
    for sufijo in (bisync.PATH1_SUFFIX, bisync.PATH2_SUFFIX):
        (pair.workdir / f"{prefijo}{sufijo}").write_text("listado\n", encoding="utf-8")
    ffile = bisync.filters_file_for(pair)
    if ffile is not None:
        Path(str(ffile) + ".md5").write_text(
            hashlib.md5(ffile.read_bytes()).hexdigest(), encoding="utf-8")


def preparar(nombres=("notas", "fotos")):
    """Una config con sus carpetas locales y un baseline al día en cada pareja."""
    cfg = mkcfg(list(nombres))
    for pair in cfg.pairs:
        pair.local_abs.mkdir(parents=True, exist_ok=True)
        listados(pair)
    return cfg


def mueve_fecha(ruta, segundos=10):
    """Cambia la fecha de modificación de `ruta` en `segundos`.

    Se fuerza en vez de esperar al reloj: la fecha de una carpeta sube de golpe
    cada pocos milisegundos y dos cambios seguidos pueden caer en el mismo.
    """
    st = os.stat(ruta)
    ns = st.st_mtime_ns + segundos * 1_000_000_000
    os.utime(ruta, ns=(ns, ns))


SIN_EQUIPO = (
    (vestibulo, "raiz_fisica", lambda ident: None),
    (fleet, "device_id", lambda app_dir=None: ID),
    (components, "pendientes", lambda *a, **k: []),
    (cifrado, "bloqueo", lambda: None),
    (model, "es_equipo", lambda *a, **k: False),
    (watch, "resumen", lambda: watch.Resumen("sin_instalar")),
)
"""Lo que lee del equipo, sustituido: las lecturas de abajo no miran el equipo de verdad."""


def leer_aislado(cfg):
    """Lee sin mirar el equipo: ni unidades, ni arranque automático, ni componentes."""
    with parchado(*SIN_EQUIPO):
        return instantanea.leer(cfg, notas=lambda config: {}, linea_llavero=lambda config: None)


def caduca(inst, cfg, tocar):
    """Hace `tocar(i)` hasta que la lectura deja de valer y dice si lo hizo.

    Se repite (hasta 2 s) porque la fecha de una carpeta sube de golpe cada pocos
    milisegundos y dos cambios seguidos pueden caer en la misma.
    """
    limite = time.monotonic() + 2
    i = 0
    while inst.vigente(cfg) and time.monotonic() < limite:
        tocar(i)
        i += 1
        time.sleep(0.005)
    return not inst.vigente(cfg)


# 0. el centinela de «búscala tú» es uno solo
for nombre, funcion in (("revision.revisar", revision.revisar),
                        ("cifrado.expulsion", cifrado.expulsion),
                        ("vestibulo.sin_sitio_fuera", vestibulo.sin_sitio_fuera)):
    c(f"{nombre}: `fisica` se busca por defecto con el centinela del vestíbulo",
      inspect.signature(funcion).parameters["fisica"].default is vestibulo.BUSCAR, True)

# 1. una pasada, sin repetir: lectores de verdad, con la raíz física contada
with sandbox():
    cfg = preparar()
    fotos = cfg.pairs[1]
    (fotos.workdir / "suelto.lck").write_text("", encoding="utf-8")
    conflicts.ruta_estado().write_text(
        '{"parejas": {"notas": ["sync-data/notas/a.conflicto-remoto1"]}}', encoding="utf-8")
    (cfg.pairs[0].local_abs / "a.conflicto-remoto1").write_text("x", encoding="utf-8")
    fisica = tmpdir()
    vistos = {"raiz_fisica": [], "device_id": 0, "revisar": [], "pendientes": [],
              "expulsion": [], "notas": [], "linea": []}
    real_revisar, real_pendientes, real_expulsion = (
        revision.revisar, components.pendientes, cifrado.expulsion)

    def raiz_fisica(device_id):
        vistos["raiz_fisica"].append(device_id)
        return fisica

    def device_id(app_dir=None):
        vistos["device_id"] += 1
        return ID

    def revisar(config, **k):
        vistos["revisar"].append(k)
        return real_revisar(config, **k)

    def pendientes(*a, **k):
        vistos["pendientes"].append(k)
        return real_pendientes(*a, **k)

    def expulsion(**k):
        vistos["expulsion"].append(k)
        return real_expulsion(**k)

    def notas(config):
        vistos["notas"].append(config)
        return {"notas": "requiere resync"}

    def linea(config):
        vistos["linea"].append(config)
        return None

    with parchado((vestibulo, "raiz_fisica", raiz_fisica), (fleet, "device_id", device_id),
                  (revision, "revisar", revisar), (components, "pendientes", pendientes),
                  (cifrado, "expulsion", expulsion),
                  (watch, "resumen", lambda: watch.Resumen("sin_instalar"))):
        inst = instantanea.leer(cfg, notas=notas, linea_llavero=linea)

    c("la raíz física se busca UNA vez en toda la lectura", vistos["raiz_fisica"], [ID])
    c("  y es la que queda en la instantánea", (inst.fisica, inst.device_id), (fisica, ID))
    c("el id del dispositivo se pregunta (cada lector que lo necesita lo pide a lo suyo)",
      vistos["device_id"] >= 1, True)
    c("`revisar` recibe la raíz ya buscada", vistos["revisar"], [{"fisica": fisica}])
    c("`pendientes` también", vistos["pendientes"], [{"fisica": fisica}])
    c("y `expulsion` también", vistos["expulsion"], [{"fisica": fisica}])
    c("las notas y la línea del llavero se piden con la config", (vistos["notas"], vistos["linea"]),
      ([cfg], [cfg]))
    c("sin fallos, `fallos` va vacío", inst.fallos, {})
    c("lo que se lee es una instantánea", isinstance(inst, instantanea.Instantanea), True)
    c("las notas salen del lector que se le pasó", inst.notas, {"notas": "requiere resync"})
    c("la línea del llavero, también", inst.llavero, None)
    c("los hallazgos salen de `revisar`", inst.hallazgos, tuple(real_revisar(cfg)))
    c("  como tupla", isinstance(inst.hallazgos, tuple), True)
    c("  con su cuenta", inst.cuenta, revision.cuenta(list(inst.hallazgos)))
    c("  y el lock suelto está entre ellos",
      sorted(h.clave for h in inst.hallazgos), ["conflicto", "lock"])
    c("los conflictos, por pareja", inst.conflictos, {"notas": 1})
    c("el estado de cada pareja bisync: el baseline y los filtros",
      {n: (e[0].status, e[1].status) for n, e in inst.estados.items()},
      {"notas": ("ok", "ok"), "fotos": ("ok", "ok")})
    c("  tal como lo dice bisync",
      inst.estados["notas"],
      (bisync.pair_state(cfg.pairs[0]),
       bisync.filters_state(bisync.filters_file_for(cfg.pairs[0]))))
    c("no es de un dispositivo en un equipo", (inst.del_equipo, inst.bloqueo), (False, None))
    c("el vigilante es el que dijo `watch.resumen`", inst.vigilante, watch.Resumen("sin_instalar"))
    c("con la hora de cuando empezó a leer",
      0 < time.time() - inst.hecha < 60, True)
    c("y la firma de la config", inst.firma, instantanea.firma(cfg))
    c("recién leída, vale", inst.vigente(cfg), True)

# 2. cada campo sale de su lector (todos sustituidos)
with sandbox():
    cfg = preparar(("notas",))
    fisica = tmpdir()
    hallazgo = revision.Hallazgo("lock", "t", "d", "notas", revision.AVISO)
    nota = revision.Hallazgo("listados", "t", "d", None, revision.NOTA)
    pend = [components.Pendiente(None, components.VERACRYPT, "1.0", "2.0", ruta=Path("x")),
            components.Pendiente(None, components.VERACRYPT, "?", "2.0", ruta=Path("x"),
                                 asistente=True)]
    script = Path("expulsar.sh")
    resumen = watch.Resumen("agente", "daemon", True)
    visto = []
    parches = (
        (vestibulo, "raiz_fisica", lambda ident: fisica),
        (fleet, "device_id", lambda app_dir=None: ID),
        (revision, "revisar", lambda config, **k: [hallazgo, nota]),
        (conflicts, "cargar", lambda config: {"notas": [1, 2]}),
        (components, "pendientes", lambda *a, **k: pend),
        (cifrado, "expulsion", lambda **k: script),
        (cifrado, "bloqueo", lambda: "uid"),
        (model, "es_equipo", lambda *a, **k: True),
        (watch, "resumen", lambda: resumen),
    )
    with parchado(*parches):
        inst = instantanea.leer(cfg, notas=lambda config: {"notas": "requiere resync"},
                                linea_llavero=lambda config: "una línea")
    c("sin fallos", inst.fallos, {})
    c("hallazgos", inst.hallazgos, (hallazgo, nota))
    c("  la cuenta no incluye las notas", inst.cuenta, 1)
    c("conflictos", inst.conflictos, {"notas": 2})
    c("componentes", inst.componentes, tuple(pend))
    c("  su texto es el del recuadro", inst.componentes_texto, components.resumen(pend))
    c("  y se pueden actualizar", inst.componentes_actualizables, True)
    c("la raíz física", inst.fisica, fisica)
    c("expulsión", inst.expulsion, script)
    c("bloqueo", inst.bloqueo, "uid")
    c("del equipo", inst.del_equipo, True)
    c("vigilante", inst.vigilante, resumen)
    c("llavero", inst.llavero, "una línea")
    c("notas", inst.notas, {"notas": "requiere resync"})

    with parchado(*parches, (components, "pendientes", lambda *a, **k: [pend[1]])):
        solo_asistente = instantanea.leer(cfg, notas=lambda config: {}, linea_llavero=lambda c_: None)
    c("si solo queda lo del asistente, no hay nada que «Actualizar…»",
      (solo_asistente.componentes_actualizables, bool(solo_asistente.componentes_texto)),
      (False, True))
    with parchado(*parches, (components, "pendientes", lambda *a, **k: [])):
        sin = instantanea.leer(cfg, notas=lambda config: {}, linea_llavero=lambda c_: None)
    c("sin componentes pendientes, ni texto ni botón",
      (sin.componentes, sin.componentes_texto, sin.componentes_actualizables), ((), None, False))

# 3. el que falla deja su valor por defecto y una línea en `fallos`; el resto se lee
with sandbox():
    cfg = preparar(("notas",))
    fisica = tmpdir()
    sano = (*SIN_EQUIPO, (vestibulo, "raiz_fisica", lambda ident: fisica))

    def revienta(*a, **k):
        raise RuntimeError("se ha ido el disco")

    def lectura(*cambios, **lectores):
        """Lee con lo sano más estos cambios; las notas y el llavero van por argumento."""
        lectores.setdefault("notas", lambda config: {"notas": "requiere resync"})
        lectores.setdefault("linea_llavero", lambda config: "una línea")
        with parchado(*sano, *cambios):
            return instantanea.leer(cfg, **lectores)

    base = lectura()
    c("la lectura de referencia no tiene fallos", base.fallos, {})
    CAMPOS = ("estados", "notas", "hallazgos", "cuenta", "conflictos", "componentes",
              "componentes_texto", "componentes_actualizables", "fisica", "expulsion", "bloqueo",
              "del_equipo", "vigilante", "llavero", "device_id")
    casos = [
        ("estados", {"estados": {}}, [(instantanea, "estados_de", revienta)], {}),
        ("notas", {"notas": {}}, [], {"notas": revienta}),
        ("hallazgos", {"hallazgos": (), "cuenta": 0}, [(revision, "revisar", revienta)], {}),
        ("conflictos", {"conflictos": {}}, [(conflicts, "cargar", revienta)], {}),
        ("componentes", {"componentes": (), "componentes_texto": None,
                         "componentes_actualizables": False},
         [(components, "pendientes", revienta)], {}),
        ("expulsion", {"expulsion": None}, [(cifrado, "expulsion", revienta)], {}),
        ("bloqueo", {"bloqueo": None}, [(cifrado, "bloqueo", revienta)], {}),
        ("del_equipo", {"del_equipo": False}, [(model, "es_equipo", revienta)], {}),
        ("vigilante", {"vigilante": watch.Resumen("no_disponible")},
         [(watch, "resumen", revienta)], {}),
        ("llavero", {"llavero": None}, [], {"linea_llavero": revienta}),
        ("device_id", {"device_id": None, "fisica": None}, [(fleet, "device_id", revienta)], {}),
        ("fisica", {"fisica": None}, [(vestibulo, "raiz_fisica", revienta)], {}),
    ]
    for campo, defecto, cambios, lectores in casos:
        inst = lectura(*cambios, **lectores)
        c(f"{campo}: el lector falla y la lectura no lanza", campo in inst.fallos, True)
        c(f"  la línea dice qué pasó", "se ha ido el disco" in inst.fallos.get(campo, ""), True)
        c(f"  y solo hay esa línea", list(inst.fallos), [campo])
        c(f"  su campo queda en el valor por defecto",
          {k: getattr(inst, k) for k in defecto}, defecto)
        c(f"  y el resto se lee igual",
          {k: getattr(inst, k) for k in CAMPOS if k not in defecto},
          {k: getattr(base, k) for k in CAMPOS if k not in defecto})
        c(f"  una instantánea con huella, que vale", inst.vigente(cfg), True)

    # lo que da una raíz sin id: no se busca nada
    visto = []
    inst = lectura((fleet, "device_id", lambda app_dir=None: None),
                   (vestibulo, "raiz_fisica", lambda ident: visto.append(ident)))
    c("sin id de dispositivo no se busca la raíz física", (visto, inst.fisica, inst.device_id),
      ([], None, None))

    # un config roto del todo no impide devolver algo
    class Roto:
        pairs = None
        llavero = None
        names = []

    c("una config que ni se puede recorrer devuelve algo vacío y no lanza",
      type(instantanea.leer(Roto())).__name__, "Instantanea")

# 4. vacía
with sandbox():
    cfg = preparar(("notas",))
    vacia = instantanea.vacia(cfg)
    c("vacía: nada leído",
      (vacia.estados, vacia.notas, vacia.hallazgos, vacia.cuenta, vacia.conflictos,
       vacia.componentes, vacia.componentes_texto, vacia.componentes_actualizables,
       vacia.fisica, vacia.expulsion, vacia.bloqueo, vacia.del_equipo, vacia.llavero,
       vacia.device_id, vacia.fallos),
      ({}, {}, (), 0, {}, (), None, False, None, None, None, False, None, None, {}))
    c("  y el vigilante no se sabe", vacia.vigilante, watch.Resumen("no_disponible"))
    c("  su firma es la de la config", vacia.firma, instantanea.firma(cfg))
    c("  no vale para nadie: no se leyó nada", vacia.vigente(cfg), False)
    compartida = instantanea.Compartida()
    compartida.poner(vacia)
    c("  y no se comparte", compartida.para(cfg), None)

# 4b. los lectores por defecto: los de `ui`, buscados al leer
import ui  # noqa: E402
from ui import llavero_editor  # noqa: E402

with sandbox():
    cfg = preparar(("notas",))
    con_llavero = model.parse_config({
        "defaults": {"remote": "nas"}, "keychain": {"base": "personal.kdbx"},
        "pair": [{"name": "notas", "local": "sync-data/notas", "remote_path": "/R/notas"}]})
    c("sin [keychain] no hay línea del llavero (y no se importa el llavero)",
      instantanea.linea_del_llavero(cfg), None)
    with parchado(*SIN_EQUIPO, (ui, "pair_status_notes", lambda config: {"notas": "requiere resync"}),
                  (llavero_editor, "linea", lambda config: "la del llavero")):
        por_defecto = instantanea.leer(cfg)
        con = instantanea.leer(con_llavero)
    c("las notas por defecto son las de `ui.pair_status_notes`, buscadas al leer",
      por_defecto.notas, {"notas": "requiere resync"})
    c("la línea por defecto de un dispositivo sin llavero es ninguna", por_defecto.llavero, None)
    c("  y con [keychain] es la de `llavero_editor.linea`", con.llavero, "la del llavero")
    c("  y la pareja del llavero no está entre los estados de «Parejas»: no es del usuario",
      sorted(con.estados), ["notas"])
    try:
        por_defecto.cuenta = 5
        inmutable = False
    except AttributeError:
        inmutable = True
    c("una instantánea no se modifica", inmutable, True)

# 5. sin Tk: en un intérprete limpio
codigo = f"""
import json, sys
sys.path.insert(0, {str(REPO / "tests")!r})
from _harness import mkcfg, sandbox
with sandbox():
    from ui import instantanea
    inst = instantanea.leer(mkcfg(["a"]))
    instantanea.vacia(mkcfg(["a"]))
    print(json.dumps({{"tkinter": "tkinter" in sys.modules, "_tkinter": "_tkinter" in sys.modules,
                      "ui.tk": "ui.tk" in sys.modules, "hecha": inst.hecha > 0}}))
"""
proc = subprocess.run([sys.executable, "-c", codigo], cwd=str(REPO), capture_output=True,
                      text=True, timeout=120)
try:
    carga = json.loads(proc.stdout.strip().splitlines()[-1])
except (ValueError, IndexError):
    carga = {"error": proc.stdout + proc.stderr}
c("tras `leer()` en un intérprete limpio no está tkinter, ni su motor, ni `ui.tk`",
  carga, {"tkinter": False, "_tkinter": False, "ui.tk": False, "hecha": True})

# 6. la firma
with sandbox():
    cfg = preparar(("notas", "fotos"))
    c("la firma de una config es la misma cada vez", instantanea.firma(cfg),
      instantanea.firma(preparar(("notas", "fotos"))))
    cambiadas = {
        "una pareja de más": mkcfg(["notas", "fotos", "docs"]),
        "una de menos": mkcfg(["notas"]),
        "otro orden de parejas": mkcfg(["fotos", "notas"]),
        "otro modo": mkcfg([], pairs=[
            {"name": "notas", "local": "sync-data/notas", "remote_path": "/R/notas",
             "mode": "up"},
            {"name": "fotos", "local": "sync-data/fotos", "remote_path": "/R/fotos"}]),
        "otra carpeta local": mkcfg([], pairs=[
            {"name": "notas", "local": "otra/notas", "remote_path": "/R/notas"},
            {"name": "fotos", "local": "sync-data/fotos", "remote_path": "/R/fotos"}]),
        "otro destino remoto": mkcfg([], pairs=[
            {"name": "notas", "local": "sync-data/notas", "remote_path": "/Otro/notas"},
            {"name": "fotos", "local": "sync-data/fotos", "remote_path": "/R/fotos"}]),
        # lo que cambia el fichero de filtros cambia si «filtros» pide resync
        "un exclude de más": mkcfg([], pairs=[
            {"name": "notas", "local": "sync-data/notas", "remote_path": "/R/notas",
             "exclude": ["*.tmp"]},
            {"name": "fotos", "local": "sync-data/fotos", "remote_path": "/R/fotos"}]),
        "un include de más": mkcfg([], pairs=[
            {"name": "notas", "local": "sync-data/notas", "remote_path": "/R/notas",
             "include": ["*.md"]},
            {"name": "fotos", "local": "sync-data/fotos", "remote_path": "/R/fotos"}]),
        "con llavero": model.parse_config({
            "defaults": {"remote": "nas"}, "keychain": {"base": "personal.kdbx"},
            "pair": [{"name": n, "local": f"sync-data/{n}", "remote_path": f"/R/{n}"}
                     for n in ("notas", "fotos")]}),
    }
    for que, otra in cambiadas.items():
        c(f"la firma cambia con {que}", instantanea.firma(otra) != instantanea.firma(cfg), True)
    flags = mkcfg([], pairs=[
        {"name": "notas", "local": "sync-data/notas", "remote_path": "/R/notas",
         "flags": {"transfers": 7}},
        {"name": "fotos", "local": "sync-data/fotos", "remote_path": "/R/fotos"}])
    c("pero no con un flag de rclone, que no cambia lo que se lee",
      instantanea.firma(flags), instantanea.firma(cfg))

# 7. cuándo vale: la huella
with sandbox() as raiz:
    cfg = preparar(("notas", "fotos"))
    notas, fotos = cfg.pairs
    inst = leer_aislado(cfg)
    c("la huella son rutas con fecha y tamaño, y el catálogo duplicado por su valor",
      (all(len(e) == 3 for e in inst.huella[:-1]), inst.huella[-1]),
      (True, ("catalogo duplicado", None)))
    c("recién leída, vale", inst.vigente(cfg), True)
    c("  y vale otra vez: preguntar no cambia nada", inst.vigente(cfg), True)

    c("otra config (una pareja de más): no vale", inst.vigente(mkcfg(["notas", "fotos", "docs"])),
      False)
    c("  (un modo cambiado): no vale", inst.vigente(cambiadas["otro modo"]), False)
    c("  (un exclude): no vale", inst.vigente(cambiadas["un exclude de más"]), False)

    # lo que escribe la propia ventana no caduca la lectura
    for nombre in ("ui_prefs.json", "ui.lock.json", "servicio.pide", "daemon.stop",
                   "ui_prefs.tmp"):
        (model.STATE_DIR / nombre).write_text("{}", encoding="utf-8")
    mueve_fecha(model.STATE_DIR / "ui_prefs.json")
    mueve_fecha(model.STATE_DIR)
    c("escribir ui_prefs.json, ui.lock.json, el buzón del servicio o un .tmp no la caduca",
      inst.vigente(cfg), True)

    c("tocar last_run.json la caduca (acaba una pasada)",
      caduca(inst, cfg, lambda i: results.apuntar("notas", 0, None)), True)
    inst = leer_aislado(cfg)
    c("  y una lectura nueva vuelve a valer", inst.vigente(cfg), True)

    c("tocar conflicts.json la caduca (el escaneo encontró otros)",
      caduca(inst, cfg, lambda i: conflicts.ruta_estado().write_text(
          '{"parejas": {"notas": []}}' + " " * i, encoding="utf-8")), True)
    inst = leer_aislado(cfg)

    from common import catalog, store
    # cada lectura del catálogo reescribe catalog.json: no caduca si no cambia lo que se lee
    store.write_json(catalog.cache_meta(), {"pulled_at": "2026-10-08 10:00:00", "endpoint": "nas:a"})
    inst = leer_aislado(cfg)
    store.write_json(catalog.cache_meta(), {"pulled_at": "2026-10-08 10:05:00", "endpoint": "nas:a"})
    mueve_fecha(catalog.cache_meta())
    c("una lectura del catálogo (reescribe catalog.json) no la caduca", inst.vigente(cfg), True)
    c("apuntar un catálogo duplicado la caduca (lo ve «Reparación»)",
      caduca(inst, cfg, lambda i: catalog.apuntar_duplicado(f"nas:/prdrive-catalog/pairs{i}.toml")),
      True)
    inst = leer_aislado(cfg)
    c("  y desapuntarlo también", caduca(inst, cfg, lambda i: catalog.apuntar_duplicado(None)),
      True)
    inst = leer_aislado(cfg)

    c("cambiar la carpeta de filtros la caduca",
      caduca(inst, cfg, lambda i: mueve_fecha(model.FILTERS_DIR)), True)
    inst = leer_aislado(cfg)

    c("crear algo en el workdir de una pareja la caduca (un .lck, un baseline apartado)",
      caduca(inst, cfg, lambda i: (fotos.workdir / f"otro{i}.lck").write_text("", encoding="utf-8")),
      True)
    inst = leer_aislado(cfg)

    c("  también si solo cambia la fecha del workdir",
      caduca(inst, cfg, lambda i: mueve_fecha(notas.workdir)), True)
    inst = leer_aislado(cfg)

    c("quitar un workdir la caduca (se apartó el baseline)",
      caduca(inst, cfg, lambda i: shutil.rmtree(notas.workdir, ignore_errors=True)), True)
    inst = leer_aislado(cfg)

    # sin holgura: la comparación es de igualdad
    c("la comparación es de igualdad: una fecha anterior también caduca",
      caduca(inst, cfg, lambda i: mueve_fecha(results.ruta_estado(), -5 - i)), True)

# 8. la lectura no deja a medias lo que regenera: lo hace antes de tomar la huella
with sandbox():
    cfg = mkcfg(["notas", "fotos"])
    for pair in cfg.pairs:
        pair.local_abs.mkdir(parents=True, exist_ok=True)
    c("sin ficheros de filtros todavía", sorted(p.name for p in model.FILTERS_DIR.iterdir()), [])
    inst = leer_aislado(cfg)
    c("leer los regenera",
      sorted(p.name for p in model.FILTERS_DIR.iterdir()), ["fotos.txt", "notas.txt"])
    c("  y no se queda sin valer por haberlos escrito él", inst.vigente(cfg), True)
    c("  sin fallos", inst.fallos, {})
    antes = instantanea.tomar_huella(cfg)
    leer_aislado(cfg)
    c("  una segunda lectura ya no escribe nada", instantanea.tomar_huella(cfg), antes)

    # el fallo de escribir no impide leer lo demás
    for p in model.FILTERS_DIR.iterdir():
        p.unlink()

    def sin_escribir(pair):
        raise PermissionError("solo lectura")

    with parchado((bisync, "filters_file_for", sin_escribir)):
        inst = leer_aislado(cfg)
    c("si no se pueden regenerar los filtros, consta y se lee lo demás",
      ("filtros" in inst.fallos, "solo lectura" in inst.fallos.get("filtros", ""),
       inst.huella is not None), (True, True, True))

# 9. la lectura compartida
with sandbox():
    cfg = preparar(("notas",))
    compartida = instantanea.Compartida()
    c("al principio no hay nada", (compartida.actual, compartida.para(cfg)), (None, None))
    inst = leer_aislado(cfg)
    avisos = []
    baja = compartida.suscribir(avisos.append)
    c("suscribir devuelve cómo darse de baja", callable(baja), True)
    compartida.poner(inst)
    c("poner la guarda y avisa a quien se suscribió", (compartida.actual, avisos), (inst, [inst]))
    c("`para` la da mientras vale", compartida.para(cfg), inst)
    c("  y no para otra config", compartida.para(mkcfg(["notas", "otra"])), None)
    c("  ni cuando ha cambiado el disco",
      caduca(inst, cfg, lambda i: results.apuntar("notas", 0, None))
      and compartida.para(cfg) is None, True)
    c("  aunque `actual` sigue siendo la última puesta", compartida.actual, inst)

    baja()
    segunda = leer_aislado(cfg)
    compartida.poner(segunda)
    c("tras darse de baja ya no avisa", avisos, [inst])
    baja()
    c("  darse de baja otra vez no hace nada", avisos, [inst])

    # varios suscritos; uno se da de baja al ser avisado; otro falla
    orden = []
    bajas = []

    def uno(i):
        orden.append(("uno", i is segunda))
        bajas[0]()

    def malo(i):
        orden.append("malo")
        raise ValueError("una ventana ya cerrada")

    def tres(i):
        orden.append("tres")

    bajas.append(compartida.suscribir(uno))
    compartida.suscribir(malo)
    compartida.suscribir(tres)
    error = None
    try:
        compartida.poner(segunda)
    except ValueError as e:
        error = e
    c("avisa a todos, también a los que quedan tras uno que falla",
      orden, [("uno", True), "malo", "tres"])
    c("  y el fallo se cuenta al final, no se esconde", type(error).__name__, "ValueError")
    orden.clear()
    try:
        compartida.poner(segunda)
    except ValueError:
        pass
    c("  quien se dio de baja durante el aviso no vuelve", orden, ["malo", "tres"])

raise SystemExit(c.report())
