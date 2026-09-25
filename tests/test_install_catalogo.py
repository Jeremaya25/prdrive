#!/usr/bin/env python3
"""
El instalador y la ruta del catálogo: el fichero, no su carpeta (#48).

Con `/prdrive-catalog` en vez de `/prdrive-catalog/pairs.toml`, el paso de
comprobaciones decía «El catálogo del remoto no es TOML válido: Cannot declare
('defaults',) twice», porque `rclone cat` de una carpeta no falla: junta todo lo
que hay dentro. Se comprueba:

  * Que el formulario de Conexión rechaza la carpeta sin tocar la red, y que la
    caja del catálogo lo dice según se teclea y no deja seguir con ella.
  * Que `pull_catalog()`, si aun así le llega una carpeta —un perfil incrustado,
    `--check`—, lo dice como carpeta y sugiere el pairs.toml de dentro.
  * Que en el camino bueno no se pregunta nada más al remoto, y que un fichero
    que de verdad no es TOML sigue diciendo eso: un diagnóstico falso es peor
    que ninguno.

Ningún rclone se ejecuta: el runner de `remote.Rclone` es de mentira, y las
respuestas de `lsjson --stat` son las de rclone v1.75.1 contra una carpeta y un
fichero de verdad.
"""

import subprocess
import sys
from dataclasses import replace

from _harness import Checks, tmpdir

from install import InstallError, profile, remote

c = Checks("instalador: la ruta del catálogo (#48)")

CATALOGO = """\
[defaults]
remote = "nas"

[[pair]]
name = "docs"
local = "sync-data/docs"
remote_path = "/datos/docs"
mode = "bisync"
"""
STAT_CARPETA = ('{\n\t"Path": "",\n\t"Name": "",\n\t"Size": -1,\n'
                '\t"MimeType": "inode/directory",\n'
                '\t"ModTime": "2026-09-25T11:38:30.975365128Z",\n\t"IsDir": true\n}\n')
STAT_FICHERO = ('{\n\t"Path": "pairs.toml",\n\t"Name": "pairs.toml",\n\t"Size": 94,\n'
                '\t"MimeType": "application/toml",\n'
                '\t"ModTime": "2026-09-25T11:38:30.643855347Z",\n\t"IsDir": false\n}\n')
NO_EXISTE = (3, "", "NOTICE: Failed to lsjson: directory not found")

llamadas: list[list[str]] = []


def rclone(*respuestas) -> remote.Rclone:
    """Un Rclone cuyo runner contesta por orden y apunta cada orden (sin el
    `--config` de delante, que no es lo que se comprueba)."""
    cola = list(respuestas)
    llamadas.clear()

    def runner(cmd, **_kw):
        llamadas.append(list(cmd[3:]))
        rc, salida, error = cola.pop(0) if cola else (0, "", "")
        if rc == "timeout":
            raise subprocess.TimeoutExpired(cmd, 1)
        return subprocess.CompletedProcess(cmd, rc, salida, error)
    return remote.Rclone("RCLONE", "CONF", runner=runner, remote_name="nas")


def trae(rc: remote.Rclone, ruta: str):
    """pull_catalog() y lo que dijo si lanzó."""
    try:
        return remote.pull_catalog(rc, ruta), ""
    except InstallError as e:
        return None, str(e)


# --- el formulario, sin red ----------------------------------------------------
for como, hacer in (
        ("from_form", lambda ruta: profile.from_form(
            "nas", {"type": "sftp"}, catalog_path=ruta)),
        ("from_rclone_conf", None)):
    if hacer is None:
        conf = tmpdir() / "rclone.conf"
        conf.write_text("[nas]\ntype = webdav\nurl = https://dav.example/\n",
                        encoding="utf-8")
        hacer = (lambda ruta, conf=conf: profile.from_rclone_conf(
            conf, "nas", catalog_path=ruta))
    try:
        hacer("/prdrive-catalog")
        c(f"{como}: una carpeta por ruta del catálogo se rechaza", "no lanzó",
          "InstallError")
    except InstallError as e:
        c.contains(f"{como}: una carpeta por ruta del catálogo se rechaza", str(e),
                   "no termina en .toml")
        c.contains(f"{como}: y se dice cuál sería", str(e),
                   "«/prdrive-catalog/pairs.toml»")
    c(f"{como}: vacía es la de fábrica", hacer("").catalog_path,
      profile.DEFAULT_CATALOG_PATH)
    c(f"{como}: y se limpia", hacer("  /otro/pairs.toml ").catalog_path,
      "/otro/pairs.toml")

bueno = profile.from_form("nas", {"type": "sftp", "host": "nas.example"})
c("un perfil con la ruta de fábrica no tiene problema", bueno.problema_catalogo, None)
# La caja del catálogo la aplica a cada tecla, y a medio escribir ninguna ruta
# termina en .toml: `with_catalog_path` no puede lanzar. Lo que impide seguir es
# la condición del paso, que mira `problema_catalogo`.
a_medias = profile.with_catalog_path(bueno, "/prdrive-catalog")
c("with_catalog_path no lanza", a_medias.catalog_path, "/prdrive-catalog")
c.contains("pero el perfil sabe lo que le pasa", a_medias.problema_catalogo or "",
           "no termina en .toml")
c("y sigue siendo una conexión configurada", a_medias.configured, True)

# --- el lector del instalador ---------------------------------------------------
cat, _ = trae(rclone((0, CATALOGO, "")), "/prdrive-catalog/pairs.toml")
c("un fichero se lee como siempre", cat.names if cat else None, ["docs"])
c("sin ninguna pregunta más", llamadas, [["cat", "nas:/prdrive-catalog/pairs.toml"]])

# Las dos copias seguidas: pairs.toml y el .bak que deja catalog.push().
cat, motivo = trae(rclone((0, CATALOGO + CATALOGO, ""), (0, STAT_CARPETA, ""),
                          (0, STAT_FICHERO, "")), "/prdrive-catalog")
c("una carpeta no se lee como catálogo", cat, None)
c.contains("se dice que es una carpeta", motivo, "es una carpeta")
c.contains("y cuál es la ruta buena", motivo, "«/prdrive-catalog/pairs.toml»")
c("sin el error de TOML engañoso", "Cannot declare" in motivo, False)
c("se pregunta qué es la ruta, y por su pairs.toml", llamadas,
  [["cat", "nas:/prdrive-catalog"],
   ["lsjson", "--stat", "nas:/prdrive-catalog"],
   ["lsjson", "--stat", "nas:/prdrive-catalog/pairs.toml"]])

# Una carpeta vacía: `cat` sale con 0 y no trae nada; el config sin parejas es
# lo que falla, y también ahí se pregunta.
_, motivo = trae(rclone((0, "", ""), (0, STAT_CARPETA, ""), NO_EXISTE),
                 "/prdrive-catalog")
c.contains("una carpeta vacía también se dice", motivo, "es una carpeta")
c.contains("con un ejemplo, sin afirmar que esté", motivo, "Por ejemplo")

# Un perfil incrustado con la carpeta, y dentro solo un pairs.toml: `cat` lo lee
# sin error. Es la ruta sin .toml lo que hace preguntar.
_, motivo = trae(rclone((0, CATALOGO, ""), (0, STAT_CARPETA, ""),
                        (0, STAT_FICHERO, "")), "/prdrive-catalog")
c.contains("una carpeta que se lee bien por casualidad también", motivo,
           "es una carpeta")

# Lo que no es una carpeta sigue diciendo lo de antes.
_, motivo = trae(rclone((0, "esto ] no [ es toml", ""), (0, STAT_FICHERO, "")),
                 "/prdrive-catalog/pairs.toml")
c.contains("un fichero que no es TOML sigue diciendo eso", motivo,
           "no es TOML válido")
_, motivo = trae(rclone((0, CATALOGO + CATALOGO, ""), ("timeout", "", "")),
                 "/prdrive-catalog")
c.contains("si la pregunta no llega a tiempo, lo de antes", motivo,
           "no es TOML válido")
_, motivo = trae(rclone((1, "", "no route to host")), "/prdrive-catalog")
c.contains("si falla el cat se cuenta el cat", motivo, "no route to host")
c("y no se pregunta nada más", len(llamadas), 1)

# --- el paso Conexión del asistente -------------------------------------------
try:
    import tkinter as tk
    from tkinter import messagebox, ttk
    raiz = tk.Tk()
    raiz.withdraw()
except Exception as e:                                   # sin entorno gráfico
    print(f"  (saltado el asistente) no hay entorno gráfico: {e}")
    sys.exit(c.report())

from ui import tk_install  # noqa: E402

messagebox.showerror = lambda *a, **k: None


def widgets(w, tipo):
    pila, salida = [w], []
    while pila:
        actual = pila.pop()
        pila += list(actual.winfo_children())
        if isinstance(actual, tipo):
            salida.append(actual)
    return salida


def estado(wiz) -> ttk.Label | None:
    for lbl in widgets(wiz.root, ttk.Label):
        if str(lbl.cget("text")).startswith(("✔", "✘")):
            return lbl
    return None


PASO = {t: i for i, (t, _, _) in enumerate(tk_install.PASOS_INSTALACION)}
root = tk.Toplevel(raiz)
root.withdraw()
wiz = tk_install.build(root)
# Un perfil incrustado con la carpeta: en ese caso «Usar esta conexión» no se
# pulsa nunca, así que es el paso el que tiene que verlo.
wiz.perfil = replace(bueno, catalog_path="/prdrive-catalog")
wiz.indice = PASO["Conexión"]
wiz.repintar()
c("con una carpeta por ruta no se sale de Conexión",
  str(wiz.boton_siguiente.cget("state")), "disabled")
lbl = estado(wiz)
c.contains("y se dice por qué", str(lbl.cget("text")) if lbl else "",
           "«/prdrive-catalog/pairs.toml»")

caja = next((e for e in widgets(wiz.root, ttk.Entry)
             if e.get() == "/prdrive-catalog"), None)
c("la caja del catálogo enseña la ruta del perfil", caja is not None, True)
if caja is not None:
    caja.insert("end", "/pairs.toml")
    c("al escribir el fichero, la ruta llega al perfil", wiz.perfil.catalog_path,
      "/prdrive-catalog/pairs.toml")
    c("y ya se puede seguir", str(wiz.boton_siguiente.cget("state")), "normal")
    lbl = estado(wiz)
    c("con la marca buena", str(lbl.cget("text"))[:1] if lbl else "", "✔")

    caja.delete(len("/prdrive-catalog"), "end")
    c("borrarlo vuelve a cerrar el paso", str(wiz.boton_siguiente.cget("state")),
      "disabled")

root.destroy()
raiz.destroy()
sys.exit(c.report())
