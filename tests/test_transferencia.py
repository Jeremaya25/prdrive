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

from _harness import Checks

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

sys.exit(c.report())
