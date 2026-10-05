#!/usr/bin/env python3
"""El llavero al preparar un dispositivo: el paso «Llavero» del asistente (§9).

Es lo de «Ajustes → Llavero…» de la ventana del dispositivo
(`ui/llavero_editor.plan_activar()`), con la misma regla
(`llavero.decidir_alta()`), sobre un dispositivo que no es el de este proceso:
todo va con su raíz, y el catálogo se escribe con el rclone del asistente
(`catalog.push(ejecutar=…)`, sin dejar copia local). Y además pone KeePassXC
(`keepassxc_bin`), que en la ventana pone «Actualizar…».

No importa `ui/`, y no toca el dispositivo hasta `aplicar()`.
"""

from __future__ import annotations

import subprocess
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from common import catalog, components, config_file, keepassxc, llavero, model
from common.model import ConfigError

from . import InstallError, deploy, keepassxc_bin
from .keepassxc_bin import Progreso
from .remote import Catalog, Rclone

ESPERA_CATALOGO = 90.0  # segundos
"""Lo más que se espera a cada orden de rclone al escribir el catálogo."""


def tabla_remota(cat: Catalog | None) -> dict | None:
    """Devuelve el `[keychain]` del catálogo, o `None` si el remoto no tiene llavero."""
    tabla = (cat.raw if cat is not None else {}).get("keychain")
    return dict(tabla) if isinstance(tabla, Mapping) else None


@dataclass
class Plan:
    """Cómo entra el llavero en el dispositivo que se prepara, todavía sin hacer.

    Args:
        alta: Lo que decide `llavero.decidir_alta()`.
        origen: La base que se ha dado, o `None` si se trae la del remoto.
        llave: Dónde está el fichero llave en este equipo, si se ha dicho.
        lineas: Lo que va a pasar, una frase por línea.
        avisos: Lo que conviene saber.
    """
    alta: llavero.Alta
    origen: Path | None
    llave: Path | None
    lineas: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)


def pensar(device_root: Path | str, cat: Catalog | None, origen: Path | None,
           pide: bool = False, nombre_llave: str = "", llave: Path | None = None) -> Plan:
    """Decide cómo entra el llavero en el dispositivo, sin tocar nada.

    Args:
        device_root: La raíz del dispositivo que se prepara.
        cat: El catálogo leído en «Comprobaciones».
        origen: La base que se da, o `None` para traer la del remoto.
        pide: Si la base que se da pide fichero llave.
        nombre_llave: Su nombre, como pista para los demás dispositivos.
        llave: Dónde está en este equipo.

    Raises:
        InstallError: Si no hay nada que traer, o lo que se da no es una base
            de KeePassXC entera.
    """
    remota = tabla_remota(cat)
    try:
        alta = llavero.decidir_alta(Path(device_root) / model.LLAVERO_LOCAL, remota,
                                    origen, pide, nombre_llave)
    except ValueError as e:
        raise InstallError(str(e)) from e
    plan = Plan(alta, origen, llave)
    base = alta.tabla["base"]
    if remota is not None:
        plan.lineas.append(f"El remoto ya tiene un llavero, {base}: la primera pasada lo "
                           "trae al dispositivo.")
    if origen is not None and alta.copia:
        plan.lineas.append(f"«{origen.name}» entra como copia de conflicto de {base}: "
                           "«Abrir llavero» ofrecerá combinarlas.")
    elif alta.destino is not None:
        plan.lineas.append(f"«{origen.name}» se copia al dispositivo; la original se queda "
                           "donde está. Desde ahora la buena es la del dispositivo.")
    if alta.subir:
        plan.lineas.append("El catálogo del remoto apunta el llavero, para que los demás "
                           "dispositivos puedan traerlo.")
    if alta.tabla.get("fichero_llave"):
        plan.lineas.append("La base pide fichero llave: se apunta dónde está en este equipo, "
                           "y el fichero no se copia ni se lee.")
    if alta.aviso_formato:
        plan.avisos.append(alta.aviso_formato)
    if not components.paquetes_keepassxc(deploy.app_dir(device_root)):
        plan.avisos.append("El dispositivo no lleva ninguna plataforma con KeePassXC propio "
                           "(Linux ARM64 no tiene): el llavero se sincroniza, y se abre "
                           "con el KeePassXC del equipo, si lo tiene.")
    return plan


def _subir(rclone: Rclone, pedido: str, tabla: dict) -> list[str]:
    """Escribe `[keychain]` en el catálogo, releído justo antes.

    Raises:
        InstallError: Si no se puede, o si mientras tanto otro dispositivo ha
            puesto un llavero (entonces la base sería la suya).
    """
    def ejecutar(args: list[str]) -> subprocess.CompletedProcess:
        """Ejecuta una orden de rclone capturando la salida."""
        return rclone.run(*args, capture=True, timeout=ESPERA_CATALOGO)

    try:
        res, donde = catalog.leer(ejecutar, pedido)
        if res.returncode != 0:
            raise InstallError(catalog.motivo_lectura(pedido, donde, res))
        texto = res.stdout or ""
        crudo = tomllib.loads(texto)
        if isinstance(crudo.get("keychain"), Mapping):
            raise InstallError("Mientras tanto otro dispositivo ha activado el llavero en el "
                               "remoto: vuelve a este paso para elegir con su base.")
        return catalog.push({**crudo, "keychain": tabla}, texto, ejecutar=ejecutar,
                            donde_pedido=donde, cachear=False)
    except (ConfigError, tomllib.TOMLDecodeError, subprocess.SubprocessError) as e:
        raise InstallError(f"No se ha podido escribir el llavero en el catálogo: {e}") from e


def aplicar(plan: Plan, device_root: Path | str, rclone: Rclone, pedido: str,
            progreso: Progreso | None = None) -> list[str]:
    """Pone el llavero en el dispositivo.

    En este orden, de lo que viene de fuera a lo del dispositivo, para que un
    fallo en la red no deje nada a medias: KeePassXC (un paquete por cada
    plataforma que lleve y lo tenga), el `[keychain]` del catálogo si el remoto no tenía
    llavero, y después `.keychain/` con la base, el config, los lanzadores y la
    ruta del fichero llave en este equipo.

    Args:
        plan: Lo que dijo `pensar()`.
        device_root: La raíz del dispositivo.
        rclone: El cliente de rclone del asistente.
        pedido: Dónde está el catálogo (`remote:ruta`).
        progreso: Para las líneas de la descarga de KeePassXC.

    Returns:
        Lo que ha hecho.

    Raises:
        InstallError: Si algo no se ha podido.
    """
    raiz = Path(device_root)
    app = deploy.app_dir(raiz)
    hechos: list[str] = []
    for paquete in components.paquetes_keepassxc(app):
        hechos += keepassxc_bin.instalar(app, paquete, progreso)
    if plan.alta.subir:
        hechos += _subir(rclone, pedido, plan.alta.tabla)
    try:
        carpeta = llavero.preparar_carpeta(raiz)
        if plan.alta.destino is not None:
            llavero.poner_base(plan.origen, plan.alta.destino)
            hechos.append(f"{plan.origen.name} → {carpeta.name}/{plan.alta.destino.name}")
        ruta = deploy.config_path(raiz)
        crudo = config_file.load_raw(ruta)
        crudo["keychain"] = dict(plan.alta.tabla)
        config_file.save(crudo, path=ruta)
        hechos.append("[keychain] en sync_config.toml")
        hechos += [str(p) for p in llavero.escribir_lanzador(raiz)]
        if plan.llave is not None:
            keepassxc.apuntar_llave(plan.llave, estado=app / "state")
    except (OSError, ConfigError) as e:
        raise InstallError(f"No se ha podido poner el llavero en el dispositivo: {e}") from e
    return hechos
