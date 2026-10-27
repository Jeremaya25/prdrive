#!/usr/bin/env python3
"""Lo que decide la ventana «Servidor…»: qué se enseña, cómo se navega y cómo se dice un fallo.

Todo es puro: ningún test abre una ventana, arranca rclone ni toca la red. Lo
que se comprueba es lo que, si falla, se nota tarde y en el servidor de alguien:
que una respuesta de `operations/list` se lee bien (orden, tamaños, fechas con
nanosegundos y desfase, entradas rotas ignoradas), que un nombre con espacios,
acentos, `%`, `#` o `?` llega a rclone tal cual y la raíz llega vacía, que una
respuesta tardía de otra carpeta no se pinta, que una pareja solo marca en su
propio remote y solo cuando la ruta coincide entera (`/datos/notas2` no está
dentro de `/datos/notas`) y que cada fallo se dice en español.
"""

import os
import sys
import time
from datetime import datetime, timedelta, timezone

from _harness import Checks, mkcfg

from common.rcd import ErrorRc, RcdCaido
from ui import servidor

c = Checks("explorador del servidor: decisiones")

# entradas
LISTA = {"list": [
    {"Name": "zeta.txt", "IsDir": False, "Size": 4096, "ModTime": "2026-10-01T10:00:00.000000000+02:00"},
    {"Name": "Fotos de verano", "IsDir": True, "Size": -1, "ModTime": "2026-03-12T09:00:00Z"},
    {"Name": "año 100% #1?", "IsDir": True, "Size": -1, "ModTime": "2026-01-01T00:00:00Z"},
    {"IsDir": True}, "no soy un objeto"]}
ENTRADAS = servidor.entradas_de(LISTA)
c("carpetas primero, luego por nombre", [e.nombre for e in ENTRADAS],
  ["año 100% #1?", "Fotos de verano", "zeta.txt"])
c("una carpeta no tiene tamaño", ENTRADAS[0].tamano, None)
c("un archivo conserva el suyo", ENTRADAS[2].tamano, 4096)
c("las carpetas se saben carpetas", [e.es_carpeta for e in ENTRADAS], [True, True, False])
c("la fecha con nanosegundos y desfase se lee",
  ENTRADAS[2].fecha, datetime(2026, 10, 1, 10, 0, tzinfo=timezone(timedelta(hours=2))))
c("la fecha con Z se lee en UTC", ENTRADAS[1].fecha, datetime(2026, 3, 12, 9, 0, tzinfo=timezone.utc))
c("sin metadatos, los permisos no se conocen", (ENTRADAS[2].modo, ENTRADAS[2].uid, ENTRADAS[2].gid), (None, None, None))
c("una respuesta sin lista es una carpeta vacía",
  [servidor.entradas_de(x) for x in ({}, {"list": None}, [], None)], [()] * 4)
RARAS = servidor.entradas_de({"list": [
    {"Name": "a", "IsDir": False, "Size": -1, "ModTime": "ayer"},
    {"Name": "b", "IsDir": False, "Size": "grande"},
    {"Name": "", "IsDir": False}, {"Name": 7}]})
c("un tamaño negativo o raro es desconocido, una fecha ilegible también",
  [(e.nombre, e.tamano, e.fecha) for e in RARAS], [("a", None, None), ("b", None, None)])
c("sin distinguir mayúsculas",
  [e.nombre for e in servidor.entradas_de({"list": [
      {"Name": "b", "IsDir": False}, {"Name": "A", "IsDir": False}, {"Name": "c", "IsDir": False}]})],
  ["A", "b", "c"])

# qué se pide
c("la raíz se pide vacía", servidor.params_listado("nas", "/", False),
  {"fs": "nas:/", "remote": "", "opt": {"noMimeType": True}})
c("un nombre raro llega tal cual", servidor.params_listado("nas", "/año 100% #1?", False)["remote"],
  "año 100% #1?")
c("siempre el mismo fs", {servidor.params_listado("nas", r, True)["fs"] for r in ("/", "/a", "/a/b")},
  {"nas:/"})
c("con permisos lleva metadata", servidor.params_listado("nas", "/a", True)["opt"],
  {"noMimeType": True, "metadata": True})
c("sin permisos no la lleva", "metadata" in servidor.params_listado("nas", "/a", False)["opt"], False)
c("la ruta se normaliza", servidor.params_listado("nas", "a//b/", False)["remote"], "a/b")

# el desplegable de remotes
CONF = "[nas]\ntype = sftp\n[pen]\ntype = combine\n[alias1]\ntype = alias\n[b2]\ntype = b2\n[otro]\ntype = sftp\n"
c("los internos no salen y el de defaults va primero",
  list(servidor.remotes_de(CONF, "otro", "pen")), ["otro", "b2", "nas"])
c("sin el de defaults, por nombre", list(servidor.remotes_de(CONF, None, None)), ["b2", "nas", "otro"])
c("con su tipo", servidor.remotes_de(CONF, None, None)["nas"], "sftp")
c("el device_remote no sale aunque no sea combine",
  list(servidor.remotes_de(CONF, None, "nas")), ["b2", "otro"])
c("un defaults que no existe o es interno no se cuela",
  (list(servidor.remotes_de(CONF, "fantasma", None)), list(servidor.remotes_de(CONF, "pen", None))),
  (["b2", "nas", "otro"], ["b2", "nas", "otro"]))
c("sin conf no hay remotes", servidor.remotes_de("", "nas", None), {})

# navegar: la última petición gana
nav = servidor.Navegacion("nas")
c("empieza en la raíz y vacía", (nav.remote, nav.ruta, nav.entradas, nav.sin_acceso),
  ("nas", "/", (), set()))
a = nav.pedir("/a")
b = nav.pedir("/b")
c("los números crecen", b.numero > a.numero, True)
c("la petición lleva remote y ruta", (b.remote, b.ruta), ("nas", "/b"))
c("la respuesta vieja se descarta", nav.recibir(a, ENTRADAS), False)
c("y no cambia nada", (nav.ruta, nav.entradas), ("/", ()))
c("la última se acepta", nav.recibir(b, ENTRADAS), True)
c("y entonces cambia la ruta y la tabla", (nav.ruta, nav.entradas), ("/b", ENTRADAS))
c("hijo y padre parten de la ruta actual", (nav.hijo("x y"), nav.padre()), ("/b/x y", "/"))
c("la raíz no tiene padre más arriba", servidor.Navegacion("nas").padre(), "/")
vieja = nav.pedir("/c")
nueva = nav.pedir("/d")
c("un fallo de una petición vieja no dice nada",
  (nav.fallo(vieja, ErrorRc("permission denied", 500)), nav.sin_acceso), (None, set()))
c("un fallo de la última sí, y recuerda el permiso",
  (nav.fallo(nueva, ErrorRc("permission denied", 500)), nav.sin_acceso),
  ("No tienes permiso para ver esta carpeta.", {("nas", "/d")}))
otra = nav.pedir("/e")
c("un fallo que no es de permiso no marca candado",
  (nav.fallo(otra, ErrorRc("directory not found", 404)), nav.sin_acceso),
  ("Esa carpeta ya no existe en el servidor.", {("nas", "/d")}))
c("tras fallar, la carpeta de antes sigue en la tabla", (nav.ruta, nav.entradas), ("/b", ENTRADAS))

# cambiar de remote
cam = servidor.Navegacion("nas")
cam.recibir(cam.pedir("/x"), ENTRADAS)
p = cam.cambiar_remote("b2")
c("cambiar de remote pide la raíz de ese remote", (p.remote, p.ruta), ("b2", "/"))
c("y hasta que llega no cambia lo que se enseña", (cam.remote, cam.ruta), ("nas", "/x"))
c("un fallo del cambio deja el remote que se ve", (cam.fallo(p, ErrorRc("directory not found", 404)),
  cam.remote, cam.ruta), ("Esa carpeta ya no existe en el servidor.", "nas", "/x"))
c("y la siguiente petición va a ese remote, no al que falló",
  (cam.pedir(cam.hijo("y")).remote, cam.pedir(cam.hijo("y")).ruta), ("nas", "/x/y"))
p3 = cam.cambiar_remote("b2")
clic = cam.pedir(cam.hijo("z"))
c("un clic en una carpeta de la tabla vieja, con el cambio en vuelo, va al remote que se ve",
  (clic.remote, clic.ruta), ("nas", "/x/z"))
c("y sustituye al cambio de remote", (cam.recibir(p3, ()), cam.remote, cam.ruta, cam.entradas),
  (False, "nas", "/x", ENTRADAS))
p2 = cam.cambiar_remote("b2")
c("llegado, remote, ruta y entradas cambian a la vez", (cam.recibir(p2, ()), cam.remote, cam.ruta, cam.entradas),
  (True, "b2", "/", ()))
c("desde entonces se pide en el nuevo", cam.pedir("/w").remote, "b2")
c("el permiso se recuerda por remote y ruta",
  (cam.fallo(cam.pedir("/q"), ErrorRc("permission denied", 500)), cam.sin_acceso),
  ("No tienes permiso para ver esta carpeta.", {("b2", "/q")}))

# frases de error
FRASES = {
    "permiso": "No tienes permiso para ver esta carpeta.",
    "red": "No hay conexión con el servidor.",
    "no existe": "Esa carpeta ya no existe en el servidor.",
    "tiempo": "El servidor no ha contestado a tiempo.",
    "rcd": "Se ha perdido la conexión con rclone.",
}
for texto in ("dial tcp 10.0.0.2:22: connect: connection refused", "No Route To Host",
              "lookup nas: no such host", "network is unreachable"):
    c(f"sin red: {texto}", servidor.frase_error(ErrorRc(texto, 500)), FRASES["red"])
    c(f"es_sin_red: {texto}", servidor.es_sin_red(ErrorRc(texto, 500)), True)
c("es_sin_red no confunde un timeout ni un permiso",
  [servidor.es_sin_red(e) for e in (ErrorRc("i/o timeout", 500), ErrorRc("permission denied", 500),
                                    RcdCaido("rclone no contesta: connection refused"))],
  [False, False, False])
c("SFTP dice permiso a su manera", servidor.frase_error(ErrorRc("SSH_FX_PERMISSION_DENIED", 500)),
  FRASES["permiso"])
c("un 403 es permiso aunque no diga nada", servidor.frase_error(ErrorRc("", 403)), FRASES["permiso"])
c("es_de_permiso: texto, 403 y lo demás",
  [servidor.es_de_permiso(e) for e in (ErrorRc("Permission Denied", 500), ErrorRc("x", 403),
                                       ErrorRc("directory not found", 404), RcdCaido("permission denied"))],
  [True, True, False, False])
c("directory not found", servidor.frase_error(ErrorRc("error in ListJSON: directory not found", 404)),
  FRASES["no existe"])
c("un 404 a secas también", servidor.frase_error(ErrorRc("lo que sea", 404)), FRASES["no existe"])
c("timeout", servidor.frase_error(ErrorRc("read tcp: i/o timeout", 500)), FRASES["tiempo"])
c("rcd caído", servidor.frase_error(RcdCaido()), FRASES["rcd"])
c("rcd caído aunque su texto hable de conexiones",
  servidor.frase_error(RcdCaido("rclone no contesta: [Errno 111] Connection refused")), FRASES["rcd"])
c("lo desconocido se cita", servidor.frase_error(ErrorRc("algo raro", 500)), "rclone dice: algo raro")
c("también con una excepción cualquiera", servidor.frase_error(ValueError("mal")), "rclone dice: mal")

# parejas
cfg = mkcfg((), pairs=[
    {"name": "Notas", "local": "sync-data/notas", "remote_path": "/datos/notas", "remote": "nas"},
    {"name": "Otra", "local": "sync-data/otra", "remote_path": "/datos/notas", "remote": "b2"},
    {"name": "Raíz", "local": "sync-data/raiz", "remote_path": "datos//fotos/", "remote": "b2"}],
    defaults={"remote": "nas"})
c("las parejas de un remote, por ruta normalizada",
  (servidor.parejas_en(cfg, "nas"), servidor.parejas_en(cfg, "b2")),
  ({"/datos/notas": "Notas"}, {"/datos/notas": "Otra", "/datos/fotos": "Raíz"}))
c("marca la carpeta de la pareja en su remote", servidor.marca(cfg, "nas", "/datos/notas"), "Notas")
c("con la ruta sin normalizar", servidor.marca(cfg, "nas", "datos/notas/"), "Notas")
c("no la de otro remote", servidor.marca(cfg, "b2", "/datos/fotos"), "Raíz")
c("no marca lo que no es", (servidor.marca(cfg, "nas", "/datos"), servidor.marca(cfg, "nas", "/datos/fotos")),
  (None, None))
c("dentro de la pareja", servidor.dentro_de(cfg, "nas", "/datos/notas/2026"), "Notas")
c("y en la propia carpeta", servidor.dentro_de(cfg, "nas", "/datos/notas"), "Notas")
c("un prefijo de texto no es estar dentro", servidor.dentro_de(cfg, "nas", "/datos/notas2"), None)
c("fuera de todas", servidor.dentro_de(cfg, "nas", "/datos"), None)
c("dentro, pero en el remote de otra", servidor.dentro_de(cfg, "b2", "/datos/notas/x"), "Otra")
c("la raíz no está dentro de nadie", servidor.dentro_de(cfg, "nas", "/"), None)
cfg_raiz = mkcfg((), pairs=[{"name": "Todo", "local": "sync-data/todo", "remote_path": "/", "remote": "nas"}],
                 defaults={"remote": "nas"})
c("una pareja en la raíz del remote contiene todo el remote",
  (servidor.dentro_de(cfg_raiz, "nas", "/a/b"), servidor.dentro_de(cfg_raiz, "nas", "/"),
   servidor.dentro_de(cfg_raiz, "b2", "/a")), ("Todo", "Todo", None))

# lo que se escribe en la tabla
c("tamaños", [servidor.tamano_legible(n) for n in (None, 0, 4096, 1572864, 52428800, 1000, 1023)],
  ["—", "0 B", "4 KB", "1,5 MB", "50 MB", "1000 B", "1023 B"])
c("tamaños grandes", [servidor.tamano_legible(n) for n in (1024 ** 3, 5 * 1024 ** 4, 3 * 1024 ** 5)],
  ["1 GB", "5 TB", "3072 TB"])
c("el redondeo no enseña 1024 de una unidad",
  servidor.tamano_legible(1024 * 1024 - 1), "1 MB")
c("cuántos", [servidor.cuantos(n) for n in (0, 1, 3)], ["0 elementos", "1 elemento", "3 elementos"])
c("sin fecha, una raya", servidor.fecha_legible(None), "—")
SIN_HORA = "0001-01-01T00:00:00Z"  # lo que da rclone cuando no sabe la hora (carpetas en S3, GCS…)
for zona in ("Europe/Madrid", "America/New_York", "UTC"):
    anterior = os.environ.get("TZ")
    os.environ["TZ"] = zona
    if hasattr(time, "tzset"):
        time.tzset()
    try:
        raras = servidor.entradas_de({"list": [{"Name": "d", "IsDir": True, "ModTime": SIN_HORA},
                                               {"Name": "v", "IsDir": False, "Size": 1, "ModTime": "1969-12-31T23:59:59Z"}]})
        c(f"sin hora conocida ({zona}): la fecha es desconocida", [e.fecha for e in raras], [None, None])
        c(f"y se enseña una raya ({zona})", [servidor.fecha_legible(e.fecha) for e in raras], ["—", "—"])
        c(f"una fecha imposible de pasar a hora local tampoco rompe ({zona})",
          servidor.fecha_legible(datetime.fromisoformat(SIN_HORA)), "—")
    finally:
        if anterior is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = anterior
        if hasattr(time, "tzset"):
            time.tzset()
c("1970 ya vale", servidor.entradas_de({"list": [{"Name": "a", "IsDir": False, "ModTime": "1970-01-02T00:00:00Z"}]})[0].fecha is not None, True)
c("las fracciones de 1 a 9 cifras se leen",
  [servidor.entradas_de({"list": [{"Name": "a", "IsDir": False, "ModTime": f"2026-10-01T10:00:00.{'123456789'[:n]}Z"}]})[0].fecha
   for n in range(1, 10)],
  [datetime(2026, 10, 1, 10, 0, 0, int(("123456789"[:n] + "000000")[:6]), tzinfo=timezone.utc) for n in range(1, 10)])
FECHA = datetime(2026, 3, 5, 9, 7, tzinfo=timezone.utc)
c("la fecha en hora local, día/mes/año hh:mm",
  servidor.fecha_legible(FECHA), FECHA.astimezone().strftime("%d/%m/%Y %H:%M"))
c("una fecha sin zona se enseña como viene",
  servidor.fecha_legible(datetime(2026, 3, 5, 9, 7)), "05/03/2026 09:07")

# la fecha más allá de lo que se puede pasar a hora local
anterior = os.environ.get("TZ")
os.environ["TZ"] = "Europe/Madrid"
if hasattr(time, "tzset"):
    time.tzset()
try:
    LEJANA = datetime(9999, 12, 31, 23, 0, tzinfo=timezone(timedelta(hours=-5)))
    c("una fecha que desborda al pasarla a hora local se enseña como raya", servidor.fecha_legible(LEJANA), "—")
    c("y al leerla es desconocida",
      servidor.entradas_de({"list": [{"Name": "a", "IsDir": False, "ModTime": "9999-12-31T23:00:00-05:00"}]})[0].fecha, None)
finally:
    if anterior is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = anterior
    if hasattr(time, "tzset"):
        time.tzset()

# permisos: cuándo se piden
c("SFTP de hoy: ReadMetadata falso → no", servidor.pide_permisos({"Features": {"ReadMetadata": False}}, "sftp"), False)
c("SFTP con el PR → sí", servidor.pide_permisos({"Features": {"ReadMetadata": True}}, "sftp"), True)
c("local → sí", servidor.pide_permisos({"Features": {"ReadMetadata": True}}, "local"), True)
c("S3 lee metadatos por objeto → no", servidor.pide_permisos({"Features": {"ReadMetadata": True}}, "s3"), False)
c("crypt sobre SFTP → no", servidor.pide_permisos({"Features": {"ReadMetadata": True}}, "crypt"), False)
c("fsinfo raro → no",
  [servidor.pide_permisos(f, "sftp") for f in ({}, {"Features": None}, {"Features": {"ReadMetadata": "true"}}, None)],
  [False] * 4)

# permisos: qué se lee
META = lambda m: {"list": [{"Name": "d", "IsDir": True, "Size": -1, "ModTime": "2026-01-01T00:00:00Z", "Metadata": m}]}
c("mode del formato del PR", servidor.entradas_de(META({"mode": "40755", "uid": "1000", "gid": "100"}))[0].modo, 0o40755)
c("uid y gid decimales",
  (lambda e: (e.uid, e.gid))(servidor.entradas_de(META({"mode": "40755", "uid": "1000", "gid": "100"}))[0]), (1000, 100))
c("modos raros dan None", [servidor.entradas_de(META({"mode": v}))[0].modo for v in ("rwxr-xr-x", "0x1ed", "", "9", "-1", "12345670", 755)],
  [None] * 7)
c("uid y gid raros dan None", [(lambda e: (e.uid, e.gid))(servidor.entradas_de(META({"uid": v, "gid": v}))[0])
                              for v in ("root", "", "-1", "1.5", 3)], [(None, None)] * 5)
c("unos Metadata que no son un diccionario no rompen",
  [servidor.entradas_de(META(m))[0].modo for m in (None, "mode", ["mode"], 40755)], [None] * 4)

# permisos: la columna
c("la columna", [servidor.texto_permisos(m) for m in (None, 0o40755, 0o100600, 0o40700, 0o40007)],
  ["—", "755", "600", "700", "007"])

# permisos: el candado previo (yo soy el 1000)
def carpeta(modo, uid=1000):
    return servidor.Entrada("d", True, None, None, modo, uid, 100)
c("dueño sin r y x → sí", servidor.sin_acceso_previo(carpeta(0o40300), 1000), True)
c("dueño sin r → sí", servidor.sin_acceso_previo(carpeta(0o40100), 1000), True)
c("dueño con r y x → no", servidor.sin_acceso_previo(carpeta(0o40700), 1000), False)
c("dueño aunque otros puedan: es el dueño quien manda", servidor.sin_acceso_previo(carpeta(0o40305), 1000), True)
c("de otro y nadie puede → sí", servidor.sin_acceso_previo(carpeta(0o40700, 0), 1000), True)
c("de otro y solo r en grupo → sí", servidor.sin_acceso_previo(carpeta(0o40740, 0), 1000), True)
c("de otro y el grupo puede → no se marca", servidor.sin_acceso_previo(carpeta(0o40750, 0), 1000), False)
c("de otro y otros pueden → no", servidor.sin_acceso_previo(carpeta(0o40705, 0), 1000), False)
c("yo soy root → nunca", servidor.sin_acceso_previo(carpeta(0o40000, 5), 0), False)
c("sin saber quién soy → no", servidor.sin_acceso_previo(carpeta(0o40000), None), False)
c("un archivo → no", servidor.sin_acceso_previo(servidor.Entrada("f", False, 1, None, 0o100000, 1000, 100), 1000), False)
c("sin modo → no", servidor.sin_acceso_previo(carpeta(None), 1000), False)
c("sin dueño → no", servidor.sin_acceso_previo(carpeta(0o40000, None), 1000), False)
c("mi uid del stat", servidor.mi_uid_de({"item": {"Metadata": {"uid": "1000"}}}), 1000)
c("sin metadatos, None", servidor.mi_uid_de({"item": {}}), None)
c("un stat raro, None",
  [servidor.mi_uid_de(x) for x in (None, {}, {"item": None}, {"item": {"Metadata": None}},
                                   {"item": {"Metadata": {"uid": "root"}}}, [])], [None] * 6)

# mi uid: en `local` es el del proceso (rclone corre como nosotros), no el del cwd del rcd
_previo_uid = servidor.uid_del_proceso
servidor.uid_del_proceso = lambda: 1234
stat_ajeno = {"item": {"Metadata": {"uid": "0"}}}
c("en local, mi uid es el del proceso aunque el stat diga otro",
  servidor.mi_uid("local", stat_ajeno), 1234)
c("  y sin stat también", servidor.mi_uid("local", None), 1234)
c("en SFTP, el uid de la carpeta de inicio", servidor.mi_uid("sftp", stat_ajeno), 0)
c("  y sin stat, None", servidor.mi_uid("sftp", None), None)
c("el stat solo se pide fuera de local",
  [servidor.uid_se_pregunta_al_servidor(t) for t in ("local", "sftp", "webdav")],
  [False, True, True])
servidor.uid_del_proceso = lambda: None             # Windows: no hay getuid
c("en local sin getuid (Windows), None", servidor.mi_uid("local", stat_ajeno), None)
servidor.uid_del_proceso = _previo_uid
c("el uid real del proceso es un entero o None",
  servidor.uid_del_proceso() == (os.getuid() if hasattr(os, "getuid") else None), True)

# una pareja más honda gana a la que contiene todo
cfg_hondo = mkcfg((), pairs=[
    {"name": "Todo", "local": "sync-data/todo", "remote_path": "/", "remote": "nas"},
    {"name": "Notas", "local": "sync-data/notas", "remote_path": "/datos/notas", "remote": "nas"}],
    defaults={"remote": "nas"})
c("dentro_de da la pareja más honda, no la primera de la configuración",
  (servidor.dentro_de(cfg_hondo, "nas", "/datos/notas/2026"), servidor.dentro_de(cfg_hondo, "nas", "/otra")),
  ("Notas", "Todo"))

sys.exit(c.report())
