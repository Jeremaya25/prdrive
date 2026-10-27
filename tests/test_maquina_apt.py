#!/usr/bin/env python3
"""`tests/maquina/comun.apt()`: un paquete que no se pudo instalar no se vuelve a esperar.

En las máquinas de GitHub cuyo núcleo no trae exFAT, `apt-get install
linux-modules-extra-<núcleo>` puede agotar sus 600 s. Antes cada prueba que pedía
exFAT lo volvía a intentar, y tres esperas bastaban para agotar los 30 min del
trabajo «maquina (ubuntu-latest)», que salía cancelado sin ningún fallo de verdad.
Aquí `ejecutar()` es de mentira: no se instala ni se toca nada.
"""

from __future__ import annotations

import sys
from types import SimpleNamespace

from _harness import Checks, REPO

sys.path.insert(0, str(REPO / "tests" / "maquina"))
import comun  # noqa: E402

LLAMADAS: list[list[str]] = []
INSTALA_BIEN: set[str] = set()


def ejecutar(cmd, timeout=180, entrada=None, callado=False, **_):
    """Hace de `comun.ejecutar()`: nada está instalado y solo `INSTALA_BIEN` se instala."""
    LLAMADAS.append(list(cmd))
    if cmd[:2] == ["dpkg", "-s"]:
        return SimpleNamespace(returncode=1, stdout="", stderr="")
    if cmd[:2] == ["apt-get", "install"]:
        paquetes = [p for p in cmd[2:] if not p.startswith("-")]
        return SimpleNamespace(returncode=0 if set(paquetes) <= INSTALA_BIEN else 100,
                               stdout="", stderr="")
    return SimpleNamespace(returncode=0, stdout="", stderr="")


def instalaciones() -> int:
    """Cuántas veces se ha llamado a `apt-get install`."""
    return sum(1 for c in LLAMADAS if c[:2] == ["apt-get", "install"])


def salta(*paquetes: str) -> str | None:
    """El motivo de `Saltada` de `comun.apt()`, o `None` si no salta."""
    try:
        comun.apt(*paquetes)
    except comun.Saltada as e:
        return str(e)
    return None


def main() -> int:
    """Comprueba que un fallo de `apt-get install` se recuerda en la ejecución."""
    c = Checks("maquina: apt() no vuelve a esperar un paquete que ya falló")
    comun.ejecutar = ejecutar
    comun._apt_al_dia = False
    comun._apt_fallidos.clear()

    MODULOS = "linux-modules-extra-6.17.0-1022-azure"
    primera = salta(MODULOS)
    c("la primera vez se intenta y salta", (instalaciones(), primera is not None), (1, True))
    segunda = salta(MODULOS)
    c("la segunda no vuelve a llamar a apt-get install", instalaciones(), 1)
    c("  y salta diciendo que ya falló", "ya falló antes" in (segunda or ""), True)
    c("  ni vuelve a hacer apt-get update",
      sum(1 for x in LLAMADAS if x[:2] == ["apt-get", "update"]), 1)

    INSTALA_BIEN.add("nfs-common")
    c("otro paquete sí se intenta, y si se instala no salta", salta("nfs-common"), None)
    c("  con su propia llamada", instalaciones(), 2)
    return c.report()


if __name__ == "__main__":
    sys.exit(main())
