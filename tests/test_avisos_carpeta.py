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
- El vigía del agente (`agente.Vigia.oir()`) vacía el descriptor en cuanto
  tiene algo, pero una ráfaga no adelanta la vuelta ni la hace girar más.

Windows (`ReadDirectoryChanges`), con un `Win32` de mentira en cualquier
sistema: un aviso es un cambio, lo ignorado no lo es, el desbordamiento pide
nada más que contar como cambio, un error pierde la pareja; ni una carpeta de
red ni un volumen de VeraCrypt se dejan abiertos; sin aviso de extracción
registrado no se deja el handle; «Expulsar» del sistema (`DBT_DEVICEQUERYREMOVE`)
cierra el handle y, si la extracción no sigue adelante, se vuelve a abrir. Con
el Windows de verdad (solo en Windows) lo básico: un cambio, lo ignorado, el
búfer desbordado y que tras `dejar()` la carpeta se puede borrar.

inotify solo se prueba en Linux; en los demás sistemas esa parte se salta.
"""

import errno
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import struct
import time
from pathlib import Path
from types import SimpleNamespace

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

# ---------------------------------------------------------------------------
# Windows: ReadDirectoryChangesW, con un Win32 de mentira (en cualquier sistema)
# ---------------------------------------------------------------------------
def paquete(entradas: list[tuple[int, str]]) -> bytes:
    """Un búfer de `FILE_NOTIFY_INFORMATION` como el que llena Windows."""
    trozos = []
    for i, (accion, nombre) in enumerate(entradas):
        n = nombre.encode("utf-16-le")
        largo = 12 + len(n)
        largo += -largo % 4
        siguiente = 0 if i == len(entradas) - 1 else largo
        trozos.append((struct.pack("<III", siguiente, accion, len(n)) + n).ljust(largo, b"\0"))
    return b"".join(trozos)


c("el búfer de Windows: acción y nombre relativo de cada entrada",
  ac.avisos_de_windows(paquete([(1, "a.txt"), (3, "sub\\ñandú.txt")])),
  [(1, "a.txt"), (3, "sub\\ñandú.txt")])
c("  vacío, nada", ac.avisos_de_windows(b""), [])


def error_windows(codigo: int) -> OSError:
    """Un `OSError` con su `winerror`, como el de `ctypes.WinError()`."""
    e = OSError(0, f"error {codigo}")
    e.winerror = codigo
    return e


class Win32Falsa:
    """Un Windows de mentira para el motor de avisos: apunta lo que se le pide.

    Los handles son números; los eventos, `threading.Event`; cada lectura
    pendiente se completa a mano con `completar()`.

    Attributes:
        abiertos: Los handles de carpeta abiertos, con su ruta.
        registrados: Los avisos de extracción registrados, con su handle.
        lecturas: Las lecturas pendientes, por handle: `(overlapped, búfer)`.
        lanzadas: Cuántas lecturas se han lanzado, por handle.
        eventos_vivos: Los eventos creados y no cerrados.
        unidades: El tipo de unidad de cada raíz (`GetDriveTypeW`), si no es fija.
        dispositivos: El dispositivo de cada letra (`QueryDosDeviceW`).
        fallar_registro: Si `RegisterDeviceNotificationW` falla.
        hwnds: Las ventanas a las que se registraron avisos.
    """

    def __init__(self) -> None:
        """Un Windows sin nada abierto."""
        self.abiertos: dict[int, str] = {}
        self.registrados: dict[int, int] = {}
        self.lecturas: dict[int, tuple] = {}
        self.lanzadas: dict[int, int] = {}
        self.eventos_vivos: set = set()
        self.unidades: dict[str, int] = {}
        self.dispositivos: dict[str, str] = {}
        self.fallar_registro = False
        self.hwnds: list = []
        self._n = 100
        self._cerrojo = threading.Lock()

    def _nuevo(self) -> int:
        """Un número de handle nuevo."""
        with self._cerrojo:
            self._n += 1
            return self._n

    def tipo_de_unidad(self, raiz: str) -> int:
        """`GetDriveTypeW`: fija salvo que se diga otra cosa."""
        return self.unidades.get(raiz.upper(), 3)

    def dispositivo_de(self, unidad: str) -> str:
        """`QueryDosDeviceW`: un disco salvo que se diga otra cosa."""
        return self.dispositivos.get(unidad.upper(), "\\Device\\HarddiskVolume3")

    def abrir_carpeta(self, ruta: str) -> int:
        """`CreateFileW` de una carpeta: un handle nuevo."""
        h = self._nuevo()
        self.abiertos[h] = ruta
        return h

    def cerrar(self, h: int) -> None:
        """`CloseHandle`: lo que estuviera leyendo se cancela."""
        self.abiertos.pop(h, None)
        self.cancelar(h, None)

    def registrar(self, hwnd, h: int) -> int:
        """`RegisterDeviceNotificationW` de un handle."""
        if self.fallar_registro:
            return 0
        self.hwnds.append(hwnd)
        a = self._nuevo()
        self.registrados[a] = h
        return a

    def desregistrar(self, aviso: int) -> None:
        """`UnregisterDeviceNotification`."""
        self.registrados.pop(aviso, None)

    def evento(self):
        """`CreateEventW`."""
        ev = threading.Event()
        self.eventos_vivos.add(ev)
        return ev

    def cerrar_evento(self, ev) -> None:
        """`CloseHandle` de un evento."""
        self.eventos_vivos.discard(ev)

    def poner(self, ev) -> None:
        """`SetEvent`."""
        ev.set()

    def quitar(self, ev) -> None:
        """`ResetEvent`."""
        ev.clear()

    def overlapped(self, ev):
        """Un `OVERLAPPED` con su evento."""
        return SimpleNamespace(evento=ev, n=0, error=0)

    def bufer(self, n: int) -> bytearray:
        """El búfer de una lectura."""
        return bytearray(n)

    def bytes_de(self, bufer: bytearray, n: int) -> bytes:
        """Los primeros `n` bytes del búfer."""
        return bytes(bufer[:n])

    def leer_cambios(self, h: int, bufer, ov, tam: int) -> None:
        """`ReadDirectoryChangesW` superpuesta: queda pendiente."""
        if h not in self.abiertos:
            raise error_windows(6)
        ov.n, ov.error = 0, 0
        self.lecturas[h] = (ov, bufer)
        self.lanzadas[h] = self.lanzadas.get(h, 0) + 1

    def resultado(self, h: int, ov) -> int:
        """`GetOverlappedResult` sin esperar."""
        if ov.error:
            raise error_windows(ov.error)
        return ov.n

    def cancelar(self, h: int, ov) -> None:
        """`CancelIoEx`: la lectura acaba con `ERROR_OPERATION_ABORTED`."""
        pendiente = self.lecturas.pop(h, None)
        if pendiente is not None:
            pendiente[0].error = ac.ERROR_OPERATION_ABORTED
            pendiente[0].evento.set()

    def esperar(self, eventos: list, ms: int) -> int:
        """`WaitForMultipleObjects` de cualquiera."""
        while True:
            for i, ev in enumerate(eventos):
                if ev.is_set():
                    return i
            time.sleep(0.002)

    def senalado(self, ev) -> bool:
        """`WaitForSingleObject` sin esperar."""
        return ev.is_set()

    # Lo que hace «el sistema» en los tests.
    def completar(self, h: int, entradas=None, error: int = 0) -> None:
        """Acaba la lectura pendiente de un handle con esos avisos (o ese error)."""
        ov, bufer = self.lecturas.pop(h)
        if error:
            ov.error = error
        else:
            datos = paquete(entradas or [])
            bufer[:len(datos)] = datos
            ov.n = len(datos)
        ov.evento.set()


def hasta(condicion, segundos: float = 3.0) -> bool:
    """Espera a que se cumpla algo que hace el hilo del motor."""
    fin = time.monotonic() + segundos
    while time.monotonic() < fin:
        if condicion():
            return True
        time.sleep(0.005)
    return condicion()


def tipos_w(motor) -> dict:
    """Los avisos recogidos del motor de Windows, con su tipo."""
    return {k: a.tipo for k, a in motor.recoger().items()}


UW = "w" * 32
KW = (UW, "docs")
IGNW = (".prversions", ".prdrive", ".keychain")
HWND = 0x1234
w = Win32Falsa()
mw = ac.ReadDirectoryChanges(w, HWND)
c("Windows: se vigila una carpeta local", mw.vigilar(KW, "E:\\datos\\docs", IGNW), None)
hw = next(iter(w.abiertos))
c("  con su handle abierto, su aviso de extracción en la ventana de la bandeja y una lectura",
  (w.abiertos[hw], list(w.registrados.values()), w.hwnds, hw in w.lecturas,
   mw.vigilancias()), ("E:\\datos\\docs", [hw], [HWND], True, 1))
c("  el motor no tiene descriptor para el vigía", (mw.fd, mw.leer()), (None, None))
c("  volver a pedirla no abre otra", (mw.vigilar(KW, "E:\\datos\\docs", IGNW), len(w.abiertos)),
  (None, 1))
w.completar(hw, [(ac.FILE_ACTION_ADDED, "nuevo.txt")])
c("un aviso es un cambio", hasta(lambda: KW in mw._pendientes) and tipos_w(mw), {KW: ac.CAMBIO})
c("  y la lectura se vuelve a lanzar al momento", hasta(lambda: w.lanzadas.get(hw) == 2), True)
w.completar(hw, [(ac.FILE_ACTION_ADDED, ".prversions\\v~1.txt"),
                 (ac.FILE_ACTION_MODIFIED, ".prdrive"),
                 (ac.FILE_ACTION_MODIFIED, ".PRDRIVE\\state\\daemon.log")])
hasta(lambda: w.lanzadas.get(hw) == 3)
c("lo de .prversions/ y .prdrive/ (sin mirar mayúsculas) no es un cambio", tipos_w(mw), {})
w.completar(hw, [(ac.FILE_ACTION_MODIFIED, "sub\\.prversions\\x")])
hasta(lambda: w.lanzadas.get(hw) == 4)
c("  más abajo, un nombre así es de alguien: sí", tipos_w(mw), {KW: ac.CAMBIO})
w.completar(hw, [])
hasta(lambda: w.lanzadas.get(hw) == 5)
c("un búfer desbordado (0 bytes) cuenta como cambio", tipos_w(mw), {KW: ac.DESBORDADO})
w.completar(hw, error=ac.ERROR_NOTIFY_ENUM_DIR)
hasta(lambda: w.lanzadas.get(hw) == 6)
c("  y ERROR_NOTIFY_ENUM_DIR también", tipos_w(mw), {KW: ac.DESBORDADO})
w.completar(hw, [(ac.FILE_ACTION_ADDED, "x")])
hasta(lambda: w.lanzadas.get(hw) == 7)
c("descartar tira lo de la pasada y dice qué era",
  ((mw.descartar(KW) or ac.Aviso("")).tipo, mw.recoger()), (ac.CAMBIO, {}))

mw.dejar(KW)
c("dejar cierra el handle y quita el aviso de extracción en el acto",
  (w.abiertos, w.registrados, mw.vigilancias()), ({}, {}, 0))
c("  y el evento de la lectura cancelada se cierra cuando acaba",
  hasta(lambda: len(w.eventos_vivos) == 1), True)

mw.vigilar(KW, "E:\\datos\\docs", IGNW)
hw = next(iter(w.abiertos))
w.completar(hw, error=5)                                    # ERROR_ACCESS_DENIED
c("otro error de la lectura (la carpeta se borró) pierde la pareja, y se dice",
  hasta(lambda: KW in mw._pendientes) and (tipos_w(mw), w.abiertos, w.registrados),
  ({KW: ac.PERDIDA}, {}, {}))

w.unidades["\\\\NAS\\COMPARTIDA\\"] = ac.DRIVE_REMOTE
motivo = mw.vigilar(KW, "\\\\nas\\compartida\\docs", IGNW)
c("una carpeta de red no se vigila con avisos, y se dice", ("red" in (motivo or ""), w.abiertos),
  (True, {}))
w.dispositivos["P:"] = "\\Device\\VeraCryptVolumeP"
motivo = mw.vigilar(KW, "P:\\notas", IGNW)
c("un volumen de VeraCrypt tampoco: se recorre hasta probarlo en un equipo real",
  ("VeraCrypt" in (motivo or ""), w.abiertos), (True, {}))
w.fallar_registro = True
motivo = mw.vigilar(KW, "E:\\datos\\docs", IGNW)
c("sin aviso de extracción registrado no se deja el handle abierto",
  (bool(motivo), w.abiertos, w.lecturas), (True, {}, {}))
w.fallar_registro = False

# «Expulsar» del sistema: DBT_DEVICEQUERYREMOVE.
mw.vigilar(KW, "E:\\datos\\docs", IGNW)
hw = next(iter(w.abiertos))
mw.dispositivo(ac.DBT_DEVICEQUERYREMOVE, hw)
c("el sistema pide la unidad: el handle se cierra en el acto", w.abiertos, {})
c("  sin avisar de nada (la unidad se va) y sin dejar el registro todavía",
  (hasta(lambda: not w.lecturas) and tipos_w(mw), len(w.registrados)), ({}, 1))
mw.dispositivo(ac.DBT_DEVICEQUERYREMOVEFAILED, hw)
c("si al final no se extrae, se vuelve a abrir y a leer",
  hasta(lambda: len(w.abiertos) == 1 and bool(w.lecturas)), True)
c("  con su aviso de extracción nuevo", list(w.registrados.values()), list(w.abiertos))
hw = next(iter(w.abiertos))
mw.dispositivo(ac.DBT_DEVICEQUERYREMOVE, hw)
mw.dispositivo(ac.DBT_DEVICEREMOVECOMPLETE, hw)
c("si se extrae, la pareja se pierde y no queda nada",
  (tipos_w(mw), w.abiertos, w.registrados), ({KW: ac.PERDIDA}, {}, {}))
mw.vigilar(KW, "E:\\datos\\docs", IGNW)
hw = next(iter(w.abiertos))
mw.dispositivo(ac.DBT_DEVICEREMOVECOMPLETE, hw)
c("una unidad arrancada sin preguntar, igual", (tipos_w(mw), w.abiertos, w.registrados),
  ({KW: ac.PERDIDA}, {}, {}))
mw.dispositivo(ac.DBT_DEVICEQUERYREMOVE, 999)
c("un handle que no es nuestro no toca nada", tipos_w(mw), {})

mw.vigilar(KW, "E:\\datos\\docs", IGNW)
mw.vigilar((UW, "otra"), "E:\\otra", IGNW)
mw.dejar_raiz(UW)
c("dejar una raíz cierra todas sus parejas", (w.abiertos, w.registrados, mw.vigilancias()),
  ({}, {}, 0))

cuantas = [mw.vigilar((UW, f"p{i}"), f"E:\\p{i}", ()) for i in range(ac.MAX_PAREJAS_WINDOWS + 1)]
c("hasta 63 parejas; la siguiente se recorre, y se dice",
  (cuantas[:-1] == [None] * ac.MAX_PAREJAS_WINDOWS, bool(cuantas[-1]),
   len(w.abiertos)), (True, True, ac.MAX_PAREJAS_WINDOWS))
mw.dejar_raiz(UW)

real_pedir = mw._pedir_armar


def pedir_y_dejar(clave, ruta, patrones):
    """Deja la pareja justo antes de que el hilo la ponga."""
    mw.dejar(clave)
    return real_pedir(clave, ruta, patrones)


mw._pedir_armar = pedir_y_dejar
c("dejar una pareja mientras se pone la para", mw.vigilar(KW, "E:\\datos\\docs", IGNW),
  ac.DEJADA)
c("  sin dejar nada abierto", w.abiertos, {})
mw._pedir_armar = real_pedir
mw.vigilar(KW, "E:\\datos\\docs", IGNW)
mw.cerrar()
c("cerrar el motor cierra todo y acaba su hilo",
  (w.abiertos, w.registrados, mw._hilo.is_alive()), ({}, {}, False))
c("abrir() sin la ventana de la bandeja no da motor en Windows",
  ac.abrir(hwnd=None) is None or not sys.platform.startswith("win"), True)

# ---------------------------------------------------------------------------
# Windows de verdad
# ---------------------------------------------------------------------------
if sys.platform.startswith("win"):
    api = ac.Win32()
    api.registrar = lambda hwnd, h: 1                      # sin ventana en la prueba
    api.desregistrar = lambda aviso: None
    unidad = os.path.splitdrive(tempfile.gettempdir())[0]
    c("Windows de verdad: el temporal no es de red ni de VeraCrypt",
      (api.tipo_de_unidad(unidad + "\\") != ac.DRIVE_REMOTE,
       api.dispositivo_de(unidad).startswith(ac.DISPOSITIVOS_VERACRYPT)), (True, False))
    mr = ac.ReadDirectoryChanges(api, 1)
    WR = tmpdir("prdrive-avisos-w-")
    (WR / ".prversions").mkdir()
    c("  se vigila una carpeta", mr.vigilar(KW, WR, IGNW), None)
    (WR / ".prversions" / "v.txt").write_text("v", encoding="utf-8")
    time.sleep(0.5)
    c("  lo de .prversions/ no avisa", tipos_w(mr), {})
    (WR / "a.txt").write_text("a", encoding="utf-8")
    c("  un fichero nuevo avisa", hasta(lambda: KW in mr._pendientes) and tipos_w(mr),
      {KW: ac.CAMBIO})
    mr.dejar(KW)
    shutil.rmtree(WR)
    c("  tras dejarla, la carpeta se puede borrar entera", WR.exists(), False)
    mr.cerrar()
    mp = ac.ReadDirectoryChanges(api, 1, tam_bufer=16)
    WP = tmpdir("prdrive-avisos-w-")
    mp.vigilar(KW, WP, IGNW)
    (WP / ("un-nombre-largo-que-no-cabe-" * 3 + ".txt")).write_text("x", encoding="utf-8")
    c("  un búfer que no da para el aviso cuenta como desbordado",
      hasta(lambda: KW in mp._pendientes) and tipos_w(mp), {KW: ac.DESBORDADO})
    mp.cerrar()
else:
    print("  (saltado) ReadDirectoryChangesW de verdad: solo en Windows")

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
c("descartar tira lo pendiente de esa pareja, y dice qué era",
  ((m10.descartar(K) or ac.Aviso("")).tipo, m10.recoger()), (ac.CAMBIO, {}))
os.rename(D / "sub", D / "sub-movida")
c("  un desbordado tirado se devuelve: hay que rehacer igual",
  ((m10.descartar(K) or ac.Aviso("")).tipo, m10.recoger()), (ac.DESBORDADO, {}))
c("  y si no hay nada, nada", m10.descartar(K), None)
D2 = arbol()
m10.vigilar((U, "otra"), D2, IGN)
shutil.rmtree(D2)
c("una pérdida no se tira: la pareja ya no se vigila y hay que saberlo",
  (m10.descartar((U, "otra")), tipos(m10.recoger())), (None, {(U, "otra"): ac.PERDIDA}))
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

# ---------------------------------------------------------------------------
# 8. El vigía del agente
# ---------------------------------------------------------------------------
import agente  # noqa: E402

DIARIO: list[str] = []
agente.diario = DIARIO.append
mv = motor()
VV = arbol()
mv.vigilar(K, VV, IGN)
vigia = agente.Vigia()
leidas = [0]


def leer_y_contar() -> None:
    """Lo que el agente le da al vigía: leer el descriptor; aquí, contando."""
    leidas[0] += 1
    mv.leer()


def rafaga(segundos: float) -> threading.Thread:
    """Escribe un fichero cada 10 ms durante esos segundos, en otro hilo."""
    def escribir() -> None:
        fin, i = time.monotonic() + segundos, 0
        while time.monotonic() < fin:
            (VV / f"r{i}.txt").write_text("r", encoding="utf-8")
            i += 1
            time.sleep(0.01)
    h = threading.Thread(target=escribir, daemon=True)
    h.start()
    return h


vigia.oir(mv.fd, leer_y_contar)
h = rafaga(1.0)
t = time.monotonic()
montajes = vigia.esperar(1.0)
dura = time.monotonic() - t
h.join()
c("vigía: una ráfaga de avisos no adelanta la vuelta ni la toma por montajes",
  (montajes, dura >= 0.95), (False, True))
c("  y el descriptor se lee a ratos, no con cada aviso",
  1 <= leidas[0] <= 1.0 / agente.CALLAR_AVISOS + 2, True)
c("  lo leído se guarda para la vuelta", tipos(mv.recoger()), CAMBIO)
h = rafaga(1.5)
threading.Timer(0.3, vigia.despertar).start()
t = time.monotonic()
vigia.esperar(5.0)
c("despertar corta la espera aunque lleguen avisos", time.monotonic() - t < 1.0, True)
h.join()
mv.recoger()
t = time.monotonic()
c("  y sin nada, espera su tiempo", (vigia.esperar(0.3), time.monotonic() - t >= 0.25),
  (False, True))

rotas = [0]


def leer_roto() -> None:
    """Un `leer` que falla: el vigía deja de oírlo, no gira en vacío."""
    rotas[0] += 1
    raise OSError("roto")


vigia2 = agente.Vigia()
vigia2.oir(mv.fd, leer_roto)
(VV / "despierta.txt").write_text("x", encoding="utf-8")
t = time.monotonic()
vigia2.esperar(0.3)
vigia2.esperar(0.3)
c("un leer que falla se deja de oír: sin girar en vacío y dicho una vez",
  (rotas[0], time.monotonic() - t >= 0.55,
   sum("avisos de las carpetas" in m for m in DIARIO)), (1, True, 1))

if montado:
    vigia3 = agente.Vigia()
    vigia3.oir(mv.fd, mv.leer)
    PUNTO2 = tmpdir("prdrive-montaje-")
    threading.Timer(0.2, lambda: subprocess.run(
        ["mount", "-t", "tmpfs", "prdrive-prueba", str(PUNTO2)])).start()
    t = time.monotonic()
    c("con los avisos oídos, un montaje nuevo se sigue viendo al momento",
      (vigia3.esperar(5.0), time.monotonic() - t < 2.0), (True, True))
    subprocess.run(["umount", "-l", str(PUNTO2)], stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL)

for mo in MOTORES:
    mo.cerrar()
raise SystemExit(c.report())
