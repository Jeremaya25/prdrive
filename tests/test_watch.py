#!/usr/bin/env python3
"""El adaptador de penwatch: filas de estado y construcción de las órdenes."""

import sys

from _harness import Checks

from common import model
from ui import watch

c = Checks("adaptador de penwatch (ui/watch.py)")

c("penwatch es importable desde la UI", watch.available(), True)

filas = watch.status_rows()
c("status devuelve filas (etiqueta, valor)",
  all(isinstance(f, tuple) and len(f) == 2 for f in filas), True)
etiquetas = [e for e, _ in filas]
for esperada in ("Directorio en el equipo", "Registro en el sistema",
                 "Vigilante", "Pen ahora mismo"):
    c(f"status incluye '{esperada}'", esperada in etiquetas, True)

filas_probe = watch.probe_rows()
c("probe devuelve filas", all(len(f) == 2 for f in filas_probe), True)
c("probe mira en algún sitio", len(filas_probe) > 0, True)
c("y de cada raíz dice qué ha encontrado",
  all(nota.strip() for _, nota in filas_probe), True)

# Que ENCUENTRE el pen solo se puede exigir si de verdad hay uno montado, y no lo
# hay en los dos casos que más se dan: desarrollando sobre una copia en disco, y
# con un pen VeraCrypt cuyo contenedor no está montado (ahí el fichero PEREPEN
# vive dentro del contenedor, así que la raíz del pen físico no lo tiene).
if any("PEREPEN OK" in nota for _, nota in filas_probe):
    c("probe encuentra el pen montado", True, True)
else:
    print("  (saltado) no hay ningún pen montado ahora mismo: "
          + "; ".join(f"{raiz} {nota}" for raiz, nota in filas_probe))

c("log_tail devuelve una lista", isinstance(watch.log_tail(), list), True)
c("is_installed responde un booleano", isinstance(watch.is_installed(), bool), True)


# --- construcción de órdenes -------------------------------------------------
def sin_python(cmd):
    """Quita el intérprete y la ruta al script: lo que importa son los flags."""
    c("la orden apunta a penwatch.py", cmd[1], str(model.PENWATCH_PY))
    return cmd[2:]


c("instalación por defecto", sin_python(watch.install_command()),
  ["install", "--mode", "ui"])

c("modo daemon con intervalo y parejas",
  sin_python(watch.install_command(mode="daemon", interval=15,
                                   pairs=["keepass", "obsidian"])),
  ["install", "--mode", "daemon", "--interval", "15", "--pairs", "keepass", "obsidian"])

c("--pairs va el último para no comerse lo que venga detrás",
  sin_python(watch.install_command(mode="sync", pairs=["a"], poll=3,
                                    extra_roots=["/mnt/pen"], start=False))[-3:],
  ["--no-start", "--pairs", "a"])

c("las raíces extra se repiten como flag",
  "--extra-root" in watch.install_command(extra_roots=["/mnt/uno", "/mnt/dos"]), True)

c("los valores vacíos no ensucian la orden",
  sin_python(watch.install_command(pairs=["", "  "], extra_roots=[" "])),
  ["install", "--mode", "ui"])

c("desinstalar", sin_python(watch.uninstall_command()), ["uninstall"])

sys.exit(c.report())
