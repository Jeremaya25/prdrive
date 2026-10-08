#!/usr/bin/env python3
"""Lo que la UI necesita de `penwatch.py`, sin Tkinter.

La dependencia va en un solo sentido: la UI conoce a penwatch y penwatch no
conoce a nadie. Es deliberado y no se puede invertir: `penwatch.py` se copia al
equipo y tiene que seguir funcionando con el dispositivo desconectado, así que
no puede importar nada que viva en el dispositivo.

Para leer (estado, detección) se importa penwatch y se usan sus funciones, que
ya devuelven filas. Para instalar y desinstalar se lanza como proceso: son
órdenes que escriben en el equipo y cuentan lo que hacen por su salida, y esa
salida se enseña en la misma ventana que se usa para `sync.py`.

El vigilante solo decide QUÉ se hace al enchufar. Las parejas y el intervalo
son los del servicio, que viven en el dispositivo y se eligen en la ventana
principal (las parejas) y en «Ajustes → Configuración» (el intervalo): el
servicio es uno, se arranque a mano o al enchufar.
"""

from __future__ import annotations

import subprocess
import sys
from typing import NamedTuple

from common import fleet, model

MODES = ("ui", "daemon", "sync")
"""Los modos del vigilante, de lo que menos hace solo a lo que más.

Van en el orden en que se ofrecen.
"""
MODE_LABELS = {
    "ui": "Abrir la ventana",
    "daemon": "Arrancar el servicio",
    "sync": "Una pasada y nada más",
}
"""Cómo se llama cada modo en la ventana."""
MODE_HELP = {
    "ui": "abre la ventana de runsync y decides tú (por defecto)",
    "daemon": "sincroniza cada N minutos mientras siga puesto",
    "sync": "sincroniza una vez, en silencio, y se cierra",
}
"""Qué hace cada modo.

Qué parejas y cada cuánto no se dice aquí: lo dice una sola vez la pantalla,
debajo de las tres opciones (son los del servicio, para las dos que
sincronizan).
"""

_AL_ENCHUFAR = {
    "ui": "abre esta ventana",
    "daemon": "arranca el servicio",
    "sync": "una pasada de estas parejas",
}
"""Lo que se hace al enchufar, dicho en la línea de la ventana principal."""


class Resumen(NamedTuple):
    """Qué hace el arranque automático de este equipo con ESTE dispositivo.

    Con agente, además, `vivo` y `pausado` salen de su `estado.json`, y
    `pausada` de su `agente.json`.

    Args:
        estado: Uno de, de más a menos grave para quien lee la línea:
            `no_disponible` (penwatch no se puede importar: no se dice nada),
            `sin_instalar` (en este equipo no hay vigilante),
            `otro_dispositivo` (lo hay, pero vigila otro prdrive: un equipo
            tiene uno), `desfasado` (vigila este, con una copia de otra
            versión), `instalado` (vigila este y `modo` es lo que hará),
            `agente_nueva` (el agente residente está instalado y este
            dispositivo no está en su lista: preguntará al enchufarlo),
            `agente` (lo tiene en su lista y `modo` es lo que hace:
            `common.equipo.MODOS`, que añade «nada») y `agente_raiz` (no es una
            unidad sino la raíz de este equipo, y el agente la atiende con ese
            `modo`).
        modo: Lo que se hace al enchufar.
        vivo: Si hay un proceso del agente en marcha en este equipo.
        pausado: Si el agente está en el «Pausar» de su bandeja, que para todo.
        pausada: Si ESTA raíz está en el «Pausar» de su ventana: el agente no
            la sincroniza hasta «Reanudar» (`equipo.Unidad.pausada`).
    """
    estado: str
    modo: str = ""
    vivo: bool = False
    pausado: bool = False
    pausada: bool = False

    @property
    def vigila_este(self) -> bool:
        """Indica si hay un vigilante en este equipo que atiende a este dispositivo."""
        return (self.estado in ("desfasado", "instalado")
                or (self.estado in ("agente", "agente_raiz") and self.modo != "nada"))

    @property
    def es_agente(self) -> bool:
        """Indica si quien atiende es el agente residente."""
        return self.estado in ("agente", "agente_raiz", "agente_nueva")

    @property
    def servicio_del_agente(self) -> bool:
        """Indica si el servicio periódico de esta raíz es el agente y está en marcha.

        Entonces la ventana no ofrece «Iniciar servicio» sino «Pausar» /
        «Reanudar» (`boton_servicio`), y la consola, si lo pide, se lo pide a
        él (`reanudar`). Solo en modo `daemon`: en `sync` hace una pasada por
        conexión y quien pide un servicio cada N minutos no pide eso.
        """
        return (self.estado in ("agente", "agente_raiz") and self.modo == "daemon"
                and self.vivo)


class Linea(NamedTuple):
    """La línea de la ventana principal: el texto, si va en ámbar y el botón.

    Args:
        texto: Lo que dice.
        aviso: Si va en ámbar.
        boton: Lo que dice el botón.
    """
    texto: str
    aviso: bool
    boton: str


CONSULTA_S = 8.0
"""Segundos que se espera a `schtasks` o `systemctl` cuando solo se les pregunta."""
CODIGO_TIEMPO = 124
"""El código con que `consulta()` devuelve una orden que no contestó a tiempo.

Es el de `timeout(1)`.
"""


def consulta(cmd: list[str], timeout: float = CONSULTA_S) -> subprocess.CompletedProcess:
    """Hace una pregunta al sistema (`schtasks /Query`…) sin esperarla para siempre.

    Es `penwatch.run_quiet()` con un tope de tiempo, y es solo para preguntar:
    una orden que cambia el sistema (`schtasks /Create`, `systemctl enable`…) no
    se corta a medias, que lo dejaría peor, y esas siguen por `run_quiet()`. Está
    aquí y no en `penwatch.py` porque cambiar los bytes de ese fichero deja
    «desfasado» a cada vigilante ya instalado (`penwatch.copia_al_dia()`).

    Args:
        cmd: La pregunta entera.
        timeout: Segundos que se le dan.

    Returns:
        El resultado. Si pasa el tiempo, la orden se mata y el código es
        `CODIGO_TIEMPO`; si no se puede lanzar, 127.
    """
    kwargs: dict = {"capture_output": True, "text": True, "errors": "replace",
                    "timeout": timeout}
    # El sistema de verdad y no `IS_WIN`, que los tests fuerzan: `creationflags`
    # en un POSIX es un error.
    if sys.platform == "win32":
        kwargs["creationflags"] = model.CREATE_NO_WINDOW
    try:
        return subprocess.run(cmd, **kwargs)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, CODIGO_TIEMPO, "",
                                           f"sin respuesta en {timeout:g} s")
    except OSError as e:
        return subprocess.CompletedProcess(cmd, 127, "", str(e))


def _penwatch():
    """Devuelve el módulo `penwatch`, importado aquí dentro y no arriba.

    Es un script hermano, no un módulo del paquete: si por lo que sea no se
    pudiera importar, eso no debe impedir que se abra la ventana principal.
    """
    import penwatch
    return penwatch


def available() -> bool:
    """Indica si `penwatch` se puede importar."""
    try:
        _penwatch()
        return True
    except Exception:
        return False


def status_rows() -> list[tuple[str, str]]:
    """Devuelve las filas de estado de penwatch."""
    return _penwatch().status_rows()


def probe_rows() -> list[tuple[str, str]]:
    """Devuelve las filas de la detección de penwatch."""
    return _penwatch().probe_rows()


def log_tail(lines: int = 10) -> list[str]:
    """Devuelve las últimas líneas del diario de penwatch."""
    return _penwatch().log_tail(lines)


def log_path() -> str:
    """Devuelve dónde vive el diario, para poder enseñarlo junto a lo que se lee de él.

    Está en el equipo, nunca en el dispositivo, y decirlo es media explicación.
    """
    try:
        return str(_penwatch().LOG_FILE)
    except Exception:
        return ""


def is_installed() -> bool:
    """Indica si penwatch está instalado en este equipo."""
    pw = _penwatch()
    return bool(pw.read_json(pw.CONFIG_FILE))


def installed_options() -> dict:
    """Devuelve con qué se instaló, para precargar el formulario; vacío si no lo está.

    Sin parejas ni intervalo aunque un `watch.json` de antes los traiga: ya no
    son del equipo, y reinstalar es precisamente lo que los quita.
    """
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
    """Devuelve qué hace el arranque automático de este equipo con este dispositivo.

    Solo lee ficheros (`watch.json`, las dos copias de penwatch, el PRDRIVE):
    nada de `schtasks` ni `systemctl`, porque lo pregunta la ventana al
    pintarse y la primera pintura tiene que ser instantánea (la misma regla que
    `update.pending()`). Si la tarea está registrada o no lo cuenta la pantalla
    del vigilante, que sí puede tardar. Nunca lanza.

    Con el agente residente instalado en este equipo manda él: sustituye a
    penwatch, que el instalador desinstala al ponerlo. Es de módulo para que
    los tests la sustituyan.
    """
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
    """Devuelve lo que el agente residente hace con este dispositivo, si hay agente.

    Solo lee su configuración (`common/equipo.py`): ni el agente ni la ventana
    se escriben el uno al otro aquí. Nunca lanza.
    """
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
                   vivo, pausado, unidad.pausada)


_AGENTE_HACE = {
    "ui": "el agente de este equipo abre esta ventana al enchufarlo.",
    "daemon": "el agente de este equipo lo sincroniza en segundo plano.",
    "sync": "el agente de este equipo hace una pasada al enchufarlo.",
    "nada": "el agente de este equipo no hace nada con él.",
}
"""Lo que hace el agente al enchufar el dispositivo, dicho en la misma línea."""

MODOS_AGENTE = ("daemon", "sync", "ui", "nada")
"""Lo que se le puede pedir al agente que haga con un dispositivo.

Son los `common.equipo.MODOS`, en el orden en que se ofrecen.
"""
MODOS_AGENTE_RAIZ = ("daemon", "nada")
"""Lo mismo para la raíz del equipo, que no se enchufa.

Abrir su ventana o una pasada «al enchufarla» no quieren decir nada.
"""
ETIQUETA_AGENTE = {
    "daemon": "Sincronizarlo en segundo plano",
    "sync": "Una pasada al enchufarlo",
    "ui": "Abrir esta ventana al enchufarlo",
    "nada": "Nada",
}
"""Cómo se llama cada modo del agente en la ventana."""
AYUDA_AGENTE = {
    "daemon": "con las parejas y el intervalo del servicio (por defecto)",
    "sync": "una vez por conexión, en silencio",
    "ui": "y decides tú desde aquí",
    "nada": "solo lo que pidas tú desde aquí",
}
"""Qué hace cada modo del agente con un dispositivo."""
AYUDA_AGENTE_RAIZ = {
    "daemon": "con las parejas y el intervalo del servicio",
    "nada": "solo lo que pidas tú desde aquí o desde la bandeja",
}
"""Qué hace cada modo del agente con la raíz del equipo."""


def modos_agente(res: Resumen) -> tuple[str, ...]:
    """Devuelve los modos que se ofrecen para esta raíz en «Qué hace el agente»."""
    return MODOS_AGENTE_RAIZ if res.estado == "agente_raiz" else MODOS_AGENTE


def ayuda_agente(res: Resumen, modo: str) -> str:
    """Devuelve lo que hace ese modo, para esta raíz."""
    return (AYUDA_AGENTE_RAIZ if res.estado == "agente_raiz" else AYUDA_AGENTE).get(modo, "")


def pedir_al_agente(peticion: dict) -> bool:
    """Deja una petición en el buzón del agente (`agente.pide`).

    La ventana no escribe `agente.json`, que es del agente y puede ser de otra
    versión que este código. Es de módulo para que los tests la sustituyan.
    """
    from common import equipo
    return equipo.pedir(peticion)


def pedir_modo(modo: str) -> bool:
    """Pide que el agente haga `modo` con ESTA raíz.

    Si no la tenía en su lista, entra con él: es la persona diciendo que sí
    desde la ventana de la propia unidad, lo mismo que «Atender» en la pregunta
    o en la bandeja.
    """
    from common import equipo
    if modo not in equipo.MODOS:
        return False
    return pedir_al_agente({"pide": equipo.PIDE_MODO, "id": fleet.device_id(),
                            "modo": modo, "nombre": fleet.nombre()})


def pedido(res: Resumen, modo: str) -> Resumen:
    """Devuelve cómo queda la línea tras pedirle `modo` al agente.

    El agente lo aplica en unos segundos y releer `agente.json` ahora mismo
    diría lo de antes: la ventana enseña lo pedido, que es lo que va a haber.
    """
    return res._replace(estado="agente_raiz" if res.estado == "agente_raiz" else "agente",
                        modo=modo)


def pedir_al_iniciar() -> bool | None:
    """Devuelve el `pedir_al_iniciar` del agente, o `None` si no aplica.

    Solo aplica si esta raíz es la cifrada de este equipo, que es a lo único a
    lo que afecta. Solo lee `agente.json`.
    """
    try:
        from common import equipo
        unidad = equipo.leer_ajustes().unidades.get(fleet.device_id())
        if unidad is None or not unidad.cifrada:
            return None
        return equipo.leer_ajustes().pedir_al_iniciar
    except Exception:                                   # noqa: BLE001
        return None


def pedir_ajuste(clave: str, valor) -> bool:
    """Pide al agente que cambie un ajuste suyo."""
    from common import equipo
    return pedir_al_agente({"pide": equipo.PIDE_AJUSTE, "clave": clave, "valor": valor})


def _agente_linea(res: Resumen) -> Linea:
    """Devuelve la línea del agente para esta raíz.

    Dice qué hace con ella, si está en marcha y si está en pausa. El botón abre
    «Qué hace el agente» (`tk_watch.open_agente`).
    """
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
    if res.pausada:
        texto += (" Está en pausa desde esta ventana: no "
                  + ("la" if res.estado == "agente_raiz" else "lo")
                  + " sincroniza hasta que pulses «Reanudar».")
    if res.pausado:
        texto += (" Está en pausa para todo: se reanuda desde su icono de la bandeja "
                  "o con «agente.py sigue».")
    return Linea(texto, False, boton)


def linea(res: Resumen) -> Linea | None:
    """Devuelve lo que dice la ventana principal del arranque automático, o `None`.

    Está aquí y no en la ventana para que el menú de consola diga lo mismo. Con
    el agente, el botón abre «Qué hace el agente», que se lo pide por su buzón:
    la ventana no escribe la configuración del equipo.
    """
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
"""Lo que se dice mientras la ventana tiene parado el servicio."""
PAUSA_AGENTE = ("En pausa mientras esta ventana esté abierta; al cerrarla vuelve el "
                "agente, salvo que pulses «Pausar».")
"""Lo mismo cuando el servicio es el agente: dice qué cambia «Pausar»."""


def pausa(res: Resumen, ventana: bool = True) -> str | None:
    """Devuelve la frase que va debajo de la línea mientras la ventana está abierta.

    Es `None` si no hay nada que decir: nadie atiende este dispositivo al
    enchufarlo, o el agente ya lo tiene en pausa por otra cosa (el «Pausar» de
    la ventana o el de la bandeja), que la línea ya dice.

    Args:
        res: Lo que hace el arranque automático con esta raíz.
        ventana: Si es para la ventana, que tiene el botón «Pausar»; la consola
            no lo tiene.
    """
    if res.es_agente and res.vivo and (res.pausada or res.pausado):
        return None
    if not res.vigila_este:
        return None
    return PAUSA_AGENTE if ventana and res.servicio_del_agente else PAUSA


INICIAR, PAUSAR, REANUDAR, SEGUIR = "iniciar", "pausar", "reanudar", "seguir"
"""Lo que hace el botón del servicio del pie de la ventana (`boton_servicio`)."""


class BotonServicio(NamedTuple):
    """El botón del servicio del pie de la ventana: qué dice y qué hace.

    Args:
        texto: Lo que dice.
        accion: `INICIAR` (arrancar el servicio de runsync, que cierra la
            ventana), `PAUSAR` / `REANUDAR` (la pausa de ESTA raíz en el
            agente, por su buzón) o `SEGUIR` (quitar la pausa de todo del
            agente, la de su bandeja).
    """
    texto: str
    accion: str


def boton_servicio(res: Resumen) -> BotonServicio:
    """Devuelve el botón del servicio para esta raíz.

    Sin agente que la atienda es «Iniciar servicio», como siempre. Con el
    agente vivo y la raíz en su lista:
    - pausada desde su ventana, «Reanudar», sea cual sea el modo: es la única
      manera de quitar esa pausa, y no puede quedar escondida;
    - siendo su servicio (modo `daemon`), «Pausar», o «Reanudar todo» si el
      agente está en la pausa de su bandeja, que para todas las raíces y la
      etiqueta lo dice.
    En cualquier otro caso (modo `sync`/`ui`/`nada`, agente parado, unidad
    fuera de la lista) el servicio de siempre.
    """
    if res.estado in ("agente", "agente_raiz") and res.vivo:
        if res.pausada:
            return BotonServicio("Reanudar", REANUDAR)
        if res.servicio_del_agente:
            return (BotonServicio("Reanudar todo", SEGUIR) if res.pausado
                    else BotonServicio("Pausar", PAUSAR))
    return BotonServicio("Iniciar servicio", INICIAR)


def pedir_a_la_raiz(peticion: dict) -> bool:
    """Deja una petición en el buzón de ESTA raíz (`state/servicio.pide`).

    Es lo que la ventana le pide al servicio de la raíz desde la que corre.
    Es de módulo para que los tests la sustituyan.
    """
    from common import equipo
    return equipo.pedir(peticion, model.STATE_DIR / equipo.BUZON_SERVICIO)


def pedir_servicio(accion: str) -> bool:
    """Le pide al agente lo que hace el botón del servicio: `PAUSAR`, `REANUDAR` o `SEGUIR`.

    «Pausar» y «Reanudar» van al buzón de esta raíz (son de ella); «Reanudar
    todo», al del agente (`sigue`, la pausa de todo).

    Returns:
        Si se pudo dejar la petición; False también con una acción que no es
        de las tres.
    """
    from common import equipo
    if accion == PAUSAR:
        return pedir_a_la_raiz({"pide": equipo.PIDE_PAUSAR_RAIZ})
    if accion == REANUDAR:
        return pedir_a_la_raiz({"pide": equipo.PIDE_REANUDAR})
    if accion == SEGUIR:
        return pedir_al_agente({"pide": equipo.PIDE_SIGUE})
    return False


def tras_servicio(res: Resumen, accion: str) -> Resumen:
    """Devuelve cómo queda la línea tras pedirle esa acción al agente.

    Por lo mismo que `pedido()`: el agente la aplica en unos segundos y la
    ventana enseña lo pedido.
    """
    if accion == PAUSAR:
        return res._replace(pausada=True)
    if accion == REANUDAR:
        return res._replace(pausada=False)
    if accion == SEGUIR:
        return res._replace(pausado=False)
    return res


def install_command(mode: str = "ui", poll=None, extra_roots=(),
                    start: bool = True) -> list[str]:
    """Devuelve la orden completa de instalación, para lanzarla y enseñar su salida.

    Va sin parejas ni intervalo: son los del servicio (ver el módulo).
    """
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
    """Devuelve la orden de desinstalar penwatch."""
    return [sys.executable, str(model.PENWATCH_PY), "uninstall"]
