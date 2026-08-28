#!/usr/bin/env python3
"""
La arquitectura del equipo y el bin/ que le toca.

Windows on ARM ejecuta los binarios x64 emulados y les miente: `platform.machine()`
contesta 'AMD64' en un Snapdragon. Como el instalador es un .exe x64 y el
`runsync.py` del dispositivo corre con el Python del equipo —ARM64 nativo en un
portátil ARM—, los dos lados sacaban respuestas distintas: uno dejaba rclone en
`bin/x64` y el otro lo buscaba en `bin/arm`.

Lo que se comprueba aquí es esa coincidencia, no la tabla por separado: la
carpeta que elige el dispositivo y el zip que descarga el instalador tienen que
hablar de la MISMA CPU. No hace falta un equipo ARM para preguntarlo, porque la
sonda del sistema —`model.maquina_nativa_windows()`— es una función de módulo y
se sustituye.
"""

import sys
from pathlib import Path

from _harness import Checks, tmpdir

from common import model
from install import rclone_bin

c = Checks("arquitectura: equipo, bin/ y zip de rclone")

IMAGE_FILE_MACHINE_ARM64 = 0xAA64
IMAGE_FILE_MACHINE_AMD64 = 0x8664
IMAGE_FILE_MACHINE_I386 = 0x014C


# --- La sonda manda sobre platform.machine() --------------------------------
#
# El caso del bug: un proceso x64 emulado en un ARM64. platform.machine() dice
# 'AMD64' y hay que ignorarlo.
original_sonda = model.maquina_nativa_windows
try:
    model.maquina_nativa_windows = lambda: IMAGE_FILE_MACHINE_ARM64
    c("equipo ARM64: machine_arch lo dice aunque platform mienta",
      model.machine_arch(), "arm64")
    c("equipo ARM64: el dispositivo mira bin/arm", model.arch_dir(), "arm")
    c("equipo ARM64: el instalador baja el zip arm64", rclone_bin.os_arch()[1], "arm64")
    c("equipo ARM64: y lo deja donde el dispositivo mira",
      rclone_bin.bin_subdir(), model.arch_dir())

    model.maquina_nativa_windows = lambda: IMAGE_FILE_MACHINE_AMD64
    c("equipo x64: bin/x64", model.arch_dir(), "x64")
    c("equipo x64: zip amd64", rclone_bin.os_arch()[1], "amd64")

    model.maquina_nativa_windows = lambda: IMAGE_FILE_MACHINE_I386
    c("equipo x86: bin/x64", model.arch_dir(), "x64")
    c("equipo x86: zip 386", rclone_bin.os_arch()[1], "386")

    # Sin respuesta de la sonda (Linux, macOS, Windows anterior a 1709) se
    # vuelve a platform.machine(), que allí no miente.
    model.maquina_nativa_windows = lambda: None
    c("sin sonda: cae en platform.machine()",
      model.machine_arch(), __import__("platform").machine().lower())
finally:
    model.maquina_nativa_windows = original_sonda


# --- La carpeta y el zip no pueden describir CPUs distintas ------------------
#
# Ésta es la comprobación que habría cazado el bug: las dos tablas viven en
# ficheros distintos (model.arch_dir y rclone_bin.os_arch) y nada las ataba.
PAREJAS = {"arm": {"arm64", "arm"}, "x64": {"amd64", "386"}}
original_model = model.machine_arch
original_bin = rclone_bin.machine_arch
try:
    for maquina in ("arm64", "aarch64", "aarch64_be", "armv7l", "amd64",
                    "x86_64", "x64", "i386", "i686", "x86", "loongarch64"):
        model.machine_arch = rclone_bin.machine_arch = lambda m=maquina: m
        carpeta = model.arch_dir()
        _, zip_arch = rclone_bin.os_arch()
        c(f"'{maquina}': bin/{carpeta} y zip {zip_arch} son la misma CPU",
          zip_arch in PAREJAS[carpeta], True)
finally:
    model.machine_arch = original_model
    rclone_bin.machine_arch = original_bin


# --- Un dispositivo ya provisionado con la carpeta equivocada ----------------
#
# Los que instaló la versión con el bug tienen el rclone en bin/x64 y nada en
# bin/arm. Un ARM64 ejecuta los x64 emulados, así que ahí se tira de lo que hay
# en vez de quedarse sin rclone; al revés no, porque un x64 no ejecuta ARM.
raiz = tmpdir()
(raiz / "bin" / "x64").mkdir(parents=True)
(raiz / "bin" / "x64" / model.rclone_name()).write_bytes(b"MZ")

originales = (model.BIN_DIR, model.BIN_FALLBACK_DIRS)
try:
    model.BIN_DIR = raiz / "bin" / "arm"
    model.BIN_FALLBACK_DIRS = (raiz / "bin" / "x64",)
    c("ARM sin bin/arm: usa el x64 que hay",
      model.rclone_path(), raiz / "bin" / "x64" / model.rclone_name())

    (raiz / "bin" / "arm").mkdir(parents=True)
    (raiz / "bin" / "arm" / model.rclone_name()).write_bytes(b"MZ")
    c("ARM con bin/arm: prefiere el suyo",
      model.rclone_path(), raiz / "bin" / "arm" / model.rclone_name())

    model.BIN_DIR = raiz / "bin" / "x64"
    model.BIN_FALLBACK_DIRS = ()
    c("x64 no tiene recambio: no mira bin/arm",
      model.rclone_path(), raiz / "bin" / "x64" / model.rclone_name())

    model.BIN_DIR = raiz / "bin" / "vacio"
    c("sin ningún binario: None, no una ruta inventada", model.rclone_path(), None)
finally:
    model.BIN_DIR, model.BIN_FALLBACK_DIRS = originales


# --- La caché de descargas va por arquitectura ------------------------------
#
# Si fuera una sola, el rclone de amd64 que dejó el instalador con el bug se
# reutilizaría para siempre y la URL corregida no llegaría a usarse nunca.
original_model = model.machine_arch
try:
    model.machine_arch = lambda: "arm64"
    cache_arm = rclone_bin.cache_dir()
    model.machine_arch = lambda: "amd64"
    cache_x64 = rclone_bin.cache_dir()
    c("la caché no mezcla arquitecturas", cache_arm != cache_x64, True)
    c("y cada una cuelga de su bin/", cache_arm.name, "arm")
    c("la otra también", cache_x64.name, "x64")
finally:
    model.machine_arch = original_model

sys.exit(c.report())
