#!/usr/bin/env python3
"""
watch.py — Lo que la UI necesita de penwatch.py. Sin Tkinter.

La dependencia va en un solo sentido: la UI conoce a penwatch, penwatch no conoce
a nadie. Eso es deliberado y no se puede invertir — `penwatch.py` se copia al
equipo y tiene que seguir funcionando con el dispositivo desconectado, así que no puede
importar nada que viva en el dispositivo.

Para leer (estado, detección) se importa penwatch y se usan sus funciones, que ya
devuelven filas. Para instalar y desinstalar se lanza como proceso: son órdenes
que escriben en el equipo y cuentan lo que hacen por su salida, y esa salida se
enseña en la misma ventana que se usa para sync.py.

El vigilante solo decide QUÉ se hace al enchufar. Las parejas y el intervalo son
los del servicio, que viven en el dispositivo y se eligen en la ventana
principal: el servicio es uno, se arranque a mano o al enchufar.
"""

from __future__ import annotations

import sys
from typing import NamedTuple

from common import fleet, model

# En el orden en que se ofrecen: de lo que menos hace solo a lo que más.
MODES = ("ui", "daemon", "sync")
MODE_LABELS = {
    "ui": "Abrir la ventana",
    "daemon": "Arrancar el servicio",
    "sync": "Una pasada y nada más",
}
# Qué parejas y cada cuánto no se dice aquí: lo dice una sola vez la pantalla,
# debajo de las tres opciones (son los del servicio, para las dos que sincronizan).
MODE_HELP = {
    "ui": "abre la ventana de runsync y decides tú (por defecto)",
    "daemon": "sincroniza cada N minutos mientras siga puesto",
    "sync": "sincroniza una vez, en silencio, y se cierra",
}

# Lo que se hace al enchufar, dicho en la línea de la ventana principal.
_AL_ENCHUFAR = {
    "ui": "abre esta ventana",
    "daemon": "arranca el servicio",
    "sync": "una pasada de estas parejas",
}


class Resumen(NamedTuple):
    """Qué hace el arranque automático de este equipo con ESTE dispositivo.

    `estado`, de más a menos grave para quien lee la línea:
      no_disponible     penwatch no se puede importar: no se dice nada
      sin_instalar      en este equipo no hay vigilante
      otro_dispositivo  lo hay, pero vigila otro prdrive (un equipo tiene uno)
      desfasado         vigila este, con una copia de otra versión
      instalado         vigila este, y `modo` es lo que hará
      agente_nueva      el agente residente (`agente.py`) está instalado y este
                        dispositivo no está en su lista: preguntará al enchufarlo
      agente            el agente lo tiene en su lista, y `modo` es lo que hace
                        (`common.equipo.MODOS`, que añade «nada»)
      agente_raiz       no es una unidad: es la raíz de este equipo, y el agente
                        la atiende con ese `modo`

    Con agente, además: `vivo` (hay un proceso suyo en marcha en este equipo)
    y `pausado` (su «Pausar», que para todo), de su `estado.json`."""
    estado: str
    modo: str = ""
    vivo: bool = False
    pausado: bool = False

    @property
    def vigila_este(self) -> bool:
        """Hay un vigilante en este equipo que atiende a este dispositivo."""
        return (self.estado in ("desfasado", "instalado")
                or (self.estado in ("agente", "agente_raiz") and self.modo != "nada"))

    @property
    def es_agente(self) -> bool:
        return self.estado in ("agente", "agente_raiz", "agente_nueva")

    @property
    def servicio_del_agente(self) -> bool:
        """¿El servicio periódico de esta raíz es el agente, y está en marcha?
        Entonces «Iniciar servicio» no arranca otro: se lo pide a él
        (`reanudar`). Solo en modo `daemon`: en `sync` hace una pasada por
        conexión, y quien pide un servicio cada N minutos no pide eso."""
        return (self.estado in ("agente", "agente_raiz") and self.modo == "daemon"
                and self.vivo)


class Linea(NamedTuple):
    """La línea de la ventana principal: el texto, si va en ámbar, y el botón."""
    texto: str
    aviso: bool
    boton: str


def _penwatch():
    """penwatch se importa aquí dentro y no arriba.

    Es un script hermano, no un módulo del paquete: si por lo que sea no se
    pudiera importar, eso no debe impedir que se abra la ventana principal."""
    import penwatch
    return penwatch


def available() -> bool:
    try:
        _penwatch()
        return True
    except Exception:
        return False


def status_rows() -> list[tuple[str, str]]:
    return _penwatch().status_rows()


def probe_rows() -> list[tuple[str, str]]:
    return _penwatch().probe_rows()


def log_tail(lines: int = 10) -> list[str]:
    return _penwatch().log_tail(lines)


def log_path() -> str:
    """Dónde vive el diario, para poder enseñarlo junto a lo que se lee de él.
    Está en el equipo, nunca en el dispositivo, y decirlo es media explicación."""
    try:
        return str(_penwatch().LOG_FILE)
    except Exception:
        return ""


def is_installed() -> bool:
    pw = _penwatch()
    return bool(pw.read_json(pw.CONFIG_FILE))


def installed_options() -> dict:
    """Con qué se instaló, para precargar el formulario. Vacío si no lo está.

    Sin parejas ni intervalo aunque un watch.json de antes los traiga: ya no son
    del equipo, y reinstalar es precisamente lo que los quita."""
    pw = _penwatch()
    cfg = pw.read_json(pw.CONFIG_FILE)
    if not cfg:
        return {}
    return {
        "mode": cfg.get("mode", "ui"),
        "poll": cfg.get("poll_seconds", pw.POLL_SECONDS),
        "extra_roots": list(cfg.get("extra_roots") or []),
        "device_id": str(cfg.get("device_id") or ""),
    }


def resumen() -> Resumen:
    """Qué hace el arranque automático de este equipo con este dispositivo.

    Solo lee ficheros —watch.json, las dos copias de penwatch, el PRDRIVE—: nada
    de `schtasks` ni `systemctl`, porque lo pregunta la ventana al pintarse y la
    primera pintura tiene que ser instantánea (la misma regla que
    `update.pending()`). Si la tarea está registrada o no lo cuenta la pantalla
    del vigilante, que sí puede tardar. Nunca lanza.

    Con el agente residente instalado en este equipo, manda él: lo sustituye a
    penwatch, que el instalador desinstala al ponerlo.

    De módulo para que los tests la sustituyan."""
    agente = _agente()
    if agente is not None:
        return agente
    try:
        pw = _penwatch()
        cfg = pw.read_json(pw.CONFIG_FILE)
    except Exception:                                   # noqa: BLE001
        return Resumen("no_disponible")
    if not cfg:
        return Resumen("sin_instalar")
    suyo = str(cfg.get("device_id") or "")
    # Sin id en watch.json el vigilante reconoce cualquier prdrive por la mera
    # presencia del PRDRIVE, así que también este.
    if suyo and suyo != fleet.device_id():
        return Resumen("otro_dispositivo")
    try:
        al_dia = pw.copia_al_dia()
    except Exception:                                   # noqa: BLE001
        al_dia = True
    modo = str(cfg.get("mode") or "ui")
    return Resumen("instalado" if al_dia else "desfasado", modo)


def _agente() -> Resumen | None:
    """Lo que el agente residente hace con este dispositivo, si hay agente.

    Solo lee su configuración (`common/equipo.py`): ni el agente ni la ventana
    se escriben el uno al otro aquí. Nunca lanza."""
    try:
        from common import equipo
        if not equipo.instalado():
            return None
        unidad = equipo.leer_ajustes().unidades.get(fleet.device_id())
        vivo = equipo.agente_vivo() is not None
        pausado = vivo and equipo.leer_estado().get("pausado") is True
    except Exception:                                   # noqa: BLE001
        return None
    if unidad is None:
        return Resumen("agente_nueva", "", vivo, pausado)
    return Resumen("agente_raiz" if unidad.es_raiz else "agente", unidad.modo,
                   vivo, pausado)


# Lo que hace el agente al enchufarlo, dicho en la misma línea.
_AGENTE_HACE = {
    "ui": "el agente de este equipo abre esta ventana al enchufarlo.",
    "daemon": "el agente de este equipo lo sincroniza en segundo plano.",
    "sync": "el agente de este equipo hace una pasada al enchufarlo.",
    "nada": "el agente de este equipo no hace nada con él.",
}

# Lo que se le puede pedir al agente que haga con esta raíz (`common.equipo.MODOS`),
# en el orden en que se ofrece. La raíz del equipo no se enchufa: abrir su
# ventana o una pasada «al enchufarla» no quieren decir nada.
MODOS_AGENTE = ("daemon", "sync", "ui", "nada")
MODOS_AGENTE_RAIZ = ("daemon", "nada")
ETIQUETA_AGENTE = {
    "daemon": "Sincronizarlo en segundo plano",
    "sync": "Una pasada al enchufarlo",
    "ui": "Abrir esta ventana al enchufarlo",
    "nada": "Nada",
}
AYUDA_AGENTE = {
    "daemon": "con las parejas y el intervalo del servicio (por defecto)",
    "sync": "una vez por conexión, en silencio",
    "ui": "y decides tú desde aquí",
    "nada": "solo lo que pidas tú desde aquí",
}
AYUDA_AGENTE_RAIZ = {
    "daemon": "con las parejas y el intervalo del servicio",
    "nada": "solo lo que pidas tú desde aquí o desde la bandeja",
}


def modos_agente(res: Resumen) -> tuple[str, ...]:
    """Los modos que se ofrecen para esta raíz en «Qué hace el agente»."""
    return MODOS_AGENTE_RAIZ if res.estado == "agente_raiz" else MODOS_AGENTE


def ayuda_agente(res: Resumen, modo: str) -> str:
    return (AYUDA_AGENTE_RAIZ if res.estado == "agente_raiz" else AYUDA_AGENTE).get(modo, "")


def pedir_al_agente(peticion: dict) -> bool:
    """Deja una petición en el buzón del agente (`agente.pide`): la ventana no
    escribe `agente.json`, que es del agente y puede ser de otra versión que
    este código. De módulo para que los tests la sustituyan."""
    from common import equipo
    return equipo.pedir(peticion)


def pedir_modo(modo: str) -> bool:
    """Que el agente haga `modo` con ESTA raíz. Si no la tenía en su lista,
    entra con él: es la persona diciendo que sí desde la ventana de la propia
    unidad, lo mismo que «Atender» en la pregunta o en la bandeja."""
    from common import equipo
    if modo not in equipo.MODOS:
        return False
    return pedir_al_agente({"pide": equipo.PIDE_MODO, "id": fleet.device_id(),
                            "modo": modo, "nombre": fleet.nombre()})


def pedido(res: Resumen, modo: str) -> Resumen:
    """Cómo queda la línea tras pedirle `modo` al agente. El agente lo aplica
    en unos segundos, y releer `agente.json` ahora mismo diría lo de antes:
    la ventana enseña lo pedido, que es lo que va a haber."""
    return res._replace(estado="agente_raiz" if res.estado == "agente_raiz" else "agente",
                        modo=modo)


def pedir_al_iniciar() -> bool | None:
    """El `pedir_al_iniciar` del agente, si esta raíz es la cifrada de este
    equipo (lo único a lo que afecta), o None. Solo lee `agente.json`."""
    try:
        from common import equipo
        unidad = equipo.leer_ajustes().unidades.get(fleet.device_id())
        if unidad is None or not unidad.cifrada:
            return None
        return equipo.leer_ajustes().pedir_al_iniciar
    except Exception:                                   # noqa: BLE001
        return None


def pedir_ajuste(clave: str, valor) -> bool:
    from common import equipo
    return pedir_al_agente({"pide": equipo.PIDE_AJUSTE, "clave": clave, "valor": valor})


def _agente_linea(res: Resumen) -> Linea:
    """La línea del agente: qué hace con esta raíz, si está en marcha y si está
    en pausa. El botón abre «Qué hace el agente» (`tk_watch.open_agente`)."""
    if res.estado == "agente_nueva":
        texto = ("El agente de este equipo no lo tiene en su lista: pregunta al "
                 "enchufarlo, o dile aquí qué hacer con él.")
        boton = "Atender…"
    elif res.estado == "agente_raiz":
        texto = ("Es la carpeta de este equipo: "
                 + ("el agente no hace nada con ella." if res.modo == "nada" else
                    "la sincroniza el agente, en segundo plano."))
        boton = "Cambiar…"
    else:
        hace = _AGENTE_HACE.get(res.modo, res.modo)
        texto, boton = hace[0].upper() + hace[1:], "Cambiar…"
    if not res.vivo:
        return Linea(texto + " Ahora no está en marcha: arranca al iniciar sesión.",
                     True, boton)
    if res.pausado:
        texto += (" Está en pausa para todo: se reanuda desde su icono de la bandeja "
                  "o con «agente.py sigue».")
    return Linea(texto, False, boton)


def linea(res: Resumen) -> Linea | None:
    """Lo que dice la ventana principal del arranque automático, o None.

    Aquí y no en la ventana para que el menú de consola diga lo mismo. Con el
    agente, el botón abre «Qué hace el agente», que se lo pide por su buzón:
    la ventana no escribe la configuración del equipo."""
    if res.estado == "no_disponible":
        return None
    if res.es_agente:
        return _agente_linea(res)
    if res.estado == "sin_instalar":
        return Linea("En este equipo no se arranca nada al enchufarlo.",
                     False, "Configurar…")
    if res.estado == "otro_dispositivo":
        return Linea("El arranque automático de este equipo es para otro "
                     "dispositivo.", False, "Cambiar…")
    if res.estado == "desfasado":
        return Linea("El arranque automático de este equipo es de otra versión: "
                     "puede no hacer lo que dice aquí.", True, "Revisar…")
    hace = _AL_ENCHUFAR.get(res.modo, res.modo)
    return Linea(f"Al enchufarlo en este equipo: {hace}.", False, "Cambiar…")


PAUSA = "En pausa mientras esta ventana esté abierta."


def install_command(mode: str = "ui", poll=None, extra_roots=(),
                    start: bool = True) -> list[str]:
    """La orden completa de instalación, para lanzarla y enseñar su salida.

    Sin parejas ni intervalo: son los del servicio (ver el docstring)."""
    cmd = [sys.executable, str(model.PENWATCH_PY), "install", "--mode", mode]
    if poll:
        cmd += ["--poll", str(poll)]
    for root in extra_roots:
        if str(root).strip():
            cmd += ["--extra-root", str(root).strip()]
    if not start:
        cmd.append("--no-start")
    return cmd


def uninstall_command() -> list[str]:
    return [sys.executable, str(model.PENWATCH_PY), "uninstall"]
