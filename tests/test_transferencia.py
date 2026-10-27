#!/usr/bin/env python3
"""Lo que decide una transferencia del explorador «Servidor…», sin Tk, sin disco y sin red.

Lo que se comprueba es lo que, si falla, copia de más o de menos en el servidor de
alguien: que cada elemento elegido se convierte en su regla de filtro de rclone y en
ninguna otra (un nombre con `* ? [ ] { } \\`, con `!`, `+` o `-` al principio, con
espacios o acentos), que las dos mitades de una copia son las rutas que se esperan
(la raíz del servidor entera como `nas:/`) y que solo cuentan como choque los
archivos que ya estaban en el destino, no las carpetas que se fusionan.
"""

import sys

from _harness import Checks, mkcfg

from common import model
from ui import transferencia

c = Checks("transferencias: qué copia un lote")

E = transferencia.Elemento
c("archivo", transferencia.reglas_de([E("a.txt", False)]), ["/a.txt"])
c("carpeta", transferencia.reglas_de([E("fotos", True)]), ["/fotos/**"])
c("patrones escapados", transferencia.reglas_de([E("raro [1]*?{x}\\", True)]),
  ["/raro \\[1\\]\\*\\?\\{x\\}\\\\/**"])
c("un archivo con patrones también se escapa", transferencia.reglas_de([E("a*b?.txt", False)]),
  ["/a\\*b\\?.txt"])
c("espacios y acentos tal cual", transferencia.reglas_de([E("Música antigua", True)]),
  ["/Música antigua/**"])
c("un ! o un - al principio no son reglas", transferencia.reglas_de([E("!x", False), E("- y", False)]),
  ["/!x", "/- y"])
c("un + al principio tampoco", transferencia.reglas_de([E("+z", True)]), ["/+z/**"])
c("una mezcla conserva el orden",
  transferencia.reglas_de([E("b", True), E("a.txt", False)]), ["/b/**", "/a.txt"])
c("sin elementos no hay reglas", transferencia.reglas_de([]), [])

L = transferencia.Lote
c("los sentidos", (transferencia.BAJAR, transferencia.SUBIR), ("bajar", "subir"))
c("bajar desde la raíz", transferencia.fs_de(L("bajar", "nas", "/", "/home/u/D", ())),
  ("nas:/", "/home/u/D"))
c("bajar desde una carpeta", transferencia.fs_de(L("bajar", "nas", "/datos/x", "/home/u/D", ())),
  ("nas:/datos/x", "/home/u/D"))
c("subir a una carpeta", transferencia.fs_de(L("subir", "nas", "/datos/x", "/home/u", ())),
  ("/home/u", "nas:/datos/x"))
c("subir a la raíz", transferencia.fs_de(L("subir", "nas", "/", "/home/u", ())),
  ("/home/u", "nas:/"))
c("una ruta sin barra inicial sigue siendo absoluta",
  transferencia.fs_de(L("bajar", "nas", "datos", "/home/u", ())), ("nas:/datos", "/home/u"))

c("choques: solo archivos que coinciden",
  transferencia.choques({"a.txt", "c/d.txt", "c/e.txt"}, {"a.txt", "c/e.txt", "z.txt"}), 2)
c("nada en el destino", transferencia.choques({"a"}, set()), 0)
c("nada que copiar", transferencia.choques(set(), {"a"}), 0)

c("singular", transferencia.texto_choques(1, "/datos"),
  "1 elemento ya existe en /datos. ¿Sobrescribirlo u omitirlo?")
c("plural", transferencia.texto_choques(3, "/datos"),
  "3 elementos ya existen en /datos. ¿Sobrescribirlos u omitirlos?")

# --- Qué parejas alcanza una copia, y qué se avisa o se bloquea -------------------------
DEVICE = model.DEVICE_ROOT
cfg = mkcfg((), pairs=[
    {"name": "Notas", "local": "sync-data/notas", "remote_path": "/datos/notas", "mode": "bisync"},
    {"name": "Copia", "local": "sync-data/copia", "remote_path": "/copia", "mode": "up-mirror"},
    {"name": "Bajadas", "local": "sync-data/bajadas", "remote_path": "/bajadas", "mode": "down-mirror"},
    {"name": "Todo", "local": "sync-data/todo", "remote_path": "/", "mode": "bisync", "remote": "b2"},
])

AVISO_BISYNC_NOTAS = ("Lo que subas a «Notas» lo bajará al dispositivo su próxima pasada; "
                      "si sobrescribes algo que también ha cambiado allí, saldrá un conflicto.")
BLOQUEO_COPIA = ("«Copia» deja el servidor igual que el dispositivo: lo que subas aquí lo "
                 "borraría su próxima pasada. Súbelo a su carpeta del dispositivo.")
BLOQUEO_BAJADAS = ("«Bajadas» deja su carpeta igual que el servidor: lo que bajes aquí lo "
                   "borraría su próxima pasada. Bájalo fuera de ella.")

c("subir dentro de una bisync avisa",
  transferencia.aviso("subir", transferencia.afectadas_subida(cfg, "nas", "/datos/notas/2026", [E("a.txt", False)])),
  AVISO_BISYNC_NOTAS)
c("subir a una up-mirror bloquea",
  transferencia.bloqueo("subir", transferencia.afectadas_subida(cfg, "nas", "/copia", [E("a", False)])),
  BLOQUEO_COPIA)
c("subir por encima de una pareja la alcanza",
  [a.pareja for a in transferencia.afectadas_subida(cfg, "nas", "/datos", [E("notas", True)])], ["Notas"])
c("subir un archivo con el nombre de la carpeta de una pareja también la alcanza",
  [a.pareja for a in transferencia.afectadas_subida(cfg, "nas", "/datos", [E("notas", False)])], ["Notas"])
c("subir un archivo por encima no alcanza lo que cuelga de él",
  transferencia.afectadas_subida(cfg, "nas", "/", [E("datos", False)]), ())
c("otro remote no cuenta", transferencia.afectadas_subida(cfg, "nas", "/", [E("x", False)]), ())
c("la raíz de b2 cuenta todo",
  [a.pareja for a in transferencia.afectadas_subida(cfg, "b2", "/z", [E("x", False)])], ["Todo"])
c("lleva el modo", transferencia.afectadas_subida(cfg, "nas", "/copia", [E("a", False)]),
  (transferencia.Afectada("Copia", "up-mirror"),))
c("bajar dentro de una down-mirror bloquea",
  transferencia.bloqueo("bajar", transferencia.afectadas_bajada(cfg, str(DEVICE / "sync-data/bajadas/sub"), [E("a", False)])),
  BLOQUEO_BAJADAS)
c("bajar por encima de la carpeta de una pareja la alcanza",
  [a.pareja for a in transferencia.afectadas_bajada(cfg, str(DEVICE / "sync-data"), [E("notas", True)])], ["Notas"])
c("bajar un archivo con el nombre de la carpeta de una pareja también la alcanza",
  transferencia.afectadas_bajada(cfg, str(DEVICE / "sync-data"), [E("notas", False)])[0].pareja, "Notas")
c("bajar un archivo no alcanza lo que cuelga de su nombre",
  transferencia.afectadas_bajada(cfg, str(DEVICE), [E("sync-data", False)]), ())
c("bajar fuera de las parejas no dice nada",
  (transferencia.bloqueo("bajar", ()), transferencia.aviso("bajar", ())), (None, None))
c("bajar a otra carpeta no alcanza a nadie",
  transferencia.afectadas_bajada(cfg, str(DEVICE / "otra"), [E("a", False)]), ())
c("prefijo de texto no es estar dentro",
  transferencia.afectadas_subida(cfg, "nas", "/datos/notas2", [E("a", False)]), ())
c("prefijo de texto local no es estar dentro",
  transferencia.afectadas_bajada(cfg, str(DEVICE / "sync-data/notas2"), [E("a", False)]), ())
c("varias: bloqueo si alguna es up-mirror",
  transferencia.bloqueo("subir", transferencia.afectadas_subida(cfg, "nas", "/", [E("copia", True), E("datos", True)])),
  BLOQUEO_COPIA)
c("sin duplicados y en el orden de la configuración",
  [a.pareja for a in transferencia.afectadas_subida(cfg, "nas", "/datos/notas", [E("a", True), E("b", True)])],
  ["Notas"])
c("un bloqueo de bajada no sale al subir",
  transferencia.bloqueo("subir", transferencia.afectadas_subida(cfg, "nas", "/bajadas", [E("a", False)])), None)
c("subir a una down-mirror avisa",
  transferencia.aviso("subir", transferencia.afectadas_subida(cfg, "nas", "/bajadas", [E("a", False)])),
  "Lo que subas a «Bajadas» lo bajará al dispositivo su próxima pasada.")

# Parejas que comparten carpeta o que están anidadas: se alcanzan todas las de la carpeta
# más honda, y un bloqueo no se escapa porque otra pareja comparta su ruta.
cfg2 = mkcfg((), pairs=[
    {"name": "Fotos", "local": "sync-data/a", "remote_path": "/fotos", "mode": "bisync"},
    {"name": "Espejo", "local": "sync-data/b", "remote_path": "/fotos", "mode": "up-mirror"},
    {"name": "Bajo", "local": "sync-data/c", "remote_path": "/otra", "mode": "down"},
    {"name": "Bajo2", "local": "sync-data/c", "remote_path": "/otra2", "mode": "down-mirror"},
    {"name": "Datos", "local": "sync-data/datos", "remote_path": "/datos", "mode": "up-mirror"},
    {"name": "Notas", "local": "sync-data/datos/notas", "remote_path": "/datos/notas", "mode": "bisync"},
])
c("dos parejas en la misma ruta del servidor: salen las dos",
  [a.pareja for a in transferencia.afectadas_subida(cfg2, "nas", "/fotos/x", [E("a", False)])],
  ["Fotos", "Espejo"])
c("dos parejas en la misma ruta del servidor: la up-mirror bloquea",
  transferencia.bloqueo("subir", transferencia.afectadas_subida(cfg2, "nas", "/fotos", [E("a", False)])),
  "«Espejo» deja el servidor igual que el dispositivo: lo que subas aquí lo borraría "
  "su próxima pasada. Súbelo a su carpeta del dispositivo.")
c("dos parejas en la misma carpeta local: salen las dos",
  [a.pareja for a in transferencia.afectadas_bajada(cfg2, str(DEVICE / "sync-data/c/x"), [E("a", False)])],
  ["Bajo", "Bajo2"])
c("dos parejas en la misma carpeta local: la down-mirror bloquea",
  transferencia.bloqueo("bajar", transferencia.afectadas_bajada(cfg2, str(DEVICE / "sync-data/c"), [E("a", False)])),
  "«Bajo2» deja su carpeta igual que el servidor: lo que bajes aquí lo borraría "
  "su próxima pasada. Bájalo fuera de ella.")
c("subir a una pareja anidada solo alcanza a la de dentro",
  [a.pareja for a in transferencia.afectadas_subida(cfg2, "nas", "/datos/notas/x", [E("a", False)])],
  ["Notas"])
c("bajar a una pareja anidada solo alcanza a la de dentro",
  [a.pareja for a in transferencia.afectadas_bajada(cfg2, str(DEVICE / "sync-data/datos/notas/x"), [E("a", False)])],
  ["Notas"])
c("subir a la externa de dos anidadas alcanza a la externa",
  [a.pareja for a in transferencia.afectadas_subida(cfg2, "nas", "/datos/otra", [E("a", False)])],
  ["Datos"])
c("lo que alcanzan el destino y dos elementos sale una vez cada pareja",
  [a.pareja for a in transferencia.afectadas_subida(cfg2, "nas", "/datos", [E("notas", True), E("notas", False)])],
  ["Datos", "Notas"])
c("dos elementos que llegan a las parejas de una misma carpeta las listan una vez",
  [a.pareja for a in transferencia.afectadas_subida(cfg2, "nas", "/", [E("fotos", True), E("fotos", False)])],
  ["Fotos", "Espejo"])

# Los textos de cada modo, en los dos sentidos.
def _aviso(sentido, modo):
    return transferencia.aviso(sentido, (transferencia.Afectada("P", modo),))

c("subir a up avisa", _aviso("subir", "up"),
  "«P» solo sube del dispositivo: lo que subas aquí se quedará en el servidor.")
c("subir a down avisa", _aviso("subir", "down"),
  "Lo que subas a «P» lo bajará al dispositivo su próxima pasada.")
c("bajar a bisync avisa", _aviso("bajar", "bisync"),
  "Lo que bajes a la carpeta de «P» lo subirá al servidor su próxima pasada.")
c("bajar a up avisa", _aviso("bajar", "up"),
  "Lo que bajes a la carpeta de «P» lo subirá al servidor su próxima pasada.")
c("bajar a up-mirror avisa", _aviso("bajar", "up-mirror"),
  "Lo que bajes a la carpeta de «P» lo subirá al servidor su próxima pasada.")
c("bajar a down avisa", _aviso("bajar", "down"),
  "«P» solo baja del servidor: lo que bajes aquí se quedará en el dispositivo.")
c("con bloqueo no hay aviso", _aviso("subir", "up-mirror"), None)
c("varios avisos van separados por una línea en blanco",
  transferencia.aviso("subir", (transferencia.Afectada("A", "down"), transferencia.Afectada("B", "down"))),
  "Lo que subas a «A» lo bajará al dispositivo su próxima pasada.\n\n"
  "Lo que subas a «B» lo bajará al dispositivo su próxima pasada.")

sys.exit(c.report())
