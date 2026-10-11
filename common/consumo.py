#!/usr/bin/env python3
"""Lo que el agente gasta en cada unidad, día a día: para verlo, no para decidir nada.

El agente apunta aquí cada pasada que termina (`apuntar()`), en su carpeta del
equipo (`consumo.json`) y nunca en la unidad: cuántas lanzó, cuántas no
encontraron nada que hacer, cuántos procesos fueron, cuánto duraron y cuántos
bytes reescribieron en la unidad. `agente.py status` lo enseña (`texto()`). Es
la manera de saber, en un equipo de verdad, si una unidad quieta cuesta lo que
dice el diseño (`docs/superpowers/specs/2026-10-11-watch-y-energia-hoja-de-ruta-design.md`).

Se guardan los últimos `DIAS` días. Un fichero que falta o está roto es «no hay
cuentas»: nada depende de él.
"""

from __future__ import annotations

from datetime import date
from typing import NamedTuple

from common import equipo, store

FICHERO = "consumo.json"
DIAS = 14
"""Cuántos días se guardan."""


class Cuenta(NamedTuple):
    """Lo gastado en una unidad en un día.

    Args:
        pasadas: Los `sync.py` lanzados que acabaron.
        vacias: Los que fueron bien y no movieron nada (`parte.Parte.vacia`).
        procesos: Los procesos que fueron: cada `sync.py` y cada rclone suyo.
        segundos: Lo que estuvieron vivos, en total.
        escrito: Bytes de sus bases de bisync que reescribieron en la unidad.
    """
    pasadas: int = 0
    vacias: int = 0
    procesos: int = 0
    segundos: float = 0.0
    escrito: int = 0

    def mas(self, otra: "Cuenta") -> "Cuenta":
        """Devuelve la suma de las dos."""
        return Cuenta(*(a + b for a, b in zip(self, otra)))


def hoy() -> str:
    """Devuelve el día de hoy como se apunta: `2026-10-11`."""
    return date.today().isoformat()


def _cuenta(d: object) -> Cuenta:
    """Lee una cuenta de lo que hubiera en el fichero; lo que no vale es cero."""
    if not isinstance(d, dict):
        return Cuenta()
    valores = []
    for campo, tipo in zip(Cuenta._fields, (int, int, int, float, int)):
        try:
            valores.append(max(tipo(d.get(campo) or 0), tipo(0)))
        except (TypeError, ValueError):
            valores.append(tipo(0))
    return Cuenta(*valores)


def leer() -> dict[str, dict[str, Cuenta]]:
    """Devuelve las cuentas guardadas: `{día: {id de la unidad: Cuenta}}`."""
    dias = store.read_json(equipo.DIR / FICHERO).get("dias")
    if not isinstance(dias, dict):
        return {}
    return {str(dia): {str(uid): _cuenta(c) for uid, c in unidades.items()}
            for dia, unidades in dias.items() if isinstance(unidades, dict)}


def apuntar(uid: str, cuenta: Cuenta, dia: str | None = None) -> None:
    """Suma `cuenta` a lo gastado hoy en esa unidad y tira los días viejos.

    No lanza: lo que no se pueda apuntar se pierde y la pasada no se entera.
    """
    dia = dia or hoy()
    dias = leer()
    de_hoy = dias.setdefault(dia, {})
    de_hoy[uid] = de_hoy.get(uid, Cuenta()).mas(cuenta)
    guardar = {d: {u: {**c._asdict(), "segundos": round(c.segundos, 1)}
                   for u, c in unidades.items()}
               for d, unidades in sorted(dias.items())[-DIAS:]}
    try:
        store.write_json(equipo.DIR / FICHERO, {"dias": guardar})
    except OSError:
        pass


def del_dia(uid: str, dia: str | None = None) -> Cuenta:
    """Devuelve lo gastado en esa unidad ese día (hoy, si no se dice)."""
    return leer().get(dia or hoy(), {}).get(uid, Cuenta())


def _tamano(octetos: int) -> str:
    """Devuelve un tamaño como lo enseña el resto de la interfaz: «1,1 MB»."""
    valor = float(octetos)
    for unidad in ("B", "KB", "MB", "GB"):
        if valor < 1024 or unidad == "GB":
            break
        valor /= 1024
    return f"{valor:.0f} {unidad}" if unidad == "B" else f"{valor:.1f} {unidad}".replace(".", ",")


def texto(cuenta: Cuenta) -> str:
    """Devuelve la cuenta en una línea: «212 pasadas (198 sin nada que hacer), 424 procesos, 131 s, 41,0 MB reescritos en la unidad»."""
    if not cuenta.pasadas:
        return "ninguna pasada"
    partes = [f"{cuenta.pasadas} pasada{'s' if cuenta.pasadas != 1 else ''}"
              + (f" ({cuenta.vacias} sin nada que hacer)" if cuenta.vacias else ""),
              f"{cuenta.procesos} procesos", f"{cuenta.segundos:.0f} s"]
    if cuenta.escrito:
        partes.append(f"{_tamano(cuenta.escrito)} reescritos en la unidad")
    return ", ".join(partes)
