#!/usr/bin/env python3
"""Bloquear sola al bloquear la sesión, suspender o apagar Windows (#178).

Con un sistema de mentira (`_agente_falso`) y una bandeja de Windows de
mentira: lo que oiría la de verdad llega como lo manda ella
(`Agente.pedir({"pide": PIDE_SESION, …})`), el VeraCrypt instalado es una
ruta que no existe y lo que se lanza se apunta. Las unidades de VeraCrypt son
una raíz física con su marca de vestíbulo y su `.hc` al lado más el volumen de
dentro; la raíz del equipo cifrada, una carpeta con su contenedor. Se comprueba:
- `agente.json` guarda los tres ajustes por unidad, solo encendidos, y uno de
  antes se lee con todos apagados. Valen en una unidad y en una raíz del equipo
  cifrada, no en una sin cifrar.
- `PIDE_AJUSTE_UNIDAD` los acepta clave por clave; lo que no vale, al diario.
- `resumen()` lleva `bloquear_solo` solo si la raíz es bloqueable, hay
  VeraCrypt instalado y bandeja de Windows, y la del bloqueo de la sesión solo
  si la bandeja la oye.
- `bloqueo`/`suspension` bloquean solo las raíces con su ajuste, también en
  pausa; `/silent` con el VeraCrypt instalado, nunca `/force` ni el portable;
  el «Bloquear» de una persona sigue sin `/silent`.
- `PIDE_SESION` por el fichero `agente.pide` se rechaza.
- Con una pasada en marcha no se lanza VeraCrypt; con la ventana abierta se
  abandona enseguida. `desbloqueo` cancela lo que no se ha lanzado y dice, una
  vez por raíz y nunca con la sesión bloqueada, lo que no se pudo y por qué.
  Sin oír la sesión, el aviso sale al volver de la suspensión.
- `al_salir` tiene solo lo que se puede bloquear al cerrar la sesión, y
  `lanzar_al_salir()` lo lanza sin esperar ni tocar el estado del agente.
"""

import os
import shutil
import sys
from pathlib import Path

from _harness import Checks, tmpdir

import _agente_falso as F
import agente
import penwatch
from common import equipo, store, vestibulo

c = Checks("agente: bloquear sola al bloquear la sesión, suspender o apagar")
F.preparar()
penwatch.candidate_roots = lambda cfg: ([Path(r) for r in cfg.get("extra_roots", [])]
                                        + list(F.RAICES))
VC = "C:/Archivos de programa/VeraCrypt/VeraCrypt.exe"
INSTALADO: list = [VC]
penwatch.installed_veracrypt = lambda: INSTALADO[0]
agente.veracrypt_propio = lambda: "C:/agente/veracrypt/VeraCrypt-x64.exe"
RETENIDO: list = [True]             # lo que contesta vestibulo.retenido
# «Otra» (`FIS2`) sigue abierta todo el test: su `.hc` siempre retenido. Con un
# solo valor para todos, al soltar el de la cifrada la otra pasaría por un
# fantasma (`Agente._fantasmas_extraibles()`, #41).
vestibulo.retenido = lambda hc: True if Path(hc).parent == FIS2 else RETENIDO[0]
agente.IS_WIN = True                # la bandeja que oye la sesión es la de Windows

SESION, SUSPENDER, APAGAR = equipo.AJUSTES_BLOQUEAR_SOLO
BLOQUEO, DESBLOQUEO, SUSPENSION = (equipo.EVENTO_BLOQUEO, equipo.EVENTO_DESBLOQUEO,
                                   equipo.EVENTO_SUSPENSION)


class BandejaFalsa:
    """La bandeja de Windows, en lo que el agente le mira: si oye la sesión."""

    puesta = True

    def __init__(self, oye: bool = True) -> None:
        """Prepara una bandeja que oye la sesión o no."""
        self.oye_sesion = oye

    def poner(self, vista) -> None:
        """No pinta nada."""


# --- agente.json
def ida_y_vuelta(u: equipo.Unidad) -> equipo.Unidad:
    """Devuelve la unidad tras escribirla en el dict de `agente.json` y leerla."""
    return equipo.desde_dict(equipo.a_dict(equipo.Ajustes(unidades={u.id: u}))).unidades[u.id]


def escrita(u: equipo.Unidad) -> dict:
    """Devuelve cómo queda esa unidad en el dict de `agente.json`."""
    return equipo.a_dict(equipo.Ajustes(unidades={u.id: u}))["unidades"][u.id]


A, Q = "a" * 32, "q" * 32
c("de fábrica, los tres apagados", [getattr(equipo.Unidad(A), k)
                                    for k in equipo.AJUSTES_BLOQUEAR_SOLO], [False] * 3)
c("  y un agente.json de antes se lee igual: todos apagados",
  [getattr(equipo.desde_dict({"unidades": {A: {"modo": "daemon"}}}).unidades[A], k)
   for k in equipo.AJUSTES_BLOQUEAR_SOLO], [False] * 3)
c("encendidos van y vuelven",
  ida_y_vuelta(equipo.Unidad(A, **{k: True for k in equipo.AJUSTES_BLOQUEAR_SOLO})),
  equipo.Unidad(A, **{k: True for k in equipo.AJUSTES_BLOQUEAR_SOLO}))
c("  solo se escriben encendidos", (escrita(equipo.Unidad(A)),
                                   escrita(equipo.Unidad(A, bloquear_al_suspender=True))),
  ({"modo": equipo.MODO_AL_ATENDER, "nombre": ""},
   {"modo": equipo.MODO_AL_ATENDER, "nombre": "", SUSPENDER: True}))
c("  lo que no es verdadero cuenta como apagado",
  [equipo.desde_dict({"unidades": {A: {SESION: v}}}).unidades[A].bloquear_al_bloquear_sesion
   for v in ("sí", 1, None, [], "true")], [False] * 5)
c("  en una raíz del equipo cifrada valen; en una sin cifrar, no",
  (equipo.desde_dict({"unidades": {Q: {"ruta": "P:\\", "contenedor": "C:\\x.hc",
                                       SUSPENDER: True}}}).unidades[Q].bloquear_al_suspender,
   equipo.desde_dict({"unidades": {Q: {"ruta": "/casa", SUSPENDER: True}}}
                     ).unidades[Q].bloquear_al_suspender), (True, False))
c("son ajustes de unidad, los tres", equipo.AJUSTES_DE_UNIDAD[1:],
  equipo.AJUSTES_BLOQUEAR_SOLO)
c("cada evento tiene su ajuste", equipo.BLOQUEAR_AL,
  {BLOQUEO: SESION, SUSPENSION: SUSPENDER, equipo.EVENTO_FIN: APAGAR})
c("PIDE_SESION no es del buzón de una raíz", equipo.PIDE_SESION in equipo.PIDE_SERVICIO,
  False)


# --- las órdenes de VeraCrypt
def orden(unidad, **kw):
    """Devuelve `orden_bloquear()`."""
    return agente.orden_bloquear(unidad, **kw)


RAIZ_P = equipo.Unidad(Q, equipo.DAEMON, "Mi portátil", "P:\\", "C:\\PRDRIVE.hc")
c("desatendido: /silent con el VeraCrypt instalado, sin /force",
  orden(RAIZ_P, desatendido=True), [VC, "/dismount", "P", "/silent", "/quit"])
c("  el de una unidad, por la letra de su volumen de dentro",
  orden(equipo.Unidad(A), desatendido=True, raiz=Path("E:\\")),
  [VC, "/dismount", "E", "/silent", "/quit"])
c("pedido por una persona, sin /silent: VeraCrypt pregunta si forzar",
  orden(RAIZ_P), [VC, "/dismount", "P", "/quit"])
INSTALADO[0] = None
c("sin VeraCrypt instalado, desatendido no hay orden: nunca el portable (pide UAC)",
  (orden(RAIZ_P, desatendido=True), orden(RAIZ_P)[0]),
  (None, "C:/agente/veracrypt/VeraCrypt-x64.exe"))
INSTALADO[0] = VC
agente.IS_WIN = False
c("en Linux, desatendido sin preguntar nada; una unidad, nada (la cierra su script)",
  (orden(RAIZ_P, desatendido=True)[1:], orden(equipo.Unidad(A), desatendido=True,
                                               raiz=Path("/media/x"))),
  (["--text", "--non-interactive", "-d", "C:\\PRDRIVE.hc"], None))
agente.IS_WIN = True


# --- una unidad con vestíbulo
def vestibulo_de(uid: str, nombre: str):
    """Devuelve una unidad de VeraCrypt de mentira: su raíz física y el volumen de dentro."""
    fisica = tmpdir("prdrive-fisica-")
    (fisica / penwatch.VESTIBULE_MARKER).write_text(f"id={uid}\n", encoding="utf-8")
    (fisica / penwatch.CONTAINER_FILE).write_bytes(b"")
    return fisica, F.unidad(uid, parejas=("docs",), nombre=nombre)


VU, OTRA = "9" * 32, "8" * 32
FIS, DENTRO = vestibulo_de(VU, "Cifrada")
FIS2, DENTRO2 = vestibulo_de(OTRA, "Otra")


def veracrypts() -> list:
    """Los VeraCrypt lanzados."""
    return [p for p in F.LANZADOS if p.args and "VeraCrypt" in p.args[0]]


def acabar_pasadas(ag) -> None:
    """Acaba bien las pasadas que se vayan lanzando, hasta que no quede ninguna en marcha."""
    for _ in range(10):
        vivas = [p for p in F.pasadas() if p.rc is None]
        if not vivas and ag.pasada is None:
            return
        for p in vivas:
            F.acabar(p)
        F.vueltas(ag, 1)


def desmontar(raiz: Path) -> None:
    """Lo que hace VeraCrypt al cerrar el volumen de dentro: deja de estar."""
    (raiz / penwatch.APP_SUBDIR).rename(raiz / "fuera")


def montar_de_nuevo(raiz: Path) -> None:
    """Vuelve a abrir el volumen de dentro."""
    (raiz / "fuera").rename(raiz / penwatch.APP_SUBDIR)


def sesion(ag, evento: str, vueltas: int = 1) -> None:
    """Lo que pide la bandeja al oír ese evento de la sesión, y unas vueltas."""
    ag.pedir({"pide": equipo.PIDE_SESION, "evento": evento})
    F.vueltas(ag, vueltas, recorrer=False)


def abiertas(oye: bool = True, **mas) -> "agente.Agente":
    """Devuelve un agente que atiende las dos unidades abiertas, sin pasadas en marcha.

    Args:
        oye: Si la bandeja oye la sesión.
        **mas: Los ajustes de la primera en `agente.json`.
    """
    equipo.guardar_ajustes(equipo.Ajustes()
                           .con_unidad(equipo.Unidad(VU, equipo.DAEMON, "Cifrada", **mas))
                           .con_unidad(equipo.Unidad(OTRA, equipo.DAEMON, "Otra")))
    for d in (DENTRO, DENTRO2):
        for f in (d / penwatch.UI_LOCK_REL, d / penwatch.DAEMON_LOCK_REL):
            f.unlink(missing_ok=True)
    F.LANZADOS.clear()
    F.AVISOS.clear()
    F.DIARIO.clear()
    F.ABIERTOS.clear()
    F.RAICES[:] = [FIS, DENTRO, FIS2, DENTRO2]
    RETENIDO[0] = True
    ag = F.nuevo()
    ag.bandeja = BandejaFalsa(oye)
    F.vueltas(ag, 3)
    acabar_pasadas(ag)
    return ag


def fila(ag, uid: str) -> dict:
    """La fila de esa raíz en `resumen()`."""
    return next(u for u in ag.resumen()["unidades"] if u["id"] == uid)


ag = abiertas(**{SESION: True, SUSPENDER: True})
c("las dos unidades se atienden abiertas, y no se pide abrir nada",
  (sorted(ag.conexiones), F.ABIERTOS, ag.pasada), (sorted([OTRA, VU]), [], None))
c("resumen(): las tres casillas, con lo que tiene cada una",
  (fila(ag, VU).get("bloquear_solo"), fila(ag, OTRA).get("bloquear_solo")),
  ({SESION: True, SUSPENDER: True, APAGAR: False},
   {SESION: False, SUSPENDER: False, APAGAR: False}))
ag.bandeja.oye_sesion = False
c("  si la bandeja no oye la sesión, sin la del bloqueo de la sesión",
  list(fila(ag, VU)["bloquear_solo"]), [SUSPENDER, APAGAR])
ag.bandeja = None
c("  sin bandeja, ninguna", "bloquear_solo" in fila(ag, VU), False)
ag.bandeja = BandejaFalsa()
INSTALADO[0] = None
ag.veracrypt_mirado = -float("inf")
c("  sin VeraCrypt instalado, ninguna", "bloquear_solo" in fila(ag, VU), False)
INSTALADO[0] = VC
F.pasar(agente.MIRAR_EMBLEMA)
c("  y vuelven al instalarlo (se mira cada poco, no en cada vuelta)",
  "bloquear_solo" in fila(ag, VU), True)
agente.IS_WIN = False
c("  fuera de Windows, ninguna", "bloquear_solo" in fila(ag, VU), False)
agente.IS_WIN = True
ag.conexiones[VU].cambiada = True
c("  ni con su código cambiado", "bloquear_solo" in fila(ag, VU), False)
ag.conexiones[VU].cambiada = False

# PIDE_SESION por el fichero: nadie más que la bandeja dice cómo está la sesión.
equipo.pedir({"pide": equipo.PIDE_SESION, "evento": BLOQUEO})
F.vueltas(ag, 1, recorrer=False)
c("un evento de la sesión por agente.pide se rechaza en el diario y no bloquea nada",
  (veracrypts(), ag.bloqueos, any("solo lo dice la bandeja" in d for d in F.DIARIO)),
  ([], {}, True))
sesion(ag, "otra cosa")
c("  uno que no se conoce, tampoco hace nada", (veracrypts(), ag.bloqueos), ([], {}))

ag.pausado = True                   # la pausa de todo no detiene la seguridad
sesion(ag, BLOQUEO)
c("bloquear la sesión: VeraCrypt en la misma vuelta, solo para la que lo tiene puesto",
  [p.args for p in veracrypts()],
  [[VC, "/dismount", str(DENTRO)[:1], "/silent", "/quit"]])
c("  también en pausa, y suelta su lock antes", (ag.pausado, F.lock(DENTRO).get("pid")),
  (True, None))
c("  nunca /force", any("/force" in p.args for p in veracrypts()), False)
c("  sin aviso ninguno", F.AVISOS, [])
F.RAICES[:] = [FIS, FIS2, DENTRO2]
desmontar(DENTRO)
RETENIDO[0] = False
veracrypts()[0].rc = 0
F.vueltas(ag, 2)
c("cerrada de verdad: bloqueada, desconectada y la otra sigue",
  (ag.bloqueos, VU in ag.conexiones, OTRA in ag.conexiones), ({}, False, True))
c("  y no se vuelve a pedir su contraseña: queda como ya pedida",
  (ag.vestibulos.get(VU), F.ABIERTOS), (str(FIS), []))
sesion(ag, DESBLOQUEO)
c("al desbloquear la sesión no sale nada: se bloqueó bien", F.AVISOS, [])
montar_de_nuevo(DENTRO)

# Sin el ajuste, nada nuevo.
ag = abiertas()
sesion(ag, BLOQUEO)
sesion(ag, SUSPENSION)
c("sin el ajuste, ni el bloqueo de la sesión ni la suspensión hacen nada",
  (veracrypts(), ag.bloqueos, sorted(ag.conexiones)), ([], {}, sorted([OTRA, VU])))
sesion(ag, DESBLOQUEO)

# Con una pasada en marcha: espera; si la persona vuelve antes, se cancela y se dice.
ag = abiertas(**{SESION: True})
ag.urgentes.append((VU, "docs"))
F.vueltas(ag, 1)
c("(una pasada de la unidad en marcha)", len([p for p in F.pasadas(DENTRO) if p.rc is None]),
  1)
sesion(ag, BLOQUEO, vueltas=3)
c("con una pasada en marcha no se lanza VeraCrypt: rclone se quedaría sin su lado",
  (veracrypts(), VU in ag.bloqueos), ([], True))
c("  ni se avisa con la sesión bloqueada", F.AVISOS, [])
sesion(ag, DESBLOQUEO)
c("al desbloquear se cancela y se dice una vez, con el motivo",
  (VU in ag.bloqueos, F.AVISOS),
  (False, [("Cifrada: no la he bloqueado",
            "Al bloquear la sesión: había una sincronización en marcha.")]))
acabar_pasadas(ag)
F.vueltas(ag, 2)
c("  y acabada la pasada, ni se bloquea ni se repite el aviso",
  (veracrypts(), len(F.AVISOS), VU in ag.conexiones), ([], 1, True))

# Con su ventana abierta: no se espera a que se cierre.
ag = abiertas(**{SESION: True})
F.ventana_abierta(DENTRO)
sesion(ag, BLOQUEO)
c("con su ventana abierta se abandona enseguida, sin lanzar nada ni avisar",
  (veracrypts(), VU in ag.bloqueos, F.AVISOS), ([], False, []))
F.vueltas(ag, 3)
sesion(ag, DESBLOQUEO)
c("  al volver, el aviso: su ventana estaba abierta",
  F.AVISOS, [("Cifrada: no la he bloqueado",
              "Al bloquear la sesión: su ventana estaba abierta.")])
sesion(ag, BLOQUEO)
sesion(ag, DESBLOQUEO)
c("  y otra vez solo si vuelve a pasar", len(F.AVISOS), 2)
(DENTRO / penwatch.UI_LOCK_REL).unlink()

# VeraCrypt no la cierra (un programa con un fichero abierto dentro): no fuerza.
ag = abiertas(**{SESION: True})
sesion(ag, BLOQUEO)
veracrypts()[0].rc = 1
F.vueltas(ag, 4, cada=agente.GRACIA_DESMONTAJE)
c("si VeraCrypt sale y sigue montada, no se fuerza ni se avisa con la sesión bloqueada",
  (len(veracrypts()), VU in ag.bloqueos, F.AVISOS), (1, False, []))
sesion(ag, DESBLOQUEO)
c("  al volver: un programa tenía un fichero abierto dentro",
  F.AVISOS, [("Cifrada: no la he bloqueado",
              "Al bloquear la sesión: un programa tenía un fichero abierto dentro.")])
c("  y se sigue atendiendo", VU in ag.conexiones, True)

# Ya lanzado, desbloquear la sesión no lo cancela.
ag = abiertas(**{SESION: True})
sesion(ag, BLOQUEO)
sesion(ag, DESBLOQUEO)
c("con VeraCrypt ya lanzado, desbloquear la sesión no lo cancela",
  (len(veracrypts()), VU in ag.bloqueos), (1, True))

# Suspender sin oír la sesión: el aviso sale al volver de la suspensión.
ag = abiertas(oye=False, **{SUSPENDER: True})
F.ventana_abierta(DENTRO)
sesion(ag, SUSPENSION)
c("suspender con la ventana abierta: no se bloquea y no se avisa todavía",
  (veracrypts(), F.AVISOS), ([], []))
sesion(ag, BLOQUEO)                 # sin `oye_sesion` no llegaría; con él, lo retiene
ag.pedir({"pide": equipo.PIDE_DESPERTAR})
F.vueltas(ag, 1, recorrer=False)
c("  al volver de la suspensión con la sesión bloqueada, todavía no", F.AVISOS, [])
sesion(ag, DESBLOQUEO)
c("  al desbloquearla, sí: al suspender el equipo",
  F.AVISOS, [("Cifrada: no la he bloqueado",
              "Al suspender el equipo: su ventana estaba abierta.")])
ag = abiertas(oye=False, **{SUSPENDER: True})
F.ventana_abierta(DENTRO)
sesion(ag, SUSPENSION)
ag.pedir({"pide": equipo.PIDE_DESPERTAR})
F.vueltas(ag, 1, recorrer=False)
c("  sin oír la sesión, sale al volver de la suspensión",
  [t for t, _ in F.AVISOS], ["Cifrada: no la he bloqueado"])
(DENTRO / penwatch.UI_LOCK_REL).unlink()

# Sin VeraCrypt instalado (el ajuste se puso antes): se dice, y nunca con el portable.
ag = abiertas(**{SESION: True})
INSTALADO[0] = None
sesion(ag, BLOQUEO)
c("sin VeraCrypt instalado no se lanza nada, ni el portable del agente",
  (veracrypts(), VU in ag.bloqueos), ([], False))
sesion(ag, DESBLOQUEO)
c("  y se dice al volver", F.AVISOS, [("Cifrada: no la he bloqueado",
                                       "Al bloquear la sesión: no hay VeraCrypt instalado "
                                       "en este equipo.")])
INSTALADO[0] = VC

# Una unidad en modo nada o fuera de Windows no se toca.
ag = abiertas(**{SESION: True})
agente.IS_WIN = False
sesion(ag, BLOQUEO)
c("fuera de Windows, una unidad con vestíbulo no se bloquea sola", veracrypts(), [])
agente.IS_WIN = True
sesion(ag, DESBLOQUEO)

# --- el ajuste por el buzón
RAIZ_PLANA = tmpdir("prdrive-raiz-plana-")
PUNTO = tmpdir("prdrive-punto-")
HC = tmpdir("prdrive-cifrado-") / vestibulo.CONTENEDOR
HC.write_bytes(b"\0" * 64)
PLANA, CIFRADA = "p" * 32, "c" * 32


def en_disco(uid: str, clave: str):
    """El valor de ese ajuste en `agente.json`."""
    return getattr(equipo.leer_ajustes().unidades[uid], clave)


equipo.guardar_ajustes(equipo.Ajustes()
                       .con_unidad(equipo.Unidad(VU, equipo.DAEMON, "Cifrada"))
                       .con_unidad(equipo.Unidad(PLANA, equipo.DAEMON, "Casa", str(RAIZ_PLANA)))
                       .con_unidad(equipo.Unidad(CIFRADA, equipo.DAEMON, "Mi portátil",
                                                 str(PUNTO), str(HC))))
F.RAICES[:] = []
ag = F.nuevo()
F.DIARIO.clear()


def pedir_ajuste(uid, clave, valor) -> None:
    """Deja un ajuste de unidad en el buzón del agente y da una vuelta."""
    equipo.pedir({"pide": equipo.PIDE_AJUSTE_UNIDAD, "id": uid, "clave": clave, "valor": valor})
    F.vueltas(ag, 1, recorrer=False)


pedir_ajuste(VU, SESION, True)
pedir_ajuste(CIFRADA, SUSPENDER, True)
c("por PIDE_AJUSTE_UNIDAD: en una unidad y en una raíz del equipo cifrada",
  (en_disco(VU, SESION), en_disco(CIFRADA, SUSPENDER), en_disco(VU, SUSPENDER)),
  (True, True, False))
c("  y lo dice el diario", F.DIARIO, ["Cifrada: ajuste bloquear_al_bloquear_sesion = True",
                                      "Mi portátil: ajuste bloquear_al_suspender = True"])
pedir_ajuste(VU, SESION, None)
c("  None es apagado, y la clave se va de agente.json",
  (en_disco(VU, SESION), SESION in store.read_json(equipo.ajustes_json())["unidades"][VU]),
  (False, False))
antes = store.read_json(equipo.ajustes_json())
F.DIARIO.clear()
rechazadas = [(PLANA, SUSPENDER, True), (CIFRADA, "pedir_al_conectar", False),
              (VU, SESION, "sí"), (VU, SESION, 1), (VU, "bloquear_al_salir", True),
              ("z" * 32, SESION, True)]
for uid, clave, valor in rechazadas:
    pedir_ajuste(uid, clave, valor)
c("lo que no vale no toca nada: una raíz sin cifrar, pedir_al_conectar en una raíz, un "
  "valor que no es sí/no, una clave que no existe, una unidad que no está",
  store.read_json(equipo.ajustes_json()), antes)
c("  y cada una deja su línea en el diario", len(F.DIARIO), len(rechazadas))


# --- la raíz del equipo cifrada
def montar() -> None:
    """Lo que hace VeraCrypt al abrirla: aparece la raíz en su punto, con el `.hc` retenido."""
    RETENIDO[0] = True
    app = PUNTO / penwatch.APP_SUBDIR
    (app / "state").mkdir(parents=True, exist_ok=True)
    store.write_json(app / "state" / "fleet.json", {"nombre": "Mi portátil"})
    (app / "PRDRIVE").write_text(f"id={CIFRADA}\ntipo=equipo\n", encoding="utf-8")
    (app / "VERSION").write_text(F.VERSION + "\n", encoding="utf-8")
    for py in ("runsync.py", "sync.py"):
        (app / py).write_text("# de mentira\n", encoding="utf-8")
    (app / "sync_config.toml").write_text(
        '[defaults]\nremote = "nas"\n\n[[pair]]\nname = "notas"\nlocal = "notas"\n'
        'remote_path = "/R/notas"\n', encoding="utf-8")


def cerrar_raiz() -> None:
    """Lo que hace VeraCrypt al cerrarla: vacía el punto y suelta el `.hc`.

    Las dos cosas: en Windows la carpeta temporal empieza por una letra
    (`C:\\…`), así que `Unidad.letra` la lee y `bloqueada()` mira el `.hc`.
    """
    for hijo in list(PUNTO.iterdir()):
        shutil.rmtree(hijo)
    RETENIDO[0] = False


LETRA = equipo.leer_ajustes().unidades[CIFRADA].letra or str(PUNTO)[:1]
"""Lo que se le pasa a `/dismount`: su letra fija (en Windows, la de la carpeta temporal)."""

montar()
ag = F.nuevo()
ag.bandeja = BandejaFalsa()
F.LANZADOS.clear()
F.vueltas(ag, 3)
acabar_pasadas(ag)
c("la raíz cifrada, abierta, ofrece las casillas", (CIFRADA in ag.conexiones,
                                                    fila(ag, CIFRADA).get("bloquear_solo")),
  (True, {SESION: False, SUSPENDER: True, APAGAR: False}))
sesion(ag, BLOQUEO)
c("bloquear la sesión no la toca: no lo tiene puesto", veracrypts(), [])
sesion(ag, DESBLOQUEO)
sesion(ag, SUSPENSION)
c("suspender, sí: desatendido, con su letra o su carpeta",
  [p.args for p in veracrypts()], [[VC, "/dismount", LETRA, "/silent", "/quit"]])
c("  y la raíz sale «bloqueándose»", fila(ag, CIFRADA)["motivo"], "bloqueándose")
for p in veracrypts():
    p.rc = 0
cerrar_raiz()
F.vueltas(ag, 2)
c("  cerrada de verdad: bloqueada", (ag.bloqueos, CIFRADA in ag.conexiones), ({}, False))
montar()
F.vueltas(ag, 3)
acabar_pasadas(ag)
F.LANZADOS.clear()
ag.pedir({"pide": equipo.PIDE_BLOQUEAR, "id": CIFRADA})
F.vueltas(ag, 1, recorrer=False)
c("el «Bloquear» de una persona sigue sin /silent", [p.args for p in veracrypts()],
  [[VC, "/dismount", LETRA, "/quit"]])
cerrar_raiz()
veracrypts()[0].rc = 0
F.vueltas(ag, 2)
ag.pedir({"pide": equipo.PIDE_DESPERTAR})
F.vueltas(ag, 1, recorrer=False)

# --- al cerrar la sesión o apagar
ag = abiertas(**{APAGAR: True})
c("al_salir: el desmontaje desatendido de la que lo tiene puesto, ya preparado",
  ag.al_salir, ([VC, "/dismount", str(DENTRO)[:1], "/silent", "/quit"],))
F.LANZADOS.clear()
c("lanzar_al_salir() lo lanza y no espera", (ag.lanzar_al_salir(),
                                             [p.args for p in veracrypts()]),
  (1, [list(ag.al_salir[0])]))
c("  sin tocar el estado del agente: ni bloqueos, ni conexiones, ni su lock",
  (ag.bloqueos, VU in ag.conexiones, F.lock(DENTRO).get("pid")), ({}, True, os.getpid()))
c("  fuera de la raíz y sin consola", veracrypts()[0].kwargs.get("cwd"), str(equipo.DIR))
ag.urgentes.append((VU, "docs"))
F.vueltas(ag, 1)
c("con una pasada suya en marcha, no se prepara nada", ag.al_salir, ())
acabar_pasadas(ag)
c("  acabada, vuelve", len(ag.al_salir), 1)
F.ventana_abierta(DENTRO)
F.vueltas(ag, 1)
c("con su ventana abierta, tampoco", ag.al_salir, ())
(DENTRO / penwatch.UI_LOCK_REL).unlink()
F.vueltas(ag, 1)
ag.keepassxc.add(VU)
ag.keepassxc_mirado = float("inf")          # que no lo vuelva a mirar en la vuelta
F.vueltas(ag, 1)
c("ni con su KeePassXC abierto", ag.al_salir, ())
ag.keepassxc.discard(VU)
ag.bandeja = None
F.vueltas(ag, 1)
c("sin la bandeja de Windows (quien oye el fin de la sesión), nada", ag.al_salir, ())
F.LANZADOS.clear()
c("  y lanzar_al_salir() no lanza nada", (ag.lanzar_al_salir(), veracrypts()), (0, []))
ag = abiertas()
c("sin el ajuste, nada preparado", ag.al_salir, ())

sys.exit(c.report())
