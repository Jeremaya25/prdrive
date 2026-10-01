#!/usr/bin/env python3
"""Resolver un conflicto de bisync, sin Tkinter.

Mismo guion que `pair_editor`: la ventana (`ui/tk_conflicts.py`) pide un plan,
enseña sus consecuencias en `tk_pairs.confirmar_plan()` y solo si la persona
dice que sí lo ejecuta. Aquí se decide qué fichero se queda con el nombre bueno
y cuáles se borran; allí solo se dibuja.

Resolver es siempre LOCAL. No se habla con el remoto: basta con dejar en este
dispositivo un solo fichero con el nombre de verdad, y la siguiente pasada de
bisync lleva el resultado al otro lado (el fichero que cambia se sube, las
copias que desaparecen se borran allí también). Así la aplicación no escribe en
el remoto por ningún camino que no sea el de siempre.

Qué hace «quedarse con la versión de este dispositivo» depende de dónde esté
esa versión, y por eso no es una regla fija de «borrar la copia»: si perdió
este dispositivo, su versión ES la copia y hay que devolverle el nombre; si
ganó, es el original y lo que sobra es la copia. `common/conflicts.py` ya sabe
cuál es cuál; este módulo solo pregunta.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from common import conflicts
from common.conflicts import Conflicto, Version

ETIQUETA_LADO = {
    conflicts.DISPOSITIVO: "versión de este dispositivo",
    conflicts.REMOTO: "versión del remoto",
}
"""Cómo se llama para la persona la versión de cada lado."""
ETIQUETA_ORIGINAL = "versión con su nombre"
"""Nombre de la versión con el nombre de verdad cuando no se sabe de qué lado viene."""
ETIQUETA_COPIA = "otra versión"
"""Nombre de una copia de conflicto cuando no se sabe de qué lado viene."""

NOTA_LOCAL = ("Solo se tocan ficheros de este dispositivo. La próxima sincronización "
              "lleva el resultado al remoto y borra allí las copias.")
"""Lo que se dice siempre al resolver: solo se toca este dispositivo."""


class ResolucionImposible(Exception):
    """El plan no se puede pensar o ejecutar.

    El mensaje es para la persona.
    """


def mover(origen: Path, destino: Path) -> None:
    """Mueve un fichero sobre otro y devuelve cuando está hecho.

    Es `os.replace` y no `rename`: sustituye al destino si existe y lo hace de
    una vez. O la versión elegida queda con su nombre y la anterior se va, o no
    ha cambiado nada; no hay un momento intermedio sin fichero. Es de módulo
    para que un test lo haga fallar.
    """
    os.replace(origen, destino)


def borrar(ruta: Path) -> None:
    """Borra un fichero; es de módulo para que un test lo haga fallar."""
    ruta.unlink()


def etiquetas(conflicto: Conflicto) -> list[tuple[Version, str]]:
    """Devuelve cada versión con su nombre para la persona, en el orden del conflicto.

    Nunca el sufijo: `.conflicto-remoto1` es cosa de rclone. Si dos versiones
    se llaman igual (dos conflictos seguidos que perdió el mismo lado) se
    numeran en el orden en que rclone las fue apartando.
    """
    def base(v: Version) -> str:
        """Devuelve el nombre de una versión sin numerar."""
        if v.lado in ETIQUETA_LADO:
            return ETIQUETA_LADO[v.lado]
        return ETIQUETA_ORIGINAL if v.es_original else ETIQUETA_COPIA

    nombres = [base(v) for v in conflicto.versiones]
    salida, vistos = [], {}
    for v, nombre in zip(conflicto.versiones, nombres):
        if nombres.count(nombre) > 1:
            vistos[nombre] = vistos.get(nombre, 0) + 1
            nombre = f"{nombre} ({vistos[nombre]})"
        salida.append((v, nombre))
    return salida


def etiqueta(conflicto: Conflicto, version: Version) -> str:
    """Devuelve el nombre para la persona de esa versión del conflicto."""
    return dict((v.ruta, e) for v, e in etiquetas(conflicto))[version.ruta]


def huella(ruta: Path) -> tuple[int, int] | None:
    """Devuelve `(tamaño, fecha en ns)` del fichero, o `None` si no está."""
    try:
        st = ruta.stat()
    except OSError:
        return None
    return st.st_size, st.st_mtime_ns


def tamano(octetos: int) -> str:
    """Devuelve un tamaño en octetos como texto («12,3 KB»)."""
    valor = float(octetos)
    for unidad in ("B", "KB", "MB", "GB"):
        if valor < 1024 or unidad == "GB":
            break
        valor /= 1024
    texto = f"{valor:.0f}" if unidad == "B" else f"{valor:.1f}".replace(".", ",")
    return f"{texto} {unidad}"


def fecha(ns: int) -> str:
    """Devuelve una fecha en nanosegundos como texto («10/09/2026 18:20»)."""
    return f"{datetime.fromtimestamp(ns / 1e9):%d/%m/%Y %H:%M}"


def describir(ruta: Path) -> str:
    """Devuelve lo que hace falta para elegir: «12,3 KB · 10/09/2026 18:20»."""
    dato = huella(ruta)
    if dato is None:
        return "ya no está"
    return f"{tamano(dato[0])} · {fecha(dato[1])}"


@dataclass
class ResolvePlan:
    """Qué versión se queda con el nombre de verdad y qué se borra.

    `consequences` y `warnings` se enseñan antes de confirmar (mismo contrato
    que `pair_editor.EditPlan`); `execute()` solo se llama si la persona dice
    que sí.

    Args:
        conflicto: El conflicto que se resuelve.
        conserva: La versión que se queda con el nombre de verdad.
        descartar: Las copias que se borran.
        huellas: Tamaño y fecha de cada fichero cuando se pensó el plan.
        consequences: Una línea por consecuencia.
        warnings: Lo que conviene saber antes de confirmar.
    """
    conflicto: Conflicto
    conserva: Version
    descartar: list[Path]
    huellas: dict[Path, tuple[int, int] | None]
    consequences: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def execute(self) -> list[str]:
        """Pone la versión elegida en su sitio, borra lo demás y devuelve qué ha hecho.

        No hace falta deshacer nada, y es por el orden. Lo primero que cambia
        el disco es `mover()`, que es atómico: si falla, no ha cambiado nada.
        Después solo quedan borrados de versiones que se han decidido
        descartar; si alguno falla, la elegida ya está en su sitio y lo que no
        se ha podido borrar sigue teniendo su nombre de conflicto, así que
        vuelve a salir en la lista. El único estado a medias posible es «falta
        por borrar una copia», que no pierde nada y se arregla repitiendo.

        Antes de tocar nada se comprueba que ningún fichero haya cambiado desde
        que se pensó el plan: lo que se confirmó eran esos tamaños y esas
        fechas, no los de ahora.

        Raises:
            ResolucionImposible: Si algo ha cambiado o no se ha podido mover o
                borrar.
        """
        for ruta, antes in self.huellas.items():
            if huella(ruta) != antes:
                raise ResolucionImposible(
                    f"«{ruta.name}» ha cambiado desde que se preparó esto. Vuelve a "
                    f"abrir el conflicto para ver cómo está ahora.")

        original = self.conflicto.original
        hechos: list[str] = []
        if self.conserva.ruta != original:
            try:
                mover(self.conserva.ruta, original)
            except OSError as e:
                raise ResolucionImposible(
                    f"No se ha podido poner «{self.conserva.ruta.name}» como "
                    f"«{original.name}»; no se ha tocado nada.\n\n{e}") from e
            hechos.append(f"«{original.name}» es ahora la "
                          f"{etiqueta(self.conflicto, self.conserva)}")

        fallidos = []
        for ruta in self.descartar:
            try:
                borrar(ruta)
                hechos.append(f"Borrado «{ruta.name}»")
            except FileNotFoundError:
                pass                              # ya no estaba: lo que se quería
            except OSError as e:
                fallidos.append(f"«{ruta.name}»: {e}")
        if fallidos:
            raise ResolucionImposible(
                f"La versión elegida ya está como «{original.name}», pero no se ha "
                f"podido borrar:\n\n" + "\n".join(fallidos) +
                "\n\nSigue apareciendo como conflicto; se puede repetir.")
        return hechos


def puede(conflicto: Conflicto, lado: str) -> bool:
    """Indica si hay UNA versión de ese lado que conservar; habilita cada botón."""
    version = conflicto.version(lado)
    return version is not None and huella(version.ruta) is not None


def plan_lado(conflicto: Conflicto, lado: str) -> ResolvePlan:
    """Devuelve el plan de quedarse con la versión de un lado.

    Es la de este dispositivo o la del remoto.
    """
    version = conflicto.version(lado)
    if version is None:
        raise ResolucionImposible(
            f"No se sabe cuál es la {ETIQUETA_LADO[lado]} de «{conflicto.relativa}»: "
            f"elige una versión concreta de la lista.")
    return plan_conservar(conflicto, version)


def plan_conservar(conflicto: Conflicto, version: Version) -> ResolvePlan:
    """Devuelve el plan de conservar `version` y borrar las demás.

    La elegida se queda con el nombre de verdad.
    """
    if huella(version.ruta) is None:
        raise ResolucionImposible(
            f"«{version.ruta.name}» ya no está: no se puede conservar. Vuelve a "
            f"abrir los conflictos para ver cómo están ahora.")

    rel = conflicto.relativa
    otras = [v for v in conflicto.versiones if v.ruta != version.ruta]
    # El original descartado no se borra: lo sustituye `mover()`, de una vez.
    a_borrar = [v.ruta for v in otras if not v.es_original]
    plan = ResolvePlan(conflicto=conflicto, conserva=version, descartar=a_borrar,
                       huellas={v.ruta: huella(v.ruta) for v in conflicto.versiones})

    nombre = etiqueta(conflicto, version)
    if version.es_original:
        plan.consequences.append(
            f"Se queda «{rel}» tal como está: la {nombre} ({describir(version.ruta)}).")
    else:
        plan.consequences.append(
            f"La {nombre} ({describir(version.ruta)}) pasa a ser «{rel}».")
    for otra in otras:
        texto = f"la {etiqueta(conflicto, otra)} ({describir(otra.ruta)})"
        if otra.es_original:
            plan.consequences.append(f"Sustituye a {texto}, que se pierde.")
        else:
            plan.consequences.append(f"Se borra {texto}.")
    plan.consequences.append("Lo que se descarta se borra del dispositivo, sin papelera.")
    plan.consequences.append(NOTA_LOCAL)

    elegida = huella(version.ruta)
    if any((h := huella(o.ruta)) is not None and elegida is not None and h[1] > elegida[1]
           for o in otras):
        plan.warnings.append(
            "La versión que se descarta es más reciente que la que se conserva. "
            "Comprueba que es la que quieres perder.")
    return plan
