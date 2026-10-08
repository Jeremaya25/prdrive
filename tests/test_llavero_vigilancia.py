#!/usr/bin/env python3
"""Quién atiende el llavero y cuándo toca una pasada (`common/llavero.py`, `runsync.py`).

Con un reloj de mentira y sin rclone: las pasadas se apuntan en vez de
lanzarse, y lo que corre en el equipo (los procesos, el registro del servicio)
se sustituye. Lo que se sujeta:
- «Pendiente de subir» sale del listado `path1` de bisync, con el formato que
  escribe rclone v1.75.1, sin otro registro.
- Las reglas: una ráfaga de guardados es una pasada tras la calma, entre dos hay
  separación, lo de otro dispositivo llega cada 5 min con KeePassXC abierto, y
  sin red la espera crece.
- El vigilante vive lo que KeePassXC, sube lo pendiente al cerrarse, cede al
  servicio y no deja su registro detrás.
- El agente atiende el llavero como una pareja vigilada, aunque no se elija.
"""

import os
import sys
from pathlib import Path

from _harness import Checks, sandbox

import runsync
from common import bisync, keepassxc, llavero, model, store

c = Checks("vigilancia del llavero")

DEF = {"remote": "nas", "device_remote": "disp", "catalog_path": "/prdrive-catalog/remote.toml"}
RAW = {"defaults": DEF, "pair": [{"name": "notas", "local": "sync-data/notas",
                                  "remote_path": "/R/notas"}],
       "keychain": {"base": "personal.kdbx"}}
P = llavero.POLITICA


def pareja() -> model.Pair:
    """La pareja del llavero del config de prueba (con las rutas del sandbox)."""
    return model.parse_config(RAW).pareja_llavero


def escribir_listado(par: model.Pair, ficheros: dict[str, Path]) -> None:
    """Deja el listado `path1` de una pasada buena, como lo escribe rclone."""
    par.workdir.mkdir(parents=True, exist_ok=True)
    lineas = ["# bisync listing v1 from 2026-10-05T06:44:33.246486494+0000"]
    for nombre, ruta in ficheros.items():
        st = ruta.stat()
        segundos, ns = divmod(st.st_mtime_ns, 1_000_000_000)
        import time as _t
        hora = _t.strftime("%Y-%m-%dT%H:%M:%S", _t.gmtime(segundos)) + f".{ns:09d}+0000"
        lineas.append(f'- {st.st_size:8d} - - {hora} "{nombre}"')
    (par.workdir / f"{bisync.expected_prefix(par)}{bisync.PATH1_SUFFIX}").write_text(
        "\n".join(lineas) + "\n", encoding="utf-8")


# pendiente de subir, contra el listado de bisync
with sandbox() as root:
    par = pareja()
    carpeta = root / ".keychain"
    carpeta.mkdir()
    c("sin bases no hay nada pendiente", llavero.pendiente(par), False)
    base = carpeta / "personal.kdbx"
    base.write_bytes(b"x" * 10)
    c("con una base y sin pasada buena, está pendiente", llavero.pendiente(par), True)
    escribir_listado(par, {"personal.kdbx": base})
    c("con la base como dice el listado, no", llavero.pendiente(par), False)
    c("el listado se lee con los nanosegundos de rclone",
      llavero.listado_local(par)["personal.kdbx"], (10, base.stat().st_mtime_ns))
    # 2 s: NTFS guarda la hora en unidades de 100 ns, y exFAT en 10 ms o 2 s.
    os.utime(base, ns=(base.stat().st_atime_ns, base.stat().st_mtime_ns + 2_000_000_000))
    c("un guardado que solo mueve la hora, pendiente", llavero.pendiente(par), True)
    escribir_listado(par, {"personal.kdbx": base})
    base.write_bytes(b"y" * 11)
    c("uno que cambia el tamaño, también", llavero.pendiente(par), True)
    escribir_listado(par, {"personal.kdbx": base})
    (carpeta / "otra.kdbx").write_bytes(b"z")
    c("y una base que el listado no tiene", llavero.pendiente(par), True)

# las reglas, con un reloj de mentira
v = llavero.Vigilancia()
v.observar(("a",), 0.0)
c("la primera foto no es un cambio", v.motivo(0.0, False), None)
v.observar(("b",), 10.0)
c("un cambio espera la calma", v.motivo(10.0 + P.calma - 1, False), None)
v.observar(("c",), 20.0)
c("  cada guardado la mueve", v.motivo(10.0 + P.calma + 1, False), None)
c("  y pasada la calma, toca", v.motivo(20.0 + P.calma, False), "cambios")
v.empieza_pasada(40.0)
v.acaba_pasada(("c",), 45.0, sin_subir=False, bien=True)
c("tras la pasada no queda nada", v.motivo(46.0, False), None)
v.observar(("d",), 50.0)
c("otro cambio pronto espera la separación", v.motivo(50.0 + P.calma, False), None)
c("  y luego toca", v.motivo(40.0 + P.separacion, False), "cambios")

v = llavero.Vigilancia()
v.observar(("a",), 0.0, sin_subir=True)
c("lo que dejó otra sesión sin subir cuenta como cambio", v.motivo(P.calma, False), "cambios")

v = llavero.Vigilancia()
v.observar(("a",), 0.0)
c("con KeePassXC abierto, lo de otro dispositivo se trae ya", v.motivo(0.0, True), "remoto")
v.empieza_pasada(0.0)
v.acaba_pasada(("a",), 5.0, sin_subir=False, bien=True)
c("  y luego cada 5 min", (v.motivo(llavero.REMOTO_ABIERTO - 1, True),
                           v.motivo(llavero.REMOTO_ABIERTO, True)), (None, "remoto"))
c("  pero con KeePassXC cerrado, no", v.motivo(10 * llavero.REMOTO_ABIERTO, False), None)

v = llavero.Vigilancia()
v.observar(("a",), 0.0)
v.observar(("b",), 1.0)
for i in range(1, 6):
    v.empieza_pasada(1000.0 * i)
    v.acaba_pasada(("b",), 1000.0 * i + 1, sin_subir=True, bien=False)
c("sin red, la espera entre pasadas crece", v.separacion, llavero.TOPE_REINTENTO)
c("  hasta un tope", v.motivo(5000.0 + llavero.TOPE_REINTENTO - 1, True), None)
v.empieza_pasada(9000.0)
v.acaba_pasada(("b",), 9001.0, sin_subir=False, bien=True)
c("  y una pasada buena la devuelve a la de siempre", v.separacion, P.separacion)
v.observar(("c",), 9002.0)
v.empieza_pasada(9003.0)
v.observar(("d",), 9004.0)
v.acaba_pasada(("e",), 9005.0, sin_subir=True, bien=True)
c("lo guardado durante una pasada no se pierde", v.cambio, 9005.0)

# quién atiende: el servicio de la raíz, si está vivo aquí
with sandbox():
    c("sin registro del servicio, no lo atiende nadie", llavero.atiende_el_servicio(), False)
    store.write_json(model.daemon_lock(), {"pid": os.getpid(), "host": llavero.equipo()})
    c("con el servicio (o el agente) vivo aquí, es suyo", llavero.atiende_el_servicio(), True)
    store.write_json(model.daemon_lock(), {"pid": os.getpid(), "host": "otro-equipo"})
    c("  el de otro equipo no cuenta", llavero.atiende_el_servicio(), False)
    agente = {"pid": os.getpid(), "host": llavero.equipo(), "agente": True}
    store.write_json(model.daemon_lock(), {**agente, "pairs": ["docs", model.LLAVERO]})
    c("  el agente que lo trae entre sus parejas, también", llavero.atiende_el_servicio(), True)
    store.write_json(model.daemon_lock(), {**agente, "pairs": ["docs"]})
    c("  uno de antes del llavero, que no lo trae, no lo atiende: se queda el vigilante",
      llavero.atiende_el_servicio(), False)
    store.write_json(model.daemon_lock(), {**agente, "pairs": "docs keychain"})
    c("  unas parejas que no son una lista no cuentan", llavero.atiende_el_servicio(), False)

# KeePassXC abierto: solo cuenta el programa, no el proxy del navegador
with sandbox() as root:
    app = root / ".prdrive"
    (app / "bin" / "x64").mkdir(parents=True)
    (app / "bin" / "x64" / "rclone.exe").write_bytes(b"MZ")
    real_procesos = store.procesos_desde
    store.procesos_desde = lambda carpeta: {7: str(carpeta / "keepassxc-proxy.exe")}
    c("con solo el proxy vivo, KeePassXC no está abierto", llavero.keepassxc_abierto(app), False)
    store.procesos_desde = lambda carpeta: {8: str(carpeta / "KeePassXC.exe")}
    c("  con KeePassXC, sí", llavero.keepassxc_abierto(app), True)
    store.procesos_desde = real_procesos


# el vigilante, con un reloj de mentira
class Reloj:
    """Un `time` de mentira: `sleep` adelanta la hora sin esperar."""

    def __init__(self):
        self.t = 1000.0

    def monotonic(self):
        return self.t

    def sleep(self, segundos):
        self.t += segundos


diario: list[str] = []
runsync.dlog = diario.append
runsync.pen_present = lambda: True
real_time, real_correr, real_abierto = runsync.time, runsync.run_pair_quiet, \
    llavero.keepassxc_abierto
try:
    with sandbox() as root:
        reloj = Reloj()
        runsync.time = reloj
        (root / "sync_config.toml").write_text(
            '[defaults]\nremote = "nas"\n\n[[pair]]\nname = "notas"\nlocal = "sync-data/notas"\n'
            'remote_path = "/R/notas"\n\n[keychain]\nbase = "personal.kdbx"\n', encoding="utf-8")
        carpeta = root / ".keychain"
        carpeta.mkdir()
        base = carpeta / "personal.kdbx"
        base.write_bytes(b"x")
        escribir_listado(model.load_config().pareja_llavero, {"personal.kdbx": base})
        pasadas: list[float] = []

        def correr(nombre):
            """Apunta la pasada y deja el listado como lo dejaría una buena."""
            pasadas.append(reloj.t)
            escribir_listado(model.load_config().pareja_llavero, {"personal.kdbx": base})
            return 0, "OK"
        runsync.run_pair_quiet = correr

        # KeePassXC abierto 10 min; a los 2 min, una ráfaga de guardados.
        cierre = reloj.t + 600

        guardados: list[float] = []
        registros: list[dict] = []

        def abierto(app_dir=None):
            registros.append(store.read_json(llavero.registro_vigilante()))
            if 1120 <= reloj.t <= 1135:
                base.write_bytes(b"y" * int(reloj.t))   # guardados seguidos
                guardados.append(reloj.t)
            return reloj.t < cierre
        llavero.keepassxc_abierto = abierto
        runsync.vigilar_llavero()
        c("el vigilante trae lo de otro dispositivo al empezar", pasadas[0], 1000.0)
        cambios = [t for t in pasadas if 1120 < t < 1300]
        c("la ráfaga de guardados es una sola pasada, tras la calma",
          len(cambios), 1)
        c("  no antes de la calma desde el último guardado",
          (len(guardados) > 1, cambios[0] >= guardados[-1] + P.calma), (True, True))
        c("con KeePassXC abierto, lo de otro dispositivo 5 min después de la última",
          any(abs(t - (cambios[0] + llavero.REMOTO_ABIERTO)) <= P.sondeo for t in pasadas), True)
        c.contains("se detiene al cerrarse KeePassXC", diario[-1], "KeePassXC cerrado")
        c("y no deja su registro", llavero.registro_vigilante().exists(), False)
        arranque = store.arranque_del_sistema()     # baila unos ms entre llamadas
        c("mientras corre, su registro apunta en qué arranque del sistema está",
          abs((registros[0].get("arranque") or 0) - (arranque or 0)) < 5, True)

        # Al cerrar KeePassXC con algo sin subir, lo sube antes de irse.
        pasadas.clear()
        runsync.run_pair_quiet = lambda n: (pasadas.append(reloj.t), (1, "sin red"))[1]
        base.write_bytes(b"cambio de ultima hora")
        cierre = reloj.t + 1
        runsync.vigilar_llavero()
        c("al cerrarse KeePassXC con algo pendiente, lo intenta subir", len(pasadas) >= 1, True)

        # Sin que KeePassXC llegue a verse, se rinde a los 30 s.
        pasadas.clear()
        llavero.keepassxc_abierto = lambda app_dir=None: False
        inicio = reloj.t
        escribir_listado(model.load_config().pareja_llavero, {"personal.kdbx": base})
        runsync.vigilar_llavero()
        c("sin ver KeePassXC, se rinde tras la espera de arranque",
          reloj.t - inicio >= runsync.ARRANQUE_KEEPASSXC, True)

        # Con el servicio de la raíz vivo, el llavero es suyo y el vigilante sobra.
        llavero.keepassxc_abierto = lambda app_dir=None: True
        store.write_json(model.daemon_lock(), {"pid": os.getpid(), "host": llavero.equipo()})
        pasadas.clear()
        runsync.vigilar_llavero()
        c.contains("con el servicio vivo, el vigilante se va", diario[-1], "servicio de la raíz")
        c("  sin hacer pasadas", pasadas, [])
        c("  y no se lanza otro", llavero.lanzar_vigilante(), None)
        model.daemon_lock().unlink()

        # Dos a la vez no: el registro lo tiene el primero.
        store.write_json(llavero.registro_vigilante(),
                         {"pid": os.getpid(), "host": runsync.HOST})
        c("con un vigilante vivo no arranca otro", (runsync.vigilar_llavero(),
                                                   llavero.vigilante_vivo()), (0, True))
        c("  ni se lanza", llavero.lanzar_vigilante(), None)
        llavero.registro_vigilante().unlink()

        # «Expulsar» le pide que pare; una parada vieja, de antes de arrancar, no.
        llavero.parada_vigilante().touch()
        diario.clear()
        inicio = reloj.t

        def abierto_hasta_expulsar(app_dir=None):
            if reloj.t > inicio + 30:
                llavero.parada_vigilante().touch()
            return True
        llavero.keepassxc_abierto = abierto_hasta_expulsar
        runsync.vigilar_llavero()
        c("una parada vieja no cuenta, y la de «Expulsar» sí",
          ("parada pedida" in diario[-1], reloj.t - inicio > 30), (True, True))
        c("  y no se queda detrás", llavero.parada_vigilante().exists(), False)

        # La unidad se va sin expulsar: en Linux su KeePassXC sigue abierto
        # (corre extraído en el equipo), y el vigilante le pide que se cierre.
        real_huerfano = keepassxc.cerrar_huerfano
        huerfanos: list[int] = []
        keepassxc.cerrar_huerfano = lambda app_dir=None: huerfanos.append(1) or 1
        runsync.pen_present = lambda: False
        try:
            runsync.vigilar_llavero()
        finally:
            runsync.pen_present = lambda: True
            keepassxc.cerrar_huerfano = real_huerfano
        if os.name != "nt":
            c("si la unidad se va, en Linux le pide a KeePassXC que se cierre",
              (huerfanos, diario[-1].endswith("se le pide a KeePassXC que se cierre")),
              ([1], True))
        else:
            c("si la unidad se va, en Windows no hace falta: KeePassXC muere con ella",
              (huerfanos, "dispositivo no conectado" in diario[-1]), ([], True))
finally:
    runsync.time, runsync.run_pair_quiet = real_time, real_correr
    llavero.keepassxc_abierto = real_abierto

# el agente atiende el llavero como una pareja vigilada, aunque no se elija
import agente  # noqa: E402

with sandbox() as root:
    raiz = root / "raiz"
    (raiz / ".prdrive" / "state").mkdir(parents=True)
    (raiz / ".prdrive" / "sync_config.toml").write_text(
        '[defaults]\nremote = "nas"\ncatalog_remote = "cat"\n\n'
        '[daemon]\npairs = ["notas"]\n\n'
        '[[pair]]\nname = "notas"\nlocal = "sync-data/notas"\nremote_path = "/R/notas"\n\n'
        '[keychain]\nbase = "personal.kdbx"\n', encoding="utf-8")
    servicio = agente.leer_servicio(raiz)
    llave = [p for p in servicio.parejas if p.nombre == model.LLAVERO]
    c("el agente atiende el llavero", len(llave), 1)
    c("  vigilado, en .keychain/", (llave[0].vigila, servicio.locales.get(model.LLAVERO)),
      (True, ".keychain"))
    c("  con el remote del catálogo, para sondearlo", llave[0].remoto, "cat")
    (raiz / ".prdrive" / "sync_config.toml").write_text(
        '[defaults]\nremote = "nas"\n\n[[pair]]\nname = "notas"\nlocal = "sync-data/notas"\n'
        'remote_path = "/R/notas"\n', encoding="utf-8")
    c("sin [keychain], no", [p.nombre for p in agente.leer_servicio(raiz).parejas], ["notas"])

sys.exit(c.report())
