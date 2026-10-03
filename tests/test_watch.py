#!/usr/bin/env python3
"""El adaptador de penwatch: filas de estado y construcción de las órdenes."""

import sys

from _harness import Checks, sandbox

from common import model
from ui import watch

c = Checks("adaptador de penwatch (ui/watch.py)")

c("penwatch es importable desde la UI", watch.available(), True)

filas = watch.status_rows()
c("status devuelve filas (etiqueta, valor)",
  all(isinstance(f, tuple) and len(f) == 2 for f in filas), True)
etiquetas = [e for e, _ in filas]
for esperada in ("Directorio en el equipo", "Registro en el sistema",
                 "Vigilante", "Dispositivo ahora mismo"):
    c(f"status incluye '{esperada}'", esperada in etiquetas, True)

filas_probe = watch.probe_rows()
c("probe devuelve filas", all(len(f) == 2 for f in filas_probe), True)
c("probe mira en algún sitio", len(filas_probe) > 0, True)
c("y de cada raíz dice qué ha encontrado",
  all(nota.strip() for _, nota in filas_probe), True)

# Que ENCUENTRE el dispositivo solo se puede exigir si de verdad hay uno montado, y no lo
# hay en los dos casos que más se dan: desarrollando sobre una copia en disco, y
# con un dispositivo VeraCrypt cuyo contenedor no está montado (ahí el fichero PRDRIVE
# vive dentro del contenedor, así que la raíz del dispositivo físico no lo tiene).
if any("PRDRIVE OK" in nota for _, nota in filas_probe):
    c("probe encuentra el dispositivo montado", True, True)
else:
    print("  (saltado) no hay ningún dispositivo montado ahora mismo: "
          + "; ".join(f"{raiz} {nota}" for raiz, nota in filas_probe))

c("log_tail devuelve una lista", isinstance(watch.log_tail(), list), True)
c("is_installed responde un booleano", isinstance(watch.is_installed(), bool), True)


# construcción de órdenes
def sin_python(cmd):
    """Quita el intérprete y la ruta al script: lo que importa son los flags."""
    c("la orden apunta a penwatch.py", cmd[1], str(model.PENWATCH_PY))
    return cmd[2:]


c("instalación por defecto", sin_python(watch.install_command()),
  ["install", "--mode", "ui"])

c("modo daemon: sin parejas ni intervalo, que son del servicio",
  sin_python(watch.install_command(mode="daemon", poll=3,
                                   extra_roots=["/mnt/dispositivo"], start=False)),
  ["install", "--mode", "daemon", "--poll", "3", "--extra-root", "/mnt/dispositivo",
   "--no-start"])

c("las raíces extra se repiten como flag",
  "--extra-root" in watch.install_command(extra_roots=["/mnt/uno", "/mnt/dos"]), True)

c("los valores vacíos no ensucian la orden",
  sin_python(watch.install_command(extra_roots=[" "])),
  ["install", "--mode", "ui"])

c("desinstalar", sin_python(watch.uninstall_command()), ["uninstall"])


# qué hace este equipo al enchufar (la línea de la ventana principal)
#
# Se sustituyen el penwatch importado y el id de este dispositivo: lo que se
# prueba es la decisión, no el disco de quien ejecuta el test.
from common import fleet  # noqa: E402


class _Pw:
    """Un penwatch de mentira: su watch.json y si su copia está al día."""
    CONFIG_FILE = "watch.json"
    POLL_SECONDS = 5.0

    def __init__(self, cfg, al_dia=True):
        """Prepara el penwatch de mentira con su `watch.json`."""
        self.cfg, self.al_dia = cfg, al_dia

    def read_json(self, _ruta):
        """Devuelve el `watch.json` de mentira, sea cual sea la ruta."""
        return dict(self.cfg)

    def copia_al_dia(self):
        """Devuelve si su copia está al día."""
        return self.al_dia


real_nombre = fleet.nombre
real_penwatch, real_device_id = watch._penwatch, fleet.device_id
fleet.device_id = lambda app_dir=None: "aaaa"


def resumen_con(cfg, al_dia=True):
    """Devuelve el resumen de `watch` con ese `watch.json`."""
    watch._penwatch = lambda: _Pw(cfg, al_dia)
    return watch.resumen()


def _roto():
    """Hace que importar penwatch falle."""
    raise ImportError("sin penwatch")


try:
    watch._penwatch = _roto
    c("sin penwatch no hay nada que decir",
      (watch.resumen(), watch.linea(watch.resumen())),
      (watch.Resumen("no_disponible"), None))

    r = resumen_con({})
    c("sin watch.json: sin instalar", r.estado, "sin_instalar")
    c("y la línea lo ofrece", watch.linea(r),
      watch.Linea("En este equipo no se arranca nada al enchufarlo.", False,
                  "Configurar…"))
    c("sin instalar no hay pausa que decir", r.vigila_este, False)

    r = resumen_con({"mode": "daemon", "device_id": "bbbb"})
    c("vigila otro prdrive", r.estado, "otro_dispositivo")
    c("y eso no es vigilar este", r.vigila_este, False)

    r = resumen_con({"mode": "daemon", "device_id": "aaaa"}, al_dia=False)
    c("copia de otra versión: desfasado", (r.estado, r.vigila_este),
      ("desfasado", True))
    c("y la línea va en ámbar", watch.linea(r).aviso, True)

    for modo, hace in (("ui", "abre esta ventana"), ("daemon", "arranca el servicio"),
                       ("sync", "una pasada de estas parejas")):
        r = resumen_con({"mode": modo, "device_id": "aaaa"})
        c(f"instalado en modo {modo}", (r.estado, r.modo), ("instalado", modo))
        c(f"y la línea dice qué hará ({modo})", watch.linea(r).texto,
          f"Al enchufarlo en este equipo: {hace}.")

    r = resumen_con({"mode": "sync"})
    c("sin id en watch.json vale para cualquier prdrive, también este",
      r.estado, "instalado")

    r = resumen_con({"mode": "daemon", "device_id": "aaaa", "pairs": ["x"],
                     "interval": 10, "poll_seconds": 3})
    c("installed_options ya no devuelve parejas ni intervalo",
      sorted(watch.installed_options()), ["device_id", "extra_roots", "mode", "poll"])

    # con el agente residente instalado en este equipo
    from common import equipo  # noqa: E402
    codigo = equipo.DIR / "agente" / "0.4.0"
    codigo.mkdir(parents=True)
    (codigo / "agente.py").write_text("", encoding="utf-8")
    from common import store  # noqa: E402
    store.write_json(equipo.instalacion_json(), {"codigo": str(codigo)})
    r = resumen_con({"mode": "ui", "device_id": "aaaa"})
    c("con el agente instalado, manda él aunque quede un watch.json",
      r.estado, "agente_nueva")
    PARADO = " Ahora no está en marcha: arranca al iniciar sesión."
    c("  sin este dispositivo en su lista: lo dice, y se le puede decir que sí",
      watch.linea(r), watch.Linea("El agente de este equipo no lo tiene en su lista: "
                                  "pregunta al enchufarlo, o dile aquí qué hacer con "
                                  "él." + PARADO, True, "Atender…"))
    c("  y no vigila este (todavía)", r.vigila_este, False)
    c("  sin agente vivo: ni vivo ni en pausa", (r.vivo, r.pausado), (False, False))
    for modo, dice in (("daemon", "lo sincroniza en segundo plano"),
                       ("ui", "abre esta ventana al enchufarlo"),
                       ("sync", "hace una pasada al enchufarlo")):
        equipo.guardar_ajustes(equipo.Ajustes().con_unidad(equipo.Unidad("aaaa", modo)))
        r = watch.resumen()
        c(f"agente, modo {modo}: lo dice", dice in watch.linea(r).texto, True)
        c(f"  y cuenta como vigilado (la ventana dice que está en pausa)",
          r.vigila_este, True)
    c("  el botón abre «Qué hace el agente»", watch.linea(r).boton, "Cambiar…")
    c("  parado: en ámbar, y lo dice", (watch.linea(r).aviso,
                                         watch.linea(r).texto.endswith(PARADO)),
      (True, True))
    c("  su servicio no es el agente si no está vivo", r.servicio_del_agente, False)

    # Vivo, y luego en pausa: su lock con este pid, su estado.json.
    import os  # noqa: E402
    equipo.guardar_ajustes(equipo.Ajustes().con_unidad(equipo.Unidad("aaaa", "daemon")))
    store.write_json(equipo.lock_json(), {"pid": os.getpid(), "host": equipo.HOST})
    r = watch.resumen()
    c("agente vivo en daemon: su servicio es el agente",
      (r.vivo, r.pausado, r.servicio_del_agente), (True, False, True))
    c("  línea normal, sin ámbar", (watch.linea(r).aviso, watch.linea(r).texto),
      (False, "El agente de este equipo lo sincroniza en segundo plano."))
    store.write_json(equipo.estado_json(), {"pausado": True})
    r = watch.resumen()
    c("  en pausa (su «Pausar»): lo dice", (r.pausado, "en pausa para todo"
                                            in watch.linea(r).texto), (True, True))
    equipo.estado_json().unlink()

    # El botón del servicio del pie (#64): con el agente como servicio,
    # «Pausar» / «Reanudar» en vez de «Iniciar servicio».
    r = watch.resumen()
    c("agente vivo en daemon: el pie ofrece «Pausar», no «Iniciar servicio»",
      watch.boton_servicio(r), watch.BotonServicio("Pausar", watch.PAUSAR))
    c("  y debajo de la línea dice qué cambia «Pausar»", watch.pausa(r), watch.PAUSA_AGENTE)
    c("  la consola, sin ese botón, la frase de siempre", watch.pausa(r, ventana=False),
      watch.PAUSA)
    equipo.guardar_ajustes(equipo.Ajustes().con_unidad(
        equipo.Unidad("aaaa", "daemon", pausada=True)))
    r = watch.resumen()
    c("pausada desde su ventana: se lee de agente.json", (r.pausada, r.pausado),
      (True, False))
    c("  el pie ofrece «Reanudar»", watch.boton_servicio(r),
      watch.BotonServicio("Reanudar", watch.REANUDAR))
    c("  la línea lo dice, sin ámbar", (watch.linea(r).aviso, watch.linea(r).texto),
      (False, "El agente de este equipo lo sincroniza en segundo plano. Está en pausa "
              "desde esta ventana: no lo sincroniza hasta que pulses «Reanudar»."))
    c("  y no dice «en pausa mientras esta ventana esté abierta»", watch.pausa(r), None)
    for modo in ("sync", "nada"):
        equipo.guardar_ajustes(equipo.Ajustes().con_unidad(
            equipo.Unidad("aaaa", modo, pausada=True)))
        c(f"  en modo {modo} sigue ofreciendo «Reanudar»: la pausa no se esconde",
          watch.boton_servicio(watch.resumen()).accion, watch.REANUDAR)
    equipo.guardar_ajustes(equipo.Ajustes().con_unidad(equipo.Unidad("aaaa", "daemon")))
    store.write_json(equipo.estado_json(), {"pausado": True})
    r = watch.resumen()
    c("con la pausa de todo de la bandeja: «Reanudar todo», que lo dice",
      watch.boton_servicio(r), watch.BotonServicio("Reanudar todo", watch.SEGUIR))
    c("  y tampoco la frase de la ventana", watch.pausa(r), None)
    equipo.estado_json().unlink()
    for res, por in ((watch.Resumen("agente", "daemon", False), "con el agente parado"),
                     (watch.Resumen("agente", "sync", True), "en modo sync"),
                     (watch.Resumen("agente", "ui", True), "en modo ui"),
                     (watch.Resumen("agente_nueva", "", True), "fuera de su lista"),
                     (watch.Resumen("agente", "daemon", False, False, True),
                      "pausada con el agente parado"),
                     (watch.Resumen("instalado", "daemon"), "con penwatch"),
                     (watch.Resumen("sin_instalar"), "sin nada")):
        c(f"  {por}: «Iniciar servicio», como siempre", watch.boton_servicio(res),
          watch.BotonServicio("Iniciar servicio", watch.INICIAR))

    # Lo que pide cada botón, y a qué buzón.
    from common import model  # noqa: E402
    with sandbox():
        buzon_raiz = model.STATE_DIR / equipo.BUZON_SERVICIO
        equipo.recoger()
        c("«Pausar» deja pausar_raiz en el buzón de ESTA raíz",
          (watch.pedir_servicio(watch.PAUSAR),
           [p["pide"] for p in equipo.recoger(buzon_raiz)], equipo.recoger()),
          (True, [equipo.PIDE_PAUSAR_RAIZ], []))
        c("«Reanudar», reanudar en el mismo",
          (watch.pedir_servicio(watch.REANUDAR),
           [p["pide"] for p in equipo.recoger(buzon_raiz)]),
          (True, [equipo.PIDE_REANUDAR]))
        c("«Reanudar todo», sigue en el del agente",
          (watch.pedir_servicio(watch.SEGUIR), [p["pide"] for p in equipo.recoger()],
           equipo.recoger(buzon_raiz)), (True, [equipo.PIDE_SIGUE], []))
        c("  y nada más", (watch.pedir_servicio(watch.INICIAR), equipo.recoger(),
                           equipo.recoger(buzon_raiz)), (False, [], []))
    viva = watch.Resumen("agente", "daemon", True)
    c("tras_servicio(): la línea enseña lo pedido",
      (watch.tras_servicio(viva, watch.PAUSAR).pausada,
       watch.tras_servicio(viva._replace(pausada=True), watch.REANUDAR).pausada,
       watch.tras_servicio(viva._replace(pausado=True), watch.SEGUIR).pausado),
      (True, False, False))
    equipo.lock_json().unlink()

    # Lo que se le pide desde la ventana, por su buzón.
    equipo.recoger()
    fleet.nombre = lambda state_dir=None: "PRDRIVE-7"
    c("pedir_modo deja PIDE_MODO para ESTE dispositivo, con su nombre",
      (watch.pedir_modo("sync"), [(p["pide"], p["id"], p["modo"], p["nombre"])
                                  for p in equipo.recoger()]),
      (True, [(equipo.PIDE_MODO, "aaaa", "sync", "PRDRIVE-7")]))
    c("  un modo que no existe, no", (watch.pedir_modo("todo"), equipo.recoger()),
      (False, []))
    c("pedido(): la línea enseña lo pedido, que el agente aplica enseguida",
      watch.pedido(watch.Resumen("agente_nueva", "", True), "daemon"),
      watch.Resumen("agente", "daemon", True))
    c("  en la raíz del equipo, sigue siendo la raíz",
      watch.pedido(watch.Resumen("agente_raiz", "daemon", True), "nada").estado,
      "agente_raiz")
    c("modos: la raíz del equipo no se enchufa",
      (watch.modos_agente(watch.Resumen("agente_raiz", "daemon")),
       watch.modos_agente(watch.Resumen("agente", "ui"))),
      (("daemon", "nada"), ("daemon", "sync", "ui", "nada")))
    c("pedir_al_iniciar: None si no es la raíz cifrada de este equipo",
      watch.pedir_al_iniciar(), None)
    equipo.guardar_ajustes(equipo.Ajustes(pedir_al_iniciar=False).con_unidad(
        equipo.Unidad("aaaa", "daemon", ruta="P:\\", contenedor="C:\\x.hc")))
    c("  y el de agente.json si lo es", watch.pedir_al_iniciar(), False)
    c("pedir_ajuste lo pide al agente, no lo escribe",
      (watch.pedir_ajuste("pedir_al_iniciar", True), equipo.leer_ajustes().pedir_al_iniciar,
       [(p["clave"], p["valor"]) for p in equipo.recoger()]),
      (True, False, [("pedir_al_iniciar", True)]))

    equipo.guardar_ajustes(equipo.Ajustes().con_unidad(equipo.Unidad("aaaa", "nada")))
    r = watch.resumen()
    c("agente, modo nada: no hace nada, y no vigila", (watch.linea(r).texto, r.vigila_este),
      ("El agente de este equipo no hace nada con él." + PARADO, False))
    store.write_json(equipo.instalacion_json(), {"codigo": str(equipo.DIR / "no-existe")})
    c("un instalacion.json sin código no es un agente",
      resumen_con({"mode": "ui", "device_id": "aaaa"}).estado, "instalado")
finally:
    watch._penwatch, fleet.device_id = real_penwatch, real_device_id
    fleet.nombre = real_nombre

sys.exit(c.report())
