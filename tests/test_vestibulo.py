#!/usr/bin/env python3
"""
El vestíbulo: lo que un dispositivo VeraCrypt deja FUERA del contenedor.

Sin él, abrir el dispositivo en otro equipo era cosa de saber que había que abrir
VeraCrypt, elegir `PRDRIVE.hc`, una letra y la contraseña, y la guía que lo
explicaba estaba dentro del contenedor. Lo que se comprueba:

  * Los `.bat` hacen lo que el código de VeraCrypt dice que hay que hacer (la
    orden de montar sin contraseña, el instalado antes que el que viaja,
    `/dismount` y no `/unmount`, sin `/silent` al cerrar), y siguen las reglas de
    `runsync.bat`: CRLF, sin bloques entre paréntesis, `chcp 65001` antes de
    cualquier acento. No se pueden ejecutar aquí: se lee su texto.
  * Los `.sh` sí se ejecutan (con sh, y con dash y bash si están), contra un
    `veracrypt`, un `udisksctl` y un `cryptsetup` de mentira que «montan» en un
    sistema de juguete: el orden de las vías (VeraCrypt > udisks2 con
    tcrypt.conf > cryptsetup > el mensaje), reconocer lo ya abierto, no
    confundirse de dispositivo, cerrar con lo mismo que abrió deduciéndolo del
    estado, y que la contraseña no aparezca nunca en una línea de órdenes. Nada
    toca una unidad de verdad, ni un sudo de verdad.
  * La marca une las dos mitades: el mismo id que el fichero de control.
  * Los nombres nuevos están en `device.RUIDO`, o un dispositivo recién hecho se
    leería como ajeno la vez siguiente.
"""

import os
import shutil
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

from _harness import Checks, tmpdir

from common import vestibulo as v
from install import CONTAINER_NAME, IS_WIN, device, vestibulo

c = Checks("vestíbulo: la entrada de un dispositivo VeraCrypt")

ID = "3f9c1a2b4d5e6f708192a3b4c5d6e7f8"

# --- 1. los nombres, una sola vez ----------------------------------------------
c("el contenedor de common y el de install son el mismo", v.CONTENEDOR, CONTAINER_NAME)
c("la marca empieza por punto: oculta en POSIX", v.MARCA.startswith("."), True)
for nombre in v.TODOS:
    c(f"«{nombre}» no cuenta como contenido ajeno", nombre.lower() in device.RUIDO, True)


# --- 2. los .bat ---------------------------------------------------------------
def lineas_de_orden(texto):
    return [ln for ln in texto.splitlines()
            if ln.strip() and not ln.lower().startswith(("rem", "echo"))]


def sin_bloques(texto) -> bool:
    """Ningún paréntesis fuera del conjunto de letras del `for`.

    Es la regla de `runsync.bat`: una ruta con «)» —`%~dp0` puede traerla—
    rompe cualquier bloque entre paréntesis."""
    for ln in lineas_de_orden(texto):
        ln = ln.replace("(C D E F G H I J K L M N O P Q R S T U V W X Y Z A B)", "")
        if "(" in ln or ")" in ln:
            return False
    return True


def acentos_tras_chcp(texto) -> bool:
    """Todo lo que no es ASCII va después de un `chcp 65001` de su mismo bloque."""
    utf8 = False
    for ln in texto.splitlines():
        if ln.startswith(":"):
            utf8 = False
        elif ln.strip() == "chcp 65001 >nul":
            utf8 = True
        elif not ln.isascii() and not utf8:
            return False
    return True


abrir = vestibulo.bat_abrir(ID)
expulsar = vestibulo.bat_expulsar(ID)
for nombre, texto in (("abrir", abrir), ("expulsar", expulsar)):
    c(f"{nombre}: sin bloques entre paréntesis", sin_bloques(texto), True)
    c(f"{nombre}: ni un acento antes de chcp 65001", acentos_tras_chcp(texto), True)
    c(f"{nombre}: lleva el id del dispositivo", f'set "ID={ID}"' in texto, True)
    c(f"{nombre}: lo busca por el fichero de control, no por letra",
      'findstr /b /l /c:"id=%ID%" "%%L:\\.prdrive\\PRDRIVE"' in texto, True)
    c(f"{nombre}: su directorio de trabajo, fuera del contenedor",
      'cd /d "%~dp0"' in texto, True)
    c(f"{nombre}: la contraseña no pasa por aquí",
      any(x in ln.lower().split() for ln in lineas_de_orden(texto)
          for x in ("/password", "/p")), False)
    instalado = texto.index('"%ProgramFiles%\\VeraCrypt\\VeraCrypt.exe"')
    viajero = texto.index('"%~dp0VeraCrypt\\VeraCrypt.exe"')
    c(f"{nombre}: el VeraCrypt instalado antes que el que viaja "
      "(ERR_DRIVER_VERSION)", instalado < viajero, True)

orden = next(ln for ln in abrir.splitlines() if "/volume" in ln)
c("abrir: monta este contenedor, junto al .bat",
  f'/volume "%~dp0{CONTAINER_NAME}"' in orden, True)
c("abrir: como medio extraíble", "/mountoption rm" in orden, True)
c("abrir: con /quit, que con /volume ya monta y sale", orden.endswith("/quit"), True)
c("abrir: sin /auto, que además abre el Explorador", "/auto" in orden, False)
c("abrir: sin guardar el contenedor en el historial ni la contraseña en caché",
  ("/history n" in orden, "/cache n" in orden), (True, True))
c("abrir: espera a que VeraCrypt termine", orden.startswith('start "" /wait'), True)
c("abrir: con el que viaja espera más (se relanza elevado y sale con 0)",
  f'if defined VIAJERO set "ESPERA={vestibulo.ESPERA_VIAJERO}"' in abrir, True)
c("abrir: lanza el runsync.bat de DENTRO", 'call "%RAIZ%\\runsync.bat"' in abrir, True)

orden = next(ln for ln in expulsar.splitlines() if "/dismount" in ln)
c("expulsar: /dismount de la letra encontrada, que aceptan todas las versiones",
  "/dismount %RAIZ:~0,1% /quit" in orden, True)
c("expulsar: nunca /unmount, que no existe antes de la 1.26.24",
  "/unmount" in expulsar, False)
c("expulsar: sin /silent, para que VeraCrypt pregunte si forzar",
  any(x in ln.split() for ln in lineas_de_orden(expulsar) for x in ("/silent", "/s")),
  False)
c("expulsar: espera antes a que la ventana que lo llama se cierre",
  expulsar.index("timeout /t 3") < expulsar.index("/dismount"), True)


def bloque(texto, etiqueta):
    """Las líneas de `:etiqueta` hasta la siguiente etiqueta."""
    lineas = texto.splitlines()
    if f":{etiqueta}" not in lineas:
        return []
    desde = lineas.index(f":{etiqueta}") + 1
    hasta = next((i for i in range(desde, len(lineas)) if lineas[i].startswith(":")),
                 len(lineas))
    return lineas[desde:hasta]


def precedida(texto, orden, antes):
    """¿Hay alguna línea con `orden`, y va cada una justo detrás de un `antes`?"""
    lineas = [ln for ln in texto.splitlines() if ln.strip()]
    donde = [i for i, ln in enumerate(lineas) if orden in ln]
    return bool(donde) and all(lineas[i - 1] == antes for i in donde)


# Tras forzar el cierre con un fichero abierto dentro, la letra se va y Windows
# sigue sin dejar quitar la unidad: el contenedor sigue retenido (G4b y H-6 en
# docs/superpowers/pruebas/…-resultados.md). Que se vaya la letra no basta.
sin_contenedor = f'if not exist "%~dp0{CONTAINER_NAME}" goto cerrado'
c("expulsar: «ya puedes quitar la unidad» solo tras ver el contenedor suelto",
  precedida(expulsar.replace(sin_contenedor + "\n", ""), "goto cerrado", "call :libre"),
  True)
c("expulsar: o si no hay contenedor al lado que mirar (un .bat copiado a otro sitio)",
  sin_contenedor in bloque(expulsar, "sin_letra"), True)
c("expulsar: y «ya estaba cerrado» tampoco sin mirarlo",
  bloque(expulsar, "ya_cerrado")[:1], ["call :libre"])
retenido = "\n".join(bloque(expulsar, "retenido"))
c.contains("expulsar: retenido, dice que no se quite", retenido, "Windows no")
c("expulsar: y no dice que se pueda", "puedes quitar la unidad." in retenido, False)

# Con el VeraCrypt que viaja, el que lanzamos sale a los dos segundos y es la
# copia elevada la que pregunta si forzar: los 30 intentos se gastaban esperando
# esa respuesta, y la consola decía «sigue abierto» con la pregunta todavía en
# pantalla (G4b en la vuelta a G:, #41). Mientras viva un VeraCrypt que no estaba
# antes, se espera sin gastar intentos; si ya había uno (en segundo plano), no
# se sabe cuál es el nuestro y se cuenta como siempre.
def despues(lineas, orden):
    """La línea que sigue a `orden`, o None."""
    return lineas[lineas.index(orden) + 1] if orden in lineas[:-1] else None


esperar = bloque(expulsar, "esperar")
c("expulsar: mira si ya había un VeraCrypt antes de lanzar el suyo",
  "VC_ANTES" in expulsar and expulsar.index("VC_ANTES") < expulsar.index("/dismount"),
  True)
c("expulsar: mientras VeraCrypt siga con lo suyo, espera sin gastar intentos",
  (despues(esperar, "call :vc_pendiente"),
   "call :vc_pendiente" in esperar
   and esperar.index("call :vc_pendiente") < esperar.index("set /a INTENTOS+=1")),
  ("if not errorlevel 1 goto esperar_vc", True))
c("expulsar: y esperar sin contar vuelve a mirar la letra",
  bloque(expulsar, "esperar_vc")[:2], ["timeout /t 1 /nobreak >nul", "goto esperar"])
c("expulsar: con uno de antes vivo, no se puede saber cuál es el suyo: se cuenta",
  bloque(expulsar, "vc_pendiente")[:1], ["if defined VC_ANTES exit /b 1"])

libre = bloque(expulsar, "libre")
c("comprobar el contenedor no lo crea si no está",
  libre[:1], [f'if not exist "%~dp0{CONTAINER_NAME}" exit /b 1'])
c("ni escribe nada en él", any(f'>>"%~dp0{CONTAINER_NAME}" type nul' in ln
                               for ln in bloque(expulsar, "tocar")), True)

# Desenchufada sin expulsar, la letra de dentro se queda (un fantasma que sirve
# el fichero de control de la caché), y «Abrir» lanzaba prdrive desde él (H1 y
# H-10). Con el volumen de verdad montado, el contenedor está retenido.
antes_de_montar = abrir[:abrir.index("/volume")]
c("abrir: antes de lanzar lo encontrado, mira que el contenedor esté abierto",
  precedida(antes_de_montar, "goto lanzar", "call :libre"), True)
fantasma = "\n".join(bloque(abrir, "fantasma"))
c("abrir: un fantasma no se lanza", "runsync" in fantasma, False)
c.contains("abrir: y se dice cómo salir", fantasma, vestibulo.NOMBRE_EXPULSAR)
c("abrir: comprueba igual que expulsar", (bool(libre), bloque(abrir, "libre")),
  (True, libre))

if IS_WIN:
    # La subrutina tal cual sale del texto, contra un contenedor de verdad: suelto,
    # retenido en exclusiva como lo retiene el driver, y sin contenedor.
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = wintypes.HANDLE
    prueba = tmpdir("prdrive-libre-")
    hc = prueba / CONTAINER_NAME
    hc.write_bytes(b"contenido")
    bat = prueba / "libre.bat"
    bat.write_text("@echo off\r\ncall :libre\r\necho %ERRORLEVEL%\r\nexit /b 0\r\n"
                   + "\r\n".join(["", ":libre", *libre, "", ":tocar",
                                  *bloque(expulsar, "tocar")]) + "\r\n",
                   encoding="ascii")

    def correr():
        r = subprocess.run(["cmd", "/c", str(bat)], capture_output=True, text=True)
        return (r.stdout + r.stderr).strip()

    c("un contenedor suelto da 0", correr(), "0")
    h = k32.CreateFileW(str(hc), 0xC0000000, 0, None, 3, 0x80, None)
    try:
        c("retenido en exclusiva da 1, sin mensajes de cmd", correr(), "1")
    finally:
        k32.CloseHandle(h)
    c("y el contenedor no ha cambiado", hc.read_bytes(), b"contenido")
    hc.unlink()
    c("sin contenedor da 1", correr(), "1")
    c("y no lo crea", hc.exists(), False)

    # `:vc_pendiente` y la línea que apunta VC_ANTES, tal cual salen del texto,
    # contra un proceso que se llama VeraCrypt.exe: una copia de ping.exe, que no
    # necesita consola ni nada al lado.
    apuntar = next((ln for ln in expulsar.splitlines() if 'set "VC_ANTES=1"' in ln),
                   "rem falta la linea que apunta VC_ANTES")
    pendiente = prueba / "pendiente.bat"

    def pendiente_da(al_empezar=True):
        """VC_ANTES y el código de `:vc_pendiente`, como «VC_ANTES-código».
        `al_empezar=False`: sin mirar antes, como si VeraCrypt no estuviera."""
        pendiente.write_text("@echo off\r\n" + (apuntar if al_empezar else "rem")
                             + "\r\ncall :vc_pendiente\r\n"
                             "echo %VC_ANTES%-%ERRORLEVEL%\r\nexit /b 0\r\n"
                             + "\r\n".join(["", ":vc_pendiente",
                                            *bloque(expulsar, "vc_pendiente")])
                             + "\r\n", encoding="utf-8")
        try:
            r = subprocess.run(["cmd", "/c", str(pendiente)], capture_output=True,
                               text=True, timeout=30)
        except subprocess.TimeoutExpired:
            return "no ha terminado en 30 s"
        return (r.stdout + r.stderr).strip()

    def vivos():
        r = subprocess.run(["tasklist", "/fi", "imagename eq VeraCrypt.exe", "/nh"],
                           capture_output=True, text=True, timeout=30)
        return "veracrypt.exe" in r.stdout.lower()

    if not vivos():         # con un VeraCrypt de verdad abierto, esto no se puede mirar
        c("sin VeraCrypt vivo: nada que esperar", pendiente_da(), "-1")
        falso = prueba / "VeraCrypt.exe"
        shutil.copy2(Path(os.environ.get("SystemRoot", r"C:\Windows"))
                     / "System32" / "PING.EXE", falso)
        proc = subprocess.Popen([str(falso), "-n", "30", "127.0.0.1"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(50):
                if vivos():
                    break
                time.sleep(0.1)
            c("con uno vivo que no estaba al empezar: esperar",
              pendiente_da(al_empezar=False), "-0")
            # Mirando al empezar, ya está vivo: es el caso de un VeraCrypt en
            # segundo plano de antes.
            c("con uno vivo desde antes, se apunta y se cuenta como siempre",
              pendiente_da(), "1-1")
        finally:
            proc.kill()
            proc.wait()

# --- 3. escribirlo -------------------------------------------------------------
fisica = tmpdir("prdrive-fisica-")
(fisica / CONTAINER_NAME).write_bytes(b"x")
escritos = vestibulo.escribir(fisica, ID)
c("deja los seis ficheros", sorted(p.name for p in escritos), sorted(v.TODOS))
c("los .bat con CRLF", all(b"\r\n" in (fisica / n).read_bytes()
                          and b"\n\n" not in (fisica / n).read_bytes().replace(b"\r\n", b"")
                          for n in (v.ABRIR_BAT, v.EXPULSAR_BAT)), True)
c("y sin BOM, que rompería el @echo off",
  (fisica / v.ABRIR_BAT).read_bytes()[:3] != b"\xef\xbb\xbf", True)
c("los .sh con LF", b"\r" in (fisica / v.ABRIR_SH).read_bytes(), False)
c("la guía con BOM, para el Bloc de notas antiguo",
  (fisica / v.LEEME).read_bytes()[:3], b"\xef\xbb\xbf")
c("la marca se lee con el mismo id", v.leer_id(fisica), ID)
# Escribir encima es como se pone al día («Añadir plataformas…»), y en Windows la
# marca ya está oculta: abrirla para escribir con CREATE_ALWAYS da «acceso
# denegado» si no se le pasan los mismos atributos, y `open(…, "w")` no los pasa.
try:
    vestibulo.escribir(fisica, ID)
    fallo = None
except vestibulo.InstallError as e:
    fallo = str(e)
c("se puede volver a escribir encima, con la marca ya oculta", fallo, None)
c("y la marca sigue con el mismo id", v.leer_id(fisica), ID)
if IS_WIN:
    import ctypes
    atributos = ctypes.windll.kernel32.GetFileAttributesW(str(fisica / v.MARCA))
    c("y sigue oculta", bool(atributos & 0x2), True)
c.contains("y dice qué contenedor", (fisica / v.MARCA).read_text(encoding="utf-8"),
           f"contenedor={CONTAINER_NAME}")
c("sin marca no hay id", v.leer_id(tmpdir()), None)
if not IS_WIN:
    c("los .sh se pueden ejecutar",
      os.access(fisica / v.ABRIR_SH, os.X_OK), True)
try:
    vestibulo.escribir(tmpdir(), "")
    fallo = "no ha protestado"
except vestibulo.InstallError:
    fallo = "InstallError"
c("sin id no se escribe una entrada que nadie reconocería", fallo, "InstallError")

estado, _ = device.install_target(fisica)
c("una raíz con contenedor y vestíbulo no se lee como ajena", estado, device.VACIO)

# --- 4. lo que se dice en la verificación ---------------------------------------
fila = vestibulo.comprobar(fisica, ID)
c("completo, en verde", [(k.etiqueta, k.ok) for k in fila],
  [("Entrada del dispositivo", True)])
c("otro id, en rojo", vestibulo.comprobar(fisica, "otro")[0].ok, False)
(fisica / v.EXPULSAR_SH).unlink()
c.contains("si falta un lanzador, lo nombra", vestibulo.comprobar(fisica, ID)[0].detalle,
           v.EXPULSAR_SH)
c("sin marca, en rojo", vestibulo.comprobar(tmpdir(), ID)[0].ok, False)
vestibulo.escribir(fisica, ID)

# --- 5. dónde va: solo con el dispositivo dentro de un contenedor ---------------
montado = tmpdir("prdrive-montado-")
estado = SimpleNamespace(device=fisica, device_root=montado)
c("con contenedor y montado en otro sitio, en la raíz física",
  vestibulo.destino(estado), fisica)
c("sin cifrar (el destino es el propio volumen), no hay vestíbulo",
  vestibulo.destino(SimpleNamespace(device=fisica, device_root=fisica)), None)
c("sin .hc al lado, tampoco",
  vestibulo.destino(SimpleNamespace(device=tmpdir(), device_root=montado)), None)
c("sin destino todavía, tampoco",
  vestibulo.destino(SimpleNamespace(device=fisica, device_root=None)), None)

# --- 6. los .sh, ejecutados ------------------------------------------------------
#
# Contra un equipo de mentira: `veracrypt`, `udisksctl`, `cryptsetup`, `losetup`,
# `mount`, `umount`, `sudo` y `pkexec` falsos que apuntan con qué se les llama y
# cambian un /sys, un /proc/mounts y un /run/media de juguete bajo
# PRDRIVE_SISTEMA, como cambiaría el de verdad. El PATH lleva solo esos falsos y
# unas pocas herramientas de verdad, para que nada del equipo real se cuele (ni un
# sudo ni un cryptsetup de verdad). La raíz del sistema lleva un espacio: el
# montaje de udisks2 también, y /proc/mounts lo escapa como \040.
#
# «La contraseña» es una línea que se escribe en la terminal (un pty) antes de
# lanzar el script: los falsos la leen de ahí, como udisksctl y cryptsetup, y el
# test comprueba que no aparece en ningún argumento de ninguna orden.
sh = shutil.which("sh")
if IS_WIN or not sh:
    print("  (saltado) sin sh: los .sh solo se leen")
    for nombre in (v.ABRIR_SH, v.EXPULSAR_SH):
        c(f"{nombre} empieza por su intérprete",
          (fisica / nombre).read_text(encoding="utf-8").startswith("#!/bin/sh"), True)
else:
    import pty
    import re

    # sh, y además dash y bash en modo POSIX si están y no son el mismo sh.
    real = Path(os.path.realpath(sh)).name
    conchas = [("sh" if real == "sh" else f"sh={real}", [sh])]
    vistos = {os.path.realpath(sh)}
    for nombre, args in (("dash", []), ("bash", ["--posix"])):
        ruta = shutil.which(nombre)
        if ruta and os.path.realpath(ruta) not in vistos:
            vistos.add(os.path.realpath(ruta))
            conchas.append((nombre, [ruta, *args]))

    for concha, orden in conchas:
        for nombre in (v.ABRIR_SH, v.EXPULSAR_SH):
            res = subprocess.run([*orden, "-n", str(fisica / nombre)], capture_output=True)
            c(f"{nombre}: {concha} lo da por bueno", (res.returncode, res.stderr), (0, b""))

    for nombre, texto in (("abrir", vestibulo.sh_abrir(ID)), ("expulsar", vestibulo.sh_expulsar())):
        c(f"{nombre}.sh: nada se le pasa por tubería a cryptsetup ni a udisksctl",
          re.search(r"\|\s*(sudo\s+|pkexec\s+)?(cryptsetup|udisksctl)", texto), None)
        c(f"{nombre}.sh: ni un fichero de clave",
          any(x in texto for x in ("--key-file", "--keyfile", "key-file")), False)

    CLAVE = "clave-de-mentira-7Q"
    HC = str(fisica / CONTAINER_NAME)
    MAPEO = vestibulo.mapeo(ID)
    trabajo = tmpdir("prdrive-sh-")
    registro = trabajo / "registro.txt"
    prefijo = trabajo / "vc"
    sistema = tmpdir("prdrive sistema-")
    PUNTO_CS = f"{sistema}{vestibulo.PUNTO_CRYPTSETUP}/{MAPEO}"
    MONTAJE_UDISKS = sistema / "run" / "media" / "prueba" / "MI PRDRIVE"

    # Las herramientas de verdad que hacen falta, y nada más.
    herramientas = trabajo / "herramientas"
    herramientas.mkdir()
    for nombre in ("sh", "dash", "bash", "sed", "cat", "grep", "mkdir", "rm", "rmdir",
                   "mv", "dirname", "id"):
        ruta = shutil.which(nombre)
        if ruta:
            (herramientas / nombre).symlink_to(ruta)

    # Los falsos, cada uno en su carpeta: así cada caso elige qué hay en el equipo.
    falsos = trabajo / "falsos"
    lib = falsos / "lib.sh"
    falsos.mkdir()
    lib.write_text(r'''S="$PRDRIVE_SISTEMA"
anotar() { [ -n "$FALSO_COMO" ] || echo "$*" >> "$REGISTRO"; }
leer_clave() {
    clave=""
    if [ -t 0 ]; then
        read -r clave
        echo "$1 leyó la contraseña de la terminal" >> "$REGISTRO"
    fi
    [ "$clave" = "$FALSO_CLAVE" ]
}
montar() {
    mkdir -p "$2/.prdrive"
    printf '# control\r\nid=%s\r\n' "$FALSO_ID" > "$2/.prdrive/PRDRIVE"
    printf '#!/bin/sh\necho "runsync $*" >> "%s"\n' "$REGISTRO" > "$2/runsync.sh"
    printf '%s %s exfat rw 0 0\n' "$1" "$(printf '%s' "$2" | sed 's/ /\\040/g')" >> "$S/proc/mounts"
}
desmontar() {
    quitado=""
    : > "$S/proc/mounts.nuevo"
    while read -r d p r; do
        p2="$(printf '%b' "$p")"
        if [ "$d" = "$1" ] || [ "$p2" = "$1" ]; then
            quitado="$p2"
        else
            printf '%s %s %s\n' "$d" "$p" "$r" >> "$S/proc/mounts.nuevo"
        fi
    done < "$S/proc/mounts"
    mv "$S/proc/mounts.nuevo" "$S/proc/mounts"
    [ -n "$quitado" ] || return 1
    rm -rf "$quitado/.prdrive" "$quitado/runsync.sh"
    echo "$quitado"
}
poner_loop() { echo "/dev/$1" > "$S/estado/loop"; mkdir -p "$S/sys/block/$1/holders"; }
poner_dm() {
    mkdir -p "$S/sys/block/$2/dm"
    : > "$S/sys/block/$1/holders/$2"
    echo "$3" > "$S/sys/block/$2/dm/name"
}
quitar_dm() { rm -rf "$S/sys/block/$2" "$S/sys/block/$1/holders/$2"; }
quitar_loop() { rm -rf "$S/sys/block/$1" "$S/estado/loop"; }
''', encoding="utf-8")

    def falso(nombre, cuerpo, carpeta=None):
        d = falsos / (carpeta or nombre)
        d.mkdir(exist_ok=True)
        f = d / nombre
        f.write_text(f'#!/bin/sh\n. "{lib}"\n' + cuerpo, encoding="utf-8")
        f.chmod(0o755)

    # VeraCrypt «monta» creando `<prefijo>1/` con el fichero de control, con CRLF
    # como lo escribe un dispositivo aprovisionado en Windows.
    falso("veracrypt", f'''echo "veracrypt $*" >> "$REGISTRO"
if [ "$1" = "-d" ] || [ "$2" = "-d" ]; then exit 0; fi
m="{prefijo}1"
mkdir -p "$m/.prdrive"
printf "# control\\r\\nid=%s\\r\\n" "$FALSO_ID" > "$m/.prdrive/PRDRIVE"
printf '#!/bin/sh\\necho "runsync $*" >> "%s"\\n' "$REGISTRO" > "$m/runsync.sh"
''')
    falso("udisksctl", '''if [ "$1" = info ]; then
    [ -z "$FALSO_UDISKS_RECONOCE" ] || echo "  org.freedesktop.UDisks2.Encrypted:"
    exit 0
fi
anotar "udisksctl $*"
case "$1" in
    loop-setup) poner_loop loop7; echo "Mapped file $3 as /dev/loop7." ;;
    unlock)
        if ! leer_clave udisksctl; then
            echo "Error unlocking /dev/loop7: wrong passphrase" >&2
            exit 1
        fi
        poner_dm loop7 dm-3 tcrypt-1792
        echo "Unlocked /dev/loop7 as /dev/dm-3." ;;
    mount) montar /dev/dm-3 "$S/run/media/$USER/MI PRDRIVE" ;;
    unmount)
        if [ -n "$FALSO_OCUPADO" ]; then echo "target is busy" >&2; exit 1; fi
        rmdir "$(desmontar /dev/dm-3)" ;;
    lock) quitar_dm loop7 dm-3 ;;
    loop-delete) quitar_loop loop7 ;;
esac
''')
    falso("cryptsetup", '''anotar "cryptsetup $*"
case "$1" in
    open)
        for a; do nombre="$a"; done
        if ! leer_clave cryptsetup; then
            echo "No device header detected with this passphrase." >&2
            exit 2
        fi
        poner_loop loop8
        poner_dm loop8 dm-4 "$nombre" ;;
    close) quitar_dm loop8 dm-4; quitar_loop loop8 ;;
esac
''')
    falso("pkexec", '''echo "pkexec $*" >> "$REGISTRO"
FALSO_COMO=pkexec; export FALSO_COMO
exec "$@"
''')
    # Lo que todo equipo tiene. `sleep` no espera: el tiempo no se prueba aquí.
    falso("losetup", '''[ "$1" = "-j" ] || exit 1
[ -f "$S/estado/loop" ] || exit 0
printf '%s: [0042]:17 (%s)\\n' "$(cat "$S/estado/loop")" "$2"
''', "comunes")
    falso("sudo", '''echo "sudo $*" >> "$REGISTRO"
FALSO_COMO=sudo; export FALSO_COMO
exec "$@"
''', "comunes")
    falso("mount", '''anotar "mount $*"
if [ "$1" = "-o" ]; then
    case "$2" in *uid=*) if [ -n "$FALSO_SIN_UID" ]; then exit 32; fi ;; esac
    shift 2
fi
montar "$1" "$2"
''', "comunes")
    falso("umount", '''anotar "umount $*"
if [ -n "$FALSO_OCUPADO" ]; then echo "target is busy" >&2; exit 32; fi
desmontar "$1" >/dev/null
''', "comunes")
    falso("sleep", "exit 0\n", "comunes")

    def limpiar(tcrypt=False):
        """Un equipo recién arrancado: nada abierto, nada montado."""
        shutil.rmtree(sistema)
        for sub in ("etc/udisks2", "sys/block", "proc", "estado", "run/media/prueba",
                    "media/prueba", "mnt"):
            (sistema / sub).mkdir(parents=True)
        (sistema / "proc" / "mounts").write_text("", encoding="utf-8")
        if tcrypt:
            (sistema / "etc" / "udisks2" / "tcrypt.conf").write_text("", encoding="utf-8")
        shutil.rmtree(f"{prefijo}1", ignore_errors=True)
        registro.unlink(missing_ok=True)

    def estado():
        """(loop, montajes) del equipo de mentira."""
        loop = sistema / "estado" / "loop"
        return (loop.read_text(encoding="utf-8").strip() if loop.exists() else None,
                (sistema / "proc" / "mounts").read_text(encoding="utf-8").splitlines())

    todo: list[str] = []            # todo lo que se ha llamado, para la contraseña

    def leer():
        texto = registro.read_text(encoding="utf-8") if registro.exists() else ""
        registro.unlink(missing_ok=True)
        todo.extend(texto.splitlines())
        return texto.splitlines()

    def lanzar(script, con=("veracrypt",), terminal=True, display=True,
               falso_id=ID, clave=CLAVE, concha=(sh,), **extra):
        entorno = {"PATH": ":".join([*(str(falsos / n) for n in con),
                                     str(falsos / "comunes"), str(herramientas)]),
                   "HOME": str(trabajo), "USER": "prueba", "REGISTRO": str(registro),
                   vestibulo.VAR_SISTEMA: str(sistema), "FALSO_ID": falso_id,
                   "FALSO_CLAVE": CLAVE, "VERACRYPT_MOUNT_PREFIX": str(prefijo),
                   **{k: v_ for k, v_ in extra.items() if v_}}
        if display:
            entorno["DISPLAY"] = ":99"
        maestro = esclavo = None
        if terminal:
            maestro, esclavo = pty.openpty()
            os.write(maestro, (clave + "\n").encode())
        try:
            return subprocess.run([*concha, str(fisica / script)], env=entorno,
                                  stdin=esclavo if terminal else subprocess.DEVNULL,
                                  capture_output=True, text=True, timeout=30)
        finally:
            for fd in (maestro, esclavo):
                if fd is not None:
                    os.close(fd)

    uid_gid = f"uid={os.getuid()},gid={os.getgid()}"
    TODAS = ("udisksctl", "cryptsetup", "pkexec")

    for concha, orden in conchas:
        def correr(script, **kw):
            return lanzar(script, concha=orden, **kw)

        def caso(titulo):
            return f"[{concha}] {titulo}"

        # -- VeraCrypt instalado: como hasta ahora ------------------------------
        limpiar()
        res = correr(v.ABRIR_SH)
        c(caso("abrir: sale bien"), (res.returncode, res.stderr), (0, ""))
        c(caso("abrir: le pide a VeraCrypt ESTE contenedor, en su ventana, y lanza prdrive"),
          leer(), [f"veracrypt {HC}", "runsync "])
        correr(v.ABRIR_SH)
        c(caso("ya abierto: no se vuelve a montar, solo se lanza prdrive"), leer(), ["runsync "])

        limpiar()
        correr(v.ABRIR_SH, display=False)
        c(caso("sin escritorio, VeraCrypt por la terminal"),
          leer(), [f"veracrypt --text {HC}", "runsync "])

        limpiar()
        res = correr(v.ABRIR_SH, falso_id="otro-dispositivo")
        c(caso("montado otro dispositivo: no lo confunde con este"), res.returncode, 1)
        c.contains(caso("y lo dice"), res.stderr, "no se ha abierto")
        leer()

        limpiar(tcrypt=True)
        correr(v.ABRIR_SH, con=("veracrypt", *TODAS), FALSO_UDISKS_RECONOCE="1")
        c(caso("con VeraCrypt y además udisks2 y cryptsetup, VeraCrypt (U10)"),
          (leer(), estado()), ([f"veracrypt {HC}", "runsync "], (None, [])))

        # -- udisks2 -------------------------------------------------------------
        limpiar(tcrypt=True)
        res = correr(v.ABRIR_SH, con=TODAS, FALSO_UDISKS_RECONOCE="1")
        c(caso("udisks2: sale bien"), (res.returncode, res.stderr), (0, ""))
        c(caso("udisks2: loop, la contraseña la lee udisksctl de la terminal, monta y lanza"),
          leer(), [f"udisksctl loop-setup -f {HC}", "udisksctl unlock -b /dev/loop7",
                   "udisksctl leyó la contraseña de la terminal",
                   "udisksctl mount -b /dev/dm-3", "runsync "])
        correr(v.ABRIR_SH, con=TODAS, FALSO_UDISKS_RECONOCE="1")
        c(caso("udisks2 ya abierto: lo encuentra en /run/media/$USER, solo se lanza prdrive"),
          leer(), ["runsync "])

        res = correr(v.EXPULSAR_SH, con=TODAS, FALSO_OCUPADO="1")
        c(caso("expulsar udisks2 con algo abierto dentro: no sigue, y lo dice"),
          (res.returncode, leer(), estado()[0]),
          (1, ["udisksctl unmount -b /dev/dm-3"], "/dev/loop7"))
        c.contains(caso("«no quites la unidad»"), res.stderr, "No quites la unidad")

        res = correr(v.EXPULSAR_SH, con=TODAS, terminal=False)
        c(caso("expulsar udisks2: desmonta, cierra y suelta el loop, sin terminal ni sudo"),
          (res.returncode, leer()),
          (0, ["udisksctl unmount -b /dev/dm-3", "udisksctl lock -b /dev/loop7",
               "udisksctl loop-delete -b /dev/loop7"]))
        c(caso("y no queda nada"), (estado(), MONTAJE_UDISKS.exists()), ((None, []), False))
        c.contains(caso("y dice que ya se puede quitar"), res.stdout, "Ya puedes quitar")

        limpiar(tcrypt=True)
        res = correr(v.ABRIR_SH, con=TODAS, FALSO_UDISKS_RECONOCE="1", clave="otra")
        c(caso("udisks2 con otra contraseña: suelta el loop y NO prueba cryptsetup"),
          (res.returncode, leer(), estado()),
          (1, [f"udisksctl loop-setup -f {HC}", "udisksctl unlock -b /dev/loop7",
               "udisksctl leyó la contraseña de la terminal",
               "udisksctl loop-delete -b /dev/loop7"], (None, [])))

        # Con tcrypt.conf pero udisks2 sin reiniciar: el loop no sale cifrado.
        limpiar(tcrypt=True)
        res = correr(v.ABRIR_SH, con=TODAS)
        c(caso("udisks2 no lo reconoce: suelta el loop y pasa a cryptsetup"),
          leer()[:3], [f"udisksctl loop-setup -f {HC}",
                       "udisksctl loop-delete -b /dev/loop7", f"sudo mkdir -p {PUNTO_CS}"])
        c.contains(caso("diciendo que reinicie udisks2"), res.stderr,
                   "sudo systemctl restart udisks2")
        correr(v.EXPULSAR_SH, con=TODAS)
        leer()

        # -- cryptsetup ------------------------------------------------------------
        limpiar()                                  # sin tcrypt.conf: udisks2 no vale
        res = correr(v.ABRIR_SH, con=TODAS)
        c(caso("cryptsetup: sale bien"), (res.returncode, res.stderr), (0, ""))
        c(caso("cryptsetup: sudo, la contraseña la lee cryptsetup de la terminal, "
               "monta con el uid de quien lo abre en /mnt/prdrive-<id> y lanza"),
          leer(), [f"sudo mkdir -p {PUNTO_CS}",
                   f"sudo cryptsetup open --type tcrypt --veracrypt {HC} {MAPEO}",
                   "cryptsetup leyó la contraseña de la terminal",
                   f"sudo mount -o {uid_gid} /dev/mapper/{MAPEO} {PUNTO_CS}", "runsync "])
        c.contains(caso("y cómo no necesitar sudo la próxima vez"), res.stdout,
                   vestibulo.ACTIVAR_UDISKS)

        res = correr(v.EXPULSAR_SH, con=("udisksctl", "cryptsetup"), terminal=False)
        c(caso("expulsar cryptsetup sin terminal ni pkexec: lo dice y no toca nada"),
          (res.returncode, leer(), estado()[0]), (1, [], "/dev/loop8"))
        c.contains(caso("y cómo hacerlo"), res.stderr, v.EXPULSAR_SH)

        res = correr(v.EXPULSAR_SH, con=TODAS)
        registrado = leer()
        c(caso("expulsar cryptsetup en una terminal: una sola orden con sudo"),
          (res.returncode, len(registrado), registrado[0].startswith("sudo sh -c "),
           registrado[0].endswith(f" sh {PUNTO_CS} {MAPEO}")), (0, 1, True, True))
        c(caso("que desmonta y cierra: no queda nada"), estado(), (None, []))

        limpiar()
        correr(v.ABRIR_SH, con=TODAS)
        leer()
        res = correr(v.EXPULSAR_SH, con=TODAS, terminal=False)
        registrado = leer()
        c(caso("sin terminal (el botón «Expulsar»), pkexec: una sola ventana"),
          (res.returncode, [r.split(" ", 1)[0] for r in registrado], estado()),
          (0, ["pkexec"], (None, [])))

        limpiar()
        res = correr(v.ABRIR_SH, con=TODAS, FALSO_SIN_UID="1")
        c(caso("un contenedor ext4 no admite uid/gid: se monta sin ellos"),
          (res.returncode, leer()[-2:]),
          (0, [f"sudo mount /dev/mapper/{MAPEO} {PUNTO_CS}", "runsync "]))

        limpiar()
        res = correr(v.ABRIR_SH, con=TODAS, clave="otra")
        c(caso("cryptsetup con otra contraseña: no monta nada"),
          (res.returncode, leer(), estado()),
          (1, [f"sudo mkdir -p {PUNTO_CS}",
               f"sudo cryptsetup open --type tcrypt --veracrypt {HC} {MAPEO}",
               "cryptsetup leyó la contraseña de la terminal"], (None, [])))

        # -- sin terminal, sin nada ------------------------------------------------
        limpiar(tcrypt=True)
        res = correr(v.ABRIR_SH, con=TODAS, terminal=False, FALSO_UDISKS_RECONOCE="1")
        c(caso("sin VeraCrypt ni terminal: no se abre nada"), (res.returncode, leer()), (1, []))
        c.contains(caso("y dice con qué vía y dónde"), res.stderr, "udisks2")
        c.contains(caso("abriendo una terminal"), res.stderr, f"/{v.ABRIR_SH}\"")

        limpiar()
        res = correr(v.ABRIR_SH, con=())
        c(caso("sin ninguna vía: no se abre nada"), (res.returncode, leer()), (1, []))
        for trozo in (vestibulo.URL_VERACRYPT, vestibulo.ACTIVAR_UDISKS, "cryptsetup"):
            c.contains(caso(f"y explica las tres salidas: {trozo}"), res.stderr, trozo)

        # -- expulsar, deducido del estado ------------------------------------------
        limpiar()
        res = correr(v.EXPULSAR_SH, con=("veracrypt",))
        c(caso("expulsar con VeraCrypt y sin loop: -d de ESTE contenedor, como siempre"),
          leer(), [f"veracrypt -d {HC}"])

        limpiar()
        (sistema / "estado" / "loop").write_text("/dev/loop9\n", encoding="utf-8")
        (sistema / "sys" / "block" / "loop9" / "holders").mkdir(parents=True)
        (sistema / "sys" / "block" / "loop9" / "holders" / "dm-5").write_text("")
        (sistema / "sys" / "block" / "dm-5" / "dm").mkdir(parents=True)
        (sistema / "sys" / "block" / "dm-5" / "dm" / "name").write_text("veracrypt1\n")
        correr(v.EXPULSAR_SH, con=("veracrypt", *TODAS))
        c(caso("un dm veracryptN lo abrió VeraCrypt: se cierra con él"),
          leer(), [f"veracrypt -d {HC}"])

        limpiar()
        (sistema / "estado" / "loop").write_text("/dev/loop7\n", encoding="utf-8")
        (sistema / "sys" / "block" / "loop7" / "holders").mkdir(parents=True)
        res = correr(v.EXPULSAR_SH, con=TODAS)
        c(caso("un loop sin abrir (se cortó entre loop-setup y unlock): se suelta"),
          (res.returncode, leer(), estado()),
          (0, ["udisksctl loop-delete -b /dev/loop7"], (None, [])))

        limpiar()
        res = correr(v.EXPULSAR_SH, con=TODAS)
        c(caso("nada abierto y sin VeraCrypt: ya estaba cerrado"),
          (res.returncode, leer()), (0, []))
        c.contains(caso("y lo dice"), res.stdout, "ya estaba cerrado")

    c("la contraseña no aparece nunca en los argumentos de nada",
      [ln for ln in todo if CLAVE in ln], [])
    c("ni hay ficheros de clave ni contraseñas en la línea de órdenes",
      [ln for ln in todo if any(x in ln for x in ("--key-file", "--keyfile",
                                                  "--password", "--passphrase"))], [])
    c("y udisksctl y cryptsetup la han leído de la terminal, que es donde la piden",
      {ln for ln in todo if "leyó la contraseña" in ln},
      {"udisksctl leyó la contraseña de la terminal",
       "cryptsetup leyó la contraseña de la terminal"})

raise SystemExit(c.report())
