#!/usr/bin/env python3
"""El llavero visto desde la ventana: su línea, «Abrir llavero» y sus ajustes. Sin Tk.

- La línea de la ventana principal (`linea()`): cómo está la base, sin red.
- «Abrir llavero» (`abrir()`): los pasos de §6 de la especificación, en orden,
  con lo que pregunta dado como funciones. `ui/tk_llavero.py` le da diálogos de
  Tk; sin entorno gráfico, `ui.abrir_llavero()` le da la consola y no pregunta.
  Qué hace falta y cómo se lanza es de `common/keepassxc.py`.
- «Ajustes → Llavero…» (§9): activarlo con una base propia o la del remoto,
  decir si la base pide fichero llave y desactivarlo. Cada cosa es un plan
  (`LlaveroPlan`) que se confirma antes de hacerse. Si el remoto ya tiene
  llavero, la base es la suya: una propia entra como copia de conflicto y se
  combina al abrir.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import Any, Callable, Mapping, NamedTuple

from common import catalog, config_file, conflicts, keepassxc, llavero, model, results
from common.model import ConfigError

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


# --- «Ajustes → Llavero…»

LEYENDO = "Leyendo el catálogo del remoto, para ver si ya tiene llavero…"
EXPLICACION = (
    "Una base de KeePassXC (contraseñas y passkeys) que viaja en el dispositivo y se "
    "sincroniza sola con la carpeta del catálogo, en el remoto. Se abre con «Abrir "
    "llavero».")
"""Lo que dice la cabecera de la pantalla."""


def tabla_remota(cat: catalog.Catalog | None) -> dict | None:
    """Devuelve el `[keychain]` del catálogo, o `None` si no tiene llavero."""
    tabla = (cat.raw if cat is not None else {}).get("keychain")
    return dict(tabla) if isinstance(tabla, Mapping) else None


class Situacion(NamedTuple):
    """Lo que enseña la pantalla del llavero.

    Args:
        activo: Si este dispositivo lo lleva (`[keychain]` en su config).
        base: El nombre de la base, si lo lleva.
        pide_llave: Si la base pide fichero llave.
        nombre_llave: Su nombre, como pista.
        llave: Dónde está en este equipo, si se ha dicho.
    """
    activo: bool
    base: str = ""
    pide_llave: bool = False
    nombre_llave: str = ""
    llave: Path | None = None


def situacion(raw: Mapping[str, Any]) -> Situacion:
    """Devuelve cómo está el llavero en este dispositivo, sin red."""
    tabla = raw.get("keychain")
    if not isinstance(tabla, Mapping):
        return Situacion(False)
    return Situacion(True, str(tabla.get("base") or ""), bool(tabla.get("fichero_llave")),
                     str(tabla.get("nombre_llave") or ""), keepassxc.llave_apuntada())


def lineas(sit: Situacion, remota: dict | None, leido: bool) -> list[str]:
    """Devuelve lo que dice la tarjeta de la pantalla, una frase por línea.

    Args:
        sit: Lo de este dispositivo.
        remota: El `[keychain]` del catálogo.
        leido: Si se ha podido leer el catálogo.
    """
    if sit.activo:
        salida = [f"Este dispositivo lleva el llavero: {sit.base}."]
        if not sit.pide_llave:
            salida.append("La base no pide fichero llave.")
        else:
            nombre = f"«{sit.nombre_llave}»" if sit.nombre_llave else "un fichero llave"
            donde = (f"En este equipo está en {sit.llave}." if sit.llave is not None
                     else "En este equipo no se ha dicho dónde está: «Abrir llavero» lo "
                          "preguntará.")
            salida.append(f"La base pide {nombre}. {donde}")
        return salida
    if not leido:
        return ["Este dispositivo no lleva el llavero."]
    if remota is None:
        return ["Este dispositivo no lleva el llavero, y el remoto todavía no tiene: el "
                "primero que lo active pone la base."]
    salida = [f"Este dispositivo no lleva el llavero. El remoto ya tiene uno: "
              f"{remota.get('base')}."]
    if remota.get("fichero_llave"):
        nombre = remota.get("nombre_llave")
        salida.append(f"Esa base pide el fichero llave «{nombre}»." if nombre
                      else "Esa base pide un fichero llave.")
    return salida


@dataclass
class LlaveroPlan:
    """Un cambio en el llavero, todavía sin hacer (el contrato de `EditPlan`).

    Args:
        hacer: Lo que hace `execute()`.
        consequences: Una línea por consecuencia.
        warnings: Lo que conviene saber antes de confirmar.
        activa: Si deja el llavero activo: quien lo ejecuta lanza entonces la
            primera pasada, que sube la base o la trae.
    """
    hacer: Callable[[], list[str]]
    consequences: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    activa: bool = False

    def execute(self) -> list[str]:
        """Hace el cambio y devuelve qué ha hecho.

        Raises:
            ConfigError: Si el catálogo no se ha podido escribir (y entonces
                no se ha tocado nada del dispositivo).
            OSError: Si no se ha podido escribir en el dispositivo.
        """
        return self.hacer()


def _con_llavero(raw: Mapping[str, Any], tabla: Mapping[str, Any] | None) -> dict:
    """Devuelve una copia del config con ese `[keychain]`, o sin él con `None`."""
    nuevo = copy.deepcopy(dict(raw))
    if tabla is None:
        nuevo.pop("keychain", None)
    else:
        nuevo["keychain"] = dict(tabla)
    return nuevo


def _raices(raw: Mapping[str, Any]) -> list[str]:
    """Devuelve las parejas bisync del dispositivo que sincronizan la raíz entera."""
    try:
        cfg = model.parse_config(_con_llavero(raw, None))
    except ConfigError:
        return []
    return [p.name for p in cfg.del_usuario if p.es_raiz and p.is_bisync]


def _sin_keepassxc() -> str | None:
    """Devuelve el aviso de que este equipo no puede abrirlo todavía, o `None`."""
    exe = keepassxc.ejecutable()
    if exe is None:
        return ("Este equipo no es Windows: el llavero se sincroniza igual, pero de momento "
                "solo se abre en Windows.")
    if not exe.is_file():
        return ("KeePassXC todavía no está en el dispositivo: lo pone «Actualizar…», en el "
                "recuadro de lo que lleva el dispositivo de la ventana de prdrive.")
    return None


def _editable(cat: catalog.Catalog | None) -> catalog.Catalog:
    """Devuelve el catálogo si está recién leído del remoto.

    Raises:
        ConfigError: Si no hay catálogo o es la copia local.
    """
    if cat is None or not cat.editable:
        raise ConfigError("Para esto hace falta haber leído el catálogo del remoto: "
                          "vuelve a intentarlo con conexión.")
    return cat


def plan_activar(raw: Mapping[str, Any], cat: catalog.Catalog | None, origen: Path | None,
                 pide: bool = False, nombre_llave: str = "",
                 llave: Path | None = None) -> LlaveroPlan:
    """Devuelve el plan de activar el llavero en este dispositivo.

    Args:
        raw: El `sync_config.toml` en bruto.
        cat: El catálogo, recién leído del remoto.
        origen: La base que se da («Usar esta base…»), o `None` para traer la
            del remoto. La original nunca se toca: se copia.
        pide: Si la base que se da pide fichero llave (si el remoto ya tiene
            llavero, lo dice su `[keychain]`).
        nombre_llave: El nombre del fichero llave, como pista para los demás
            dispositivos.
        llave: Dónde está el fichero llave en este equipo.

    Raises:
        ConfigError: Si no se puede: sin catálogo leído, sin base que traer, o
            una base que no es de KeePassXC o no está entera.
    """
    cat = _editable(cat)
    remota = tabla_remota(cat)
    try:
        alta = llavero.decidir_alta(llavero.carpeta(), remota, origen, pide, nombre_llave)
    except ValueError as e:
        raise ConfigError(str(e)) from e
    tabla, destino = alta.tabla, alta.destino
    plan = LlaveroPlan(hacer=lambda: [], activa=True)
    if alta.aviso_formato:
        plan.warnings.append(alta.aviso_formato)
    if remota is not None:
        plan.consequences.append(f"El remoto ya tiene un llavero, {remota.get('base')}: "
                                 "la primera pasada lo trae al dispositivo.")
    if origen is not None and alta.copia:
        plan.consequences.append(
            f"Se copia «{origen.name}» a la carpeta del llavero como copia de conflicto "
            f"de {tabla['base']}, que es la base que vale: «Abrir llavero» ofrecerá "
            "combinarlas, sin perder lo de ninguna.")
    elif destino is not None:
        plan.consequences.append(
            f"Se copia «{origen.name}» a la carpeta del llavero del dispositivo "
            "(.keychain). La original se queda donde está, sin tocar: desde ahora la "
            "buena es la del dispositivo.")
    nuevo_local = _con_llavero(raw, tabla)
    model.parse_config(nuevo_local)                       # un [keychain] que no vale, ahora
    if alta.subir:
        plan.consequences.append(
            f"El catálogo del remoto apunta el llavero ([keychain] en "
            f"{Path(cat.endpoint).name or catalog.FICHERO}), para que los demás "
            "dispositivos puedan traerlo. La primera pasada sube la base a keychain/, "
            "junto al catálogo.")
    if tabla.get("fichero_llave"):
        nombre = tabla.get("nombre_llave")
        plan.consequences.append(
            (f"La base pide el fichero llave «{nombre}»" if nombre
             else "La base pide un fichero llave")
            + (f"; en este equipo está en {llave}" if llave is not None else "")
            + ". prdrive solo apunta dónde está: el fichero no se copia ni se lee.")
    plan.consequences.append(f"Se pone {llavero.LANZADOR} en la raíz del dispositivo, "
                             "para abrirlo sin la ventana de prdrive.")
    raices = _raices(raw)
    if raices:
        plan.warnings.append(
            f"{', '.join(f'«{n}»' for n in raices)} sincroniza la raíz entera: desde ahora "
            "deja fuera .keychain/, y por eso pedirá un --resync.")
    aviso = _sin_keepassxc()
    if aviso:
        plan.warnings.append(aviso)

    def hacer() -> list[str]:
        """Escribe el catálogo (si hace falta) y después lo del dispositivo."""
        hechos: list[str] = []
        if alta.subir:
            hechos += catalog.push(_con_llavero(cat.raw, tabla), cat.text, raw)
        carpeta = llavero.preparar_carpeta()
        if destino is not None:
            llavero.poner_base(origen, destino)
            hechos.append(f"«{origen.name}» copiada a {carpeta.name}/{destino.name}")
        config_file.save(nuevo_local)
        hechos.append("[keychain] escrito en sync_config.toml")
        llavero.escribir_lanzador()
        hechos.append(f"{llavero.LANZADOR} en la raíz")
        if llave is not None:
            keepassxc.apuntar_llave(llave)
        return hechos

    plan.hacer = hacer
    return plan


def plan_pide_llave(raw: Mapping[str, Any], cat: catalog.Catalog | None, pide: bool,
                    nombre_llave: str = "", llave: Path | None = None) -> LlaveroPlan:
    """Devuelve el plan de apuntar si la base pide fichero llave, aquí y en el catálogo.

    prdrive no tiene cómo saberlo (la cabecera KDBX no dice qué credenciales
    lleva la base): lo dice la persona cuando lo cambia en KeePassXC.

    Args:
        raw: El `sync_config.toml` en bruto.
        cat: El catálogo, recién leído del remoto.
        pide: Si la base pide fichero llave desde ahora.
        nombre_llave: Su nombre, como pista para los demás dispositivos.
        llave: Dónde está en este equipo, si se ha dicho.

    Raises:
        ConfigError: Sin catálogo leído, o si el del remoto no es este llavero.
    """
    cat = _editable(cat)
    sit = situacion(raw)
    remota = tabla_remota(cat)
    if not sit.activo or remota is None or remota.get("base") != sit.base:
        raise ConfigError("El catálogo del remoto no tiene este llavero: no se puede "
                          "cambiar desde aquí.")
    tabla = {**remota, "fichero_llave": bool(pide)}
    if not pide:
        tabla.pop("nombre_llave", None)
    elif nombre_llave:
        tabla["nombre_llave"] = nombre_llave
    nuevo_local = _con_llavero(raw, tabla)
    if pide:
        nombre = tabla.get("nombre_llave")
        que = f"{sit.base} pide el fichero llave" + (f" «{nombre}»" if nombre else "")
    else:
        que = f"{sit.base} ya no pide fichero llave"
    plan = LlaveroPlan(hacer=lambda: [])
    plan.consequences.append(f"Se apunta que {que}, aquí y en el catálogo del remoto: los "
                             "demás dispositivos lo sabrán al traerlo.")
    plan.consequences.append("La base no se toca: eso se cambia en KeePassXC.")

    def hacer() -> list[str]:
        """Escribe el catálogo y después el config del dispositivo."""
        hechos = catalog.push(_con_llavero(cat.raw, tabla), cat.text, raw)
        config_file.save(nuevo_local)
        keepassxc.apuntar_llave(llave if pide else None)
        return hechos + ["[keychain] cambiado en sync_config.toml"]

    plan.hacer = hacer
    return plan


def plan_desactivar(raw: Mapping[str, Any]) -> LlaveroPlan:
    """Devuelve el plan de desactivar el llavero en este dispositivo.

    Solo se quita `[keychain]` de aquí (y `Llavero.bat`): la carpeta del llavero
    y el remoto no se tocan, y los demás dispositivos siguen con él.

    Raises:
        ConfigError: Si no está activo.
    """
    sit = situacion(raw)
    if not sit.activo:
        raise ConfigError("Este dispositivo no lleva el llavero.")
    nuevo_local = _con_llavero(raw, None)
    plan = LlaveroPlan(hacer=lambda: [])
    plan.consequences.append("Se quita [keychain] de sync_config.toml: el llavero deja de "
                             "sincronizarse en este dispositivo.")
    plan.consequences.append(
        f"La carpeta del llavero (.keychain, con {sit.base}) se queda donde está, y el "
        "remoto no se toca: los demás dispositivos siguen con él.")
    plan.consequences.append(f"Se quita {llavero.LANZADOR} de la raíz.")
    if llavero.keepassxc_abierto():
        plan.warnings.append("KeePassXC está abierto: ciérralo antes, o lo que guardes "
                             "desde ahora ya no subirá.")
    raices = _raices(raw)
    if raices:
        plan.warnings.append(
            f"{', '.join(f'«{n}»' for n in raices)} sincroniza la raíz entera: sin llavero, "
            ".keychain/ viajará con ella, y pedirá un --resync.")

    def hacer() -> list[str]:
        """Quita `[keychain]`, para al vigilante y quita el lanzador."""
        config_file.save(nuevo_local)
        try:
            llavero.parada_vigilante().touch()
        except OSError:
            pass                            # sin config de llavero, sale solo
        quitado = llavero.quitar_lanzador()
        return ["[keychain] quitado de sync_config.toml"] + (
            [f"{llavero.LANZADOR} quitado"] if quitado else [])

    plan.hacer = hacer
    return plan
