#!/usr/bin/env python3
"""
La raíz de un equipo: una carpeta del ordenador que es un prdrive más (fase 2).

Lo que se comprueba es lo que la hace distinta de una unidad, y nada más:

  * `tipo=equipo` en el fichero de control, y quién lo lee (`model`, `device`,
    `fleet`), sin que un penwatch viejo deje de encontrar el id.
  * La pareja de la raíz entera no vale, ni una que salga de ella: al parsear
    (`model.parse_config(equipo=True)` y `load_config()`), al elegir la carpeta
    (`pair_editor.ruta_local_relativa`) y en el asistente (`revisar_local`).
  * Qué carpetas valen de raíz (`examinar`), y el aviso de otro cliente de
    sincronización con ubicaciones de OneDrive y Dropbox falsas.
  * Instalar la raíz en un temporal, de verdad, con un rclone de mentira: lleva
    rclone, conexión y control, y no lleva lanzadores ni Python.
  * El `local` cambiado solo aquí (`device_config(locales=)`).
  * Lo que el agente recibe: la raíz en su lista con su ruta, y el acceso del
    menú.
"""

import json
import os
import sys
from pathlib import Path

from _harness import Checks, tmpdir

import tomllib

import penwatch
from common import equipo, fleet, model
from install import InstallError, agente as ia, deploy, device, profile, raiz_equipo
from install import rclone_bin, remote
from ui import pair_editor, tk_fleet, watch

c = Checks("la raíz de un equipo")


def config(*locales):
    return {"defaults": {"remote": "nas"},
            "pair": [{"name": f"p{i}", "local": l, "remote_path": f"/R/{i}"}
                     for i, l in enumerate(locales)]}


def rechaza(etiqueta, crudo, equipo_=True):
    try:
        model.parse_config(crudo, equipo=equipo_)
    except model.ConfigError as e:
        c(etiqueta, True, True)
        return str(e)
    c(etiqueta, "aceptado", "rechazado")
    return ""


# --- el config: la raíz entera no es una pareja --------------------------------
for local in (".", "", "./", "../fuera", "a/../../b", "/etc", "C:\\Users", "\\\\srv\\x"):
    rechaza(f"en un equipo, local = {local!r} no vale", config(local))
c("en un equipo, una carpeta de dentro sí",
  model.parse_config(config("Documentos/Obsidian", "sync-data/x"), equipo=True).names,
  ["p0", "p1"])
c("en una unidad, la raíz entera sigue valiendo", model.parse_config(config(".")).names,
  ["p0"])
texto = rechaza("el mensaje nombra la pareja", config("docs", "."))
c.contains("  y dice por qué", texto, "[p1] local = \".\" es la raíz entera")
c("problema_local_equipo: None si vale", model.problema_local_equipo("a/b"), None)

# tipo_raiz / es_equipo, del fichero de control. El nombre del fichero es una
# copia más de `penwatch.CONTROL_FILE` (ver AGENTS.md): que no se separen.
app = tmpdir("prdrive-tipo-") / ".prdrive"
c("model lee el mismo fichero de control que penwatch y fleet",
  (penwatch.CONTROL_FILE.name, fleet.control_file(app).name), ("PRDRIVE", "PRDRIVE"))
app.mkdir()
c("sin fichero de control: una unidad", model.tipo_raiz(app), model.TIPO_UNIDAD)
(app / "PRDRIVE").write_text("# x\nid=abc\n", encoding="utf-8")
c("sin línea tipo=: una unidad", model.es_equipo(app), False)
(app / "PRDRIVE").write_text("# x\nid=abc\nTipo= Equipo \n", encoding="utf-8")
c("tipo=equipo, sin distinguir mayúsculas", model.es_equipo(app), True)

# load_config() lee el tipo de la carpeta que corre
viejos = model.APP_DIR, model.CONFIG_FILE
model.APP_DIR, model.CONFIG_FILE = app, app / "sync_config.toml"
try:
    (app / "sync_config.toml").write_text(
        '[[pair]]\nname = "todo"\nlocal = "."\nremote_path = "/x"\n', encoding="utf-8")
    try:
        model.load_config()
        c("load_config() con tipo=equipo rechaza la raíz entera", "aceptado", "rechazado")
    except model.ConfigError as e:
        c.contains("load_config() con tipo=equipo rechaza la raíz entera", str(e),
                   "raíz entera")
    (app / "PRDRIVE").write_text("id=abc\n", encoding="utf-8")
    c("  y en una unidad la acepta", model.load_config().names, ["todo"])
finally:
    model.APP_DIR, model.CONFIG_FILE = viejos

# pair_editor: elegir la raíz entera con el diálogo, en un equipo
raiz_pe = tmpdir("prdrive-pe-")
(raiz_pe / ".prdrive").mkdir()
(raiz_pe / ".prdrive" / "PRDRIVE").write_text("id=x\ntipo=equipo\n", encoding="utf-8")
viejos = model.APP_DIR, model.DEVICE_ROOT
model.APP_DIR, model.DEVICE_ROOT = raiz_pe / ".prdrive", raiz_pe
try:
    try:
        pair_editor.ruta_local_relativa(raiz_pe)
        c("pair_editor: en un equipo, elegir la raíz entera se rechaza", ".", "error")
    except model.ConfigError:
        c("pair_editor: en un equipo, elegir la raíz entera se rechaza", True, True)
    c("  y una carpeta de dentro, relativa",
      pair_editor.ruta_local_relativa(raiz_pe / "Documentos" / "Obsidian"),
      "Documentos/Obsidian")
finally:
    model.APP_DIR, model.DEVICE_ROOT = viejos

# --- el fichero de control ------------------------------------------------------
raiz_c = tmpdir("prdrive-control-")
uid = device.ensure_control_file(raiz_c, renew=True, tipo=model.TIPO_EQUIPO)
c("ensure_control_file(tipo=equipo) lo escribe", device.control_tipo(raiz_c), "equipo")
c("  y penwatch sigue leyendo el id", penwatch.control_id(raiz_c), uid)
c("  sin renovar, se queda el id", device.ensure_control_file(
    raiz_c, tipo=model.TIPO_EQUIPO), uid)
raiz_u = tmpdir("prdrive-control-u-")
uid_u = device.ensure_control_file(raiz_u, renew=True)
c("una unidad no lleva la línea",
  "tipo=" in (raiz_u / device.CONTROL_FILE).read_text(encoding="utf-8"), False)
c("pasarla a equipo conserva el id",
  (device.ensure_control_file(raiz_u, tipo=model.TIPO_EQUIPO),
   device.control_tipo(raiz_u)), (uid_u, "equipo"))
# Una unidad de verdad, para lo que sigue.
raiz_u = tmpdir("prdrive-unidad-")
device.ensure_control_file(raiz_u, renew=True)

# --- otros clientes de sincronización -------------------------------------------
casa = tmpdir("prdrive-casa-")
onedrive = casa / "OneDrive - Empresa"
dropbox = casa / "Dropbox"
for var in raiz_equipo.VARIABLES_ONEDRIVE:
    os.environ.pop(var, None)
os.environ["OneDriveCommercial"] = str(onedrive)
(casa / ".dropbox").mkdir()
(casa / ".dropbox" / "info.json").write_text(
    json.dumps({"personal": {"path": str(dropbox)}, "business": "basura"}),
    encoding="utf-8")
viejo_home = os.environ.get("HOME")
os.environ["HOME"] = str(casa)
raiz_equipo.IS_WIN = False
try:
    c("carpetas_sincronizadas: la variable de OneDrive y el info.json de Dropbox",
      raiz_equipo.carpetas_sincronizadas(), [("OneDrive", onedrive), ("Dropbox", dropbox)])
finally:
    os.environ.pop("OneDriveCommercial")
    if viejo_home is not None:
        os.environ["HOME"] = viejo_home
raiz_equipo.carpetas_sincronizadas = lambda: [("OneDrive", onedrive)]
c("otro_cliente: una carpeta dentro de OneDrive",
  raiz_equipo.otro_cliente(onedrive / "notas"), f"OneDrive ({onedrive})")
c("  y una que contiene a OneDrive, también", raiz_equipo.otro_cliente(casa),
  f"OneDrive ({onedrive})")
c("  y una al lado, no", raiz_equipo.otro_cliente(casa / "OneDriveNo"), None)

# --- ¿vale esta carpeta? -------------------------------------------------------
equipo.DIR = tmpdir("prdrive-agente-") / "prdrive"
nueva = tmpdir("prdrive-raiz-") / "PRDRIVE"
c("examinar: una que no existe es nueva", raiz_equipo.examinar(nueva).estado,
  raiz_equipo.NUEVA)
c("  relativa no vale", raiz_equipo.examinar("PRDRIVE").vale, False)
fichero = tmpdir("prdrive-f-") / "f"
fichero.write_text("x", encoding="utf-8")
c("  un fichero no vale", raiz_equipo.examinar(fichero).vale, False)
c("  dentro de la carpeta del agente no vale",
  raiz_equipo.examinar(equipo.DIR / "x").vale, False)
c("  ni una que la contenga",
  raiz_equipo.examinar(equipo.DIR.parent).vale, False)
c("  una unidad prdrive no vale", raiz_equipo.examinar(raiz_u).vale, False)
ya = raiz_equipo.examinar(raiz_c)
c("  la raíz de un equipo se reinstala con su id",
  (ya.estado, uid[:8] in ya.texto), (raiz_equipo.YA_EQUIPO, True))
con_cosas = tmpdir("prdrive-cosas-")
(con_cosas / "algo.txt").write_text("x", encoding="utf-8")
ex = raiz_equipo.examinar(con_cosas)
c("  con cosas: se puede, en ámbar", (ex.estado, ex.vale, ex.aviso),
  (raiz_equipo.CON_COSAS, True, True))
ex = raiz_equipo.examinar(con_cosas, raiz_equipo.PERSONAL)
c("  la personal: se puede, sin ámbar", (ex.vale, ex.aviso), (True, False))
ex = raiz_equipo.examinar(onedrive / "PRDRIVE")
c("  dentro de OneDrive: ámbar y lo nombra", (ex.vale, ex.aviso, "OneDrive" in ex.texto),
  (True, True, True))

# --- el local de cada pareja, visto desde la raíz --------------------------------
info = raiz_equipo.revisar_local(casa, "\\Documentos\\Obsidian\\")
c("revisar_local normaliza y resuelve", (info.local, info.ruta, info.error),
  ("Documentos/Obsidian", casa / "Documentos" / "Obsidian", None))
c("  la raíz entera es un error", bool(raiz_equipo.revisar_local(casa, ".").error), True)
c("  salir de la raíz también", bool(raiz_equipo.revisar_local(casa, "../x").error),
  True)
c("  dentro de OneDrive, un aviso",
  raiz_equipo.revisar_local(casa, "OneDrive - Empresa/x").avisos[0].startswith(
      "ya la sincroniza OneDrive"), True)
(casa / "Musica").mkdir()
(casa / "Musica" / "a.mp3").write_text("x", encoding="utf-8")
c("  una carpeta con cosas, un aviso de que se juntan",
  raiz_equipo.revisar_local(casa, "Musica").avisos,
  ("ya existe y tiene cosas: la inicialización las junta con lo del remoto",))
raiz_equipo.carpetas_sincronizadas = lambda: []

# --- instalar la raíz, de verdad, con un rclone de mentira -----------------------
RCLONE = tmpdir("prdrive-rc-") / "rclone"
RCLONE.write_bytes(b"\x7fELF")
pedidos = []
rclone_bin.rclone_for = lambda plat, progreso=None, allow_download=True: (
    pedidos.append(plat.clave) or RCLONE)
PERFIL = profile.from_form("nas", {"type": "sftp", "host": "nas.example"})
escrito, ident = raiz_equipo.instalar(nueva, PERFIL)
from install import platforms  # noqa: E402
anfitrion = platforms.host()
c("instalar: rclone solo para este equipo", pedidos, [anfitrion.clave])
c("  con tipo=equipo y el id que devuelve",
  (device.control_tipo(nueva), device.control_id(nueva)), ("equipo", ident))
c("  el código, la conexión y rclone",
  all((nueva / ".prdrive" / f).exists() for f in ("sync.py", "runsync.py", "rclone.conf",
                                                   "common", "ui")), True)
c("  sin lanzadores, ni guía, ni Python",
  [p.name for p in nueva.iterdir()], [".prdrive"])
c("  ni runtime", (nueva / ".prdrive" / "runtime").exists(), False)
_, otra_vez = raiz_equipo.instalar(nueva, PERFIL)
c("reinstalar conserva el id: el agente la tiene por él", otra_vez, ident)
try:
    raiz_equipo.instalar(raiz_u, PERFIL)
    c("instalar encima de una unidad se niega", "instalado", "InstallError")
except InstallError:
    c("instalar encima de una unidad se niega", True, True)

# --- el config de la raíz: el local cambiado aquí --------------------------------
CAT = remote.parse_catalog(
    '[defaults]\nremote = "nas"\n\n'
    '[[pair]]\nname = "todo"\nlocal = "."\nremote_path = "/t"\nmode = "up-mirror"\n\n'
    '[[pair]]\nname = "docs"\nlocal = "sync-data/docs"\nremote_path = "/d"\n')
try:
    deploy.write_device_config(nueva, CAT, ["todo", "docs"])
    c("write_device_config en un equipo: la raíz entera no se escribe", "escrito", "error")
except model.ConfigError:
    c("write_device_config en un equipo: la raíz entera no se escribe", True, True)
destino = deploy.write_device_config(nueva, CAT, ["todo", "docs"],
                                     locales={"todo": "copia", "docs": "sync-data/docs"})
escrito_cfg = tomllib.loads(destino.read_text(encoding="utf-8"))
c("  con su local cambiado, sí; lo demás, como en el catálogo",
  [(p["name"], p["local"], p["remote_path"]) for p in escrito_cfg["pair"]],
  [("todo", "copia", "/t"), ("docs", "sync-data/docs", "/d")])
c("  y el catálogo no se toca", CAT.pair("todo")["local"], ".")
c("local_dirs con los locales de aquí",
  deploy.local_dirs(CAT, ["todo", "docs"], {"todo": "copia"}),
  [Path("copia"), Path("sync-data/docs")])
c("en una unidad, device_config sigue aceptando la raíz",
  deploy.device_config(CAT, ["todo"])["pair"][0]["local"], ".")

# --- verificar: sin lanzadores ni Python que pedirle -----------------------------
filas = {k.etiqueta: k for k in raiz_equipo.verificar(nueva, ["todo", "docs"])}
c("verificar: control con «raíz del equipo»", filas["Fichero de control"].detalle.endswith(
    "raíz del equipo"), True)
c("  el config se lee con las reglas del equipo", filas["El config se lee"].ok, True)
c("  sin fila de lanzador ni de Python",
  [e for e in filas if e.startswith(("Lanzador", "Python para"))], [])

# --- la nota de la flota ------------------------------------------------------
nota = fleet.nota_de(nueva / ".prdrive", "Mi portátil", "0.4.0", "ok")
c("fleet: la nota de la raíz lleva tipo = equipo", (nota.tipo, nota.es_equipo),
  ("equipo", True))
c("  y vuelve igual del texto", fleet.parse(fleet.dumps(nota)), nota)
nota_u = fleet.nota_de(raiz_u / ".prdrive", "Azul", "0.4.0", "ok")
c("  la de una unidad no escribe la clave", "tipo" in fleet.dumps(nota_u), False)
c("tk_fleet: la ficha dice que es de un equipo",
  tk_fleet.ficha(nota, "")[1].lineas[0].texto, tk_fleet.EN_UN_EQUIPO)

# --- la flota, para el paso «Unidades» ----------------------------------------


class RcFlota:
    """`copy` de la carpeta devices/: deja las notas en el destino."""

    def __init__(self, rc=0):
        self.rc, self.pedido = rc, []

    def run(self, *args, capture=False, timeout=None):
        self.pedido.append(args)
        destino = Path(args[2])
        for disp in (nota, nota_u):
            (destino / f"{disp.id}.toml").write_text(fleet.dumps(disp), encoding="utf-8")
        (destino / "roto.toml").write_text("esto no es toml [", encoding="utf-8")

        class R:
            returncode = self.rc
        return R()


rc = RcFlota()
flota = raiz_equipo.de_la_flota(rc, "nas:/prdrive-catalog/pairs.toml")
c("de_la_flota: una sola llamada, a devices/",
  [a[:2] for a in rc.pedido], [("copy", "nas:/prdrive-catalog/devices")])
c("  las unidades, sin las raíces de otros equipos ni las rotas",
  [d.id for d in flota], [nota_u.id])
c("  sin red, ninguna", raiz_equipo.de_la_flota(RcFlota(rc=1), "nas:/c/pairs.toml"), [])

# --- lo que recibe el agente ----------------------------------------------------
equipo.DIR = tmpdir("prdrive-agente-2-")
RAIZ = equipo.Unidad(ident, equipo.DAEMON, "Mi portátil", str(nueva))
ia.aplicar_unidades({"u" * 32: (equipo.SYNC, "Azul")}, 90.0, RAIZ)
aj = equipo.leer_ajustes()
c("aplicar_unidades sin agente.json: la raíz entra con su ruta",
  (aj.raices, sorted(aj.unidades)), ({ident: RAIZ}, sorted([ident, "u" * 32])))
c("  y se relee igual", equipo.desde_dict(equipo.a_dict(aj)), aj)
c("candidatas() no ofrece la raíz como unidad",
  [x.id for x in ia.candidatas() if x.id == ident], [])
otra = equipo.Unidad("r" * 32, equipo.DAEMON, "Otra", "/home/x/PRDRIVE")
ia.aplicar_unidades({}, 90.0, otra)
pedido = [json.loads(l) for l in equipo.buzon().read_text(encoding="utf-8").splitlines()]
c("con agente.json, la raíz se pide por el buzón (PIDE_RAIZ)",
  [(p["pide"], p["id"], p["ruta"], p["modo"]) for p in pedido],
  [(equipo.PIDE_RAIZ, "r" * 32, "/home/x/PRDRIVE", equipo.DAEMON)])
c("  y la verificación la da por pedida", ia.raiz_pedida("r" * 32), True)
c("  la que no se ha pedido, no", ia.raiz_pedida("z" * 32), False)
equipo.buzon().unlink()
ia.aplicar_unidades({}, 90.0, RAIZ)
c("  una raíz que ya está igual no se vuelve a pedir", equipo.buzon().exists(), False)

# El acceso del menú (Linux: un .desktop visible, con el Exec escapado).
MENU = tmpdir("prdrive-menu-") / "applications" / "prdrive.desktop"
ia.acceso_menu = lambda: MENU
ia.IS_WIN = False
prep = ia.Preparado(equipo.DIR / "agente" / "0.4.0", Path("/opt/py dir/bin/python3"), "s")
msg = ia.poner_menu(prep)
texto = MENU.read_text(encoding="utf-8")
c("poner_menu: lo dice", msg.startswith("Acceso «prdrive»"), True)
c("  abre con agente.py abrir, con el Python del agente",
  f'Exec="/opt/py dir/bin/python3" "{equipo.DIR}/agente/0.4.0/agente.py" "abrir"'
  in texto, True)
c("  visible en el menú (sin NoDisplay)", "NoDisplay" in texto, False)
c("quitar_menu lo borra", (ia.quitar_menu() is not None, MENU.exists()), (True, False))
c("  y sin menú no dice nada", ia.quitar_menu(), None)

# Desinstalar nunca borra la raíz, y lo dice.
ia.desregistrar = lambda: "sin registro"
ia.parar_agente = lambda: None
msgs = ia.desinstalar()
c("desinstalar dice dónde sigue la raíz",
  any(str(nueva) in m and "sigue" in m for m in msgs), True)
c("  y no la toca", (nueva / ".prdrive" / "PRDRIVE").is_file(), True)

# --- la línea de la ventana -----------------------------------------------------
c("watch: la raíz del equipo, atendida por el agente",
  watch.linea(watch.Resumen("agente_raiz", equipo.DAEMON)).texto,
  "Es la carpeta de este equipo: la sincroniza el agente, en segundo plano.")
c("  y eso cuenta como que la vigila",
  watch.Resumen("agente_raiz", equipo.DAEMON).vigila_este, True)

sys.exit(c.report())
