#!/usr/bin/env python3
"""Los avisos del sistema de que una carpeta ha cambiado (`common/avisos_carpeta.py`).

Con carpetas de verdad en un temporal y el inotify de verdad del núcleo:
- Qué avisa: crear, guardar, renombrar, borrar y cambiar la fecha de un
  fichero, una carpeta nueva (y lo que se escribe dentro después), en
  cualquier profundidad. Qué no: leer, cambiar los permisos de una carpeta, y
  lo de `.prversions/`, `.prdrive/` y el ruido del sistema en la raíz de la
  pareja.
- Una carpeta que entra o sale del árbol pide rehacer la vigilancia
  (`DESBORDADO`) y, rehecha, lo de dentro se sigue viendo y lo de fuera no.
- Dos parejas que se solapan (`local = "."` y una subcarpeta) comparten
  vigilancias, y dejar una no deja sorda a la otra.
- La carpeta de la pareja borrada, movida o desmontada es `PERDIDA` y no deja
  vigilancias puestas. Desmontar con vigilancias puestas funciona (como root y
  con `mount`; si no, `(saltado)`).
- Lo que no se vigila, y por qué: una carpeta de red, el presupuesto (la mitad
  de `max_user_watches`), `ENOSPC` del sistema, una pareja que se deja
  mientras se pone. Sin dejar nada puesto.
- Qué sistema de ficheros tiene una carpeta, leyendo mountinfo.

Fuera de Linux no hay motor (`abrir()` es `None`) y el resto se salta.
"""

import errno
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from _harness import Checks, tmpdir

from common import avisos_carpeta as ac
from common import model

c = Checks("avisos del sistema de una carpeta (inotify)")

c("el texto de mountinfo: gana el punto de montaje más largo, y el último si se apilan",
  ac.tipo_en_mountinfo("/media/u/USB STICK/datos",
                       "22 1 8:1 / / rw - ext4 /dev/sda1 rw\n"
                       "30 22 8:17 / /media/u/USB\\040STICK rw - vfat /dev/sdb1 rw\n"
                       "31 30 0:50 / /media/u/USB\\040STICK rw - exfat /dev/sdb1 rw\n"
                       "32 22 0:51 / /media/u/USB rw - nfs4 nas:/x rw\n"),
  "exfat")
c("  la raíz si no hay otro", ac.tipo_en_mountinfo("/home/x", "22 1 8:1 / / rw - ext4 a rw\n"),
  "ext4")
c("  con campos opcionales delante del guion",
  ac.tipo_en_mountinfo("/srv/x", "40 22 0:9 / /srv rw shared:1 master:2 - fuse.sshfs a rw\n"),
  "fuse.sshfs")
c("  y una ruta que solo empieza igual no es de ese montaje",
  ac.tipo_en_mountinfo("/srvx/y", "22 1 8:1 / / rw - ext4 a rw\n"
                                  "40 22 0:9 / /srv rw - nfs a rw\n"), "ext4")
c("las carpetas de red y compartidas están en la tabla",
  {"nfs", "nfs4", "cifs", "smb3", "fuse.sshfs", "fuse.rclone", "9p"} <= ac.DE_RED, True)
c("  y las de un pendrive o un disco no",
  {"vfat", "exfat", "ntfs3", "fuseblk", "ext4", "btrfs", "tmpfs"} & ac.DE_RED, set())

if not sys.platform.startswith("linux"):
    print("  (saltado) inotify es de Linux: lo demás no se prueba aquí")
    c("fuera de Linux no hay motor de avisos", ac.abrir(), None)
    raise SystemExit(c.report())

U = "u" * 32
K = (U, "docs")
IGN = (".prversions", ".prdrive", ".keychain")
MOTORES: list = []


def motor():
    """Abre un motor de avisos y lo apunta para cerrarlo al final."""
    m = ac.abrir()
    MOTORES.append(m)
    return m


def arbol() -> Path:
    """Una carpeta de pareja de verdad: dos niveles, ficheros y lo que no se mira."""
    t = tmpdir("prdrive-avisos-")
    (t / "sub" / "hondo").mkdir(parents=True)
    (t / ".prversions").mkdir()
    (t / ".prdrive" / "state").mkdir(parents=True)
    (t / "a.txt").write_text("a", encoding="utf-8")
    (t / "sub" / "b.txt").write_text("b", encoding="utf-8")
    return t


def tipos(avisos: dict) -> dict:
    """Los avisos recogidos, solo con su tipo."""
    return {k: a.tipo for k, a in avisos.items()}


def tras(m, accion) -> dict:
    """Hace algo en el disco y devuelve los tipos de los avisos que deja."""
    accion()
    return tipos(m.recoger())


CAMBIO = {K: ac.CAMBIO}

# ---------------------------------------------------------------------------
# 1. Qué avisa y qué no
# ---------------------------------------------------------------------------
m = motor()
T = arbol()
c("se vigila una carpeta local", m.vigilar(K, T, IGN), None)
c("  y al ponerla no llega nada", m.recoger(), {})
c("  una vigilancia por carpeta, sin las que no se miran", m.vigilancias(), 3)
c("crear un fichero avisa", tras(m, lambda: (T / "nuevo.txt").write_text("x")), CAMBIO)
c("guardar uno que ya estaba", tras(m, lambda: (T / "sub" / "b.txt").write_text("bb")), CAMBIO)
c("en una subcarpeta honda", tras(m, lambda: (T / "sub" / "hondo" / "c.txt").write_text("c")),
  CAMBIO)
c("renombrar", tras(m, lambda: os.rename(T / "a.txt", T / "a2.txt")), CAMBIO)
c("borrar", tras(m, lambda: (T / "a2.txt").unlink()), CAMBIO)
c("cambiar la fecha", tras(m, lambda: os.utime(T / "nuevo.txt", (1, 1))), CAMBIO)
c("leer no avisa", tras(m, lambda: (T / "nuevo.txt").read_text()), {})
c("una carpeta nueva avisa", tras(m, lambda: (T / "nueva").mkdir()), CAMBIO)
c("  y lo que se escribe dentro después, también",
  tras(m, lambda: (T / "nueva" / "f.txt").write_text("f")), CAMBIO)


def llena() -> None:
    """Una carpeta nueva que ya trae otra dentro, con un fichero."""
    (T / "llena" / "x").mkdir(parents=True)
    (T / "llena" / "x" / "g.txt").write_text("g", encoding="utf-8")


c("una carpeta nueva que ya trae algo dentro", tras(m, llena), CAMBIO)
c("  y lo de su subcarpeta, después", tras(m, lambda: (T / "llena" / "x" / "g.txt").write_text("gg")),
  CAMBIO)
c("en .prversions/ no avisa", tras(m, lambda: (T / ".prversions" / "v~1.txt").write_text("v")), {})
c("en .prdrive/ tampoco", tras(m, lambda: (T / ".prdrive" / "state" / "x.json").write_text("{}")),
  {})
c("  ni cambiar los permisos de .prversions/",
  tras(m, lambda: os.chmod(T / ".prversions", 0o700)), {})
c("cambiar los permisos de una carpeta no es un cambio (como en la foto)",
  tras(m, lambda: os.chmod(T / "sub", 0o700)), {})
c("  los de un fichero sí", tras(m, lambda: os.chmod(T / "nuevo.txt", 0o600)), CAMBIO)
vigilancias = m.vigilancias()

# ---------------------------------------------------------------------------
# 2. Una carpeta que entra o sale del árbol
# ---------------------------------------------------------------------------
c("mover una carpeta dentro del árbol avisa y pide rehacer la vigilancia",
  tras(m, lambda: os.rename(T / "sub", T / "movida")), {K: ac.DESBORDADO})
c("  rehecha", m.vigilar(K, T, IGN), None)
c("  lo que se guarda en la carpeta movida se sigue viendo",
  tras(m, lambda: (T / "movida" / "hondo" / "c.txt").write_text("cc")), CAMBIO)
FUERA = tmpdir("prdrive-fuera-")
c("sacar una carpeta del árbol avisa y pide rehacer",
  tras(m, lambda: os.rename(T / "movida", FUERA / "movida")), {K: ac.DESBORDADO})
c("  rehecha", m.vigilar(K, T, IGN), None)
c("  lo que pasa en lo que salió ya no avisa",
  tras(m, lambda: (FUERA / "movida" / "hondo" / "c.txt").write_text("x")), {})
c("  y sus vigilancias se han quitado", m.vigilancias(), vigilancias - 2)
ENTRA = tmpdir("prdrive-entra-")
(ENTRA / "de-fuera" / "dentro").mkdir(parents=True)
c("meter una carpeta de fuera pide rehacer",
  tras(m, lambda: os.rename(ENTRA / "de-fuera", T / "de-fuera")), {K: ac.DESBORDADO})
m.vigilar(K, T, IGN)
c("  y, rehecha, lo de su subcarpeta se ve",
  tras(m, lambda: (T / "de-fuera" / "dentro" / "h.txt").write_text("h")), CAMBIO)
m._procesar(-1, ac.IN_Q_OVERFLOW, 0, "")
c("si el sistema perdió avisos (cola llena), pide rehacer: cuenta como cambio",
  tipos(m.recoger()), {K: ac.DESBORDADO})
c("lo que llega a la vez se queda con lo más grave",
  tras(m, lambda: ((T / "z.txt").write_text("z"), os.rename(T / "nueva", T / "nueva2"))),
  {K: ac.DESBORDADO})

# ---------------------------------------------------------------------------
# 3. El ruido del sistema en la raíz de la unidad
# ---------------------------------------------------------------------------
m3 = motor()
RU = arbol()
(RU / "$RECYCLE.BIN").mkdir()
(RU / "System Volume Information").mkdir()
c("en la raíz de la unidad se deja fuera el ruido del sistema",
  m3.vigilar(K, RU, IGN + model.RUIDO_DEL_SISTEMA), None)
c("  la papelera de Windows no avisa",
  tras(m3, lambda: (RU / "$RECYCLE.BIN" / "x").write_text("x")), {})
c("  ni la de Linux al crearse", tras(m3, lambda: (RU / ".Trash-1000").mkdir()), {})
c("  ni lo que cae en ella", tras(m3, lambda: (RU / ".Trash-1000" / "f").write_text("f")), {})
c("  lo demás, sí", tras(m3, lambda: (RU / "doc.txt").write_text("d")), CAMBIO)
c("  y una carpeta con ese nombre más abajo es de alguien: avisa",
  tras(m3, lambda: (RU / "sub" / "$RECYCLE.BIN").mkdir()), CAMBIO)

# ---------------------------------------------------------------------------
# 4. Parejas que se solapan
# ---------------------------------------------------------------------------
m4 = motor()
R = arbol()
RAIZ_P, SUB_P = (U, "raiz"), (U, "sub")
c("dos parejas solapadas se vigilan las dos",
  (m4.vigilar(RAIZ_P, R, IGN), m4.vigilar(SUB_P, R / "sub", ())), (None, None))
c("  y comparten las vigilancias de lo común", m4.vigilancias(), 3)
c("lo de la carpeta común avisa a las dos",
  tras(m4, lambda: (R / "sub" / "b.txt").write_text("1")), {RAIZ_P: ac.CAMBIO, SUB_P: ac.CAMBIO})
c("lo de fuera de la pequeña, solo a la grande",
  tras(m4, lambda: (R / "a.txt").write_text("1")), {RAIZ_P: ac.CAMBIO})
m4.dejar(SUB_P)
c("al dejar una, la otra sigue oyendo lo común",
  tras(m4, lambda: (R / "sub" / "hondo" / "c.txt").write_text("2")), {RAIZ_P: ac.CAMBIO})
c("  con sus vigilancias puestas", m4.vigilancias(), 3)
m4.dejar(RAIZ_P)
c("y al dejar las dos no queda ninguna", (m4.vigilancias(), tras(m4, lambda: (R / "a.txt")
                                                                 .write_text("3"))), (0, {}))
m4.vigilar(RAIZ_P, R, IGN)
m4.vigilar(SUB_P, R / "sub", ())
os.rename(R / "sub", R / "sub2")
c("mover la carpeta de la pequeña: la grande rehace y la pequeña se pierde",
  tipos(m4.recoger()), {RAIZ_P: ac.DESBORDADO, SUB_P: ac.PERDIDA})
m4.dejar_raiz(U)
c("dejar todas las de una raíz", m4.vigilancias(), 0)

# ---------------------------------------------------------------------------
# 5. La carpeta de la pareja se va
# ---------------------------------------------------------------------------
m5 = motor()
P = arbol()
m5.vigilar(K, P, IGN)
shutil.rmtree(P)
r = m5.recoger()
c("borrar la carpeta de la pareja la pierde, y se dice por qué",
  (tipos(r), bool(r.get(K, ac.Aviso("")).motivo)), ({K: ac.PERDIDA}, True))
c("  sin vigilancias puestas", m5.vigilancias(), 0)
c("  y lo que pase después no avisa de nada",
  tras(m5, lambda: P.mkdir() or (P / "a.txt").write_text("a")), {})
P2 = arbol()
m5.vigilar(K, P2, IGN)
os.rename(P2, P2.with_name(P2.name + "-movida"))
c("moverla, también", (tipos(m5.recoger()), m5.vigilancias()), ({K: ac.PERDIDA}, 0))
c("  y lo de dentro, ya en otro sitio, no avisa",
  tras(m5, lambda: (P2.with_name(P2.name + "-movida") / "sub" / "b.txt").write_text("x")), {})

# ---------------------------------------------------------------------------
# 6. Lo que no se vigila, y por qué
# ---------------------------------------------------------------------------
real_sistema = ac.sistema_de
ac.sistema_de = lambda carpeta: "nfs4"
m6 = motor()
motivo = m6.vigilar(K, arbol(), IGN)
c("una carpeta de red no se vigila con avisos, y se dice por qué",
  ("nfs4" in (motivo or ""), m6.vigilancias()), (True, 0))
ac.sistema_de = real_sistema
c("de qué sistema es una carpeta: /proc es proc", ac.sistema_de("/proc/self"), "proc")
c("  y la de un temporal tiene alguno", bool(ac.sistema_de(tempfile.gettempdir())), True)
c("  una que no existe, el de donde estaría", bool(ac.sistema_de("/no/existe/x")), True)

real_limite = ac.limite_de_vigilancias
ac.limite_de_vigilancias = lambda: 6                    # el agente usa, como mucho, 3
m7 = motor()
B = arbol()
c("lo que cabe en el presupuesto se vigila", m7.vigilar(K, B, IGN), None)
r = tras(m7, lambda: (B / "una-mas").mkdir())
c("  una carpeta nueva que no cabe pierde la pareja (y se dice por qué)",
  (r, m7.vigilancias()), ({K: ac.PERDIDA}, 0))
motivo = m7.vigilar(K, B, IGN)
c("pasado el presupuesto (la mitad de max_user_watches) no se vigila, y se dice",
  ("carpetas" in (motivo or ""), "max_user_watches" in (motivo or "")), (True, True))
c("  sin dejar nada puesto", m7.vigilancias(), 0)
ac.limite_de_vigilancias = real_limite
c("el límite de verdad se lee del sistema", real_limite() > 0, True)

m8 = motor()
real_add = m8._add_watch
llamadas = [0]


def add_sin_sitio(ruta):
    """Un `inotify_add_watch` que a la tercera dice que el sistema no da más."""
    llamadas[0] += 1
    if llamadas[0] == 3:
        raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC), ruta)
    return real_add(ruta)


m8._add_watch = add_sin_sitio
motivo = m8.vigilar(K, arbol(), IGN)
c("sin vigilancias en el sistema (ENOSPC) no se vigila, y se dice",
  "max_user_watches" in (motivo or ""), True)
c("  sin dejar nada puesto", m8.vigilancias(), 0)

m9 = motor()
real_add9 = m9._add_watch
llamadas9 = [0]


def add_y_dejar(ruta):
    """Deja la pareja mientras se está poniendo (la unidad se va a medias)."""
    llamadas9[0] += 1
    if llamadas9[0] == 2:
        m9.dejar(K)
    return real_add9(ruta)


m9._add_watch = add_y_dejar
c("dejar una pareja mientras se pone la para", m9.vigilar(K, arbol(), IGN), ac.DEJADA)
c("  sin dejar nada puesto", m9.vigilancias(), 0)
c("una carpeta que no existe no se vigila, y se dice",
  bool(motor().vigilar(K, Path(tempfile.gettempdir()) / "prdrive-no-existe-xyz", IGN)), True)

m10 = motor()
D = arbol()
m10.vigilar(K, D, IGN)
(D / "x.txt").write_text("x", encoding="utf-8")
m10.descartar(K)
c("descartar tira lo pendiente de esa pareja", m10.recoger(), {})
m10.cerrar()
c("cerrado no lanza: ni leer ni recoger", (m10.leer(), m10.recoger()), (None, {}))

# ---------------------------------------------------------------------------
# 7. Desmontar con las vigilancias puestas
# ---------------------------------------------------------------------------
PUNTO = tmpdir("prdrive-montaje-")
montado = os.geteuid() == 0 and subprocess.run(
    ["mount", "-t", "tmpfs", "prdrive-prueba", str(PUNTO)],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
if montado:
    try:
        (PUNTO / "datos" / "sub").mkdir(parents=True)
        mm = motor()
        c("en una unidad montada se vigila", mm.vigilar(K, PUNTO / "datos", IGN), None)
        rc = subprocess.run(["umount", str(PUNTO)], stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL).returncode
        c("desmontar con las vigilancias puestas funciona", rc, 0)
        c("  y la pareja se pierde", tipos(mm.recoger()), {K: ac.PERDIDA})
        c("  sin vigilancias que quitar", mm.vigilancias(), 0)
    finally:
        subprocess.run(["umount", "-l", str(PUNTO)], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)
else:
    print("  (saltado) sin permisos para montar: no se prueba desmontar con vigilancias")

for mo in MOTORES:
    mo.cerrar()
raise SystemExit(c.report())
