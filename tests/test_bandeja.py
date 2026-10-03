#!/usr/bin/env python3
"""La bandeja del agente (fase 4): lo que enseña y lo que pide, sin Windows.

`ui/bandeja.py` es puro: del resumen del agente sale el icono, la línea del
ratón y el menú, y cada entrada lleva las peticiones del buzón que hace. Aquí
se comprueba con el resumen de un agente de verdad (unidades y raíces de
mentira, `_agente_falso`), y que lo que pide la bandeja lo atiende el agente
por el mismo camino que el buzón:
- Los cinco estados, con su orden de prioridad.
- Un desplegable por dispositivo, sin repetir su nombre dentro:
  «Configurar» (su ventana), «Abrir en explorador» (su carpeta),
  «Sincronizar ahora» (solo él); fuera, «Sincronizar todo ahora» solo con dos
  o más, «Pausar»/«Reanudar», «Cerrar el agente».
- Su icono: el color o el `.ico` de su `autorun.inf`, solo de una raíz de la
  lista; de las demás, la marca de prdrive.
- «Atender…» para una unidad con «Ahora no», y NUNCA «Configurar» ni «Abrir
  en explorador» para una que no está en la lista.
- La raíz cifrada: «Desbloquear…», «Bloquear», la casilla de
  `pedir_al_iniciar`; «Configurar…» y «Abrir en explorador…» con ella cerrada
  desbloquean y abren al verla.
- Un desbloqueo cancelado se olvida y se vuelve a ofrecer.
- `despertar` (vuelta de la suspensión) sondea ya los remotos sin conexión.
- El agente le pasa la vista a la bandeja solo cuando cambia.
- Los iconos de los cinco estados, y el `Vigia` que se despierta.
"""

import shutil
import struct
import sys
import time
from pathlib import Path

from _harness import Checks, tmpdir

import _agente_falso as F
import agente
import penwatch
from common import equipo, vestibulo
from ui import bandeja, icons

c = Checks("la bandeja del agente: qué enseña y qué pide")

F.preparar()


def textos(vista) -> list[str]:
    """Devuelve los textos del menú de una vista."""
    return [e.texto for e in vista.menu]


def entrada(vista, texto: str):
    """Devuelve la entrada del menú con ese texto, o `None`."""
    for e in bandeja._todas(vista.menu):
        if e.texto == texto:
            return e
    return None


def desplegable(vista, rotulo: str):
    """Devuelve el desplegable de un dispositivo por su rótulo, o `None`."""
    return next((e for e in vista.menu if e.texto == rotulo and e.hijos), None)


def dentro(vista, rotulo: str) -> list[str]:
    """Devuelve los textos de dentro del desplegable de un dispositivo."""
    return [e.texto for e in desplegable(vista, rotulo).hijos]


def en(vista, rotulo: str, texto: str):
    """Devuelve la entrada `texto` del desplegable `rotulo`, o `None`."""
    return next((e for e in desplegable(vista, rotulo).hijos if e.texto == texto), None)


def elegir(ag, vista, texto: str, rotulo: str | None = None) -> None:
    """Lo que hace la bandeja al elegir una entrada: sus peticiones, al agente."""
    e = en(vista, rotulo, texto) if rotulo else entrada(vista, texto)
    for p in e.pide:
        ag.pedir(p)


# El explorador de este equipo: el de Linux, haya o no `xdg-open` aquí.
ORDEN_EXPLORAR = agente.orden_explorar
agente.orden_explorar = lambda ruta: ["xdg-open", str(ruta)]


def explorados() -> list[str]:
    """Devuelve las carpetas abiertas en el explorador, por los procesos «lanzados»."""
    return [p.args[1] for p in F.LANZADOS if p.args and p.args[0] == "xdg-open"]


def autorun(raiz: Path, icono: str) -> None:
    """Le pone a una raíz un `autorun.inf` con ese `icon=`, como «Nombre e icono…»."""
    (raiz / "autorun.inf").write_text(f"[autorun]\nicon={icono}\n", encoding="utf-16")


class BandejaFalsa:
    """Bandeja de mentira que apunta las vistas que le ponen.

    Attributes:
        vistas: Las vistas recibidas, en orden.
    """
    def __init__(self):
        """Empieza sin ninguna vista."""
        self.vistas = []

    def poner(self, vista):
        """Apunta la vista recibida."""
        self.vistas.append(vista)


# sin nada
ag = F.nuevo()
ag.bandeja = falsa = BandejaFalsa()
F.vueltas(ag, 1)
v = falsa.vistas[-1]
c("sin raíces ni unidades: bien, esperando unidades", (v.icono, v.tip),
  (icons.BIEN, "prdrive · esperando unidades"))
c("  el menú, sin cabecera gris ni dispositivos: pausar y cerrar",
  textos(v), ["Pausar", "", "Cerrar el agente"])
c("  cada entrada con su icono, y todos existen como glifo",
  ([e.icono for e in v.menu if e.texto],
   all(i in icons.GLIFOS for i in bandeja.ICONOS)),
  ([bandeja.I_PAUSAR, bandeja.I_CERRAR], True))
F.vueltas(ag, 3)
c("el agente solo pasa la vista cuando cambia", len(falsa.vistas), 1)

# una unidad atendida
UNO = "1" * 32
raiz1 = F.unidad(UNO, nombre="PRDRIVE-1")
autorun(raiz1, r".prdrive\icono-verde.ico")
equipo.guardar_ajustes(equipo.leer_ajustes().con_unidad(
    equipo.Unidad(UNO, equipo.DAEMON, "PRDRIVE-1")))
ag = F.nuevo()
ag.bandeja = falsa = BandejaFalsa()
F.RAICES[:] = [raiz1]
F.vueltas(ag, 3)
v = falsa.vistas[-1]
c("una pasada en marcha: sincronizando, con la unidad y la pareja",
  (v.icono, v.tip), (icons.SINCRONIZANDO, "prdrive · sincronizando PRDRIVE-1 · docs"))
c("  el menú: su desplegable, y lo del agente fuera (con una sola, sin «todo»)",
  textos(v), ["PRDRIVE-1", "", "Pausar", "", "Cerrar el agente"])
c("  dentro, sin repetir su nombre: configurar, explorador, sincronizar",
  dentro(v, "PRDRIVE-1"), ["Configurar", "Abrir en explorador", "Sincronizar ahora"])
c("  «Configurar» es la primera, la de por defecto, con el engranaje, y abre su ventana",
  (en(v, "PRDRIVE-1", "Configurar").defecto, en(v, "PRDRIVE-1", "Configurar").icono,
   en(v, "PRDRIVE-1", "Configurar").pide, v.defecto() is en(v, "PRDRIVE-1", "Configurar")),
  (True, bandeja.I_CONFIGURAR, ({"pide": equipo.PIDE_ABRIR, "id": UNO},), True))
c("  «Abrir en explorador» lleva la carpeta, ahora con su sentido",
  (en(v, "PRDRIVE-1", "Abrir en explorador").icono,
   en(v, "PRDRIVE-1", "Abrir en explorador").pide),
  (bandeja.I_EXPLORAR, ({"pide": equipo.PIDE_EXPLORAR, "id": UNO},)))
c("  «Sincronizar ahora» pide su pasada, con todas sus parejas",
  en(v, "PRDRIVE-1", "Sincronizar ahora").pide,
  ({"pide": equipo.PIDE_PASADA, "id": UNO, "parejas": []},))
c("  el icono del desplegable es el de su autorun.inf: la marca en verde",
  (ag.resumen()["unidades"][0]["emblema"], desplegable(v, "PRDRIVE-1").emblema),
  ({"marca": "verde"}, bandeja.Emblema(campo=icons.CAMPOS["verde"])))
propio = raiz1 / ".prdrive" / "icono-propio-0123abcd.ico"
propio.write_bytes(icons.ico((16,)))
autorun(raiz1, r".prdrive\icono-propio-0123abcd.ico")
c("  un icono cambiado desde su ventana no se relee en cada vuelta",
  ag.resumen()["unidades"][0]["emblema"], {"marca": "verde"})
F.pasar(agente.MIRAR_EMBLEMA)
c("  pasado MIRAR_EMBLEMA, sí: un .ico propio va por su ruta",
  ag.resumen()["unidades"][0]["emblema"], {"ico": str(propio)})
F.acabar(F.pasadas()[-1], rc=0)
F.vueltas(ag, 1)
# La siguiente pareja ya ha empezado: lo de «sincronizado» se mira sin ella.
en_marcha, ag.pasada = ag.pasada, None
buena = ag.resumen()["ultima_pasada"]
c("acabada bien: el resumen lleva cuándo, y el ratón lo dice",
  (isinstance(buena, float),
   bandeja.vista(ag.resumen(), buena + 5).tip,
   bandeja.vista(ag.resumen(), buena + 7 * 60 + 5).tip),
  (True, "prdrive · sincronizado hace un momento", "prdrive · sincronizado hace 7 min"))
falsa.vistas.clear()
ag._escribir_estado()
F.pasar(60)
ag._escribir_estado()
ag._escribir_estado()
c("  el agente se la vuelve a pasar a la bandeja cuando cambia el «hace», y solo entonces",
  [v.tip for v in falsa.vistas],
  ["prdrive · sincronizado hace un momento", "prdrive · sincronizado hace 1 min"])
ag.pasada = en_marcha
F.acabar(F.pasadas()[-1], rc=1, salida="ERROR : algo raro\n")
F.vueltas(ag, 1)
v = falsa.vistas[-1]
c("una pareja que falla: aviso, y lo dice", (v.icono, v.tip),
  (icons.AVISO, "prdrive · PRDRIVE-1: falla fotos"))
c("  y en el menú, arriba, una línea que lleva a su ventana",
  (textos(v)[0], entrada(v, "PRDRIVE-1: falla fotos · Abrir…").pide,
   entrada(v, "PRDRIVE-1: falla fotos · Abrir…").activa,
   entrada(v, "PRDRIVE-1: falla fotos · Abrir…").icono),
  ("PRDRIVE-1: falla fotos · Abrir…", ({"pide": equipo.PIDE_ABRIR, "id": UNO},), True,
   bandeja.I_AVISO))

elegir(ag, v, "Pausar")
F.vueltas(ag, 1)
v = falsa.vistas[-1]
c("«Pausar» lo pide al agente, que se pausa", (ag.pausado, v.icono), (True, icons.PAUSA))
c("  y el menú ofrece «Reanudar»", entrada(v, "Reanudar") is not None, True)
c("  en pausa, el aviso sigue arriba y no hay cabecera de estado", textos(v)[:2],
  ["PRDRIVE-1: falla fotos · Abrir…", ""])
elegir(ag, v, "Reanudar")
F.vueltas(ag, 1)
c("«Reanudar» también", ag.pausado, False)

antes = len(F.LANZADOS)
elegir(ag, falsa.vistas[-1], "Configurar", "PRDRIVE-1")
F.vueltas(ag, 1)
lanzado = F.LANZADOS[antes:]
c("«Configurar» lanza la ventana de la unidad, aunque el agente la esté atendiendo",
  [p.args[-1] for p in lanzado], [str(raiz1 / penwatch.APP_SUBDIR / "runsync.py")])
c("  fuera de la unidad", lanzado[0].kwargs.get("cwd"), str(equipo.DIR))
antes = len(F.LANZADOS)
elegir(ag, falsa.vistas[-1], "Abrir en explorador", "PRDRIVE-1")
F.vueltas(ag, 1)
lanzado = F.LANZADOS[antes:]
c("«Abrir en explorador» abre su carpeta con el explorador del sistema, nada de runsync",
  [p.args for p in lanzado], [["xdg-open", str(raiz1)]])
c("  también desde fuera de la unidad", lanzado[0].kwargs.get("cwd"), str(equipo.DIR))
F.PANTALLA[0] = False
antes = len(F.LANZADOS)
ag.pedir({"pide": equipo.PIDE_EXPLORAR, "id": UNO})
F.vueltas(ag, 1)
F.PANTALLA[0] = True
c("  sin entorno gráfico no lanza nada, y lo dice",
  (len(F.LANZADOS) - antes, any("no hay dónde abrir su carpeta" in d for d in F.DIARIO)),
  (0, True))
F.ventana_abierta(raiz1)
antes = len(F.LANZADOS)
elegir(ag, falsa.vistas[-1], "Configurar", "PRDRIVE-1")
F.vueltas(ag, 1)
c("  con su ventana ya abierta no lanza otra", len(F.LANZADOS), antes)
(raiz1 / penwatch.UI_LOCK_REL).unlink()
F.pasar(agente.GRACIA)                  # la gracia tras cerrarse la ventana

# una unidad a la que se dijo «Ahora no»
DOS = "2" * 32
raiz2 = F.unidad(DOS, nombre="PRDRIVE-2")
(raiz2 / ".prdrive" / "icono-propio-0123abcd.ico").write_bytes(icons.ico((16,)))
autorun(raiz2, r".prdrive\icono-propio-0123abcd.ico")
F.PANTALLA[0] = False                   # sin pantalla: «Ahora no» al momento
F.RAICES[:] = [raiz1, raiz2]
F.vueltas(ag, 3)
F.PANTALLA[0] = True
v = falsa.vistas[-1]
c("una unidad con «Ahora no»: su desplegable lo dice, y dentro solo «Atender…»",
  (dentro(v, "PRDRIVE-2 (sin atender)"),
   en(v, "PRDRIVE-2 (sin atender)", "Atender…").pide),
  (["Atender…"], ({"pide": equipo.PIDE_ATENDER, "id": DOS},)))
c("  ni «Configurar» ni «Abrir en explorador»: sería tocar su código sin el sí",
  [e.texto for e in bandeja._todas(desplegable(v, "PRDRIVE-2 (sin atender)").hijos)
   if e.pide and e.pide[0]["pide"] in (equipo.PIDE_ABRIR, equipo.PIDE_EXPLORAR)], [])
c("  y su icono es la marca de prdrive: de su autorun.inf no se lee nada",
  (desplegable(v, "PRDRIVE-2 (sin atender)").emblema,
   next(u for u in ag.resumen()["unidades"] if u["id"] == DOS)["emblema"]),
  (bandeja.MARCA, {}))
antes = len(F.LANZADOS)
ag.pedir({"pide": equipo.PIDE_ABRIR, "id": DOS})
ag.pedir({"pide": equipo.PIDE_EXPLORAR, "id": DOS})
F.vueltas(ag, 1)
c("  ni aunque se pida a mano: ni su ventana ni su carpeta",
  [p for p in F.LANZADOS[antes:] if str(raiz2) in " ".join(p.args)], [])
elegir(ag, v, "Atender…", "PRDRIVE-2 (sin atender)")
F.vueltas(ag, 1)
c("«Atender…» la añade a la lista", DOS in equipo.leer_ajustes().unidades, True)
v = falsa.vistas[-1]
c("con dos atendidas, cada una su desplegable (bajo el aviso que sigue), y fuera "
  "«Sincronizar todo ahora»",
  textos(v), ["PRDRIVE-1: falla fotos · Abrir…", "", "PRDRIVE-1", "PRDRIVE-2", "",
              "Sincronizar todo ahora", "Pausar", "", "Cerrar el agente"])
c("  que pide las dos", [p["id"] for p in entrada(v, "Sincronizar todo ahora").pide],
  [UNO, DOS])
c("  ya en la lista, su icono propio", desplegable(v, "PRDRIVE-2").emblema,
  bandeja.Emblema(ico=str(raiz2 / ".prdrive" / "icono-propio-0123abcd.ico")))

elegir(ag, v, "Cerrar el agente")
F.vueltas(ag, 1)
c("«Cerrar el agente» lo termina (en cuanto acabe lo que esté en marcha)",
  ag.terminar, True)
F.RAICES[:] = []

# la raíz cifrada
penwatch.candidate_roots = lambda cfg: ([Path(r) for r in cfg.get("extra_roots", [])]
                                        + list(F.RAICES))
VC = "/opt/veracrypt/veracrypt"
penwatch.installed_veracrypt = lambda: VC
penwatch._con_escritorio = lambda: True
vestibulo.retenido = lambda hc: None
# La raíz cifrada montada en una carpeta, con el `veracrypt` de la línea de
# órdenes, es Linux; en Windows va en una letra fija, y una carpeta `C:\…` se
# leería como la letra C. Se hace Linux en cualquier sistema, como en
# `test_agente_veracrypt.py`, y se deshace al acabar la sección.
LINUX_FINGIDO = (penwatch.IS_WIN, agente.IS_WIN, equipo.Unidad.letra)
penwatch.IS_WIN = agente.IS_WIN = False
equipo.Unidad.letra = property(lambda self: "")
UID = "c" * 32
FISICA = tmpdir("prdrive-cifrado-")
HC = FISICA / vestibulo.CONTENEDOR
HC.write_bytes(b"\0" * 512)
PUNTO = tmpdir("prdrive-punto-")


def montar() -> None:
    """Hace lo que VeraCrypt al abrirlo: aparece la raíz en su punto."""
    app = PUNTO / penwatch.APP_SUBDIR
    (app / "state").mkdir(parents=True, exist_ok=True)
    (app / "PRDRIVE").write_text(f"id={UID}\ntipo=equipo\n", encoding="utf-8")
    (app / "VERSION").write_text(F.VERSION + "\n", encoding="utf-8")
    for py in ("runsync.py", "sync.py"):
        (app / py).write_text("# de mentira\n", encoding="utf-8")
    (app / "sync_config.toml").write_text(
        '[defaults]\nremote = "nas"\n\n[[pair]]\nname = "notas"\nlocal = "notas"\n'
        'remote_path = "/R/notas"\n', encoding="utf-8")


def desmontar() -> None:
    """Vacía el punto de montaje, como al cerrar el contenedor."""
    for hijo in PUNTO.iterdir():
        shutil.rmtree(hijo) if hijo.is_dir() else hijo.unlink()


def veracrypts() -> list:
    """Devuelve los procesos lanzados que son el VeraCrypt de mentira."""
    return [p for p in F.LANZADOS if p.args and p.args[0] == VC]


equipo.guardar_ajustes(equipo.Ajustes(pedir_al_iniciar=False).con_unidad(
    equipo.Unidad(UID, equipo.DAEMON, "Mi portátil", str(PUNTO), str(HC))))
ag = F.nuevo()
ag.bandeja = falsa = BandejaFalsa()
F.vueltas(ag, 3)
v = falsa.vistas[-1]
R = "Mi portátil (bloqueada)"
c("la raíz cifrada cerrada: icono de bloqueada, sin alarmar",
  (v.icono, v.tip), (icons.BLOQUEADO, "prdrive · Mi portátil bloqueada"))
c("  su desplegable dice que está bloqueada, y lleva la marca de prdrive por icono",
  (textos(v), desplegable(v, R).emblema),
  ([R, "", "Pausar", "", "Cerrar el agente"], bandeja.MARCA))
c("  dentro: configurar y explorador (desbloqueando antes), sincronizar apagado, "
  "desbloquear y la casilla",
  [(e.texto, e.activa) for e in desplegable(v, R).hijos],
  [("Configurar…", True), ("Abrir en explorador…", True), ("Sincronizar ahora", False),
   ("", True), ("Desbloquear…", True), ("Pedir la contraseña al iniciar sesión", True)])
c("  «Configurar…» es la entrada por defecto", v.defecto().texto, "Configurar…")
casilla = en(v, R, "Pedir la contraseña al iniciar sesión")
c("  la casilla dice el ajuste y pide el contrario", (casilla.marcada, casilla.pide),
  (False, ({"pide": equipo.PIDE_AJUSTE, "clave": "pedir_al_iniciar", "valor": True},)))
elegir(ag, v, "Pedir la contraseña al iniciar sesión")
F.vueltas(ag, 1)
c("  elegida, el agente escribe el ajuste",
  (equipo.leer_ajustes().pedir_al_iniciar,
   entrada(falsa.vistas[-1], "Pedir la contraseña al iniciar sesión").marcada), (True, True))

elegir(ag, falsa.vistas[-1], "Configurar…")
F.vueltas(ag, 1)
c("«Configurar…» con ella cerrada: VeraCrypt pide la contraseña",
  [p.args for p in veracrypts()], [[VC, str(HC), str(PUNTO)]])
v = falsa.vistas[-1]
c("  mientras, «Desbloqueando…», sin ofrecer otro desbloqueo",
  (textos(v)[0], [e.texto for e in desplegable(v, textos(v)[0]).hijos if "esbloque" in e.texto],
   v.icono),
  ("Mi portátil (desbloqueando…)", ["Desbloqueando: la contraseña la pide VeraCrypt"],
   icons.BLOQUEADO))
ag.pedir({"pide": equipo.PIDE_DESBLOQUEAR, "id": UID})
F.vueltas(ag, 1)
c("  pedirlo otra vez no abre una segunda ventana de VeraCrypt", len(veracrypts()), 1)
autorun(FISICA, ".prdrive-icono-granate.ico")
montar()
antes = len(F.LANZADOS)
F.vueltas(ag, 3)
ventanas = [p for p in F.LANZADOS[antes:] if p.args[-1].endswith("runsync.py")]
c("  abierta, sale su ventana sola", [p.args[-1] for p in ventanas],
  [str(PUNTO / penwatch.APP_SUBDIR / "runsync.py")])
c("  y no su carpeta: eso es «Abrir en explorador»", explorados(), [str(raiz1)])
v = falsa.vistas[-1]
c("  abierta, sin paréntesis y con el icono del autorun.inf de junto al contenedor",
  (textos(v)[0], desplegable(v, "Mi portátil").emblema),
  ("Mi portátil", bandeja.Emblema(campo=icons.CAMPOS["granate"])))
c("  y se le puede pedir una pasada y bloquearla",
  (en(v, "Mi portátil", "Sincronizar ahora").activa, en(v, "Mi portátil", "Bloquear").pide),
  (True, ({"pide": equipo.PIDE_BLOQUEAR, "id": UID},)))
F.acabar(F.pasadas(PUNTO)[-1], rc=0)
elegir(ag, v, "Bloquear", "Mi portátil")
F.vueltas(ag, 1)
c("«Bloquear» lo pide al agente, que desmonta", len(veracrypts()), 2)
c("  «Bloqueando…»", (textos(falsa.vistas[-1])[0],
                      entrada(falsa.vistas[-1], "Bloqueando…").activa),
  ("Mi portátil (bloqueando…)", False))
desmontar()
F.vueltas(ag, 2)
c("  y vuelve a bloqueada, otra vez con la marca de prdrive",
  (falsa.vistas[-1].icono, desplegable(falsa.vistas[-1], R).emblema),
  (icons.BLOQUEADO, bandeja.MARCA))

# «Abrir en explorador…» con ella cerrada: desbloquea y abre su carpeta.
elegir(ag, falsa.vistas[-1], "Abrir en explorador…")
F.vueltas(ag, 1)
c("«Abrir en explorador…» con ella cerrada: VeraCrypt pide la contraseña",
  len(veracrypts()), 3)
montar()
antes = len(F.LANZADOS)
F.vueltas(ag, 3)
c("  abierta, sale su carpeta en el explorador, y no su ventana",
  ([p.args[1] for p in F.LANZADOS[antes:] if p.args[0] == "xdg-open"],
   [p for p in F.LANZADOS[antes:] if p.args[-1].endswith("runsync.py")]),
  ([str(PUNTO)], []))
F.acabar(F.pasadas(PUNTO)[-1], rc=0)
elegir(ag, falsa.vistas[-1], "Bloquear", "Mi portátil")
F.vueltas(ag, 1)
desmontar()
F.vueltas(ag, 2)
c("  y se vuelve a bloquear como siempre", (len(veracrypts()), falsa.vistas[-1].icono),
  (4, icons.BLOQUEADO))

# Un desbloqueo cancelado: VeraCrypt sale y la raíz no aparece.
elegir(ag, falsa.vistas[-1], "Desbloquear…")
F.vueltas(ag, 1)
veracrypts()[-1].rc = 1
F.vueltas(ag, 2)
c("un desbloqueo cancelado sigue «Desbloqueando…» un rato",
  UID in ag.desbloqueos, True)
F.pasar(agente.GRACIA_ABRIR)
F.vueltas(ag, 1)
c("  y luego se olvida y se vuelve a ofrecer",
  (UID in ag.desbloqueos, entrada(falsa.vistas[-1], "Desbloquear…") is not None),
  (False, True))
c("  el diario lo cuenta", any("no se ha desbloqueado" in d for d in F.DIARIO), True)

# El fantasma: se ofrece bloquear, que es la salida.
vestibulo.retenido = lambda hc: False
montar()
F.vueltas(ag, 3)
v = falsa.vistas[-1]
c("un volumen fantasma es un aviso, y su desplegable ofrece bloquear",
  (v.icono, en(v, "Mi portátil (no responde)", "Bloquear") is not None,
   en(v, "Mi portátil (no responde)", "Configurar").activa), (icons.AVISO, True, False))
desmontar()
vestibulo.retenido = lambda hc: None
F.vueltas(ag, 2)
penwatch.IS_WIN, agente.IS_WIN, equipo.Unidad.letra = LINUX_FINGIDO

# despertar
ag.entorno = agente.pl.sin_conexion(ag.entorno, UNO, "nas", F.RELOJ[0] + 3600)
ag.entorno_leido = F.RELOJ[0]
ag.pedir({"pide": equipo.PIDE_DESPERTAR})
ag._buzon(F.RELOJ[0])
c("vuelta de la suspensión: el remoto sin conexión se sondea ya",
  ag.entorno.sin_conexion[(UNO, "nas")] <= F.RELOJ[0], True)
c("  y el entorno se vuelve a leer", ag.entorno_leido, float("-inf"))
# Windows manda dos eventos de reanudación seguidos: el diario, una línea.
ag.pedir({"pide": equipo.PIDE_DESPERTAR})
ag._buzon(F.RELOJ[0] + 1)
c("  el segundo aviso de la misma vuelta no se apunta otra vez",
  sum(x == "el equipo vuelve de la suspensión" for x in F.DIARIO), 1)
ag.pedir({"pide": equipo.PIDE_DESPERTAR})
ag._buzon(F.RELOJ[0] + 1 + agente.DESPERTAR_DOBLE)
c("  otra suspensión más tarde, sí",
  sum(x == "el equipo vuelve de la suspensión" for x in F.DIARIO), 2)

# «Probar ahora» en un aviso de «Sin conexión»
ag.entorno = agente.pl.sin_conexion(ag.entorno, UNO, "nas", F.RELOJ[0] + 3600)
leido = ag.entorno_leido = F.RELOJ[0]
ag.pedir({"pide": equipo.PIDE_SONDEAR})
ag._buzon(F.RELOJ[0])
c("«Probar ahora»: el remoto sin conexión se sondea ya, sin releer lo demás",
  (ag.entorno.sin_conexion[(UNO, "nas")] <= F.RELOJ[0], ag.entorno_leido), (True, leido))

# lo puro, suelto
largo = bandeja.tip("x" * 300)
c("la línea del ratón cabe en szTip (127)", (len(largo), largo.endswith("…")), (127, True))
muchos = {"unidades": [{"id": "u", "nombre": "U", "fallando": ["a", "b", "c", "d", "e"]}]}
v = bandeja.vista(muchos)
c("con muchos avisos: tres líneas y «y N más», apagada",
  (textos(v)[:4], entrada(v, "y 2 más").activa),
  (["U: falla a · Abrir…", "U: falla b · Abrir…", "U: falla c · Abrir…", "y 2 más"],
   False))
fuera = bandeja.vista({"sin_conexion": ["U: nas"], "ausentes": ["C:\\x.hc"],
                       "fantasmas": ["P:\\"],
                       "equipo": [{"id": "e", "ruta": "P:\\", "estado": bandeja.FANTASMA}],
                       "unidades": [{"id": "u", "nombre": "U"}]})
c("un remoto sin conexión se prueba ya; un fantasma se bloquea; una raíz que no "
  "está, apagada",
  [(e.texto, e.pide, e.activa) for e in fuera.menu[:3]],
  [("Sin conexión: U: nas · Probar ahora", ({"pide": equipo.PIDE_SONDEAR},), True),
   ("Falta la raíz de este equipo: C:\\x.hc", (), False),
   ("Volumen fantasma en P:\\ · Bloquear", ({"pide": equipo.PIDE_BLOQUEAR, "id": "e"},),
    True)])
c("«hace»: un momento, minutos, la hora de hoy, y la fecha de otro día",
  (bandeja.hace(30, 0), bandeja.hace(125, 0),
   bandeja.hace(2 * 3600, time.mktime((2026, 9, 30, 9, 5, 0, 0, 0, -1))),
   bandeja.hace(2 * 86400, time.mktime((2026, 9, 28, 9, 5, 0, 0, 0, -1)))),
  ("hace un momento", "hace 2 min", "a las 09:05", "el 28/09 a las 09:05"))
c("bien y sin pasadas todavía: con algo atendido, se espera; sin nada, se dice",
  (bandeja.estado({"unidades": [{"atendida": True}]})[1],
   bandeja.estado({"unidades": [{"atendida": False}]})[1]),
  ("esperando la primera pasada", "sin nada que sincronizar ahora"))
c("lo que retiene sin ser pausa (red de uso medido) usa el icono de pausa",
  bandeja.estado({"retenido": "red de uso medido", "unidades": [{}]}),
  (icons.PAUSA, "esperando: red de uso medido"))
# El «Pausar» de la ventana de una raíz (#64): pausa, con su nombre, por debajo
# de los avisos y por encima de «sincronizado hace…».
PAUSADA = {"nombre": "PRDRIVE-3", "pausada": True, "atendida": False}
c("una raíz pausada desde su ventana: el icono de pausa y su nombre",
  bandeja.estado({"unidades": [PAUSADA, {"nombre": "OTRA", "atendida": True}],
                  "ultima_pasada": 0}, ahora=60),
  (icons.PAUSA, "PRDRIVE-3 en pausa"))
c("  un aviso manda sobre ella",
  bandeja.estado({"unidades": [{**PAUSADA, "fallando": ["docs"]}]})[0], icons.AVISO)

# los desplegables, sueltos
fila = {"id": "u", "nombre": "U", "en_lista": True, "atendida": True}
r = {"equipo": [{"id": "e", "nombre": "Casa", "estado": bandeja.ABIERTA}],
     "unidades": [fila, {"id": "e", "nombre": "Casa", "del_equipo": True, "en_lista": True}]}
c("primero las raíces de este equipo, luego las unidades; una sola atendida, sin «todo»",
  textos(bandeja.vista(r)), ["Casa", "U", "", "Pausar", "", "Cerrar el agente"])
c("  una raíz sin cifrar no lleva bloquear ni la casilla", dentro(bandeja.vista(r), "Casa"),
  ["Configurar", "Abrir en explorador", "Sincronizar ahora"])
c("  con la ventana abierta (el agente no la atiende) «Sincronizar ahora» se apaga",
  en(bandeja.vista(r), "Casa", "Sincronizar ahora").activa, False)
rotulos = [textos(bandeja.vista({"equipo": [{"id": "e", "nombre": "Casa", "estado": e,
                                             "cifrada": True}]}))[0]
           for e in (bandeja.FANTASMA, bandeja.AUSENTE, bandeja.BLOQUEANDO)]
rotulos.append(textos(bandeja.vista({"equipo": [{"id": "e", "nombre": "Casa",
                                                  "estado": bandeja.BUSCANDO}]}))[0])
c("  el rótulo de una raíz dice entre paréntesis lo que no está bien", rotulos,
  ["Casa (no responde)", "Casa (no está en su sitio)", "Casa (bloqueando…)",
   "Casa (buscándola…)"])
pausadas = {"equipo": [{"id": "e", "nombre": "Casa", "estado": bandeja.ABIERTA}],
            "unidades": [{**fila, "pausada": True, "atendida": False},
                         {"id": "e", "nombre": "Casa", "del_equipo": True,
                          "en_lista": True, "pausada": True}]}
c("  pausadas desde su ventana (#64), raíz y unidad lo dicen en su desplegable",
  textos(bandeja.vista(pausadas))[:2], ["Casa (en pausa)", "U (en pausa)"])
ausente = bandeja.vista({"equipo": [{"id": "e", "nombre": "Casa", "estado": bandeja.AUSENTE,
                                     "cifrada": True}]})
c("  sin su carpeta, todo apagado: no hay nada que hacer desde aquí",
  [e.activa for e in desplegable(ausente, "Casa (no está en su sitio)").hijos if e.texto
   and e.marcada is None], [False, False, False, False])
dos = bandeja.vista({"pedir_al_iniciar": False, "equipo": [
    {"id": "a", "nombre": "A", "estado": bandeja.BLOQUEADA, "cifrada": True},
    {"id": "b", "nombre": "B", "estado": bandeja.BLOQUEADA, "cifrada": True}]})
c("con dos raíces cifradas la casilla (que vale para las dos) sale fuera, y lo dice",
  ([e.texto for e in bandeja._todas(dos.menu) if e.marcada is not None],
   "Pedir la contraseña de cada raíz cifrada al iniciar sesión" in textos(dos)),
  (["Pedir la contraseña de cada raíz cifrada al iniciar sesión"], True))
otras = bandeja.vista({"unidades": [
    {"id": "v", "nombre": "Vieja", "vieja": "0.4.3", "en_lista": False},
    {"id": "c", "nombre": "Otra", "cambiada": True, "preguntando": True,
     "emblema": {"marca": "verde"}}]})
c("una unidad vieja y una con el código cambiado: lo dicen, sin abrir nada",
  [(e.texto, [(h.texto, h.activa) for h in e.hijos]) for e in otras.menu if e.hijos],
  [("Vieja (por actualizar)", [("Actualízala para que la atienda", False)]),
   ("Otra (código cambiado)", [("Atender con su código nuevo…", True)])])
c("  las dos con la marca de prdrive, aunque el resumen trajera otra cosa",
  [e.emblema for e in otras.menu if e.hijos], [bandeja.MARCA, bandeja.MARCA])
vieja_raiz = bandeja.vista({"equipo": [{"id": "e", "nombre": "Casa", "estado": bandeja.ABIERTA}],
                            "unidades": [{"id": "e", "nombre": "Casa", "del_equipo": True,
                                          "vieja": "0.4.3", "en_lista": False,
                                          "atendida": True,
                                          "emblema": {"marca": "morado"}}]})
raiz = next(e for e in vieja_raiz.menu if e.hijos)
c("una raíz del equipo con un programa antiguo lo dice, como una unidad",
  raiz.texto, "Casa (por actualizar)")
c("  y no deja abrir nada suyo: Configurar, Abrir y Sincronizar, apagados",
  [(h.texto, h.activa) for h in raiz.hijos],
  [("Configurar", False), ("Abrir en explorador", False), ("Sincronizar ahora", False),
   ("Actualízala para que la atienda", False)])
c("  con la marca de prdrive y no su icono", raiz.emblema, bandeja.MARCA)
cifrada_vieja = bandeja.vista({"equipo": [{"id": "e", "nombre": "Casa", "cifrada": True,
                                           "estado": bandeja.ABIERTA}],
                               "unidades": [{"id": "e", "nombre": "Casa", "del_equipo": True,
                                             "vieja": "", "en_lista": False}]})
hijos_cifrada = next(e for e in cifrada_vieja.menu if e.hijos).hijos
c("  una cifrada y de versión desconocida (\"\") también, y sigue pudiendo bloquearse",
  (next(e for e in cifrada_vieja.menu if e.hijos).texto,
   [h.activa for h in hijos_cifrada if h.texto == "Bloquear"]),
  ("Casa (por actualizar)", [True]))
c("el icono, de la fila de una unidad de la lista: color, .ico, y lo raro es la marca",
  [bandeja._emblema({"en_lista": True, "emblema": d}) for d in
   ({"marca": "morado"}, {"ico": "/x/i.ico"}, {"marca": "fucsia"}, {"ico": 3}, "verde", {})],
  [bandeja.Emblema(campo=icons.CAMPOS["morado"]), bandeja.Emblema(ico="/x/i.ico"),
   bandeja.MARCA, bandeja.MARCA, bandeja.MARCA, bandeja.MARCA])
c("  de una que no está en la lista, la marca", bandeja._emblema(
    {"en_lista": False, "emblema": {"marca": "morado"}}), bandeja.MARCA)

# la caché de iconos pintados no crece sin tope
cache = bandeja.CacheAcotada(3)
for i in range(5):
    cache[i] = f"icono {i}"
c("la caché acotada suelta la entrada más antigua al llenarse",
  (list(cache), len(cache)), ([2, 3, 4], 3))
cache[3] = "otro dibujo"
c("  cambiar una que ya está no saca nada", (list(cache), cache[3]), ([2, 3, 4], "otro dibujo"))
c("  y por defecto cabe `TOPE_CACHE`", bandeja.CacheAcotada().tope, bandeja.TOPE_CACHE)

# el explorador de cada sistema
EXPLORADOR_WIN = agente.IS_WIN
agente.IS_WIN = True
orden = ORDEN_EXPLORAR(Path("E:/"))
agente.IS_WIN = False
c("«Abrir en explorador»: explorer.exe con la carpeta en Windows, xdg-open en Linux",
  (Path(orden[0]).name, orden[1], ORDEN_EXPLORAR(Path("/media/x"))
   in ([shutil.which("xdg-open"), "/media/x"], None)), ("explorer.exe", str(Path("E:/")), True))
agente.IS_WIN = EXPLORADOR_WIN

# una unidad en un contenedor VeraCrypt: su autorun.inf está en la raíz física
VU = "4" * 32
FIS = tmpdir("prdrive-fisica-")
(FIS / vestibulo.MARCA).write_text(f"id={VU}\n", encoding="utf-8")
(FIS / vestibulo.CONTENEDOR).write_bytes(b"\0" * 512)
autorun(FIS, ".prdrive-icono-morado.ico")
MONTADA = F.unidad(VU, nombre="Cifrada")
autorun(MONTADA, r".prdrive\icono-verde.ico")       # dentro no lo ve el Explorador
equipo.guardar_ajustes(equipo.leer_ajustes().con_unidad(
    equipo.Unidad(VU, equipo.NADA, "Cifrada")))
ag = F.nuevo()
F.RAICES[:] = [FIS, MONTADA]
F.vueltas(ag, 3)
c("una unidad en un contenedor: el icono sale del autorun.inf de su raíz física",
  (ag.conexiones[VU].fisica, next(u for u in ag.resumen()["unidades"]
                                  if u["id"] == VU)["emblema"]), (FIS, {"marca": "morado"}))
F.RAICES[:] = []

# los iconos
negro = icons.pixeles_menu(bandeja.I_PAUSAR, 16, "#000000")
blanco = icons.pixeles_menu(bandeja.I_PAUSAR, 16, "#ffffff")
alfas = negro[3::4]
c("el glifo de un menú de Windows: 16×16 BGRA, con transparencia",
  (len(negro), min(alfas), max(alfas)), (16 * 16 * 4, 0, 255))
c("  premultiplicado: ningún canal por encima de su alfa, y blanco = alfa",
  (all(max(blanco[i:i + 3]) <= blanco[i + 3] for i in range(0, len(blanco), 4)),
   all(blanco[i] == blanco[i + 3] for i in range(0, len(blanco), 4))), (True, True))
destino = tmpdir("prdrive-iconos-")
rutas = icons.write_bandeja(destino)
c("se pintan los cinco estados", sorted(p.name for p in rutas),
  sorted(f"bandeja-{e}.ico" for e in icons.BANDEJA_ESTADOS))
cabecera = rutas[0].read_bytes()[:6]
c("  cada uno un .ico con los tamaños del icono pequeño",
  struct.unpack("<HHH", cabecera), (0, 1, len(icons.BANDEJA_TAMANOS)))
distintos = {icons.ico_bandeja(e, (16,)) for e in icons.BANDEJA_ESTADOS}
c("  distintos entre sí ya a 16 px", len(distintos), 5)
rutas[0].write_bytes(b"viejo")
icons.write_bandeja(destino, solo_si_faltan=True)
c("  al arrancar solo se pintan los que faltan", rutas[0].read_bytes(), b"viejo")
try:
    icons.capas_bandeja(16, "raro")
    c("un estado desconocido es un error", False, True)
except ValueError:
    c("un estado desconocido es un error", True, True)

# el vigía se despierta
vigia = agente.Vigia()
vigia.despertar()
t = time.monotonic()
c("despertar corta la espera, sin decir que cambiaron los montajes",
  (vigia.esperar(5.0), time.monotonic() - t < 1.0), (False, True))
vigia.despertar(montajes=True)
c("  con montajes, lo dice (hay que recorrer en racha)", vigia.esperar(5.0), True)
t = time.monotonic()
vigia.esperar(0.2)
c("  y sin nadie, espera su tiempo", time.monotonic() - t >= 0.15, True)

sys.exit(c.report())
