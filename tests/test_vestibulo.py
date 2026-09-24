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
  * Los `.sh` sí se ejecutan, con un `veracrypt` de mentira que «monta» creando
    una carpeta: abrir, reconocer lo ya abierto, no confundirse de dispositivo y
    cerrar. Nada toca una unidad de verdad.
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
# Un `veracrypt` de mentira que apunta con qué se le llama y, al «montar», crea
# `<prefijo>1/` con el fichero de control y un runsync.sh que también apunta. El
# prefijo es el de `VERACRYPT_MOUNT_PREFIX`, que el propio VeraCrypt respeta.
sh = shutil.which("sh")
if IS_WIN or not sh:
    print("  (saltado) sin sh: los .sh solo se leen")
    for nombre in (v.ABRIR_SH, v.EXPULSAR_SH):
        c(f"{nombre} empieza por su intérprete",
          (fisica / nombre).read_text(encoding="utf-8").startswith("#!/bin/sh"), True)
else:
    for nombre in (v.ABRIR_SH, v.EXPULSAR_SH):
        res = subprocess.run([sh, "-n", str(fisica / nombre)], capture_output=True)
        c(f"{nombre}: sh lo da por bueno", (res.returncode, res.stderr), (0, b""))

    trabajo = tmpdir("prdrive-sh-")
    registro = trabajo / "registro.txt"
    prefijo = trabajo / "vc"
    binarios = trabajo / "bin"
    binarios.mkdir()
    falso = binarios / "veracrypt"
    falso.write_text(
        "#!/bin/sh\n"
        f'echo "veracrypt $*" >> "{registro}"\n'
        'if [ "$1" = "-d" ] || [ "$2" = "-d" ]; then exit 0; fi\n'
        f'm="{prefijo}1"\n'
        'mkdir -p "$m/.prdrive"\n'
        # CRLF a propósito: un dispositivo aprovisionado en Windows lo escribe así.
        'printf "# control\\r\\nid=%s\\r\\n" "$FALSO_ID" > "$m/.prdrive/PRDRIVE"\n'
        f'printf \'#!/bin/sh\\necho "runsync $*" >> "{registro}"\\n\' > "$m/runsync.sh"\n',
        encoding="utf-8")
    falso.chmod(0o755)

    def lanzar(script, falso_id=ID, display=True, *args):
        entorno = {"PATH": f"{binarios}:/usr/bin:/bin", "FALSO_ID": falso_id,
                   "VERACRYPT_MOUNT_PREFIX": str(prefijo), "HOME": str(trabajo)}
        if display:
            entorno["DISPLAY"] = ":99"
        return subprocess.run([sh, str(fisica / script), *args], env=entorno,
                              capture_output=True, text=True, timeout=30)

    def leer():
        texto = registro.read_text(encoding="utf-8") if registro.exists() else ""
        registro.unlink(missing_ok=True)
        return texto.splitlines()

    res = lanzar(v.ABRIR_SH)
    c("abrir: sale bien", (res.returncode, res.stderr), (0, ""))
    c("abrir: le pide a VeraCrypt ESTE contenedor, en su ventana, y lanza prdrive",
      leer(), [f"veracrypt {fisica / CONTAINER_NAME}", "runsync "])

    res = lanzar(v.ABRIR_SH)
    c("ya abierto: no se vuelve a montar, solo se lanza prdrive",
      leer(), ["runsync "])

    shutil.rmtree(f"{prefijo}1")
    res = lanzar(v.ABRIR_SH, ID, False)
    c("sin escritorio, VeraCrypt por la terminal",
      leer(), [f"veracrypt --text {fisica / CONTAINER_NAME}", "runsync "])

    shutil.rmtree(f"{prefijo}1")
    res = lanzar(v.ABRIR_SH, "otro-dispositivo")
    c("montado otro dispositivo: no lo confunde con este", res.returncode, 1)
    c.contains("y lo dice", res.stderr, "no se ha abierto")
    leer()

    sin_vc = subprocess.run([sh, str(fisica / v.ABRIR_SH)],
                            env={"PATH": "/nonexistent", "HOME": str(trabajo)},
                            capture_output=True, text=True, timeout=30)
    c("sin VeraCrypt instalado lo dice, en vez de fallar sin más",
      (sin_vc.returncode, "no encuentro VeraCrypt" in sin_vc.stderr), (1, True))

    res = lanzar(v.EXPULSAR_SH)
    c("expulsar: -d de ESTE contenedor", leer(),
      [f"veracrypt -d {fisica / CONTAINER_NAME}"])

raise SystemExit(c.report())
