#!/usr/bin/env python3
"""
La bandeja del agente (fase 4): lo que enseña y lo que pide, sin Windows.

`ui/bandeja.py` es puro: del resumen del agente sale el icono, la línea del
ratón y el menú, y cada entrada lleva las peticiones del buzón que hace. Aquí
se comprueba con el resumen de un agente de verdad (unidades y raíces de
mentira, `_agente_falso`), y que lo que pide la bandeja lo atiende el agente
por el mismo camino que el buzón:

  * los cinco estados, con su orden de prioridad;
  * «Abrir», «Sincronizar ahora», «Pausar»/«Reanudar», «Cerrar el agente»;
  * «Atender…» para una unidad con «Ahora no», y NUNCA «Abrir» para una que no
    está en la lista;
  * la raíz cifrada: «Desbloquear…», «Bloquear», la casilla de
    `pedir_al_iniciar`; «Abrir» con ella cerrada desbloquea y abre al verla;
  * un desbloqueo cancelado se olvida y se vuelve a ofrecer;
  * `despertar` (vuelta de la suspensión) sondea ya los remotos sin conexión;
  * el agente le pasa la vista a la bandeja solo cuando cambia;
  * los iconos de los cinco estados, y el `Vigia` que se despierta.
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
    return [e.texto for e in vista.menu]


def entrada(vista, texto: str):
    for e in bandeja._todas(vista.menu):
        if e.texto == texto:
            return e
    return None


def elegir(ag, vista, texto: str) -> None:
    """Lo que hace la bandeja al elegir una entrada: sus peticiones, al agente."""
    for p in entrada(vista, texto).pide:
        ag.pedir(p)


class BandejaFalsa:
    def __init__(self):
        self.vistas = []

    def poner(self, vista):
        self.vistas.append(vista)


# --- sin nada --------------------------------------------------------------------
ag = F.nuevo()
ag.bandeja = falsa = BandejaFalsa()
F.vueltas(ag, 1)
v = falsa.vistas[-1]
c("sin raíces ni unidades: bien, esperando unidades", (v.icono, v.tip),
  (icons.BIEN, "prdrive — esperando unidades"))
c("  el menú: estado, sincronizar (apagado), pausar, cerrar",
  textos(v), ["Esperando unidades", "", "Sincronizar ahora", "Pausar", "",
              "Cerrar el agente"])
c("  «Sincronizar ahora» sin nada atendido está apagado",
  entrada(v, "Sincronizar ahora").activa, False)
F.vueltas(ag, 3)
c("el agente solo pasa la vista cuando cambia", len(falsa.vistas), 1)

# --- una unidad atendida ---------------------------------------------------------
UNO = "1" * 32
raiz1 = F.unidad(UNO, nombre="PRDRIVE-1")
equipo.guardar_ajustes(equipo.leer_ajustes().con_unidad(
    equipo.Unidad(UNO, equipo.DAEMON, "PRDRIVE-1")))
ag = F.nuevo()
ag.bandeja = falsa = BandejaFalsa()
F.RAICES[:] = [raiz1]
F.vueltas(ag, 3)
v = falsa.vistas[-1]
c("una pasada en marcha: sincronizando, con la unidad y la pareja",
  (v.icono, v.tip), (icons.SINCRONIZANDO, "prdrive — sincronizando PRDRIVE-1 · docs"))
c("  el menú ofrece abrirla y sincronizar",
  textos(v), ["Sincronizando PRDRIVE-1 · docs", "", "Abrir PRDRIVE-1", "",
              "Sincronizar ahora", "Pausar", "", "Cerrar el agente"])
c("  «Sincronizar ahora» pide su pasada, con todas sus parejas",
  entrada(v, "Sincronizar ahora").pide,
  ({"pide": equipo.PIDE_PASADA, "id": UNO, "parejas": []},))
F.acabar(F.pasadas()[-1], rc=0)
F.vueltas(ag, 1)
F.acabar(F.pasadas()[-1], rc=1, salida="ERROR : algo raro\n")
F.vueltas(ag, 1)
v = falsa.vistas[-1]
c("una pareja que falla: aviso, y lo dice", (v.icono, v.tip),
  (icons.AVISO, "prdrive — PRDRIVE-1: falla fotos"))

elegir(ag, v, "Pausar")
F.vueltas(ag, 1)
v = falsa.vistas[-1]
c("«Pausar» lo pide al agente, que se pausa", (ag.pausado, v.icono), (True, icons.PAUSA))
c("  y el menú ofrece «Reanudar»", entrada(v, "Reanudar") is not None, True)
c("  con el aviso debajo del estado", textos(v)[:2],
  ["En pausa", "  PRDRIVE-1: falla fotos"])
elegir(ag, v, "Reanudar")
F.vueltas(ag, 1)
c("«Reanudar» también", ag.pausado, False)

antes = len(F.LANZADOS)
elegir(ag, falsa.vistas[-1], "Abrir PRDRIVE-1")
F.vueltas(ag, 1)
lanzado = F.LANZADOS[antes:]
c("«Abrir» lanza la ventana de la unidad, aunque el agente la esté atendiendo",
  [p.args[-1] for p in lanzado], [str(raiz1 / penwatch.APP_SUBDIR / "runsync.py")])
c("  fuera de la unidad", lanzado[0].kwargs.get("cwd"), str(equipo.DIR))
F.ventana_abierta(raiz1)
antes = len(F.LANZADOS)
elegir(ag, falsa.vistas[-1], "Abrir PRDRIVE-1")
F.vueltas(ag, 1)
c("  con su ventana ya abierta no lanza otra", len(F.LANZADOS), antes)
(raiz1 / penwatch.UI_LOCK_REL).unlink()
F.pasar(agente.GRACIA)                  # la gracia tras cerrarse la ventana

# --- una unidad a la que se dijo «Ahora no» ------------------------------------------
DOS = "2" * 32
raiz2 = F.unidad(DOS, nombre="PRDRIVE-2")
F.PANTALLA[0] = False                   # sin pantalla: «Ahora no» al momento
F.RAICES[:] = [raiz1, raiz2]
F.vueltas(ag, 3)
F.PANTALLA[0] = True
v = falsa.vistas[-1]
c("una unidad con «Ahora no»: «Atender…» mientras siga conectada",
  entrada(v, "PRDRIVE-2, conectada · Atender…").pide,
  ({"pide": equipo.PIDE_ATENDER, "id": DOS},))
c("  y nunca «Abrir»: sería ejecutar su código sin el sí",
  entrada(v, "Abrir PRDRIVE-2"), None)
antes = len(F.LANZADOS)
ag.pedir({"pide": equipo.PIDE_ABRIR, "id": DOS})
F.vueltas(ag, 1)
c("  ni aunque se pida a mano", [p for p in F.LANZADOS[antes:]
                                 if str(raiz2) in " ".join(p.args)], [])
elegir(ag, v, "PRDRIVE-2, conectada · Atender…")
F.vueltas(ag, 1)
c("«Atender…» la añade a la lista", DOS in equipo.leer_ajustes().unidades, True)
v = falsa.vistas[-1]
c("con dos atendidas, «Sincronizar ahora» es un submenú: todas y cada una",
  [e.texto for e in entrada(v, "Sincronizar ahora").hijos],
  ["Todas", "", "PRDRIVE-1", "PRDRIVE-2"])
c("  «Todas» pide las dos", [p["id"] for p in entrada(v, "Todas").pide], [UNO, DOS])

elegir(ag, v, "Cerrar el agente")
F.vueltas(ag, 1)
c("«Cerrar el agente» lo termina (en cuanto acabe lo que esté en marcha)",
  ag.terminar, True)
F.RAICES[:] = []

# --- la raíz cifrada ---------------------------------------------------------------
penwatch.candidate_roots = lambda cfg: ([Path(r) for r in cfg.get("extra_roots", [])]
                                        + list(F.RAICES))
VC = "/opt/veracrypt/veracrypt"
penwatch.installed_veracrypt = lambda: VC
penwatch._con_escritorio = lambda: True
vestibulo.retenido = lambda hc: None
UID = "c" * 32
FISICA = tmpdir("prdrive-cifrado-")
HC = FISICA / vestibulo.CONTENEDOR
HC.write_bytes(b"\0" * 512)
PUNTO = tmpdir("prdrive-punto-")


def montar() -> None:
    app = PUNTO / penwatch.APP_SUBDIR
    (app / "state").mkdir(parents=True, exist_ok=True)
    (app / "PRDRIVE").write_text(f"id={UID}\ntipo=equipo\n", encoding="utf-8")
    for py in ("runsync.py", "sync.py"):
        (app / py).write_text("# de mentira\n", encoding="utf-8")
    (app / "sync_config.toml").write_text(
        '[defaults]\nremote = "nas"\n\n[[pair]]\nname = "notas"\nlocal = "notas"\n'
        'remote_path = "/R/notas"\n', encoding="utf-8")


def desmontar() -> None:
    for hijo in PUNTO.iterdir():
        shutil.rmtree(hijo) if hijo.is_dir() else hijo.unlink()


def veracrypts() -> list:
    return [p for p in F.LANZADOS if p.args and p.args[0] == VC]


equipo.guardar_ajustes(equipo.Ajustes(pedir_al_iniciar=False).con_unidad(
    equipo.Unidad(UID, equipo.DAEMON, "Mi portátil", str(PUNTO), str(HC))))
ag = F.nuevo()
ag.bandeja = falsa = BandejaFalsa()
F.vueltas(ag, 3)
v = falsa.vistas[-1]
c("la raíz cifrada cerrada: icono de bloqueada, sin alarmar",
  (v.icono, v.tip), (icons.BLOQUEADO, "prdrive — Mi portátil bloqueada"))
c("  el menú: abrir (desbloqueando antes), desbloquear y la casilla",
  textos(v), ["Mi portátil bloqueada", "", "Abrir Mi portátil…", "Desbloquear Mi portátil…",
              "Pedir la contraseña al iniciar sesión", "", "Sincronizar ahora", "Pausar",
              "", "Cerrar el agente"])
c("  «Abrir» es la entrada del doble clic", v.defecto().texto, "Abrir Mi portátil…")
casilla = entrada(v, "Pedir la contraseña al iniciar sesión")
c("  la casilla dice el ajuste y pide el contrario", (casilla.marcada, casilla.pide),
  (False, ({"pide": equipo.PIDE_AJUSTE, "clave": "pedir_al_iniciar", "valor": True},)))
elegir(ag, v, "Pedir la contraseña al iniciar sesión")
F.vueltas(ag, 1)
c("  elegida, el agente escribe el ajuste",
  (equipo.leer_ajustes().pedir_al_iniciar,
   entrada(falsa.vistas[-1], "Pedir la contraseña al iniciar sesión").marcada), (True, True))

elegir(ag, falsa.vistas[-1], "Abrir Mi portátil…")
F.vueltas(ag, 1)
c("«Abrir» con ella cerrada: VeraCrypt pide la contraseña",
  [p.args for p in veracrypts()], [[VC, str(HC), str(PUNTO)]])
v = falsa.vistas[-1]
c("  mientras, «Desbloqueando…», sin ofrecer otro desbloqueo",
  ([e.texto for e in v.menu[1:] if "esbloque" in e.texto], v.icono),
  (["Desbloqueando Mi portátil: la contraseña la pide VeraCrypt"], icons.BLOQUEADO))
ag.pedir({"pide": equipo.PIDE_DESBLOQUEAR, "id": UID})
F.vueltas(ag, 1)
c("  pedirlo otra vez no abre una segunda ventana de VeraCrypt", len(veracrypts()), 1)
montar()
antes = len(F.LANZADOS)
F.vueltas(ag, 3)
ventanas = [p for p in F.LANZADOS[antes:] if p.args[-1].endswith("runsync.py")]
c("  abierta, sale su ventana sola", [p.args[-1] for p in ventanas],
  [str(PUNTO / penwatch.APP_SUBDIR / "runsync.py")])
v = falsa.vistas[-1]
c("  y el menú ofrece bloquearla", entrada(v, "Bloquear Mi portátil").pide,
  ({"pide": equipo.PIDE_BLOQUEAR, "id": UID},))
F.acabar(F.pasadas(PUNTO)[-1], rc=0)
elegir(ag, v, "Bloquear Mi portátil")
F.vueltas(ag, 1)
c("«Bloquear» lo pide al agente, que desmonta", len(veracrypts()), 2)
c("  «Bloqueando…»", entrada(falsa.vistas[-1], "Bloqueando Mi portátil…") is not None,
  True)
desmontar()
F.vueltas(ag, 2)
c("  y vuelve a bloqueada", falsa.vistas[-1].icono, icons.BLOQUEADO)

# Un desbloqueo cancelado: VeraCrypt sale y la raíz no aparece.
elegir(ag, falsa.vistas[-1], "Desbloquear Mi portátil…")
F.vueltas(ag, 1)
veracrypts()[-1].rc = 1
F.vueltas(ag, 2)
c("un desbloqueo cancelado sigue «Desbloqueando…» un rato",
  UID in ag.desbloqueos, True)
F.pasar(agente.GRACIA_ABRIR)
F.vueltas(ag, 1)
c("  y luego se olvida y se vuelve a ofrecer",
  (UID in ag.desbloqueos, entrada(falsa.vistas[-1], "Desbloquear Mi portátil…") is not None),
  (False, True))
c("  el diario lo cuenta", any("no se ha desbloqueado" in d for d in F.DIARIO), True)

# El fantasma: se ofrece bloquear, que es la salida.
vestibulo.retenido = lambda hc: False
montar()
F.vueltas(ag, 3)
v = falsa.vistas[-1]
c("un volumen fantasma es un aviso, y el menú ofrece bloquear",
  (v.icono, entrada(v, "Bloquear Mi portátil") is not None), (icons.AVISO, True))
desmontar()
vestibulo.retenido = lambda hc: None
F.vueltas(ag, 2)

# --- despertar ---------------------------------------------------------------------
ag.entorno = agente.pl.sin_conexion(ag.entorno, UNO, "nas", F.RELOJ[0] + 3600)
ag.entorno_leido = F.RELOJ[0]
ag.pedir({"pide": equipo.PIDE_DESPERTAR})
ag._buzon(F.RELOJ[0])
c("vuelta de la suspensión: el remoto sin conexión se sondea ya",
  ag.entorno.sin_conexion[(UNO, "nas")] <= F.RELOJ[0], True)
c("  y el entorno se vuelve a leer", ag.entorno_leido, float("-inf"))

# --- lo puro, suelto -----------------------------------------------------------------
largo = bandeja.tip("x" * 300)
c("la línea del ratón cabe en szTip (127)", (len(largo), largo.endswith("…")), (127, True))
muchos = {"unidades": [{"id": "u", "nombre": "U", "fallando": ["a", "b", "c", "d", "e"]}]}
v = bandeja.vista(muchos)
c("con muchos avisos: la cuenta, tres líneas y «y N más»",
  textos(v)[:5], ["5 avisos", "  U: falla a", "  U: falla b", "  U: falla c", "  y 2 más"])
c("lo que retiene sin ser pausa (red de uso medido) usa el icono de pausa",
  bandeja.estado({"retenido": "red de uso medido", "unidades": [{}]}),
  (icons.PAUSA, "esperando: red de uso medido"))

# --- los iconos -----------------------------------------------------------------------
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

# --- el vigía se despierta -------------------------------------------------------------
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
