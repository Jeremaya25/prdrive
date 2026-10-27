#!/usr/bin/env python3
"""El catálogo de errores de rclone (`common/errores.py`): qué reconoce y qué no.

Las líneas con que se prueba son las de `tests/_logs_errores.py`: logs de verdad del
rclone fijado o frases de su código fuente, nunca inventadas. Un error sin
reconocer tiene que dar `None`: una explicación equivocada es peor que ninguna.
"""

import contextlib
import io
import os
import re
import sys

from _harness import Checks, sandbox
from _logs_errores import (ABORTO, CAPTURADA, CUOTA_DESCARGA, FILTROS_CAMBIADOS, FUENTE,
                           LINEAS, SFTP_AUTENTICACION, SIN_SECCION)
from _logs_frenos import BISYNC_BORRADOS, ESPEJO_UP

import sync
from common import errores, moderacion, pins

c = Checks("el catálogo de errores de rclone")


def clave(texto):
    """Devuelve la clave de la causa de ese texto, o `None`."""
    causa = errores.clasificar(texto)
    return None if causa is None else causa.clave


# ---- Cada línea da su clave ------------------------------------------------------------

for texto, esperada, procedencia in LINEAS:
    primera = next(l for l in texto.splitlines() if "ERROR" in l or "Error" in l
                   or "CRITICAL" in l or "NOTICE" in l)
    c(f"{esperada} ({procedencia}): {primera[20:80]}…", clave(texto), esperada)
c("cada línea dice su procedencia",
  {p for _, _, p in LINEAS} <= {CAPTURADA, FUENTE}, True)
c("toda causa del catálogo tiene al menos una línea que la pruebe, salvo las de Windows",
  {causa.clave for _, causa in errores.ENTRADAS}
  - {k for _, k, _ in LINEAS} - {"en_uso", "known_hosts", "critico"}, set())

# ---- Lo que NO se puede confundir ------------------------------------------------------

c("un SFTP que rechaza la clave es autenticación, no red",
  clave(SFTP_AUTENTICACION), "autenticacion")
c("  aunque `moderacion` (el agente) lo cuente como de red: es otro issue",
  moderacion.es_de_red(SFTP_AUTENTICACION), True)
EINVAL = ("2026/10/27 10:00:00 ERROR : nota?.md: Failed to copy: open "
          "/media/usb/sync-data/notas/nota?.md: invalid argument\n")
c("un EINVAL suelto (un nombre que exFAT no admite) no es un flag mal puesto",
  clave(EINVAL), None)
DISPERSO = ("2026/10/27 10:00:00 ERROR : grande.bin: Failed to set sparse: FSCTL_SET_SPARSE: "
            "Incorrect function.\n")
c("el ruido de exFAT con los ficheros dispersos no es nada", clave(DISPERSO), None)
c("un texto desconocido no es nada",
  clave("2026/10/27 10:00:00 ERROR : algo que rclone no ha dicho nunca\n"), None)
c("un texto vacío tampoco", clave(""), None)
c("la cuota de DESCARGA de Google no es un remoto lleno", clave(CUOTA_DESCARGA), None)
c("los frenos de borrados no son de este catálogo (los reconoce `frenos`, antes)",
  (clave(BISYNC_BORRADOS), clave(ESPEJO_UP)), (None, None))
c("el «Attempt N/N failed» solo no es una causa",
  clave("2026/10/27 10:00:00 ERROR : Attempt 3/3 failed with 1 errors and: algo\n"), None)

# ---- El orden: lo concreto gana --------------------------------------------------------

c("el aborto crítico solo es `critico`", clave(ABORTO), "critico")
c("los filtros (que llevan «must run --resync») ganan a `critico`",
  (clave(FILTROS_CAMBIADOS), clave(FILTROS_CAMBIADOS + ABORTO)), ("filtros", "filtros"))
c("  y el log de los filtros también casa con la aguja de `critico`",
  errores.casa("Must run --resync", FILTROS_CAMBIADOS), True)
c("una causa concreta gana a `sin_extremo`",
  (errores.casa("Failed to create file system", SIN_SECCION), clave(SIN_SECCION)),
  (True, "sin_seccion"))
c("las agujas de texto no distinguen mayúsculas",
  clave("ERROR : open x: PERMISSION DENIED\n"), "permiso")
c("las expresiones regulares, sí: el valor de un flag es el texto de pflag",
  clave('Error: invalid argument "x" for "--checkers" flag\n'), "flag_valor")

# ---- El catálogo ------------------------------------------------------------------------


def version(texto):
    """Devuelve `v1.75.2` como `(1, 75, 2)`."""
    return tuple(int(n) for n in re.findall(r"\d+", texto))


causas = [causa for _, causa in errores.ENTRADAS]
c("toda causa está comprobada con una versión de rclone que no es posterior a la fijada",
  [k.clave for k in causas if version(k.comprobado) > version(pins.RCLONE_VERSION)], [])
c("las claves no se repiten", len({k.clave for k in causas}), len(causas))
c("los arreglos son de los que existen",
  [k.clave for k in causas if not set(k.arreglos) <= errores.ARREGLOS], [])
c("«reintentar» solo para la red, el límite de la API y el fichero en uso",
  sorted(k.clave for k in causas if errores.REINTENTAR in k.arreglos),
  ["en_uso", "limite_api", "red"])
c("ningún arreglo es `--force`",
  any("force" in a for k in causas for a in k.arreglos), False)
c("toda causa dice su riesgo y algo que hacer (un arreglo o un paso a mano)",
  [k.clave for k in causas if not k.riesgo or not (k.arreglos or k.a_mano)], [])
c("la carpeta que falta no se aconseja crear vacía",
  "crea" in (errores.CARPETA_REMOTA.a_mano or "").lower(), False)
c("la red dice lo mismo que el agente", errores.RED.explicacion,
  moderacion.EXPLICACION_RED)

# ---- La consola: el mismo texto -------------------------------------------------------


def explicar(texto):
    """Devuelve lo que `sync.explain_failure()` dice de un log con ese texto."""
    with sandbox():
        log = sync.temp_log("errores")
        log.write_text(texto, encoding="utf-8")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            sync.explain_failure(log)
        log.unlink(missing_ok=True)
        return buf.getvalue()


for texto, esperada, _ in LINEAS:
    causa = errores.clasificar(texto)
    c(f"la consola explica `{esperada}` con el texto del catálogo",
      explicar(texto).strip(), f">> {causa.texto}")
c("la consola no explica un EINVAL suelto", explicar(EINVAL), "")
c("KNOWN_ERRORS lleva los frenos tras los filtros",
  [i for i, (_, e) in enumerate(sync.KNOWN_ERRORS) if e == errores.FILTROS.texto][-1] + 1,
  next(i for i, (_, e) in enumerate(sync.KNOWN_ERRORS)
       if e == sync.frenos.EXPLICACION_BORRADOS))
c("las agujas de texto que buscan otros tests siguen ahí",
  {"Failed to create file system", "Must run --resync", "filters file has changed"}
  <= {a for a, _ in sync.KNOWN_ERRORS if isinstance(a, str)}, True)

# ---- La última línea de error, tal cual ------------------------------------------------

c("la última línea de error, sin la fecha",
  errores.ultima_linea_de_error(SIN_SECCION),
  'CRITICAL: Failed to create file system for "nohay:/x": didn\'t find section in config '
  'file ("nohay")')
c("sin línea de error, nada",
  errores.ultima_linea_de_error("2026/10/27 10:00:00 INFO  : todo bien\n"), None)
larga = errores.ultima_linea_de_error("2026/10/27 10:00:00 ERROR : " + "x" * 500 + "\n")
c("una línea larga se recorta", (len(larga), larga.endswith("…")),
  (errores.TOPE_LINEA, True))

# ---- Los textos de Windows: los da el propio sistema ------------------------------------

AGUJAS_WINDOWS = {
    5: ("Access is denied", "Acceso denegado"),
    32: ("being used by another process", "está siendo utilizado por otro proceso"),
    112: ("There is not enough space on the disk", "No hay espacio suficiente en el disco"),
    123: ("The filename, directory name, or volume label syntax is incorrect",
          "La sintaxis del nombre de archivo"),
}
"""Código de Windows → (aguja inglesa, aguja española) del catálogo."""
todas = {a for agujas, _ in errores.ENTRADAS for a in agujas if isinstance(a, str)}
c("las agujas de Windows, en inglés y en español, están en el catálogo",
  {a for par in AGUJAS_WINDOWS.values() for a in par} <= todas, True)
c("y cada una da la causa de su código",
  [clave(a) for codigo in (5, 32, 112, 123) for a in AGUJAS_WINDOWS[codigo]],
  ["en_uso"] * 4 + ["disco_lleno"] * 2 + ["nombre_invalido"] * 2)

if os.name == "nt":
    import ctypes

    idioma = ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF  # el idioma primario
    lado = {0x09: 0, 0x0A: 1}.get(idioma)
    if lado is None:
        print(f"  (saltado) FormatError en un Windows que no es inglés ni español ({idioma:#x})")
    else:
        for codigo, agujas in AGUJAS_WINDOWS.items():
            mensaje = ctypes.FormatError(codigo)
            c(f"FormatError({codigo}) lleva su aguja: {mensaje}",
              agujas[lado].lower() in mensaje.lower(), True)
else:
    print("  (saltado) los textos de FormatError solo se pueden pedir en Windows")

sys.exit(c.report())
