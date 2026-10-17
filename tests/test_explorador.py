#!/usr/bin/env python3
"""El nombre y el icono de la letra de un volumen VeraCrypt en el Explorador (`common/explorador.py`).

Con un registro de mentira y letras de mentira (cada una, un directorio
temporal), nada toca el registro ni una unidad de verdad. Se comprueba:
- Solo se escribe para la letra de un volumen VeraCrypt donde vive un
  dispositivo de prdrive, y lo que se escribe es lo que dice su `autorun.inf`:
  la ruta ABSOLUTA del icono y el nombre, cada subclave con la marca y el id.
- Lo que el fichero ya no dice se quita; una subclave de otro no se toca nunca.
- Quitar se lleva solo las subclaves marcadas (las de ese id, si se dice) y las
  de encima si quedan vacías; limpiar, las huérfanas de letras cerradas o que
  ya tiene otra unidad, y avisa al Explorador de cada letra que limpia.
- Nada de esto lanza, ni con el registro roto.
- Los que lo llaman: «Nombre e icono» al guardar, la ventana al expulsar, y la
  ventana y el servicio al arrancar.
"""

import os
from pathlib import Path

from _harness import Checks, sandbox, tmpdir

from common import autorun, explorador, model, registro
from ui import cifrado

c = Checks("nombre e icono de la letra en el Explorador")

APP = ".prdrive"


class Registro:
    """Un `HKEY_CURRENT_USER` de mentira: clave (sin mayúsculas) → {valor: dato}."""

    def __init__(self) -> None:
        self.claves: dict[str, dict[str, str]] = {}
        self.roto = False

    @staticmethod
    def _k(clave: str) -> str:
        return clave.lower()

    def leer(self, clave, nombre=""):
        return self.claves.get(self._k(clave), {}).get(nombre.lower())

    def escribir(self, clave, valor, nombre=""):
        if self.roto:
            raise OSError("acceso denegado")
        partes = clave.split("\\")
        for i in range(1, len(partes)):
            self.claves.setdefault(self._k("\\".join(partes[:i])), {})
        self.claves.setdefault(self._k(clave), {})[nombre.lower()] = valor

    def _hijas(self, clave):
        prefijo = self._k(clave) + "\\"
        return [k for k in self.claves if k.startswith(prefijo)]

    def borrar(self, clave):
        if self.roto:
            raise OSError("acceso denegado")
        if self._k(clave) not in self.claves:
            return False
        if self._hijas(clave):
            raise OSError("tiene subclaves")
        del self.claves[self._k(clave)]
        return True

    def vacia(self, clave):
        if self._k(clave) not in self.claves:
            return None
        return not self._hijas(clave) and not self.claves[self._k(clave)]

    def subclaves(self, clave):
        prefijo = self._k(clave) + "\\"
        return [k[len(prefijo):] for k in self.claves
                if k.startswith(prefijo) and "\\" not in k[len(prefijo):]]


REAL_REGISTRO = (registro.leer, registro.escribir, registro.borrar, registro.vacia,
                 registro.subclaves)
REAL_EXPLORADOR = (explorador.letra_de, explorador.raiz_de, explorador.de_veracrypt,
                   explorador.avisar_shell)

# --- lo de verdad, sin escribir nada
c("letra_de: la raíz de una letra", [explorador.letra_de(r) for r in
                                     ("H:\\", "h:/", "H:", "C:\\Users", "/media/pen")],
  ["H", "H", None, None, None])
if os.name == "nt":
    sistema = os.environ.get("SystemDrive", "C:")[:1]
    c("de_veracrypt: la unidad del sistema no lo es", explorador.de_veracrypt(sistema), False)
else:
    c("fuera de Windows no hay volúmenes de VeraCrypt", explorador.de_veracrypt("H"), False)
    c("  ni subclaves en el registro", registro.subclaves(explorador.DRIVES), [])

# --- el mundo de mentira
reg = Registro()
registro.leer, registro.escribir, registro.borrar = reg.leer, reg.escribir, reg.borrar
registro.vacia, registro.subclaves = reg.vacia, reg.subclaves
LETRAS: dict[str, Path] = {}
VERACRYPT: set[str] = set()
AVISADAS: list = []
explorador.letra_de = lambda raiz: next((l for l, r in LETRAS.items() if Path(raiz) == r), None)
explorador.raiz_de = lambda letra: LETRAS.get(letra, Path("/no/existe"))
explorador.de_veracrypt = lambda letra: letra in VERACRYPT
explorador.avisar_shell = AVISADAS.append

ID_H, ID_J = "a" * 32, "b" * 32
ICONO = f"{APP}\\icono-verde.ico"


def unidad(letra: str, dispositivo: str, etiqueta: str = "", icono: str = "",
           con_icono: bool = True) -> Path:
    """Una raíz con un dispositivo de prdrive dentro, en esa letra (de VeraCrypt)."""
    raiz = tmpdir(f"prdrive-letra-{letra}-")
    (raiz / APP).mkdir()
    (raiz / APP / "PRDRIVE").write_text(f"id={dispositivo}\n", encoding="utf-8")
    if icono and con_icono:
        raiz.joinpath(*icono.split("\\")).write_bytes(b"ico")
    autorun.escribir(raiz, autorun.con("", etiqueta, icono))
    LETRAS[letra] = raiz
    VERACRYPT.add(letra)
    return raiz


def clave(letra: str, sub: str = "") -> str:
    return f"{explorador.DRIVES}\\{letra}" + (f"\\{sub}" if sub else "")


def valores(letra: str, sub: str) -> tuple:
    return (registro.leer(clave(letra, sub)), registro.leer(clave(letra, sub), explorador.MARCA))


try:
    H = unidad("H", ID_H, "Pendrive de Pere", ICONO)
    VERACRYPT.discard("H")
    c("una letra que no es de VeraCrypt no se toca", (explorador.poner(H, APP), reg.claves),
      (False, {}))
    VERACRYPT.add("H")

    c("en la de un volumen VeraCrypt, sí", explorador.poner(H, APP), True)
    c("  el icono, con su ruta absoluta en el volumen, y la marca con el id",
      valores("H", explorador.ICONO), (str(H / APP / "icono-verde.ico"), ID_H))
    c("  el nombre, igual", valores("H", explorador.NOMBRE), ("Pendrive de Pere", ID_H))
    c("  y se le avisa al Explorador", AVISADAS, [H])
    AVISADAS.clear()
    c("otra vez lo mismo: nada cambia y no se avisa", (explorador.poner(H, APP), AVISADAS),
      (True, []))
    c("  ni las rutas de verdad salen de la carpeta de la letra",
      explorador.icono_absoluto(H, ICONO).startswith(str(H)), True)

    # lo que el fichero deja de decir se quita
    autorun.escribir(H, autorun.con(autorun.leer(H).texto, "Pendrive de Pere", ""))
    explorador.poner(H, APP)
    c("sin icono en el fichero, sin icono en la letra (el nombre sigue)",
      (valores("H", explorador.ICONO), valores("H", explorador.NOMBRE)[0]),
      ((None, None), "Pendrive de Pere"))
    autorun.escribir(H, autorun.con(autorun.leer(H).texto, "", ICONO))
    explorador.poner(H, APP)
    c("y al revés", (valores("H", explorador.ICONO)[0], valores("H", explorador.NOMBRE)),
      (str(H / APP / "icono-verde.ico"), (None, None)))

    # icon= que no se le pasa
    c("icono_absoluto: solo un fichero que existe dentro, relativo y sin coma",
      [explorador.icono_absoluto(H, i) for i in
       (ICONO, f"{APP}\\no-esta.ico", "C:\\fuera.ico", "\\raiz.ico", "..\\fuera.ico",
        f"{APP}\\icono-verde.ico,0", "")],
      [str(H / APP / "icono-verde.ico"), "", "", "", "", "", ""])

    # sin dispositivo de prdrive, nada
    (H / APP / "PRDRIVE").unlink()
    c("sin fichero de control no se marca nada", explorador.poner(H, APP), False)
    (H / APP / "PRDRIVE").write_text(f"id={ID_H}\n", encoding="utf-8")

    # la de otro no se toca
    J = unidad("J", ID_J, "Otro", ICONO)
    reg.escribir(clave("J", explorador.ICONO), "C:\\mio.ico")
    explorador.poner(J, APP)
    c("una subclave de otro (sin marca) no se pisa", valores("J", explorador.ICONO),
      ("C:\\mio.ico", None))
    c("  la que falta sí se pone", valores("J", explorador.NOMBRE), ("Otro", ID_J))

    # quitar
    c("quitar con el id de otra unidad no toca nada", explorador.quitar(J, ID_H), False)
    c("quitar se lleva solo lo marcado de esa unidad", explorador.quitar(J, ID_J), True)
    c("  la de otro sigue, y por ella también la clave de la letra",
      (valores("J", explorador.ICONO), reg.vacia(clave("J"))), (("C:\\mio.ico", None), False))
    reg.borrar(clave("J", explorador.ICONO))
    c("quitar donde no hay nada marcado no quita nada", explorador.quitar(J), False)
    c("  pero recoge la clave de la letra, ya vacía", reg.vacia(clave("J")), None)
    c("quitar sin decir el id se lleva lo marcado", explorador.quitar(H), True)
    c("  y lo que queda vacío encima, hasta Explorer.exe",
      [k for k in reg.claves if k.startswith(explorador.APLICACION.lower())], [])
    c("  pero no Applications, que es de todos",
      reg.vacia("Software\\Classes\\Applications"), True)
    reg.escribir(explorador.APLICACION + "\\shell\\open", "otra cosa")
    explorador.poner(H, APP)
    explorador.quitar(H)
    c("Explorer.exe con otras cosas se queda", reg.vacia(explorador.APLICACION), False)
    c("quitar una raíz que no es una letra: nada", explorador.quitar(Path("/media/pen")),
      False)

    # limpiar
    explorador.poner(H, APP)
    explorador.poner(J, APP)
    K = unidad("K", ID_H, "Viejo", ICONO)
    explorador.poner(K, APP)
    VERACRYPT.discard("K")                      # cerrada desde VeraCrypt
    reg.escribir(clave("L"), "")                # una letra vacía que dejó alguien
    reg.claves[reg._k(clave("L"))] = {}
    AVISADAS.clear()
    c("limpiar: la de una letra cerrada se va, las abiertas se quedan",
      (explorador.limpiar(APP), sorted(registro.subclaves(explorador.DRIVES))),
      (["K"], ["h", "j"]))
    c("  y se le avisa al Explorador de la letra que se limpia, solo de ella", AVISADAS, [K])
    (J / APP / "PRDRIVE").write_text(f"id={'c' * 32}\n", encoding="utf-8")
    c("  y la de una letra que ya tiene otra unidad", explorador.limpiar(APP), ["J"])
    c("  también se avisa de esa", AVISADAS, [K, J])
    c("  sin nada que limpiar, no se avisa de nada más", (explorador.limpiar(APP), AVISADAS),
      ([], [K, J]))
    c("  lo de H sigue", valores("H", explorador.ICONO)[1], ID_H)

    # nada lanza
    reg.roto = True
    autorun.escribir(H, autorun.con(autorun.leer(H).texto, "Nuevo nombre", ICONO))
    c("con el registro roto, poner dice que no y no lanza", explorador.poner(H, APP), False)
    c("  quitar tampoco", explorador.quitar(H), False)
    c("  ni limpiar", explorador.limpiar(APP), [])
    reg.roto = False

    # quien lo llama
    with sandbox():
        reales = (model.DEVICE_ROOT, model.APP_DIR)
        try:
            model.DEVICE_ROOT, model.APP_DIR = H, H / APP
            c("por defecto, la carpeta del programa es la de APP_DIR",
              (explorador.poner(H), valores("H", explorador.NOMBRE)[0]),
              (True, "Nuevo nombre"))
            cifrado.olvidar_letra()
            c("la ventana, al expulsar, quita lo de este dispositivo",
              registro.subclaves(explorador.DRIVES), [])
            K2 = unidad("K", ID_J, "Quieto", ICONO)
            explorador.poner(K2, APP)
            VERACRYPT.discard("K")
            VERACRYPT.discard("H")
            antes = {k: dict(v) for k, v in reg.claves.items()}
            cifrado.nombrar_letra()
            c("fuera de un volumen VeraCrypt, al arrancar no se toca el registro",
              reg.claves, antes)
            VERACRYPT.add("H")
            cifrado.nombrar_letra()
            c("en uno, la ventana y el servicio al arrancar limpian y ponen la suya",
              (sorted(registro.subclaves(explorador.DRIVES)),
               valores("H", explorador.NOMBRE)[0]), (["h"], "Nuevo nombre"))
        finally:
            model.DEVICE_ROOT, model.APP_DIR = reales
finally:
    (registro.leer, registro.escribir, registro.borrar, registro.vacia,
     registro.subclaves) = REAL_REGISTRO
    (explorador.letra_de, explorador.raiz_de, explorador.de_veracrypt,
     explorador.avisar_shell) = REAL_EXPLORADOR

raise SystemExit(c.report())
