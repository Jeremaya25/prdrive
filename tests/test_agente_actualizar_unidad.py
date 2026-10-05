#!/usr/bin/env python3
"""«Actualizar a la vX» de una raíz: el agente la pone a SU versión.

Lo que se comprueba:
- Una raíz de la lista con un programa anterior al del agente se ofrece a poner
  al día en su desplegable de la bandeja, y se dice UNA vez con un aviso. Una
  de la misma versión no, y una que no está en la lista tampoco: de ella no se
  toca nada.
- Pedirlo con su ventana abierta no lanza nada y lo dice. Si no, se deja de
  servir, se espera a que acabe la pareja en curso, se suelta el lock y se
  lanza UN hijo suelto (`agente.py actualizar-raiz RAIZ`) fuera de toda raíz;
  mientras, no se lanza nada suyo ni se abre su ventana.
- Al acabar bien (sale con 0 y lleva la versión del agente) se vuelve a servir
  y la huella nueva se apunta como aceptada, pero solo si la de antes lo era:
  si alguien cambió su código entretanto, se vuelve a preguntar.
- Al acabar mal: si no la tocó (`SIN_TOCAR`) se sigue sirviendo; si la tocó,
  queda «por actualizar» y solo se ofrece volver a ponerla al día.
- Una de antes de la 0.5.0 de la lista también se ofrece, y al acabar se
  atiende.
- `agente.py actualizar-raiz` baja el tag DEL AGENTE (no el de la última
  release) a un temporal, ejecuta SU instalador con `--update RAIZ` y el
  Python del agente, y lo borra. `agente.py actualizar ID` lo pide al buzón.
"""

import subprocess
import sys
from pathlib import Path

from _harness import Checks

import _agente_falso as F
import agente
import penwatch
from common import equipo, update
from ui import bandeja

c = Checks("«Actualizar a la vX» de una raíz")
F.preparar()
update.fetch = lambda url, timeout: c("ningún test toca la red", url, "nada")

NUEVA = "9.9.9"


def lista(uid: str, raiz: Path, nombre: str = "U") -> None:
    """Pone la unidad en la lista con la huella de su código de ahora."""
    equipo.guardar_ajustes(equipo.leer_ajustes().con_unidad(
        equipo.Unidad(uid, equipo.DAEMON, nombre, codigo=agente.huella(raiz) or "")))


def con_version(raiz: Path, version: str) -> Path:
    """Escribe la `VERSION` de una raíz."""
    (raiz / ".prdrive" / "VERSION").write_text(version + "\n", encoding="utf-8")
    return raiz


def hijos() -> list:
    """Los `agente.py actualizar-raiz` lanzados."""
    return [p for p in F.LANZADOS if "actualizar-raiz" in p.args]


def desplegable(ag, nombre: str):
    """Devuelve el desplegable de la bandeja cuyo rótulo empieza por `nombre`."""
    return next(e for e in bandeja.vista(ag.resumen()).menu
                if e.hijos and e.texto.startswith(nombre))


def instalar(raiz: Path, version: str = NUEVA, rc: int = 0) -> None:
    """Hace lo que haría el instalador: cambia el programa y su `VERSION`."""
    (raiz / ".prdrive" / "sync.py").write_text(f"# de la {version}\n", encoding="utf-8")
    con_version(raiz, version)
    hijos()[-1].rc = rc


def avisos(texto: str) -> list[str]:
    """Los títulos de los avisos que dicen `texto`."""
    return [t for t, x in F.AVISOS if texto in t or texto in x]


# una de la lista, más vieja que el agente
U = "a" * 32
RU = con_version(F.unidad(U, parejas=("docs",)), "0.5.0")
lista(U, RU)
F.RAICES[:] = [RU]
ag = F.nuevo()
ag.version = NUEVA
F.vueltas(ag, 2)
fila = next(u for u in ag.resumen()["unidades"] if u["id"] == U)
c("se sirve como siempre, y el resumen dice que se puede poner al día",
  (F.lock(RU).get("pid") is not None, fila["actualizable"], fila["actualizando"]),
  (True, True, False))
c("la bandeja lo ofrece en su desplegable, antes de su versión",
  [(e.texto, e.activa, e.pide) for e in desplegable(ag, "U").hijos][3:],
  [(f"Actualizar a la v{NUEVA}", True, ({"pide": equipo.PIDE_ACTUALIZAR_UNIDAD, "id": U},)),
   ("", True, ()), ("Versión 0.5.0", False, ())])
c("  y lo avisa una vez, diciendo cómo", avisos("tiene la 0.5.0"), ["U tiene la 0.5.0"])
F.vueltas(ag, 5)
c("  sin repetirlo", len(avisos("tiene la 0.5.0")), 1)
c("  sin bandeja, con la orden", "agente.py actualizar " + U in F.AVISOS[-1][1], True)

# ni a la misma versión, ni a una que no está en la lista
M = "b" * 32
RM = F.unidad(M, parejas=("docs",))
lista(M, RM, "Misma")
con_version(RM, NUEVA)
lista(M, RM, "Misma")
D = "d" * 32
RD = con_version(F.unidad(D, parejas=("docs",)), "0.5.0")
F.RAICES[:] = [RU, RM, RD]
F.vueltas(ag, 3)
filas = {u["id"]: u for u in ag.resumen()["unidades"]}
c("a una de la misma versión, o que no está en la lista, no se le ofrece",
  (filas[M]["actualizable"], filas[D]["actualizable"],
   [e.texto for e in bandeja._todas(bandeja.vista(ag.resumen()).menu)
    if e.texto.startswith("Actualizar")]),
  (False, False, [f"Actualizar a la v{NUEVA}"]))
c("  ni se avisa de ellas", (avisos("Misma tiene"), avisos(f"{RD.name} tiene")), ([], []))
ag.pedir({"pide": equipo.PIDE_ACTUALIZAR_UNIDAD, "id": D})
ag.pedir({"pide": equipo.PIDE_ACTUALIZAR_UNIDAD, "id": M})
F.vueltas(ag, 1)
c("  y pedirlo a mano no lanza nada", hijos(), [])
for p in F.pasadas():
    if p.rc is None:
        F.acabar(p)
F.RAICES[:] = [RU]
F.vueltas(ag, 3)

# con su ventana abierta, no
F.ventana_abierta(RU)
F.vueltas(ag, 1)
F.AVISOS.clear()
ag.pedir({"pide": equipo.PIDE_ACTUALIZAR_UNIDAD, "id": U})
F.vueltas(ag, 1)
c("con su ventana abierta no se lanza nada, y se dice",
  (hijos(), avisos("ventana abierta"), ag.conexiones[U].actualizacion),
  ([], ["U: tiene su ventana abierta"], None))
(RU / penwatch.UI_LOCK_REL).unlink()
F.pasar(agente.GRACIA + 1)
F.vueltas(ag, 2)

# pedida con una pasada en marcha: espera a que acabe
ag.pedir({"pide": equipo.PIDE_PASADA, "id": U, "parejas": []})
F.vueltas(ag, 1)
en_marcha = [p for p in F.pasadas(RU) if p.rc is None]
c("(hay una pasada suya en marcha)", len(en_marcha), 1)
ag.pedir({"pide": equipo.PIDE_ACTUALIZAR_UNIDAD, "id": U})
F.vueltas(ag, 2)
c("pedida con una pasada suya en marcha, espera a que acabe",
  (hijos(), ag.conexiones[U].motivo, F.lock(RU).get("pid") is not None),
  ([], "actualizándose", True))
F.acabar(en_marcha[0])
pasadas_antes = len(F.pasadas(RU))
F.vueltas(ag, 1)
c("acabada, suelta el lock y lanza UN hijo suelto fuera de toda raíz",
  (F.lock(RU), len(hijos()), hijos()[0].args[1:], hijos()[0].kwargs.get("cwd")),
  ({}, 1, [str(agente.SCRIPT_DIR / "agente.py"), "actualizar-raiz", str(RU)],
   str(equipo.DIR)))
ag.pedir({"pide": equipo.PIDE_ACTUALIZAR_UNIDAD, "id": U})
ag.pedir({"pide": equipo.PIDE_PASADA, "id": U, "parejas": []})
ag.pedir({"pide": equipo.PIDE_ABRIR, "id": U})
F.vueltas(ag, 3)
c("  mientras, ni otro hijo, ni pasadas, ni su ventana",
  (len(hijos()), len(F.pasadas(RU)) - pasadas_antes,
   [p for p in F.LANZADOS if p.args[-1].endswith("runsync.py")]), (1, 0, []))
c("  la bandeja dice «Actualizando…» apagado, y no deja abrirla",
  [(e.texto, e.activa) for e in desplegable(ag, "U").hijos if e.texto][:4],
  [("Configurar", False), ("Abrir en explorador", False), ("Sincronizar ahora", False),
   (f"Actualizando a la v{NUEVA}…", False)])

# acaba bien
F.AVISOS.clear()
instalar(RU)
F.vueltas(ag, 2)
c("al acabar bien, apunta la huella nueva y lo dice",
  (equipo.leer_ajustes().unidades[U].codigo == agente.huella(RU),
   avisos("actualizada"), ag.conexiones[U].actualizacion),
  (True, [f"U actualizada a la {NUEVA}"], None))
c("  y la vuelve a servir, sin preguntar nada",
  (F.lock(RU).get("pid") is not None,
   [p for p in F.LANZADOS if "pregunta" in p.args and "U" in p.args]), (True, []))
c("  ya no se ofrece", [e.texto for e in desplegable(ag, "U").hijos
                        if e.texto.startswith("Actualiz")], [])
c("  y su desplegable dice la versión nueva",
  [e.texto for e in desplegable(ag, "U").hijos if e.texto.startswith("Versión")],
  [f"Versión {NUEVA}"])


def otra_unidad(uid: str, version: str = "0.5.0", nombre: str = "O"):
    """Un agente nuevo con una unidad vieja de la lista, conectada y servida."""
    r = con_version(F.unidad(uid, parejas=("docs",)), version)
    lista(uid, r, nombre)
    F.RAICES[:] = [r]
    a = F.nuevo()
    a.version = NUEVA
    F.vueltas(a, 2)
    for p in F.pasadas(r):
        F.acabar(p)
    F.vueltas(a, 1)
    return a, r


# alguien cambió su código antes de pedirlo: se pone, pero se vuelve a preguntar
ag, RC = otra_unidad("c" * 32)
(RC / ".prdrive" / "json.py").write_text("print('hola')\n", encoding="utf-8")
ag.pedir({"pide": equipo.PIDE_ACTUALIZAR_UNIDAD, "id": "c" * 32})
F.vueltas(ag, 1)
instalar(RC)
F.vueltas(ag, 2)
preguntas = [p for p in F.LANZADOS if "pregunta" in p.args]
c("si su código no era el aceptado al pedirlo, no se apunta: se vuelve a preguntar",
  (equipo.leer_ajustes().unidades["c" * 32].codigo == agente.huella(RC),
   ag.conexiones["c" * 32].cambiada, "--cambiada" in preguntas[-1].args, F.lock(RC)),
  (False, True, True, {}))

# acaba mal sin tocarla: se sigue sirviendo
ag, RN = otra_unidad("e" * 32)
ag.pedir({"pide": equipo.PIDE_ACTUALIZAR_UNIDAD, "id": "e" * 32})
F.vueltas(ag, 1)
F.AVISOS.clear()
hijos()[-1].rc = agente.SIN_TOCAR
F.vueltas(ag, 2)
c("si no llegó a tocarla (no se pudo bajar), lo dice y se sigue sirviendo",
  (avisos("no he podido actualizarla"), ag.conexiones["e" * 32].a_medias,
   F.lock(RN).get("pid") is not None),
  (["O: no he podido actualizarla"], False, True))

# acaba mal tocándola: a medias
ag, RA = otra_unidad("f" * 32)
ag.pedir({"pide": equipo.PIDE_ACTUALIZAR_UNIDAD, "id": "f" * 32})
F.vueltas(ag, 1)
(RA / ".prdrive" / "sync.py").write_text("# a medias\n", encoding="utf-8")
hijos()[-1].rc = 1
F.vueltas(ag, 2)
c("si la tocó y falló, queda a medias: ni se sirve ni se apunta su huella",
  (ag.conexiones["f" * 32].a_medias, F.lock(RA),
   equipo.leer_ajustes().unidades["f" * 32].codigo == agente.huella(RA)),
  (True, {}, False))
menu = desplegable(ag, "O")
c("  la bandeja la dice «por actualizar» y solo ofrece volver a ponerla al día",
  (menu.texto, [(e.texto, e.activa) for e in menu.hijos if e.texto][:1]),
  ("O (por actualizar)", [(f"Actualizar a la v{NUEVA}", True)]))
ag.pedir({"pide": equipo.PIDE_ABRIR, "id": "f" * 32})
F.vueltas(ag, 1)
c("  y no abre su ventana", [p for p in F.LANZADOS if p.args[-1] == str(
    RA / ".prdrive" / "runsync.py")], [])
ag.pedir({"pide": equipo.PIDE_ACTUALIZAR_UNIDAD, "id": "f" * 32})
F.vueltas(ag, 1)
instalar(RA)
F.vueltas(ag, 2)
c("  pedida otra vez y acabada bien, se apunta (era la aceptada antes del primer intento)",
  (ag.conexiones["f" * 32].a_medias,
   equipo.leer_ajustes().unidades["f" * 32].codigo == agente.huella(RA),
   F.lock(RA).get("pid") is not None), (False, True, True))

# sale con 0 pero no lleva la versión del agente: mal
ag, RX = otra_unidad("9" * 32)
ag.pedir({"pide": equipo.PIDE_ACTUALIZAR_UNIDAD, "id": "9" * 32})
F.vueltas(ag, 1)
F.AVISOS.clear()
instalar(RX, version="0.5.1")
F.vueltas(ag, 1)
c("si sale con 0 pero no lleva la versión del agente, ha ido mal",
  (avisos("no he podido actualizarla"), ag.conexiones["9" * 32].a_medias),
  (["O: no he podido actualizarla"], True))

# una de antes de la 0.5.0, de la lista
V = "6" * 32
RV = con_version(F.unidad(V, parejas=("docs",)), "0.4.3")
lista(V, RV, "Vieja")
F.RAICES[:] = [RV]
F.AVISOS.clear()
ag = F.nuevo()
ag.version = NUEVA
F.vueltas(ag, 3)
c("una de la lista anterior a la 0.5.0: no se atiende, se avisa una vez, y se ofrece",
  (F.lock(RV), len([t for t, _ in F.AVISOS]),
   [(e.texto, e.activa) for e in desplegable(ag, "Vieja").hijos][:1]),
  ({}, 1, [(f"Actualizar a la v{NUEVA}", True)]))
ag.pedir({"pide": equipo.PIDE_ACTUALIZAR_UNIDAD, "id": V})
F.vueltas(ag, 1)
instalar(RV)
F.vueltas(ag, 2)
c("  puesta al día, se atiende", (ag.conexiones[V].vieja, F.lock(RV).get("pid") is not None,
                                 desplegable(ag, "Vieja").texto), (None, True, "Vieja"))

# una raíz de este equipo, igual (pura: la bandeja con un resumen hecho a mano)
casa = {"equipo": [{"id": "e", "nombre": "Casa", "estado": bandeja.ABIERTA}], "version": NUEVA,
        "unidades": [{"id": "e", "nombre": "Casa", "del_equipo": True, "en_lista": True,
                      "atendida": True, "version": "0.5.0", "actualizable": True}]}
raiz = next(e for e in bandeja.vista(casa).menu if e.hijos)
c("a una raíz de este equipo más vieja se le ofrece igual, en su desplegable",
  [(e.texto, e.pide) for e in raiz.hijos if e.texto.startswith("Actualiz")],
  [(f"Actualizar a la v{NUEVA}", ({"pide": equipo.PIDE_ACTUALIZAR_UNIDAD, "id": "e"},))])
casa["unidades"][0].update(actualizable=False, actualizando=True, atendida=False)
raiz = next(e for e in bandeja.vista(casa).menu if e.hijos)
c("  y mientras se actualiza, nada suyo se abre",
  [(e.texto, e.activa) for e in raiz.hijos if e.texto][:4],
  [("Configurar", False), ("Abrir en explorador", False), ("Sincronizar ahora", False),
   (f"Actualizando a la v{NUEVA}…", False)])

# mientras el propio agente se actualiza, no se ofrece
ag.version = "99.0.0"
ag.actualizando = F.Proc(["agente.py", "actualizar"])
c("mientras el agente se actualiza a sí mismo, no se ofrece",
  next(u for u in ag.resumen()["unidades"] if u["id"] == V)["actualizable"], False)
ag.actualizando.rc = 0

# agente.py actualizar ID: al buzón
equipo.recoger()
rc = agente.main(["actualizar", U])
c("agente.py actualizar ID lo deja en el buzón",
  (rc, [(p.get("pide"), p.get("id")) for p in equipo.recoger()]),
  (0, [(equipo.PIDE_ACTUALIZAR_UNIDAD, U)]))

# agente.py actualizar-raiz
bajadas: list = []


def bajar(tag, destino, progreso=None):
    """Descarga de mentira: apunta lo pedido y deja un instalador vacío."""
    bajadas.append((tag, Path(destino)))
    Path(destino).mkdir(parents=True)
    (Path(destino) / "prdrive-install.py").write_text("", encoding="utf-8")
    return Path(destino)


update.download = bajar
ejecutadas: list = []
agente.ejecutar = lambda args, **kw: ejecutadas.append((args, kw)) or \
    subprocess.CompletedProcess(args, 0, "Actualizando /x\nHecho.\n", "")
update.installed_version = lambda root=None: "0.5.4"
rc = agente.main(["actualizar-raiz", str(RU)])
c("actualizar-raiz baja el tag DEL AGENTE a un temporal fuera de toda raíz",
  (bajadas[0][0], bajadas[0][1].is_relative_to(Path(agente.tempfile.gettempdir()))),
  ("v0.5.4", True))
args, kw = ejecutadas[0]
c("  ejecuta SU instalador con --update RAIZ y el Python del agente",
  args, [sys.executable, "-u", str(bajadas[0][1] / "prdrive-install.py"), "--update",
         str(RU)])
c("  desde la carpeta del agente", kw.get("cwd"), str(equipo.DIR))
c("  lo que dice va al diario, y sale con lo que salga el instalador",
  (rc, any(d.endswith("Hecho.") and "actualizar" in d for d in F.DIARIO)), (0, True))
c("  borra el temporal", bajadas[0][1].parent.exists(), False)
agente.ejecutar = lambda args, **kw: subprocess.CompletedProcess(args, 1, "", "InstallError\n")
c("  si el instalador falla, sale con su código", agente.main(["actualizar-raiz", str(RU)]), 1)


def bajar_mal(tag, destino, progreso=None):
    """Descarga que falla porque el zip está dañado."""
    raise update.UpdateError("El zip descargado está dañado (x). No se ha extraído nada.")


update.download = bajar_mal
ejecutadas.clear()
c("una descarga que no se comprueba no ejecuta nada: SIN_TOCAR",
  (agente.main(["actualizar-raiz", str(RU)]), ejecutadas), (agente.SIN_TOCAR, []))
update.installed_version = lambda root=None: ""
update.download = bajar
c("sin saber la versión del agente, nada: SIN_TOCAR",
  (agente.main(["actualizar-raiz", str(RU)]), ejecutadas), (agente.SIN_TOCAR, []))

sys.exit(c.report())
