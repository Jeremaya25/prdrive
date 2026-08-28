#!/usr/bin/env python3
"""
El aviso de versión nueva (common/update.py).

`update.fetch` se sustituye entera: aquí no se habla con GitHub. Lo que se
comprueba es lo que puede hacer daño —que no se le deje tocar el dispositivo a
un zip que no es el que se pidió, ni a uno con rutas que se salen de su
carpeta— y lo que sostiene la ventana: que mirar no lance nunca, que el primer
pintado no vaya a la red, y que no se pregunte una vez por apertura.
"""

import io
import json
import sys
import zipfile
from pathlib import Path

from _harness import Checks, sandbox, tmpdir

from common import store, update

c = Checks("aviso de versión nueva (common/update.py)")

CRUDO = {"tag_name": "v9.9.9", "name": "La novena", "html_url": "https://x/9",
         "published_at": "2026-08-28T08:12:13Z", "body": "Arreglado esto."}

llamadas: list[str] = []


def responder(*respuestas):
    """Sustituye update.fetch por una cola, apuntando cada URL pedida."""
    cola = list(respuestas)
    llamadas.clear()

    def _fetch(url, timeout):
        llamadas.append(url)
        if not cola:
            raise OSError("no quedan respuestas preparadas")
        valor = cola.pop(0)
        if isinstance(valor, Exception):
            raise valor
        return valor
    update.fetch = _fetch


def api(crudo=None) -> bytes:
    return json.dumps(crudo or CRUDO).encode()


def zip_codigo(version="9.9.9", raiz="prdrive-9.9.9", quitar=(), extra=()) -> bytes:
    """Un zip con la pinta del que sirve codeload para un tag."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for nombre in update.OBLIGATORIOS:
            if nombre in quitar:
                continue
            z.writestr(f"{raiz}/{nombre}",
                       version if nombre == "VERSION" else "# codigo\n")
        for nombre in extra:
            z.writestr(nombre, "esto no debería aterrizar")
    return buf.getvalue()


# --- comparar versiones ------------------------------------------------------
# Por tuplas de enteros y no por cadenas: comparando texto, "0.0.9" va después
# de "0.0.10" y el aviso desaparecería justo al llegar a la décima release.
c("0.0.10 es posterior a 0.0.9", update.is_newer("0.0.10", "0.0.9"), True)
c("0.0.9 no es posterior a 0.0.10", update.is_newer("0.0.9", "0.0.10"), False)
c("la misma versión no es nueva", update.is_newer("0.0.2", "0.0.2"), False)
c("el prefijo v no cuenta", update.is_newer("v0.1.0", "0.0.9"), True)
c("sin versión instalada, todo es nuevo", update.is_newer("0.0.1", ""), True)
c("sin release no hay nada nuevo", update.is_newer("", "0.0.1"), False)
c("un tag raro no revienta", update.parse_version("1.2.3-rc1"), (1, 2, 3))

# Un dispositivo instalado antes de que existiera VERSION no tiene el fichero, y
# eso no es un fallo: es uno que tiene que actualizarse.
c("sin fichero VERSION la versión es desconocida",
  update.installed_version(tmpdir("prdrive-sinver-")), "")


# --- mirar: nunca lanza, y no va a la red más de la cuenta -------------------
with sandbox():
    responder(api())
    rel, motivo = update.check()
    c("se lee la release", (rel.tag, rel.version, rel.name),
      ("v9.9.9", "9.9.9", "La novena"))
    c("y sin queja", motivo, None)
    c("se ha preguntado una vez", len(llamadas), 1)

    update.check()
    c("la caché de 24 h evita la segunda consulta", len(llamadas), 1)

    update.check(force=True)
    c("force sí vuelve a preguntar", len(llamadas), 2)

with sandbox():
    responder(OSError("no route to host"))
    rel, motivo = update.check()
    c("sin red y sin caché no hay release", rel, None)
    c.contains("y se explica", motivo or "", "no route to host")

with sandbox():
    # Primero se llena la caché, y después se le quita la red: lo que se supo
    # ayer sigue valiendo hoy, que es lo que sostiene el aviso sin conexión.
    responder(api(), OSError("la wifi del hotel"))
    update.check()
    rel, motivo = update.check(force=True)
    c("sin red se enseña lo último que se supo", rel.tag, "v9.9.9")
    c.contains("diciendo que es viejo", motivo or "", "lo último que se supo")

with sandbox():
    responder(api({"name": "una release sin tag_name"}))
    rel, motivo = update.check()
    c("una respuesta sin tag_name no lanza", rel, None)
    c.contains("y se explica", motivo or "", "tag_name")


# --- el primer pintado de la ventana: caché y solo caché ---------------------
with sandbox():
    responder(api())
    update.check()
    llamadas.clear()
    nueva = update.pending(root=tmpdir("prdrive-viejo-"))     # sin VERSION
    c("pending ve la release guardada", nueva.tag if nueva else None, "v9.9.9")
    c("y NO ha tocado la red", len(llamadas), 0)

    puesto = tmpdir("prdrive-aldia-")
    (puesto / "VERSION").write_text("9.9.9", encoding="utf-8")
    c("al día no hay nada pendiente", update.pending(root=puesto), None)

with sandbox():
    responder()
    c("sin caché tampoco se pregunta", update.pending(), None)
    c("de verdad que no", len(llamadas), 0)

with sandbox():
    # Un estado ilegible es «aquí no hay nada», no una excepción en el arranque.
    update.state_file().parent.mkdir(parents=True, exist_ok=True)
    update.state_file().write_text("{ esto no es json", encoding="utf-8")
    c("un update.json corrupto no impide abrir", update.pending(), None)


# --- traerse el código: lo que NO se acepta ----------------------------------
with sandbox():
    responder(zip_codigo())
    destino = tmpdir("prdrive-ok-")
    update.download("v9.9.9", destino)
    c("se quita la carpeta raíz que mete GitHub",
      (destino / "sync.py").is_file(), True)
    c("y el árbol queda entero", (destino / "common" / "model.py").is_file(), True)
    c("con su VERSION", (destino / "VERSION").read_text(encoding="utf-8"), "9.9.9")


def rechaza(label: str, datos, tag="v9.9.9") -> None:
    """Descargar tiene que negarse, y sin haber escrito en el destino."""
    responder(datos)
    destino = tmpdir("prdrive-malo-")
    try:
        update.download(tag, destino)
        c(label, "no se ha quejado", "UpdateError")
    except update.UpdateError:
        c(label, True, True)


with sandbox():
    # El caso peligroso de verdad: un zip que dice ser otra versión. Si se
    # aceptara, el dispositivo quedaría con un VERSION que no describe su código
    # y no volvería a ofrecerse la actualización de verdad.
    rechaza("se rechaza un zip de otra versión", zip_codigo(version="1.2.3"))
    rechaza("se rechaza un árbol incompleto", zip_codigo(quitar=("common/model.py",)))
    rechaza("se rechaza lo que no es un zip", b"esto no es un zip")
    # `extractall()` es el clásico: basta un miembro con .. para escribir fuera.
    rechaza("se rechaza un miembro que se sale",
            zip_codigo(extra=("prdrive-9.9.9/../fuera.txt",)))
    rechaza("se rechaza un zip con dos raíces", zip_codigo(extra=("otra/cosa.txt",)))

with sandbox():
    responder(OSError("se cayó la red a media descarga"))
    destino = tmpdir("prdrive-corte-")
    try:
        update.download("v9.9.9", destino)
        c("una descarga cortada se explica", "no se ha quejado", "UpdateError")
    except update.UpdateError as e:
        c.contains("una descarga cortada se explica", str(e), "se cayó la red")


# --- la orden que instala ----------------------------------------------------
orden = update.apply_command(Path("/tmp/staged"), Path("/media/pen"))
c("se ejecuta el prdrive-install.py DESCARGADO, no el del dispositivo",
  Path(orden[2]).name, "prdrive-install.py")
c.contains("y desde la carpeta descargada", orden[2], "staged")
c("con --update y la raíz del volumen", orden[3:], ["--update", str(Path("/media/pen"))])
c("sin buffer, para que la ventana de salida enseñe línea a línea",
  "-u" in orden, True)

sys.exit(c.report())
