#!/usr/bin/env python3
"""Cambios locales (`watch = true`): la clave, la foto de la carpeta y las reglas.

Tres capas, de abajo arriba:
- `model`: `watch` se lee una vez, solo vale donde el local es origen (bisync,
  up, up-mirror) y de otro tipo que un booleano se rechaza al parsear;
  `pide_watch()` es la misma regla sin lanzar, para quien lee el TOML a pelo.
- `huella`: la foto barata de una carpeta, sobre un directorio temporal de
  verdad: ve renombrados y cambios de contenido, ignora `.prversions/`, no
  sigue enlaces, se corta en el tope y devuelve `None` si no puede.
- `planificador`: las reglas, con un reloj de mentira: la calma, la ráfaga, la
  separación, el tope, la moderación, la foto de después de una pasada.
"""

import math
import os
import sys
from pathlib import Path

from _harness import Checks, tmpdir

from common import config_file, huella, model
from common import planificador as pl
from common.model import ConfigError
from ui import pair_editor

c = Checks("cambios locales de una pareja (watch)")


def pareja(extra=None):
    """Una pareja bisync con lo que se le añada encima."""
    raw = {"name": "docs", "local": "sync-data/docs", "remote_path": "/docs",
           "mode": "bisync"}
    raw.update(extra or {})
    return model.parse_config({"defaults": {"remote": "nas"}, "pair": [raw]}).pairs[0]


def falla(extra, *trozos):
    """Dice si esa pareja se rechaza y el mensaje nombra todos los `trozos`."""
    try:
        pareja(extra)
    except ConfigError as e:
        return all(t in str(e) for t in trozos)
    return False


# ---------------------------------------------------------------------------
# 1. model: la clave
# ---------------------------------------------------------------------------
c("sin la clave, no vigila", pareja().watch, False)
c("watch = false, no vigila", pareja({"watch": False}).watch, False)
for modo in ("bisync", "up", "up-mirror"):
    c(f"watch = true se acepta en '{modo}'", pareja({"watch": True, "mode": modo}).watch, True)
for modo in ("down", "down-mirror"):
    c(f"watch = true se rechaza en '{modo}' y el mensaje dice cuál", falla(
        {"watch": True, "mode": modo}, "'watch'", modo, "bisync, up, up-mirror"), True)
    c(f"watch = false vale en '{modo}'", pareja({"watch": False, "mode": modo}).watch, False)
for malo in ("true", "yes", 1, 0, ["x"], {"a": 1}, 1.0, None):
    c(f"watch = {malo!r} no es un booleano: se rechaza", falla({"watch": malo}, "'watch'"), True)
c("el modo por omisión (bisync) también admite watch",
  model.parse_config({"defaults": {"remote": "nas"}, "pair": [
      {"name": "a", "local": "a", "remote_path": "/a", "watch": True}]}).pairs[0].watch, True)

# lo que lee el agente: el TOML a pelo, sin lanzar
RAW = {"name": "a", "local": "a", "remote_path": "/a"}
for etiqueta, extra, esperado in (
        ("true en bisync", {"watch": True, "mode": "bisync"}, True),
        ("true sin modo (bisync)", {"watch": True}, True),
        ("true en up", {"watch": True, "mode": "up"}, True),
        ("true en up-mirror", {"watch": True, "mode": "up-mirror"}, True),
        ("true en down", {"watch": True, "mode": "down"}, False),
        ("true en down-mirror", {"watch": True, "mode": "down-mirror"}, False),
        ("true en un modo que no existe", {"watch": True, "mode": "otro"}, False),
        ("true con el modo mal escrito (lista)", {"watch": True, "mode": ["up"]}, False),
        ("false", {"watch": False}, False),
        ("el string 'true'", {"watch": "true"}, False),
        ("el número 1", {"watch": 1}, False),
        ("sin la clave", {}, False)):
    c(f"pide_watch: {etiqueta}", model.pide_watch({**RAW, **extra}), esperado)

# la clave sobrevive al TOML y a la ventana de parejas
raw = {"defaults": {"remote": "nas"}, "pair": [{**RAW, "mode": "up", "watch": True}]}
c("watch se escribe y se relee igual (dumps_checked)",
  "watch = true" in config_file.dumps_checked(raw), True)
anterior = raw["pair"][0]
c("el formulario de parejas no pierde watch al guardar otra cosa",
  pair_editor.merge_form(anterior, {"local": "b"}).get("watch"), True)

# ---------------------------------------------------------------------------
# 2. huella: la foto de una carpeta
# ---------------------------------------------------------------------------


def escribe(ruta: Path, texto="x", mtime=None):
    """Crea un fichero (y sus carpetas), con el mtime que se pida."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(texto, encoding="utf-8")
    if mtime is not None:
        os.utime(ruta, ns=(mtime, mtime))


MTIME = 1_700_000_000_000_000_000
base = tmpdir("prdrive-huella-")
escribe(base / "a.txt", "uno", MTIME)
escribe(base / "sub" / "b.txt", "dos", MTIME)
(base / "vacia").mkdir()
h0 = huella.de_carpeta(base)
c("cuenta ficheros y carpetas", h0.entradas, 4)
c("sin tocar nada, la misma foto", huella.de_carpeta(base), h0)

escribe(base / "a.txt", "uno", MTIME)
c("reescribir lo mismo con el mismo mtime no es un cambio", huella.de_carpeta(base), h0)
escribe(base / "a.txt", "uno", MTIME + 5_000_000_000)
c("el mismo contenido con otro mtime sí", huella.de_carpeta(base) != h0, True)
escribe(base / "a.txt", "tres", MTIME)
c("otro tamaño con el mismo mtime sí", huella.de_carpeta(base) != h0, True)
escribe(base / "a.txt", "uno", MTIME)
c("y al volver a como estaba, la foto de antes", huella.de_carpeta(base), h0)

(base / "a.txt").rename(base / "z.txt")
c("renombrar un fichero cambia la foto (lo que un máximo o una suma no verían)",
  huella.de_carpeta(base) != h0, True)
(base / "z.txt").rename(base / "a.txt")
escribe(base / "x1.bin", "ab", MTIME)
escribe(base / "x2.bin", "cd", MTIME)
h1 = huella.de_carpeta(base)
(base / "x1.bin").unlink()
(base / "x2.bin").unlink()
escribe(base / "y1.bin", "ab", MTIME)
escribe(base / "y2.bin", "cd", MTIME)
c("cambiar dos ficheros por otros del mismo tamaño y mtime, con otro nombre, cambia la foto",
  huella.de_carpeta(base) != h1, True)
(base / "y1.bin").unlink()
(base / "y2.bin").unlink()

(base / "nueva").mkdir()
c("una carpeta vacía nueva cambia la foto", huella.de_carpeta(base) != h0, True)
(base / "nueva").rmdir()
c("y al quitarla vuelve", huella.de_carpeta(base), h0)

# .prversions/ no cuenta, solo en la raíz de la pareja
escribe(base / model.VERSIONS_DIR / "docs" / "a~20260922-093000.txt", "viejo", MTIME)
c(".prversions/ de la raíz no cuenta", huella.de_carpeta(base), h0)
escribe(base / "sub" / model.VERSIONS_DIR / "a.txt", "no es la de la pareja", MTIME)
c("una carpeta con ese nombre más adentro sí", huella.de_carpeta(base) != h0, True)
(base / "sub" / model.VERSIONS_DIR / "a.txt").unlink()
(base / "sub" / model.VERSIONS_DIR).rmdir()

# no sigue enlaces fuera de la carpeta
fuera = tmpdir("prdrive-fuera-")
escribe(fuera / "secreto.txt", "no debe verse", MTIME)
enlace = True
try:
    (base / "salida").symlink_to(fuera, target_is_directory=True)
except (OSError, NotImplementedError):
    enlace = False
if enlace:
    h_enlace = huella.de_carpeta(base)
    c("un enlace a una carpeta cuenta como una entrada y no se entra en él",
      h_enlace.entradas, h0.entradas + 1)
    escribe(fuera / "otro.txt", "tampoco", MTIME)
    c("  y lo que cambia al otro lado no cambia la foto", huella.de_carpeta(base), h_enlace)
    (base / "salida").unlink()
    c("quitar el enlace deja la foto de antes", huella.de_carpeta(base), h0)
else:
    print("  (saltado) enlaces simbólicos: este sistema no deja crearlos")

# el tope
base_grande = tmpdir("prdrive-grande-")
for i in range(12):
    escribe(base_grande / f"f{i:02}.txt", str(i), MTIME)
c("justo en el tope cabe", huella.de_carpeta(base_grande, tope=12).entradas, 12)
corta = huella.de_carpeta(base_grande, tope=5)
c("pasado el tope se corta y dice que no cabe", corta.entradas > 5, True)
c("  y no se molesta en firmar", corta.firma, 0)

# lo que no se puede mirar
c("una carpeta que no existe no tiene foto", huella.de_carpeta(base / "no-existe"), None)
c("un fichero donde se esperaba una carpeta tampoco", huella.de_carpeta(base / "a.txt"), None)

real = os.scandir


def retirada(ruta, *a, **k):
    """`scandir` de una unidad que se retira: la raíz va y la subcarpeta falla con EIO."""
    if str(ruta).endswith("sub"):
        raise OSError(5, "Input/output error")
    return real(ruta, *a, **k)


os.scandir = retirada
try:
    c("un error de entrada/salida a medias invalida la foto entera",
      huella.de_carpeta(base), None)
finally:
    os.scandir = real


def se_va_la_raiz(ruta, *a, **k):
    """`scandir` donde la subcarpeta ya no está (FileNotFoundError) y la raíz tampoco."""
    if str(ruta).endswith("sub"):
        raise FileNotFoundError(2, "no such file")
    return real(ruta, *a, **k)


os.scandir = se_va_la_raiz
real_stat = os.stat
try:
    c("una subcarpeta que desaparece (lo normal mientras alguien trabaja) se salta",
      huella.de_carpeta(base).entradas, h0.entradas - 1)

    def raiz_muerta(ruta, *a, **k):
        if str(ruta) == str(base):
            raise FileNotFoundError(2, "no such file")
        return real_stat(ruta, *a, **k)

    os.stat = raiz_muerta
    c("pero si al terminar la propia carpeta ya no está, no hay foto",
      huella.de_carpeta(base), None)
finally:
    os.scandir = real
    os.stat = real_stat

# ---------------------------------------------------------------------------
# 3. planificador: las reglas, con un reloj de mentira
# ---------------------------------------------------------------------------
T0 = 1_000_000.0
MIN = 60.0
P = pl.Politica(mirar_maximo=pl.HORA)         # que el minuto de siempre no tape lo que toca
V = pl.PoliticaCambios()
c("los valores de fábrica: sondeo 10 s, calma 20 s, separación 2 min, tope 20 000",
  (V.sondeo, V.calma, V.separacion, V.tope_entradas), (10.0, 20.0, 120.0, 20_000))

DOCS = ("equipo", "docs")
FOTOS = ("equipo", "fotos")
RAIZ = pl.Raiz("equipo", (pl.Pareja("docs", "nas", vigila=True), pl.Pareja("fotos", "nas")),
               30 * MIN)
# Las dos acabaron una pasada hace cinco minutos: el intervalo (30 min) no toca.
HECHAS = {DOCS: pl.Marca(T0 - 5 * MIN), FOTOS: pl.Marca(T0 - 5 * MIN)}
H1 = pl.Huella(10, 111)
H2 = pl.Huella(10, 222)
H3 = pl.Huella(11, 333)


def dec(vig, ahora, raices=(RAIZ,), marcas=None, entorno=pl.Entorno(), **kw):
    """Pide una decisión con las parejas vigiladas que se den."""
    return pl.decidir(raices, HECHAS if marcas is None else marcas, entorno, ahora, P,
                      vigiladas=vig, **kw)


def que(d):
    """Devuelve `(raíz, pareja)` de la tarea decidida, o `None`."""
    return None if d.tarea is None else (d.tarea.raiz, d.tarea.pareja)


# observar
v = pl.observar(pl.Vigilada(), H1, T0)
c("la primera foto es la de partida: no hay cambio", (v.huella, v.cambio, v.revisada),
  (H1, None, T0))
v = pl.observar(v, H1, T0 + 10)
c("la misma foto: nada que ver, y se apunta que se miró", (v.cambio, v.revisada), (None, T0 + 10))
v = pl.observar(v, H2, T0 + 20)
c("otra foto: cambio, a la hora en que se vio", (v.huella, v.cambio), (H2, T0 + 20))
v = pl.observar(v, None, T0 + 30)
c("sin foto (unidad retirada a medias) no es un cambio ni borra lo sabido",
  (v.huella, v.cambio, v.revisada), (H2, T0 + 20, T0 + 30))
v = pl.observar(pl.Vigilada(H1, None, T0), None, T0 + 10)
c("sin foto y sin cambio pendiente, sigue sin haberlo", v.cambio, None)

# la calma
cambio = T0
pend = {DOCS: pl.Vigilada(H2, cambio, cambio)}
c("el cambio de hace 19 s todavía no toca", que(dec(pend, cambio + 19)), None)
d = dec(pend, cambio + 19)
c("  y se vuelve a mirar justo cuando vence la calma (1 s más)", d.mirar_en, 1.0)
d = dec(pend, cambio + 20)
c("a los 20 s de calma, la pasada de esa pareja", que(d), DOCS)
c("  es una pasada corriente adelantada: no es urgente", d.tarea.urgente, False)
c("  y dice que la han adelantado los cambios", d.tarea.por_cambios, True)

# una ráfaga es una sola pasada
v = pl.Vigilada(H1, None, T0)
for i, huella_i in enumerate((H2, H3, pl.Huella(12, 444)), start=1):
    v = pl.observar(v, huella_i, T0 + 15 * i)           # un fichero nuevo cada 15 s
c("una ráfaga que no se calma no dispara a los 20 s del primer cambio",
  que(dec({DOCS: v}, T0 + 15 + 20)), None)
c("  tampoco a los 20 s del segundo", que(dec({DOCS: v}, T0 + 30 + 20)), None)
c("  dispara a los 20 s del último", que(dec({DOCS: v}, T0 + 45 + 20)), DOCS)

# la separación
reciente = {DOCS: pl.Marca(T0 - 30), FOTOS: pl.Marca(T0 - 5 * MIN)}
pend = {DOCS: pl.Vigilada(H2, T0 - 25, T0)}
c("con la última pasada de hace 30 s, el cambio calmado espera a la separación",
  que(dec(pend, T0, marcas=reciente)), None)
c("  toca 2 min después de aquella pasada, no 20 s después del cambio",
  pl.toca_por_cambios(pend[DOCS], reciente[DOCS]), T0 - 30 + 120)
c("  y a esa hora, la pasada", que(dec(pend, T0 - 30 + 120, marcas=reciente)), DOCS)
c("  mirando justo entonces: faltan 90 s", dec(pend, T0, marcas=reciente).mirar_en, 90.0)

# el intervalo manda si llega antes
vencida = {DOCS: pl.Marca(T0 - 31 * MIN), FOTOS: pl.Marca(T0 - 5 * MIN)}
d = dec({DOCS: pl.Vigilada(H2, T0 - 25, T0)}, T0, marcas=vencida)
c("si el intervalo ya había vencido, la pasada es la del intervalo", que(d), DOCS)
c("  y no se dice que la hayan adelantado los cambios", d.tarea.por_cambios, False)
nunca = dec({DOCS: pl.Vigilada(H2, T0 - 25, T0)}, T0, marcas={})
c("una pareja que nunca se ha intentado toca ya, por su intervalo",
  (que(nunca), nunca.tarea.por_cambios), (DOCS, False))

# solo lo que lo pide, y solo mientras no falla
c("una pareja sin watch no se adelanta aunque haya cambio pendiente",
  que(dec({FOTOS: pl.Vigilada(H2, T0 - 60, T0)}, T0)), None)
c("sin estado de vigilancia no hay nada pendiente", que(dec({}, T0 + 3600 * 0.4)), None)
fallando = {DOCS: pl.Marca(T0 - 5 * MIN, 2), FOTOS: pl.Marca(T0 - 5 * MIN)}
c("una pareja que está fallando no se adelanta: la espera creciente se respeta",
  que(dec({DOCS: pl.Vigilada(H2, T0 - 60, T0)}, T0, marcas=fallando)), None)
c("  y su cambio sigue pendiente para la pasada que le toque",
  pl.toca_por_cambios(pl.Vigilada(H2, T0 - 60, T0), fallando[DOCS]), math.inf)
c("una pareja sin cambio pendiente no tiene hora por cambios",
  pl.toca_por_cambios(pl.Vigilada(H2, None, T0), HECHAS[DOCS]), math.inf)
c("una abandonada tampoco", pl.toca_por_cambios(
    pl.Vigilada(None, T0 - 60, T0, abandonada=True), HECHAS[DOCS]), math.inf)

# la moderación la retiene como a cualquier otra pasada
lista = {DOCS: pl.Vigilada(H2, T0 - 60, T0)}
c("sin moderación, la pasada toca", que(dec(lista, T0)), DOCS)
for etiqueta, entorno, motivo in (
        ("en pausa", pl.Entorno(pausado=True), "en pausa"),
        ("con batería (la política no lo admite)", pl.Entorno(con_bateria=True, bateria=80), None),
        ("con la batería baja", pl.Entorno(con_bateria=True, bateria=10), "batería"),
        ("en red de uso medido", pl.Entorno(red_medida=True), "red de uso medido")):
    politica = pl.Politica(mirar_maximo=pl.HORA, con_bateria=not etiqueta.startswith("con batería ("))
    d = pl.decidir([RAIZ], HECHAS, entorno, T0, politica, vigiladas=lista)
    c(f"{etiqueta}: no se lanza ninguna pasada por cambios", d.tarea, None)
    c(f"  y se dice por qué", d.retenido is not None and (motivo is None or motivo in d.retenido),
      True)
c("«Sincronizar ahora» sí se salta la moderación y los cambios no",
  que(pl.decidir([RAIZ], HECHAS, pl.Entorno(pausado=True), T0, P, vigiladas=lista,
                 urgentes=[DOCS])), DOCS)
c("  y esa sí es urgente", pl.decidir([RAIZ], HECHAS, pl.Entorno(pausado=True), T0, P,
                                      vigiladas=lista, urgentes=[DOCS]).tarea.urgente, True)
c("pasada la moderación, el cambio pendiente sale en cuanto se levanta",
  que(pl.decidir([RAIZ], HECHAS, pl.Entorno(), T0 + 3600, P, vigiladas=lista)), DOCS)

# remoto sin conexión, raíz que no está, una pasada en marcha, un intervalo infinito
sin_red = pl.Entorno(sin_conexion={("equipo", "nas"): T0 + 5 * MIN})
d = pl.decidir([RAIZ], HECHAS, sin_red, T0, P, vigiladas=lista)
c("con el remoto sin conexión no se lanza la pareja, y aún no toca ni la sonda", d.tarea, None)
d = pl.decidir([RAIZ], HECHAS, sin_red, T0 + 5 * MIN, P, vigiladas=lista)
c("  cuando toca, es la sonda y no la pasada", (d.tarea.tipo, d.tarea.pareja),
  (pl.SONDA, None))
c("con una pasada en marcha no se decide otra", dec(lista, T0, ocupado=True).tarea, None)
apartada = pl.Raiz("equipo", RAIZ.parejas, 30 * MIN, atendible=False)
c("una raíz que no se puede atender no tiene pasadas, haya cambios o no",
  dec(lista, T0, raices=(apartada,)).tarea, None)
sync_una_vez = pl.Raiz("equipo", RAIZ.parejas, math.inf)
c("en una raíz de modo sync (intervalo infinito) los cambios no adelantan nada",
  dec(lista, T0, raices=(sync_una_vez,)).tarea, None)

# la cola única: dos parejas con cambios van una detrás de otra, la que lleva más esperando primero
DOS = pl.Raiz("equipo", (pl.Pareja("docs", "nas", vigila=True),
                         pl.Pareja("notas", "nas", vigila=True)), 30 * MIN)
marcas2 = {DOCS: pl.Marca(T0 - 5 * MIN), ("equipo", "notas"): pl.Marca(T0 - 5 * MIN)}
vig2 = {DOCS: pl.Vigilada(H2, T0 - 25, T0), ("equipo", "notas"): pl.Vigilada(H2, T0 - 40, T0)}
c("de dos parejas con cambios, primero la que antes estuvo lista",
  que(dec(vig2, T0, raices=(DOS,), marcas=marcas2)), ("equipo", "notas"))

# el tope
grande = pl.Huella(V.tope_entradas + 1, 0)
v0 = pl.Vigilada(H1, T0 - 60, T0 - 10)
v1 = pl.observar(v0, grande, T0)
c("pasar del tope abandona la pareja", v1.abandonada, True)
c("  la abandona una sola vez (es lo que se apunta en el diario)",
  (pl.se_abandona(v0, v1), pl.se_abandona(v1, pl.observar(v1, grande, T0 + 10))),
  (True, False))
c("  y con ello el cambio pendiente deja de contar", v1.cambio, None)
c("  nada más la saca de ahí", pl.observar(v1, H1, T0 + 10).abandonada, True)
c("  y ya no tiene hora por cambios", pl.toca_por_cambios(v1, HECHAS[DOCS]), math.inf)
c("justo en el tope, no se abandona", pl.observar(v0, pl.Huella(V.tope_entradas, 5), T0)
  .abandonada, False)
c("una abandonada no se adelanta: manda el intervalo",
  que(dec({DOCS: v1}, T0 + 3600 * 0.4)), None)

# la foto de después de una pasada
v = pl.Vigilada(H2, T0 - 60, T0 - 10)
t = pl.tras_pasada(v, H3, T0)
c("tras una pasada la foto de después es la de partida y no queda cambio",
  (t.huella, t.cambio, t.revisada), (H3, None, T0))
c("  lo que la pasada escribió (H3) no es un cambio al recorrer", pl.observar(t, H3, T0 + 10).cambio,
  None)
c("  uno de verdad después sí", pl.observar(t, H1, T0 + 10).cambio, T0 + 10)
c("  y la pasada que acaba de terminar no deja nada que adelantar",
  que(dec({DOCS: t}, T0 + 600, marcas={DOCS: pl.Marca(T0), FOTOS: pl.Marca(T0)})), None)
sin_foto = pl.tras_pasada(v, None, T0)
c("si no se pudo tomar la foto de después, la próxima es la de partida",
  (sin_foto.huella, sin_foto.cambio), (None, None))
c("  y esa no cuenta como cambio", pl.observar(sin_foto, H1, T0 + 10).cambio, None)
c("una abandonada sigue abandonada tras una pasada",
  pl.tras_pasada(v1, H1, T0 + 20).abandonada, True)

# a qué parejas toca recorrer
otra = pl.Raiz("unidad", (pl.Pareja("claves", "otro", vigila=True),), 10 * MIN)
todas = (RAIZ, otra)
c("sin nada recordado, se recorren las que piden watch y solo esas",
  pl.a_recorrer(todas, {}, T0), [DOCS, ("unidad", "claves")])
rec = {DOCS: pl.Vigilada(H1, None, T0 - 5)}
c("recorrida hace 5 s, todavía no", pl.a_recorrer([RAIZ], rec, T0), [])
c("  a los 10 s, sí", pl.a_recorrer([RAIZ], rec, T0 + 5), [DOCS])
c("con la moderación reteniendo, no se recorre nada",
  pl.a_recorrer(todas, {}, T0, retenido=True), [])
c("una raíz que no se puede atender no se recorre",
  pl.a_recorrer([apartada, otra], {}, T0), [("unidad", "claves")])
c("una de modo sync no se recorre", pl.a_recorrer([sync_una_vez], {}, T0), [])
c("la pareja con una pasada en marcha no se recorre: la escribe rclone",
  pl.a_recorrer(todas, {}, T0, ocupadas=[DOCS]), [("unidad", "claves")])
c("una abandonada no se vuelve a recorrer",
  pl.a_recorrer([RAIZ], {DOCS: pl.Vigilada(abandonada=True)}, T0 + 3600), [])
c("una política con otro sondeo manda",
  pl.a_recorrer([RAIZ], rec, T0 + 5, pl.PoliticaCambios(sondeo=30.0)), [])

sys.exit(c.report())
