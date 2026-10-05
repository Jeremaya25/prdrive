#!/usr/bin/env python3
"""El llavero visto desde la ventana: su línea y «Abrir llavero». Sin Tk.

- La línea de la ventana principal (`linea()`): cómo está la base, sin red.
- «Abrir llavero» (`abrir()`): los pasos de §6 de la especificación, en orden,
  con lo que pregunta dado como funciones. `ui/tk_llavero.py` le da diálogos de
  Tk; sin entorno gráfico, `ui.abrir_llavero()` le da la consola y no pregunta.
  Qué hace falta y cómo se lanza es de `common/keepassxc.py`.
"""

from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import Callable, NamedTuple

from common import conflicts, keepassxc, llavero, model, results

from . import conflict_editor, cuando, cuando_sello

TITULO = "Llavero"
ABRIR = "Abrir llavero"
"""El botón de la ventana, y lo que hacen `Llavero.bat` y `runsync.py --llavero`."""
REDISTRIBUIBLE = "https://aka.ms/vs/17/release/vc_redist.x64.exe"
"""El instalador oficial de Microsoft del runtime de Visual C++ 2015-2022 (x64).

El de x64 también en Windows ARM64: allí KeePassXC es el x64, emulado.
"""

OTRO_ABIERTO = (
    "Hay otro KeePassXC abierto en este equipo, que no es el del dispositivo.\n\n"
    "Ciérralo y vuelve a pulsar «Abrir llavero». Si no, el del dispositivo le "
    "pasaría la base a ése, que tiene otra configuración.")
SIN_BASE = (
    "El llavero todavía no tiene base: ni en el dispositivo ni en el remoto.\n\n"
    "Actívalo con una base en «Ajustes → Llavero…».")
TRAYENDO = "Trayendo lo último del llavero…"
COMBINAR = "Combinar las copias del llavero"
"""El título de la confirmación de «Combinar» al abrir."""
SIN_COMBINAR = "Cancelar abre KeePassXC sin combinar"
"""La nota de esa confirmación: cancelar no deja de abrir."""
ABRIENDO = "Abriendo KeePassXC…"
FALTA_RUNTIME = (
    "KeePassXC no ha podido arrancar: a este equipo le falta el runtime de Visual C++ "
    "2015-2022, que KeePassXC necesita y no lleva consigo.\n\n"
    "Instalarlo pide un administrador. El instalador oficial de Microsoft está en:\n\n"
    f"{REDISTRIBUIBLE}")


def pregunta_llave(nombre: str) -> str:
    """Devuelve el título del diálogo que pregunta por el fichero llave en este equipo."""
    return f"¿Dónde está «{nombre}» en este equipo?" if nombre else \
        "¿Dónde está el fichero llave en este equipo?"


def se_cayo(codigo: int) -> str:
    """Devuelve lo que se dice si KeePassXC sale nada más lanzarlo, con un código que no es 0."""
    if codigo in keepassxc.VC_FALTA:
        return FALTA_RUNTIME
    return (f"KeePassXC se ha cerrado nada más abrirse (código {codigo:#x}).\n\n"
            "Prueba a abrirlo otra vez; si vuelve a pasar, ábrelo desde "
            ".prdrive\\keepassxc para ver qué dice.")


def sin_traer_base(rc: int) -> str:
    """Devuelve lo que se dice si la base no está en el dispositivo y no se ha podido traer."""
    return (f"La base del llavero no está en el dispositivo y no se ha podido traer del "
            f"remoto (código {rc}). Vuelve a intentarlo con conexión.")


def sin_traer(rc: int) -> str:
    """Devuelve la línea de una pasada de antes de abrir que no ha ido bien.

    Se abre igual, con lo que hay en el dispositivo.
    """
    return (f"No se ha podido traer lo último del remoto (código {rc}): se ha abierto "
            "la base del dispositivo. Lo que guardes subirá cuando haya conexión.")


class Linea(NamedTuple):
    """La línea del llavero en la ventana principal.

    Args:
        texto: Lo que dice.
        aviso: Si va en ámbar.
        abrir: Si «Abrir llavero» se puede pulsar.
    """
    texto: str
    aviso: bool
    abrir: bool


def linea(config: model.Config) -> Linea | None:
    """Devuelve la línea del llavero, o `None` si el dispositivo no lo lleva.

    Lee ficheros del dispositivo y mira los procesos del equipo (si el
    KeePassXC de la unidad está abierto), sin red: cabe en el primer pintado.
    """
    pareja = config.pareja_llavero
    if config.llavero is None or pareja is None:
        return None
    exe = keepassxc.ejecutable()
    if exe is None:
        return Linea(keepassxc.SOLO_WINDOWS, False, False)
    if not exe.is_file():
        return Linea("Falta KeePassXC en el dispositivo: lo pone «Actualizar…».", True, False)
    base = config.llavero["base"]
    fallo = next(iter(results.fallos_de([model.LLAVERO])), None)
    if fallo is not None:
        hace = cuando_sello(fallo.cuando)
        return Linea(f"{base}: la última pasada falló" + (f" ({hace})" if hace else "")
                     + ". Se vuelve a intentar al abrirlo y en cada guardado.", True, True)
    if not (llavero.carpeta() / base).exists():
        return Linea(f"{base} todavía no está en el dispositivo: «Abrir llavero» la trae "
                     "del remoto.", False, True)
    if llavero.keepassxc_abierto():
        return Linea(f"{base}, abierto en KeePassXC.", False, True)
    if llavero.pendiente(pareja):
        return Linea(f"{base}, con cambios que aún no han subido.", False, True)
    ultima = results.ultimas_buenas([model.LLAVERO]).get(model.LLAVERO)
    hace = cuando(ultima)
    return Linea(f"{base}, al día" + (f" · última pasada {hace}." if hace else "."),
                 False, True)


def llave_de_este_equipo(config: model.Config,
                         elegir_llave: Callable[[str], Path | None]) -> Path | None:
    """Devuelve el fichero llave de la base en este equipo, preguntándolo si hace falta.

    Si `[keychain]` dice que la base lo pide y en este equipo no está apuntado
    (o ya no está donde se apuntó: otro pendrive, que no está puesto), se
    pregunta y se apunta la ruta. El fichero ni se abre.

    Returns:
        La ruta, o `None` si la base no lo pide o no se ha dicho.
    """
    datos = config.llavero or {}
    if not datos.get("fichero_llave"):
        return None
    llave = keepassxc.llave_apuntada()
    if llave is not None and llave.is_file():
        return llave
    llave = elegir_llave(str(datos.get("nombre_llave") or ""))
    if llave is not None:
        keepassxc.apuntar_llave(llave)
    return llave


def conflicto_de_la_base(config: model.Config, base: Path) -> conflicts.Conflicto | None:
    """Devuelve el conflicto de la base del llavero, si tiene copias; recorre `.keychain/`."""
    pareja = config.pareja_llavero
    if pareja is None:
        return None
    try:
        encontrados = conflicts.actualizar_pareja(pareja)
    except OSError:
        return None
    return next((x for x in encontrados if x.original == base and x.copias), None)


def abrir(config: model.Config, avisar: Callable[[str], None],
          esperar: Callable[[str, Callable], tuple[bool, object]],
          elegir_llave: Callable[[str], Path | None],
          confirmar: Callable[[object, str, str], bool], decir_sin_traer: bool) -> bool:
    """Hace «Abrir llavero»: los pasos de §6, preguntando con lo que se le da.

    Con el KeePassXC de la unidad ya abierto, solo lo trae delante. Con otro
    KeePassXC abierto en el equipo, lo dice y no abre nada. Si la última pasada
    es vieja, trae lo último (si falla, abre igual). Si la base pide fichero
    llave y en este equipo no se sabe dónde está, lo pregunta y apunta la ruta.
    Si la base tiene copias de conflicto, ofrece combinarlas antes de abrir:
    después de la pasada, que es la que las trae, y del fichero llave, que hace
    falta para combinar. Al final, el vigilante del llavero, si nadie lo
    atiende.

    Args:
        config: El del dispositivo.
        avisar: Enseña un texto y espera a que se lea.
        esperar: `esperar(mensaje, funcion)` corre `funcion()` mientras dice
            `mensaje`, y devuelve `(True, resultado)` o `(False, excepción)`,
            como `tk.working()`.
        elegir_llave: Pregunta dónde está en este equipo el fichero llave de
            ese nombre; `None` si no se dice (KeePassXC lo pedirá).
        confirmar: `confirmar(plan, titulo, nota)` enseña un plan y dice si
            se sigue, como `tk_pairs.confirmar_plan()`.
        decir_sin_traer: Si una pasada que falla se dice con un aviso. La
            ventana de prdrive no lo hace: lo dice su línea del llavero.

    Returns:
        True si KeePassXC se ha abierto (o traído delante).
    """
    ap = keepassxc.mirar_apertura(config)
    if ap.motivo is not None:
        avisar(ap.motivo)
        return False
    if ap.otro:
        avisar(OTRO_ABIERTO)
        return False
    if ap.pasada:
        hecho, valor = esperar(TRAYENDO, llavero.pasada)
        rc = valor[0] if hecho else -1
        if not ap.base.exists():
            avisar(SIN_BASE if rc == 0 else sin_traer_base(rc))
            return False
        if rc != 0 and decir_sin_traer:
            avisar(sin_traer(rc))
    llave = ap.llave if ap.abierto else llave_de_este_equipo(config, elegir_llave)
    conflicto = None if ap.abierto else conflicto_de_la_base(config, ap.base)
    if conflicto is not None:
        try:
            plan = conflict_editor.plan_combinar(conflicto, llave)
        except conflict_editor.ResolucionImposible as e:
            avisar(str(e))
        else:
            if confirmar(plan, COMBINAR, SIN_COMBINAR):
                hecho, valor = esperar(conflict_editor.ESPERANDO_CONSOLA, plan.execute)
                if not hecho:
                    avisar(str(valor))
                conflicto_de_la_base(config, ap.base)     # al día para «Reparación»
    hecho, valor = esperar(ABRIENDO, partial(keepassxc.abrir, ap, llave))
    if not hecho:
        avisar(f"No se ha podido abrir KeePassXC: {valor}")
        return False
    if valor.codigo not in (None, 0):
        avisar(se_cayo(valor.codigo))
        return False
    avisos = list(valor.avisos)
    try:
        llavero.lanzar_vigilante()
    except OSError as e:
        avisos.append(f"No se ha podido arrancar el vigilante del llavero ({e}): lo que "
                      "guardes subirá con la próxima pasada.")
    if avisos:
        avisar("\n\n".join(avisos))
    return True
