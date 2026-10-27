#!/usr/bin/env python3
"""El nombre de los listados de bisync ya no depende de la máquina.

bisync guarda su baseline en ficheros cuyo nombre deduce de los dos extremos.
Con el lado local como ruta absoluta, ese nombre lleva dentro el punto de
montaje (`F__sync-data_notas..nas_datos_notas`), así que el mismo dispositivo
en otra letra de unidad (o en un Linux) ya no encontraba su baseline. Esa
herida la tapaba un renombrado automático de los listados, peligroso por
definición: renombrar es decirle a bisync que el listado del destino ANTERIOR
describe el NUEVO.

La cura es `device_remote`: el lado local va como un remote 'combine' propio y
el prefijo deja de saber dónde está montado nada. Esto comprueba las dos
mitades (el prefijo y las variables de entorno que definen ese remote) y que la
venda ya no está.

También fija cómo nombra rclone el extremo de un remote `local` y de uno
`alias` (que se escribe con el destino ya resuelto): los nombres de la
derecha son los que escribió rclone de verdad.
"""

import csv
import sys
from pathlib import Path

from _harness import Checks, sandbox

from common import bisync, model

c = Checks("bisync: prefijos independientes de la máquina")

PAREJAS = [{"name": "notas", "local": "sync-data/notas", "remote_path": "/datos/notas",
            "mode": "bisync"},
           {"name": "fotos", "local": "media/fotos", "remote_path": "/datos/fotos",
            "mode": "bisync"}]


def releer(texto):
    """Lo que rclone entiende al leer `upstreams`: un CSV separado por espacios."""
    return next(csv.reader([texto], delimiter=" ", quotechar='"'))


def config(device_remote=None, raiz=None):
    """Una config con (o sin) device_remote, montada en la raíz que se diga."""
    defaults = {"remote": "nas"}
    if device_remote:
        defaults["device_remote"] = device_remote
    if raiz is not None:
        model.DEVICE_ROOT = Path(raiz)
    return model.parse_config({"defaults": defaults, "pair": PAREJAS})


with sandbox() as root:
    original = model.DEVICE_ROOT

    # sin device_remote: el punto de montaje está DENTRO del nombre
    suelto = config(raiz=root).pairs[0]
    prefijo_suelto = bisync.expected_prefix(suelto)
    # `resolve()`: en Windows la ruta del temporal llega en formato 8.3
    # (PCERQU~1) y el modelo la resuelve al nombre largo.
    marca = bisync.canonical_path(str(Path(root).resolve()))
    c("sin device_remote el prefijo lleva el punto de montaje",
      marca in prefijo_suelto, True)

    # con device_remote: el mismo nombre en cualquier equipo
    pareja = config("disp", raiz=root).pairs[0]
    prefijo = bisync.expected_prefix(pareja)
    c("con device_remote el prefijo sale del nombre del remote",
      prefijo, "disp_sync-data_notas..nas__datos_notas")
    c("y no lleva dentro el punto de montaje", marca in prefijo, False)

    # La prueba de verdad: el MISMO dispositivo montado en otro sitio. Es lo que
    # pasa al llevárselo a otro equipo, y lo que rompía antes.
    otra_raiz = root / "otro-punto-de-montaje"
    otra_raiz.mkdir()
    en_otro_sitio = config("disp", raiz=otra_raiz).pairs[0]
    c("el prefijo no cambia al montar el dispositivo en otro sitio",
      bisync.expected_prefix(en_otro_sitio), prefijo)
    c("sin device_remote sí cambiaba",
      bisync.expected_prefix(config(raiz=otra_raiz).pairs[0]) == prefijo_suelto, False)

    # las variables que definen el remote 'combine'
    model.DEVICE_ROOT = root
    entorno = config("disp", raiz=root).pen_environment()
    c("el remote del dispositivo es un 'combine'",
      entorno["RCLONE_CONFIG_DISP_TYPE"], "combine")
    upstreams = entorno["RCLONE_CONFIG_DISP_UPSTREAMS"]
    # Un upstream por primer tramo de ruta local, de TODAS las parejas: el
    # remote tiene que ser idéntico se ejecute lo que se ejecute.
    c("un upstream por cada carpeta de primer nivel",
      upstreams, f'"media={(root / "media").resolve()}" '
                 f'"sync-data={(root / "sync-data").resolve()}"')
    c("sin device_remote no hay entorno que poner", config(raiz=root).pen_environment(), {})

    # y ese texto lo tiene que saber leer rclone
    #
    # rclone lee `upstreams` como fs.SpaceSepList (fs/types.go), que es un CSV
    # con el espacio de separador. `releer` hace lo mismo: si lo que generamos
    # no vuelve a salir entero, rclone tampoco lo va a entender.
    c("los upstreams se releen como los pares que son",
      releer(upstreams), [f'media={(root / "media").resolve()}',
                          f'sync-data={(root / "sync-data").resolve()}'])

    # La razón de ser de las comillas: una carpeta con un espacio en el nombre.
    con_espacio = model.parse_config(
        {"defaults": {"remote": "nas", "device_remote": "disp"},
         "pair": [{"name": "notas", "local": "mis documentos/notas",
                   "remote_path": "/datos/notas", "mode": "bisync"}]})
    c("una carpeta con espacios sigue siendo UN upstream",
      releer(con_espacio.pen_environment()["RCLONE_CONFIG_DISP_UPSTREAMS"]),
      [f'mis documentos={(root / "mis documentos").resolve()}'])

    model.DEVICE_ROOT = original

# la pareja que sincroniza la RAÍZ del dispositivo
#
# `local = "."` no tiene primer tramo. Dejarlo en "." daba el upstream "." y el
# extremo `disp:.`, y rclone limpia la ruta ANTES de buscar el upstream: se
# quedaba buscando el upstream "" y fallaba con «combine for remote "":
# directory not found». Ni siquiera es un fallo de la pareja de la raíz sola:
# es la pareja que se lleva el dispositivo entero.
with sandbox() as root:
    original = model.DEVICE_ROOT
    model.DEVICE_ROOT = Path(root)

    raiz = model.parse_config(
        {"defaults": {"remote": "nas", "device_remote": "disp"},
         "pair": [{"name": "todo", "local": ".", "remote_path": "/copia", "mode": "down"},
                  {"name": "notas", "local": "sync-data/notas",
                   "remote_path": "/datos/notas", "mode": "bisync"}]})
    todo, notas = raiz.pairs

    c("la raíz se declara con un nombre, no con un punto",
      todo.top_level_dir, model.RAIZ_UPSTREAM)
    c("y el extremo local deja de ser 'disp:.'", todo.local_endpoint, "disp:raiz")
    c("el upstream de la raíz apunta a la raíz del dispositivo",
      todo.top_level_abs, Path(root).resolve())
    c("una pareja normal no cambia", notas.local_endpoint, "disp:sync-data/notas")
    c("y su upstream sigue siendo su carpeta",
      notas.top_level_abs, (Path(root) / "sync-data").resolve())
    c("los dos upstreams, cada uno con su carpeta",
      releer(raiz.pen_environment()["RCLONE_CONFIG_DISP_UPSTREAMS"]),
      [f'raiz={Path(root).resolve()}',
       f'sync-data={(Path(root) / "sync-data").resolve()}'])

    # Si alguien tiene una carpeta llamada como el upstream de la raíz, el mismo
    # nombre apuntaría a dos sitios. Mejor plantarse que sincronizar a ciegas.
    choque = model.parse_config(
        {"defaults": {"remote": "nas", "device_remote": "disp"},
         "pair": [{"name": "todo", "local": ".", "remote_path": "/copia", "mode": "down"},
                  {"name": "otra", "local": f"{model.RAIZ_UPSTREAM}/cosas",
                   "remote_path": "/cosas", "mode": "down"}]})
    try:
        choque.pen_environment()
        c("dos upstreams con el mismo nombre se avisan", "no avisó", "ConfigError")
    except model.ConfigError as e:
        c("dos upstreams con el mismo nombre se avisan",
          model.RAIZ_UPSTREAM in str(e), True)

    model.DEVICE_ROOT = original


# la forma exacta que tumbó el dispositivo de pruebas
#
# Un dispositivo montado en F: tiene la propia raíz como upstream (la pareja
# cuyo `local` es "."), y `F:\` acaba en barra. Entrecomillando solo la ruta
# salía `.="F:\"`: un campo que no empieza por comilla con una comilla dentro.
# rclone rechazaba la línea entera con «bare " in non-quoted-field», así que
# NINGUNA pareja del dispositivo podía correr. Con el par entero entre comillas
# la barra final queda dentro y se relee bien.
c("la raíz de una unidad acaba en barra y aun así se relee",
  releer(r'".=F:\" "sync-data=F:\sync-data"'), ['.=F:\\', 'sync-data=F:\\sync-data'])

# un remote de tipo `local`: rclone pone su `Root()`, no la ruta tal cual
#
# Los nombres de la derecha son los que escribió rclone v1.75.1 de verdad: en
# Linux, con este remote en un rclone.conf; en Windows, en el CI de
# `llavero-real.yml` (la ruta del remoto era D:/a/_temp/…), donde prdrive
# esperaba `nas_D__a__temp…` y no encontraba el listado del llavero.
with sandbox():
    model.RCLONE_CONF.write_text("[nas]\ntype = local\n\n[otro]\ntype = local\nnounc = true\n\n"
                                 "[nube]\ntype = sftp\n", encoding="utf-8")

    def nombre(destino):
        """El nombre del lado del remoto, como lo calcula prdrive."""
        return bisync.canonical_path(bisync.fs_path_remote(destino))

    real_win = bisync.IS_WIN
    try:
        bisync.IS_WIN = False
        for destino, de_rclone in (("nas:/tmp/p/w//x", "nas__tmp_p_w_x"),
                                   ("nas:/tmp/p/w/./x", "nas__tmp_p_w_x"),
                                   ("nas:/tmp/p/w/x/", "nas__tmp_p_w_x"),
                                   ("nas:rel/x", "nas_rel_x"), ("nas:a/../b", "nas_b"),
                                   ("nas:", "nas_\uff0e"), ("nas:/", "nas_")):
            c(f"en Linux, un remote local va con su ruta limpia: {destino}",
              nombre(destino), de_rclone)
        c("  uno de otro tipo, tal cual", nombre("nube:/datos//x"), "nube__datos__x")
        bisync.IS_WIN = True
        c("en Windows, con \\\\?\\ delante (el nombre que escribió rclone en el CI)",
          nombre("nas:D:/a/_temp/prdrive-real-0vhwz033/remoto/prdrive-catalog/keychain"),
          "nas_____D__a__temp_prdrive-real-0vhwz033_remoto_prdrive-catalog_keychain")
        c("  una ruta de red, con \\\\?\\UNC\\", nombre(r"nas:\\servidor\datos"),
          "nas_____UNC_servidor_datos")
        c("  con nounc = true, sin el prefijo", nombre("otro:D:/datos"), "otro_D__datos")
        c("  uno de otro tipo, tal cual", nombre("nube:/datos"), "nube__datos")
        c("  una relativa, desde .prdrive/ (rclone corre ahí)",
          nombre("nas:datos") == nombre(f"nas:{model.APP_DIR}/datos"), True)
    finally:
        bisync.IS_WIN = real_win
    model.RCLONE_CONF.unlink()
    c("sin rclone.conf, como cualquier remote", nombre("nas:/tmp/p/w//x"), "nas__tmp_p_w__x")


# los espacios raros y los caracteres de control, como rclone (#174)
#
# Los valores de la derecha no están escritos a mano: los dio el código de rclone v1.75.2
# (`bilib.CanonicalPath`, el `Root()` de un remote `type = local` por `fs.NewFs` y
# `bilib.SessionName`), llamado desde un programa en Go contra ese módulo. El `\s` de Go es
# `[\t\n\f\r ]`, no el de Python; y el `Root()` del backend local pasa cada tramo por el
# codificador de nombres (lib/encoder): un carácter de control sale como su símbolo y una
# `‛` suelta, doble. Solo en POSIX: en Windows el codificador es otro y no se ha contrastado.
ORACULO_V1_75_2 = (
    # (ruta, CanonicalPath(ruta), Root() de `nas:` + ruta)
    ("a　b", "a　b", "a　b"),
    ("a\u000bb", "a\u000bb", "a␋b"),
    ("a\u0085b", "a\u0085b", "a\u0085b"),
    ("a b", "a b", "a b"),
    ("a\u001cb", "a\u001cb", "a␜b"),
    ("it‛s", "it‛s", "it‛‛s"),
    ("‛", "‛", "‛‛"),
    ("a\u007fb", "a\u007fb", "a␡b"),
    ("a\u0001b", "a\u0001b", "a␁b"),
    ("a\u0000b", "a\u0000b", "a␀b"),
    ("a\tb", "a_b", "a␉b"),
    ("␁", "␁", "␁"),
    ("␡", "␡", "␡"),
    ("‛␀", "‛␀", "‛␀"),
    ("sync-data/．/x", "sync-data_．_x", "sync-data/．/x"),
    ("／", "／", "／"),
    ("．", "．", "．"),
    ("‛．", "‛．", "‛．"),
    ("a/./b", "a_._b", "a/b"),
    ("..", "..", "．．"),
)
real_win = bisync.IS_WIN
try:
    bisync.IS_WIN = False
    for ruta, canonica, raiz in ORACULO_V1_75_2:
        c(f"CanonicalPath como rclone: {ruta!r}", bisync.canonical_path(ruta), canonica)
        c(f"  y el Root() de un remote local: {ruta!r}", bisync.raiz_local(ruta), raiz)
    with sandbox():
        model.RCLONE_CONF.write_text("[nas]\ntype = local\n", encoding="utf-8")
        for local, remote_path, sesion in (
                ("sync-data/notas　mías", "/datos/a\u000bb c/it‛s/\u007f",
                 "disp_sync-data_notas　mías..nas__datos_a␋b_c_it‛‛s_␡"),
                ("sync-data/x\u0085y", "/datos/x y",
                 "disp_sync-data_x\u0085y..nas__datos_x y")):
            par = model.parse_config({"defaults": {"remote": "nas", "device_remote": "disp"},
                                      "pair": [{"name": "p", "local": local,
                                                "remote_path": remote_path}]}).pairs[0]
            c(f"el prefijo es el SessionName de rclone: {local!r} y {remote_path!r}",
              bisync.expected_prefix(par), sesion)
        # Sin `device_remote` el lado local es el backend `local` a secas: su `Root()` también.
        suelta = model.parse_config({"defaults": {"remote": "nube"},
                                     "pair": [{"name": "p", "local": "it‛s\u000b",
                                               "remote_path": "/x"}]}).pairs[0]
        c("sin device_remote, la ruta local también va codificada",
          bisync.expected_prefix(suelta).split("..")[0].endswith("_it‛‛s␋"), True)
finally:
    bisync.IS_WIN = real_win


# un remote `alias`: rclone nombra los listados con el destino YA resuelto
#
# `alias` no es un envoltorio con nombre propio. Su `NewFs` devuelve el `Fs` del
# destino (`cache.Get(ctx, fspath.JoinRootPath(opt.Remote, root))`,
# backend/alias/alias.go), así que `FsPath` (cmd/bisync/bilib/canonical.go) ve el
# `Name()` y el `Root()` del destino y no los del alias. Si el destino es una
# ruta suelta su `Name()` es `local` y `FsPath` la escribe sin `nombre:`; si es
# un remote `local`, con su nombre y su `Root()` limpio; si es otro alias, se
# sigue. Los nombres de la derecha son los que escribió `rclone bisync --resync`
# v1.75.1 de verdad, en Linux, con este `rclone.conf` y los extremos
# `disp:sync-data/prueba` (un combine, como `device_remote`) y el de la izquierda.
# Los envoltorios de verdad (crypt, union, combine, chunker, hasher, compress)
# devuelven su propio `Fs`, con el nombre de su sección (`Name()` y `Root()` de
# cada backend), y ahí la regla de siempre vale: se comprueba que no se toca.
RAIZ_ALIAS = "/srv/prdrive-alias/remoto"
ALIAS_CONF = f"""
[nas]
type = local

[pruebas]
type = alias
remote = {RAIZ_ALIAS}

[pruebas_nas]
type = alias
remote = nas:{RAIZ_ALIAS}

[base_alias]
type = alias
remote = {RAIZ_ALIAS}

[alias_de_alias]
type = alias
remote = base_alias:datos

[pruebas_subruta]
type = alias
remote = {RAIZ_ALIAS}/datos

[alias_a_nas_vacio]
type = alias
remote = nas:

[alias_a_cmb]
type = alias
remote = cmb:r

[alias_a_cmb_raiz]
type = alias
remote = cmb:

[cmb]
type = combine
upstreams = r={RAIZ_ALIAS}

[uni]
type = union
upstreams = {RAIZ_ALIAS}/datos {RAIZ_ALIAS}/otro

[cif]
type = crypt
remote = {RAIZ_ALIAS}/cifrado

[chk]
type = chunker
remote = {RAIZ_ALIAS}

[hsh]
type = hasher
remote = {RAIZ_ALIAS}

[cmp]
type = compress
remote = {RAIZ_ALIAS}

[mem]
type = memory
"""
LISTADO_ALIAS = "srv_prdrive-alias_remoto_datos_prueba"
"""El extremo que escribe rclone para una ruta suelta: sin `nombre:` delante."""

with sandbox():
    model.RCLONE_CONF.write_text(ALIAS_CONF, encoding="utf-8")

    def canonico(destino):
        """El nombre del extremo del remoto, como lo calcula prdrive."""
        return bisync.canonical_path(bisync.fs_path_remote(destino))

    real_win = bisync.IS_WIN
    try:
        bisync.IS_WIN = False
        for destino, de_rclone in (
                ("pruebas:datos/prueba", LISTADO_ALIAS),
                ("pruebas:/datos/prueba", LISTADO_ALIAS),
                ("pruebas:/datos//./prueba/", LISTADO_ALIAS),
                ("pruebas_nas:datos/prueba", "nas__srv_prdrive-alias_remoto_datos_prueba"),
                ("alias_de_alias:prueba", LISTADO_ALIAS),
                ("pruebas_subruta:prueba", LISTADO_ALIAS),
                (f"alias_a_nas_vacio:{RAIZ_ALIAS}/datos/prueba",
                 "nas__srv_prdrive-alias_remoto_datos_prueba"),
                ("alias_a_cmb:datos/prueba", "cmb_r_datos_prueba"),
                ("alias_a_cmb_raiz:r/datos/prueba", "cmb_r_datos_prueba")):
            c(f"un alias se resuelve a su destino: {destino}", canonico(destino), de_rclone)

        # los que ya valían y no hay que tocar
        for destino, de_rclone in (
                (f"nas:{RAIZ_ALIAS}/datos/prueba", "nas__srv_prdrive-alias_remoto_datos_prueba"),
                ("cmb:r/datos/prueba", "cmb_r_datos_prueba"),
                ("uni:datos/prueba", "uni_datos_prueba"),
                ("cif:prueba", "cif_prueba"),
                ("chk:datos/prueba", "chk_datos_prueba"),
                ("hsh:datos/prueba", "hsh_datos_prueba"),
                ("cmp:datos/prueba", "cmp_datos_prueba"),
                ("mem:datos/prueba", "mem_datos_prueba")):
            c(f"el resto de remotes, con su propio nombre: {destino}", canonico(destino), de_rclone)
    finally:
        bisync.IS_WIN = real_win

    # En Windows, con la unidad de por medio. El primero es el que escribió rclone
    # en la prueba del 24/09/2026 (alias `pruebas` sobre C:\prdrive-pruebas\remoto),
    # el que «Reparación» daba por ajeno. Los demás los escribió rclone v1.75.1 en
    # el CI (`prefijo-alias-real.yml`, Windows Server, runneradmin): un alias a una
    # ruta suelta va sin `nombre:` ni `\\?\`; a un remote `local`, con su nombre y
    # el `\\?\` de su Root(). No se ha observado todavía un destino de red
    # (`\\srv\…`, que saldría como `UNC_srv_…`) ni `nounc`.
    WIN_RAIZ = r"C:\Users\runneradmin\AppData\Local\Temp\prdrive-alias-hl0r6_13\remoto"
    WIN_LISTADO = "C__Users_runneradmin_AppData_Local_Temp_prdrive-alias-hl0r6_13_remoto_datos_prueba"
    model.RCLONE_CONF.write_text(
        "[nas]\ntype = local\n\n"
        "[pruebas]\ntype = alias\nremote = C:\\prdrive-pruebas\\remoto\n\n"
        f"[a_carpeta]\ntype = alias\nremote = {WIN_RAIZ}\n\n"
        f"[a_nas]\ntype = alias\nremote = nas:{WIN_RAIZ}\n\n"
        f"[base]\ntype = alias\nremote = {WIN_RAIZ}\n\n"
        "[de_alias]\ntype = alias\nremote = base:datos\n\n"
        f"[con_subruta]\ntype = alias\nremote = {WIN_RAIZ}\\datos\n", encoding="utf-8")
    try:
        bisync.IS_WIN = True
        c("en Windows, un alias a una unidad (el nombre de la prueba del 24/09)",
          canonico("pruebas:datos/prueba"), "C__prdrive-pruebas_remoto_datos_prueba")
        for destino, de_rclone in (
                ("a_carpeta:datos/prueba", WIN_LISTADO),
                ("a_carpeta:/datos/prueba", WIN_LISTADO),
                ("a_carpeta:/datos//./prueba/", WIN_LISTADO),
                ("a_nas:datos/prueba", "nas_____" + WIN_LISTADO),
                ("de_alias:prueba", WIN_LISTADO),
                ("con_subruta:prueba", WIN_LISTADO)):
            c(f"en Windows, un alias se resuelve a su destino: {destino}",
              canonico(destino), de_rclone)
    finally:
        bisync.IS_WIN = real_win
    model.RCLONE_CONF.write_text(ALIAS_CONF, encoding="utf-8")

    # lo que no se puede resolver no se inventa
    SIN_RESOLVER = """
[sin_destino]
type = alias

[ciclo_a]
type = alias
remote = ciclo_b:x

[ciclo_b]
type = alias
remote = ciclo_a:y

[a_si_mismo]
type = alias
remote = a_si_mismo:x

[con_cadena]
type = alias
remote = :local:/srv/prdrive-alias

[con_parametros]
type = alias
remote = nas,nounc=true:/srv/prdrive-alias

[a_fantasma]
type = alias
remote = no_existe:/srv/prdrive-alias

[a_otro_sin_resolver]
type = alias
remote = sin_destino:x
"""
    model.RCLONE_CONF.write_text(ALIAS_CONF + SIN_RESOLVER, encoding="utf-8")
    for alias in ("sin_destino", "ciclo_a", "a_si_mismo", "con_cadena", "con_parametros",
                  "a_fantasma", "a_otro_sin_resolver"):
        c(f"un alias que no se resuelve no da extremo: {alias}",
          bisync.resolver_extremo(f"{alias}:datos/prueba"), None)
    c("y uno que sí se resuelve, el suyo",
      bisync.resolver_extremo("pruebas:datos/prueba") is not None, True)

    sin_resolver = model.parse_config({"defaults": {"remote": "ciclo_a", "device_remote": "disp"},
                                       "pair": PAREJAS[:1]}).pairs[0]
    resuelto = model.parse_config({"defaults": {"remote": "pruebas", "device_remote": "disp"},
                                   "pair": PAREJAS[:1]}).pairs[0]
    c("la pareja con un alias sin resolver no se puede comprobar",
      bisync.prefijo_comprobable(sin_resolver), False)
    c("pero sigue dando un prefijo, para quien lo necesita igualmente",
      isinstance(bisync.expected_prefix(sin_resolver), str), True)
    c("la de un alias que se resuelve, sí", bisync.prefijo_comprobable(resuelto), True)
    c("y una sin alias, también",
      bisync.prefijo_comprobable(config("disp", raiz=model.DEVICE_ROOT).pairs[0]), True)
    model.RCLONE_CONF.unlink()


# el rclone.conf se lee una vez por decisión, no una por extremo
#
# `tipos_de_remote()` lee y analiza el fichero entero, y cada extremo que se
# resolvía lo volvía a llamar: 4 lecturas por pareja en cada pasada y 10 en
# `--doctor`. Quien decide lo lee una vez y pasa lo leído (`tipos=`). No hay caché
# por (ruta, mtime) a propósito: con los 2 s de granularidad de FAT, una ventana
# abierta mucho rato serviría el destino de un alias viejo, y daría un «el baseline
# no es de esta pareja» falso que apartaría uno bueno.
from common import revision

with sandbox():
    model.RCLONE_CONF.write_text(ALIAS_CONF + "\n[ciclo_a]\ntype = alias\nremote = ciclo_a:x\n",
                                 encoding="utf-8")
    real_tipos = bisync.tipos_de_remote
    leidas: list[int] = []

    def tipos_contado():
        """Lee el rclone.conf como siempre, y apunta que lo ha leído."""
        leidas.append(1)
        return real_tipos()

    def lecturas(que):
        """Devuelve `(resultado, cuántas veces ha leído el rclone.conf)` al hacer `que()`."""
        leidas.clear()
        bisync.tipos_de_remote = tipos_contado
        try:
            resultado = que()
        finally:
            bisync.tipos_de_remote = real_tipos
        return resultado, len(leidas)

    def pareja_de(remote):
        """La pareja `notas` sobre ese remote, con su carpeta local creada."""
        par = model.parse_config({"defaults": {"remote": remote, "device_remote": "disp"},
                                  "pair": PAREJAS[:1]}).pairs[0]
        par.local_abs.mkdir(parents=True, exist_ok=True)
        return par

    def con_baseline(par, prefijo=None):
        """Deja en el workdir los dos listados vacíos de un baseline, con ese prefijo."""
        par.workdir.mkdir(parents=True, exist_ok=True)
        for sufijo in (bisync.PATH1_SUFFIX, bisync.PATH2_SUFFIX):
            (par.workdir / ((prefijo or bisync.expected_prefix(par)) + sufijo)).write_text(
                "# bisync listing v1 from 2026-10-12T10:00:00.000000000+0200\n",
                encoding="utf-8")

    par = pareja_de("pruebas")
    tipos = real_tipos()
    c("sin baseline, referencia_vacia no lee el rclone.conf",
      lecturas(lambda: bisync.referencia_vacia(par)), (False, 0))
    con_baseline(par)
    c("con baseline, referencia_vacia lo lee una sola vez (eran cuatro)",
      lecturas(lambda: bisync.referencia_vacia(par)), (True, 1))
    c("  y con lo ya leído, ninguna",
      lecturas(lambda: bisync.referencia_vacia(par, tipos=tipos)), (True, 0))

    esperado = bisync.expected_prefix(par)
    c("expected_prefix con lo ya leído no lee, y da el mismo prefijo",
      lecturas(lambda: bisync.expected_prefix(par, tipos)), (esperado, 0))
    c("  prefijo_comprobable, igual",
      (lecturas(lambda: bisync.prefijo_comprobable(par, tipos)),
       bisync.prefijo_comprobable(par)), ((True, 0), True))
    c("  fs_path_remote y resolver_extremo, igual",
      (lecturas(lambda: bisync.fs_path_remote("pruebas:datos", tipos)),
       lecturas(lambda: bisync.resolver_extremo("pruebas:datos", tipos))),
      ((bisync.fs_path_remote("pruebas:datos"), 0), (bisync.resolver_extremo("pruebas:datos"), 0)))
    c("un diccionario vacío es un rclone.conf sin remotes, no «sin leer»",
      lecturas(lambda: bisync.fs_path_remote("pruebas:datos", {})), ("pruebas:datos/", 0))

    # `--doctor`: una lectura por pareja en su informe, no cuatro más seis
    c("el informe de una pareja bisync lee el rclone.conf una sola vez",
      lecturas(lambda: revision._informe_pareja(par))[1], 1)
    informe, _ = lecturas(lambda: revision._informe_pareja(par))
    c.contains("  y sigue diciendo su prefijo", "\n".join(informe),
               f"prefijo esperado: {esperado}\n")
    c.contains("  y que su referencia está vacía", "\n".join(informe), "referencia: vacía")
    otra = model.parse_config({"defaults": {"remote": "pruebas"},
                               "pair": [{**PAREJAS[0], "mode": "down-mirror"}]}).pairs[0]
    c("el de una pareja que no es bisync, ninguna",
      lecturas(lambda: revision._informe_pareja(otra))[1], 0)

    # «Reparación»: lo mismo en `_prefijo`, en el camino corto y en el largo
    estado = bisync.pair_state(par)
    c("_prefijo con el baseline de esta pareja: una lectura, sin hallazgo",
      lecturas(lambda: revision._prefijo(par, estado)), (None, 1))
    ajeno = bisync.PairState(estado.status, estado.detail, "disp_otra..cosa")
    hallazgo, n = lecturas(lambda: revision._prefijo(par, ajeno))
    c("  con el de otra, también una (eran cuatro), y acusa",
      (hallazgo.clave if hallazgo else None, n), ("prefijo", 1))
    ciclo = pareja_de("ciclo_a")
    hallazgo, n = lecturas(lambda: revision._prefijo(
        ciclo, bisync.PairState(estado.status, estado.detail, "disp_otra..cosa")))
    c("  y con un alias que no se puede seguir, una y no acusa", (hallazgo, n), (None, 1))

# llaves en la carpeta del dispositivo: el sufijo `{hash}` del `combine` (#177)
#
# El `combine` del dispositivo se define por el entorno (`pen_environment()`).
# rclone v1.75.2 lee esas variables con `configmap.PriorityNormal`
# (`fs/configmap.go`), `Options.Overridden()` (`fs/registry.go`) las cuenta y
# `fs.NewFs()` (`fs/newfs.go`) le añade al nombre del `Fs` un sufijo `{hash}`:
# `disp{xxxxx}`. `SessionName` quita solo la primera `{…}` (`StripHexString`,
# cmd/bisync/bilib/canonical.go), que es ese sufijo, y las llaves de la carpeta
# se quedan. Los valores de la derecha los escribió el binario fijado (rclone
# v1.75.2, `bisync --resync` con el `combine` por el entorno) en el triaje de
# #177. Sin el sufijo, prdrive se comía la `{2024}` y decía `disp_Fotos_`.
# En el lado remoto un remote del `rclone.conf` no lleva sufijo: allí rclone y
# prdrive se comen las dos la primera `{…}` de la carpeta.
def pareja_llaves(local, remote_path="/datos/x", device_remote="disp"):
    """Una pareja bisync `fotos` sobre `nas`, con esa carpeta local."""
    defaults = {"remote": "nas"}
    if device_remote:
        defaults["device_remote"] = device_remote
    return model.parse_config({"defaults": defaults,
                               "pair": [{"name": "fotos", "local": local,
                                         "remote_path": remote_path,
                                         "mode": "bisync"}]}).pairs[0]


with sandbox():
    c("llaves en la carpeta del dispositivo: se quedan, como en rclone",
      bisync.expected_prefix(pareja_llaves("Fotos {2024}")), "disp_Fotos_{2024}..nas__datos_x")
    c("  y en varios tramos, todas",
      bisync.expected_prefix(pareja_llaves("Fotos {2024}/sub {b}")),
      "disp_Fotos_{2024}_sub_{b}..nas__datos_x")
    c("  sin llaves, el prefijo de siempre, byte a byte",
      bisync.expected_prefix(pareja_llaves("sync-data/notas", "/datos/notas")),
      "disp_sync-data_notas..nas__datos_notas")
    model.RCLONE_CONF.write_text("[nas]\ntype = local\n", encoding="utf-8")
    c("  el lado sin sufijo (un remote `local` del rclone.conf) pierde sus llaves",
      bisync.expected_prefix(pareja_llaves("sync-data/p", "/datos/dest {x}")),
      "disp_sync-data_p..nas__datos_dest_")
    # El `TYPE` del entorno manda sobre una sección del mismo nombre del rclone.conf.
    model.RCLONE_CONF.write_text("[nas]\ntype = local\n\n[disp]\ntype = alias\n"
                                 "remote = /srv/otra\n", encoding="utf-8")
    con_seccion = pareja_llaves("Fotos {2024}")
    c("  un [disp] de tipo alias en el rclone.conf no cambia el extremo del combine",
      bisync.expected_prefix(con_seccion), "disp_Fotos_{2024}..nas__datos_x")
    c("  y el prefijo sigue siendo comprobable",
      bisync.prefijo_comprobable(con_seccion), True)
    model.RCLONE_CONF.unlink()

    # Un workdir cuyo único baseline se llama como lo escribió rclone: es de esta pareja.
    fotos = pareja_llaves("Fotos {2024}")
    fotos.local_abs.mkdir(parents=True, exist_ok=True)
    fotos.workdir.mkdir(parents=True, exist_ok=True)
    for sufijo in (bisync.PATH1_SUFFIX, bisync.PATH2_SUFFIX):
        (fotos.workdir / ("disp_Fotos_{2024}..nas__datos_x" + sufijo)).write_text(
            "# bisync listing v1 from 2026-10-27T10:00:00.000000000+0100\n", encoding="utf-8")
    estado_fotos = bisync.pair_state(fotos)
    c("  el baseline que nombró rclone se ve como el de esta pareja",
      estado_fotos.prefix, bisync.expected_prefix(fotos))
    c("  revision no da el hallazgo «prefijo»", revision._prefijo(fotos, estado_fotos), None)
    c("  y la referencia vacía se rehace sola", bisync.referencia_vacia(fotos), True)

# la venda, retirada
#
# No es una comprobación de aspecto: renombrar los listados al prefijo nuevo es
# la operación que puede provocar borrados masivos (ver el docstring de
# `bisync.shelve_baseline`). Si alguien la reintroduce, que sea leyendo esto.
for nombre in ("normalize_prefix", "rename_prefix", "heal_listings"):
    c(f"bisync ya no renombra listados: sin {nombre}()", hasattr(bisync, nombre), False)

sys.exit(c.report())
