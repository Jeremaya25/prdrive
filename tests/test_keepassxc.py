#!/usr/bin/env python3
"""«Abrir llavero»: KeePassXC en este equipo (`common/keepassxc.py`, `ui/llavero_editor.py`).

Sin Windows, sin registro y sin lanzar nada: el registro es un diccionario, los
procesos se dicen, y `lanzar()` apunta la orden. Lo que se sujeta:
- La configuración se edita línea a línea: cambian las claves pedidas y el
  resto queda byte a byte, con su fin de línea. Lo de «solo al crear» no pisa
  lo que cambió la persona, y las rutas recientes se mueven a la raíz de ahora.
- El navegador: al abrir, las cuatro claves apuntan a los JSON de la unidad;
  al cerrar, solo las de prdrive se quitan o vuelven a un KeePassXC instalado,
  y `NativeMessagingHosts` se va solo si se queda vacía.
- La ruta del fichero llave es de cada equipo, y el fichero no se toca.
- Los pasos de «Abrir llavero», en su orden, con lo que se dice en cada caso,
  y la línea de la ventana.
"""

import contextlib
import io
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from _harness import Checks, sandbox, tmpdir

import ui
import ui.tk as uitk
from common import components, keepassxc, llavero, model, pins, registro, results, store
from ui import llavero_editor

c = Checks("abrir el llavero (common/keepassxc.py)")

# --- la configuración, línea a línea
GENERAL = {"UseAtomicSaves": "true", "GUI/CheckForUpdates": "false"}

nuevo = keepassxc.editar_ini("", GENERAL)
c("un ini nuevo: cada clave en su sección, con el fin de línea de QSettings en Windows",
  nuevo, "[General]\r\nUseAtomicSaves=true\r\n\r\n[GUI]\r\nCheckForUpdates=false\r\n")

PERSONA = ("[General]\nConfigVersion=2\nuseatomicsaves=false\n; una nota a mano\n"
           "MinimizeOnStartup=true\n\n[Browser]\nEnabled=true\n")
editado = keepassxc.editar_ini(PERSONA, {**GENERAL, "Browser/UpdateBinaryPath": "true"})
c("uno de la persona: cambia lo pedido, añade lo que falta en su sección y respeta el resto",
  editado, "[General]\nConfigVersion=2\nuseatomicsaves=true\n; una nota a mano\n"
  "MinimizeOnStartup=true\n\n[Browser]\nEnabled=true\nUpdateBinaryPath=true\n\n"
  "[GUI]\nCheckForUpdates=false\n")
c("  sin nada que cambiar, el mismo texto",
  keepassxc.editar_ini(editado, {**GENERAL, "Browser/UpdateBinaryPath": "true"}), editado)
c("  sin fin de línea al final, se lo pone para escribir detrás",
  keepassxc.editar_ini("[GUI]\r\nX=1", {"GUI/Y": "2"}), "[GUI]\r\nX=1\r\nY=2\r\n")
c("  las claves de antes de toda sección son de [General]",
  keepassxc.editar_ini("UseAtomicSaves=false\n[GUI]\nX=1\n", GENERAL),
  "UseAtomicSaves=true\n[GUI]\nX=1\nCheckForUpdates=false\n")
c("  cambiar() solo ve las que no van en valores, con su valor tal cual",
  keepassxc.editar_ini("[General]\nA=1\nB= 2\n", {"A": "9"},
                       lambda clave, valor: f"<{clave}{valor}>"),
  "[General]\nA=9\nB=<B 2>\n")

# las rutas recientes
c("la raíz de una unidad", keepassxc.forma_ini(Path("E:/")), "E:")
c("  y de una carpeta, con / ", keepassxc.forma_ini("C:\\Users\\Ana\\mi raiz\\"),
  "C:/Users/Ana/mi raiz")
for mala in ("C:/Usuarios/José", "C:/a,b", 'C:/"x"', " C:/x"):
    c(f"  {mala!r} no se busca tal cual: QSettings la escaparía", keepassxc.forma_ini(mala), None)
mover = keepassxc.mover_raiz
c("una ruta", mover("E:/.keychain/personal.kdbx", "E:", "F:"), "F:/.keychain/personal.kdbx")
c("  una lista", mover("E:/.keychain/a.kdbx, D:/otra.kdbx, e:/b.kdbx", "E:", "F:"),
  "F:/.keychain/a.kdbx, D:/otra.kdbx, F:/b.kdbx")
c("  entrecomillada", mover('"E:/a, b.kdbx", "E:/c.kdbx"', "E:", "F:"),
  '"F:/a, b.kdbx", "F:/c.kdbx"')
c("  con \\\\ como la escribe QSettings", mover("E:\\\\.keychain\\\\a.kdbx", "E:", "F:"),
  "F:\\\\.keychain\\\\a.kdbx")
c("  la raíz sola", mover("E:/", "E:", "F:"), "F:/")
c("  y una carpeta, con sus barras", mover("C:\\\\raiz\\\\a.kdbx, C:/raiz/b.kdbx",
                                          "C:/raiz", "D:/otra"),
  "D:\\\\otra\\\\a.kdbx, D:/otra/b.kdbx")
c("  ni otra letra ni otra carpeta que empieza igual",
  (mover("EE:/a.kdbx", "E:", "F:"), mover("C:/raiz2/a.kdbx", "C:/raiz", "D:/x")),
  ("EE:/a.kdbx", "C:/raiz2/a.kdbx"))


def fin_de_linea(ruta: Path) -> bool:
    """Indica si todas las líneas del fichero acaban en \\r\\n."""
    datos = ruta.read_bytes()
    return datos.count(b"\n") == datos.count(b"\r\n") > 0


real_app = model.APP_DIR
try:
    with sandbox() as root:
        model.APP_DIR = root / ".prdrive"
        donde = keepassxc.carpeta_config()
        escritos = keepassxc.ajustar_config(Path("E:/"))
        ini = (donde / keepassxc.INI).read_bytes().decode("utf-8")
        local = (donde / keepassxc.INI_LOCAL).read_bytes().decode("utf-8")
        c("la primera vez se crean los dos ficheros y la raíz",
          escritos, [keepassxc.INI, keepassxc.INI_LOCAL, keepassxc.RAIZ])
        c("  en .prdrive/keepassxc/config/windows/, fuera de la carpeta del programa",
          donde.relative_to(model.APP_DIR).as_posix(), "keepassxc/config/windows")
        for clave, valor in {**keepassxc.SIEMPRE, **keepassxc.AL_CREAR}.items():
            c.contains(f"  {clave}={valor}", ini, f"{clave.split('/')[-1]}={valor}")
        c("  y el desbloqueo rápido apagado, en el del equipo (H-1)",
          local, "[Security]\r\nQuickUnlock=false\r\n")
        c("  con \\r\\n", (fin_de_linea(donde / keepassxc.INI),
                           fin_de_linea(donde / keepassxc.INI_LOCAL)), (True, True))
        c("  y la raíz apuntada", (donde / keepassxc.RAIZ).read_text(encoding="utf-8"), "E:\n")
        c("la segunda vez, igual, no se escribe nada", keepassxc.ajustar_config(Path("E:/")), [])

        # la persona cambia cosas; KeePassXC escribe sus recientes
        tocado = ini.replace("UseAtomicSaves=true", "UseAtomicSaves=false")
        (donde / keepassxc.INI).write_bytes(tocado.replace("Enabled=true", "Enabled=false")
                                            .encode("utf-8"))
        (donde / keepassxc.INI_LOCAL).write_bytes(
            b"[General]\r\nLastDatabases=E:/.keychain/personal.kdbx, C:/Users/a/otra.kdbx\r\n"
            b"LastDir=E:/\r\nLastKeyFiles=@Variant(\\0\\0\\0\\b)\r\n\r\n"
            b"[Security]\r\nQuickUnlock=true\r\n")
        keepassxc.ajustar_config(Path("F:/"))
        ini = (donde / keepassxc.INI).read_text(encoding="utf-8")
        local = (donde / keepassxc.INI_LOCAL).read_bytes()
        c("UseAtomicSaves se vuelve a encender en cada arranque (H-11)",
          "UseAtomicSaves=true" in ini, True)
        c("  pero lo de «solo al crear» se queda como lo dejó la persona",
          "Enabled=false" in ini, True)
        c("las recientes pasan a la raíz de ahora; lo demás, byte a byte", local,
          b"[General]\r\nLastDatabases=F:/.keychain/personal.kdbx, C:/Users/a/otra.kdbx\r\n"
          b"LastDir=F:/\r\nLastKeyFiles=@Variant(\\0\\0\\0\\b)\r\n\r\n"
          b"[Security]\r\nQuickUnlock=true\r\n")
        c("  y se apunta la raíz nueva", (donde / keepassxc.RAIZ).read_text(encoding="utf-8"),
          "F:\n")
        (donde / keepassxc.INI_LOCAL).write_bytes(b"[General]\r\nLastDir=caf\xe9\r\n")
        keepassxc.ajustar_config(Path("F:/"))
        c("un byte que no es UTF-8 sale como entró",
          (donde / keepassxc.INI_LOCAL).read_bytes(), b"[General]\r\nLastDir=caf\xe9\r\n")
finally:
    model.APP_DIR = real_app


# --- el navegador
class Registro:
    """HKCU de mentira: clave → valor predeterminado (`None` si no tiene)."""

    def __init__(self, inicial=None) -> None:
        self.claves: dict[str, str | None] = {}
        self.no_escribe: set[str] = set()
        for clave, valor in (inicial or {}).items():
            self.escribir(clave, valor)

    def _k(self, clave: str) -> str:
        return clave.lower()

    def leer(self, clave):
        return self.claves.get(self._k(clave))

    def escribir(self, clave, valor):
        if clave in self.no_escribe:
            raise OSError("acceso denegado")
        partes = clave.split("\\")
        for i in range(1, len(partes)):
            self.claves.setdefault(self._k("\\".join(partes[:i])), None)
        self.claves[self._k(clave)] = valor

    def _hijas(self, clave):
        prefijo = self._k(clave) + "\\"
        return [k for k in self.claves if k.startswith(prefijo)]

    def borrar(self, clave):
        if self._k(clave) not in self.claves:
            return False
        if self._hijas(clave):
            raise OSError("tiene subclaves")
        del self.claves[self._k(clave)]
        return True

    def vacia(self, clave):
        if self._k(clave) not in self.claves:
            return None
        return not self._hijas(clave) and self.claves[self._k(clave)] is None


def usar(reg: Registro) -> None:
    """Pone el registro de mentira en `common.registro`."""
    registro.leer, registro.escribir = reg.leer, reg.escribir
    registro.borrar, registro.vacia = reg.borrar, reg.vacia


CHROME, EDGE, MOZILLA, CHROMIUM = (keepassxc.clave_nativa(b) for b, _ in keepassxc.NAVEGADORES)
reales_registro = (registro.leer, registro.escribir, registro.borrar, registro.vacia)
real_local = os.environ.get("LOCALAPPDATA")
try:
    raiz = tmpdir("prdrive-kpxc-raiz-")
    model.APP_DIR = raiz / ".prdrive"
    exe = components.keepassxc_exe(model.APP_DIR, "windows-x64")
    reg = Registro({"Software\\Google\\Chrome\\NativeMessagingHosts\\com.otro.programa":
                    "C:\\Otro\\otro.json"})
    usar(reg)
    c("al abrir se escriben las cuatro claves", keepassxc.abrir_navegador(exe), [])
    c("  cada una a su JSON en <exe>/config/ (con .portable van ahí)",
      [reg.leer(k) for k in (CHROME, EDGE, MOZILLA, CHROMIUM)],
      [str(exe.parent / "config" / f"org.keepassxc.keepassxc_browser_{n}.json")
       for n in ("chrome", "edge", "firefox", "chromium")])
    reg.no_escribe.add(EDGE)
    c.contains("  lo que no se puede escribir se dice, y lo demás sigue",
               " ".join(keepassxc.abrir_navegador(exe)), "Microsoft\\Edge")
    reg.no_escribe.clear()

    # al cerrar: Chrome tiene otra clave al lado, y hay un KeePassXC instalado con
    # el JSON de Firefox y el de Brave (que comparte la clave de Chrome, H-5)
    suyo = tmpdir("prdrive-kpxc-local-")
    os.environ["LOCALAPPDATA"] = str(suyo)
    (suyo / "KeePassXC").mkdir()
    for nombre in ("firefox", "brave"):
        keepassxc.json_nativo(suyo / "KeePassXC", nombre).write_text("{}", encoding="utf-8")
    reg.escribir(CHROMIUM, "X:\\.prdrive\\keepassxc\\windows-x64\\config\\viejo.json")
    reg.escribir(EDGE, "C:\\Program Files\\Otro\\edge.json")
    plan = keepassxc.plan_cerrar_navegador(raiz)
    c("al cerrar, solo las de prdrive: las de esta unidad y las de una que ya no está",
      [p.clave for p in plan], [CHROME, MOZILLA, CHROMIUM])
    c("  las que tienen un KeePassXC instalado vuelven a él",
      [p.valor for p in plan[:2]],
      [str(keepassxc.json_nativo(suyo / "KeePassXC", "brave")),
       str(keepassxc.json_nativo(suyo / "KeePassXC", "firefox"))])
    c("  y las demás se borran", plan[2].valor, None)
    c("lo hace sin errores", keepassxc.cerrar_navegador(raiz), [])
    c("  la clave de otro programa sigue, y la de Edge, que no era nuestra",
      (reg.leer("Software\\Google\\Chrome\\NativeMessagingHosts\\com.otro.programa"),
       reg.leer(EDGE)), ("C:\\Otro\\otro.json", "C:\\Program Files\\Otro\\edge.json"))
    c("  NativeMessagingHosts de Chromium se va, vacía; la del navegador, no",
      (reg.vacia("Software\\Chromium\\NativeMessagingHosts"), reg.vacia("Software\\Chromium")),
      (None, True))
    c("  y otra vez, nada que hacer: las devueltas ya no son de prdrive",
      keepassxc.plan_cerrar_navegador(raiz), [])
finally:
    registro.leer, registro.escribir, registro.borrar, registro.vacia = reales_registro
    model.APP_DIR = real_app
    if real_local is None:
        os.environ.pop("LOCALAPPDATA", None)
    else:
        os.environ["LOCALAPPDATA"] = real_local
if os.name != "nt":
    c("fuera de Windows no hay registro", registro.leer(CHROME), None)
else:
    print("  (saltado) el registro de verdad no se toca en las pruebas")

# --- el fichero llave, por equipo
with sandbox() as root:
    c("sin apuntar, ninguna", keepassxc.llave_apuntada(), None)
    keepassxc.apuntar_llave(Path("D:/llaves/personal.keyx"))
    datos = store.read_json(keepassxc.registro_llaves())
    datos["equipos"]["otro-equipo"] = {"fichero_llave": "G:/personal.keyx"}
    store.write_json(keepassxc.registro_llaves(), datos)
    c("se apunta la de este equipo", keepassxc.llave_apuntada(), Path("D:/llaves/personal.keyx"))
    c("  en state/keychain.json", keepassxc.registro_llaves().name, "keychain.json")
    keepassxc.apuntar_llave(None)
    c("olvidarla deja la de los otros equipos",
      (keepassxc.llave_apuntada(), store.read_json(keepassxc.registro_llaves())["equipos"]),
      (None, {"otro-equipo": {"fichero_llave": "G:/personal.keyx"}}))

# --- lanzarlo
try:
    model.APP_DIR = Path("E:/.prdrive")
    exe = Path("E:/.prdrive/keepassxc/windows-x64/KeePassXC.exe")
    base = Path("E:/.keychain/personal.kdbx")
    donde = keepassxc.carpeta_config()
    c("la orden: su configuración, y la base",
      keepassxc.orden(exe, base),
      [str(exe), "--config", str(donde / "keepassxc.ini"),
       "--localconfig", str(donde / "keepassxc_local.ini"), str(base)])
    llave = Path("D:/k.keyx")
    c("  con el fichero llave de este equipo, --keyfile",
      keepassxc.orden(exe, base, llave)[-3:], ["--keyfile", str(llave), str(base)])
    c("lo que se exporte cae en la raíz (PK5)",
      keepassxc.entorno(Path("E:/"))["KPXC_INITIAL_DIR"], str(Path("E:/")))
finally:
    model.APP_DIR = real_app


class Proc:
    """Un proceso de mentira que sale con `codigo` a las `vueltas` miradas."""

    def __init__(self, codigo=None, vueltas=0):
        self.codigo, self.vueltas = codigo, vueltas

    def poll(self):
        if self.vueltas <= 0:
            return self.codigo
        self.vueltas -= 1
        return None


esperas: list = []
llavero.dormir = esperas.append
c("si sale enseguida sin el runtime de VC++, se ve su código",
  keepassxc.esperar_arranque(Proc(0xC0000135, 3), 5), 0xC0000135)
c("  y si sigue abierto, None", keepassxc.esperar_arranque(Proc(None), 0.05), None)

# los procesos: el KeePassXC de la unidad y otro del equipo
real_procesos = store.procesos
try:
    raiz = tmpdir("prdrive-kpxc-procesos-")
    model.APP_DIR = raiz / ".prdrive"
    rclone = components.rclone_path(model.APP_DIR, pins.plataforma("windows-x64"))
    rclone.parent.mkdir(parents=True)
    rclone.write_bytes(b"rclone")
    nuestro = components.keepassxc_exe(model.APP_DIR, "windows-x64")
    store.procesos = lambda: {10: str(nuestro), 11: str(raiz / "Firefox" / "firefox.exe")}
    c("el de la unidad no es «otro»", (keepassxc.otro_abierto(), llavero.keepassxc_abierto()),
      (False, True))
    store.procesos = lambda: {12: str(Path("C:/Program Files/KeePassXC/KeePassXC.exe"))}
    c("uno instalado sí", (keepassxc.otro_abierto(), llavero.keepassxc_abierto()),
      (True, False))
finally:
    store.procesos = real_procesos
    model.APP_DIR = real_app


# --- «Abrir llavero», paso a paso
DEF = {"remote": "nas", "catalog_path": "/prdrive-catalog/remote.toml"}
PAREJA = {"name": "notas", "local": "sync-data/notas", "remote_path": "/R/notas"}


def config(**llave):
    """Un config con llavero con esas claves; con `base=None`, sin llavero."""
    data = {"defaults": DEF, "pair": [PAREJA]}
    if llave.get("base", "personal.kdbx") is not None:
        data["keychain"] = {"base": "personal.kdbx", **llave}
    return model.parse_config(data)


class Equipo:
    """Lo que el flujo pregunta al equipo, dicho a mano, y lo que se ha lanzado."""

    def __init__(self) -> None:
        self.paquete = "windows-x64"
        self.nuestro = False
        self.otro = False
        self.servicio = False
        self.codigo = None
        self.lanzadas: list = []
        self.pasadas: list = []
        self.vigilantes = 0
        self.trae_base = True
        self.rc = 0
        self.reg = Registro()

    def pasada(self):
        self.pasadas.append(time.time())
        if self.trae_base:
            llavero.carpeta().mkdir(exist_ok=True)
            (llavero.carpeta() / "personal.kdbx").write_bytes(b"base")
        return self.rc, "salida"

    def lanzar(self, orden, entorno):
        self.lanzadas.append((orden, entorno))
        return Proc(self.codigo, 0 if self.codigo is not None else 10 ** 9)


def preparar(eq: Equipo) -> None:
    """Engancha `eq` en los puntos de sustitución."""
    keepassxc.paquete_del_equipo = lambda: eq.paquete
    llavero.keepassxc_abierto = lambda app_dir=None: eq.nuestro
    keepassxc.otro_abierto = lambda: eq.otro
    llavero.atiende_el_servicio = lambda: eq.servicio
    llavero.pasada = eq.pasada
    keepassxc.lanzar = eq.lanzar
    keepassxc.ESPERA_ARRANQUE = 0.01
    llavero.lanzar_vigilante = lambda: setattr(eq, "vigilantes", eq.vigilantes + 1)
    usar(eq.reg)


def abrir(cfg, llave=None, suelto=False):
    """Hace «Abrir llavero» apuntando lo que se dice y lo que se espera."""
    dicho, esperado, preguntas = [], [], []

    def esperar(mensaje, funcion):
        esperado.append(mensaje)
        try:
            return True, funcion()
        except Exception as e:                            # noqa: BLE001
            return False, e

    def elegir(nombre):
        preguntas.append(nombre)
        return llave

    hecho = llavero_editor.abrir(cfg, dicho.append, esperar, elegir,
                                 lambda plan, titulo, nota: False, decir_sin_traer=suelto)
    return hecho, dicho, esperado, preguntas


reales = (keepassxc.paquete_del_equipo, llavero.keepassxc_abierto, keepassxc.otro_abierto,
          llavero.atiende_el_servicio, llavero.pasada, keepassxc.lanzar,
          keepassxc.ESPERA_ARRANQUE, llavero.lanzar_vigilante)
try:
    with sandbox() as root:
        model.APP_DIR = root / ".prdrive"
        eq = Equipo()
        preparar(eq)
        exe = components.keepassxc_exe(model.APP_DIR, "windows-x64")

        c("sin llavero, se dice", abrir(config(base=None))[:2],
          (False, [keepassxc.SIN_LLAVERO]))
        eq.paquete = None
        c("fuera de Windows, se dice", abrir(config())[:2], (False, [keepassxc.SOLO_WINDOWS]))
        eq.paquete = "windows-x64"
        c("sin KeePassXC en la unidad, se dice cómo ponerlo", abrir(config())[:2],
          (False, [keepassxc.FALTA_KEEPASSXC]))
        exe.parent.mkdir(parents=True)
        exe.write_bytes(b"MZ")

        eq.otro = True
        c("con otro KeePassXC abierto, se dice y no se lanza nada",
          (abrir(config())[:2], eq.lanzadas), ((False, [llavero_editor.OTRO_ABIERTO]), []))
        eq.otro = False

        hecho, dicho, esperado, _ = abrir(config())
        c("sin base en el dispositivo: se trae, y se abre", (hecho, dicho, esperado),
          (True, [], [llavero_editor.TRAYENDO, llavero_editor.ABRIENDO]))
        orden, entorno = eq.lanzadas[-1]
        c("  con su configuración y la base", (orden[0], orden[-1]),
          (str(exe), str(llavero.carpeta() / "personal.kdbx")))
        c("  la configuración puesta", (keepassxc.carpeta_config() / keepassxc.INI).is_file(),
          True)
        c("  el navegador apuntado a la unidad", eq.reg.leer(MOZILLA),
          str(exe.parent / "config" / "org.keepassxc.keepassxc_browser_firefox.json"))
        c("  y el vigilante en marcha", eq.vigilantes, 1)

        results.apuntar(model.LLAVERO, 0, None)
        eq.pasadas.clear()
        abrir(config())
        c("con una pasada buena de hace nada, no se trae otra vez", eq.pasadas, [])
        datos = store.read_json(results.ruta_estado())
        hace_10_min = datetime.fromtimestamp(time.time() - 600)
        datos["parejas"][model.LLAVERO]["buena"] = f"{hace_10_min:{store.FORMATO}}"
        store.write_json(results.ruta_estado(), datos)
        abrir(config())
        c("  con una de hace más de 2 min, sí", len(eq.pasadas), 1)
        eq.servicio = True
        abrir(config())
        c("  salvo si el servicio atiende la raíz: lo trae él", len(eq.pasadas), 1)
        eq.servicio = False

        eq.rc = 7
        hecho, dicho, _, _ = abrir(config())
        c("si no se puede traer, se abre igual y la ventana no lo dice con un aviso",
          (hecho, dicho), (True, []))
        hecho, dicho, _, _ = abrir(config(), suelto=True)
        c("  suelto, sí", (hecho, dicho), (True, [llavero_editor.sin_traer(7)]))
        (llavero.carpeta() / "personal.kdbx").unlink()
        eq.trae_base = False
        c("sin base y sin poder traerla, no se abre",
          abrir(config())[:2], (False, [llavero_editor.sin_traer_base(7)]))
        eq.rc = 0
        c("  y si el remoto tampoco la tiene, se dice", abrir(config())[:2],
          (False, [llavero_editor.SIN_BASE]))
        eq.trae_base = True

        # el fichero llave
        llave = root / "personal.keyx"
        hecho, _, _, preguntas = abrir(config(fichero_llave=True, nombre_llave="personal.keyx"))
        c("con fichero llave y sin saber dónde está, se pregunta por su nombre",
          (hecho, preguntas, "--keyfile" in eq.lanzadas[-1][0]), (True, ["personal.keyx"], False))
        llave.write_bytes(b"secreto")
        hecho, _, _, preguntas = abrir(config(fichero_llave=True), llave=llave)
        c("  la ruta elegida se apunta y se pasa con --keyfile",
          (keepassxc.llave_apuntada(), eq.lanzadas[-1][0][-3:-1]),
          (llave, ["--keyfile", str(llave)]))
        c("  el fichero ni se toca", llave.read_bytes(), b"secreto")
        _, _, _, preguntas = abrir(config(fichero_llave=True))
        c("  la vez siguiente no se pregunta", (preguntas, eq.lanzadas[-1][0][-2]),
          ([], str(llave)))
        llave.unlink()
        _, _, _, preguntas = abrir(config(fichero_llave=True, nombre_llave="personal.keyx"))
        c("  si ya no está (otro pendrive), se vuelve a preguntar", preguntas, ["personal.keyx"])

        # ya abierto: solo se trae delante
        eq.nuestro = True
        ini = keepassxc.carpeta_config() / keepassxc.INI
        ini.write_text("[General]\nUseAtomicSaves=false\n", encoding="utf-8")
        eq.pasadas.clear()
        hecho, dicho, esperado, preguntas = abrir(config(fichero_llave=True))
        c("con el de la unidad ya abierto: sin pasada, sin pregunta, y se lanza para traerlo",
          (hecho, eq.pasadas, preguntas, esperado), (True, [], [], [llavero_editor.ABRIENDO]))
        c("  sin tocar su configuración, que la reescribiría al salir",
          ini.read_text(encoding="utf-8"), "[General]\nUseAtomicSaves=false\n")
        eq.nuestro = False

        # KeePassXC que no arranca
        eq.codigo = 0xC0000135
        hecho, dicho, _, _ = abrir(config())
        c("sin el runtime de Visual C++ (K3), se dice qué falta y dónde está",
          (hecho, dicho), (False, [llavero_editor.FALTA_RUNTIME]))
        c.contains("  con el instalador oficial", dicho[0], llavero_editor.REDISTRIBUIBLE)
        eq.codigo = 1
        c.contains("con otro código, se dice cuál", abrir(config())[1][0], "0x1")
        eq.codigo = 0
        c("con 0 enseguida (le pasó la base a uno abierto), bien", abrir(config())[:2],
          (True, []))
        eq.codigo = None
        eq.reg.no_escribe.add(EDGE)
        hecho, dicho, _, _ = abrir(config())
        c("si no se pueden escribir claves del navegador, se abre igual y se dice en una línea",
          (hecho, len(dicho)), (True, 1))
        c.contains("  cuántas", dicho[0], "1 de sus 4 claves")
        eq.reg.no_escribe.clear()

        def no_lanza(orden, entorno):
            raise OSError("no existe")
        keepassxc.lanzar = no_lanza
        c.contains("si no se puede lanzar, se dice", abrir(config())[1][0], "no existe")
        keepassxc.lanzar = eq.lanzar

        # la línea de la ventana
        linea = llavero_editor.linea
        c("sin llavero, no hay línea", linea(config(base=None)), None)
        eq.paquete = None
        c("fuera de Windows, una línea sin botón", linea(config()),
          llavero_editor.Linea(keepassxc.SOLO_WINDOWS, False, False))
        eq.paquete = "windows-x64"
        exe.rename(exe.with_name("apartado"))
        c("sin KeePassXC, en ámbar y sin botón: lo pone «Actualizar…»",
          linea(config())[1:], (True, False))
        exe.with_name("apartado").rename(exe)
        results.apuntar(model.LLAVERO, 1, None)
        c.contains("la última pasada falló: en ámbar, con botón", linea(config()).texto,
                   "la última pasada falló")
        c("  y ámbar", linea(config())[1:], (True, True))
        results.apuntar(model.LLAVERO, 0, None)
        eq.nuestro = True
        c("abierto", linea(config()).texto, "personal.kdbx, abierto en KeePassXC.")
        eq.nuestro = False
        real_pendiente = llavero.pendiente
        llavero.pendiente = lambda pareja: True
        c("con algo sin subir", linea(config()).texto,
          "personal.kdbx, con cambios que aún no han subido.")
        llavero.pendiente = lambda pareja: False
        c.contains("al día, con la hora de la última pasada", linea(config()).texto,
                   "personal.kdbx, al día · última pasada ")
        llavero.pendiente = real_pendiente
        (llavero.carpeta() / "personal.kdbx").unlink()
        c.contains("sin la base, se dice que «Abrir llavero» la trae", linea(config()).texto,
                   "la trae del remoto")

        # sin entorno gráfico: por la consola y sin preguntar
        real_oculto = uitk.root_oculto
        uitk.root_oculto = lambda: (_ for _ in ()).throw(RuntimeError("sin display"))
        try:
            salida = io.StringIO()
            with contextlib.redirect_stdout(salida):
                rc = ui.abrir_llavero(config(fichero_llave=True))
            c("sin entorno gráfico, por la consola", (rc, salida.getvalue().splitlines()[-1]),
              (0, llavero_editor.ABRIENDO))
        finally:
            uitk.root_oculto = real_oculto
finally:
    (keepassxc.paquete_del_equipo, llavero.keepassxc_abierto, keepassxc.otro_abierto,
     llavero.atiende_el_servicio, llavero.pasada, keepassxc.lanzar,
     keepassxc.ESPERA_ARRANQUE, llavero.lanzar_vigilante) = reales
    registro.leer, registro.escribir, registro.borrar, registro.vacia = reales_registro
    model.APP_DIR = real_app

sys.exit(c.report())
